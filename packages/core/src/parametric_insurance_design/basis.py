"""Evaluation basis and the probability measure over outcomes (ADR 0002, SPEC §6.2).

Objectives, pricing, constraints and evaluation never read event rates
directly. They receive an :class:`OutcomeMeasure`, built once per design
problem by :func:`outcome_measure`, which says:

* which **outcome** each EventSet row belongs to (``outcome_of_row``), and
* the **probability** of each outcome.

Per-row quantities are first transformed row by row (for example the
uncovered loss ``(L_e - pi_e)^+``), then summed into outcomes with
:meth:`OutcomeMeasure.aggregate` (numpy) or
:meth:`OutcomeMeasure.aggregate_expression` (cvxpy, a sparse 0/1 matrix), and
finally weighted by ``probability``. This one mechanism covers all three
bases. With ``Y`` the EventSet's ``metadata.n_years``, ``S`` the years the
rows represent (the sample's years; all ``Y`` by default) and ``D`` the number
of draws:

``event_conditional`` (thesis parity)
    One outcome per row; probability ``rate / sum(rate)`` over the rows given.
    This reproduces the thesis's rescaling after the threshold filter, so
    ``beta`` has no return-period meaning (thesis issue M3).
``event``
    One outcome per row with probability ``rate * Y / |S|``: the row's annual
    rate, unrescaled. On the full sample ``Y / |S| = 1``; on a sample of
    fewer years the factor re-expresses the rate over the years the sample
    covers (an event seen once in ``|S|`` years). The remaining mass
    ``1 - sum(probability)``, the probability of "no event", is one extra
    outcome without rows (zero loss, zero payout), present only if it
    exceeds :data:`PROBABILITY_ATOL`. The rows' annual rates must therefore
    sum to at most one event per year; otherwise this raises. ``beta`` is then
    an annual occurrence probability: ``CVaR_beta`` is the mean over the
    worst ``1 - beta`` of annual event probability, which approximates an
    occurrence (OEP) tail when years rarely hold more than one event.
``annual`` (paper default)
    One outcome per simulated year and draw (SPEC §5: each draw is one
    simulated version of its year), rows summed within it, so that
    ``U_y = sum_{e in y} (L_e - pi_e)^+``. Every (year, draw) slot has
    probability ``1 / (|S| * D)``. ``D`` follows from the rates: the draw-row
    convention gives every row ``rate = 1 / (Y * D)`` (SPEC §5), and a row
    whose rate does not fit it raises, because the rates would then say
    something the year structure cannot. Zero-loss years enter through the
    rates' year structure: the slots with rows are outcomes in (year, draw)
    order, and every slot without rows is pooled into **one** last outcome
    whose probability is their count over ``|S| * D``. Pooling is exact for
    everything computed on a measure (expectations, quantiles, CVaR, the
    exceedance curves): those slots have value 0 for every per-row quantity
    summed or maximised into an outcome, and a discrete distribution does not
    change when atoms at the same value merge. It keeps the number of
    outcomes, and so of Rockafellar-Uryasev auxiliaries, at most
    ``n_rows + 1`` instead of ``|S| * D``. The year of an outcome with rows
    is the year of its rows.

With exactly one event per year and no draws, ``event`` and ``annual`` give
the same outcomes and probabilities (in another order on a sample), so every
objective, premium and KPI agrees on the two bases.

**MSE on a grouped basis.** :class:`~parametric_insurance_design.objectives.MSE`
squares each outcome's summed residual, ``(L_y - pi_y)^2`` with
``L_y - pi_y = sum_{e in y} (L_e - pi_e)``, not ``sum_{e in y} (L_e -
pi_e)^2``. Decided in MAR-24 (SPEC §6.2) and explained in
``docs/methodology/annual-basis.md``: the annual basis measures the risk
owner's net position per year, the premium is annual, and the MSE design then
minimises exactly the ``rmse_residual`` KPI that evaluation reports on the
same basis. The per-event sum would make the annual MSE design the
event-basis design for any year structure.

Owner: MAR-61 wrote ``event_conditional``; MAR-24 owns this file afterwards
and added ``event``, ``annual`` and the grouped case of
:meth:`OutcomeMeasure.aggregate_expression`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import cached_property
from typing import Final, cast

import cvxpy as cp
import numpy as np
import scipy.sparse as sp
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.eventset import EventSet

__all__ = [
    "DRAW_RATE_RTOL",
    "PROBABILITY_ATOL",
    "Basis",
    "OutcomeMeasure",
    "outcome_measure",
]

PROBABILITY_ATOL: float = 1e-9
"""Absolute tolerance for outcome probabilities summing to one."""

DRAW_RATE_RTOL: Final[float] = 1e-6
"""Relative tolerance of the annual basis's rate check: every row's
``1 / (rate * n_years)`` must equal the number of draws within it."""


class Basis(StrEnum):
    """Which outcomes the uncovered loss, the premium and the KPIs refer to.

    Attributes
    ----------
    EVENT_CONDITIONAL : str
        Per event row, probabilities rescaled to sum to one. Thesis parity only.
    EVENT : str
        Per event row, unrescaled rates, plus a "no event" outcome.
    ANNUAL : str
        Per simulated year (and draw): losses and payouts of a year are
        summed, and CVaR is taken over years. The paper default.
    """

    EVENT_CONDITIONAL = "event_conditional"
    EVENT = "event"
    ANNUAL = "annual"


@dataclass(frozen=True, eq=False)
class OutcomeMeasure:
    """Probability measure over outcomes, with the row-to-outcome mapping.

    Parameters
    ----------
    basis : Basis
        The basis the measure was built for.
    outcome_of_row : array_like of int
        Outcome of each EventSet row, shape ``(n_rows,)``, values in
        ``[0, n_outcomes)``. An outcome may have no rows (a zero-loss year).
    probability : array_like of float
        Probability of each outcome, shape ``(n_outcomes,)``. Finite, >= 0 and
        summing to one within :data:`PROBABILITY_ATOL`.

    Raises
    ------
    InputMismatchError
        If the arrays have the wrong shape, an outcome index is out of range,
        or the probabilities are invalid.
    """

    basis: Basis
    outcome_of_row: NDArray[np.int64]
    probability: NDArray[np.float64]

    def __post_init__(self) -> None:
        """Validate the fields and store read-only copies."""
        basis = Basis(self.basis)
        rows = np.array(self.outcome_of_row, copy=True)
        prob = np.array(self.probability, dtype=np.float64, copy=True)
        if rows.ndim != 1 or not np.issubdtype(rows.dtype, np.integer):
            raise InputMismatchError("outcome_of_row must be a 1-D integer array")
        if prob.ndim != 1 or prob.size == 0:
            raise InputMismatchError("probability must be a non-empty 1-D array")
        rows = rows.astype(np.int64)
        if rows.size and (rows.min() < 0 or rows.max() >= prob.size):
            raise InputMismatchError(
                f"outcome_of_row values must lie in [0, {prob.size}), "
                f"got [{rows.min()}, {rows.max()}]"
            )
        if not np.all(np.isfinite(prob)) or np.any(prob < 0):
            raise InputMismatchError("probability must be finite and >= 0")
        total = float(prob.sum())
        if abs(total - 1.0) > PROBABILITY_ATOL:
            raise InputMismatchError(f"probability must sum to 1, got {total!r}")
        rows.setflags(write=False)
        prob.setflags(write=False)
        object.__setattr__(self, "basis", basis)
        object.__setattr__(self, "outcome_of_row", rows)
        object.__setattr__(self, "probability", prob)

    @classmethod
    def per_row(cls, basis: Basis, probability: ArrayLike) -> OutcomeMeasure:
        """Build a measure with one outcome per row.

        Parameters
        ----------
        basis : Basis
            The basis the measure is for.
        probability : array_like of float
            Probability of each row, shape ``(n_rows,)``.

        Returns
        -------
        OutcomeMeasure
            Measure whose ``outcome_of_row`` is ``0, 1, ..., n_rows - 1``.
        """
        prob = np.asarray(probability, dtype=np.float64)
        return cls(
            basis=basis,
            outcome_of_row=np.arange(prob.shape[0] if prob.ndim else 0),
            probability=prob,
        )

    @property
    def n_rows(self) -> int:
        """Number of EventSet rows the measure maps."""
        return int(self.outcome_of_row.shape[0])

    @property
    def n_outcomes(self) -> int:
        """Number of outcomes."""
        return int(self.probability.shape[0])

    @property
    def is_per_row(self) -> bool:
        """True if every row is its own outcome, in row order."""
        return self.n_rows == self.n_outcomes and bool(
            np.array_equal(self.outcome_of_row, np.arange(self.n_rows))
        )

    @cached_property
    def _grouping_matrix(self) -> sp.csr_matrix:
        """Sparse 0/1 matrix that sums rows into outcomes.

        Returns
        -------
        scipy.sparse.csr_matrix
            Shape ``(n_outcomes, n_rows)``; entry ``(o, e)`` is 1 if row ``e``
            belongs to outcome ``o``. Built once per measure.
        """
        n = self.n_rows
        return sp.csr_matrix(
            (np.ones(n), (self.outcome_of_row, np.arange(n))),
            shape=(self.n_outcomes, n),
        )

    def aggregate(self, values: ArrayLike) -> NDArray[np.float64]:
        """Sum per-row values into outcomes.

        Parameters
        ----------
        values : array_like of float
            Shape ``(n_rows,)`` or ``(n_rows, k)``.

        Returns
        -------
        numpy.ndarray
            Shape ``(n_outcomes,)`` or ``(n_outcomes, k)``. Outcomes without
            rows get zero.

        Raises
        ------
        InputMismatchError
            If the first dimension is not ``n_rows``.
        """
        arr = np.asarray(values, dtype=np.float64)
        if arr.ndim not in (1, 2) or arr.shape[0] != self.n_rows:
            raise InputMismatchError(
                f"values must have shape ({self.n_rows},) or ({self.n_rows}, k), "
                f"got {arr.shape}"
            )
        if self.is_per_row:
            return arr.copy()
        out = np.zeros((self.n_outcomes, *arr.shape[1:]), dtype=np.float64)
        np.add.at(out, self.outcome_of_row, arr)
        return out

    def expectation(self, values: ArrayLike) -> float:
        """Return the expected outcome sum of per-row values.

        Parameters
        ----------
        values : array_like of float
            Per-row values, shape ``(n_rows,)``.

        Returns
        -------
        float
            ``probability @ aggregate(values)``.
        """
        return float(self.probability @ self.aggregate(values))

    def aggregate_expression(self, expression: cp.Expression) -> cp.Expression:
        """Sum a per-row cvxpy expression into outcomes.

        On a per-row measure the expression is returned unchanged (so the
        ``event_conditional`` problems are exactly the thesis's). Otherwise it
        is multiplied by a sparse 0/1 matrix, built once per measure;
        outcomes without rows are the constant 0.

        Parameters
        ----------
        expression : cvxpy.Expression
            Shape ``(n_rows,)``.

        Returns
        -------
        cvxpy.Expression
            Shape ``(n_outcomes,)``.

        Raises
        ------
        InputMismatchError
            If the expression does not have shape ``(n_rows,)``.
        """
        if tuple(expression.shape) != (self.n_rows,):
            raise InputMismatchError(
                f"expression must have shape ({self.n_rows},), "
                f"got {tuple(expression.shape)}"
            )
        if self.is_per_row:
            return expression
        return cast(cp.Expression, self._grouping_matrix @ expression)


def _sample_years(eventset: EventSet, years: ArrayLike | None) -> NDArray[np.int64]:
    """Return the sorted years the rows represent, checked against the rows.

    Raises
    ------
    InputMismatchError
        If ``years`` is not a non-empty 1-D integer array of unique values in
        ``[0, n_years)``, or a row's year is not among them.
    """
    n_years = eventset.metadata.n_years
    if years is None:
        out = np.arange(n_years, dtype=np.int64)
    else:
        arr = np.asarray(years)
        if arr.ndim != 1 or arr.size == 0 or not np.issubdtype(arr.dtype, np.integer):
            raise InputMismatchError("years must be a non-empty 1-D integer array")
        out = np.sort(arr.astype(np.int64))
        if np.any(np.diff(out) == 0):
            raise InputMismatchError("years must be unique")
        if out[0] < 0 or out[-1] >= n_years:
            raise InputMismatchError(
                f"years must lie in [0, {n_years}) (metadata.n_years), "
                f"got [{out[0]}, {out[-1]}]"
            )
    row_years = eventset.events["year"].to_numpy(dtype=np.int64)
    stray = np.setdiff1d(row_years, out)
    if stray.size:
        raise InputMismatchError(
            f"rows lie in years outside the given years, e.g. {stray[:5].tolist()}"
        )
    return out


def _n_draws(eventset: EventSet) -> int:
    """Return the number of draws ``D`` implied by rates ``1 / (n_years * D)``.

    Raises
    ------
    InputMismatchError
        If a row's rate is not ``1 / (n_years * D)`` for one integer ``D`` (SPEC
        §5 draw-row convention), or a ``draw_id`` lies outside ``[0, D)``.
    """
    n_years = eventset.metadata.n_years
    rates = eventset.rates
    implied = 1.0 / (rates * n_years)
    n_draws = int(np.rint(np.median(implied)))
    if n_draws < 1 or not np.allclose(implied, n_draws, rtol=DRAW_RATE_RTOL, atol=0):
        raise InputMismatchError(
            "the annual basis needs every row's rate to be 1 / (n_years * n_draws) "
            f"(SPEC §5) with n_years = {n_years}; the rates imply between "
            f"{implied.min():.6g} and {implied.max():.6g} draws per event"
        )
    draws = eventset.events["draw_id"].to_numpy(dtype=np.int64)
    if draws.min() < 0 or draws.max() >= n_draws:
        raise InputMismatchError(
            f"draw_id must lie in [0, {n_draws}) for rates 1 / (n_years * "
            f"{n_draws}), got [{draws.min()}, {draws.max()}]"
        )
    return n_draws


def _event_measure(eventset: EventSet, years: NDArray[np.int64]) -> OutcomeMeasure:
    """Per-row rates over the sample's years, plus a "no event" outcome."""
    factor = eventset.metadata.n_years / years.size
    probability = eventset.rates * factor
    none = 1.0 - float(probability.sum())
    if none < -PROBABILITY_ATOL:
        raise InputMismatchError(
            "the event basis needs the rows' annual rates to sum to at most 1 "
            f"(at most one event per year on average), got {1.0 - none:.6g} over "
            f"{years.size} years; use the annual basis"
        )
    if none <= PROBABILITY_ATOL:
        return OutcomeMeasure.per_row(Basis.EVENT, probability)
    return OutcomeMeasure(
        basis=Basis.EVENT,
        outcome_of_row=np.arange(eventset.n_rows),
        probability=np.append(probability, none),
    )


