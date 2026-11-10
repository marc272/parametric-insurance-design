"""Block-bootstrap confidence intervals over years (MAR-23, SPEC §6.1).

* Resampling: :func:`resample_years` and :class:`YearResample`.
* Exactness: every replicate equals the KPIs of the explicitly concatenated
  resampled years, on the ``event_conditional``, ``event`` and ``annual``
  bases (the annual basis pools empty year-draw slots into one outcome; the
  event basis has a "no event" outcome).
* Point estimates: ``bootstrap_kpis`` keeps ``evaluate.kpis``'s values.
* Paired differences, undefined replicates and error paths.
* Paired differences across scopes (MAR-179): portfolio-level rows only,
  reproducing MAR-158's ``problem_id`` relabelling on the parity fixture.
* Repeated pairing keys (MAR-211): a typed ``BootstrapError``, not pandas'
  ``MergeError``; separately calibrated cluster designs pair as any scope.
* Coverage on a synthetic case with a known answer.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from parametric_insurance_design.basis import Basis, OutcomeMeasure, outcome_measure
from parametric_insurance_design.bootstrap import (  # pyright: ignore[reportPrivateUsage]
    DEFAULT_LEVEL,
    DEFAULT_N_BOOTSTRAP,
    PAIR_KEY,
    PORTFOLIO_PAIR_KEY,
    BootstrapError,
    KpiBootstrap,
    YearResample,
    _is_quantile_step,
    _var_cvar_rows,
    bootstrap_kpis,
    kpi_replicates,
    paired_difference,
    percentile_interval,
    premium_replicates,
    resample_years,
)
from parametric_insurance_design.errors import ComponentConfigError, InputMismatchError
from parametric_insurance_design.evaluate import evaluate_results, kpis, var_cvar
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import load_config, parse_config
from parametric_insurance_design.experiment.runner import load_input, prepare_eventset
from parametric_insurance_design.interfaces import Sample, SolveResult
from parametric_insurance_design.objectives import MSE, WeightedCVaR
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.records import ALL_PROBLEMS, KPIS, KpiName
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio
from parametric_insurance_design.solve import solve
from parametric_insurance_design.splits import holdout

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"

needs_fixture = pytest.mark.skipif(
    not (PARITY_EVENTSET.is_dir() and PARITY_CONFIG.is_file()),
    reason="the parity fixture is only in a repository checkout",
)

BETA = 0.83
"""KPI level. Not a multiple of the toy probabilities (1/12, 1/36, 1/40, ...),
so no VaR falls exactly on a step of a distribution; see
``test_var_on_a_step_of_the_distribution`` for that case."""

# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def with_rows(
    toy: EventSet,
    years: Sequence[int],
    draws: Sequence[int],
    loss: NDArray[np.float64],
    *,
    n_years: int,
    n_draws: int = 1,
) -> EventSet:
    """The toy's two locations with new rows; rate ``1 / (n_years * n_draws)``.

    Rows with the same position in ``years`` share an ``event_id`` across
    draws only if they share year and row number, so every (event, draw)
    pair is unique.
    """
    n = len(years)
    events = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(n)],
            "year": list(years),
            "rate": [1.0 / (n_years * n_draws)] * n,
            "draw_id": list(draws),
            "scenario_id": ["toy"] * n,
        }
    )
    loss = np.asarray(loss, dtype=np.float64)
    return EventSet(
        events=events,
        locations=toy.locations,
        index=20.0 + 4.0 * loss,
        loss=loss,
        metadata=dataclasses.replace(toy.metadata, n_years=n_years),
    )


def random_rows(toy: EventSet, *, n_years: int, n_draws: int, seed: int) -> EventSet:
    """Several events per year, several draws, some years without rows."""
    rng = np.random.default_rng(seed)
    years: list[int] = []
    draws: list[int] = []
    for year in range(n_years):
        if year % 3 == 2:
            continue  # a year without rows
        for _ in range(int(rng.integers(1, 4))):
            for d in range(n_draws):
                if rng.random() < 0.8:  # some draws of the event are missing
                    years.append(year)
                    draws.append(d)
    loss = np.round(rng.gamma(1.5, 3.0, size=(len(years), 2)), 2)
    return with_rows(toy, years, draws, loss, n_years=n_years, n_draws=n_draws)


def reference_kpis(
    loss: NDArray[np.float64],
    payout: NDArray[np.float64],
    prob: NDArray[np.float64],
    beta: float,
) -> dict[KpiName, float]:
    """KPIs of explicit outcomes, with ``evaluate.var_cvar``."""
    p = prob / prob.sum()
    uncovered = np.maximum(loss - payout, 0.0)
    residual = loss - payout
    var, cvar = var_cvar(uncovered, p, beta)
    el = float(p @ loss)
    ep = float(p @ payout)
    dx = loss - el
    dy = payout - ep
    sx = math.sqrt(float(p @ dx**2))
    sy = math.sqrt(float(p @ dy**2))
    corr = math.nan if sx == 0 or sy == 0 else float(p @ (dx * dy)) / (sx * sy)
    return {
        KpiName.EXPECTED_LOSS: el,
        KpiName.EXPECTED_PAYOUT: ep,
        KpiName.EXPECTED_UNCOVERED: float(p @ uncovered),
        KpiName.VAR_UNCOVERED: var,
        KpiName.CVAR_UNCOVERED: cvar,
        KpiName.RMSE_RESIDUAL: math.sqrt(float(p @ residual**2)),
        KpiName.PAYOUT_TO_LOSS_RATIO: math.nan if el == 0 else ep / el,
        KpiName.CORRELATION: corr,
    }


def explicit_outcomes(
    data: EventSet,
    basis: Basis,
    years: NDArray[np.int64],
    drawn: NDArray[np.int32],
    loss: NDArray[np.float64],
    payout: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Outcomes of the concatenated resampled years, built from scratch.

    ``drawn`` holds positions into ``years``, one per resampled year.
    """
    row_years = data.events["year"].to_numpy()
    draws = data.events["draw_id"].to_numpy()
    rates = data.rates
    n_years = data.metadata.n_years
    out_loss: list[float] = []
    out_pay: list[float] = []
    out_prob: list[float] = []
    if basis is Basis.ANNUAL:
        n_draws = round(1.0 / (rates[0] * n_years))
        for pos in drawn:
            for d in range(n_draws):
                rows = (row_years == years[pos]) & (draws == d)
                out_loss.append(float(loss[rows].sum()))
                out_pay.append(float(payout[rows].sum()))
                out_prob.append(1.0 / (years.size * n_draws))
    else:
        for pos in drawn:
            rows = np.flatnonzero(row_years == years[pos])
            out_loss.extend(loss[rows].tolist())
            out_pay.extend(payout[rows].tolist())
            if basis is Basis.EVENT:
                out_prob.extend((rates[rows] * n_years / years.size).tolist())
            else:
                out_prob.extend(rates[rows].tolist())
        if basis is Basis.EVENT:
            none = 1.0 - sum(out_prob)
            assert none >= -1e-12
            out_loss.append(0.0)
            out_pay.append(0.0)
            out_prob.append(max(none, 0.0))
    return np.array(out_loss), np.array(out_pay), np.array(out_prob)


