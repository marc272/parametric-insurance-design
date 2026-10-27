"""Tests of the ``event`` and ``annual`` bases (MAR-24, SPEC §6.2).

The measures are checked by hand on small EventSets, then through the whole
engine: ``build_problems`` and ``solve`` with the real components, and
``evaluate.kpis``. The engine properties (feasibility, scaling, alpha = 0) on
these bases are in ``test_engine_properties_bases.py``.
"""

from __future__ import annotations

import dataclasses

import cvxpy as cp
import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from parametric_insurance_design.basis import (
    Basis,
    OutcomeMeasure,
    outcome_measure,
)
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.evaluate import kpis, var_cvar
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import Objective, Sample
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.objectives import (
    MSE,
    ExpectedUncovered,
    WeightedCVaR,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.records import KpiName
from parametric_insurance_design.scopes import Individual, Portfolio
from parametric_insurance_design.solve import solve


def with_events(
    toy: EventSet,
    years: list[int],
    index: NDArray[np.float64],
    loss: NDArray[np.float64],
    *,
    n_years: int,
    rate: float | None = None,
) -> EventSet:
    """The toy's locations with new event rows (rate 1/n_years by default)."""
    n = len(years)
    events = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "year": years,
            "rate": [1.0 / n_years if rate is None else rate] * n,
            "draw_id": [0] * n,
            "scenario_id": ["toy"] * n,
        }
    )
    return EventSet(
        events=events,
        locations=toy.locations,
        index=np.asarray(index, dtype=np.float64),
        loss=np.asarray(loss, dtype=np.float64),
        metadata=dataclasses.replace(toy.metadata, n_years=n_years),
    )


def clustered(toy: EventSet) -> EventSet:
    """Four events in years 0, 0, 1, 0 of five (years 2-4 have no rows).

    ===  ====  =======  =======  ======  ======
    row  year  index A  index B  loss A  loss B
    ===  ====  =======  =======  ======  ======
    0    0     30       35       4       2
    1    0     50       55       10      6
    2    1     50       15       6       1
    3    0     10       55       0       3
    ===  ====  =======  =======  ======  ======
    """
    return with_events(
        toy,
        [0, 0, 1, 0],
        np.array([[30.0, 35.0], [50.0, 55.0], [50.0, 15.0], [10.0, 55.0]]),
        np.array([[4.0, 2.0], [10.0, 6.0], [6.0, 1.0], [0.0, 3.0]]),
        n_years=5,
    )


def one_per_year(toy: EventSet, n_years: int = 8, seed: int = 3) -> EventSet:
    """``n_years`` events, one per year, in shuffled row order."""
    rng = np.random.default_rng(seed)
    index = rng.uniform(0.0, 80.0, size=(n_years, 2))
    loss = np.round(np.clip(index - 20.0, 0.0, None) * [1.0, 0.5], 1)
    years = rng.permutation(n_years).tolist()
    return with_events(toy, years, index, loss, n_years=n_years)


# --------------------------------------------------------------------------
# The annual measure
# --------------------------------------------------------------------------


def test_annual_sums_rows_per_year_and_pools_empty_years(toy_eventset: EventSet) -> None:
    data = clustered(toy_eventset)
    measure = outcome_measure(data, Basis.ANNUAL)
    assert measure.basis is Basis.ANNUAL
    # Year 0, year 1, then the three empty years pooled into one outcome.
    np.testing.assert_array_equal(measure.outcome_of_row, [0, 0, 1, 0])
    np.testing.assert_allclose(measure.probability, [0.2, 0.2, 0.6])
    assert not measure.is_per_row
    # U_y = sum_{e in y} (L_e - pi_e)^+ for entity A with payout 1, 8, 8, 1.
    uncovered = np.maximum(data.loss[:, 0] - np.array([1.0, 8.0, 8.0, 1.0]), 0.0)
    np.testing.assert_allclose(measure.aggregate(uncovered), [5.0, 0.0, 0.0])
    # E[U] over years equals the rate-weighted sum over events.
    assert measure.expectation(uncovered) == pytest.approx(data.rates @ uncovered)


def test_annual_on_a_sample_counts_its_years_only(toy_eventset: EventSet) -> None:
    data = clustered(toy_eventset)
    rows = data.events["year"].to_numpy() == 1
    sample = Sample("test", rows=rows, years=np.array([1, 2, 3, 4]))
    measure = outcome_measure(sample.select(data), Basis.ANNUAL, years=sample.years)
    np.testing.assert_array_equal(measure.outcome_of_row, [0])
    np.testing.assert_allclose(measure.probability, [0.25, 0.75])


