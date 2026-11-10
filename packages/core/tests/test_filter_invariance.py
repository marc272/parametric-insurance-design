"""The threshold filter is exact under ``below_attachment="zero"`` (MAR-170).

Owner: MAR-170. Design review MAR-161, finding F1
(``docs/reviews/core-design-review.md``). On the ``event`` and ``annual``
bases, a row that a threshold filter dropped, and a year without rows, is
mass with zero loss and zero payout (``basis.py``; SPEC §5: "dropped rows
count as zero-loss mass").

With ``StepPayout(..., below_attachment="zero")`` a row whose index is below
the attachment at every location pays nothing for every ``theta``. If its loss
is zero too, it adds nothing to any outcome, on either basis: dropping it
leaves the distribution of (loss, payout) over outcomes, and so the objective,
the premium and the budget as functions of ``theta``, unchanged. The property
tests check the consequence on solved designs, for MSE, E[U] and weighted
CVaR, on the individual and portfolio scopes, with and without a budget:

* the optimal objective value is the same with and without those rows;
* the design calibrated without them has, on all rows, the objective value
  and the premium recorded for it, and meets the budget there: it is an
  optimal design of the unfiltered problem, and vice versa.

``theta`` itself is compared where the optimum is unique (the review's
reproduction below, MSE). Elsewhere optima can tie (the E[U] and CVaR LPs,
MSE with an empty bin), and two solves of equal problems may then return
different optimal ``theta``; the properties above hold for every optimum.

Under the default ``"first_bin"`` (the thesis code) a kept row below the
attachment pays ``theta[j, 0]`` and a dropped one nothing, and the review's
reproduction shows that the filter then changes the design and its premium.

The rows are dropped in two ways: by ``EventSet.filter_threshold`` at the
attachment (the thesis filter; the generated rows below the attachment at
every location then have zero loss), and as a subset of the zero-loss rows
below the attachment, while other rows below the attachment keep a positive
loss (they pay nothing under ``"zero"`` either way).

Every objective and premium is recomputed in numpy with an outcome measure
written out here independently of ``basis.py``: on ``event`` one outcome per
row plus "no event"; on ``annual`` every (year, draw) slot of every year, no
pooling. Determinism: hypothesis runs with ``derandomize=True`` and no example
database, as in ``test_engine_properties.py``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from numpy.typing import NDArray

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.bootstrap import bootstrap_kpis, resample_years
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.evaluate import exceedance_curves, kpis
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.experiment.config import parse_config
from parametric_insurance_design.experiment.runner import run_config
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import (
    Constraint,
    Objective,
    Scope,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.objectives import (
    MSE,
    ExpectedUncovered,
    WeightedCVaR,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.riskmeasures import var_cvar
from parametric_insurance_design.scopes import Individual, Portfolio
from parametric_insurance_design.solve import solve

ATTACHMENT = 20.0
LIMIT = 70.0
BASES = (Basis.EVENT, Basis.ANNUAL)
TOL_INTERIOR_POINT = 1e-6
"""Tolerance in scaled units for Clarabel, HiGHS and OSQP at the default
policy's accuracy, as in ``test_engine_properties.py``."""
TOL_FIRST_ORDER = 1e-4
"""Tolerance in scaled units for SCS at its default accuracy."""
FIRST_ORDER_SOLVERS = frozenset({"SCS"})
EXACT_RTOL = 1e-9
"""Relative tolerance of quantities that are equal as functions of ``theta``
(one ``theta`` evaluated on two EventSets): only the summation order of the
floating-point sums differs."""

PROPERTY_SETTINGS = settings(
    derandomize=True,
    database=None,
    deadline=None,
    print_blob=True,
    suppress_health_check=[HealthCheck.too_slow],
)
"""Reproducible hypothesis profile: fixed examples, no example database."""


def solver_tol(results: Sequence[SolveResult]) -> float:
    """Tolerance in scaled units for the least accurate solver used."""
    if any(r.solver in FIRST_ORDER_SOLVERS for r in results):
        return TOL_FIRST_ORDER
    return TOL_INTERIOR_POINT


