"""Cat-in-a-circle index from storm tracks (MAR-26, SPEC §6.3 index (b)).

The industry-standard tropical-cyclone trigger: for each asset and storm, the
highest Saffir–Simpson category that the storm's **track** reaches within a
circle of radius ``r`` around the asset. Unlike the thesis index (the modelled
wind at the asset, :class:`~parametric_insurance_design_climada.hooks.CentroidWindIndex`),
it does not use the wind field that drives the loss, so index and loss are
decoupled as in a real contract (thesis issue M2).

How :class:`CatInCircleIndex` computes it, per storm and asset:

1. Take the storm's track points (centre position and maximum sustained wind)
   from the batch's CLIMADA tracks. Optionally interpolate the track
   linearly in time (latitude, longitude and wind) to ``track_step_hours``,
   so that a storm passing between two 3-hourly IRIS points is not missed by
   a small circle. The original points are kept exactly.
2. Keep the points within ``radius_km`` of the asset (inclusive), by the
   haversine distance of :func:`~parametric_insurance_design_climada.tracks.haversine_km`
   (sphere of 6,371 km, as the proximity filter).
3. Take the maximum wind of those points (0 if there are none).
4. ``metric="category"``: the number of breakpoints that this wind reaches,
   0 to ``len(breakpoints_kn)``. ``metric="max_wind"``: the wind itself, in
   m/s.

Because the category is monotone in the wind, the maximum category of the
points equals the category of their maximum wind.

**Wind and breakpoints.** IRIS ``vmax`` is the storm's maximum 1-minute
sustained surface wind in m/s: IRIS is calibrated on IBTrACS data of the US
agencies, which report 1-minute averages (Sparks and Toumi 2024, *Scientific
Data* 11:424, doi:10.1038/s41597-024-03250-y). The Saffir–Simpson Hurricane
Wind Scale is defined on the same 1-minute sustained wind, in knots, so no
averaging-period conversion is needed. The default breakpoints
:data:`SAFFIR_SIMPSON_KN` are the NHC scale's lower bounds of categories 1 to
5 (64, 83, 96, 113 and 137 kn; https://www.nhc.noaa.gov/aboutsshws.php),
the same values as CLIMADA's ``climada.hazard.tc_tracks.SAFFIR_SIM_CAT``.
Tropical storms and depressions are category 0 here. The tracks hold the wind
in knots (``vmax`` × :data:`~parametric_insurance_design_climada.tracks.MS_TO_KT`),
which are compared with the breakpoints directly; ``max_wind`` converts back
to m/s.

**Reference configuration.** Steinmann et al. (2023, *Environment Systems and
Decisions* 43:555–568) build cat-in-a-circle products in CLIMADA with radii
of 10 to 50 km and step payouts on Saffir–Simpson categories. This module
reproduces the index, not their product selection; it is realism, not a
novelty (``research/lit/notes.md`` O3).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final, Literal

import numpy as np
import xarray as xr
from numpy.typing import NDArray

from parametric_insurance_design.errors import ComponentConfigError
from parametric_insurance_design.eventset import IndexDefinition
from parametric_insurance_design_climada.tracks import (
    EARTH_RADIUS_KM,
    MS_TO_KT,
    haversine_km,
)

if TYPE_CHECKING:
    from parametric_insurance_design_climada.hooks import HazardBatch

__all__ = [
    "DEFAULT_TRACK_STEP_HOURS",
    "SAFFIR_SIMPSON_KN",
    "SAFFIR_SIMPSON_SOURCE",
    "CatInCircleIndex",
    "Metric",
    "category_of",
    "densify_track",
    "max_wind_within_radius",
]

#: Lower bounds of Saffir–Simpson categories 1-5, 1-minute sustained wind in
#: knots (NHC). Equal to ``climada.hazard.tc_tracks.SAFFIR_SIM_CAT[1:6]``.
SAFFIR_SIMPSON_KN: Final[tuple[float, ...]] = (64.0, 83.0, 96.0, 113.0, 137.0)
#: Where :data:`SAFFIR_SIMPSON_KN` comes from, for the provenance record.
SAFFIR_SIMPSON_SOURCE: Final[str] = (
    "NHC Saffir-Simpson Hurricane Wind Scale, 1-minute sustained wind, lower "
    "bounds of categories 1-5 in kn (https://www.nhc.noaa.gov/aboutsshws.php)"
)
#: Default time step (hours) the tracks are interpolated to.
DEFAULT_TRACK_STEP_HOURS: Final[float] = 0.5

#: What the index reports: the category or the wind.
Metric = Literal["category", "max_wind"]

_WIND_UNIT: Final[str] = "kn"


def category_of(
    wind_kn: NDArray[np.float64], breakpoints_kn: Sequence[float]
) -> NDArray[np.float64]:
    """Return the category of each wind: the number of breakpoints it reaches.

    Parameters
    ----------
    wind_kn : numpy.ndarray
        Winds in knots.
    breakpoints_kn : sequence of float
        Strictly increasing lower bounds of categories 1, 2, ...

    Returns
    -------
    numpy.ndarray
        ``float64`` categories, 0 to ``len(breakpoints_kn)``; a wind equal to
        a breakpoint is in the higher category.
    """
    bounds = np.asarray(breakpoints_kn, dtype=np.float64)
    wind = np.asarray(wind_kn, dtype=np.float64)
    return np.searchsorted(bounds, wind, side="right").astype(np.float64)


def densify_track(
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    wind: NDArray[np.float64],
    hours: NDArray[np.float64],
    step_hours: float | None,
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Interpolate a track linearly in time to at most ``step_hours`` apart.

    Each segment between consecutive points is split into
    ``ceil(dt / step_hours)`` equal parts; latitude, longitude and wind are
    interpolated linearly, as CLIMADA's ``TCTracks.equal_timestep`` does. The
    original points are kept exactly. Longitudes are unwrapped first, so a
    segment crossing the antimeridian takes the short way.

    Parameters
    ----------
    lat, lon, wind : numpy.ndarray
        The track points, in time order (degrees, degrees, any wind unit).
    hours : numpy.ndarray
        Time of each point, in hours (any origin), strictly increasing.
    step_hours : float or None
        Maximum time between interpolated points. None returns the points
        unchanged.

    Returns
    -------
    tuple of numpy.ndarray
        ``(lat, lon, wind)`` of the interpolated track.

    Raises
    ------
    ValueError
        If the arrays differ in length or the times do not increase.
    """
    lat, lon, wind, hours = (
        np.asarray(a, dtype=np.float64) for a in (lat, lon, wind, hours)
    )
    n = len(lat)
    if not len(lon) == len(wind) == len(hours) == n:
        raise ValueError("lat, lon, wind and hours must have the same length")
    if step_hours is None or n < 2:
        return lat, lon, wind
    dt = np.diff(hours)
    if not (dt > 0).all():
        raise ValueError("track times must increase strictly")
    parts = np.maximum(np.ceil(dt / step_hours), 1).astype(np.int64)
    segment = np.repeat(np.arange(n - 1), parts)
    first = np.cumsum(parts) - parts
    fraction = (np.arange(int(parts.sum())) - np.repeat(first, parts)) / np.repeat(
        parts, parts
    )
    lon_unwrapped = np.rad2deg(np.unwrap(np.deg2rad(lon)))

    def interp(values: NDArray[np.float64]) -> NDArray[np.float64]:
        start, end = values[segment], values[segment + 1]
        return np.append(start + fraction * (end - start), values[-1])

    return interp(lat), interp(lon_unwrapped), interp(wind)


