#pragma once
// Checkpoint/restart support for the configuration-driven solver (V2.1.0).
// Design contract: docs/validation/../../plans (project root) r2 plan sections 4-8;
// acceptance thresholds: docs/validation/checkpoint-tolerance-thresholds.md.
#include "config.hpp"
#include "lbm.hpp"
#include "version.hpp"
#include <algorithm>
#include <cstring>
#include <fstream>
#include <iostream>
#include <cstdio>
#include <cstdlib>
#include <ctime>
#include <functional>
#include <map>
#include <set>
#include <string>
#include <vector>
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <io.h>
#include <windows.h>
#else
#include <fcntl.h>
#include <unistd.h>
#endif

namespace fxconfig {

// Bumped whenever the on-disk checkpoint layout or its semantics change.
constexpr int checkpoint_format_version_value = 1;

// Dedicated nonzero exit codes (1 remains the generic error code of entry()).
constexpr int checkpoint_exit_no_usable = 3;   // every candidate failed integrity validation
constexpr int checkpoint_exit_save_failed = 4; // a checkpoint save/commit failed; the run aborts, previous checkpoints stay usable
constexpr int checkpoint_exit_rejected = 5;    // identity/compatibility/config-whitelist rejection; no output is modified

struct checkpoint_error : std::runtime_error {
    int code;
    checkpoint_error(int exit_code, const std::string &message) : std::runtime_error(message), code(exit_code) {}
};

inline std::string utc_stamp() {
    const auto now = std::time(nullptr);
    std::tm tm{};
#ifdef _WIN32
    gmtime_s(&tm, &now);
#else
    gmtime_r(&now, &tm);
#endif
    char text[32];
    std::strftime(text, sizeof(text), "%Y%m%dT%H%M%SZ", &tm);
    return text;
}

// ---------------------------------------------------------------------------
// Test-only fault injection (r2 plan section 5.2/5.3). Default off; any value
// other than the documented stage names disables injection entirely.
// ---------------------------------------------------------------------------
inline const std::string &checkpoint_fault_stage() {
    static const std::string value = [] {
#ifdef _WIN32
        char *buffer = nullptr;
        size_t length = 0;
        if (_dupenv_s(&buffer, &length, "SOLVER_IBM_CHECKPOINT_FAULT") == 0 && buffer != nullptr) {
            const std::string result(buffer);
            std::free(buffer);
            return result;
        }
        return std::string();
#else
        const char *environment = std::getenv("SOLVER_IBM_CHECKPOINT_FAULT");
        return environment ? std::string(environment) : std::string();
#endif
    }();
    return value;
}
inline bool checkpoint_fault(const char *stage) { return checkpoint_fault_stage() == stage; }

// ---------------------------------------------------------------------------
// Low-level persistent I/O helpers
// ---------------------------------------------------------------------------
inline std::FILE *fopen_binary(const fs::path &path, const wchar_t *mode_w, const char *mode) {
#ifdef _WIN32
    (void)mode;
    std::FILE *file = nullptr;
    if (_wfopen_s(&file, path.c_str(), mode_w) != 0)
        return nullptr;
    return file;
#else
    (void)mode_w;
    return std::fopen(path.string().c_str(), mode);
#endif
}

inline void persist_and_close(std::FILE *file, const fs::path &path) {
    require(std::fflush(file) == 0, "Flush failed: " + path.u8string());
#ifdef _WIN32
    const HANDLE handle = reinterpret_cast<HANDLE>(_get_osfhandle(_fileno(file)));
    require(handle != INVALID_HANDLE_VALUE && FlushFileBuffers(handle),
            "FlushFileBuffers failed: " + path.u8string());
#else
    require(::fsync(::fileno(file)) == 0, "fsync failed: " + path.u8string());
#endif
    require(std::fclose(file) == 0, "Close failed: " + path.u8string());
}

inline void write_binary_persistent(const fs::path &path, const void *data, size_t bytes) {
    std::FILE *file = fopen_binary(path, L"wb", "wb");
    require(file != nullptr, "Cannot write " + path.u8string());
    require(bytes == 0 || std::fwrite(data, 1, bytes, file) == bytes, "Short write " + path.u8string());
    persist_and_close(file, path);
}

inline void write_json_persistent(const fs::path &path, const Json &value) {
    std::string text = value.dump(2);
    text.push_back('\n');
    write_binary_persistent(path, text.data(), text.size());
}

inline void flush_directory_metadata(const fs::path &directory, std::vector<std::string> &warnings) {
#ifdef _WIN32
    // Windows provides no user-mode directory fsync: FlushFileBuffers on a directory handle fails with
    // ACCESS_DENIED regardless of the access mask. Rename durability is provided by the NTFS metadata log
    // (lazy flush window of a few seconds). Crash consistency therefore rests on load-time validation of
    // every candidate checkpoint (r2 plan section 5.4), not on flush ordering; both "rename lost" and
    // "rename persisted" are safe outcomes. Intentionally a no-op here.
    (void)directory;
    (void)warnings;
#else
    const int descriptor = ::open(directory.string().c_str(), O_RDONLY | O_DIRECTORY);
    if (descriptor >= 0) {
        if (::fsync(descriptor) != 0)
            warnings.push_back("Checkpoint directory metadata flush failed");
        ::close(descriptor);
    } else {
        warnings.push_back("Cannot open checkpoint directory for metadata flush");
    }
#endif
}

inline std::string executable_sha256() {
#ifdef _WIN32
    wchar_t exe[32768];
    const DWORD length = GetModuleFileNameW(nullptr, exe, 32768);
    if (length == 0 || length >= 32768)
        return std::string();
    try {
        return sha256(fs::path(exe));
    } catch (...) {
        return std::string();
    }
#else
    return std::string();
#endif
}

// ---------------------------------------------------------------------------
// Device field plan: exactly the cross-step state fields of r2 plan section 4.1
// ---------------------------------------------------------------------------
struct FieldIo {
    std::string name;
    unsigned long long bytes = 0;
    std::function<void(void *, unsigned long long, unsigned long long)> read;   // device -> external memory
    std::function<void(const void *, unsigned long long, unsigned long long)> write; // external memory -> device
    std::function<void()> sync_host; // refresh the Memory host mirror after a device write (null for device-only fields)
};

template <typename T>
FieldIo make_field_io(const std::string &name, Memory<T> &memory, const unsigned long long elements,
                      const bool host_sync) {
    FieldIo io;
    io.name = name;
    io.bytes = elements * static_cast<unsigned long long>(sizeof(T));
    io.read = [&memory](void *destination, const unsigned long long offset, const unsigned long long length) {
        memory.read_to_external(destination, offset / sizeof(T), length / sizeof(T));
    };
    io.write = [&memory](const void *source, const unsigned long long offset, const unsigned long long length) {
        memory.write_from_external(source, offset / sizeof(T), length / sizeof(T));
    };
    io.sync_host = host_sync ? [&memory]() { memory.read_from_device(); } : std::function<void()>();
    return io;
}

inline std::vector<FieldIo> checkpoint_fields(LBM &lbm, const Config &c) {
    auto *domain = lbm.lbm_domain[0];
    const unsigned long long N = lbm.get_N();
    std::vector<FieldIo> fields;
    fields.push_back(make_field_io<uchar>("fi", domain->get_fi(), domain->get_distribution_capacity(), false));
    fields.push_back(make_field_io<float>("rho", domain->rho, N, true));
    fields.push_back(make_field_io<float>("u", domain->u, N * 3, true));
    fields.push_back(make_field_io<uchar>("flags", domain->flags, N, true));
#ifdef SURFACE
    if (c.model.free_surface) {
        fields.push_back(make_field_io<float>("contact_angle", domain->contact_angle, N, true));
        fields.push_back(make_field_io<float>("phi", domain->phi, N, true));
        fields.push_back(make_field_io<float>("mass", domain->get_surface_mass(), N, true));
        fields.push_back(make_field_io<float>("massex", domain->get_surface_massex(), N, false)); // device-only cross-step state
    }
#endif // SURFACE
#ifdef TEMPERATURE
    if (c.model.temperature) {
        fields.push_back(make_field_io<float>("t_field", domain->T, N, true));
        fields.push_back(make_field_io<uchar>("material", domain->material, N, true));
        fields.push_back(make_field_io<float>("thermal_capacity", domain->thermal_capacity, N, true));
        fields.push_back(make_field_io<float>("thermal_conductivity", domain->thermal_conductivity, N, true));
        fields.push_back(make_field_io<float>("thermal_source", domain->thermal_source, N, true));
    }
#endif // TEMPERATURE
    if (c.model.dynamic_geometry)
        fields.push_back(make_field_io<uchar>("object_id", domain->object_id, N, true));
    return fields;
}

// Development diagnostics: when SOLVER_IBM_DEBUG_HASH_AT=<step> is set, print SHA256 hashes of every
// checkpointed device field at the given time step. Used to localize restart divergences; no effect
// when the variable is unset.
inline void debug_state_hash(const char *phase, LBM &lbm, const Config &c) {
    std::string value;
#ifdef _WIN32
    char *buffer = nullptr;
    size_t length = 0;
    if (_dupenv_s(&buffer, &length, "SOLVER_IBM_DEBUG_HASH_AT") != 0 || buffer == nullptr)
        return;
    value.assign(buffer);
    std::free(buffer);
#else
    const char *environment = std::getenv("SOLVER_IBM_DEBUG_HASH_AT");
    if (environment == nullptr)
        return;
    value.assign(environment);
#endif
    if (value.empty())
        return;
    const unsigned long long at = std::strtoull(value.c_str(), nullptr, 10);
    if (lbm.get_t() != at)
        return;
    std::string line = std::string("DEBUGHASH t=") + std::to_string(lbm.get_t()) + " phase=" + phase;
    std::vector<char> scratch;
    for (const auto &field : checkpoint_fields(lbm, c)) {
        scratch.resize(static_cast<size_t>(field.bytes));
        field.read(scratch.data(), 0, field.bytes);
        line += " " + field.name + "=" + sha256_bytes(std::string(scratch.data(), scratch.size())).substr(0, 16);
    }
    {
        auto &F = lbm.lbm_domain[0]->F;
        std::vector<char> fscratch(static_cast<size_t>(F.capacity()));
        F.read_to_external(fscratch.data(), 0, fscratch.size());
        line += " F=" + sha256_bytes(std::string(fscratch.data(), fscratch.size())).substr(0, 16);
    }
    std::cout << line << std::endl;
}

inline unsigned long long checkpoint_estimate_bytes(LBM &lbm, const Config &c,
                                                    const std::vector<unsigned long long> &body_target_cells) {
    unsigned long long total = 1048576; // JSON metadata headroom
    for (const auto &field : checkpoint_fields(lbm, c))
        total += field.bytes;
    for (const auto cells : body_target_cells)
        total += cells * 24; // cells(8) + material positions(12) + temperatures(4)
    return total;
}

inline void require_disk_headroom(const fs::path &output, const unsigned long long estimate) {
    std::error_code ec;
    const auto space = fs::space(output, ec);
    require(!ec, "Cannot query free disk space for checkpointing");
    require(space.available >= 2 * estimate + (64ull << 20),
            "Insufficient free disk space for checkpointing: need at least " +
                std::to_string((2 * estimate + (64ull << 20)) >> 20) + " MiB, available " +
                std::to_string(space.available >> 20) + " MiB");
}

// ---------------------------------------------------------------------------
// Host state (r2 plan section 4.2)
// ---------------------------------------------------------------------------
struct OutputFileRecord {
    std::string path; // relative to the run output directory
    unsigned long long bytes = 0;
    unsigned long long last_step = 0;
};

struct BodyThermalState {
    unsigned long long target_cells = 0;
    std::string cells_file, positions_file, temperatures_file;
    std::vector<unsigned long long> cells;
    std::vector<float> positions;    // 3 floats per sample, material frame
    std::vector<float> temperatures; // 1 float per sample
};

struct CheckpointHostState {
    unsigned long long t = 0;
    double initial_mass = 0, initial_energy = 0;
    double cumulative_mass_outward = 0, cumulative_enthalpy_outward = 0;
    double cumulative_source_in = 0, cumulative_boundary_heat_in = 0;
    bool dynamic_mass_enabled = false;
    double dynamic_mass_target = 0;
    bool dynamic_energy_enabled = false;
    double dynamic_energy_target = 0;
    bool open_mass_enabled = false;
    double open_mass_target = 0;
    bool open_energy_enabled = false;
    double open_energy_target = 0;
    double source_per_step = 0;
    bool analysis_enabled = false;
    Json moments; // Analysis::serialize_moments(); null when analysis is disabled
    std::vector<BodyThermalState> bodies;
    std::vector<OutputFileRecord> outputs;
    std::vector<std::pair<std::string, unsigned long long>> vtk_frames; // field name, step stamp
    unsigned long long restart_count = 0;
    bool final_checkpoint = false;
    Json restarts = Json::array();