def _annual_measure(eventset: EventSet, years: NDArray[np.int64]) -> OutcomeMeasure:
    """One outcome per (year, draw) slot with rows, plus the pooled empty slots."""
    n_draws = _n_draws(eventset)
    row_years = eventset.events["year"].to_numpy(dtype=np.int64)
    draws = eventset.events["draw_id"].to_numpy(dtype=np.int64)
    slot = np.searchsorted(years, row_years) * n_draws + draws
    occupied, outcome_of_row = np.unique(slot, return_inverse=True)
    n_slots = years.size * n_draws
    n_empty = n_slots - occupied.size
    probability = np.full(occupied.size, 1.0 / n_slots)
    if n_empty:
        probability = np.append(probability, n_empty / n_slots)
    return OutcomeMeasure(
        basis=Basis.ANNUAL,
        outcome_of_row=outcome_of_row.reshape(-1),
        probability=probability,
    )


def outcome_measure(
    eventset: EventSet,
    basis: Basis,
    *,
    years: ArrayLike | None = None,
) -> OutcomeMeasure:
    """Build the outcome measure of an EventSet for a basis.

    See the module docstring for the outcomes and probabilities of each basis.

    Parameters
    ----------
    eventset : EventSet
        The rows to build the measure over, usually a
        :class:`~parametric_insurance_design.interfaces.Sample` of a larger
        EventSet. Its ``metadata.n_years`` is the parent's ``Y``.
    basis : Basis
        The evaluation basis.
    years : array_like of int, optional
        Simulation years the rows represent, including years without rows
        (``Sample.years``). Unique, in ``[0, metadata.n_years)``, and every
        row's year among them. Defaults to ``0 .. metadata.n_years - 1``.
        Ignored by ``event_conditional``.

    Returns
    -------
    OutcomeMeasure
        Measure aligned with ``eventset``'s rows.

    Raises
    ------
    InputMismatchError
        If the EventSet has no rows; or, on the ``event`` and ``annual``
        bases, if ``years`` is invalid or misses a row's year; on ``event``,
        if the rows' rates sum to more than one event per year; on
        ``annual``, if the rates do not follow ``1 / (n_years * n_draws)``
        or a ``draw_id`` lies outside ``[0, n_draws)``.
    """
    basis = Basis(basis)
    if eventset.n_rows == 0:
        raise InputMismatchError("cannot build an outcome measure without rows")
    if basis is Basis.EVENT_CONDITIONAL:
        rates = eventset.rates
        return OutcomeMeasure.per_row(basis, rates / rates.sum())
    sample_years = _sample_years(eventset, years)
    if basis is Basis.EVENT:
        return _event_measure(eventset, sample_years)
    return _annual_measure(eventset, sample_years)
