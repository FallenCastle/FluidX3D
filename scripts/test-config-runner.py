"""NUC-only integration and numerical checks; creates retained, isolated run artifacts."""
import argparse
import array
import copy
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import subprocess
import sys


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def vtk(path):
    header, payload = path.read_bytes().split(b"LOOKUP_TABLE default\n", 1)
    lines = header.decode("ascii").splitlines()
    dimensions = tuple(map(int, next(x for x in lines if x.startswith("DIMENSIONS ")).split()[1:]))
    origin = tuple(map(float, next(x for x in lines if x.startswith("ORIGIN ")).split()[1:]))
    spacing = tuple(map(float, next(x for x in lines if x.startswith("SPACING ")).split()[1:]))
    scalar = next(x for x in lines if x.startswith("SCALARS ")).split()
    components = int(scalar[3])
    size = math.prod(dimensions) * components
    assert len(payload) == size * (1 if scalar[2] == "unsigned_char" else 4), path
    values = array.array("B" if scalar[2] == "unsigned_char" else "f")
    values.frombytes(payload)
    if scalar[2] != "unsigned_char" and sys.byteorder == "little":
        values.byteswap()
    return {"dimensions": dimensions, "origin": origin, "spacing": spacing,
            "values": values, "payload": payload}


def cube(path):
    vertices = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]
    triangles = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7),
                 (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
                 (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    with path.open("wb") as out:
        out.write(b"generated cube".ljust(80, b"\0") + struct.pack("<I", len(triangles)))
        for triangle in triangles:
            xyz = [v for index in triangle for v in vertices[index]]
            out.write(struct.pack("<12fH", 0, 0, 0, *xyz, 0))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--build-name", default="config-runner")
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run integration and numerical tests on the Windows NUC only")
    workspace = Path(args.workspace_root)
    repo = workspace / "src"
    exe = workspace / "bin" / args.build_name / "FluidX3D.exe"
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = workspace / "workingdir" / "config-validation" / now
    root.mkdir(parents=True, exist_ok=False)
    tests = []
    report = {"executable_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
              "build": json.loads((exe.parent / "build.json").read_text(encoding="utf-8-sig")),
              "tests": tests, "status": "running"}
    write_json(root / "report.json", report)

    def invoke(name, config=None, *, success=True, options=(), raw=None, expected_error=None):
        directory = root / name
        directory.mkdir()
        config_path = directory / "case.json"
        if raw is not None:
            config_path.write_text(raw, encoding="utf-8")
        elif config is not None:
            write_json(config_path, config)
        command = [str(exe)]
        if config is not None or raw is not None:
            command += ["--config", str(config_path), "--device", args.device,
                        "--output", str(directory / "results")]
        command += list(options)
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            completed = subprocess.run(command, cwd=workspace, stdout=stdout, stderr=stderr, timeout=180)
        tests.append({"name": name, "exit_code": completed.returncode, "expected_success": success})
        assert (completed.returncode == 0) == success, f"{name}: inspect {directory}"
        if expected_error:
            error = (directory / "stderr.log").read_text(encoding="utf-8", errors="replace")
            assert expected_error.lower() in error.lower(), (name, error)
        write_json(root / "report.json", report)
        return directory / "results"

    def example(name):
        return json.loads((repo / "configs" / name).read_text(encoding="utf-8"))

    try:
        invoke("help", options=("--help",))
        invoke("capabilities", options=("--capabilities",))
        invoke("devices", options=("--list-devices",))
        lattice = example("periodic-lattice.json")
        invoke("validate", lattice, options=("--validate",))
        invalid = copy.deepcopy(lattice); invalid["typo"] = 1
        invoke("unknown", invalid, success=False, expected_error="unknown field")
        invalid = copy.deepcopy(lattice); invalid["solver"] = {"collision": "MRT"}
        invoke("unsupported", invalid, success=False, expected_error="Unsupported solver")
        invalid = copy.deepcopy(lattice); invalid["fluid"]["nu"] = -1
        invoke("negative-nu", invalid, success=False, expected_error="positive")
        invalid = copy.deepcopy(lattice); invalid["domain"]["cells"][0] = 2
        invoke("small-grid", invalid, success=False, expected_error="at least 3")
        invalid = copy.deepcopy(lattice); invalid["units"]["dt"] = 0.1
        invoke("mixed-units", invalid, success=False, expected_error="SI scale")
        raw = json.dumps(lattice).replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
        invoke("duplicate", raw=raw, success=False, expected_error="Duplicate JSON key")
        invalid = copy.deepcopy(lattice); invalid["boundaries"][0]["faces"].remove("xmax")
        invalid["boundaries"].append({"id": "wall", "faces": ["xmax"], "type": "no_slip"})
        invoke("unpaired-periodic", invalid, success=False, expected_error="paired")
        invalid = copy.deepcopy(lattice); invalid["boundaries"] = [
            {"id": "all-wall", "type": "no_slip", "faces": lattice["boundaries"][0]["faces"]},
            {"id": "inlet", "type": "equilibrium", "faces": ["xmin"], "rho": 1, "velocity": [0.03, 0, 0]}]
        invoke("conflict", invalid, success=False, expected_error="Conflicting")
        invalid["boundaries"][1]["priority"] = 1
        invoke("priority", invalid, options=("--prepare-only",))
        periodic = invoke("periodic", lattice)
        completion = json.loads((periodic / "completion.json").read_text())
        assert completion["steps"] == 23 and completion["status"] == "succeeded"
        assert sorted(int(p.stem.split("-")[-1]) for p in periodic.glob("u-*.vtk")) == [0, 7, 14, 21, 23]
        u0 = vtk(periodic / "u-000000000.vtk"); uf = vtk(periodic / "u-000000023.vtk")
        assert max(abs(a-b) for a,b in zip(u0["values"],uf["values"])) < 1e-6
        # FP16S stores shifted populations in half precision. Uniform fields remain
        # spatially constant, but their reconstructed density need not equal 1 to
        # FP32 precision. Bound this case's density/mass drift at 1e-4 relative.
        density_final = vtk(periodic / "rho-000000023.vtk")["values"]
        assert max(density_final) == min(density_final)
        assert max(abs(v-1) for v in density_final) < 1e-4
        assert max(abs(v-expected) for v,expected in zip(uf["values"], [0.03,0,0]*4096)) < 1e-5
        assert u0["origin"] == (0.5, 0.5, 0.5)
        si = invoke("SI 中文 paths", example("periodic-si.json"))
        su = vtk(si / "u-000000023.vtk")
        assert su["origin"] == (0.005, 0.005, 0.005) and su["spacing"] == (0.01,)*3
        assert max(abs(a-b*0.003/0.01) for a,b in zip(uf["values"],su["values"])) < 1e-7
        si_density = vtk(si / "rho-000000023.vtk")["values"]
        assert max(abs(v-1000) for v in si_density) < 0.1
        assert max(abs(a-b/1000) for a,b in zip(density_final,si_density)) < 1e-7
        sr = example("periodic-si.json"); sr["units"].pop("dt")
        sr["units"].update(reference_velocity=0.1, lattice_velocity=0.03)
        sr["run"] = {"duration": 0.069, "monitor_every": 7}
        timed = invoke("si-time-reference", sr)
        assert json.loads((timed / "completion.json").read_text())["steps"] == 23
        inv = copy.deepcopy(lattice)
        inv["geometry"] = [{"id": "missing", "file": str(root/"missing.stl"),
                            "transform": {"mode":"fit", "size": 6, "center":[8,8,8]}}]
        invoke("missing-stl", inv, success=False, expected_error="STL not found")
        bad = root / "bad.stl"; bad.write_bytes(b"not an stl")
        inv["geometry"][0]["file"] = str(bad)
        invoke("bad-stl", inv, success=False, expected_error="Truncated STL")
        asset = root / "cube.stl"; cube(asset)
        geo = copy.deepcopy(lattice)
        geo["geometry"] = [{"id":"cube", "file":str(asset),
                            "transform":{"mode":"scale", "factor":6, "translation":[3,3,3]}}]
        prepared = invoke("cube-a", geo, options=("--prepare-only",))
        assert json.loads((prepared / "completion.json").read_text())["steps"] == 0
        af = vtk(prepared / "flags-000000000.vtk")["values"]
        occupied = [(i%16,(i//16)%16,i//256) for i,v in enumerate(af) if v&1]
        assert occupied and all(all(3 <= x <= 8 for x in p) for p in occupied), occupied[:10]
        geo2 = copy.deepcopy(geo);geo2["geometry"][0]["transform"]["translation"]=[6,4,4]
        prepared2 = invoke("cube-b",geo2,options=("--prepare-only",))
        bf=vtk(prepared2 / "flags-000000000.vtk")["values"]
        both=copy.deepcopy(geo);both["geometry"].append(geo2["geometry"][0]);both["geometry"][1]["id"]="cube-b"
        union=invoke("cube-union",both,options=("--prepare-only",))
        cf=vtk(union / "flags-000000000.vtk")["values"]
        assert all(bool(c&1)==bool((a|b)&1) for a,b,c in zip(af,bf,cf)), "STL union lost cells"
        shifted=copy.deepcopy(geo);shifted["domain"]["origin"]=[10,20,30]
        shifted["geometry"][0]["transform"]["translation"]=[13,23,33]
        shifted_result=invoke("translated-origin",shifted,options=("--prepare-only",))
        vf=vtk(shifted_result/"flags-000000000.vtk")
        assert vf["values"]==af and vf["origin"]==(10.5,20.5,30.5)
        distant=copy.deepcopy(geo);distant["domain"]["origin"]=[1e9,1e9,1e9]
        distant["geometry"][0]["transform"]["translation"]=[1e9+3]*3
        distant_result=invoke("distant-origin",distant,options=("--prepare-only",))
        assert vtk(distant_result/"flags-000000000.vtk")["values"]==af
        local=copy.deepcopy(lattice)
        local["boundaries"]=[{"id":"walls","faces":lattice["boundaries"][0]["faces"],"type":"no_slip"},
            {"id":"patch","faces":["xmin"],"type":"equilibrium","priority":1,
             "region":{"min":[4,4],"max":[12,12]},"rho":1,"velocity":[0.03,0,0]}]
        patch=invoke("local-boundary",local,options=("--prepare-only",))
        pf=vtk(patch/"flags-000000000.vtk")["values"]
        assert sum(v==2 for v in pf)==64
        assert all(pf[16*y+256*z]==2 for y in range(4,12) for z in range(4,12))
        outside=copy.deepcopy(geo);outside["geometry"][0]["transform"]["translation"]=[-5,3,3]
        invoke("outside",outside,success=False,expected_error="outside domain")
        # Snapshot input geometry and configuration are sufficient for a repeat run.
        repeated=invoke("snapshot-repeat",options=("--config",str(union/"effective-config.json"),
                        "--device",args.device,"--prepare-only","--output",str(root/"snapshot-repeated-results")))
        assert vtk(root/"snapshot-repeated-results"/"flags-000000000.vtk")["values"]==cf
        invoke("occupied-output", options=("--config",str(union/"effective-config.json"),
               "--output",str(union)),success=False,expected_error="must be empty")
        for name, template in [("boeing","boeing-regression.json"),("ahmed","ahmed-smoke.json")]:
            cfg=example(template)
            for geometry in cfg["geometry"]:
                geometry["file"]=str((repo/"configs"/geometry["file"]).resolve())
            result=invoke(name,cfg)
            resolved=json.loads((result/"resolved-config.json").read_text())
            done=json.loads((result/"completion.json").read_text())
            assert done["steps"]==cfg["run"]["steps"] and resolved["solid_cells"]>0
            assert json.loads((result/"manifest.json").read_text())["executable_sha256"]==report["executable_sha256"]
            if name=="boeing":
                assert resolved["cells"]==[170,339,85]
                runs=sorted((workspace/"workingdir"/"config-baseline-boeing").glob("*/run.json"))
                baseline_record=json.loads(runs[-1].read_text(encoding="utf-8-sig"))
                assert baseline_record["status"]=="succeeded"
                baseline=runs[-1].parent/"results"
                comparisons=[]
                for step in (0,1000):
                    for field in ("flags","rho","u"):
                        filename=f"{field}-{step:09d}.vtk"
                        before=vtk(baseline/filename);after=vtk(result/filename)
                        equal=before["payload"]==after["payload"]
                        comparison={"file":filename,"payload_exact":equal}
                        if not equal:
                            comparison["max_absolute_difference"]=max(abs(a-b) for a,b in zip(before["values"],after["values"]))
                        comparisons.append(comparison)
                        write_json(root/"baseline-comparison.json",comparisons)
                        assert equal, f"Boeing baseline differs: {comparison}"
                report["baseline_run"]=str(runs[-1].parent)
        report["status"]="succeeded"
    except Exception as exc:
        report["status"]="failed";report["error"]=str(exc)
        raise
    finally:
        write_json(root/"report.json",report)
        print(root,flush=True)


if __name__ == "__main__":
    main()
