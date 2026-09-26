"""NUC-only Solver-IBM V2 scenario and external-benchmark acceptance suite."""
import argparse
import copy
import csv
import datetime
import hashlib
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


def csv_rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


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


def finite_table(path, text_columns=()):
    records = csv_rows(path)
    assert records, path
    for row in records:
        for key, value in row.items():
            if key in text_columns:
                continue
            assert value not in {"", "nan", "-nan"} and math.isfinite(float(value)), (path, key, value)
    return records


def final_budget(result):
    records = csv_rows(result / "conservation-budget.csv")
    assert records
    return {key: float(value) for key, value in records[-1].items() if key not in {"step", "time"}}


def row_at(records, step, geometry=None):
    matches = [row for row in records if int(row["step"]) == step and
               (geometry is None or row.get("geometry_id") == geometry)]
    assert len(matches) == 1, (step, geometry, len(matches))
    return matches[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--build-name", required=True)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run on the Windows NUC only")
    workspace = args.workspace_root.resolve()
    repository = (args.repository_root or workspace / "src").resolve()
    configs = repository / "configs"
    executable = (args.executable or workspace / "bin" / args.build_name / "Solver-IBM.exe").resolve()
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    root = workspace / "workingdir" / "v2-scenarios" / stamp
    root.mkdir(parents=True)
    report = {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "build": read(executable.parent / "build.json"),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "device": args.device,
        "thresholds": {
            "marin_level_rmse_fraction_of_initial_depth": 0.20,
            "marin_arrival_time_seconds": 0.15,
            "closed_liquid_mass_fraction": 0.001,
            "sensible_energy_fraction": 0.005,
            "prescribed_pose_absolute": 1e-9,
            "known_flux_relative": 1e-5,
        },
        "tests": [],
    }
    assert report["build"]["executableSha256"] == report["executable_sha256"]
    write(root / "report.json", report)

    def invoke(name, config, timeout=1800):
        directory = root / name
        directory.mkdir()
        config = copy.deepcopy(config)
        absolute_assets(config, configs)
        config_path = directory / "case.json"
        write(config_path, config)
        started = time.perf_counter()
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            process = subprocess.run(
                [str(executable), "--config", str(config_path), "--output", str(directory / "results"),
                 "--device", args.device], cwd=directory, stdout=stdout, stderr=stderr, timeout=timeout)
        entry = {"name": name, "status": "failed", "exit_code": process.returncode,
                 "elapsed_seconds": time.perf_counter() - started, "results": str(directory / "results")}
        report["tests"].append(entry)
        write(root / "report.json", report)
        assert process.returncode == 0, name
        completion = read(directory / "results" / "completion.json")
        assert completion["status"] == "succeeded" and completion["steps"] == config["run"].get("steps", completion["steps"])
        finite_table(directory / "results" / "monitor.csv")
        entry["status"] = "succeeded"
        print(name, "completed", flush=True)
        return directory / "results", entry

    def check_budget(result, entry, *, mass=False, energy=False):
        budget = final_budget(result)
        if mass:
            scale = max(abs(budget["mass_initial_lattice"]), abs(budget["mass_current_lattice"]), 1.0)
            fraction = abs(budget["mass_residual_lattice"]) / scale
            entry["mass_residual_fraction"] = fraction
            assert fraction <= report["thresholds"]["closed_liquid_mass_fraction"], entry
        if energy:
            scale = max(abs(budget["sensible_energy_initial_lattice"]),
                        abs(budget["cumulative_heat_source_in_lattice"]),
                        abs(budget["cumulative_boundary_heat_in_lattice"]), 1.0)
            fraction = abs(budget["sensible_energy_residual_lattice"]) / scale
            entry["sensible_energy_residual_fraction"] = fraction
            assert fraction <= report["thresholds"]["sensible_energy_fraction"], entry
        return budget

    try:
        # SPHERIC Test 2 / MARIN benchmark. Window, probes, norm and arrival threshold are fixed in
        # configs/reference/README.md before executing this suite.
        marin = read(configs / "free-surface-marin-dam-break-si.json")
        result, entry = invoke("marin-dam-break", marin)
        actual_rows = finite_table(result / "surface-levels.csv", {"id"})
        actual = {(round(float(row["time"]), 2), row["id"]): float(row["liquid_height"])
                  for row in actual_rows}
        reference_rows = csv_rows(configs / "reference" / "spheric-test2-levels.csv")
        squared = []
        reference_series, actual_series = {}, {}
        for probe in ("H1", "H2", "H3", "H4"):
            reference_series[probe] = []
            actual_series[probe] = []
        for row in reference_rows:
            sample_time = round(float(row["time_s"]), 2)
            for probe in ("H1", "H2", "H3", "H4"):
                measured = actual[(sample_time, probe)]
                reference = float(row[f"{probe}_m"])
                actual_series[probe].append((sample_time, measured))
                reference_series[probe].append((sample_time, reference))
                squared.append((measured - reference) ** 2)
        rmse = math.sqrt(sum(squared) / len(squared))
        normalized_rmse = rmse / 0.55
        arrivals = {}
        for probe in ("H1", "H2", "H3"):
            actual_arrival = next(t for t, value in actual_series[probe] if value > 0.02)
            reference_arrival = next(t for t, value in reference_series[probe] if value > 0.02)
            error = abs(actual_arrival - reference_arrival)
            arrivals[probe] = {"measured_seconds": actual_arrival, "reference_seconds": reference_arrival,
                               "absolute_error_seconds": error}
            assert error <= report["thresholds"]["marin_arrival_time_seconds"], (probe, arrivals[probe])
        entry.update(rmse_m=rmse, normalized_rmse=normalized_rmse, arrivals=arrivals,
                     reference_archive_sha256="a2ad06e367f61c70351f3d66a8dc5041b53972e3a3aecebde0e06efdd62bf6d1")
        assert normalized_rmse <= report["thresholds"]["marin_level_rmse_fraction_of_initial_depth"], entry
        check_budget(result, entry, mass=True)

        fill = read(configs / "free-surface-fill-drain-lattice.json")
        result, entry = invoke("fill-drain-known-flow", fill)
        flux = finite_table(result / "boundary-flux.csv", {"boundary_id", "boundary_type"})
        resolved = read(result / "resolved-config.json")
        links = {item["id"]: item["face_links"] for item in resolved["boundary_flux_surfaces"]}
        inlet = [row for row in flux if row["boundary_id"] == "inlet"]
        expected_inlet = -links["inlet"] * 0.03
        inlet_error = max(abs(float(row["mass_flow_outward_lattice"]) - expected_inlet) for row in inlet)
        entry.update(inlet_face_links=links["inlet"], expected_inlet_mass_flow_lattice=expected_inlet,
                     maximum_inlet_mass_flow_error_lattice=inlet_error)
        assert inlet_error / abs(expected_inlet) <= report["thresholds"]["known_flux_relative"], entry
        budget = check_budget(result, entry, mass=True)
        assert budget["mass_current_lattice"] > budget["mass_initial_lattice"]

        heated_channel = read(configs / "conjugate-heated-cube-lattice.json")
        heated_channel["run"] = {"steps": 200, "monitor_every": 20}
        heated_channel["output"] = {"vtk_fields": ["T", "material", "u"], "vtk_every": 200,
                                      "initial": True}
        result, entry = invoke("conjugate-heated-solid-channel", heated_channel)
        budget = check_budget(result, entry, energy=True)
        resolved = read(result / "resolved-config.json")
        solid_cells = resolved["geometry"][0]["solid_cells"]
        expected_source = solid_cells * 0.0001 * 200
        source_error = abs(budget["cumulative_heat_source_in_lattice"] - expected_source) / expected_source
        entry.update(solid_cells=solid_cells, expected_source_heat_lattice=expected_source,
                     measured_source_heat_lattice=budget["cumulative_heat_source_in_lattice"],
                     relative_error=source_error)
        assert source_error <= report["thresholds"]["known_flux_relative"], entry

        heat_flux = {
            "schema_version": 1, "case": {"name": "thermal-known-heat-flux"},
            "solver": {"lattice": "D3Q19", "collision": "TRT", "storage": "FP32", "turbulence": "none"},
            "physics": {"thermal": {"reference_temperature": 1.0, "initial_temperature": 1.0,
                                      "specific_heat": 1.0, "conductivity": 0.05}},
            "units": {"mode": "lattice"}, "domain": {"cells": [18, 8, 8]},
            "fluid": {"rho": 1.0, "nu": 0.08}, "initial": {"velocity": [0, 0, 0]}, "geometry": [],
            "boundaries": [
                {"id": "heater", "faces": ["xmin"], "type": "no_slip",
                 "thermal": {"type": "heat_flux", "heat_flux": 0.002}},
                {"id": "insulated", "faces": ["xmax"], "type": "no_slip",
                 "thermal": {"type": "adiabatic"}},
                {"id": "periodic", "faces": ["ymin", "ymax", "zmin", "zmax"], "type": "periodic"}],
            "run": {"steps": 100, "monitor_every": 20},
            "output": {"vtk_fields": ["T"], "vtk_every": 100, "initial": True}}
        result, entry = invoke("thermal-known-heat-flux", heat_flux)
        budget = check_budget(result, entry, energy=True)
        expected_heat = 8 * 8 * 0.002 * 100
        heat_error = abs(budget["cumulative_boundary_heat_in_lattice"] - expected_heat) / expected_heat
        entry.update(expected_boundary_heat_lattice=expected_heat,
                     measured_boundary_heat_lattice=budget["cumulative_boundary_heat_in_lattice"],
                     relative_error=heat_error)
        assert heat_error <= report["thresholds"]["known_flux_relative"], entry

        source = {
            "schema_version": 1, "case": {"name": "thermal-known-solid-source"},
            "solver": {"lattice": "D3Q19", "collision": "TRT", "storage": "FP32", "turbulence": "none"},
            "physics": {"thermal": {"reference_temperature": 1.0, "initial_temperature": 1.0,
                "specific_heat": 1.0, "conductivity": 0.02, "materials": [{"id": "heated", "density": 2.0,
                "specific_heat": 1.0, "conductivity": 0.02, "heat_source": 0.001, "initial_temperature": 1.0}]}},
            "units": {"mode": "lattice"}, "domain": {"cells": [16, 12, 12]},
            "fluid": {"rho": 1.0, "nu": 0.08}, "initial": {"velocity": [0, 0, 0]},
            "geometry": [{"id": "heater", "file": "assets/unit-cube-binary.stl", "material": "heated",
                          "transform": {"mode": "fit", "size": 4.0, "center": [8, 6, 6]}}],
            "boundaries": [{"id": "walls", "faces": ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax"],
                            "type": "no_slip", "thermal": {"type": "adiabatic"}}],
            "run": {"steps": 100, "monitor_every": 20},
            "output": {"vtk_fields": ["T", "material"], "vtk_every": 100, "initial": True}}
        result, entry = invoke("thermal-known-solid-source", source)
        budget = check_budget(result, entry, energy=True)
        resolved = read(result / "resolved-config.json")
        solid_cells = resolved["geometry"][0]["solid_cells"]
        expected_source = solid_cells * 0.001 * 100
        source_error = abs(budget["cumulative_heat_source_in_lattice"] - expected_source) / expected_source
        entry.update(solid_cells=solid_cells, expected_source_heat_lattice=expected_source,
                     measured_source_heat_lattice=budget["cumulative_heat_source_in_lattice"],
                     relative_error=source_error)
        assert source_error <= report["thresholds"]["known_flux_relative"], entry

        motion_cases = [
            ("translation-stop", "dynamic-translation-stop-lattice.json"),
            ("fixed-axis-rotation", "dynamic-rotation-lattice.json"),
            ("trajectory-table", "dynamic-trajectory-lattice.json"),
            ("sinusoidal-multi-body", "dynamic-sinusoidal-multi-lattice.json"),
        ]
        motion_results = {}
        for name, filename in motion_cases:
            result, entry = invoke(name, read(configs / filename))
            motion = finite_table(result / "object-motion.csv", {"geometry_id"})
            counts = {}
            for row in motion:
                counts.setdefault(row["geometry_id"], set()).add(int(row["solid_cells"]))
            assert all(len(values) == 1 for values in counts.values()), counts
            entry["constant_cell_counts"] = {key: next(iter(value)) for key, value in counts.items()}
            motion_results[name] = (motion, entry)
        tolerance = report["thresholds"]["prescribed_pose_absolute"]
        translation = row_at(motion_results["translation-stop"][0], 60, "moving-cube")
        assert abs(float(translation["translation_x_lattice"]) - 1.2) <= tolerance
        assert abs(float(translation["linear_velocity_x_lattice"])) <= tolerance
        rotation = row_at(motion_results["fixed-axis-rotation"][0], 400, "rotating-box")
        assert abs(float(rotation["degrees"]) - 90.0) <= tolerance
        assert abs(float(rotation["angular_velocity_radians_per_step"])) <= tolerance
        trajectory = motion_results["trajectory-table"][0]
        expected_frames = {120: ([2, 0, 0], 10), 240: ([2, 1, 0], -5),
                           360: ([0, 0, 0], 0), 400: ([0, 0, 0], 0)}
        for step, (shift, degrees) in expected_frames.items():
            row = row_at(trajectory, step, "trajectory-box")
            measured = [float(row[f"translation_{axis}_lattice"]) for axis in "xyz"]
            assert max(abs(a - b) for a, b in zip(measured, shift)) <= tolerance
            assert abs(float(row["degrees"]) - degrees) <= tolerance
        multiple = motion_results["sinusoidal-multi-body"][0]
        for geometry in ("oscillating-cube", "combined-box"):
            row = row_at(multiple, 480, geometry)
            assert max(abs(float(row[f"translation_{axis}_lattice"])) for axis in "xyz") <= tolerance
            assert abs(float(row["degrees"])) <= tolerance

        result, entry = invoke("prescribed-water-entry", read(configs / "dynamic-water-entry-lattice.json"))
        motion = finite_table(result / "object-motion.csv", {"geometry_id"})
        final = row_at(motion, 350, "entering-cube")
        assert abs(float(final["translation_z_lattice"]) + 6.0) <= tolerance
        assert abs(float(final["linear_velocity_z_lattice"])) <= tolerance
        peak_force = max(math.sqrt(sum(float(row[f"force_{axis}_lattice"]) ** 2 for axis in "xyz")) for row in motion)
        entry["peak_force_lattice"] = peak_force
        assert peak_force > 1e-8
        check_budget(result, entry, mass=True)

        triple = read(configs / "thermal-free-surface-dynamic-cycle-lattice.json")
        result, entry = invoke("thermal-free-surface-dynamic-cycle", triple)
        motion = finite_table(result / "object-motion.csv", {"geometry_id"})
        final = row_at(motion, 800, "heated-oscillator")
        assert max(abs(float(final[f"translation_{axis}_lattice"])) for axis in "xyz") <= tolerance
        assert abs(float(final["degrees"])) <= tolerance
        check_budget(result, entry, mass=True, energy=True)

        combined = read(configs / "thermal-free-surface-dynamic-fill-drain-lattice.json")
        result, entry = invoke("heated-moving-temperature-fill-drain", combined)
        motion = finite_table(result / "object-motion.csv", {"geometry_id"})
        final = row_at(motion, 200, "heated-oscillator")
        assert max(abs(float(final[f"translation_{axis}_lattice"])) for axis in "xyz") <= tolerance
        assert abs(float(final["degrees"])) <= tolerance
        flux = finite_table(result / "boundary-flux.csv", {"boundary_id", "boundary_type"})
        inlet = [row for row in flux if row["boundary_id"] == "hot-inlet"]
        assert inlet
        inlet_temperature = [float(row["sensible_enthalpy_flow_outward_lattice"]) /
                             float(row["mass_flow_outward_lattice"]) for row in inlet
                             if abs(float(row["mass_flow_outward_lattice"])) > 1e-12]
        maximum_temperature_error = max(abs(value - 1.2) for value in inlet_temperature)
        entry.update(inlet_enthalpy_temperature_min=min(inlet_temperature),
                     inlet_enthalpy_temperature_max=max(inlet_temperature),
                     maximum_inlet_temperature_error=maximum_temperature_error)
        assert maximum_temperature_error <= report["thresholds"]["known_flux_relative"], entry
        budget = check_budget(result, entry, mass=True, energy=True)
        resolved = read(result / "resolved-config.json")
        solid_cells = resolved["geometry"][0]["solid_cells"]
        expected_source = solid_cells * 0.0002 * 200
        source_error = abs(budget["cumulative_heat_source_in_lattice"] - expected_source) / expected_source
        entry.update(solid_cells=solid_cells, expected_source_heat_lattice=expected_source,
                     measured_source_heat_lattice=budget["cumulative_heat_source_in_lattice"],
                     source_relative_error=source_error)
        assert source_error <= report["thresholds"]["known_flux_relative"], entry

        finite_slosh = read(configs / "free-surface-sloshing-lattice.json")
        for i, region in enumerate(finite_slosh["initial"]["liquid_regions"]):
            region["box_max"][2] = 15.5 + 4.0 * math.cos(math.pi * (i + 0.5) / 62.0)
        finite_slosh["case"]["name"] = "free-surface-finite-amplitude-sloshing"
        finite_slosh["run"] = {"steps": 3000, "monitor_every": 20}
        finite_slosh["output"] = {"vtk_fields": ["phi"], "vtk_every": 3000, "initial": True}
        result, entry = invoke("finite-amplitude-sloshing", finite_slosh)
        surface = finite_table(result / "free-surface.csv")
        centroids = [float(row["centroid_x_lattice"]) for row in surface]
        excursion = max(centroids) - min(centroids)
        entry["centroid_excursion_lattice"] = excursion
        assert excursion >= 1.0, entry
        check_budget(result, entry, mass=True)

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
