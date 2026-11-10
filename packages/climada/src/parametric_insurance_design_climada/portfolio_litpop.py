"""Aggregate LitPop cells to administrative units: the D2 Florida portfolio.

The paper portfolio (D2, SPEC §6.6) is Florida's 67 counties, each valued by
the sum of the cells of the pinned CLIMADA data-API file
``LitPop_150arcsec_USA`` v3 that fall in it, and located at the cells'
value-weighted centroid. This module builds that EventSet v1 ``locations``
table (SPEC §5) with its provenance:

1. download both inputs and check their size, MD5 and SHA256 against the
   manifest shipped with this package (``litpop_florida_manifest.json``):
   the LitPop file and the U.S. Census Bureau TIGER/Line county boundaries
   (:func:`prepare_inputs`, which reuses :func:`.iris.download_file`);
2. read the LitPop cells (:func:`read_litpop_cells`) and the county polygons
   (:func:`read_county_boundaries`);
3. assign every cell to a unit and aggregate (:func:`aggregate_cells`);
4. write the table and its provenance (:func:`build_florida_locations`).

**Assignment.** A cell is a point (its centre, as LitPop stores it). Only
cells inside the *region*, the bounding box of the target units widened by a
margin, are tested; every other cell is counted as outside the region. A
region cell is assigned to the unit whose polygon contains or touches it
(``intersects``). Each region cell ends in exactly one of three groups:

* a target unit (it counts towards that unit's value);
* another unit of the boundary file (e.g. a Georgia county next to Florida);
* no unit at all (e.g. a cell offshore of every county polygon).

Nothing is dropped silently. The counts and values of all groups are in the
:class:`AssignmentReport`, and ``outside="raise"`` turns unassigned cells
with a positive value into an :class:`UnassignedCellsError`. A cell on a
shared edge goes to the unit with the smallest ID, and is counted. A target
unit without any cell raises :class:`EmptyUnitError`, and one whose cells
are all zero-valued raises :class:`ZeroValueUnitError`, because its
value-weighted centroid is undefined.

**Centroid.** The value-weighted mean of the cells' latitudes and longitudes.
At county scale and far from the antimeridian, this is a good stand-in for
the geodesic mean.

The output, under ``out_dir``:

* ``locations.yaml``: the table in the layout ``pipeline.read_locations``
  reads (``locations: yaml`` in a build config), sorted by ``location_id``;
* ``cells.parquet``: every region cell with its unit, so that a loss can be
  computed per cell and summed per county;
* ``provenance.json``: source files and checksums, the method, the counts
  and the checksums of the two files above.

Run it with ``pixi run florida-locations`` from ``packages/climada`` (writes
to the git-ignored ``data/litpop-florida/`` at the repository root), or
``python -m parametric_insurance_design_climada.portfolio_litpop --help``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Collection, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from typing import Any, Final, Literal, cast

import geopandas as gpd
import numpy as np
import pandas as pd
import pyproj
import shapely
import yaml
from numpy.typing import NDArray

from parametric_insurance_design_climada import iris

__all__ = [
    "AssignmentReport",
    "CellAggregation",
    "EmptyUnitError",
    "FloridaBuild",
    "PortfolioError",
    "PortfolioInputError",
    "PortfolioManifest",
    "PortfolioPaths",
    "UnassignedCellsError",
    "ZeroValueUnitError",
    "aggregate_cells",
    "build_florida_locations",
    "load_manifest",
    "main",
    "prepare_inputs",
    "read_county_boundaries",
    "read_litpop_cells",
]

logger = logging.getLogger(__name__)

MANIFEST_RESOURCE: Final = "litpop_florida_manifest.json"
LOCATIONS_YAML: Final = "locations.yaml"
CELLS_PARQUET: Final = "cells.parquet"
PROVENANCE_JSON: Final = "provenance.json"
CRS: Final = "EPSG:4326"
METHOD: Final = (
    "Each LitPop cell (its centre point) inside the region (the target "
    "units' bounding box widened by region_margin_deg) is assigned to the "
    "boundary polygon it intersects; a cell on a shared edge goes to the "
    "smallest unit ID. A unit's value is the sum of its cells' values; its "
    "lat/lon is the value-weighted mean of its cells' lat/lon (WGS 84). "
    "Boundaries are reprojected from NAD83 to WGS 84 (EPSG:4326)."
)


class PortfolioError(Exception):
    """Base class for errors while building a LitPop portfolio."""


class PortfolioInputError(PortfolioError):
    """The cells, the units or the manifest are malformed."""


class EmptyUnitError(PortfolioError):
    """A target unit contains no cell."""


class ZeroValueUnitError(PortfolioError):
    """A target unit's cells all have zero value, so it has no centroid."""


