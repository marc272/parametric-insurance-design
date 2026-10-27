"""Tests of the ``parametric-insurance-design`` command (MAR-66).

The commands run in-process through :func:`cli.main` on toy configs written
as YAML next to the three-event EventSet of ``conftest.py``.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import sys
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any, Protocol

import pytest
import yaml

from parametric_insurance_design import cli
from parametric_insurance_design.cli import ExitCode, main
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import config_hash, load_config
from parametric_insurance_design.experiment.runner import load_input, run_key
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.experiment.sweeps import SWEEPS_DIR
from parametric_insurance_design.solve import DEFAULT_POLICY, THESIS_POLICY

CLUSTER = {
    "kind": "cluster",
    "n_clusters": 3,  # the toy EventSet has 2 locations: a build failure
    "strategy": {"kind": "thesis_ward", "beta_tail": 0.5},
}


def toy_dict(**changes: object) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "toy",
        "eventset": {"path": "eventset"},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
        "scopes": [{"kind": "individual"}, {"kind": "portfolio"}],
        "objectives": [
            {"kind": "mse"},
            {"kind": "weighted_cvar", "alpha": 0.5, "beta": 0.5},
        ],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.5},
        "output": {"directory": "results"},
    }
    data.update(changes)
    return data


class WriteConfig(Protocol):
    """Factory of toy config files (the ``write_config`` fixture)."""

    def __call__(self, name: str = ..., **changes: object) -> Path: ...


@pytest.fixture
def write_config(tmp_path: Path, toy_eventset: EventSet) -> WriteConfig:
    """Write the toy EventSet and return a factory of config files beside it."""
    toy_eventset.to_parquet(tmp_path / "eventset")

    def write(name: str = "toy.yaml", **changes: object) -> Path:
        path = tmp_path / name
        path.write_text(yaml.safe_dump(toy_dict(**changes)), encoding="utf-8")
        return path

    return write


SWEEP = {
    "scopes": [{"kind": "portfolio"}],
    "objectives": [{"kind": "mse"}],
    "sweeps": [
        {"parameter": "n_bins", "values": [2, 4]},
        {"parameter": "budget_loading", "values": [1.0, 1.5]},
    ],
}


def lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines()]


# -- arguments ----------------------------------------------------------------


def test_entry_point_is_declared() -> None:
    (script,) = entry_points(
        group="console_scripts", name="parametric-insurance-design"
    )
    assert script.value == "parametric_insurance_design.cli:main"
    assert script.load() is main


def test_help_and_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--help"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "run" in out
    assert "sweep" in out
    assert main(["--version"]) == ExitCode.OK
    assert capsys.readouterr().out.startswith("parametric-insurance-design ")
    assert main(["sweep", "--help"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "--dry-run" in out
    assert "parity gate only" in out


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["frobnicate", "x.yaml"],
        ["run"],
        ["run", "x.yaml", "--policy", "fast"],
        ["run", "x.yaml", "--force", "--retry-failed"],
        ["run", "x.yaml", "-v", "-q"],
        ["sweep", "x.yaml", "--parameter", "gamma"],
        ["run", "x.yaml", "--parameter", "alpha"],
    ],
)
def test_usage_errors_exit_2(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(argv) == ExitCode.USAGE
    assert "usage:" in capsys.readouterr().err


def test_policies_are_the_solver_policies() -> None:
    assert cli.POLICIES == {"default": DEFAULT_POLICY, "thesis": THESIS_POLICY}


def test_python_m_runs_the_command() -> None:
    done = subprocess.run(
        [sys.executable, "-m", "parametric_insurance_design.cli", "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("parametric-insurance-design ")


# -- run ----------------------------------------------------------------------


def test_run_writes_the_runs_then_hits_the_cache(
    write_config: WriteConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config()
    assert main(["run", str(path)]) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert out[-1] == "4 runs: 0 cached, 0 failed"
    ran = [line for line in out if line.startswith("ran")]
    assert len(ran) == 4
    assert all(line.endswith(" ok") for line in ran)
    assert any("portfolio x weighted_cvar" in line for line in ran)
    store = ResultStore(tmp_path / "results")
    assert len(store.run_ids()) == 4
    assert set(store.read("runs")["source"]) == {"single_run"}

    assert main(["run", str(path)]) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert out[-1] == "4 runs: 4 cached, 0 failed"
    assert sum(line.startswith("cached") for line in out) == 4

    assert main(["run", str(path), "--force"]) == ExitCode.OK
    assert lines(capsys.readouterr().out)[-1] == "4 runs: 0 cached, 0 failed"


def test_run_dry_run_prints_the_plan_and_writes_nothing(
    write_config: WriteConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config()
    config = load_config(path)
    checksum = load_input(config).checksum
    ids = [run_key(config_hash(s), checksum) for s in config.single_runs()]

    assert main(["run", str(path), "--dry-run"]) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert not (tmp_path / "results").exists()
    assert out[0] == f"dry run: 'toy', store {tmp_path / 'results'}"
    assert out[1] == f"input checksum {checksum}, policy 'default'"
    assert out[2] == "runs:"
    plan = out[3:7]
    assert [line.split()[0] for line in plan] == ["run"] * 4
    assert [cli._short(i) in line for line, i in zip(plan, ids, strict=True)] == [
        True
    ] * 4
    assert "individual x mse" in plan[0]
    assert out[-1] == "plan: 4 runs, 4 to run, 0 cached"

    assert main(["run", str(path), "-q"]) == ExitCode.OK
    capsys.readouterr()
    assert main(["run", str(path), "--dry-run"]) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert [line.split()[0] for line in out[3:7]] == ["cached"] * 4
    assert out[-1] == "plan: 4 runs, 0 to run, 4 cached"

    assert main(["run", str(path), "--dry-run", "--force"]) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert all(line.startswith("run (--force)") for line in out[3:7])
    assert out[-1] == "plan: 4 runs, 4 to run, 0 cached"


def test_thesis_policy_is_another_run(
    write_config: WriteConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(scopes=[{"kind": "portfolio"}], objectives=[{"kind": "mse"}])
    config = load_config(path)
    (single,) = config.single_runs()
    checksum = load_input(config).checksum
    thesis = run_key(config_hash(single), checksum, policy=THESIS_POLICY)
    default = run_key(config_hash(single), checksum, policy=DEFAULT_POLICY)
    assert thesis != default

    assert main(["run", str(path), "--dry-run", "--policy", "thesis"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "policy 'thesis'" in out
    assert cli._short(thesis) in out
    assert main(["run", str(path), "-q", "--policy", "thesis"]) == ExitCode.OK
    assert cli._short(thesis) in capsys.readouterr().out
    store = ResultStore(load_config(path).output.directory)
    assert store.run_ids() == (thesis,)
    manifest = store.manifest(thesis)
    policy = manifest["cache_key"]["solver_policy"]
    assert policy["solver_options"]["SCS"] == {"max_iters": 20000}


def test_failed_runs_exit_1_and_are_listed(
    write_config: WriteConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(
        scopes=[CLUSTER, {"kind": "portfolio"}], objectives=[{"kind": "mse"}]
    )
    assert main(["run", str(path), "-q"]) == ExitCode.RUNS_FAILED
    out = lines(capsys.readouterr().out)
    assert out[-1] == "2 runs: 0 cached, 1 failed"
    (failed,) = [line for line in out if "FAILED" in line]
    assert "FAILED (*)" in failed
    assert "cluster x mse" in failed

    # Cached failures still fail the command, and a dry run shows them.
    assert main(["run", str(path), "-q"]) == ExitCode.RUNS_FAILED
    capsys.readouterr()
    assert main(["run", str(path), "--dry-run"]) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert out[3].startswith("cached (failed)")
    assert out[4].startswith("cached ")
    assert main(["run", str(path), "--dry-run", "--retry-failed"]) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert out[3].startswith("run (--retry-failed)")
    assert out[-1] == "plan: 2 runs, 1 to run, 1 cached"


def test_not_evaluated_status() -> None:
    from parametric_insurance_design.experiment.runner import RunOutcome

    outcome = RunOutcome("sha256:" + "0" * 64, "h", "c", "single_run", cached=False)
    assert cli._outcome_status(outcome) == "FAILED (not evaluated)"


# -- sweep --------------------------------------------------------------------


def test_sweep_runs_the_baseline_and_the_sweeps(
    write_config: WriteConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(**SWEEP)
    assert main(["sweep", str(path)]) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert out[1] == "baseline:"
    assert out[2].startswith("ran")
    # n_bins = 2 and budget_loading = 1.0 are the baseline: cache hits.
    n_bins = next(line for line in out if line.startswith("sweep n_bins:"))
    assert n_bins.startswith("sweep n_bins: 2 points, 1 cached, 0 failed")
    loading = next(line for line in out if line.startswith("sweep budget_loading:"))
    assert loading.startswith("sweep budget_loading: 2 points, 1 cached, 0 failed")
    assert out[-1] == "5 runs: 0 failed"
    manifests = sorted((tmp_path / "results" / SWEEPS_DIR).glob("*.json"))
    assert len(manifests) == 2
    assert {json.loads(m.read_text())["parameter"] for m in manifests} == {
        "n_bins",
        "budget_loading",
    }


def test_sweep_dry_run_marks_points_planned_above(
    write_config: WriteConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(**SWEEP)
    assert main(["sweep", str(path), "--dry-run"]) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert not (tmp_path / "results").exists()
    assert out[2:] == [
        "baseline:",
        out[3],
        "sweep n_bins (2 points):",
        out[5],
        out[6],
        "sweep budget_loading (2 points):",
        out[8],
        out[9],
        "plan: 5 runs, 3 to run, 2 cached",
    ]
    assert out[3].startswith("run ")
    assert out[5].startswith("cached (planned above)")
    assert "n_bins=2 portfolio x mse" in out[5]
    assert out[6].startswith("run ")
    assert "n_bins=4 portfolio x mse" in out[6]
    assert out[8].startswith("cached (planned above)")
    assert "budget_loading=1.0" in out[8]

    # Without the baseline, the baseline-equal point is the first to run it.
    argv = ["sweep", str(path), "--dry-run", "--no-baseline", "-p", "n_bins"]
    assert main(argv) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert out[2:] == ["sweep n_bins (2 points):", out[3], out[4], out[5]]
    assert out[3].startswith("run ")
    assert out[-1] == "plan: 2 runs, 2 to run, 0 cached"


def test_sweep_dry_run_lists_n_assets_subsets(
    write_config: WriteConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(
        scopes=[{"kind": "portfolio"}],
        objectives=[{"kind": "mse"}],
        sweeps=[{"parameter": "n_assets", "values": [1, 2]}],
    )
    assert main(["sweep", str(path), "--dry-run", "--no-baseline"]) == ExitCode.OK
    out = capsys.readouterr().out
    assert "n_assets=1 [A] portfolio x mse" in out
    assert "n_assets=1 [B] portfolio x mse" in out
    assert "n_assets=2 [A,B] portfolio x mse" in out


def test_sweep_selects_parameters_and_skips_the_baseline(
    write_config: WriteConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(**SWEEP)
    argv = ["sweep", str(path), "--parameter", "n_bins", "--no-baseline", "-q"]
    assert main(argv) == ExitCode.OK
    out = lines(capsys.readouterr().out)
    assert "baseline:" not in out
    assert [line.split(":")[0] for line in out if line.startswith("sweep ")] == [
        "sweep 'toy' into " + str(tmp_path / "results"),
        "sweep n_bins",
    ]
    assert out[-1] == "2 runs: 0 failed"
    store = ResultStore(tmp_path / "results")
    assert set(store.read("runs")["source"]) == {"n_bins_sweep"}


def test_sweep_failures_exit_1_and_list_the_points(
    write_config: WriteConfig, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write_config(
        scopes=[{**CLUSTER, "n_clusters": 2}],
        objectives=[{"kind": "mse"}],
        portfolio={"location_ids": ["A", "B"]},
        sweeps=[{"parameter": "n_assets", "values": [1, 2]}],
    )
    assert main(["sweep", str(path), "-q"]) == ExitCode.RUNS_FAILED
    out = lines(capsys.readouterr().out)
    assert any(
        line.startswith("sweep n_assets: 3 points, 1 cached, 2 failed") for line in out
    )
    failed = [line for line in out if "FAILED" in line]
    assert len(failed) == 2
    assert "n_assets=1 [A] cluster x mse" in failed[0]
    assert out[-1] == "4 runs: 2 failed"


@pytest.mark.parametrize(
    ("changes", "argv", "message"),
    [
        ({}, [], "has no sweeps; use 'run'"),
        (SWEEP, ["-p", "alpha"], "has no sweep of ['alpha']"),
        (SWEEP, ["-p", "alpha", "--dry-run"], "has no sweep of ['alpha']"),
    ],
)
def test_sweep_refuses_missing_sweeps(
    write_config: WriteConfig,
    caplog: pytest.LogCaptureFixture,
    changes: dict[str, Any],
    argv: list[str],
    message: str,
) -> None:
    path = write_config(**changes)
    assert main(["sweep", str(path), *argv]) == ExitCode.INPUT_ERROR
    assert message in caplog.text
    assert not (path.parent / "results").exists()


def _without_timings(out: str) -> list[str]:
    return [re.sub(r"\d+\.\d s;", "_ s;", line) for line in lines(out)]


def test_sweep_jobs_runs_in_worker_processes(
    write_config: WriteConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # MAR-105: --jobs N gives the serial summary and the same store.
    serial = write_config("serial.yaml", **SWEEP)
    parallel = write_config(
        "parallel.yaml", **SWEEP, output={"directory": "results-parallel"}
    )
    assert main(["sweep", str(serial), "-q"]) == ExitCode.OK
    expected = _without_timings(capsys.readouterr().out)
    assert main(["sweep", str(parallel), "-q", "--jobs", "2"]) == ExitCode.OK
    got = _without_timings(capsys.readouterr().out)
    assert got[1:] == expected[1:]  # the first line names the store
    left = ResultStore(tmp_path / "results")
    right = ResultStore(tmp_path / "results-parallel")
    assert left.run_ids() == right.run_ids()
    assert len(right.run_ids()) == 5
    manifests = [
        sorted(p.name for p in (store.root / SWEEPS_DIR).glob("*.json"))
        for store in (left, right)
    ]
    assert manifests[0] == manifests[1]
    assert len(manifests[0]) == 2


@pytest.mark.parametrize("jobs", ["0", "-2", "two", "1.5"])
def test_sweep_jobs_must_be_positive(
    jobs: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["sweep", "x.yaml", "--jobs", jobs]) == ExitCode.USAGE
    assert "--jobs" in capsys.readouterr().err


def test_jobs_is_a_sweep_option(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["sweep", "--help"]) == ExitCode.OK
    assert "--jobs N" in capsys.readouterr().out
    assert main(["run", "x.yaml", "--jobs", "2"]) == ExitCode.USAGE


# -- errors and logging -------------------------------------------------------


def test_input_errors_exit_3(
    write_config: WriteConfig, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    assert main(["run", str(tmp_path / "missing.yaml")]) == ExitCode.INPUT_ERROR
    assert "ConfigError: cannot read config" in caplog.text

    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [unclosed", encoding="utf-8")
    assert main(["run", str(bad)]) == ExitCode.INPUT_ERROR
    assert "not valid YAML" in caplog.text

    path = write_config(eventset={"path": "eventset", "checksum": "sha256:" + "0" * 64})
    assert main(["run", str(path), "--dry-run"]) == ExitCode.INPUT_ERROR
    assert "ChecksumMismatchError" in caplog.text

    (tmp_path / "results").write_text("not a directory", encoding="utf-8")
    assert main(["run", str(write_config())]) == ExitCode.INPUT_ERROR
    assert "StoreError" in caplog.text


def test_unexpected_errors_exit_4_with_a_traceback(
    write_config: WriteConfig,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(cli, "run_config", boom)
    assert main(["run", str(write_config())]) == ExitCode.INTERNAL_ERROR
    (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert record.getMessage() == "internal error"
    assert record.exc_info is not None


def test_interrupt_exits_130(
    write_config: WriteConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupt(*args: object, **kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "run_sweeps", interrupt)
    assert main(["sweep", str(write_config(**SWEEP))]) == ExitCode.INTERRUPTED


@pytest.mark.parametrize(
    ("flag", "debug", "info"),
    [("-v", True, True), (None, False, True), ("-q", False, False)],
)
def test_log_levels(
    write_config: WriteConfig,
    capsys: pytest.CaptureFixture[str],
    flag: str | None,
    debug: bool,
    info: bool,
) -> None:
    logger = logging.getLogger("parametric_insurance_design")
    before = (logger.level, list(logger.handlers))
    path = write_config(**SWEEP)
    argv = ["sweep", str(path), "-p", "n_bins", *([flag] if flag else [])]
    assert main(argv) == ExitCode.OK
    err = capsys.readouterr().err
    assert (
        "DEBUG parametric_insurance_design.experiment.sweeps: sweep n_bins: point"
        in err
    ) is debug
    assert (
        "INFO parametric_insurance_design.experiment.sweeps: sweep n_bins:" in err
    ) is info
    assert (logger.level, list(logger.handlers)) == before
