"""STORM track catalogue: reading, year mapping and conversion to CLIMADA.

STORM (Bloemendaal et al. 2020; dataset "STORM IBTrACS present climate
synthetic tropical cyclone tracks", version 4, 4TU.ResearchData,
doi:10.4121/12706085, CC0 1.0) is the second hazard catalogue of the robust
design (SPEC §6.5 (i), D7). It ships 10,000 synthetic years per basin
as ten 1,000-year text files, ``STORM_DATA_IBTRACS_<basin>_1000_YEARS_<k>.txt``
with ``k`` = 0 … 9 (file names as in the version-4 archive).

This module is the STORM counterpart of :mod:`.tracks` (IRIS):

1. :func:`read_storm_catalogue` reads the ten files of one basin from a
   directory into the table layout the pipeline uses for IRIS (one row per
   track point, ``event_id``, ``year``, ``tc``, ``timestep``, ``lat``,
   ``lon``, ``vmax``, ``pmin``, ``rmw``, ``basin``), and **rebuilds the
   simulation year**: STORM's year column restarts at 0 in every file, so the
   year of a storm is ``1000 * k + year`` (:data:`YEARS_PER_FILE`), and the
   catalogue covers ``1000 * n_files`` years. CLIMADA's own reader
   (``TCTracks.from_simulations_storm``) instead puts every track in 1980
   with frequency 1, which is why the adapter does not use it.
2. :func:`storm_to_track` turns one storm's rows into the
   :class:`xarray.Dataset` that :class:`climada.hazard.TCTracks` holds, with
   the same time axis, units and environmental pressure as the IRIS path
   (:func:`.tracks.storm_to_track`), so that the two catalogues differ only in
   the tracks.

**Fail loudly.** :class:`.tracks.CatalogueFormatError` is raised where the year
mapping or the tracks would otherwise be wrong silently: a file name without
an index, an index missing or repeated, a year outside ``[0, 1000)`` in a file
(it could not be told from a year that is already global), a row of another
basin, non-integer codes, duplicate or non-consecutive time steps, and values
out of range. CLIMADA's reader drops duplicate ``(year, tc, timestep)`` rows
silently ("a bug in the data", fixed in version 4 of the dataset); this module
raises instead.

**Conversions** (recorded in :data:`TRACK_CONVERSION` and the EventSet's build
record):

* wind: STORM's maximum wind is a 10-minute mean in m/s. It is divided by
  :data:`WIND_10MIN_TO_1MIN` (0.88, Bloemendaal et al. 2020; CLIMADA's
  ``STORM_1MIN_WIND_FACTOR``) to give the 1-minute sustained wind that
  CLIMADA's wind models and the Saffir-Simpson scale use. ``vmax`` in the
  table is that 1-minute wind in m/s; :func:`storm_to_track` converts it to
  knots as the IRIS path does;
* longitude: STORM gives 0 to 360° east; the table holds ``lon - 360`` for
  ``lon > 180``, i.e. ``(-180, 180]`` as the IRIS catalogue and the locations;
* radius of maximum winds: km to nautical miles, as for IRIS;
* STORM has no radius of the outermost closed isobar (IRIS's ``r18``), so the
  track has no ``radius_oci``, as with CLIMADA's own STORM reader. CLIMADA's
  wind models do not use it;
* environmental pressure: :data:`.tracks.ENV_PRESSURE_HPA` (1,013 hPa, the
  thesis value of the IRIS path) at every point. CLIMADA's own STORM reader
  uses its basin default (1,010 hPa for the North Atlantic) instead.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
import xarray as xr

from parametric_insurance_design_climada import iris, tracks
from parametric_insurance_design_climada.tracks import CatalogueFormatError

__all__ = [
    "BASIN_IDS",
    "LON_CONVERSION",
    "STORM_COLUMNS",
    "TRACK_CONVERSION",
    "WIND_10MIN_TO_1MIN",
    "YEARS_PER_FILE",
    "StormCatalogue",
    "StormFile",
    "member_name",
    "read_storm_catalogue",
    "read_storm_file",
    "storm_member_files",
    "storm_to_track",
]

#: Columns of a STORM file, in file order (README of the 4TU dataset;
#: Bloemendaal et al. 2020, Table 2). ``vmax_10min`` is the 10-minute mean
#: maximum wind in m/s, ``dist_to_land`` in km, ``rmw`` in km.
STORM_COLUMNS: Final[tuple[str, ...]] = (
    "year",
    "month",
    "tc",
    "timestep",
    "basin_id",
    "lat",
    "lon",
    "pmin",
    "vmax_10min",
    "rmw",
    "category",
    "landfall",
    "dist_to_land",
)
_INT_COLUMNS: Final[tuple[str, ...]] = (
    "year",
    "month",
    "tc",
    "timestep",
    "basin_id",
    "category",
    "landfall",
)
#: STORM basin codes (README: 0=EP, 1=NA, 2=NI, 3=SI, 4=SP, 5=WP).
BASIN_IDS: Final[Mapping[str, int]] = {
    "EP": 0,
    "NA": 1,
    "NI": 2,
    "SI": 3,
    "SP": 4,
    "WP": 5,
}
#: Simulated years in one STORM file; a file's year column runs in [0, 1000).
YEARS_PER_FILE: Final[int] = 1000
#: 1-minute sustained wind = 10-minute mean / 0.88 (Bloemendaal et al. 2020;
#: CLIMADA's ``STORM_1MIN_WIND_FACTOR``).
WIND_10MIN_TO_1MIN: Final[float] = 0.88
#: TC numbers must stay below this, so that ``year * 1000 + tc`` is a unique
#: integer track ID (CLIMADA's ``id_no`` convention for STORM).
_MAX_TC: Final[int] = 1000
LON_CONVERSION: Final[str] = (
    "STORM longitude in [0, 360] degrees east; lon - 360 for lon > 180, "
    "giving (-180, 180]"
)
#: How STORM rows become CLIMADA tracks; written into the build record.
TRACK_CONVERSION: Final[Mapping[str, Any]] = {
    "source_format": "STORM (comma-separated, 13 columns, no header)",
    "year": (
        f"simulation year = {YEARS_PER_FILE} * file index k + year in file "
        f"(year in file in [0, {YEARS_PER_FILE}))"
    ),
    "vmax_10min_to_1min_divisor": WIND_10MIN_TO_1MIN,
    "vmax_m_s_to_kn": tracks.MS_TO_KT,
    "rmw_km_to_nm": tracks.KM_TO_NM,
    "radius_oci": "none (STORM has no outer radius; unused by CLIMADA's wind models)",
    "lon": LON_CONVERSION,
    "timestep_hours": tracks.TIMESTEP_HOURS,
    "environmental_pressure_hpa": tracks.ENV_PRESSURE_HPA,
}
_MEMBER: Final[re.Pattern[str]] = re.compile(
    r"^STORM_DATA_IBTRACS_(?P<basin>[A-Z]{2})_1000_YEARS_(?P<index>\d+)\.txt$"
)


def member_name(basin: str, index: int) -> str:
    """Return the file name of one STORM 1,000-year file.

    Parameters
    ----------
    basin : str
        Basin code, e.g. ``"NA"``.
    index : int
        File index ``k`` (0 to 9 in the dataset).

    Returns
    -------
    str
        ``STORM_DATA_IBTRACS_<basin>_1000_YEARS_<index>.txt``.
    """
    return f"STORM_DATA_IBTRACS_{basin}_1000_YEARS_{index}.txt"


@dataclass(frozen=True)
class StormFile:
    """One STORM file as read, with what the year mapping did to it.

    Attributes
    ----------
    name : str
        File name.
    index : int
        File index ``k`` from the name; its storms get years
        ``1000 * k + year``.
    sha256 : str
        Lower-case hex SHA256 of the file.
    n_rows : int
        Track points.
    n_storms : int
        Storms (distinct ``(year, tc)``).
    year_min, year_max : int
        Smallest and largest year in the file (before the mapping).
    """

    name: str
    index: int
    sha256: str
    n_rows: int
    n_storms: int
    year_min: int
    year_max: int

    def record(self) -> dict[str, Any]:
        """Return the file's entry of the build record (JSON-ready)."""
        offset = YEARS_PER_FILE * self.index
        return {
            "file": self.name,
            "sha256": self.sha256,
            "index": self.index,
            "n_track_points": self.n_rows,
            "n_storms": self.n_storms,
            "year_in_file": [self.year_min, self.year_max],
            "simulation_year": [offset + self.year_min, offset + self.year_max],
        }


