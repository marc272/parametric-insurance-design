"""Evaluation: KPIs and exceedance curves (SPEC §4.2, §6.1, §6.2).

Owner: MAR-16. Port of the thesis ``benchmarking.py``
(``calculate_benchmarking_kpis``) and of the quantile behind its exceedance
plots (``plotting._weighted_quantile``). Outputs are tidy tables validated
against :data:`~parametric_insurance_design.records.KPIS` and
:data:`~parametric_insurance_design.records.EXCEEDANCE`.

How a run is evaluated
    1. ``data = sample.select(eventset)``; the sample defaults to
       ``Sample.full(eventset)``.
    2. ``measure = basis.outcome_measure(data, basis, years=sample.years)``.
    3. Every result's spec is materialised on ``data`` with
       ``scope.materialise`` and its payouts are evaluated with
       ``SolveResult.payouts``. Out-of-sample evaluation passes the test
       sample here and reuses the specs calibrated on the training sample.
    4. Per-row loss ``L`` and payout ``pi`` are formed for every **subject**:
       each entity (``level = "entity"``), each design problem (the sum over
       its entities, ``level = "problem"``) and the whole run (the sum over
       every location and every entity payout, ``level = "portfolio"``,
       ``problem_id = "*"`` when the run has several design problems).
    5. Per-row quantities are summed into outcomes with the measure, and
       weighted with its probabilities.

KPIs of one subject (``p`` the outcome probabilities, ``o`` an outcome, sums
over the rows ``e`` of an outcome)
    * ``U_o = sum_e (L_e - pi_e)^+`` (SPEC §6.2), ``R_o = sum_e (L_e - pi_e)``,
      ``L_o = sum_e L_e`` and ``pi_o = sum_e pi_e``.
    * ``expected_uncovered = E[U]`` [thesis ``E_Uncovered``].
    * ``var_uncovered``, ``cvar_uncovered``: :func:`var_cvar` of ``U`` at
      ``beta`` [``VaR_Uncovered``, ``CVaR_Uncovered``]. ``var_cvar`` lives in
      ``riskmeasures.py`` since MAR-143 and is re-exported here. A cumulative
      probability within ``riskmeasures.CDF_ATOL`` (``1e-10``) of ``beta``
      counts as reaching it, so a VaR on a step of the distribution is the
      exact-arithmetic quantile on every platform (the thesis compared
      exactly).
    * ``rmse_residual = sqrt(E[R^2])`` [``E_Residual``; despite the thesis
      name, a root mean square].
    * ``payout_to_loss_ratio = E[pi] / E[L]``, null if ``E[L] = 0``
      [``E_Payout_to_E_Loss_Ratio``].
    * ``correlation``: correlation of ``L_o`` and ``pi_o`` weighted with
      ``p``, null if either has zero variance [``Correlation``].
    * ``expected_loss = E[L]`` and ``expected_payout = E[pi]``.
    * ``premium`` (only if a pricing is given): ``pricing.premium_value`` of
      each design problem's payout at ``level = "problem"``, and of the
      portfolio payout (the sum over every entity's payout) at ``level =
      "portfolio"``: the premium of the run's whole cover bought by one owner
      (MAR-27). For the pure premium that is the sum of the problem
      premiums. A loaded pricing (``CostOfCapitalLoad``) is sub-additive, so
      the portfolio premium can be less than that sum: the tails of
      separately designed covers diversify when one writer holds them all.
      The sum of the ``problem`` rows is the price of buying each cover
      separately. Pricing is a design-problem component (ADR 0002), so no
      entity-level premium is reported. See ``docs/methodology/pricing.md``.

    On the ``event_conditional`` basis every row is an outcome with
    probability ``rate / sum(rate)``, so these are exactly the thesis
    formulas. On the ``annual`` basis an outcome is a simulated year (and
    draw), years without rows included, so the same code gives the KPIs over
    years. Nothing here depends on the basis beyond the measure (ADR 0002
    §4); the annual measure itself is built in ``basis.py`` (MAR-24).

Exceedance curves
    For each subject and quantity (loss, payout, uncovered loss), the value
    exceeded with probability ``1 / T`` at return period ``T``: the lower
    ``(1 - 1/T)``-quantile of the outcome values, the same quantile as the VaR
    of :func:`var_cvar` (``riskmeasures.lower_quantile``, with the same
    tolerance; thesis ``_weighted_quantile``). On the ``annual``
    basis there are two curves: ``aep`` over the yearly sums and ``oep`` over
    the yearly maximum event (the largest per-row value in each outcome; an
    outcome without rows counts as 0). On the event bases there is one curve,
    ``event``, over the per-event values. ``1 / T`` is a probability under
    the measure, so the unit of ``T`` depends on the basis (``S`` the
    sample's years, ``D`` the draws; see ``basis.py``):

    * ``annual``: years, exactly. Every (year, draw) slot has probability
      ``1 / (|S| * D)``, and each draw is one simulated version of its year
      (SPEC §5), so ``1 / T`` is the share of years whose value exceeds the
      level, averaged over the draws. With ``D = 1`` that is the share of
      the ``|S|`` simulated years. With ``D > 1`` the curve mixes the draws:
      its ``|S| * D`` slots share the hazard of ``|S|`` years, so they are not
      ``|S| * D`` independent years of record.
    * ``event``: years, approximately. Probabilities are the rows' annual
      rates (over the sample's years) plus a "no event" outcome, so ``1 / T``
      is the expected number of events per year whose value exceeds the
      level, and ``T`` is their mean recurrence interval in years. The share
      of years with such an event is at most that rate, so ``T`` reads as an
      occurrence (OEP) return period only while years rarely hold more than
      one such event.
    * ``event_conditional``: events, not years (thesis convention).
      Probabilities are ``rate / sum(rate)`` over the rows given, so ``1 /
      T`` is a share of those rows' events and ``T`` counts events.

No silent failures (thesis issue C3)
    Results whose design problems repeat, overlap in locations, or do not
    cover exactly the EventSet's locations raise
    :class:`~parametric_insurance_design.errors.EntityMismatchError`, as does
    a spec that the scope cannot materialise on the evaluation data. The
    thesis skipped such groups. Undefined KPI values are null rows, never
    missing rows.

Block-bootstrap confidence bounds (MAR-23) fill the ``ci_*`` columns of the
KPI table; ADR 0002 places them in a new module ``bootstrap.py``. Here they
are null.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Final

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import Basis, OutcomeMeasure, outcome_measure
from parametric_insurance_design.errors import (
    ComponentConfigError,
    EntityMismatchError,
    InputMismatchError,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Pricing,
    Sample,
    Scope,
    SolveResult,
)
from parametric_insurance_design.records import (
    ALL_PROBLEMS,
    EXCEEDANCE,
    KPIS,
    CurveKind,
    CurveQuantity,
    KpiLevel,
    KpiName,
)
from parametric_insurance_design.riskmeasures import (
    check_beta,
    discrete_distribution,
    lower_quantile,
    sorted_cdf,
    var_cvar,
)

__all__ = [
    "DEFAULT_RETURN_PERIODS",
    "PORTFOLIO_SUBJECT",
    "Evaluation",
    "KpiSubject",
    "evaluate_results",
    "exceedance_curves",
    "kpis",
    "var_cvar",
]

PORTFOLIO_SUBJECT: Final[str] = "portfolio"
"""``subject_id`` of the rows at ``level = "portfolio"``."""

DEFAULT_RETURN_PERIODS: Final[tuple[float, ...]] = (
    2.0,
    5.0,
    10.0,
    25.0,
    50.0,
    100.0,
    250.0,
)
"""Default return periods of :func:`exceedance_curves`: years on the
``annual`` and ``event`` bases, events on ``event_conditional``."""


# --------------------------------------------------------------------------
# Distribution helpers (VaR, CVaR and quantiles live in riskmeasures.py)
# --------------------------------------------------------------------------


def _mean(x: NDArray[np.float64], p: NDArray[np.float64]) -> float:
    """Weighted mean with normalised weights (thesis ``weighted_mean``)."""
    return float(np.sum(p * x))


def _correlation(
    x: NDArray[np.float64], y: NDArray[np.float64], p: NDArray[np.float64]
) -> float:
    """Weighted Pearson correlation (thesis ``weighted_correlation``).

    NaN if either variable has zero weighted variance.
    """
    dev_x = x - np.sum(p * x)
    dev_y = y - np.sum(p * y)
    cov = np.sum(p * dev_x * dev_y)
    std_x = np.sqrt(np.sum(p * dev_x**2))
    std_y = np.sqrt(np.sum(p * dev_y**2))
    if std_x <= 0 or std_y <= 0:
        return math.nan
    return float(cov / (std_x * std_y))


# --------------------------------------------------------------------------
# Evaluating the results on the data
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class KpiSubject:
    """Per-row loss and payout of one KPI subject (module docstring, step 4).

    Public since MAR-143, for ``bootstrap.py``, which recomputes the KPIs of
    exactly these vectors on resampled measures.

    Attributes
    ----------
    level : KpiLevel
        ``entity``, ``problem`` or ``portfolio``.
    problem_id : str
        Design problem of the subject; ``records.ALL_PROBLEMS`` for the
        portfolio of a run with several design problems.
    subject_id : str
        Entity id, problem id, or :data:`PORTFOLIO_SUBJECT`.
    loss, payout : numpy.ndarray
        Per-row loss and payout on the evaluated rows, shape ``(n_rows,)``,
        loss units.
    """

    level: KpiLevel
    problem_id: str
    subject_id: str
    loss: NDArray[np.float64]
    payout: NDArray[np.float64]


@dataclass(frozen=True, eq=False)
class Evaluation:
    """A run's results evaluated on the rows of one sample.

    Returned by :func:`evaluate_results`; :func:`kpis` and
    :func:`exceedance_curves` compute from it, and so does ``bootstrap.py``.

    Attributes
    ----------
    sample : Sample
        The evaluated sample (``Sample.full`` if none was given).
    measure : OutcomeMeasure
        Outcome measure over the sample's rows.
    subjects : tuple of KpiSubject
        Every entity, then its design problem, in result order, and the
        portfolio last.
    problem_payouts : tuple of (str, numpy.ndarray)
        Each design problem's id and objective-level payout per row (the
        payout that ``pricing.premium_value`` prices).
    """

    sample: Sample
    measure: OutcomeMeasure
    subjects: tuple[KpiSubject, ...]
    problem_payouts: tuple[tuple[str, NDArray[np.float64]], ...]


def _check_results(data: EventSet, results: Sequence[SolveResult]) -> None:
    """Check that the results form one run over the EventSet's locations.

    Raises
    ------
    EntityMismatchError
        If there are no results, a problem id repeats, two problems share a
        location, or the problems do not cover exactly the EventSet's
        locations (a missing result would bias the portfolio KPIs).
    """
    if len(results) == 0:
        raise EntityMismatchError("no results to evaluate")
    for r in results:
        if not isinstance(r, SolveResult):
            raise EntityMismatchError(f"results must be SolveResults, got {r!r}")
    ids = [r.problem_id for r in results]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise EntityMismatchError(f"design problems repeat: {repeated}")
    owner: dict[str, str] = {}
    for r in results:
        for loc in r.spec.location_ids:
            if loc in owner:
                raise EntityMismatchError(
                    f"location {loc!r} is in design problems {owner[loc]!r} "
                    f"and {r.problem_id!r}"
                )
            owner[loc] = r.problem_id
    present = data.location_ids
    missing = [loc for loc in present if loc not in owner]
    unknown = sorted(set(owner) - set(present))
    if missing or unknown:
        raise EntityMismatchError(
            "results and EventSet locations differ: no result covers "
            f"{missing}, not in the EventSet {unknown}"
        )


def evaluate_results(
    eventset: EventSet,
    scope: Scope,
    results: Sequence[SolveResult],
    *,
    basis: Basis,
    sample: Sample | None = None,
) -> Evaluation:
    """Materialise every result on the sample and form the KPI subjects.

    Steps 1 to 4 of the module docstring, shared by :func:`kpis`,
    :func:`exceedance_curves` and ``bootstrap.bootstrap_kpis`` (public since
    MAR-143), so that all of them see the same per-row vectors.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    scope : Scope
        Scope the results were calibrated with.
    results : sequence of SolveResult
        One per design problem of the run. Together they cover exactly the
        EventSet's locations.
    basis : Basis
        Evaluation basis.
    sample : Sample, optional
        Rows to evaluate on. Default: all rows.

    Returns
    -------
    Evaluation
        The sample, its measure, the KPI subjects and the design problems'
        payouts.

    Raises
    ------
    ComponentConfigError
        If ``scope`` is not a Scope.
    EntityMismatchError
        If the results do not form one run over the EventSet's locations, or
        a spec cannot be materialised on the evaluation rows.
    InputMismatchError
        If the sample does not fit the EventSet.
    """
    basis = Basis(basis)
    if not isinstance(scope, Scope):
        raise ComponentConfigError(f"scope must be a Scope, got {scope!r}")
    sample = Sample.full(eventset) if sample is None else sample
    data = sample.select(eventset)
    _check_results(data, results)
    measure = outcome_measure(data, basis, years=sample.years)
    if measure.n_rows != data.n_rows:
        raise InputMismatchError(
            f"the measure covers {measure.n_rows} rows, the sample {data.n_rows}"
        )

    subjects: list[KpiSubject] = []
    problem_payouts: list[tuple[str, NDArray[np.float64]]] = []
    entity_payouts: list[NDArray[np.float64]] = []
    for result in results:
        problem = scope.materialise(data, result.spec)
        payout = result.payouts(problem)
        pid = result.problem_id
        for j, entity_id in enumerate(problem.spec.entity_ids):
            subjects.append(
                KpiSubject(
                    KpiLevel.ENTITY,
                    pid,
                    entity_id,
                    problem.entity_loss[:, j],
                    payout[:, j],
                )
            )
            entity_payouts.append(payout[:, j])
        problem_payout = np.vstack(list(payout.T)).sum(axis=0)
        subjects.append(
            KpiSubject(KpiLevel.PROBLEM, pid, pid, problem.loss, problem_payout)
        )
        problem_payouts.append((pid, problem_payout))

    # Portfolio: every location's loss and every entity's payout, summed one
    # vector after the other, as the thesis does.
    portfolio_loss = np.vstack(list(data.loss.T)).sum(axis=0)
    portfolio_payout = np.vstack(entity_payouts).sum(axis=0)
    portfolio_pid = ALL_PROBLEMS if len(results) > 1 else results[0].problem_id
    subjects.append(
        KpiSubject(
            KpiLevel.PORTFOLIO,
            portfolio_pid,
            PORTFOLIO_SUBJECT,
            portfolio_loss,
            portfolio_payout,
        )
    )
    return Evaluation(
        sample=sample,
        measure=measure,
        subjects=tuple(subjects),
        problem_payouts=tuple(problem_payouts),
    )


def _check_run_id(run_id: object) -> str:
    if not isinstance(run_id, str) or not run_id:
        raise InputMismatchError(f"run_id must be a non-empty string, got {run_id!r}")
    return run_id


def _subject_kpis(
    subject: KpiSubject, measure: OutcomeMeasure, p: NDArray[np.float64], beta: float
) -> dict[KpiName, float]:
    """KPI values of one subject (thesis ``_calculate_entity_kpis``)."""
    residual = subject.loss - subject.payout
    loss_o = measure.aggregate(subject.loss)
    payout_o = measure.aggregate(subject.payout)
    uncovered_o = measure.aggregate(np.maximum(0.0, residual))
    residual_o = measure.aggregate(residual)

    var, cvar = var_cvar(uncovered_o, measure.probability, beta)
    expected_loss = _mean(loss_o, p)
    expected_payout = _mean(payout_o, p)
    ratio = math.nan if expected_loss == 0 else expected_payout / expected_loss
    return {
        KpiName.EXPECTED_LOSS: expected_loss,
        KpiName.EXPECTED_PAYOUT: expected_payout,
        KpiName.EXPECTED_UNCOVERED: _mean(uncovered_o, p),
        KpiName.VAR_UNCOVERED: var,
        KpiName.CVAR_UNCOVERED: cvar,
        KpiName.RMSE_RESIDUAL: math.sqrt(_mean(residual_o**2, p)),
        KpiName.PAYOUT_TO_LOSS_RATIO: ratio,
        KpiName.CORRELATION: _correlation(loss_o, payout_o, p),
    }


_BETA_KPIS: Final[frozenset[KpiName]] = frozenset(
    {KpiName.VAR_UNCOVERED, KpiName.CVAR_UNCOVERED}
)


def kpis(
    eventset: EventSet,
    scope: Scope,
    results: Sequence[SolveResult],
    *,
    basis: Basis,
    beta: float,
    run_id: str,
    sample: Sample | None = None,
    pricing: Pricing | None = None,
) -> pd.DataFrame:
    """KPIs per entity, design problem and portfolio.

    See the module docstring for the subjects, the formulas and their thesis
    names.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    scope : Scope
        Scope the results were calibrated with; materialises their specs on
        the evaluation rows.
    results : sequence of SolveResult
        One per design problem of the run. Together they cover exactly the
        EventSet's locations.
    basis : Basis
        Evaluation basis.
    beta : float
        Confidence level of the VaR/CVaR KPIs, in ``(0, 1)``.
    run_id : str
        Written to every row.
    sample : Sample, optional
        Rows to evaluate on (e.g. the test sample). Default: all rows. Its
        ``name`` and ``fold`` go into ``eval_split`` and ``fold``.
    pricing : Pricing, optional
        If given, adds the ``premium`` KPI at the problem and portfolio
        levels. The portfolio premium is the pricing of the aggregate payout,
        not the sum of the problem premiums (module docstring).

    Returns
    -------
    pandas.DataFrame
        Table with the ``records.KPIS`` schema: for every subject, the eight
        KPIs (plus ``premium``), ``beta`` set on the VaR/CVaR rows only, and
        null ``ci_*`` columns. Undefined values (a ratio with zero expected
        loss, a correlation with zero variance) are null.

    Raises
    ------
    ComponentConfigError
        If ``beta`` is not in ``(0, 1)``, or ``scope`` or ``pricing`` is not
        a component of the right kind.
    EntityMismatchError
        If the results do not form one run over the EventSet's locations, or
        a spec cannot be materialised on the evaluation rows.
    InputMismatchError
        If the sample does not fit the EventSet or ``run_id`` is empty.
    RecordSchemaError
        If the sample name is not a ``records.Split`` value.
    """
    level_beta = check_beta(beta)
    run_id = _check_run_id(run_id)
    if pricing is not None and not isinstance(pricing, Pricing):
        raise ComponentConfigError(f"pricing must be a Pricing, got {pricing!r}")
    ev = evaluate_results(eventset, scope, results, basis=basis, sample=sample)
    measure = ev.measure
    p = measure.probability / measure.probability.sum()

    rows: list[dict[str, Any]] = []

    def add(subject: KpiSubject, kpi: KpiName, value: float) -> None:
        rows.append(
            {
                "run_id": run_id,
                "problem_id": subject.problem_id,
                "eval_split": ev.sample.name,
                "fold": ev.sample.fold,
                "basis": measure.basis.value,
                "level": subject.level.value,
                "subject_id": subject.subject_id,
                "kpi": kpi.value,
                "beta": level_beta if kpi in _BETA_KPIS else None,
                "value": None if math.isnan(value) else value,
                "ci_low": None,
                "ci_high": None,
                "ci_level": None,
                "n_bootstrap": None,
            }
        )

    premiums: dict[str, float] = {}
    portfolio_premium = math.nan
    if pricing is not None:
        premiums = {
            pid: float(pricing.premium_value(payout, measure))
            for pid, payout in ev.problem_payouts
        }
        # Portfolio: the pricing applied to the aggregate payout (MAR-27).
        portfolio_premium = next(
            float(pricing.premium_value(s.payout, measure))
            for s in ev.subjects
            if s.level is KpiLevel.PORTFOLIO
        )
    for subject in ev.subjects:
        for kpi, value in _subject_kpis(subject, measure, p, level_beta).items():
            add(subject, kpi, value)
        if pricing is None:
            continue
        if subject.level is KpiLevel.PROBLEM:
            add(subject, KpiName.PREMIUM, premiums[subject.problem_id])
        elif subject.level is KpiLevel.PORTFOLIO:
            add(subject, KpiName.PREMIUM, portfolio_premium)
    return KPIS.from_rows(rows)


def _check_return_periods(return_periods: ArrayLike) -> NDArray[np.float64]:
    """Validate return periods: finite, unique and greater than 1 year.

    Raises
    ------
    InputMismatchError
        If the return periods are empty, not 1-D, not finite, repeat, or any
        is <= 1.
    """
    t = np.atleast_1d(np.asarray(return_periods, dtype=np.float64))
    if t.ndim != 1 or t.size == 0:
        raise InputMismatchError("return_periods must be a non-empty 1-D array")
    if not np.all(np.isfinite(t)) or np.any(t <= 1.0):
        raise InputMismatchError(
            f"return periods must be finite and > 1, got {t.tolist()}"
        )
    if np.unique(t).size != t.size:
        raise InputMismatchError(f"return periods repeat: {t.tolist()}")
    return t


def _outcome_max(
    measure: OutcomeMeasure, values: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Largest per-row value of each outcome; 0 for outcomes without rows."""
    out = np.zeros(measure.n_outcomes, dtype=np.float64)
    np.maximum.at(out, measure.outcome_of_row, values)
    return out


