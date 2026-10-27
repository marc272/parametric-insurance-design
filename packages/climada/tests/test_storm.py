"""Tests of the STORM track loader and the STORM pipeline path (MAR-32).

CI never downloads STORM. The fixture writes the five storms of the IRIS
fixture (``conftest.py``) as STORM files: the same tracks, with the wind as a
10-minute mean (times 0.88), longitudes in 0 to 360° and the years spread over two
1,000-year files. A STORM build of these files must then give the same index
and losses as the IRIS build, because the two paths differ only in how the
tracks are read.

========  ====  ===  ===============  ===============================
IRIS      file  year STORM event_id   role (see conftest.py)
========  ====  ===  ===============  ===============================
NA_3_0    0     3    STORM_NA_3_0     strong hit
NA_10_1   0     10   STORM_NA_10_1    weaker, north of Miami
NA_8_0    1     8    STORM_NA_1008_0  weak, zero row
NA_7_2    1     7    STORM_NA_1007_2  single point: skipped
NA_5_0    1     5    STORM_NA_1005_0  far away: filtered
========  ====  ===  ===============  ===============================
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest
import yaml
from climada.hazard import TCTracks

from parametric_insurance_design_climada import storm
from parametric_insurance_design_climada.config import (
    PipelineConfigError,
    parse_config,
)
from parametric_insurance_design_climada.pipeline import build_eventset
from parametric_insurance_design_climada.tracks import (
    MS_TO_KT,
    CatalogueFormatError,
    read_iris_catalogue,
)

from .conftest import LOCATIONS, catalogue_text

WHEN = datetime(2026, 10, 27, tzinfo=UTC)
#: IRIS event -> (STORM file index, year in file).
PLACEMENT: dict[str, tuple[int, int]] = {
    "NA_3_0": (0, 3),
    "NA_10_1": (0, 10),
    "NA_8_0": (1, 8),
    "NA_7_2": (1, 7),
    "NA_5_0": (1, 5),
}
#: STORM event -> IRIS event of the same track, in the pipeline's row order
#: (event IDs sorted as strings).
SAME_TRACK: dict[str, str] = {
    "STORM_NA_1008_0": "NA_8_0",
    "STORM_NA_10_1": "NA_10_1",
    "STORM_NA_3_0": "NA_3_0",
}


def storm_line(
    year: int,
    tc: int,
    step: int,
    lat: float,
    lon: float,
    vmax_10min: float,
    pmin: float = 950.0,
    rmw: float = 30.0,
    *,
    month: int = 9,
    basin_id: int = 1,
) -> str:
    """One STORM row in the file's float format."""
    return (
        f"{year:5.1f},{month:5.1f},{tc:5.1f},{step:5.1f},{basin_id:5.1f},"
        f"{lat:.10f},{lon:.10f},{pmin:.6f},{vmax_10min:.12f},{rmw:.6f},"
        f"  0.0,  0.0,123.4\n"
    )


def iris_fixture_as_storm(directory: Path) -> list[Path]:
    """Write the IRIS fixture's storms as two STORM NA files."""
    directory.mkdir(parents=True, exist_ok=True)
    iris_path = directory.parent / "iris_for_storm.txt"
    iris_path.write_text(catalogue_text(), encoding="utf-8")
    iris = read_iris_catalogue(iris_path)
    lines: dict[int, list[str]] = {0: [], 1: []}
    for event_id, rows in iris.groupby("event_id", sort=False):
        index, year = PLACEMENT[str(event_id)]
        for row in rows.to_dict("records"):
            lines[index].append(
                storm_line(
                    year,
                    int(row["tc"]),
                    int(row["timestep"]),
                    float(row["lat"]),
                    float(row["lon"]) + 360.0,
                    float(row["vmax"]) * storm.WIND_10MIN_TO_1MIN,
                    float(row["pmin"]),
                    float(row["rmw"]),
                    month=int(row["month"]),
                )
            )
    paths = []
    for index, text in lines.items():
        path = directory / storm.member_name("NA", index)
        path.write_text("".join(text), encoding="utf-8")
        paths.append(path)
    return paths


@pytest.fixture
def storm_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "storm"
    iris_fixture_as_storm(directory)
    return directory


