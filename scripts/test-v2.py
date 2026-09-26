"""NUC-only Solver-IBM V2 feature-combination and FP32 model-matrix acceptance."""
import argparse
import copy
import csv
import datetime
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def finite_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert rows, path
    for row in rows:
        for key, value in row.items():
            if key in {"boundary_id", "boundary_type", "geometry_id"} or value in {"", "nan", "-nan"}:
                continue
            assert math.isfinite(float(value)), (path, key, value)
    return rows


def absolute_assets(config, configs_root):
    for geometry in config.get("geometry", []):
        source = Path(geometry["file"])
        if not source.is_absolute():
            geometry["file"] = str((configs_root / source).resolve())
    for region in config.get("initial", {}).get("liquid_regions", []):
        if region.get("shape") == "stl":
            source = Path(region["file"])
            if not source.is_absolute():
                region["file"] = str((configs_root / source).resolve())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--build-name", default="solver-ibm-v1.1.0-dev")
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--device", default="0")
    parser.add_argument("--steps", type=int, default=8)
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run on the Windows NUC only")
    assert args.steps > 0
    workspace = args.workspace_root.resolve()
    repository = (args.repository_root or workspace / "src").resolve()
    configs_root = repository / "configs"
    executable = (args.executable or workspace / "bin" / args.build_name / "Solver-IBM.exe").resolve()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = workspace / "workingdir" / "v2-validation" / stamp
    root.mkdir(parents=True)
    build = read(executable.parent / "build.json")
    executable_hash = sha256(executable)
    assert build["status"] == "succeeded" and build["executableSha256"] == executable_hash
    report = {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "build": build,
        "executable_sha256": executable_hash,
        "device": args.device,
        "matrix": [],
    }
    write(root / "report.json", report)
    features = [
        ("thermal", "thermal-diffusion-lattice.json"),
        ("free-surface", "free-surface-dam-break-lattice.json"),
        ("dynamic-stl", "dynamic-translation-stop-lattice.json"),
        ("thermal+free-surface", "thermal-free-surface-smoke.json"),
        ("thermal+dynamic-stl", "dynamic-thermal-cycle-lattice.json"),
        ("free-surface+dynamic-stl", "dynamic-water-entry-lattice.json"),
        ("thermal+free-surface+dynamic-stl", "thermal-free-surface-dynamic-cycle-lattice.json"),
    ]
    models = itertools.product(["D3Q19", "D3Q27"], ["SRT", "TRT"], ["none", "smagorinsky"])
    try:
        capabilities = json.loads(subprocess.check_output([str(executable), "--capabilities"], text=True))
        assert capabilities["lattice"] == ["D3Q19", "D3Q27"]
        assert capabilities["collision"] == ["SRT", "TRT"]
        assert capabilities["turbulence"] == ["none", "smagorinsky"]
        report["capabilities"] = capabilities
        for lattice, collision, turbulence in models:
            model = {
                "lattice": lattice,
                "collision": collision,
                "storage": "FP32",
                "turbulence": turbulence,
            }
            for feature, filename in features:
                tag = "-".join([feature.replace("+", "_"), lattice, collision, turbulence])
                folder = root / tag
                folder.mkdir()
                config = copy.deepcopy(read(configs_root / filename))
                absolute_assets(config, configs_root)
                config["case"]["name"] = "v2-matrix-" + tag
                config["solver"] = model
                config["run"] = {"steps": args.steps, "monitor_every": args.steps}
                config["output"] = {"vtk_fields": ["flags"], "vtk_every": 0, "initial": False}
                config_path = folder / "case.json"
                write(config_path, config)
                started = time.perf_counter()
                with (folder / "stdout.log").open("wb") as stdout, (folder / "stderr.log").open("wb") as stderr:
                    process = subprocess.run(
                        [str(executable), "--config", str(config_path), "--output", str(folder / "results"),
                         "--device", args.device],
                        cwd=folder, stdout=stdout, stderr=stderr, timeout=300,
                    )
                elapsed = time.perf_counter() - started
                row = {"feature": feature, "solver": model, "status": "failed", "exit_code": process.returncode,
                       "elapsed_seconds": elapsed, "results": str(folder / "results")}
                report["matrix"].append(row)
                write(root / "report.json", report)
                assert process.returncode == 0, tag
                completion = read(folder / "results" / "completion.json")
                resolved = read(folder / "results" / "resolved-config.json")
                assert completion["status"] == "succeeded" and completion["steps"] == args.steps
                assert all(resolved["solver"][key] == value for key, value in model.items())
                finite_csv(folder / "results" / "monitor.csv")
                if resolved["solver"]["physics"]["free_surface"]:
                    finite_csv(folder / "results" / "free-surface.csv")
                if resolved["solver"]["physics"]["free_surface"] or resolved["solver"]["physics"]["thermal"]:
                    finite_csv(folder / "results" / "conservation-budget.csv")
                if resolved["solver"]["physics"]["dynamic_geometry"]:
                    finite_csv(folder / "results" / "object-motion.csv")
                row["status"] = "succeeded"
                print(tag, "succeeded", flush=True)
        assert len(report["matrix"]) == 56 and all(row["status"] == "succeeded" for row in report["matrix"])
        report["status"] = "succeeded"
        report["completed_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    except Exception as error:
        report["status"] = "failed"
        report["error"] = repr(error)
        raise
    finally:
        write(root / "report.json", report)
        print(root / "report.json", flush=True)


if __name__ == "__main__":
    main()