def exceedance_curves(
    eventset: EventSet,
    scope: Scope,
    results: Sequence[SolveResult],
    *,
    basis: Basis,
    run_id: str,
    return_periods: ArrayLike = DEFAULT_RETURN_PERIODS,
    sample: Sample | None = None,
) -> pd.DataFrame:
    """Exceedance curves of loss, payout and uncovered loss.

    For every subject (entity, design problem, portfolio; see the module
    docstring) and quantity, the value exceeded with probability ``1 / T``:
    the lower ``(1 - 1/T)``-quantile of the outcome values under the
    measure, as the VaR of :func:`var_cvar`. The per-row uncovered loss is
    ``(L_e - pi_e)^+``.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    scope : Scope
        Scope the results were calibrated with.
    results : sequence of SolveResult
        One per design problem of the run. Together they cover exactly the
        EventSet's locations.
    basis : Basis
        ``annual`` gives OEP curves (the largest event of each year, a year
        without rows counting as 0) and AEP curves (the sum over each year).
        The event bases give per-event curves (``curve = "event"``). The
        unit of the return period depends on the basis (module docstring,
        "Exceedance curves"):

        * ``annual``: years, exactly. ``1 / T`` is the share of (year, draw)
          slots above the level, i.e. the share of years above it averaged
          over the draws; with one draw, the share of the sample's years.
        * ``event``: years, approximately. ``1 / T`` is the annual rate of
          events above the level, which bounds the share of years with such
          an event from above and equals it when no year holds two.
        * ``event_conditional``: events. ``1 / T`` is a share of the given
          rows' events (thesis plots).
    run_id : str
        Written to every row.
    return_periods : array_like of float, optional
        Return periods, each finite and > 1, unique. In the unit the basis
        gives them (see ``basis``).
    sample : Sample, optional
        Rows to evaluate on. Default: all rows.

    Returns
    -------
    pandas.DataFrame
        Table with the ``records.EXCEEDANCE`` schema.

    Raises
    ------
    EntityMismatchError
        If the results do not form one run over the EventSet's locations, or
        a spec cannot be materialised on the evaluation rows.
    InputMismatchError
        If the return periods are invalid, the sample does not fit the
        EventSet, or ``run_id`` is empty.
    RecordSchemaError
        If the sample name is not a ``records.Split`` value.
    """
    run_id = _check_run_id(run_id)
    periods = _check_return_periods(return_periods)
    ev = evaluate_results(eventset, scope, results, basis=basis, sample=sample)
    measure = ev.measure
    annual = measure.basis is Basis.ANNUAL
    levels = 1.0 - 1.0 / periods

    rows: list[dict[str, Any]] = []
    for subject in ev.subjects:
        per_row = {
            CurveQuantity.LOSS: subject.loss,
            CurveQuantity.PAYOUT: subject.payout,
            CurveQuantity.UNCOVERED: np.maximum(0.0, subject.loss - subject.payout),
        }
        for quantity, values in per_row.items():
            curves: dict[CurveKind, NDArray[np.float64]]
            if annual:
                curves = {
                    CurveKind.OEP: _outcome_max(measure, values),
                    CurveKind.AEP: measure.aggregate(values),
                }
            else:
                curves = {CurveKind.EVENT: measure.aggregate(values)}
            for curve, outcome_values in curves.items():
                x, p = discrete_distribution(outcome_values, measure.probability)
                sorted_x, _, cdf = sorted_cdf(x, p)
                for period, level in zip(periods, levels, strict=True):
                    rows.append(
                        {
                            "run_id": run_id,
                            "problem_id": subject.problem_id,
                            "eval_split": ev.sample.name,
                            "fold": ev.sample.fold,
                            "basis": measure.basis.value,
                            "level": subject.level.value,
                            "subject_id": subject.subject_id,
                            "quantity": quantity.value,
                            "curve": curve.value,
                            "return_period": float(period),
                            "value": lower_quantile(sorted_x, cdf, float(level)),
                        }
                    )
    return EXCEEDANCE.from_rows(rows)