def _write(directory: Path, name: str, text: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path


def _two_point(year: int, tc: int = 0, **kwargs: Any) -> str:  # noqa: ANN401
    return storm_line(year, tc, 0, 25.0, 280.0, 30.0, **kwargs) + storm_line(
        year, tc, 1, 25.5, 279.5, 31.0, **kwargs
    )


# --------------------------------------------------------------------------
# Loader
# --------------------------------------------------------------------------


def test_years_are_rebuilt_from_the_file_index(storm_dir: Path) -> None:
    loaded = storm.read_storm_catalogue(storm_dir, n_years=2000)
    assert loaded.n_years == 2000
    first = loaded.frame.groupby("event_id")["year"].first()
    assert first.to_dict() == {
        "STORM_NA_3_0": 3,
        "STORM_NA_10_1": 10,
        "STORM_NA_1008_0": 1008,
        "STORM_NA_1007_2": 1007,
        "STORM_NA_1005_0": 1005,
    }
    mapping = loaded.year_mapping()
    assert mapping["n_years"] == 2000
    assert mapping["n_years_with_storms"] == 5
    assert mapping["simulation_year"] == [3, 1008]
    assert [f["index"] for f in mapping["files"]] == [0, 1]
    assert mapping["files"][1]["year_in_file"] == [5, 8]
    assert mapping["files"][1]["simulation_year"] == [1005, 1008]
    assert mapping["files"][0]["n_storms"] == 2
    assert all(len(f["sha256"]) == 64 for f in mapping["files"])
    assert "1000 * file index k + year in file" in mapping["rule"]


def test_wind_is_one_minute_and_longitude_is_signed(storm_dir: Path) -> None:
    iris_path = storm_dir.parent / "iris_for_storm.txt"
    iris = read_iris_catalogue(iris_path).set_index(["event_id", "timestep"])
    frame = storm.read_storm_catalogue(storm_dir).frame
    hit = frame[frame["event_id"] == "STORM_NA_3_0"].set_index("timestep")
    ref = iris.loc["NA_3_0"]
    np.testing.assert_allclose(hit["vmax"], ref["vmax"], rtol=1e-12)
    np.testing.assert_allclose(hit["vmax_10min"], ref["vmax"] * 0.88, rtol=1e-12)
    np.testing.assert_allclose(hit["lon"], ref["lon"], atol=1e-9)
    assert (frame["lon"] <= 180).all()
    assert (frame["basin"] == "NA").all()


def test_other_basins_and_files_are_ignored(storm_dir: Path) -> None:
    _write(storm_dir, storm.member_name("EP", 0), _two_point(1, basin_id=0))
    _write(storm_dir, "README.txt", "not a track file\n")
    assert [p.name for p in storm.storm_member_files(storm_dir)] == [
        storm.member_name("NA", 0),
        storm.member_name("NA", 1),
    ]
    ep = storm.read_storm_catalogue(storm_dir, basin="EP")
    assert ep.frame["event_id"].unique().tolist() == ["STORM_EP_1_0"]


def test_ten_files_cover_ten_thousand_years(tmp_path: Path) -> None:
    for k in range(10):
        _write(tmp_path, storm.member_name("NA", k), _two_point(999 if k == 9 else k))
    loaded = storm.read_storm_catalogue(tmp_path, n_years=10_000)
    years = sorted(loaded.frame["year"].unique().tolist())
    assert years == [1000 * k + k for k in range(9)] + [9999]


@pytest.mark.parametrize(
    ("names", "message"),
    [
        ([0, 2], r"indices are \[0, 2\]"),
        ([1], r"indices are \[1\]"),
    ],
)
def test_missing_file_indices_fail(
    tmp_path: Path, names: list[int], message: str
) -> None:
    for k in names:
        _write(tmp_path, storm.member_name("NA", k), _two_point(0))
    with pytest.raises(CatalogueFormatError, match=message):
        storm.read_storm_catalogue(tmp_path)


def test_a_repeated_file_index_fails(tmp_path: Path) -> None:
    _write(tmp_path, storm.member_name("NA", 0), _two_point(0))
    _write(tmp_path, "STORM_DATA_IBTRACS_NA_1000_YEARS_00.txt", _two_point(0))
    with pytest.raises(CatalogueFormatError, match=r"indices are \[0, 0\]"):
        storm.read_storm_catalogue(tmp_path)


def test_directory_errors(tmp_path: Path) -> None:
    with pytest.raises(CatalogueFormatError, match="not a directory"):
        storm.storm_member_files(tmp_path / "missing")
    with pytest.raises(CatalogueFormatError, match="no STORM file of basin NA"):
        storm.storm_member_files(tmp_path)
    with pytest.raises(CatalogueFormatError, match="unknown STORM basin"):
        storm.storm_member_files(tmp_path, "SA")


def test_n_years_must_match_the_files(storm_dir: Path) -> None:
    with pytest.raises(CatalogueFormatError, match="cover 2000 years"):
        storm.read_storm_catalogue(storm_dir, n_years=10_000)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (_two_point(1000), r"year outside \[0, 1000\)"),
        (_two_point(-1), r"year outside \[0, 1000\)"),
        (_two_point(1, basin_id=0), "basin ID other than 1"),
        (_two_point(1, month=13), "month outside 1-12"),
        (_two_point(1, tc=1000), "TC number of 1000"),
        (storm_line(1, 0, 0, 25, 280, 30) * 2, r"repeated \(year, tc, timestep\)"),
        (
            storm_line(1, 0, 0, 25, 280, 30) + storm_line(1, 0, 2, 25, 280, 30),
            "non-consecutive time steps",
        ),
        (storm_line(1, 0, 0, 25, -80, 30), r"longitude outside \[0, 360\]"),
        (storm_line(1, 0, 0, 95, 280, 30), "latitude outside"),
        (storm_line(1, 0, 0, 25, 280, -1), "negative wind"),
        (storm_line(1, 0, 0, 25, 280, 30, rmw=0.0), "non-positive pressure"),
        (storm_line(1, 0, 0, 25, 280, 30).replace("  1.0,", "  1.5,", 1), "integer"),
        ("1.0,2.0,3.0\n", "3 columns, expected 13"),
        (storm_line(1, 0, 0, 25, 280, 30).replace("123.4", "inf"), "non-finite"),
        ("", "no track points"),
        ("a,b,c,d,e,f,g,h,i,j,k,l,m\n", "cannot parse as STORM"),
    ],
)
def test_malformed_files_fail(tmp_path: Path, text: str, message: str) -> None:
    _write(tmp_path, storm.member_name("NA", 0), text)
    with pytest.raises(CatalogueFormatError, match=message):
        storm.read_storm_catalogue(tmp_path)


