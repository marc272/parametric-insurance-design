"""Tests of the index builders, on small synthetic CLIMADA objects.

Track ``A`` runs along latitude 25.75 from 77 to 83 W, 0.5 degrees (about
50 km) between points, at 120.5 kn (category 4); ``B`` along 26.9 N at
73.9 kn (category 1), 105.6 km from the third point and about 125 km from
the others; ``C`` along 29.5 N at 37 kn (category 0). The first point lies
1.3 km, the second 4.5 km and the third 22.2 km from A's path.

The simulation-year tests use a 10,000-year catalogue in the IRIS layout
(:data:`STORMS`): storms named ``NA_<year>_<number>`` in years 0 to 9,999,
frequency 1 / 10,000, and dates that carry year ``y`` as 1 January of
``y + 1``, so that no date holds year 9,999.
"""

from __future__ import annotations

import datetime as dt
import unittest
from typing import Any

import numpy as np
from climada.hazard import TCTracks

from petals_parametric import (
    SAFFIR_SIMPSON_KN,
    ExpectedUncovered,
    ParametricIndex,
    ParametricInputError,
    StepPayout,
    basis_risk,
    calibrate,
    split_years,
)
from petals_parametric.calibrate import loss_matrix
from petals_parametric.index import category_of, densify_track
from petals_parametric.test._synthetic import (
    array_index,
    catalogue_tracks,
    exposures,
    hazard_and_impact,
    straight_track,
)


def _tracks() -> TCTracks:
    return TCTracks(
        [
            straight_track("A", 25.75, -77.0, -83.0, 120.5, year=2001),
            straight_track("B", 26.9, -77.0, -83.0, 73.9, year=2003),
            straight_track("C", 29.5, -78.0, -81.0, 37.0, n_points=6, year=2003),
        ]
    )


class TestCatInCircleHelpers(unittest.TestCase):
    """Categories and track interpolation."""

    def test_category_counts_the_breakpoints_reached(self) -> None:
        wind = np.array([0.0, 63.99, 64.0, 82.9, 83.0, 96.0, 113.0, 137.0, 500.0])
        np.testing.assert_array_equal(
            category_of(wind, SAFFIR_SIMPSON_KN), [0, 0, 1, 1, 2, 3, 4, 5, 5]
        )

    def test_densify_keeps_the_points(self) -> None:
        lat = np.array([20.0, 21.0, 23.0])
        lon = np.array([-70.0, -71.0, -71.0])
        wind = np.array([60.0, 90.0, 30.0])
        out = densify_track(lat, lon, wind, np.array([0.0, 3.0, 6.0]), 0.5)
        self.assertEqual(len(out[0]), 13)
        np.testing.assert_array_equal(out[0][[0, 6, 12]], lat)
        np.testing.assert_allclose(out[2][6:], np.linspace(90, 30, 7), atol=1e-12)