class UnassignedCellsError(PortfolioError):
    """Cells with a positive value lie in the region but in no unit."""


@dataclass(frozen=True)
class PortfolioManifest:
    """Pinned inputs of the Florida portfolio.

    Attributes
    ----------
    portfolio, licence, attribution : str
        What is built, the licence of the result and the attribution text.
    litpop : iris.RemoteFile
        The LitPop HDF5 file, with the CLIMADA data API's MD5.
    litpop_info : dict of str to str
        Dataset name, version, uuid, record URL and licence of ``litpop``.
    boundaries : iris.RemoteFile
        The TIGER/Line county zip.
    boundaries_info : dict of str to str
        Dataset, version, record URL, licence and shapefile member.
    state_fips : str
        Two-digit state FIPS code of the target counties (``"12"``).
    expected_units : int
        Number of target units the build must find (67).
    region_margin_deg : float
        Margin around the target units' bounding box, in degrees.
    """

    portfolio: str
    licence: str
    attribution: str
    litpop: iris.RemoteFile
    litpop_info: dict[str, str]
    boundaries: iris.RemoteFile
    boundaries_info: dict[str, str]
    state_fips: str
    expected_units: int
    region_margin_deg: float


@dataclass(frozen=True)
class PortfolioPaths:
    """Where :func:`prepare_inputs` put each input, and what it had to do.

    Attributes
    ----------
    litpop, boundaries : Path
        The verified files.
    actions : dict of str to str
        For each file name, ``"created"`` or ``"verified"``.
    """

    litpop: Path
    boundaries: Path
    actions: dict[str, str]


@dataclass(frozen=True)
class AssignmentReport:
    """Where every cell went. Counts add up to ``n_cells``.

    Attributes
    ----------
    n_cells, value_total : int, float
        All input cells and their total value.
    n_outside_region, value_outside_region : int, float
        Cells outside the region (not tested against any polygon).
    n_in_target, value_in_target : int, float
        Region cells in a target unit.
    n_in_other_units, value_in_other_units : int, float
        Region cells in a unit that is not a target.
    n_unassigned, value_unassigned : int, float
        Region cells in no unit.
    n_unassigned_positive : int
        Unassigned cells with a positive value.
    n_on_shared_edge : int
        Region cells that touch more than one unit (assigned to the smallest
        unit ID).
    n_target_units : int
        Target units, all of which have at least one cell.
    region_bounds : tuple of float
        ``(min_lon, min_lat, max_lon, max_lat)`` of the region.
    """

    n_cells: int
    value_total: float
    n_outside_region: int
    value_outside_region: float
    n_in_target: int
    value_in_target: float
    n_in_other_units: int
    value_in_other_units: float
    n_unassigned: int
    value_unassigned: float
    n_unassigned_positive: int
    n_on_shared_edge: int
    n_target_units: int
    region_bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class CellAggregation:
    """Result of :func:`aggregate_cells`.

    Attributes
    ----------
    locations : pandas.DataFrame
        One row per target unit, sorted by ``location_id``: ``location_id``,
        ``lat``, ``lon``, ``value``, ``name`` (SPEC §5) and the free columns
        ``n_cells``, ``n_cells_positive`` and ``centroid_in_unit`` (whether
        the value-weighted centroid lies in the unit's own polygon).
    cells : pandas.DataFrame
        Every region cell: ``cell`` (its row label in the input), ``lat``,
        ``lon``, ``value``, ``unit_id`` (``None`` if in no unit) and
        ``location_id`` (``None`` unless in a target unit).
    report : AssignmentReport
        Counts and values of every group of cells.
    """

    locations: pd.DataFrame
    cells: pd.DataFrame
    report: AssignmentReport


