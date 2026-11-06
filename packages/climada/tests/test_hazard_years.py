"""The pipeline's CLIMADA hazards carry the catalogue's rate and years (MAR-258).

Each batch's ``TropCyclone`` has frequency ``1 / n_years`` and its events are
dated by their simulation year, so that the hazard can be used on its own:
the frequencies sum to the annual event rate, the years round-trip through
the dates and the event names (also through CLIMADA's ``concat``, ``select``
and HDF5 files), and the petals prototype's README example runs on the
adapter's hazard without setting frequencies or years by hand. None of this
changes the EventSet.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from climada.engine import Impact, ImpactCalc
from climada.hazard import TCTracks, TropCyclone
from hypothesis import given
from hypothesis import strategies as st
from numpy.typing import NDArray

import petals_parametric as pm
from parametric_insurance_design.eventset import EventSet, IndexDefinition
from parametric_insurance_design_climada import pipeline, tracks
from parametric_insurance_design_climada.hooks import (
    CentroidWindIndex,
    HazardBatch,
    NoDraws,
)
from parametric_insurance_design_climada.pipeline import build_eventset

from .conftest import HEADER, N_YEARS, _storm
from .test_cell_loss import CELLS, _write_cells
from .test_petals_parametric_readme import _block
from .test_storm import iris_fixture_as_storm

WHEN = datetime(2026, 11, 6, tzinfo=UTC)
DRAWS = {"kind": "emanuel_v_half", "n_draws": 3, "seed": 7}


# --- capturing hooks ----------------------------------------------------------


@dataclass(frozen=True)
class _CaptureIndex:
    """The default index builder, recording every batch it gets."""

    batches: list[HazardBatch] = field(default_factory=list)

    def describe(self, wind_field: str) -> IndexDefinition:
        return CentroidWindIndex().describe(wind_field)

    def parameters(self) -> dict[str, Any]:
        return CentroidWindIndex().parameters()

    def build(self, batch: HazardBatch) -> NDArray[np.float64]:
        self.batches.append(batch)
        return CentroidWindIndex().build(batch)


@dataclass(frozen=True)
class _CaptureDraws(NoDraws):
    """No draws, recording every batch (the cell batch with cell losses)."""

    batches: list[HazardBatch] = field(default_factory=list)

    def losses(
        self,
        batch: HazardBatch,
        base_loss: NDArray[np.float64],
        rng: np.random.Generator | None,
    ) -> NDArray[np.float64]:
        self.batches.append(batch)
        return super().losses(batch, base_loss, rng)


def _concat(batches: list[HazardBatch]) -> tuple[TropCyclone, TCTracks]:
    """All batches' hazards as one hazard, and their tracks, in row order."""
    hazard = TropCyclone.concat([b.hazard for b in batches])
    assert isinstance(hazard, TropCyclone)
    return hazard, TCTracks([t for b in batches for t in b.tracks.data])


def _years_by_name(es: EventSet) -> dict[str, int]:
    first = es.events.groupby("event_id", sort=False)["year"].first()
    return {str(e): int(y) for e, y in first.items()}


def _year_in_name(name: str) -> int:
    """``<basin>_<year>_<tc>`` (IRIS) or ``STORM_<basin>_<year>_<tc>``."""
    return int(name.split("_")[-2])


# --- the date convention ------------------------------------------------------


def test_simulation_years_are_dated_on_1_january_of_year_plus_one() -> None:
    years = np.array([0, 1, 2025, 9998, 9999, 12_000, 0])
    dates = tracks.simulation_year_dates(years)
    assert dates.dtype == np.int64
    assert dates.tolist() == [
        dt.date(1, 1, 1).toordinal(),
        dt.date(2, 1, 1).toordinal(),
        dt.date(2026, 1, 1).toordinal(),
        dt.date(9999, 1, 1).toordinal(),
        tracks.UNDATED,
        tracks.UNDATED,
        1,
    ]
    assert tracks.LAST_DATED_YEAR == 9998
    assert tracks.simulation_year_dates(np.array([], dtype=np.int64)).size == 0


