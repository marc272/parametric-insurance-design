"""Track → wind → impact pipeline writing an EventSet (MAR-73, SPEC §7 F-07).

Port of the thesis ``src/CLIMADA/engine.py``. :func:`build_eventset` runs:

1. read the locations (:func:`read_locations`) and the IRIS catalogue
   (:func:`~parametric_insurance_design_climada.tracks.read_iris_catalogue`);
2. keep the storms whose track passes within ``proximity_km`` of any
   location, sorted by event ID as in the thesis;
3. in batches of ``batch_size`` storms: convert each storm to a CLIMADA track
   (thesis unit conversions), compute ``TropCyclone.from_tracks`` at one
   centroid per location, and ``ImpactCalc`` with the configured impact
   function;
4. build the index with an
   :class:`~parametric_insurance_design_climada.hooks.IndexBuilder`
   (default: wind at the centroid; the config's ``index`` section selects
   another, e.g. cat-in-a-circle, see :func:`make_index_builder`) and the
   loss draws with a
   :class:`~parametric_insurance_design_climada.hooks.VulnerabilityDraws`
   (default: none, ``draw_id`` 0; the config's ``vulnerability`` section
   selects Emanuel ``v_half`` draws, MAR-25, see
   :func:`make_vulnerability_draws`);
5. assemble the EventSet (schema v1): ``index`` from the builder, ``loss`` = impact,
   ``rate`` = ``1 / n_years`` (divided by the number of draws), ``year`` from
   IRIS.

Differences from the thesis, all deliberate:

* Storms with fewer than two track points (CLIMADA needs two) were skipped
  silently. They are still skipped, but listed in :attr:`PipelineResult.skipped`
  and in the EventSet's provenance record.
* Locations keep the order given; the thesis sorted them by asset ID (the
  same order for ``A1`` … ``A9``).
* Each location is assigned to its own centroid explicitly, instead of by
  CLIMADA's nearest-centroid search (the same result for distinct
  coordinates).
* The distance-to-coast filter is off by default (see
  :class:`~parametric_insurance_design_climada.config.WindConfig`).

**Provenance.** ``hazard.release`` and the catalogue checksum come from the
IRIS manifest (``iris_manifest.json``, MAR-72). The metadata's first
:class:`~parametric_insurance_design.eventset.TransformRecord`, named
:data:`BUILD_RECORD_NAME`, records the CLIMADA version, the catalogue
checksum and counts, the proximity radius, the skipped storms, the unit
conversions, the wind parameters and the impact function (parameters and its
intensity-damage table). It is part of :meth:`EventSet.content_hash`, so two
builds with different CLIMADA versions or impact functions never share a
checksum. ``batch_size`` is left out: it does not change the data.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Final, cast

import numpy as np
import pandas as pd
import yaml
from climada.engine.impact_calc import ImpactCalc
from climada.entity import Exposures, ImpactFuncSet
from climada.entity.impact_funcs.trop_cyclone import ImpfTropCyclone
from climada.hazard import Centroids, TCTracks, TropCyclone
from numpy.typing import NDArray

from parametric_insurance_design.errors import ParametricInsuranceDesignError
from parametric_insurance_design.eventset import (
    LOCATIONS_FILE,
    EventSet,
    EventSetMetadata,
    HazardSource,
    LossDefinition,
    Provenance,
    TransformRecord,
)
from parametric_insurance_design_climada import iris, tracks
from parametric_insurance_design_climada.cat_in_circle import CatInCircleIndex
from parametric_insurance_design_climada.config import (
    CatInCircleIndexConfig,
    EmanuelVHalfDrawsConfig,
    LocationsConfig,
    PipelineConfig,
    PipelineConfigError,
    check_circle_radius,
)
from parametric_insurance_design_climada.hooks import (
    CentroidWindIndex,
    HazardBatch,
    IndexBuilder,
    NoDraws,
    VulnerabilityDraws,
)

__all__ = [
    "BUILD_RECORD_NAME",
    "HAZARD_TYPE",
    "PRODUCER",
    "PipelineError",
    "PipelineResult",
    "SkippedStorm",
    "build_eventset",
    "make_impact_function",
    "make_index_builder",
    "make_vulnerability_draws",
    "read_locations",
]

logger = logging.getLogger(__name__)

#: Name of the provenance record the pipeline writes first.
BUILD_RECORD_NAME: Final[str] = "climada_tc_impact"
#: Distribution name written as the EventSet producer.
PRODUCER: Final[str] = "parametric-insurance-design-climada"
#: CLIMADA hazard type of tropical cyclones.
HAZARD_TYPE: Final[str] = "TC"
_LOCATION_COLUMNS: Final[tuple[str, ...]] = ("location_id", "lat", "lon", "value")


class PipelineError(ParametricInsuranceDesignError, RuntimeError):
    """The pipeline cannot produce a consistent EventSet from its inputs."""


@dataclass(frozen=True)
class SkippedStorm:
    """A storm within the proximity radius that the pipeline could not model.

    Attributes
    ----------
    event_id : str
        The storm.
    reason : str
        Why it was skipped.
    """

    event_id: str
    reason: str


@dataclass(frozen=True)
class PipelineResult:
    """Output of :func:`build_eventset`.

    Attributes
    ----------
    eventset : EventSet
        The EventSet (not yet written).
    n_storms_catalogue : int
        Storms in the catalogue.
    n_storms_near : int
        Storms within ``proximity_km`` of a location.
    skipped : tuple of SkippedStorm
        Storms within the radius that have no row (zero-loss mass, rates not
        rescaled).
    seconds : float
        Wall-clock runtime of the build.
    """

    eventset: EventSet
    n_storms_catalogue: int
    n_storms_near: int
    skipped: tuple[SkippedStorm, ...]
    seconds: float


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


def read_locations(source: LocationsConfig) -> pd.DataFrame:
    """Read the asset locations.

    Parameters
    ----------
    source : LocationsConfig
        An EventSet directory or a YAML file.

    Returns
    -------
    pandas.DataFrame
        The ``locations`` table, in the given order, with its free columns.

    Raises
    ------
    PipelineConfigError
        If the source cannot be read, lacks a required column, repeats a
        ``location_id``, or has a coordinate or value out of range.
    """
    path = source.path
    if source.eventset is not None:
        try:
            frame = EventSet.from_parquet(path).locations.copy()
        except (OSError, ValueError) as exc:
            raise PipelineConfigError(
                f"cannot read locations from {path}: {exc}"
            ) from exc
    else:
        try:
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise PipelineConfigError(f"cannot read locations {path}: {exc}") from exc
        rows = data.get("locations") if isinstance(data, dict) else None
        if not isinstance(rows, list) or not rows:
            raise PipelineConfigError(
                f"{path}: expected a non-empty top-level 'locations' list"
            )
        frame = pd.DataFrame(rows)
    missing = [c for c in (*_LOCATION_COLUMNS, "name") if c not in frame.columns]
    if missing:
        raise PipelineConfigError(f"{path}: locations lack columns {missing}")
    frame["location_id"] = frame["location_id"].astype(str)
    if frame["location_id"].duplicated().any():
        raise PipelineConfigError(f"{path}: location_id values repeat")
    try:
        lat, lon, value = (
            frame[c].to_numpy(dtype=np.float64) for c in ("lat", "lon", "value")
        )
    except (TypeError, ValueError) as exc:
        raise PipelineConfigError(f"{path}: lat, lon and value: {exc}") from exc
    if not np.isfinite(np.concatenate([lat, lon, value])).all():
        raise PipelineConfigError(f"{path}: lat, lon and value must be finite")
    if (np.abs(lat) > 90).any() or (np.abs(lon) > 180).any() or (value < 0).any():
        raise PipelineConfigError(
            f"{path}: lat must be in [-90, 90], lon in [-180, 180], value >= 0"
        )
    return frame.reset_index(drop=True)


def make_impact_function(config: PipelineConfig) -> ImpfTropCyclone:
    """Build the configured impact function.

    Parameters
    ----------
    config : PipelineConfig
        The pipeline config.

    Returns
    -------
    climada.entity.impact_funcs.trop_cyclone.ImpfTropCyclone
        A ``TC`` impact function with ID ``config.impact_function.impf_id``,
        on CLIMADA's default intensity grid (0 to 120 m/s in steps of 5).
    """
    impf = config.impact_function
    return ImpfTropCyclone.from_emanuel_usa(
        impf_id=impf.impf_id,
        v_thresh=impf.v_thresh,
        v_half=impf.v_half,
        scale=impf.scale,
    )


def make_index_builder(config: PipelineConfig) -> IndexBuilder:
    """Build the index builder the config's ``index`` section selects.

    Parameters
    ----------
    config : PipelineConfig
        The pipeline config.

    Returns
    -------
    IndexBuilder
        :class:`~parametric_insurance_design_climada.hooks.CentroidWindIndex`
        for ``kind: centroid_wind`` (the default),
        :class:`~parametric_insurance_design_climada.cat_in_circle.CatInCircleIndex`
        for ``kind: cat_in_circle``.
    """
    index = config.index
    if isinstance(index, CatInCircleIndexConfig):
        return index.builder()
    return CentroidWindIndex()


def make_vulnerability_draws(
    config: PipelineConfig, *, record_seed: bool = True
) -> VulnerabilityDraws:
    """Build the vulnerability draws the config's ``vulnerability`` section selects.

    Parameters
    ----------
    config : PipelineConfig
        The pipeline config.
    record_seed : bool, optional
        Record ``vulnerability.seed`` in the draws' transform record (default).
        False when the caller passes its own generator.

    Returns
    -------
    VulnerabilityDraws
        :class:`~parametric_insurance_design_climada.hooks.NoDraws` for
        ``kind: none`` (the default),
        :class:`~parametric_insurance_design_climada.vulnerability.EmanuelVHalfDraws`
        for ``kind: emanuel_v_half``.

    Raises
    ------
    VulnerabilityError
        If the prior cannot be loaded (e.g. CLIMADA's calibration file has
        another checksum).
    """
    draws = config.vulnerability
    if isinstance(draws, EmanuelVHalfDrawsConfig):
        return draws.draws(config.impact_function, record_seed=record_seed)
    return NoDraws()


def _hazard_release(
    config: PipelineConfig, sha256: str, basins: Sequence[str]
) -> tuple[str, str]:
    """Return ``(release, source key)`` for the catalogue."""
    manifest = iris.load_manifest()
    if sha256 == manifest.merged.sha256:
        if list(basins) != [manifest.basin]:
            raise PipelineError(
                f"catalogue basins {list(basins)} differ from the manifest's "
                f"{manifest.basin!r}"
            )
        release = (
            f"{manifest.dataset}, {manifest.version}, collection "
            f"{manifest.collection_doi} (main dataset {manifest.archive.doi}), "
            f"basin {manifest.basin}, merged catalogue {manifest.merged.name}"
        )
        return config.hazard_release or release, manifest.merged.name
    if config.hazard_release is None:
        raise PipelineConfigError(
            f"the catalogue {config.catalogue.name} (sha256 {sha256}) is not the "
            f"pinned IRIS merged file {manifest.merged.name}; set hazard_release "
            "in the config to describe it"
        )
    return config.hazard_release, config.catalogue.name


def _location_checksum(source: LocationsConfig) -> tuple[str, str]:
    """Return ``(source key, sha256)`` of the locations input file."""
    if source.eventset is not None:
        path = source.eventset / LOCATIONS_FILE
        key = f"{source.eventset.name}/{LOCATIONS_FILE}"
    else:
        assert source.yaml is not None
        path, key = source.yaml, source.yaml.name
    return key, iris.file_digests(path)[1]


def _check_impf_column(locations: pd.DataFrame, impf_id: int) -> None:
    column = f"impf_{HAZARD_TYPE}"
    if column in locations.columns:
        values = set(locations[column].tolist())
        if values != {impf_id}:
            raise PipelineConfigError(
                f"locations column {column} holds {sorted(values)}, but the "
                f"pipeline applies impact function {impf_id} to every location"
            )


# --------------------------------------------------------------------------
# CLIMADA steps
# --------------------------------------------------------------------------


def _exposures(locations: pd.DataFrame, impf_id: int) -> Exposures:
    """Locations as exposures, row ``j`` assigned to centroid ``j``."""
    n = len(locations)
    return Exposures(
        pd.DataFrame(
            {
                "latitude": locations["lat"].to_numpy(dtype=np.float64),
                "longitude": locations["lon"].to_numpy(dtype=np.float64),
                "value": locations["value"].to_numpy(dtype=np.float64),
                f"impf_{HAZARD_TYPE}": np.full(n, impf_id, dtype=np.int64),
                f"centr_{HAZARD_TYPE}": np.arange(n, dtype=np.int64),
            }
        )
    )


def _wind_kwargs(config: PipelineConfig) -> dict[str, Any]:
    wind = config.wind
    kwargs: dict[str, Any] = {
        "model": wind.model,
        "intensity_thres": wind.intensity_thres,
        "max_dist_eye_km": wind.max_dist_eye_km,
        "max_latitude": wind.max_latitude,
    }
    if wind.max_dist_inland_km is None:
        kwargs["ignore_distance_to_coast"] = True
    else:
        kwargs["ignore_distance_to_coast"] = False
        kwargs["max_dist_inland_km"] = wind.max_dist_inland_km
    return kwargs


def _wind_field_text(config: PipelineConfig, climada_version: str) -> str:
    wind = config.wind
    inland = (
        "no distance-to-coast cut-off"
        if wind.max_dist_inland_km is None
        else f"max {wind.max_dist_inland_km:g} km inland"
    )
    return (
        f"CLIMADA {climada_version} TropCyclone.from_tracks intensity (wind model "
        f"{wind.model}, intensity threshold {wind.intensity_thres:g} m/s, max "
        f"{wind.max_dist_eye_km:g} km from the eye, max latitude "
        f"{wind.max_latitude:g}, {inland})"
    )


def _check_matrix(
    name: str, array: object, shape: tuple[int, ...], *, non_negative: bool
) -> NDArray[np.float64]:
    matrix = np.asarray(array, dtype=np.float64)
    if matrix.shape != shape:
        raise PipelineError(f"{name} has shape {matrix.shape}, expected {shape}")
    if not np.isfinite(matrix).all():
        raise PipelineError(f"{name} holds non-finite values")
    if non_negative and (matrix < 0).any():
        raise PipelineError(f"{name} holds negative values")
    return matrix


def _run_batch(
    event_ids: list[str],
    storms: dict[str, pd.DataFrame],
    *,
    config: PipelineConfig,
    locations: pd.DataFrame,
    centroids: Centroids,
    exposures: Exposures,
    impact_functions: ImpactFuncSet,
    index_builder: IndexBuilder,
    vulnerability: VulnerabilityDraws,
    rng: np.random.Generator | None,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return ``(index, loss draws)`` of one batch of modelled storms."""
    track_data = TCTracks([tracks.storm_to_track(storms[e]) for e in event_ids])
    hazard = cast(
        TropCyclone,
        TropCyclone.from_tracks(
            track_data, centroids=centroids, **_wind_kwargs(config)
        ),
    )
    if [str(name) for name in hazard.event_name] != event_ids:
        raise PipelineError("CLIMADA returned the events in another order")
    shape = (len(event_ids), len(locations))
    wind = _check_matrix("wind", hazard.intensity.toarray(), shape, non_negative=True)
    impact = ImpactCalc(exposures, impact_functions, hazard).impact(
        save_mat=True, assign_centroids=False
    )
    base_loss = _check_matrix(
        "loss", impact.imp_mat.toarray(), shape, non_negative=True
    )
    batch = HazardBatch(
        event_ids=tuple(event_ids),
        tracks=track_data,
        hazard=hazard,
        locations=locations,
        exposures=exposures,
        impact_functions=impact_functions,
        wind=wind,
    )
    index = _check_matrix(
        "index", index_builder.build(batch), shape, non_negative=False
    )
    draws = _check_matrix(
        "loss draws",
        vulnerability.losses(batch, base_loss, rng),
        (vulnerability.n_draws, *shape),
        non_negative=True,
    )
    return index, draws