    static Json encode_target(const bool enabled, const double value) {
        return {{"enabled", enabled}, {"value", enabled ? value : 0.0}};
    }
    Json to_json() const {
        Json bodies_json = Json::array();
        for (size_t i = 0; i < bodies.size(); i++)
            bodies_json.push_back({{"target_cells", bodies[i].target_cells},
                                   {"cells_file", "body-" + std::to_string(i) + "-cells.bin"},
                                   {"positions_file", "body-" + std::to_string(i) + "-positions.bin"},
                                   {"temperatures_file", "body-" + std::to_string(i) + "-temperatures.bin"}});
        Json outputs_json = Json::array();
        for (const auto &record : outputs)
            outputs_json.push_back(
                {{"path", record.path}, {"bytes", record.bytes}, {"last_step", record.last_step}});
        Json frames_json = Json::array();
        for (const auto &frame : vtk_frames)
            frames_json.push_back({{"field", frame.first}, {"stamp", frame.second}});
        return {{"t", t},
                {"budget",
                 {{"initial_mass", initial_mass},
                  {"initial_energy", initial_energy},
                  {"cumulative_mass_outward", cumulative_mass_outward},
                  {"cumulative_enthalpy_outward", cumulative_enthalpy_outward},
                  {"cumulative_source_in", cumulative_source_in},
                  {"cumulative_boundary_heat_in", cumulative_boundary_heat_in}}},
                {"targets",
                 {{"dynamic_mass", encode_target(dynamic_mass_enabled, dynamic_mass_target)},
                  {"dynamic_energy", encode_target(dynamic_energy_enabled, dynamic_energy_target)},
                  {"open_mass", encode_target(open_mass_enabled, open_mass_target)},
                  {"open_energy", encode_target(open_energy_enabled, open_energy_target)}}},
                {"source_per_step", source_per_step},
                {"analysis_enabled", analysis_enabled},
                {"moments", analysis_enabled ? moments : Json(nullptr)},
                {"bodies", bodies_json},
                {"outputs", outputs_json},
                {"vtk_frames", frames_json},
                {"restart_count", restart_count},
                {"final_checkpoint", final_checkpoint},
                {"restarts", restarts}};
    }

