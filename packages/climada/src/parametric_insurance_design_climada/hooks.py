"""Extension points of the track → wind → impact pipeline.

The pipeline (:func:`parametric_insurance_design_climada.pipeline.build_eventset`)
computes, for each batch of storms, a CLIMADA :class:`~climada.hazard.TropCyclone`
hazard at the location centroids and the impact on the locations. Two steps
are pluggable, so that the paper's realistic basis-risk inputs (SPEC §6.3,
Paper P-03) can be added without changing the pipeline:

:class:`IndexBuilder`
    Turns a batch into the ``index`` matrix. The default,
    :class:`CentroidWindIndex`, is the thesis index: the storm's maximum
    sustained wind at the location's centroid.
    :class:`~parametric_insurance_design_climada.cat_in_circle.CatInCircleIndex`
    is the cat-in-a-circle builder: it reads the tracks and the
    locations, not the wind field. The config's ``index`` section selects the
    builder (:func:`~parametric_insurance_design_climada.pipeline.make_index_builder`).
:class:`VulnerabilityDraws`
    Turns a batch and its base loss matrix into one loss matrix per draw
    (``draw_id``). The default, :class:`NoDraws`, keeps the base loss as the
    single draw 0.
    :class:`~parametric_insurance_design_climada.vulnerability.EmanuelVHalfDraws`
    recomputes the loss with the Emanuel ``v_half`` drawn from a
    prior per storm and draw; the config's ``vulnerability`` section selects
    it (:func:`~parametric_insurance_design_climada.pipeline.make_vulnerability_draws`).
    The pipeline expands the rows, gives each draw ``rate / n_draws``
    (SPEC §5) and appends the hook's
    :class:`~parametric_insurance_design.eventset.TransformRecord`.

Both are :class:`typing.Protocol` classes: any object with the right methods
works. Implementations must be deterministic given their inputs; randomness
comes only from the :class:`numpy.random.Generator` the pipeline passes on.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import numpy as np
import pandas as pd
from climada.entity import Exposures, ImpactFuncSet
from climada.hazard import TCTracks, TropCyclone
from numpy.typing import NDArray

from parametric_insurance_design.eventset import IndexDefinition, TransformRecord

__all__ = [
    "CentroidWindIndex",
    "HazardBatch",
    "IndexBuilder",
    "NoDraws",
    "VulnerabilityDraws",
]


@dataclass(frozen=True)
class HazardBatch:
    """One batch of storms after the CLIMADA hazard and impact steps.

    Rows of every matrix follow ``event_ids``; columns follow ``locations``.

    Attributes
    ----------
    event_ids : tuple of str
        The batch's event IDs, in row order.
    tracks : climada.hazard.TCTracks
        The tracks, one per event, in row order.
    hazard : climada.hazard.TropCyclone
        The wind hazard at the location centroids: centroid ``j`` is
        location ``j``.
    locations : pandas.DataFrame
        The EventSet ``locations`` table (``location_id``, ``lat``, ``lon``,
        ``value``, ``name`` and free columns).
    exposures : climada.entity.Exposures
        The locations as CLIMADA exposures, row ``j`` assigned to centroid
        ``j``.
    impact_functions : climada.entity.ImpactFuncSet
        The configured (base) impact functions.
    wind : numpy.ndarray
        Dense ``(n_events, n_locations)`` maximum sustained wind in m/s from
        ``hazard.intensity``; values below CLIMADA's intensity threshold are 0.
    """

    event_ids: tuple[str, ...]
    tracks: TCTracks
    hazard: TropCyclone
    locations: pd.DataFrame
    exposures: Exposures
    impact_functions: ImpactFuncSet
    wind: NDArray[np.float64]

    @property
    def n_events(self) -> int:
        """Number of events (matrix rows) in the batch."""
        return len(self.event_ids)

    @property
    def n_locations(self) -> int:
        """Number of locations (matrix columns)."""
        return len(self.locations)


@runtime_checkable
class IndexBuilder(Protocol):
    """Builds the ``index`` matrix of a batch.

    Implementations must return a finite ``float64`` array of shape
    ``(batch.n_events, batch.n_locations)``.
    """

    def describe(self, wind_field: str) -> IndexDefinition:
        """Return the EventSet index definition.

        Parameters
        ----------
        wind_field : str
            How the pipeline computed the wind field (CLIMADA version, wind
            model, thresholds), to quote in the definition.

        Returns
        -------
        IndexDefinition
            Definition and unit of the index values.
        """
        ...

    def parameters(self) -> dict[str, Any]:
        """Return the builder's parameters as a JSON object, for provenance."""
        ...

    def build(self, batch: HazardBatch) -> NDArray[np.float64]:
        """Return the index matrix of ``batch``."""
        ...