@dataclass(frozen=True)
class StormCatalogue:
    """The STORM files of one basin, as one table.

    Attributes
    ----------
    frame : pandas.DataFrame
        One row per track point, in file order (files by index): ``event_id``
        (``STORM_<basin>_<year>_<tc>``), ``year`` (simulation year, in
        ``[0, n_years)``), ``tc``, ``month``, ``timestep``, ``lat``, ``lon``
        (in ``(-180, 180]``), ``vmax`` (1-minute wind, m/s), ``vmax_10min``
        (as in the file), ``pmin`` (hPa), ``rmw`` (km), ``category``,
        ``landfall``, ``dist_to_land`` (km), ``basin`` (str) and
        ``file_index``.
    files : tuple of StormFile
        The files, by index.
    basin : str
        The basin code.
    """

    frame: pd.DataFrame
    files: tuple[StormFile, ...]
    basin: str

    @property
    def n_years(self) -> int:
        """Simulated years the catalogue covers: ``1000 * n_files``."""
        return YEARS_PER_FILE * len(self.files)

    def year_mapping(self) -> dict[str, Any]:
        """Return the year-mapping check of the catalogue (JSON-ready).

        Returns
        -------
        dict
            The rule, ``n_years``, the number of years with at least one
            storm, the overall simulation-year range and one entry per file
            (:meth:`StormFile.record`).
        """
        years = self.frame["year"].to_numpy(dtype=np.int64)
        return {
            "rule": TRACK_CONVERSION["year"],
            "n_years": self.n_years,
            "n_years_with_storms": int(np.unique(years).size),
            "simulation_year": [int(years.min()), int(years.max())],
            "files": [f.record() for f in self.files],
        }


