"""Tests of the index builders, on small synthetic CLIMADA objects.

Track ``A`` runs along latitude 25.75 from 77 to 83 W, 0.5 degrees (about
50 km) between points, at 120.5 kn (category 4); ``B`` along 26.9 N at
73.9 kn (category 1), 105.6 km from the third point and about 125 km from
the others; ``C`` along 29.5 N at 37 kn (category 0). The first point lies
1.3 km, the second 4.5 km and the third 22.2 km from A's path.
"""

from __future__ import annotations

import unittest

import numpy as np
from climada.hazard import TCTracks

from petals_parametric import (
    SAFFIR_SIMPSON_KN,
    ParametricIndex,
    ParametricInputError,
    split_years,
)
from petals_parametric.calibrate import loss_matrix
from petals_parametric.index import category_of, densify_track
from petals_parametric.test._synthetic import (
    array_index,
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