class TestFromClimada(unittest.TestCase):
    """Both builders on a TropCyclone hazard and its tracks."""

    def setUp(self) -> None:
        self.tracks = _tracks()
        self.exposures = exposures()
        self.hazard, self.impact = hazard_and_impact(self.tracks, self.exposures)

    def test_centroid_intensity(self) -> None:
        index = ParametricIndex.from_hazard(self.hazard, self.exposures)
        np.testing.assert_array_equal(index.values, self.hazard.intensity.toarray())
        self.assertEqual(index.unit, "m/s")
        self.assertEqual(index.event_name, ("A", "B", "C"))
        self.assertNotIn("centr_TC", self.exposures.gdf.columns)
        # Three years, 2001 to 2003, from the dates and frequency 1 / 3.
        np.testing.assert_array_equal(index.years, [2001, 2002, 2003])
        np.testing.assert_array_equal(index.event_year, [2001, 2003, 2003])
        np.testing.assert_array_equal(
            loss_matrix(index, self.impact), self.impact.imp_mat.toarray()
        )

    def test_cat_in_circle_by_radius(self) -> None:
        expected = {
            30.0: [[4, 4, 4], [0, 0, 0], [0, 0, 0]],
            110.0: [[4, 4, 4], [0, 0, 1], [0, 0, 0]],
            150.0: [[4, 4, 4], [1, 1, 1], [0, 0, 0]],
        }
        for radius, values in expected.items():
            index = ParametricIndex.from_cat_in_circle(
                self.tracks, self.exposures, hazard=self.hazard, radius_km=radius
            )
            with self.subTest(radius=radius):
                np.testing.assert_array_equal(index.values, values)
                self.assertEqual(index.unit, "Saffir-Simpson category")

    def test_interpolation_catches_a_storm_between_track_points(self) -> None:
        raw = ParametricIndex.from_cat_in_circle(
            self.tracks,
            self.exposures,
            hazard=self.hazard,
            radius_km=10.0,
            track_step_hours=None,
        )
        fine = ParametricIndex.from_cat_in_circle(
            self.tracks, self.exposures, hazard=self.hazard, radius_km=10.0
        )
        np.testing.assert_array_equal(raw.values, np.zeros((3, 3)))
        np.testing.assert_array_equal(fine.values[0], [4, 4, 0])

    def test_max_wind_metric_is_in_metres_per_second(self) -> None:
        index = ParametricIndex.from_cat_in_circle(
            self.tracks,
            self.exposures,
            hazard=self.hazard,
            radius_km=30.0,
            metric="max_wind",
        )
        np.testing.assert_allclose(index.values[0], 120.5 / 1.9438444924406)
        self.assertEqual(index.unit, "m/s")

    def test_events_need_their_track(self) -> None:
        with self.assertRaisesRegex(ParametricInputError, "no track"):
            ParametricIndex.from_cat_in_circle(
                TCTracks(self.tracks.data[:2]),
                self.exposures,
                hazard=self.hazard,
                radius_km=30.0,
            )
        knots = self.tracks.data[0].copy()
        knots.attrs["max_sustained_wind_unit"] = "m/s"
        with self.assertRaisesRegex(ParametricInputError, "kn"):
            ParametricIndex.from_cat_in_circle(
                TCTracks([knots, *self.tracks.data[1:]]),
                self.exposures,
                hazard=self.hazard,
                radius_km=30.0,
            )

    def test_an_impact_of_other_events_is_refused(self) -> None:
        index = ParametricIndex.from_hazard(self.hazard, self.exposures)
        _, other = hazard_and_impact(TCTracks(self.tracks.data[:2]), self.exposures)
        with self.assertRaises(ParametricInputError):
            loss_matrix(index, other)
        no_matrix = self.impact.__class__(
            event_id=self.impact.event_id,
            event_name=self.impact.event_name,
            date=self.impact.date,
            frequency=self.impact.frequency,
            coord_exp=self.impact.coord_exp,
            eai_exp=self.impact.eai_exp,
            at_event=self.impact.at_event,
        )
        with self.assertRaisesRegex(ParametricInputError, "save_mat"):
            loss_matrix(index, no_matrix)


#: A 10,000-year catalogue with storms in its first and last year.
N_CATALOGUE = 10_000
STORMS: tuple[tuple[int, int, float, float], ...] = (
    (0, 0, 25.75, 120.5),
    (2500, 0, 25.8, 100.0),
    (5000, 0, 25.9, 110.0),
    (6999, 0, 25.76, 90.0),
    (7000, 0, 25.8, 115.0),
    (9999, 0, 25.85, 120.0),
    (9999, 1, 26.0, 95.0),
)


def _year_dates(years: list[int]) -> list[int]:
    """Date year ``y`` on 1 January of ``y + 1``; 0 (no date) above 9998.

    A date holds the calendar years 1 to 9999, so a hazard dated this way
    cannot date the last year of a 10,000-year catalogue.
    """
    return [dt.date(y + 1, 1, 1).toordinal() if y < dt.MAXYEAR else 0 for y in years]


