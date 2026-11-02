"""IRIS track catalogue: reading, proximity filter and conversion to CLIMADA.

This is the track half of the thesis ``src/CLIMADA/engine.py``:

1. :func:`read_iris_catalogue` reads the whitespace-separated IRIS text
   catalogue (e.g. the merged ``IRIS_NA_10000Y_merged.txt`` written by
   ``pixi run iris``) into a typed table, with one event ID per storm,
   ``<basin>_<year>_<tc>`` as in the thesis.
2. :func:`storms_near_locations` keeps the storms whose track passes within a
   radius of any location (great-circle distance), in the thesis row order.
3. :func:`storm_to_track` turns one storm's rows into the
   :class:`xarray.Dataset` that :class:`climada.hazard.TCTracks` holds, with
   the thesis unit conversions (m/s to knots, km to nautical miles).

The thesis checked nothing about the catalogue. This module raises
:class:`CatalogueFormatError` where the thesis code would have produced wrong
tracks silently: missing values, an event ID shared by two IRIS storms, a
storm spanning two years, duplicate or non-consecutive time steps.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
import xarray as xr
from numpy.typing import NDArray

__all__ = [
    "EARTH_RADIUS_KM",
    "ENV_PRESSURE_HPA",
    "IRIS_COLUMNS",
    "KM_TO_NM",
    "MS_TO_KT",
    "TIMESTEP_HOURS",
    "TRACK_REF_TIME",
    "CatalogueFormatError",
    "haversine_km",
    "read_iris_catalogue",
    "storm_to_track",
    "storms_near_locations",
]

#: 1 m/s in knots (thesis constant). CLIMADA's track wind unit is knots.
MS_TO_KT: Final[float] = 1.9438444924406
#: 1 km in nautical miles (thesis constant). CLIMADA's radii are in nm.
KM_TO_NM: Final[float] = 0.5399568034557
#: Hours between consecutive IRIS track points.
TIMESTEP_HOURS: Final[int] = 3
#: Earth radius of the thesis haversine distance.
EARTH_RADIUS_KM: Final[float] = 6371.0
#: Background environmental pressure given to every track point (thesis).
ENV_PRESSURE_HPA: Final[float] = 1013.0
#: Arbitrary anchor time of every track. The absolute date does not affect
#: CLIMADA's wind field, so all storms start at the same time (thesis).
TRACK_REF_TIME: Final[np.datetime64] = np.datetime64("2000-01-01T00:00")

#: Columns of an IRIS catalogue file, in file order (IRIS README).
IRIS_COLUMNS: Final[tuple[str, ...]] = (
    "tcid",
    "basin",
    "year",
    "tc",
    "month",
    "timestep",
    "lon",
    "lat",
    "vmax",
    "pmin",
    "rmw",
    "r18",
)
_INT_COLUMNS: Final[tuple[str, ...]] = ("tcid", "year", "tc", "month", "timestep")
_FLOAT_COLUMNS: Final[tuple[str, ...]] = ("lon", "lat", "vmax", "pmin", "rmw", "r18")


class CatalogueFormatError(ValueError):
    """The track catalogue does not have the layout this module expects."""


def read_iris_catalogue(path: str | Path) -> pd.DataFrame:
    """Read an IRIS track catalogue.

    The ``#`` header line is skipped and the columns are named from
    :data:`IRIS_COLUMNS`. ``NA`` is the North Atlantic basin code, so pandas'
    default missing-value parsing is off (as in the thesis).

    Parameters
    ----------
    path : str or pathlib.Path
        An IRIS text file: one row per track point, whitespace-separated, in
        the column order of the IRIS README.

    Returns
    -------
    pandas.DataFrame
        The columns of :data:`IRIS_COLUMNS` (integers as ``int64``, floats as
        ``float64``, ``basin`` as ``str``) plus ``event_id``,
        ``<basin>_<year>_<tc>``, in file order.

    Raises
    ------
    CatalogueFormatError
        If a row has the wrong number of fields, a value is missing or not a
        number, the catalogue is empty, or an ``event_id`` maps to more than
        one IRIS ``tcid`` (or the reverse).
    """
    # Columns are named only after counting them: with ``names=`` pandas would
    # turn surplus leading fields into an index and shift every column.
    try:
        frame = pd.read_csv(
            path,
            sep=r"\s+",
            comment="#",
            header=None,
            keep_default_na=False,
            na_values=[""],
            dtype={1: str},
        )
    except pd.errors.EmptyDataError:
        frame = pd.DataFrame()
    except (ValueError, pd.errors.ParserError) as exc:
        raise CatalogueFormatError(f"{path}: cannot parse as IRIS: {exc}") from exc
    if frame.empty:
        raise CatalogueFormatError(f"{path}: no track points")
    if frame.shape[1] != len(IRIS_COLUMNS):
        raise CatalogueFormatError(
            f"{path}: {frame.shape[1]} columns, expected {len(IRIS_COLUMNS)} "
            f"({' '.join(IRIS_COLUMNS)}); cannot parse as IRIS"
        )
    frame.columns = list(IRIS_COLUMNS)
    bad = [str(c) for c in frame.columns if frame[c].isna().to_numpy().any()]
    if bad:
        raise CatalogueFormatError(f"{path}: missing values in columns {bad}")
    for column in _INT_COLUMNS:
        if not pd.api.types.is_integer_dtype(frame[column]):
            raise CatalogueFormatError(f"{path}: column {column!r} is not integer")
        frame[column] = frame[column].astype(np.int64)
    for column in _FLOAT_COLUMNS:
        if not pd.api.types.is_numeric_dtype(frame[column]):
            raise CatalogueFormatError(f"{path}: column {column!r} is not numeric")
        frame[column] = frame[column].astype(np.float64)
    if not np.isfinite(frame[list(_FLOAT_COLUMNS)].to_numpy()).all():
        raise CatalogueFormatError(f"{path}: non-finite values")
    frame["event_id"] = (
        frame["basin"] + "_" + frame["year"].astype(str) + "_" + frame["tc"].astype(str)
    )
    tcids_per_event = frame.groupby("event_id")["tcid"].nunique()
    events_per_tcid = frame.groupby("tcid")["event_id"].nunique()
    shared = [
        *tcids_per_event.index.to_numpy()[tcids_per_event.to_numpy() > 1].tolist(),
        *events_per_tcid.index.to_numpy()[events_per_tcid.to_numpy() > 1].tolist(),
    ]
    if shared:
        raise CatalogueFormatError(
            f"{path}: event_id and tcid are not one-to-one, e.g. {shared[:4]}"
        )
    return frame


def haversine_km(
    lat: NDArray[np.float64], lon: NDArray[np.float64], lat0: float, lon0: float
) -> NDArray[np.float64]:
    """Great-circle distance from each point to one point (thesis formula).

    Parameters
    ----------
    lat, lon : numpy.ndarray
        Points, in degrees.
    lat0, lon0 : float
        The reference point, in degrees.

    Returns
    -------
    numpy.ndarray
        Distances in km on a sphere of radius :data:`EARTH_RADIUS_KM`.
    """
    rl1, rl2 = np.radians(lat), np.radians(lat0)
    dlat = np.radians(lat0 - lat)
    dlon = np.radians(lon0 - lon)
    a = np.sin(dlat / 2) ** 2 + np.cos(rl1) * np.cos(rl2) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))


def storms_near_locations(
    catalogue: pd.DataFrame,
    lats: Sequence[float],
    lons: Sequence[float],
    radius_km: float,
) -> list[str]:
    """Return the storms whose track passes within ``radius_km`` of a location.

    A storm is kept if any of its track points lies within ``radius_km``
    (inclusive) of any location. Only track points are tested, not the
    segments between them (thesis behaviour).

    Parameters
    ----------
    catalogue : pandas.DataFrame
        Output of :func:`read_iris_catalogue` (needs ``event_id``, ``lat``,
        ``lon``).
    lats, lons : sequence of float
        Location coordinates, in degrees.
    radius_km : float
        Proximity radius in km.

    Returns
    -------
    list of str
        Event IDs, sorted as strings (``NA_0_8`` < ``NA_1000_4`` <
        ``NA_10_0``). This is the row order of the thesis event-loss table,
        which the thesis noise layer's random stream depends on.

    Raises
    ------
    ValueError
        If ``lats`` and ``lons`` differ in length or are empty, or
        ``radius_km`` is not positive.
    """
    if len(lats) != len(lons) or len(lats) == 0:
        raise ValueError("lats and lons must be non-empty and of equal length")
    if not radius_km > 0:
        raise ValueError(f"radius_km must be > 0, got {radius_km}")
    track_lat = catalogue["lat"].to_numpy(dtype=np.float64)
    track_lon = catalogue["lon"].to_numpy(dtype=np.float64)
    # Loop over locations, not storms, so memory stays O(track points).
    min_dist = np.full(len(catalogue), np.inf)
    for lat0, lon0 in zip(lats, lons, strict=True):
        np.minimum(
            min_dist,
            haversine_km(track_lat, track_lon, float(lat0), float(lon0)),
            out=min_dist,
        )
    closest = pd.Series(min_dist, index=catalogue["event_id"]).groupby(level=0).min()
    keep = closest.index.to_numpy()[closest.to_numpy() <= radius_km].tolist()
    return sorted(str(e) for e in keep)


def storm_to_track(storm: pd.DataFrame) -> xr.Dataset:
    """Convert one storm's catalogue rows into a CLIMADA track dataset.

    Units are converted as in the thesis: ``vmax`` m/s to knots, ``rmw`` and
    ``r18`` km to nautical miles. ``r18`` (radius of gale-force winds) is
    CLIMADA's ``radius_oci``, the environmental pressure is
    :data:`ENV_PRESSURE_HPA`, and the time axis starts at
    :data:`TRACK_REF_TIME` with :data:`TIMESTEP_HOURS` between points.

    Parameters
    ----------
    storm : pandas.DataFrame
        The rows of one ``event_id`` from :func:`read_iris_catalogue`, in any
        order.

    Returns
    -------
    xarray.Dataset
        A track with the variables and attributes
        :class:`climada.hazard.TCTracks` expects; ``sid`` and ``name`` are
        the event ID.

    Raises
    ------
    CatalogueFormatError
        If the rows belong to more than one event, have fewer than two
        points (CLIMADA needs at least two), or their time steps repeat or are
        not consecutive.
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
    time = TRACK_REF_TIME + steps.astype("timedelta64[h]") * TIMESTEP_HOURS
    return xr.Dataset(
        data_vars={
            "time_step": ("time", np.full(n, float(TIMESTEP_HOURS))),
            "radius_max_wind": ("time", storm["rmw"].to_numpy() * KM_TO_NM),
            "radius_oci": ("time", storm["r18"].to_numpy() * KM_TO_NM),
            "max_sustained_wind": ("time", storm["vmax"].to_numpy() * MS_TO_KT),
            "central_pressure": ("time", storm["pmin"].to_numpy()),
            "environmental_pressure": ("time", np.full(n, ENV_PRESSURE_HPA)),
            "basin": ("time", storm["basin"].to_numpy()),
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
            "data_provider": "IRIS",
            "id_no": int(storm["tcid"].iloc[0]),
            "category": 0,
        },
    )
