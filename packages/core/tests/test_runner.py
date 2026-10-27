"""Tests of the run executor and its content-hashed cache (MAR-64).

Toy tests use the three-event EventSet of ``conftest.py``; the acceptance
tests run the thesis configuration (``parity/configs/thesis.yaml``) on the
parity fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from parametric_insurance_design import splits
from parametric_insurance_design.errors import ConfigError, InfeasibleError
from parametric_insurance_design.eventset import EventSet, InconsistentKeysError
from parametric_insurance_design.experiment import runner
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import (
    MANIFEST_FORMAT,
    PACKAGE,
    RUN_KEY_DOMAIN,
    ChecksumMismatchError,
    RunInput,
    RunOutcome,
    execute,
    load_input,
    package_versions,
    policy_fingerprint,
    prepare_eventset,
    run_config,
    run_key,
    run_parameters,
    run_single,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import Sample, SolveStatus
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.records import ALL_PROBLEMS, TABLES
from parametric_insurance_design.solve import DEFAULT_POLICY, SolverPolicy, solve

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"

needs_fixture = pytest.mark.skipif(
    not (PARITY_EVENTSET.is_dir() and PARITY_CONFIG.is_file()),
    reason="the parity fixture is only in a repository checkout",
)


@pytest.fixture
def toy_dir(tmp_path: Path, toy_eventset: EventSet) -> Path:
    """The toy EventSet of ``conftest.py`` as a directory."""
    path = tmp_path / "eventset"
    toy_eventset.to_parquet(path)
    return path


def toy_dict(eventset_path: Path, output: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": "toy",
        "eventset": {"path": str(eventset_path)},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
        "scopes": [{"kind": "individual"}, {"kind": "portfolio"}],
        "objectives": [
            {"kind": "mse"},
            {"kind": "expected_uncovered"},
            {"kind": "weighted_cvar", "alpha": 0.5, "beta": 0.5},
        ],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.5},
        "output": {"directory": str(output)},
    }


def toy_config(
    eventset_path: Path, output: Path, /, **changes: object
) -> ExperimentConfig:
    data = toy_dict(eventset_path, output)
    data.update(changes)
    return parse_config(data)


def single(config: ExperimentConfig, scope: str, objective: str) -> ExperimentConfig:
    for run in config.single_runs():
        if run.scopes[0].kind == scope and run.objectives[0].kind == objective:
            return run
    raise AssertionError(f"no run {scope} x {objective}")


# -- end to end on the toy EventSet ------------------------------------------


def test_run_fills_the_store_and_a_second_run_hits_the_cache(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(toy_dir, tmp_path / "results")
    first = run_config(config)
    assert len(first) == 6
    assert not any(o.cached for o in first)
    assert all(o.ok for o in first)

    store = ResultStore(tmp_path / "results")
    assert set(store.run_ids()) == {o.run_id for o in first}
    sizes = {name: len(store.read(name)) for name in TABLES}
    # individual: 2 problems x 3 objectives; portfolio: 1 x 3
    assert sizes["runs"] == 9
    assert sizes["entities"] == 3 * 2 + 3 * 2
    assert sizes["payouts"] == 3 * 2 * 2 + 3 * 2 * 2
    assert sizes["kpis"] > 0
    assert sizes["exceedance"] > 0
    mtimes = {p: p.stat().st_mtime_ns for p in (tmp_path / "results").rglob("*")}

    second = run_config(config)
    assert all(o.cached for o in second)
    assert [o.run_id for o in second] == [o.run_id for o in first]
    assert [o.statuses for o in second] == [o.statuses for o in first]
    assert {name: len(store.read(name)) for name in TABLES} == sizes
    assert {p: p.stat().st_mtime_ns for p in mtimes} == mtimes  # nothing rewritten


def test_runs_rows_carry_provenance(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    config = toy_config(toy_dir, tmp_path)
    run = single(config, "individual", "weighted_cvar")
    data = load_input(config)
    outcome = run_single(run, data, ResultStore(tmp_path))
    runs = ResultStore(tmp_path).read("runs")
    assert runs["problem_id"].tolist() == ["A", "B"]
    assert set(runs["run_id"]) == {outcome.run_id}
    assert set(runs["config_hash"]) == {config_hash(run)}
    assert set(runs["eventset_checksum"]) == {toy_eventset.content_hash()}
    assert set(runs["package_version"]) == {package_versions()[PACKAGE]}
    assert set(runs["status"]) == {"optimal"}
    assert bool(runs["solver"].notna().all())
    assert bool((runs["build_seconds"] >= 0).all())
    assert bool((runs["solve_seconds"] > 0).all())
    assert bool(runs["error_type"].isna().all())
    assert set(runs["source"]) == {"single_run"}
    assert set(runs["scope"]) == {"individual"}
    assert set(runs["objective"]) == {"weighted_cvar"}
    assert set(runs["calibration_split"]) == {"full"}
    params = json.loads(runs["parameters"].iloc[0])
    assert params["alpha"] == 0.5
    assert params["beta"] == 0.5
    assert params["budget_loading"] == 1.0
    assert params["n_assets"] == 2


def test_stored_payouts_match_a_direct_solve(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    config = toy_config(toy_dir, tmp_path)
    run = single(config, "portfolio", "expected_uncovered")
    run_single(run, load_input(config), ResultStore(tmp_path))
    payouts = ResultStore(tmp_path).read("payouts")

    components = run.to_components()
    (built,) = build_problems(
        toy_eventset,
        components.scopes[0],
        components.payout,
        components.objectives[0],
        components.pricing,
        components.constraints,
        basis=components.basis,
    )
    result = solve(built)
    lower, upper = components.payout.parameter_bounds()
    for j, entity in enumerate(result.entity_ids):
        rows = payouts.loc[payouts["entity_id"] == entity]
        np.testing.assert_array_equal(rows["param_index"], np.arange(len(lower)))
        np.testing.assert_allclose(rows["value"], result.theta[j], rtol=1e-9)
        np.testing.assert_array_equal(rows["lower"], lower)
        np.testing.assert_array_equal(rows["upper"], upper)


def test_manifest_records_provenance(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(toy_dir, tmp_path)
    run = single(config, "portfolio", "mse")
    data = load_input(config)
    outcome = run_single(run, data, ResultStore(tmp_path), source="alpha_sweep")
    m = ResultStore(tmp_path).manifest(outcome.run_id)
    assert m["format"] == MANIFEST_FORMAT
    assert m["source"] == "alpha_sweep"
    assert m["cache_key"] == {
        "domain": RUN_KEY_DOMAIN,
        "config_hash": config_hash(run),
        "eventset_checksum": data.checksum,
        "package_version": package_versions()[PACKAGE],
        "solver_policy": policy_fingerprint(DEFAULT_POLICY),
    }
    assert m["config"]["name"] == "toy"
    assert m["input"]["content_hash"] == data.checksum
    assert m["prepared_eventset"]["content_hash"] == data.checksum  # no transforms
    assert m["environment"]["packages"]["cvxpy"] is not None
    assert set(m["timings"]) == {
        "load_seconds",
        "prepare_seconds",
        "build_seconds",
        "solve_seconds",
        "evaluate_seconds",
        "total_seconds",
    }
    (problem,) = m["problems"]
    assert problem["status"] == "optimal"
    assert problem["attempts"][-1]["solver"] == problem["solver"] == "OSQP"
    assert m["evaluation"] == {"evaluated": True, "skipped_reason": None, "beta": 0.5}
    assert RunOutcome.from_manifest(m, cached=True) == RunOutcome(
        run_id=outcome.run_id,
        config_hash=outcome.config_hash,
        eventset_checksum=outcome.eventset_checksum,
        source="alpha_sweep",
        cached=True,
        statuses=outcome.statuses,
        evaluated=True,
    )


def test_cache_hit_keeps_the_first_source_tag(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(toy_dir, tmp_path)
    run = single(config, "portfolio", "mse")
    data = load_input(config)
    store = ResultStore(tmp_path)
    run_single(run, data, store)
    again = run_single(run, data, store, source="alpha_sweep")
    assert again.cached
    assert again.source == "single_run"
    assert set(store.read("runs")["source"]) == {"single_run"}


# -- failures are recorded ----------------------------------------------------


@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
def test_failing_solve_is_a_runs_row_with_its_error(
    toy_dir: Path, tmp_path: Path
) -> None:
    # SCS stopped after one iteration, inaccurate results refused: every
    # design problem fails with status optimal_inaccurate.
    policy = SolverPolicy(
        lp_solvers=("SCS",),
        accept_inaccurate=False,
        solver_options={"SCS": {"max_iters": 1}},
    )
    config = toy_config(toy_dir, tmp_path)
    run = single(config, "individual", "expected_uncovered")
    store = ResultStore(tmp_path)
    outcome = run_single(run, load_input(config), store, policy=policy)
    assert outcome.failed == ("A", "B")
    assert not outcome.ok
    assert not outcome.evaluated

    runs = store.read("runs")
    assert runs["status"].tolist() == ["optimal_inaccurate"] * 2
    assert runs["error_type"].tolist() == ["SolveError"] * 2
    assert bool(runs["error_message"].str.contains("SCS: optimal_inaccurate").all())
    assert bool(runs["solver"].isna().all())
    assert bool(runs["objective_value"].isna().all())
    assert bool((runs["solve_seconds"] > 0).all())
    assert len(store.read("payouts")) == 0
    assert len(store.read("kpis")) == 0
    assert len(store.read("entities")) == 2  # membership is known
    m = store.manifest(outcome.run_id)
    assert m["evaluation"]["skipped_reason"].startswith("2 of 2 design problems")
    assert [a["solver"] for a in m["problems"][0]["attempts"]] == ["SCS"]


def test_partial_failure_keeps_the_solved_problems(
    toy_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_on_b(built: BuiltProblem, policy: SolverPolicy = DEFAULT_POLICY) -> Any:  # noqa: ANN401
        if built.spec.problem_id == "B":
            raise InfeasibleError(
                "no solver returned an acceptable result [CLARABEL: infeasible]",
                problem_id="B",
                status=SolveStatus.INFEASIBLE,
            )
        return solve(built, policy)

    monkeypatch.setattr(runner, "solve", fail_on_b)
    config = toy_config(toy_dir, tmp_path)
    store = ResultStore(tmp_path)
    outcome = run_single(single(config, "individual", "mse"), load_input(config), store)
    assert outcome.statuses == {"A": SolveStatus.OPTIMAL, "B": SolveStatus.INFEASIBLE}
    runs = store.read("runs").set_index("problem_id")
    assert runs.loc["B", "status"] == "infeasible"
    assert runs.loc["B", "error_type"] == "InfeasibleError"
    assert "[B]" in runs.loc["B", "error_message"]
    assert np.isnan(runs.loc["B", "solve_seconds"])  # no attempts recorded
    assert runs.loc["A", "status"] == "optimal"
    assert set(store.read("payouts")["problem_id"]) == {"A"}
    assert len(store.read("kpis")) == 0


def test_build_failure_is_a_run_level_row(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        scopes=[
            {
                "kind": "cluster",
                "n_clusters": 3,  # the toy EventSet has 2 locations
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.5},
            }
        ],
        objectives=[{"kind": "mse"}],
    )
    store = ResultStore(tmp_path)
    (outcome,) = run_config(config, store=store)
    assert outcome.statuses == {ALL_PROBLEMS: SolveStatus.ERROR}
    (row,) = store.read("runs").to_dict("records")
    assert row["problem_id"] == ALL_PROBLEMS
    assert row["status"] == "error"
    assert row["error_type"] == "InputMismatchError"
    assert "n_clusters" in row["error_message"]
    assert row["build_seconds"] >= 0
    assert np.isnan(row["solve_seconds"])
    assert len(store.read("entities")) == 0
    reason = store.manifest(outcome.run_id)["evaluation"]["skipped_reason"]
    assert reason == "building the design problems failed"


@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
def test_failed_runs_are_cached_unless_retried(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(toy_dir, tmp_path)
    run = single(config, "portfolio", "expected_uncovered")
    data = load_input(config)
    store = ResultStore(tmp_path)
    policy = SolverPolicy(
        lp_solvers=("SCS",),
        accept_inaccurate=False,
        solver_options={"SCS": {"max_iters": 1}},
    )
    failed = run_single(run, data, store, policy=policy)
    assert failed.failed == ("portfolio",)
    assert run_single(run, data, store, policy=policy).cached
    retried = run_single(run, data, store, policy=policy, retry_failed=True)
    assert not retried.cached
    assert retried.run_id == failed.run_id
    assert len(store.read("runs")) == 1


def test_force_reexecutes_a_cached_run(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(toy_dir, tmp_path)
    run = single(config, "portfolio", "mse")
    data = load_input(config)
    store = ResultStore(tmp_path)
    first = run_single(run, data, store)
    assert run_single(run, data, store, retry_failed=True).cached  # nothing failed
    forced = run_single(run, data, store, force=True)
    assert not forced.cached
    assert forced.run_id == first.run_id
    assert len(store.read("runs")) == 1


# -- cache key ----------------------------------------------------------------


def test_run_key_depends_on_every_part() -> None:
    base = run_key("sha256:c", "sha256:e", package_version="1.0")
    assert base.startswith("sha256:")
    assert len(base) == len("sha256:") + 64
    assert base == run_key("sha256:c", "sha256:e", package_version="1.0")
    assert base != run_key("sha256:d", "sha256:e", package_version="1.0")
    assert base != run_key("sha256:c", "sha256:f", package_version="1.0")
    assert base != run_key("sha256:c", "sha256:e", package_version="1.1")
    other_policy = SolverPolicy(lp_solvers=("CLARABEL",))
    assert base != run_key(
        "sha256:c", "sha256:e", package_version="1.0", policy=other_policy
    )
    assert run_key("sha256:c", "sha256:e") == run_key(
        "sha256:c", "sha256:e", package_version=package_versions()[PACKAGE]
    )


def test_package_version_bump_invalidates_the_cache(
    toy_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = toy_config(toy_dir, tmp_path)
    run = single(config, "portfolio", "mse")
    data = load_input(config)
    store = ResultStore(tmp_path)
    first = run_single(run, data, store)
    monkeypatch.setattr(runner, "_package_version", lambda: "999.0")
    bumped = run_single(run, data, store)
    assert not bumped.cached
    assert bumped.run_id != first.run_id
    assert len(store.run_ids()) == 2


def test_labels_and_locations_do_not_change_the_key(
    toy_dir: Path, tmp_path: Path
) -> None:
    a = toy_config(toy_dir, tmp_path / "a")
    b = toy_config(toy_dir, tmp_path / "b", name="renamed", description="other")
    data = load_input(a)
    store = ResultStore(tmp_path / "store")
    first = run_single(single(a, "portfolio", "mse"), data, store)
    second = run_single(single(b, "portfolio", "mse"), data, store)
    assert second.cached
    assert second.run_id == first.run_id


def test_input_data_changes_the_key(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    config = toy_config(toy_dir, tmp_path)
    run = single(config, "portfolio", "mse")
    store = ResultStore(tmp_path)
    eventset = toy_eventset
    first = run_single(run, RunInput.from_eventset(eventset), store)
    changed = EventSet(
        events=eventset.events,
        locations=eventset.locations,
        index=eventset.index,
        loss=eventset.loss * 2.0,
        metadata=eventset.metadata,
    )
    second = run_single(run, RunInput.from_eventset(changed), store)
    assert not second.cached
    assert second.eventset_checksum != first.eventset_checksum


def test_policy_options_must_be_json() -> None:
    policy = SolverPolicy(solver_options={"SCS": {"callback": object()}})
    with pytest.raises(ConfigError, match="JSON"):
        policy_fingerprint(policy)


# -- input and preparation ----------------------------------------------------


def test_pinned_checksum_is_checked(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    good = toy_eventset.content_hash()
    pinned = toy_config(
        toy_dir, tmp_path, eventset={"path": str(toy_dir), "checksum": good}
    )
    assert load_input(pinned).checksum == good
    wrong = "sha256:" + "0" * 64
    bad = toy_config(
        toy_dir, tmp_path, eventset={"path": str(toy_dir), "checksum": wrong}
    )
    with pytest.raises(ChecksumMismatchError, match=wrong):
        load_input(bad)
    with pytest.raises(ChecksumMismatchError):
        RunInput.from_eventset(toy_eventset, expected_checksum=wrong)
    # A RunInput of other data cannot be used with a pinned config either.
    data = load_input(toy_config(toy_dir, tmp_path))
    with pytest.raises(ChecksumMismatchError):
        run_single(single(bad, "portfolio", "mse"), data, ResultStore(tmp_path))
    with pytest.raises(ChecksumMismatchError):
        execute(single(bad, "portfolio", "mse"), data)


def test_run_input_from_disk_and_memory_agree(
    toy_dir: Path, toy_eventset: EventSet
) -> None:
    from_disk = RunInput.load(toy_dir)
    in_memory = RunInput.from_eventset(toy_eventset)
    assert from_disk.checksum == in_memory.checksum
    assert from_disk.path == toy_dir
    assert in_memory.path is None
    assert from_disk.load_seconds >= 0


def test_prepare_follows_the_thesis_order(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        portfolio={"location_ids": ["B", "A"]},
        noise={"kind": "heteroscedastic", "level": 0.3, "n_copies": 4, "seed": 7},
        threshold={"value": 20.0},
    )
    eventset = toy_eventset
    prepared = prepare_eventset(config, eventset)
    expected = add_noise(
        eventset.select_locations(["B", "A"]),
        level=0.3,
        kind="heteroscedastic",
        n_copies=4,
        rng=np.random.default_rng(7),
    ).filter_threshold(20.0)
    assert prepared.equals(expected)
    assert prepared.content_hash() == expected.content_hash()
    assert [t.name for t in prepared.metadata.transforms] == [
        "select_locations",
        "noise",
    ]
    assert len(prepared.metadata.filters) == 1
    # Deterministic: a fresh generator per preparation.
    assert prepare_eventset(config, eventset).equals(prepared)


def test_prepare_without_steps_returns_the_input(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    eventset = toy_eventset
    assert prepare_eventset(toy_config(toy_dir, tmp_path), eventset) is eventset


def test_unknown_location_propagates(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(toy_dir, tmp_path, portfolio={"location_ids": ["A", "Z"]})
    store = ResultStore(tmp_path)
    with pytest.raises(InconsistentKeysError):
        run_config(config, store=store)
    assert store.run_ids() == ()


def test_noisy_run_records_both_checksums(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        noise={"kind": "homoscedastic", "level": 0.2, "n_copies": 3, "seed": 1},
    )
    run = single(config, "portfolio", "mse")
    data = load_input(config)
    tables, manifest = execute(run, data)
    assert set(tables.runs["eventset_checksum"]) == {data.checksum}
    prepared = manifest["prepared_eventset"]
    assert prepared["content_hash"] != data.checksum
    assert prepared["n_rows"] == 9
    assert [t["name"] for t in prepared["transforms"]] == ["noise"]
    params = json.loads(tables.runs["parameters"].iloc[0])
    assert params["noise_level"] == 0.2
    assert params["noise_seed"] == 1
    assert params["n_copies"] == 3


# -- samples and config checks ------------------------------------------------


def test_holdout_calibrates_on_train_and_evaluates_both(
    toy_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_holdout(
        eventset: EventSet, *, train_fraction: float = 0.7
    ) -> tuple[Sample, Sample]:
        years = eventset.events["year"].to_numpy()
        train = Sample("train", years < 2, np.array([0, 1]))
        test = Sample("test", years >= 2, np.array([2]))
        return train, test

    monkeypatch.setattr(splits, "holdout", fake_holdout)
    config = toy_config(
        toy_dir, tmp_path, sample={"kind": "holdout", "train_fraction": 0.6}
    )
    store = ResultStore(tmp_path)
    outcome = run_single(single(config, "portfolio", "mse"), load_input(config), store)
    assert outcome.ok
    assert set(store.read("runs")["calibration_split"]) == {"train"}
    assert set(store.read("kpis")["eval_split"]) == {"train", "test"}
    assert set(store.read("exceedance")["eval_split"]) == {"train", "test"}
    m = store.manifest(outcome.run_id)
    assert m["samples"]["evaluation"] == [
        {"name": "train", "fold": 0},
        {"name": "test", "fold": 0},
    ]
    assert m["parameters"]["train_fraction"] == 0.6


def test_kfold_without_a_fold_is_refused(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    # MAR-22: each fold is a run of its own; single_runs() sets the fold.
    config = toy_config(toy_dir, tmp_path, sample={"kind": "kfold", "k": 3})
    run = single(config, "portfolio", "mse")
    assert run_parameters(run, toy_eventset)["k"] == 3
    assert run_parameters(run, toy_eventset)["fold"] == 0
    whole = toy_config(
        toy_dir,
        tmp_path,
        sample={"kind": "kfold", "k": 3},
        scopes=[{"kind": "portfolio"}],
        objectives=[{"kind": "mse"}],
    )
    with pytest.raises(ConfigError, match="k-fold"):
        execute(whole, load_input(config))


def test_run_single_needs_one_scope_and_objective(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(toy_dir, tmp_path)
    with pytest.raises(ConfigError, match="single_runs"):
        run_single(config, load_input(config), ResultStore(tmp_path))
    with pytest.raises(ConfigError, match="single_runs"):
        execute(config, load_input(config))


def test_parameters_name_the_sweep_parameters(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        scopes=[
            {
                "kind": "cluster",
                "n_clusters": 2,
                "index": "point",
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
            }
        ],
        objectives=[{"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.95}],
        pricing={"kind": "cost_of_capital", "rate": 0.1, "q": 0.99},
        threshold={"value": 25.0},
    )
    params = run_parameters(config, toy_eventset)
    assert params == {
        "attachment": 20.0,
        "limit": 60.0,
        "n_bins": 2,
        "n_assets": 2,
        "evaluation_beta": 0.5,
        "sample": "full",
        "scope_index": "point",
        "n_clusters": 2,
        "beta_tail": 0.9,
        "linkage": "ward",
        "alpha": 0.9,
        "beta": 0.95,
        "pricing_rate": 0.1,
        "pricing_q": 0.99,
        "budget_loading": 1.0,
        "threshold": 25.0,
        "threshold_column": "index",
    }


def test_package_versions_list_missing_packages_as_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "PROVENANCE_PACKAGES", (PACKAGE, "no-such-dist-xyz"))
    versions = package_versions()
    assert versions[PACKAGE]
    assert versions["no-such-dist-xyz"] is None


# -- acceptance on the parity fixture (thesis defaults) ------------------------


@needs_fixture
def test_thesis_run_fills_the_store_and_hits_the_cache(tmp_path: Path) -> None:
    config = load_config(PARITY_CONFIG)
    store = ResultStore(tmp_path)
    data = load_input(config)
    assert data.checksum == config.eventset.checksum

    first = run_config(config, store=store, data=data)
    assert len(first) == 9  # 3 scopes x 3 objectives
    assert all(o.ok and not o.cached for o in first)
    runs = store.read("runs")
    assert len(runs) == 9 * 3 + 1 * 6  # individual: 9 assets; others: 1 problem
    assert set(runs["status"]) == {"optimal"}
    assert set(runs["eventset_checksum"]) == {config.eventset.checksum}
    assert len(store.read("payouts")) == (9 * 3 + 9 * 3 + 3 * 3) * 15
    assert len(store.read("kpis")) > 0
    manifest = store.manifest(first[0].run_id)
    assert manifest["prepared_eventset"]["n_rows"] == 13897  # thesis row count
    assert [t["name"] for t in manifest["prepared_eventset"]["transforms"]] == [
        "select_locations",
        "noise",
    ]

    second = run_config(config, store=store, data=data)
    assert all(o.cached for o in second)
    assert [o.run_id for o in second] == [o.run_id for o in first]
    assert len(store.read("runs")) == len(runs)


@needs_fixture
@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
def test_thesis_failing_solve_shows_up_in_runs(tmp_path: Path) -> None:
    config = load_config(PARITY_CONFIG)
    run = next(
        r
        for r in config.single_runs()
        if r.scopes[0].kind == "portfolio"
        and r.objectives[0].kind == "expected_uncovered"
    )
    policy = SolverPolicy(
        lp_solvers=("SCS",),
        accept_inaccurate=False,
        solver_options={"SCS": {"max_iters": 1}},
    )
    store = ResultStore(tmp_path)
    outcome = run_single(run, load_input(config), store, policy=policy)
    assert outcome.failed == ("portfolio",)
    (row,) = store.read("runs").to_dict("records")
    assert row["status"] != "optimal"
    assert row["error_type"] == "SolveError"
    assert "SCS" in row["error_message"]
    assert row["eventset_checksum"] == config.eventset.checksum