def test_annual_without_empty_years_has_no_pooled_outcome(
    toy_eventset: EventSet,
) -> None:
    measure = outcome_measure(toy_eventset, Basis.ANNUAL)
    assert measure.is_per_row
    np.testing.assert_allclose(measure.probability, [1 / 3] * 3)


def test_annual_outcomes_are_per_year_and_draw(toy_eventset: EventSet) -> None:
    # Two draws per event (rate 1/(3 * 2) each, SPEC §5), then year 0's rows
    # dropped: 4 occupied (year, draw) slots of 6, and one pooled empty slot.
    noisy = add_noise(
        toy_eventset,
        level=0.3,
        kind="homoscedastic",
        n_copies=2,
        rng=np.random.default_rng(0),
    )
    keep = noisy.events["year"].to_numpy() > 0
    data = Sample("x", rows=keep, years=np.arange(3)).select(noisy)
    measure = outcome_measure(data, Basis.ANNUAL)
    slots = list(
        zip(
            data.events["year"].to_numpy()[np.argsort(measure.outcome_of_row)],
            data.events["draw_id"].to_numpy()[np.argsort(measure.outcome_of_row)],
            strict=True,
        )
    )
    assert slots == [(1, 0), (1, 1), (2, 0), (2, 1)]
    np.testing.assert_allclose(measure.probability, [1 / 6] * 4 + [2 / 6])
    assert measure.expectation(data.loss[:, 0]) == pytest.approx(
        data.rates @ data.loss[:, 0]
    )


def test_annual_needs_the_draw_rate_convention(toy_eventset: EventSet) -> None:
    data = clustered(toy_eventset)
    unequal = data.events.assign(rate=[0.2, 0.2, 0.1, 0.2])
    with pytest.raises(InputMismatchError, match=r"1 / \(n_years \* n_draws\)"):
        outcome_measure(
            dataclasses.replace(data, events=unequal), Basis.ANNUAL
        )
    # Rates 1/Y but a draw_id of 1: the draws' rates were not divided.
    drawn = data.events.assign(draw_id=[0, 1, 0, 0])
    with pytest.raises(InputMismatchError, match=r"draw_id must lie in \[0, 1\)"):
        outcome_measure(dataclasses.replace(data, events=drawn), Basis.ANNUAL)


@pytest.mark.parametrize(
    ("years", "match"),
    [
        (np.array([], dtype=np.int64), "non-empty"),
        (np.array([[0, 1]]), "1-D"),
        (np.array([0.0, 1.0]), "integer"),
        (np.array([0, 0, 1]), "unique"),
        (np.array([0, 1, 5]), r"\[0, 5\)"),
        (np.array([-1, 0, 1]), r"\[0, 5\)"),
        (np.array([1, 2]), "outside the given years"),
    ],
)
@pytest.mark.parametrize("basis", [Basis.ANNUAL, Basis.EVENT])
def test_years_are_checked(
    toy_eventset: EventSet, basis: Basis, years: NDArray[np.int64], match: str
) -> None:
    with pytest.raises(InputMismatchError, match=match):
        outcome_measure(clustered(toy_eventset), basis, years=years)


# --------------------------------------------------------------------------
# The event measure
# --------------------------------------------------------------------------


def test_event_uses_unrescaled_rates_and_a_no_event_outcome(
    toy_eventset: EventSet,
) -> None:
    filtered = toy_eventset.filter_threshold(20.0)  # drops ev1
    measure = outcome_measure(filtered, Basis.EVENT)
    assert measure.basis is Basis.EVENT
    np.testing.assert_array_equal(measure.outcome_of_row, [0, 1])
    np.testing.assert_allclose(measure.probability, [1 / 3, 1 / 3, 1 / 3])
    # The dropped row's mass is zero-loss mass, not rescaled away.
    assert measure.expectation(filtered.loss[:, 0]) == pytest.approx(14 / 3)
    conditional = outcome_measure(filtered, Basis.EVENT_CONDITIONAL)
    assert conditional.expectation(filtered.loss[:, 0]) == pytest.approx(7.0)


def test_event_without_spare_mass_is_per_row(toy_eventset: EventSet) -> None:
    measure = outcome_measure(toy_eventset, Basis.EVENT)
    assert measure.is_per_row
    np.testing.assert_allclose(measure.probability, toy_eventset.rates)


