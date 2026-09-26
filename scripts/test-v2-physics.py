"""NUC-only Solver-IBM V2 physical-accuracy acceptance suite."""
import argparse
import array
import copy
import csv
import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location("config_tests", Path(__file__).with_name("test-config-runner.py"))
config_tests = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(config_tests)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def solve_linear(matrix, right):
    size = len(right)
    augmented = [list(map(float, matrix[row])) + [float(right[row])] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        assert abs(augmented[pivot][column]) > 1e-14
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [a - factor * b for a, b in zip(augmented[row], augmented[column])]
    return [augmented[row][-1] for row in range(size)]


def least_squares(columns, values):
    count = len(columns[0])
    assert count and all(len(column) == count for column in columns) and len(values) == count
    matrix = [[sum(a * b for a, b in zip(left, right)) for right in columns] for left in columns]
    right = [sum(a * value for a, value in zip(column, values)) for column in columns]
    return solve_linear(matrix, right)


def fit_sphere(points):
    columns = [[point[axis] for point in points] for axis in range(3)] + [[1.0] * len(points)]
    values = [-(x * x + y * y + z * z) for x, y, z in points]
    a, b, c, d = least_squares(columns, values)
    center = (-0.5 * a, -0.5 * b, -0.5 * c)
    radius = math.sqrt(sum(value * value for value in center) - d)
    return center, radius


def sinusoid_fit(times, values, omega):
    columns = [[1.0] * len(times), [math.cos(omega * t) for t in times], [math.sin(omega * t) for t in times]]
    coefficients = least_squares(columns, values)
    residual = sum((value - sum(c * column[i] for c, column in zip(coefficients, columns))) ** 2
                   for i, value in enumerate(values))
    return residual, coefficients


def damped_sinusoid_fit(times, values, omega, damping):
    envelope = [math.exp(-damping * t) for t in times]
    columns = [
        [1.0] * len(times),
        list(times),
        [value * math.cos(omega * t) for value, t in zip(envelope, times)],
        [value * math.sin(omega * t) for value, t in zip(envelope, times)],
    ]
    coefficients = least_squares(columns, values)
    residual = sum((value - sum(c * column[i] for c, column in zip(coefficients, columns))) ** 2
                   for i, value in enumerate(values))
    return residual, coefficients


def relative_l2(actual, expected, reference=None):
    reference = expected if reference is None else reference
    denominator = sum(value * value for value in reference)
    assert denominator > 0
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(actual, expected)) / denominator)


def index(dimensions, x, y, z):
    return x + dimensions[0] * (y + dimensions[1] * z)


def absolute_assets(config, configs_root):
    for geometry in config.get("geometry", []):
        path = Path(geometry["file"])
        if not path.is_absolute():
            geometry["file"] = str((configs_root / path).resolve())
    for region in config.get("initial", {}).get("liquid_regions", []):
        if region.get("shape") == "stl":
            path = Path(region["file"])
            if not path.is_absolute():
                region["file"] = str((configs_root / path).resolve())


