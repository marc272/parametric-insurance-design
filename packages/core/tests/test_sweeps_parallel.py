"""Tests of parallel sweep execution, ``jobs > 1`` (MAR-105).

The parallel path must leave the same store as the serial one: the same
``run_id`` values, the same records and manifests (apart from wall times and
timestamps), the same sweep manifests and the same outcomes. Toy tests run on
the three-event EventSet of ``conftest.py``; the acceptance test runs a
reduced thesis grid on the parity fixture with ``jobs=1`` and ``jobs=4``.
"""

from __future__ import annotations

import os
import pickle
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from parametric_insurance_design.errors import ConfigError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment import sweeps as module
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import (
    ChecksumMismatchError,
    RunInput,
    load_input,
    policy_fingerprint,
    run_key,
)
from parametric_insurance_design.experiment.store import (
    MANIFESTS_DIR,
    ResultStore,
    StoreError,
)
from parametric_insurance_design.experiment.sweeps import (
    SweepsOutcome,
    SweepWorkerError,
    read_sweep_manifests,
    run_sweep,
    run_sweeps,
)
from parametric_insurance_design.records import ALL_PROBLEMS, TABLES
from parametric_insurance_design.solve import DEFAULT_POLICY, SolverPolicy

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"

needs_fixture = pytest.mark.skipif(
    not (PARITY_EVENTSET.is_dir() and PARITY_CONFIG.is_file()),
    reason="the parity fixture is only in a repository checkout",
)

CLUSTER = {
    "kind": "cluster",
    "n_clusters": 2,
    "strategy": {"kind": "thesis_ward", "beta_tail": 0.5},
}
NOISE = {"kind": "heteroscedastic", "level": 0.3, "n_copies": 2, "seed": 7}
PORTFOLIO_MSE: dict[str, Any] = {
    "scopes": [{"kind": "portfolio"}],
    "objectives": [{"kind": "mse"}],
}
# A policy whose solves fail: the runs are recorded with a failure.
FAILING_POLICY = SolverPolicy(
    lp_solvers=("SCS",),
    qp_solvers=("SCS",),
    accept_inaccurate=False,
    solver_options={"SCS": {"max_iters": 1}},
)


@pytest.fixture
def toy_dir(tmp_path: Path, toy_eventset: EventSet) -> Path:
    """The toy EventSet of ``conftest.py`` as a directory."""
    path = tmp_path / "eventset"
    toy_eventset.to_parquet(path)
    return path


def toy_config(
    eventset_path: Path, output: Path, /, **changes: object
) -> ExperimentConfig:
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "toy",
        "eventset": {"path": str(eventset_path)},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
        "scopes": [{"kind": "individual"}, {"kind": "portfolio"}],
        "objectives": [
            {"kind": "mse"},
            {"kind": "weighted_cvar", "alpha": 0.5, "beta": 0.5},
        ],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.5},
        "output": {"directory": str(output)},
    }
    data.update(changes)
    return parse_config(data)


# -- comparing stores ---------------------------------------------------------


def _volatile(key: str) -> bool:
    """Wall times and timestamps: the only fields allowed to differ.

    ``*_seconds`` and ``seconds`` are the runner's timings, ``*_time`` the
    solver's own (``diagnostics.solver_solve_time``).
    """
    return (
        key in {"created_at", "seconds"}
        or key.endswith("_seconds")
        or key.endswith("_time")
    )


def _stable(value: object) -> object:
    """A JSON value without its wall times and timestamps."""
    if isinstance(value, dict):
        return {k: _stable(v) for k, v in value.items() if not _volatile(k)}
    if isinstance(value, list):
        return [_stable(v) for v in value]
    return value


def _records(store: ResultStore, table: str) -> pd.DataFrame:
    """A record table without its timings, in a fixed row order."""
    frame = store.read(table)
    columns = [str(c) for c in frame.columns if not _volatile(str(c))]
    stable = pd.DataFrame(frame[columns])
    return stable.sort_values(by=columns).reset_index(drop=True)


def assert_same_contents(left: ResultStore, right: ResultStore) -> None:
    """Same runs, records, run manifests and sweep manifests, wall times aside."""
    assert left.run_ids() == right.run_ids()
    assert left.uncommitted_runs() == right.uncommitted_runs() == ()
    for table in TABLES:
        pd.testing.assert_frame_equal(_records(left, table), _records(right, table))
    for run_id in left.run_ids():
        assert _stable(left.manifest(run_id)) == _stable(right.manifest(run_id))
    assert [_stable(m) for m in read_sweep_manifests(left)] == [
        _stable(m) for m in read_sweep_manifests(right)
    ]