def homogeneity(objective: Objective) -> int:
    """Degree of the objective in the losses: 2 for MSE, 1 otherwise."""
    return 2 if isinstance(objective, MSE) else 1


# --- EventSets ---------------------------------------------------------------


@dataclass(frozen=True)
class Layout:
    """Events of a random EventSet, before expansion into draw rows.

    ``quiet`` marks the events below the attachment at every location with
    zero loss in every draw: the rows the tests drop.
    """

    n_years: int
    years: list[int]
    n_draws: int
    index: NDArray[np.float64]  # (n_events, n_locations)
    loss: NDArray[np.float64]  # (n_events * n_draws, n_locations), event-major
    quiet: NDArray[np.bool_]  # (n_events,)
    by_filter: bool  # drop with filter_threshold(ATTACHMENT), else the subset


def make_eventset(layout: Layout, keep: NDArray[np.bool_] | None = None) -> EventSet:
    """Event-major rows (event 0 draws 0..D-1, ...) with rate ``1 / (Y D)``.

    ``keep`` selects events (default: all); rates and ``n_years`` do not
    change, so the dropped events become zero-loss mass.
    """
    n_events, n_locations = layout.index.shape
    d = layout.n_draws
    keep_events = np.ones(n_events, dtype=bool) if keep is None else keep
    keep_rows = np.repeat(keep_events, d)
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
        scenario="filter invariance",
        provenance=Provenance(
            producer="tests",
            producer_version="0",
            created_at=datetime(2026, 10, 31, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events.loc[keep_rows].reset_index(drop=True),
        locations=locations,
        index=np.repeat(layout.index, d, axis=0)[keep_rows],
        loss=layout.loss[keep_rows],
        metadata=metadata,
    )


@st.composite
def layouts(draw: st.DrawFn) -> Layout:
    """3-8 years, 2..n_years events in random years (repeats and gaps), 1-3
    locations, one or two draws per event; at most one event per year on
    average, so the ``event`` basis is defined too.

    At least one event is quiet (dropped) and at least one is not; the first
    other event reaches the attachment at location 0, so a row is kept.
    Index values lie on a 0.5 grid in ``[0, 90]`` (quiet events: in
    ``[0, ATTACHMENT)``), losses are integers in ``[0, 100]``. When the rows
    are dropped by the filter, every other event below the attachment at
    every location gets zero loss too, so the filter drops no loss.
    """
    n_years = draw(st.integers(3, 8))
    n_events = draw(st.integers(2, n_years))
    years = draw(
        st.lists(st.integers(0, n_years - 1), min_size=n_events, max_size=n_events)
    )
    n_locations = draw(st.integers(1, 3))
    n_draws = draw(st.sampled_from([1, 2]))
    quiet = np.array(
        draw(st.lists(st.booleans(), min_size=n_events, max_size=n_events))
    )
    quiet[draw(st.integers(0, n_events - 1))] = True
    others = np.flatnonzero(~quiet)
    if others.size == 0:
        quiet[0] = False
        others = np.array([0])
    size = n_events * n_locations
    index = np.reshape(
        np.array(draw(st.lists(st.integers(0, 180), min_size=size, max_size=size)))
        / 2.0,
        (n_events, n_locations),
    )
    below = np.array(
        draw(
            st.lists(
                st.integers(0, int(2 * ATTACHMENT) - 1), min_size=size, max_size=size
            )
        )
    )
    index[quiet] = np.reshape(below / 2.0, (n_events, n_locations))[quiet]
    index[others[0], 0] = max(index[others[0], 0], ATTACHMENT)
    loss_size = size * n_draws
    loss = np.reshape(
        np.array(
            draw(st.lists(st.integers(0, 100), min_size=loss_size, max_size=loss_size)),
            dtype=np.float64,
        ),
        (n_events * n_draws, n_locations),
    )
    by_filter = draw(st.booleans())
    silent = quiet | (by_filter & np.all(index < ATTACHMENT, axis=1))
    loss[np.repeat(silent, n_draws)] = 0.0
    return Layout(
        n_years=n_years,
        years=years,
        n_draws=n_draws,
        index=index,
        loss=loss,
        quiet=silent,
        by_filter=by_filter,
    )


def drop_quiet(layout: Layout) -> tuple[EventSet, EventSet]:
    """The full EventSet and the one without the quiet events."""
    full = make_eventset(layout)
    if layout.by_filter:
        reduced = full.filter_threshold(ATTACHMENT)
        record = reduced.metadata.filters[-1]
        assert record.expected_loss_dropped == 0.0
    else:
        reduced = make_eventset(layout, keep=~layout.quiet)
    assert reduced.n_rows == full.n_rows - int(layout.quiet.sum()) * layout.n_draws
    return full, reduced


def step_payouts(below_attachment: str) -> st.SearchStrategy[StepPayout]:
    """Uniform step payouts on ``[ATTACHMENT, LIMIT]`` with 1-6 bins."""
    return st.integers(1, 6).map(
        lambda n: StepPayout(
            ATTACHMENT,
            LIMIT,
            n,
            below_attachment=below_attachment,  # type: ignore[arg-type]
        )
    )


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
            alpha=st.sampled_from([0.3, 0.7, 1.0]),
            beta=st.sampled_from([0.5, 0.8, 0.95]),
        ),
    )