@dataclass(frozen=True)
class FloridaBuild:
    """What :func:`build_florida_locations` wrote.

    Attributes
    ----------
    locations_yaml, cells_parquet, provenance_json : Path
        The output files.
    aggregation : CellAggregation
        The table, the cells and the report.
    provenance : dict
        The content of ``provenance.json``.
    """

    locations_yaml: Path
    cells_parquet: Path
    provenance_json: Path
    aggregation: CellAggregation
    provenance: dict[str, Any]


# --- manifest ---------------------------------------------------------------


def _remote(raw: dict[str, Any]) -> iris.RemoteFile:
    return iris.RemoteFile(
        name=str(raw["name"]),
        size=int(raw["size"]),
        sha256=str(raw["sha256"]).lower(),
        url=str(raw["url"]),
        doi=str(raw.get("doi", "")),
        md5=str(raw["md5"]).lower(),
    )


def _info(raw: dict[str, Any], keys: Sequence[str]) -> dict[str, str]:
    return {key: str(raw[key]) for key in keys}


def load_manifest(path: Path | None = None) -> PortfolioManifest:
    """Read the Florida portfolio manifest.

    Parameters
    ----------
    path : Path, optional
        A manifest JSON file. Defaults to the one shipped with this package.

    Returns
    -------
    PortfolioManifest
        The parsed manifest.

    Raises
    ------
    PortfolioInputError
        If a required key is missing.
    """
    if path is None:
        text = files(__package__ or "parametric_insurance_design_climada")
        raw = json.loads(text.joinpath(MANIFEST_RESOURCE).read_text("utf-8"))
    else:
        raw = json.loads(Path(path).read_text("utf-8"))
    try:
        return PortfolioManifest(
            portfolio=str(raw["portfolio"]),
            licence=str(raw["licence"]),
            attribution=str(raw["attribution"]),
            litpop=_remote(raw["litpop"]),
            litpop_info=_info(
                raw["litpop"], ("dataset", "version", "uuid", "record", "licence")
            ),
            boundaries=_remote(raw["boundaries"]),
            boundaries_info=_info(
                raw["boundaries"], ("dataset", "version", "record", "licence", "member")
            ),
            state_fips=str(raw["state_fips"]),
            expected_units=int(raw["expected_units"]),
            region_margin_deg=float(raw["region_margin_deg"]),
        )
    except KeyError as exc:
        raise PortfolioInputError(
            f"portfolio manifest is missing the key {exc}"
        ) from exc


# --- inputs -----------------------------------------------------------------