def outcomes(outcome: SweepsOutcome) -> list[Any]:
    """Baseline outcomes, then (sweep id, point, outcome) of every point."""
    return [
        *outcome.baseline,
        *((s.sweep_id, p.point, p.outcome) for s in outcome.sweeps for p in s.points),
    ]


def two_stores(tmp_path: Path) -> tuple[ResultStore, ResultStore]:
    return ResultStore(tmp_path / "serial"), ResultStore(tmp_path / "parallel")


# -- the parallel path is the serial path ---------------------------------------


def test_parallel_sweeps_write_what_serial_sweeps_write(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path / "unused",
        noise=NOISE,
        sweeps=[
            {"parameter": "alpha", "values": [0.5, 0.9]},
            {"parameter": "n_bins", "values": [2, 3]},
            {"parameter": "noise_level", "values": [0.0, 0.3]},
            {"parameter": "n_assets", "values": [1, 2]},
        ],
    )
    serial, parallel = two_stores(tmp_path)
    one = run_sweeps(config, store=serial, jobs=1)
    many = run_sweeps(config, store=parallel, jobs=3)
    assert outcomes(one) == outcomes(many)
    assert [s.manifest_path.name for s in one.sweeps] == [
        s.manifest_path.name for s in many.sweeps
    ]
    assert_same_contents(serial, parallel)
    # Baseline-equal points are cache hits that keep "single_run".
    alpha = many.sweeps[0]
    assert [p.outcome.source for p in alpha.points[:2]] == ["single_run"] * 2
    assert alpha.n_cached == 2

    # Re-running is all cache hits; it rewrites the sweep manifests.
    again = [
        run_sweeps(config, store=s, jobs=j) for s, j in ((serial, 1), (parallel, 2))
    ]
    assert outcomes(again[0]) == outcomes(again[1])
    assert all(o.cached for o in again[1].baseline)
    assert all(p.outcome.cached for s in again[1].sweeps for p in s.points)
    assert_same_contents(serial, parallel)


def test_parallel_failed_points_are_recorded_as_serially(
    toy_dir: Path, tmp_path: Path
) -> None:
    # Two clusters cannot be built from one location: a run-level failure.
    config = toy_config(
        toy_dir,
        tmp_path,
        scopes=[CLUSTER],
        objectives=[{"kind": "mse"}],
        portfolio={"location_ids": ["A", "B"]},
        sweeps=[{"parameter": "n_assets", "values": [1, 2]}],
    )
    serial, parallel = two_stores(tmp_path)
    one = run_sweeps(config, store=serial)
    many = run_sweeps(config, store=parallel, jobs=2)
    (result,) = many.sweeps
    assert [p.point.location_ids for p in result.failed] == [("A",), ("B",)]
    assert all(p.outcome.failed == (ALL_PROBLEMS,) for p in result.failed)
    assert outcomes(one) == outcomes(many)
    assert_same_contents(serial, parallel)


@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
def test_parallel_force_and_retry_failed_match_the_serial_path(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        **PORTFOLIO_MSE,
        sweeps=[{"parameter": "n_bins", "values": [2, 4]}],
    )
    serial, parallel = two_stores(tmp_path)
    runs: list[tuple[bool, bool]] = [(False, False)] * 2 + [
        (True, False),
        (False, True),
    ]
    for force, retry_failed in runs:
        one, many = (
            run_sweeps(
                config,
                store=store,
                policy=FAILING_POLICY,
                force=force,
                retry_failed=retry_failed,
                jobs=jobs,
            )
            for store, jobs in ((serial, 1), (parallel, 2))
        )
        assert outcomes(one) == outcomes(many)
        assert not any(o.ok for o in many.baseline)
    assert_same_contents(serial, parallel)


