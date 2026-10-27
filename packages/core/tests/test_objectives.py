"""Objectives on tiny hand-computed problems (MAR-13, SPEC §6, §6.7).

The payout structures, the grouped measure and the context builder are shared
with the pricing and budget tests in ``_doubles.py`` (MAR-87): the context is
built by the real ``problem.build_context`` with ``scale = 1``, so that the
hand numbers are the scaled ones.

Reference data (event-conditional, one row per outcome)::

    row   index   L    p     bin (edges 0, 20, 40)
    0     5       0    0.4   0
    1     15      2    0.3   0
    2     25      4    0.2   1
    3     35      10   0.1   1

    E[L] = 2.4
"""

from __future__ import annotations

import math
from typing import cast

import cvxpy as cp
import numpy as np
import pytest
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.errors import ComponentConfigError, InputMismatchError
from parametric_insurance_design.interfaces import (
    ObjectiveTerm,
    PayoutStructure,
    ProblemContext,
)
from parametric_insurance_design.objectives import (
    MSE,
    ExpectedUncovered,
    Objective,
    WeightedCVaR,
    rockafellar_uryasev,
)

from ._doubles import (
    EXPECTED_LOSS,
    LOSS,
    PROB,
    FreePayout,
    Step,
    grouped_measure,
    make_context,
)

# A fixed payout and its hand-computed objective values.
FIXED_PAYOUT = np.array([1.0, 1.0, 1.0, 4.0])
# Signed residual (-1, 1, 3, 6): 0.4 + 0.3 + 1.8 + 3.6.
FIXED_MSE = 6.1
# Uncovered loss U = (0, 1, 3, 6): 0.3 + 0.6 + 0.6.
FIXED_EU = 1.5
# CVaR_beta(U): mean of the worst (1 - beta) probability mass of U.
FIXED_CVAR = {
    0.9: 6.0,  # 0.1 * 6 / 0.1
    0.75: 4.2,  # (0.1 * 6 + 0.15 * 3) / 0.25
    0.5: 2.8,  # (0.1 * 6 + 0.2 * 3 + 0.2 * 1) / 0.5
}

# --------------------------------------------------------------------------
# The builder recipe
# --------------------------------------------------------------------------


def budget(ctx: ProblemContext, loading: float) -> cp.Constraint:
    """Pure-premium budget, written out so these tests need only objectives."""
    return (
        ctx.measure.probability @ ctx.measure.aggregate_expression(ctx.payout)
        <= loading * ctx.expected_loss
    )


def fix_payout(ctx: ProblemContext, payout: ArrayLike) -> cp.Constraint:
    """Pin the free payout of every row (FreePayout only)."""
    return ctx.theta[0] == np.asarray(payout, dtype=np.float64)


def solve(
    ctx: ProblemContext, term: ObjectiveTerm, *extra: cp.Constraint
) -> cp.Problem:
    """Assemble and solve as the builder does; return the solved problem."""
    constraints = [
        *ctx.payout_structure.constraints(ctx.theta, ctx.cap),
        *term.constraints,
        *extra,
    ]
    problem = cp.Problem(cp.Minimize(term.expression), constraints)
    assert problem.is_dcp()
    problem.solve(solver=cp.CLARABEL)
    assert problem.status == cp.OPTIMAL
    return problem


def value(expression: cp.Expression | float) -> float:
    if isinstance(expression, int | float):
        return float(expression)
    v = expression.value
    assert v is not None
    return float(np.asarray(v))


def theta_of(ctx: ProblemContext) -> NDArray[np.float64]:
    v = ctx.theta.value
    assert v is not None
    return np.asarray(v)[0]


def assert_decomposes(ctx: ProblemContext, term: ObjectiveTerm) -> None:
    """``expression == probability @ per_outcome + offset`` (ADR 0002)."""
    per_outcome = term.per_outcome.value
    assert per_outcome is not None
    assert np.shape(per_outcome) == (ctx.measure.n_outcomes,)
    recombined = float(ctx.measure.probability @ per_outcome) + value(term.offset)
    assert recombined == pytest.approx(value(term.expression), rel=1e-9, abs=1e-12)