def col(frame: pd.DataFrame, name: str) -> NDArray[Any]:
    """A column as a numpy array (typed, for pyright)."""
    return np.asarray(frame[name].to_numpy())


def assert_kpis_close(
    got: dict[KpiName, float], expected: dict[KpiName, float]
) -> None:
    for kpi, value in expected.items():
        if math.isnan(value):
            assert math.isnan(got[kpi]), kpi
        else:
            assert got[kpi] == pytest.approx(value, rel=1e-9, abs=1e-9), kpi


# --------------------------------------------------------------------------
# Resampling years
# --------------------------------------------------------------------------


def test_resample_years_shape_counts_and_determinism() -> None:
    years = np.array([7, 3, 5, 9])
    rs = resample_years(years, 50, np.random.default_rng(1))
    assert rs.n_bootstrap == 50
    assert rs.n_years == 4
    np.testing.assert_array_equal(rs.years, [3, 5, 7, 9])
    counts = rs.counts()
    assert counts.shape == (50, 4)
    np.testing.assert_array_equal(counts.sum(axis=1), 4)
    for b in range(50):
        np.testing.assert_array_equal(
            counts[b], np.bincount(rs.indices[b], minlength=4)
        )
    np.testing.assert_array_equal(rs.counts(10, 20), counts[10:20])
    again = resample_years(years, 50, np.random.default_rng(1))
    assert rs.same_as(again)
    assert not rs.same_as(resample_years(years, 50, np.random.default_rng(2)))
    assert not rs.same_as(resample_years(years + 1, 50, np.random.default_rng(1)))


@pytest.mark.parametrize(
    ("years", "n", "rng"),
    [
        ([1, 2], 0, np.random.default_rng(0)),
        ([1, 2], True, np.random.default_rng(0)),
        ([1, 2], 2.0, np.random.default_rng(0)),
        ([1, 1], 2, np.random.default_rng(0)),
        ([], 2, np.random.default_rng(0)),
        ([1.5, 2.5], 2, np.random.default_rng(0)),
        ([1, 2], 2, 0),
    ],
)
def test_resample_years_rejects_bad_input(
    years: object, n: object, rng: object
) -> None:
    with pytest.raises(BootstrapError):
        resample_years(years, n, rng)  # type: ignore[arg-type]


def test_year_resample_validates() -> None:
    with pytest.raises(BootstrapError):
        YearResample(years=np.array([2, 1]), indices=np.zeros((1, 2), dtype=int))
    with pytest.raises(BootstrapError):
        YearResample(years=np.array([1, 2]), indices=np.zeros((1, 3), dtype=int))
    with pytest.raises(BootstrapError):
        YearResample(years=np.array([1, 2]), indices=np.full((1, 2), 2))
    rs = YearResample(years=np.array([1, 2]), indices=np.array([[0, 1]], np.int32))
    assert not rs.indices.flags.writeable


def test_defaults_follow_the_spec() -> None:
    assert DEFAULT_N_BOOTSTRAP == 1000
    assert DEFAULT_LEVEL == 0.9


def test_percentile_interval() -> None:
    values = np.arange(101, dtype=float)
    assert percentile_interval(values, 0.9) == pytest.approx((5.0, 95.0))
    low, high = percentile_interval([1.0, np.nan], 0.9)
    assert math.isnan(low)
    assert math.isnan(high)
    with pytest.raises(BootstrapError):
        percentile_interval(values, 1.0)
    with pytest.raises(BootstrapError):
        percentile_interval([], 0.9)


# --------------------------------------------------------------------------
# Every replicate is the KPI of the concatenated resampled years
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("basis", "n_draws"),
    [
        (Basis.EVENT_CONDITIONAL, 2),
        (Basis.ANNUAL, 1),
        (Basis.ANNUAL, 3),
    ],
)
def test_replicates_equal_the_concatenated_years(
    toy_eventset: EventSet, basis: Basis, n_draws: int
) -> None:
    data = random_rows(toy_eventset, n_years=12, n_draws=n_draws, seed=5)
    measure = outcome_measure(data, basis)
    if basis is Basis.ANNUAL:
        # Empty year-draw slots are pooled into one last outcome without rows.
        has_rows = np.bincount(measure.outcome_of_row, minlength=measure.n_outcomes)
        assert has_rows[-1] == 0
    loss = data.loss[:, 0]
    payout = np.minimum(loss, 4.0) * 0.9
    years = np.arange(data.metadata.n_years)
    rs = resample_years(years, 25, np.random.default_rng(11))
    reps = kpi_replicates(
        loss, payout, measure, data.events["year"].to_numpy(), rs, beta=BETA
    )
    for b in range(rs.n_bootstrap):
        ref = reference_kpis(
            *explicit_outcomes(data, basis, rs.years, rs.indices[b], loss, payout),
            BETA,
        )
        assert_kpis_close({k: float(v[b]) for k, v in reps.items()}, ref)


def test_event_basis_no_event_outcome(toy_eventset: EventSet) -> None:
    # One event in each of years 0, 1, 3 of 6 (rates 1/6): a "no event" outcome
    # of probability 1/2, which the replicates rebuild from the drawn years.
    loss = np.array([[3.0, 1.0], [7.0, 2.0], [1.0, 5.0]])
    data = with_rows(toy_eventset, [0, 1, 3], [0, 0, 0], loss, n_years=6)
    measure = outcome_measure(data, Basis.EVENT)
    assert measure.n_outcomes == 4
    payout = np.array([1.0, 6.0, 0.5])
    rs = resample_years(np.arange(6), 40, np.random.default_rng(3))
    reps = kpi_replicates(
        loss[:, 0], payout, measure, data.events["year"].to_numpy(), rs, beta=BETA
    )
    for b in range(rs.n_bootstrap):
        ref = reference_kpis(
            *explicit_outcomes(
                data, Basis.EVENT, rs.years, rs.indices[b], loss[:, 0], payout
            ),
            BETA,
        )
        assert_kpis_close({k: float(v[b]) for k, v in reps.items()}, ref)


def test_identity_resample_reproduces_the_point(toy_eventset: EventSet) -> None:
    data = random_rows(toy_eventset, n_years=9, n_draws=2, seed=2)
    measure = outcome_measure(data, Basis.ANNUAL)
    loss = data.loss.sum(axis=1)
    payout = 0.7 * loss
    identity = YearResample(
        years=np.arange(9), indices=np.arange(9, dtype=np.int32)[None, :]
    )
    reps = kpi_replicates(
        loss, payout, measure, data.events["year"].to_numpy(), identity, beta=BETA
    )
    p = measure.probability
    ref = reference_kpis(
        np.append(measure.aggregate(loss), 0.0),
        np.append(measure.aggregate(payout), 0.0),
        np.append(p, 0.0),
        BETA,
    )
    assert_kpis_close({k: float(v[0]) for k, v in reps.items()}, ref)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