def max_wind_within_radius(
    lat: NDArray[np.float64],
    lon: NDArray[np.float64],
    wind: NDArray[np.float64],
    location_lat: NDArray[np.float64],
    location_lon: NDArray[np.float64],
    radius_km: float,
) -> NDArray[np.float64]:
    """Return, per location, the maximum wind of the points within the radius.

    Parameters
    ----------
    lat, lon, wind : numpy.ndarray
        Track points (degrees, degrees, any wind unit).
    location_lat, location_lon : numpy.ndarray
        The locations, in degrees.
    radius_km : float
        Circle radius in km; a point at exactly ``radius_km`` is inside.

    Returns
    -------
    numpy.ndarray
        ``float64`` array with one value per location: the maximum wind of the
        track points within ``radius_km`` (haversine distance), or 0 if none
        is.
    """
    lat, lon, wind = (np.asarray(a, dtype=np.float64) for a in (lat, lon, wind))
    out = np.zeros(len(location_lat), dtype=np.float64)
    for j, (lat0, lon0) in enumerate(zip(location_lat, location_lon, strict=True)):
        inside = haversine_km(lat, lon, float(lat0), float(lon0)) <= radius_km
        if inside.any():
            out[j] = float(wind[inside].max())
    return out


def _track_arrays(
    track: xr.Dataset,
) -> tuple[
    NDArray[np.float64], NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]
]:
    """Return ``(lat, lon, wind in kn, hours)`` of a CLIMADA track."""
    unit = track.attrs.get("max_sustained_wind_unit")
    if unit != _WIND_UNIT:
        raise ValueError(
            f"track {track.attrs.get('sid')!r}: max_sustained_wind_unit is "
            f"{unit!r}, expected {_WIND_UNIT!r}"
        )
    time = np.asarray(track["time"].values)
    hours = (time - time[0]) / np.timedelta64(1, "h")
    return (
        np.asarray(track["lat"].values, dtype=np.float64),
        np.asarray(track["lon"].values, dtype=np.float64),
        np.asarray(track["max_sustained_wind"].values, dtype=np.float64),
        np.asarray(hours, dtype=np.float64),
    )