@given(st.lists(st.integers(0, tracks.LAST_DATED_YEAR), min_size=1, max_size=50))
def test_dated_years_round_trip(years: list[int]) -> None:
    dates = tracks.simulation_year_dates(years)
    np.testing.assert_array_equal(tracks.simulation_years_of_dates(dates), years)
    calendar = [dt.date.fromordinal(int(d)).year for d in dates]
    assert calendar == [y + tracks.DATE_YEAR_OFFSET for y in years]


@pytest.mark.parametrize(
    ("years", "match"),
    [
        ([-1, 3], "must be >= 0"),
        ([1.0, 2.0], "must be integers"),
        ([[1, 2]], "one-dimensional"),
    ],
)
def test_bad_simulation_years_are_errors(years: Any, match: str) -> None:  # noqa: ANN401
    with pytest.raises(ValueError, match=match):
        tracks.simulation_year_dates(years)


def test_dates_without_a_simulation_year_are_errors() -> None:
    with pytest.raises(ValueError, match="read the year from the event name"):
        tracks.simulation_years_of_dates([1, tracks.UNDATED])
    with pytest.raises(ValueError, match="is not 1 January"):
        tracks.simulation_years_of_dates([dt.date(2000, 9, 1).toordinal()])


# --- the pipeline's hazards ---------------------------------------------------


@pytest.mark.parametrize("draws", [None, DRAWS], ids=["no-draws", "draws"])
def test_frequencies_sum_to_the_annual_event_rate(
    make_config: Callable[..., Any], draws: dict[str, Any] | None
) -> None:
    capture = _CaptureIndex()
    extra = {} if draws is None else {"vulnerability": draws}
    es = build_eventset(make_config(**extra), index_builder=capture).eventset
    assert len(capture.batches) == 2  # batch_size 2, three modelled storms
    hazard, _ = _concat(capture.batches)
    n_events = int(es.events["event_id"].nunique())
    # One event per storm, not per draw: frequency 1 / n_years, not / n_draws.
    np.testing.assert_array_equal(hazard.frequency, np.full(n_events, 1 / N_YEARS))
    assert hazard.frequency_unit == "1/year"
    assert hazard.frequency.sum() == pytest.approx(n_events / N_YEARS, rel=1e-15)
    assert hazard.frequency.sum() == pytest.approx(es.rates.sum(), rel=1e-12)
    # CLIMADA's own expected annual impact now agrees with the EventSet's.
    batch = capture.batches[0]
    impact = ImpactCalc(batch.exposures, batch.impact_functions, hazard).impact()
    if draws is None:
        expected = float(es.rates @ es.loss.sum(axis=1))
        assert impact.aai_agg == pytest.approx(expected, rel=1e-12)


def test_years_round_trip_through_the_dates_and_the_names(
    make_config: Callable[..., Any],
) -> None:
    capture = _CaptureIndex()
    es = build_eventset(make_config(), index_builder=capture).eventset
    hazard, _ = _concat(capture.batches)
    names = [str(n) for n in hazard.event_name]
    assert names == es.events["event_id"].tolist()
    expected = es.events["year"].to_numpy()
    np.testing.assert_array_equal(
        tracks.simulation_years_of_dates(hazard.date), expected
    )
    assert [_year_in_name(n) for n in names] == expected.tolist()
    # CLIMADA's calendar-year view: one year per simulation year, plus one.
    year_set = hazard.calc_year_set()
    assert sorted(year_set) == sorted({int(y) + 1 for y in expected})
    for year, ids in year_set.items():
        chosen = [names[i] for i in np.flatnonzero(np.isin(hazard.event_id, ids))]
        assert {_years_by_name(es)[n] for n in chosen} == {year - 1}


