"""Tests for ``scripts/compare_hazard_return_levels.py`` (MAR-32).

The annual aggregation and the return-level rule against hand-computed
values, and one end-to-end run on the tiny IRIS and STORM fixture builds.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design_climada.config import parse_config
from parametric_insurance_design_climada.pipeline import build_eventset

from .test_storm import iris_fixture_as_storm

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "compare_hazard_return_levels.py"
)


def _load() -> ModuleType:
    name = "compare_hazard_return_levels"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


crl = _load()


def _eventset(
    years: list[int],
    loss: list[list[float]],
    *,
    n_years: int,
    draws: list[int] | None = None,
    index: list[list[float]] | None = None,
    rate: float | None = None,
) -> EventSet:
    from parametric_insurance_design.eventset import (
        EventSetMetadata,
        HazardSource,
        IndexDefinition,
        LossDefinition,
        Provenance,
    )

    n = len(years)
    draws = draws or [0] * n
    n_draws = max(draws) + 1
    loss_arr = np.asarray(loss, dtype=np.float64)
    events = pd.DataFrame(
        {
            "event_id": [f"E{i // n_draws}" for i in range(n)],
            "year": years,
            "rate": rate if rate is not None else 1.0 / (n_years * n_draws),
            "draw_id": draws,
            "scenario_id": "s",
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": [f"L{j}" for j in range(loss_arr.shape[1])],
            "lat": 25.0,
            "lon": -80.0,
            "value": 1.0,
            "name": [f"N{j}" for j in range(loss_arr.shape[1])],
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name="H", release="r"),
        index=IndexDefinition(definition="wind", unit="m/s"),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=n_years,
        scenario="test",
        provenance=Provenance(
            producer="test",
            producer_version="0",
            created_at=datetime(2026, 10, 27, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events,
        locations=locations,
        index=np.asarray(index if index is not None else loss, dtype=np.float64),
        loss=loss_arr,
        metadata=metadata,
    )


def test_annual_outcomes_sum_and_max_per_year_and_draw() -> None:
    es = _eventset(
        [0, 0, 2, 2],
        [[1.0, 0.0], [2.0, 5.0], [3.0, 1.0], [4.0, 0.0]],
        n_years=3,
        draws=[0, 1, 0, 1],
    )
    total = crl.annual_outcomes(es, es.loss, "sum")
    np.testing.assert_array_equal(
        total, [[1, 0], [2, 5], [0, 0], [0, 0], [3, 1], [4, 0]]
    )
    two = _eventset([1, 1], [[1.0, 2.0], [3.0, 1.0]], n_years=2)
    np.testing.assert_array_equal(
        crl.annual_outcomes(two, two.loss, "max"), [[0, 0], [3, 2]]
    )
    np.testing.assert_array_equal(
        crl.annual_outcomes(two, two.loss, "sum"), [[0, 0], [4, 3]]
    )


def test_annual_outcomes_reject_unequal_rates_and_bad_input() -> None:
    es = _eventset([0], [[1.0]], n_years=2, rate=0.1)
    with pytest.raises(crl.ComparisonError, match="equally likely"):
        crl.annual_outcomes(es, es.loss, "sum")
    ok = _eventset([0], [[1.0]], n_years=2)
    with pytest.raises(crl.ComparisonError, match="unknown aggregation"):
        crl.annual_outcomes(ok, ok.loss, "mean")
    with pytest.raises(crl.ComparisonError, match="non-negative"):
        crl.annual_outcomes(ok, -ok.loss, "sum")
    gap = _eventset([0, 1], [[1.0], [1.0]], n_years=2, draws=[0, 2])
    with pytest.raises(crl.ComparisonError, match="draw_id"):
        crl.annual_outcomes(gap, gap.loss, "sum")


def test_return_levels_are_the_kth_largest_year() -> None:
    outcomes = np.arange(10_000, dtype=np.float64)[:, np.newaxis]
    levels = crl.return_levels(outcomes, (10, 50, 100, 250))
    # the 1,000th, 200th, 100th and 40th largest of 0 .. 9,999
    np.testing.assert_array_equal(levels[:, 0], [9000, 9800, 9900, 9960])
    with pytest.raises(crl.ComparisonError, match="return periods"):
        crl.return_levels(outcomes, (20_000,))


def test_compare_an_eventset_with_itself_gives_ratio_one() -> None:
    es = _eventset(
        list(range(10)), [[float(i), 2.0 * i] for i in range(10)], n_years=10
    )
    table, curves = crl.compare(es, es, (2, 5))
    assert set(table["metric"]) == {"annual_loss", "annual_max_index"}
    assert (table["reference"] == table["scenario"]).all()
    assert table["ratio"].dropna().eq(1.0).all()
    portfolio = table[table["location_id"] == "portfolio"]
    assert portfolio["metric"].eq("annual_loss").all()
    np.testing.assert_array_equal(portfolio["reference"], [15.0, 24.0])
    assert curves["reference"]["annual_loss"].iloc[0] == 27.0
    counts = crl.summarise(table)
    assert all(c["equal"] == c["n_locations"] for c in counts)


def test_compare_rejects_other_locations_and_units() -> None:
    one = _eventset([0], [[1.0]], n_years=2)
    two = _eventset([0], [[1.0, 2.0]], n_years=2)
    with pytest.raises(crl.ComparisonError, match="different locations"):
        crl.compare(one, two)


def test_end_to_end_iris_against_storm(
    tmp_path: Path, make_config: Callable[..., Any]
) -> None:
    iris = build_eventset(make_config()).eventset
    storm_dir = tmp_path / "storm"
    iris_fixture_as_storm(storm_dir)
    config = make_config().model_dump()
    config.update(
        catalogue=str(storm_dir),
        tracks={"kind": "storm"},
        n_years=2000,
        scenario_id="storm-present-climate",
        licence="CC-BY-4.0",
        hazard_release="synthetic STORM test files",
    )
    storm = build_eventset(parse_config(config)).eventset
    iris.to_parquet(tmp_path / "iris_es")
    storm.to_parquet(tmp_path / "storm_es")
    out = tmp_path / "out"
    status = crl.main(
        [
            "--reference",
            str(tmp_path / "iris_es"),
            "--scenario",
            str(tmp_path / "storm_es"),
            "--out-dir",
            str(out),
            "--return-periods",
            "2",
            "12",
            "--attribution",
            "test attribution",
        ]
    )
    assert status == 0
    table = pd.read_csv(out / "return_levels.csv")
    assert set(table["return_period"]) == {2, 12}
    summary = json.loads((out / "summary.json").read_text())
    assert summary["reference"]["hazard"] == "IRIS"
    assert summary["scenario"]["hazard"] == "STORM"
    assert summary["scenario"]["content_hash"] == storm.content_hash()
    assert (out / "return_levels.png").stat().st_size > 10_000
    # The 12-year level is the largest of 12 IRIS years (a loss) but the
    # 167th largest of 2,000 STORM years, which hold the same three storms (0).
    loss12 = table[(table["metric"] == "annual_loss") & (table["return_period"] == 12)]
    assert (loss12["scenario"] == 0).all()
    assert (loss12["reference"] > 0).any()
    assert (
        crl.main(
            [
                "--reference",
                str(tmp_path / "x"),
                "--scenario",
                "y",
                "--out-dir",
                str(out),
            ]
        )
        == 1
    )