@dataclass(frozen=True)
class CatInCircleIndex:
    """Cat-in-a-circle index: the track's top category within ``radius_km``.

    An :class:`~parametric_insurance_design_climada.hooks.IndexBuilder`. See
    the module docstring for the method, the wind and the breakpoints.

    Parameters
    ----------
    radius_km : float
        Radius of the circle around each asset, in km (e.g. 30, 50, 100).
    metric : {"category", "max_wind"}
        ``"category"`` (default): the category, 0 to ``len(breakpoints_kn)``.
        ``"max_wind"``: the maximum 1-minute sustained wind of the track
        points within the circle, in m/s.
    breakpoints_kn : tuple of float
        Strictly increasing, positive lower bounds of categories 1, 2, ... in
        knots of 1-minute sustained wind. Default :data:`SAFFIR_SIMPSON_KN`.
        Recorded for both metrics; used only by ``"category"``.
    track_step_hours : float or None
        Interpolate the tracks to this time step (hours) before testing the
        distance. Default 0.5. None uses the track points as they are
        (3-hourly for IRIS: a fast storm moves 50 km or more between points,
        so a small circle can miss a storm that passes through it).

    Raises
    ------
    ComponentConfigError
        If a parameter is out of range.
    """

    radius_km: float
    metric: Metric = "category"
    breakpoints_kn: tuple[float, ...] = field(default=SAFFIR_SIMPSON_KN)
    track_step_hours: float | None = DEFAULT_TRACK_STEP_HOURS

    def __post_init__(self) -> None:
        """Validate the parameters."""
        if not (math.isfinite(self.radius_km) and self.radius_km > 0):
            raise ComponentConfigError(
                f"radius_km must be finite and > 0, got {self.radius_km}"
            )
        if self.metric not in ("category", "max_wind"):
            raise ComponentConfigError(
                f"metric must be 'category' or 'max_wind', got {self.metric!r}"
            )
        bounds = tuple(float(b) for b in self.breakpoints_kn)
        if (
            not bounds
            or not all(math.isfinite(b) and b > 0 for b in bounds)
            or any(b >= c for b, c in zip(bounds, bounds[1:], strict=False))
        ):
            raise ComponentConfigError(
                "breakpoints_kn must be non-empty, finite, positive and strictly "
                f"increasing, got {list(self.breakpoints_kn)}"
            )
        object.__setattr__(self, "breakpoints_kn", bounds)
        step = self.track_step_hours
        if step is not None and not (math.isfinite(step) and step > 0):
            raise ComponentConfigError(
                f"track_step_hours must be finite and > 0 or None, got {step}"
            )

    @property
    def is_saffir_simpson(self) -> bool:
        """Whether the breakpoints are the Saffir–Simpson scale's."""
        return self.breakpoints_kn == SAFFIR_SIMPSON_KN

    def _breakpoint_text(self) -> str:
        values = ", ".join(f"{b:g}" for b in self.breakpoints_kn)
        if self.is_saffir_simpson:
            return f"Saffir-Simpson breakpoints [{values}] kn (NHC)"
        return f"custom breakpoints [{values}] kn"

    def describe(self, wind_field: str) -> IndexDefinition:
        """Return the index definition.

        Parameters
        ----------
        wind_field : str
            Ignored: the index uses the tracks, not the modelled wind field.

        Returns
        -------
        IndexDefinition
            ``cat_in_circle(r=<radius> km, ...)`` followed by the method.
        """
        step = (
            "track points as given"
            if self.track_step_hours is None
            else f"track interpolated linearly to {self.track_step_hours:g} h steps"
        )
        head = (
            f"cat_in_circle(r={self.radius_km:g} km, metric={self.metric}): "
            "from the storm's track points within "
            f"{self.radius_km:g} km of the asset (haversine, sphere of "
            f"{EARTH_RADIUS_KM:g} km; {step}), "
        )
        wind = (
            "the track's maximum 1-minute sustained surface wind (IRIS vmax, "
            f"converted at {MS_TO_KT} kn per m/s)"
        )
        if self.metric == "category":
            definition = (
                f"{head}the highest category reached: the number of "
                f"{self._breakpoint_text()} that {wind} reaches; 0 below the "
                "first breakpoint or when no track point lies within the circle"
            )
            unit = "Saffir-Simpson category" if self.is_saffir_simpson else "category"
        else:
            definition = (
                f"{head}the highest {wind}, in m/s; 0 when no track point lies "
                "within the circle"
            )
            unit = "m/s"
        return IndexDefinition(definition=definition, unit=unit)

    def parameters(self) -> dict[str, Any]:
        """Return the builder's parameters, for the build provenance record."""
        return {
            "kind": "cat_in_circle",
            "radius_km": self.radius_km,
            "metric": self.metric,
            "breakpoints_kn": list(self.breakpoints_kn),
            "breakpoint_source": (
                SAFFIR_SIMPSON_SOURCE if self.is_saffir_simpson else "custom"
            ),
            "track_step_hours": self.track_step_hours,
            "distance": f"haversine, sphere of {EARTH_RADIUS_KM:g} km, inclusive",
            "wind": (
                "track max_sustained_wind (IRIS vmax, 1-minute sustained, "
                f"m/s x {MS_TO_KT} = kn)"
            ),
        }

    def build(self, batch: HazardBatch) -> NDArray[np.float64]:
        """Return the ``(n_events, n_locations)`` index matrix of ``batch``.

        Raises
        ------
        ValueError
            If the batch's tracks do not match its events, or a track's wind
            is not in knots.

        Notes
        -----
        ``max_wind`` divides the tracks' knots by
        :data:`~parametric_insurance_design_climada.tracks.MS_TO_KT`, which
        returns the IRIS m/s values up to floating-point rounding.
        """
        if len(batch.tracks.data) != batch.n_events:
            raise ValueError(
                f"{len(batch.tracks.data)} tracks for {batch.n_events} events"
            )
        location_lat = batch.locations["lat"].to_numpy(dtype=np.float64)
        location_lon = batch.locations["lon"].to_numpy(dtype=np.float64)
        wind_kn = np.zeros((batch.n_events, batch.n_locations), dtype=np.float64)
        for row, track in enumerate(batch.tracks.data):
            if str(track.attrs.get("sid")) != batch.event_ids[row]:
                raise ValueError(
                    f"track {row} is {track.attrs.get('sid')!r}, expected "
                    f"{batch.event_ids[row]!r}"
                )
            lat, lon, wind, hours = _track_arrays(track)
            lat, lon, wind = densify_track(
                lat, lon, wind, hours, self.track_step_hours
            )
            wind_kn[row] = max_wind_within_radius(
                lat, lon, wind, location_lat, location_lon, self.radius_km
            )
        if self.metric == "category":
            return category_of(wind_kn, self.breakpoints_kn)
        return wind_kn / MS_TO_KT
