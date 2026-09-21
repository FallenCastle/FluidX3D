#include "setup.hpp"
#include <filesystem>

static const string case_assets =
    "F:/01-Project/Opensource/01-FluidX3D/workingdir/boeing-747/assets/";

static string case_model(const string& filename) {
    namespace fs = std::filesystem;
    const fs::path src = fs::path(case_assets) / filename;
    const fs::path dst = fs::path("inputs") / filename;
    std::error_code ec;
    fs::create_directories(dst.parent_path(), ec);
    if(ec) print_error("Cannot create input directory: " + ec.message());
    fs::copy_file(src, dst, fs::copy_options::none, ec);
    if(ec) print_error("Cannot snapshot model " + src.string() + ": " + ec.message());
    return dst.generic_string();
}

void main_setup() {
    const uint3 lbm_N = resolution(float3(1.0f, 2.0f, 0.5f), 256u);
    const float lbm_Re = 1000000.0f;
    const float lbm_u = 0.075f;
    const ulong lbm_T = 1000ull;
    LBM lbm(lbm_N, units.nu_from_Re(lbm_Re, (float)lbm_N.x, lbm_u));

    const float size = lbm.size().x;
    const float3 center(lbm.center().x, 0.55f*size, lbm.center().z);
    const float3x3 rotation(float3(1, 0, 0), radians(-15.0f));
    lbm.voxelize_stl(case_model("techtris_airplane.stl"), center, rotation, size);

    const uint Nx=lbm.get_Nx(), Ny=lbm.get_Ny(), Nz=lbm.get_Nz();
    parallel_for(lbm.get_N(), [&](ulong n) {
        uint x=0u, y=0u, z=0u;
        lbm.coordinates(n, x, y, z);
        if(!(lbm.flags[n]&TYPE_S)) lbm.u.y[n] = lbm_u;
        if(x==0u || x==Nx-1u || y==0u || y==Ny-1u || z==0u || z==Nz-1u)
            lbm.flags[n] = TYPE_E;
    });

    lbm.run(0u, lbm_T);
    lbm.flags.write_device_to_vtk("", false);
    lbm.u.write_device_to_vtk("", false);
    lbm.rho.write_device_to_vtk("", false);

    while(lbm.get_t()<lbm_T) {
        const ulong remaining = lbm_T-lbm.get_t();
        const ulong step = remaining<100ull ? remaining : 100ull;
        lbm.run(step, lbm_T);
    }
    lbm.u.write_device_to_vtk("", false);
    lbm.rho.write_device_to_vtk("", false);
    lbm.flags.write_device_to_vtk("", false);
    lbm.write_status();
}
