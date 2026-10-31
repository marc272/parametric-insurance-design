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
fitted ``theta``, with an outcome measure written out here independently of
``basis.py``: on ``annual`` one outcome per (year, draw) slot, every slot of
every year listed (no pooling of the empty ones), probability
``1 / (n_years * n_draws)``; on ``event`` one outcome per row with its rate
plus a "no event" outcome.

Determinism: hypothesis runs with ``derandomize=True`` and no example
database, as in the sibling file.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from numpy.typing import NDArray

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
"""Tolerance in scaled units for the interior-point solvers and OSQP at the
default policy's accuracy, as in ``test_engine_properties.py``."""
TOL_FIRST_ORDER = 1e-4
"""Tolerance in scaled units for SCS at its default accuracy."""
FIRST_ORDER_SOLVERS = frozenset({"SCS"})
BASES = (Basis.EVENT, Basis.ANNUAL)

PROPERTY_SETTINGS = settings(
    derandomize=True,
    database=None,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
"""Reproducible hypothesis profile: fixed examples, no example database."""


def solver_tol(solver: str) -> float:
    """Tolerance in scaled units for a solver's accuracy."""
    return TOL_FIRST_ORDER if solver in FIRST_ORDER_SOLVERS else TOL_INTERIOR_POINT


# --- EventSets ---------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    """Event years, draws and data of a random EventSet, before expansion."""

    n_years: int
    years: list[int]
    n_draws: int
    index: NDArray[np.float64]  # (n_events, n_locations)
    loss: NDArray[np.float64]  # (n_events * n_draws, n_locations), event-major


def make_eventset(layout: Layout, loss_factor: float = 1.0) -> EventSet:
    """Event-major rows: event 0 draws 0..D-1, event 1 ...; rate 1/(Y D)."""
    n_events, n_locations = layout.index.shape
    d = layout.n_draws
    events = pd.DataFrame(
        {
            "event_id": np.repeat([f"e{i}" for i in range(n_events)], d),
            "year": np.repeat(layout.years, d),
            "rate": np.full(n_events * d, 1.0 / (layout.n_years * d)),
            "draw_id": np.tile(np.arange(d), n_events),
            "scenario_id": ["prop"] * (n_events * d),
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
        n_years=layout.n_years,
        scenario="property tests",
        provenance=Provenance(
            producer="tests",
            producer_version="0",
            created_at=datetime(2026, 10, 27, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events,
        locations=locations,
        index=np.repeat(layout.index, d, axis=0),
        loss=layout.loss * loss_factor,
        metadata=metadata,
    )


@st.composite
def layouts(draw: st.DrawFn) -> Layout:
    """3-8 years, 2..n_years events in random years (repeats and gaps), 1-3
    locations, one or two draws per event. At most one event per year on
    average, so the event basis is defined too."""
    n_years = draw(st.integers(3, 8))
    n_events = draw(st.integers(2, n_years))
    years = draw(
        st.lists(st.integers(0, n_years - 1), min_size=n_events, max_size=n_events)
    )
    n_locations = draw(st.integers(1, 3))
    n_draws = draw(st.sampled_from([1, 2]))
    size = n_events * n_locations
    index = draw(st.lists(st.integers(0, 180), min_size=size, max_size=size))
    loss_size = size * n_draws
    loss = draw(st.lists(st.integers(0, 100), min_size=loss_size, max_size=loss_size))
    return Layout(
        n_years=n_years,
        years=years,
        n_draws=n_draws,
        index=np.reshape(np.array(index, dtype=np.float64) / 2.0, (n_events, -1)),
        loss=np.reshape(np.array(loss, dtype=np.float64), (n_events * n_draws, -1)),
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


# --- Independent numpy measure and evaluation --------------------------------


def numpy_measure(
    eventset: EventSet, basis: Basis
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """``(G, p)``: a dense outcome-by-row 0/1 matrix and outcome probabilities.

    Written from SPEC §6.2 without ``basis.py``: annual lists every (year,
    draw) slot of every year; event lists every row and then "no event".
    """
    n_rows = eventset.n_rows
    rates = eventset.rates
    if basis is Basis.EVENT:
        grouping = np.vstack([np.eye(n_rows), np.zeros((1, n_rows))])
        return grouping, np.append(rates, 1.0 - rates.sum())
    n_years = eventset.metadata.n_years
    n_draws = round(1.0 / (rates[0] * n_years))
    years = eventset.events["year"].to_numpy()
    draws = eventset.events["draw_id"].to_numpy()
    grouping = np.zeros((n_years * n_draws, n_rows))
    for row in range(n_rows):
        grouping[years[row] * n_draws + draws[row], row] = 1.0
    return grouping, np.full(n_years * n_draws, 1.0 / (n_years * n_draws))


def objective_value(
    objective: Objective,
    loss: NDArray[np.float64],
    payout: NDArray[np.float64],
    grouping: NDArray[np.float64],
    probability: NDArray[np.float64],
) -> float:
    """SPEC §6 objective over outcomes, in numpy (MSE: squared summed
    residual of each outcome, the MAR-24 choice)."""
    if isinstance(objective, MSE):
        return float(probability @ (grouping @ (loss - payout)) ** 2)
    uncovered = grouping @ np.maximum(loss - payout, 0.0)
    expected = float(probability @ uncovered)
    if isinstance(objective, ExpectedUncovered):
        return expected
    if isinstance(objective, WeightedCVaR):
        _, cvar = var_cvar(uncovered, probability, objective.beta)
        return objective.alpha * cvar + (1.0 - objective.alpha) * expected
    raise AssertionError(f"no numpy evaluation for {objective!r}")


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
            objective, self.loss, self.payout(theta), self.grouping, self.probability
        )

    @property
    def tol(self) -> float:
        """Tolerance in loss units for the solver that produced the result."""
        return solver_tol(self.result.solver) * self.result.scale

    def objective_tol(self, objective: Objective) -> float:
        """Tolerance for objective values in loss units."""
        homogeneity = 2 if isinstance(objective, MSE) else 1
        return solver_tol(self.result.solver) * self.result.scale**homogeneity


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
    eventset = make_eventset(layout)
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
    eventset = make_eventset(layout)
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
    base = design(make_eventset(layout), basis, scope, payout, objective, constraints)
    scaled = design(
        make_eventset(layout, factor), basis, scope, payout, objective, constraints
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
