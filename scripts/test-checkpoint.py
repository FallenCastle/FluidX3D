"""Windows-only Solver-IBM checkpoint/restart acceptance suite.

Covers r2 plan test matrix groups:
  T1 numerical equivalence (mode A, same build: byte-exact per the frozen threshold table),
  T2 commit/recovery protocol (fault injection, forced kill, quarantine/fallback, finish-only, locks),
  T3 compatibility rejection (exit code 5, no mutation of existing outputs),
  T4 retention/overhead (keep policy, informational overhead measurement).

Exit codes under test: 0 success (including fallback-with-warning), 1 generic error,
3 no usable checkpoint, 4 checkpoint save failure, 5 compatibility rejection.
Fault injection: SOLVER_IBM_CHECKPOINT_FAULT=<stage>[#<n>] (test-only hook, default off).
"""
import argparse
import copy
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

sys.dont_write_bytecode = True

EXIT_NO_USABLE = 3
EXIT_SAVE_FAILED = 4
EXIT_REJECTED = 5

CSV_NAMES = ("monitor.csv", "probes.csv", "analysis.csv", "forces.csv", "free-surface.csv",
             "conservation-budget.csv", "object-motion.csv", "boundary-flux.csv", "surface-levels.csv")


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def absolute_assets(config, configs_root):
    for geometry in config.get("geometry", []):
        source = Path(geometry["file"])
        if not source.is_absolute():
            geometry["file"] = str((configs_root / source).resolve())
    for region in config.get("initial", {}).get("liquid_regions", []):
        if region.get("shape") == "stl" and region.get("file"):
            source = Path(region["file"])
            if not source.is_absolute():
                region["file"] = str((configs_root / source).resolve())


# ---------------------------------------------------------------------------
# Embedded self-contained base case (single-phase FP32 shear flow with analysis)
# ---------------------------------------------------------------------------
def base_case(steps=120, cells=(32, 32, 32)):
    return {
        "schema_version": 1,
        "case": {"name": "checkpoint-suite-base"},
        "solver": {"lattice": "D3Q19", "collision": "SRT", "storage": "FP32", "turbulence": "none"},
        "units": {"mode": "lattice"},
        "domain": {"cells": list(cells)},
        "fluid": {"rho": 1.0, "nu": 0.02},
        "initial": {
            "velocity": [0.02, 0.0, 0.0],
            "regions": [
                {"box_min": [0.0, 0.0, 0.0],
                 "box_max": [float(cells[0]), float(cells[1]), float(cells[2]) / 2.0],
                 "rho": 1.0, "velocity": [-0.02, 0.0, 0.0]}
            ],
        },
        "geometry": [],
        "boundaries": [
            {"id": "walls", "faces": ["xmin", "xmax", "ymin", "ymax"], "type": "no_slip"},
            {"id": "periodic", "faces": ["zmin", "zmax"], "type": "periodic"},
        ],
        "run": {"steps": steps, "monitor_every": 7},
        "output": {"vtk_fields": ["u", "rho", "flags"], "vtk_every": 30, "initial": True},
        "analysis": {
            "every": 11, "start_step": 5, "statistics": True,
            "probes": [{"id": "center", "position": [cells[0] / 2.0, cells[1] / 2.0, cells[2] / 2.0]}],
        },
    }