def final_budget(result):
    records = rows(result / "conservation-budget.csv")
    assert records
    return {key: float(value) for key, value in records[-1].items() if key not in {"step", "time"}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--build-name", default="solver-ibm-v1.1.0-dev")
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
    root = workspace / "workingdir" / "v2-physics" / stamp
    root.mkdir(parents=True)
    report = {
        "schema_version": 1,
        "status": "running",
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "build": read(executable.parent / "build.json"),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
        "device": args.device,
        "thresholds": {
            "smooth_thermal_relative_l2": 0.02,
            "multilayer_heat_flux_relative": 0.03,
            "natural_convection_nusselt_relative": 0.05,
            "laplace_pressure_relative": 0.05,
            "contact_angle_degrees": 5.0,
            "sloshing_frequency_relative": 0.03,
            "closed_liquid_mass_fraction": 0.001,
            "sensible_energy_fraction": 0.005,
            "moving_temperature_relative_l2": 0.02,
        },
        "tests": [],
    }
    write(root / "report.json", report)

    def invoke(name, config, timeout=1200):
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
        assert completion["status"] == "succeeded" and completion["steps"] == config["run"]["steps"]
        entry["status"] = "succeeded"
        print(name, "completed", flush=True)
        return directory / "results", entry

    def check_budget(entry, result, *, mass=False, energy=False):
        budget = final_budget(result)
        if mass:
            fraction = abs(budget["mass_residual_lattice"]) / budget["mass_initial_lattice"]
            entry["mass_residual_fraction"] = fraction
            assert fraction <= report["thresholds"]["closed_liquid_mass_fraction"], entry
        if energy:
            scale = max(abs(budget["sensible_energy_initial_lattice"]),
                        abs(budget["cumulative_heat_source_in_lattice"]),
                        abs(budget["cumulative_boundary_heat_in_lattice"]), 1e-30)
            fraction = abs(budget["sensible_energy_residual_lattice"]) / scale
            entry["sensible_energy_residual_fraction"] = fraction
            assert fraction <= report["thresholds"]["sensible_energy_fraction"], entry

    try:
        # Smooth periodic diffusion fixes the norm, mode, grid and comparison time before execution.
        cells = [32, 8, 8]
        amplitude, alpha, steps = 0.1, 0.05, 200
        diffusion = read(configs / "thermal-diffusion-lattice.json")
        diffusion["case"]["name"] = "v2-smooth-periodic-thermal-diffusion"
        diffusion["domain"]["cells"] = cells
        diffusion["physics"]["thermal"]["conductivity"] = alpha
        diffusion["initial"]["regions"] = [
            {"box_min": [x, 0, 0], "box_max": [x + 0.999, cells[1], cells[2]], "rho": 1.0,
             "velocity": [0, 0, 0], "temperature": 1.0 + amplitude * math.sin(2.0 * math.pi * (x + 0.5) / cells[0])}
            for x in range(cells[0])]
        diffusion["run"] = {"steps": steps, "monitor_every": 50}
        diffusion["output"] = {"vtk_fields": ["T"], "vtk_every": steps, "initial": True}
        result, entry = invoke("smooth-thermal-diffusion", diffusion)
        field = config_tests.vtk(result / f"T-{steps:09d}.vtk")
        actual = [sum(field["values"][index(cells, x, y, z)] for y in range(cells[1]) for z in range(cells[2])) /
                  (cells[1] * cells[2]) for x in range(cells[0])]
        decay = math.exp(-alpha * (2.0 * math.pi / cells[0]) ** 2 * steps)
        expected = [1.0 + amplitude * decay * math.sin(2.0 * math.pi * (x + 0.5) / cells[0])
                    for x in range(cells[0])]
        perturbation = [value - 1.0 for value in expected]
        error = relative_l2(actual, expected, perturbation)
        entry.update(relative_l2=error, analytical_decay=decay)
        assert error <= report["thresholds"]["smooth_thermal_relative_l2"], entry
        check_budget(entry, result, energy=True)

        # Periodic forced convection of the same smooth mode checks temperature transport and phase speed.
        forced = copy.deepcopy(diffusion)
        forced["case"]["name"] = "v2-smooth-forced-convection"
        forced["domain"]["cells"] = [64, 8, 8]
        forced["physics"]["thermal"]["conductivity"] = 0.02
        forced["initial"]["velocity"] = [0.01, 0, 0]
        forced["initial"]["regions"] = [
            {"box_min": [x, 0, 0], "box_max": [x + 0.999, 8, 8], "rho": 1.0,
             "velocity": [0.01, 0, 0], "temperature": 1.0 + amplitude * math.sin(2.0 * math.pi * (x + 0.5) / 64)}
            for x in range(64)]
        forced["run"] = {"steps": 100, "monitor_every": 25}
        forced["output"] = {"vtk_fields": ["T"], "vtk_every": 100, "initial": True}
        result, entry = invoke("smooth-forced-convection", forced)
        field = config_tests.vtk(result / "T-000000100.vtk")
        actual = [sum(field["values"][index((64, 8, 8), x, y, z)] for y in range(8) for z in range(8)) / 64
                  for x in range(64)]
        wave = 2.0 * math.pi / 64
        decay = math.exp(-0.02 * wave * wave * 100)
        expected = [1.0 + amplitude * decay * math.sin(wave * (x + 0.5 - 0.01 * 100)) for x in range(64)]
        error = relative_l2(actual, expected, [value - 1.0 for value in expected])
        entry.update(relative_l2=error, analytical_shift_lattice=1.0)
        assert error <= 0.03, entry
        check_budget(entry, result, energy=True)

        multilayer = read(configs / "thermal-multilayer-conduction-lattice.json")
        result, entry = invoke("multilayer-conduction", multilayer)
        temperature = config_tests.vtk(result / "T-000040000.vtk")
        material = config_tests.vtk(result / "material-000040000.vtk")
        dimensions = temperature["dimensions"]
        plane_temperature, plane_material = [], []
        for x in range(dimensions[0]):
            indices = [index(dimensions, x, y, z) for y in range(dimensions[1]) for z in range(dimensions[2])]
            plane_temperature.append(sum(temperature["values"][n] for n in indices) / len(indices))
            plane_material.append(round(sum(material["values"][n] for n in indices) / len(indices)))
        conductivities = [0.2 if plane_material[x] == 1 else 0.05 for x in range(1, dimensions[0] - 1)]
        expected_flux = 0.2 / sum(1.0 / value for value in conductivities)
        measured_flux = 2.0 * 0.05 * (1.1 - plane_temperature[1])
        flux_error = abs(measured_flux - expected_flux) / expected_flux
        entry.update(expected_heat_flux_lattice=expected_flux, measured_heat_flux_lattice=measured_flux,
                     relative_error=flux_error, material_planes=plane_material)
        assert flux_error <= report["thresholds"]["multilayer_heat_flux_relative"], entry
        check_budget(entry, result, energy=True)

        boundary_case = read(configs / "thermal-boundaries-lattice.json")
        boundary_case["case"]["name"] = "v2-thermal-boundary-budget"
        boundary_case["run"] = {"steps": 500, "monitor_every": 100}
        boundary_case["output"] = {"vtk_fields": ["T"], "vtk_every": 500, "initial": True}
        result, entry = invoke("thermal-boundary-budget", boundary_case)
        budget = final_budget(result)
        entry["cumulative_boundary_heat_in_lattice"] = budget["cumulative_boundary_heat_in_lattice"]
        assert abs(entry["cumulative_boundary_heat_in_lattice"]) > 0
        check_budget(entry, result, energy=True)

        natural = read(configs / "thermal-natural-convection-cavity-lattice.json")
        natural["domain"]["cells"] = [34, 34, 4]
        natural["physics"]["gravity"] = [0, -0.0006103515625, 0]
        natural["boundaries"][-1] = {"id": "adiabatic-horizontal", "faces": ["ymin", "ymax"],
                                      "type": "no_slip", "thermal": {"type": "adiabatic"}}
        natural["boundaries"].append({"id": "periodic-depth", "faces": ["zmin", "zmax"], "type": "periodic"})
        natural["run"] = {"steps": 50000, "monitor_every": 2500}
        natural["output"] = {"vtk_fields": ["T", "u"], "vtk_every": 50000, "initial": True}
        result, entry = invoke("natural-convection-ra1000", natural)
        temperature = config_tests.vtk(result / "T-000050000.vtk")
        dimensions = temperature["dimensions"]
        wall_fluxes = [2.0 * 0.02 * (1.1 - temperature["values"][index(dimensions, 1, y, z)])
                       for y in range(1, 33) for z in range(4)]
        nusselt = (sum(wall_fluxes) / len(wall_fluxes)) * 32.0 / (0.02 * 0.2)
        reference_nusselt = 1.118
        nu_error = abs(nusselt - reference_nusselt) / reference_nusselt
        entry.update(rayleigh=1000.0, nusselt=nusselt, reference_nusselt=reference_nusselt,
                     relative_error=nu_error)
        assert nu_error <= report["thresholds"]["natural_convection_nusselt_relative"], entry
        check_budget(entry, result, energy=True)

        conductive_wall = read(configs / "thermal-natural-convection-conductive-wall-lattice.json")
        result, entry = invoke("natural-convection-conductive-wall", conductive_wall)
        temperature = config_tests.vtk(result / "T-000001000.vtk")
        material = config_tests.vtk(result / "material-000001000.vtk")
        solid_temperature = [temperature["values"][n] for n, value in enumerate(material["values"]) if value == 1]
        assert solid_temperature, entry
        entry.update(solid_cells=len(solid_temperature), solid_temperature_min=min(solid_temperature),
                     solid_temperature_max=max(solid_temperature))
        assert max(solid_temperature) > 1.0001, entry
        check_budget(entry, result, energy=True)

        hydrostatic = read(configs / "free-surface-hydrostatic-lattice.json")
        result, entry = invoke("hydrostatic-column", hydrostatic)
        probe_rows = rows(result / "probes.csv")
        final_probes = {row["id"]: row for row in probe_rows if int(row["step"]) == hydrostatic["run"]["steps"]}
        assert set(final_probes) == {"deep", "middle", "shallow"}, final_probes
        deep = float(final_probes["deep"]["p"])
        shallow = float(final_probes["shallow"]["p"])
        height = float(final_probes["shallow"]["z"]) - float(final_probes["deep"]["z"])
        expected_difference = abs(hydrostatic["physics"]["gravity"][2]) * height
        measured_difference = deep - shallow
        pressure_error = abs(measured_difference - expected_difference) / expected_difference
        entry.update(expected_pressure_difference_lattice=expected_difference,
                     measured_pressure_difference_lattice=measured_difference,
                     relative_error=pressure_error)
        assert pressure_error <= report["thresholds"]["laplace_pressure_relative"], entry
        check_budget(entry, result, mass=True)

        droplet = read(configs / "free-surface-static-droplet-lattice.json")
        result, entry = invoke("static-droplet", droplet)
        pressure = config_tests.vtk(result / "p-000001000.vtk")
        phi = config_tests.vtk(result / "phi-000001000.vtk")
        dimensions = phi["dimensions"]
        volume = sum(max(0.0, min(1.0, value)) for value in phi["values"])
        radius = (3.0 * volume / (4.0 * math.pi)) ** (1.0 / 3.0)
        center_values = []
        for z in range(dimensions[2]):
            for y in range(dimensions[1]):
                for x in range(dimensions[0]):
                    if (x + 0.5 - 24) ** 2 + (y + 0.5 - 24) ** 2 + (z + 0.5 - 24) ** 2 < (0.45 * radius) ** 2:
                        center_values.append(pressure["values"][index(dimensions, x, y, z)])
        measured_pressure = sum(center_values) / len(center_values)
        expected_pressure = 2.0 * 0.005 / radius
        pressure_error = abs(measured_pressure - expected_pressure) / expected_pressure
        entry.update(effective_radius_lattice=radius, measured_pressure_lattice=measured_pressure,
                     expected_pressure_lattice=expected_pressure, relative_error=pressure_error)
        assert pressure_error <= report["thresholds"]["laplace_pressure_relative"], entry
        check_budget(entry, result, mass=True)

        for requested in (60, 90, 120):
            contact = read(configs / f"free-surface-contact-angle-{requested}-lattice.json")
            contact["run"] = {"steps": 800, "monitor_every": 40}
            contact["output"] = {"vtk_fields": ["phi"], "vtk_every": 800, "initial": True}
            result, entry = invoke(f"contact-angle-{requested}", contact)
            phi = config_tests.vtk(result / "phi-000000800.vtk")
            dimensions = phi["dimensions"]
            points = []
            for z in range(1, dimensions[2]):
                for y in range(dimensions[1]):
                    for x in range(dimensions[0]):
                        value = phi["values"][index(dimensions, x, y, z)]
                        if 0.05 < value < 0.95:
                            points.append((x + 0.5, y + 0.5, z + 0.5))
            assert len(points) >= 20, (requested, len(points))
            center, radius = fit_sphere(points)
            cosine = max(-1.0, min(1.0, -(center[2] - 1.0) / radius))
            measured = math.degrees(math.acos(cosine))
            angle_error = abs(measured - requested)
            entry.update(interface_points=len(points), fitted_center=center, fitted_radius=radius,
                         measured_contact_angle_degrees=measured, error_degrees=angle_error)
            assert angle_error <= report["thresholds"]["contact_angle_degrees"], entry
            check_budget(entry, result, mass=True)

        sloshing = read(configs / "free-surface-sloshing-lattice.json")
        sloshing["run"] = {"steps": 3000, "monitor_every": 10}
        sloshing["output"] = {"vtk_fields": ["phi"], "vtk_every": 3000, "initial": True}
        result, entry = invoke("small-amplitude-sloshing", sloshing)
        surface = rows(result / "free-surface.csv")
        samples = [(float(row["time"]), float(row["centroid_x_lattice"])) for row in surface]
        times = [sample[0] for sample in samples]
        values = [sample[1] for sample in samples]
        length, depth, gravity = 62.0, 14.5, 0.0002
        wave = math.pi / length
        expected_omega = math.sqrt(gravity * wave * math.tanh(wave * depth))
        frequencies = [expected_omega * (0.9 + 0.0005 * i) for i in range(401)]
        dampings = [0.00005 * i for i in range(61)]
        measured_omega, measured_damping, fit = min(
            ((omega, damping, damped_sinusoid_fit(times, values, omega, damping))
             for damping in dampings for omega in frequencies),
            key=lambda item: item[2][0])
        frequency_error = abs(measured_omega - expected_omega) / expected_omega
        entry.update(expected_angular_frequency=expected_omega, measured_angular_frequency=measured_omega,
                     fitted_damping=measured_damping, relative_error=frequency_error,
                     fitted_coefficients=fit[1], fit_residual=fit[0])
        assert frequency_error <= report["thresholds"]["sloshing_frequency_relative"], entry
        check_budget(entry, result, mass=True)

        moving = read(configs / "dynamic-thermal-cycle-lattice.json")
        moving["physics"]["thermal"]["conductivity"] = 1e-6
        moving["physics"]["thermal"]["materials"][0]["conductivity"] = 1e-6
        moving["run"] = {"steps": 600, "monitor_every": 100}
        moving["output"] = {"vtk_fields": ["material", "T"], "vtk_every": 600, "initial": True}
        static = copy.deepcopy(moving)
        static["geometry"][0]["motion"]["translation"]["amplitude"] = [0, 0, 0]
        static["geometry"][0]["motion"]["rotation"]["amplitude_degrees"] = 0
        static["case"]["name"] = "dynamic-thermal-static-reference"
        static_result, static_entry = invoke("moving-temperature-static-reference", static)
        moving_result, moving_entry = invoke("moving-temperature-full-cycle", moving)
        static_object = config_tests.vtk(static_result / "material-000000600.vtk")["values"]
        moving_object = config_tests.vtk(moving_result / "material-000000600.vtk")["values"]
        assert static_object == moving_object
        static_temperature = config_tests.vtk(static_result / "T-000000600.vtk")["values"]
        moving_temperature = config_tests.vtk(moving_result / "T-000000600.vtk")["values"]
        expected = [static_temperature[n] for n, object_id in enumerate(static_object) if object_id == 1]
        actual = [moving_temperature[n] for n, object_id in enumerate(moving_object) if object_id == 1]
        reference = [value - 300.0 for value in expected]
        mapping_error = relative_l2(actual, expected, reference)
        moving_entry.update(relative_l2=mapping_error, compared_solid_cells=len(actual),
                            static_reference_results=str(static_result))
        assert mapping_error <= report["thresholds"]["moving_temperature_relative_l2"], moving_entry
        check_budget(static_entry, static_result, energy=True)
        check_budget(moving_entry, moving_result, energy=True)

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
