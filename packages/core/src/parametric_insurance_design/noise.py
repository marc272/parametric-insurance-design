"""Thesis noise layer: lognormal loss noise on copies of each event (SPEC §4.2).

The thesis baseline of SPEC §6.3: with the wind at the asset as the index,
this noise layer is the only mismatch between index and loss. SPEC §6.3 keeps
it for comparison with the thesis, next to the vulnerability draws of the
CLIMADA adapter. It is supported, and the experiment runner applies it (the
config's ``noise`` section). It is off the package's top level (ADR 0004,
Q2): the package's ``__init__`` doesn't import it, so import it by its full
name, ``parametric_insurance_design.noise``.

Owner: MAR-10. A bit-identical port of the thesis
``add_noise_to_asset_losses`` (``src/utils/data_processing.py`` in
``parametric-insurance-framework``) for parity (F-06). Each event row is
repeated ``n_copies`` times (``draw_id = 0 .. n_copies - 1``, event-major order
as in the thesis), and each location's loss is multiplied by a mean-one
lognormal factor. The index is unchanged.

Rates: each copy gets ``rate / n_copies``, so the copies of an event keep its
total rate (thesis: ``1 / (Y * n_copies)`` per row). This is the draw-row rate
convention of SPEC §5.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Sequence
from importlib.metadata import version
from typing import Any, Literal, get_args

import numpy as np

from parametric_insurance_design.errors import ComponentConfigError, InputMismatchError
from parametric_insurance_design.eventset import EventSet, TransformRecord

__all__ = ["TRANSFORM_NAME", "NoiseKind", "add_noise"]

NoiseKind = Literal["homoscedastic", "heteroscedastic"]
"""Constant relative noise, or noise growing with the index between bounds."""

TRANSFORM_NAME = "noise"
"""``TransformRecord.name`` of the records written by :func:`add_noise`."""

_KINDS: tuple[str, ...] = get_args(NoiseKind)
_VERSION: str = version("parametric-insurance-design")


def add_noise(
    eventset: EventSet,
    *,
    level: float,
    kind: NoiseKind,
    n_copies: int,
    rng: np.random.Generator,
    bounds: tuple[float, float] = (20.0, 70.0),
    location_ids: Sequence[str] | None = None,
) -> EventSet:
    """Return an EventSet with noisy copies of every row.

    The thesis noise layer, ported so that it draws exactly the same random
    numbers in the same order:

    1. Every row is repeated ``n_copies`` times, event-major: the copies of
       row ``i`` are output rows ``i * n_copies`` to ``(i + 1) * n_copies - 1``
       and get ``draw_id = 0 .. n_copies - 1`` (thesis ``noise_sample_id``).
    2. For each perturbed location, in the order of ``location_ids``, one call
       ``rng.normal(loc=mu, scale=sigma, size=n_rows * n_copies)`` draws the
       log-factors of all output rows, and the location's loss is multiplied
       by ``exp`` of them. ``mu = -sigma**2 / 2``, so every factor has mean 1.

       - ``homoscedastic``: ``sigma = sqrt(log(1 + level**2))`` for every row,
         so ``level`` is the coefficient of variation of the factor.
       - ``heteroscedastic``: ``r = clip((index - low) / (high - low), 0, 1)``
         with the row's index at that location, and
         ``sigma = sqrt(log(1 + (level * r)**2))``. The noise ramps from 0 at
         ``low`` to ``level`` at ``high``. A zero ``sigma`` still consumes its
         draw.

    **Rate convention.** Each copy gets ``rate / n_copies``, so the copies of
    an event keep the event's total rate, and the total rate of the EventSet
    is unchanged. This is what the thesis does: it sets the probability of
    every expanded row to ``1 / (Y * n_copies)``
    (``calculate_annual_event_probabilities``), and every thesis input row
    has rate ``1 / Y``. On the parity fixture (rate ``1e-4``, 13 copies) the
    two expressions are bit-identical.

    **Metadata.** The threshold filters already in ``metadata.filters`` are
    kept unchanged: they describe the input rows before the expansion.
    ``metadata.scenario`` is unchanged too. One
    :class:`~parametric_insurance_design.eventset.TransformRecord` is
    appended to ``metadata.transforms``, with ``name="noise"``, ``function``
    ``"parametric_insurance_design.noise.add_noise"``, the package version,
    ``n_filters_before = len(metadata.filters)`` and the parameters
    ``kind``, ``level``, ``n_copies``, ``bounds`` (``[low, high]``, or None
    for homoscedastic noise, which ignores them) and ``location_ids`` (the
    perturbed locations in call order, also when the default "all" was
    used). The seed is not recorded here: the caller owns the generator and
    records its seed in the run configuration. For thesis parity, apply the
    noise before any threshold filter, as the thesis does; the filter does
    not change which rows are noisy, but the random stream depends on the
    number of rows.

    Parameters
    ----------
    eventset : EventSet
        Input without draws (every ``draw_id`` is 0).
    level : float
        Noise level ``eta >= 0`` (coefficient of variation of the factor).
    kind : {"homoscedastic", "heteroscedastic"}
        Noise model.
    n_copies : int
        Copies per event row, >= 1 (thesis ``noise_reshuffel``).
    rng : numpy.random.Generator
        Source of randomness; pass ``np.random.default_rng(seed)`` for
        parity (thesis seed 42).
    bounds : tuple of float, default (20.0, 70.0)
        Index range ``(low, high)`` over which heteroscedastic noise ramps
        from 0 to ``level``. The thesis hard-coded 20/70, its attachment and
        limit; pass them from the configuration. Ignored for homoscedastic
        noise.
    location_ids : sequence of str, optional
        Locations to perturb, in the thesis call order (the order in which
        they consume random numbers). The other locations keep their losses.
        Default: all, in EventSet order.

    Returns
    -------
    EventSet
        ``n_copies * n_rows`` rows. The event key is ``(event_id, draw_id)``.

    Raises
    ------
    ComponentConfigError
        If ``level`` is negative or not finite, ``kind`` is unknown,
        ``n_copies`` is not an int >= 1, ``bounds`` is not a finite pair with
        ``low < high``, or ``rng`` is not a :class:`numpy.random.Generator`.
    InputMismatchError
        If the input already has draws, or ``location_ids`` is empty, a
        string, or names an unknown or repeated location. (The thesis
        skipped unknown assets silently.)

    Examples
    --------
    >>> import numpy as np
    >>> noisy = add_noise(  # doctest: +SKIP
    ...     eventset,
    ...     level=0.3,
    ...     kind="heteroscedastic",
    ...     n_copies=13,
    ...     rng=np.random.default_rng(42),
    ... )
    >>> noisy.n_rows == 13 * eventset.n_rows  # doctest: +SKIP
    True
    """
    level, low, high = _check_parameters(level, kind, n_copies, rng, bounds)
    columns = _resolve_locations(eventset, location_ids)
    draw_ids = eventset.events["draw_id"].to_numpy()
    if (draw_ids != 0).any():
        raise InputMismatchError(
            "add_noise needs an EventSet without draws (every draw_id 0); "
            f"got draw_ids up to {int(draw_ids.max())}"
        )

    n_rows = eventset.n_rows
    n = n_rows * n_copies
    source = np.repeat(np.arange(n_rows), n_copies)
    events = eventset.events.iloc[source].reset_index(drop=True)
    events["draw_id"] = np.tile(np.arange(n_copies), n_rows)
    events["rate"] = events["rate"] / n_copies
    index = eventset.index[source]
    loss = eventset.loss[source]  # fancy indexing returns a writable copy

    # The arithmetic below follows the thesis expression by expression, so
    # that the results are bit-identical.
    for j in columns:
        if kind == "homoscedastic":
            sigma_log = np.full(n, np.sqrt(np.log(1.0 + level**2)))
        else:
            r = np.clip((index[:, j] - low) / (high - low), 0.0, 1.0)
            sigma_log = np.sqrt(np.log(1.0 + (level * r) ** 2))
        mu_log = -0.5 * sigma_log**2
        factor = np.exp(rng.normal(loc=mu_log, scale=sigma_log, size=n))
        loss[:, j] = loss[:, j] * factor

    record = _transform_record(eventset, kind, level, n_copies, (low, high), columns)
    metadata = dataclasses.replace(
        eventset.metadata, transforms=(*eventset.metadata.transforms, record)
    )
    return EventSet(
        events=events,
        locations=eventset.locations,
        index=index,
        loss=loss,
        metadata=metadata,
    )


def _check_parameters(
    level: float,
    kind: str,
    n_copies: int,
    rng: np.random.Generator,
    bounds: tuple[float, float],
) -> tuple[float, float, float]:
    """Validate the scalar parameters and return ``(level, low, high)``."""
    if kind not in _KINDS:
        raise ComponentConfigError(f"kind must be one of {_KINDS}, got {kind!r}")
    if isinstance(n_copies, bool) or not isinstance(n_copies, int | np.integer):
        raise ComponentConfigError(f"n_copies must be an int, got {n_copies!r}")
    if n_copies < 1:
        raise ComponentConfigError(f"n_copies must be >= 1, got {n_copies}")
    if not isinstance(rng, np.random.Generator):
        raise ComponentConfigError(
            "rng must be a numpy.random.Generator, e.g. np.random.default_rng(42); "
            f"got {type(rng).__name__}"
        )
    level = _finite(level, "level")
    if level < 0:
        raise ComponentConfigError(f"level must be >= 0, got {level}")
    try:
        low, high = bounds
    except (TypeError, ValueError):
        raise ComponentConfigError(
            f"bounds must be a pair (low, high), got {bounds!r}"
        ) from None
    low = _finite(low, "bounds[0]")
    high = _finite(high, "bounds[1]")
    if not low < high:
        raise ComponentConfigError(f"bounds must have low < high, got {bounds!r}")
    return level, low, high


def _finite(value: object, name: str) -> float:
    """Convert a real number to a finite float or raise."""
    if isinstance(value, bool) or not isinstance(value, int | float | np.number):
        raise ComponentConfigError(f"{name} must be a real number, got {value!r}")
    result = float(value)
    if not math.isfinite(result):
        raise ComponentConfigError(f"{name} must be finite, got {result}")
    return result


def _resolve_locations(
    eventset: EventSet, location_ids: Sequence[str] | None
) -> list[int]:
    """Return the matrix columns to perturb, in call order."""
    known = eventset.location_ids
    if location_ids is None:
        return list(range(len(known)))
    if isinstance(location_ids, str):
        raise InputMismatchError(
            f"location_ids must be a sequence of ids, not the string {location_ids!r}"
        )
    requested = list(location_ids)
    if not requested:
        raise InputMismatchError("location_ids is empty; pass None to perturb all")
    unknown = [loc for loc in requested if loc not in known]
    if unknown:
        raise InputMismatchError(f"unknown location_ids: {unknown}")
    repeated = sorted({loc for loc in requested if requested.count(loc) > 1})
    if repeated:
        raise InputMismatchError(f"repeated location_ids: {repeated}")
    position = {loc: j for j, loc in enumerate(known)}
    return [position[loc] for loc in requested]


def _transform_record(
    eventset: EventSet,
    kind: str,
    level: float,
    n_copies: int,
    bounds: tuple[float, float],
    columns: list[int],
) -> TransformRecord:
    """Return the metadata record of one :func:`add_noise` call."""
    ids = eventset.location_ids
    parameters: dict[str, Any] = {
        "kind": kind,
        "level": level,
        "n_copies": int(n_copies),
        "bounds": list(bounds) if kind == "heteroscedastic" else None,
        "location_ids": [ids[j] for j in columns],
    }
    return TransformRecord(
        name=TRANSFORM_NAME,
        function=f"{add_noise.__module__}.{add_noise.__qualname__}",
        version=_VERSION,
        n_filters_before=len(eventset.metadata.filters),
        parameters=parameters,
    )