def test_climada_keeps_the_years_and_frequencies(
    make_config: Callable[..., Any], tmp_path: Path
) -> None:
    capture = _CaptureIndex()
    build_eventset(make_config(), index_builder=capture)
    hazard, _ = _concat(capture.batches)
    path = tmp_path / "hazard.h5"
    hazard.write_hdf5(path)
    back = TropCyclone.from_hdf5(path)
    np.testing.assert_array_equal(back.date, hazard.date)
    np.testing.assert_array_equal(back.frequency, hazard.frequency)
    assert list(back.event_name) == list(hazard.event_name)
    one = hazard.select(event_names=["NA_3_0"])
    assert one is not None
    assert tracks.simulation_years_of_dates(one.date).tolist() == [3]
    assert one.frequency.tolist() == [1 / N_YEARS]
    impact = ImpactCalc(
        capture.batches[0].exposures, capture.batches[0].impact_functions, hazard
    ).impact()
    np.testing.assert_array_equal(impact.date, hazard.date)
    np.testing.assert_array_equal(impact.frequency, hazard.frequency)


def test_cell_hazards_carry_the_same_years(
    make_config: Callable[..., Any], tmp_path: Path
) -> None:
    cells = _write_cells(tmp_path / "cells.parquet", CELLS)
    index, draws = _CaptureIndex(), _CaptureDraws()
    es = build_eventset(
        make_config(loss={"kind": "cells", "cells": str(cells)}),
        index_builder=index,
        vulnerability=draws,
    ).eventset
    location_hazard, _ = _concat(index.batches)
    cell_hazard, _ = _concat(draws.batches)
    assert cell_hazard.centroids.size > location_hazard.centroids.size
    for hazard in (location_hazard, cell_hazard):
        np.testing.assert_array_equal(hazard.date, location_hazard.date)
        np.testing.assert_array_equal(hazard.frequency, np.full(3, 1 / N_YEARS))
    np.testing.assert_array_equal(
        tracks.simulation_years_of_dates(cell_hazard.date), es.events["year"]
    )


def test_storm_hazards_carry_the_rebuilt_years(
    make_config: Callable[..., Any], tmp_path: Path
) -> None:
    directory = tmp_path / "storm"
    iris_fixture_as_storm(directory)
    capture = _CaptureIndex()
    config = make_config(
        catalogue=str(directory),
        tracks={"kind": "storm"},
        n_years=2000,
        licence="CC-BY-4.0",
    )
    es = build_eventset(config, index_builder=capture).eventset
    hazard, _ = _concat(capture.batches)
    years = es.events["year"].to_numpy()
    assert years.max() >= 1000  # the second file's years: 1000 * k + year
    np.testing.assert_array_equal(tracks.simulation_years_of_dates(hazard.date), years)
    assert [_year_in_name(str(n)) for n in hazard.event_name] == years.tolist()
    np.testing.assert_array_equal(hazard.frequency, np.full(len(years), 1 / 2000))


CIRCLE = {"kind": "cat_in_circle", "radius_km": 50}


@pytest.mark.parametrize(
    "update",
    [{}, {"vulnerability": DRAWS}, {"index": CIRCLE}],
    ids=["centroid", "draws", "cat-in-circle"],
)
def test_the_hazards_years_do_not_change_the_eventset(
    make_config: Callable[..., Any],
    monkeypatch: pytest.MonkeyPatch,
    update: dict[str, Any],
) -> None:
    config = make_config(**update)
    dated = build_eventset(config, created_at=WHEN).eventset
    monkeypatch.setattr(pipeline, "_set_simulation_years", lambda *_: None)
    undated = build_eventset(config, created_at=WHEN).eventset
    assert dated.content_hash() == undated.content_hash()


