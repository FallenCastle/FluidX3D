#pragma once
#include "third_party/nlohmann/json.hpp"
#include <array>
#include <filesystem>
#include <string>
#include <vector>

namespace fxconfig {
using Json = nlohmann::json;
using Vec = std::array<double, 3>;
namespace fs = std::filesystem;
struct Geometry {
    std::string id;
    fs::path file;
    std::string mode;
    double size=1, factor=1, degrees=0;
    Vec center{}, pivot{}, translation{}, axis{1,0,0};
};
struct Boundary {
    std::string id, type;
    std::vector<int> faces;
    int priority=0;
    bool region=false;
    std::array<double,2> lower{}, upper{};
    double rho=1;
    Vec velocity{};
};
struct InitialRegion { Vec lower{}, upper{}, velocity{}; double rho=1; };
struct Config {
    Json source;
    fs::path path;
    std::string name;
    bool si=false;
    std::array<unsigned,3> cells{};
    Vec origin{};
    double dx=1, dt=1, reference_density=1, nu=0, rho=1;
    Vec velocity{};
    std::vector<InitialRegion> regions;
    std::vector<Geometry> geometry;
    std::vector<Boundary> boundaries;
    std::array<bool,3> periodic{};
    unsigned long long steps=0, monitor_every=100, vtk_every=0;
    bool initial_output=true;
    std::vector<std::string> vtk_fields{"u","rho","flags"};
    Json resolved;
};
void require(bool ok, const std::string& message);
double number(const Json& j, const std::string& where);
void save_json(const fs::path& path, const Json& value);
std::string sha256(const fs::path& path);
Config read_config(const fs::path& path);
Json capabilities();
int entry(int argc, char* argv[]);
}