def prepare_inputs(
    data_dir: Path,
    *,
    manifest: PortfolioManifest | None = None,
    opener: iris.Opener | None = None,
) -> PortfolioPaths:
    """Download the LitPop file and the county boundaries, with checksums.

    Both go to ``data_dir / "raw"``. A file that is already present and
    verified is kept; one that does not match raises and is left untouched
    (:func:`.iris.download_file`).

    Parameters
    ----------
    data_dir : Path
        Root of the portfolio data.
    manifest : PortfolioManifest, optional
        Defaults to the manifest shipped with this package.
    opener : callable, optional
        Opens a URL for reading bytes (for tests). Defaults to urllib.

    Returns
    -------
    PortfolioPaths
        The verified files and what was done to each.

    Raises
    ------
    iris.ChecksumMismatchError
        If a downloaded or existing file does not match the manifest. If the
        LitPop file was withdrawn or replaced upstream, do not regenerate it:
        that needs a NASA login, which only the owner may use.
    """
    manifest = manifest or load_manifest()
    raw_dir = data_dir / "raw"
    actions: dict[str, str] = {}
    paths: list[Path] = []
    for remote in (manifest.litpop, manifest.boundaries):
        path, created = iris.download_file(remote, raw_dir, opener=opener)
        actions[remote.name] = "created" if created else "verified"
        paths.append(path)
    return PortfolioPaths(litpop=paths[0], boundaries=paths[1], actions=actions)