def test_an_outcome_spanning_two_years_is_refused() -> None:
    measure = OutcomeMeasure(
        basis=Basis.ANNUAL, outcome_of_row=np.array([0, 0]), probability=np.array([1.0])
    )
    rs = resample_years(np.array([0, 1]), 3, np.random.default_rng(0))
    with pytest.raises(BootstrapError, match="several years"):
        kpi_replicates([1.0, 2.0], [0.0, 0.0], measure, [0, 1], rs, beta=BETA)


def test_rows_outside_the_resampled_years_are_refused() -> None:
    measure = OutcomeMeasure.per_row(Basis.EVENT_CONDITIONAL, [0.5, 0.5])
    rs = resample_years(np.array([0, 1]), 3, np.random.default_rng(0))
    with pytest.raises(BootstrapError, match="outside"):
        kpi_replicates([1.0, 2.0], [0.0, 0.0], measure, [0, 5], rs, beta=BETA)
    with pytest.raises(BootstrapError, match="row_years"):
        kpi_replicates([1.0, 2.0], [0.0, 0.0], measure, [0], rs, beta=BETA)


def test_event_replicate_with_more_than_one_event_per_year_is_refused() -> None:
    # Year 0 holds probability 0.9; drawing it twice needs 1.8 > 1.
    measure = OutcomeMeasure(
        basis=Basis.EVENT,
        outcome_of_row=np.array([0]),
        probability=np.array([0.9, 0.1]),
    )
    rs = YearResample(years=np.array([0, 1]), indices=np.array([[0, 0]]))
    with pytest.raises(BootstrapError, match="more than one event per year"):
        kpi_replicates([1.0], [0.0], measure, [0], rs, beta=BETA)


def test_event_conditional_replicate_without_rows_is_refused() -> None:
    measure = OutcomeMeasure.per_row(Basis.EVENT_CONDITIONAL, [1.0])
    rs = YearResample(years=np.array([0, 1]), indices=np.array([[1, 1]]))
    with pytest.raises(BootstrapError, match="only years without rows"):
        kpi_replicates([1.0], [0.0], measure, [0], rs, beta=BETA)


def test_bad_values_and_beta_are_refused() -> None:
    measure = OutcomeMeasure.per_row(Basis.EVENT_CONDITIONAL, [0.5, 0.5])
    rs = resample_years(np.array([0, 1]), 3, np.random.default_rng(0))
    with pytest.raises(InputMismatchError, match="loss"):
        kpi_replicates([1.0, np.inf], [0.0, 0.0], measure, [0, 1], rs, beta=BETA)
    with pytest.raises(InputMismatchError, match="beta"):
        kpi_replicates([1.0, 2.0], [0.0, 0.0], measure, [0, 1], rs, beta=1.0)


# --------------------------------------------------------------------------
# A run's KPI table
# --------------------------------------------------------------------------


def solved(
    data: EventSet,
    scope: Individual | Portfolio,
    objective: MSE | WeightedCVaR,
    basis: Basis,
    sample: Sample | None = None,
) -> list[SolveResult]:
    built = build_problems(
        data,
        scope,
        StepPayout(attachment=0.0, limit=40.0, n_bins=4),
        objective,
        PurePremium(),
        (),
        basis=basis,
        sample=sample,
    )
    return [solve(p) for p in built]


@pytest.mark.parametrize("basis", [Basis.EVENT_CONDITIONAL, Basis.ANNUAL])
def test_bootstrap_kpis_keeps_the_point_and_fills_the_intervals(
    toy_eventset: EventSet, basis: Basis
) -> None:
    data = random_rows(toy_eventset, n_years=30, n_draws=2, seed=8)
    scope = Individual()
    results = solved(data, scope, MSE(), basis)
    rs = resample_years(np.arange(30), 200, np.random.default_rng(4))
    boot = bootstrap_kpis(
        data,
        scope,
        results,
        basis=basis,
        beta=BETA,
        run_id="run",
        resample=rs,
        pricing=PurePremium(),
    )
    expected = kpis(
        data,
        scope,
        results,
        basis=basis,
        beta=BETA,
        run_id="run",
        pricing=PurePremium(),
    )
    table = boot.table
    KPIS.validate(table)
    pd.testing.assert_frame_equal(
        table.drop(columns=["ci_low", "ci_high", "ci_level", "n_bootstrap"]),
        expected.drop(columns=["ci_low", "ci_high", "ci_level", "n_bootstrap"]),
    )
    low_col, high_col, value = (
        col(table, "ci_low"),
        col(table, "ci_high"),
        col(table, "value"),
    )
    np.testing.assert_array_equal(col(table, "ci_level"), 0.9)
    np.testing.assert_array_equal(col(table, "n_bootstrap"), 200)
    assert boot.replicates.shape == (len(table), 200)
    bounded = ~np.isnan(low_col)
    assert bounded.any()
    assert np.all(low_col[bounded] <= high_col[bounded])
    # The bounds are the percentile interval of the stored replicates.
    for i in np.flatnonzero(bounded):
        assert percentile_interval(boot.replicates[i], 0.9) == (low_col[i], high_col[i])
    # Premium (pure) equals the expected payout in every replicate.
    kpi, level = col(table, "kpi"), col(table, "level")
    for name in ("problem", "portfolio"):
        prem = boot.replicates[(level == name) & (kpi == "premium")]
        pay = boot.replicates[(level == name) & (kpi == "expected_payout")]
        np.testing.assert_allclose(prem, pay, rtol=1e-12)
    # Every subject's expected loss is bounded around its point.
    el = kpi == "expected_loss"
    assert np.all((low_col[el] <= value[el]) & (value[el] <= high_col[el]))


def test_bootstrap_kpis_on_a_test_sample(toy_eventset: EventSet) -> None:
    data = random_rows(toy_eventset, n_years=30, n_draws=1, seed=9)
    years = data.events["year"].to_numpy()
    train = Sample("train", years < 20, np.arange(20))
    test = Sample("test", years >= 20, np.arange(20, 30))
    scope = Portfolio()
    results = solved(data, scope, MSE(), Basis.ANNUAL, sample=train)
    rs = resample_years(test.years, 100, np.random.default_rng(0))
    boot = bootstrap_kpis(
        data,
        scope,
        results,
        basis=Basis.ANNUAL,
        beta=BETA,
        run_id="r",
        resample=rs,
        sample=test,
    )
    assert set(boot.table["eval_split"]) == {"test"}
    wrong = resample_years(np.arange(30), 100, np.random.default_rng(0))
    with pytest.raises(BootstrapError, match=r"Sample\.years"):
        bootstrap_kpis(
            data,
            scope,
            results,
            basis=Basis.ANNUAL,
            beta=BETA,
            run_id="r",
            resample=wrong,
            sample=test,
        )


