"""Out-of-sample runs: calibrate on train, evaluate on train and test (MAR-22).

The runner and config side of SPEC §6.1: holdout and k-fold samples through
``run_single`` / ``run_config``, a ``run_id`` per k-fold fold, and the
in-sample vs. out-of-sample gap read back from the store.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from parametric_insurance_design import splits
from parametric_insurance_design.errors import ConfigError
from parametric_insurance_design.evaluate import kpis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import (
    execute,
    load_input,
    prepare_eventset,
    run_config,
    run_parameters,
    run_single,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.experiment.sweeps import sweep_points
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.solve import solve
from parametric_insurance_design.splits import SplitError, kpi_gap

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"

needs_fixture = pytest.mark.skipif(
    not (PARITY_EVENTSET.is_dir() and PARITY_CONFIG.is_file()),
    reason="the parity fixture is only in a repository checkout",
)

HOLDOUT = {"kind": "holdout", "train_fraction": 0.7}
KFOLD3 = {"kind": "kfold", "k": 3}


@pytest.fixture
def toy_dir(tmp_path: Path, toy_eventset: EventSet) -> Path:
    """The toy EventSet of ``conftest.py`` (3 events in 3 years) on disk."""
    path = tmp_path / "eventset"
    toy_eventset.to_parquet(path)
    return path


def toy_config(
    eventset_path: Path,
    output: Path,
    /,
    **changes: Any,  # noqa: ANN401
) -> ExperimentConfig:
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "toy",
        "eventset": {"path": str(eventset_path)},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
        "scopes": [{"kind": "portfolio"}],
        "objectives": [{"kind": "mse"}],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.5},
        "output": {"directory": str(output)},
    }
    data.update(changes)
    return parse_config(data)


# -- holdout -------------------------------------------------------------------


def test_holdout_run_calibrates_on_train_and_evaluates_both(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(toy_dir, tmp_path / "store", sample=HOLDOUT)
    (run,) = config.single_runs()
    data = load_input(config)
    store = ResultStore(tmp_path / "store")
    outcome = run_single(run, data, store)
    assert outcome.ok

    # The stored payout is the solution calibrated on the training years only.
    prepared = prepare_eventset(run, data.eventset)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    c = run.to_components()
    (built,) = build_problems(
        prepared,
        c.scopes[0],
        c.payout,
        c.objectives[0],
        c.pricing,
        c.constraints,
        basis=c.basis,
        sample=train,
    )
    result = solve(built)
    payouts = store.read("payouts").sort_values(["entity_id", "param_index"])
    np.testing.assert_allclose(payouts["value"], result.theta.ravel(), atol=1e-6)

    runs = store.read("runs")
    assert runs["calibration_split"].tolist() == ["train"]
    assert runs["fold"].tolist() == [0]
    stored = store.read("kpis")
    assert set(stored["eval_split"]) == {"train", "test"}
    assert set(stored["fold"]) == {0}

    # The test KPIs are evaluate.kpis of the train-calibrated result on test.
    expected = kpis(
        prepared,
        c.scopes[0],
        [result],
        basis=c.basis,
        beta=0.5,
        run_id=outcome.run_id,
        sample=test,
        pricing=c.pricing,
    )
    got = stored[stored["eval_split"] == "test"]
    key = ["level", "subject_id", "kpi"]
    merged = got.merge(expected, on=key, suffixes=("", "_expected"))
    assert len(merged) == len(expected) == len(got)
    np.testing.assert_allclose(
        merged["value"], merged["value_expected"], rtol=1e-6, atol=1e-9
    )


def test_holdout_and_full_runs_differ(toy_dir: Path, tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "store")
    full = toy_config(toy_dir, tmp_path / "store")
    held = toy_config(toy_dir, tmp_path / "store", sample=HOLDOUT)
    assert config_hash(full.single_runs()[0]) != config_hash(held.single_runs()[0])
    (a,) = run_config(full, store=store)
    (b,) = run_config(held, store=store)
    assert a.run_id != b.run_id
    kpi_table = store.read("kpis")
    splits_of = {
        run_id: set(kpi_table.loc[kpi_table["run_id"] == run_id, "eval_split"])
        for run_id in (a.run_id, b.run_id)
    }
    assert splits_of == {a.run_id: {"full"}, b.run_id: {"train", "test"}}


def test_kpi_gap_from_a_holdout_store(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path / "store",
        sample=HOLDOUT,
        objectives=[
            {"kind": "mse"},
            {"kind": "weighted_cvar", "alpha": 0.5, "beta": 0.5},
        ],
    )
    store = ResultStore(tmp_path / "store")
    outcomes = run_config(config, store=store)
    table = store.read("kpis")
    gap = kpi_gap(table)
    assert len(gap) * 2 == len(table)
    assert set(gap["run_id"]) == {o.run_id for o in outcomes}
    np.testing.assert_allclose(gap["gap"], gap["test"] - gap["train"])


def test_a_holdout_without_training_years_propagates(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir, tmp_path, sample={"kind": "holdout", "train_fraction": 0.1}
    )
    store = ResultStore(tmp_path / "store")
    with pytest.raises(SplitError, match="training years"):
        run_config(config, store=store)
    assert store.run_ids() == ()


# -- k-fold: a run per fold ------------------------------------------------------


def test_kfold_config_expands_into_one_run_per_fold(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        sample=KFOLD3,
        scopes=[{"kind": "individual"}, {"kind": "portfolio"}],
        objectives=[{"kind": "mse"}, {"kind": "expected_uncovered"}],
    )
    assert config.sample.kind == "kfold"
    assert config.sample.fold is None
    singles = config.single_runs()
    assert len(singles) == 2 * 2 * 3
    order = [
        (s.scopes[0].kind, s.objectives[0].kind, s.sample.fold)  # type: ignore[union-attr]
        for s in singles
    ]
    assert order[:4] == [
        ("individual", "mse", 0),
        ("individual", "mse", 1),
        ("individual", "mse", 2),
        ("individual", "expected_uncovered", 0),
    ]
    assert len({config_hash(s) for s in singles}) == len(singles)
    # A single run's config is already one fold: no further expansion.
    assert singles[1].single_runs() == (singles[1],)
    assert config_hash(singles[1].single_runs()[0]) == config_hash(singles[1])


@pytest.mark.parametrize("sample", [{"kind": "full"}, HOLDOUT])
def test_single_runs_keep_other_samples(
    toy_dir: Path, tmp_path: Path, sample: dict[str, Any]
) -> None:
    config = toy_config(toy_dir, tmp_path, sample=sample)
    (single,) = config.single_runs()
    assert single.sample == config.sample
    assert config_hash(single) == config_hash(config)


@pytest.mark.parametrize(
    ("sample", "message"),
    [
        ({"kind": "kfold", "k": 3, "fold": 3}, "fold 3 is not in 0 .. 2"),
        ({"kind": "kfold", "fold": -1}, "sample.kfold.fold"),
        ({"kind": "kfold", "fold": 1.0}, "sample.kfold.fold"),
        ({"kind": "holdout", "fold": 0}, "unknown key 'fold'"),
    ],
)
def test_invalid_folds_are_config_errors(
    toy_dir: Path, tmp_path: Path, sample: dict[str, Any], message: str
) -> None:
    with pytest.raises(ConfigError, match=message):
        toy_config(toy_dir, tmp_path, sample=sample)


def test_kfold_runs_one_run_id_per_fold(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    config = toy_config(toy_dir, tmp_path / "store", sample=KFOLD3)
    store = ResultStore(tmp_path / "store")
    first = run_config(config, store=store)
    assert len(first) == 3
    assert all(o.ok and not o.cached for o in first)
    assert len({o.run_id for o in first}) == 3

    runs = store.read("runs").sort_values("fold")
    assert runs["fold"].tolist() == [0, 1, 2]
    assert set(runs["calibration_split"]) == {"train"}
    assert [json.loads(p)["fold"] for p in runs["parameters"]] == [0, 1, 2]
    assert [json.loads(p)["k"] for p in runs["parameters"]] == [3, 3, 3]

    table = store.read("kpis")
    pairs = set(zip(table["eval_split"], table["fold"], strict=True))
    assert pairs == {(s, f) for s in ("train", "test") for f in range(3)}
    for outcome in first:
        m = store.manifest(outcome.run_id)
        fold = m["config"]["sample"]["fold"]
        assert m["samples"]["calibration"] == {"name": "train", "fold": fold}
        assert m["samples"]["evaluation"] == [
            {"name": "train", "fold": fold},
            {"name": "test", "fold": fold},
        ]
    gap = kpi_gap(table)
    assert sorted(set(gap["fold"])) == [0, 1, 2]

    second = run_config(config, store=store)
    assert all(o.cached for o in second)
    assert [o.run_id for o in second] == [o.run_id for o in first]

    single = config.single_runs()[2]
    assert run_parameters(single, toy_eventset)["fold"] == 2


def test_a_kfold_run_needs_its_fold(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(toy_dir, tmp_path, sample=KFOLD3)
    with pytest.raises(ConfigError, match=r"sample\.fold"):
        execute(config, load_input(config))
    with pytest.raises(ConfigError, match=r"sample\.fold"):
        run_single(config, load_input(config), ResultStore(tmp_path / "store"))


def test_kfold_sweep_points_keep_the_fold(toy_dir: Path, tmp_path: Path) -> None:
    config = toy_config(
        toy_dir,
        tmp_path,
        sample=KFOLD3,
        sweeps=[{"parameter": "n_bins", "values": [2, 3]}],
    )
    points = sweep_points(config, "n_bins")
    assert [(p.value, p.config.sample.fold) for p in points] == [  # type: ignore[union-attr]
        (2, 0),
        (2, 1),
        (2, 2),
        (3, 0),
        (3, 1),
        (3, 2),
    ]


# -- the thesis configuration out of sample ------------------------------------


@needs_fixture
def test_thesis_holdout_run_on_the_parity_fixture(tmp_path: Path) -> None:
    base = load_config(PARITY_CONFIG)
    config = parse_config(
        {
            **base.model_dump(mode="json"),
            "sample": HOLDOUT,
            "scopes": [{"kind": "portfolio"}],
            "objectives": [{"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.95}],
            "sweeps": [],
            "output": {"directory": str(tmp_path)},
        }
    )
    (run,) = config.single_runs()
    store = ResultStore(tmp_path)
    outcome = run_single(run, load_input(config), store)
    assert outcome.ok
    m = store.manifest(outcome.run_id)
    assert m["samples"]["calibration"] == {"name": "train", "fold": 0}
    table = store.read("kpis")
    gap = kpi_gap(table)
    mask = (gap["level"] == "portfolio") & (gap["kpi"] == "expected_loss")
    train = gap.loc[mask, "train"].to_list()
    test = gap.loc[mask, "test"].to_list()
    assert len(train) == len(test) == 1
    # Train years 0 .. 6,999 and test years 7,000 .. 9,999 are different data.
    assert train != test
