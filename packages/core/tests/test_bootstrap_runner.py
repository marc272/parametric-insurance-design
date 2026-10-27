"""The ``bootstrap`` config section and its runner wiring (MAR-23).

Opt-in: without the section, configs keep their hashes and YAML and the
``ci_*`` columns stay null. With it, the runner fills them for every
evaluation sample, the point estimates do not change, and the section is
part of the config hash (the intervals are part of the cached output).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.errors import ConfigError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    BootstrapConfig,
    ExperimentConfig,
    canonical_json,
    config_hash,
    dump_config,
    load_config,
    parse_config,
    to_dict,
)
from parametric_insurance_design.experiment.runner import load_input, run_single
from parametric_insurance_design.experiment.store import ResultStore

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"

needs_fixture = pytest.mark.skipif(
    not (PARITY_EVENTSET.is_dir() and PARITY_CONFIG.is_file()),
    reason="the parity fixture is only in a repository checkout",
)

CI_COLUMNS = ["ci_low", "ci_high", "ci_level", "n_bootstrap"]


def col(frame: pd.DataFrame, name: str) -> np.ndarray:
    """A column as a float numpy array (typed, for pyright)."""
    return np.asarray(frame[name].to_numpy(), dtype=np.float64)


@pytest.fixture
def toy_dir(tmp_path: Path, toy_eventset: EventSet) -> Path:
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


# -- config ----------------------------------------------------------------


def test_absent_bootstrap_is_left_out_of_the_hash_and_the_yaml(
    toy_dir: Path, tmp_path: Path
) -> None:
    config = toy_config(toy_dir, tmp_path)
    assert config.bootstrap is None
    assert '"bootstrap"' not in canonical_json(config)
    assert "bootstrap" not in to_dict(config)
    assert "\nbootstrap:" not in dump_config(config)


def test_bootstrap_section_defaults_and_hash(toy_dir: Path, tmp_path: Path) -> None:
    base = toy_config(toy_dir, tmp_path)
    config = toy_config(toy_dir, tmp_path, bootstrap={"seed": 7})
    assert config.bootstrap == BootstrapConfig(seed=7, n_bootstrap=1000, level=0.9)
    assert config_hash(config) != config_hash(base)
    for other in (
        {"seed": 8},
        {"seed": 7, "n_bootstrap": 10},
        {"seed": 7, "level": 0.8},
    ):
        assert config_hash(toy_config(toy_dir, tmp_path, bootstrap=other)) != (
            config_hash(config)
        )
    # Round trip through YAML, and into every single run.
    assert to_dict(config)["bootstrap"] == {
        "seed": 7,
        "n_bootstrap": 1000,
        "level": 0.9,
    }
    (run,) = config.single_runs()
    assert run.bootstrap == config.bootstrap
    path = tmp_path / "c.yaml"
    path.write_text(dump_config(config), encoding="utf-8")
    assert config_hash(load_config(path)) == config_hash(config)


def test_bootstrap_rng_is_fresh() -> None:
    boot = BootstrapConfig(seed=3)
    assert boot.rng().integers(0, 1000, 5).tolist() == (
        boot.rng().integers(0, 1000, 5).tolist()
    )


@pytest.mark.parametrize(
    "section",
    [
        {},
        {"seed": -1},
        {"seed": 1, "n_bootstrap": 0},
        {"seed": 1, "n_bootstrap": 10.0},
        {"seed": 1, "level": 1.0},
        {"seed": 1, "level": 0.0},
        {"seed": 1, "sead": 2},
    ],
)
def test_invalid_bootstrap_sections(
    toy_dir: Path, tmp_path: Path, section: dict[str, Any]
) -> None:
    with pytest.raises(ConfigError, match="bootstrap"):
        toy_config(toy_dir, tmp_path, bootstrap=section)


# -- runner ----------------------------------------------------------------


def run_kpis(config: ExperimentConfig, store_dir: Path) -> tuple[pd.DataFrame, dict]:
    (run,) = config.single_runs()
    store = ResultStore(store_dir)
    outcome = run_single(run, load_input(config), store)
    assert outcome.ok
    return store.read("kpis"), store.manifest(outcome.run_id)


def test_runner_without_bootstrap_leaves_the_intervals_null(
    toy_dir: Path, tmp_path: Path
) -> None:
    table, manifest = run_kpis(toy_config(toy_dir, tmp_path), tmp_path / "s")
    for name in CI_COLUMNS:
        assert np.all(np.isnan(col(table, name)))
    assert manifest["bootstrap"] is None


def test_runner_fills_the_intervals_and_keeps_the_points(
    toy_dir: Path, tmp_path: Path
) -> None:
    sample = {"kind": "full"}
    plain, _ = run_kpis(toy_config(toy_dir, tmp_path, sample=sample), tmp_path / "a")
    boot = {"seed": 5, "n_bootstrap": 50, "level": 0.8}
    config = toy_config(toy_dir, tmp_path, sample=sample, bootstrap=boot)
    table, manifest = run_kpis(config, tmp_path / "b")
    key = ["problem_id", "eval_split", "fold", "basis", "level", "subject_id", "kpi"]
    merged = plain.merge(table, on=key, suffixes=("_plain", ""), validate="one_to_one")
    assert len(merged) == len(plain) == len(table)
    np.testing.assert_array_equal(merged["value_plain"], merged["value"])
    np.testing.assert_array_equal(col(table, "ci_level"), 0.8)
    np.testing.assert_array_equal(col(table, "n_bootstrap"), 50)
    assert not np.all(np.isnan(col(table, "ci_low")))
    entry = manifest["bootstrap"]
    assert {k: entry[k] for k in ("seed", "n_bootstrap", "level")} == boot
    (logged,) = entry["samples"]
    assert logged["sample"] == "full"
    assert logged["n_without_bounds"] == int(np.isnan(col(table, "ci_low")).sum())
    assert logged["seconds"] >= 0
    # Same config, new store: the same intervals (the seed fixes the resample).
    again, _ = run_kpis(config, tmp_path / "c")
    first = table.sort_values(key).reset_index(drop=True)
    second = again.sort_values(key).reset_index(drop=True)
    for name in CI_COLUMNS:
        np.testing.assert_array_equal(col(first, name), col(second, name))


@needs_fixture
def test_thesis_holdout_with_intervals(tmp_path: Path) -> None:
    base = load_config(PARITY_CONFIG)
    data = {
        **base.model_dump(mode="json"),
        "sample": {"kind": "holdout", "train_fraction": 0.7},
        "scopes": [{"kind": "portfolio"}],
        "objectives": [{"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.95}],
        "sweeps": [],
        "output": {"directory": str(tmp_path)},
    }
    plain, _ = run_kpis(parse_config(data), tmp_path / "plain")
    config = parse_config({**data, "bootstrap": {"seed": 0, "n_bootstrap": 200}})
    table, manifest = run_kpis(config, tmp_path / "boot")
    key = ["eval_split", "level", "subject_id", "kpi"]
    merged = plain.merge(table, on=key, suffixes=("_plain", ""), validate="one_to_one")
    np.testing.assert_array_equal(merged["value_plain"], merged["value"])
    assert {s["sample"] for s in manifest["bootstrap"]["samples"]} == {"train", "test"}
    split = np.asarray(table["eval_split"].to_numpy())
    level = np.asarray(table["level"].to_numpy())
    kpi = np.asarray(table["kpi"].to_numpy())
    test = (split == "test") & (level == "portfolio")
    assert not np.any(np.isnan(col(table, "ci_low")[test]))
    (i,) = np.flatnonzero(test & (kpi == "cvar_uncovered"))
    assert col(table, "ci_low")[i] < col(table, "value")[i] < col(table, "ci_high")[i]
