"""Engine properties on the ``event`` and ``annual`` bases (MAR-24, SPEC §6.7).

The sibling of ``test_engine_properties.py`` (MAR-15), which covers
``event_conditional``. The same properties, on random small EventSets whose
years hold several events, some years none, and optionally two draws per
event:

* the solution is feasible (``theta >= 0``, monotone, ``<= cap``, budget
  met) and no worse than the zero payout and a flat feasible payout;
* ``alpha = 0``: weighted CVaR equals E[U];
* scaling invariance: losses times ``c`` give payouts times ``c``.

Every check recomputes the objective in numpy from the EventSet and the
fitted ``theta``, with an outcome measure written out independently of
``basis.py`` (``_properties.numpy_measure``): on ``annual`` one outcome per
(year, draw) slot, every slot of every year listed (no pooling of the empty
ones), probability ``1 / (n_years * n_draws)``; on ``event`` one outcome per
row with its rate plus a "no event" outcome.

Determinism: hypothesis runs with ``derandomize=True`` and no example
database, as in the sibling file.
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
from parametric_insurance_design.eventset import (
    EventSet,
)
from parametric_insurance_design.interfaces import (
    Constraint,
    DesignProblem,
    Objective,
    Scope,
    SolveResult,
)
from parametric_insurance_design.objectives import (
    ExpectedUncovered,
    WeightedCVaR,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.solve import solve

from ._properties import (
    PROPERTY_SETTINGS,
    Layout,
    budgets,
    homogeneity,
    layout_eventset,
    layouts,
    numpy_measure,
    objective_value,
    objectives,
    scopes,
    solver_tol,
    step_payouts,
)

BASES = (Basis.EVENT, Basis.ANNUAL)


# --- EventSets ---------------------------------------------------------------


# --- Independent numpy measure and evaluation --------------------------------


@dataclass(frozen=True)
class Outcome:
    """One solved design problem with its data and the numpy measure."""

    result: SolveResult
    problem: DesignProblem
    grouping: NDArray[np.float64]
    probability: NDArray[np.float64]

    @property
    def loss(self) -> NDArray[np.float64]:
        """Objective-level loss per row."""
        return self.problem.loss

    @property
    def cap(self) -> NDArray[np.float64]:
        """Payout cap per entity: the entity's maximum loss (thesis)."""
        return self.problem.entity_loss.max(axis=0)

    def payout(self, theta: NDArray[np.float64]) -> NDArray[np.float64]:
        """Objective-level payout per row of any ``theta``."""
        entity = self.result.payout_structure.evaluate(self.problem.index, theta)
        return entity.sum(axis=1)

    def expectation(self, values: NDArray[np.float64]) -> float:
        """Expected outcome sum of per-row values."""
        return float(self.probability @ (self.grouping @ values))

    def value(self, objective: Objective, theta: NDArray[np.float64]) -> float:
        """Objective value of ``theta`` in loss units, computed in numpy."""
        return objective_value(
            objective,
            self.loss,
            self.payout(theta),
            self.probability,
            self.grouping,
        )

    @property
    def tol(self) -> float:
        """Tolerance in loss units for the solver that produced the result."""
        return solver_tol(self.result.solver) * self.result.scale

    def objective_tol(self, objective: Objective) -> float:
        """Tolerance for objective values in loss units."""
        degree = homogeneity(objective)
        return solver_tol(self.result.solver) * self.result.scale**degree


def design(
    eventset: EventSet,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    constraints: Sequence[Constraint] = (),
) -> list[Outcome]:
    """Build and solve every design problem; pair each result with its data."""
    built = build_problems(
        eventset, scope, payout, objective, PurePremium(), constraints, basis=basis
    )
    grouping, probability = numpy_measure(eventset, basis)
    out = []
    for problem in built:
        result = solve(problem)
        data = scope.materialise(eventset, result.spec)
        out.append(Outcome(result, data, grouping, probability))
    return out


def flat_feasible_theta(outcome: Outcome, budget: Budget | None) -> NDArray[np.float64]:
    """A flat payout ``t * cap_j`` per entity that meets the cap and budget.

    Every index value falls in some bin, so the premium is
    ``t * sum_j cap_j * E[number of rows in the outcome]``.
    """
    cap = outcome.cap
    t = 1.0
    rows_per_outcome = outcome.expectation(np.ones(outcome.problem.n_rows))
    if budget is not None and cap.sum() > 0:
        allowed = budget.loading * outcome.expectation(outcome.loss)
        t = min(1.0, allowed / (cap.sum() * rows_per_outcome))
    n_params = outcome.result.payout_structure.n_params
    return np.repeat((t * cap)[:, None], n_params, axis=1)