def read_litpop_cells(path: Path) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Read a LitPop HDF5 file written by CLIMADA.

    Parameters
    ----------
    path : Path
        The file, e.g. ``LitPop_150arcsec_USA.hdf5``.

    Returns
    -------
    tuple of (pandas.DataFrame, dict)
        The cells (``lat``, ``lon``, ``value``, in file order) and the
        file's own metadata: ``ref_year``, ``value_unit``, ``description``
        and ``crs``.

    Raises
    ------
    PortfolioInputError
        If the file is not in WGS 84.
    """
    from climada.entity import Exposures  # heavy import, deferred

    exposures = Exposures.from_hdf5(str(path))
    gdf = exposures.gdf
    crs = None if exposures.crs is None else pyproj.CRS.from_user_input(exposures.crs)
    if crs is None or crs.to_epsg() != 4326:
        raise PortfolioInputError(f"{path}: expected WGS 84, got {exposures.crs}")
    cells = pd.DataFrame(
        {
            "lat": gdf.geometry.y.to_numpy(dtype=np.float64),
            "lon": gdf.geometry.x.to_numpy(dtype=np.float64),
            "value": gdf["value"].to_numpy(dtype=np.float64),
        }
    )
    if exposures.ref_year is None:
        raise PortfolioInputError(f"{path}: no reference year")
    meta = {
        "ref_year": int(exposures.ref_year),
        "value_unit": str(exposures.value_unit),
        "description": str(exposures.description),
        "crs": "EPSG:4326",
    }
    return cells, meta


def read_county_boundaries(zip_path: Path, member: str) -> gpd.GeoDataFrame:
    """Read TIGER/Line county polygons from the Census zip, in WGS 84.

    Parameters
    ----------
    zip_path : Path
        ``tl_<year>_us_county.zip``.
    member : str
        The shapefile inside it, e.g. ``tl_2025_us_county.shp``.

    Returns
    -------
    geopandas.GeoDataFrame
        Columns ``unit_id`` (the five-digit county GEOID), ``name`` (the
        county name without "County"), ``state_fips`` and ``geometry``.

    Raises
    ------
    PortfolioInputError
        If a required attribute is missing or GEOIDs repeat.
    """
    gdf = gpd.read_file(f"zip://{Path(zip_path).resolve()}!{member}")
    missing = [c for c in ("GEOID", "NAME", "STATEFP") if c not in gdf.columns]
    if missing:
        raise PortfolioInputError(f"{zip_path}: lacks attributes {missing}")
    units = gpd.GeoDataFrame(
        {
            "unit_id": gdf["GEOID"].astype(str),
            "name": gdf["NAME"].astype(str),
            "state_fips": gdf["STATEFP"].astype(str),
        },
        geometry=gdf.geometry,
        crs=gdf.crs,
    ).to_crs(CRS)
    if units["unit_id"].duplicated().any():
        raise PortfolioInputError(f"{zip_path}: GEOID values repeat")
    return units


# --- aggregation ------------------------------------------------------------


def _check_cells(cells: pd.DataFrame) -> None:
    missing = [c for c in ("lat", "lon", "value") if c not in cells.columns]
    if missing:
        raise PortfolioInputError(f"cells lack columns {missing}")
    if not cells.index.is_unique:
        raise PortfolioInputError("cells must have a unique index")
    data = cells[["lat", "lon", "value"]].to_numpy(dtype=np.float64)
    if not np.isfinite(data).all():
        raise PortfolioInputError("cell lat, lon and value must be finite")
    if (data[:, 2] < 0).any():
        raise PortfolioInputError("cell values must be >= 0")


def _check_units(units: gpd.GeoDataFrame) -> None:
    missing = [c for c in ("unit_id", "name") if c not in units.columns]
    if missing:
        raise PortfolioInputError(f"units lack columns {missing}")
    if units.crs is None or units.crs.to_epsg() != 4326:
        raise PortfolioInputError(f"units must be in {CRS}, got {units.crs}")
    if units["unit_id"].astype(str).duplicated().any():
        raise PortfolioInputError("unit_id values repeat")
    if units.geometry.isna().any() or units.geometry.is_empty.any():
        raise PortfolioInputError("every unit needs a non-empty geometry")


def aggregate_cells(
    cells: pd.DataFrame,
    units: gpd.GeoDataFrame,
    *,
    target: Collection[str] | None = None,
    margin_deg: float = 0.5,
    outside: Literal["report", "raise"] = "report",
) -> CellAggregation:
    """Assign gridded cells to unit polygons and aggregate the target units.

    Parameters
    ----------
    cells : pandas.DataFrame
        Columns ``lat``, ``lon`` (degrees, WGS 84) and ``value`` (>= 0), with
        a unique index.
    units : geopandas.GeoDataFrame
        Columns ``unit_id``, ``name`` and polygon geometries in EPSG:4326.
        Include the neighbours of the target units, so that cells across a
        border are counted as "in another unit" rather than "in no unit".
    target : collection of str, optional
        The ``unit_id`` values to build locations for. Defaults to all units.
    margin_deg : float, default 0.5
        Margin around the target units' bounding box that defines the region.
    outside : {"report", "raise"}, default "report"
        What to do with region cells that lie in no unit and have a positive
        value: count them in the report, or raise.

    Returns
    -------
    CellAggregation
        The locations table, the region cells with their unit and the report.

    Raises
    ------
    PortfolioInputError
        If the inputs are malformed, ``margin_deg`` is negative, or a target
        is not a unit.
    EmptyUnitError
        If a target unit contains no cell.
    ZeroValueUnitError
        If a target unit's cells all have zero value.
    UnassignedCellsError
        If ``outside="raise"`` and a positive-value region cell is in no unit.
    """
    _check_cells(cells)
    _check_units(units)
    if not margin_deg >= 0:
        raise PortfolioInputError(f"margin_deg must be >= 0, got {margin_deg}")
    if outside not in ("report", "raise"):
        raise PortfolioInputError(f"outside must be 'report' or 'raise': {outside!r}")
    units = cast(
        gpd.GeoDataFrame,
        units.assign(unit_id=units["unit_id"].astype(str)).reset_index(drop=True),
    )
    all_ids = set(units["unit_id"])
    targets = sorted(all_ids if target is None else {str(t) for t in target})
    if not targets:
        raise PortfolioInputError("no target units")
    unknown = sorted(set(targets) - all_ids)
    if unknown:
        raise PortfolioInputError(f"target units not in the boundaries: {unknown}")

    is_target = units["unit_id"].isin(targets)
    min_lon, min_lat, max_lon, max_lat = units.loc[is_target].total_bounds
    bounds = (
        float(min_lon - margin_deg),
        float(min_lat - margin_deg),
        float(max_lon + margin_deg),
        float(max_lat + margin_deg),
    )
    lat = cells["lat"].to_numpy(dtype=np.float64)
    lon = cells["lon"].to_numpy(dtype=np.float64)
    value = cells["value"].to_numpy(dtype=np.float64)
    in_region = (
        (lon >= bounds[0])
        & (lon <= bounds[2])
        & (lat >= bounds[1])
        & (lat <= bounds[3])
    )
    region = pd.DataFrame(
        {
            "cell": cells.index[in_region],
            "lat": lat[in_region],
            "lon": lon[in_region],
            "value": value[in_region],
        }
    )

    # Spatial join on the units that reach into the region.
    box = shapely.box(*bounds)
    near_units = units.loc[units.geometry.intersects(box)]
    points = gpd.GeoDataFrame(
        {"row": np.arange(len(region))},
        geometry=gpd.points_from_xy(region["lon"], region["lat"]),
        crs=CRS,
    )
    joined = gpd.sjoin(
        points, near_units[["unit_id", "geometry"]], how="inner", predicate="intersects"
    )
    hits = pd.DataFrame(
        {"row": joined["row"].to_numpy(), "unit_id": joined["unit_id"].to_numpy()}
    ).sort_values(["row", "unit_id"], kind="stable")
    n_on_shared_edge = int((hits.groupby("row").size() > 1).sum())
    first = hits.drop_duplicates("row", keep="first").set_index("row")["unit_id"]
    unit_of = first.reindex(np.arange(len(region)))
    region["unit_id"] = unit_of.to_numpy(dtype=object)
    region.loc[region["unit_id"].isna(), "unit_id"] = None
    target_mask = region["unit_id"].isin(targets).to_numpy()
    region["location_id"] = [
        u if t else None for u, t in zip(region["unit_id"], target_mask, strict=True)
    ]
    unassigned = region["unit_id"].isna().to_numpy()
    other = ~unassigned & ~target_mask

    region_values = region["value"].to_numpy(dtype=np.float64)
    n_unassigned_positive = int((unassigned & (region_values > 0)).sum())
    report = AssignmentReport(
        n_cells=len(cells),
        value_total=float(value.sum()),
        n_outside_region=int((~in_region).sum()),
        value_outside_region=float(value[~in_region].sum()),
        n_in_target=int(target_mask.sum()),
        value_in_target=float(region_values[target_mask].sum()),
        n_in_other_units=int(other.sum()),
        value_in_other_units=float(region_values[other].sum()),
        n_unassigned=int(unassigned.sum()),
        value_unassigned=float(region_values[unassigned].sum()),
        n_unassigned_positive=n_unassigned_positive,
        n_on_shared_edge=n_on_shared_edge,
        n_target_units=len(targets),
        region_bounds=bounds,
    )
    if outside == "raise" and n_unassigned_positive:
        raise UnassignedCellsError(
            f"{n_unassigned_positive} region cells with a positive value "
            f"(total {report.value_unassigned:.6g}) lie in no unit"
        )

    in_target = region.loc[target_mask]
    counts = in_target.groupby("location_id").size()
    empty = [t for t in targets if t not in counts.index]
    if empty:
        raise EmptyUnitError(f"target units without any cell: {empty}")
    weighted = in_target.assign(
        wlat=in_target["lat"] * in_target["value"],
        wlon=in_target["lon"] * in_target["value"],
        positive=in_target["value"] > 0,
    )
    sums = weighted.groupby("location_id")[["value", "wlat", "wlon", "positive"]].sum()
    sums = sums.reindex(targets)
    zero = sums.index[sums["value"] <= 0].tolist()
    if zero:
        raise ZeroValueUnitError(
            f"target units whose cells all have zero value: {zero}"
        )

    names = units.set_index("unit_id")["name"]
    geoms = units.set_index("unit_id").geometry
    c_lat = (sums["wlat"] / sums["value"]).to_numpy(dtype=np.float64)
    c_lon = (sums["wlon"] / sums["value"]).to_numpy(dtype=np.float64)
    inside = shapely.intersects(
        geoms.reindex(targets).to_numpy(), shapely.points(c_lon, c_lat)
    )
    locations = pd.DataFrame(
        {
            "location_id": targets,
            "lat": c_lat,
            "lon": c_lon,
            "value": sums["value"].to_numpy(dtype=np.float64),
            "name": names.reindex(targets).astype(str).to_numpy(),
            "n_cells": counts.reindex(targets).to_numpy(dtype=np.int64),
            "n_cells_positive": sums["positive"].to_numpy(dtype=np.int64),
            "centroid_in_unit": np.asarray(inside, dtype=bool),
        }
    )
    return CellAggregation(
        locations=locations, cells=region.reset_index(drop=True), report=report
    )


# --- Florida build ----------------------------------------------------------


def _write_locations_yaml(path: Path, locations: pd.DataFrame, header: str) -> None:
    rows = [
        {
            "location_id": str(r["location_id"]),
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "value": float(r["value"]),
            "name": str(r["name"]),
            "n_cells": int(r["n_cells"]),
            "n_cells_positive": int(r["n_cells_positive"]),
            "centroid_in_unit": bool(r["centroid_in_unit"]),
        }
        for r in locations.to_dict("records")
    ]
    body = yaml.safe_dump({"locations": rows}, sort_keys=False, allow_unicode=True)
    path.write_text(header + body, encoding="utf-8")


def _value_summary(values: NDArray[np.float64]) -> dict[str, float]:
    """Skew of the value distribution across units."""
    v = np.sort(values)[::-1]
    total = float(v.sum())
    share = v / total
    return {
        "total": total,
        "max_share": float(share[0]),
        "top5_share": float(share[:5].sum()),
        "top10_share": float(share[:10].sum()),
        "median": float(np.median(v)),
        "max_over_median": float(v[0] / np.median(v)),
        "hhi": float((share**2).sum()),
        "effective_n": float(1.0 / (share**2).sum()),
    }


def build_florida_locations(
    data_dir: Path,
    *,
    out_dir: Path | None = None,
    manifest: PortfolioManifest | None = None,
    opener: iris.Opener | None = None,
    overwrite: bool = False,
) -> FloridaBuild:
    """Build the D2 locations table: Florida's counties from LitPop.

    Parameters
    ----------
    data_dir : Path
        Root of the portfolio data; inputs go to ``data_dir / "raw"``.
    out_dir : Path, optional
        Output directory. Defaults to ``data_dir / "locations"``.
    manifest : PortfolioManifest, optional
        Defaults to the manifest shipped with this package.
    opener : callable, optional
        Opens a URL for reading bytes (for tests). Defaults to urllib.
    overwrite : bool, default False
        Replace existing output files.

    Returns
    -------
    FloridaBuild
        The files written, the aggregation and the provenance.

    Raises
    ------
    PortfolioError
        If the number of target units differs from the manifest, an output
        file exists and ``overwrite`` is False, or :func:`aggregate_cells`
        raises.
    iris.ChecksumMismatchError
        If an input does not match the manifest.
    """
    manifest = manifest or load_manifest()
    out_dir = out_dir or data_dir / "locations"
    outputs = [out_dir / n for n in (LOCATIONS_YAML, CELLS_PARQUET, PROVENANCE_JSON)]
    existing = [str(p) for p in outputs if p.exists()]
    if existing and not overwrite:
        raise PortfolioError(f"outputs exist (pass overwrite): {existing}")

    paths = prepare_inputs(data_dir, manifest=manifest, opener=opener)
    cells, litpop_meta = read_litpop_cells(paths.litpop)
    units = read_county_boundaries(paths.boundaries, manifest.boundaries_info["member"])
    target = units.loc[units["state_fips"] == manifest.state_fips, "unit_id"].tolist()
    if len(target) != manifest.expected_units:
        raise PortfolioError(
            f"found {len(target)} units with state FIPS {manifest.state_fips}, "
            f"expected {manifest.expected_units}"
        )
    aggregation = aggregate_cells(
        cells, units, target=target, margin_deg=manifest.region_margin_deg
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    header = (
        f"# {manifest.portfolio}\n"
        f"# Licence: {manifest.licence}. {manifest.attribution}\n"
        f"# Value unit: {litpop_meta['value_unit']} (LitPop reference_year "
        f"{litpop_meta['ref_year']}). Provenance: {PROVENANCE_JSON}.\n"
    )
    _write_locations_yaml(outputs[0], aggregation.locations, header)
    aggregation.cells.to_parquet(outputs[1], index=False)

    def _source(remote: iris.RemoteFile, info: dict[str, str]) -> dict[str, Any]:
        return {
            **info,
            "file": remote.name,
            "url": remote.url,
            "size": remote.size,
            "md5": remote.md5,
            "sha256": remote.sha256,
        }

    provenance: dict[str, Any] = {
        "portfolio": manifest.portfolio,
        "licence": manifest.licence,
        "attribution": manifest.attribution,
        "sources": {
            "litpop": _source(manifest.litpop, manifest.litpop_info),
            "boundaries": _source(manifest.boundaries, manifest.boundaries_info),
        },
        "litpop_file_metadata": litpop_meta,
        "method": METHOD,
        "parameters": {
            "state_fips": manifest.state_fips,
            "region_margin_deg": manifest.region_margin_deg,
            "predicate": "intersects",
            "outside": "report",
        },
        "report": asdict(aggregation.report),
        "value_summary": _value_summary(
            aggregation.locations["value"].to_numpy(dtype=np.float64)
        ),
        "outputs": {
            p.name: {"sha256": iris.file_digests(p)[1], "size": p.stat().st_size}
            for p in outputs[:2]
        },
        "producer": {
            "package": "parametric-insurance-design-climada",
            "version": version("parametric-insurance-design-climada"),
            # Spelled out: __name__ is "__main__" under `python -m`.
            "function": (
                "parametric_insurance_design_climada.portfolio_litpop."
                "build_florida_locations"
            ),
            "climada": version("climada"),
            "geopandas": version("geopandas"),
            "shapely": version("shapely"),
        },
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    outputs[2].write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")
    return FloridaBuild(
        locations_yaml=outputs[0],
        cells_parquet=outputs[1],
        provenance_json=outputs[2],
        aggregation=aggregation,
        provenance=provenance,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point; see ``--help``.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit status: 0 on success, 1 on a data or portfolio error.
    """
    parser = argparse.ArgumentParser(
        prog="python -m parametric_insurance_design_climada.portfolio_litpop",
        description=(
            "Download the pinned LitPop USA file and the TIGER/Line county "
            "boundaries (checksums in litpop_florida_manifest.json), aggregate "
            "the LitPop cells to Florida's counties and write the EventSet "
            "locations table with its provenance."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        required=True,
        help="portfolio data root (git-ignored), e.g. ../../data/litpop-florida",
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None, help="default: <data-dir>/locations"
    )
    parser.add_argument(
        "--download-only", action="store_true", help="only fetch and verify inputs"
    )
    parser.add_argument("--overwrite", action="store_true", help="replace outputs")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        if args.download_only:
            paths = prepare_inputs(args.data_dir)
            for name, action in paths.actions.items():
                print(f"{action:9s} {name}")
            return 0
        build = build_florida_locations(
            args.data_dir, out_dir=args.out_dir, overwrite=args.overwrite
        )
    except (iris.IrisDataError, PortfolioError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    report = build.aggregation.report
    print(json.dumps(asdict(report), indent=2))
    for path in (build.locations_yaml, build.cells_parquet, build.provenance_json):
        print(f"wrote {path}")
    for name, out in build.provenance["outputs"].items():
        print(f"sha256 {name}: {out['sha256']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