    // Validation follows r2 plan section 4.2 / R11: explicit enabled flags, exact
    // array lengths against the current configuration, finiteness, step consistency.
    static CheckpointHostState from_json(const Json &j, const Config &c, const unsigned long long step,
                                         const size_t dynamic_body_count) {
        CheckpointHostState state;
        require(j.is_object(), "host-state.json must be an object");
        require(j.contains("t") && j["t"].is_number_integer() && j["t"].get<unsigned long long>() == step,
                "host-state.json step does not match the checkpoint step");
        state.t = step;
        auto finite = [](const Json &parent, const char *key) {
            require(parent.contains(key) && parent[key].is_number(), std::string("host-state: missing ") + key);
            const double value = parent[key].get<double>();
            require(std::isfinite(value), std::string("host-state: non-finite ") + key);
            return value;
        };
        const auto &budget = j.at("budget");
        state.initial_mass = finite(budget, "initial_mass");
        state.initial_energy = finite(budget, "initial_energy");
        state.cumulative_mass_outward = finite(budget, "cumulative_mass_outward");
        state.cumulative_enthalpy_outward = finite(budget, "cumulative_enthalpy_outward");
        state.cumulative_source_in = finite(budget, "cumulative_source_in");
        state.cumulative_boundary_heat_in = finite(budget, "cumulative_boundary_heat_in");
        auto target = [](const Json &parent, const char *key, bool &enabled, double &value) {
            const auto &entry = parent.at(key);
            require(entry.is_object() && entry.contains("enabled") && entry["enabled"].is_boolean(),
                    std::string("host-state: invalid target encoding ") + key);
            enabled = entry["enabled"].get<bool>();
            require(entry.contains("value") && entry["value"].is_number(),
                    std::string("host-state: invalid target encoding ") + key);
            value = entry["value"].get<double>();
            require(!enabled || std::isfinite(value), std::string("host-state: non-finite target ") + key);
        };
        const auto &targets = j.at("targets");
        target(targets, "dynamic_mass", state.dynamic_mass_enabled, state.dynamic_mass_target);
        target(targets, "dynamic_energy", state.dynamic_energy_enabled, state.dynamic_energy_target);
        target(targets, "open_mass", state.open_mass_enabled, state.open_mass_target);
        target(targets, "open_energy", state.open_energy_enabled, state.open_energy_target);
        state.source_per_step = finite(j, "source_per_step");
        require(j.contains("analysis_enabled") && j["analysis_enabled"].is_boolean(),
                "host-state: missing analysis_enabled");
        state.analysis_enabled = j["analysis_enabled"].get<bool>();
        require(state.analysis_enabled == c.analysis, "host-state: analysis flag differs from configuration");
        if (state.analysis_enabled) {
            require(j.contains("moments") && j["moments"].is_object(), "host-state: missing moments");
            const auto &moments = j["moments"];
            auto moments_valid = [](const Json &m, const size_t fields) {
                if (!m.is_object() || !m.contains("count") || !m["count"].is_number_integer())
                    return false;
                const auto count = m["count"].get<unsigned long long>();
                if (!m.contains("mean") || !m.contains("m2") || !m["mean"].is_array() || !m["m2"].is_array())
                    return false;
                const size_t expected = count == 0 ? 0 : fields;
                if (m["mean"].size() != expected || m["m2"].size() != expected)
                    return false;
                for (const auto &v : m["mean"])
                    if (!v.is_number() || !std::isfinite(v.get<double>()))
                        return false;
                for (const auto &v : m["m2"])
                    if (!v.is_number() || !std::isfinite(v.get<double>()) || v.get<double>() < 0)
                        return false;
                if (count > 0) {
                    if (!m.contains("first") || !m.contains("last") || !m["first"].is_number_integer() ||
                        !m["last"].is_number_integer())
                        return false;
                    if (m["first"].get<unsigned long long>() > m["last"].get<unsigned long long>())
                        return false;
                }
                return true;
            };
            require(moments.contains("global") && moments_valid(moments["global"], 8),
                    "host-state: invalid global moments");
            require(moments.contains("probes") && moments["probes"].is_array() &&
                        moments["probes"].size() == c.probes.size(),
                    "host-state: probe moments count mismatch");
            for (const auto &m : moments["probes"])
                require(moments_valid(m, 6), "host-state: invalid probe moments");
            require(moments.contains("forces") && moments["forces"].is_array() &&
                        moments["forces"].size() == c.forces.size(),
                    "host-state: force moments count mismatch");
            for (const auto &m : moments["forces"])
                require(moments_valid(m, 3), "host-state: invalid force moments");
            state.moments = moments;
        }
        const bool bodies_expected = c.model.dynamic_geometry && c.model.temperature;
        require(j.contains("bodies") && j["bodies"].is_array(), "host-state: missing bodies");
        require(j["bodies"].size() == (bodies_expected ? dynamic_body_count : 0),
                "host-state: dynamic body count mismatch");
        for (const auto &body : j["bodies"]) {
            BodyThermalState entry;
            require(body.is_object() && body.contains("target_cells") && body["target_cells"].is_number_integer(),
                    "host-state: invalid body record");
            entry.target_cells = body["target_cells"].get<unsigned long long>();
            require(body.contains("cells_file") && body.contains("positions_file") &&
                        body.contains("temperatures_file"),
                    "host-state: body files missing");
            entry.cells_file = body["cells_file"].get<std::string>();
            entry.positions_file = body["positions_file"].get<std::string>();
            entry.temperatures_file = body["temperatures_file"].get<std::string>();
            state.bodies.push_back(std::move(entry));
        }
        require(j.contains("outputs") && j["outputs"].is_array(), "host-state: missing outputs");
        for (const auto &record : j["outputs"]) {
            require(record.is_object() && record.contains("path") && record["path"].is_string() &&
                        record.contains("bytes") && record["bytes"].is_number_integer(),
                    "host-state: invalid output record");
            OutputFileRecord entry;
            entry.path = record["path"].get<std::string>();
            entry.bytes = record["bytes"].get<unsigned long long>();
            entry.last_step = record.value("last_step", 0ull);
            state.outputs.push_back(std::move(entry));
        }
        require(j.contains("vtk_frames") && j["vtk_frames"].is_array(), "host-state: missing vtk_frames");
        for (const auto &frame : j["vtk_frames"]) {
            require(frame.is_object() && frame.contains("field") && frame["field"].is_string() &&
                        frame.contains("stamp") && frame["stamp"].is_number_integer(),
                    "host-state: invalid vtk frame record");
            state.vtk_frames.emplace_back(frame["field"].get<std::string>(), frame["stamp"].get<unsigned long long>());
        }
        state.restart_count = j.value("restart_count", 0ull);
        state.final_checkpoint = j.value("final_checkpoint", false);
        state.restarts = j.contains("restarts") && j["restarts"].is_array() ? j["restarts"] : Json::array();
        return state;
    }
};

inline void read_body_binaries(const fs::path &directory, CheckpointHostState &state) {
    for (size_t i = 0; i < state.bodies.size(); i++) {
        auto &body = state.bodies[i];
        const unsigned long long count = body.target_cells;
        auto read_all = [&](const std::string &name, const unsigned long long element_bytes,
                            std::vector<unsigned char> &raw) {
            const fs::path path = directory / name;
            require(fs::exists(path), "Missing body file " + name);
            const auto size = fs::file_size(path);
            require(size == count * element_bytes, "Body file " + name + " has wrong size");
            raw.resize(static_cast<size_t>(size));
            if (size > 0) {
                std::FILE *file = fopen_binary(path, L"rb", "rb");
                require(file != nullptr, "Cannot read " + name);
                const bool ok =
                    std::fread(raw.data(), 1, static_cast<size_t>(size), file) == static_cast<size_t>(size);
                std::fclose(file);
                require(ok, "Short read " + name);
            }
        };
        std::vector<unsigned char> raw;
        read_all(body.cells_file, 8, raw);
        body.cells.resize(static_cast<size_t>(count));
        if (count > 0)
            std::memcpy(body.cells.data(), raw.data(), raw.size());
        read_all(body.positions_file, 12, raw);
        body.positions.resize(static_cast<size_t>(count) * 3);
        if (count > 0)
            std::memcpy(body.positions.data(), raw.data(), raw.size());
        read_all(body.temperatures_file, 4, raw);
        body.temperatures.resize(static_cast<size_t>(count));
        if (count > 0)
            std::memcpy(body.temperatures.data(), raw.data(), raw.size());
    }
}

// ---------------------------------------------------------------------------
// Canonical configuration diff (r2 plan section 3.3)
// ---------------------------------------------------------------------------
inline void collect_diff_paths(const Json &a, const Json &b, const std::string &base,
                               std::vector<std::string> &out) {
    if (a.is_object() && b.is_object()) {
        std::set<std::string> keys;
        for (auto it = a.begin(); it != a.end(); ++it)
            keys.insert(it.key());
        for (auto it = b.begin(); it != b.end(); ++it)
            keys.insert(it.key());
        for (const auto &key : keys) {
            const std::string path = base + "/" + key;
            if (a.contains(key) && b.contains(key))
                collect_diff_paths(a[key], b[key], path, out);
            else
                out.push_back(path);
        }
        return;
    }
    if (a.is_array() && b.is_array()) {
        if (a.size() != b.size()) {
            out.push_back(base);
            return;
        }
        for (size_t i = 0; i < a.size(); i++)
            collect_diff_paths(a[i], b[i], base + "/" + std::to_string(i), out);
        return;
    }
    if (a.type() != b.type() || !(a == b))
        out.push_back(base);
}

// ---------------------------------------------------------------------------
// Output directory single-writer lock (r2 plan section 3.4)
// ---------------------------------------------------------------------------
class OutputLock {
  public:
    OutputLock() = default;
    ~OutputLock() { release(); }
    OutputLock(const OutputLock &) = delete;
    OutputLock &operator=(const OutputLock &) = delete;
    void acquire(const fs::path &output, const bool allow_stale_break) {
#ifdef _WIN32
        path_ = output / "run.lock";
        for (int attempt = 0;; attempt++) {
            handle_ = CreateFileW(path_.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                                  FILE_ATTRIBUTE_NORMAL, nullptr);
            if (handle_ != INVALID_HANDLE_VALUE)
                break;
            require(GetLastError() == ERROR_FILE_EXISTS, "Cannot create run lock: " + path_.u8string());
            unsigned long pid = 0;
            {
                const HANDLE reader = CreateFileW(path_.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                                  nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
                if (reader != INVALID_HANDLE_VALUE) {
                    char buffer[64] = {};
                    DWORD got = 0;
                    ReadFile(reader, buffer, sizeof(buffer) - 1, &got, nullptr);
                    CloseHandle(reader);
                    pid = std::strtoul(buffer, nullptr, 10);
                }
            }
            bool alive = false;
            if (pid != 0) {
                const HANDLE process = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
                if (process != nullptr) {
                    DWORD code = 0;
                    alive = GetExitCodeProcess(process, &code) && code == STILL_ACTIVE;
                    CloseHandle(process);
                }
            }
            require(!alive, "Another Solver-IBM run is active on this output directory (PID " + std::to_string(pid) +
                                "): " + path_.u8string());
            require(allow_stale_break, "Stale run.lock found; only --restart may remove it: " + path_.u8string());
            DeleteFileW(path_.c_str());
            require(attempt < 3, "Cannot acquire run lock: " + path_.u8string());
        }
        const std::string content = std::to_string(GetCurrentProcessId()) + " " + utc_stamp();
        DWORD written = 0;
        WriteFile(handle_, content.data(), static_cast<DWORD>(content.size()), &written, nullptr);
        FlushFileBuffers(handle_);
#else
        (void)output;
        (void)allow_stale_break;
#endif
    }
    void release() {
#ifdef _WIN32
        if (handle_ != INVALID_HANDLE_VALUE) {
            CloseHandle(handle_);
            handle_ = INVALID_HANDLE_VALUE;
        }
#endif
    }

  private:
    fs::path path_;
#ifdef _WIN32
    HANDLE handle_ = INVALID_HANDLE_VALUE;
#endif
};

// ---------------------------------------------------------------------------
// Save (r2 plan sections 5.2-5.6, 6.1)
// ---------------------------------------------------------------------------
struct CheckpointIdentity {
    std::string numerical_identity;   // SHA256 of the numerical kernel source
    std::string original_config_sha;  // SHA256 of inputs/original-config.json
    std::string current_config_sha;   // SHA256 of the config used by the writing run
    std::string executable_sha;       // informational
    std::string device_name;          // informational
    std::string device_driver;        // informational
    unsigned long long accepted_target_steps = 0;
};

constexpr unsigned long long checkpoint_chunk_bytes = 64ull << 20;

inline std::string checkpoint_dir_name(const unsigned long long step) {
    char name[32];
    std::snprintf(name, sizeof(name), "step-%012llu", step);
    return name;
}

inline unsigned long long save_checkpoint(LBM &lbm, const Config &c, const fs::path &output,
                                          const CheckpointHostState &state, const CheckpointIdentity &identity,
                                          std::vector<std::string> &warnings) {
    const fs::path root = output / "checkpoint";
    std::error_code ec;
    fs::create_directories(root, ec);
    require(!ec, "Cannot create checkpoint directory");
    const std::string name = checkpoint_dir_name(state.t);
    const fs::path final_dir = root / name;
    const fs::path tmp_dir = root / (name + ".tmp");
    fs::remove_all(tmp_dir, ec);
    fs::create_directories(tmp_dir);
    try {
        auto fields = checkpoint_fields(lbm, c);
        std::vector<char> buffer(static_cast<size_t>(std::min(checkpoint_chunk_bytes, 64ull << 20)));
        Json layout = Json::array();
        auto write_file = [&](const std::string &file, const unsigned long long bytes,
                              const std::function<void(void *, unsigned long long, unsigned long long)> &read_slice) {
            const fs::path path = tmp_dir / file;
            std::FILE *handle = fopen_binary(path, L"wb", "wb");
            require(handle != nullptr, "Cannot create " + file);
            unsigned long long written = 0;
            while (written < bytes) {
                unsigned long long length = std::min(checkpoint_chunk_bytes, bytes - written);
                read_slice(buffer.data(), written, length);
                require(std::fwrite(buffer.data(), 1, static_cast<size_t>(length), handle) ==
                            static_cast<size_t>(length),
                        "Short write " + file);
                written += length;
            }
            persist_and_close(handle, path);
            const std::string hash = sha256(path);
            if (checkpoint_fault("short_write") && file == fields.front().name + ".bin")
                fs::resize_file(path, bytes / 2); // injected partial write after hashing; caught by the verification stage
            layout.push_back({{"name", file}, {"bytes", bytes}, {"sha256", hash}});
        };
        if (checkpoint_fault("fail_write"))
            throw std::runtime_error("injected failure during field write");
        for (const auto &field : fields)
            write_file(field.name + ".bin", field.bytes, field.read);
        for (size_t i = 0; i < state.bodies.size(); i++) {
            const auto &body = state.bodies[i];
            write_file("body-" + std::to_string(i) + "-cells.bin", body.cells.size() * 8ull,
                       [&](void *destination, const unsigned long long offset, const unsigned long long length) {
                           std::memcpy(destination, reinterpret_cast<const char *>(body.cells.data()) + offset,
                                       static_cast<size_t>(length));
                       });
            write_file("body-" + std::to_string(i) + "-positions.bin", body.positions.size() * 4ull,
                       [&](void *destination, const unsigned long long offset, const unsigned long long length) {
                           std::memcpy(destination, reinterpret_cast<const char *>(body.positions.data()) + offset,
                                       static_cast<size_t>(length));
                       });
            write_file("body-" + std::to_string(i) + "-temperatures.bin", body.temperatures.size() * 4ull,
                       [&](void *destination, const unsigned long long offset, const unsigned long long length) {
                           std::memcpy(destination, reinterpret_cast<const char *>(body.temperatures.data()) + offset,
                                       static_cast<size_t>(length));
                       });
        }
        write_json_persistent(tmp_dir / "host-state.json", state.to_json());
        layout.push_back({{"name", "host-state.json"},
                          {"bytes", fs::file_size(tmp_dir / "host-state.json")},
                          {"sha256", sha256(tmp_dir / "host-state.json")}});
        if (checkpoint_fault("after_file_write"))
            std::_Exit(70); // injected crash: fully written and flushed tmp directory, not yet published
        Json metadata = {{"checkpoint_format_version", checkpoint_format_version_value},
                         {"endianness", "little"},
                         {"product", SOLVER_IBM_NAME},
                         {"version", SOLVER_IBM_VERSION_STRING},
                         {"release_status", SOLVER_IBM_RELEASE_STATUS},
                         {"executable_sha256", identity.executable_sha},
                         {"numerical_identity", identity.numerical_identity},
                         {"config_sha256_original", identity.original_config_sha},
                         {"config_sha256_current", identity.current_config_sha},
                         {"cells", {c.cells[0], c.cells[1], c.cells[2]}},
                         {"storage", ddf_storage_name(c.storage)},
                         {"velocity_set", c.model.q},
                         {"solver_description", solver_description(c)},
                         {"step", state.t},
                         {"time", static_cast<double>(state.t) * c.dt},
                         {"accepted_target_steps", identity.accepted_target_steps},
                         {"final_checkpoint", state.final_checkpoint},
                         {"restart_count", state.restart_count},
                         {"device", {{"name", identity.device_name}, {"driver", identity.device_driver}}},
                         {"created_utc", utc_stamp()},
                         {"state_layout", layout}};
        write_json_persistent(tmp_dir / "checkpoint.json", metadata);
        if (checkpoint_fault("fail_verify")) { // injected corruption after metadata write; caught by W3
            std::FILE *handle = fopen_binary(tmp_dir / (fields.front().name + ".bin"), L"ab", "ab");
            require(handle != nullptr, "Cannot corrupt field file");
            const char zero = 0;
            require(std::fwrite(&zero, 1, 1, handle) == 1, "Fault injection write failed");
            persist_and_close(handle, tmp_dir / (fields.front().name + ".bin"));
        }
        // W3: verify every recorded file against the freshly computed layout
        for (const auto &entry : layout) {
            const fs::path path = tmp_dir / entry["name"].get<std::string>();
            require(fs::exists(path), "Checkpoint file vanished: " + entry["name"].get<std::string>());
            require(fs::file_size(path) == entry["bytes"].get<unsigned long long>(),
                    "Checkpoint file size mismatch: " + entry["name"].get<std::string>());
            require(sha256(path) == entry["sha256"].get<std::string>(),
                    "Checkpoint file hash mismatch: " + entry["name"].get<std::string>());
        }
        if (checkpoint_fault("crash_before_rename"))
            std::_Exit(70); // injected crash: verified tmp directory, not yet published
        // W4: publish (committed once the rename succeeds); same-step republish is idempotent under the lock
        fs::remove_all(final_dir, ec);
        fs::rename(tmp_dir, final_dir, ec);
        require(!ec, "Cannot publish checkpoint directory: " + ec.message());
        if (checkpoint_fault("crash_after_rename"))
            std::_Exit(71); // injected crash: published but latest.json not yet updated
        flush_directory_metadata(root, warnings);
        // W5: update the advisory pointer; failure does not roll back the commit
        try {
            const fs::path latest_tmp = root / "latest.json.tmp";
            write_json_persistent(latest_tmp, {{"step", state.t}, {"dir", name}});
            fs::rename(latest_tmp, root / "latest.json", ec);
            require(!ec, "Cannot update latest.json: " + ec.message());
        } catch (const std::exception &e) {
            warnings.push_back(std::string("latest.json update failed (checkpoint still committed): ") + e.what());
        }
        // W6: retention cleanup; failure does not roll back the commit
        if (checkpoint_fault("crash_during_cleanup"))
            std::_Exit(72); // injected crash: committed, latest published, old checkpoints not yet evicted
        try {
            std::vector<std::pair<unsigned long long, fs::path>> published;
            for (const auto &entry : fs::directory_iterator(root))
                if (entry.is_directory()) {
                    const std::string stem = entry.path().filename().string();
                    unsigned long long step = 0;
                    if (stem.rfind("step-", 0) == 0 && stem.size() == 17 &&
                        stem.find_first_not_of("0123456789", 5) == std::string::npos) {
                        step = std::stoull(stem.substr(5));
                        published.emplace_back(step, entry.path());
                    }
                }
            std::sort(published.begin(), published.end(),
                      [](const auto &a, const auto &b) { return a.first > b.first; });
            for (size_t i = static_cast<size_t>(c.checkpoint_keep); i < published.size(); i++) {
                std::error_code remove_ec;
                fs::remove_all(published[i].second, remove_ec);
                if (remove_ec)
                    warnings.push_back("Old checkpoint cleanup failed: " + published[i].second.u8string());
            }
        } catch (const std::exception &e) {
            warnings.push_back(std::string("Old checkpoint cleanup failed: ") + e.what());
        }
        return state.t;
    } catch (const std::exception &e) {
        fs::remove_all(tmp_dir, ec); // W1-W3 failure: remove the temporary directory, latest.json still points to the previous checkpoint
        throw checkpoint_error(checkpoint_exit_save_failed,
                               "Checkpoint save failed at step " + std::to_string(state.t) + ": " + e.what());
    }
}

// ---------------------------------------------------------------------------
// Load (r2 plan sections 5.4, 6.2, 7, 8)
// ---------------------------------------------------------------------------
struct SelectedCheckpoint {
    fs::path directory;
    unsigned long long step = 0;
    Json metadata;
    CheckpointHostState state;
    bool used_fallback = false;
    bool finish_only = false;
    std::vector<std::string> warnings;
};

inline void quarantine_checkpoint(const fs::path &root, const fs::path &directory, const std::string &reason,
                                  std::vector<std::string> &warnings) {
    std::error_code ec;
    fs::create_directories(root / "quarantine", ec);
    const fs::path target = root / "quarantine" /
                            (directory.filename().string() + "-" + utc_stamp() + "-" +
                             std::to_string(static_cast<unsigned long long>(std::time(nullptr)) % 1000));
    fs::rename(directory, target, ec);
    if (!ec)
        warnings.push_back("Quarantined invalid checkpoint " + directory.filename().string() + " (" + reason + ")");
    else
        warnings.push_back("Could not quarantine invalid checkpoint " + directory.filename().string() + ": " +
                           ec.message());
}

inline SelectedCheckpoint select_checkpoint(LBM &lbm, const Config &c, const fs::path &output,
                                            const std::string &numerical_identity,
                                            const size_t dynamic_body_count) {
    const fs::path root = output / "checkpoint";
    if (!fs::is_directory(root))
        throw checkpoint_error(checkpoint_exit_no_usable,
                               "Restart requested but no checkpoint directory exists: " + root.u8string());
    std::vector<std::pair<unsigned long long, fs::path>> candidates;
    for (const auto &entry : fs::directory_iterator(root)) {
        if (!entry.is_directory())
            continue;
        const std::string stem = entry.path().filename().string();
        if (stem.rfind("step-", 0) != 0 || stem.size() != 17 ||
            stem.find_first_not_of("0123456789", 5) != std::string::npos)
            continue; // ignores quarantine/, *.tmp and anything else
        candidates.emplace_back(std::stoull(stem.substr(5)), entry.path());
    }
    if (candidates.empty())
        throw checkpoint_error(checkpoint_exit_no_usable, "No published checkpoints found in " + root.u8string());
    std::sort(candidates.begin(), candidates.end(), [](const auto &a, const auto &b) { return a.first > b.first; });
    // latest.json is an advisory hint only; prefer it when it names an existing candidate
    {
        std::ifstream latest(root / "latest.json", std::ios::binary);
        if (latest) {
            try {
                const Json hint = Json::parse(latest);
                const auto step = hint.value("step", ~0ull);
                for (size_t i = 0; i < candidates.size(); i++)
                    if (candidates[i].first == step && i != 0) {
                        std::swap(candidates[0], candidates[i]);
                        break;
                    }
            } catch (...) {
                // corrupt hint: fall through to newest-first scanning
            }
        }
    }
    SelectedCheckpoint selected;
    selected.warnings.reserve(4);
    auto fields = checkpoint_fields(lbm, c);
    // Incompatible-identity gates reject the restart outright (exit code 5, never quarantine or fall
    // back); only structural corruption of a candidate quarantines it and tries the next-oldest one.
    auto reject = [](const bool ok, const std::string &message) {
        if (!ok)
            throw checkpoint_error(checkpoint_exit_rejected, message);
    };
    for (size_t index = 0; index < candidates.size(); index++) {
        const auto &candidate = candidates[index];
        const fs::path &directory = candidate.second;
        try {
            std::ifstream metadata_stream(directory / "checkpoint.json", std::ios::binary);
            require(bool(metadata_stream), "checkpoint.json missing");
            const Json metadata = Json::parse(metadata_stream);
            // Compatibility gates (r2 section 8): failures here are rejections, never fallbacks
            reject(metadata.value("checkpoint_format_version", -1) == checkpoint_format_version_value,
                   "Checkpoint format version mismatch");
            reject(metadata.value("endianness", "") == "little", "Checkpoint endianness unsupported");
            reject(metadata.value("product", "") == std::string(SOLVER_IBM_NAME), "Checkpoint product mismatch");
            reject(metadata.value("version", "") == std::string(SOLVER_IBM_VERSION_STRING),
                   "Checkpoint was written by product version " + metadata.value("version", std::string("?")) +
                       ", this executable is " SOLVER_IBM_VERSION_STRING);
            reject(metadata.value("release_status", "") == std::string(SOLVER_IBM_RELEASE_STATUS),
                   "Checkpoint release status mismatch");
            reject(metadata.value("numerical_identity", "") == numerical_identity,
                   "Checkpoint numerical kernel identity differs (source or model changed); refusing to restart");
            reject(metadata.contains("cells") && metadata["cells"].is_array() && metadata["cells"].size() == 3,
                   "Checkpoint metadata lacks grid resolution");
            for (int axis = 0; axis < 3; axis++)
                reject(metadata["cells"][axis].is_number_integer() &&
                           metadata["cells"][axis].get<unsigned>() == c.cells[axis],
                       "Checkpoint grid resolution differs from configuration");
            reject(metadata.value("storage", "") == std::string(ddf_storage_name(c.storage)),
                   "Checkpoint DDF storage differs from configuration");
            reject(metadata.value("velocity_set", 0u) == c.model.q, "Checkpoint velocity set differs");
            reject(metadata.value("config_sha256_original", "") == sha256(output / "original-config.json"),
                   "Run directory original config does not match the checkpoint");
            const unsigned long long step = candidate.first;
            require(metadata.value("step", ~0ull) == step, "Checkpoint step differs from directory name");
            const unsigned long long accepted_target = metadata.value("accepted_target_steps", step);
            reject(c.steps >= step,
                   "Requested steps (" + std::to_string(c.steps) + ") is below the checkpoint step (" +
                       std::to_string(step) + "); nothing to do");
            reject(c.steps >= accepted_target,
                   "Requested steps (" + std::to_string(c.steps) + ") is below the previously accepted target (" +
                       std::to_string(accepted_target) + "); extending runs must not shrink");
            // state_layout must match the planned fields exactly (names, order-independent, sizes)
            reject(metadata.contains("state_layout") && metadata["state_layout"].is_array(),
                   "Checkpoint state_layout missing");
            std::map<std::string, Json> layout;
            for (const auto &entry : metadata["state_layout"])
                layout[entry.value("name", "")] = entry;
            for (const auto &field : fields) {
                const std::string file = field.name + ".bin";
                reject(layout.count(file) == 1, "Checkpoint lacks required field " + file);
                reject(layout[file].value("bytes", ~0ull) == field.bytes,
                       "Field " + file + " size differs from the current model");
            }
            for (const auto &entry : layout) {
                const std::string &name = entry.first;
                if (name == "checkpoint.json")
                    continue;
                const bool known_field =
                    std::any_of(fields.begin(), fields.end(), [&](const FieldIo &f) { return f.name + ".bin" == name; });
                const bool known_body = name.rfind("body-", 0) == 0;
                const bool known_state = name == "host-state.json";
                reject(known_field || known_body || known_state, "Checkpoint contains unknown state file " + name);
            }
            // Integrity: every recorded file must exist with the recorded size and hash
            for (const auto &entry : metadata["state_layout"]) {
                const std::string name = entry.value("name", "");
                const fs::path path = directory / name;
                require(fs::exists(path), "Missing checkpoint file " + name);
                require(fs::file_size(path) == entry.value("bytes", ~0ull), "Checkpoint file size mismatch " + name);
                require(sha256(path) == entry.value("sha256", ""), "Checkpoint file hash mismatch " + name);
            }
            // Host state structural validation
            std::ifstream state_stream(directory / "host-state.json", std::ios::binary);
            require(bool(state_stream), "host-state.json missing");
            CheckpointHostState state = CheckpointHostState::from_json(Json::parse(state_stream), c, step,
                                                                       dynamic_body_count);
            read_body_binaries(directory, state);
            // Output pre-checks: recorded CSV prefixes must exist on disk; recorded VTK frames must exist
            for (const auto &record : state.outputs) {
                const fs::path path = output / record.path;
                require(fs::exists(path), "Recorded output file missing: " + record.path);
                require(fs::file_size(path) >= record.bytes,
                        "Recorded output file lost data: " + record.path);
            }
            for (const auto &frame : state.vtk_frames) {
                char stamp[16];
                std::snprintf(stamp, sizeof(stamp), "%09llu", frame.second);
                const fs::path path = output / (frame.first + "-" + stamp + ".vtk");
                require(fs::exists(path) && fs::file_size(path) > 0, "Recorded VTK frame missing: " + path.u8string());
            }
            selected.directory = directory;
            selected.step = step;
            selected.metadata = metadata;
            selected.state = std::move(state);
            selected.used_fallback = index > 0;
            selected.finish_only = (c.steps == step) && metadata.value("final_checkpoint", false);
            if (selected.used_fallback)
                selected.warnings.push_back("Newest checkpoints unusable; restored from " + directory.filename().string());
            if (metadata.value("executable_sha256", "") != executable_sha256())
                selected.warnings.push_back(
                    "Checkpoint was written by a different executable build (numerical identity matches); results are "
                    "only guaranteed comparable on the same device and driver");
            return selected;
        } catch (const checkpoint_error &) {
            throw; // compatibility rejections never fall back
        } catch (const std::exception &e) {
            quarantine_checkpoint(root, directory, e.what(), selected.warnings);
        }
    }
    throw checkpoint_error(checkpoint_exit_no_usable,
                           "No usable checkpoint in " + root.u8string() + " (all candidates failed validation)");
}

inline void apply_checkpoint(LBM &lbm, const Config &c, const fs::path &output, const SelectedCheckpoint &selected) {
    const CheckpointHostState &state = selected.state;
    // Output repair (r2 section 7.1): truncate CSVs to the confirmed byte positions, remove stray VTK frames.
    for (const auto &record : state.outputs) {
        const fs::path path = output / record.path;
        const auto size = fs::file_size(path);
        if (size > record.bytes)
            fs::resize_file(path, record.bytes);
    }
    std::set<std::string> keep_frames;
    for (const auto &frame : state.vtk_frames) {
        char stamp[16];
        std::snprintf(stamp, sizeof(stamp), "%09llu", frame.second);
        keep_frames.insert(frame.first + "-" + stamp + ".vtk");
    }
    std::vector<fs::path> stray;
    for (const auto &entry : fs::directory_iterator(output)) {
        if (!entry.is_regular_file())
            continue;
        const std::string name = entry.path().filename().string();
        if (entry.path().extension() != ".vtk" || name.size() < 15 || name[name.size() - 14] != '-')
            continue;
        const std::string digits = name.substr(name.size() - 13, 9);
        if (digits.find_first_not_of("0123456789") != std::string::npos)
            continue;
        if (keep_frames.count(name) == 0)
            stray.push_back(entry.path());
    }
    std::error_code ec;
    for (const auto &path : stray)
        fs::remove(path, ec);
    // Device state load: chunked staging, uniform for host-backed and device-only fields
    auto fields = checkpoint_fields(lbm, c);
    std::vector<char> buffer(static_cast<size_t>(checkpoint_chunk_bytes));
    for (const auto &field : fields) {
        const fs::path path = selected.directory / (field.name + ".bin");
        std::FILE *handle = fopen_binary(path, L"rb", "rb");
        require(handle != nullptr, "Cannot read " + path.u8string());
        unsigned long long loaded = 0;
        while (loaded < field.bytes) {
            const unsigned long long length = std::min(checkpoint_chunk_bytes, field.bytes - loaded);
            require(std::fread(buffer.data(), 1, static_cast<size_t>(length), handle) == static_cast<size_t>(length),
                    "Short read " + field.name);
            field.write(buffer.data(), loaded, length);
            loaded += length;
        }
        // Defense in depth: read the device buffer back and compare against the file byte-for-byte
        // before the run continues; any mismatch aborts the restart instead of evolving wrong state.
        std::rewind(handle);
        std::vector<char> readback(static_cast<size_t>(std::min(checkpoint_chunk_bytes, field.bytes ? field.bytes : 1ull)));
        unsigned long long verified = 0;
        while (verified < field.bytes) {
            const unsigned long long length = std::min(checkpoint_chunk_bytes, field.bytes - verified);
            require(std::fread(buffer.data(), 1, static_cast<size_t>(length), handle) == static_cast<size_t>(length),
                    "Short read " + field.name);
            field.read(readback.data(), verified, length);
            if (std::memcmp(readback.data(), buffer.data(), static_cast<size_t>(length)) != 0) {
                unsigned long long offset = 0;
                while (offset < length && readback[offset] == buffer[offset])
                    offset++;
                std::fclose(handle);
                throw checkpoint_error(checkpoint_exit_no_usable,
                                       "Device state load verification failed for field " + field.name + " at byte " +
                                           std::to_string(verified + offset));
            }
            verified += length;
        }
        std::fclose(handle);
        if (field.sync_host)
            field.sync_host();
    }
    // Time step restore: set_time_step also aligns t_last_update_fields so the next container
    // read_from_device() does not fire a redundant kernel_update_fields (not idempotent for TYPE_MS
    // cells; it would clobber the restored rho/u). Mirrors a continuous run at the checkpoint save point.
    lbm.lbm_domain[0]->set_time_step(state.t);
}

} // namespace fxconfig
