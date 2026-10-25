"""Evaluation: KPIs and exceedance curves (SPEC §4.2, §6.1, §6.2).

Owner: MAR-16. Port of the thesis ``benchmarking.py``. Outputs are tidy
tables validated against :data:`~parametric_insurance_design.records.KPIS`
and :data:`~parametric_insurance_design.records.EXCEEDANCE`.

Every KPI uses an :class:`~parametric_insurance_design.basis.OutcomeMeasure`
from ``basis.outcome_measure``. KPIs on the annual basis therefore need no
code here beyond aggregating with the measure; they become available when
MAR-24 implements the annual measure. Out-of-sample evaluation materialises
each result's spec on the test sample with ``Scope.materialise``. Missing or
mismatched entities raise
:class:`~parametric_insurance_design.errors.EntityMismatchError`; nothing is
dropped (thesis issue C3).

Block-bootstrap confidence bounds (MAR-23) fill the ``ci_*`` columns of the
KPI table; ADR 0002 places them in a new module ``bootstrap.py``.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from numpy.typing import ArrayLike

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Pricing,
    Sample,
    Scope,
    SolveResult,
)

__all__ = ["exceedance_curves", "kpis", "var_cvar"]


def var_cvar(
    values: ArrayLike, probability: ArrayLike, beta: float
) -> tuple[float, float]:
    """VaR and CVaR of a discrete distribution (thesis ``calculate_var_cvar``).

    Parameters
    ----------
    values : array_like of float
        Outcome values, shape ``(n_outcomes,)``.
    probability : array_like of float
        Outcome probabilities, same shape, summing to one.
    beta : float
        Confidence level in ``(0, 1)``.

    Returns
    -------
    var, cvar : float
        Value-at-risk and conditional value-at-risk at ``beta``.
    """
    raise NotImplementedError("MAR-16")  # pragma: no cover


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
    """KPIs per location, entity, design problem and portfolio.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    scope : Scope
        Scope the results were calibrated with.
    results : sequence of SolveResult
        One per design problem of the run.
    basis : Basis
        Evaluation basis.
    beta : float
        Confidence level of the VaR/CVaR KPIs.
    run_id : str
        Written to every row.
    sample : Sample, optional
        Rows to evaluate on (e.g. the test sample). Default: all rows.
    pricing : Pricing, optional
        If given, adds the ``premium`` KPI.

    Returns
    -------
    pandas.DataFrame
        Table with the ``records.KPIS`` schema.
    """
    raise NotImplementedError("MAR-16")  # pragma: no cover


def exceedance_curves(
    eventset: EventSet,
    scope: Scope,
    results: Sequence[SolveResult],
    *,
    basis: Basis,
    run_id: str,
    return_periods: ArrayLike = (2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0),
    sample: Sample | None = None,
) -> pd.DataFrame:
    """Exceedance curves of loss, payout and uncovered loss.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    scope : Scope
        Scope the results were calibrated with.
    results : sequence of SolveResult
        One per design problem of the run.
    basis : Basis
        ``annual`` gives OEP and AEP curves; the event bases give per-event
        curves.
    run_id : str
        Written to every row.
    return_periods : array_like of float, optional
        Return periods in years.
    sample : Sample, optional
        Rows to evaluate on. Default: all rows.

    Returns
    -------
    pandas.DataFrame
        Table with the ``records.EXCEEDANCE`` schema.
    """
    raise NotImplementedError("MAR-16")  # pragma: no cover
