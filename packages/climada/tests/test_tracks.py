"""Tests for the IRIS track reader, proximity filter and track conversion."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design_climada import tracks

from .conftest import HEADER, LOCATIONS


def _storm(frame: pd.DataFrame, event_id: str) -> pd.DataFrame:
    return cast(pd.DataFrame, frame.loc[frame["event_id"] == event_id])


def test_read_keeps_na_basin_and_builds_event_ids(catalogue_path: Path) -> None:
    frame = tracks.read_iris_catalogue(catalogue_path)
    assert (frame["basin"] == "NA").all()
    assert frame["event_id"].unique().tolist() == [
        "NA_3_0",
        "NA_5_0",
        "NA_7_2",
        "NA_8_0",
        "NA_10_1",
    ]
    assert frame["year"].dtype == np.int64
    assert frame["vmax"].dtype == np.float64
    assert len(frame) == 13 + 4 + 1 + 6 + 13


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("", "no track points"),
        (
            "1 NA 0 0 9 0 -80.0 25.0 40.0 950.0 30.0 200.0\n"
            "1 NA 0 0 9 1 -80.0 25.0 40.0 950.0 30.0\n",
            "missing",
        ),
        ("1 NA 0 0 9 0 -80.0 25.0 40.0 950.0 30.0\n", "11 columns"),
        (
            "1 NA 0 0 9 0 -80.0 25.0 40.0 950.0 30.0 200.0\n"
            "1 NA 0 0 9 1 -80.0 25.0 40.0 950.0 30.0 200.0 7 8\n",
            "parse",
        ),
        ("1 NA 0 0 9 0 -80.0 25.0 fast 950.0 30.0 200.0\n", "numeric"),
        ("1 NA 0 0 9 0.5 -80.0 25.0 40.0 950.0 30.0 200.0\n", "integer"),
        ("1 NA 0 0 9 0 -80.0 25.0 inf 950.0 30.0 200.0\n", "non-finite"),
        (
            "1 NA 0 0 9 0 -80.0 25.0 40.0 950.0 30.0 200.0\n"
            "2 NA 0 0 9 1 -80.0 25.0 40.0 950.0 30.0 200.0\n",
            "one-to-one",
        ),
        ("1 NA 0 0 9 0 -80.0 25.0 40.0 950.0 30.0 200.0 7 8\n", "14 columns"),
    ],
)
def test_read_rejects_malformed_catalogues(
    tmp_path: Path, body: str, match: str
) -> None:
    path = tmp_path / "bad.txt"
    path.write_text(HEADER + body, encoding="utf-8")
    with pytest.raises(tracks.CatalogueFormatError, match=match):
        tracks.read_iris_catalogue(path)


def test_haversine_matches_one_degree_of_latitude() -> None:
    d = tracks.haversine_km(np.array([0.0, 10.0]), np.array([0.0, 0.0]), 1.0, 0.0)
    expected = 2 * np.pi * tracks.EARTH_RADIUS_KM / 360
    np.testing.assert_allclose(d, [expected, 9 * expected], rtol=1e-12)


def test_storms_near_locations_sorts_ids_as_strings(catalogue_path: Path) -> None:
    frame = tracks.read_iris_catalogue(catalogue_path)
    lats = [row["lat"] for row in LOCATIONS]
    lons = [row["lon"] for row in LOCATIONS]
    near = tracks.storms_near_locations(frame, lats, lons, 500)
    assert near == ["NA_10_1", "NA_3_0", "NA_7_2", "NA_8_0"]
    assert tracks.storms_near_locations(frame, lats, lons, 200) == [
        "NA_10_1",
        "NA_3_0",
        "NA_7_2",
    ]


def test_storms_near_locations_radius_is_inclusive() -> None:
    frame = pd.DataFrame({"event_id": ["A", "B"], "lat": [1.0, 2.0], "lon": [0.0, 0.0]})
    one_degree = float(tracks.haversine_km(np.array([1.0]), np.array([0.0]), 0, 0)[0])
    assert tracks.storms_near_locations(frame, [0.0], [0.0], one_degree) == ["A"]


@pytest.mark.parametrize(
    ("lats", "lons", "radius"),
    [([], [], 1.0), ([1.0], [1.0, 2.0], 1.0), ([1.0], [1.0], 0.0)],
)
def test_storms_near_locations_checks_arguments(
    catalogue_path: Path, lats: list[float], lons: list[float], radius: float
) -> None:
    frame = tracks.read_iris_catalogue(catalogue_path)
    with pytest.raises(ValueError, match=r"radius|lats"):
        tracks.storms_near_locations(frame, lats, lons, radius)


def test_storm_to_track_converts_units_and_time(catalogue_path: Path) -> None:
    frame = tracks.read_iris_catalogue(catalogue_path)
    storm = _storm(frame, "NA_3_0").iloc[::-1]  # order must not matter
    track = tracks.storm_to_track(storm)
    ordered = storm.sort_values("timestep")
    np.testing.assert_allclose(
        track["max_sustained_wind"].to_numpy(), ordered["vmax"] * tracks.MS_TO_KT
    )
    np.testing.assert_allclose(
        track["radius_max_wind"].to_numpy(), ordered["rmw"] * tracks.KM_TO_NM
    )
    np.testing.assert_allclose(
        track["radius_oci"].to_numpy(), ordered["r18"] * tracks.KM_TO_NM
    )
    np.testing.assert_array_equal(track["lon"].to_numpy(), ordered["lon"])
    steps = np.diff(track["time"].to_numpy()).astype("timedelta64[h]").astype(int)
    assert (steps == tracks.TIMESTEP_HOURS).all()
    assert track["time"].to_numpy()[0] == tracks.TRACK_REF_TIME
    assert (track["environmental_pressure"] == tracks.ENV_PRESSURE_HPA).all()
    assert track.attrs["sid"] == "NA_3_0"
    assert track.attrs["id_no"] == 30
    assert track.attrs["max_sustained_wind_unit"] == "kn"


def test_storm_to_track_rejects_bad_storms(catalogue_path: Path) -> None:
    frame = tracks.read_iris_catalogue(catalogue_path)
    with pytest.raises(tracks.CatalogueFormatError, match="events"):
        tracks.storm_to_track(frame)
    with pytest.raises(tracks.CatalogueFormatError, match="needs >= 2"):
        tracks.storm_to_track(_storm(frame, "NA_7_2"))
    gap = _storm(frame, "NA_3_0").iloc[[0, 1, 3, 4]]
    with pytest.raises(tracks.CatalogueFormatError, match="consecutive"):
        tracks.storm_to_track(gap)
