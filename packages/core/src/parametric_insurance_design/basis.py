"""Evaluation basis and the probability measure over outcomes (ADR 0002, SPEC §6.2).

Objectives, pricing, constraints and evaluation never read event rates
directly. They receive an :class:`OutcomeMeasure`, built once per design
problem by :func:`outcome_measure`, which says:

* which **outcome** each EventSet row belongs to (``outcome_of_row``), and
* the **probability** of each outcome.

Per-row quantities are first transformed row by row (for example the
uncovered loss ``(L_e - pi_e)^+``), then summed into outcomes with
:meth:`OutcomeMeasure.aggregate` (numpy) or
:meth:`OutcomeMeasure.aggregate_expression` (cvxpy), and finally weighted by
``probability``. This one mechanism covers all three bases:

``event_conditional`` (thesis parity)
    One outcome per row; probability ``rate / sum(rate)`` over the rows given.
    This reproduces the thesis's rescaling after the threshold filter.
``event``
    One outcome per row with unrescaled rates (SPEC §6.2, optional). How the
    remaining mass is represented is decided in MAR-24.
``annual`` (paper default)
    One outcome per simulated year (and draw), rows summed within it, so that
    ``U_y = sum_{e in y} (L_e - pi_e)^+``. Years without rows are outcomes
    with no rows, which carries the zero-loss mass. Decided and built in
    MAR-24.

Owner: MAR-61 wrote ``event_conditional``; MAR-24 owns this file afterwards
and adds ``event``, ``annual`` and the general case of
:meth:`OutcomeMeasure.aggregate_expression`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.eventset import EventSet

__all__ = ["PROBABILITY_ATOL", "Basis", "OutcomeMeasure", "outcome_measure"]

PROBABILITY_ATOL: float = 1e-9
"""Absolute tolerance for outcome probabilities summing to one."""


class Basis(StrEnum):
    """Which outcomes the uncovered loss, the premium and the KPIs refer to.

    Attributes
    ----------
    EVENT_CONDITIONAL : str
        Per event row, probabilities rescaled to sum to one. Thesis parity only.
    EVENT : str
        Per event row, unrescaled rates.
    ANNUAL : str
        Per simulated year: losses and payouts of a year are summed, and CVaR
        is taken over years. The paper default.
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
        raise NotImplementedError(  # pragma: no cover - MAR-24
            "aggregating rows into outcomes is implemented in MAR-24"
        )


def outcome_measure(
    eventset: EventSet,
    basis: Basis,
    *,
    years: ArrayLike | None = None,
) -> OutcomeMeasure:
    """Build the outcome measure of an EventSet for a basis.

    Parameters
    ----------
    eventset : EventSet
        The rows to build the measure over, usually a
        :class:`~parametric_insurance_design.interfaces.Sample` of a larger
        EventSet.
    basis : Basis
        The evaluation basis.
    years : array_like of int, optional
        Simulation years the rows represent, including years without rows.
        Used by the ``annual`` basis; defaults to ``0 .. metadata.n_years - 1``.
        Ignored by ``event_conditional``.

    Returns
    -------
    OutcomeMeasure
        Measure aligned with ``eventset``'s rows.

    Raises
    ------
    InputMismatchError
        If the EventSet has no rows.
    """
    basis = Basis(basis)
    if eventset.n_rows == 0:
        raise InputMismatchError("cannot build an outcome measure without rows")
    if basis is Basis.EVENT_CONDITIONAL:
        rates = eventset.rates
        return OutcomeMeasure.per_row(basis, rates / rates.sum())
    raise NotImplementedError(  # pragma: no cover - MAR-24
        f"basis {basis.value!r} is implemented in MAR-24"
    )
