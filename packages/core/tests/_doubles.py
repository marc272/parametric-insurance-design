"""Shared test doubles for the objective, pricing and budget tests (MAR-87).

``test_objectives.py``, ``test_pricing.py`` and ``test_constraints.py`` import
these with ``from ._doubles import ...``. A relative import works under
``--import-mode=importlib``, because pytest gives every test module a dotted
name from the root directory; pytest does not collect this file, as its name
does not match ``test_*.py``.

The context is built by the real :func:`~parametric_insurance_design.problem.
build_context` (MAR-14) with ``scale = 1``, so that the hand-computed numbers
are the scaled ones. The payout structures stay doubles, so that these unit
tests do not depend on the real ``StepPayout`` (MAR-11) bin semantics. The
grouped measure is a real annual :class:`OutcomeMeasure` with hand-set
outcomes (MAR-24).

Reference data (event-conditional, one row per outcome)::

    row   index   L    p     bin (edges 0, 20, 40)
    0     5       0    0.4   0
    1     15      2    0.3   0
    2     25      4    0.2   1
    3     35      10   0.1   1

    E[L] = 2.4, cap = max L = 10
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import Basis, OutcomeMeasure
from parametric_insurance_design.interfaces import (
    DesignProblem,
    Entity,
    PayoutStructure,
    ProblemContext,
    ProblemSpec,
)
from parametric_insurance_design.problem import build_context

LOSS = np.array([0.0, 2.0, 4.0, 10.0])
PROB = np.array([0.4, 0.3, 0.2, 0.1])
INDEX = np.array([5.0, 15.0, 25.0, 35.0])
EXPECTED_LOSS = 2.4


@dataclass(frozen=True)
class FreePayout(PayoutStructure):
    """One parameter per row: every row's payout is free in ``[0, cap]``."""

    name: ClassVar[str] = "free"
    n: int = 4

    @property
    def n_params(self) -> int:
        return self.n

    def parameter_bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        edges = np.arange(self.n + 1, dtype=np.float64)
        return edges[:-1], edges[1:]

    def basis_matrix(self, index: ArrayLike) -> NDArray[np.float64]:
        assert np.shape(index) == (self.n,)
        return np.eye(self.n)

    def constraints(
        self, theta: cp.Variable, cap: NDArray[np.float64]
    ) -> tuple[cp.Constraint, ...]:
        return (theta >= 0, theta <= np.repeat(cap[:, None], self.n, axis=1))

    def evaluate(self, index: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        return np.asarray(theta, dtype=np.float64).T.copy()


@dataclass(frozen=True)
class Step(PayoutStructure):
    """Monotone, capped step payout on fixed edges (stands in for MAR-11)."""

    name: ClassVar[str] = "step"
    edges: tuple[float, ...] = (0.0, 20.0, 40.0)

    @property
    def n_params(self) -> int:
        return len(self.edges) - 1

    def parameter_bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        e = np.asarray(self.edges)
        return e[:-1], e[1:]

    def basis_matrix(self, index: ArrayLike) -> NDArray[np.float64]:
        x = np.asarray(index, dtype=np.float64)
        e = np.asarray(self.edges)
        k = np.searchsorted(e, np.clip(x, e[0], e[-1] - 1e-12), side="right") - 1
        m = np.zeros((x.shape[0], self.n_params))
        m[np.arange(x.shape[0]), k] = 1.0
        return m

    def constraints(
        self, theta: cp.Variable, cap: NDArray[np.float64]
    ) -> tuple[cp.Constraint, ...]:
        return (
            theta >= 0,
            cp.diff(theta, axis=1) >= 0,
            theta <= np.repeat(cap[:, None], self.n_params, axis=1),
        )

    def evaluate(self, index: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        xi = np.asarray(index, dtype=np.float64)
        th = np.asarray(theta, dtype=np.float64)
        return np.column_stack(
            [self.basis_matrix(xi[:, j]) @ th[j] for j in range(xi.shape[1])]
        )


def event_measure() -> OutcomeMeasure:
    """The event-conditional measure of the reference rows, probability ``PROB``."""
    return OutcomeMeasure.per_row(Basis.EVENT_CONDITIONAL, PROB)


def grouped_measure() -> OutcomeMeasure:
    """Annual measure: years {0, 1}, {2}, {3} and a year without rows.

    Each year has probability 1/4, so ``E[L] = (2 + 4 + 10 + 0) / 4 = 4``. A
    real :class:`OutcomeMeasure`, so ``aggregate_expression`` is the grouped
    case built in MAR-24 (it replaced MAR-87's ``GroupedMeasure`` double).
    """
    return OutcomeMeasure(
        basis=Basis.ANNUAL,
        outcome_of_row=np.array([0, 0, 1, 2]),
        probability=np.full(4, 0.25),
    )


def make_context(
    payout_structure: PayoutStructure,
    *,
    loss: ArrayLike = LOSS,
    index: ArrayLike = INDEX,
    measure: OutcomeMeasure | None = None,
) -> ProblemContext:
    """One entity ``A``, built by the real ``build_context`` with scale 1.

    The cap is the entity's maximum loss (the builder's thesis default).
    ``measure`` defaults to :func:`event_measure`.
    """
    loss_arr = np.asarray(loss, dtype=np.float64)
    index_arr = np.asarray(index, dtype=np.float64)
    spec = ProblemSpec("A", (Entity("A", ("A",)),))
    problem = DesignProblem(spec, index_arr[:, None], loss_arr[:, None])
    return build_context(
        problem,
        payout_structure,
        event_measure() if measure is None else measure,
        scale=1.0,
    )
