"""Properties of the tail and portfolio formulations (MAR-161, SPEC §6.7).

Owner: MAR-161 (the core design review, ``docs/reviews/core-design-review.md``).
These tests prove the mathematical claims the review relies on, through the
public engine API (``problem.build_problems``, ``solve.solve``,
``evaluate.kpis``) with the real components, on all three bases:

* **The joint problem relaxes the individual one.** At an equal total budget
  ``kappa * E[sum_i L_i]``, the individual designs are feasible for the
  portfolio problem (same caps; their aggregate premium is at most the sum
  of their premiums, which meets the total budget, for the pure premium and
  for the sub-additive cost-of-capital load). So the portfolio optimum is at
  most the objective of the individual designs evaluated on the aggregate.
  For E[U] and weighted CVaR, that aggregate objective is in turn at most the
  sum of the individual objectives (``(sum_i a_i)^+ <= sum_i a_i^+``, and CVaR
  is monotone and sub-additive).
* **A cluster per location is the portfolio scope.** The value-weighted index
  of a single-location cluster is that location's index, so ``Cluster`` with
  one location per cluster solves the portfolio problem.
* **The cluster index is not a restriction of the portfolio scope.** A
  counterexample where one cluster on the value-weighted mean index beats the
  portfolio scope in sample: comparing the two mixes a change of index with
  the change of calibration.
* **The objective equals its KPI.** The objective value of a design equals
  the problem-level KPI that ``evaluate.kpis`` reports for it:
  ``alpha * cvar_uncovered + (1 - alpha) * expected_uncovered`` for weighted
  CVaR, ``expected_uncovered`` for E[U] and ``rmse_residual ** 2`` for MSE.
* **Weighted CVaR reproduces the E[U] design when beta <= P(L_o = 0).** Then
  ``P(U_o = 0) >= beta`` for every payout (``0 <= U_o <= L_o``), so
  ``VaR_beta(U) = 0`` and ``CVaR_beta(U) = E[U] / (1 - beta)`` for every
  design, and the weighted-CVaR objective is a positive multiple of E[U]:
  the same minimisers, for any ``alpha`` in ``(0, 1]``. This is the
  explanation of the annual-basis "coincidence" (``research/notes/
  annual-basis-rerun.md``, observations 4 and 6) as far as it is a theorem.
* **... but not beyond it in general.** A counterexample where the E[U] design has
  ``VaR_beta(U) = 0`` (so ``CVaR_beta = E[U] / (1 - beta)`` *at that design*)
  but ``beta > P(L_o = 0)``, and the weighted-CVaR design is a different,
  lower-CVaR design. ``VaR_beta = 0`` at the E[U] optimum does not make it the
  CVaR optimum.
* **CVaR on an exact step does not depend on the order of ties.** At a
  ``beta`` exactly on a step of the distribution, ``var_cvar`` returns one of
  the two adjacent atoms as VaR (MAR-155), but its CVaR is the exact tail
  mean either way: the step convention moves the VaR KPI and the exceedance
  curves only, never a CVaR, a design or a premium.

Every objective is recomputed in numpy with an outcome measure written out
here independently of ``basis.py`` (per row on ``event_conditional``; per
row plus "no event" on ``event``; every (year, draw) slot on ``annual``, no
pooling). Determinism: hypothesis runs with ``derandomize=True`` and no
example database, as in ``test_engine_properties.py``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st
from numpy.typing import NDArray

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.evaluate import kpis
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
    Objective,
    Pricing,
    Scope,
    SolveResult,
)
from parametric_insurance_design.objectives import (
    MSE,
    ExpectedUncovered,
    WeightedCVaR,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.riskmeasures import var_cvar
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio
from parametric_insurance_design.solve import solve

ATTACHMENT = 20.0
LIMIT = 70.0
BASES = (Basis.EVENT_CONDITIONAL, Basis.EVENT, Basis.ANNUAL)
TOL_INTERIOR_POINT = 1e-6
"""Tolerance in scaled units for Clarabel, HiGHS and OSQP at the default
policy's accuracy, as in ``test_engine_properties.py``."""
TOL_FIRST_ORDER = 1e-4
"""Tolerance in scaled units for SCS at its default accuracy."""
FIRST_ORDER_SOLVERS = frozenset({"SCS"})