# --------------------------------------------------------------------------
# Build
# --------------------------------------------------------------------------


def _scenario_text(
    config: PipelineConfig,
    *,
    n_locations: int,
    n_events: int,
    n_zero: int,
    n_skipped: int,
    n_draws: int,
    has_draws: bool,
) -> str:
    impf = config.impact_function
    if has_draws:
        draws = (
            f"{n_draws} vulnerability draws per storm (draw_id 0-{n_draws - 1}) "
            "replace these losses; the last metadata transform describes them."
        )
    else:
        draws = "No noise or vulnerability draws (draw_id 0)."
    skipped = (
        f" {n_skipped} storm(s) within the radius have fewer than two track "
        "points and no row (zero-loss mass)."
        if n_skipped
        else ""
    )
    return (
        f"IRIS {config.n_years:,}-year synthetic tropical-cyclone catalogue "
        f"for {n_locations} locations. One row per storm whose track passes "
        f"within {config.proximity_km:g} km of any location ({n_events:,} "
        f"storms, {n_zero:,} of them with zero index and loss at every "
        "location); years without such a storm are implicit zero-loss years."
        f"{skipped} Losses from CLIMADA's Emanuel (2011) USA tropical-cyclone "
        f"impact function (v_thresh {impf.v_thresh:g} m/s, v_half "
        f"{impf.v_half:g} m/s, scale {impf.scale:g}). {draws}"
    )


