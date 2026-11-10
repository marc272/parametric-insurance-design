"""Portfolio premium of ``evaluate.kpis`` under a loaded pricing (MAR-27).

The portfolio ``premium`` KPI is the pricing applied to the aggregate payout
of the run (one owner buys the whole cover), not the sum of the problem
premiums. For the pure premium the two agree; a cost-of-capital load is
sub-additive, so on payouts whose tails fall in different events the
portfolio premium is strictly less than the sum.

Data: the toy EventSet of ``conftest.py`` with location B's index reversed,
so A pays most in ``ev3`` and B in ``ev1``. Expected values are recomputed
here from ``StepPayout.evaluate`` and ``var_cvar``.
"""

from __future__ import annotations

import dataclasses

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.evaluate import kpis, var_cvar
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Entity,
    Pricing,
    ProblemSpec,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.records import KpiLevel, KpiName
from parametric_insurance_design.scopes import Individual, Portfolio

PAYOUT = StepPayout(attachment=20.0, limit=60.0, n_bins=2)
THETA = {"A": [1.0, 8.0], "B": [1.0, 5.0]}
P = np.full(3, 1 / 3)


@pytest.fixture
def crossed_eventset(toy_eventset: EventSet) -> EventSet:
    """The toy EventSet with location B's index reversed (55, 35, 15)."""
    index = toy_eventset.index.copy()
    index[:, 1] = index[::-1, 1]
    return dataclasses.replace(toy_eventset, index=index)


def _result(spec: ProblemSpec, theta: list[list[float]]) -> SolveResult:
    return SolveResult(
        spec=spec,
        payout_structure=PAYOUT,
        theta=np.asarray(theta, dtype=np.float64),
        status=SolveStatus.OPTIMAL,
        objective_value=0.0,
        premium=0.0,
        scale=1.0,
        solver="test",
        attempts=(),
        build_seconds=0.0,
        solve_seconds=0.0,
    )


def individual_results() -> tuple[SolveResult, ...]:
    return tuple(
        _result(ProblemSpec(loc, (Entity(loc, (loc,)),)), [THETA[loc]])
        for loc in ("A", "B")
    )


def portfolio_results() -> tuple[SolveResult, ...]:
    spec = ProblemSpec("portfolio", (Entity("A", ("A",)), Entity("B", ("B",))))
    return (_result(spec, [THETA["A"], THETA["B"]]),)


def location_payouts(eventset: EventSet) -> dict[str, NDArray[np.float64]]:
    """Per-event payout of each location under ``THETA``, in numpy."""
    theta = np.array([THETA["A"], THETA["B"]])
    payout = PAYOUT.evaluate(eventset.index, theta)
    return {"A": payout[:, 0], "B": payout[:, 1]}


def loaded(payout: NDArray[np.float64], rate: float, q: float) -> float:
    _, cvar = var_cvar(payout, P, q)
    return (1 - rate) * float(P @ payout) + rate * cvar


def premium_kpi(table: pd.DataFrame, level: KpiLevel, subject_id: str) -> float:
    rows = table.loc[
        (table["kpi"] == KpiName.PREMIUM)
        & (table["level"] == level)
        & (table["subject_id"] == subject_id)
    ]
    assert len(rows) == 1
    return float(rows["value"].to_numpy()[0])


def run_kpis(
    eventset: EventSet,
    pricing: Pricing,
    *,
    individual: bool = True,
    basis: Basis = Basis.EVENT_CONDITIONAL,
) -> pd.DataFrame:
    return kpis(
        eventset,
        Individual() if individual else Portfolio(),
        individual_results() if individual else portfolio_results(),
        basis=basis,
        beta=0.5,
        run_id="r",
        pricing=pricing,
    )


# The toy EventSet has one event in each of its 3 years, all rates 1/3, so the
# three bases give the same outcomes, each with probability 1/3 (``P``): on
# ``annual`` an outcome is a year, on ``event`` the "no event" mass is 0.
@pytest.mark.parametrize("basis", [Basis.EVENT_CONDITIONAL, Basis.ANNUAL, Basis.EVENT])
@pytest.mark.parametrize(("rate", "q"), [(0.1, 0.5), (0.5, 0.6), (1.0, 0.5)])
def test_portfolio_premium_is_the_load_on_the_aggregate_payout(
    crossed_eventset: EventSet, rate: float, q: float, basis: Basis
) -> None:
    pay = location_payouts(crossed_eventset)
    # The tails do not coincide: A pays most in ev3, B in ev1.
    assert int(np.argmax(pay["A"])) != int(np.argmax(pay["B"]))
    table = run_kpis(crossed_eventset, CostOfCapitalLoad(rate=rate, q=q), basis=basis)
    problem_a = premium_kpi(table, KpiLevel.PROBLEM, "A")
    problem_b = premium_kpi(table, KpiLevel.PROBLEM, "B")
    portfolio = premium_kpi(table, KpiLevel.PORTFOLIO, "portfolio")
    assert problem_a == pytest.approx(loaded(pay["A"], rate, q), rel=1e-12)
    assert problem_b == pytest.approx(loaded(pay["B"], rate, q), rel=1e-12)
    assert portfolio == pytest.approx(loaded(pay["A"] + pay["B"], rate, q), rel=1e-12)
    # Sub-additive, and strictly so here: the separately priced covers cost
    # more than the aggregate cover.
    assert portfolio < problem_a + problem_b - 1e-9


def test_portfolio_premium_of_the_pure_premium_is_the_sum(
    crossed_eventset: EventSet,
) -> None:
    table = run_kpis(crossed_eventset, PurePremium())
    total = premium_kpi(table, KpiLevel.PROBLEM, "A") + premium_kpi(
        table, KpiLevel.PROBLEM, "B"
    )
    assert premium_kpi(table, KpiLevel.PORTFOLIO, "portfolio") == pytest.approx(
        total, rel=1e-14
    )


def test_one_problem_run_prices_the_portfolio_like_the_problem(
    crossed_eventset: EventSet,
) -> None:
    table = run_kpis(
        crossed_eventset, CostOfCapitalLoad(rate=0.1, q=0.5), individual=False
    )
    assert premium_kpi(table, KpiLevel.PORTFOLIO, "portfolio") == pytest.approx(
        premium_kpi(table, KpiLevel.PROBLEM, "portfolio"), rel=1e-14
    )


def test_rate_zero_gives_the_pure_premium_kpis(crossed_eventset: EventSet) -> None:
    pure = run_kpis(crossed_eventset, PurePremium())
    zero = run_kpis(crossed_eventset, CostOfCapitalLoad(rate=0.0, q=0.99))
    for level, subject in (
        (KpiLevel.PROBLEM, "A"),
        (KpiLevel.PROBLEM, "B"),
        (KpiLevel.PORTFOLIO, "portfolio"),
    ):
        assert premium_kpi(zero, level, subject) == premium_kpi(pure, level, subject)