def test_event_on_a_sample_expresses_rates_over_its_years(
    toy_eventset: EventSet,
) -> None:
    data = clustered(toy_eventset)
    rows = data.events["year"].to_numpy() == 1
    sample = Sample("test", rows=rows, years=np.array([1, 2, 3, 4]))
    measure = outcome_measure(sample.select(data), Basis.EVENT, years=sample.years)
    # One event in four years: probability 1/4, "no event" 3/4.
    np.testing.assert_allclose(measure.probability, [0.25, 0.75])


def test_event_needs_at_most_one_event_per_year(toy_eventset: EventSet) -> None:
    data = clustered(toy_eventset)
    with pytest.raises(InputMismatchError, match="at most 1"):
        outcome_measure(data, Basis.EVENT, years=np.array([0, 1]))


# --------------------------------------------------------------------------
# aggregate_expression on a grouped measure
# --------------------------------------------------------------------------


def test_grouped_aggregate_expression_matches_numpy(toy_eventset: EventSet) -> None:
    data = clustered(toy_eventset)
    for basis in (Basis.ANNUAL, Basis.EVENT):
        measure = outcome_measure(data, basis, years=np.arange(5))
        x = cp.Variable(data.n_rows)
        values = np.array([1.0, -2.0, 4.0, 8.0])
        out = measure.aggregate_expression(cp.pos(x))
        assert tuple(out.shape) == (measure.n_outcomes,)
        problem = cp.Problem(cp.Minimize(measure.probability @ out), [x == values])
        problem.solve(solver=cp.CLARABEL)
        assert out.value is not None
        np.testing.assert_allclose(
            out.value, measure.aggregate(np.maximum(values, 0.0)), atol=1e-9
        )
        with pytest.raises(InputMismatchError, match="shape"):
            measure.aggregate_expression(cp.Variable(3))


def test_aggregate_expression_on_a_per_row_measure_is_the_expression() -> None:
    measure = OutcomeMeasure.per_row(Basis.ANNUAL, [0.5, 0.5])
    x = cp.Variable(2)
    assert measure.aggregate_expression(x) is x


# --------------------------------------------------------------------------
# One event per year: the event and annual bases agree
# --------------------------------------------------------------------------


def test_one_event_per_year_gives_the_same_measure(toy_eventset: EventSet) -> None:
    data = one_per_year(toy_eventset)
    event = outcome_measure(data, Basis.EVENT)
    annual = outcome_measure(data, Basis.ANNUAL)
    assert event.n_outcomes == annual.n_outcomes == data.n_rows
    # The same probability per row; only the outcome order differs.
    np.testing.assert_allclose(
        event.probability[event.outcome_of_row],
        annual.probability[annual.outcome_of_row],
    )
    values = data.loss[:, 0] - 3.0
    np.testing.assert_allclose(
        event.aggregate(values)[event.outcome_of_row],
        annual.aggregate(values)[annual.outcome_of_row],
    )


OBJECTIVES: list[Objective] = [
    MSE(),
    ExpectedUncovered(),
    WeightedCVaR(alpha=0.9, beta=0.8),
    WeightedCVaR(alpha=1.0, beta=0.95),
]


@pytest.mark.parametrize("objective", OBJECTIVES, ids=lambda o: repr(o))
@pytest.mark.parametrize("scope", [Individual(), Portfolio()], ids=["ind", "port"])
@pytest.mark.parametrize("on_sample", [False, True], ids=["full", "sample"])
def test_one_event_per_year_designs_agree(
    toy_eventset: EventSet,
    objective: Objective,
    scope: Individual | Portfolio,
    on_sample: bool,
) -> None:
    data = one_per_year(toy_eventset, n_years=10)
    sample = None
    if on_sample:
        years = np.arange(7)
        sample = Sample(
            "train", rows=np.isin(data.events["year"].to_numpy(), years), years=years
        )
    payout = StepPayout(20.0, 70.0, 4)
    results = {}
    tables = {}
    for basis in (Basis.EVENT, Basis.ANNUAL):
        built = build_problems(
            data,
            scope,
            payout,
            objective,
            PurePremium(),
            (Budget(0.8),),
            basis=basis,
            sample=sample,
        )
        results[basis] = [solve(b) for b in built]
        tables[basis] = kpis(
            data,
            scope,
            results[basis],
            basis=basis,
            beta=0.8,
            run_id="r",
            sample=sample,
            pricing=PurePremium(),
        )
    for a, b in zip(results[Basis.EVENT], results[Basis.ANNUAL], strict=True):
        assert a.objective_value == pytest.approx(b.objective_value, rel=1e-6, abs=1e-6)
        assert a.premium == pytest.approx(b.premium, rel=1e-6, abs=1e-6)
    # KPIs of one solution are identical on both bases (same distribution).
    same = kpis(
        data,
        scope,
        results[Basis.EVENT],
        basis=Basis.ANNUAL,
        beta=0.8,
        run_id="r",
        sample=sample,
        pricing=PurePremium(),
    )
    left = tables[Basis.EVENT].drop(columns="basis")
    right = same.drop(columns="basis")
    pd.testing.assert_frame_equal(left, right, check_exact=False, rtol=1e-9, atol=1e-9)