ALL_OBJECTIVES: list[Objective] = [
    MSE(),
    ExpectedUncovered(),
    WeightedCVaR(alpha=0.0, beta=0.9),
    WeightedCVaR(alpha=0.5, beta=0.75),
    WeightedCVaR(alpha=1.0, beta=0.9),
]

# --------------------------------------------------------------------------
# Fixed payout: the objective formulas
# --------------------------------------------------------------------------


def test_mse_is_the_signed_squared_residual() -> None:
    ctx = make_context(FreePayout(4))
    term = MSE().build(ctx)
    solve(ctx, term, fix_payout(ctx, FIXED_PAYOUT))
    # Over-payment in row 0 (residual -1) counts: 6.1, not 5.7.
    assert value(term.expression) == pytest.approx(FIXED_MSE, rel=1e-7)
    assert value(term.components["mse"]) == pytest.approx(FIXED_MSE, rel=1e-7)
    assert term.homogeneity == 2
    assert isinstance(term.offset, float)
    assert term.offset == 0.0
    assert term.constraints == ()


def test_expected_uncovered_clips_over_payment() -> None:
    ctx = make_context(FreePayout(4))
    term = ExpectedUncovered().build(ctx)
    solve(ctx, term, fix_payout(ctx, FIXED_PAYOUT))
    assert value(term.expression) == pytest.approx(FIXED_EU, rel=1e-7)
    assert value(term.components["expected_uncovered"]) == pytest.approx(
        FIXED_EU, rel=1e-7
    )
    per_outcome = term.per_outcome.value
    assert per_outcome is not None
    np.testing.assert_allclose(per_outcome, [0, 1, 3, 6], atol=1e-7)
    assert term.homogeneity == 1


@pytest.mark.parametrize("beta", sorted(FIXED_CVAR))
def test_cvar_at_a_fixed_payout(beta: float) -> None:
    ctx = make_context(FreePayout(4))
    term = WeightedCVaR(alpha=1.0, beta=beta).build(ctx)
    solve(ctx, term, fix_payout(ctx, FIXED_PAYOUT))
    assert value(term.expression) == pytest.approx(FIXED_CVAR[beta], rel=1e-6)
    assert value(term.components["cvar"]) == pytest.approx(FIXED_CVAR[beta], rel=1e-6)
    assert value(term.components["expected_uncovered"]) == pytest.approx(
        FIXED_EU, rel=1e-6
    )


def test_weighted_cvar_mixes_cvar_and_expected_uncovered() -> None:
    ctx = make_context(FreePayout(4))
    term = WeightedCVaR(alpha=0.5, beta=0.75).build(ctx)
    solve(ctx, term, fix_payout(ctx, FIXED_PAYOUT))
    # 0.5 * 4.2 + 0.5 * 1.5
    assert value(term.expression) == pytest.approx(2.85, rel=1e-6)
    assert value(term.components["cvar"]) == pytest.approx(4.2, rel=1e-6)
    assert value(term.components["expected_uncovered"]) == pytest.approx(1.5, rel=1e-6)


def test_cvar_with_small_beta_tends_to_expected_uncovered() -> None:
    # With beta below the probability of the lowest atom (U = 0, p = 0.4),
    # CVaR_beta(U) = E[U] / (1 - beta) exactly, which tends to E[U].
    for beta in (0.3, 0.01, 1e-4):
        ctx = make_context(FreePayout(4))
        term = WeightedCVaR(alpha=1.0, beta=beta).build(ctx)
        solve(ctx, term, fix_payout(ctx, FIXED_PAYOUT))
        assert value(term.expression) == pytest.approx(FIXED_EU / (1 - beta), rel=1e-6)
    assert value(term.expression) == pytest.approx(FIXED_EU, rel=2e-4)


