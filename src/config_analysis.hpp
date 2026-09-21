#pragma once
#include "config.hpp"
#include "lbm.hpp"
#include <fstream>
#include <iomanip>
#include <map>

namespace fxconfig {
inline bool is_solid(uchar flags) { return (flags & (TYPE_S | TYPE_E)) == TYPE_S; }
inline double pressure(const Config &c, double rho) {
    return (rho - c.pressure_rho) / 3 * c.reference_density * (c.dx / c.dt) * (c.dx / c.dt);
}
inline std::string csv_string(const std::string &s) {
    std::string out = "\"";
    for (char c : s) {
        out += c;
        if (c == '"')
            out += '"';
    }
    return out + '"';
}
struct Moments {
    unsigned long long count = 0, first = 0, last = 0;
    std::vector<double> mean, m2;
    void add(unsigned long long step, const std::vector<double> &v) {
        if (!count) {
            first = step;
            mean.resize(v.size(), 0);
            m2.resize(v.size(), 0);
        }
        last = step;
        count++;
        for (size_t i = 0; i < v.size(); i++) {
            double delta = v[i] - mean[i];
            mean[i] += delta / count;
            m2[i] += delta * (v[i] - mean[i]);
            require(std::isfinite(mean[i]) && std::isfinite(m2[i]), "Statistics overflow");
        }
    }
    Json json(const std::vector<std::string> &names) const {
        Json out = {{"count", count},
                    {"first_step", count ? Json(first) : Json(nullptr)},
                    {"last_step", count ? Json(last) : Json(nullptr)}};
        out["fields"] = Json::object();
        for (size_t i = 0; i < names.size(); i++)
            out["fields"][names[i]] = {
                {"mean", count ? Json(mean[i]) : Json(nullptr)},
                {"std_population", count ? Json(std::sqrt(std::max(0.0, m2[i] / count))) : Json(nullptr)}};
        return out;
    }
};
class Analysis {
    const Config &c;
    fs::path output;
    std::ofstream probes, global, forces;
    std::vector<std::vector<ulong>> groups;
    std::vector<Moments> probe_moments, force_moments;
    Moments global_moments;
    const std::vector<std::string> probe_names{"rho", "ux", "uy", "uz", "speed", "p"};
    const std::vector<std::string> global_names{"mass",    "rho_mean",   "ux_mean", "uy_mean",
                                                "uz_mean", "speed_mean", "p_mean",  "kinetic_energy"};
    const std::vector<std::string> force_names{"fx", "fy", "fz"};
    void row(std::ofstream &out, const std::vector<double> &values) {
        for (double x : values) {
            require(std::isfinite(x), "Non-finite analysis value");
            out << ',' << x;
        }
        out << '\n';
    }

  public:
    Analysis(const Config &config, const fs::path &dir, std::vector<std::vector<ulong>> targets)
        : c(config), output(dir), groups(std::move(targets)), probe_moments(c.probes.size()),
          force_moments(c.forces.size()) {
        if (!c.analysis)
            return;
        probes.open(output / "probes.csv", std::ios::binary);
        global.open(output / "analysis.csv", std::ios::binary);
        forces.open(output / "forces.csv", std::ios::binary);
        require(bool(probes) && bool(global) && bool(forces), "Cannot create analysis CSV");
        probes << std::setprecision(17) << "step,time,id,x,y,z,rho,ux,uy,uz,speed,p\n";
        global << std::setprecision(17)
               << "step,time,fluid_cells,mass,rho_mean,ux_mean,uy_mean,uz_mean,speed_mean,p_mean,kinetic_energy\n";
        forces << std::setprecision(17) << "step,time,id,fx,fy,fz\n";
    }
    void sample(LBM &lbm) {
        if (!c.analysis)
            return;
        auto values = [&](ulong n) {
            double rho = lbm.rho[n] * c.reference_density, ux = lbm.u.x[n] * c.dx / c.dt, uy = lbm.u.y[n] * c.dx / c.dt,
                   uz = lbm.u.z[n] * c.dx / c.dt;
            require(rho > 0, "Non-positive analysis density");
            return std::vector<double>{
                rho, ux, uy, uz, std::sqrt(ux * ux + uy * uy + uz * uz), pressure(c, lbm.rho[n])};
        };
        auto step = lbm.get_t();
        for (size_t i = 0; i < c.probes.size(); i++) {
            const auto &p = c.probes[i];
            auto v = values(p.index);
            probes << step << ',' << step * c.dt << ',' << csv_string(p.id);
            for (double x : p.actual)
                probes << ',' << x;
            row(probes, v);
            if (c.statistics)
                probe_moments[i].add(step, v);
        }
        std::vector<double> sums(8, 0);
        unsigned long long cells = 0;
        double volume = c.dx * c.dx * c.dx;
        for (ulong n = 0; n < lbm.get_N(); n++)
            if (!is_solid(lbm.flags[n])) {
                auto v = values(n);
                cells++;
                for (double x : v)
                    require(std::isfinite(x), "Non-finite fluid analysis value");
                sums[0] += v[0] * volume;
                for (size_t i = 0; i < 6; i++)
                    sums[i + 1] += v[i];
                sums[7] += 0.5 * v[0] * v[4] * v[4] * volume;
            }
        require(cells > 0, "No fluid cells for analysis");
        for (size_t i = 1; i < 7; i++)
            sums[i] /= cells;
        global << step << ',' << step * c.dt << ',' << cells;
        row(global, sums);
        if (c.statistics)
            global_moments.add(step, sums);
        if (!groups.empty()) {
            lbm.lbm_domain[0]->enqueue_config_force_field(static_cast<float>(c.pressure_rho));
            lbm.F.read_from_device();
            double scale = c.reference_density * std::pow(c.dx, 4) / (c.dt * c.dt);
            for (size_t i = 0; i < groups.size(); i++) {
                std::vector<double> f(3, 0);
                for (ulong n : groups[i]) {
                    f[0] += lbm.F.x[n];
                    f[1] += lbm.F.y[n];
                    f[2] += lbm.F.z[n];
                }
                for (auto &x : f)
                    x *= scale;
                forces << step << ',' << step * c.dt << ',' << csv_string(c.forces[i].id);
                row(forces, f);
                if (c.statistics)
                    force_moments[i].add(step, f);
            }
        }
        probes.flush();
        global.flush();
        forces.flush();
        require(bool(probes) && bool(global) && bool(forces), "Analysis CSV write failed");
    }
    void finish() {
        if (!c.analysis || !c.statistics)
            return;
        Json result = {{"units", c.si ? "si" : "lattice"}, {"every", c.sample_every},
                       {"start_step", c.sample_start},     {"global", global_moments.json(global_names)},
                       {"probes", Json::object()},         {"forces", Json::object()}};
        for (size_t i = 0; i < c.probes.size(); i++)
            result["probes"][c.probes[i].id] = probe_moments[i].json(probe_names);
        for (size_t i = 0; i < c.forces.size(); i++)
            result["forces"][c.forces[i].id] = force_moments[i].json(force_names);
        save_json(output / "statistics.json", result);
    }
};
} // namespace fxconfig