def build_eventset(
    config: PipelineConfig,
    *,
    index_builder: IndexBuilder | None = None,
    vulnerability: VulnerabilityDraws | None = None,
    rng: np.random.Generator | None = None,
    created_at: datetime | None = None,
) -> PipelineResult:
    """Run the track → wind → impact pipeline and return the EventSet.

    Parameters
    ----------
    config : PipelineConfig
        The pipeline config (paths absolute or relative to the working
        directory).
    index_builder : IndexBuilder, optional
        Builds the index matrix. Default: the one ``config.index`` selects
        (:func:`make_index_builder`; :class:`CentroidWindIndex` unless the
        config says otherwise). A builder passed here replaces the config's;
        the build record holds the parameters of the one used.
    vulnerability : VulnerabilityDraws, optional
        Builds the loss draws. Default: the one ``config.vulnerability``
        selects (:func:`make_vulnerability_draws`; :class:`NoDraws` unless the
        config says otherwise). A hook passed here replaces the config's.
    rng : numpy.random.Generator, optional
        Passed to ``vulnerability``; unused by :class:`NoDraws`. If None and
        the config selects draws, the pipeline creates
        ``numpy.random.default_rng(config.vulnerability.seed)``. A generator
        passed here replaces the config's seed, and the draws record then
        holds ``seed: null``.
    created_at : datetime.datetime, optional
        Provenance timestamp (timezone-aware). Default: now (UTC).

    Returns
    -------
    PipelineResult
        The EventSet, the storm counts, the skipped storms and the runtime.

    Raises
    ------
    PipelineConfigError
        If the locations are invalid, the catalogue is not the pinned IRIS
        file and ``hazard_release`` is not set, or a cat-in-a-circle radius
        exceeds half of ``proximity_km``.
    PipelineError
        If a catalogue year lies outside ``[0, n_years)``, no storm can be
        modelled, or a hook returns a malformed matrix.
    CatalogueFormatError
        If the catalogue is malformed.
    VulnerabilityError
        If the configured prior cannot be loaded, or a draws hook gets no
        generator.
    """
    start = time.perf_counter()
    index_builder = (
        index_builder if index_builder is not None else make_index_builder(config)
    )
    if isinstance(index_builder, CatInCircleIndex):
        try:
            check_circle_radius(index_builder.radius_km, config.proximity_km)
        except ValueError as exc:
            raise PipelineConfigError(str(exc)) from exc
    if vulnerability is None:
        vulnerability = make_vulnerability_draws(config, record_seed=rng is None)
        draws_config = config.vulnerability
        if rng is None and isinstance(draws_config, EmanuelVHalfDrawsConfig):
            rng = np.random.default_rng(draws_config.seed)
    n_draws = int(vulnerability.n_draws)
    if n_draws < 1:
        raise PipelineError(f"n_draws must be >= 1, got {n_draws}")
    climada_version = version("climada")

    locations = read_locations(config.locations)
    _check_impf_column(locations, config.impact_function.impf_id)
    location_key, location_sha = _location_checksum(config.locations)

    catalogue_sha = iris.file_digests(config.catalogue)[1]
    catalogue = tracks.read_iris_catalogue(config.catalogue)
    release, catalogue_key = _hazard_release(
        config, catalogue_sha, sorted(catalogue["basin"].unique().tolist())
    )
    years = catalogue["year"].to_numpy()
    if years.min() < 0 or years.max() >= config.n_years:
        raise PipelineError(
            f"catalogue years span [{years.min()}, {years.max()}], outside "
            f"[0, n_years) with n_years={config.n_years}"
        )
    n_storms = int(catalogue["event_id"].nunique())

    near = tracks.storms_near_locations(
        catalogue,
        locations["lat"].tolist(),
        locations["lon"].tolist(),
        config.proximity_km,
    )
    logger.info(
        "%d of %d storms pass within %g km of a location",
        len(near),
        n_storms,
        config.proximity_km,
    )
    subset = catalogue[catalogue["event_id"].isin(near)]
    storms: dict[str, pd.DataFrame] = {
        str(k): cast(pd.DataFrame, g) for k, g in subset.groupby("event_id", sort=False)
    }
    first_year = subset.groupby("event_id")["year"].first()
    year_of = {str(e): int(y) for e, y in first_year.items()}

    skipped: list[SkippedStorm] = []
    modelled: list[str] = []
    for event_id in near:
        n_points = len(storms[event_id])
        if n_points < 2:
            skipped.append(
                SkippedStorm(
                    event_id,
                    f"{n_points} track point(s); CLIMADA needs at least two",
                )
            )
        else:
            modelled.append(event_id)
    for storm in skipped:
        logger.warning("skipped %s: %s", storm.event_id, storm.reason)
    if not modelled:
        raise PipelineError(
            f"no storm with at least two track points passes within "
            f"{config.proximity_km:g} km of a location"
        )

    impf = make_impact_function(config)
    impact_functions = ImpactFuncSet([impf])
    exposures = _exposures(locations, config.impact_function.impf_id)
    centroids = Centroids(
        lat=locations["lat"].to_numpy(dtype=np.float64),
        lon=locations["lon"].to_numpy(dtype=np.float64),
    )
    index_parts: list[NDArray[np.float64]] = []
    loss_parts: list[NDArray[np.float64]] = []
    n_batches = -(-len(modelled) // config.batch_size)
    for number, first in enumerate(range(0, len(modelled), config.batch_size), 1):
        batch_ids = modelled[first : first + config.batch_size]
        logger.info("batch %d/%d (%d storms)", number, n_batches, len(batch_ids))
        index, draws = _run_batch(
            batch_ids,
            storms,
            config=config,
            locations=locations,
            centroids=centroids,
            exposures=exposures,
            impact_functions=impact_functions,
            index_builder=index_builder,
            vulnerability=vulnerability,
            rng=rng,
        )
        index_parts.append(index)
        loss_parts.append(draws)

    n_locations = len(locations)
    index_all = np.concatenate(index_parts, axis=0)
    # (n_draws, n_events, n_loc) -> event-major rows: event 0 draws 0..n-1, ...
    loss_all = np.concatenate(loss_parts, axis=1).transpose(1, 0, 2)
    loss_rows = loss_all.reshape(len(modelled) * n_draws, n_locations)
    index_rows = np.repeat(index_all, n_draws, axis=0)
    events = pd.DataFrame(
        {
            "event_id": np.repeat(np.array(modelled, dtype=object), n_draws),
            "year": np.repeat(
                np.array([year_of[e] for e in modelled], dtype=np.int64), n_draws
            ),
            "rate": np.full(len(modelled) * n_draws, 1.0 / config.n_years / n_draws),
            "draw_id": np.tile(np.arange(n_draws, dtype=np.int64), len(modelled)),
            "scenario_id": config.scenario_id,
        }
    )
    n_zero = int(((index_all == 0) & (loss_all == 0).all(axis=1)).all(axis=1).sum())

    build_record = TransformRecord(
        name=BUILD_RECORD_NAME,
        function=f"{__name__}.build_eventset",
        version=version(PRODUCER),
        n_filters_before=0,
        parameters={
            "climada_version": climada_version,
            "catalogue": {
                "file": catalogue_key,
                "sha256": catalogue_sha,
                "n_storms": n_storms,
                "n_track_points": len(catalogue),
            },
            "proximity_km": config.proximity_km,
            "n_storms_within_radius": len(near),
            "skipped_storms": [
                {"event_id": s.event_id, "reason": s.reason} for s in skipped
            ],
            "event_order": "event_id sorted as strings (thesis order)",
            "track_conversion": {
                "vmax_m_s_to_kn": tracks.MS_TO_KT,
                "rmw_r18_km_to_nm": tracks.KM_TO_NM,
                "radius_oci": "r18",
                "timestep_hours": tracks.TIMESTEP_HOURS,
                "environmental_pressure_hpa": tracks.ENV_PRESSURE_HPA,
            },
            "wind": config.wind.model_dump(mode="json"),
            "impact_function": {
                **config.impact_function.model_dump(mode="json"),
                "haz_type": HAZARD_TYPE,
                "name": str(impf.name),
                "intensity_unit": str(impf.intensity_unit),
                "intensity": np.asarray(impf.intensity, dtype=np.float64).tolist(),
                "mdd": np.asarray(impf.mdd, dtype=np.float64).tolist(),
                "paa": np.asarray(impf.paa, dtype=np.float64).tolist(),
            },
            "index": index_builder.parameters(),
            "n_draws": n_draws,
        },
    )
    transforms = [build_record]
    draw_record = vulnerability.record(n_filters_before=0)
    if draw_record is not None:
        transforms.append(draw_record)

    metadata = EventSetMetadata(
        hazard=HazardSource(name="IRIS", release=release),
        index=index_builder.describe(_wind_field_text(config, climada_version)),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=config.n_years,
        scenario=config.scenario
        or _scenario_text(
            config,
            n_locations=n_locations,
            n_events=len(modelled),
            n_zero=n_zero,
            n_skipped=len(skipped),
            n_draws=n_draws,
            has_draws=not isinstance(vulnerability, NoDraws),
        ),
        provenance=Provenance(
            producer=PRODUCER,
            producer_version=version(PRODUCER),
            created_at=created_at or datetime.now(UTC),
            source_checksums={
                catalogue_key: f"sha256:{catalogue_sha}",
                location_key: f"sha256:{location_sha}",
            },
        ),
        licence=config.licence,
        transforms=tuple(transforms),
    )
    eventset = EventSet(
        events=events,
        locations=locations,
        index=index_rows,
        loss=loss_rows,
        metadata=metadata,
    )
    return PipelineResult(
        eventset=eventset,
        n_storms_catalogue=n_storms,
        n_storms_near=len(near),
        skipped=tuple(skipped),
        seconds=time.perf_counter() - start,
    )