PROPERTY_SETTINGS = settings(
    derandomize=True,
    database=None,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
"""Reproducible hypothesis profile: fixed examples, no example database."""


def solver_tol(results: Sequence[SolveResult]) -> float:
    """Tolerance in scaled units for the least accurate solver used."""
    if any(r.solver in FIRST_ORDER_SOLVERS for r in results):
        return TOL_FIRST_ORDER
    return TOL_INTERIOR_POINT


# --- EventSets ---------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    """Event years, draws and data of a random EventSet, before expansion."""

    n_years: int
    years: list[int]
    n_draws: int
    index: NDArray[np.float64]  # (n_events, n_locations)
    loss: NDArray[np.float64]  # (n_events * n_draws, n_locations), event-major
    values: NDArray[np.float64]  # (n_locations,)


def make_eventset(layout: Layout) -> EventSet:
    """Event-major rows (event 0 draws 0..D-1, ...) with rate ``1 / (Y D)``."""
    n_events, n_locations = layout.index.shape
    d = layout.n_draws
    events = pd.DataFrame(
        {
            "event_id": np.repeat([f"e{i}" for i in range(n_events)], d),
            "year": np.repeat(layout.years, d),
            "rate": np.full(n_events * d, 1.0 / (layout.n_years * d)),
            "draw_id": np.tile(np.arange(d), n_events),
            "scenario_id": ["design-review"] * (n_events * d),
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": [f"L{j}" for j in range(n_locations)],
            "lat": np.full(n_locations, 25.0),
            "lon": np.linspace(-81.0, -80.0, n_locations),
            "value": layout.values,
            "name": [f"Asset {j}" for j in range(n_locations)],
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name="synthetic", release="1"),
        index=IndexDefinition(definition="wind at the asset", unit="m/s"),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=layout.n_years,
        scenario="design review properties",
        provenance=Provenance(
            producer="tests",
            producer_version="0",
            created_at=datetime(2026, 10, 31, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events,
        locations=locations,
        index=np.repeat(layout.index, d, axis=0),
        loss=layout.loss,
        metadata=metadata,
    )


@st.composite
def layouts(
    draw: st.DrawFn, min_locations: int = 2, max_locations: int = 3
) -> EventSet:
    """3-8 years, 2..n_years events in random years (repeats and gaps), 2-3
    locations, one or two draws per event. Losses are 0 about a third of
    the time, so zero-loss outcomes exist on every basis. At most one event
    per year on average, so the event basis is defined."""
    n_years = draw(st.integers(3, 8))
    n_events = draw(st.integers(2, n_years))
    years = draw(
        st.lists(st.integers(0, n_years - 1), min_size=n_events, max_size=n_events)
    )
    n_locations = draw(st.integers(min_locations, max_locations))
    n_draws = draw(st.sampled_from([1, 2]))
    size = n_events * n_locations
    index = draw(st.lists(st.integers(0, 180), min_size=size, max_size=size))
    loss_size = size * n_draws
    loss = draw(
        st.lists(
            st.one_of(st.just(0), st.just(0), st.integers(1, 100)),
            min_size=loss_size,
            max_size=loss_size,
        )
    )
    values = draw(
        st.lists(st.integers(1, 5), min_size=n_locations, max_size=n_locations)
    )
    return make_eventset(
        Layout(
            n_years=n_years,
            years=years,
            n_draws=n_draws,
            index=np.reshape(np.array(index, dtype=np.float64) / 2.0, (n_events, -1)),
            loss=np.reshape(np.array(loss, dtype=np.float64), (n_events * n_draws, -1)),
            values=100.0 * np.array(values, dtype=np.float64),
        )
    )


def step_payouts() -> st.SearchStrategy[StepPayout]:
    """Uniform step payouts on ``[ATTACHMENT, LIMIT]`` with 1-5 bins."""
    return st.integers(1, 5).map(lambda n: StepPayout(ATTACHMENT, LIMIT, n))


def budgets() -> st.SearchStrategy[Budget | None]:
    """No budget, a zero, a binding and a slack budget."""
    return st.sampled_from([None, Budget(0.0), Budget(0.3), Budget(1.0), Budget(5.0)])


def pricings() -> st.SearchStrategy[Pricing]:
    """The pure premium and two cost-of-capital loads."""
    return st.sampled_from(
        [
            PurePremium(),
            CostOfCapitalLoad(rate=0.1, q=0.9),
            CostOfCapitalLoad(0.5, 0.75),
        ]
    )


def objectives() -> st.SearchStrategy[Objective]:
    """MSE, E[U] and weighted CVaR."""
    return st.one_of(
        st.just(MSE()),
        st.just(ExpectedUncovered()),
        st.builds(
            WeightedCVaR,
            alpha=st.sampled_from([0.3, 0.9, 1.0]),
            beta=st.sampled_from([0.5, 0.8, 0.95]),
        ),
    )


# --- Independent numpy measure and objectives --------------------------------


def numpy_measure(
    eventset: EventSet, basis: Basis
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """``(G, p)``: a dense outcome-by-row 0/1 matrix and outcome probabilities.

    Written from SPEC §6.2 without ``basis.py``: ``event_conditional`` one
    outcome per row with ``rate / sum(rate)``; ``event`` every row with its
    rate, then "no event"; ``annual`` every (year, draw) slot of every year.
    """
    n_rows = eventset.n_rows
    rates = eventset.rates
    if basis is Basis.EVENT_CONDITIONAL:
        return np.eye(n_rows), rates / rates.sum()
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


@dataclass(frozen=True)
class Measure:
    """The numpy measure of one basis over an EventSet's rows."""

    grouping: NDArray[np.float64]
    probability: NDArray[np.float64]

    @classmethod
    def of(cls, eventset: EventSet, basis: Basis) -> Measure:
        """Build the measure."""
        return cls(*numpy_measure(eventset, basis))

    def expectation(self, per_row: NDArray[np.float64]) -> float:
        """Expected outcome sum of per-row values."""
        return float(self.probability @ (self.grouping @ per_row))

    def zero_loss_mass(self, loss: NDArray[np.float64]) -> float:
        """``P(L_o = 0)``: probability of the outcomes without loss."""
        return float(self.probability[self.grouping @ loss == 0.0].sum())

    @property
    def max_rows_per_outcome(self) -> float:
        """Largest number of rows in one outcome (at least 1)."""
        return max(1.0, float(self.grouping.sum(axis=1).max()))

    def expected_uncovered(
        self, loss: NDArray[np.float64], payout: NDArray[np.float64]
    ) -> float:
        """``E[U]`` with ``U_o = sum_{e in o} (L_e - pi_e)^+``."""
        return self.expectation(np.maximum(loss - payout, 0.0))

    def objective(
        self,
        objective: Objective,
        loss: NDArray[np.float64],
        payout: NDArray[np.float64],
    ) -> float:
        """SPEC §6 objective over outcomes, in numpy, loss units."""
        if isinstance(objective, MSE):
            residual = self.grouping @ (loss - payout)
            return float(self.probability @ residual**2)
        uncovered = self.grouping @ np.maximum(loss - payout, 0.0)
        expected = float(self.probability @ uncovered)
        if isinstance(objective, ExpectedUncovered):
            return expected
        if isinstance(objective, WeightedCVaR):
            _, cvar = var_cvar(uncovered, self.probability, objective.beta)
            return objective.alpha * cvar + (1.0 - objective.alpha) * expected
        raise AssertionError(f"no numpy evaluation for {objective!r}")


def homogeneity(objective: Objective) -> int:
    """Degree of the objective in the losses: 2 for MSE, else 1."""
    return 2 if isinstance(objective, MSE) else 1


def tail_factor(objective: Objective) -> float:
    """``1 / (1 - beta)`` for weighted CVaR (its Lipschitz factor), else 1."""
    if isinstance(objective, WeightedCVaR):
        return 1.0 / (1.0 - objective.beta)
    return 1.0


# --- Designs -------------------------------------------------------------------


@dataclass(frozen=True)
class Design:
    """One solved design problem with its built problem."""

    built: BuiltProblem
    result: SolveResult

    def payout(self) -> NDArray[np.float64]:
        """The design's objective-level payout per row, loss units."""
        index = self.built.context.problem.index
        theta = self.result.theta
        return self.result.payout_structure.evaluate(index, theta).sum(axis=1)

    @property
    def loss(self) -> NDArray[np.float64]:
        """Objective-level loss per row, loss units."""
        return self.built.context.problem.loss

    @property
    def cap(self) -> NDArray[np.float64]:
        """Payout cap per entity, loss units."""
        ctx = self.built.context
        return ctx.cap * ctx.scale


def designs(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    pricing: Pricing,
    constraints: Sequence[Constraint],
    basis: Basis,
) -> list[Design]:
    """Build and solve every design problem of a scope."""
    built = build_problems(
        eventset, scope, payout, objective, pricing, constraints, basis=basis
    )
    return [Design(b, solve(b, pricing=pricing)) for b in built]


def budget_of(constraints: Sequence[Constraint]) -> Budget | None:
    """The budget among the constraints, if any."""
    found = [c for c in constraints if isinstance(c, Budget)]
    return found[0] if found else None


# --- The joint problem relaxes the individual one -----------------------------


@given(
    eventset=layouts(),
    basis=st.sampled_from(BASES),
    payout=step_payouts(),
    objective=objectives(),
    pricing=pricings(),
    budget=budgets(),
)
@settings(PROPERTY_SETTINGS, max_examples=150)
def test_portfolio_optimum_is_at_most_the_individual_designs_on_the_aggregate(
    eventset: EventSet,
    basis: Basis,
    payout: StepPayout,
    objective: Objective,
    pricing: Pricing,
    budget: Budget | None,
) -> None:
    """In sample, at an equal total budget, the portfolio optimum is at most
    the aggregate objective of the individual designs, because the individual
    designs are feasible for the portfolio problem."""
    constraints = () if budget is None else (budget,)
    individual = designs(
        eventset, Individual(), payout, objective, pricing, constraints, basis
    )
    (portfolio,) = designs(
        eventset, Portfolio(), payout, objective, pricing, constraints, basis
    )
    results = [d.result for d in individual] + [portfolio.result]
    tol = solver_tol(results)
    measure = Measure.of(eventset, basis)
    lib_measure = portfolio.built.context.measure
    scales = [d.result.scale for d in individual] + [portfolio.result.scale]
    loss_tol = tol * sum(scales) * measure.max_rows_per_outcome

    # Same entities, same caps: the individual thetas fit the portfolio's.
    assert portfolio.result.entity_ids == tuple(d.result.problem_id for d in individual)
    ind_cap = np.concatenate([d.cap for d in individual])
    np.testing.assert_allclose(portfolio.cap, ind_cap, rtol=1e-12)

    # Budget: aggregate premium <= sum of premiums <= kappa * E[sum_i L_i].
    aggregate_payout = np.sum([d.payout() for d in individual], axis=0)
    aggregate_premium = pricing.premium_value(aggregate_payout, lib_measure)
    premium_sum = sum(d.result.premium for d in individual)
    assert aggregate_premium <= premium_sum + loss_tol
    if budget is not None:
        total_budget = budget.loading * measure.expectation(portfolio.loss)
        assert premium_sum <= total_budget + loss_tol
        assert portfolio.result.premium <= total_budget + loss_tol

    # The relaxation: the portfolio optimum is no worse.
    h = homogeneity(objective)
    obj_tol = (
        tol
        * sum(scales) ** h
        * measure.max_rows_per_outcome**h
        * tail_factor(objective)
        * (2.0 if h == 2 else 1.0)
    )
    on_aggregate = measure.objective(objective, portfolio.loss, aggregate_payout)
    assert portfolio.result.objective_value <= on_aggregate + obj_tol
    assert measure.objective(
        objective, portfolio.loss, portfolio.payout()
    ) == pytest.approx(portfolio.result.objective_value, abs=obj_tol)

    # One-sided objectives net across assets: aggregate <= sum of the parts.
    if not isinstance(objective, MSE):
        own = sum(measure.objective(objective, d.loss, d.payout()) for d in individual)
        assert on_aggregate <= own + obj_tol


# --- Cluster scope against the portfolio scope --------------------------------


@dataclass(frozen=True)
class OneClusterPerLocation:
    """Clustering strategy: location ``i`` (EventSet order) is cluster ``i + 1``."""

    def assign(self, eventset: EventSet, n_clusters: int) -> Mapping[str, int]:
        """Assign every location to its own cluster."""
        assert n_clusters == eventset.n_locations
        return {loc: i + 1 for i, loc in enumerate(eventset.location_ids)}


@dataclass(frozen=True)
class AllInOneCluster:
    """Clustering strategy: every location in cluster 1."""

    def assign(self, eventset: EventSet, n_clusters: int) -> Mapping[str, int]:
        """Assign every location to cluster 1."""
        assert n_clusters == 1
        return dict.fromkeys(eventset.location_ids, 1)


@given(
    eventset=layouts(),
    basis=st.sampled_from(BASES),
    payout=step_payouts(),
    objective=objectives(),
    pricing=pricings(),
    budget=budgets(),
)
@settings(PROPERTY_SETTINGS, max_examples=60)
def test_one_cluster_per_location_is_the_portfolio_scope(
    eventset: EventSet,
    basis: Basis,
    payout: StepPayout,
    objective: Objective,
    pricing: Pricing,
    budget: Budget | None,
) -> None:
    """Singleton clusters: the value-weighted index is the point index, the
    caps are the asset caps, so the cluster problem is the portfolio one."""
    constraints = () if budget is None else (budget,)
    scope = Cluster(OneClusterPerLocation(), n_clusters=eventset.n_locations)
    (cluster,) = designs(
        eventset, scope, payout, objective, pricing, constraints, basis
    )
    (portfolio,) = designs(
        eventset, Portfolio(), payout, objective, pricing, constraints, basis
    )
    np.testing.assert_array_equal(
        cluster.built.context.problem.index, portfolio.built.context.problem.index
    )
    np.testing.assert_array_equal(cluster.cap, portfolio.cap)
    results = [cluster.result, portfolio.result]
    measure = Measure.of(eventset, basis)
    h = homogeneity(objective)
    obj_tol = (
        solver_tol(results)
        * portfolio.result.scale**h
        * measure.max_rows_per_outcome**h
        * tail_factor(objective)
        * 2.0
    )
    assert cluster.result.objective_value == pytest.approx(
        portfolio.result.objective_value, abs=obj_tol
    )


def _two_location_eventset(
    index: Sequence[Sequence[float]], loss: Sequence[Sequence[float]]
) -> EventSet:
    """One event per year, two locations of equal value."""
    n = len(index)
    return make_eventset(
        Layout(
            n_years=n,
            years=list(range(n)),
            n_draws=1,
            index=np.array(index, dtype=np.float64),
            loss=np.array(loss, dtype=np.float64),
            values=np.array([100.0, 100.0]),
        )
    )


@pytest.mark.parametrize("basis", BASES)
def test_one_cluster_can_beat_the_portfolio_scope_in_sample(basis: Basis) -> None:
    """The cluster index is not a restriction of the portfolio scope.

    The loss occurs only when both winds are high. The mean wind separates
    that event from the others; no sum ``f_1(x_1) + f_2(x_2)`` of monotone
    non-negative steps can. So one cluster on the value-weighted mean index
    has MSE 0, and the portfolio scope (one payout per asset) has MSE
    ``(10 / 3) ** 2 * 3 / 4``: the best additive fit pays ``10 / 3`` per
    asset at high wind."""
    eventset = _two_location_eventset(
        index=[[60.0, 60.0], [60.0, 20.0], [20.0, 60.0], [20.0, 20.0]],
        loss=[[5.0, 5.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]],
    )
    payout = StepPayout(ATTACHMENT, LIMIT, 5)
    constraints = (Budget(5.0),)
    (cluster,) = designs(
        eventset,
        Cluster(AllInOneCluster(), n_clusters=1),
        payout,
        MSE(),
        PurePremium(),
        constraints,
        basis,
    )
    (portfolio,) = designs(
        eventset, Portfolio(), payout, MSE(), PurePremium(), constraints, basis
    )
    p = 0.25  # every basis gives each of the four events probability 1/4
    assert cluster.result.objective_value == pytest.approx(0.0, abs=1e-6)
    assert portfolio.result.objective_value == pytest.approx(
        p * 3 * (10.0 / 3.0) ** 2, rel=1e-5
    )


# --- The objective equals its KPI ----------------------------------------------


@given(
    eventset=layouts(min_locations=1),
    basis=st.sampled_from(BASES),
    scope=st.sampled_from([Individual(), Portfolio()]),
    payout=step_payouts(),
    objective=objectives(),
    budget=budgets(),
)
@settings(PROPERTY_SETTINGS, max_examples=80)
def test_objective_value_equals_its_problem_level_kpi(
    eventset: EventSet,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    budget: Budget | None,
) -> None:
    """``evaluate.kpis`` reports, at ``level = "problem"``, the quantity each
    design minimised: the objective is the KPI, on every basis."""
    constraints = () if budget is None else (budget,)
    solved = designs(
        eventset, scope, payout, objective, PurePremium(), constraints, basis
    )
    beta = objective.beta if isinstance(objective, WeightedCVaR) else 0.9
    table = kpis(
        eventset,
        scope,
        [d.result for d in solved],
        basis=basis,
        beta=beta,
        run_id="design-review",
    )
    problem_rows = table[table["level"] == "problem"]
    measure = Measure.of(eventset, basis)
    for d in solved:
        rows = problem_rows[problem_rows["problem_id"] == d.result.problem_id]
        value = dict(zip(rows["kpi"], rows["value"], strict=True))
        if isinstance(objective, MSE):
            reported = value["rmse_residual"] ** 2
        elif isinstance(objective, ExpectedUncovered):
            reported = value["expected_uncovered"]
        else:
            assert isinstance(objective, WeightedCVaR)
            reported = (
                objective.alpha * value["cvar_uncovered"]
                + (1.0 - objective.alpha) * value["expected_uncovered"]
            )
        h = homogeneity(objective)
        tol = (
            solver_tol([d.result])
            * d.result.scale**h
            * measure.max_rows_per_outcome**h
            * tail_factor(objective)
        )
        assert d.result.objective_value == pytest.approx(reported, abs=tol)


# --- Weighted CVaR and E[U] ----------------------------------------------------


@given(
    eventset=layouts(min_locations=1),
    basis=st.sampled_from(BASES),
    scope=st.sampled_from([Individual(), Portfolio()]),
    payout=step_payouts(),
    budget=budgets(),
    alpha=st.sampled_from([0.5, 0.9, 1.0]),
    share=st.sampled_from([0.3, 0.7, 0.95]),
)
@settings(PROPERTY_SETTINGS, max_examples=120)
def test_weighted_cvar_reproduces_expected_uncovered_below_the_zero_loss_mass(
    eventset: EventSet,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    budget: Budget | None,
    alpha: float,
    share: float,
) -> None:
    """``beta <= P(L_o = 0)`` on every design problem: the weighted-CVaR design
    is an E[U] design, and its objective is ``(alpha / (1 - beta) + 1 -
    alpha) * min E[U]``. With ``alpha = 1`` this is MAR-161's "wCVaR with
    alpha = 1 reproduces the E[U] design", under the condition that makes it
    a theorem (sufficient, not necessary)."""
    constraints = () if budget is None else (budget,)
    measure = Measure.of(eventset, basis)
    zero_mass = min(
        measure.zero_loss_mass(scope.materialise(eventset, spec).loss)
        for spec in scope.partition(eventset)
    )
    assume(zero_mass >= 0.1)
    beta = share * zero_mass
    eu = designs(
        eventset, scope, payout, ExpectedUncovered(), PurePremium(), constraints, basis
    )
    wcvar = designs(
        eventset,
        scope,
        payout,
        WeightedCVaR(alpha, beta),
        PurePremium(),
        constraints,
        basis,
    )
    factor = alpha / (1.0 - beta) + 1.0 - alpha
    for a, b in zip(wcvar, eu, strict=True):
        tol = (
            solver_tol([a.result, b.result])
            * b.result.scale
            * measure.max_rows_per_outcome
            * factor
        )
        best = b.result.objective_value
        # The weighted-CVaR design is an E[U] minimiser ...
        assert measure.expected_uncovered(a.loss, a.payout()) == pytest.approx(
            best, abs=tol
        )
        # ... and its objective is the constant multiple of E[U].
        assert a.result.objective_value == pytest.approx(factor * best, abs=tol)


def _counterexample_eventset() -> EventSet:
    """100 years, one location, bins [20, 45) and [45, 70).

    40 years without an event; 50 years with an event in bin 0 and loss 1;
    9 years with an event in bin 1 and loss 10; 1 year with an event in bin 1
    and loss 0. ``P(L_o = 0) = 0.41``.
    """
    index = [30.0] * 50 + [60.0] * 10
    loss = [1.0] * 50 + [10.0] * 9 + [0.0]
    return make_eventset(
        Layout(
            n_years=100,
            years=list(range(60)),
            n_draws=1,
            index=np.array(index)[:, None],
            loss=np.array(loss)[:, None],
            values=np.array([100.0]),
        )
    )


@pytest.mark.parametrize("basis", [Basis.ANNUAL, Basis.EVENT])
@pytest.mark.parametrize("alpha", [1.0, 0.9])
def test_var_zero_at_the_expected_uncovered_design_is_not_enough(
    basis: Basis, alpha: float
) -> None:
    """``beta = 0.9 > P(L_o = 0) = 0.41``. Budget 0.8 a year.

    E[U] fills bin 0 first (each unit of premium removes a unit of E[U]
    there, 0.9 in bin 1): ``theta = (1, 3)``, unique, ``E[U] = 0.63``, and
    only the 9 % of years with loss 10 are uncovered, so ``VaR_0.9(U) = 0``
    and ``CVaR_0.9(U) = E[U] / 0.1 = 6.3``. Weighted CVaR moves the budget to
    bin 1: ``theta = (0, 8)``, ``CVaR_0.9(U) = 1.9``, ``E[U] = 0.68``. So the
    E[U] design having ``VaR_beta = 0`` does not make it the CVaR design."""
    eventset = _counterexample_eventset()
    payout = StepPayout(ATTACHMENT, LIMIT, 2)
    constraints = (Budget(4.0 / 7.0),)  # E[L] = 1.4 a year, budget 0.8
    measure = Measure.of(eventset, basis)
    loss = eventset.loss[:, 0]
    assert measure.zero_loss_mass(loss) == pytest.approx(0.41)

    (eu,) = designs(
        eventset,
        Individual(),
        payout,
        ExpectedUncovered(),
        PurePremium(),
        constraints,
        basis,
    )
    np.testing.assert_allclose(eu.result.theta[0], [1.0, 3.0], atol=1e-6)
    uncovered = measure.grouping @ np.maximum(loss - eu.payout(), 0.0)
    var, cvar = var_cvar(uncovered, measure.probability, 0.9)
    assert var == pytest.approx(0.0, abs=1e-6)
    assert cvar == pytest.approx(6.3, abs=1e-5)

    (wc,) = designs(
        eventset,
        Individual(),
        payout,
        WeightedCVaR(alpha, 0.9),
        PurePremium(),
        constraints,
        basis,
    )
    np.testing.assert_allclose(wc.result.theta[0], [0.0, 8.0], atol=1e-5)
    uncovered = measure.grouping @ np.maximum(loss - wc.payout(), 0.0)
    _, cvar_wc = var_cvar(uncovered, measure.probability, 0.9)
    assert cvar_wc == pytest.approx(1.9, abs=1e-5)
    assert measure.expected_uncovered(loss, wc.payout()) == pytest.approx(
        0.68, abs=1e-6
    )


# --- CVaR on an exact step -------------------------------------------------------


@given(data=st.data())
@settings(PROPERTY_SETTINGS, max_examples=200)
def test_cvar_on_an_exact_step_does_not_depend_on_the_order_of_ties(
    data: st.DataObject,
) -> None:
    """Equally likely outcomes (plus, optionally, a pooled zero atom as on the
    annual basis) and ``beta = k / n`` exactly on a step: VaR is one of the
    two adjacent atoms, depending on rounding and the order of ties, but CVaR
    is the exact tail mean for every order."""
    n = data.draw(st.integers(2, 60), label="n")
    pooled = data.draw(st.integers(0, n - 1), label="pooled_zero_slots")
    n_listed = n - pooled
    values = np.array(
        data.draw(
            st.lists(st.integers(0, 4), min_size=n_listed, max_size=n_listed),
            label="values",
        ),
        dtype=np.float64,
    )
    probability = np.full(n_listed, 1.0 / n)
    if pooled:
        values = np.append(values, 0.0)
        probability = np.append(probability, pooled / n)
    k = data.draw(st.integers(1, n - 1), label="k")
    beta = k / n
    # The n equally likely slots, the pooled ones expanded, in exact order.
    slots = np.sort(np.concatenate([values[:n_listed], np.zeros(pooled)]))
    tail_mean = float(slots[k:].mean())

    order = np.array(data.draw(st.permutations(range(values.size)), label="order"))
    var_a, cvar_a = var_cvar(values, probability, beta)
    var_b, cvar_b = var_cvar(values[order], probability[order], beta)
    scale = max(1.0, float(values.max()))
    for var, cvar in ((var_a, cvar_a), (var_b, cvar_b)):
        assert var in (slots[k - 1], slots[k])
        assert cvar == pytest.approx(tail_mean, abs=1e-12 * scale * n)
    assert cvar_a == pytest.approx(cvar_b, abs=1e-12 * scale * n)