def test_the_hazard_needs_one_year_per_event() -> None:
    hazard = TropCyclone()
    hazard.event_id = np.array([1, 2])
    with pytest.raises(pipeline.PipelineError, match="for a hazard of 2 events"):
        pipeline._set_simulation_years(hazard, np.array([0]), 10)


# --- the last year of a 10,000-year catalogue -------------------------------------


def _write_catalogue(path: Path, storms: list[tuple[int, int, float]]) -> Path:
    """IRIS text with one straight storm per ``(year, tc, latitude)``."""
    lon = np.linspace(-77.0, -83.0, 13)
    rows = [HEADER]
    for tcid, (year, tc, lat) in enumerate(storms, start=1):
        rows += _storm(tcid, year, tc, np.full(13, lat), lon, 55.0, 945.0)
    path.write_text("".join(rows), encoding="utf-8")
    return path


def test_the_last_year_of_10000_has_no_date_but_keeps_its_name(
    make_config: Callable[..., Any],
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    catalogue = _write_catalogue(
        tmp_path / "iris_10000.txt",
        [(0, 0, 25.75), (5000, 0, 25.8), (9999, 0, 25.85), (9999, 1, 26.0)],
    )
    capture = _CaptureIndex()
    with caplog.at_level(logging.WARNING, logger=pipeline.__name__):
        es = build_eventset(
            make_config(catalogue=str(catalogue), n_years=10_000, batch_size=10),
            index_builder=capture,
        ).eventset
    (batch,) = capture.batches
    hazard = batch.hazard
    names = [str(n) for n in hazard.event_name]
    assert names == ["NA_0_0", "NA_5000_0", "NA_9999_0", "NA_9999_1"]
    assert hazard.date.tolist() == [
        1,
        dt.date(5001, 1, 1).toordinal(),
        tracks.UNDATED,
        tracks.UNDATED,
    ]
    assert es.events["year"].tolist() == [0, 5000, 9999, 9999]
    assert [_year_in_name(n) for n in names] == [0, 5000, 9999, 9999]
    warnings = [r.getMessage() for r in caplog.records if "no date" in r.getMessage()]
    assert len(warnings) == 1
    assert "2 storm(s)" in warnings[0]
    assert "NA_9999_0" in warnings[0]
    # Readers of the date refuse it instead of returning a wrong year ...
    with pytest.raises(ValueError, match="event name"):
        tracks.simulation_years_of_dates(hazard.date)
    with pytest.raises(pm.ParametricInputError, match="pass event_year"):
        pm.ParametricIndex.from_hazard(hazard, batch.exposures)
    # ... and the years from the names work.
    index = pm.ParametricIndex.from_hazard(
        hazard,
        batch.exposures,
        event_year=[_year_in_name(n) for n in names],
        years=np.arange(10_000),
    )
    assert index.years.size == 10_000


# --- the petals prototype's README example, on the adapter's hazard ---------------

README_YEARS = 30


@pytest.fixture
def readme_catalogue(tmp_path: Path) -> Path:
    """40 straight storms in simulation years 0-29 across the README's sites."""
    rng = np.random.default_rng(20261106)
    years = np.sort(rng.integers(0, README_YEARS, size=40))
    years[[0, -1]] = [0, README_YEARS - 1]
    lon = np.linspace(-77.0, -83.0, 13)
    rows = [HEADER]
    seen: dict[int, int] = {}
    for tcid, year in enumerate(years.tolist(), start=1):
        tc = seen.get(year, 0)
        seen[year] = tc + 1
        lat = float(rng.uniform(25.0, 26.8))
        vmax = float(rng.uniform(25.0, 75.0))
        rows += _storm(tcid, year, tc, np.full(13, lat), lon, vmax, 950.0)
    path = tmp_path / "iris_readme.txt"
    path.write_text("".join(rows), encoding="utf-8")
    return path


@pytest.fixture
def adapter_objects(
    make_config: Callable[..., Any], readme_catalogue: Path
) -> tuple[EventSet, dict[str, Any]]:
    """The adapter's EventSet, and its CLIMADA objects, used as they come."""
    capture = _CaptureIndex()
    config = make_config(
        catalogue=str(readme_catalogue), n_years=README_YEARS, batch_size=16
    )
    es = build_eventset(config, index_builder=capture).eventset
    assert len(capture.batches) == 3
    hazard, track_data = _concat(capture.batches)
    exposures = capture.batches[0].exposures
    impact = ImpactCalc(exposures, capture.batches[0].impact_functions, hazard).impact(
        save_mat=True
    )
    return es, {
        "tracks": track_data,
        "hazard": hazard,
        "exposures": exposures,
        "impact": impact,
    }


def test_the_readme_example_runs_on_the_adapters_hazard(
    adapter_objects: tuple[EventSet, dict[str, Any]],
) -> None:
    es, objects = adapter_objects
    namespace = dict(objects)
    exec(compile(_block("design"), "README design example", "exec"), namespace)
    index = namespace["index"]
    # The prototype read the years from the dates and N from the frequency.
    np.testing.assert_array_equal(index.event_year - 1, es.events["year"])
    np.testing.assert_array_equal(index.years - 1, np.arange(README_YEARS))
    train, test = namespace["train"], namespace["test"]
    n_train = 21  # SPEC §6.1: the first 70 % of the 30 years
    np.testing.assert_array_equal(train - 1, np.arange(n_train))
    np.testing.assert_array_equal(test - 1, np.arange(n_train, README_YEARS))
    np.testing.assert_allclose(
        objects["impact"].imp_mat.toarray(), es.loss, rtol=1e-12, atol=0
    )
    for name in ("tail", "joint", "combined"):
        assert isinstance(namespace[name], pm.ParametricCover)
    assert isinstance(namespace["payouts"], Impact)
    assert isinstance(namespace["metrics"], pd.DataFrame)
    assert index.values.max() >= 1
    assert namespace["combined"].premium > 0
    # The test years hold storms with loss, so the test metrics are not void.
    assert es.loss[np.isin(es.events["year"], np.arange(n_train, 30))].sum() > 0


def test_the_hand_fix_is_no_longer_needed(
    adapter_objects: tuple[EventSet, dict[str, Any]],
) -> None:
    """The adapter's hazard as it comes = the hazard with the old hand fix."""
    es, objects = adapter_objects
    hazard, exposures = objects["hazard"], objects["exposures"]
    fixed = hazard.select(event_names=list(hazard.event_name))
    assert fixed is not None
    fixed.frequency = np.full(fixed.size, 1.0 / README_YEARS)
    by_hand = pm.ParametricIndex.from_hazard(
        fixed,
        exposures,
        event_year=es.events["year"].to_numpy(),
        years=np.arange(README_YEARS),
    )
    as_is = pm.ParametricIndex.from_hazard(hazard, exposures)
    np.testing.assert_array_equal(as_is.frequency, by_hand.frequency)
    np.testing.assert_array_equal(as_is.values, by_hand.values)
    train_by_hand, _ = pm.split_years(by_hand, train_fraction=0.7)
    train_as_is, _ = pm.split_years(as_is, train_fraction=0.7)
    impact = objects["impact"]
    payout = pm.StepPayout(attachment=20, limit=70, n_steps=10)
    for scope in ("individual", "portfolio"):
        args: dict[str, Any] = {
            "payout": payout,
            "objective": pm.WeightedCVaR(alpha=0.9, beta=0.9),
            "basis": "annual",
            "scope": scope,
            "budget": 1.0,
        }
        hand = pm.calibrate(by_hand, impact, years=train_by_hand, **args)
        auto = pm.calibrate(as_is, impact, years=train_as_is, **args)
        for a, b in zip(auto.problems, hand.problems, strict=True):
            assert a.objective_value == pytest.approx(b.objective_value, rel=1e-9)
