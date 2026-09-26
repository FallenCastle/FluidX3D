#include "config.hpp"
#include "version.hpp"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <limits>
#include <set>
#include <sstream>
#include <stdexcept>
#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <wincrypt.h>
#endif

namespace fxconfig {
void require(bool ok, const std::string &message) {
    if (!ok)
        throw std::runtime_error(message);
}
static void keys(const Json &j, std::initializer_list<const char *> names, const std::string &at) {
    require(j.is_object(), at + ": expected an object");
    std::set<std::string> allowed;
    for (auto name : names)
        allowed.insert(name);
    for (auto it = j.begin(); it != j.end(); ++it)
        require(allowed.count(it.key()) != 0, at + ": unknown field '" + it.key() + "'");
}
static const Json &field(const Json &j, const char *name) {
    require(j.contains(name), std::string("Missing required field: ") + name);
    return j.at(name);
}
static std::string string_value(const Json &j, const std::string &at) {
    require(j.is_string(), at + ": expected a string");
    return j.get<std::string>();
}
double number(const Json &j, const std::string &at) {
    require(j.is_number(), at + ": expected a number");
    double x = j.get<double>();
    require(std::isfinite(x), at + ": must be finite");
    return x;
}
static double positive(const Json &j, const std::string &at) {
    double x = number(j, at);
    require(x > 0, at + ": must be positive");
    return x;
}
static unsigned long long integer(const Json &j, const std::string &at, bool zero = false) {
    require(j.is_number_integer(), at + ": expected an integer");
    require(j.is_number_unsigned() || j.get<long long>() >= 0, at + ": must be nonnegative");
    auto x = j.get<unsigned long long>();
    require((zero || x > 0) && x <= 9007199254740991ull, at + ": integer outside supported range");
    return x;
}
static Vec vec(const Json &j, const std::string &at) {
    require(j.is_array() && j.size() == 3, at + ": expected three coordinates");
    return {number(j[0], at), number(j[1], at), number(j[2], at)};
}
static void finite_float(double x, const std::string &at, bool pos = false) {
    require(std::isfinite(x) && std::abs(x) <= std::numeric_limits<float>::max(), at + ": outside float range");
    if (pos)
        require(static_cast<float>(x) > 0, at + ": underflow or non-positive value");
}
void save_json(const fs::path &path, const Json &j) {
    std::ofstream out(path, std::ios::binary);
    require(bool(out), "Cannot write " + path.u8string());
    out << j.dump(2) << '\n';
    out.close();
    require(bool(out), "Cannot finish writing " + path.u8string());
}
std::string sha256(const fs::path &path) {
#ifdef _WIN32
    HCRYPTPROV provider = 0;
    HCRYPTHASH hash = 0;
    require(CryptAcquireContextW(&provider, nullptr, nullptr, PROV_RSA_AES, CRYPT_VERIFYCONTEXT) != 0,
            "SHA256 provider failure");
    if (!CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash)) {
        CryptReleaseContext(provider, 0);
        throw std::runtime_error("SHA256 hash failure");
    }
    try {
        std::ifstream in(path, std::ios::binary);
        require(bool(in), "Cannot hash " + path.u8string());
        char block[65536];
        while (in) {
            in.read(block, sizeof(block));
            auto n = in.gcount();
            if (n > 0)
                require(CryptHashData(hash, reinterpret_cast<BYTE *>(block), static_cast<DWORD>(n), 0) != 0,
                        "SHA256 update failure");
        }
        require(in.eof(), "Hash input read failure");
        BYTE result[32];
        DWORD count = 32;
        require(CryptGetHashParam(hash, HP_HASHVAL, result, &count, 0) != 0 && count == 32, "SHA256 result failure");
        std::ostringstream out;
        out << std::hex << std::setfill('0');
        for (auto v : result)
            out << std::setw(2) << unsigned(v);
        CryptDestroyHash(hash);
        CryptReleaseContext(provider, 0);
        return out.str();
    } catch (...) {
        CryptDestroyHash(hash);
        CryptReleaseContext(provider, 0);
        throw;
    }
#else
    throw std::runtime_error("Configuration runner hashing currently requires the Windows NUC build");
#endif
}
Json capabilities() {
    return {{"product", SOLVER_IBM_NAME},
            {"version", SOLVER_IBM_VERSION_STRING},
            {"release_status", SOLVER_IBM_RELEASE_STATUS},
            {"upstream", {{"product", SOLVER_IBM_UPSTREAM_NAME}, {"version", SOLVER_IBM_UPSTREAM_VERSION}}},
            {"schema_version", 1},
            {"lattice", {"D3Q19", "D3Q27"}},
            {"collision", {"SRT", "TRT"}},
            {"storage", {"FP16S", "FP32"}},
            {"default_storage", "FP16S"},
            {"arithmetic", "FP32"},
            {"turbulence", {"none", "smagorinsky"}},
            {"units", {"lattice", "si"}},
            {"boundaries", {"no_slip", "moving_wall", "equilibrium", "periodic"}},
            {"physics",
             {{"thermal", {{"storage", "FP32"}, {"model", "D3Q7 advection-diffusion with Boussinesq coupling"}}},
              {"free_surface", {{"storage", "FP32"}, {"gas", "fixed environment pressure"}}}}},
            {"geometry", "binary STL static union; prescribed motion is staged after M1"},
            {"outputs", {"VTK", "CSV", "JSON"}},
            {"body_force", "constant force density"},
            {"analysis", {"probes", "temporal statistics", "gauge force on solids"}},
            {"device_bytes_per_cell", {{"FP16S", 67}, {"FP32", 105}}},
            {"defaults",
             {{"lattice", "D3Q19"},
              {"collision", "SRT"},
              {"storage", "FP16S"},
              {"turbulence", "smagorinsky"},
              {"smagorinsky_constant", SolverOptions::default_cs},
              {"trt_magic_parameter", 0.1875}}},
            {"model_device_bytes_per_cell",
             {{"D3Q19", {{"FP16S", 67}, {"FP32", 105}}}, {"D3Q27", {{"FP16S", 83}, {"FP32", 137}}}}},
            {"parameters",
             {{"smagorinsky_constant", {{"exclusive_minimum", 0}, {"maximum", 1}, {"requires", "smagorinsky"}}},
              {"trt_magic_parameter", {{"exclusive_minimum", 0}, {"maximum", 1}, {"requires", "TRT"}}}}},
            {"graphics", false},
            {"devices_per_run", 1}};
}
Json solver_description(const Config &c) {
    float even_rate = 1.0f / (3.0f * static_cast<float>(c.nu) + 0.5f);
    Json result = {{"lattice", c.model.lattice_name()},
                   {"collision", c.model.collision_name()},
                   {"storage", ddf_storage_name(c.storage)},
                   {"turbulence", c.model.turbulence_name()},
                   {"base_even_relaxation_rate", even_rate}};
    result["physics"] = {{"thermal", c.model.temperature}, {"free_surface", c.model.free_surface}};
    if (c.model.subgrid) {
        result["smagorinsky_constant"] = c.model.smagorinsky_constant;
        result["smagorinsky_coefficient_fp32"] = c.model.smagorinsky_coefficient();
    }
    if (c.model.collision == CollisionModel::TwoRelaxation) {
        float lambda = static_cast<float>(c.model.trt_magic_parameter);
        float odd_rate = 1.0f / (lambda / (1.0f / even_rate - 0.5f) + 0.5f);
        require(std::isfinite(even_rate) && even_rate > 0 && even_rate < 2 && std::isfinite(odd_rate) && odd_rate > 0 &&
                    odd_rate < 2,
                "solver.trt_magic_parameter and viscosity produce unrepresentable relaxation rates");
        result["trt_magic_parameter"] = c.model.trt_magic_parameter;
        result["trt_magic_parameter_fp32"] = lambda;
        result["base_odd_relaxation_rate"] = odd_rate;
    }
    return result;
}
Config read_config(const fs::path &path) {
    Config c;
    c.path = fs::absolute(path);
    std::ifstream input(c.path, std::ios::binary);
    require(bool(input), "Cannot open config: " + c.path.u8string());
    std::vector<std::set<std::string>> objects;
    auto callback = [&](int, nlohmann::json::parse_event_t event, Json &value) {
        if (event == Json::parse_event_t::object_start)
            objects.emplace_back();
        if (event == Json::parse_event_t::key)
            require(objects.back().insert(value.get<std::string>()).second,
                    "Duplicate JSON key: " + value.get<std::string>());
        if (event == Json::parse_event_t::object_end)
            objects.pop_back();
        return true;
    };
    c.source = Json::parse(input, callback);
    const auto &j = c.source;
    keys(j,
         {"schema_version", "case", "solver", "physics", "units", "domain", "fluid", "initial", "geometry", "boundaries",
          "run", "output", "analysis"},
         "config");
    require(integer(field(j, "schema_version"), "schema_version") == 1, "Unsupported schema_version");
    const auto &ca = field(j, "case");
    keys(ca, {"name"}, "case");
    c.name = string_value(field(ca, "name"), "case.name");
    require(!c.name.empty(), "Empty case name");
    if (j.contains("solver")) {
        const auto &solver = j["solver"];
        keys(solver, {"lattice", "collision", "storage", "turbulence", "smagorinsky_constant", "trt_magic_parameter"},
             "solver");
        auto choice = [&](const char *key, const char *fallback, const char *a, const char *b) {
            auto value =
                solver.contains(key) ? string_value(solver[key], std::string("solver.") + key) : std::string(fallback);
            require(value == a || value == b, std::string("Unsupported solver.") + key + "; use --capabilities");
            return value;
        };
        c.model.q = choice("lattice", "D3Q19", "D3Q19", "D3Q27") == "D3Q27" ? 27u : 19u;
        c.model.collision = choice("collision", "SRT", "SRT", "TRT") == "TRT" ? CollisionModel::TwoRelaxation
                                                                              : CollisionModel::SingleRelaxation;
        c.storage =
            choice("storage", "FP16S", "FP16S", "FP32") == "FP32" ? DdfStorage::Float32 : DdfStorage::Float16Scaled;
        c.model.subgrid = choice("turbulence", "smagorinsky", "none", "smagorinsky") == "smagorinsky";
        if (solver.contains("smagorinsky_constant")) {
            require(c.model.subgrid, "solver.smagorinsky_constant requires turbulence=smagorinsky");
            c.model.smagorinsky_constant = number(solver["smagorinsky_constant"], "solver.smagorinsky_constant");
            require(c.model.smagorinsky_constant > 0 && c.model.smagorinsky_constant <= 1,
                    "solver.smagorinsky_constant must be in (0,1]");
            require(std::isfinite(c.model.smagorinsky_coefficient()) && c.model.smagorinsky_coefficient() > 0,
                    "solver.smagorinsky_constant coefficient is not representable in FP32");
        }
        if (solver.contains("trt_magic_parameter")) {
            require(c.model.collision == CollisionModel::TwoRelaxation,
                    "solver.trt_magic_parameter requires collision=TRT");
            c.model.trt_magic_parameter = number(solver["trt_magic_parameter"], "solver.trt_magic_parameter");
            require(c.model.trt_magic_parameter > 0 && c.model.trt_magic_parameter <= 1,
                    "solver.trt_magic_parameter must be in (0,1]");
        }
    }
    const Json *physics = nullptr;
    if (j.contains("physics")) {
        physics = &j["physics"];
        keys(*physics, {"gravity", "thermal", "free_surface"}, "physics");
        if (physics->contains("thermal")) {
            require((*physics)["thermal"].is_object(), "physics.thermal must be an object");
            c.model.temperature = true;
        }
        if (physics->contains("free_surface")) {
            require((*physics)["free_surface"].is_object(), "physics.free_surface must be an object");
            c.model.free_surface = true;
        }
        require(!(c.model.temperature || c.model.free_surface) || c.storage == DdfStorage::Float32,
                "Thermal and free-surface physics require solver.storage=FP32");
    }
    const auto &u = field(j, "units");
    keys(u, {"mode", "reference_density", "dt", "reference_velocity", "lattice_velocity"}, "units");
    auto mode = string_value(field(u, "mode"), "units.mode");
    require(mode == "si" || mode == "lattice", "units.mode must be si or lattice");
    c.si = mode == "si";
    const auto &d = field(j, "domain");
    keys(d, {"cells", "aspect_ratio", "memory_budget_mb", "length", "dx", "origin"}, "domain");
    if (d.contains("origin"))
        c.origin = vec(d["origin"], "domain.origin");
    if (c.si) {
        require(!d.contains("cells") && !d.contains("aspect_ratio") && !d.contains("memory_budget_mb"),
                "SI domain requires length and dx only");
        c.dx = positive(field(d, "dx"), "domain.dx");
        auto length = vec(field(d, "length"), "domain.length");
        for (int a = 0; a < 3; a++) {
            double n = length[a] / c.dx;
            require(n > 0 && std::isfinite(n) && n <= 1000000, "Invalid domain length/dx");
            double nearest = std::round(n);
            if (std::abs(n - nearest) < 1e-10 * std::max(1.0, n))
                n = nearest;
            c.cells[a] = static_cast<unsigned>(std::ceil(n));
        }
        c.reference_density = positive(field(u, "reference_density"), "units.reference_density");
        if (u.contains("dt")) {
            require(!u.contains("reference_velocity") && !u.contains("lattice_velocity"),
                    "Choose dt or velocity time scaling");
            c.dt = positive(u["dt"], "units.dt");
        } else
            c.dt = positive(field(u, "lattice_velocity"), "units.lattice_velocity") * c.dx /
                   positive(field(u, "reference_velocity"), "units.reference_velocity");
    } else {
        require(u.size() == 1, "Lattice units do not accept SI scale fields");
        require(!d.contains("length") && !d.contains("dx"), "Lattice domain uses cells or memory budget");
        if (d.contains("cells")) {
            require(!d.contains("aspect_ratio") && !d.contains("memory_budget_mb"), "Choose cells or memory budget");
            const auto &ns = d["cells"];
            require(ns.is_array() && ns.size() == 3, "domain.cells requires three integers");
            for (int a = 0; a < 3; a++) {
                auto n = integer(ns[a], "domain.cells");
                require(n <= 1000000, "domain.cells exceeds supported dimension");
                c.cells[a] = static_cast<unsigned>(n);
            }
        } else {
            auto aspect = vec(field(d, "aspect_ratio"), "domain.aspect_ratio");
            auto mb = integer(field(d, "memory_budget_mb"), "domain.memory_budget_mb");
            require(mb <= 1048576, "Memory budget too large");
            for (auto v : aspect)
                require(v > 0 && v < 1e6, "Invalid aspect ratio");
            // Match the upstream float calculation and nearest-integer conversion.
            float ax = static_cast<float>(aspect[0]), ay = static_cast<float>(aspect[1]),
                  az = static_cast<float>(aspect[2]);
            float bytes = ax * ay * az * static_cast<float>(c.device_cell_bytes()) / 1048576.0f;
            float scale = std::cbrt(static_cast<float>(mb) / bytes);
            for (int a = 0; a < 3; a++) {
                double n = static_cast<float>(scale * static_cast<float>(aspect[a])) + 0.5f;
                require(std::isfinite(n) && n <= 1000000, "Invalid memory-derived dimension");
                c.cells[a] = static_cast<unsigned>(n);
            }
        }
    }
    for (auto n : c.cells)
        require(n >= 3, "Each domain dimension must be at least 3");
    unsigned long long count = 1;
    for (auto n : c.cells) {
        require(count <= std::numeric_limits<unsigned long long>::max() / n, "Grid product overflow");
        count *= n;
    }
    require(count <= std::numeric_limits<size_t>::max() / 64 && count <= 10000000000ull,
            "Grid exceeds supported allocation range");
    require(std::isfinite(c.dt) && c.dt > 0, "Invalid dt");
    finite_float(c.dx, "dx", true);
    finite_float(c.dt, "dt", true);
    finite_float(c.reference_density, "reference_density", true);
    finite_float(c.dx / c.dt, "velocity unit scale", true);
    finite_float(c.reference_density * c.dx * c.dx * c.dx, "mass unit scale", true);
    for (int a = 0; a < 3; a++) {
        require(std::isfinite(c.origin[a] + c.cells[a] * c.dx), "Domain coordinates overflow");
        require(c.origin[a] + 0.5 * c.dx != c.origin[a] + 1.5 * c.dx,
                "Domain origin is too large to resolve the chosen spacing");
    }
    const auto &f = field(j, "fluid");
    keys(f, {"rho", "nu", "reynolds", "reference_length", "reference_velocity", "body_force"}, "fluid");
    double density = positive(field(f, "rho"), "fluid.rho");
    c.rho = density / c.reference_density;
    c.pressure_rho = c.rho;
    if (f.contains("body_force")) {
        c.body_force = vec(f["body_force"], "fluid.body_force");
        for (auto &x : c.body_force) {
            x *= c.dt * c.dt / (c.reference_density * c.dx);
            finite_float(x, "lattice body force");
        }
    }
    double viscosity;
    if (f.contains("nu")) {
        require(!f.contains("reynolds") && !f.contains("reference_length") && !f.contains("reference_velocity"),
                "Choose nu or Reynolds mode");
        viscosity = positive(f["nu"], "fluid.nu");
    } else
        viscosity = positive(field(f, "reference_velocity"), "fluid.reference_velocity") *
                    positive(field(f, "reference_length"), "fluid.reference_length") /
                    positive(field(f, "reynolds"), "fluid.reynolds");
    c.nu = viscosity * c.dt / (c.dx * c.dx);
    finite_float(c.nu, "lattice viscosity", true);
    finite_float(0.5 + 3 * c.nu, "relaxation time", true);
    finite_float(c.rho, "lattice density", true);
    if (c.model.free_surface) {
        const auto &surface = (*physics)["free_surface"];
        keys(surface, {"surface_tension", "environment_pressure"}, "physics.free_surface");
        double sigma = number(field(surface, "surface_tension"), "physics.free_surface.surface_tension");
        require(sigma >= 0, "physics.free_surface.surface_tension must be nonnegative");
        c.surface_tension = c.si ? sigma * c.dt * c.dt /
                                           (c.reference_density * c.dx * c.dx * c.dx)
                                     : sigma;
        require(c.surface_tension <= 0.1, "Lattice surface tension must not exceed 0.1");
        finite_float(c.surface_tension, "lattice surface tension");
        if (surface.contains("environment_pressure")) {
            c.environment_pressure = number(surface["environment_pressure"], "physics.free_surface.environment_pressure");
            require(c.environment_pressure >= 0, "environment pressure must be nonnegative");
        }
        const double pressure_scale = c.reference_density * (c.dx / c.dt) * (c.dx / c.dt);
        const double lattice_pressure = c.si ? c.environment_pressure / pressure_scale : c.environment_pressure;
        c.environment_lattice_density = c.pressure_rho + 3.0 * lattice_pressure;
        require(c.environment_lattice_density > 0, "environment pressure produces non-positive lattice density");
        finite_float(c.environment_lattice_density, "environment lattice density", true);
        c.model.ambient_density = c.environment_lattice_density;
    }
    if (c.model.temperature) {
        const auto &thermal = (*physics)["thermal"];
        keys(thermal,
             {"reference_temperature", "initial_temperature", "specific_heat", "conductivity", "thermal_expansion",
              "turbulent_prandtl"},
             "physics.thermal");
        c.temperature_scale = positive(field(thermal, "reference_temperature"), "physics.thermal.reference_temperature");
        c.initial_temperature =
            positive(field(thermal, "initial_temperature"), "physics.thermal.initial_temperature") / c.temperature_scale;
        c.fluid_specific_heat = positive(field(thermal, "specific_heat"), "physics.thermal.specific_heat");
        c.fluid_conductivity = positive(field(thermal, "conductivity"), "physics.thermal.conductivity");
        double alpha = c.fluid_conductivity / (density * c.fluid_specific_heat);
        c.thermal_diffusivity = c.si ? alpha * c.dt / (c.dx * c.dx) : alpha;
        require(c.thermal_diffusivity > 0 && c.thermal_diffusivity < 1.75,
                "Lattice thermal diffusivity must be in (0,1.75)");
        c.thermal_expansion = thermal.contains("thermal_expansion")
                                  ? number(thermal["thermal_expansion"], "physics.thermal.thermal_expansion") *
                                        c.temperature_scale
                                  : 0.0;
        require(c.thermal_expansion >= 0, "thermal expansion must be nonnegative");
        c.model.reference_temperature = 1.0;
        if (thermal.contains("turbulent_prandtl"))
            c.turbulent_prandtl = positive(thermal["turbulent_prandtl"], "physics.thermal.turbulent_prandtl");
        finite_float(c.initial_temperature, "initial lattice temperature", true);
        finite_float(c.thermal_diffusivity, "lattice thermal diffusivity", true);
        finite_float(c.thermal_expansion, "lattice thermal expansion");
    }
    c.gravity = physics && physics->contains("gravity") ? vec((*physics)["gravity"], "physics.gravity") : Vec{};
    for (int a = 0; a < 3; a++) {
        const double acceleration = c.si ? c.gravity[a] * c.dt * c.dt / c.dx : c.gravity[a];
        c.model.gravity[a] = c.rho * acceleration;
        c.body_force[a] += c.model.gravity[a];
        finite_float(c.model.gravity[a], "lattice gravity force density");
        finite_float(c.body_force[a], "combined lattice body force");
    }
    auto velocity = [&](const Json &v, const std::string &at) {
        Vec out = vec(v, at);
        for (auto &x : out) {
            x = x * c.dt / c.dx;
            finite_float(x, at);
        }
        return out;
    };
    const auto &init = field(j, "initial");
    keys(init, {"rho", "velocity", "temperature", "regions", "liquid_regions"}, "initial");
    c.velocity = velocity(field(init, "velocity"), "initial.velocity");
    if (init.contains("rho"))
        c.rho = positive(init["rho"], "initial.rho") / c.reference_density;
    if (init.contains("temperature")) {
        require(c.model.temperature, "initial.temperature requires physics.thermal");
        c.initial_temperature = positive(init["temperature"], "initial.temperature") / c.temperature_scale;
    }
    finite_float(c.rho, "initial lattice density", true);
    if (init.contains("regions")) {
        require(init["regions"].is_array(), "initial.regions must be an array");
        for (const auto &r : init["regions"]) {
            keys(r, {"box_min", "box_max", "rho", "velocity", "temperature"}, "initial region");
            InitialRegion region;
            region.lower = vec(field(r, "box_min"), "box_min");
            region.upper = vec(field(r, "box_max"), "box_max");
            region.rho = positive(field(r, "rho"), "region.rho") / c.reference_density;
            finite_float(region.rho, "region.rho", true);
            region.velocity = velocity(field(r, "velocity"), "region.velocity");
            if (r.contains("temperature")) {
                require(c.model.temperature, "region.temperature requires physics.thermal");
                region.has_temperature = true;
                region.temperature = positive(r["temperature"], "region.temperature") / c.temperature_scale;
                finite_float(region.temperature, "region.temperature", true);
            }
            for (int a = 0; a < 3; a++)
                require(region.lower[a] <= region.upper[a], "Reversed initial region");
            c.regions.push_back(region);
        }
    }
    if (init.contains("liquid_regions")) {
        require(c.model.free_surface, "initial.liquid_regions requires physics.free_surface");
        require(init["liquid_regions"].is_array() && !init["liquid_regions"].empty(),
                "initial.liquid_regions must be a nonempty array");
        for (const auto &r : init["liquid_regions"]) {
            keys(r, {"box_min", "box_max", "fill"}, "liquid region");
            LiquidRegion region;
            region.lower = vec(field(r, "box_min"), "liquid region.box_min");
            region.upper = vec(field(r, "box_max"), "liquid region.box_max");
            region.fill = r.contains("fill") ? number(r["fill"], "liquid region.fill") : 1.0;
            require(region.fill > 0 && region.fill <= 1, "liquid region.fill must be in (0,1]");
            for (int a = 0; a < 3; a++)
                require(region.lower[a] <= region.upper[a], "Reversed liquid region");
            c.liquid_regions.push_back(region);
        }
    }
    require(!c.model.free_surface || !c.liquid_regions.empty(),
            "Free-surface physics requires initial.liquid_regions");
    const auto &gs = field(j, "geometry");
    require(gs.is_array(), "geometry must be an array");
    std::set<std::string> ids;
    for (const auto &g : gs) {
        keys(g, {"id", "file", "transform"}, "geometry");
        Geometry geo;
        geo.id = string_value(field(g, "id"), "geometry.id");
        require(!geo.id.empty() && ids.insert(geo.id).second, "Empty/duplicate geometry ID");
        geo.file = fs::absolute(c.path.parent_path() / fs::u8path(string_value(field(g, "file"), "geometry.file")));
        const auto &t = field(g, "transform");
        keys(t, {"mode", "size", "center", "factor", "pivot", "translation", "axis", "degrees"}, "transform");
        geo.mode = string_value(field(t, "mode"), "transform.mode");
        if (t.contains("axis"))
            geo.axis = vec(t["axis"], "transform.axis");
        if (t.contains("degrees"))
            geo.degrees = number(t["degrees"], "transform.degrees");
        double norm = std::hypot(geo.axis[0], std::hypot(geo.axis[1], geo.axis[2]));
        require(std::isfinite(norm) && norm > 0, "Rotation axis must be nonzero");
        for (auto &v : geo.axis)
            v /= norm;
        if (geo.mode == "fit") {
            require(!t.contains("factor") && !t.contains("pivot") && !t.contains("translation"),
                    "fit uses size and center");
            geo.size = positive(field(t, "size"), "transform.size");
            geo.center = vec(field(t, "center"), "transform.center");
        } else {
            require(geo.mode == "scale", "transform.mode must be fit or scale");
            require(!t.contains("size") && !t.contains("center"), "scale uses factor, pivot and translation");
            geo.factor = positive(field(t, "factor"), "transform.factor");
            geo.pivot = t.contains("pivot") ? vec(t["pivot"], "transform.pivot") : Vec{};
            geo.translation = vec(field(t, "translation"), "transform.translation");
        }
        require(fs::is_regular_file(geo.file), "STL not found: " + geo.file.u8string());
        c.geometry.push_back(geo);
    }
    const auto &bs = field(j, "boundaries");
    require(bs.is_array(), "boundaries must be an array");
    ids.clear();
    const std::array<std::string, 6> names{"xmin", "xmax", "ymin", "ymax", "zmin", "zmax"};
    std::array<int, 6> topology{};
    for (const auto &b : bs) {
        keys(b, {"id", "faces", "type", "priority", "region", "rho", "velocity"}, "boundary");
        Boundary bound;
        bound.id = string_value(field(b, "id"), "boundary.id");
        require(!bound.id.empty() && ids.insert(bound.id).second, "Empty/duplicate boundary ID");
        bound.type = string_value(field(b, "type"), "boundary.type");
        require(bound.type == "periodic" || bound.type == "equilibrium" || bound.type == "no_slip" ||
                    bound.type == "moving_wall",
                "Unsupported boundary type");
        if (b.contains("priority")) {
            require(b["priority"].is_number_integer(), "priority must be integer");
            double p = number(b["priority"], "priority");
            require(p >= -1000000 && p <= 1000000, "priority out of range");
            bound.priority = static_cast<int>(p);
        }
        auto &faces = field(b, "faces");
        require(faces.is_array() && !faces.empty(), "boundary.faces must be nonempty");
        std::set<int> unique;
        for (const auto &face : faces) {
            auto name = string_value(face, "face");
            auto it = std::find(names.begin(), names.end(), name);
            require(it != names.end(), "Unknown face: " + name);
            int index = static_cast<int>(it - names.begin());
            require(unique.insert(index).second, "Duplicate face");
            bound.faces.push_back(index);
            topology[index] |= bound.type == "periodic" ? 1 : 2;
        }
        if (b.contains("region")) {
            require(bound.type != "periodic", "Periodic boundaries must cover entire axes");
            keys(b["region"], {"min", "max"}, "boundary.region");
            const auto &lo = field(b["region"], "min");
            const auto &hi = field(b["region"], "max");
            require(lo.is_array() && hi.is_array() && lo.size() == 2 && hi.size() == 2,
                    "region requires two tangential coordinates");
            for (int a = 0; a < 2; a++) {
                bound.lower[a] = number(lo[a], "region.min");
                bound.upper[a] = number(hi[a], "region.max");
                require(bound.lower[a] <= bound.upper[a], "Reversed boundary region");
            }
            bound.region = true;
        }
        if (bound.type == "equilibrium") {
            bound.rho = positive(field(b, "rho"), "boundary.rho") / c.reference_density;
            finite_float(bound.rho, "boundary.rho", true);
            bound.velocity = velocity(field(b, "velocity"), "boundary.velocity");
        } else if (bound.type == "moving_wall") {
            require(!b.contains("rho"), "moving_wall does not accept rho");
            bound.velocity = velocity(field(b, "velocity"), "moving_wall.velocity");
            for (int face : bound.faces)
                require(bound.velocity[face / 2] == 0, "moving_wall velocity must be tangential");
        } else
            require(!b.contains("rho") && !b.contains("velocity"), "Only equilibrium/moving_wall accept velocity");
        c.boundaries.push_back(bound);
    }
    for (int a = 0; a < 3; a++) {
        require(topology[2 * a] && topology[2 * a + 1], "All six faces must be declared");
        require(topology[2 * a] != 3 && topology[2 * a + 1] != 3, "Periodic face conflicts with boundary rules");
        require((topology[2 * a] == 1) == (topology[2 * a + 1] == 1), "Periodic axes must be paired");
        c.periodic[a] = topology[2 * a] == 1;
    }
    const auto &run = field(j, "run");
    keys(run, {"steps", "duration", "monitor_every"}, "run");
    require(run.contains("steps") != run.contains("duration"), "Choose steps or duration");
    if (run.contains("steps"))
        c.steps = integer(run["steps"], "run.steps");
    else {
        require(c.si, "duration requires SI units");
        double raw_steps = positive(run["duration"], "run.duration") / c.dt;
        double nearest = std::round(raw_steps);
        if (std::abs(raw_steps - nearest) < 1e-10 * std::max(1.0, raw_steps))
            raw_steps = nearest;
        double steps = std::ceil(raw_steps);
        require(std::isfinite(steps) && steps >= 1 && steps <= 9007199254740991.,
                "duration/dt outside supported range");
        c.steps = static_cast<unsigned long long>(steps);
    }
    if (run.contains("monitor_every"))
        c.monitor_every = integer(run["monitor_every"], "monitor_every");
    if (j.contains("output")) {
        const auto &out = j["output"];
        keys(out, {"vtk_fields", "vtk_every", "initial"}, "output");
        if (out.contains("vtk_every"))
            c.vtk_every = integer(out["vtk_every"], "vtk_every", true);
        if (out.contains("initial")) {
            require(out["initial"].is_boolean(), "output.initial must be boolean");
            c.initial_output = out["initial"].get<bool>();
        }
        if (out.contains("vtk_fields")) {
            require(out["vtk_fields"].is_array() && !out["vtk_fields"].empty(), "vtk_fields must be nonempty");
            c.vtk_fields.clear();
            std::set<std::string> unique;
            for (const auto &item : out["vtk_fields"]) {
                auto name = string_value(item, "vtk_fields");
                require(name == "u" || name == "rho" || name == "flags" || name == "p" ||
                            (name == "T" && c.model.temperature) || (name == "phi" && c.model.free_surface),
                        "Unknown or unavailable output field");
                require(unique.insert(name).second, "Duplicate output field");
                c.vtk_fields.push_back(name);
            }
        }
    }
    for (const auto &b : c.boundaries)
        if (b.type == "moving_wall") {
            require(c.pressure_rho == 1 && c.rho == 1, "moving_wall requires lattice density 1");
            for (const auto &r : c.regions)
                require(r.rho == 1, "moving_wall requires lattice density 1");
            for (const auto &e : c.boundaries)
                require(e.rho == 1, "moving_wall requires lattice density 1");
        }
    c.sample_every = c.monitor_every;
    if (j.contains("analysis")) {
        c.analysis = true;
        const auto &a = j["analysis"];
        keys(a, {"every", "start_step", "statistics", "probes", "forces"}, "analysis");
        if (a.contains("every"))
            c.sample_every = integer(a["every"], "analysis.every");
        if (a.contains("start_step"))
            c.sample_start = integer(a["start_step"], "analysis.start_step", true);
        require(c.sample_start <= c.steps, "analysis.start_step exceeds run.steps");
        if (a.contains("statistics")) {
            require(a["statistics"].is_boolean(), "analysis.statistics must be boolean");
            c.statistics = a["statistics"].get<bool>();
        }
        ids.clear();
        if (a.contains("probes")) {
            require(a["probes"].is_array(), "analysis.probes must be an array");
            for (const auto &v : a["probes"]) {
                keys(v, {"id", "position"}, "probe");
                Probe p;
                p.id = string_value(field(v, "id"), "probe.id");
                require(!p.id.empty() && ids.insert(p.id).second, "Empty/duplicate probe ID");
                p.position = vec(field(v, "position"), "probe.position");
                for (int k = 0; k < 3; k++) {
                    double q = (p.position[k] - c.origin[k]) / c.dx;
                    require(q >= 0 && q < c.cells[k], "Probe outside domain: " + p.id);
                    p.cell[k] = static_cast<unsigned>(std::floor(q));
                    p.actual[k] = c.origin[k] + (p.cell[k] + 0.5) * c.dx;
                }
                p.index = p.cell[0] + static_cast<unsigned long long>(c.cells[0]) *
                                          (p.cell[1] + static_cast<unsigned long long>(c.cells[1]) * p.cell[2]);
                c.probes.push_back(p);
            }
        }
        ids.clear();
        if (a.contains("forces")) {
            require(a["forces"].is_array(), "analysis.forces must be an array");
            for (const auto &v : a["forces"]) {
                keys(v, {"id", "target"}, "force target");
                ForceTarget t;
                t.id = string_value(field(v, "id"), "force.id");
                t.target = string_value(field(v, "target"), "force.target");
                require(!t.id.empty() && ids.insert(t.id).second, "Empty/duplicate force ID");
                bool valid = t.target == "all_solids";
                for (const auto &g : c.geometry)
                    valid = valid || t.target == "geometry:" + g.id;
                for (const auto &b : c.boundaries)
                    valid =
                        valid || ((b.type == "no_slip" || b.type == "moving_wall") && t.target == "boundary:" + b.id);
                require(valid, "Unknown or non-solid force target: " + t.target);
                c.forces.push_back(t);
            }
        }
    }
    finite_float(c.reference_density * (c.dx / c.dt) * (c.dx / c.dt), "pressure scale", true);
    finite_float(c.reference_density * std::pow(c.dx, 4) / (c.dt * c.dt), "force scale", true);
    require(std::isfinite(c.steps * c.dt), "Actual duration overflows");
    double umax = 0;
    auto speed = [&](const Vec &v) { return std::hypot(v[0], std::hypot(v[1], v[2])); };
    umax = speed(c.velocity);
    for (const auto &b : c.boundaries)
        umax = std::max(umax, speed(b.velocity));
    for (const auto &r : c.regions)
        umax = std::max(umax, speed(r.velocity));
    require(static_cast<float>(0.5 + 3 * c.nu) > 0.5f,
            "Viscosity is too small to represent a relaxation time above 0.5");
    c.resolved = {{"product", SOLVER_IBM_NAME},
                  {"version", SOLVER_IBM_VERSION_STRING},
                  {"release_status", SOLVER_IBM_RELEASE_STATUS},
                  {"schema_version", 1},
                  {"case", c.name},
                  {"capabilities", capabilities()},
                  {"storage", ddf_storage_name(c.storage)},
                  {"solver", solver_description(c)},
                  {"velocity_set", c.model.q},
                  {"distribution_bytes_per_value", ddf_storage_bytes(c.storage)},
                  {"distribution_buffer_bytes", count * c.model.q * ddf_storage_bytes(c.storage)},
                  {"cells", c.cells},
                  {"dx", c.dx},
                  {"dt", c.dt},
                  {"reference_density", c.reference_density},
                  {"origin", c.origin},
                  {"lattice_nu", c.nu},
                  {"lattice_body_force", c.body_force},
                  {"pressure_reference_lattice_rho", c.pressure_rho},
                  {"initial_lattice_rho", c.rho},
                  {"initial_lattice_velocity", c.velocity},
                  {"tau", 0.5 + 3 * c.nu},
                  {"max_prescribed_mach", umax * std::sqrt(3.0)},
                  {"steps", c.steps},
                  {"actual_duration", c.steps * c.dt},
                  {"device_field_bytes", count * c.device_cell_bytes()},
                  {"host_field_and_union_bytes", count * (c.host_cell_bytes() + 1)},
                  {"actual_domain_length", {c.cells[0] * c.dx, c.cells[1] * c.dx, c.cells[2] * c.dx}}};
    if (c.model.free_surface)
        c.resolved["free_surface"] = {{"lattice_surface_tension", c.surface_tension},
                                       {"environment_pressure", c.environment_pressure},
                                       {"environment_lattice_density", c.environment_lattice_density},
                                       {"initial_liquid_regions", c.liquid_regions.size()}};
    if (c.model.temperature)
        c.resolved["thermal"] = {{"temperature_scale", c.temperature_scale},
                                  {"initial_lattice_temperature", c.initial_temperature},
                                  {"lattice_diffusivity", c.thermal_diffusivity},
                                  {"lattice_expansion", c.thermal_expansion},
                                  {"lattice_gravity_force_density", c.model.gravity},
                                  {"turbulent_prandtl", c.turbulent_prandtl}};
    if (c.analysis) {
        c.resolved["analysis"] = {{"every", c.sample_every},
                                  {"start_step", c.sample_start},
                                  {"statistics", c.statistics},
                                  {"units", c.si ? "SI: m,s,kg,kg/m^3,m/s,Pa,J,N" : "lattice"},
                                  {"pressure_reference", "fluid.rho"}};
        c.resolved["analysis"]["probes"] = Json::array();
        for (const auto &p : c.probes)
            c.resolved["analysis"]["probes"].push_back(
                {{"id", p.id}, {"requested", p.position}, {"actual", p.actual}, {"cell", p.cell}});
    }
    return c;
}
} // namespace fxconfig