class TestSimulationYears(unittest.TestCase):
    """Years from the dates, the event names, or n_years and first_year."""

    def setUp(self) -> None:
        self.exposures = exposures()
        self.tracks = catalogue_tracks(STORMS)
        self.years = [year for year, *_ in STORMS]
        self.hazard, self.impact = hazard_and_impact(
            self.tracks,
            self.exposures,
            frequency=1 / N_CATALOGUE,
            date=_year_dates(self.years),
        )

    def test_a_10000_year_catalogue_calibrates_from_its_event_names(self) -> None:
        # The last year has no date, so the default route refuses the hazard.
        with self.assertRaisesRegex(ParametricInputError, "pass event_year"):
            ParametricIndex.from_hazard(self.hazard, self.exposures)
        index = ParametricIndex.from_hazard(
            self.hazard, self.exposures, event_year="event_name"
        )
        np.testing.assert_array_equal(index.event_year, self.years)
        np.testing.assert_array_equal(index.years, np.arange(N_CATALOGUE))
        stated = ParametricIndex.from_hazard(
            self.hazard,
            self.exposures,
            event_year="event_name",
            n_years=N_CATALOGUE,
            first_year=0,
        )
        np.testing.assert_array_equal(stated.years, index.years)
        circle = ParametricIndex.from_cat_in_circle(
            self.tracks,
            self.exposures,
            hazard=self.hazard,
            radius_km=50.0,
            event_year="event_name",
            first_year=0,
        )
        np.testing.assert_array_equal(circle.event_year, self.years)
        np.testing.assert_array_equal(circle.years, index.years)
        train, test = split_years(index, train_fraction=0.7)
        np.testing.assert_array_equal(train, np.arange(7000))
        np.testing.assert_array_equal(test, np.arange(7000, N_CATALOGUE))
        np.testing.assert_array_equal(index.event_mask(test), [False] * 4 + [True] * 3)
        payout = StepPayout(attachment=20, limit=70, n_steps=5)
        for scope in ("individual", "portfolio"):
            cover = calibrate(
                index,
                self.impact,
                payout=payout,
                objective=ExpectedUncovered(),
                basis="annual",
                scope=scope,
                budget=1.0,
                years=train,
            )
            with self.subTest(scope=scope):
                np.testing.assert_array_equal(cover.calibration_years, train)
                self.assertGreater(cover.premium, 0.0)
                metrics = basis_risk(index, self.impact, cover, beta=0.99, years=test)
                self.assertEqual(len(metrics), self.exposures.gdf.shape[0] + 1)

    def test_the_span_is_stated_not_taken_from_the_first_event(self) -> None:
        storms = [s for s in STORMS if s[0] != 0]  # no storm in year 0
        tracks = catalogue_tracks(storms)
        hazard, _ = hazard_and_impact(tracks, self.exposures, frequency=1 / N_CATALOGUE)
        # The years 2500-9999 are 7,500 of 10,000: where the rest lie is unknown.
        with self.assertRaisesRegex(ParametricInputError, "Pass first_year"):
            ParametricIndex.from_hazard(hazard, self.exposures, event_year="event_name")
        index = ParametricIndex.from_hazard(
            hazard, self.exposures, event_year="event_name", first_year=0
        )
        np.testing.assert_array_equal(index.years, np.arange(N_CATALOGUE))
        train, _ = split_years(index, train_fraction=0.7)
        np.testing.assert_array_equal(train, np.arange(7000))
        # Every track starts on one date: the dates give one year, not 10,000.
        with self.assertRaisesRegex(ParametricInputError, "run from 2000 to 2000"):
            ParametricIndex.from_hazard(hazard, self.exposures)

    def test_the_date_route_is_the_default(self) -> None:
        tracks = _tracks()
        hazard, _ = hazard_and_impact(tracks, self.exposures)
        default = ParametricIndex.from_hazard(hazard, self.exposures)
        dated = ParametricIndex.from_hazard(hazard, self.exposures, event_year="date")
        np.testing.assert_array_equal(dated.event_year, [2001, 2003, 2003])
        np.testing.assert_array_equal(dated.years, default.years)
        stated = ParametricIndex.from_hazard(
            hazard, self.exposures, n_years=5, first_year=2000
        )
        np.testing.assert_array_equal(stated.years, np.arange(2000, 2005))

    def test_n_years_and_first_year_with_explicit_event_years(self) -> None:
        # An ensemble of two members per storm of a 3-year catalogue: member
        # m of year y has the year y + 3 m.
        hazard, _ = hazard_and_impact(_tracks(), self.exposures)
        index = ParametricIndex.from_hazard(
            hazard, self.exposures, event_year=[0, 2, 5], n_years=6, first_year=0
        )
        np.testing.assert_array_equal(index.years, np.arange(6))
        np.testing.assert_array_equal(index.event_year, [0, 2, 5])
        # n_years does not need the frequencies to agree on N.
        hazard.frequency = np.array([0.1, 0.2, 0.3])
        index = ParametricIndex.from_hazard(
            hazard, self.exposures, event_year=[0, 2, 5], n_years=6, first_year=0
        )
        np.testing.assert_array_equal(index.years, np.arange(6))

    def test_ambiguous_or_invalid_years_raise(self) -> None:
        hazard, exp = self.hazard, self.exposures
        cases: list[tuple[dict[str, Any], str]] = [
            ({"years": np.arange(N_CATALOGUE), "n_years": N_CATALOGUE}, "not both"),
            ({"years": np.arange(N_CATALOGUE), "first_year": 0}, "not both"),
            ({"event_year": "calendar"}, "'date', 'event_name'"),
            ({"event_year": "event_name", "n_years": 0}, "n_years must be >= 1"),
            ({"event_year": "event_name", "n_years": 2.5}, "n_years must be an int"),
            ({"event_year": "event_name", "n_years": True}, "n_years must be an int"),
            ({"event_year": "event_name", "first_year": "0"}, "first_year must be"),
            ({"event_year": "event_name", "first_year": 1}, "outside the 10000"),
            ({"event_year": "event_name", "n_years": 5000}, "more than the 5000"),
        ]
        for kwargs, match in cases:
            with (
                self.subTest(kwargs=kwargs),
                self.assertRaisesRegex(ParametricInputError, match),
            ):
                ParametricIndex.from_hazard(hazard, exp, **kwargs)
        uneven = hazard.select(event_names=list(hazard.event_name))
        uneven.frequency = np.linspace(1e-4, 2e-4, uneven.size)
        with self.assertRaisesRegex(ParametricInputError, "pass n_years or years"):
            ParametricIndex.from_hazard(uneven, exp, event_year="event_name")

    def test_event_names_without_a_year_raise(self) -> None:
        for names in (["A", "B", "C"], ["NA_5_0_gen1", "NA_5_0", "NA_x_0"]):
            tracks = catalogue_tracks(STORMS[:3])
            for track, name in zip(tracks.data, names, strict=True):
                track.attrs["sid"] = track.attrs["name"] = name
            hazard, _ = hazard_and_impact(tracks, self.exposures)
            with (
                self.subTest(names=names),
                self.assertRaisesRegex(
                    ParametricInputError, "<prefix>_<year>_<number>"
                ),
            ):
                ParametricIndex.from_hazard(
                    hazard, self.exposures, event_year="event_name"
                )