# --------------------------------------------------------------------------
# CVaR over years, annual premium, and the MSE choice
# --------------------------------------------------------------------------


def hundred_years(toy: EventSet) -> EventSet:
    """30 events in 100 years, several per year; 75 years have none."""
    rng = np.random.default_rng(11)
    years = np.sort(rng.choice(25, size=30)).tolist()
    index = rng.uniform(15.0, 75.0, size=(30, 2))
    loss = np.round(np.clip(index - 20.0, 0.0, None) * rng.uniform(0.5, 1.5, (30, 2)))
    return with_events(toy, years, index, loss, n_years=100)


def test_weighted_cvar_is_taken_over_years(toy_eventset: EventSet) -> None:
    data = hundred_years(toy_eventset)
    beta = 0.99
    (built,) = build_problems(
        data,
        Portfolio(),
        StepPayout(20.0, 70.0, 5),
        WeightedCVaR(alpha=1.0, beta=beta),
        PurePremium(),
        (Budget(0.5),),
        basis=Basis.ANNUAL,
    )
    result = solve(built)
    payout = result.payout_structure.evaluate(data.index, result.theta).sum(axis=1)
    per_row = np.maximum(data.loss.sum(axis=1) - payout, 0.0)
    # U per year over all 100 years, by hand; zero for the empty years.
    annual = np.zeros(100)
    np.add.at(annual, data.events["year"].to_numpy(), per_row)
    _, cvar = var_cvar(annual, np.full(100, 0.01), beta)
    # beta = 0.99 over 100 years: the mean of the worst 1 % is the worst year.
    assert cvar == pytest.approx(annual.max())
    assert result.objective_value == pytest.approx(cvar, rel=1e-5, abs=1e-5)
    # Annual premium: E[annual payout] = sum_e rate_e * pi_e.
    assert result.premium == pytest.approx(data.rates @ payout, rel=1e-6)
    assert result.premium <= 0.5 * float(data.rates @ data.loss.sum(axis=1)) * (
        1 + 1e-6
    )


def test_mse_squares_the_summed_yearly_residual(toy_eventset: EventSet) -> None:
    """MAR-24 decision: (L_y - pi_y)^2, not sum_{e in y} (L_e - pi_e)^2."""
    data = clustered(toy_eventset)
    measure = outcome_measure(data, Basis.ANNUAL)
    loss = data.loss[:, 0]
    payout = np.array([1.0, 8.0, 8.0, 1.0])
    x = cp.Variable(4)
    term_expr = measure.probability @ cp.square(
        measure.aggregate_expression(loss - x)
    )
    problem = cp.Problem(cp.Minimize(term_expr), [x == payout])
    problem.solve(solver=cp.CLARABEL)
    # Residuals 3, 2, -2, -1: year 0 (rows 0, 1, 3) sums to 4, year 1 is -2,
    # so E[(L_y - pi_y)^2] = (16 + 4) / 5.
    assert problem.value == pytest.approx(4.0)
    per_event = float(data.rates @ (loss - payout) ** 2)
    assert per_event == pytest.approx((9 + 4 + 4 + 1) / 5)
    # The MSE objective builds the same expression.
    built = build_problems(
        data,
        Individual(),
        StepPayout(20.0, 70.0, 2),
        MSE(),
        PurePremium(),
        basis=Basis.ANNUAL,
    )
    result = solve(built[0])  # entity A
    fitted = result.payout_structure.evaluate(
        data.index[:, :1], result.theta
    ).sum(axis=1)
    residual = measure.aggregate(loss - fitted)
    assert result.objective_value == pytest.approx(
        float(measure.probability @ residual**2), rel=1e-5, abs=1e-6
    )
