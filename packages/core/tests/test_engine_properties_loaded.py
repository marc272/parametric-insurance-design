"""Engine property tests under cost-of-capital pricing (MAR-27, from MAR-15).

Sibling of ``test_engine_properties.py`` (MAR-15), whose EventSet strategy,
components and tolerances it reuses through the public engine API
(``problem.build_problems`` and ``solve.solve``):

* ``rate = 0``: ``CostOfCapitalLoad`` gives the same problem as
  ``PurePremium``, so the same ``theta`` and premium, bit for bit.
* Loaded pricing: the solution is feasible, the budget holds under the
  *loaded* premium recomputed in numpy (``(1 - r) E[pi] + r CVaR_q(pi)``,
  ``riskmeasures.var_cvar``), ``SolveResult.premium`` (``solve`` given the
  pricing, MAR-143) equals that premium whether the budget binds or not, and
  the optimum is no worse than the zero payout.
* Loading tightens the budget: the loaded premium of a payout is at least its
  pure premium, so the optimum with a loaded budget is no better than with
  the pure one, and no better at a higher ``rate``.
* Scaling invariance: losses times ``c`` give ``theta`` and the loaded
  premium times ``c``.

These use the ``event_conditional`` basis, as the MAR-15 tests do. On the
``annual`` and ``event`` bases (MAR-24), with the EventSets and the
independent numpy outcome measure of ``test_engine_properties_bases.py``:
``r = 0`` equals ``PurePremium`` again, and the loaded premium is priced over
the basis's outcomes (years on ``annual``): ``SolveResult.premium`` equals
the numpy premium, the budget holds under it, and the optimum is no worse
than no cover.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from numpy.typing import NDArray

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Constraint,
    DesignProblem,
    Objective,
    Pricing,
    Scope,
    SolveResult,
)
from parametric_insurance_design.objectives import MSE
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.riskmeasures import var_cvar
from parametric_insurance_design.solve import solve

from .test_engine_properties import (
    PROPERTY_SETTINGS,
    eventsets,
    objective_value,
    objectives,
    scopes,
    solver_tol,
    step_payouts,
    with_scaled_losses,
)
from .test_engine_properties_bases import Layout, layouts, numpy_measure
from .test_engine_properties_bases import make_eventset as make_layout_eventset
from .test_engine_properties_bases import objective_value as basis_objective_value


def loaded_pricings() -> st.SearchStrategy[CostOfCapitalLoad]:
    """Cost-of-capital loads: paper rates and levels plus extremes."""
    return st.builds(
        CostOfCapitalLoad,
        rate=st.sampled_from([0.06, 0.1, 0.5, 1.0]),
        q=st.sampled_from([0.5, 0.9, 0.99, 0.995]),
    )


def budgets() -> st.SearchStrategy[Budget | None]:
    """No budget, a zero, a binding or a slack budget."""
    return st.sampled_from([None, Budget(0.0), Budget(0.3), Budget(1.0), Budget(5.0)])


@dataclass(frozen=True)
class Solved:
    """One solved design problem with its data in loss units."""

    result: SolveResult
    problem: DesignProblem
    probability: NDArray[np.float64]

    @property
    def payout(self) -> NDArray[np.float64]:
        """Objective-level payout per row of the fitted ``theta``."""
        entity = self.result.payout_structure.evaluate(
            self.problem.index, self.result.theta
        )
        return entity.sum(axis=1)

    @property
    def expected_loss(self) -> float:
        return float(self.probability @ self.problem.loss)

    def pure(self) -> float:
        """Pure premium of the fitted payout, in numpy."""
        return float(self.probability @ self.payout)

    def loaded(self, pricing: CostOfCapitalLoad) -> float:
        """Loaded premium of the fitted payout, in numpy."""
        _, cvar = var_cvar(self.payout, self.probability, pricing.q)
        return (1.0 - pricing.rate) * self.pure() + pricing.rate * cvar

    @property
    def tol(self) -> float:
        """Tolerance in loss units for the solver that produced the result."""
        return solver_tol(self.result.solver) * self.result.scale

    def objective_tol(self, objective: Objective) -> float:
        homogeneity = 2 if isinstance(objective, MSE) else 1
        return solver_tol(self.result.solver) * self.result.scale**homogeneity


def design(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    pricing: Pricing,
    constraints: Sequence[Constraint] = (),
) -> list[Solved]:
    """Build and solve every design problem; pair each result with its data."""
    built = build_problems(
        eventset,
        scope,
        payout,
        objective,
        pricing,
        constraints,
        basis=Basis.EVENT_CONDITIONAL,
    )
    probability = eventset.rates / eventset.rates.sum()
    out = []
    for problem in built:
        result = solve(problem, pricing=pricing)
        out.append(
            Solved(result, scope.materialise(eventset, result.spec), probability)
        )
    return out


@given(
    eventset=eventsets(),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    budget=budgets(),
    q=st.sampled_from([0.5, 0.99, 0.995]),
)
@settings(PROPERTY_SETTINGS, max_examples=40)
def test_rate_zero_equals_pure_premium(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    budget: Budget | None,
    q: float,
) -> None:
    """r = 0: the same theta and premium as PurePremium, bit for bit."""
    constraints = () if budget is None else (budget,)
    zero = design(
        eventset, scope, payout, objective, CostOfCapitalLoad(0.0, q), constraints
    )
    pure = design(eventset, scope, payout, objective, PurePremium(), constraints)
    for a, b in zip(zero, pure, strict=True):
        np.testing.assert_array_equal(a.result.theta, b.result.theta)
        assert a.result.premium == b.result.premium
        assert a.result.objective_value == b.result.objective_value


@given(
    eventset=eventsets(),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    pricing=loaded_pricings(),
    budget=budgets(),
)
@settings(PROPERTY_SETTINGS, max_examples=120)
def test_loaded_solution_is_feasible_and_meets_the_loaded_budget(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    pricing: CostOfCapitalLoad,
    budget: Budget | None,
) -> None:
    """theta >= 0, monotone, <= cap; loaded premium <= kappa E[L]; reported
    premium is the loaded premium of theta; objective <= zero payout."""
    constraints = () if budget is None else (budget,)
    for s in design(eventset, scope, payout, objective, pricing, constraints):
        theta, tol = s.result.theta, s.tol
        cap = s.problem.entity_loss.max(axis=0)
        assert np.all(theta >= -tol)
        assert np.all(np.diff(theta, axis=1) >= -tol)
        assert np.all(theta <= cap[:, None] + tol)
        premium = s.loaded(pricing)
        # Reported premium: the loaded premium of theta, budget binding or not.
        assert s.result.premium == pytest.approx(premium, abs=tol)
        # The loaded premium is at least the pure one.
        assert premium >= s.pure() - tol
        if budget is not None:
            assert premium <= budget.loading * s.expected_loss + tol
        # Reported objective matches numpy; no worse than the zero payout.
        value = objective_value(objective, s.problem.loss, s.payout, s.probability)
        objective_tol = s.objective_tol(objective)
        assert s.result.objective_value == pytest.approx(value, abs=objective_tol)
        zero = np.zeros_like(s.problem.loss)
        no_cover = objective_value(objective, s.problem.loss, zero, s.probability)
        assert value <= no_cover + objective_tol


@given(
    eventset=eventsets(),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    budget=st.sampled_from([Budget(0.3), Budget(1.0)]),
    q=st.sampled_from([0.9, 0.99]),
)
@settings(PROPERTY_SETTINGS, max_examples=40)
def test_loading_never_improves_the_optimum(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    budget: Budget,
    q: float,
) -> None:
    """Optimum under pure <= under r = 0.06 <= under r = 0.10 <= under r = 1:
    the loaded premium is non-decreasing in r, so the feasible set shrinks."""
    previous = [-np.inf]
    for pricing in (
        PurePremium(),
        CostOfCapitalLoad(0.06, q),
        CostOfCapitalLoad(0.10, q),
        CostOfCapitalLoad(1.0, q),
    ):
        solved = design(eventset, scope, payout, objective, pricing, (budget,))
        if len(previous) != len(solved):
            previous = [-np.inf] * len(solved)
        for i, s in enumerate(solved):
            value = s.result.objective_value
            assert value >= previous[i] - s.objective_tol(objective)
            previous[i] = value


@given(
    eventset=eventsets(),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    pricing=loaded_pricings(),
    budget=budgets(),
    factor=st.sampled_from([1e-3, 7.0, 1e4]),
)
@settings(PROPERTY_SETTINGS, max_examples=40)
def test_scaling_losses_scales_the_loaded_design(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    pricing: CostOfCapitalLoad,
    budget: Budget | None,
    factor: float,
) -> None:
    """Losses times c: theta and the loaded premium times c."""
    constraints = () if budget is None else (budget,)
    base = design(eventset, scope, payout, objective, pricing, constraints)
    scaled = design(
        with_scaled_losses(eventset, factor),
        scope,
        payout,
        objective,
        pricing,
        constraints,
    )
    for a, b in zip(base, scaled, strict=True):
        tol = factor * a.tol
        np.testing.assert_allclose(b.payout, factor * a.payout, atol=tol)
        assert b.result.premium == pytest.approx(factor * a.result.premium, abs=tol)
        assert b.loaded(pricing) == pytest.approx(factor * a.loaded(pricing), abs=tol)


# --- The annual and event bases (MAR-24) --------------------------------------


@dataclass(frozen=True)
class SolvedOnBasis:
    """One solved design problem with the numpy outcome measure of MAR-24's
    sibling tests (every (year, draw) slot on ``annual``; rows plus "no
    event" on ``event``)."""

    result: SolveResult
    problem: DesignProblem
    grouping: NDArray[np.float64]
    probability: NDArray[np.float64]

    @property
    def payout(self) -> NDArray[np.float64]:
        """Objective-level payout per row of the fitted ``theta``."""
        entity = self.result.payout_structure.evaluate(
            self.problem.index, self.result.theta
        )
        return entity.sum(axis=1)

    def loaded(self, pricing: CostOfCapitalLoad) -> float:
        """Loaded premium over outcomes (e.g. years), in numpy."""
        outcome_payout = self.grouping @ self.payout
        expected = float(self.probability @ outcome_payout)
        _, cvar = var_cvar(outcome_payout, self.probability, pricing.q)
        return (1.0 - pricing.rate) * expected + pricing.rate * cvar

    @property
    def tol(self) -> float:
        return solver_tol(self.result.solver) * self.result.scale


def design_on_basis(
    eventset: EventSet,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    pricing: Pricing,
    constraints: Sequence[Constraint] = (),
) -> list[SolvedOnBasis]:
    """Build and solve every design problem on ``basis``."""
    built = build_problems(
        eventset, scope, payout, objective, pricing, constraints, basis=basis
    )
    grouping, probability = numpy_measure(eventset, basis)
    return [
        SolvedOnBasis(
            result,
            scope.materialise(eventset, result.spec),
            grouping,
            probability,
        )
        for result in (solve(problem, pricing=pricing) for problem in built)
    ]


@given(
    layout=layouts(),
    basis=st.sampled_from([Basis.ANNUAL, Basis.EVENT]),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    budget=budgets(),
    q=st.sampled_from([0.5, 0.99]),
)
@settings(PROPERTY_SETTINGS, max_examples=30)
def test_rate_zero_equals_pure_premium_on_annual_and_event_bases(
    layout: Layout,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    budget: Budget | None,
    q: float,
) -> None:
    """r = 0: the same theta and premium as PurePremium on every basis."""
    eventset = make_layout_eventset(layout)
    constraints = () if budget is None else (budget,)
    zero = design_on_basis(
        eventset,
        basis,
        scope,
        payout,
        objective,
        CostOfCapitalLoad(0.0, q),
        constraints,
    )
    pure = design_on_basis(
        eventset, basis, scope, payout, objective, PurePremium(), constraints
    )
    for a, b in zip(zero, pure, strict=True):
        np.testing.assert_array_equal(a.result.theta, b.result.theta)
        assert a.result.premium == b.result.premium


@given(
    layout=layouts(),
    basis=st.sampled_from([Basis.ANNUAL, Basis.EVENT]),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    pricing=loaded_pricings(),
    budget=budgets(),
)
@settings(PROPERTY_SETTINGS, max_examples=80)
def test_loaded_premium_on_annual_and_event_bases(
    layout: Layout,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    pricing: CostOfCapitalLoad,
    budget: Budget | None,
) -> None:
    """The loaded premium is priced over the basis's outcomes (years on
    ``annual``): ``SolveResult.premium`` equals the numpy premium over
    outcomes, it is at least the pure premium, the budget holds under it,
    and the objective is no worse than without cover."""
    eventset = make_layout_eventset(layout)
    constraints = () if budget is None else (budget,)
    for s in design_on_basis(
        eventset, basis, scope, payout, objective, pricing, constraints
    ):
        tol = s.tol
        premium = s.loaded(pricing)
        assert s.result.premium == pytest.approx(premium, abs=tol)
        pure = float(s.probability @ (s.grouping @ s.payout))
        assert premium >= pure - tol
        expected_loss = float(s.probability @ (s.grouping @ s.problem.loss))
        if budget is not None:
            assert premium <= budget.loading * expected_loss + tol
        loss = s.problem.loss
        value = basis_objective_value(
            objective, loss, s.payout, s.grouping, s.probability
        )
        no_cover = basis_objective_value(
            objective, loss, np.zeros_like(loss), s.grouping, s.probability
        )
        homogeneity = 2 if isinstance(objective, MSE) else 1
        objective_tol = solver_tol(s.result.solver) * s.result.scale**homogeneity
        assert s.result.objective_value == pytest.approx(value, abs=objective_tol)
        assert value <= no_cover + objective_tol