class TestParametricIndex(unittest.TestCase):
    """Validation and year splits."""

    def test_split_years_is_two_contiguous_blocks(self) -> None:
        index, _ = array_index(np.zeros((3, 1)), np.zeros((3, 1)), [0, 4, 9], 10)
        train, test = split_years(index, train_fraction=0.7)
        np.testing.assert_array_equal(train, np.arange(7))
        np.testing.assert_array_equal(test, [7, 8, 9])
        np.testing.assert_array_equal(index.event_mask(test), [False, False, True])
        with self.assertRaises(ParametricInputError):
            split_years(index, train_fraction=0.01)

    def test_invalid_arrays_raise(self) -> None:
        with self.assertRaisesRegex(ParametricInputError, "event years outside"):
            array_index(np.zeros((2, 1)), np.zeros((2, 1)), [0, 10], 10)
        with self.assertRaisesRegex(ParametricInputError, "finite"):
            array_index(np.full((2, 1), np.nan), np.zeros((2, 1)), [0, 1], 10)
        index, _ = array_index(np.zeros((2, 1)), np.zeros((2, 1)), [0, 1], 10)
        with self.assertRaises(ParametricInputError):
            index.check_years([3, 3])
        with self.assertRaises(ParametricInputError):
            index.check_years([42])


if __name__ == "__main__":
    unittest.main()