@pytest.mark.parametrize("objective", ALL_OBJECTIVES, ids=lambda o: repr(o))
def test_homogeneity_degree(objective: Objective) -> None:
    # objective(c * L, c * pi) == c**d * objective(L, pi).
    values = []
    for c in (1.0, 3.0):
        ctx = make_context(FreePayout(4), loss=c * LOSS)
        term = objective.build(ctx)
        solve(ctx, term, fix_payout(ctx, c * FIXED_PAYOUT))
        values.append(value(term.expression))
    expected_ratio = 3.0 ** objective.build(make_context(FreePayout(4))).homogeneity
    assert values[1] == pytest.approx(expected_ratio * values[0], rel=1e-6)


# --------------------------------------------------------------------------
# Optimisation: hand-computed optima
# --------------------------------------------------------------------------


def test_mse_with_slack_budget_pays_the_bin_conditional_mean() -> None:
    # SPEC §6.7: theta_b = E[L | bin b] = (0.6 / 0.7, 1.8 / 0.3) = (6/7, 6).
    ctx = make_context(Step())
    term = MSE().build(ctx)
    solve(ctx, term, budget(ctx, 2.0))
    np.testing.assert_allclose(theta_of(ctx), [6 / 7, 6.0], rtol=1e-6)
    # Within-bin variance: bin 0 gives 33.6 / 49, bin 1 gives 2.4.
    assert value(term.expression) == pytest.approx(108 / 35, rel=1e-6)
    assert ctx.problem.n_rows == 4


def test_mse_with_binding_budget_hits_the_lower_bound() -> None:
    # Budget 0.5 * 2.4 = 1.2. An equal shift by 1.2 would make theta_0 < 0,
    # so theta_0 = 0 and the whole budget buys theta_1 = 1.2 / 0.3 = 4.
    # Residuals (0, 2, 0, 6): 0.3 * 4 + 0.1 * 36.
    ctx = make_context(Step())
    term = MSE().build(ctx)
    solve(ctx, term, budget(ctx, 0.5))
    np.testing.assert_allclose(theta_of(ctx), [0.0, 4.0], atol=1e-6)
    assert value(term.expression) == pytest.approx(4.8, rel=1e-6)


def test_expected_uncovered_spends_where_no_payout_is_wasted() -> None:
    # Bin 1 has no row with L below 4, so each unit of premium there lowers
    # E[U] by one unit; in bin 0 the L = 0 row wastes 4/7 of it. Optimum:
    # theta = (0, 4), E[U] = E[L] - budget = 1.2.
    ctx = make_context(Step())
    term = ExpectedUncovered().build(ctx)
    solve(ctx, term, budget(ctx, 0.5))
    np.testing.assert_allclose(theta_of(ctx), [0.0, 4.0], atol=1e-6)
    assert value(term.expression) == pytest.approx(EXPECTED_LOSS - 1.2, rel=1e-6)


def test_cvar_optimum_on_step_payout() -> None:
    # theta = (0, 4) gives U = (0, 2, 0, 6) and CVaR_0.75 = (0.6 + 0.15 * 2) /
    # 0.25 = 3.6; moving premium into bin 0 raises U_3 by 7/3 per unit, which
    # costs more tail mass than it saves (checked by a grid search too).
    ctx = make_context(Step())
    term = WeightedCVaR(alpha=1.0, beta=0.75).build(ctx)
    solve(ctx, term, budget(ctx, 0.5))
    np.testing.assert_allclose(theta_of(ctx), [0.0, 4.0], atol=1e-5)
    assert value(term.expression) == pytest.approx(3.6, rel=1e-6)
    assert_decomposes(ctx, term)