def storm_member_files(directory: str | Path, basin: str = "NA") -> list[Path]:
    """Return the STORM 1,000-year files of a basin in a directory, by index.

    Parameters
    ----------
    directory : str or pathlib.Path
        Directory holding ``STORM_DATA_IBTRACS_<basin>_1000_YEARS_<k>.txt``
        files. Files of other basins and other files are ignored.
    basin : str, default "NA"
        Basin code.

    Returns
    -------
    list of pathlib.Path
        The files, ordered by ``k``.

    Raises
    ------
    CatalogueFormatError
        If ``basin`` is not a STORM basin, the directory does not exist or
        has no file of the basin, or the indices are not exactly ``0 …
        n - 1``, each once.
    """
    if basin not in BASIN_IDS:
        raise CatalogueFormatError(
            f"unknown STORM basin {basin!r}; expected one of {sorted(BASIN_IDS)}"
        )
    root = Path(directory)
    if not root.is_dir():
        raise CatalogueFormatError(f"{root}: not a directory of STORM files")
    keyed: list[tuple[int, Path]] = []
    for path in root.iterdir():
        match = _MEMBER.match(path.name)
        if match is not None and match.group("basin") == basin:
            keyed.append((int(match.group("index")), path))
    if not keyed:
        raise CatalogueFormatError(
            f"{root}: no STORM file of basin {basin} "
            f"({member_name(basin, 0)} ... {member_name(basin, 9)})"
        )
    indices = sorted(k for k, _ in keyed)
    if indices != list(range(len(indices))):
        raise CatalogueFormatError(
            f"{root}: the {basin} file indices are {indices}; expected 0 to "
            f"{len(indices) - 1}, each once, so that every simulation year "
            "1000 * k + year is defined exactly once"
        )
    return [path for _, path in sorted(keyed)]


