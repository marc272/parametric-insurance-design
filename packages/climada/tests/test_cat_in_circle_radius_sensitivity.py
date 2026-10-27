"""Tests for ``scripts/cat_in_circle_radius_sensitivity.py`` (MAR-133).

The category shares, the step payout and its unexplained share against
hand-computed values, and one end-to-end run on the tiny synthetic pipeline
output at two radii.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design_climada.pipeline import build_eventset

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "cat_in_circle_radius_sensitivity.py"
)


def _load() -> ModuleType:
    name = "cat_in_circle_radius_sensitivity"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


crs = _load()

# Four rows, two locations, three categories (0-2).
INDEX = np.array([[0.0, 1.0], [0.0, 2.0], [1.0, 2.0], [2.0, 0.0]])
LOSS = np.array([[1.0, 2.0], [3.0, 4.0], [4.0, 6.0], [8.0, 0.0]])
RATES = np.full(4, 0.25)


def test_category_shares_by_hand() -> None:
    table = crs.category_shares(INDEX, LOSS, RATES, 3)
    assert table["n_pairs"].tolist() == [3, 2, 3]
    np.testing.assert_allclose(table["pair_share"], [3 / 8, 2 / 8, 3 / 8])
    # Total loss 28: category 0 holds 1 + 3 + 0, category 1 holds 2 + 4,
    # category 2 holds 4 + 6 + 8.
    np.testing.assert_allclose(table["loss_share"], [4 / 28, 6 / 28, 18 / 28])


def test_category_shares_rejects_bad_index() -> None:
    with pytest.raises(ValueError, match="integers"):
        crs.category_shares(INDEX + 0.5, LOSS, RATES, 3)
    with pytest.raises(ValueError, match="integers"):
        crs.category_shares(INDEX, LOSS, RATES, 2)
    with pytest.raises(ValueError, match="total loss is zero"):
        crs.category_shares(INDEX, np.zeros_like(LOSS), RATES, 3)


def test_step_payout_is_the_weighted_mean_loss_per_category() -> None:
    rates = np.array([0.1, 0.3, 0.2, 0.4])
    fitted, levels = crs.step_payout(INDEX, LOSS, rates, 3)
    # Location 0: category 0 rows 0 and 1 (weights 0.1, 0.3).
    np.testing.assert_allclose(levels[:, 0], [(0.1 + 0.9) / 0.4, 4.0, 8.0])
    # Location 1: category 2 rows 1 and 2 (weights 0.3, 0.2).
    np.testing.assert_allclose(levels[:, 1], [0.0, 2.0, (1.2 + 1.2) / 0.5])
    np.testing.assert_allclose(fitted[:, 0], [2.5, 2.5, 4.0, 8.0])
    np.testing.assert_allclose(fitted[:, 1], [2.0, 4.8, 4.8, 0.0])


def test_unexplained_share_by_hand() -> None:
    target = np.array([0.0, 2.0, 4.0])
    weights = np.ones(3)
    assert crs.unexplained_share(target, target, weights) == pytest.approx(0.0)
    # Fitting the mean leaves all the variance.
    assert crs.unexplained_share(target, np.full(3, 2.0), weights) == pytest.approx(1.0)
    # Residuals (0, 1, 0): 1 / 8.
    assert crs.unexplained_share(
        target, np.array([0.0, 1.0, 4.0]), weights
    ) == pytest.approx(1 / 8)
    out = crs.unexplained_share(np.ones((3, 2)), np.ones((3, 2)), weights)
    assert np.isnan(out).all()


def test_matrix_hash_depends_on_shape_and_values() -> None:
    a = np.arange(6, dtype=np.float64).reshape(2, 3)
    assert crs.matrix_hash(a) == crs.matrix_hash(a.astype(np.float32))
    assert crs.matrix_hash(a) != crs.matrix_hash(a.reshape(3, 2))
    assert crs.matrix_hash(a).startswith("sha256:")
    with pytest.raises(ValueError, match="2-D"):
        crs.matrix_hash(np.arange(3.0))


def test_annual_sums() -> None:
    values = np.array([1.0, 2.0, 4.0])
    out = crs.annual_sums(values, np.array([0, 0, 2]), np.array([0, 1, 1]), 3)
    np.testing.assert_allclose(out, [1.0, 2.0, 0.0, 0.0, 0.0, 4.0])
    with pytest.raises(ValueError, match="draw_id"):
        crs.annual_sums(values, np.array([0, 0, 2]), np.array([0, 2, 2]), 3)


def test_analyse_rejects_a_wind_index(make_config: Callable[..., Any]) -> None:
    es = build_eventset(make_config()).eventset
    with pytest.raises(ValueError, match="cat-in-a-circle"):
        crs.analyse(es, label="x", provisional=False, config_sha256=None)


def test_main_writes_the_tables_and_the_figure(
    make_config: Callable[..., Any], tmp_path: Path
) -> None:
    paths = []
    for radius in (50, 100):
        es = build_eventset(
            make_config(index={"kind": "cat_in_circle", "radius_km": radius})
        ).eventset
        paths.append(es.to_parquet(tmp_path / f"es{radius}"))
    config = tmp_path / "config.yaml"
    config.write_text("x: 1\n", encoding="utf-8")
    out = tmp_path / "out"
    argv = [
        "--eventset",
        str(paths[0]),
        "--eventset",
        str(paths[1]),
        "--config",
        str(config),
        "--config",
        str(config),
        "--provisional",
        str(paths[0]),
        "--out-dir",
        str(out),
    ]
    assert crs.main(argv) == 0
    summary = pd.read_csv(out / "summary.csv")
    assert summary["radius_km"].tolist() == [50, 100, 50]
    assert summary["provisional"].tolist() == [False, False, True]
    shares = summary[[f"loss_share_cat{c}" for c in range(6)]].sum(axis=1)
    np.testing.assert_allclose(shares, 1.0)
    # Same rows and loss at both radii; only the index differs.
    assert summary["loss_matrix_hash"].nunique() == 1
    es50 = type(build_eventset(make_config()).eventset).from_parquet(paths[0])
    assert summary["eventset_content_hash"][0] == es50.content_hash()
    assert summary["index_table_hash"][0] == crs.matrix_hash(es50.index)
    counties = pd.read_csv(out / "counties.csv")
    assert len(counties) == 3 * es50.n_locations
    np.testing.assert_allclose(
        counties["eal_usd"][: es50.n_locations], es50.rates @ es50.loss, rtol=1e-5
    )
    assert (out / "radius_sensitivity.png").stat().st_size > 10_000
    checksums = json.loads((out / "checksums.json").read_text(encoding="utf-8"))
    assert set(checksums["outputs"]) == {
        "summary.csv",
        "counties.csv",
        "radius_sensitivity.png",
    }