@pytest.mark.parametrize("basis", [Basis.EVENT_CONDITIONAL, Basis.ANNUAL])
def test_loaded_premium_is_priced_on_each_replicate(
    toy_eventset: EventSet, basis: Basis
) -> None:
    # Premium (1 - r) E[pi] + r CVaR_q(pi) of the portfolio payout, priced on
    # the concatenated resampled years (MAR-27 pricing on the aggregate payout).
    data = random_rows(toy_eventset, n_years=20, n_draws=2, seed=12)
    scope = Individual()
    results = solved(data, scope, MSE(), basis)
    pricing = CostOfCapitalLoad(rate=0.3, q=BETA)
    rs = resample_years(np.arange(20), 30, np.random.default_rng(2))
    boot = bootstrap_kpis(
        data,
        scope,
        results,
        basis=basis,
        beta=BETA,
        run_id="r",
        resample=rs,
        pricing=pricing,
    )
    expected = kpis(
        data, scope, results, basis=basis, beta=BETA, run_id="r", pricing=pricing
    )
    np.testing.assert_array_equal(col(boot.table, "value"), col(expected, "value"))
    ev = evaluate_results(data, scope, results, basis=basis)
    (portfolio,) = [s for s in ev.subjects if s.level.value == "portfolio"]
    (row,) = np.flatnonzero(
        (col(boot.table, "level") == "portfolio")
        & (col(boot.table, "kpi") == "premium")
    )
    loss = portfolio.loss
    for b in range(rs.n_bootstrap):
        _, pay, prob = explicit_outcomes(
            data, basis, rs.years, rs.indices[b], loss, portfolio.payout
        )
        p = prob / prob.sum()
        _, cvar = var_cvar(pay, p, BETA)
        premium = 0.7 * float(p @ pay) + 0.3 * cvar
        assert boot.replicates[row, b] == pytest.approx(premium, rel=1e-9)
    # A loaded premium exceeds the expected payout in every replicate here.
    (pay_row,) = np.flatnonzero(
        (col(boot.table, "level") == "portfolio")
        & (col(boot.table, "kpi") == "expected_payout")
    )
    assert np.all(boot.replicates[row] >= boot.replicates[pay_row] - 1e-9)


@pytest.mark.parametrize("basis", [Basis.EVENT_CONDITIONAL, Basis.ANNUAL])
@pytest.mark.parametrize(
    "pricing", [PurePremium(), CostOfCapitalLoad(rate=0.3, q=BETA)], ids=str
)
def test_premium_replicates_equal_those_of_bootstrap_kpis(
    toy_eventset: EventSet, basis: Basis, pricing: PurePremium | CostOfCapitalLoad
) -> None:
    # MAR-153: the array-level helper gives bootstrap_kpis' premium
    # replicates, bit for bit, on the same rows, measure and resample.
    data = random_rows(toy_eventset, n_years=20, n_draws=2, seed=13)
    scope = Individual()
    results = solved(data, scope, MSE(), basis)
    rs = resample_years(np.arange(20), 40, np.random.default_rng(5))
    boot = bootstrap_kpis(
        data,
        scope,
        results,
        basis=basis,
        beta=BETA,
        run_id="r",
        resample=rs,
        pricing=pricing,
    )
    ev = evaluate_results(data, scope, results, basis=basis)
    row_years = data.events["year"].to_numpy()[ev.sample.rows]
    level, kpi = col(boot.table, "level"), col(boot.table, "kpi")
    subject = col(boot.table, "subject_id")
    for s in ev.subjects:
        if s.level.value not in ("problem", "portfolio"):
            continue
        (row,) = np.flatnonzero(
            (level == s.level.value) & (subject == s.subject_id) & (kpi == "premium")
        )
        reps = premium_replicates(s.payout, ev.measure, row_years, rs, pricing)
        assert reps.shape == (rs.n_bootstrap,)
        np.testing.assert_array_equal(reps, boot.replicates[row])


def test_premium_replicates_refuse_bad_input() -> None:
    measure = OutcomeMeasure(
        basis=Basis.EVENT_CONDITIONAL,
        outcome_of_row=np.array([0, 1]),
        probability=np.array([0.5, 0.5]),
    )
    rs = resample_years([0, 1], 5, np.random.default_rng(0))
    pure = PurePremium()
    np.testing.assert_allclose(
        premium_replicates([1.0, 3.0], measure, [0, 1], rs, pure),
        kpi_replicates([0.0, 0.0], [1.0, 3.0], measure, [0, 1], rs, beta=BETA)[
            KpiName.EXPECTED_PAYOUT
        ],
        rtol=1e-12,
    )
    with pytest.raises(ComponentConfigError, match="Pricing"):
        premium_replicates([1.0, 3.0], measure, [0, 1], rs, "pure")  # type: ignore[arg-type]
    with pytest.raises(BootstrapError, match="YearResample"):
        premium_replicates([1.0, 3.0], measure, [0, 1], "rs", pure)  # type: ignore[arg-type]
    with pytest.raises(InputMismatchError, match="payout"):
        premium_replicates([1.0], measure, [0, 1], rs, pure)
    with pytest.raises(BootstrapError, match="outside the resampled years"):
        premium_replicates([1.0, 3.0], measure, [0, 5], rs, pure)


def test_undefined_replicates_give_null_bounds(toy_eventset: EventSet) -> None:
    # Location B's only loss is in year 0: a replicate without year 0 has
    # E[L] = 0 (undefined ratio) and constant loss (undefined correlation).
    loss = np.array([[1.0, 5.0], [2.0, 0.0], [3.0, 0.0], [4.0, 0.0]])
    data = with_rows(toy_eventset, [0, 1, 2, 3], [0, 0, 0, 0], loss, n_years=4)
    scope = Individual()
    results = solved(data, scope, MSE(), Basis.ANNUAL)
    rs = resample_years(np.arange(4), 300, np.random.default_rng(1))
    boot = bootstrap_kpis(
        data,
        scope,
        results,
        basis=Basis.ANNUAL,
        beta=BETA,
        run_id="r",
        resample=rs,
    )
    undefined = boot.n_undefined
    ratio_b = (col(undefined, "subject_id") == "B") & (
        col(undefined, "kpi") == "payout_to_loss_ratio"
    )
    assert ratio_b.sum() >= 1
    assert np.all(col(undefined, "n_undefined")[ratio_b] > 0)
    t = boot.table
    rows = (col(t, "subject_id") == "B") & (col(t, "kpi") == "payout_to_loss_ratio")
    assert np.all(np.isnan(col(t, "ci_low")[rows]))
    assert not np.any(np.isnan(col(t, "value")[rows]))
    np.testing.assert_array_equal(col(t, "n_bootstrap")[rows], 300)


def test_var_on_a_step_of_the_distribution() -> None:
    # Ten equally likely values; beta a rounding error above the 7th step.
    values = np.arange(10.0)
    prob = np.full((1, 10), 0.1)
    beta = float(np.cumsum(prob[0])[6]) + 5e-13
    var, _ = _var_cvar_rows(values, prob, beta)
    assert var[0] == 6.0  # the exact-arithmetic 0.7-quantile
    assert var_cvar(values, prob[0], beta)[0] == 7.0  # strict comparison
    assert _is_quantile_step(values, prob[0], beta, 6.0, 7.0)
    assert not _is_quantile_step(values, prob[0], beta, 6.0, 8.0)
    assert not _is_quantile_step(values, prob[0], 0.65, 6.0, 7.0)