def read_storm_file(path: str | Path, *, index: int, basin: str) -> pd.DataFrame:
    """Read and check one STORM file; return its rows with simulation years.

    Parameters
    ----------
    path : str or pathlib.Path
        A STORM 1,000-year text file.
    index : int
        Its file index ``k``.
    basin : str
        The basin every row must belong to.

    Returns
    -------
    pandas.DataFrame
        The columns of :class:`StormCatalogue.frame` for this file.

    Raises
    ------
    CatalogueFormatError
        If the file cannot be parsed, is empty, has the wrong number of
        columns, missing or non-finite values, non-integer codes, a row of
        another basin, a year outside ``[0, 1000)``, a month outside 1 to 12, a
        negative TC number or time step, a TC number of 1000 or more, a
        latitude outside ``[-90, 90]`` or longitude outside ``[0, 360]``, a
        negative wind, a non-positive pressure or radius, or a storm with
        repeated or non-consecutive time steps.
    """
    name = Path(path).name
    try:
        raw = pd.read_csv(
            path,
            sep=",",
            header=None,
            skipinitialspace=True,
            dtype=np.float64,
            keep_default_na=False,
            na_values=[""],
        )
    except pd.errors.EmptyDataError:
        raw = pd.DataFrame()
    except (ValueError, pd.errors.ParserError) as exc:
        raise CatalogueFormatError(f"{name}: cannot parse as STORM: {exc}") from exc
    if raw.empty:
        raise CatalogueFormatError(f"{name}: no track points")
    if raw.shape[1] != len(STORM_COLUMNS):
        raise CatalogueFormatError(
            f"{name}: {raw.shape[1]} columns, expected {len(STORM_COLUMNS)} "
            f"({', '.join(STORM_COLUMNS)}); cannot parse as STORM"
        )
    raw.columns = list(STORM_COLUMNS)
    values = raw.to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        bad = [c for c in STORM_COLUMNS if not np.isfinite(raw[c].to_numpy()).all()]
        raise CatalogueFormatError(f"{name}: missing or non-finite values in {bad}")
    frame = pd.DataFrame(index=raw.index)
    for column in _INT_COLUMNS:
        col = raw[column].to_numpy()
        if not (col == np.round(col)).all():
            raise CatalogueFormatError(f"{name}: column {column!r} is not integer")
        frame[column] = col.astype(np.int64)
    for column in ("lat", "lon", "pmin", "vmax_10min", "rmw", "dist_to_land"):
        frame[column] = raw[column].to_numpy(dtype=np.float64)

    def fail(what: str, mask: Any) -> None:  # noqa: ANN401
        rows = np.flatnonzero(np.asarray(mask))
        if rows.size:
            raise CatalogueFormatError(
                f"{name}: {what} ({rows.size} row(s), first at line {rows[0] + 1})"
            )

    expected_basin = BASIN_IDS[basin]
    fail(
        f"basin ID other than {expected_basin} ({basin})",
        frame["basin_id"] != expected_basin,
    )
    year = frame["year"].to_numpy()
    fail(
        f"year outside [0, {YEARS_PER_FILE}): the year column must restart at 0 "
        "in every file, else the mapping 1000 * k + year is ambiguous",
        (year < 0) | (year >= YEARS_PER_FILE),
    )
    fail("month outside 1-12", (frame["month"] < 1) | (frame["month"] > 12))
    fail("negative TC number or time step", (frame["tc"] < 0) | (frame["timestep"] < 0))
    fail(f"TC number of {_MAX_TC} or more", frame["tc"] >= _MAX_TC)
    fail("latitude outside [-90, 90]", frame["lat"].abs() > 90)
    fail(
        "longitude outside [0, 360] (STORM gives degrees east)",
        (frame["lon"] < 0) | (frame["lon"] > 360),
    )
    fail("negative wind", frame["vmax_10min"] < 0)
    fail("non-positive pressure or radius", (frame["pmin"] <= 0) | (frame["rmw"] <= 0))

    duplicated = frame.duplicated(subset=["year", "tc", "timestep"], keep=False)
    fail("repeated (year, tc, timestep)", duplicated)
    ordered = frame[["year", "tc", "timestep"]].to_numpy(dtype=np.int64)
    ordered = ordered[np.lexsort((ordered[:, 2], ordered[:, 1], ordered[:, 0]))]
    same_storm = (np.diff(ordered[:, :2], axis=0) == 0).all(axis=1)
    gap = same_storm & (np.diff(ordered[:, 2]) != 1)
    if gap.any():
        year0, tc0 = ordered[int(np.flatnonzero(gap)[0]), :2].tolist()
        raise CatalogueFormatError(
            f"{name}: storm year {year0} tc {tc0} has non-consecutive time steps"
        )

    offset = YEARS_PER_FILE * index
    frame["year"] = frame["year"] + offset
    frame["vmax"] = frame["vmax_10min"] / WIND_10MIN_TO_1MIN
    lon = frame["lon"].to_numpy()
    frame["lon"] = np.where(lon > 180.0, lon - 360.0, lon)
    frame["basin"] = basin
    frame["file_index"] = np.int64(index)
    frame["event_id"] = (
        f"STORM_{basin}_" + frame["year"].astype(str) + "_" + frame["tc"].astype(str)
    )
    return frame.reset_index(drop=True)


