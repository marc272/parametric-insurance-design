"""Tests for ``evaluate``: KPIs and exceedance curves (MAR-16).

Thesis parity on the Miami fixture is in ``parity/tests/test_evaluate_parity.py``.
The last test here runs its golden-table check, so that CI runs it while
``parity/tests`` is not yet in CI (MAR-86).

The annual measure is MAR-24's. The annual tests stand in for it with a
grouped :class:`OutcomeMeasure` (one outcome per sample year, years without
rows included), patched into ``evaluate.outcome_measure``. Every EventSet
built here keeps ``year`` in ``[0, n_years)`` (ADR 0002 §5).
"""

from __future__ import annotations

import dataclasses
import importlib.util
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from numpy.typing import ArrayLike

from parametric_insurance_design import evaluate, records
from parametric_insurance_design.basis import Basis, OutcomeMeasure
from parametric_insurance_design.errors import (
    ComponentConfigError,
    EntityMismatchError,
    InputMismatchError,
    RecordSchemaError,
)
from parametric_insurance_design.evaluate import exceedance_curves, kpis, var_cvar
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Entity,
    ProblemSpec,
    Sample,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.records import ALL_PROBLEMS, KpiLevel, KpiName
from parametric_insurance_design.scopes import Individual, Portfolio

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_TEST = REPO_ROOT / "parity" / "tests" / "test_evaluate_parity.py"
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"

PAYOUT = StepPayout(attachment=20.0, limit=60.0, n_bins=2)  # bins [20,40), [40,60]
THETA = {"A": [1.0, 8.0], "B": [1.0, 5.0]}


def _result(spec: ProblemSpec, theta: ArrayLike) -> SolveResult:
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


def portfolio_results() -> tuple[SolveResult, ...]:
    spec = ProblemSpec("portfolio", (Entity("A", ("A",)), Entity("B", ("B",))))
    return (_result(spec, [THETA["A"], THETA["B"]]),)


def individual_results() -> tuple[SolveResult, ...]:
    return tuple(
        _result(ProblemSpec(loc, (Entity(loc, (loc,)),)), [THETA[loc]])
        for loc in ("A", "B")
    )


def value(table: pd.DataFrame, level: str, subject: str, kpi: KpiName) -> float:
    row = table.loc[
        (table["level"] == level)
        & (table["subject_id"] == subject)
        & (table["kpi"] == kpi.value)
    ]
    assert len(row) == 1
    return float(row["value"].to_numpy()[0])


def col(table: pd.DataFrame, name: str) -> np.ndarray:
    return np.asarray(table[name])


def weighted_corr(x: np.ndarray, y: np.ndarray) -> float:
    return float(np.corrcoef(x, y)[0, 1])


# --------------------------------------------------------------------------
# var_cvar
# --------------------------------------------------------------------------


def test_var_cvar_splits_the_atom_at_the_var() -> None:
    # Sorted 0, 2, 3 with p 1/3 each; beta 0.5: VaR 2, tail {3} has 1/3, so
    # CVaR = (1/3 * 3 + (0.5 - 1/3) * 2) / 0.5 = 8/3.
    var, cvar = var_cvar([3.0, 0.0, 2.0], np.full(3, 1 / 3), 0.5)
    assert var == 2.0
    assert cvar == pytest.approx(8 / 3, rel=1e-15)


def test_var_cvar_without_mass_above_the_var() -> None:
    assert var_cvar([1.0, 5.0], [0.5, 0.5], 0.9) == (5.0, 5.0)


def test_var_cvar_doc_example() -> None:
    assert var_cvar([0.0, 1.0, 2.0, 10.0], np.full(4, 0.25), 0.5) == (1.0, 6.0)


@pytest.mark.parametrize("seed", range(20))
@pytest.mark.parametrize("beta", [0.1, 0.5, 0.9, 0.95, 0.99])
def test_var_cvar_is_the_rockafellar_uryasev_minimum(seed: int, beta: float) -> None:
    rng = np.random.default_rng(seed)
    n = int(rng.integers(1, 40))
    x = np.round(rng.exponential(size=n), 1)  # ties included
    p = rng.random(n)
    p /= p.sum()
    var, cvar = var_cvar(x, p, beta)
    # The RU function is piecewise linear in zeta with kinks at the values,
    # so its minimum is attained at one of them, and the lower quantile is a
    # minimiser.
    ru = [z + float(p @ np.maximum(x - z, 0.0)) / (1 - beta) for z in x]
    assert cvar == pytest.approx(min(ru), rel=1e-12, abs=1e-12)
    order = np.argsort(x)
    cdf = np.cumsum(p[order])
    assert var == x[order][min(np.searchsorted(cdf, beta), n - 1)]
    assert np.sum(p[x < var]) < beta <= np.sum(p[x <= var]) + 1e-12
    assert cvar >= var


