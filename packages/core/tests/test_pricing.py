"""PurePremium on hand-computed payouts (MAR-13, SPEC §6.4).

Context doubles as in ``test_objectives.py``: one entity, scale 1, a free
payout per row. Rows: ``L = (0, 2, 4, 10)``, ``p = (0.4, 0.3, 0.2, 0.1)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, cast

import cvxpy as cp
import numpy as np
import pytest
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import Basis, OutcomeMeasure
from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.interfaces import (
    DesignProblem,
    Entity,
    PayoutStructure,
    ProblemContext,
    ProblemSpec,
)
from parametric_insurance_design.pricing import PurePremium

LOSS = np.array([0.0, 2.0, 4.0, 10.0])
PROB = np.array([0.4, 0.3, 0.2, 0.1])
PAYOUT = np.array([1.0, 1.0, 1.0, 4.0])
# 0.4 + 0.3 + 0.2 + 0.4
PREMIUM = 1.3


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
        return np.eye(self.n)

    def constraints(
        self, theta: cp.Variable, cap: NDArray[np.float64]
    ) -> tuple[cp.Constraint, ...]:
        return (theta >= 0, theta <= np.repeat(cap[:, None], self.n, axis=1))

    def evaluate(self, index: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        return np.asarray(theta, dtype=np.float64).T.copy()


@dataclass(frozen=True, eq=False)
class GroupedMeasure(OutcomeMeasure):
    """Rows summed into outcomes with a 0/1 matrix (stands in for MAR-24)."""

    def aggregate_expression(self, expression: cp.Expression) -> cp.Expression:
        groups = np.zeros((self.n_outcomes, self.n_rows))
        groups[self.outcome_of_row, np.arange(self.n_rows)] = 1.0
        return groups @ expression


def event_measure() -> OutcomeMeasure:
    return OutcomeMeasure.per_row(Basis.EVENT_CONDITIONAL, PROB)


def grouped_measure() -> GroupedMeasure:
    # Years {0, 1}, {2}, {3} and a year without rows, probability 1/4 each.
    return GroupedMeasure(
        basis=Basis.ANNUAL,
        outcome_of_row=np.array([0, 0, 1, 2]),
        probability=np.full(4, 0.25),
    )


def make_context(measure: OutcomeMeasure) -> ProblemContext:
    payout = FreePayout()
    spec = ProblemSpec("A", (Entity("A", ("A",)),))
    index = np.arange(4, dtype=np.float64)
    problem = DesignProblem(spec, index[:, None], LOSS[:, None])
    theta = cp.Variable((1, payout.n_params))
    entity_payout = cp.vstack([payout.basis_matrix(index) @ theta[0]]).T
    return ProblemContext(
        problem=problem,
        payout_structure=payout,
        measure=measure,
        scale=1.0,
        theta=theta,
        entity_payout=entity_payout,
        payout=cast(cp.Expression, cp.sum(entity_payout, axis=1)),
        loss=LOSS,
        entity_loss=LOSS[:, None],
        cap=np.array([LOSS.max()]),
    )


def premium_at(ctx: ProblemContext, payout: ArrayLike) -> float:
    term = PurePremium().premium(ctx)
    ctx.theta.value = np.asarray(payout, dtype=np.float64)[None, :]
    v = term.expression.value
    assert v is not None
    return float(np.asarray(v))


def test_premium_is_the_expected_payout() -> None:
    ctx = make_context(event_measure())
    term = PurePremium().premium(ctx)
    assert term.constraints == ()
    assert term.expression.is_affine()
    assert premium_at(ctx, PAYOUT) == pytest.approx(PREMIUM, rel=1e-12)


def test_premium_value_matches_the_expression() -> None:
    measure = event_measure()
    assert PurePremium().premium_value(PAYOUT, measure) == pytest.approx(
        PREMIUM, rel=1e-12
    )
    assert PurePremium().premium_value(PAYOUT.tolist(), measure) == pytest.approx(
        premium_at(make_context(measure), PAYOUT), rel=1e-12
    )


def test_premium_of_zero_payout_is_zero() -> None:
    ctx = make_context(event_measure())
    assert premium_at(ctx, np.zeros(4)) == 0.0
    assert PurePremium().premium_value(np.zeros(4), ctx.measure) == 0.0


def test_premium_aggregates_rows_into_outcomes() -> None:
    # Outcome payouts (1 + 1, 1, 4, 0), probability 1/4 each.
    measure = grouped_measure()
    expected = (2 + 1 + 4 + 0) / 4
    assert premium_at(make_context(measure), PAYOUT) == pytest.approx(expected)
    assert PurePremium().premium_value(PAYOUT, measure) == pytest.approx(expected)


def test_premium_is_homogeneous_of_degree_one() -> None:
    ctx = make_context(event_measure())
    assert premium_at(ctx, 3.0 * PAYOUT) == pytest.approx(3.0 * PREMIUM)


@pytest.mark.parametrize(
    ("payout", "match"),
    [
        (np.ones(3), "shape"),
        (np.ones((4, 1)), "shape"),
        (np.array([1.0, np.nan, 1.0, 1.0]), "finite"),
        (np.array([1.0, np.inf, 1.0, 1.0]), "finite"),
    ],
)
def test_premium_value_rejects_bad_payouts(
    payout: NDArray[np.float64], match: str
) -> None:
    with pytest.raises(InputMismatchError, match=match):
        PurePremium().premium_value(payout, event_measure())


def test_name() -> None:
    assert PurePremium.name == "pure"
    assert PurePremium() == PurePremium()