@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
@pytest.mark.parametrize(
    "options",
    [{}, {"force": True}, {"retry_failed": True}],
    ids=["cache", "force", "retry_failed"],
)
def test_duplicate_runs_get_the_serial_outcomes(
    toy_dir: Path, tmp_path: Path, options: dict[str, bool]
) -> None:
    # One dispatch with repeated run_ids, succeeding and failing ones.
    good = toy_config(toy_dir, tmp_path, **PORTFOLIO_MSE)
    failing = toy_config(
        toy_dir,
        tmp_path,
        scopes=[{**CLUSTER, "n_clusters": 3}],  # 3 clusters of 2 locations
        objectives=[{"kind": "mse"}],
    )
    configs = [good, failing, good, failing, good]
    data = load_input(good)
    serial, parallel = two_stores(tmp_path)
    common: dict[str, Any] = {
        "source": "n_bins_sweep",
        "policy": DEFAULT_POLICY,
        "force": False,
        "retry_failed": False,
        **options,
    }
    with module._workers(2, data) as workers:
        for _ in range(2):  # an empty store, then a full one
            expected = module._run_all(configs, data, serial, workers=None, **common)
            got = module._run_all(configs, data, parallel, workers=workers, **common)
            assert got == expected
            assert [o.ok for o in got] == [True, False, True, False, True]
    assert len(parallel.run_ids()) == 2
    assert_same_contents(serial, parallel)


def test_run_sweep_alone_runs_in_parallel(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir, tmp_path, sweeps=[{"parameter": "alpha", "values": [0.5, 0.7]}]
    )
    data = load_input(config)
    serial, parallel = two_stores(tmp_path)
    one = run_sweep(config, "alpha", data, serial)
    many = run_sweep(config, "alpha", data, parallel, jobs=2)
    assert one.points == many.points
    assert one.sweep_id == many.sweep_id
    assert_same_contents(serial, parallel)


# -- no silent failures -------------------------------------------------------


def test_worker_errors_propagate_with_their_type(toy_dir: Path, tmp_path: Path) -> None:
    # The runner refuses k-fold samples; here it does so inside a worker.
    config = toy_config(
        toy_dir,
        tmp_path,
        **PORTFOLIO_MSE,
        sample={"kind": "kfold", "k": 2},
        sweeps=[{"parameter": "n_bins", "values": [3]}],
    )
    store = ResultStore(tmp_path / "store")
    with pytest.raises(ConfigError, match="k-fold"):
        run_sweeps(config, store=store, baseline=False, jobs=2)
    assert store.run_ids() == ()
    assert read_sweep_manifests(store) == ()


