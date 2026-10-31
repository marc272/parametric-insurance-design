"""Tests for the LitPop-to-county aggregation (MAR-113).

CI never downloads LitPop or TIGER/Line. The aggregation is tested on a small
synthetic grid of square units; the readers and the Florida build on a tiny
CLIMADA HDF5 file and a tiny shapefile zip written in ``tmp_path`` and served
through an injected opener.

Synthetic layout (degrees, lon x lat)::

    lat 2 +-------+
          |   C   |            C: unit "C" (not a target)
    lat 1 +-------+-------+
          |   A   |   B   |    A, B: target units "A", "B"
    lat 0 +-------+-------+
        lon 0   lon 1   lon 2
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import replace
from pathlib import Path
from typing import IO, Any

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import shapely

from parametric_insurance_design_climada import iris
from parametric_insurance_design_climada import portfolio_litpop as pl
from parametric_insurance_design_climada.config import LocationsConfig
from parametric_insurance_design_climada.pipeline import read_locations

D2_NOTE = Path(__file__).parents[3] / "research" / "notes" / "d2-paper-portfolio.md"


def _units() -> gpd.GeoDataFrame:
    return gpd.GeoDataFrame(
        {"unit_id": ["A", "B", "C"], "name": ["Alpha", "Beta", "Gamma"]},
        geometry=[
            shapely.box(0, 0, 1, 1),
            shapely.box(1, 0, 2, 1),
            shapely.box(0, 1, 1, 2),
        ],
        crs=pl.CRS,
    )


def _cells(rows: list[tuple[float, float, float]]) -> pd.DataFrame:
    """Cells from (lon, lat, value) tuples."""
    return pd.DataFrame(
        {
            "lon": [r[0] for r in rows],
            "lat": [r[1] for r in rows],
            "value": [r[2] for r in rows],
        }
    )


BASE = [
    (0.25, 0.25, 1.0),  # A
    (0.75, 0.75, 3.0),  # A
    (1.5, 0.5, 2.0),  # B
    (1.25, 0.25, 0.0),  # B, zero value
    (0.5, 1.5, 7.0),  # C (other unit)
]


# --- aggregation ------------------------------------------------------------


def test_sums_and_value_weighted_centroids() -> None:
    agg = pl.aggregate_cells(_cells(BASE), _units(), target=["B", "A"])
    loc = agg.locations.set_index("location_id")
    assert list(agg.locations["location_id"]) == ["A", "B"]  # sorted
    assert loc.loc["A", "value"] == pytest.approx(4.0)
    assert loc.loc["B", "value"] == pytest.approx(2.0)
    # A: (1*0.25 + 3*0.75) / 4 in both axes.
    assert loc.loc["A", "lon"] == pytest.approx(0.625)
    assert loc.loc["A", "lat"] == pytest.approx(0.625)
    # B: the zero-value cell has no weight.
    assert (loc.loc["B", "lon"], loc.loc["B", "lat"]) == pytest.approx((1.5, 0.5))
    assert loc.loc["A", "name"] == "Alpha"
    assert loc.loc["B", "n_cells"] == 2
    assert loc.loc["B", "n_cells_positive"] == 1
    assert bool(loc["centroid_in_unit"].all())
    assert set(agg.locations.columns) >= {"location_id", "lat", "lon", "value", "name"}


def test_report_accounts_for_every_cell() -> None:
    rows = [
        *BASE,
        (-0.25, 0.5, 5.0),  # in the region (margin), in no unit
        (2.25, 0.5, 0.0),  # in the region, in no unit, zero value
        (10.0, 10.0, 11.0),  # outside the region
    ]
    agg = pl.aggregate_cells(_cells(rows), _units(), target=["A", "B"], margin_deg=0.5)
    r = agg.report
    assert r.n_cells == 8
    assert (r.n_in_target, r.value_in_target) == (4, pytest.approx(6.0))
    assert (r.n_in_other_units, r.value_in_other_units) == (1, pytest.approx(7.0))
    assert (r.n_unassigned, r.value_unassigned) == (2, pytest.approx(5.0))
    assert r.n_unassigned_positive == 1
    assert (r.n_outside_region, r.value_outside_region) == (1, pytest.approx(11.0))
    assert (
        r.n_in_target + r.n_in_other_units + r.n_unassigned + r.n_outside_region
        == r.n_cells
    )
    total = r.value_in_target + r.value_in_other_units + r.value_unassigned
    assert total + r.value_outside_region == pytest.approx(r.value_total)
    assert r.region_bounds == (-0.5, -0.5, 2.5, 1.5)
    assert r.n_target_units == 2
    # The cells table holds every region cell, with its unit (None if none).
    cells = agg.cells
    assert len(cells) == 7
    unassigned = cells[cells["unit_id"].isna()]
    assert sorted(unassigned["cell"]) == [5, 6]
    assert cells.loc[cells["unit_id"] == "C", "location_id"].isna().all()


def test_unassigned_positive_cells_raise_when_asked() -> None:
    rows = [*BASE, (-0.25, 0.5, 5.0)]
    with pytest.raises(pl.UnassignedCellsError, match="1 region cells"):
        pl.aggregate_cells(_cells(rows), _units(), target=["A", "B"], outside="raise")


def test_unassigned_zero_value_cells_do_not_raise() -> None:
    rows = [*BASE, (-0.25, 0.5, 0.0)]
    agg = pl.aggregate_cells(_cells(rows), _units(), target=["A", "B"], outside="raise")
    assert agg.report.n_unassigned == 1


def test_empty_target_unit_raises_typed_error() -> None:
    rows = [r for r in BASE if not (1 <= r[0] <= 2 and r[1] < 1)]  # B has no cell
    with pytest.raises(pl.EmptyUnitError, match=r"\['B'\]"):
        pl.aggregate_cells(_cells(rows), _units(), target=["A", "B"])


def test_zero_value_target_unit_raises_typed_error() -> None:
    rows = [(*r[:2], 0.0) if r[0] > 1 else r for r in BASE]
    with pytest.raises(pl.ZeroValueUnitError, match=r"\['B'\]"):
        pl.aggregate_cells(_cells(rows), _units(), target=["A", "B"])


def test_cell_on_a_shared_edge_goes_to_the_smallest_id_and_is_counted() -> None:
    rows = [*BASE, (1.0, 0.5, 4.0)]
    agg = pl.aggregate_cells(_cells(rows), _units(), target=["A", "B"])
    assert agg.report.n_on_shared_edge == 1
    loc = agg.locations.set_index("location_id")
    assert loc.loc["A", "value"] == pytest.approx(8.0)
    assert loc.loc["B", "value"] == pytest.approx(2.0)
    assert agg.report.n_in_target == 5


def test_default_target_is_every_unit() -> None:
    agg = pl.aggregate_cells(_cells(BASE), _units())
    assert list(agg.locations["location_id"]) == ["A", "B", "C"]
    assert agg.report.n_in_other_units == 0


def test_centroid_outside_a_two_part_unit_is_flagged() -> None:
    units = gpd.GeoDataFrame(
        {"unit_id": ["K"], "name": ["Keys"]},
        geometry=[
            shapely.MultiPolygon([shapely.box(0, 0, 1, 1), shapely.box(3, 0, 4, 1)])
        ],
        crs=pl.CRS,
    )
    agg = pl.aggregate_cells(_cells([(0.5, 0.5, 1.0), (3.5, 0.5, 1.0)]), units)
    row = agg.locations.iloc[0]
    assert (row["lon"], row["lat"]) == pytest.approx((2.0, 0.5))
    assert not row["centroid_in_unit"]


@pytest.mark.parametrize(
    ("cells", "units", "kwargs", "match"),
    [
        (_cells(BASE).drop(columns="value"), _units(), {}, "lack columns"),
        (_cells([(0.5, 0.5, -1.0)]), _units(), {}, ">= 0"),
        (_cells([(0.5, np.nan, 1.0)]), _units(), {}, "finite"),
        (_cells(BASE), _units().to_crs("EPSG:3857"), {}, "EPSG:4326"),
        (_cells(BASE), _units().assign(unit_id="A"), {}, "repeat"),
        (_cells(BASE), _units().drop(columns="name"), {}, "lack columns"),
        (_cells(BASE), _units(), {"target": ["Z"]}, "not in the boundaries"),
        (_cells(BASE), _units(), {"target": []}, "no target"),
        (_cells(BASE), _units(), {"margin_deg": -1.0}, "margin_deg"),
        (_cells(BASE), _units(), {"outside": "drop"}, "outside"),
        (_cells(BASE).set_index(pd.Index([0, 0, 1, 2, 3])), _units(), {}, "unique"),
    ],
)
def test_bad_inputs_raise(
    cells: pd.DataFrame, units: gpd.GeoDataFrame, kwargs: dict[str, Any], match: str
) -> None:
    with pytest.raises(pl.PortfolioInputError, match=match):
        pl.aggregate_cells(cells, units, **kwargs)


def test_empty_geometry_raises() -> None:
    units = _units()
    units.loc[2, "geometry"] = shapely.Polygon()
    with pytest.raises(pl.PortfolioInputError, match="non-empty geometry"):
        pl.aggregate_cells(_cells(BASE), units)


# --- manifest ---------------------------------------------------------------


def test_shipped_manifest_pins_the_litpop_file_of_the_d2_note() -> None:
    manifest = pl.load_manifest()
    note = D2_NOTE.read_text(encoding="utf-8")
    assert manifest.litpop_info["uuid"] == "678e9551-32ca-40f3-9881-9bd38412c1cd"
    assert manifest.litpop_info["uuid"] in note
    assert f"md5:{manifest.litpop.md5}" in note
    assert f"{manifest.litpop.size:,}" in note
    assert manifest.litpop_info["dataset"] == "LitPop_150arcsec_USA"
    assert manifest.litpop_info["version"] == "v3"
    assert manifest.litpop.url.endswith(manifest.litpop.name)
    assert manifest.litpop_info["uuid"] in manifest.litpop.url
    assert manifest.boundaries.url.startswith("https://www2.census.gov/")
    assert manifest.boundaries_info["member"].endswith(".shp")
    assert (manifest.state_fips, manifest.expected_units) == ("12", 67)
    assert manifest.licence == "CC-BY-4.0"
    for remote in (manifest.litpop, manifest.boundaries):
        assert len(remote.sha256) == 64
        assert len(remote.md5) == 32


def test_manifest_missing_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "m.json"
    path.write_text(json.dumps({"portfolio": "x"}), encoding="utf-8")
    with pytest.raises(pl.PortfolioInputError, match="missing the key"):
        pl.load_manifest(path)


# --- readers and the Florida build on tiny files ----------------------------


class FakeHost:
    """Serves bytes by URL and counts requests."""

    def __init__(self, content: dict[str, bytes]) -> None:
        self.content = content
        self.calls: list[str] = []

    def __call__(self, url: str) -> AbstractContextManager[IO[bytes]]:
        self.calls.append(url)
        return io.BytesIO(self.content[url])


def _write_litpop(path: Path, cells: pd.DataFrame) -> bytes:
    from climada.entity import Exposures

    exposures = Exposures(
        data=pd.DataFrame(
            {
                "latitude": cells["lat"],
                "longitude": cells["lon"],
                "value": cells["value"],
            }
        ),
        ref_year=2018,
        value_unit="USD",
        description="synthetic LitPop",
    )
    exposures.write_hdf5(str(path))
    return path.read_bytes()


def _write_counties(directory: Path) -> bytes:
    """A TIGER-like zip: A and B in state 99, C in state 98, in NAD83."""
    units = _units()
    gdf = gpd.GeoDataFrame(
        {
            "GEOID": ["99001", "99003", "98001"],
            "NAME": units["name"],
            "STATEFP": ["99", "99", "98"],
        },
        geometry=units.geometry,
        crs=pl.CRS,
    ).to_crs("EPSG:4269")
    shp_dir = directory / "shp"
    shp_dir.mkdir()
    gdf.to_file(shp_dir / "tl_test_county.shp")
    zip_path = directory / "tl_test_county.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for part in sorted(shp_dir.iterdir()):
            zf.write(part, part.name)
    return zip_path.read_bytes()


def _remote(name: str, data: bytes, url: str) -> dict[str, Any]:
    return {
        "name": name,
        "url": url,
        "size": len(data),
        "md5": hashlib.md5(data, usedforsecurity=False).hexdigest(),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


Mini = tuple[pl.PortfolioManifest, FakeHost, Path]


@pytest.fixture
def mini(tmp_path: Path) -> Mini:
    src = tmp_path / "src"
    src.mkdir()
    litpop = _write_litpop(src / "LitPop_test.hdf5", _cells(BASE))
    counties = _write_counties(src)
    raw = {
        "portfolio": "test portfolio",
        "licence": "CC-BY-4.0",
        "attribution": "test attribution",
        "litpop": {
            **_remote("LitPop_test.hdf5", litpop, "https://example.test/litpop"),
            "dataset": "LitPop_test",
            "version": "v0",
            "uuid": "0000",
            "record": "https://example.test/record",
            "licence": "CC-BY-4.0",
        },
        "boundaries": {
            **_remote("tl_test_county.zip", counties, "https://example.test/tl"),
            "dataset": "test counties",
            "version": "test",
            "record": "https://example.test/meta",
            "licence": "test",
            "member": "tl_test_county.shp",
        },
        "state_fips": "99",
        "expected_units": 2,
        "region_margin_deg": 0.5,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    host = FakeHost(
        {"https://example.test/litpop": litpop, "https://example.test/tl": counties}
    )
    return pl.load_manifest(path), host, tmp_path / "data"


def test_prepare_inputs_downloads_verifies_and_is_idempotent(mini: Mini) -> None:
    manifest, host, data_dir = mini
    first = pl.prepare_inputs(data_dir, manifest=manifest, opener=host)
    assert set(first.actions.values()) == {"created"}
    second = pl.prepare_inputs(data_dir, manifest=manifest, opener=host)
    assert set(second.actions.values()) == {"verified"}
    assert len(host.calls) == 2
    assert first.litpop == data_dir / "raw" / "LitPop_test.hdf5"


def test_prepare_inputs_rejects_a_changed_file(mini: Mini) -> None:
    manifest, host, data_dir = mini
    host.content["https://example.test/litpop"] += b"x"
    with pytest.raises(iris.ChecksumMismatchError):
        pl.prepare_inputs(data_dir, manifest=manifest, opener=host)
    assert not (data_dir / "raw" / "LitPop_test.hdf5").exists()


def test_readers(mini: Mini) -> None:
    manifest, host, data_dir = mini
    paths = pl.prepare_inputs(data_dir, manifest=manifest, opener=host)
    cells, meta = pl.read_litpop_cells(paths.litpop)
    assert cells[["lon", "lat", "value"]].to_numpy() == pytest.approx(np.array(BASE))
    assert meta["ref_year"] == 2018
    assert meta["value_unit"] == "USD"
    units = pl.read_county_boundaries(paths.boundaries, "tl_test_county.shp")
    assert units.crs is not None
    assert units.crs.to_epsg() == 4326
    assert list(units["unit_id"]) == ["99001", "99003", "98001"]
    assert list(units["state_fips"]) == ["99", "99", "98"]


def test_build_writes_a_pipeline_readable_table_with_provenance(mini: Mini) -> None:
    manifest, host, data_dir = mini
    build = pl.build_florida_locations(data_dir, manifest=manifest, opener=host)
    frame = read_locations(LocationsConfig(yaml=build.locations_yaml))
    assert list(frame["location_id"]) == ["99001", "99003"]
    assert frame["value"].tolist() == pytest.approx([4.0, 2.0])
    assert frame.loc[0, "lat"] == pytest.approx(0.625, abs=1e-6)
    assert frame["name"].tolist() == ["Alpha", "Beta"]
    assert build.locations_yaml.read_text("utf-8").startswith("# test portfolio\n")

    prov = json.loads(build.provenance_json.read_text("utf-8"))
    assert prov["licence"] == "CC-BY-4.0"
    assert prov["sources"]["litpop"]["sha256"] == manifest.litpop.sha256
    assert prov["sources"]["boundaries"]["md5"] == manifest.boundaries.md5
    assert prov["litpop_file_metadata"]["value_unit"] == "USD"
    assert prov["report"]["n_in_other_units"] == 1
    assert prov["value_summary"]["max_share"] == pytest.approx(4 / 6)
    assert prov["value_summary"]["effective_n"] == pytest.approx(1 / (4 / 9 + 1 / 9))
    for name in (pl.LOCATIONS_YAML, pl.CELLS_PARQUET):
        path = build.locations_yaml.parent / name
        assert prov["outputs"][name]["sha256"] == iris.file_digests(path)[1]
    cells = pd.read_parquet(build.cells_parquet)
    assert len(cells) == len(BASE)

    with pytest.raises(pl.PortfolioError, match="outputs exist"):
        pl.build_florida_locations(data_dir, manifest=manifest, opener=host)
    again = pl.build_florida_locations(
        data_dir, manifest=manifest, opener=host, overwrite=True
    )
    # Same inputs give the same table, byte for byte.
    assert again.provenance["outputs"] == prov["outputs"]


def test_build_checks_the_unit_count(mini: Mini) -> None:
    manifest, host, data_dir = mini
    wrong = replace(manifest, expected_units=67)
    with pytest.raises(pl.PortfolioError, match="expected 67"):
        pl.build_florida_locations(data_dir, manifest=wrong, opener=host)


def test_main(
    mini: Mini, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest, host, data_dir = mini
    opener: Callable[[str], AbstractContextManager[IO[bytes]]] = host
    monkeypatch.setattr(pl, "load_manifest", lambda path=None: manifest)
    monkeypatch.setattr(iris, "_urlopen", opener)
    assert pl.main(["--data-dir", str(data_dir), "--download-only"]) == 0
    assert "created   LitPop_test.hdf5" in capsys.readouterr().out
    assert pl.main(["--data-dir", str(data_dir)]) == 0
    out = capsys.readouterr().out
    assert "sha256 locations.yaml:" in out
    assert pl.main(["--data-dir", str(data_dir)]) == 1  # outputs exist
    assert "outputs exist" in capsys.readouterr().err
