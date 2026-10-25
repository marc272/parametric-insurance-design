"""Budget constraint (MAR-13, SPEC §6.4): Premium <= kappa * E[L].

Context doubles as in ``test_objectives.py``: one entity, scale 1. Rows:
``index = (5, 15, 25, 35)``, ``L = (0, 2, 4, 10)``, ``p = (0.4, 0.3, 0.2,
0.1)``, so ``E[L] = 2.4`` and the cap is 10.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, cast

import cvxpy as cp
import numpy as np
import pytest
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import Basis, OutcomeMeasure
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import ComponentConfigError
from parametric_insurance_design.interfaces import (
    DesignProblem,
    Entity,
    PayoutStructure,
    ProblemContext,
    ProblemSpec,
    Term,
)
from parametric_insurance_design.objectives import (
    ExpectedUncovered,
    WeightedCVaR,
)
from parametric_insurance_design.pricing import PurePremium

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
        return np.eye(self.n)

    def constraints(
        self, theta: cp.Variable, cap: NDArray[np.float64]
    ) -> tuple[cp.Constraint, ...]:
        return (theta >= 0, theta <= np.repeat(cap[:, None], self.n, axis=1))

    def evaluate(self, index: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        return np.asarray(theta, dtype=np.float64).T.copy()


@dataclass(frozen=True)
class Step(PayoutStructure):
    """Monotone, capped step payout on edges (0, 20, 40)."""

    name: ClassVar[str] = "step"

    @property
    def n_params(self) -> int:
        return 2

    def parameter_bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        return np.array([0.0, 20.0]), np.array([20.0, 40.0])

    def basis_matrix(self, index: ArrayLike) -> NDArray[np.float64]:
        x = np.asarray(index, dtype=np.float64)
        return np.column_stack([x < 20.0, x >= 20.0]).astype(np.float64)

    def constraints(
        self, theta: cp.Variable, cap: NDArray[np.float64]
    ) -> tuple[cp.Constraint, ...]:
        return (
            theta >= 0,
            cp.diff(theta, axis=1) >= 0,
            theta <= np.repeat(cap[:, None], 2, axis=1),
        )

    def evaluate(self, index: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        xi = np.asarray(index, dtype=np.float64)
        th = np.asarray(theta, dtype=np.float64)
        return np.column_stack(
            [self.basis_matrix(xi[:, j]) @ th[j] for j in range(xi.shape[1])]
        )


@dataclass(frozen=True, eq=False)
class GroupedMeasure(OutcomeMeasure):
    """Rows summed into outcomes with a 0/1 matrix (stands in for MAR-24)."""

    def aggregate_expression(self, expression: cp.Expression) -> cp.Expression:
        groups = np.zeros((self.n_outcomes, self.n_rows))
        groups[self.outcome_of_row, np.arange(self.n_rows)] = 1.0
        return groups @ expression


def make_context(
    payout_structure: PayoutStructure, measure: OutcomeMeasure | None = None
) -> ProblemContext:
    if measure is None:
        measure = OutcomeMeasure.per_row(Basis.EVENT_CONDITIONAL, PROB)
    spec = ProblemSpec("A", (Entity("A", ("A",)),))
    problem = DesignProblem(spec, INDEX[:, None], LOSS[:, None])
    theta = cp.Variable((1, payout_structure.n_params))
    entity_payout = cp.vstack([payout_structure.basis_matrix(INDEX) @ theta[0]]).T
    return ProblemContext(
        problem=problem,
        payout_structure=payout_structure,
        measure=measure,
        scale=1.0,
        theta=theta,
        entity_payout=entity_payout,
        payout=cast(cp.Expression, cp.sum(entity_payout, axis=1)),
        loss=LOSS,
        entity_loss=LOSS[:, None],
        cap=np.array([LOSS.max()]),
    )


def max_premium(ctx: ProblemContext, loading: float) -> float:
    """Largest pure premium the budget allows within the payout constraints."""
    premium = PurePremium().premium(ctx)
    constraints = [
        *ctx.payout_structure.constraints(ctx.theta, ctx.cap),
        *premium.constraints,
        *Budget(loading).build(ctx, premium),
    ]
    problem = cp.Problem(cp.Maximize(premium.expression), constraints)
    problem.solve(solver=cp.CLARABEL)
    assert problem.status == cp.OPTIMAL
    v = premium.expression.value
    assert v is not None
    return float(np.asarray(v))


@pytest.mark.parametrize(
    ("loading", "expected"),
    [
        (0.0, 0.0),
        (0.5, 0.5 * EXPECTED_LOSS),
        (1.0, EXPECTED_LOSS),
        # Above E[cap] = 10 the cap binds, not the budget.
        (5.0, 10.0),
    ],
)
def test_budget_caps_the_premium(loading: float, expected: float) -> None:
    ctx = make_context(FreePayout())
    assert max_premium(ctx, loading) == pytest.approx(expected, rel=1e-6, abs=1e-7)


def test_budget_uses_the_problem_measure() -> None:
    # Years {0, 1}, {2}, {3} and an empty year: E[L] = (2 + 4 + 10 + 0) / 4.
    measure = GroupedMeasure(
        basis=Basis.ANNUAL,
        outcome_of_row=np.array([0, 0, 1, 2]),
        probability=np.full(4, 0.25),
    )
    ctx = make_context(FreePayout(), measure)
    assert ctx.expected_loss == pytest.approx(4.0)
    assert max_premium(ctx, 0.5) == pytest.approx(2.0, rel=1e-6)


def test_budget_builds_one_constraint() -> None:
    ctx = make_context(FreePayout())
    premium = PurePremium().premium(ctx)
    (constraint,) = Budget(1.0).build(ctx, premium)
    assert constraint.is_dcp()
    ctx.theta.value = LOSS[None, :]
    assert constraint.value()  # paying every loss costs exactly E[L]
    ctx.theta.value = LOSS[None, :] + 0.1
    assert not constraint.value()


def test_objective_pricing_and_budget_compose() -> None:
    # The builder recipe with the real components: E[U] on the step payout
    # with budget 0.5 * 2.4 = 1.2 buys theta = (0, 4), E[U] = 1.2.
    for objective in (ExpectedUncovered(), WeightedCVaR(alpha=0.0, beta=0.9)):
        ctx = make_context(Step())
        term = objective.build(ctx)
        premium = PurePremium().premium(ctx)
        constraints = [
            *ctx.payout_structure.constraints(ctx.theta, ctx.cap),
            *term.constraints,
            *premium.constraints,
            *Budget(0.5).build(ctx, premium),
        ]
        problem = cp.Problem(cp.Minimize(term.expression), constraints)
        problem.solve(solver=cp.CLARABEL)
        assert problem.status == cp.OPTIMAL
        theta = ctx.theta.value
        assert theta is not None
        np.testing.assert_allclose(theta[0], [0.0, 4.0], atol=1e-6)
        assert problem.value == pytest.approx(1.2, rel=1e-6)
        payout = ctx.payout_structure.evaluate(INDEX[:, None], theta).sum(axis=1)
        assert PurePremium().premium_value(payout, ctx.measure) == pytest.approx(
            1.2, rel=1e-6
        )


def test_budget_rejects_a_non_convex_premium() -> None:
    ctx = make_context(FreePayout())
    concave = Term(expression=-cp.square(ctx.theta[0, 0]))
    with pytest.raises(ComponentConfigError, match="convex"):
        Budget(1.0).build(ctx, concave)


@pytest.mark.parametrize("loading", [-0.1, math.nan, math.inf, True, "1.0", None])
def test_budget_rejects_bad_loading(loading: object) -> None:
    with pytest.raises(ComponentConfigError, match="loading"):
        Budget(cast(float, loading))


def test_budget_normalises_loading() -> None:
    budget = Budget(1)
    assert budget.loading == 1.0
    assert isinstance(budget.loading, float)
    assert budget == Budget(1.0)
    assert Budget.name == "budget"
