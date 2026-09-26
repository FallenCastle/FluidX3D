#pragma once
#include <array>
#include <cmath>

enum class CollisionModel { SingleRelaxation, TwoRelaxation };
struct SolverOptions {
    unsigned q = 19;
    CollisionModel collision = CollisionModel::SingleRelaxation;
    bool subgrid = true;
    bool free_surface = false;
    bool temperature = false;
    std::array<double, 3> gravity{0.0, 0.0, 0.0};
    double reference_temperature = 1.0;
    double ambient_density = 1.0;
    static constexpr double default_cs = 0.17326595533835415;
    double smagorinsky_constant = default_cs;
    double trt_magic_parameter = 0.1875;
    unsigned transfers() const { return q == 27 ? 9u : 5u; }
    const char *lattice_name() const { return q == 27 ? "D3Q27" : "D3Q19"; }
    const char *collision_name() const { return collision == CollisionModel::TwoRelaxation ? "TRT" : "SRT"; }
    const char *turbulence_name() const { return subgrid ? "smagorinsky" : "none"; }
    float smagorinsky_coefficient() const {
        return smagorinsky_constant == default_cs
                   ? 0.76421222f
                   : static_cast<float>(18.0 * std::sqrt(2.0) * smagorinsky_constant * smagorinsky_constant);
    }
};