@runtime_checkable
class VulnerabilityDraws(Protocol):
    """Expands each event into ``n_draws`` loss draws (``draw_id``).

    Implementations must return a finite, non-negative ``float64`` array of
    shape ``(n_draws, batch.n_events, batch.n_locations)``; slice ``d`` holds
    the losses of ``draw_id == d``.
    """

    @property
    def n_draws(self) -> int:
        """Number of draws per event (>= 1)."""
        ...

    def record(self, *, n_filters_before: int) -> TransformRecord | None:
        """Return the transform record appended to the EventSet metadata.

        Parameters
        ----------
        n_filters_before : int
            Number of threshold filters already recorded (the pipeline
            applies none, so 0).

        Returns
        -------
        TransformRecord or None
            None when the hook changes nothing (no draws).
        """
        ...

    def losses(
        self,
        batch: HazardBatch,
        base_loss: NDArray[np.float64],
        rng: np.random.Generator | None,
    ) -> NDArray[np.float64]:
        """Return the loss draws of ``batch``.

        Parameters
        ----------
        batch : HazardBatch
            The batch.
        base_loss : numpy.ndarray
            ``(n_events, n_locations)`` losses with the base impact functions.
        rng : numpy.random.Generator or None
            The generator the caller passed to the pipeline. Batches are
            processed in row order, so the stream is consumed in a fixed
            order.

        Returns
        -------
        numpy.ndarray
            ``(n_draws, n_events, n_locations)`` losses.
        """
        ...


@dataclass(frozen=True)
class CentroidWindIndex:
    """The thesis index: maximum sustained wind at the location's centroid.

    The value is CLIMADA's ``TropCyclone`` intensity at the centroid placed on
    the location: the maximum 1-minute sustained wind at 10 m over the
    storm's lifetime, in m/s, with values below the intensity threshold set
    to 0.
    """

    def describe(self, wind_field: str) -> IndexDefinition:
        """Return the index definition, quoting ``wind_field``."""
        return IndexDefinition(
            definition=(
                "Maximum 1-minute sustained wind speed at 10 m above ground at "
                f"the asset over the storm's lifetime: {wind_field}, at a "
                "centroid placed on the asset; winds below the intensity "
                "threshold are stored as 0"
            ),
            unit="m/s",
        )

    def parameters(self) -> dict[str, Any]:
        """Return the builder's parameters (it has none beyond its kind)."""
        return {"kind": "centroid_wind"}

    def build(self, batch: HazardBatch) -> NDArray[np.float64]:
        """Return a copy of ``batch.wind``."""
        return np.array(batch.wind, dtype=np.float64, copy=True)


@dataclass(frozen=True)
class NoDraws:
    """No vulnerability draws: every event is one row with ``draw_id`` 0."""

    @property
    def n_draws(self) -> int:
        """Always 1."""
        return 1

    def record(self, *, n_filters_before: int) -> TransformRecord | None:
        """Return None: nothing to record."""
        return None

    def losses(
        self,
        batch: HazardBatch,
        base_loss: NDArray[np.float64],
        rng: np.random.Generator | None,
    ) -> NDArray[np.float64]:
        """Return ``base_loss`` as the single draw."""
        return np.asarray(base_loss, dtype=np.float64)[np.newaxis, :, :]