# --- Independent numpy measure and evaluation --------------------------------


def numpy_measure(
    eventset: EventSet, basis: Basis
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """``(G, p)``: a dense outcome-by-row 0/1 matrix and outcome probabilities.

    Written from SPEC §6.2 without ``basis.py``: ``annual`` lists every (year,
    draw) slot of every year; ``event`` lists every row and then "no event".
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


@dataclass(frozen=True)
class Priced:
    """A design evaluated in numpy on one EventSet and basis."""

    objective: float
    premium: float
    expected_loss: float


def price(
    eventset: EventSet,
    basis: Basis,
    scope: Scope,
    result: SolveResult,
    objective: Objective,
) -> Priced:
    """Objective, pure premium and E[L] of a design problem's ``theta``.

    The problem is materialised on ``eventset`` from the result's spec, so a
    design calibrated on one EventSet can be evaluated on another.
    """
    problem = scope.materialise(eventset, result.spec)
    payout = result.payout_structure.evaluate(problem.index, result.theta).sum(axis=1)
    loss = problem.loss
    grouping, probability = numpy_measure(eventset, basis)
    if isinstance(objective, MSE):
        value = float(probability @ (grouping @ (loss - payout)) ** 2)
    else:
        uncovered = grouping @ np.maximum(loss - payout, 0.0)
        value = float(probability @ uncovered)
        if isinstance(objective, WeightedCVaR):
            _, cvar = var_cvar(uncovered, probability, objective.beta)
            value = objective.alpha * cvar + (1.0 - objective.alpha) * value
    return Priced(
        objective=value,
        premium=float(probability @ (grouping @ payout)),
        expected_loss=float(probability @ (grouping @ loss)),
    )


def design(
    eventset: EventSet,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    constraints: Sequence[Constraint] = (),
) -> dict[str, SolveResult]:
    """Build and solve every design problem, with the exact premium recorded."""
    built = build_problems(
        eventset, scope, payout, objective, PurePremium(), constraints, basis=basis
    )
    results = (solve(problem, pricing=PurePremium()) for problem in built)
    return {result.problem_id: result for result in results}


# --- The property ----------------------------------------------------------------


@given(
    layout=layouts(),
    basis=st.sampled_from(BASES),
    scope=scopes(),
    payout=step_payouts("zero"),
    objective=objectives(),
    budget=budgets(),
)
@settings(PROPERTY_SETTINGS, max_examples=150)
def test_dropping_quiet_rows_changes_neither_the_design_nor_its_premium(
    layout: Layout,
    basis: Basis,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    budget: Budget | None,
) -> None:
    """``below_attachment="zero"``: the filter at the attachment is exact."""
    full, reduced = drop_quiet(layout)
    constraints = () if budget is None else (budget,)
    on_full = design(full, basis, scope, payout, objective, constraints)
    on_reduced = design(reduced, basis, scope, payout, objective, constraints)
    assert on_full.keys() == on_reduced.keys()
    h = homogeneity(objective)
    for problem_id, a in on_full.items():
        b = on_reduced[problem_id]
        assert a.scale == b.scale
        tol = solver_tol([a, b])
        objective_tol = 2 * tol * a.scale**h
        # The same optimal value with and without the quiet rows.
        assert b.objective_value == pytest.approx(a.objective_value, abs=objective_tol)
        for result in (a, b):
            here = price(full, basis, scope, result, objective)
            there = price(reduced, basis, scope, result, objective)
            # One theta: the same objective, premium and E[L] on both
            # EventSets, up to the order of the floating-point sums.
            assert there.objective == pytest.approx(
                here.objective, rel=EXACT_RTOL, abs=EXACT_RTOL * a.scale**h
            )
            assert there.premium == pytest.approx(
                here.premium, rel=EXACT_RTOL, abs=EXACT_RTOL * a.scale
            )
            assert there.expected_loss == pytest.approx(
                here.expected_loss, rel=EXACT_RTOL, abs=EXACT_RTOL * a.scale
            )
            # The recorded premium is the premium on all rows ...
            assert result.premium == pytest.approx(
                here.premium, rel=EXACT_RTOL, abs=EXACT_RTOL * a.scale
            )
            # ... which meets the budget on all rows ...
            if budget is not None:
                assert here.premium <= budget.loading * here.expected_loss + (
                    tol * a.scale
                )
            # ... and the design is optimal on all rows and on the kept rows.
            assert here.objective <= a.objective_value + objective_tol
            assert there.objective <= b.objective_value + objective_tol


# --- The review's reproduction (MAR-161 F1) -------------------------------------


def review_eventset() -> EventSet:
    """One location, 10 years: (index 30, loss 4), (60, 10) and (5, 0)."""
    layout = Layout(
        n_years=10,
        years=[0, 1, 2],
        n_draws=1,
        index=np.array([[30.0], [60.0], [5.0]]),
        loss=np.array([[4.0], [10.0], [0.0]]),
        quiet=np.array([False, False, True]),
        by_filter=True,
    )
    return make_eventset(layout)


def two_bins(below_attachment: str) -> StepPayout:
    """``StepPayout(20, 70, 2)``: bins [20, 45) and [45, 70)."""
    return StepPayout(20.0, 70.0, 2, below_attachment=below_attachment)  # type: ignore[arg-type]


def premium_on(eventset: EventSet, result: SolveResult, basis: Basis) -> float:
    """Portfolio premium KPI of a design evaluated on ``eventset``."""
    table = kpis(
        eventset,
        Individual(),
        [result],
        basis=basis,
        beta=0.9,
        run_id="review",
        pricing=PurePremium(),
    )
    (value,) = kpi_values(table, "portfolio", "premium")
    return value


def kpi_values(
    table: pd.DataFrame, level: str, kpi: str, subject_id: str | None = None
) -> list[float]:
    """The values of one KPI at one level (and subject) of a ``kpis`` table."""
    mask = (table["level"] == level) & (table["kpi"] == kpi)
    if subject_id is not None:
        mask &= table["subject_id"] == subject_id
    return [float(v) for v in table.loc[mask, "value"].to_numpy()]


def solve_one(
    eventset: EventSet,
    basis: Basis,
    payout: StepPayout,
    objective: Objective,
    budget: Budget,
) -> SolveResult:
    """The single design problem of the review's EventSet."""
    (result,) = design(
        eventset, basis, Individual(), payout, objective, [budget]
    ).values()
    assert result.status is SolveStatus.OPTIMAL
    return result


@pytest.mark.parametrize("basis", BASES)
def test_review_reproduction_first_bin_depends_on_the_filter(basis: Basis) -> None:
    """``"first_bin"``: the filter moves the MSE design and its premium."""
    full = review_eventset()
    filtered = full.filter_threshold(ATTACHMENT)
    assert filtered.n_rows == 2
    assert filtered.metadata.filters[-1].expected_loss_dropped == 0.0
    payout = two_bins("first_bin")
    # MSE, Budget(5): budget 7, slack. The optimum is unique.
    a = solve_one(full, basis, payout, MSE(), Budget(5.0))
    b = solve_one(filtered, basis, payout, MSE(), Budget(5.0))
    np.testing.assert_allclose(a.theta, [[2.0, 10.0]], atol=1e-5)
    np.testing.assert_allclose(b.theta, [[4.0, 10.0]], atol=1e-5)
    assert a.premium == pytest.approx(1.4, abs=1e-6)
    assert b.premium == pytest.approx(1.4, abs=1e-6)
    assert premium_on(full, a, basis) == pytest.approx(1.4, abs=1e-6)
    # Priced on all events, the filtered design costs more than recorded.
    assert premium_on(full, b, basis) == pytest.approx(1.8, abs=1e-5)
    # E[U], Budget(0.5): budget 0.7. On the filtered rows every theta with
    # theta_0 + theta_1 = 7 and theta_0 <= 4 is optimal; on all events it
    # costs 0.7 + theta_0 / 10, over the budget unless theta_0 = 0.
    c = solve_one(full, basis, payout, ExpectedUncovered(), Budget(0.5))
    d = solve_one(filtered, basis, payout, ExpectedUncovered(), Budget(0.5))
    np.testing.assert_allclose(c.theta, [[0.0, 7.0]], atol=1e-5)
    assert d.theta.sum() == pytest.approx(7.0, abs=1e-5)
    assert d.premium == pytest.approx(0.7, abs=1e-6)
    assert premium_on(full, d, basis) == pytest.approx(
        0.7 + d.theta[0, 0] / 10.0, abs=1e-6
    )
    over = replace(d, theta=np.array([[4.0, 3.0]]))
    assert price(
        filtered, basis, Individual(), over, ExpectedUncovered()
    ).objective == (pytest.approx(d.objective_value, abs=1e-6))
    assert premium_on(full, over, basis) == pytest.approx(1.1)
    assert premium_on(full, over, basis) > 0.5 * 1.4


@pytest.mark.parametrize("basis", BASES)
def test_review_reproduction_zero_does_not_depend_on_the_filter(basis: Basis) -> None:
    """``"zero"``: the same MSE design, and every premium as recorded."""
    full = review_eventset()
    filtered = full.filter_threshold(ATTACHMENT)
    payout = two_bins("zero")
    a = solve_one(full, basis, payout, MSE(), Budget(5.0))
    b = solve_one(filtered, basis, payout, MSE(), Budget(5.0))
    np.testing.assert_allclose(a.theta, [[4.0, 10.0]], atol=1e-5)
    np.testing.assert_allclose(b.theta, [[4.0, 10.0]], atol=1e-5)
    for result in (a, b):
        assert result.premium == pytest.approx(1.4, abs=1e-6)
        assert premium_on(full, result, basis) == pytest.approx(1.4, abs=1e-6)
    # E[U]: optima tie (theta_0 + theta_1 = 7), but every one costs 0.7, the
    # budget, on all events and on the filtered rows alike.
    c = solve_one(full, basis, payout, ExpectedUncovered(), Budget(0.5))
    d = solve_one(filtered, basis, payout, ExpectedUncovered(), Budget(0.5))
    assert d.objective_value == pytest.approx(c.objective_value, abs=1e-6)
    for result in (c, d):
        assert result.theta.sum() == pytest.approx(7.0, abs=1e-5)
        assert result.premium == pytest.approx(0.7, abs=1e-6)
        assert premium_on(full, result, basis) == pytest.approx(0.7, abs=1e-6)


# --- Consumers of a basis matrix with all-zero rows -----------------------------


@pytest.mark.parametrize("basis", [Basis.EVENT_CONDITIONAL, *BASES])
def test_engine_and_evaluation_accept_rows_that_pay_nothing(basis: Basis) -> None:
    """Build, solve, KPIs, exceedance curves and bootstrap with ``"zero"``.

    Location ``L1`` is below the attachment on every row, so its basis matrix
    is all zeros and it pays nothing for any ``theta``.
    """
    layout = Layout(
        n_years=4,
        years=[0, 1, 3],
        n_draws=1,
        index=np.array([[30.0, 5.0], [60.0, 10.0], [5.0, 15.0]]),
        loss=np.array([[4.0, 1.0], [10.0, 2.0], [1.0, 0.0]]),
        quiet=np.zeros(3, dtype=bool),
        by_filter=False,
    )
    eventset = make_eventset(layout)
    payout = two_bins("zero")
    assert not payout.basis_matrix(eventset.index[:, 1]).any()
    for scope in (Individual(), Portfolio()):
        results = list(
            design(
                eventset, basis, scope, payout, WeightedCVaR(0.5, 0.5), [Budget(1.0)]
            ).values()
        )
        assert all(r.status is SolveStatus.OPTIMAL for r in results)
        table = kpis(
            eventset,
            scope,
            results,
            basis=basis,
            beta=0.5,
            run_id="zero",
            pricing=PurePremium(),
        )
        assert kpi_values(table, "entity", "expected_payout", "L1") == [0.0]
        curves = exceedance_curves(eventset, scope, results, basis=basis, run_id="zero")
        assert not curves.empty
        boot = bootstrap_kpis(
            eventset,
            scope,
            results,
            basis=basis,
            beta=0.5,
            run_id="zero",
            resample=resample_years(np.arange(4), 20, np.random.default_rng(170)),
            pricing=PurePremium(),
        )
        assert bool(boot.table["ci_low"].notna().to_numpy().any())


def review_config(
    eventset_path: Path, output: Path, *, below_attachment: str | None, threshold: bool
) -> dict[str, Any]:
    """A config of the review's EventSet, MSE on the individual scope."""
    payout: dict[str, Any] = {"attachment": 20.0, "limit": 70.0, "n_bins": 2}
    if below_attachment is not None:
        payout["below_attachment"] = below_attachment
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "review",
        "eventset": {"path": str(eventset_path)},
        "basis": "annual",
        "payout": payout,
        "scopes": [{"kind": "individual"}],
        "objectives": [{"kind": "mse"}],
        "constraints": [{"kind": "budget", "loading": 5.0}],
        "evaluation": {"beta": 0.9},
        "output": {"directory": str(output)},
    }
    if threshold:
        data["threshold"] = {"value": 20.0}
    return data