@pytest.mark.parametrize(("alpha", "optimum"), [(1.0, 2.0), (0.5, 1.6)])
def test_weighted_cvar_water_fills_the_largest_losses(
    alpha: float, optimum: float
) -> None:
    # Free payouts, budget 1.2. Cutting every loss down to c = 2 costs
    # 0.1 * 8 + 0.2 * 2 = 1.2, so U = (0, 2, 2, 2) and CVaR_0.9(U) = 2, the
    # least possible maximum. It wastes nothing, so E[U] = 2.4 - 1.2 = 1.2
    # too, and alpha = 0.5 gives 0.5 * 2 + 0.5 * 1.2 = 1.6.
    ctx = make_context(FreePayout(4))
    term = WeightedCVaR(alpha=alpha, beta=0.9).build(ctx)
    solve(ctx, term, budget(ctx, 0.5))
    np.testing.assert_allclose(theta_of(ctx), [0.0, 0.0, 2.0, 8.0], atol=1e-5)
    assert value(term.expression) == pytest.approx(optimum, rel=1e-6)
    assert value(term.components["cvar"]) == pytest.approx(2.0, rel=1e-6)
    assert value(term.components["expected_uncovered"]) == pytest.approx(1.2, rel=1e-6)
    assert_decomposes(ctx, term)


# --------------------------------------------------------------------------
# alpha = 0 equals E[U]
# --------------------------------------------------------------------------


@pytest.mark.parametrize("payout_structure", [Step(), FreePayout(4)], ids=repr)
@pytest.mark.parametrize("loading", [0.0, 0.5, 1.0, 2.0])
def test_alpha_zero_equals_expected_uncovered(
    payout_structure: PayoutStructure, loading: float
) -> None:
    ctx_w = make_context(payout_structure)
    weighted = WeightedCVaR(alpha=0.0, beta=0.95).build(ctx_w)
    solve(ctx_w, weighted, budget(ctx_w, loading))
    ctx_e = make_context(payout_structure)
    plain = ExpectedUncovered().build(ctx_e)
    solve(ctx_e, plain, budget(ctx_e, loading))
    assert value(weighted.expression) == pytest.approx(
        value(plain.expression), rel=1e-7, abs=1e-9
    )
    # Same term structure: no CVaR auxiliary, no offset, no cvar component.
    assert weighted.expression.variables() == [ctx_w.theta]
    assert isinstance(weighted.offset, float)
    assert weighted.offset == 0.0
    assert set(weighted.components) == {"expected_uncovered"}


def test_alpha_zero_equals_expected_uncovered_at_any_payout() -> None:
    ctx = make_context(FreePayout(4))
    weighted = WeightedCVaR(alpha=0.0, beta=0.5).build(ctx)
    plain = ExpectedUncovered().build(ctx)
    ctx.theta.value = FIXED_PAYOUT[None, :]
    assert value(weighted.expression) == pytest.approx(FIXED_EU, rel=1e-12)
    assert value(plain.expression) == pytest.approx(FIXED_EU, rel=1e-12)


# --------------------------------------------------------------------------
# Decomposition, problem class and basis-agnostic aggregation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("objective", ALL_OBJECTIVES, ids=lambda o: repr(o))
def test_term_decomposes_over_outcomes(objective: Objective) -> None:
    ctx = make_context(Step())
    term = objective.build(ctx)
    solve(ctx, term, budget(ctx, 0.5))
    assert_decomposes(ctx, term)


def test_problem_classes() -> None:
    ctx = make_context(Step())
    assert MSE().build(ctx).expression.is_quadratic()
    for objective in (ExpectedUncovered(), WeightedCVaR(alpha=0.7, beta=0.9)):
        # Piecewise-linear objective + affine constraints = LP.
        assert objective.build(ctx).expression.is_pwl()