@pytest.mark.parametrize("beta", [0.0, 1.0, -0.5, math.nan, True, "0.9"])
def test_var_cvar_rejects_bad_beta(beta: object) -> None:
    with pytest.raises(ComponentConfigError, match="beta"):
        var_cvar([1.0], [1.0], beta)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("values", "probability", "match"),
    [
        ([], [], "non-empty"),
        ([[1.0]], [[1.0]], "non-empty 1-D"),
        ([1.0, 2.0], [1.0], "shape"),
        ([1.0, math.inf], [0.5, 0.5], "values must be finite"),
        ([1.0, 2.0], [1.5, -0.5], ">= 0"),
        ([1.0, 2.0], [0.5, math.nan], ">= 0"),
        ([1.0, 2.0], [0.5, 0.4], "sum to 1"),
    ],
)
def test_var_cvar_rejects_bad_distributions(
    values: list[float], probability: list[float], match: str
) -> None:
    with pytest.raises(InputMismatchError, match=match):
        var_cvar(values, probability, 0.5)


# --------------------------------------------------------------------------
# kpis, event-conditional basis
# --------------------------------------------------------------------------


def test_kpis_by_hand_on_the_toy(toy_eventset: EventSet) -> None:
    # Toy rows (p = 1/3 each). Entity A: index 10, 30, 50 -> bins 0, 0, 1,
    # payout 1, 1, 8 against loss 0, 4, 10; uncovered 0, 3, 2.
    table = kpis(
        toy_eventset,
        Portfolio(),
        portfolio_results(),
        basis=Basis.EVENT_CONDITIONAL,
        beta=0.5,
        run_id="r1",
    )
    entity = "entity"
    assert value(table, entity, "A", KpiName.EXPECTED_LOSS) == pytest.approx(14 / 3)
    assert value(table, entity, "A", KpiName.EXPECTED_PAYOUT) == pytest.approx(10 / 3)
    assert value(table, entity, "A", KpiName.EXPECTED_UNCOVERED) == pytest.approx(5 / 3)
    assert value(table, entity, "A", KpiName.VAR_UNCOVERED) == 2.0
    assert value(table, entity, "A", KpiName.CVAR_UNCOVERED) == pytest.approx(8 / 3)
    assert value(table, entity, "A", KpiName.RMSE_RESIDUAL) == pytest.approx(
        math.sqrt(14 / 3)
    )
    assert value(table, entity, "A", KpiName.PAYOUT_TO_LOSS_RATIO) == pytest.approx(
        5 / 7
    )
    assert value(table, entity, "A", KpiName.CORRELATION) == pytest.approx(
        weighted_corr(np.array([0.0, 4.0, 10.0]), np.array([1.0, 1.0, 8.0]))
    )
    # Portfolio: loss 1, 6, 16 against payout 2, 2, 13; uncovered 0, 4, 3.
    for level in ("problem", "portfolio"):
        assert value(table, level, "portfolio", KpiName.EXPECTED_UNCOVERED) == (
            pytest.approx(7 / 3)
        )
        assert value(table, level, "portfolio", KpiName.VAR_UNCOVERED) == 3.0
        assert value(table, level, "portfolio", KpiName.CVAR_UNCOVERED) == (
            pytest.approx((4 / 3 + (0.5 - 1 / 3) * 3) / 0.5)
        )
        assert value(table, level, "portfolio", KpiName.RMSE_RESIDUAL) == (
            pytest.approx(math.sqrt((1 + 16 + 9) / 3))
        )
        assert value(table, level, "portfolio", KpiName.PAYOUT_TO_LOSS_RATIO) == (
            pytest.approx(17 / 23)
        )


