"""Analytical and property tests of the design engine (SPEC §6.7, MAR-15).

Owner: MAR-15 (ADR 0002 ownership map). These tests check correctness that
does not depend on the thesis numbers, through the public API only:
``problem.build_problems`` and ``solve.solve`` with the real components
(``StepPayout``, ``Individual``/``Portfolio``, ``MSE``/``ExpectedUncovered``/
``WeightedCVaR``, ``PurePremium``, ``Budget``).

* Analytical: with fine bins, no noise and a slack budget, the individual MSE
  solution is the bin-wise conditional mean loss.
* Properties on random small EventSets (hypothesis): ``theta >= 0``,
  monotone, ``<= cap``, budget satisfied, and the optimum is no worse than
  the zero payout and a flat feasible payout.
* ``alpha = 0``: weighted CVaR equals E[U]. ``beta -> 0``: weighted CVaR
  converges to E[U], inside the bound ``E[U] <= CVaR_beta(U) <= E[U] / (1 -
  beta)`` for ``U >= 0``.
* Scaling invariance: losses times ``c`` give payouts times ``c``.

Every check recomputes the quantity in numpy from the EventSet and the
fitted ``theta``, independently of the cvxpy expressions. Only the
``event_conditional`` basis is implemented so far (``event`` and ``annual``
come with MAR-24), so every test uses it.

Determinism: hypothesis runs with ``derandomize=True`` and no example
database, so CI draws the same examples every run. The analytical tests draw
their data from an explicit ``np.random.Generator``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

# hypothesis is locked in the uv workspace's test group, so this skip never
# fires there. The CLIMADA pixi env (packages/climada) also runs the core
# tests and has no hypothesis yet; the skip reason names that gap.
pytest.importorskip(
    "hypothesis",
    reason=(
        "hypothesis is not installed: the CLIMADA pixi env lacks it "
        "(MAR-15 follow-up: add it to packages/climada/pixi.toml)"
    ),
)

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.evaluate import var_cvar
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.interfaces import (
    Constraint,
    DesignProblem,
    Objective,
    Scope,
    SolveResult,
)
from parametric_insurance_design.objectives import (
    MSE,
    ExpectedUncovered,
    WeightedCVaR,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.scopes import Individual, Portfolio
from parametric_insurance_design.solve import solve

ATTACHMENT = 20.0
LIMIT = 70.0
TOL_INTERIOR_POINT = 1e-6
"""Tolerance in scaled units (losses divided by the problem's scale, so <= 1)
for interior-point solvers (Clarabel, HiGHS) and for OSQP with the default
policy's ``eps_abs = eps_rel = 1e-8`` (MAR-98): measured violations are about
3e-9 (Clarabel) and 1.2e-8 (OSQP) on these EventSets."""
TOL_FIRST_ORDER = 1e-4
"""Tolerance in scaled units for SCS (first-order, run at its default
accuracy). Real violations would be of the order of the losses themselves,
i.e. near 1."""
FIRST_ORDER_SOLVERS = frozenset({"SCS"})


def solver_tol(solver: str) -> float:
    """Tolerance in scaled units for a solver's accuracy."""
    return TOL_FIRST_ORDER if solver in FIRST_ORDER_SOLVERS else TOL_INTERIOR_POINT


PROPERTY_SETTINGS = settings(
    derandomize=True,
    database=None,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
"""Reproducible hypothesis profile: fixed examples, no example database."""


# --- EventSets ---------------------------------------------------------------


def make_eventset(
    index: NDArray[np.float64],
    loss: NDArray[np.float64],
    rates: NDArray[np.float64],
) -> EventSet:
    """EventSet with one event per simulation year (row ``i`` is year ``i``)."""
    n_rows, n_locations = index.shape
    events = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(n_rows)],
            "year": np.arange(n_rows),
            "rate": rates,
            "draw_id": np.zeros(n_rows, dtype=np.int64),
            "scenario_id": ["prop"] * n_rows,
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": [f"L{j}" for j in range(n_locations)],
            "lat": np.full(n_locations, 25.0),
            "lon": np.linspace(-81.0, -80.0, n_locations),
            "value": np.full(n_locations, 100.0),
            "name": [f"Asset {j}" for j in range(n_locations)],
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name="synthetic", release="1"),
        index=IndexDefinition(definition="wind at the asset", unit="m/s"),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=n_rows,
        scenario="property tests",
        provenance=Provenance(
            producer="tests",
            producer_version="0",
            created_at=datetime(2026, 10, 25, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events,
        locations=locations,
        index=np.asarray(index, dtype=np.float64),
        loss=np.asarray(loss, dtype=np.float64),
        metadata=metadata,
    )


def with_scaled_losses(eventset: EventSet, factor: float) -> EventSet:
    """The same EventSet with every loss multiplied by ``factor``."""
    return make_eventset(eventset.index, eventset.loss * factor, eventset.rates)


@st.composite
def eventsets(draw: st.DrawFn, max_rows: int = 8, max_locations: int = 3) -> EventSet:
    """Small random EventSets: 2-8 rows, 1-3 locations.

    Index values lie on a 0.5 grid in ``[0, 90]``, so they fall below the
    attachment, inside ``[ATTACHMENT, LIMIT)`` and at or above the limit.
    Losses are integers in ``[0, 100]`` (zero rows included), rates are
    positive and unequal.
    """
    n_rows = draw(st.integers(2, max_rows))
    n_locations = draw(st.integers(1, max_locations))
    size = n_rows * n_locations
    index = draw(st.lists(st.integers(0, 180), min_size=size, max_size=size))
    loss = draw(st.lists(st.integers(0, 100), min_size=size, max_size=size))
    weights = draw(st.lists(st.integers(1, 4), min_size=n_rows, max_size=n_rows))
    return make_eventset(
        np.reshape(np.array(index, dtype=np.float64) / 2.0, (n_rows, n_locations)),
        np.reshape(np.array(loss, dtype=np.float64), (n_rows, n_locations)),
        np.array(weights, dtype=np.float64) / n_rows,
    )


def step_payouts() -> st.SearchStrategy[StepPayout]:
    """Uniform step payouts on ``[ATTACHMENT, LIMIT]`` with 1-6 bins."""
    return st.integers(1, 6).map(lambda n: StepPayout(ATTACHMENT, LIMIT, n))


def scopes() -> st.SearchStrategy[Scope]:
    """The individual and the portfolio scope."""
    return st.sampled_from([Individual(), Portfolio()])


def budgets() -> st.SearchStrategy[Budget | None]:
    """No budget, a binding budget, a zero budget or a slack one."""
    return st.sampled_from([None, Budget(0.0), Budget(0.3), Budget(1.0), Budget(5.0)])


def objectives() -> st.SearchStrategy[Objective]:
    """MSE, E[U] and weighted CVaR with a range of alpha and beta."""
    return st.one_of(
        st.just(MSE()),
        st.just(ExpectedUncovered()),
        st.builds(
            WeightedCVaR,
            alpha=st.sampled_from([0.0, 0.3, 0.7, 1.0]),
            beta=st.sampled_from([0.5, 0.8, 0.95]),
        ),
    )


# --- Independent numpy evaluation -------------------------------------------


@dataclass(frozen=True)
class Outcome:
    """One solved design problem with its data in loss units."""

    result: SolveResult
    problem: DesignProblem
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
        """Probability-weighted mean over rows (event-conditional measure)."""
        return float(self.probability @ values)

    def value(self, objective: Objective, theta: NDArray[np.float64]) -> float:
        """Objective value of ``theta`` in loss units, computed in numpy."""
        return objective_value(
            objective, self.loss, self.payout(theta), self.probability
        )

    @property
    def tol(self) -> float:
        """Tolerance in loss units for the solver that produced the result."""
        return solver_tol(self.result.solver) * self.result.scale

    def objective_tol(self, objective: Objective) -> float:
        """Tolerance for objective values in loss units."""
        homogeneity = 2 if isinstance(objective, MSE) else 1
        return solver_tol(self.result.solver) * self.result.scale**homogeneity


def objective_value(
    objective: Objective,
    loss: NDArray[np.float64],
    payout: NDArray[np.float64],
    probability: NDArray[np.float64],
) -> float:
    """SPEC §6 objective on the event-conditional basis, in numpy.

    The weighted CVaR uses ``evaluate.var_cvar``, the exact discrete CVaR,
    which equals the Rockafellar-Uryasev minimum over ``zeta``.
    """
    if isinstance(objective, MSE):
        return float(probability @ (loss - payout) ** 2)
    uncovered = np.maximum(loss - payout, 0.0)
    expected = float(probability @ uncovered)
    if isinstance(objective, ExpectedUncovered):
        return expected
    if isinstance(objective, WeightedCVaR):
        _, cvar = var_cvar(uncovered, probability, objective.beta)
        return objective.alpha * cvar + (1.0 - objective.alpha) * expected
    raise AssertionError(f"no numpy evaluation for {objective!r}")


def design(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    constraints: Sequence[Constraint] = (),
) -> list[Outcome]:
    """Build and solve every design problem; pair each result with its data."""
    built = build_problems(
        eventset,
        scope,
        payout,
        objective,
        PurePremium(),
        constraints,
        basis=Basis.EVENT_CONDITIONAL,
    )
    probability = eventset.rates / eventset.rates.sum()
    out = []
    for problem in built:
        result = solve(problem)
        data = scope.materialise(eventset, result.spec)
        out.append(Outcome(result, data, probability))
    return out


def flat_feasible_theta(outcome: Outcome, budget: Budget | None) -> NDArray[np.float64]:
    """A flat payout per entity that meets the cap and the budget.

    Entity ``j`` pays ``t * cap_j`` on every row (every index value falls in
    some bin), so the premium is ``t * sum_j cap_j``. ``t`` is 1, or smaller
    so that the premium equals the budget.
    """
    cap = outcome.cap
    t = 1.0
    if budget is not None and cap.sum() > 0:
        allowed = budget.loading * outcome.expectation(outcome.loss)
        t = min(1.0, allowed / cap.sum())
    n_params = outcome.result.payout_structure.n_params
    return np.repeat((t * cap)[:, None], n_params, axis=1)


# --- Analytical: MSE equals the bin-wise conditional mean -------------------


def conditional_mean_by_bin(
    payout: StepPayout,
    index: NDArray[np.float64],
    loss: NDArray[np.float64],
    probability: NDArray[np.float64],
) -> tuple[NDArray[np.bool_], NDArray[np.float64]]:
    """Occupied bins and the probability-weighted mean loss in each."""
    bins = payout.bin_index(index)
    mass = np.bincount(bins, weights=probability, minlength=payout.n_params)
    weighted = np.bincount(bins, weights=probability * loss, minlength=payout.n_params)
    occupied = mass > 0
    mean = np.zeros(payout.n_params)
    mean[occupied] = weighted[occupied] / mass[occupied]
    return occupied, mean


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_individual_mse_is_the_binwise_conditional_mean_loss(seed: int) -> None:
    """Fine bins, losses a deterministic monotone function of the index (no
    noise) and a slack budget: theta_k = E[L | index in B_k] (SPEC §6.7)."""
    rng = np.random.default_rng(seed)
    n_rows, n_bins = 200, 25
    index = rng.uniform(0.0, 90.0, size=(n_rows, 2))
    value = np.array([100.0, 40.0])
    damage = np.clip((index - 25.0) / 50.0, 0.0, 1.0)
    loss = value * np.stack([damage[:, 0] ** 2, damage[:, 1] ** 3], axis=1)
    rates = rng.uniform(0.5, 2.0, size=n_rows) / n_rows
    eventset = make_eventset(index, loss, rates)
    payout = StepPayout(ATTACHMENT, LIMIT, n_bins)

    outcomes = design(eventset, Individual(), payout, MSE(), (Budget(2.0),))

    assert len(outcomes) == 2
    for j, outcome in enumerate(outcomes):
        occupied, mean = conditional_mean_by_bin(
            payout, index[:, j], loss[:, j], outcome.probability
        )
        assert occupied.sum() >= 20  # fine bins, nearly all occupied
        theta = outcome.result.theta[0]
        np.testing.assert_allclose(theta[occupied], mean[occupied], atol=outcome.tol)
        # Tower property: the premium of the conditional mean is E[L], half
        # the budget, so the budget is slack.
        expected_loss = outcome.expectation(outcome.loss)
        assert outcome.result.premium == pytest.approx(expected_loss, abs=outcome.tol)
        assert outcome.result.premium < 2.0 * expected_loss


@given(data=st.data())
@settings(PROPERTY_SETTINGS, max_examples=60)
def test_individual_mse_is_the_binwise_conditional_mean_loss_on_random_data(
    data: st.DataObject,
) -> None:
    """The same on random tiny EventSets: any monotone loss-of-index function,
    any bins, unequal rates. With one row per bin, theta reproduces L."""
    n_rows = data.draw(st.integers(2, 10), label="n_rows")
    grid = data.draw(
        st.lists(st.integers(0, 10), min_size=91, max_size=91), label="increments"
    )
    loss_of_index = np.cumsum(np.array(grid, dtype=np.float64))  # non-decreasing
    cells = data.draw(
        st.lists(st.integers(0, 90), min_size=n_rows, max_size=n_rows), label="index"
    )
    weights = data.draw(
        st.lists(st.integers(1, 4), min_size=n_rows, max_size=n_rows), label="rates"
    )
    payout = data.draw(st.integers(1, 12), label="n_bins")
    step = StepPayout(ATTACHMENT, LIMIT, payout)
    index = np.array(cells, dtype=np.float64)[:, None]
    loss = loss_of_index[np.array(cells)][:, None]
    eventset = make_eventset(index, loss, np.array(weights, dtype=np.float64) / n_rows)

    (outcome,) = design(eventset, Individual(), step, MSE(), (Budget(1.5),))

    occupied, mean = conditional_mean_by_bin(
        step, index[:, 0], loss[:, 0], outcome.probability
    )
    theta = outcome.result.theta[0]
    np.testing.assert_allclose(theta[occupied], mean[occupied], atol=outcome.tol)


# --- Properties on random EventSets ----------------------------------------


@given(
    eventset=eventsets(),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    budget=budgets(),
)
@settings(PROPERTY_SETTINGS, max_examples=150)
def test_solution_is_feasible_and_beats_zero_and_flat_payouts(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    budget: Budget | None,
) -> None:
    """theta >= 0, monotone, <= cap, budget met; objective <= zero and flat."""
    constraints = () if budget is None else (budget,)
    for outcome in design(eventset, scope, payout, objective, constraints):
        theta = outcome.result.theta
        tol = outcome.tol
        # Payout family: non-negative, non-decreasing in the bin, capped.
        assert np.all(theta >= -tol)
        assert np.all(np.diff(theta, axis=1) >= -tol)
        assert np.all(theta <= outcome.cap[:, None] + tol)
        # Budget, recomputed from theta: E[pi] <= kappa * E[L].
        premium = outcome.expectation(outcome.payout(theta))
        assert outcome.result.premium == pytest.approx(premium, abs=tol)
        if budget is not None:
            assert premium <= budget.loading * outcome.expectation(outcome.loss) + tol
        # Reported objective matches the numpy objective of theta.
        value = outcome.value(objective, theta)
        objective_tol = outcome.objective_tol(objective)
        assert outcome.result.objective_value == pytest.approx(value, abs=objective_tol)
        # No worse than two feasible comparators.
        zero = np.zeros_like(theta)
        flat = flat_feasible_theta(outcome, budget)
        assert value <= outcome.value(objective, zero) + objective_tol
        assert value <= outcome.value(objective, flat) + objective_tol


# --- alpha = 0 and beta -> 0 --------------------------------------------------


@given(
    eventset=eventsets(),
    scope=scopes(),
    payout=step_payouts(),
    budget=budgets(),
    beta=st.sampled_from([0.5, 0.9, 0.99]),
)
@settings(PROPERTY_SETTINGS, max_examples=50)
def test_weighted_cvar_with_alpha_zero_equals_expected_uncovered(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    budget: Budget | None,
    beta: float,
) -> None:
    """alpha = 0: the same optimum as E[U], whatever beta (SPEC §6.7)."""
    constraints = () if budget is None else (budget,)
    cvar0 = design(eventset, scope, payout, WeightedCVaR(0.0, beta), constraints)
    eu = design(eventset, scope, payout, ExpectedUncovered(), constraints)
    for a, b in zip(cvar0, eu, strict=True):
        tol = a.objective_tol(ExpectedUncovered())
        assert a.result.objective_value == pytest.approx(
            b.result.objective_value, abs=tol
        )
        # The alpha = 0 solution is an E[U] optimum, evaluated in numpy.
        assert a.value(ExpectedUncovered(), a.result.theta) == pytest.approx(
            b.result.objective_value, abs=tol
        )
        assert "cvar" not in a.result.diagnostics


BETAS_TO_ZERO = (0.5, 0.1, 1e-2, 1e-3)


@given(
    eventset=eventsets(),
    scope=scopes(),
    payout=step_payouts(),
    budget=budgets(),
    alpha=st.sampled_from([0.25, 0.5, 1.0]),
)
@settings(PROPERTY_SETTINGS, max_examples=30)
def test_weighted_cvar_converges_to_expected_uncovered_as_beta_goes_to_zero(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    budget: Budget | None,
    alpha: float,
) -> None:
    """beta -> 0: for U >= 0, E[U] <= CVaR_beta(U) <= E[U] / (1 - beta), so the
    weighted-CVaR optimum F_beta satisfies
    F_EU <= F_beta <= F_EU * (1 + alpha * beta / (1 - beta)), and F_beta is
    non-increasing as beta decreases (CVaR is non-decreasing in beta)."""
    constraints = () if budget is None else (budget,)
    eu = design(eventset, scope, payout, ExpectedUncovered(), constraints)
    previous = [np.inf] * len(eu)
    for beta in BETAS_TO_ZERO:
        cvar = design(eventset, scope, payout, WeightedCVaR(alpha, beta), constraints)
        for i, (a, b) in enumerate(zip(cvar, eu, strict=True)):
            tol = a.objective_tol(ExpectedUncovered())
            f_beta, f_eu = a.result.objective_value, b.result.objective_value
            assert f_eu - tol <= f_beta
            assert f_beta <= f_eu * (1.0 + alpha * beta / (1.0 - beta)) + tol
            assert f_beta <= previous[i] + tol
            previous[i] = f_beta


# --- Scaling invariance -------------------------------------------------------


@given(
    eventset=eventsets(),
    scope=scopes(),
    payout=step_payouts(),
    objective=objectives(),
    budget=budgets(),
    factor=st.sampled_from([1e-3, 0.25, 7.0, 1e4]),
)
@settings(PROPERTY_SETTINGS, max_examples=80)
def test_scaling_losses_scales_payouts(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    budget: Budget | None,
    factor: float,
) -> None:
    """Losses times c: theta, payouts and premium times c, objective times
    c ** homogeneity (1 for E[U] and CVaR, 2 for MSE)."""
    constraints = () if budget is None else (budget,)
    base = design(eventset, scope, payout, objective, constraints)
    scaled = design(
        with_scaled_losses(eventset, factor), scope, payout, objective, constraints
    )
    homogeneity = 2 if isinstance(objective, MSE) else 1
    for a, b in zip(base, scaled, strict=True):
        tol = factor * a.tol
        np.testing.assert_allclose(b.result.theta, factor * a.result.theta, atol=tol)
        np.testing.assert_allclose(
            b.payout(b.result.theta), factor * a.payout(a.result.theta), atol=tol
        )
        assert b.result.premium == pytest.approx(factor * a.result.premium, abs=tol)
        assert b.result.objective_value == pytest.approx(
            factor**homogeneity * a.result.objective_value,
            abs=factor**homogeneity * a.objective_tol(objective),
        )
