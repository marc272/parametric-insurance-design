"""Tests of the configurable exceedance return periods (MAR-117).

``evaluation.return_periods`` chooses the return periods of the ``exceedance``
table. The default is ``evaluate.DEFAULT_RETURN_PERIODS`` and is left out of
every dump and of the config hash, so configs that do not set another grid
keep their hash and run ids. The parity config sets the thesis grid
of Figure 5.6 (thesis ``plot_exceedance_curves``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from parametric_insurance_design.errors import ConfigError
from parametric_insurance_design.evaluate import DEFAULT_RETURN_PERIODS
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    EvaluationConfig,
    canonical_json,
    config_hash,
    dump_config,
    load_config,
    parse_config,
    to_dict,
)
from parametric_insurance_design.experiment.runner import load_input, run_config
from parametric_insurance_design.experiment.store import ResultStore

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"

needs_fixture = pytest.mark.skipif(
    not (PARITY_EVENTSET.is_dir() and PARITY_CONFIG.is_file()),
    reason="the parity fixture is only in a repository checkout",
)

THESIS_GRID = (2.0, 5.0, 10.0, 20.0, 50.0, 100.0, 200.0, 500.0)
"""Thesis ``plot_exceedance_curves`` default (``src/utils/plotting.py``)."""

THESIS_SINGLE_RUN_HASHES_BEFORE_MAR_117 = (
    "sha256:3eec7ac6ed4dac0540d409a87893d4e000f5e52c006833efd2f3e2db6e85d24c",
    "sha256:8e3e9ca927bfacf4ed5170f7498c7b8d3fbb12d9b55a2aa1ef6ace7fc20a86bd",
    "sha256:3666438e3ea961bf33412f3c1c6901baf1c80327f49ce186da0218620812dba5",
    "sha256:9cedd23cf2511120da05d19a683dd783c25b34a90ad93484a946ca1837401d81",
    "sha256:5ebf4bdfcedf9a1b65338e0866cfb2d813b53d5c5102d321ed0a35703686fda9",
    "sha256:e85db2607bc6c8f8530baa4cfbf55ece989c8e25d210693bd215fd59222254f2",
    "sha256:e134d0bea41f0bbf99b12a8817b161a2d3acb92a7bd38f9a8ea756322ac2178c",
    "sha256:bbe10df69cbe6dc84bc6b8fca70e57eda14a20389e4ef954416232908c27236b",
    "sha256:71718bcbd1d5384f70fba6472d89e3f846a62160f728ee6663e08a2522d27a6b",
)
"""``config_hash`` of the 9 thesis single runs before MAR-117 (default grid)."""


def toy_dict(eventset_path: Path, output: Path) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": "toy",
        "eventset": {"path": str(eventset_path)},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
        "scopes": [{"kind": "portfolio"}],
        "objectives": [{"kind": "expected_uncovered"}],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.5},
        "output": {"directory": str(output)},
    }


def toy(
    tmp_path: Path, return_periods: object = None, *, set_it: bool = True
) -> dict[str, Any]:
    data = toy_dict(tmp_path / "eventset", tmp_path / "results")
    if set_it:
        data["evaluation"]["return_periods"] = return_periods
    return data


@pytest.fixture
def toy_dir(tmp_path: Path, toy_eventset: EventSet) -> Path:
    path = tmp_path / "eventset"
    toy_eventset.to_parquet(path)
    return path


# -- default ----------------------------------------------------------------------


def test_default_is_the_core_grid_and_left_out_of_dumps(tmp_path: Path) -> None:
    unset = parse_config(toy(tmp_path, set_it=False))
    assert unset.evaluation.return_periods == DEFAULT_RETURN_PERIODS
    assert "return_periods" not in to_dict(unset)["evaluation"]
    assert "return_periods" not in canonical_json(unset)
    assert "return_periods" not in dump_config(unset)


@pytest.mark.parametrize(
    "grid", [list(DEFAULT_RETURN_PERIODS), [2, 5, 10, 25, 50, 100, 250]]
)
def test_explicit_default_hashes_as_unset(tmp_path: Path, grid: list[float]) -> None:
    unset = parse_config(toy(tmp_path, set_it=False))
    explicit = parse_config(toy(tmp_path, grid))
    assert explicit == unset
    assert canonical_json(explicit) == canonical_json(unset)
    assert config_hash(explicit) == config_hash(unset)
    assert to_dict(explicit) == to_dict(unset)


def test_evaluation_config_default() -> None:
    assert EvaluationConfig(beta=0.9).return_periods == DEFAULT_RETURN_PERIODS


# -- custom -----------------------------------------------------------------------


def test_custom_grid_is_dumped_hashed_and_read_back(tmp_path: Path) -> None:
    custom = parse_config(toy(tmp_path, [2, 5, 10, 20, 50, 100, 200, 500]))
    plain = parse_config(toy(tmp_path, set_it=False))
    assert custom.evaluation.return_periods == THESIS_GRID
    assert all(type(t) is float for t in custom.evaluation.return_periods)
    assert to_dict(custom)["evaluation"]["return_periods"] == list(THESIS_GRID)
    assert '"return_periods":[2.0,5.0,10.0,20.0,50.0,100.0,200.0,500.0]' in (
        canonical_json(custom)
    )
    assert config_hash(custom) != config_hash(plain)
    again = parse_config(yaml.safe_load(dump_config(custom)))
    assert again == custom
    assert config_hash(again) == config_hash(custom)


def test_custom_grid_is_kept_by_derived_configs(tmp_path: Path) -> None:
    data = toy(tmp_path, [1.5, 20.0, 1000.0])
    data["objectives"] = [{"kind": "weighted_cvar", "alpha": 0.5, "beta": 0.9}]
    data["sweeps"] = [{"parameter": "alpha", "values": [0.1, 0.9]}]
    config = parse_config(data)
    grid = (1.5, 20.0, 1000.0)
    assert all(s.evaluation.return_periods == grid for s in config.single_runs())
    assert config.with_parameter("alpha", 0.1).evaluation.return_periods == grid


@pytest.mark.parametrize(
    ("grid", "message"),
    [
        ([], "at least one return period"),
        ([0, 2], "greater than 1"),
        ([-5.0], "greater than 1"),
        ([1, 2], "greater than 1"),
        ([5, 2], "increasing order"),
        ([2, 10, 5], "increasing order"),
        ([2, 2, 5], "repeat"),
        ([2.0, 5, 5.0], "repeat"),
        ([2, float("inf")], "finite number"),
        ([2, float("nan")], "finite number"),
        (["20"], "valid number"),
        ([True, 2], "valid number"),
        (20, "valid tuple"),
        (None, "valid tuple"),
    ],
)
def test_invalid_grids_raise_config_error(
    tmp_path: Path, grid: object, message: str
) -> None:
    with pytest.raises(ConfigError) as info:
        parse_config(toy(tmp_path, grid), source="test.yaml")
    text = str(info.value)
    assert "evaluation.return_periods" in text
    assert message in text


# -- runner -----------------------------------------------------------------------


def test_runner_stores_the_configured_grid(toy_dir: Path, tmp_path: Path) -> None:
    del toy_dir
    grid = [1.5, 3.0, 40.0]
    store = ResultStore(tmp_path / "custom")
    run_config(parse_config(toy(tmp_path, grid)), store=store)
    stored = np.unique(store.read("exceedance")["return_period"].to_numpy())
    np.testing.assert_array_equal(stored, grid)


def test_runner_default_grid_and_run_id_unchanged(
    toy_dir: Path, tmp_path: Path
) -> None:
    del toy_dir
    unset = parse_config(toy(tmp_path, set_it=False))
    explicit = parse_config(toy(tmp_path, list(DEFAULT_RETURN_PERIODS)))
    store = ResultStore(tmp_path / "default")
    (first,) = run_config(unset, store=store)
    (second,) = run_config(explicit, store=store)
    assert second.cached
    assert second.run_id == first.run_id
    stored = np.unique(store.read("exceedance")["return_period"].to_numpy())
    np.testing.assert_array_equal(stored, DEFAULT_RETURN_PERIODS)


# -- the parity config ------------------------------------------------------------


def test_parity_config_sets_the_thesis_grid() -> None:
    config = load_config(PARITY_CONFIG)
    assert config.evaluation.return_periods == THESIS_GRID
    # Only the grid changed: without it the single runs hash as before MAR-117.
    data = to_dict(config)
    del data["evaluation"]["return_periods"]
    before = parse_config(data, base_dir=PARITY_CONFIG.parent)
    assert tuple(config_hash(s) for s in before.single_runs()) == (
        THESIS_SINGLE_RUN_HASHES_BEFORE_MAR_117
    )
    assert not {config_hash(s) for s in config.single_runs()} & set(
        THESIS_SINGLE_RUN_HASHES_BEFORE_MAR_117
    )


@needs_fixture
def test_parity_run_stores_rp_20_200_and_500(tmp_path: Path) -> None:
    config = load_config(PARITY_CONFIG)
    (run,) = [
        s
        for s in config.single_runs()
        if s.scopes[0].kind == "portfolio" and s.objectives[0].kind == "weighted_cvar"
    ]
    store = ResultStore(tmp_path)
    (outcome,) = run_config(run, store=store, data=load_input(config))
    assert outcome.ok
    exceedance = store.read("exceedance")
    portfolio = exceedance.loc[exceedance["level"] == "portfolio", "return_period"]
    stored = np.unique(portfolio.to_numpy(dtype=np.float64))
    np.testing.assert_array_equal(stored, THESIS_GRID)
    assert {20.0, 200.0, 500.0} <= set(stored)