@pytest.mark.parametrize(
    ("below_attachment", "theta_full", "theta_filtered"),
    [
        pytest.param(None, [2.0, 10.0], [4.0, 10.0], id="default-first-bin"),
        pytest.param("zero", [4.0, 10.0], [4.0, 10.0], id="zero"),
    ],
)
def test_config_runs_with_and_without_the_filter(
    tmp_path: Path,
    below_attachment: str | None,
    theta_full: list[float],
    theta_filtered: list[float],
) -> None:
    """Through the experiment config and the runner: the stored levels."""
    path = tmp_path / "eventset"
    review_eventset().to_parquet(path)
    store = ResultStore(tmp_path / "store")
    levels = {}
    for threshold in (False, True):
        config = parse_config(
            review_config(
                path,
                tmp_path / "out",
                below_attachment=below_attachment,
                threshold=threshold,
            )
        )
        assert config.payout.build().below_attachment == (
            below_attachment or "first_bin"
        )
        (outcome,) = run_config(config, store=store)
        assert outcome.ok
        payouts = store.read("payouts", run_ids=[outcome.run_id])
        levels[threshold] = payouts.sort_values("param_index")["value"].to_numpy()
    np.testing.assert_allclose(levels[False], theta_full, atol=1e-5)
    np.testing.assert_allclose(levels[True], theta_filtered, atol=1e-5)
