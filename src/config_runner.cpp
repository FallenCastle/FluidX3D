#include "config.hpp"
#include "config_analysis.hpp"
#include "info.hpp"
#include "lbm.hpp"
#include "version.hpp"
#include <cstring>
#include <iomanip>
#include <memory>
#include <set>
#include <sstream>
#if !defined(D3Q19) || !defined(SRT) || !defined(FP16S) || !defined(SUBGRID) || !defined(EQUILIBRIUM_BOUNDARIES) ||    \
    defined(GRAPHICS) || defined(TRT) || defined(D3Q27) || defined(D3Q15) || defined(D2Q9) || defined(FP16C) ||        \
    !defined(VOLUME_FORCE) || !defined(FORCE_FIELD) || !defined(SURFACE) || !defined(TEMPERATURE) ||                   \
    defined(PARTICLES) || !defined(MOVING_BOUNDARIES) || defined(BENCHMARK)
#error The configuration runner requires its documented fixed headless solver profile.
#endif
#ifdef _WIN32
#include <shellapi.h>
#endif

namespace fxconfig {
static float3 f3(const Vec &v) {
    return float3(static_cast<float>(v[0]), static_cast<float>(v[1]), static_cast<float>(v[2]));
}
static Vec point(const Config &c, unsigned x, unsigned y, unsigned z) {
    return {c.origin[0] + (x + 0.5) * c.dx, c.origin[1] + (y + 0.5) * c.dx, c.origin[2] + (z + 0.5) * c.dx};
}
static bool same(const Boundary &a, const Boundary &b) {
    return a.type == b.type && a.contact_angle == b.contact_angle &&
           (a.type == "no_slip" || (a.rho == b.rho && a.velocity == b.velocity));
}
static int boundary_at(const Config &c, unsigned x, unsigned y, unsigned z) {
    unsigned xyz[3]{x, y, z};
    auto p = point(c, x, y, z);
    std::vector<int> candidates;
    for (int face = 0; face < 6; face++) {
        int axis = face / 2;
        if (c.periodic[axis] || xyz[axis] != (face % 2 ? c.cells[axis] - 1 : 0))
            continue;
        bool covered = false;
        for (size_t i = 0; i < c.boundaries.size(); i++) {
            const auto &b = c.boundaries[i];
            if (b.type == "periodic" || std::find(b.faces.begin(), b.faces.end(), face) == b.faces.end())
                continue;
            if (b.region) {
                bool matches = true;
                int k = 0;
                for (int a = 0; a < 3; a++)
                    if (a != axis) {
                        matches = matches && p[a] >= b.lower[k] && p[a] <= b.upper[k];
                        k++;
                    }
                if (!matches)
                    continue;
            }
            covered = true;
            candidates.push_back(static_cast<int>(i));
        }
        require(covered, "Uncovered boundary face at cell " + std::to_string(x) + "," + std::to_string(y) + "," +
                             std::to_string(z));
    }
    if (candidates.empty())
        return -1;
    int winner = candidates.front();
    for (int i : candidates)
        if (c.boundaries[i].priority > c.boundaries[winner].priority)
            winner = i;
    for (int i : candidates)
        if (c.boundaries[i].priority == c.boundaries[winner].priority)
            require(same(c.boundaries[i], c.boundaries[winner]),
                    "Conflicting boundaries: " + c.boundaries[i].id + " / " + c.boundaries[winner].id);
    return winner;
}
static void validate_faces(const Config &c) {
    // Traverse surfaces only; do not allocate a volume grid for --validate.
    for (unsigned z = 0; z < c.cells[2]; z++)
        for (unsigned y = 0; y < c.cells[1]; y++) {
            boundary_at(c, 0, y, z);
            boundary_at(c, c.cells[0] - 1, y, z);
        }
    for (unsigned z = 0; z < c.cells[2]; z++)
        for (unsigned x = 1; x + 1 < c.cells[0]; x++) {
            boundary_at(c, x, 0, z);
            boundary_at(c, x, c.cells[1] - 1, z);
        }
    for (unsigned y = 1; y + 1 < c.cells[1]; y++)
        for (unsigned x = 1; x + 1 < c.cells[0]; x++) {
            boundary_at(c, x, y, 0);
            boundary_at(c, x, y, c.cells[2] - 1);
        }
}
static std::unique_ptr<Mesh> mesh(const Config &c, const Geometry &g) {
    std::ifstream in(g.file, std::ios::binary);
    require(bool(in), "Cannot read STL " + g.file.u8string());
    auto bytes = fs::file_size(g.file);
    require(bytes >= 84, "Truncated STL: " + g.id);
    char header[84];
    in.read(header, 84);
    uint32_t triangles = 0;
    std::memcpy(&triangles, header + 80, 4);
    require(triangles > 0 && bytes == 84ull + 50ull * triangles, "Only valid binary STL is supported: " + g.id);
    auto m = std::make_unique<Mesh>(triangles, float3(0));
    float3x3 rotation(f3(g.axis), radians(static_cast<float>(std::remainder(g.degrees, 360.0))));
    for (uint32_t i = 0; i < triangles; i++) {
        char record[50];
        in.read(record, 50);
        require(bool(in), "STL read failure: " + g.id);
        for (int vertex = 0; vertex < 3; vertex++) {
            float v[3];
            std::memcpy(v, record + 12 + vertex * 12, 12);
            for (float value : v)
                require(std::isfinite(value), "Non-finite STL vertex: " + g.id);
            float3 p(v[0], v[1], v[2]);
            if (g.mode == "fit")
                p = rotation * p;
            else {
                // Subtract world origins in double precision before converting to native float coordinates.
                double x = (v[0] - g.pivot[0]) * (g.factor / c.dx);
                double y = (v[1] - g.pivot[1]) * (g.factor / c.dx);
                double z = (v[2] - g.pivot[2]) * (g.factor / c.dx);
                p = float3(static_cast<float>((g.translation[0] - c.origin[0]) / c.dx + rotation.xx * x +
                                              rotation.xy * y + rotation.xz * z - 0.5),
                           static_cast<float>((g.translation[1] - c.origin[1]) / c.dx + rotation.yx * x +
                                              rotation.yy * y + rotation.yz * z - 0.5),
                           static_cast<float>((g.translation[2] - c.origin[2]) / c.dx + rotation.zx * x +
                                              rotation.zy * y + rotation.zz * z - 0.5));
            }
            require(std::isfinite(p.x) && std::isfinite(p.y) && std::isfinite(p.z), "Invalid transformed STL: " + g.id);
            (vertex == 0 ? m->p0 : vertex == 1 ? m->p1 : m->p2)[i] = p;
        }
    }
    auto bounds = [&]() {
        m->pmin = m->pmax = m->p0[0];
        for (uint32_t i = 0; i < triangles; i++)
            for (auto vertices : {m->p0, m->p1, m->p2}) {
                auto p = vertices[i];
                m->pmin = float3(std::min(m->pmin.x, p.x), std::min(m->pmin.y, p.y), std::min(m->pmin.z, p.z));
                m->pmax = float3(std::max(m->pmax.x, p.x), std::max(m->pmax.y, p.y), std::max(m->pmax.z, p.z));
            }
    };
    bounds();
    require(m->get_max_size() > 0, "Zero-size STL: " + g.id);
    const float scale = g.mode == "fit" ? static_cast<float>(g.size / c.dx) / m->get_max_size() : 1.0f;
    const float3 offset = g.mode == "fit" ? -0.5f * (m->pmin + m->pmax) : float3(0.0f);
    Vec target{};
    if (g.mode == "fit")
        for (int a = 0; a < 3; a++)
            target[a] = (g.center[a] - c.origin[a]) / c.dx - 0.5;
    const float3 translation = g.mode == "fit" ? f3(target) : float3(0.0f);
    for (uint32_t i = 0; i < triangles; i++)
        for (auto points : {m->p0, m->p1, m->p2}) {
            points[i] = translation + scale * (offset + points[i]);
            require(std::isfinite(points[i].x) && std::isfinite(points[i].y) && std::isfinite(points[i].z),
                    "Non-finite transformed STL: " + g.id);
        }
    bounds();
    for (int a = 0; a < 3; a++) {
        float lo = a == 0 ? m->pmin.x : a == 1 ? m->pmin.y : m->pmin.z;
        float hi = a == 0 ? m->pmax.x : a == 1 ? m->pmax.y : m->pmax.z;
        require(std::isfinite(lo) && std::isfinite(hi) && lo >= -0.5001f && hi <= c.cells[a] - 0.4999f,
                "STL outside domain or invalid transformed coordinates: " + g.id);
    }
    return m;
}
static Json inspect_meshes(const Config &c) {
    Json list = Json::array();
    for (const auto &g : c.geometry) {
        auto m = mesh(c, g);
        list.push_back(
            {{"id", g.id},
             {"triangles", m->triangle_number},
             {"file_bytes", fs::file_size(g.file)},
             {"native_index_bounds", {{m->pmin.x, m->pmin.y, m->pmin.z}, {m->pmax.x, m->pmax.y, m->pmax.z}}}});
    }
    return list;
}
static std::string stamp(unsigned long long t) {
    std::ostringstream s;
    s << std::setw(9) << std::setfill('0') << t;
    return s.str();
}
static void vtk(LBM &lbm, const Config &c, const fs::path &output, const std::string &fieldname) {
    unsigned dim = fieldname == "u" ? 3 : 1;
    bool bytes = fieldname == "flags" || fieldname == "material";
    fs::path filename = output / (fieldname + "-" + stamp(lbm.get_t()) + ".vtk");
    std::ofstream file(filename, std::ios::binary);
    require(bool(file), "Cannot write VTK");
    file << std::setprecision(17)
         << "# vtk DataFile Version 3.0\n" SOLVER_IBM_NAME " " SOLVER_IBM_VERSION_STRING
            " (based on " SOLVER_IBM_UPSTREAM_NAME " " SOLVER_IBM_UPSTREAM_VERSION
            ")\nBINARY\nDATASET STRUCTURED_POINTS\nDIMENSIONS "
         << c.cells[0] << ' ' << c.cells[1] << ' ' << c.cells[2] << "\nORIGIN " << c.origin[0] + .5 * c.dx << ' '
         << c.origin[1] + .5 * c.dx << ' ' << c.origin[2] + .5 * c.dx << "\nSPACING " << c.dx << ' ' << c.dx << ' '
         << c.dx << "\nPOINT_DATA " << lbm.get_N() << "\nSCALARS " << fieldname << ' '
         << (bytes ? "unsigned_char" : "float") << ' ' << dim << "\nLOOKUP_TABLE default\n";
    std::vector<char> block;
    block.reserve(65536);
    for (ulong n = 0; n < lbm.get_N(); n++)
        for (unsigned a = 0; a < dim; a++) {
            if (bytes)
                block.push_back(static_cast<char>(fieldname == "flags" ? lbm.flags[n]
                                                                        : lbm.lbm_domain[0]->material[n]));
            else {
                float value = fieldname == "rho"
                                  ? lbm.rho[n] * static_cast<float>(c.reference_density)
                                  : fieldname == "T"
                                        ? lbm.T[n] * static_cast<float>(c.temperature_scale)
                                        : fieldname == "phi"
                                              ? lbm.phi[n]
                                              : lbm.u[n + static_cast<ulong>(a) * lbm.get_N()] *
                                                    static_cast<float>(c.dx / c.dt);
                if (fieldname == "p")
                    value = static_cast<float>(pressure(c, lbm.rho[n]));
                require(std::isfinite(value), "Non-finite VTK value");
                uint32_t bits;
                std::memcpy(&bits, &value, 4);
                block.push_back(static_cast<char>(bits >> 24));
                block.push_back(static_cast<char>(bits >> 16));
                block.push_back(static_cast<char>(bits >> 8));
                block.push_back(static_cast<char>(bits));
            }
            if (block.size() >= 65536) {
                file.write(block.data(), block.size());
                block.clear();
            }
        }
    if (!block.empty())
        file.write(block.data(), block.size());
    file.close();
    require(bool(file), "VTK write failed: " + filename.u8string());
}
static void sync(LBM &lbm) {
    lbm.rho.read_from_device();
    lbm.u.read_from_device();
    lbm.flags.read_from_device();
    if (lbm.get_model().free_surface)
        lbm.phi.read_from_device();
    if (lbm.get_model().temperature)
        lbm.T.read_from_device();
}
struct BoundaryFluxLink {
    ulong cell = 0;
    Vec outward_normal{};
};
struct BoundaryFluxSurface {
    std::string id, type;
    std::vector<BoundaryFluxLink> links;
};
static std::string quote_csv_field(const std::string &value) {
    std::string out = "\"";
    for (char c : value) {
        out.push_back(c);
        if (c == '"')
            out.push_back(c);
    }
    return out + '"';
}
static void monitor(LBM &lbm, const Config &c, std::ofstream &file,
                    const std::vector<BoundaryFluxSurface> &flux_surfaces, std::ofstream *flux_file) {
    double mass = 0, umax = 0, rmin = std::numeric_limits<double>::infinity(), rmax = 0;
    double tmin = std::numeric_limits<double>::infinity(), tmax = -std::numeric_limits<double>::infinity(), energy = 0;
    ulong count = 0;
    for (ulong n = 0; n < lbm.get_N(); n++)
        if (!is_solid(lbm.flags[n]) &&
            (!c.model.free_surface || (lbm.flags[n] & (TYPE_F | TYPE_I)))) {
            double rho = lbm.rho[n], x = lbm.u.x[n], y = lbm.u.y[n], z = lbm.u.z[n];
            require(std::isfinite(rho) && rho > 0 && std::isfinite(x) && std::isfinite(y) && std::isfinite(z),
                    "Non-finite velocity or non-positive density at step " + std::to_string(lbm.get_t()));
            mass += rho * (c.model.free_surface ? lbm.phi[n] : 1.0);
            rmin = std::min(rmin, rho);
            rmax = std::max(rmax, rho);
            umax = std::max(umax, std::sqrt(x * x + y * y + z * z));
            count++;
        }
    if (c.model.temperature) {
        auto *domain = lbm.lbm_domain[0];
        for (ulong n = 0; n < lbm.get_N(); n++)
            if (domain->material[n] != 255u && (!c.model.free_surface || (lbm.flags[n] & (TYPE_F | TYPE_I)) ||
                                                                           domain->material[n] != 0u)) {
                const double temperature = lbm.T[n];
                require(std::isfinite(temperature), "Non-finite temperature at step " + std::to_string(lbm.get_t()));
                tmin = std::min(tmin, temperature);
                tmax = std::max(tmax, temperature);
                energy += domain->thermal_capacity[n] * temperature;
            }
        require(std::isfinite(tmin) && std::isfinite(tmax), "No active thermal cells remain");
    }
    require(count > 0, "No fluid cells remain");
    file << std::setprecision(17) << lbm.get_t() << ',' << lbm.get_t() * c.dt << ',' << count << ',' << mass << ','
         << rmin << ',' << rmax << ',' << umax;
    if (c.model.temperature)
        file << ',' << tmin << ',' << tmax << ',' << energy;
    file << '\n';
    file.flush();
    require(bool(file), "Monitor write failed");
    if (flux_file) {
        for (const auto &surface : flux_surfaces) {
            double mass_flow = 0, enthalpy_flow = 0;
            for (const auto &link : surface.links) {
                const ulong n = link.cell;
                if (is_solid(lbm.flags[n]) || !(lbm.flags[n] & (TYPE_F | TYPE_I)))
                    continue;
                const double normal_velocity = lbm.u.x[n] * link.outward_normal[0] +
                                               lbm.u.y[n] * link.outward_normal[1] +
                                               lbm.u.z[n] * link.outward_normal[2];
                const double cell_mass_flow = lbm.rho[n] * lbm.phi[n] * normal_velocity;
                mass_flow += cell_mass_flow;
                if (c.model.temperature)
                    enthalpy_flow += cell_mass_flow * lbm.T[n];
            }
            *flux_file << std::setprecision(17) << lbm.get_t() << ',' << lbm.get_t() * c.dt << ','
                       << quote_csv_field(surface.id) << ',' << surface.type << ',' << mass_flow;
            if (c.model.temperature)
                *flux_file << ',' << enthalpy_flow;
            *flux_file << '\n';
        }
        flux_file->flush();
        require(bool(*flux_file), "Boundary flux monitor write failed");
    }
    std::cout << "Step " << lbm.get_t() << "/" << c.steps << "; lattice rho=[" << rmin << "," << rmax
              << "]; max speed=" << umax << std::endl;
}
static void solve(Config &c, const fs::path &output, int device, bool prepare) {
    const auto devices = get_devices(false); // verify the explicit device instead of silently falling back
    if (device >= 0) {
        bool found = false;
        for (const auto &d : devices)
            found = found || static_cast<int>(d.id) == device;
        require(found, "Requested OpenCL device not found");
        main_arguments = {std::to_string(device)};
    } else {
        device = static_cast<int>(select_device_with_most_flops(devices).id);
        main_arguments = {std::to_string(device)};
    }
    auto selected = select_device_with_id(static_cast<uint>(device), devices);
    unsigned long long count = static_cast<unsigned long long>(c.cells[0]) * c.cells[1] * c.cells[2], mesh_bytes = 0;
    for (const auto &g : c.geometry)
        mesh_bytes = std::max(mesh_bytes, (fs::file_size(g.file) - 84) / 50 * 36ull);
    require(count * c.device_cell_bytes() + mesh_bytes + 64 <=
                static_cast<unsigned long long>(selected.memory) * 1048576,
            "Estimated device memory exceeds selected device capacity");
    require(count * c.model.q * ddf_storage_bytes(c.storage) <=
                static_cast<unsigned long long>(selected.max_global_buffer) * 1048576,
            "Distribution buffer exceeds selected device allocation limit");
    c.resolved["estimated_device_peak_bytes"] = count * c.device_cell_bytes() + mesh_bytes + 64;
    c.resolved["estimated_host_fields_union_and_mesh_bytes"] = count * (c.host_cell_bytes() + 1) + mesh_bytes;
    LBM lbm(c.cells[0], c.cells[1], c.cells[2], 1u, 1u, 1u, static_cast<float>(c.nu),
            static_cast<float>(c.body_force[0]), static_cast<float>(c.body_force[1]),
            static_cast<float>(c.body_force[2]), static_cast<float>(c.surface_tension),
            static_cast<float>(c.thermal_diffusivity), static_cast<float>(c.thermal_expansion), 0u, 1.0f, c.storage,
            c.model);
    const auto actual_capacity = lbm.lbm_domain[0]->get_distribution_capacity();
    require(actual_capacity == count * c.model.q * ddf_storage_bytes(c.storage),
            "DDF allocation does not match requested storage");
    c.resolved["actual_distribution_buffer_bytes"] = actual_capacity;
    c.resolved["device_id"] = lbm.lbm_domain[0]->get_device().info.id;
    c.resolved["device_name"] = lbm.lbm_domain[0]->get_device().info.name;
    c.resolved["device_driver"] = lbm.lbm_domain[0]->get_device().info.driver_version;
    std::vector<uchar> solid(static_cast<size_t>(lbm.get_N()), 0);
    std::vector<std::vector<ulong>> force_groups(c.forces.size());
    std::vector<int> owner;
    bool need_owner = (c.model.temperature || c.model.free_surface) && !c.geometry.empty();
    for (const auto &f : c.forces)
        need_owner = need_owner || f.target.rfind("geometry:", 0) == 0;
    if (need_owner)
        owner.assign(static_cast<size_t>(lbm.get_N()), -1);
    Json geometries = Json::array();
    for (const auto &g : c.geometry) {
        for (ulong n = 0; n < lbm.get_N(); n++)
            lbm.flags[n] = 0;
        lbm.flags.write_to_device();
        auto m = mesh(c, g);
        lbm.voxelize_mesh_on_device(m.get(), TYPE_S);
        ulong count = 0;
        for (ulong n = 0; n < lbm.get_N(); n++)
            if (lbm.flags[n] & TYPE_S) {
                solid[static_cast<size_t>(n)] = TYPE_S;
                if (need_owner) {
                    int &o = owner[static_cast<size_t>(n)];
                    int id = static_cast<int>(&g - c.geometry.data());
                    if (o != -1) {
                        require(!c.model.temperature, "Thermal geometries overlap: " + g.id);
                        require(!c.model.free_surface, "Free-surface geometries overlap: " + g.id);
                        for (const auto &f : c.forces)
                            require(f.target != "geometry:" + g.id &&
                                        (o < 0 || f.target != "geometry:" + c.geometry[o].id),
                                    "Overlapping geometry force target: " + g.id);
                        o = -2;
                    } else
                        o = id;
                }
                count++;
            }
        require(count > 0, "STL voxelized to zero solid cells: " + g.id);
        geometries.push_back({{"id", g.id},
                              {"solid_cells", count},
                              {"material", g.material.empty() ? Json(nullptr) : Json(g.material)},
                              {"contact_angle_degrees", c.model.free_surface ? Json(g.contact_angle) : Json(nullptr)}});
    }
    std::vector<unsigned long long> coverage(c.boundaries.size(), 0);
    std::vector<BoundaryFluxSurface> flux_surfaces;
    std::vector<int> flux_surface_for_boundary(c.boundaries.size(), -1);
    for (size_t i = 0; i < c.boundaries.size(); i++)
        if (c.boundaries[i].type == "liquid_inlet" || c.boundaries[i].type == "open_outlet") {
            flux_surface_for_boundary[i] = static_cast<int>(flux_surfaces.size());
            flux_surfaces.push_back({c.boundaries[i].id, c.boundaries[i].type, {}});
        }
    ulong solid_count = 0;
    for (ulong n = 0; n < lbm.get_N(); n++) {
        uint x, y, z;
        lbm.coordinates(n, x, y, z);
        auto p = point(c, x, y, z);
        double rho = c.rho;
        Vec velocity = c.velocity;
        double temperature = c.initial_temperature;
        bool temperature_override = false;
        for (const auto &r : c.regions)
            if (p[0] >= r.lower[0] && p[0] <= r.upper[0] && p[1] >= r.lower[1] && p[1] <= r.upper[1] &&
                p[2] >= r.lower[2] && p[2] <= r.upper[2]) {
                rho = r.rho;
                velocity = r.velocity;
                if (r.has_temperature)
                    temperature = r.temperature;
                temperature_override = temperature_override || r.has_temperature;
            }
        lbm.flags[n] = solid[static_cast<size_t>(n)];
        int b = boundary_at(c, x, y, z);
        if (b >= 0) {
            const auto &rule = c.boundaries[b];
            coverage[b]++;
            if (flux_surface_for_boundary[static_cast<size_t>(b)] >= 0) {
                const unsigned xyz[3]{x, y, z};
                for (int face : rule.faces) {
                    const int axis = face / 2;
                    if (xyz[axis] != (face % 2 ? c.cells[axis] - 1 : 0))
                        continue;
                    bool in_region = true;
                    if (rule.region) {
                        int k = 0;
                        for (int a = 0; a < 3; a++)
                            if (a != axis) {
                                in_region = in_region && p[a] >= rule.lower[k] && p[a] <= rule.upper[k];
                                k++;
                            }
                    }
                    if (in_region) {
                        Vec normal{};
                        normal[axis] = face % 2 ? 1.0 : -1.0;
                        flux_surfaces[static_cast<size_t>(flux_surface_for_boundary[static_cast<size_t>(b)])]
                            .links.push_back({n, normal});
                    }
                }
            }
            if (rule.type == "no_slip" || rule.type == "moving_wall") {
                require(rule.type != "moving_wall" || !solid[static_cast<size_t>(n)],
                        "Geometry intersects moving_wall: " + rule.id);
                if (need_owner && owner[static_cast<size_t>(n)] >= 0)
                    for (const auto &f : c.forces)
                        require(f.target != "geometry:" + c.geometry[owner[static_cast<size_t>(n)]].id,
                                "Geometry force target touches domain wall");
                lbm.flags[n] = TYPE_S;
                velocity = rule.velocity;
            } else {
                require(!(lbm.flags[n] & TYPE_S), "Geometry intersects open boundary: " + rule.id);
                lbm.flags[n] = TYPE_E;
                if (rule.type == "liquid_inlet")
                    lbm.flags[n] = static_cast<uchar>(lbm.flags[n] | TYPE_X);
                else if (rule.type == "open_outlet")
                    lbm.flags[n] = static_cast<uchar>(lbm.flags[n] | TYPE_Y);
                rho = rule.rho;
                velocity = rule.velocity;
            }
        }
        if (lbm.flags[n] & TYPE_S) {
            if (b < 0 || c.boundaries[b].type != "moving_wall")
                velocity = {0, 0, 0};
            solid_count++;
            for (size_t i = 0; i < c.forces.size(); i++) {
                const auto &target = c.forces[i].target;
                bool matches = target == "all_solids" || (b >= 0 && target == "boundary:" + c.boundaries[b].id);
                if (need_owner && owner[static_cast<size_t>(n)] >= 0)
                    matches = matches || target == "geometry:" + c.geometry[owner[static_cast<size_t>(n)]].id;
                if (matches)
                    force_groups[i].push_back(n);
            }
        }
        if (c.model.free_surface && (lbm.flags[n] & TYPE_S)) {
            double angle = 90.0;
            const int geometry_owner = owner.empty() ? -1 : owner[static_cast<size_t>(n)];
            if (geometry_owner >= 0)
                angle = c.geometry[static_cast<size_t>(geometry_owner)].contact_angle;
            if (b >= 0 && (c.boundaries[b].type == "no_slip" || c.boundaries[b].type == "moving_wall"))
                angle = c.boundaries[b].contact_angle;
            lbm.lbm_domain[0]->contact_angle[n] = static_cast<float>(angle * 0.017453292519943295769);
        }
        if (c.model.free_surface && !(lbm.flags[n] & TYPE_S)) {
            double fill = 0;
            for (const auto &r : c.liquid_regions)
                if ((r.shape == "box" && p[0] >= r.lower[0] && p[0] <= r.upper[0] && p[1] >= r.lower[1] &&
                     p[1] <= r.upper[1] && p[2] >= r.lower[2] && p[2] <= r.upper[2]) ||
                    (r.shape == "sphere" &&
                     (p[0] - r.center[0]) * (p[0] - r.center[0]) +
                             (p[1] - r.center[1]) * (p[1] - r.center[1]) +
                             (p[2] - r.center[2]) * (p[2] - r.center[2]) <=
                         r.radius * r.radius))
                    fill = std::max(fill, r.fill);
            if (b >= 0 && c.boundaries[b].type == "liquid_inlet")
                fill = 1.0;
            lbm.flags[n] = static_cast<uchar>((lbm.flags[n] & ~(TYPE_F | TYPE_I | TYPE_G)) |
                                               (fill >= 1 ? TYPE_F : fill > 0 ? TYPE_I : TYPE_G));
            lbm.phi[n] = static_cast<float>(fill);
        }
        lbm.rho[n] = static_cast<float>(rho);
        lbm.u.x[n] = static_cast<float>(velocity[0]);
        lbm.u.y[n] = static_cast<float>(velocity[1]);
        lbm.u.z[n] = static_cast<float>(velocity[2]);
        if (c.model.temperature)
            lbm.T[n] = static_cast<float>(temperature);
        if (c.model.temperature) {
            auto *domain = lbm.lbm_domain[0];
            const bool external_solid = b >= 0 &&
                                        (c.boundaries[b].type == "no_slip" || c.boundaries[b].type == "moving_wall");
            const int geometry_owner = owner.empty() ? -1 : owner[static_cast<size_t>(n)];
            if (geometry_owner >= 0) {
                const auto &geometry = c.geometry[static_cast<size_t>(geometry_owner)];
                const auto &material = c.thermal_materials[static_cast<size_t>(geometry.material_index - 1)];
                domain->thermal_capacity[n] = static_cast<float>(material.capacity_lattice);
                domain->thermal_conductivity[n] = static_cast<float>(material.conductivity_lattice);
                domain->thermal_source[n] = static_cast<float>(material.source_lattice);
                domain->material[n] = static_cast<uchar>(geometry.material_index);
                if (!temperature_override) {
                    temperature = material.initial_temperature;
                    lbm.T[n] = static_cast<float>(temperature);
                }
            } else {
                domain->thermal_capacity[n] = 1.0f;
                domain->thermal_conductivity[n] = static_cast<float>(c.thermal_diffusivity);
                domain->thermal_source[n] = 0.0f;
                domain->material[n] = external_solid ? 255u : 0u;
            }
            uchar thermal_type = 0u;
            if (b >= 0 && c.boundaries[b].thermal) {
                const auto &type = c.boundaries[b].thermal_type;
                thermal_type = type == "fixed_temperature" ? 1u : type == "heat_flux" ? 2u :
                               type == "convection" ? 3u : 0u;
            }
            domain->thermal_boundary_type[n] = thermal_type;
            domain->thermal_boundary_value[n] =
                b >= 0 && c.boundaries[b].thermal ? static_cast<float>(c.boundaries[b].thermal_value)
                                                  : static_cast<float>(temperature);
            domain->thermal_boundary_coefficient[n] =
                b >= 0 && c.boundaries[b].thermal ? static_cast<float>(c.boundaries[b].thermal_coefficient) : 0.0f;
            if (thermal_type == 1u) {
                lbm.T[n] = domain->thermal_boundary_value[n];
                lbm.flags[n] = static_cast<uchar>(lbm.flags[n] | TYPE_T);
            }
        }
    }
    c.resolved["geometry"] = geometries;
    c.resolved["solid_cells"] = solid_count;
    for (size_t i = 0; i < c.boundaries.size(); i++)
        c.resolved["boundary_coverage"].push_back({{"id", c.boundaries[i].id}, {"winning_cells", coverage[i]}});
    for (const auto &surface : flux_surfaces) {
        require(!surface.links.empty(), "Open free-surface boundary has no active face links: " + surface.id);
        c.resolved["boundary_flux_surfaces"].push_back(
            {{"id", surface.id}, {"type", surface.type}, {"face_links", surface.links.size()}});
    }
    unsigned long long group_bytes = 0;
    for (size_t i = 0; i < force_groups.size(); i++) {
        require(!force_groups[i].empty(), "Empty force target: " + c.forces[i].id);
        group_bytes += force_groups[i].capacity() * sizeof(ulong);
        c.resolved["analysis"]["forces"].push_back(
            {{"id", c.forces[i].id}, {"target", c.forces[i].target}, {"solid_cells", force_groups[i].size()}});
    }
    for (const auto &p : c.probes)
        require(!is_solid(lbm.flags[p.index]), "Probe is inside solid: " + p.id);
    c.resolved["force_group_host_bytes"] = group_bytes;
    c.resolved["geometry_owner_peak_host_bytes"] = owner.capacity() * sizeof(int);
    std::vector<int>().swap(owner);
    save_json(output / "resolved-config.json", c.resolved);
    units.set_m_kg_s(static_cast<float>(c.dx), static_cast<float>(c.reference_density * c.dx * c.dx * c.dx),
                     static_cast<float>(c.dt));
    lbm.run(0, c.steps);
    sync(lbm);
    std::ofstream stats(output / "monitor.csv", std::ios::binary);
    require(bool(stats), "Cannot create monitor.csv");
    stats << "step,time,fluid_cells,mass_lattice,rho_min_lattice,rho_max_lattice,speed_max_lattice";
    if (c.model.temperature)
        stats << ",temperature_min_lattice,temperature_max_lattice,sensible_energy_lattice";
    stats << '\n';
    std::ofstream flux;
    std::ofstream *flux_file = nullptr;
    if (!flux_surfaces.empty()) {
        flux.open(output / "boundary-flux.csv", std::ios::binary);
        require(bool(flux), "Cannot create boundary-flux.csv");
        flux << "step,time,boundary_id,boundary_type,mass_flow_outward_lattice";
        if (c.model.temperature)
            flux << ",sensible_enthalpy_flow_outward_lattice";
        flux << '\n';
        flux_file = &flux;
    }
    monitor(lbm, c, stats, flux_surfaces, flux_file);
    Analysis analysis(c, output, std::move(force_groups));
    auto next_sample = c.sample_start;
    if (!prepare && c.analysis && next_sample == 0) {
        analysis.sample(lbm);
        next_sample = c.sample_every;
    }
    if (prepare || c.initial_output) {
        for (const auto &name : c.vtk_fields)
            vtk(lbm, c, output, name);
        if (prepare && std::find(c.vtk_fields.begin(), c.vtk_fields.end(), "flags") == c.vtk_fields.end())
            vtk(lbm, c, output, "flags");
    }
    auto next_monitor = c.monitor_every, next_vtk = c.vtk_every;
    ulong last_output = 0;
    while (!prepare && lbm.get_t() < c.steps) {
        auto next = std::min(c.steps, next_monitor);
        if (c.analysis)
            next = std::min(next, next_sample);
        if (c.vtk_every)
            next = std::min(next, next_vtk);
        lbm.run(next - lbm.get_t(), c.steps);
        sync(lbm);
        if (c.analysis && next == next_sample) {
            analysis.sample(lbm);
            next_sample = next + c.sample_every; // both <= 2^53; sum fits uint64
        }
        if (next == next_monitor || next == c.steps) {
            monitor(lbm, c, stats, flux_surfaces, flux_file);
            next_monitor = next > c.steps - std::min(c.monitor_every, c.steps) ? c.steps : next + c.monitor_every;
        }
        if ((c.vtk_every && next == next_vtk) || next == c.steps) {
            for (const auto &name : c.vtk_fields)
                vtk(lbm, c, output, name);
            last_output = next;
            if (c.vtk_every)
                next_vtk = next > c.steps - std::min(c.vtk_every, c.steps) ? c.steps : next + c.vtk_every;
        }
    }
    (void)last_output;
    analysis.finish();
    std::ofstream status(output / "status.txt", std::ios::binary);
    status << SOLVER_IBM_NAME " " SOLVER_IBM_VERSION_STRING "\nBased on " SOLVER_IBM_UPSTREAM_NAME " "
              SOLVER_IBM_UPSTREAM_VERSION "\nCase = " << c.name << "\nSteps = " << lbm.get_t()
           << "\nRequested steps = " << c.steps << "\nLattice viscosity = " << std::setprecision(17) << c.nu
           << "\nTime per step = " << c.dt << "\nStorage = " << ddf_storage_name(c.storage)
           << "\nSolver = " << solver_description(c).dump() << "\n";
    status.close();
    require(bool(status), "Cannot write status report");
    save_json(output / "completion.json", {{"product", SOLVER_IBM_NAME},
                                           {"version", SOLVER_IBM_VERSION_STRING},
                                           {"release_status", SOLVER_IBM_RELEASE_STATUS},
                                           {"status", prepare ? "prepared" : "succeeded"},
                                           {"storage", ddf_storage_name(c.storage)},
                                           {"solver", solver_description(c)},
                                           {"steps", lbm.get_t()},
                                           {"requested_steps", c.steps},
                                           {"actual_time", lbm.get_t() * c.dt}});
}
static std::vector<std::string> arguments(int argc, char *argv[]) {
    std::vector<std::string> out;
#ifdef _WIN32
    int count = 0;
    LPWSTR *wide = CommandLineToArgvW(GetCommandLineW(), &count);
    require(wide != nullptr, "Cannot read command line");
    for (int i = 1; i < count; i++) {
        int n = WideCharToMultiByte(CP_UTF8, 0, wide[i], -1, nullptr, 0, nullptr, nullptr);
        std::string s(static_cast<size_t>(n), 0);
        WideCharToMultiByte(CP_UTF8, 0, wide[i], -1, &s[0], n, nullptr, nullptr);
        s.pop_back();
        out.push_back(s);
    }
    LocalFree(wide);
#else
    for (int i = 1; i < argc; i++)
        out.emplace_back(argv[i]);
#endif
    return out;
}
int entry(int argc, char *argv[]) {
    console_batch_mode = true;
    fs::path output;
    bool owns_output = false;
    try {
        auto args = arguments(argc, argv);
        fs::path config_path;
        int device = -1;
        bool validate = false, prepare = false;
        std::set<std::string> seen;
        if (args.empty() || (args.size() == 1 && args[0] == "--help")) {
            std::cout << SOLVER_IBM_NAME " " SOLVER_IBM_VERSION_STRING "\n"
                         SOLVER_IBM_EXECUTABLE " --config FILE [--device ID] [--output DIR] [--validate | "
                         "--prepare-only]\n" SOLVER_IBM_EXECUTABLE
                         " --capabilities | --list-devices | --version | --help\n"
                         "Based on " SOLVER_IBM_UPSTREAM_NAME " " SOLVER_IBM_UPSTREAM_VERSION "; "
                         SOLVER_IBM_UPSTREAM_CREDIT ".\n";
            return 0;
        }
        if (args.size() == 1 && args[0] == "--version") {
            std::cout << SOLVER_IBM_NAME " " SOLVER_IBM_VERSION_STRING "\n";
            return 0;
        }
        if (args.size() == 1 && args[0] == "--capabilities") {
            std::cout << capabilities().dump(2) << std::endl;
            return 0;
        }
        if (args.size() == 1 && args[0] == "--list-devices") {
            get_devices();
            return 0;
        }
        for (size_t i = 0; i < args.size(); i++) {
            const auto &arg = args[i];
            require(seen.insert(arg).second, "Repeated command option: " + arg);
            if (arg == "--validate")
                validate = true;
            else if (arg == "--prepare-only")
                prepare = true;
            else {
                require(arg == "--config" || arg == "--device" || arg == "--output", "Unknown command option: " + arg);
                require(i + 1 < args.size(), "Missing value for " + arg);
                auto value = args[++i];
                if (arg == "--config")
                    config_path = fs::u8path(value);
                else if (arg == "--output")
                    output = fs::u8path(value);
                else {
                    require(!value.empty() && value.find_first_not_of("0123456789") == std::string::npos,
                            "Device ID must be a nonnegative integer");
                    unsigned long long n = std::stoull(value);
                    require(n <= INT_MAX, "Device ID out of range");
                    device = static_cast<int>(n);
                }
            }
        }
        require(!config_path.empty(), "--config is required");
        require(!(validate && prepare), "--validate and --prepare-only are mutually exclusive");
        Config c = read_config(config_path);
        validate_faces(c);
        auto geometry = inspect_meshes(c);
        c.resolved["geometry_inspection"] = geometry;
        if (validate) {
            std::cout << c.resolved.dump(2) << "\nValidation passed (no GPU initialized).\n";
            return 0;
        }
        if (output.empty())
            output = c.path.parent_path() / "results";
        output = fs::absolute(output);
        require(!fs::exists(output) || (fs::is_directory(output) && fs::is_empty(output)),
                "Output directory must be empty: " + output.u8string());
        fs::create_directories(output / "inputs" / "assets");
        owns_output = true;
        auto original = output / "original-config.json";
        fs::copy_file(c.path, original);
        require(sha256(c.path) == sha256(original), "Config changed while snapshotting");
        std::ifstream copied_config(original, std::ios::binary);
        require(Json::parse(copied_config) == c.source, "Config changed after validation");
        Json effective = c.source, manifest = {{"product", SOLVER_IBM_NAME},
                                               {"version", SOLVER_IBM_VERSION_STRING},
                                               {"release_status", SOLVER_IBM_RELEASE_STATUS},
                                               {"config_sha256", sha256(original)},
                                               {"assets", Json::array()}};
        for (size_t i = 0; i < c.geometry.size(); i++) {
            auto name = std::to_string(i) + ".stl";
            auto target = output / "inputs" / "assets" / name;
            fs::copy_file(c.geometry[i].file, target);
            auto hash = sha256(target);
            require(hash == sha256(c.geometry[i].file), "STL changed while snapshotting");
            effective["geometry"][i]["file"] = "inputs/assets/" + name;
            manifest["assets"].push_back({{"id", c.geometry[i].id},
                                          {"original_path", c.geometry[i].file.u8string()},
                                          {"snapshot", "inputs/assets/" + name},
                                          {"sha256", hash}});
        }
        save_json(output / "effective-config.json", effective);
        c = read_config(output / "effective-config.json");
        validate_faces(c);
        c.resolved["geometry_inspection"] = inspect_meshes(c);
        c.resolved["requested_device"] = device;
#ifdef _WIN32
        wchar_t exe[32768];
        DWORD len = GetModuleFileNameW(nullptr, exe, 32768);
        require(len > 0 && len < 32768, "Cannot locate executable");
        manifest["executable_sha256"] = sha256(fs::path(exe));
#endif
        save_json(output / "manifest.json", manifest);
        save_json(output / "completion.json", {{"product", SOLVER_IBM_NAME},
                                               {"version", SOLVER_IBM_VERSION_STRING},
                                               {"release_status", SOLVER_IBM_RELEASE_STATUS},
                                               {"status", "starting"},
                                               {"requested_steps", c.steps},
                                               {"steps", 0}});
        info.print_logo();
        solve(c, output, device, prepare);
        running = false;
        return 0;
    } catch (const std::exception &e) {
        std::cerr << "Error: " << e.what() << std::endl;
        if (owns_output)
            try {
                save_json(output / "completion.json", {{"product", SOLVER_IBM_NAME},
                                                       {"version", SOLVER_IBM_VERSION_STRING},
                                                       {"status", "failed"},
                                                       {"error", e.what()}});
            } catch (...) {
            }
        running = false;
        return 1;
    }
}
} // namespace fxconfig