# --- Properties ---------------------------------------------------------------


@given(
    layout=layouts(),
    basis=st.sampled_from(BASES),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    budget=budgets(),
)
@settings(PROPERTY_SETTINGS, max_examples=120)
def test_solution_is_feasible_and_beats_zero_and_flat_payouts(
    layout: Layout,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    budget: Budget | None,
) -> None:
    """theta >= 0, monotone, <= cap, budget met; objective <= zero and flat."""
    eventset = layout_eventset(layout)
    constraints = () if budget is None else (budget,)
    for outcome in design(eventset, basis, scope, payout, objective, constraints):
        theta = outcome.result.theta
        tol = outcome.tol
        assert np.all(theta >= -tol)
        assert np.all(np.diff(theta, axis=1) >= -tol)
        assert np.all(theta <= outcome.cap[:, None] + tol)
        # Annual premium E[pi], recomputed from theta; it is sum_e rate_e pi_e.
        premium = outcome.expectation(outcome.payout(theta))
        assert premium == pytest.approx(
            float(eventset.rates @ outcome.payout(theta)), abs=tol
        )
        assert outcome.result.premium == pytest.approx(premium, abs=tol)
        if budget is not None:
            assert premium <= budget.loading * outcome.expectation(outcome.loss) + tol
        value = outcome.value(objective, theta)
        objective_tol = outcome.objective_tol(objective)
        assert outcome.result.objective_value == pytest.approx(value, abs=objective_tol)
        zero = np.zeros_like(theta)
        flat = flat_feasible_theta(outcome, budget)
        assert value <= outcome.value(objective, zero) + objective_tol
        assert value <= outcome.value(objective, flat) + objective_tol


@given(
    layout=layouts(),
    basis=st.sampled_from(BASES),
    scope=scopes(),
    payout=step_payouts(),
    budget=budgets(),
    beta=st.sampled_from([0.5, 0.9, 0.99]),
)
@settings(PROPERTY_SETTINGS, max_examples=40)
def test_weighted_cvar_with_alpha_zero_equals_expected_uncovered(
    layout: Layout,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    budget: Budget | None,
    beta: float,
) -> None:
    """alpha = 0: the same optimum as E[U], whatever beta (SPEC §6.7)."""
    eventset = layout_eventset(layout)
    constraints = () if budget is None else (budget,)
    cvar0 = design(eventset, basis, scope, payout, WeightedCVaR(0.0, beta), constraints)
    eu = design(eventset, basis, scope, payout, ExpectedUncovered(), constraints)
    for a, b in zip(cvar0, eu, strict=True):
        tol = a.objective_tol(ExpectedUncovered())
        assert a.result.objective_value == pytest.approx(
            b.result.objective_value, abs=tol
        )
        assert a.value(ExpectedUncovered(), a.result.theta) == pytest.approx(
            b.result.objective_value, abs=tol
        )
        assert "cvar" not in a.result.diagnostics


@given(
    layout=layouts(),
    basis=st.sampled_from(BASES),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    budget=budgets(),
    factor=st.sampled_from([1e-3, 0.25, 7.0, 1e4]),
)
@settings(PROPERTY_SETTINGS, max_examples=60)
def test_scaling_losses_scales_payouts(
    layout: Layout,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    budget: Budget | None,
    factor: float,
) -> None:
    """Losses times c: theta, payouts and premium times c, objective times
    c ** homogeneity (1 for E[U] and CVaR, 2 for MSE)."""
    constraints = () if budget is None else (budget,)
    base = design(layout_eventset(layout), basis, scope, payout, objective, constraints)
    scaled = design(
        layout_eventset(layout, factor), basis, scope, payout, objective, constraints
    )
    degree = homogeneity(objective)
    for a, b in zip(base, scaled, strict=True):
        tol = factor * a.tol
        np.testing.assert_allclose(b.result.theta, factor * a.result.theta, atol=tol)
        np.testing.assert_allclose(
            b.payout(b.result.theta), factor * a.payout(a.result.theta), atol=tol
        )
        assert b.result.premium == pytest.approx(factor * a.result.premium, abs=tol)
        assert b.result.objective_value == pytest.approx(
            factor**degree * a.result.objective_value,
            abs=factor**degree * a.objective_tol(objective),
        )