def test_storm_to_track_matches_climada_expectations(storm_dir: Path) -> None:
    frame = storm.read_storm_catalogue(storm_dir).frame

    def rows_where(column: str, value: object) -> pd.DataFrame:
        return cast(pd.DataFrame, frame.loc[frame[column] == value])

    rows = rows_where("event_id", "STORM_NA_1008_0")
    track = storm.storm_to_track(cast(pd.DataFrame, rows.iloc[::-1]))
    assert track.attrs["sid"] == "STORM_NA_1008_0"
    assert track.attrs["data_provider"] == "STORM"
    assert track.attrs["id_no"] == 1008 * 1000
    assert "radius_oci" not in track
    np.testing.assert_allclose(
        track["max_sustained_wind"],
        rows["vmax"].to_numpy(dtype=np.float64) * MS_TO_KT,
    )
    assert (np.diff(track["time"].to_numpy()) == np.timedelta64(3, "h")).all()
    TCTracks([track])  # CLIMADA accepts it
    with pytest.raises(CatalogueFormatError, match="needs >= 2"):
        storm.storm_to_track(rows_where("event_id", "STORM_NA_1007_2"))
    with pytest.raises(CatalogueFormatError, match="rows of 2 events"):
        storm.storm_to_track(rows_where("file_index", 0))


def test_storm_to_track_rejects_gaps() -> None:
    rows = pd.DataFrame(
        {
            "event_id": ["E", "E"],
            "timestep": [0, 2],
            "year": [0, 0],
            "tc": [0, 0],
        }
    )
    with pytest.raises(CatalogueFormatError, match="consecutive"):
        storm.storm_to_track(rows)


# --------------------------------------------------------------------------
# Config and pipeline
# --------------------------------------------------------------------------


