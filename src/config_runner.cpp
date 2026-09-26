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
struct MotionState {
    Vec translation{}, linear_velocity{}, axis{0, 0, 1};
    double degrees = 0, angular_velocity_radians = 0;
};
static double active_elapsed(double time, double start, double stop) {
    if (time <= start)
        return 0;
    return stop < 0 ? time - start : std::min(time, stop) - start;
}
static bool active_now(double time, double start, double stop) {
    return time >= start && (stop < 0 || time < stop);
}
static MotionState motion_state(const Geometry &geometry, double time) {
    MotionState state;
    const auto &motion = geometry.motion;
    if (!motion.trajectory.empty()) {
        const auto &frames = motion.trajectory;
        state.axis = motion.trajectory_axis;
        if (time <= frames.front().time) {
            state.translation = frames.front().translation;
            state.degrees = frames.front().degrees;
            if (time == frames.front().time) {
                const auto &a = frames[0], &b = frames[1];
                const double duration = b.time - a.time;
                for (int component = 0; component < 3; component++)
                    state.linear_velocity[component] =
                        (b.translation[component] - a.translation[component]) / duration;
                state.angular_velocity_radians =
                    (b.degrees - a.degrees) / duration * 0.017453292519943295769;
            }
        } else if (time >= frames.back().time) {
            state.translation = frames.back().translation;
            state.degrees = frames.back().degrees;
        } else {
            auto upper = std::upper_bound(frames.begin(), frames.end(), time,
                                          [](double t, const MotionKeyframe &frame) { return t < frame.time; });
            const auto &b = *upper, &a = *(upper - 1);
            const double duration = b.time - a.time, fraction = (time - a.time) / duration;
            for (int component = 0; component < 3; component++) {
                state.translation[component] =
                    a.translation[component] + fraction * (b.translation[component] - a.translation[component]);
                state.linear_velocity[component] =
                    (b.translation[component] - a.translation[component]) / duration;
            }
            state.degrees = a.degrees + fraction * (b.degrees - a.degrees);
            state.angular_velocity_radians = (b.degrees - a.degrees) / duration * 0.017453292519943295769;
        }
        return state;
    }
    const auto &translation = motion.translation;
    if (translation.type == "constant_velocity") {
        const double elapsed = active_elapsed(time, translation.start, translation.stop);
        for (int component = 0; component < 3; component++) {
            state.translation[component] = translation.velocity[component] * elapsed;
            state.linear_velocity[component] =
                active_now(time, translation.start, translation.stop) ? translation.velocity[component] : 0.0;
        }
    } else if (translation.type == "sinusoidal") {
        const double elapsed = active_elapsed(time, translation.start, translation.stop);
        const double omega = 6.2831853071795864769 / translation.period;
        const double phase = translation.phase_degrees * 0.017453292519943295769;
        for (int component = 0; component < 3; component++) {
            state.translation[component] =
                translation.amplitude[component] * (std::sin(omega * elapsed + phase) - std::sin(phase));
            state.linear_velocity[component] = active_now(time, translation.start, translation.stop)
                                                   ? translation.amplitude[component] * omega *
                                                         std::cos(omega * elapsed + phase)
                                                   : 0.0;
        }
    }
    const auto &rotation = motion.rotation;
    if (!rotation.type.empty())
        state.axis = rotation.axis;
    if (rotation.type == "constant_angular_velocity") {
        const double elapsed = active_elapsed(time, rotation.start, rotation.stop);
        state.degrees = rotation.angular_velocity_degrees * elapsed;
        state.angular_velocity_radians = active_now(time, rotation.start, rotation.stop)
                                               ? rotation.angular_velocity_degrees * 0.017453292519943295769
                                               : 0.0;
    } else if (rotation.type == "sinusoidal") {
        const double elapsed = active_elapsed(time, rotation.start, rotation.stop);
        const double omega = 6.2831853071795864769 / rotation.period;
        const double phase = rotation.phase_degrees * 0.017453292519943295769;
        state.degrees = rotation.amplitude_degrees * (std::sin(omega * elapsed + phase) - std::sin(phase));
        state.angular_velocity_radians = active_now(time, rotation.start, rotation.stop)
                                               ? rotation.amplitude_degrees * omega *
                                                     std::cos(omega * elapsed + phase) * 0.017453292519943295769
                                               : 0.0;
    }
    return state;
}
static std::unique_ptr<Mesh> transform_mesh(const Mesh &base, const Vec &pivot, const MotionState &state) {
    auto result = std::make_unique<Mesh>(base.triangle_number, f3(pivot));
    const float3 pivot3 = f3(pivot), shift = f3(state.translation);
    const float3x3 rotation(f3(state.axis), radians(static_cast<float>(state.degrees)));
    for (uint triangle = 0; triangle < base.triangle_number; triangle++) {
        result->p0[triangle] = pivot3 + rotation * (base.p0[triangle] - pivot3) + shift;
        result->p1[triangle] = pivot3 + rotation * (base.p1[triangle] - pivot3) + shift;
        result->p2[triangle] = pivot3 + rotation * (base.p2[triangle] - pivot3) + shift;
    }
    result->find_bounds();
    result->center = pivot3 + shift;
    return result;
}
static double mesh_volume(const Mesh &mesh) {
    double volume = 0;
    for (uint triangle = 0; triangle < mesh.triangle_number; triangle++) {
        const float3 &a = mesh.p0[triangle], &b = mesh.p1[triangle], &c = mesh.p2[triangle];
        volume += static_cast<double>(a.x) * (static_cast<double>(b.y) * c.z - static_cast<double>(b.z) * c.y) +
                  static_cast<double>(a.y) * (static_cast<double>(b.z) * c.x - static_cast<double>(b.x) * c.z) +
                  static_cast<double>(a.z) * (static_cast<double>(b.x) * c.y - static_cast<double>(b.y) * c.x);
    }
    return std::abs(volume) / 6.0;
}
static double point_triangle_distance_squared(const float3 &point, const float3 &a, const float3 &b,
                                              const float3 &c) {
    const float3 ab = b - a, ac = c - a, ap = point - a;
    const double d1 = dot(ab, ap), d2 = dot(ac, ap);
    if (d1 <= 0 && d2 <= 0)
        return static_cast<double>(dot(ap, ap));
    const float3 bp = point - b;
    const double d3 = dot(ab, bp), d4 = dot(ac, bp);
    if (d3 >= 0 && d4 <= d3)
        return static_cast<double>(dot(bp, bp));
    const double vc = d1 * d4 - d3 * d2;
    if (vc <= 0 && d1 >= 0 && d3 <= 0) {
        const float3 difference = point - (a + ab * static_cast<float>(d1 / (d1 - d3)));
        return static_cast<double>(dot(difference, difference));
    }
    const float3 cp = point - c;
    const double d5 = dot(ab, cp), d6 = dot(ac, cp);
    if (d6 >= 0 && d5 <= d6)
        return static_cast<double>(dot(cp, cp));
    const double vb = d5 * d2 - d1 * d6;
    if (vb <= 0 && d2 >= 0 && d6 <= 0) {
        const float3 difference = point - (a + ac * static_cast<float>(d2 / (d2 - d6)));
        return static_cast<double>(dot(difference, difference));
    }
    const double va = d3 * d6 - d5 * d4;
    if (va <= 0 && d4 - d3 >= 0 && d5 - d6 >= 0) {
        const float3 difference = point - (b + (c - b) * static_cast<float>((d4 - d3) / ((d4 - d3) + (d5 - d6))));
        return static_cast<double>(dot(difference, difference));
    }
    const double denominator = 1.0 / (va + vb + vc), v = vb * denominator, w = vc * denominator;
    const float3 difference = point - (a + ab * static_cast<float>(v) + ac * static_cast<float>(w));
    return static_cast<double>(dot(difference, difference));
}
static double mesh_surface_distance_squared(const Mesh &mesh, const float3 &point) {
    double distance = std::numeric_limits<double>::infinity();
    for (uint triangle = 0; triangle < mesh.triangle_number; triangle++)
        distance = std::min(distance,
                            point_triangle_distance_squared(point, mesh.p0[triangle], mesh.p1[triangle],
                                                            mesh.p2[triangle]));
    return distance;
}
static bool point_inside_mesh(const Mesh &mesh, const float3 &point) {
    const float3 direction(1.0f, 0.372312f, 0.618034f);
    std::vector<double> intersections;
    intersections.reserve(mesh.triangle_number / 2u + 1u);
    for (uint triangle = 0; triangle < mesh.triangle_number; triangle++) {
        const float3 &a = mesh.p0[triangle], edge1 = mesh.p1[triangle] - a, edge2 = mesh.p2[triangle] - a;
        const float3 h = cross(direction, edge2);
        const double determinant = dot(edge1, h);
        if (std::abs(determinant) < 1e-10)
            continue;
        const double inverse = 1.0 / determinant;
        const float3 s = point - a;
        const double u = inverse * dot(s, h);
        if (u < -1e-8 || u > 1.0 + 1e-8)
            continue;
        const float3 q = cross(s, edge1);
        const double v = inverse * dot(direction, q);
        if (v < -1e-8 || u + v > 1.0 + 1e-8)
            continue;
        const double distance = inverse * dot(edge2, q);
        if (distance > 1e-8)
            intersections.push_back(distance);
    }
    std::sort(intersections.begin(), intersections.end());
    size_t unique = 0;
    for (double distance : intersections)
        if (unique == 0 || std::abs(distance - intersections[unique - 1]) > 1e-6)
            intersections[unique++] = distance;
    return unique % 2u != 0u;
}
static void rasterize_object_mask(const Config &c, const Mesh &mesh, const uchar object,
                                  std::vector<uchar> &objects, const std::vector<uchar> &old_objects,
                                  const std::vector<uchar> &flags, const std::string &id) {
    const int lower[3]{std::max(0, static_cast<int>(std::floor(mesh.pmin.x)) - 1),
                       std::max(0, static_cast<int>(std::floor(mesh.pmin.y)) - 1),
                       std::max(0, static_cast<int>(std::floor(mesh.pmin.z)) - 1)};
    const int upper[3]{std::min(static_cast<int>(c.cells[0]) - 1, static_cast<int>(std::ceil(mesh.pmax.x)) + 1),
                       std::min(static_cast<int>(c.cells[1]) - 1, static_cast<int>(std::ceil(mesh.pmax.y)) + 1),
                       std::min(static_cast<int>(c.cells[2]) - 1, static_cast<int>(std::ceil(mesh.pmax.z)) + 1)};
    for (int z = lower[2]; z <= upper[2]; z++)
        for (int y = lower[1]; y <= upper[1]; y++)
            for (int x = lower[0]; x <= upper[0]; x++) {
                const ulong n = static_cast<ulong>(x) +
                                (static_cast<ulong>(y) + static_cast<ulong>(z) * c.cells[1]) * c.cells[0];
                if (!point_inside_mesh(mesh, float3(static_cast<float>(x), static_cast<float>(y),
                                                    static_cast<float>(z))))
                    continue;
                require(objects[static_cast<size_t>(n)] == 0u,
                        "Prescribed STL objects overlap: " + id);
                require(!is_solid(flags[static_cast<size_t>(n)]) || old_objects[static_cast<size_t>(n)] > 0u,
                        "Dynamic STL intersects a fixed solid: " + id);
                objects[static_cast<size_t>(n)] = object;
            }
}
static ulong enforce_object_volume(const Config &c, const Mesh &mesh, const ulong target, const uchar object,
                                   std::vector<uchar> &objects, const std::vector<uchar> *flags = nullptr) {
    ulong count = static_cast<ulong>(std::count(objects.begin(), objects.end(), object));
    if (count == target)
        return count;
    struct Candidate {
        ulong index;
        double distance;
    };
    std::vector<Candidate> candidates;
    const int lower[3]{std::max(0, static_cast<int>(std::floor(mesh.pmin.x)) - 2),
                       std::max(0, static_cast<int>(std::floor(mesh.pmin.y)) - 2),
                       std::max(0, static_cast<int>(std::floor(mesh.pmin.z)) - 2)};
    const int upper[3]{std::min(static_cast<int>(c.cells[0]) - 1, static_cast<int>(std::ceil(mesh.pmax.x)) + 2),
                       std::min(static_cast<int>(c.cells[1]) - 1, static_cast<int>(std::ceil(mesh.pmax.y)) + 2),
                       std::min(static_cast<int>(c.cells[2]) - 1, static_cast<int>(std::ceil(mesh.pmax.z)) + 2)};
    for (int z = lower[2]; z <= upper[2]; z++)
        for (int y = lower[1]; y <= upper[1]; y++)
            for (int x = lower[0]; x <= upper[0]; x++) {
                const ulong n = static_cast<ulong>(x) +
                                (static_cast<ulong>(y) + static_cast<ulong>(z) * c.cells[1]) * c.cells[0];
                const bool removable = count > target && objects[static_cast<size_t>(n)] == object;
                const bool addable = count < target && objects[static_cast<size_t>(n)] == 0u &&
                                     (!flags || !is_solid((*flags)[static_cast<size_t>(n)]));
                if (removable || addable)
                    candidates.push_back({n, mesh_surface_distance_squared(
                                                  mesh, float3(static_cast<float>(x), static_cast<float>(y),
                                                               static_cast<float>(z)))});
            }
    std::sort(candidates.begin(), candidates.end(), [](const Candidate &a, const Candidate &b) {
        return a.distance < b.distance || (a.distance == b.distance && a.index < b.index);
    });
    const ulong difference = count > target ? count - target : target - count;
    require(candidates.size() >= difference, "Insufficient cells to conserve prescribed STL volume");
    for (ulong i = 0; i < difference; i++)
        objects[static_cast<size_t>(candidates[static_cast<size_t>(i)].index)] = count > target ? 0u : object;
    return target;
}
struct DynamicBody {
    const Geometry *geometry = nullptr;
    Vec pivot{};
    std::unique_ptr<Mesh> base, current;
    MotionState state;
    ulong target_cells = 0;
};
static std::string quote_csv_field(const std::string &value);
static float3x3 motion_rotation(const MotionState &state) {
    return float3x3(f3(state.axis), radians(static_cast<float>(state.degrees)));
}
static double sample_object_temperature(const Config &c, const std::vector<float> &temperature,
                                        const std::vector<uchar> &objects, uchar object, const float3 &position,
                                        double fallback) {
    const int x0 = static_cast<int>(std::floor(position.x)), y0 = static_cast<int>(std::floor(position.y)),
              z0 = static_cast<int>(std::floor(position.z));
    double weighted = 0, weights = 0;
    for (int dz = 0; dz <= 1; dz++)
        for (int dy = 0; dy <= 1; dy++)
            for (int dx = 0; dx <= 1; dx++) {
                const int x = x0 + dx, y = y0 + dy, z = z0 + dz;
                if (x < 0 || y < 0 || z < 0 || x >= static_cast<int>(c.cells[0]) ||
                    y >= static_cast<int>(c.cells[1]) || z >= static_cast<int>(c.cells[2]))
                    continue;
                const ulong n = static_cast<ulong>(x) +
                                (static_cast<ulong>(y) + static_cast<ulong>(z) * c.cells[1]) * c.cells[0];
                if (objects[static_cast<size_t>(n)] != object)
                    continue;
                const double wx = dx ? position.x - x0 : 1.0 - (position.x - x0);
                const double wy = dy ? position.y - y0 : 1.0 - (position.y - y0);
                const double wz = dz ? position.z - z0 : 1.0 - (position.z - z0);
                const double weight = std::max(0.0, wx * wy * wz);
                weighted += weight * temperature[static_cast<size_t>(n)];
                weights += weight;
            }
    if (weights > 1e-12)
        return weighted / weights;
    int nearest_distance = 100;
    double nearest = fallback;
    const int cx = static_cast<int>(std::round(position.x)), cy = static_cast<int>(std::round(position.y)),
              cz = static_cast<int>(std::round(position.z));
    for (int dz = -2; dz <= 2; dz++)
        for (int dy = -2; dy <= 2; dy++)
            for (int dx = -2; dx <= 2; dx++) {
                const int x = cx + dx, y = cy + dy, z = cz + dz, distance = dx * dx + dy * dy + dz * dz;
                if (distance >= nearest_distance || x < 0 || y < 0 || z < 0 ||
                    x >= static_cast<int>(c.cells[0]) || y >= static_cast<int>(c.cells[1]) ||
                    z >= static_cast<int>(c.cells[2]))
                    continue;
                const ulong n = static_cast<ulong>(x) +
                                (static_cast<ulong>(y) + static_cast<ulong>(z) * c.cells[1]) * c.cells[0];
                if (objects[static_cast<size_t>(n)] == object) {
                    nearest_distance = distance;
                    nearest = temperature[static_cast<size_t>(n)];
                }
            }
    return nearest;
}
static void update_dynamic_geometry(LBM &lbm, Config &c, std::vector<DynamicBody> &bodies, double time,
                                    const double mass_target) {
    auto *domain = lbm.lbm_domain[0];
    domain->object_id.read_from_device();
    lbm.rho.read_from_device();
    lbm.u.read_from_device();
    lbm.flags.read_from_device();
    std::vector<float> old_surface_mass(c.model.free_surface ? static_cast<size_t>(lbm.get_N()) : 0u);
    if (c.model.free_surface) {
        domain->settle_dynamic_surface_mass(old_surface_mass.data());
        lbm.phi.read_from_device();
    }
    std::vector<uchar> old_objects(static_cast<size_t>(lbm.get_N()));
    for (ulong n = 0; n < lbm.get_N(); n++)
        old_objects[static_cast<size_t>(n)] = domain->object_id[n];
    std::vector<float> old_temperature;
    double energy_before_remap = 0;
    if (c.model.temperature) {
        domain->T.read_from_device();
        old_temperature.resize(static_cast<size_t>(lbm.get_N()));
        for (ulong n = 0; n < lbm.get_N(); n++) {
            old_temperature[static_cast<size_t>(n)] = domain->T[n];
            const bool active = domain->material[n] != 255u &&
                                (!c.model.free_surface || domain->material[n] > 0u ||
                                 (lbm.flags[n] & (TYPE_F | TYPE_I)));
            if (active) {
                const double liquid_fraction = c.model.free_surface && domain->material[n] == 0u
                                                   ? std::clamp(static_cast<double>(lbm.phi[n]), 0.0, 1.0)
                                                   : 1.0;
                energy_before_remap +=
                    liquid_fraction * static_cast<double>(domain->thermal_capacity[n]) * domain->T[n];
            }
        }
    }
    for (auto &body : bodies) {
        MotionState next_state = motion_state(*body.geometry, time);
        auto next = transform_mesh(*body.base, body.pivot, next_state);
        const float3 actual_min = next->pmin, actual_max = next->pmax;
        require(actual_min.x >= -0.5001f && actual_min.y >= -0.5001f && actual_min.z >= -0.5001f &&
                    actual_max.x <= c.cells[0] - 0.4999f && actual_max.y <= c.cells[1] - 0.4999f &&
                    actual_max.z <= c.cells[2] - 0.4999f,
                "Dynamic STL crosses the domain: " + body.geometry->id + " at step " +
                    std::to_string(static_cast<unsigned long long>(time)));
        next->pmin = float3(std::min(body.current->pmin.x, actual_min.x),
                            std::min(body.current->pmin.y, actual_min.y),
                            std::min(body.current->pmin.z, actual_min.z));
        next->pmax = float3(std::max(body.current->pmax.x, actual_max.x),
                            std::max(body.current->pmax.y, actual_max.y),
                            std::max(body.current->pmax.z, actual_max.z));
        const float3 center = f3(body.pivot) + f3(next_state.translation);
        const float3 linear = f3(next_state.linear_velocity);
        const float3 angular = f3(next_state.axis) * static_cast<float>(next_state.angular_velocity_radians);
        double radius = 0;
        for (int corner = 0; corner < 8; corner++) {
            const float3 point(corner & 1 ? actual_max.x : actual_min.x,
                               corner & 2 ? actual_max.y : actual_min.y,
                               corner & 4 ? actual_max.z : actual_min.z);
            radius = std::max(radius, static_cast<double>(length(point - center)));
        }
        require(length(linear) + length(angular) * radius <= 0.05f,
                "Dynamic STL surface velocity exceeds the validated low-Mach limit (0.05 lattice units/step): " +
                    body.geometry->id);
        next->pmin = actual_min;
        next->pmax = actual_max;
        body.current = std::move(next);
        body.state = next_state;
    }
    std::vector<uchar> desired_objects(static_cast<size_t>(lbm.get_N())), current_flags(static_cast<size_t>(lbm.get_N()));
    for (ulong n = 0; n < lbm.get_N(); n++) {
        desired_objects[static_cast<size_t>(n)] = old_objects[static_cast<size_t>(n)];
        current_flags[static_cast<size_t>(n)] = old_objects[static_cast<size_t>(n)] > 0u ? 0u : lbm.flags[n];
    }
    for (const auto &body : bodies) {
        const uchar object = static_cast<uchar>(body.geometry->object_index);
        for (uchar &cell : desired_objects)
            if (cell == object)
                cell = 0u;
    }
    for (const auto &body : bodies)
        rasterize_object_mask(c, *body.current, static_cast<uchar>(body.geometry->object_index), desired_objects,
                              old_objects, current_flags, body.geometry->id);
    for (const auto &body : bodies)
        enforce_object_volume(c, *body.current, body.target_cells, static_cast<uchar>(body.geometry->object_index),
                              desired_objects, &current_flags);
    std::vector<float> release_density(static_cast<size_t>(lbm.get_N()), 1.0f);
    std::vector<float> release_velocity(static_cast<size_t>(3u * lbm.get_N()), 0.0f);
    std::vector<float> release_mass(c.model.free_surface ? static_cast<size_t>(lbm.get_N()) : 1u, 0.0f);
    for (const auto &body : bodies) {
        const uchar object = static_cast<uchar>(body.geometry->object_index);
        std::vector<ulong> occupied, released;
        for (ulong n = 0; n < lbm.get_N(); n++) {
            if (old_objects[static_cast<size_t>(n)] != object && desired_objects[static_cast<size_t>(n)] == object)
                occupied.push_back(n);
            if (old_objects[static_cast<size_t>(n)] == object && desired_objects[static_cast<size_t>(n)] != object)
                released.push_back(n);
        }
        require(occupied.size() == released.size(), "Prescribed STL remap changed object volume: " + body.geometry->id);
        std::vector<bool> used(occupied.size(), false);
        for (ulong destination : released) {
            uint dx, dy, dz;
            lbm.coordinates(destination, dx, dy, dz);
            size_t nearest = occupied.size();
            unsigned long long nearest_distance = std::numeric_limits<unsigned long long>::max();
            for (size_t i = 0; i < occupied.size(); i++) {
                if (used[i])
                    continue;
                uint sx, sy, sz;
                lbm.coordinates(occupied[i], sx, sy, sz);
                const long long x = static_cast<long long>(sx) - dx, y = static_cast<long long>(sy) - dy,
                                z = static_cast<long long>(sz) - dz;
                const unsigned long long distance = static_cast<unsigned long long>(x * x + y * y + z * z);
                if (distance < nearest_distance) {
                    nearest = i;
                    nearest_distance = distance;
                }
            }
            require(nearest < occupied.size(), "Prescribed STL remap could not pair boundary cells");
            used[nearest] = true;
            const ulong source = occupied[nearest];
            release_density[static_cast<size_t>(destination)] = lbm.rho[source];
            release_velocity[static_cast<size_t>(destination)] = lbm.u.x[source];
            release_velocity[static_cast<size_t>(lbm.get_N() + destination)] = lbm.u.y[source];
            release_velocity[static_cast<size_t>(2u * lbm.get_N() + destination)] = lbm.u.z[source];
            if (c.model.free_surface) {
                const float liquid_mass = old_surface_mass[static_cast<size_t>(source)];
                require(std::isfinite(liquid_mass),
                        "Prescribed STL remap encountered invalid free-surface mass");
                release_mass[static_cast<size_t>(destination)] = liquid_mass;
            }
        }
    }
    for (const auto &body : bodies) {
        const float3 center = f3(body.pivot) + f3(body.state.translation);
        const float3 linear = f3(body.state.linear_velocity);
        const float3 angular = f3(body.state.axis) * static_cast<float>(body.state.angular_velocity_radians);
        domain->reconcile_dynamic_object_mask(desired_objects.data(), release_density.data(),
                                              release_velocity.data(), release_mass.data(),
                                              static_cast<uchar>(body.geometry->object_index), center, linear,
                                              angular);
    }
    lbm.update_moving_boundaries();
    domain->refresh_dynamic_macroscopic_fields();
    domain->object_id.read_from_device();
    lbm.rho.read_from_device();
    lbm.flags.read_from_device();
    lbm.u.read_from_device();
    for (ulong n = 0; n < lbm.get_N(); n++)
        require(domain->object_id[n] != 255u,
                "Prescribed STL objects overlap at step " + std::to_string(static_cast<unsigned long long>(time)));
    for (const auto &body : bodies) {
        const uchar object = static_cast<uchar>(body.geometry->object_index);
        ulong cells = 0;
        for (ulong n = 0; n < lbm.get_N(); n++)
            cells += domain->object_id[n] == object;
        require(cells == body.target_cells, "Prescribed STL volume reconciliation failed: " + body.geometry->id);
    }
    if (std::isfinite(mass_target)) {
        if (c.model.free_surface) {
            std::vector<float> current_surface_mass(static_cast<size_t>(lbm.get_N()));
            domain->read_dynamic_surface_mass(current_surface_mass.data());
            double current_mass = 0;
            for (ulong n = 0; n < lbm.get_N(); n++)
                if (!is_solid(lbm.flags[n]))
                    current_mass += current_surface_mass[static_cast<size_t>(n)];
            const double correction = mass_target - current_mass;
            double capacity = 0;
            for (ulong n = 0; n < lbm.get_N(); n++)
                if (!is_solid(lbm.flags[n]) && (lbm.flags[n] & TYPE_I)) {
                    const double cell_mass = current_surface_mass[static_cast<size_t>(n)];
                    capacity += correction >= 0 ? std::max(0.0, static_cast<double>(lbm.rho[n]) - cell_mass)
                                                : std::max(0.0, cell_mass);
                }
            require(std::isfinite(correction) && capacity + 1.0e-9 >= std::abs(correction),
                    "Dynamic free-surface mass correction exceeds interface capacity");
            if (std::abs(correction) > 1.0e-9) {
                for (ulong n = 0; n < lbm.get_N(); n++)
                    if (!is_solid(lbm.flags[n]) && (lbm.flags[n] & TYPE_I)) {
                        const double cell_mass = current_surface_mass[static_cast<size_t>(n)];
                        const double available = correction >= 0
                                                     ? std::max(0.0, static_cast<double>(lbm.rho[n]) - cell_mass)
                                                     : std::max(0.0, cell_mass);
                        current_surface_mass[static_cast<size_t>(n)] =
                            static_cast<float>(cell_mass + correction * available / capacity);
                        lbm.phi[n] = std::clamp(current_surface_mass[static_cast<size_t>(n)] / lbm.rho[n],
                                               0.0f, 1.0f);
                    }
                domain->write_dynamic_surface_mass(current_surface_mass.data());
                lbm.phi.write_to_device();
            }
        } else {
            double current_mass = 0, minimum_density = std::numeric_limits<double>::infinity();
            ulong fluid_cells = 0;
            for (ulong n = 0; n < lbm.get_N(); n++)
                if (!is_solid(lbm.flags[n])) {
                    current_mass += lbm.rho[n];
                    minimum_density = std::min(minimum_density, static_cast<double>(lbm.rho[n]));
                    fluid_cells++;
                }
            require(fluid_cells > 0, "Dynamic mass correction has no fluid cells");
            const double density_delta = (mass_target - current_mass) / static_cast<double>(fluid_cells);
            require(std::isfinite(density_delta) && minimum_density + density_delta > 0,
                    "Dynamic mass correction would produce a non-positive density");
            domain->correct_dynamic_mass(static_cast<float>(density_delta));
        }
    }
    if (c.model.free_surface) {
        for (ulong n = 0; n < lbm.get_N(); n++) {
            const uchar object = domain->object_id[n];
            if (object > 0u) {
                const auto &geometry = c.geometry[static_cast<size_t>(object - 1u)];
                domain->contact_angle[n] =
                    static_cast<float>(geometry.contact_angle * 0.017453292519943295769);
            }
        }
        domain->contact_angle.enqueue_write_to_device();
    }
    if (c.model.temperature) {
        for (auto &body : bodies) {
            const uchar object = static_cast<uchar>(body.geometry->object_index);
            double fallback = 0, old_energy = 0;
            ulong old_count = 0;
            const auto &material = c.thermal_materials[static_cast<size_t>(body.geometry->material_index - 1)];
            for (ulong n = 0; n < lbm.get_N(); n++)
                if (old_objects[static_cast<size_t>(n)] == object) {
                    fallback += old_temperature[static_cast<size_t>(n)];
                    old_energy += material.capacity_lattice * old_temperature[static_cast<size_t>(n)];
                    old_count++;
                }
            require(old_count > 0, "Dynamic STL lost all thermal cells: " + body.geometry->id);
            fallback /= static_cast<double>(old_count);
            const MotionState old_state = motion_state(*body.geometry, time - 1.0);
            const float3x3 old_rotation = motion_rotation(old_state), new_rotation = motion_rotation(body.state);
            const float3 pivot = f3(body.pivot), old_shift = f3(old_state.translation),
                         new_shift = f3(body.state.translation);
            std::vector<std::pair<ulong, double>> mapped;
            double mapped_energy = 0;
            for (ulong n = 0; n < lbm.get_N(); n++)
                if (domain->object_id[n] == object) {
                    uint x, y, z;
                    lbm.coordinates(n, x, y, z);
                    const float3 current(static_cast<float>(x), static_cast<float>(y), static_cast<float>(z));
                    const float3 base_position = pivot + (current - pivot - new_shift) * new_rotation;
                    const float3 old_position = pivot + old_rotation * (base_position - pivot) + old_shift;
                    const double value = sample_object_temperature(c, old_temperature, old_objects, object,
                                                                   old_position, fallback);
                    mapped.push_back({n, value});
                    mapped_energy += material.capacity_lattice * value;
                }
            require(!mapped.empty() && mapped_energy > 0, "Dynamic STL voxelized to zero thermal cells: " + body.geometry->id);
            const double correction = old_energy / mapped_energy;
            for (const auto &entry : mapped)
                domain->T[entry.first] = static_cast<float>(entry.second * correction);
        }
        for (ulong n = 0; n < lbm.get_N(); n++) {
            const uchar old_object = old_objects[static_cast<size_t>(n)], object = domain->object_id[n];
            if (old_object > 0u && object == 0u) {
                domain->thermal_capacity[n] = 1.0f;
                domain->thermal_conductivity[n] = static_cast<float>(c.thermal_diffusivity);
                domain->thermal_source[n] = 0.0f;
                domain->material[n] = 0u;
                domain->T[n] = static_cast<float>(c.initial_temperature);
            }
            if (object > 0u) {
                const auto &geometry = c.geometry[static_cast<size_t>(object - 1u)];
                const auto &material = c.thermal_materials[static_cast<size_t>(geometry.material_index - 1)];
                domain->thermal_capacity[n] = static_cast<float>(material.capacity_lattice);
                domain->thermal_conductivity[n] = static_cast<float>(material.conductivity_lattice);
                domain->thermal_source[n] = static_cast<float>(material.source_lattice);
                domain->material[n] = static_cast<uchar>(geometry.material_index);
            }
        }
        double energy_after_remap = 0, correction_capacity = 0;
        for (ulong n = 0; n < lbm.get_N(); n++) {
            const bool active = domain->material[n] != 255u &&
                                (!c.model.free_surface || domain->material[n] > 0u ||
                                 (lbm.flags[n] & (TYPE_F | TYPE_I)));
            const double liquid_fraction = active && c.model.free_surface && domain->material[n] == 0u
                                               ? std::clamp(static_cast<double>(lbm.phi[n]), 0.0, 1.0)
                                               : 1.0;
            if (active)
                energy_after_remap +=
                    liquid_fraction * static_cast<double>(domain->thermal_capacity[n]) * domain->T[n];
            if (active && domain->material[n] == 0u)
                correction_capacity += liquid_fraction * domain->thermal_capacity[n];
        }
        const bool correct_all_active = correction_capacity == 0;
        if (correct_all_active) {
            for (ulong n = 0; n < lbm.get_N(); n++) {
                const bool active = domain->material[n] != 255u &&
                                    (!c.model.free_surface || domain->material[n] > 0u ||
                                     (lbm.flags[n] & (TYPE_F | TYPE_I)));
                if (active) {
                    const double liquid_fraction = c.model.free_surface && domain->material[n] == 0u
                                                       ? std::clamp(static_cast<double>(lbm.phi[n]), 0.0, 1.0)
                                                       : 1.0;
                    correction_capacity += liquid_fraction * domain->thermal_capacity[n];
                }
            }
        }
        require(correction_capacity > 0, "Dynamic thermal remap has no active heat capacity");
        const double temperature_correction = (energy_before_remap - energy_after_remap) / correction_capacity;
        for (ulong n = 0; n < lbm.get_N(); n++) {
            const bool active = domain->material[n] != 255u &&
                                (!c.model.free_surface || domain->material[n] > 0u ||
                                 (lbm.flags[n] & (TYPE_F | TYPE_I)));
            const bool correct = active && (correct_all_active || domain->material[n] == 0u);
            if (correct) {
                domain->T[n] = static_cast<float>(domain->T[n] + temperature_correction);
                require(std::isfinite(domain->T[n]) && domain->T[n] > 0,
                        "Dynamic thermal conservation correction produced an invalid temperature");
            }
        }
        domain->T.enqueue_write_to_device();
        domain->thermal_capacity.enqueue_write_to_device();
        domain->thermal_conductivity.enqueue_write_to_device();
        domain->thermal_source.enqueue_write_to_device();
        domain->material.enqueue_write_to_device();
    }
}
static void write_object_motion(LBM &lbm, const Config &c, const std::vector<DynamicBody> &bodies,
                                std::ofstream &file) {
    lbm.lbm_domain[0]->enqueue_config_force_field(static_cast<float>(c.pressure_rho));
    lbm.F.read_from_device();
    lbm.lbm_domain[0]->object_id.read_from_device();
    for (const auto &body : bodies) {
        const uchar object = static_cast<uchar>(body.geometry->object_index);
        const Vec center{body.pivot[0] + body.state.translation[0], body.pivot[1] + body.state.translation[1],
                         body.pivot[2] + body.state.translation[2]};
        Vec force{}, torque{};
        ulong cells = 0;
        for (ulong n = 0; n < lbm.get_N(); n++)
            if (lbm.lbm_domain[0]->object_id[n] == object) {
                uint x, y, z;
                lbm.coordinates(n, x, y, z);
                const Vec f{lbm.F.x[n], lbm.F.y[n], lbm.F.z[n]};
                const Vec r{static_cast<double>(x) - center[0], static_cast<double>(y) - center[1],
                            static_cast<double>(z) - center[2]};
                for (int a = 0; a < 3; a++)
                    force[a] += f[a];
                torque[0] += r[1] * f[2] - r[2] * f[1];
                torque[1] += r[2] * f[0] - r[0] * f[2];
                torque[2] += r[0] * f[1] - r[1] * f[0];
                cells++;
            }
        require(cells > 0, "Dynamic object has no occupied cells: " + body.geometry->id);
        file << std::setprecision(17) << lbm.get_t() << ',' << lbm.get_t() * c.dt << ','
             << quote_csv_field(body.geometry->id) << ',' << body.geometry->object_index << ',' << cells;
        for (double value : body.state.translation)
            file << ',' << value;
        for (double value : center)
            file << ',' << value;
        for (double value : body.state.axis)
            file << ',' << value;
        file << ',' << body.state.degrees;
        for (double value : body.state.linear_velocity)
            file << ',' << value;
        file << ',' << body.state.angular_velocity_radians;
        for (double value : force)
            file << ',' << value;
        for (double value : torque)
            file << ',' << value;
        if (c.model.temperature) {
            double minimum = std::numeric_limits<double>::infinity();
            double maximum = -std::numeric_limits<double>::infinity();
            double energy = 0;
            for (ulong n = 0; n < lbm.get_N(); n++)
                if (lbm.lbm_domain[0]->object_id[n] == object) {
                    minimum = std::min(minimum, static_cast<double>(lbm.T[n]));
                    maximum = std::max(maximum, static_cast<double>(lbm.T[n]));
                    energy += lbm.lbm_domain[0]->thermal_capacity[n] * lbm.T[n];
                }
            require(std::isfinite(minimum) && std::isfinite(maximum) && std::isfinite(energy),
                    "Non-finite dynamic-object thermal diagnostic: " + body.geometry->id);
            file << ',' << minimum * c.temperature_scale << ',' << maximum * c.temperature_scale << ',' << energy;
        }
        file << '\n';
    }
    file.flush();
    require(bool(file), "Object motion output failed");
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
    bool bytes = fieldname == "flags" || fieldname == "material" || fieldname == "object";
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
                                                    : fieldname == "material" ? lbm.lbm_domain[0]->material[n]
                                                                                : lbm.lbm_domain[0]->object_id[n]));
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
    if (lbm.get_model().dynamic_geometry)
        lbm.lbm_domain[0]->object_id.read_from_device();
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
    std::vector<float> dynamic_surface_mass(c.model.free_surface && c.model.dynamic_geometry
                                                ? static_cast<size_t>(lbm.get_N())
                                                : 0u);
    if (!dynamic_surface_mass.empty())
        lbm.lbm_domain[0]->read_dynamic_surface_mass(dynamic_surface_mass.data());
    if (!dynamic_surface_mass.empty())
        for (ulong n = 0; n < lbm.get_N(); n++)
            if (!is_solid(lbm.flags[n]))
                mass += dynamic_surface_mass[static_cast<size_t>(n)];
    for (ulong n = 0; n < lbm.get_N(); n++)
        if (!is_solid(lbm.flags[n]) &&
            (!c.model.free_surface || (lbm.flags[n] & (TYPE_F | TYPE_I)))) {
            double rho = lbm.rho[n], x = lbm.u.x[n], y = lbm.u.y[n], z = lbm.u.z[n];
            require(std::isfinite(rho) && rho > 0 && std::isfinite(x) && std::isfinite(y) && std::isfinite(z),
                    "Non-finite velocity or non-positive density at step " + std::to_string(lbm.get_t()));
            if (dynamic_surface_mass.empty())
                mass += c.model.free_surface ? rho * lbm.phi[n] : rho;
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
                const double liquid_fraction = c.model.free_surface && domain->material[n] == 0u
                                                   ? std::clamp(static_cast<double>(lbm.phi[n]), 0.0, 1.0)
                                                   : 1.0;
                energy += liquid_fraction * domain->thermal_capacity[n] * temperature;
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
    bool need_owner = (c.model.temperature || c.model.free_surface || c.model.dynamic_geometry) && !c.geometry.empty();
    for (const auto &f : c.forces)
        need_owner = need_owner || f.target.rfind("geometry:", 0) == 0;
    if (need_owner)
        owner.assign(static_cast<size_t>(lbm.get_N()), -1);
    Json geometries = Json::array();
    std::vector<DynamicBody> dynamic_bodies;
    std::vector<MotionState> initial_motion(c.geometry.size());
    for (const auto &g : c.geometry) {
        for (ulong n = 0; n < lbm.get_N(); n++)
            lbm.flags[n] = 0;
        lbm.flags.write_to_device();
        auto m = mesh(c, g);
        Mesh *active_mesh = m.get();
        if (g.motion.enabled) {
            DynamicBody body;
            body.geometry = &g;
            body.pivot = g.motion.has_pivot
                             ? g.motion.pivot
                             : Vec{m->get_bounding_box_center().x, m->get_bounding_box_center().y,
                                   m->get_bounding_box_center().z};
            body.state = motion_state(g, 0.0);
            initial_motion[static_cast<size_t>(&g - c.geometry.data())] = body.state;
            body.base = std::move(m);
            body.target_cells = std::max<ulong>(1u, static_cast<ulong>(std::llround(mesh_volume(*body.base))));
            body.current = transform_mesh(*body.base, body.pivot, body.state);
            active_mesh = body.current.get();
            dynamic_bodies.push_back(std::move(body));
        }
        lbm.voxelize_mesh_on_device(active_mesh, TYPE_S);
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
                        require(!c.model.dynamic_geometry, "Dynamic STL geometries overlap: " + g.id);
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
                              {"object_id", g.object_index},
                              {"dynamic", g.motion.enabled},
                              {"material", g.material.empty() ? Json(nullptr) : Json(g.material)},
                              {"contact_angle_degrees", c.model.free_surface ? Json(g.contact_angle) : Json(nullptr)}});
    }
    if (c.model.dynamic_geometry) {
        std::vector<uchar> initial_objects(static_cast<size_t>(lbm.get_N()), 0u);
        for (ulong n = 0; n < lbm.get_N(); n++)
            if (owner[static_cast<size_t>(n)] >= 0)
                initial_objects[static_cast<size_t>(n)] =
                    static_cast<uchar>(c.geometry[static_cast<size_t>(owner[static_cast<size_t>(n)])].object_index);
        const std::vector<uchar> rough_objects = initial_objects;
        const std::vector<uchar> no_fixed_flags(static_cast<size_t>(lbm.get_N()), 0u);
        for (const auto &body : dynamic_bodies) {
            const uchar object = static_cast<uchar>(body.geometry->object_index);
            for (uchar &cell : initial_objects)
                if (cell == object)
                    cell = 0u;
        }
        for (const auto &body : dynamic_bodies)
            rasterize_object_mask(c, *body.current, static_cast<uchar>(body.geometry->object_index), initial_objects,
                                  rough_objects, no_fixed_flags, body.geometry->id);
        for (const auto &body : dynamic_bodies) {
            const uchar object = static_cast<uchar>(body.geometry->object_index);
            const ulong corrected =
                enforce_object_volume(c, *body.current, body.target_cells, object, initial_objects);
            geometries[static_cast<size_t>(body.geometry - c.geometry.data())]["solid_cells"] = corrected;
            geometries[static_cast<size_t>(body.geometry - c.geometry.data())]["target_cells"] = body.target_cells;
        }
        std::fill(solid.begin(), solid.end(), 0u);
        std::fill(owner.begin(), owner.end(), -1);
        for (ulong n = 0; n < lbm.get_N(); n++) {
            const uchar object = initial_objects[static_cast<size_t>(n)];
            if (object == 0u)
                continue;
            solid[static_cast<size_t>(n)] = TYPE_S;
            owner[static_cast<size_t>(n)] = static_cast<int>(object) - 1;
        }
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
        if (c.model.dynamic_geometry)
            lbm.lbm_domain[0]->object_id[n] =
                owner.empty() || owner[static_cast<size_t>(n)] < 0
                    ? 0u
                    : static_cast<uchar>(c.geometry[static_cast<size_t>(owner[static_cast<size_t>(n)])].object_index);
        int b = boundary_at(c, x, y, z);
        if (b >= 0) {
            const auto &rule = c.boundaries[b];
            if (need_owner && owner[static_cast<size_t>(n)] >= 0)
                require(!c.geometry[static_cast<size_t>(owner[static_cast<size_t>(n)])].motion.enabled,
                        "Dynamic geometry intersects a domain boundary: " +
                            c.geometry[static_cast<size_t>(owner[static_cast<size_t>(n)])].id);
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
            const int geometry_owner = owner.empty() ? -1 : owner[static_cast<size_t>(n)];
            const bool moving_geometry = geometry_owner >= 0 && c.geometry[static_cast<size_t>(geometry_owner)].motion.enabled;
            if (moving_geometry) {
                const auto &state = initial_motion[static_cast<size_t>(geometry_owner)];
                const auto &body = *std::find_if(dynamic_bodies.begin(), dynamic_bodies.end(), [&](const DynamicBody &item) {
                    return item.geometry == &c.geometry[static_cast<size_t>(geometry_owner)];
                });
                const Vec center{body.pivot[0] + state.translation[0], body.pivot[1] + state.translation[1],
                                 body.pivot[2] + state.translation[2]};
                const Vec radius{static_cast<double>(x) - center[0], static_cast<double>(y) - center[1],
                                 static_cast<double>(z) - center[2]};
                const Vec omega{state.axis[0] * state.angular_velocity_radians,
                                state.axis[1] * state.angular_velocity_radians,
                                state.axis[2] * state.angular_velocity_radians};
                velocity = {state.linear_velocity[0] + omega[1] * radius[2] - omega[2] * radius[1],
                            state.linear_velocity[1] + omega[2] * radius[0] - omega[0] * radius[2],
                            state.linear_velocity[2] + omega[0] * radius[1] - omega[1] * radius[0]};
            }
            if ((b < 0 || c.boundaries[b].type != "moving_wall") && !moving_geometry)
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
        if (c.model.free_surface && (!(lbm.flags[n] & TYPE_S) || c.model.dynamic_geometry)) {
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
    double dynamic_mass_target = std::numeric_limits<double>::quiet_NaN();
    bool closed_dynamic_domain = c.model.dynamic_geometry;
    for (const auto &boundary : c.boundaries)
        closed_dynamic_domain = closed_dynamic_domain &&
                                (boundary.type == "no_slip" || boundary.type == "moving_wall" ||
                                 boundary.type == "periodic");
    if (closed_dynamic_domain) {
        dynamic_mass_target = 0;
        if (c.model.free_surface) {
            std::vector<float> initial_surface_mass(static_cast<size_t>(lbm.get_N()));
            lbm.lbm_domain[0]->settle_dynamic_surface_mass(initial_surface_mass.data());
            for (ulong n = 0; n < lbm.get_N(); n++)
                if (!is_solid(lbm.flags[n]))
                    dynamic_mass_target += initial_surface_mass[static_cast<size_t>(n)];
        } else {
            for (ulong n = 0; n < lbm.get_N(); n++)
                if (!is_solid(lbm.flags[n]))
                    dynamic_mass_target += lbm.rho[n];
        }
    }
    auto advance_to = [&](ulong target) {
        if (!c.model.dynamic_geometry) {
            lbm.run(target - lbm.get_t(), c.steps);
            return;
        }
        while (lbm.get_t() < target) {
            lbm.run(1, c.steps);
            update_dynamic_geometry(lbm, c, dynamic_bodies, static_cast<double>(lbm.get_t()),
                                    dynamic_mass_target);
        }
    };
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
    std::ofstream object_motion;
    if (c.model.dynamic_geometry) {
        object_motion.open(output / "object-motion.csv", std::ios::binary);
        require(bool(object_motion), "Cannot create object-motion.csv");
        object_motion
            << "step,time,geometry_id,object_index,solid_cells,translation_x_lattice,translation_y_lattice,"
               "translation_z_lattice,pivot_x_lattice,pivot_y_lattice,pivot_z_lattice,axis_x,axis_y,axis_z,"
               "degrees,linear_velocity_x_lattice,linear_velocity_y_lattice,linear_velocity_z_lattice,"
               "angular_velocity_radians_per_step,force_x_lattice,force_y_lattice,force_z_lattice,"
               "torque_x_lattice,torque_y_lattice,torque_z_lattice";
        if (c.model.temperature)
            object_motion << ",temperature_min,temperature_max,sensible_energy_lattice";
        object_motion << '\n';
    }
    monitor(lbm, c, stats, flux_surfaces, flux_file);
    if (c.model.dynamic_geometry)
        write_object_motion(lbm, c, dynamic_bodies, object_motion);
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
        advance_to(next);
        sync(lbm);
        if (c.analysis && next == next_sample) {
            analysis.sample(lbm);
            next_sample = next + c.sample_every; // both <= 2^53; sum fits uint64
        }
        if (next == next_monitor || next == c.steps) {
            monitor(lbm, c, stats, flux_surfaces, flux_file);
            if (c.model.dynamic_geometry)
                write_object_motion(lbm, c, dynamic_bodies, object_motion);
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