def read_storm_catalogue(
    directory: str | Path, *, basin: str = "NA", n_years: int | None = None
) -> StormCatalogue:
    """Read the STORM files of one basin and rebuild the simulation years.

    Parameters
    ----------
    directory : str or pathlib.Path
        Directory with ``STORM_DATA_IBTRACS_<basin>_1000_YEARS_<k>.txt``,
        ``k`` = 0 … n-1 (the dataset has n = 10).
    basin : str, default "NA"
        Basin code.
    n_years : int, optional
        If given, must equal ``1000 * n`` (the years the files cover), so
        that the rate ``1 / n_years`` is right.

    Returns
    -------
    StormCatalogue
        The table (files in index order) and the per-file record.

    Raises
    ------
    CatalogueFormatError
        See :func:`storm_member_files` and :func:`read_storm_file`; also if
        ``n_years`` does not match the files.
    """
    paths = storm_member_files(directory, basin)
    covered = YEARS_PER_FILE * len(paths)
    if n_years is not None and n_years != covered:
        raise CatalogueFormatError(
            f"n_years is {n_years}, but the {len(paths)} {basin} file(s) in "
            f"{directory} cover {covered} years ({YEARS_PER_FILE} each)"
        )
    frames: list[pd.DataFrame] = []
    files: list[StormFile] = []
    for index, path in enumerate(paths):
        frame = read_storm_file(path, index=index, basin=basin)
        local = frame["year"].to_numpy() - YEARS_PER_FILE * index
        files.append(
            StormFile(
                name=path.name,
                index=index,
                sha256=iris.file_digests(path)[1],
                n_rows=len(frame),
                n_storms=int(frame["event_id"].nunique()),
                year_min=int(local.min()),
                year_max=int(local.max()),
            )
        )
        frames.append(frame)
    return StormCatalogue(
        frame=pd.concat(frames, ignore_index=True),
        files=tuple(files),
        basin=basin,
    )


def storm_to_track(storm: pd.DataFrame) -> xr.Dataset:
    """Convert one storm's rows into a CLIMADA track dataset.

    The time axis, unit conversions and environmental pressure are the IRIS
    path's (:func:`.tracks.storm_to_track`); see the module docstring for the
    STORM-specific conversions.

    Parameters
    ----------
    storm : pandas.DataFrame
        The rows of one ``event_id`` of :attr:`StormCatalogue.frame`, in any
        order.

    Returns
    -------
    xarray.Dataset
        A track with the variables and attributes
        :class:`climada.hazard.TCTracks` expects; ``sid`` and ``name`` are
        the event ID, ``id_no`` is ``1000 * year + tc``.

    Raises
    ------
    CatalogueFormatError
        If the rows belong to more than one event, have fewer than two points
        (CLIMADA needs at least two), or their time steps repeat or are not
        consecutive.
    """
    ids = storm["event_id"].unique()
    if len(ids) != 1:
        raise CatalogueFormatError(f"rows of {len(ids)} events given: {ids[:4]}")
    sid = str(ids[0])
    storm = storm.sort_values("timestep", kind="stable").reset_index(drop=True)
    n = len(storm)
    if n < 2:
        raise CatalogueFormatError(f"{sid}: {n} track point(s); CLIMADA needs >= 2")
    steps = storm["timestep"].to_numpy(dtype=np.int64)
    if not (np.diff(steps) == 1).all():
        raise CatalogueFormatError(
            f"{sid}: time steps must be consecutive without repeats, got "
            f"{steps.tolist()[:10]}"
        )
    time = (
        tracks.TRACK_REF_TIME + steps.astype("timedelta64[h]") * tracks.TIMESTEP_HOURS
    )
    return xr.Dataset(
        data_vars={
            "time_step": ("time", np.full(n, float(tracks.TIMESTEP_HOURS))),
            "radius_max_wind": ("time", storm["rmw"].to_numpy() * tracks.KM_TO_NM),
            "max_sustained_wind": ("time", storm["vmax"].to_numpy() * tracks.MS_TO_KT),
            "central_pressure": ("time", storm["pmin"].to_numpy()),
            "environmental_pressure": ("time", np.full(n, tracks.ENV_PRESSURE_HPA)),
            "basin": ("time", storm["basin"].to_numpy().astype("<U2")),
        },
        coords={
            "time": ("time", time),
            "lat": ("time", storm["lat"].to_numpy()),
            "lon": ("time", storm["lon"].to_numpy()),
        },
        attrs={
            "max_sustained_wind_unit": "kn",
            "central_pressure_unit": "hPa",
            "name": sid,
            "sid": sid,
            "orig_event_flag": True,
            "data_provider": "STORM",
            "id_no": int(storm["year"].iloc[0]) * _MAX_TC + int(storm["tc"].iloc[0]),
            "category": int(storm["category"].max()),
        },
    )
