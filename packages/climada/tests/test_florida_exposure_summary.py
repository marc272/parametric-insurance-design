"""Tests for ``scripts/florida_exposure_summary.py`` (MAR-114).

The annual-loss and tail-dependence helpers against hand-computed values,
and one end-to-end run of the figure on the tiny synthetic pipeline output.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from parametric_insurance_design_climada.pipeline import build_eventset

from .conftest import LOCATIONS

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "florida_exposure_summary.py"


def _load() -> ModuleType:
    name = "florida_exposure_summary"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fes = _load()


def test_tail_dependence_by_hand() -> None:
    # 100 outcomes: column 0 exceeds its 0.99 quantile only at row 99,
    # column 1 at row 99 too, column 2 at row 0.
    annual = np.zeros((100, 3))
    annual[:, 0] = np.arange(100)
    annual[:, 1] = np.arange(100) * 2.0
    annual[:, 2] = np.arange(100)[::-1]
    lam, quantiles, p = fes.tail_dependence(annual, 0.99)
    np.testing.assert_allclose(quantiles, [98.01, 196.02, 98.01])
    np.testing.assert_allclose(p, [0.01, 0.01, 0.01])
    np.testing.assert_allclose(
        lam, [[1.0, 1.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 1.0]], atol=1e-12
    )
    with pytest.raises(ValueError, match="q must be"):
        fes.tail_dependence(annual, 1.0)


def test_rare_losses_give_a_zero_quantile_and_a_small_diagonal() -> None:
    annual = np.zeros((1000, 1))
    annual[:3, 0] = 1.0
    lam, quantiles, p = fes.tail_dependence(annual, 0.99)
    assert quantiles[0] == 0.0
    assert p[0] == pytest.approx(0.003)
    assert lam[0, 0] == pytest.approx(0.3)


def test_annual_losses_sum_rows_per_year_and_draw(
    make_config: Callable[..., Any],
) -> None:
    es = build_eventset(
        make_config(vulnerability={"kind": "emanuel_v_half", "n_draws": 2, "seed": 1})
    ).eventset
    annual, n_draws = fes.annual_losses(es)
    assert n_draws == 2
    assert annual.shape == (es.metadata.n_years * 2, es.n_locations)
    np.testing.assert_allclose(annual.sum(axis=0), es.loss.sum(axis=0))
    # Every row lands at year * n_draws + draw_id.
    row = es.events.iloc[3]
    expected = es.loss[
        (es.events["year"] == row["year"]) & (es.events["draw_id"] == row["draw_id"])
    ].sum(axis=0)
    np.testing.assert_allclose(annual[row["year"] * 2 + row["draw_id"]], expected)


def test_summary_writes_the_figure_and_its_data(
    make_config: Callable[..., Any], tmp_path: Path
) -> None:
    es = build_eventset(make_config()).eventset
    fes_monroe = fes.MONROE
    # Relabel L1 as Monroe so that the Monroe panel has data.
    locations = es.locations.copy()
    locations.loc[0, "location_id"] = fes_monroe
    es = type(es)(
        events=es.events,
        locations=locations,
        index=es.index,
        loss=es.loss,
        metadata=es.metadata,
    )
    cells = pd.DataFrame(
        {
            "lat": [loc["lat"] for loc in LOCATIONS] + [26.0],
            "lon": [loc["lon"] for loc in LOCATIONS] + [-80.5],
            "value": [loc["value"] for loc in LOCATIONS] + [0.0],
            "location_id": [fes_monroe, "L2", "L3", None],
        }
    )
    counties = gpd.GeoDataFrame(
        {
            "unit_id": [fes_monroe, "L2"],
            "name": ["Monroe", "Other"],
            "state_fips": ["12", "12"],
        },
        geometry=[shapely.box(-81, 25, -80, 26), shapely.box(-80.2, 25.7, -80, 26)],
        crs="EPSG:4326",
    )
    summary = fes.summarise(es, cells, counties, tmp_path / "out", q=0.9)
    out = tmp_path / "out"
    assert (out / "exposure_summary.png").stat().st_size > 10_000
    table = pd.read_csv(out / "counties.csv", dtype={"location_id": str})
    assert len(table) == 3
    assert table["value_rank"].tolist() == [1, 2, 3]
    np.testing.assert_allclose(
        table.set_index("location_id")
        .loc[es.location_ids, "expected_annual_loss"]
        .to_numpy(),
        es.rates @ es.loss,
        rtol=1e-5,
    )
    assert len(pd.read_csv(out / "tail_dependence.csv")) == 9
    assert len(pd.read_csv(out / "monroe_cells.csv")) == 1
    written = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert written["eventset_content_hash"] == es.content_hash()
    assert summary["monroe"]["n_cells"] == 1
