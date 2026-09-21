#include "config.hpp"
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
void require(bool ok, const std::string& message) { if(!ok) throw std::runtime_error(message); }
static void keys(const Json& j, std::initializer_list<const char*> names, const std::string& at) {
    require(j.is_object(), at+": expected an object");
    std::set<std::string> allowed; for(auto name:names) allowed.insert(name);
    for(auto it=j.begin();it!=j.end();++it) require(allowed.count(it.key())!=0, at+": unknown field '"+it.key()+"'");
}
static const Json& field(const Json& j, const char* name) {
    require(j.contains(name), std::string("Missing required field: ")+name); return j.at(name);
}
static std::string string_value(const Json& j, const std::string& at) {
    require(j.is_string(), at+": expected a string"); return j.get<std::string>();
}
double number(const Json& j, const std::string& at) {
    require(j.is_number(), at+": expected a number");
    double x=j.get<double>(); require(std::isfinite(x),at+": must be finite"); return x;
}
static double positive(const Json& j, const std::string& at) { double x=number(j,at); require(x>0,at+": must be positive");return x; }
static unsigned long long integer(const Json& j, const std::string& at, bool zero=false) {
    require(j.is_number_integer(),at+": expected an integer");
    require(j.is_number_unsigned() || j.get<long long>()>=0,at+": must be nonnegative");
    auto x=j.get<unsigned long long>(); require((zero||x>0)&&x<=9007199254740991ull,at+": integer outside supported range");return x;
}
static Vec vec(const Json& j, const std::string& at) {
    require(j.is_array()&&j.size()==3,at+": expected three coordinates");return {number(j[0],at),number(j[1],at),number(j[2],at)};
}
static void finite_float(double x, const std::string& at, bool pos=false) {
    require(std::isfinite(x)&&std::abs(x)<=std::numeric_limits<float>::max(),at+": outside float range");
    if(pos) require(static_cast<float>(x)>0,at+": underflow or non-positive value");
}
void save_json(const fs::path& path,const Json& j) {
    std::ofstream out(path,std::ios::binary); require(bool(out),"Cannot write "+path.u8string());
    out<<j.dump(2)<<'\n'; out.close(); require(bool(out),"Cannot finish writing "+path.u8string());
}
std::string sha256(const fs::path& path) {
#ifdef _WIN32
    HCRYPTPROV provider=0; HCRYPTHASH hash=0;
    require(CryptAcquireContextW(&provider,nullptr,nullptr,PROV_RSA_AES,CRYPT_VERIFYCONTEXT)!=0,"SHA256 provider failure");
    if(!CryptCreateHash(provider,CALG_SHA_256,0,0,&hash)) { CryptReleaseContext(provider,0); throw std::runtime_error("SHA256 hash failure"); }
    try {
        std::ifstream in(path,std::ios::binary); require(bool(in),"Cannot hash "+path.u8string());
        char block[65536]; while(in) { in.read(block,sizeof(block)); auto n=in.gcount(); if(n>0) require(CryptHashData(hash,reinterpret_cast<BYTE*>(block),static_cast<DWORD>(n),0)!=0,"SHA256 update failure"); }
        require(in.eof(),"Hash input read failure");
        BYTE result[32]; DWORD count=32;
        require(CryptGetHashParam(hash,HP_HASHVAL,result,&count,0)!=0&&count==32,"SHA256 result failure");
        std::ostringstream out;out<<std::hex<<std::setfill('0');for(auto v:result) out<<std::setw(2)<<unsigned(v);
        CryptDestroyHash(hash);CryptReleaseContext(provider,0);return out.str();
    } catch(...) {CryptDestroyHash(hash);CryptReleaseContext(provider,0);throw;}
#else
    throw std::runtime_error("Configuration runner hashing currently requires the Windows NUC build");
#endif
}
Json capabilities() {
    return {{"schema_version",1},{"lattice","D3Q19"},{"collision","SRT"},{"storage","FP16S"},
        {"turbulence","smagorinsky"},{"units",{"lattice","si"}},{"boundaries",{"no_slip","equilibrium","periodic"}},
        {"geometry","binary STL static union"},{"outputs",{"VTK","CSV","JSON"}},{"graphics",false},{"devices_per_run",1}};
}
Config read_config(const fs::path& path) {
    Config c;c.path=fs::absolute(path);
    std::ifstream input(c.path,std::ios::binary);require(bool(input),"Cannot open config: "+c.path.u8string());
    std::vector<std::set<std::string>> objects;
    auto callback=[&](int,nlohmann::json::parse_event_t event,Json& value) {
        if(event==Json::parse_event_t::object_start) objects.emplace_back();
        if(event==Json::parse_event_t::key) require(objects.back().insert(value.get<std::string>()).second,"Duplicate JSON key: "+value.get<std::string>());
        if(event==Json::parse_event_t::object_end) objects.pop_back();return true;
    };
    c.source=Json::parse(input,callback); const auto& j=c.source;
    keys(j,{"schema_version","case","solver","units","domain","fluid","initial","geometry","boundaries","run","output"},"config");
    require(integer(field(j,"schema_version"),"schema_version")==1,"Unsupported schema_version");
    const auto& ca=field(j,"case");keys(ca,{"name"},"case");c.name=string_value(field(ca,"name"),"case.name");require(!c.name.empty(),"Empty case name");
    if(j.contains("solver")) {
        keys(j["solver"],{"lattice","collision","storage","turbulence"},"solver");auto cap=capabilities();
        for(auto it=j["solver"].begin();it!=j["solver"].end();++it) require(it.value()==cap[it.key()],"Unsupported solver."+it.key()+"; use --capabilities");
    }
    const auto& u=field(j,"units");keys(u,{"mode","reference_density","dt","reference_velocity","lattice_velocity"},"units");
    auto mode=string_value(field(u,"mode"),"units.mode");require(mode=="si"||mode=="lattice","units.mode must be si or lattice");c.si=mode=="si";
    const auto& d=field(j,"domain");keys(d,{"cells","aspect_ratio","memory_budget_mb","length","dx","origin"},"domain");
    if(d.contains("origin")) c.origin=vec(d["origin"],"domain.origin");
    if(c.si) {
        require(!d.contains("cells")&&!d.contains("aspect_ratio")&&!d.contains("memory_budget_mb"),"SI domain requires length and dx only");
        c.dx=positive(field(d,"dx"),"domain.dx");auto length=vec(field(d,"length"),"domain.length");
        for(int a=0;a<3;a++) { double n=length[a]/c.dx; require(n>0&&std::isfinite(n)&&n<=1000000,"Invalid domain length/dx"); double nearest=std::round(n); if(std::abs(n-nearest)<1e-10*std::max(1.0,n))n=nearest;c.cells[a]=static_cast<unsigned>(std::ceil(n)); }
        c.reference_density=positive(field(u,"reference_density"),"units.reference_density");
        if(u.contains("dt")) { require(!u.contains("reference_velocity")&&!u.contains("lattice_velocity"),"Choose dt or velocity time scaling");c.dt=positive(u["dt"],"units.dt"); }
        else c.dt=positive(field(u,"lattice_velocity"),"units.lattice_velocity")*c.dx/positive(field(u,"reference_velocity"),"units.reference_velocity");
    } else {
        require(u.size()==1,"Lattice units do not accept SI scale fields");require(!d.contains("length")&&!d.contains("dx"),"Lattice domain uses cells or memory budget");
        if(d.contains("cells")) {
            require(!d.contains("aspect_ratio")&&!d.contains("memory_budget_mb"),"Choose cells or memory budget");const auto& ns=d["cells"];require(ns.is_array()&&ns.size()==3,"domain.cells requires three integers");
            for(int a=0;a<3;a++) {auto n=integer(ns[a],"domain.cells");require(n<=1000000,"domain.cells exceeds supported dimension");c.cells[a]=static_cast<unsigned>(n);}
        } else {
            auto aspect=vec(field(d,"aspect_ratio"),"domain.aspect_ratio");auto mb=integer(field(d,"memory_budget_mb"),"domain.memory_budget_mb");require(mb<=1048576,"Memory budget too large");
            for(auto v:aspect) require(v>0&&v<1e6,"Invalid aspect ratio");
            // Match the upstream float calculation and nearest-integer conversion.
            float ax=static_cast<float>(aspect[0]),ay=static_cast<float>(aspect[1]),az=static_cast<float>(aspect[2]);
            float bytes=ax*ay*az*55.0f/1048576.0f;float scale=std::cbrt(static_cast<float>(mb)/bytes);
            for(int a=0;a<3;a++) {double n=static_cast<float>(scale*static_cast<float>(aspect[a]))+0.5f;require(std::isfinite(n)&&n<=1000000,"Invalid memory-derived dimension");c.cells[a]=static_cast<unsigned>(n);}
        }
    }
    for(auto n:c.cells)require(n>=3,"Each domain dimension must be at least 3");
    unsigned long long count=1;for(auto n:c.cells) {require(count<=std::numeric_limits<unsigned long long>::max()/n,"Grid product overflow");count*=n;}
    require(count<=std::numeric_limits<size_t>::max()/64&&count<=10000000000ull,"Grid exceeds supported allocation range");
    require(std::isfinite(c.dt)&&c.dt>0,"Invalid dt");
    const auto& f=field(j,"fluid");keys(f,{"rho","nu","reynolds","reference_length","reference_velocity"},"fluid");
    double density=positive(field(f,"rho"),"fluid.rho");c.rho=density/c.reference_density;
    double viscosity;
    if(f.contains("nu")) {require(!f.contains("reynolds")&&!f.contains("reference_length")&&!f.contains("reference_velocity"),"Choose nu or Reynolds mode");viscosity=positive(f["nu"],"fluid.nu");}
    else viscosity=positive(field(f,"reference_velocity"),"fluid.reference_velocity")*positive(field(f,"reference_length"),"fluid.reference_length")/positive(field(f,"reynolds"),"fluid.reynolds");
    c.nu=viscosity*c.dt/(c.dx*c.dx);finite_float(c.nu,"lattice viscosity",true);finite_float(c.rho,"lattice density",true);
    auto velocity=[&](const Json& v,const std::string& at){Vec out=vec(v,at);for(auto& x:out){x=x*c.dt/c.dx;finite_float(x,at);}return out;};
    const auto& init=field(j,"initial");keys(init,{"rho","velocity","regions"},"initial");
    c.velocity=velocity(field(init,"velocity"),"initial.velocity");if(init.contains("rho"))c.rho=positive(init["rho"],"initial.rho")/c.reference_density;
    finite_float(c.rho,"initial lattice density",true);
    if(init.contains("regions")) {
        require(init["regions"].is_array(),"initial.regions must be an array");
        for(const auto& r:init["regions"]) {keys(r,{"box_min","box_max","rho","velocity"},"initial region");InitialRegion region;region.lower=vec(field(r,"box_min"),"box_min");region.upper=vec(field(r,"box_max"),"box_max");region.rho=positive(field(r,"rho"),"region.rho")/c.reference_density;finite_float(region.rho,"region.rho",true);region.velocity=velocity(field(r,"velocity"),"region.velocity");for(int a=0;a<3;a++) require(region.lower[a]<=region.upper[a],"Reversed initial region");c.regions.push_back(region);}
    }
    const auto& gs=field(j,"geometry");require(gs.is_array(),"geometry must be an array");std::set<std::string> ids;
    for(const auto& g:gs) {
        keys(g,{"id","file","transform"},"geometry");Geometry geo;geo.id=string_value(field(g,"id"),"geometry.id");require(!geo.id.empty()&&ids.insert(geo.id).second,"Empty/duplicate geometry ID");geo.file=fs::absolute(c.path.parent_path()/fs::u8path(string_value(field(g,"file"),"geometry.file")));
        const auto& t=field(g,"transform");keys(t,{"mode","size","center","factor","pivot","translation","axis","degrees"},"transform");geo.mode=string_value(field(t,"mode"),"transform.mode");
        if(t.contains("axis"))geo.axis=vec(t["axis"],"transform.axis");if(t.contains("degrees"))geo.degrees=number(t["degrees"],"transform.degrees");
        double norm=std::hypot(geo.axis[0],std::hypot(geo.axis[1],geo.axis[2]));require(std::isfinite(norm)&&norm>0,"Rotation axis must be nonzero");for(auto& v:geo.axis)v/=norm;
        if(geo.mode=="fit") {require(!t.contains("factor")&&!t.contains("pivot")&&!t.contains("translation"),"fit uses size and center");geo.size=positive(field(t,"size"),"transform.size");geo.center=vec(field(t,"center"),"transform.center");}
        else {require(geo.mode=="scale","transform.mode must be fit or scale");require(!t.contains("size")&&!t.contains("center"),"scale uses factor, pivot and translation");geo.factor=positive(field(t,"factor"),"transform.factor");geo.pivot=t.contains("pivot")?vec(t["pivot"],"transform.pivot"):Vec{};geo.translation=vec(field(t,"translation"),"transform.translation");}
        require(fs::is_regular_file(geo.file),"STL not found: "+geo.file.u8string());c.geometry.push_back(geo);
    }
    const auto& bs=field(j,"boundaries");require(bs.is_array(),"boundaries must be an array");ids.clear();
    const std::array<std::string,6> names{"xmin","xmax","ymin","ymax","zmin","zmax"};std::array<int,6> topology{};
    for(const auto& b:bs) {
        keys(b,{"id","faces","type","priority","region","rho","velocity"},"boundary");Boundary bound;bound.id=string_value(field(b,"id"),"boundary.id");require(!bound.id.empty()&&ids.insert(bound.id).second,"Empty/duplicate boundary ID");bound.type=string_value(field(b,"type"),"boundary.type");require(bound.type=="periodic"||bound.type=="equilibrium"||bound.type=="no_slip","Unsupported boundary type");
        if(b.contains("priority")){require(b["priority"].is_number_integer(),"priority must be integer");double p=number(b["priority"],"priority");require(p>=-1000000&&p<=1000000,"priority out of range");bound.priority=static_cast<int>(p);}
        auto& faces=field(b,"faces");require(faces.is_array()&&!faces.empty(),"boundary.faces must be nonempty");std::set<int> unique;
        for(const auto& face:faces) {auto name=string_value(face,"face");auto it=std::find(names.begin(),names.end(),name);require(it!=names.end(),"Unknown face: "+name);int index=static_cast<int>(it-names.begin());require(unique.insert(index).second,"Duplicate face");bound.faces.push_back(index);topology[index]|=bound.type=="periodic"?1:2;}
        if(b.contains("region")) {require(bound.type!="periodic","Periodic boundaries must cover entire axes");keys(b["region"],{"min","max"},"boundary.region");const auto& lo=field(b["region"],"min");const auto& hi=field(b["region"],"max");require(lo.is_array()&&hi.is_array()&&lo.size()==2&&hi.size()==2,"region requires two tangential coordinates");for(int a=0;a<2;a++){bound.lower[a]=number(lo[a],"region.min");bound.upper[a]=number(hi[a],"region.max");require(bound.lower[a]<=bound.upper[a],"Reversed boundary region");}bound.region=true;}
        if(bound.type=="equilibrium") {bound.rho=positive(field(b,"rho"),"boundary.rho")/c.reference_density;finite_float(bound.rho,"boundary.rho",true);bound.velocity=velocity(field(b,"velocity"),"boundary.velocity");}
        else require(!b.contains("rho")&&!b.contains("velocity"),"Only equilibrium accepts rho/velocity");c.boundaries.push_back(bound);
    }
    for(int a=0;a<3;a++){require(topology[2*a]&&topology[2*a+1],"All six faces must be declared");require(topology[2*a]!=3&&topology[2*a+1]!=3,"Periodic face conflicts with boundary rules");require((topology[2*a]==1)==(topology[2*a+1]==1),"Periodic axes must be paired");c.periodic[a]=topology[2*a]==1;}
    const auto& run=field(j,"run");keys(run,{"steps","duration","monitor_every"},"run");require(run.contains("steps")!=run.contains("duration"),"Choose steps or duration");
    if(run.contains("steps"))c.steps=integer(run["steps"],"run.steps");else {require(c.si,"duration requires SI units");double steps=std::ceil(positive(run["duration"],"run.duration")/c.dt);require(std::isfinite(steps)&&steps>=1&&steps<=9007199254740991.,"duration/dt outside supported range");c.steps=static_cast<unsigned long long>(steps);}
    if(run.contains("monitor_every"))c.monitor_every=integer(run["monitor_every"],"monitor_every");
    if(j.contains("output")) {const auto& out=j["output"];keys(out,{"vtk_fields","vtk_every","initial"},"output");if(out.contains("vtk_every"))c.vtk_every=integer(out["vtk_every"],"vtk_every",true);if(out.contains("initial")){require(out["initial"].is_boolean(),"output.initial must be boolean");c.initial_output=out["initial"].get<bool>();}if(out.contains("vtk_fields")){require(out["vtk_fields"].is_array()&&!out["vtk_fields"].empty(),"vtk_fields must be nonempty");c.vtk_fields.clear();std::set<std::string> unique;for(const auto& item:out["vtk_fields"]){auto name=string_value(item,"vtk_fields");require(name=="u"||name=="rho"||name=="flags","Unknown output field");require(unique.insert(name).second,"Duplicate output field");c.vtk_fields.push_back(name);}}}
    double umax=0;auto speed=[&](const Vec& v){return std::hypot(v[0],std::hypot(v[1],v[2]));};umax=speed(c.velocity);for(const auto& b:c.boundaries)umax=std::max(umax,speed(b.velocity));for(const auto& r:c.regions)umax=std::max(umax,speed(r.velocity));
    require(static_cast<float>(0.5+3*c.nu)>0.5f,"Viscosity is too small to represent a relaxation time above 0.5");
    c.resolved={{"schema_version",1},{"case",c.name},{"capabilities",capabilities()},{"cells",c.cells},{"dx",c.dx},{"dt",c.dt},{"reference_density",c.reference_density},{"origin",c.origin},{"lattice_nu",c.nu},{"initial_lattice_rho",c.rho},{"initial_lattice_velocity",c.velocity},{"tau",0.5+3*c.nu},{"max_prescribed_mach",umax*std::sqrt(3.0)},{"steps",c.steps},{"actual_duration",c.steps*c.dt},{"device_field_bytes",count*55},{"host_field_and_union_bytes",count*18},{"actual_domain_length",{c.cells[0]*c.dx,c.cells[1]*c.dx,c.cells[2]*c.dx}}};
    return c;
}
}
