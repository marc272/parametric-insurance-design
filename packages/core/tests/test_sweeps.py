"""Tests of the one-factor-at-a-time sweeps (MAR-65).

Toy tests run on the three-event EventSet of ``conftest.py``. The acceptance
tests plan the thesis sweep grid (``parity/configs/thesis.yaml``) and compare
its points with the thesis results CSVs in ``parity/golden``, and run a
reduced grid on the parity fixture. The full grid runs outside CI (PR #36).
"""

from __future__ import annotations

import itertools
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.errors import ConfigError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    SweepConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import (
    load_input,
    run_config,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore, StoreError
from parametric_insurance_design.experiment.sweeps import (
    MEMBERSHIP_COLUMNS,
    SWEEP_MANIFEST_FORMAT,
    SWEEP_SOURCES,
    SWEEPS_DIR,
    SweepPoint,
    n_assets_subsets,
    read_sweep_manifests,
    run_sweep,
    run_sweeps,
    sweep_id,
    sweep_membership,
    sweep_points,
)
from parametric_insurance_design.records import ALL_PROBLEMS
from parametric_insurance_design.solve import SolverPolicy

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"
GOLDEN_RESULTS = REPO_ROOT / "parity" / "golden" / "full_optimization_results.csv.gz"

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


CLUSTER = {
    "kind": "cluster",
    "n_clusters": 2,
    "strategy": {"kind": "thesis_ward", "beta_tail": 0.5},
}
NOISE = {"kind": "heteroscedastic", "level": 0.3, "n_copies": 2, "seed": 7}


def kinds(points: tuple[SweepPoint, ...]) -> list[tuple[str, str]]:
    return [(p.scope, p.objective) for p in points]


# -- sources and subsets -------------------------------------------------------


def test_sources_are_the_thesis_tags() -> None:
    assert dict(SWEEP_SOURCES) == {
        "alpha": "alpha_sweep",
        "beta": "beta_sweep",
        "budget_loading": "budget_loading_sweep",
        "n_bins": "n_bins_sweep",
        "n_clusters": "n_clusters_sweep",
        "noise_level": "noise_value_sweep",
        "n_assets": "n_assets_sweep",
    }


def thesis_n_assets_choices(
    assets: list[str], values: list[int], max_combos_per_n: int | None, seed: int
) -> list[tuple[str, ...]]:
    """Copy of the subset choice of the thesis ``_build_kpi_df_n_assets``."""
    rng = np.random.default_rng(seed)
    chosen: list[tuple[str, ...]] = []
    for n in values:
        if n < 1 or n > len(assets):
            continue
        all_combos = list(itertools.combinations(assets, n))
        if max_combos_per_n and len(all_combos) > max_combos_per_n:
            idx = rng.choice(len(all_combos), size=max_combos_per_n, replace=False)
            all_combos = [all_combos[i] for i in idx]
        chosen.extend(all_combos)
    return chosen


@pytest.mark.parametrize(
    ("sizes", "max_combinations", "seed"),
    [
        (list(range(1, 10)), 25, 42),
        (list(range(1, 10)), 50, 42),
        ([3, 1, 5], 4, 0),
        ([9, 2], None, None),
    ],
)
def test_subsets_reproduce_the_thesis_sampling(
    sizes: list[int], max_combinations: int | None, seed: int | None
) -> None:
    assets = [f"A{k}" for k in range(1, 10)]
    per_size = n_assets_subsets(
        assets, sizes, max_combinations=max_combinations, seed=seed
    )
    assert [len(c) for c in per_size] == [
        min(len(list(itertools.combinations(assets, n))), max_combinations or 10**9)
        for n in sizes
    ]
    flat = [subset for chosen in per_size for subset in chosen]
    assert flat == thesis_n_assets_choices(assets, sizes, max_combinations, seed or 0)


def test_thesis_subset_counts() -> None:
    assets = [f"A{k}" for k in range(1, 10)]
    per_size = n_assets_subsets(assets, range(1, 10), max_combinations=25, seed=42)
    assert [len(c) for c in per_size] == [9, 25, 25, 25, 25, 25, 25, 9, 1]
    assert sum(len(c) for c in per_size) == 169


@pytest.mark.parametrize(
    ("sizes", "options", "message"),
    [
        ([0], {}, r"1\.\.3"),
        ([4], {}, r"1\.\.3"),
        ([1], {"max_combinations": 2}, "needs a seed"),
        ([1], {"max_combinations": 0, "seed": 1}, ">= 1"),
    ],
)
def test_subset_errors(sizes: list[int], options: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        n_assets_subsets(["a", "b", "c"], sizes, **options)


def test_subsets_refuse_repeated_locations() -> None:
    with pytest.raises(ConfigError, match="repeat"):
        n_assets_subsets(["a", "a"], [1])


# -- planning -----------------------------------------------------------------


def test_optimisation_sweeps_vary_one_parameter_on_the_runs_that_accept_it(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        scopes=[{"kind": "individual"}, CLUSTER],
        sweeps=[
            {"parameter": "alpha", "values": [0.1, 0.5]},
            {"parameter": "budget_loading", "values": [0.8, 1.2]},
            {"parameter": "n_clusters", "values": [1, 2]},
        ],
    )
    alpha = sweep_points(config, "alpha")
    # Value-major; only the weighted-CVaR runs, scope order of single_runs().
    assert [p.value for p in alpha] == [0.1, 0.1, 0.5, 0.5]
    assert (
        kinds(alpha)
        == [("individual", "weighted_cvar"), ("cluster", "weighted_cvar")] * 2
    )
    for point in alpha:
        objective = point.config.objectives[0]
        assert objective.kind == "weighted_cvar"
        assert objective.alpha == point.value
        assert objective.beta == 0.5  # held at baseline
        assert point.config.constraints[0].loading == 1.0
        assert point.config.sweeps == ()
        assert point.location_ids is None
        assert point.subset_index is None

    loading = sweep_points(config, "budget_loading")
    assert len(loading) == 2 * 4  # every scope x objective
    assert [p.config.constraints[0].loading for p in loading] == [0.8] * 4 + [1.2] * 4

    clusters = sweep_points(config, "n_clusters")
    assert kinds(clusters) == [("cluster", "mse"), ("cluster", "weighted_cvar")] * 2
    n_clusters = [p.config.scopes[0].model_dump()["n_clusters"] for p in clusters]
    assert n_clusters == [1, 1, 2, 2]


def test_baseline_point_has_the_baseline_config_hash(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir, tmp_path, sweeps=[{"parameter": "alpha", "values": [0.5, 0.9]}]
    )
    baseline = {config_hash(s) for s in config.single_runs()}
    hashes = [config_hash(p.config) for p in sweep_points(config, "alpha")]
    assert [h in baseline for h in hashes] == [True, True, False, False]


def test_noise_sweep_covers_every_run(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        noise=NOISE,
        sweeps=[{"parameter": "noise_level", "values": [0, 0.5]}],
    )
    points = sweep_points(config, "noise_level")
    assert len(points) == 2 * 4
    for point in points:
        assert point.config.noise is not None
        assert point.config.noise.level == point.value
        assert point.config.noise.seed == 7


def test_n_assets_sweep_plans_subsets(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        portfolio={"location_ids": ["B", "A"]},
        sweeps=[{"parameter": "n_assets", "values": [1, 2]}],
    )
    points = sweep_points(config, "n_assets")
    # sizes 1 (B, A) and 2 (B+A), each for the 4 runs; portfolio order kept
    assert [p.location_ids for p in points] == [("B",)] * 4 + [("A",)] * 4 + [
        ("B", "A")
    ] * 4
    assert [p.subset_index for p in points] == [0] * 4 + [1] * 4 + [0] * 4
    assert [p.value for p in points] == [1] * 8 + [2] * 4
    for point in points:
        assert point.config.portfolio.location_ids == point.location_ids
    # The whole portfolio, in order, is the baseline.
    baseline = {config_hash(s) for s in config.single_runs()}
    assert {config_hash(p.config) for p in points[8:]} == baseline


def test_n_assets_over_all_locations_needs_the_eventset_order(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir, tmp_path, sweeps=[{"parameter": "n_assets", "values": [1]}]
    )
    with pytest.raises(ConfigError, match="location_ids"):
        sweep_points(config, "n_assets")
    points = sweep_points(config, "n_assets", location_ids=["A", "B"])
    assert [p.location_ids for p in points] == [("A",)] * 4 + [("B",)] * 4
    with pytest.raises(ConfigError, match=r"1\.\.1"):
        sweep_points(
            config, SweepConfig(parameter="n_assets", values=(2,)), location_ids=["A"]
        )


def test_sweep_lookup(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(toy_dir, tmp_path)
    with pytest.raises(ConfigError, match="no 'alpha' sweep"):
        sweep_points(config, "alpha")
    spec = SweepConfig(parameter="beta", values=(0.6,))
    betas = [
        p.config.objectives[0].model_dump()["beta"] for p in sweep_points(config, spec)
    ]
    assert betas == [0.6] * 2
    with pytest.raises(ConfigError, match="accepts 'n_clusters'"):
        sweep_points(config, SweepConfig(parameter="n_clusters", values=(1,)))


# -- running --------------------------------------------------------------------


def test_sweep_runs_points_with_the_sweep_tag_and_writes_a_manifest(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path / "store",
        sweeps=[{"parameter": "alpha", "values": [0.5, 0.9]}],
    )
    store = ResultStore(tmp_path / "store")
    data = load_input(config)
    baseline = run_config(config, store=store, data=data)
    result = run_sweep(config, "alpha", data, store)

    assert result.parameter == "alpha"
    assert result.source == "alpha_sweep"
    assert result.ok
    assert len(result.points) == 4
    # alpha = 0.5 is the baseline: a cache hit that keeps "single_run".
    assert [p.outcome.cached for p in result.points] == [True, True, False, False]
    assert [p.outcome.source for p in result.points] == ["single_run"] * 2 + [
        "alpha_sweep"
    ] * 2
    assert result.n_cached == 2
    wcvar = {o.run_id for o in baseline} & {p.outcome.run_id for p in result.points}
    assert len(wcvar) == 2

    runs = store.read("runs")
    new = runs[runs["run_id"].isin([p.outcome.run_id for p in result.points[2:]])]
    assert set(new["source"]) == {"alpha_sweep"}
    assert {json.loads(p)["alpha"] for p in new["parameters"]} == {0.9}

    manifest = json.loads(result.manifest_path.read_text())
    assert result.manifest_path.parent == store.root / SWEEPS_DIR
    assert manifest["format"] == SWEEP_MANIFEST_FORMAT
    assert manifest["sweep_id"] == result.sweep_id
    assert manifest["base_config_hash"] == config_hash(config)
    assert manifest["eventset_checksum"] == data.checksum
    assert manifest["sweep"]["values"] == [0.5, 0.9]
    assert (manifest["n_points"], manifest["n_cached"], manifest["n_failed"]) == (
        4,
        2,
        0,
    )
    assert [p["run_id"] for p in manifest["points"]] == [
        p.outcome.run_id for p in result.points
    ]
    assert [p["value"] for p in manifest["points"]] == [0.5, 0.5, 0.9, 0.9]

    membership = sweep_membership(store)
    assert list(membership.columns) == list(MEMBERSHIP_COLUMNS)
    assert len(membership) == 4
    assert set(membership["source"]) == {"alpha_sweep"}
    assert membership["run_source"].tolist() == ["single_run"] * 2 + ["alpha_sweep"] * 2
    assert bool(membership["subset_index"].isna().all())
    assert set(membership["run_id"]) <= set(store.run_ids())

    again = run_sweep(config, "alpha", data, store)
    assert again.sweep_id == result.sweep_id
    assert again.n_cached == 4
    assert len(read_sweep_manifests(store)) == 1


def test_sweep_id_follows_the_runs(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir, tmp_path, sweeps=[{"parameter": "alpha", "values": [0.5]}]
    )
    points = sweep_points(config, "alpha")
    checksum = load_input(config).checksum
    ids = [run_key(config_hash(p.config), checksum) for p in points]
    first = sweep_id("alpha", list(zip(points, ids, strict=True)))
    assert first == sweep_id("alpha", list(zip(points, ids, strict=True)))
    other = run_key(config_hash(points[0].config), checksum, package_version="0")
    assert first != sweep_id("alpha", [(points[0], other), (points[1], ids[1])])
    assert first.startswith("sha256:")
    assert len(first) == 7 + 64


def test_noise_sweep_rebuilds_the_eventset(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        objectives=[{"kind": "mse"}],
        scopes=[{"kind": "portfolio"}],
        noise=NOISE,
        sweeps=[{"parameter": "noise_level", "values": [0.0, 0.3, 0.6]}],
    )
    store = ResultStore(tmp_path)
    outcome = run_sweeps(config, store=store, baseline=False)
    (result,) = outcome.sweeps
    assert outcome.baseline == ()
    assert result.source == "noise_value_sweep"
    assert [p.outcome.cached for p in result.points] == [False] * 3
    levels = []
    for point in result.points:
        prepared = store.manifest(point.outcome.run_id)["prepared_eventset"]
        (noise,) = [t for t in prepared["transforms"] if t["name"] == "noise"]
        levels.append(noise["parameters"]["level"])
        assert prepared["n_rows"] == 3 * 2  # n_copies = 2
    assert levels == [0.0, 0.3, 0.6]
    assert len({p.outcome.run_id for p in result.points}) == 3


def test_n_assets_sweep_runs_location_subsets(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        objectives=[{"kind": "mse"}],
        sweeps=[{"parameter": "n_assets", "values": [1, 2]}],
    )
    store = ResultStore(tmp_path)
    outcome = run_sweeps(config, store=store)
    assert len(outcome.baseline) == 2
    (result,) = outcome.sweeps
    assert result.source == "n_assets_sweep"
    assert result.ok
    subsets = [p.point.location_ids for p in result.points]
    assert subsets == [("A",), ("A",), ("B",), ("B",), ("A", "B"), ("A", "B")]
    entities = store.read("entities")
    for point in result.points:
        members = entities.loc[entities["run_id"] == point.outcome.run_id]
        assert set(members["location_id"]) == set(point.point.location_ids or ())
    membership = sweep_membership(store)
    assert membership["location_ids"].tolist() == subsets
    assert membership["subset_index"].tolist() == [0, 0, 1, 1, 0, 0]
    assert membership["value"].tolist() == [1, 1, 1, 1, 2, 2]


def test_failed_points_stay_in_the_sweep(toy_dir: Path, tmp_path: Path) -> None:
    # Two clusters cannot be built from one location: a run-level failure.
    config = toy_config(
        toy_dir,
        tmp_path,
        scopes=[CLUSTER],
        objectives=[{"kind": "mse"}],
        portfolio={"location_ids": ["A", "B"]},
        sweeps=[{"parameter": "n_assets", "values": [1, 2]}],
    )
    store = ResultStore(tmp_path)
    (result,) = run_sweeps(config, store=store).sweeps
    assert not result.ok
    assert [p.point.location_ids for p in result.failed] == [("A",), ("B",)]
    assert all(p.outcome.failed == (ALL_PROBLEMS,) for p in result.failed)
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["n_failed"] == 2
    assert [p["ok"] for p in manifest["points"]] == [False, False, True]
    assert manifest["points"][0]["failed"] == [ALL_PROBLEMS]
    assert sweep_membership(store)["ok"].tolist() == [False, False, True]


@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
def test_options_reach_the_runner(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        scopes=[{"kind": "portfolio"}],
        objectives=[{"kind": "mse"}],
        sweeps=[{"parameter": "n_bins", "values": [2, 4]}],
    )
    store = ResultStore(tmp_path)
    bad = SolverPolicy(
        lp_solvers=("SCS",),
        qp_solvers=("SCS",),
        accept_inaccurate=False,
        solver_options={"SCS": {"max_iters": 1}},
    )
    failed = run_sweeps(config, store=store, policy=bad)
    assert not failed.sweeps[0].ok
    manifest = json.loads(failed.sweeps[0].manifest_path.read_text())
    assert manifest["solver_policy"]["lp_solvers"] == ["SCS"]
    cached = run_sweeps(config, store=store, policy=bad)
    assert all(p.outcome.cached for p in cached.sweeps[0].points)
    forced = run_sweeps(config, store=store, policy=bad, force=True, baseline=False)
    assert not any(p.outcome.cached for p in forced.sweeps[0].points)
    retried = run_sweeps(config, store=store, policy=bad, retry_failed=True)
    assert not any(p.outcome.cached for p in retried.sweeps[0].points)


def test_run_sweeps_selects_parameters(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        scopes=[{"kind": "portfolio"}],
        sweeps=[
            {"parameter": "alpha", "values": [0.7]},
            {"parameter": "n_bins", "values": [3]},
        ],
    )
    outcome = run_sweeps(config, parameters=["n_bins"])  # store and data from config
    assert [s.parameter for s in outcome.sweeps] == ["n_bins"]
    assert len(outcome.baseline) == 2
    store = ResultStore(tmp_path)
    assert [m["parameter"] for m in read_sweep_manifests(store)] == ["n_bins"]
    with pytest.raises(ConfigError, match="no sweep of"):
        run_sweeps(config, parameters=["beta"])


# -- reading manifests --------------------------------------------------------


def test_empty_store_has_no_membership(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "nothing")
    assert read_sweep_manifests(store) == ()
    membership = sweep_membership(store)
    assert list(membership.columns) == list(MEMBERSHIP_COLUMNS)
    assert len(membership) == 0


@pytest.mark.parametrize(
    ("content", "message"),
    [("{not json", "not valid JSON"), ('{"format": "other"}', "is not a")],
)
def test_bad_manifests_are_errors(tmp_path: Path, content: str, message: str) -> None:
    directory = tmp_path / SWEEPS_DIR
    directory.mkdir()
    (directory / "x.json").write_text(content)
    (directory / ".x.json.tmp").write_text("ignored")
    with pytest.raises(StoreError, match=message):
        read_sweep_manifests(ResultStore(tmp_path))


# -- k-fold: the fold of every point (MAR-138) ---------------------------------


def test_kfold_sweep_manifest_lists_the_fold_per_point(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path / "store",
        sample={"kind": "kfold", "k": 3},
        sweeps=[{"parameter": "alpha", "values": [0.5, 0.9]}],
    )
    store = ResultStore(tmp_path / "store")
    result = run_sweep(config, "alpha", load_input(config), store)
    assert result.ok, [p.outcome.failed for p in result.failed]
    # value x scope (weighted_cvar only) x fold, folds next to each other.
    assert [p.point.fold for p in result.points] == [0, 1, 2] * 4

    (manifest,) = read_sweep_manifests(store)
    entries = manifest["points"]
    assert [e["fold"] for e in entries] == [0, 1, 2] * 4
    assert len({e["run_id"] for e in entries}) == 12  # a run per fold

    # The manifest's fold is the fold the run calibrated on.
    runs = store.read("runs").drop_duplicates("run_id").set_index("run_id")
    for entry in entries:
        assert int(runs.at[entry["run_id"], "fold"]) == entry["fold"]
        run = store.manifest(entry["run_id"])
        assert run["config"]["sample"]["fold"] == entry["fold"]

    membership = sweep_membership(store)
    assert list(membership.columns) == list(MEMBERSHIP_COLUMNS)
    assert membership["fold"].dtype == "Int64"
    assert membership["fold"].tolist() == [0, 1, 2] * 4


def test_other_samples_have_no_fold_in_the_manifest(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path / "store",
        sample={"kind": "holdout", "train_fraction": 0.7},
        sweeps=[{"parameter": "alpha", "values": [0.5]}],
    )
    store = ResultStore(tmp_path / "store")
    result = run_sweep(config, "alpha", load_input(config), store)
    assert all(p.point.fold is None for p in result.points)
    (manifest,) = read_sweep_manifests(store)
    assert not any("fold" in e for e in manifest["points"])
    assert bool(sweep_membership(store)["fold"].isna().all())


def test_membership_reads_manifests_without_the_fold(
    toy_dir: Path, tmp_path: Path
) -> None:
    """A manifest written before MAR-138 (no ``fold`` key) still reads."""
    config = toy_config(
        toy_dir,
        tmp_path / "store",
        sample={"kind": "kfold", "k": 3},
        sweeps=[{"parameter": "alpha", "values": [0.9]}],
    )
    store = ResultStore(tmp_path / "store")
    result = run_sweep(config, "alpha", load_input(config), store)
    manifest = json.loads(result.manifest_path.read_text())
    for entry in manifest["points"]:
        del entry["fold"]
    result.manifest_path.write_text(json.dumps(manifest))

    membership = sweep_membership(store)
    assert len(membership) == 6
    assert membership["fold"].dtype == "Int64"
    assert bool(membership["fold"].isna().all())


# -- acceptance: the thesis grid ------------------------------------------------

# Thesis optimisation sweeps: (scope, objective) of our config -> thesis
# (Approach, Method) in the results CSVs.
THESIS_SCOPES = {
    "individual": "individual_optimization",
    "cluster": "cluster_optimization",
    "portfolio": "integrated_portfolio_optimization",
}
THESIS_OBJECTIVES = {
    "mse": "pure_basis_risk_minimization",
    "expected_uncovered": "pure_uncovered_loss_minimization",
    "weighted_cvar": "weighted_cvar_minimization",
}
THESIS_COLUMNS = {
    "alpha": "Alpha",
    "beta": "Beta",
    "budget_loading": "Budget_Loading",
    "n_bins": "N_Bins",
    "n_clusters": "N_Clusters",
}


@pytest.fixture(scope="module")
def thesis_config() -> ExperimentConfig:
    if not PARITY_CONFIG.is_file():
        pytest.skip("the parity fixture is only in a repository checkout")
    return load_config(PARITY_CONFIG)


@needs_fixture
def test_thesis_grid_point_counts(thesis_config: ExperimentConfig) -> None:
    counts = {
        s.parameter: len(sweep_points(thesis_config, s)) for s in thesis_config.sweeps
    }
    assert counts == {
        "alpha": 10 * 3,  # weighted CVaR x 3 scopes
        "beta": 10 * 3,
        "budget_loading": 11 * 9,  # every scope x objective
        "n_clusters": 9 * 3,  # cluster scope x 3 objectives
        "n_bins": 5 * 9,
        "n_assets": 169 * 9,  # thesis subsets x every scope x objective
        "noise_level": 11 * 9,
    }


@needs_fixture
@pytest.mark.skipif(not GOLDEN_RESULTS.is_file(), reason="no golden results CSV")
@pytest.mark.parametrize("parameter", sorted(THESIS_COLUMNS))
def test_thesis_optimisation_sweeps_match_the_results_csv(
    thesis_config: ExperimentConfig, parameter: str
) -> None:
    golden = pd.read_csv(GOLDEN_RESULTS)
    golden = golden[golden["Source"] == SWEEP_SOURCES[parameter]]
    thesis = {
        key: sorted(set(group[THESIS_COLUMNS[parameter]]))
        for key, group in golden.groupby(["Approach", "Method"])
    }
    ours: dict[tuple[str, str], list[float]] = {}
    for point in sweep_points(thesis_config, parameter):
        key = (THESIS_SCOPES[point.scope], THESIS_OBJECTIVES[point.objective])
        ours.setdefault(key, []).append(point.value)
    # The same scope x objective runs, each with every sweep value once.
    assert set(ours) == set(thesis)
    for key, values in ours.items():
        assert Counter(values) == Counter(set(values))
        if parameter == "budget_loading" and "pure_basis_risk" in key[1]:
            # The thesis dropped failed solves (low loadings of the MSE
            # runs); every value it kept is a point here.
            assert set(thesis[key]) < set(values)
        else:
            assert sorted(values) == pytest.approx(thesis[key])


@needs_fixture
def test_thesis_n_assets_points_follow_the_thesis_subsets(
    thesis_config: ExperimentConfig,
) -> None:
    (spec,) = [s for s in thesis_config.sweeps if s.parameter == "n_assets"]
    assets = thesis_config.portfolio.location_ids
    assert assets is not None
    assert spec.seed is not None
    expected = thesis_n_assets_choices(
        list(assets), [int(v) for v in spec.values], spec.max_combinations, spec.seed
    )
    points = sweep_points(thesis_config, spec)
    n_runs = len(thesis_config.single_runs())
    assert [p.location_ids for p in points[::n_runs]] == expected


@needs_fixture
@pytest.mark.filterwarnings("ignore:Solution may be inaccurate")
def test_reduced_thesis_grid_runs(tmp_path: Path) -> None:
    # Every kind of sweep on the parity fixture, two scopes, a few values.
    config = load_config(PARITY_CONFIG)
    data = config.model_dump(mode="python", round_trip=True)
    data["scopes"] = [s for s in data["scopes"] if s["kind"] != "individual"]
    data["objectives"] = [o for o in data["objectives"] if o["kind"] == "weighted_cvar"]
    data["sweeps"] = [
        {"parameter": "alpha", "values": [0.5, 0.9]},
        {"parameter": "n_clusters", "values": [2]},
        {"parameter": "noise_level", "values": [0.0]},
        {"parameter": "n_assets", "values": [8], "max_combinations": 2, "seed": 42},
    ]
    data["eventset"]["path"] = str(PARITY_EVENTSET)
    config = parse_config(data)
    store = ResultStore(tmp_path)
    outcome = run_sweeps(config, store=store)
    assert len(outcome.baseline) == 2
    assert all(o.ok for o in outcome.baseline)
    sizes = {s.parameter: (len(s.points), s.n_cached) for s in outcome.sweeps}
    assert sizes == {
        "alpha": (4, 2),  # alpha = 0.9 is the baseline
        "n_clusters": (1, 0),
        "noise_level": (2, 0),
        "n_assets": (4, 0),
    }
    assert all(s.ok for s in outcome.sweeps)
    membership = sweep_membership(store)
    assert len(membership) == 11
    runs = store.read("runs")
    tagged = runs.groupby("source")["run_id"].nunique().to_dict()
    assert tagged == {
        "single_run": 2,
        "alpha_sweep": 2,
        "n_clusters_sweep": 1,
        "noise_value_sweep": 2,
        "n_assets_sweep": 4,
    }
    n_assets = membership[membership["parameter"] == "n_assets"]
    expected = thesis_n_assets_choices([f"A{k}" for k in range(1, 10)], [8], 2, 42)
    assert n_assets["location_ids"].tolist()[::2] == expected
