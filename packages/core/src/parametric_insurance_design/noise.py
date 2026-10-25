"""Thesis noise layer: lognormal loss noise on copies of each event (SPEC §4.2).

Owner: MAR-10. A bit-identical port of the thesis
``add_noise_to_asset_losses`` for parity (F-06). Each event row is repeated
``n_copies`` times (``draw_id = 0 .. n_copies - 1``, event-major order as in
the thesis), and each location's loss is multiplied by a mean-one lognormal
factor. The index is unchanged.

Rates: each copy gets ``rate / n_copies``, so the copies of an event keep its
total rate (thesis: ``1 / (Y * n_copies)`` per row). ADR 0002 records this as
the proposed draw-row rate convention.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

import numpy as np

from parametric_insurance_design.eventset import EventSet

__all__ = ["NoiseKind", "add_noise"]

NoiseKind = Literal["homoscedastic", "heteroscedastic"]
"""Constant relative noise, or noise growing with the index between bounds."""


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
        parity.
    bounds : tuple of float, default (20.0, 70.0)
        Index range over which heteroscedastic noise ramps from 0 to
        ``level`` (thesis hard-coded 20/70).
    location_ids : sequence of str, optional
        Locations to perturb, in the thesis call order. Default: all, in
        EventSet order.

    Returns
    -------
    EventSet
        ``n_copies * n_rows`` rows.
    """
    raise NotImplementedError("MAR-10")  # pragma: no cover