def test_kpis_table_layout(toy_eventset: EventSet) -> None:
    table = kpis(
        toy_eventset,
        Portfolio(),
        portfolio_results(),
        basis=Basis.EVENT_CONDITIONAL,
        beta=0.9,
        run_id="r1",
    )
    assert list(table.columns) == list(records.KPIS.column_names)
    records.KPIS.validate(table)
    # 2 entities + 1 problem + 1 portfolio, 8 KPIs each (no pricing).
    assert len(table) == 4 * 8
    assert set(table["kpi"]) == set(KpiName) - {KpiName.PREMIUM}
    assert np.all(col(table, "run_id") == "r1")
    assert np.all(col(table, "problem_id") == "portfolio")
    assert np.all(col(table, "eval_split") == "full")
    assert np.all(col(table, "fold") == 0)
    assert np.all(col(table, "basis") == "event_conditional")
    with_beta = table["kpi"].isin(["var_uncovered", "cvar_uncovered"])
    assert np.all(col(table.loc[with_beta], "beta") == 0.9)
    assert np.all(pd.isna(col(table.loc[~with_beta], "beta")))
    for column in ("ci_low", "ci_high", "ci_level", "n_bootstrap"):
        assert np.all(pd.isna(col(table, column)))
    levels = table.drop_duplicates(["level", "subject_id"])
    assert sorted(zip(levels["level"], levels["subject_id"], strict=True)) == [
        ("entity", "A"),
        ("entity", "B"),
        ("portfolio", "portfolio"),
        ("problem", "portfolio"),
    ]


def test_individual_scope_portfolio_rows_span_all_problems(
    toy_eventset: EventSet,
) -> None:
    joint = kpis(
        toy_eventset,
        Portfolio(),
        portfolio_results(),
        basis=Basis.EVENT_CONDITIONAL,
        beta=0.5,
        run_id="joint",
    )
    single = kpis(
        toy_eventset,
        Individual(),
        individual_results(),
        basis=Basis.EVENT_CONDITIONAL,
        beta=0.5,
        run_id="single",
        pricing=PurePremium(),
    )
    portfolio = single.loc[single["level"] == KpiLevel.PORTFOLIO]
    assert np.all(col(portfolio, "problem_id") == ALL_PROBLEMS)
    problems = single[single["level"] == KpiLevel.PROBLEM]
    assert set(problems["problem_id"]) == {"A", "B"}
    # Same payouts, so the same entity and portfolio values as the joint run.
    for level, subject in (
        ("entity", "A"),
        ("entity", "B"),
        ("portfolio", "portfolio"),
    ):
        for kpi in set(KpiName) - {KpiName.PREMIUM}:
            assert value(single, level, subject, kpi) == pytest.approx(
                value(joint, level, subject, kpi), rel=1e-15
            )
    # Premium per problem, summed for the portfolio; none per entity.
    premium = single[single["kpi"] == KpiName.PREMIUM]
    assert set(premium["level"]) == {"problem", "portfolio"}
    assert value(single, "problem", "A", KpiName.PREMIUM) == pytest.approx(10 / 3)
    assert value(single, "problem", "B", KpiName.PREMIUM) == pytest.approx(7 / 3)
    assert value(single, "portfolio", "portfolio", KpiName.PREMIUM) == (
        pytest.approx(17 / 3)
    )


def test_undefined_kpis_are_null(toy_eventset: EventSet) -> None:
    # A zero payout has no variance (correlation null); location A has zero
    # loss on the only test row (payout-to-loss ratio null).
    sample = Sample(
        "test", rows=np.array([True, False, False]), years=np.array([0]), fold=2
    )
    spec = ProblemSpec("portfolio", (Entity("A", ("A",)), Entity("B", ("B",))))
    table = kpis(
        toy_eventset,
        Portfolio(),
        (_result(spec, np.zeros((2, 2))),),
        basis=Basis.EVENT_CONDITIONAL,
        beta=0.5,
        run_id="r",
        sample=sample,
    )
    assert math.isnan(value(table, "entity", "A", KpiName.CORRELATION))
    assert math.isnan(value(table, "entity", "A", KpiName.PAYOUT_TO_LOSS_RATIO))
    assert value(table, "entity", "B", KpiName.PAYOUT_TO_LOSS_RATIO) == 0.0
    assert np.all(col(table, "eval_split") == "test")
    assert np.all(col(table, "fold") == 2)