def _config_data(base: Path, storm_dir: Path, **updates: Any) -> dict[str, Any]:  # noqa: ANN401
    (base / "assets.yaml").write_text(
        yaml.safe_dump({"locations": LOCATIONS}), encoding="utf-8"
    )
    return {
        "catalogue": str(storm_dir),
        "tracks": {"kind": "storm"},
        "n_years": 2000,
        "locations": {"yaml": str(base / "assets.yaml")},
        "batch_size": 2,
        "hazard_release": "synthetic STORM test files",
        "scenario_id": "storm-present-climate",
        "licence": "CC-BY-4.0",
        "output": str(base / "out"),
        **updates,
    }


@pytest.mark.parametrize("key", ["hazard_release", "licence"])
def test_storm_config_needs_release_and_licence(
    tmp_path: Path, storm_dir: Path, key: str
) -> None:
    data = _config_data(tmp_path, storm_dir)
    del data[key]
    with pytest.raises(PipelineConfigError, match=f"STORM tracks need {key}"):
        parse_config(data)


def test_tracks_default_to_iris(make_config: Callable[..., Any]) -> None:
    assert make_config().tracks.kind == "iris"


def test_storm_build_equals_the_iris_build_of_the_same_tracks(
    tmp_path: Path, storm_dir: Path, make_config: Callable[..., Any]
) -> None:
    result = build_eventset(
        parse_config(_config_data(tmp_path, storm_dir)), created_at=WHEN
    )
    es = result.eventset
    assert es.events["event_id"].tolist() == list(SAME_TRACK)
    assert es.events["year"].tolist() == [1008, 10, 3]
    np.testing.assert_array_equal(es.rates, np.full(3, 1 / 2000))
    assert (es.events["scenario_id"] == "storm-present-climate").all()
    assert result.n_storms_catalogue == 5
    assert [s.event_id for s in result.skipped] == ["STORM_NA_1007_2"]

    iris = build_eventset(make_config(), created_at=WHEN).eventset
    rows = [iris.events["event_id"].tolist().index(e) for e in SAME_TRACK.values()]
    np.testing.assert_allclose(es.index, iris.index[rows], rtol=1e-9, atol=1e-9)
    np.testing.assert_allclose(es.loss, iris.loss[rows], rtol=1e-9, atol=1e-6)
    assert es.index.max() > 40


def test_storm_metadata_records_files_year_mapping_and_conversion(
    tmp_path: Path, storm_dir: Path
) -> None:
    es = build_eventset(
        parse_config(_config_data(tmp_path, storm_dir)), created_at=WHEN
    ).eventset
    meta = es.metadata
    assert meta.hazard.name == "STORM"
    assert meta.hazard.release == "synthetic STORM test files"
    assert meta.licence == "CC-BY-4.0"
    assert meta.scenario.startswith("STORM 2,000-year synthetic tropical-cyclone")
    names = [storm.member_name("NA", k) for k in (0, 1)]
    assert set(meta.provenance.source_checksums) == {*names, "assets.yaml"}
    params = meta.transforms[0].parameters
    catalogue = params["catalogue"]
    assert catalogue["format"] == "storm"
    assert catalogue["basin"] == "NA"
    assert catalogue["n_storms"] == 5
    assert [f["file"] for f in catalogue["year_mapping"]["files"]] == names
    assert params["track_conversion"]["vmax_10min_to_1min_divisor"] == 0.88
    assert params["track_conversion"]["environmental_pressure_hpa"] == 1013.0


def test_storm_cat_in_circle_equals_iris(
    tmp_path: Path, storm_dir: Path, make_config: Callable[..., Any]
) -> None:
    index = {"kind": "cat_in_circle", "radius_km": 50}
    es = build_eventset(
        parse_config(_config_data(tmp_path, storm_dir, index=index)),
        created_at=WHEN,
    ).eventset
    iris = build_eventset(make_config(index=index), created_at=WHEN).eventset
    rows = [iris.events["event_id"].tolist().index(e) for e in SAME_TRACK.values()]
    np.testing.assert_array_equal(es.index, iris.index[rows])
    assert es.index.max() >= 3


def test_storm_n_years_mismatch_fails_the_build(
    tmp_path: Path, storm_dir: Path
) -> None:
    config = parse_config(_config_data(tmp_path, storm_dir, n_years=10_000))
    with pytest.raises(CatalogueFormatError, match="cover 2000 years"):
        build_eventset(config)