def test_point_check_accepts_the_other_side_of_a_step(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    import parametric_insurance_design.bootstrap as bootstrap_module

    # 40 equally likely (year, draw) slots and beta = 0.8: the portfolio VaR
    # falls on a step, where evaluate and the bootstrap may round to the two
    # adjacent atoms on different platforms (seen on Linux CI).
    data = random_rows(toy_eventset, n_years=20, n_draws=2, seed=12)
    scope = Portfolio()
    results = solved(data, scope, MSE(), Basis.ANNUAL)
    rs = resample_years(np.arange(20), 20, np.random.default_rng(0))
    real = bootstrap_module.kpis  # pyright: ignore[reportPrivateImportUsage]
    table = real(data, scope, results, basis=Basis.ANNUAL, beta=0.8, run_id="r")
    ev = evaluate_results(data, scope, results, basis=Basis.ANNUAL)
    (portfolio,) = [s for s in ev.subjects if s.level.value == "portfolio"]
    u = ev.measure.aggregate(np.maximum(portfolio.loss - portfolio.payout, 0.0))
    p = ev.measure.probability
    is_var = (col(table, "level") == "portfolio") & (
        col(table, "kpi") == "var_uncovered"
    )
    var = float(col(table, "value")[is_var][0])
    atoms = np.unique(u)
    below = float(p[u <= var].sum())
    other = atoms[atoms > var][0] if abs(below - 0.8) < 1e-9 else atoms[atoms < var][-1]
    assert _is_quantile_step(u, p, 0.8, var, float(other))

    def replaced(value: float) -> object:
        def fake(*args: object, **kwargs: object) -> pd.DataFrame:
            out = real(*args, **kwargs)  # type: ignore[arg-type]
            out.loc[is_var, "value"] = value
            return out

        return fake

    monkeypatch.setattr(bootstrap_module, "kpis", replaced(float(other)))
    boot = bootstrap_kpis(
        data, scope, results, basis=Basis.ANNUAL, beta=0.8, run_id="r", resample=rs
    )
    assert float(col(boot.table, "value")[is_var][0]) == float(other)
    monkeypatch.setattr(bootstrap_module, "kpis", replaced(var + 1e3))
    with pytest.raises(BootstrapError, match="drifted"):
        bootstrap_kpis(
            data, scope, results, basis=Basis.ANNUAL, beta=0.8, run_id="r", resample=rs
        )


def test_a_kpi_the_bootstrap_does_not_know_is_refused(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    import parametric_insurance_design.bootstrap as bootstrap_module

    data = random_rows(toy_eventset, n_years=6, n_draws=1, seed=1)
    scope = Portfolio()
    results = solved(data, scope, MSE(), Basis.ANNUAL)
    rs = resample_years(np.arange(6), 5, np.random.default_rng(0))
    real = bootstrap_module.kpis  # pyright: ignore[reportPrivateImportUsage]

    def drifted(*args: object, **kwargs: object) -> pd.DataFrame:
        table = real(*args, **kwargs)  # type: ignore[arg-type]
        table.loc[table["kpi"] == "expected_loss", "value"] *= 1.01
        return table

    monkeypatch.setattr(bootstrap_module, "kpis", drifted)
    with pytest.raises(BootstrapError, match="drifted"):
        bootstrap_kpis(
            data, scope, results, basis=Basis.ANNUAL, beta=BETA, run_id="r", resample=rs
        )


# --------------------------------------------------------------------------
# Paired differences
# --------------------------------------------------------------------------


def two_designs(toy_eventset: EventSet) -> tuple[KpiBootstrap, KpiBootstrap, EventSet]:
    data = random_rows(toy_eventset, n_years=30, n_draws=1, seed=4)
    scope = Portfolio()
    rs = resample_years(np.arange(30), 300, np.random.default_rng(6))
    out: list[KpiBootstrap] = []
    for run_id, objective in (
        ("wcvar", WeightedCVaR(alpha=0.9, beta=0.8)),
        ("mse", MSE()),
    ):
        results = solved(data, scope, objective, Basis.ANNUAL)
        out.append(
            bootstrap_kpis(
                data,
                scope,
                results,
                basis=Basis.ANNUAL,
                beta=BETA,
                run_id=run_id,
                resample=rs,
            )
        )
    return out[0], out[1], data


def test_paired_difference(toy_eventset: EventSet) -> None:
    a, b, _ = two_designs(toy_eventset)
    diff = paired_difference(a, b)
    assert len(diff) == len(a.table)
    assert set(diff["run_id_a"]) == {"wcvar"}
    assert set(diff["run_id_b"]) == {"mse"}
    np.testing.assert_allclose(diff["difference"], diff["value_a"] - diff["value_b"])

    def portfolio_cvar(frame: pd.DataFrame) -> int:
        mask = (col(frame, "level") == "portfolio") & (
            col(frame, "kpi") == "cvar_uncovered"
        )
        (i,) = np.flatnonzero(mask)
        return int(i)

    i, ia, ib = portfolio_cvar(diff), portfolio_cvar(a.table), portfolio_cvar(b.table)
    low, high = percentile_interval(a.replicates[ia] - b.replicates[ib], 0.9)
    assert col(diff, "ci_low")[i] == low
    assert col(diff, "ci_high")[i] == high
    # Same losses in both designs: the expected-loss difference is exactly 0.
    el = col(diff, "kpi") == "expected_loss"
    for name in ("difference", "ci_low", "ci_high"):
        np.testing.assert_array_equal(col(diff, name)[el], 0.0)
    # A design against itself.
    same = paired_difference(a, a, level=0.5)
    np.testing.assert_array_equal(col(same, "ci_level"), 0.5)
    bounded = ~np.isnan(col(same, "ci_low"))
    np.testing.assert_array_equal(col(same, "ci_low")[bounded], 0.0)
    np.testing.assert_array_equal(col(same, "ci_high")[bounded], 0.0)


def test_paired_difference_needs_the_same_resample(toy_eventset: EventSet) -> None:
    a, b, _ = two_designs(toy_eventset)
    other = dataclasses.replace(
        b, resample=resample_years(np.arange(30), 300, np.random.default_rng(7))
    )
    with pytest.raises(BootstrapError, match="different resamples"):
        paired_difference(a, other)
    fewer = dataclasses.replace(b, table=b.table.iloc[1:].reset_index(drop=True))
    with pytest.raises(BootstrapError, match="no partner"):
        paired_difference(a, fewer)


@pytest.mark.parametrize("across_scopes", [False, True])
def test_paired_difference_names_missing_columns(
    toy_eventset: EventSet, across_scopes: bool
) -> None:
    # A hand-built table without a column the pairing reads raises a typed
    # error naming every missing column, not pandas' bare KeyError, and before
    # any other check reads the table (across_scopes reads ``level`` first).
    a, b, _ = two_designs(toy_eventset)
    if across_scopes:
        a, b = a.portfolio_rows(), b.portfolio_rows()
    expected = paired_difference(a, b, across_scopes=across_scopes)
    for dropped in (["level"], ["value", "run_id"]):
        bare = dataclasses.replace(b, table=b.table.drop(columns=dropped))
        missing = ", ".join(c for c in (*PAIR_KEY, "run_id", "value") if c in dropped)
        with pytest.raises(
            BootstrapError, match=rf"design b's .* column\(s\) {missing};"
        ):
            paired_difference(a, bare, across_scopes=across_scopes)
        bare = dataclasses.replace(a, table=a.table.drop(columns=dropped))
        with pytest.raises(
            BootstrapError, match=rf"design a's .* column\(s\) {missing};"
        ):
            paired_difference(bare, b, across_scopes=across_scopes)
    # A table with every column (extra ones included) pairs as before.
    extra = dataclasses.replace(b, table=b.table.assign(note="hand-built"))
    pd.testing.assert_frame_equal(
        paired_difference(a, extra, across_scopes=across_scopes), expected
    )


# --------------------------------------------------------------------------
# Paired differences across scopes (MAR-179)
# --------------------------------------------------------------------------

DIFFERENCE_COLUMNS = [
    "run_id_a",
    "run_id_b",
    "value_a",
    "value_b",
    "difference",
    "ci_low",
    "ci_high",
    "ci_level",
    "n_bootstrap",
]


def relabelled_portfolio_rows(boot: KpiBootstrap) -> KpiBootstrap:
    """MAR-158's workaround, ``research/scripts/c1_rq2.py::portfolio_rows``.

    Kept here verbatim as the reference the library pairing must reproduce:
    the portfolio-level rows, every ``problem_id`` relabelled to ``"*"``.
    """
    mask = (boot.table["level"] == "portfolio").to_numpy()
    table = boot.table.loc[mask].copy().reset_index(drop=True)
    table["problem_id"] = ALL_PROBLEMS
    return KpiBootstrap(
        table=table,
        replicates=boot.replicates[mask],
        resample=boot.resample,
        level=boot.level,
    )


def assert_same_as_relabelled(
    new: pd.DataFrame, a: KpiBootstrap, b: KpiBootstrap
) -> None:
    """``new`` equals the workaround's pairing of ``a`` and ``b`` bit for bit."""
    old = paired_difference(relabelled_portfolio_rows(a), relabelled_portfolio_rows(b))
    assert list(new.columns) == [
        "problem_id_a",
        "problem_id_b",
        *PORTFOLIO_PAIR_KEY,
        *DIFFERENCE_COLUMNS,
    ]
    pd.testing.assert_frame_equal(
        new.drop(columns=["problem_id_a", "problem_id_b"]),
        old.drop(columns=["problem_id"]),
        check_exact=True,
    )
    for name in ("value_a", "value_b", "difference", "ci_low", "ci_high"):
        assert np.array_equal(col(new, name), col(old, name), equal_nan=True)


def scope_designs(
    toy_eventset: EventSet,
) -> tuple[KpiBootstrap, KpiBootstrap, KpiBootstrap]:
    """Portfolio-scope MSE, individual-scope MSE and portfolio-scope CVaR."""
    data = random_rows(toy_eventset, n_years=30, n_draws=1, seed=4)
    rs = resample_years(np.arange(30), 300, np.random.default_rng(6))
    out: list[KpiBootstrap] = []
    for run_id, scope, objective in (
        ("joint", Portfolio(), MSE()),
        ("individual", Individual(), MSE()),
        ("joint_wcvar", Portfolio(), WeightedCVaR(alpha=0.9, beta=0.8)),
    ):
        results = solved(data, scope, objective, Basis.ANNUAL)
        out.append(
            bootstrap_kpis(
                data,
                scope,
                results,
                basis=Basis.ANNUAL,
                beta=BETA,
                run_id=run_id,
                resample=rs,
                pricing=PurePremium(),
            )
        )
    return out[0], out[1], out[2]


def test_portfolio_rows_keeps_the_portfolio_rows_and_their_replicates(
    toy_eventset: EventSet,
) -> None:
    _, individual, _ = scope_designs(toy_eventset)
    rows = individual.portfolio_rows()
    mask = col(individual.table, "level") == "portfolio"
    assert mask.sum() == len(rows.table) > 0
    assert set(rows.table["level"].astype(str)) == {"portfolio"}
    assert set(rows.table["problem_id"]) == {ALL_PROBLEMS}
    np.testing.assert_array_equal(rows.replicates, individual.replicates[mask])
    pd.testing.assert_frame_equal(
        rows.table, individual.table.loc[mask].reset_index(drop=True)
    )
    assert rows.resample is individual.resample
    assert rows.level == individual.level


def test_paired_difference_across_scopes(toy_eventset: EventSet) -> None:
    joint, individual, _ = scope_designs(toy_eventset)
    # Without the option the portfolio rows don't pair: "portfolio" vs "*".
    with pytest.raises(BootstrapError, match="no partner"):
        paired_difference(joint.portfolio_rows(), individual.portfolio_rows())
    a, b = joint.portfolio_rows(), individual.portfolio_rows()
    diff = paired_difference(a, b, across_scopes=True)
    assert len(diff) == len(a.table) == len(b.table)
    assert set(diff["kpi"]) >= {"expected_uncovered", "cvar_uncovered", "premium"}
    assert set(diff["problem_id_a"]) == {"portfolio"}
    assert set(diff["problem_id_b"]) == {ALL_PROBLEMS}
    assert set(diff["level"].astype(str)) == {"portfolio"}
    assert set(diff["run_id_a"]) == {"joint"}
    assert set(diff["run_id_b"]) == {"individual"}
    np.testing.assert_array_equal(
        col(diff, "difference"), col(diff, "value_a") - col(diff, "value_b")
    )
    for i, kpi in enumerate(diff["kpi"]):
        (ia,) = np.flatnonzero(col(a.table, "kpi") == kpi)
        (ib,) = np.flatnonzero(col(b.table, "kpi") == kpi)
        assert col(diff, "value_a")[i] == col(a.table, "value")[ia]
        assert col(diff, "value_b")[i] == col(b.table, "value")[ib]
        low, high = percentile_interval(a.replicates[ia] - b.replicates[ib], 0.9)
        assert np.array_equal(
            [col(diff, "ci_low")[i], col(diff, "ci_high")[i]],
            [low, high],
            equal_nan=True,
        )
    # Same losses under both scopes: the expected-loss difference is exactly 0.
    el = col(diff, "kpi") == "expected_loss"
    for name in ("difference", "ci_low", "ci_high"):
        np.testing.assert_array_equal(col(diff, name)[el], 0.0)
    assert_same_as_relabelled(diff, joint, individual)
    # The level argument still applies.
    assert set(paired_difference(a, b, level=0.5, across_scopes=True)["ci_level"]) == {
        0.5
    }


def test_across_scopes_agrees_with_the_plain_pairing_within_a_scope(
    toy_eventset: EventSet,
) -> None:
    joint, _, joint_wcvar = scope_designs(toy_eventset)
    plain = paired_difference(joint_wcvar, joint)
    plain = plain.loc[col(plain, "level") == "portfolio"].reset_index(drop=True)
    across = paired_difference(
        joint_wcvar.portfolio_rows(), joint.portfolio_rows(), across_scopes=True
    )
    assert (across["problem_id_a"] == plain["problem_id"]).all()
    assert (across["problem_id_b"] == plain["problem_id"]).all()
    pd.testing.assert_frame_equal(
        across.drop(columns=["problem_id_a", "problem_id_b"]),
        plain.drop(columns=["problem_id"]),
        check_exact=True,
    )


@pytest.mark.parametrize("level", ["location", "entity", "problem"])
def test_across_scopes_refuses_rows_below_the_portfolio_level(
    toy_eventset: EventSet, level: str
) -> None:
    joint, individual, _ = scope_designs(toy_eventset)
    # evaluate.kpis writes no location rows today; relabel entity rows.
    source = "entity" if level == "location" else level
    mask = col(individual.table, "level") == source
    assert mask.any()
    table = individual.table.loc[mask].reset_index(drop=True)
    table["level"] = level
    rows = KpiBootstrap(
        table=table,
        replicates=individual.replicates[mask],
        resample=individual.resample,
        level=individual.level,
    )
    with pytest.raises(BootstrapError, match=rf"design b has .* at level {level}"):
        paired_difference(joint.portfolio_rows(), rows, across_scopes=True)
    with pytest.raises(BootstrapError, match=rf"design a has .* at level {level}"):
        paired_difference(rows, joint.portfolio_rows(), across_scopes=True)


def test_across_scopes_refuses_full_tables_empty_tables_and_other_resamples(
    toy_eventset: EventSet,
) -> None:
    joint, individual, _ = scope_designs(toy_eventset)
    with pytest.raises(BootstrapError, match="portfolio-level rows only"):
        paired_difference(joint, individual, across_scopes=True)
    with pytest.raises(BootstrapError, match=r"design b has .* entity, problem"):
        paired_difference(joint.portfolio_rows(), individual, across_scopes=True)
    empty = KpiBootstrap(
        table=joint.table.iloc[:0],
        replicates=joint.replicates[:0],
        resample=joint.resample,
        level=joint.level,
    )
    with pytest.raises(BootstrapError, match="design a has no portfolio-level"):
        paired_difference(empty, individual.portfolio_rows(), across_scopes=True)
    other = dataclasses.replace(
        individual.portfolio_rows(),
        resample=resample_years(np.arange(30), 300, np.random.default_rng(7)),
    )
    with pytest.raises(BootstrapError, match="different resamples"):
        paired_difference(joint.portfolio_rows(), other, across_scopes=True)
    fewer = joint.portfolio_rows()
    fewer = dataclasses.replace(
        fewer,
        table=fewer.table.iloc[1:].reset_index(drop=True),
        replicates=fewer.replicates[1:],
    )
    with pytest.raises(BootstrapError, match=r"no partner.*same portfolio"):
        paired_difference(fewer, individual.portfolio_rows(), across_scopes=True)


# --------------------------------------------------------------------------
# Paired differences: typed errors for repeated keys (MAR-211)
# --------------------------------------------------------------------------


def stacked(*boots: KpiBootstrap) -> KpiBootstrap:
    """The rows and replicates of several bootstraps in one table."""
    return KpiBootstrap(
        table=pd.concat([b.table for b in boots], ignore_index=True),
        replicates=np.vstack([b.replicates for b in boots]),
        resample=boots[0].resample,
        level=boots[0].level,
    )


def test_paired_difference_refuses_a_table_of_several_runs(
    toy_eventset: EventSet,
) -> None:
    # Two runs' rows in one table repeat every PAIR_KEY (it has no run_id):
    # a BootstrapError naming the runs, not pandas' MergeError.
    joint, _, joint_wcvar = scope_designs(toy_eventset)
    both = stacked(joint, joint_wcvar)
    pattern = (
        r"design {side} has {n} KPI rows whose pairing key repeats.*"
        r"run_id \['joint', 'joint_wcvar'\].*one bootstrap_kpis result per design"
    )
    n = len(both.table)
    with pytest.raises(BootstrapError, match=pattern.format(side="a", n=n)):
        paired_difference(both, joint)
    with pytest.raises(BootstrapError, match=pattern.format(side="b", n=n)):
        paired_difference(joint_wcvar, both)


@pytest.mark.parametrize("level", ["entity", "problem", "portfolio"])
def test_paired_difference_refuses_a_repeated_row_on_the_default_path(
    toy_eventset: EventSet, level: str
) -> None:
    # A row at any level, e.g. a problem-level row, that appears twice in one
    # table has no unique partner; the default path checks every level.
    _, individual, _ = scope_designs(toy_eventset)
    mask = col(individual.table, "level") == level
    extra = KpiBootstrap(
        table=individual.table.loc[mask].reset_index(drop=True),
        replicates=individual.replicates[mask],
        resample=individual.resample,
        level=individual.level,
    )
    twice = stacked(individual, extra)
    match = rf"design a has {2 * int(mask.sum())} KPI rows.*level='{level}'"
    with pytest.raises(BootstrapError, match=match):
        paired_difference(twice, individual)


def test_across_scopes_refuses_portfolio_rows_of_several_problem_ids(
    toy_eventset: EventSet,
) -> None:
    # PORTFOLIO_PAIR_KEY has no problem_id: the portfolio rows of two scopes
    # in one table collide, and the error names both problem ids.
    joint, individual, _ = scope_designs(toy_eventset)
    both = stacked(joint.portfolio_rows(), individual.portfolio_rows())
    match = (
        r"design b has .* pairing key repeats.*problem_id \['\*', 'portfolio'\]"
        r".*across_scopes ignores problem_id"
    )
    with pytest.raises(BootstrapError, match=match):
        paired_difference(joint.portfolio_rows(), both, across_scopes=True)
    # The check runs after the portfolio-only check, which still comes first.
    with pytest.raises(BootstrapError, match="portfolio-level rows only"):
        paired_difference(stacked(joint, individual), both, across_scopes=True)


@dataclasses.dataclass(frozen=True)
class OneClusterPerLocation:
    """Clustering test double: location ``i`` (EventSet order) is cluster ``i + 1``."""

    def assign(self, eventset: EventSet, n_clusters: int) -> Mapping[str, int]:
        return {loc: i + 1 for i, loc in enumerate(eventset.location_ids)}


def test_paired_difference_of_separately_calibrated_cluster_designs(
    toy_eventset: EventSet,
) -> None:
    # Cluster(joint=False) (MAR-180): problem ids "cluster:C<k>". Two such
    # designs pair on the default path, row for row; stacked, they're refused.
    data = random_rows(toy_eventset, n_years=30, n_draws=1, seed=4)
    rs = resample_years(np.arange(30), 300, np.random.default_rng(6))
    scope = Cluster(OneClusterPerLocation(), n_clusters=2, joint=False)
    out: list[KpiBootstrap] = []
    for run_id, objective in (
        ("sep_wcvar", WeightedCVaR(alpha=0.9, beta=0.8)),
        ("sep_mse", MSE()),
    ):
        built = build_problems(
            data,
            scope,
            StepPayout(attachment=0.0, limit=40.0, n_bins=4),
            objective,
            PurePremium(),
            (),
            basis=Basis.ANNUAL,
        )
        results = [solve(p) for p in built]
        out.append(
            bootstrap_kpis(
                data,
                scope,
                results,
                basis=Basis.ANNUAL,
                beta=BETA,
                run_id=run_id,
                resample=rs,
            )
        )
    a, b = out
    assert set(a.table["problem_id"]) == {"cluster:C1", "cluster:C2", ALL_PROBLEMS}
    diff = paired_difference(a, b)
    assert len(diff) == len(a.table) == len(b.table)
    assert set(diff["problem_id"]) == set(a.table["problem_id"])
    np.testing.assert_array_equal(
        col(diff, "difference"), col(diff, "value_a") - col(diff, "value_b")
    )
    across = paired_difference(
        a.portfolio_rows(), b.portfolio_rows(), across_scopes=True
    )
    plain = diff.loc[col(diff, "level") == "portfolio"].reset_index(drop=True)
    pd.testing.assert_frame_equal(
        across.drop(columns=["problem_id_a", "problem_id_b"]),
        plain.drop(columns=["problem_id"]),
        check_exact=True,
    )
    with pytest.raises(BootstrapError, match=r"sep_mse', 'sep_wcvar'"):
        paired_difference(stacked(a, b), b)


@needs_fixture
def test_across_scopes_reproduces_the_c1_relabelling_on_the_parity_fixture() -> None:
    """MAR-179 acceptance: MAR-158's ``scope_paired.csv`` pairing, fixture-sized.

    The C1 RQ2 holdout set-up (``research/scripts/c1_rq2.py``,
    ``holdout_worker``) on the parity fixture: annual basis, 70/30 holdout,
    pure pricing, budget at kappa 1, weighted CVaR at beta 0.99, test KPIs at
    beta 0.95 and 0.99 bootstrapped on one resample of the test years. B is
    200 instead of 1000 and there is no noise layer, to keep it CI-sized.
    For every C1 pair of scopes, the library pairing equals the workaround's
    bit for bit. The same check on the real C1 rows is in the PR (local).
    """
    base = load_config(PARITY_CONFIG)
    config = parse_config(
        {
            **base.model_dump(mode="json"),
            "noise": None,
            "basis": "annual",
            "sample": {"kind": "holdout", "train_fraction": 0.7},
            "objectives": [{"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.99}],
            "sweeps": [],
        }
    )
    prepared = prepare_eventset(config, load_input(config).eventset)
    train, test = holdout(prepared, train_fraction=0.7)
    comps = config.to_components()
    resample = resample_years(test.years, 200, np.random.default_rng(0))
    boots: dict[tuple[str, float], KpiBootstrap] = {}
    for scope_config, scope in zip(config.scopes, comps.scopes, strict=True):
        built = build_problems(
            prepared,
            scope,
            comps.payout,
            comps.objectives[0],
            comps.pricing,
            comps.constraints,
            basis=comps.basis,
            sample=train,
        )
        results = [solve(b, pricing=comps.pricing) for b in built]
        for beta in (0.95, 0.99):
            boots[(scope_config.kind, beta)] = bootstrap_kpis(
                prepared,
                scope,
                results,
                basis=comps.basis,
                beta=beta,
                run_id=scope_config.kind,
                resample=resample,
                sample=test,
                pricing=comps.pricing,
            )
    pairs = (
        ("portfolio", "individual"),
        ("cluster", "individual"),
        ("cluster", "portfolio"),
    )
    for a, b in pairs:
        for beta in (0.95, 0.99):
            boot_a, boot_b = boots[(a, beta)], boots[(b, beta)]
            diff = paired_difference(
                boot_a.portfolio_rows(), boot_b.portfolio_rows(), across_scopes=True
            )
            assert_same_as_relabelled(diff, boot_a, boot_b)
            assert len(diff) == int((col(boot_a.table, "level") == "portfolio").sum())
            assert not np.all(np.isnan(col(diff, "ci_low")))
    # The individual and cluster runs have several problems ("*"), the
    # portfolio run one ("portfolio"): the pair the plain call refuses.
    joint = boots[("portfolio", 0.99)].portfolio_rows()
    individual = boots[("individual", 0.99)].portfolio_rows()
    assert set(joint.table["problem_id"]) == {"portfolio"}
    assert set(individual.table["problem_id"]) == {ALL_PROBLEMS}
    with pytest.raises(BootstrapError, match="no partner"):
        paired_difference(joint, individual)
    assert "problem_id" in PAIR_KEY
    assert "problem_id" not in PORTFOLIO_PAIR_KEY


# --------------------------------------------------------------------------
# Coverage on a synthetic case with a known answer
# --------------------------------------------------------------------------


def synthetic_years(
    rng: np.random.Generator, n_years: int, per_year: int
) -> tuple[NDArray[np.float64], NDArray[np.int64]]:
    """Losses with a shared year effect: ``10 + 2 Z_y + 0.5 eps``, E = 10.

    Events of one year are strongly correlated (correlation 16 / 16.25), so a
    resampling that ignored the years would understate the uncertainty.
    """
    z = rng.standard_normal(n_years)
    eps = rng.standard_normal((n_years, per_year))
    loss = np.maximum(10.0 + 2.0 * z[:, None] + 0.5 * eps, 0.01).ravel()
    years = np.repeat(np.arange(n_years), per_year)
    return loss, years


def test_coverage_on_a_synthetic_case_with_a_known_answer() -> None:
    """90 % intervals cover the true value about 90 % of the time.

    Known answers: E[L] = 10 per event (event_conditional basis, equal rates),
    and for payouts 0.5 L (design a) and 0.3 L (design b) the paired
    difference E[U_a] - E[U_b] = (0.5 - 0.7) * 10 = -2. A row-level
    resample (each row its own "year") misses the year effect and covers far
    less often; that is the reason for year blocks.
    """
    rng = np.random.default_rng(20261028)
    n_sets, n_years, per_year, n_boot = 300, 150, 4, 300
    hits = {"mean": 0, "paired": 0, "rows": 0}
    for _ in range(n_sets):
        loss, years = synthetic_years(rng, n_years, per_year)
        n = loss.size
        measure = OutcomeMeasure.per_row(Basis.EVENT_CONDITIONAL, np.full(n, 1.0 / n))
        rs = resample_years(np.arange(n_years), n_boot, rng)
        a = kpi_replicates(loss, 0.5 * loss, measure, years, rs, beta=0.9)
        b = kpi_replicates(loss, 0.3 * loss, measure, years, rs, beta=0.9)
        low, high = percentile_interval(a[KpiName.EXPECTED_LOSS], 0.9)
        hits["mean"] += low <= 10.0 <= high
        diff = a[KpiName.EXPECTED_UNCOVERED] - b[KpiName.EXPECTED_UNCOVERED]
        low, high = percentile_interval(diff, 0.9)
        hits["paired"] += low <= -2.0 <= high
        rows = resample_years(np.arange(n), n_boot, rng)
        naive = kpi_replicates(loss, 0.5 * loss, measure, np.arange(n), rows, beta=0.9)
        low, high = percentile_interval(naive[KpiName.EXPECTED_LOSS], 0.9)
        hits["rows"] += low <= 10.0 <= high
    coverage = {k: v / n_sets for k, v in hits.items()}
    # Binomial standard error at 0.9 with 300 sets: 0.017.
    assert 0.85 <= coverage["mean"] <= 0.95, coverage
    assert 0.85 <= coverage["paired"] <= 0.95, coverage
    assert coverage["rows"] < 0.75, coverage