def test_out_of_sample_uses_only_the_sample_rows(toy_eventset: EventSet) -> None:
    sample = Sample("test", rows=np.array([False, True, True]), years=np.array([1, 2]))
    table = kpis(
        toy_eventset,
        Portfolio(),
        portfolio_results(),
        basis=Basis.EVENT_CONDITIONAL,
        beta=0.5,
        run_id="r",
        sample=sample,
    )
    # Entity A on rows 2 and 3 (p 1/2 each): uncovered 3 and 2.
    assert value(table, "entity", "A", KpiName.EXPECTED_UNCOVERED) == 2.5
    assert value(table, "entity", "A", KpiName.VAR_UNCOVERED) == 2.0
    assert value(table, "entity", "A", KpiName.CVAR_UNCOVERED) == 3.0


# --------------------------------------------------------------------------
# kpis: errors instead of dropped entities (thesis C3)
# --------------------------------------------------------------------------


def _kpis(eventset: EventSet, scope: object, results: object, **kw: object) -> None:
    args: dict[str, object] = {
        "basis": Basis.EVENT_CONDITIONAL,
        "beta": 0.5,
        "run_id": "r",
    }
    args.update(kw)
    kpis(eventset, scope, results, **args)  # type: ignore[arg-type]


def test_missing_result_raises(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError, match=r"no result covers \['B'\]"):
        _kpis(toy_eventset, Individual(), individual_results()[:1])


def test_no_results_raise(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError, match="no results"):
        _kpis(toy_eventset, Individual(), ())


def test_repeated_problem_raises(toy_eventset: EventSet) -> None:
    a = individual_results()[0]
    with pytest.raises(EntityMismatchError, match="repeat"):
        _kpis(toy_eventset, Individual(), (a, a))


def test_overlapping_problems_raise(toy_eventset: EventSet) -> None:
    a, b = individual_results()
    other = _result(ProblemSpec("A2", (Entity("A2", ("A",)),)), [THETA["A"]])
    with pytest.raises(EntityMismatchError, match="location 'A'"):
        _kpis(toy_eventset, Individual(), (a, b, other))


def test_unknown_location_raises(toy_eventset: EventSet) -> None:
    extra = _result(ProblemSpec("C", (Entity("C", ("C",)),)), [THETA["A"]])
    with pytest.raises(EntityMismatchError, match=r"not in the EventSet \['C'\]"):
        _kpis(toy_eventset, Individual(), (*individual_results(), extra))


def test_spec_the_scope_cannot_materialise_raises(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError):
        _kpis(toy_eventset, Individual(), portfolio_results())


def test_non_result_raises(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError, match="SolveResult"):
        _kpis(toy_eventset, Individual(), ("A",))


@pytest.mark.parametrize(
    ("kwargs", "error", "match"),
    [
        ({"beta": 1.0}, ComponentConfigError, "beta"),
        ({"run_id": ""}, InputMismatchError, "run_id"),
        ({"pricing": "pure"}, ComponentConfigError, "pricing"),
        (
            {"sample": Sample("holdout", np.ones(3, dtype=bool), np.arange(3))},
            RecordSchemaError,
            "eval_split",
        ),
        (
            {"sample": Sample("test", np.ones(2, dtype=bool), np.arange(3))},
            InputMismatchError,
            "rows",
        ),
    ],
)
def test_bad_arguments_raise(
    toy_eventset: EventSet,
    kwargs: dict[str, object],
    error: type[Exception],
    match: str,
) -> None:
    with pytest.raises(error, match=match):
        _kpis(toy_eventset, Portfolio(), portfolio_results(), **kwargs)