def test_a_store_error_leaves_the_earlier_points_as_serially(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(toy_dir, tmp_path, **PORTFOLIO_MSE)
    (base,) = config.single_runs()
    configs = [base.with_parameter("n_bins", n) for n in (2, 3, 4, 5)]
    data = load_input(config)
    run_ids = [run_key(config_hash(c), data.checksum) for c in configs]
    common: dict[str, Any] = {
        "source": "n_bins_sweep",
        "policy": DEFAULT_POLICY,
        "force": False,
        "retry_failed": False,
    }
    for name, jobs in (("serial", 1), ("parallel", 2)):
        store = ResultStore(tmp_path / name)
        module._run_all(configs[2:3], data, store, workers=None, **common)
        # The cached run of the third point has an unreadable manifest.
        (store.root / MANIFESTS_DIR / f"{run_ids[2][7:]}.json").write_text("{bad")
        with (
            module._workers(jobs, data) as workers,
            pytest.raises(StoreError, match="not valid JSON"),
        ):
            module._run_all(configs, data, store, workers=workers, **common)
        assert [store.has_run(r) for r in run_ids] == [True, True, True, False]
        assert store.uncommitted_runs() == ()


def test_a_dead_worker_is_a_typed_error(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(toy_dir, tmp_path, **PORTFOLIO_MSE)
    data = load_input(config)
    store = ResultStore(tmp_path / "store")
    # A worker process that exits as it starts breaks the pool, as a crash does.
    executor = ProcessPoolExecutor(
        max_workers=1,
        mp_context=get_context("spawn"),
        initializer=os._exit,
        initargs=(3,),
    )
    try:
        with pytest.raises(SweepWorkerError, match="worker process died"):
            module._run_all(
                config.single_runs(),
                data,
                store,
                source="single_run",
                policy=DEFAULT_POLICY,
                force=False,
                retry_failed=False,
                workers=module._Workers(executor, data, 1),
            )
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    assert store.run_ids() == ()


def test_a_worker_without_the_input_refuses_to_run(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(toy_dir, tmp_path, **PORTFOLIO_MSE)
    data = load_input(config)
    (single,) = config.single_runs()
    sent = module._PolicyFields.of(DEFAULT_POLICY)
    with pytest.raises(SweepWorkerError, match="no input or another input"):
        module._execute_in_worker(single, data.checksum, "single_run", sent)
    module._init_worker(data)
    try:
        with pytest.raises(SweepWorkerError, match="another input"):
            module._execute_in_worker(single, "sha256:0", "single_run", sent)
        tables, manifest = module._execute_in_worker(
            single, data.checksum, "single_run", sent
        )
        assert manifest["run_id"] == tables.run_id
    finally:
        module._worker_data = None


@pytest.mark.parametrize("policy", [DEFAULT_POLICY, FAILING_POLICY, SolverPolicy()])
def test_policies_survive_the_trip_to_a_worker(policy: SolverPolicy) -> None:
    # SolverPolicy itself cannot be pickled (read-only option mappings).
    sent = module._PolicyFields.of(policy)
    rebuilt = pickle.loads(pickle.dumps(sent)).policy()
    assert rebuilt == policy
    assert type(rebuilt) is type(policy)
    assert policy_fingerprint(rebuilt) == policy_fingerprint(policy)


def test_the_pool_must_hold_the_sweep_input(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(toy_dir, tmp_path, **PORTFOLIO_MSE)
    data = load_input(config)
    with module._workers(2, data) as workers, pytest.raises(ValueError, match="pool"):
        module._run_all(
            config.single_runs(),
            load_input(config),  # equal, but another object
            ResultStore(tmp_path / "store"),
            source="single_run",
            policy=DEFAULT_POLICY,
            force=False,
            retry_failed=False,
            workers=workers,
        )


@pytest.mark.parametrize("jobs", [0, -1, True, 1.5, "2"])
def test_jobs_must_be_a_positive_integer(
    toy_dir: Path, tmp_path: Path, jobs: object
) -> None:
    config = toy_config(
        toy_dir, tmp_path, sweeps=[{"parameter": "alpha", "values": [0.5]}]
    )
    store = ResultStore(tmp_path / "store")
    with pytest.raises(ConfigError, match="jobs must be a positive integer"):
        run_sweeps(config, store=store, jobs=jobs)  # pyright: ignore[reportArgumentType]
    with pytest.raises(ConfigError, match="jobs must be a positive integer"):
        run_sweep(config, "alpha", load_input(config), store, jobs=jobs)  # pyright: ignore[reportArgumentType]
    assert not store.root.exists()


@pytest.mark.parametrize("jobs", [1, 2])
def test_the_pinned_checksum_is_checked(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet, jobs: int
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        eventset={"path": str(toy_dir), "checksum": "sha256:" + "0" * 64},
        sweeps=[{"parameter": "alpha", "values": [0.5]}],
    )
    store = ResultStore(tmp_path / "store")
    data = RunInput.from_eventset(toy_eventset)
    with pytest.raises(ChecksumMismatchError, match=r"pins eventset\.checksum"):
        run_sweep(config, "alpha", data, store, jobs=jobs)
    assert store.run_ids() == ()


# -- acceptance: a reduced thesis grid ------------------------------------------


@needs_fixture
@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
def test_reduced_thesis_grid_is_the_same_with_four_jobs(tmp_path: Path) -> None:
    # MAR-105: the same run_ids and results with jobs=1 and jobs=4, on every
    # kind of sweep of the thesis config, on the parity fixture.
    config = load_config(PARITY_CONFIG)
    data = config.model_dump(mode="python", round_trip=True)
    data["scopes"] = [s for s in data["scopes"] if s["kind"] != "individual"]
    data["objectives"] = [o for o in data["objectives"] if o["kind"] == "weighted_cvar"]
    data["sweeps"] = [
        {"parameter": "alpha", "values": [0.5, 0.9]},
        {"parameter": "budget_loading", "values": [1.5]},
        {"parameter": "n_bins", "values": [3]},
        {"parameter": "n_clusters", "values": [2]},
        {"parameter": "noise_level", "values": [0.0]},
        {"parameter": "n_assets", "values": [8], "max_combinations": 2, "seed": 42},
    ]
    data["eventset"]["path"] = str(PARITY_EVENTSET)
    config = parse_config(data)
    serial, parallel = two_stores(tmp_path)
    one = run_sweeps(config, store=serial, jobs=1)
    many = run_sweeps(config, store=parallel, jobs=4)
    assert outcomes(one) == outcomes(many)
    assert_same_contents(serial, parallel)
    # 2 baseline runs, 2 new alpha points (alpha = 0.9 is the baseline), and
    # 2 + 2 + 1 + 2 + 4 points of the other sweeps: 15 distinct runs.
    assert len(serial.run_ids()) == 15
    assert all(o.ok for o in outcomes(many)[:2])