@pytest.mark.parametrize(
    ("objective", "expected"),
    [
        # Outcome residuals (2 - 2, 4 - 1, 10 - 4, 0) = (0, 3, 6, 0).
        (MSE(), (0 + 9 + 36 + 0) / 4),
        # Outcome uncovered losses U_o = (0 + 1, 3, 6, 0).
        (ExpectedUncovered(), (1 + 3 + 6 + 0) / 4),
        (WeightedCVaR(alpha=1.0, beta=0.75), 6.0),
        (WeightedCVaR(alpha=1.0, beta=0.5), (6 + 3) / 2),
        (WeightedCVaR(alpha=0.5, beta=0.5), 0.5 * 4.5 + 0.5 * 2.5),
    ],
    ids=lambda x: repr(x),
)
def test_objectives_aggregate_rows_into_outcomes(
    objective: Objective, expected: float
) -> None:
    ctx = make_context(FreePayout(4), measure=grouped_measure())
    assert ctx.basis is Basis.ANNUAL
    term = objective.build(ctx)
    solve(ctx, term, fix_payout(ctx, FIXED_PAYOUT))
    assert value(term.expression) == pytest.approx(expected, rel=1e-6)
    assert_decomposes(ctx, term)


# --------------------------------------------------------------------------
# rockafellar_uryasev and configuration errors
# --------------------------------------------------------------------------


def test_rockafellar_uryasev_returns_cvar_and_var() -> None:
    values = cp.Variable(4)
    cvar, excess, zeta = rockafellar_uryasev(values, PROB, 0.75)
    problem = cp.Problem(cp.Minimize(cvar), [values == np.array([0, 1, 3, 6])])
    problem.solve(solver=cp.CLARABEL)
    assert problem.status == cp.OPTIMAL
    assert value(cvar) == pytest.approx(4.2, rel=1e-6)
    # The 0.75-quantile of U is 3.
    assert value(zeta) == pytest.approx(3.0, abs=1e-5)
    assert tuple(excess.shape) == (4,)
    assert zeta.shape == ()


@pytest.mark.parametrize("beta", [0.0, 1.0, -0.1, 1.5, math.nan, True, "0.9"])
def test_rockafellar_uryasev_rejects_bad_beta(beta: object) -> None:
    with pytest.raises(ComponentConfigError, match="beta"):
        rockafellar_uryasev(cp.Variable(4), PROB, cast(float, beta))


@pytest.mark.parametrize(
    ("values", "probability", "match"),
    [
        (cp.Variable((2, 2)), PROB, "1-D"),
        (cp.Variable(3), PROB, "shape"),
        (cp.Variable(4), np.array([0.5, 0.5, 0.5, -0.5]), ">= 0"),
        (cp.Variable(4), np.array([0.4, 0.3, 0.2, np.nan]), "finite"),
        (cp.Variable(4), np.array([0.4, 0.3, 0.2, 0.2]), "sum to 1"),
    ],
)
def test_rockafellar_uryasev_rejects_bad_inputs(
    values: cp.Expression, probability: NDArray[np.float64], match: str
) -> None:
    with pytest.raises(InputMismatchError, match=match):
        rockafellar_uryasev(values, probability, 0.9)


@pytest.mark.parametrize(
    ("alpha", "beta", "match"),
    [
        (-0.1, 0.9, "alpha"),
        (1.1, 0.9, "alpha"),
        (math.nan, 0.9, "alpha"),
        (True, 0.9, "alpha"),
        ("0.5", 0.9, "alpha"),
        (0.5, 0.0, "beta"),
        (0.5, 1.0, "beta"),
        (0.5, None, "beta"),
    ],
)
def test_weighted_cvar_rejects_bad_parameters(
    alpha: object, beta: object, match: str
) -> None:
    with pytest.raises(ComponentConfigError, match=match):
        WeightedCVaR(alpha=cast(float, alpha), beta=cast(float, beta))


def test_weighted_cvar_normalises_parameters_and_names() -> None:
    objective = WeightedCVaR(alpha=1, beta=0.95)
    assert objective.alpha == 1.0
    assert isinstance(objective.alpha, float)
    assert objective == WeightedCVaR(alpha=1.0, beta=0.95)
    assert (MSE.name, ExpectedUncovered.name, WeightedCVaR.name) == (
        "mse",
        "expected_uncovered",
        "weighted_cvar",
    )