class Suite:
    def __init__(self, args):
        self.args = args
        self.workspace = args.workspace_root.resolve()
        repository = (args.repository_root or self.workspace / "src").resolve()
        self.configs = (args.configs_root or repository / "configs").resolve()
        self.executable = (args.executable or self.workspace / "bin" / args.build_name / "Solver-IBM.exe").resolve()
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        self.root = self.workspace / "workingdir" / "checkpoint-validation" / stamp
        self.root.mkdir(parents=True)
        self.report = {
            "schema_version": 1,
            "status": "running",
            "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "build": read(self.executable.parent / "build.json"),
            "executable_sha256": sha_file(self.executable),
            "device": args.device,
            "criteria": "mode A of docs/validation/checkpoint-tolerance-thresholds.md (same build: byte-exact)",
            "tests": [],
        }
        assert self.report["build"]["executableSha256"] == self.report["executable_sha256"]
        write(self.root / "report.json", self.report)
        self.processes = []

    # -- process helpers ----------------------------------------------------
    def solver_command(self, config_path, output, restart=False):
        command = [str(self.executable), "--config", str(config_path), "--output", str(output),
                   "--device", str(self.args.device)]
        if restart:
            command.append("--restart")
        return command

    def run_solver(self, name, config=None, config_path=None, restart=False, fault=None,
                   expect_exit=0, timeout=1800, output=None):
        directory = self.root / name
        directory.mkdir(parents=True, exist_ok=True)
        if config is not None:
            config_path = directory / "case.json"
            write(config_path, config)
        results = output if output is not None else directory / "results"
        environment = os.environ.copy()
        if fault:
            environment["SOLVER_IBM_CHECKPOINT_FAULT"] = fault
        else:
            environment.pop("SOLVER_IBM_CHECKPOINT_FAULT", None)
        started = time.perf_counter()
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            process = subprocess.run(self.solver_command(config_path, results, restart),
                                     cwd=directory, stdout=stdout, stderr=stderr,
                                     timeout=timeout, env=environment)
        elapsed = round(time.perf_counter() - started, 2)
        out_text = (directory / "stdout.log").read_text(encoding="utf-8", errors="replace")
        err_text = (directory / "stderr.log").read_text(encoding="utf-8", errors="replace")
        assert process.returncode == expect_exit, \
            f"{name}: exit {process.returncode}, expected {expect_exit}\nstdout: {out_text[-1200:]}\nstderr: {err_text[-1200:]}"
        return {"results": Path(results), "stdout": out_text, "stderr": err_text, "seconds": elapsed,
                "directory": directory}

    def launch_solver(self, name, config_path, output, restart=False, fault=None):
        directory = self.root / name
        directory.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        if fault:
            environment["SOLVER_IBM_CHECKPOINT_FAULT"] = fault
        else:
            environment.pop("SOLVER_IBM_CHECKPOINT_FAULT", None)
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            process = subprocess.Popen(self.solver_command(config_path, output, restart),
                                       cwd=directory, stdout=stdout, stderr=stderr, env=environment)
        self.processes.append(process)
        return process

    def cleanup(self):
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.wait()

    # -- checkpoint helpers -------------------------------------------------
    @staticmethod
    def checkpoint_dirs(results):
        root = results / "checkpoint"
        if not root.is_dir():
            return {}
        out = {}
        for entry in sorted(root.glob("step-*")):
            if entry.is_dir() and not entry.name.endswith(".tmp"):
                out[int(entry.name.split("-", 1)[1])] = entry
        return out

    @staticmethod
    def restarted_step(stdout_text):
        for line in stdout_text.splitlines():
            if line.startswith("Restarted from checkpoint step "):
                return int(line.rsplit(" ", 1)[1])
        raise AssertionError("restart banner not found in stdout")

    def split_case(self, base, n, k, s, keep=2, patch=None):
        """A: continuous reference to n; B: split run to s; both checkpointed (grid k, keep)."""
        cfg_a = copy.deepcopy(base)
        if patch:
            patch(cfg_a)
        cfg_a.setdefault("run", {})
        cfg_a["run"].update(steps=n, checkpoint_every=k, checkpoint_keep=keep)
        cfg_b = copy.deepcopy(cfg_a)
        cfg_b["run"]["steps"] = s
        return cfg_a, cfg_b

    # -- comparison (mode A: byte-exact) ------------------------------------
    def compare_continuation(self, name, a_results, c_results, s, keep=2, extra_stamps=None):
        failures = []
        allowed_extra = set(extra_stamps) if extra_stamps else {s}
        a_vtk = sorted(p.name for p in a_results.glob("*.vtk"))
        for vtk in a_vtk:
            target = c_results / vtk
            if not target.exists():
                failures.append(f"VTK missing in C: {vtk}")
            elif sha_file(a_results / vtk) != sha_file(target):
                failures.append(f"VTK differs: {vtk}")
        for path in c_results.glob("*.vtk"):
            if path.name in set(a_vtk):
                continue
            stem = path.name[:-4]
            try:
                stamp = int(stem.split("-")[-1])
            except ValueError:
                failures.append(f"unparsable extra VTK: {path.name}")
                continue
            if stamp not in allowed_extra:
                failures.append(f"unexpected extra VTK in C: {path.name}")
        for csv_name in CSV_NAMES:
            ap, cp = a_results / csv_name, c_results / csv_name
            if not ap.exists() and not cp.exists():
                continue
            if not ap.exists() or not cp.exists():
                failures.append(f"CSV presence mismatch: {csv_name}")
                continue
            a_lines = ap.read_text(encoding="utf-8").splitlines(keepends=True)
            c_lines = cp.read_text(encoding="utf-8").splitlines(keepends=True)
            if a_lines[0] != c_lines[0]:
                failures.append(f"CSV header differs: {csv_name}")
            step_of = lambda line: int(line.split(",", 1)[0])
            a_rows = [line for line in a_lines[1:] if step_of(line) > s]
            a_steps = {step_of(line) for line in a_rows}
            historic_extra = allowed_extra - a_steps
            c_rows = [line for line in c_lines[1:]
                      if step_of(line) > s and step_of(line) not in historic_extra]
            if a_rows != c_rows:
                failures.append(f"CSV rows > {s} differ: {csv_name} ({len(a_rows)} vs {len(c_rows)})")
        if (a_results / "statistics.json").exists():
            if sha_file(a_results / "statistics.json") != sha_file(c_results / "statistics.json"):
                failures.append("statistics.json differs")
        da, dc = self.checkpoint_dirs(a_results), self.checkpoint_dirs(c_results)
        if len(dc) > keep:
            failures.append(f"retention violated in C: {sorted(dc)}")
        common = sorted(set(da) & set(dc))
        if not common:
            failures.append("no common checkpoints for Tier1")
        numeric_keys = ("t", "budget", "targets", "source_per_step", "analysis_enabled", "moments", "bodies")
        for step in common:
            fa, fc = da[step], dc[step]
            a_files = sorted(p.name for p in fa.iterdir())
            c_files = sorted(p.name for p in fc.iterdir())
            if a_files != c_files:
                failures.append(f"checkpoint {step}: file list differs")
                continue
            for f in a_files:
                if f.endswith(".bin") and sha_file(fa / f) != sha_file(fc / f):
                    failures.append(f"checkpoint {step}: Tier1 field differs: {f}")
            ha = read(fa / "host-state.json")
            hc = read(fc / "host-state.json")
            if {k: ha.get(k) for k in numeric_keys} != {k: hc.get(k) for k in numeric_keys}:
                failures.append(f"checkpoint {step}: host-state numeric subset differs")
        completion = read(c_results / "completion.json")
        if completion.get("status") != "succeeded":
            failures.append("completion status is not succeeded")
        return failures

    # -- test bookkeeping ---------------------------------------------------
    def test(self, name, fn):
        started = time.perf_counter()
        entry = {"name": name, "status": "passed"}
        try:
            details = fn()
            if isinstance(details, dict):
                entry.update(details)
        except AssertionError as error:
            entry["status"] = "failed"
            entry["error"] = str(error)[:4000]
        except Exception as error:  # infrastructure fault, not a product verdict
            entry["status"] = "failed"
            entry["error"] = f"{type(error).__name__}: {error}"[:4000]
        entry["seconds"] = round(time.perf_counter() - started, 2)
        self.report["tests"].append(entry)
        write(self.root / "report.json", self.report)
        print(f"{name}: {entry['status']} ({entry['seconds']}s)"
              + ("" if entry["status"] == "passed" else f" | {entry.get('error', '')[:300]}"), flush=True)

    def equivalence_case(self, name, base, n, k, s, keep=2, patch=None, extra_assert=None):
        def body2():
            cfg_a, cfg_b = self.split_case(base, n, k, s, keep, patch)
            ref = self.run_solver(f"{name}-ref", config=cfg_a)
            split = self.run_solver(f"{name}-split", config=cfg_b)
            cont_dir = self.root / f"{name}-cont"
            cont_dir.mkdir(parents=True, exist_ok=True)
            write(cont_dir / "case.json", cfg_a)
            cont = self.run_solver(f"{name}-cont", config_path=cont_dir / "case.json",
                                   restart=True, output=split["results"])
            assert self.restarted_step(cont["stdout"]) == s, "restored from an unexpected step"
            failures = self.compare_continuation(name, ref["results"], split["results"], s, keep)
            if extra_assert:
                extra_assert(ref, split, cont, failures)
            assert not failures, "; ".join(failures[:6])
            return {"S": s, "N": n, "common_checkpoints": sorted(self.checkpoint_dirs(ref["results"]))}
        self.test(name, body2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", required=True, type=Path)
    parser.add_argument("--build-name", required=True)
    parser.add_argument("--repository-root", type=Path)
    parser.add_argument("--configs-root", type=Path)
    parser.add_argument("--executable", type=Path)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()
    if os.name != "nt":
        parser.error("Run on the Windows server only")
    suite = Suite(args)
    configs = suite.configs

    def repo_case(filename):
        config = read(configs / filename)
        absolute_assets(config, configs)
        return config

    try:
        # ------------------------------------------------------------------
        # T1: numerical equivalence across modules (mode A byte-exact)
        # ------------------------------------------------------------------
        suite.equivalence_case("t1-fp32-singlephase", base_case(), 120, 20, 40)
        suite.equivalence_case("t1-fp16s-analysis", base_case(), 120, 20, 40,
                               patch=lambda c: c["solver"].__setitem__("storage", "FP16S"))
        suite.equivalence_case("t1-odd-cadence", base_case(), 120, 7, 21)
        suite.equivalence_case("t1-sparse-moments", base_case(), 120, 20, 40,
                               patch=lambda c: c["analysis"].__setitem__("start_step", 39))
        suite.equivalence_case("t1-conjugate-thermal", repo_case("conjugate-heated-cube-lattice.json"), 40, 10, 20)
        suite.equivalence_case("t1-thermal-boundaries", repo_case("thermal-boundaries-lattice.json"), 40, 10, 30)
        suite.equivalence_case("t1-sloshing", repo_case("free-surface-sloshing-lattice.json"), 3000, 500, 1500)
        suite.equivalence_case("t1-fill-drain", repo_case("free-surface-fill-drain-lattice.json"), 200, 50, 100)
        suite.equivalence_case("t1-dam-break", repo_case("free-surface-dam-break-lattice.json"), 20, 5, 10)
        suite.equivalence_case("t1-translation-stop", repo_case("dynamic-translation-stop-lattice.json"), 60, 15, 30)
        suite.equivalence_case("t1-sinusoidal-multi", repo_case("dynamic-sinusoidal-multi-lattice.json"), 480, 120, 240)
        suite.equivalence_case("t1-water-entry-ca60", repo_case("dynamic-water-entry-lattice.json"), 350, 70, 175,
                               patch=lambda c: c["geometry"][0].__setitem__("contact_angle", 60.0))
        suite.equivalence_case("t1-thermal-cycle", repo_case("dynamic-thermal-cycle-lattice.json"), 600, 150, 300)
        suite.equivalence_case("t1-combined-container",
                               repo_case("thermal-free-surface-dynamic-fill-drain-lattice.json"), 200, 50, 100)

        # T1-8: forced kill mid-run (G2 crash window), restart to completion
        def t1_kill_resume():
            base = base_case(steps=20000, cells=(64, 64, 64))
            base["output"] = {"vtk_fields": ["u"], "vtk_every": 5000, "initial": True}
            base["analysis"] = {"every": 997, "start_step": 3, "statistics": True,
                                "probes": [{"id": "center", "position": [32.0, 32.0, 32.0]}]}
            cfg_a = copy.deepcopy(base)
            cfg_a["run"].update(steps=20000, monitor_every=1000, checkpoint_every=1000, checkpoint_keep=2)
            ref = suite.run_solver("t1-kill-ref", config=cfg_a, timeout=3600)
            kill_dir = suite.root / "t1-kill"
            kill_dir.mkdir(exist_ok=True)
            write(kill_dir / "case.json", cfg_a)
            results = kill_dir / "results"
            process = suite.launch_solver("t1-kill", kill_dir / "case.json", results)
            latest = results / "checkpoint" / "latest.json"
            deadline = time.time() + 1200
            while not latest.exists():
                assert process.poll() is None, f"killed run exited early: {process.poll()}"
                assert time.time() < deadline, "first checkpoint never appeared"
                time.sleep(0.05)
            time.sleep(0.3)  # land in an arbitrary phase (mid-output or mid-save)
            process.kill()
            process.wait()
            cont = suite.run_solver("t1-kill-cont", config_path=kill_dir / "case.json",
                                    restart=True, output=results, timeout=3600)
            s = suite.restarted_step(cont["stdout"])
            assert s % 1000 == 0 and 0 < s < 20000, f"unexpected restore step {s}"
            failures = suite.compare_continuation("t1-kill", ref["results"], results, s)
            assert not failures, "; ".join(failures[:6])
            return {"restored_from": s, "killed_phase": "arbitrary (0.3s after first latest.json)"}
        suite.test("t1-kill-resume", t1_kill_resume)

        # T1-9/10: consecutive extensions and a restore chain of two restarts
        def t1_restore_chain():
            cfg_a, cfg_b = suite.split_case(base_case(), 120, 20, 40)
            cfg_mid = copy.deepcopy(cfg_a)
            cfg_mid["run"]["steps"] = 80
            ref = suite.run_solver("t1-chain-ref", config=cfg_a)
            split = suite.run_solver("t1-chain-b", config=cfg_b)
            mid_dir = suite.root / "t1-chain-c1"
            mid_dir.mkdir()
            write(mid_dir / "case.json", cfg_mid)
            c1 = suite.run_solver("t1-chain-c1", config_path=mid_dir / "case.json",
                                   restart=True, output=split["results"])
            assert suite.restarted_step(c1["stdout"]) == 40
            final_dir = suite.root / "t1-chain-c2"
            final_dir.mkdir()
            write(final_dir / "case.json", cfg_a)
            c2 = suite.run_solver("t1-chain-c2", config_path=final_dir / "case.json",
                                  restart=True, output=split["results"])
            assert suite.restarted_step(c2["stdout"]) == 80
            failures = suite.compare_continuation("t1-chain", ref["results"], split["results"], 40,
                                                  extra_stamps={40, 80})
            assert not failures, "; ".join(failures[:6])
            completion = read(split["results"] / "completion.json")
            chain = completion.get("restarts")
            assert isinstance(chain, list) and len(chain) == 2, f"restarts chain wrong: {chain}"
            assert [entry["source_step"] for entry in chain] == [40, 80], chain
            assert chain[0]["restart_index"] == 1 and chain[1]["restart_index"] == 2, chain
            return {"chain": [entry["source_step"] for entry in chain]}
        suite.test("t1-restore-chain", t1_restore_chain)

        # ------------------------------------------------------------------
        # T2: commit protocol, fallback, repair, finish-only, locks
        # ------------------------------------------------------------------
        def t2_fault_graceful(stage):
            def body():
                cfg_a, cfg_b = suite.split_case(base_case(steps=40), 40, 10, 20)
                cfg_b["run"]["steps"] = 40
                split = suite.run_solver(f"t2-{stage}-b", config=cfg_b, fault=f"{stage}#2",
                                         expect_exit=EXIT_SAVE_FAILED)
                results = split["results"]
                published = suite.checkpoint_dirs(results)
                assert list(published) == [10], f"published set after {stage}: {list(published)}"
                tmps = list((results / "checkpoint").glob("*.tmp"))
                assert not tmps, f"temporary directory not cleaned: {tmps}"
                assert read(results / "checkpoint" / "latest.json")["step"] == 10
                cont = suite.run_solver(f"t2-{stage}-c", config_path=split["directory"] / "case.json",
                                        restart=True, output=results)
                assert suite.restarted_step(cont["stdout"]) == 10
                completion = read(results / "completion.json")
                assert completion["status"] == "succeeded" and completion["steps"] == 40
                return {"stage": stage, "restored_from": 10}
            return body
        for stage in ("fail_write", "short_write", "fail_verify"):
            suite.test(f"t2-graceful-{stage}", t2_fault_graceful(stage))

        def t2_crash_before_rename():
            cfg_a, cfg_b = suite.split_case(base_case(steps=40), 40, 10, 20)
            split = suite.run_solver("t2-crash-before-b", config=cfg_b, fault="crash_before_rename#2",
                                     expect_exit=70)
            results = split["results"]
            assert list(suite.checkpoint_dirs(results)) == [10]
            tmps = list((results / "checkpoint").glob("*.tmp"))
            assert len(tmps) == 1, f"expected the crashed temporary directory to remain: {tmps}"
            cont = suite.run_solver("t2-crash-before-c", config_path=split["directory"] / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 10
            assert read(results / "completion.json")["status"] == "succeeded"
            return {"tmp_ignored": tmps[0].name}
        suite.test("t2-crash-before-rename", t2_crash_before_rename)

        def t2_crash_after_rename():
            cfg_a, cfg_b = suite.split_case(base_case(steps=60), 60, 20, 40)
            split = suite.run_solver("t2-crash-after-b", config=cfg_b, fault="crash_after_rename#2",
                                     expect_exit=71)
            results = split["results"]
            assert list(suite.checkpoint_dirs(results)) == [20, 40], "published-but-unreferenced checkpoint missing"
            assert read(results / "checkpoint" / "latest.json")["step"] == 20, "stale latest.json expected"
            cont_dir = suite.root / "t2-crash-after-c"
            cont_dir.mkdir()
            write(cont_dir / "case.json", cfg_a)
            cont = suite.run_solver("t2-crash-after-c", config_path=cont_dir / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 40, "newest-first scan must prefer the published step 40"
            ref = suite.run_solver("t2-crash-after-ref", config=cfg_a)
            failures = suite.compare_continuation("t2-crash-after", ref["results"], results, 40)
            assert not failures, "; ".join(failures[:6])
            return {"restored_from": 40}
        suite.test("t2-crash-after-rename", t2_crash_after_rename)

        def t2_crash_during_cleanup():
            base = base_case(steps=60)
            cfg = copy.deepcopy(base)
            cfg["run"].update(steps=60, checkpoint_every=10, checkpoint_keep=2)
            split = suite.run_solver("t2-cleanup-b", config=cfg, fault="crash_during_cleanup#3",
                                     expect_exit=72)
            results = split["results"]
            published = suite.checkpoint_dirs(results)
            assert len(published) == 3, f"expected over-retention after cleanup crash: {list(published)}"
            cont = suite.run_solver("t2-cleanup-c", config_path=split["directory"] / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 30
            final = suite.checkpoint_dirs(results)
            assert len(final) <= 2, f"retention not restored after successful saves: {list(final)}"
            assert read(results / "completion.json")["status"] == "succeeded"
            return {"over_retention_observed": sorted(published), "final": sorted(final)}
        suite.test("t2-crash-during-cleanup", t2_crash_during_cleanup)

        def t2_latest_corrupt():
            cfg_a, cfg_b = suite.split_case(base_case(), 120, 20, 40)
            split = suite.run_solver("t2-latest-b", config=cfg_b)
            results = split["results"]
            (results / "checkpoint" / "latest.json").write_bytes(b"{corrupt")
            cont_dir = suite.root / "t2-latest-c"
            cont_dir.mkdir()
            write(cont_dir / "case.json", cfg_a)
            cont = suite.run_solver("t2-latest-c", config_path=cont_dir / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 40
            ref = suite.run_solver("t2-latest-ref", config=cfg_a)
            failures = suite.compare_continuation("t2-latest", ref["results"], results, 40)
            assert not failures, "; ".join(failures[:6])
            return {}
        suite.test("t2-latest-corrupt", t2_latest_corrupt)

        def t2_field_corrupt_fallback():
            cfg_a, cfg_b = suite.split_case(base_case(), 120, 20, 40)
            split = suite.run_solver("t2-corrupt-b", config=cfg_b)
            results = split["results"]
            victim = results / "checkpoint" / "step-000000000040" / "fi.bin"
            with victim.open("ab") as handle:
                handle.write(b"\x00")
            cont_dir = suite.root / "t2-corrupt-c"
            cont_dir.mkdir()
            write(cont_dir / "case.json", cfg_a)
            cont = suite.run_solver("t2-corrupt-c", config_path=cont_dir / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 20, "must fall back to the next-newest candidate"
            quarantine = list((results / "checkpoint" / "quarantine").glob("step-000000000040-*"))
            assert len(quarantine) == 1, f"corrupt candidate not quarantined: {quarantine}"
            assert "Quarantined" in cont["stdout"], "missing quarantine warning"
            ref = suite.run_solver("t2-corrupt-ref", config=cfg_a)
            failures = suite.compare_continuation("t2-corrupt", ref["results"], results, 20)
            assert not failures, "; ".join(failures[:6])
            return {"quarantined": quarantine[0].name, "replayed_across": 40}
        suite.test("t2-field-corrupt-fallback", t2_field_corrupt_fallback)

        def t2_all_corrupt():
            cfg_a, cfg_b = suite.split_case(base_case(steps=40), 40, 10, 20)
            split = suite.run_solver("t2-allcorrupt-b", config=cfg_b)
            results = split["results"]
            for step_dir in suite.checkpoint_dirs(results).values():
                with (step_dir / "fi.bin").open("ab") as handle:
                    handle.write(b"\x00")
            cont = suite.run_solver("t2-allcorrupt-c", config_path=split["directory"] / "case.json",
                                    restart=True, output=results, expect_exit=EXIT_NO_USABLE)
            quarantine = list((results / "checkpoint" / "quarantine").iterdir())
            assert len(quarantine) == 2, f"both candidates must be quarantined: {quarantine}"
            assert "No usable checkpoint" in cont["stderr"], cont["stderr"][-400:]
            return {"exit_code": EXIT_NO_USABLE}
        suite.test("t2-all-corrupt", t2_all_corrupt)

        def t2_host_state_corrupt():
            cfg_a, cfg_b = suite.split_case(base_case(), 120, 20, 40)
            split = suite.run_solver("t2-hoststate-b", config=cfg_b)
            results = split["results"]
            victim = results / "checkpoint" / "step-000000000040" / "host-state.json"
            victim.write_text('{"t": 999}', encoding="utf-8")  # step mismatch -> structural corruption
            cont_dir = suite.root / "t2-hoststate-c"
            cont_dir.mkdir()
            write(cont_dir / "case.json", cfg_a)
            cont = suite.run_solver("t2-hoststate-c", config_path=cont_dir / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 20
            return {}
        suite.test("t2-host-state-corrupt", t2_host_state_corrupt)

        def t2_output_repair():
            cfg_a, cfg_b = suite.split_case(base_case(), 120, 20, 40)
            split = suite.run_solver("t2-repair-b", config=cfg_b)
            results = split["results"]
            monitor = results / "monitor.csv"
            recorded = monitor.stat().st_size
            with monitor.open("a", encoding="utf-8") as handle:
                handle.write("99999,garbage-half-row")  # partial row past the checkpoint record
            stray = results / "rho-000000070.vtk"
            stray.write_bytes(b"# vtk fake stray frame beyond the checkpoint")
            cont_dir = suite.root / "t2-repair-c"
            cont_dir.mkdir()
            write(cont_dir / "case.json", cfg_a)
            cont = suite.run_solver("t2-repair-c", config_path=cont_dir / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 40
            content = monitor.read_text(encoding="utf-8")
            assert "garbage-half-row" not in content, "partial row was not truncated away"
            assert not stray.exists(), "stray VTK frame beyond the checkpoint was not removed"
            ref = suite.run_solver("t2-repair-ref", config=cfg_a)
            failures = suite.compare_continuation("t2-repair", ref["results"], results, 40)
            assert not failures, "; ".join(failures[:6])
            return {"truncated_from_bytes": recorded}
        suite.test("t2-output-repair", t2_output_repair)

        def t2_repair_retry():
            # Repair must be re-entrant: interrupt the continuation after repair, restart again.
            cfg_a, cfg_b = suite.split_case(base_case(steps=20000, cells=(64, 64, 64)), 20000, 2000, 2000)
            cfg_a["run"]["monitor_every"] = 2000
            cfg_a["output"] = {"vtk_fields": ["u"], "vtk_every": 5000, "initial": True}
            cfg_a.pop("analysis", None)
            cfg_b["run"]["monitor_every"] = 2000
            cfg_b = copy.deepcopy(cfg_a)
            cfg_b["run"]["steps"] = 2000
            split = suite.run_solver("t2-retry-b", config=cfg_b, timeout=3600)
            results = split["results"]
            monitor = results / "monitor.csv"
            with monitor.open("a", encoding="utf-8") as handle:
                handle.write("99999,garbage-half-row")
            cont_dir = suite.root / "t2-retry-cont"
            cont_dir.mkdir()
            write(cont_dir / "case.json", cfg_a)
            process = suite.launch_solver("t2-retry-c1", cont_dir / "case.json", results, restart=True)
            deadline = time.time() + 600
            # wait until the repair truncated the garbage row, then kill before the next
            # checkpoint boundary (monitor/checkpoint grid is 2000, so the next one is step 4000)
            repaired = None
            while time.time() < deadline:
                content = monitor.read_text(encoding="utf-8")
                if "garbage-half-row" not in content:
                    repaired = len(content.encode("utf-8"))
                    break
                assert process.poll() is None, "continuation exited before repair could be observed"
                time.sleep(0.02)
            assert repaired is not None, "repair was not observed"
            time.sleep(0.1)
            process.kill()
            process.wait()
            cont = suite.run_solver("t2-retry-c2", config_path=cont_dir / "case.json",
                                    restart=True, output=results, timeout=3600)
            s = suite.restarted_step(cont["stdout"])
            assert s == 2000, f"second restart must reuse the last committed checkpoint, got {s}"
            content = monitor.read_text(encoding="utf-8")
            assert "garbage-half-row" not in content
            ref = suite.run_solver("t2-retry-ref", config=cfg_a, timeout=3600)
            failures = suite.compare_continuation("t2-retry", ref["results"], results, s)
            assert not failures, "; ".join(failures[:6])
            return {"second_restart_from": s}
        suite.test("t2-repair-retry", t2_repair_retry)

        def t2_finish_only():
            base = base_case(steps=40)
            cfg = copy.deepcopy(base)
            cfg["run"].update(steps=40, checkpoint_every=40, checkpoint_keep=2)
            crashed = suite.run_solver("t2-finish-b", config=cfg, fault="crash_after_rename",
                                       expect_exit=71)
            results = crashed["results"]
            assert list(suite.checkpoint_dirs(results)) == [40], "terminal checkpoint not published"
            assert not (results / "statistics.json").exists(), "finish artifacts must be missing pre-restart"
            reference = suite.run_solver("t2-finish-ref", config=cfg)
            cont = suite.run_solver("t2-finish-c", config_path=crashed["directory"] / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 40
            completion = read(results / "completion.json")
            assert completion["status"] == "succeeded" and completion["steps"] == 40
            assert sha_file(results / "statistics.json") == sha_file(reference["results"] / "statistics.json"), \
                "finish-only statistics differ from the continuous reference"
            assert list(suite.checkpoint_dirs(results)) == [40], "finish-only must not create new checkpoints"
            return {"mode": "finish-only"}
        suite.test("t2-finish-only", t2_finish_only)

        def t2_stale_lock():
            cfg_a, cfg_b = suite.split_case(base_case(), 120, 20, 40)
            split = suite.run_solver("t2-stalelock-b", config=cfg_b)
            results = split["results"]
            (results / "run.lock").write_text("999996 stale\n", encoding="utf-8")
            cont_dir = suite.root / "t2-stalelock-c"
            cont_dir.mkdir()
            write(cont_dir / "case.json", cfg_a)
            cont = suite.run_solver("t2-stalelock-c", config_path=cont_dir / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 40
            return {}
        suite.test("t2-stale-lock", t2_stale_lock)

        def t2_active_lock():
            base = base_case(steps=20000, cells=(64, 64, 64))
            base["output"] = {"vtk_fields": ["u"], "vtk_every": 0, "initial": False}
            base.pop("analysis", None)
            cfg = copy.deepcopy(base)
            cfg["run"].update(steps=20000, monitor_every=1000, checkpoint_every=1000, checkpoint_keep=2)
            holder_dir = suite.root / "t2-lock-holder"
            holder_dir.mkdir()
            write(holder_dir / "case.json", cfg)
            results = holder_dir / "results"
            process = suite.launch_solver("t2-lock-holder", holder_dir / "case.json", results)
            try:
                deadline = time.time() + 1200
                while not ((results / "run.lock").exists() and
                           (results / "checkpoint" / "latest.json").exists()):
                    assert process.poll() is None, "lock holder exited early"
                    assert time.time() < deadline, "lock/checkpoint never appeared"
                    time.sleep(0.05)
                attempt_dir = suite.root / "t2-lock-attempt"
                attempt_dir.mkdir()
                cfg2 = copy.deepcopy(cfg)
                cfg2["run"]["steps"] = 20000
                write(attempt_dir / "case.json", cfg2)
                attempt = suite.run_solver("t2-lock-attempt", config_path=attempt_dir / "case.json",
                                           restart=True, output=results, expect_exit=1)
                assert "Another Solver-IBM run is active" in attempt["stderr"] + attempt["stdout"], \
                    "active-lock rejection message missing"
                return {}
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        suite.test("t2-active-lock", t2_active_lock)

        # ------------------------------------------------------------------
        # T3: compatibility rejection (exit 5) and asset policies
        # ------------------------------------------------------------------
        def t3_prepare_split(name="t3"):
            cfg_a, cfg_b = suite.split_case(base_case(), 120, 20, 40)
            split = suite.run_solver(f"{name}-b", config=cfg_b)
            return cfg_a, cfg_b, split

        def t3_rejection(name, mutate, expect_message, target="config"):
            def body():
                cfg_a, cfg_b, split = t3_prepare_split(name)
                results = split["results"]
                before = {p.name: sha_file(p) for p in sorted(results.glob("monitor.csv"))}
                before_ckpts = sorted(suite.checkpoint_dirs(results))
                cont_dir = suite.root / f"{name}-c"
                cont_dir.mkdir()
                if target == "config":
                    mutated = copy.deepcopy(cfg_a)
                    mutate(mutated)
                    write(cont_dir / "case.json", mutated)
                else:
                    write(cont_dir / "case.json", cfg_a)
                    mutate(results)
                attempt = suite.run_solver(name, config_path=cont_dir / "case.json",
                                           restart=True, output=results, expect_exit=EXIT_REJECTED)
                combined = attempt["stderr"] + attempt["stdout"]
                assert expect_message in combined, f"rejection message missing: {combined[-500:]}"
                after = {p.name: sha_file(p) for p in sorted(results.glob("monitor.csv"))}
                assert before == after, "rejection mutated outputs"
                assert before_ckpts == sorted(suite.checkpoint_dirs(results)), "rejection mutated checkpoints"
                return {"rejected": expect_message}
            suite.test(name, body)

        t3_rejection("t3-steps-shrink", lambda c: c["run"].__setitem__("steps", 30),
                     "below the checkpoint step")
        t3_rejection("t3-physics-change", lambda c: c["fluid"].__setitem__("nu", 0.03),
                     "/fluid/nu")
        t3_rejection("t3-storage-change", lambda c: c["solver"].__setitem__("storage", "FP16S"),
                     "/solver/storage")
        t3_rejection("t3-analysis-change",
                     lambda c: c["analysis"]["probes"][0].__setitem__("position", [8.0, 8.0, 8.0]),
                     "/analysis/probes")
        t3_rejection("t3-identity-mismatch",
                     lambda results: _edit_checkpoint_json(results, {"numerical_identity": "0" * 64}),
                     "numerical kernel identity differs", target="results")
        t3_rejection("t3-version-mismatch",
                     lambda results: _edit_checkpoint_json(results, {"version": "9.9.9"}),
                     "product version", target="results")
        t3_rejection("t3-layout-missing-field",
                     lambda results: _edit_checkpoint_json(results, {"drop_layout": "rho.bin"}),
                     "lacks required field", target="results")
        t3_rejection("t3-layout-size",
                     lambda results: _edit_checkpoint_json(results, {"layout_bytes": ["rho.bin", 4]}),
                     "size differs", target="results")
        t3_rejection("t3-endianness",
                     lambda results: _edit_checkpoint_json(results, {"endianness": "big"}),
                     "endianness", target="results")

        def t3_steps_duration_switch():
            base = read(configs / "periodic-si.json")
            cfg_a = copy.deepcopy(base)
            cfg_a.setdefault("run", {})
            cfg_a["run"].update(steps=20, checkpoint_every=10, checkpoint_keep=2)
            cfg_a["run"].pop("duration", None)
            cfg_b = copy.deepcopy(cfg_a)
            cfg_b["run"]["steps"] = 10
            split = suite.run_solver("t3-switch-b", config=cfg_b)
            cont_dir = suite.root / "t3-switch-c"
            cont_dir.mkdir()
            cfg_c = copy.deepcopy(cfg_a)
            cfg_c["run"].pop("steps")
            cfg_c["run"]["duration"] = 1.0
            write(cont_dir / "case.json", cfg_c)
            attempt = suite.run_solver("t3-switch-c", config_path=cont_dir / "case.json",
                                       restart=True, output=split["results"], expect_exit=EXIT_REJECTED)
            assert "cannot switch between run.steps and run.duration" in attempt["stderr"], attempt["stderr"][-400:]
            return {}
        suite.test("t3-steps-duration-switch", t3_steps_duration_switch)

        def t3_asset_changed_and_missing():
            base = read(configs / "dynamic-translation-stop-lattice.json")
            absolute_assets(base, configs)
            asset = Path(base["geometry"][0]["file"])
            case_dir = suite.root / "t3-asset"
            case_dir.mkdir()
            local_asset = case_dir / "object.stl"
            shutil.copyfile(asset, local_asset)
            base["geometry"][0]["file"] = str(local_asset)
            cfg_a = copy.deepcopy(base)
            cfg_a.setdefault("run", {})
            cfg_a["run"].update(steps=60, checkpoint_every=15, checkpoint_keep=2)
            cfg_b = copy.deepcopy(cfg_a)
            cfg_b["run"]["steps"] = 30
            split = suite.run_solver("t3-asset-b", config=cfg_b)
            results = split["results"]
            # changed asset -> rejection
            with local_asset.open("ab") as handle:
                handle.write(b"\x00")
            attempt = suite.run_solver("t3-asset-changed", config_path=split["directory"] / "case.json",
                                       restart=True, output=results, expect_exit=EXIT_REJECTED)
            assert "Asset changed since the original run" in attempt["stderr"], attempt["stderr"][-400:]
            # missing asset -> snapshot fallback with a recorded warning
            local_asset.unlink()
            cont_dir = suite.root / "t3-asset-c"
            cont_dir.mkdir()
            write(cont_dir / "case.json", cfg_a)
            cont = suite.run_solver("t3-asset-missing", config_path=cont_dir / "case.json",
                                    restart=True, output=results)
            assert suite.restarted_step(cont["stdout"]) == 30
            assert "using sealed snapshot" in cont["stdout"], "snapshot fallback warning missing"
            completion = read(results / "completion.json")
            assert completion.get("used_snapshot_assets") is True, completion
            resolved = read(results / "resolved-config.json")
            assert resolved.get("used_snapshot_assets") is True
            ref = suite.run_solver("t3-asset-ref", config=cfg_a)
            failures = suite.compare_continuation("t3-asset", ref["results"], results, 30)
            assert not failures, "; ".join(failures[:6])
            return {"fallback": "inputs/assets snapshot"}
        suite.test("t3-asset-changed-and-missing", t3_asset_changed_and_missing)

        # ------------------------------------------------------------------
        # T4: retention and overhead (informational)
        # ------------------------------------------------------------------
        def t4_keep_policy():
            cfg = copy.deepcopy(base_case())
            cfg["run"].update(steps=40, checkpoint_every=10, checkpoint_keep=1)
            run = suite.run_solver("t4-keep", config=cfg)
            published = suite.checkpoint_dirs(run["results"])
            assert list(published) == [40], f"keep=1 must retain only the newest: {list(published)}"
            return {"published": sorted(published)}
        suite.test("t4-keep-policy", t4_keep_policy)

        def t4_overhead():
            cfg_off = copy.deepcopy(base_case(steps=5000, cells=(64, 64, 64)))
            cfg_off["output"] = {"vtk_fields": ["u"], "vtk_every": 0, "initial": False}
            cfg_off.pop("analysis", None)
            cfg_on = copy.deepcopy(cfg_off)
            cfg_on["run"].update(checkpoint_every=500, checkpoint_keep=2)
            off = suite.run_solver("t4-overhead-off", config=cfg_off, timeout=3600)
            on = suite.run_solver("t4-overhead-on", config=cfg_on, timeout=3600)
            ratio = on["seconds"] / max(off["seconds"], 0.01)
            sizes = sorted((p.name, p.stat().st_size) for p in
                           (on["results"] / "checkpoint" / "step-000000005000").iterdir())
            total = sum(size for _, size in sizes)
            return {"seconds_without": off["seconds"], "seconds_with": on["seconds"],
                    "wall_ratio": round(ratio, 3), "checkpoint_bytes": total,
                    "note": "informational; no pass/fail gate (r2 plan T4-26)"}
        suite.test("t4-overhead", t4_overhead)

    finally:
        suite.cleanup()
        passed = sum(1 for t in suite.report["tests"] if t["status"] == "passed")
        total = len(suite.report["tests"])
        suite.report["status"] = "succeeded" if passed == total else "failed"
        suite.report["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        suite.report["passed"] = passed
        suite.report["total"] = total
        write(suite.root / "report.json", suite.report)
        print(f"CHECKPOINT SUITE: {passed}/{total} passed")
        print(suite.root / "report.json")
    sys.exit(0 if suite.report["status"] == "succeeded" else 1)


def _edit_checkpoint_json(results, mutation):
    """Apply a metadata mutation to the newest checkpoint for rejection tests."""
    directories = Suite.checkpoint_dirs(results)
    newest = directories[max(directories)]
    path = newest / "checkpoint.json"
    metadata = read(path)
    if "numerical_identity" in mutation:
        metadata["numerical_identity"] = mutation["numerical_identity"]
    if "version" in mutation:
        metadata["version"] = mutation["version"]
    if "endianness" in mutation:
        metadata["endianness"] = mutation["endianness"]
    if "drop_layout" in mutation:
        metadata["state_layout"] = [e for e in metadata["state_layout"] if e["name"] != mutation["drop_layout"]]
    if "layout_bytes" in mutation:
        name, value = mutation["layout_bytes"]
        for entry in metadata["state_layout"]:
            if entry["name"] == name:
                entry["bytes"] = value
    write(path, metadata)


if __name__ == "__main__":
    main()