def test_measure_of_the_wrong_rows_raises(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    def short_measure(
        eventset: EventSet, basis: Basis, *, years: ArrayLike | None = None
    ) -> OutcomeMeasure:
        return OutcomeMeasure.per_row(basis, [0.5, 0.5])

    monkeypatch.setattr(evaluate, "outcome_measure", short_measure)
    with pytest.raises(InputMismatchError, match="measure covers 2 rows"):
        _kpis(toy_eventset, Portfolio(), portfolio_results())


def test_bad_scope_raises(toy_eventset: EventSet) -> None:
    with pytest.raises(ComponentConfigError, match="scope"):
        _kpis(toy_eventset, "portfolio", portfolio_results())


# --------------------------------------------------------------------------
# Annual basis (grouped measure standing in for MAR-24)
# --------------------------------------------------------------------------


def annual_eventset(toy: EventSet) -> EventSet:
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
    events = pd.DataFrame(
        {
            "event_id": ["e0", "e1", "e2", "e3"],
            "year": [0, 0, 1, 0],
            "rate": [0.2] * 4,
            "draw_id": [0] * 4,
            "scenario_id": ["toy"] * 4,
        }
    )
    return EventSet(
        events=events,
        locations=toy.locations,
        index=np.array([[30.0, 35.0], [50.0, 55.0], [50.0, 15.0], [10.0, 55.0]]),
        loss=np.array([[4.0, 2.0], [10.0, 6.0], [6.0, 1.0], [0.0, 3.0]]),
        metadata=dataclasses.replace(toy.metadata, n_years=5),
    )


def grouped_measure(
    eventset: EventSet, basis: Basis, *, years: ArrayLike | None = None
) -> OutcomeMeasure:
    """One outcome per year of the sample, probability 1/n_years each."""
    assert basis is Basis.ANNUAL
    assert years is not None
    y = np.asarray(years)
    row_years = eventset.events["year"].to_numpy()
    return OutcomeMeasure(
        basis=basis,
        outcome_of_row=np.searchsorted(y, row_years),
        probability=np.full(y.size, 1.0 / y.size),
    )


@pytest.fixture
def annual(toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch) -> EventSet:
    monkeypatch.setattr(evaluate, "outcome_measure", grouped_measure)
    return annual_eventset(toy_eventset)


def test_annual_kpis_are_over_years(annual: EventSet) -> None:
    # Entity A: payout 1, 8, 8, 1; per-row uncovered 3, 2, 0, 0, so
    # U_y = 5, 0, 0, 0, 0 (row 3 over-pays and does not offset row 0).
    # Residual per year 4, -2, 0, 0, 0. Loss per year 14, 6; payout 10, 8.
    table = kpis(
        annual,
        Portfolio(),
        portfolio_results(),
        basis=Basis.ANNUAL,
        beta=0.5,
        run_id="r",
    )
    assert np.all(col(table, "basis") == "annual")
    assert value(table, "entity", "A", KpiName.EXPECTED_UNCOVERED) == 1.0
    assert value(table, "entity", "A", KpiName.VAR_UNCOVERED) == 0.0
    assert value(table, "entity", "A", KpiName.CVAR_UNCOVERED) == pytest.approx(2.0)
    assert value(table, "entity", "A", KpiName.RMSE_RESIDUAL) == pytest.approx(2.0)
    assert value(table, "entity", "A", KpiName.EXPECTED_LOSS) == pytest.approx(4.0)
    assert value(table, "entity", "A", KpiName.EXPECTED_PAYOUT) == pytest.approx(3.6)
    assert value(table, "entity", "A", KpiName.PAYOUT_TO_LOSS_RATIO) == (
        pytest.approx(0.9)
    )
    assert value(table, "entity", "A", KpiName.CORRELATION) == pytest.approx(
        weighted_corr(np.array([14.0, 6, 0, 0, 0]), np.array([10.0, 8, 0, 0, 0]))
    )


def test_annual_kpis_on_a_test_sample_keep_its_empty_years(annual: EventSet) -> None:
    # Test years 1..4: one row (year 1), three empty years.
    rows = annual.events["year"].to_numpy() == 1
    sample = Sample("test", rows=rows, years=np.array([1, 2, 3, 4]))
    table = kpis(
        annual,
        Portfolio(),
        portfolio_results(),
        basis=Basis.ANNUAL,
        beta=0.5,
        run_id="r",
        sample=sample,
    )
    # Entity B in year 1: payout 1 (index 15), loss 1 -> E[L] = 1/4.
    assert value(table, "entity", "B", KpiName.EXPECTED_LOSS) == 0.25


def test_annual_exceedance_oep_and_aep(annual: EventSet) -> None:
    table = exceedance_curves(
        annual,
        Portfolio(),
        portfolio_results(),
        basis=Basis.ANNUAL,
        run_id="r",
        return_periods=[2.0, 10.0],
    )
    records.EXCEEDANCE.validate(table)
    assert set(table["curve"]) == {"oep", "aep"}

    def at(curve: str, quantity: str, period: float, subject: str = "A") -> float:
        row = table.loc[
            (table["level"] == "entity")
            & (table["subject_id"] == subject)
            & (table["curve"] == curve)
            & (table["quantity"] == quantity)
            & (table["return_period"] == period)
        ]
        assert len(row) == 1
        return float(row["value"].to_numpy()[0])

    # Entity A uncovered: year 0 has events 3, 2, 0 -> OEP 3, AEP 5.
    assert at("oep", "uncovered", 10.0) == 3.0
    assert at("aep", "uncovered", 10.0) == 5.0
    assert at("oep", "uncovered", 2.0) == 0.0  # 3 of 5 years have nothing
    # Loss: year 0 max 10, sum 14.
    assert at("oep", "loss", 10.0) == 10.0
    assert at("aep", "loss", 10.0) == 14.0
    # Payout: year 0 max 8, sum 10.
    assert at("oep", "payout", 10.0) == 8.0
    assert at("aep", "payout", 10.0) == 10.0
    # 2 entities + problem + portfolio, 3 quantities, 2 curves, 2 periods.
    assert len(table) == 4 * 3 * 2 * 2


# --------------------------------------------------------------------------
# Exceedance curves, event basis
# --------------------------------------------------------------------------


def test_event_exceedance_is_the_lower_quantile(toy_eventset: EventSet) -> None:
    periods = [1.2, 2.0, 2.5, 100.0]
    table = exceedance_curves(
        toy_eventset,
        Individual(),
        individual_results(),
        basis=Basis.EVENT_CONDITIONAL,
        run_id="r",
        return_periods=periods,
    )
    assert list(table.columns) == list(records.EXCEEDANCE.column_names)
    assert set(table["curve"]) == {"event"}
    uncovered = table.loc[
        (table["level"] == "portfolio") & (table["quantity"] == "uncovered")
    ]
    assert np.all(col(uncovered, "problem_id") == ALL_PROBLEMS)
    # Portfolio uncovered per event 0, 4, 3 (p = 1/3): the lower
    # (1 - 1/T)-quantile is 0 for T = 1.2, 3 for T = 2 and 2.5, 4 for T = 100.
    got = dict(zip(uncovered["return_period"], uncovered["value"], strict=True))
    assert got == {1.2: 0.0, 2.0: 3.0, 2.5: 3.0, 100.0: 4.0}
    # Equal to the VaR at beta = 1 - 1/T.
    for period, v in got.items():
        assert v == var_cvar([0.0, 4.0, 3.0], np.full(3, 1 / 3), 1 - 1 / period)[0]


def test_default_return_periods(toy_eventset: EventSet) -> None:
    table = exceedance_curves(
        toy_eventset,
        Portfolio(),
        portfolio_results(),
        basis=Basis.EVENT_CONDITIONAL,
        run_id="r",
    )
    assert sorted(set(table["return_period"])) == list(evaluate.DEFAULT_RETURN_PERIODS)


@pytest.mark.parametrize(
    "periods", [[], [1.0], [0.5, 2.0], [2.0, 2.0], [math.inf], [[2.0, 3.0]]]
)
def test_bad_return_periods_raise(toy_eventset: EventSet, periods: object) -> None:
    with pytest.raises(InputMismatchError, match=r"return.period"):
        exceedance_curves(
            toy_eventset,
            Portfolio(),
            portfolio_results(),
            basis=Basis.EVENT_CONDITIONAL,
            run_id="r",
            return_periods=periods,  # type: ignore[arg-type]
        )


def test_exceedance_missing_result_raises(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError):
        exceedance_curves(
            toy_eventset,
            Individual(),
            individual_results()[1:],
            basis=Basis.EVENT_CONDITIONAL,
            run_id="r",
        )


def test_exceedance_bad_run_id_raises(toy_eventset: EventSet) -> None:
    with pytest.raises(InputMismatchError, match="run_id"):
        exceedance_curves(
            toy_eventset,
            Portfolio(),
            portfolio_results(),
            basis=Basis.EVENT_CONDITIONAL,
            run_id="",
        )


# -- thesis KPI table on the parity fixture (MAR-16 acceptance, CI copy) ------


@pytest.mark.skipif(
    not (PARITY_TEST.is_file() and PARITY_EVENTSET.is_dir()),
    reason="the parity fixture is only in a repository checkout",
)
def test_parity_fixture_matches_thesis_kpis() -> None:
    spec = importlib.util.spec_from_file_location("mar16_evaluate_parity", PARITY_TEST)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    stats = module.check_golden(module.thesis_data())
    assert set(stats) == set(module.KPI_COLUMNS)
    assert all(s["n"] > 0 for s in stats.values())
