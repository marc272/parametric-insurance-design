"""Budget constraint (MAR-13, SPEC §6.4): Premium <= kappa * E[L].

Doubles and context builder from ``_doubles.py`` (MAR-87): one entity, scale
1. Rows: ``index = (5, 15, 25, 35)``, ``L = (0, 2, 4, 10)``, ``p = (0.4, 0.3,
0.2, 0.1)``, so ``E[L] = 2.4`` and the cap is 10.
"""

from __future__ import annotations

import math
from typing import cast

import cvxpy as cp
import numpy as np
import pytest

from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import ComponentConfigError
from parametric_insurance_design.interfaces import ProblemContext, Term
from parametric_insurance_design.objectives import (
    ExpectedUncovered,
    WeightedCVaR,
)
from parametric_insurance_design.pricing import PurePremium

from ._doubles import (
    EXPECTED_LOSS,
    INDEX,
    LOSS,
    FreePayout,
    Step,
    grouped_measure,
    make_context,
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
    ctx = make_context(FreePayout(), measure=grouped_measure())
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
