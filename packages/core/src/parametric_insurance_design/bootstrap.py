"""Block-bootstrap confidence intervals over years (SPEC §6.1, thesis issue M1).

Owner: MAR-23. Fills the ``ci_low``, ``ci_high``, ``ci_level`` and
``n_bootstrap`` columns of the ``kpis`` table (ADR 0002 §7) and gives paired
confidence intervals for the difference of a KPI between two designs.
Method notes: ``docs/methodology/bootstrap.md``.

Resampling unit: a year
    A replicate draws ``|S|`` years with replacement from the ``|S|`` years
    ``S`` of the evaluation sample (``Sample.years``, years without rows
    included). Every row of a drawn year comes along: all its events and all
    their draws (noise copies, vulnerability ``draw_id``), so the dependence
    within a year is kept. :func:`resample_years` draws the year indices
    once; every design evaluated on the same sample can reuse them, which
    makes the comparison **paired** (:func:`paired_difference`).

From year counts to a resampled measure
    A replicate is described by how often each year was drawn, ``c_y``.
    Resampling never changes a row's loss or payout, only how much
    probability its outcome carries, so a replicate is the evaluation
    measure (``basis.outcome_measure``) with reweighted outcomes:

    * an outcome with rows lies in one year ``y`` (checked: an outcome
      spanning two years raises :class:`BootstrapError`) and gets
      probability ``p_o * c_y``;
    * ``event_conditional`` probabilities are conditional on an event, so
      they are divided by their sum (the thesis' rescaling, applied to the
      resampled rows);
    * on ``event`` and ``annual``, probabilities are absolute (a row's
      annual rate; ``1 / (|S| * D)`` per year-and-draw slot), so the
      outcomes with rows keep ``p_o * c_y`` and the outcomes without rows
      (the ``event`` basis' "no event" outcome, the ``annual`` basis'
      pooled empty year-draw slots) take the remaining mass
      ``1 - sum(p_o * c_y)``, shared in proportion to their probabilities.
      If there is no such outcome, a zero-valued one is added. On ``annual``
      this is exact: the empty slots of year ``y`` are drawn ``c_y`` times,
      and their total is the remainder. A negative remainder (an ``event``
      replicate with more than one event per year on average, which that
      basis cannot represent) raises :class:`BootstrapError`.

    Duplicating an outcome ``c`` times and multiplying its probability by
    ``c`` give the same discrete distribution, so every KPI of the replicate
    (means, VaR, CVaR, correlation, premium) equals the KPI of the
    concatenated resampled years. All-ones counts give the evaluation
    measure itself, which :func:`bootstrap_kpis` uses to check that its
    vectorised KPI formulas reproduce ``evaluate.kpis`` (a guard against
    drift; a mismatch raises :class:`BootstrapError`).

Intervals
    Percentile intervals: the ``(1 - level) / 2`` and ``(1 + level) / 2``
    quantiles (``numpy.quantile``, linear interpolation) of the replicate
    values; ``level = 0.9`` by default (SPEC §6.1). Point estimates are
    never changed: they are ``evaluate.kpis``'s values.

No silent failures
    A KPI that is undefined in some replicate (a payout-to-loss ratio with
    zero expected loss, a correlation with zero variance) gets null bounds,
    and :attr:`KpiBootstrap.n_undefined` counts its undefined replicates.
    ``ci_level`` and ``n_bootstrap`` are set on every row of a bootstrapped
    table, so a null bound next to them means "bootstrapped, undefined", not
    "not bootstrapped". A KPI that this module cannot replicate raises.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Final

import numpy as np
import pandas as pd
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import (
    PROBABILITY_ATOL,
    Basis,
    OutcomeMeasure,
)
from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.evaluate import (
    _evaluate,  # pyright: ignore[reportPrivateUsage]
    _Subject,  # pyright: ignore[reportPrivateUsage]
    kpis,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import Pricing, Sample, Scope, SolveResult
from parametric_insurance_design.records import KPIS, KpiLevel, KpiName

__all__ = [
    "DEFAULT_LEVEL",
    "DEFAULT_N_BOOTSTRAP",
    "PAIR_KEY",
    "BootstrapError",
    "KpiBootstrap",
    "YearResample",
    "bootstrap_kpis",
    "kpi_replicates",
    "paired_difference",
    "percentile_interval",
    "resample_years",
]

DEFAULT_N_BOOTSTRAP: Final[int] = 1000
"""Default number of bootstrap replicates ``B`` (SPEC §6.1)."""

DEFAULT_LEVEL: Final[float] = 0.9
"""Default confidence level of the intervals (SPEC §6.1)."""

PAIR_KEY: Final[tuple[str, ...]] = (
    "problem_id",
    "eval_split",
    "fold",
    "basis",
    "level",
    "subject_id",
    "kpi",
    "beta",
)
"""Columns that pair a KPI row of one design with the row of another in
:func:`paired_difference`: the ``kpis`` key without ``run_id``."""

_CHUNK_CELLS: Final[int] = 2_000_000
"""Replicates are processed in chunks of about this many (replicate, outcome)
cells, which bounds the memory of the probability matrices (16 MB each)."""

_POINT_RTOL: Final[float] = 1e-9
"""Relative tolerance of the check against ``evaluate.kpis``."""

_CDF_ATOL: Final[float] = 1e-10
"""A cumulative probability within this of ``beta`` counts as reaching it.

VaR is the smallest value whose cumulative probability reaches ``beta``.
When ``beta`` falls exactly on a step of the distribution (e.g. ``beta = 0.8``
with 40 equally likely years), the summed probabilities land a rounding
error above or below ``beta`` depending on the summation order, which differs
between platforms (``numpy.argsort`` of tied values). Treating a shortfall of
at most this much as reaching ``beta`` gives the exact-arithmetic answer."""

_TIE_ATOL: Final[float] = 1e-9
"""Tolerance of the knife-edge check in :func:`_is_quantile_step`."""

_KEY_COLUMNS: Final[tuple[str, ...]] = ("problem_id", "level", "subject_id", "kpi")
"""Columns that identify a KPI row within one ``evaluate.kpis`` call."""


class BootstrapError(InputMismatchError):
    """A bootstrap cannot be formed from the inputs.

    Raised when an outcome spans several years, a resample cannot be
    represented on the basis, two designs were not resampled together, or
    the vectorised KPIs disagree with ``evaluate.kpis``.
    """


# --------------------------------------------------------------------------
# Resampling years
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class YearResample:
    """Year indices of ``B`` bootstrap replicates of one sample.

    Parameters
    ----------
    years : array_like of int
        The sample's years ``S``, unique; stored sorted.
    indices : array_like of int
        Shape ``(B, |S|)``: replicate ``b`` draws the years
        ``years[indices[b]]``. Values in ``[0, |S|)``.

    Raises
    ------
    BootstrapError
        If the arrays have the wrong shape or values.
    """

    years: NDArray[np.int64]
    indices: NDArray[np.int32]

    def __post_init__(self) -> None:
        """Validate the fields and store read-only copies."""
        years = np.array(self.years, copy=True)
        if (
            years.ndim != 1
            or years.size == 0
            or not np.issubdtype(years.dtype, np.integer)
        ):
            raise BootstrapError("years must be a non-empty 1-D integer array")
        years = years.astype(np.int64)
        if np.any(np.diff(years) <= 0):
            raise BootstrapError("years must be sorted and unique")
        idx = np.array(self.indices, copy=True)
        if (
            idx.ndim != 2
            or idx.shape[0] < 1
            or idx.shape[1] != years.size
            or not np.issubdtype(idx.dtype, np.integer)
        ):
            raise BootstrapError(
                f"indices must be an integer array of shape (B, {years.size})"
            )
        if idx.min() < 0 or idx.max() >= years.size:
            raise BootstrapError(f"indices must lie in [0, {years.size})")
        idx = idx.astype(np.int32)
        years.setflags(write=False)
        idx.setflags(write=False)
        object.__setattr__(self, "years", years)
        object.__setattr__(self, "indices", idx)

    @property
    def n_bootstrap(self) -> int:
        """Number of replicates ``B``."""
        return int(self.indices.shape[0])

    @property
    def n_years(self) -> int:
        """Number of years ``|S|`` per replicate."""
        return int(self.years.shape[0])

    def counts(self, start: int = 0, stop: int | None = None) -> NDArray[np.int64]:
        """How often each year is drawn, for replicates ``start .. stop - 1``.

        Parameters
        ----------
        start, stop : int
            Replicate range, as in a slice. Default: every replicate.

        Returns
        -------
        numpy.ndarray of int
            Shape ``(stop - start, |S|)``; each row sums to ``|S|``.
        """
        idx = self.indices[start:stop].astype(np.int64)
        b, n = idx.shape
        flat = (idx + np.arange(b, dtype=np.int64)[:, None] * n).ravel()
        return np.bincount(flat, minlength=b * n).reshape(b, n)

    def same_as(self, other: YearResample) -> bool:
        """Whether two resamples draw the same years in every replicate."""
        return bool(
            np.array_equal(self.years, other.years)
            and np.array_equal(self.indices, other.indices)
        )


def resample_years(
    years: ArrayLike, n_bootstrap: int, rng: np.random.Generator
) -> YearResample:
    """Draw ``B`` block-bootstrap replicates of a set of years.

    Parameters
    ----------
    years : array_like of int
        The evaluation sample's years (``Sample.years``), unique, including
        years without rows.
    n_bootstrap : int
        Number of replicates ``B``, at least 1.
    rng : numpy.random.Generator
        Source of randomness; ``rng.integers(0, |S|, size=(B, |S|))`` is
        drawn once.

    Returns
    -------
    YearResample
        The replicates' year indices.

    Raises
    ------
    BootstrapError
        If ``years`` is invalid, ``n_bootstrap`` is not a positive integer or
        ``rng`` is not a ``numpy.random.Generator``.
    """
    if isinstance(n_bootstrap, bool) or not isinstance(n_bootstrap, Integral):
        raise BootstrapError(f"n_bootstrap must be an int, got {n_bootstrap!r}")
    if n_bootstrap < 1:
        raise BootstrapError(f"n_bootstrap must be >= 1, got {n_bootstrap}")
    if not isinstance(rng, np.random.Generator):
        raise BootstrapError(f"rng must be a numpy.random.Generator, got {rng!r}")
    arr = np.asarray(years)
    if arr.ndim != 1 or arr.size == 0 or not np.issubdtype(arr.dtype, np.integer):
        raise BootstrapError("years must be a non-empty 1-D integer array")
    sorted_years = np.sort(arr.astype(np.int64))
    if np.any(np.diff(sorted_years) == 0):
        raise BootstrapError("years must be unique")
    n = sorted_years.size
    indices = rng.integers(0, n, size=(int(n_bootstrap), n), dtype=np.int32)
    return YearResample(years=sorted_years, indices=indices)


# --------------------------------------------------------------------------
# Reweighting a measure
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class _Reweighting:
    """Maps year counts to replicate probabilities of one measure's outcomes.

    Column ``n_outcomes`` of :meth:`probabilities` is an extra zero-valued
    outcome that holds the "no rows" mass when the measure has no outcome
    without rows (module docstring).
    """

    measure: OutcomeMeasure
    year_of_outcome: NDArray[np.int64]
    has_rows: NDArray[np.bool_]
    probability: NDArray[np.float64]

    @classmethod
    def build(
        cls, measure: OutcomeMeasure, row_years: ArrayLike, years: NDArray[np.int64]
    ) -> _Reweighting:
        """Locate each outcome's year among the resampled years.

        Raises
        ------
        BootstrapError
            If ``row_years`` does not have one entry per row of the measure,
            a row's year is not among ``years``, an outcome holds rows of
            several years, or an ``event_conditional`` outcome has no rows.
        """
        ry = np.asarray(row_years, dtype=np.int64)
        if ry.shape != (measure.n_rows,):
            raise BootstrapError(
                f"row_years must have shape ({measure.n_rows},), got {ry.shape}"
            )
        pos = np.searchsorted(years, ry)
        pos = np.minimum(pos, years.size - 1)
        if not np.array_equal(years[pos], ry):
            stray = np.setdiff1d(ry, years)
            raise BootstrapError(
                f"rows lie in years outside the resampled years, e.g. "
                f"{stray[:5].tolist()}"
            )
        year_of_outcome = np.full(measure.n_outcomes, -1, dtype=np.int64)
        year_of_outcome[measure.outcome_of_row] = pos
        if not np.array_equal(year_of_outcome[measure.outcome_of_row], pos):
            raise BootstrapError(
                "an outcome holds rows of several years; a year-block bootstrap "
                "cannot resample it"
            )
        has_rows = year_of_outcome >= 0
        probability = measure.probability / measure.probability.sum()
        if measure.basis is Basis.EVENT_CONDITIONAL and np.any(
            probability[~has_rows] > 0
        ):
            raise BootstrapError(
                "an event_conditional outcome without rows has no year to resample"
            )
        return cls(measure, year_of_outcome, has_rows, probability)

    @property
    def n_outcomes(self) -> int:
        return self.measure.n_outcomes

    def probabilities(self, counts: NDArray[np.int64]) -> NDArray[np.float64]:
        """Replicate probabilities, shape ``(b, n_outcomes + 1)``, rows sum to 1.

        Raises
        ------
        BootstrapError
            If an ``event_conditional`` replicate holds no rows, or an
            ``event`` replicate needs a negative "no event" mass.
        """
        b = counts.shape[0]
        n = self.n_outcomes
        out = np.zeros((b, n + 1), dtype=np.float64)
        rows = self.has_rows
        out[:, :n][:, rows] = (
            self.probability[rows] * counts[:, self.year_of_outcome[rows]]
        )
        total = out.sum(axis=1)
        if self.measure.basis is Basis.EVENT_CONDITIONAL:
            if np.any(total <= 0):
                raise BootstrapError(
                    "a replicate drew only years without rows; its "
                    "event_conditional measure is undefined"
                )
            return out / total[:, None]
        remainder = 1.0 - total
        if np.any(remainder < -PROBABILITY_ATOL):
            raise BootstrapError(
                f"a replicate puts probability {float(total.max()):.6g} > 1 on "
                f"outcomes with rows (basis {self.measure.basis.value!r}: more "
                "than one event per year on average); use the annual basis"
            )
        remainder = np.maximum(remainder, 0.0)
        empty = self.probability[~rows]
        if empty.sum() > 0:
            share = empty / empty.sum()
            out[:, :n][:, ~rows] = remainder[:, None] * share
        else:
            out[:, n] = remainder
        return out / out.sum(axis=1)[:, None]

    def replicate_measure(self, probability: NDArray[np.float64]) -> OutcomeMeasure:
        """Return the measure of one replicate (a row of :meth:`probabilities`)."""
        n = self.n_outcomes
        extra = float(probability[n])
        prob = probability[:n] if extra == 0.0 else probability
        return OutcomeMeasure(
            basis=self.measure.basis,
            outcome_of_row=self.measure.outcome_of_row,
            probability=prob,
        )


# --------------------------------------------------------------------------
# Vectorised KPIs
# --------------------------------------------------------------------------


def _var_cvar_rows(
    values: NDArray[np.float64], prob: NDArray[np.float64], beta: float
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """``evaluate.var_cvar`` for every row of ``prob`` over the same values.

    The sort order of the values does not depend on the weights, so the
    values are sorted once and only the cumulative weights differ per row.
    A cumulative probability within :data:`_CDF_ATOL` below ``beta`` counts
    as reaching it (the exact-arithmetic VaR on a step of the distribution).
    """
    order = np.argsort(values)
    xs = values[order]
    ps = prob[:, order]
    n = xs.size
    cdf = np.cumsum(ps, axis=1)
    pos = np.minimum((cdf < beta - _CDF_ATOL).sum(axis=1), n - 1)
    var = xs[pos]
    first_tail = np.searchsorted(xs, var, side="right")
    # Tail sums over the values above the VaR, direct (no cancellation). The
    # tail is short (about 1 - beta of the mass), so only the columns from
    # the smallest tail start on are touched.
    start = int(first_tail.min())
    in_tail = np.arange(start, n)[None, :] >= first_tail[:, None]
    tail = ps[:, start:] * in_tail
    tp = tail.sum(axis=1)
    tpx = tail @ xs[start:]
    with np.errstate(invalid="ignore", divide="ignore"):
        cvar = np.where(tp > 0, (tpx + (1.0 - beta - tp) * var) / (1.0 - beta), var)
    return var, cvar


def _correlation_rows(
    x: NDArray[np.float64], y: NDArray[np.float64], prob: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Weighted Pearson correlation per row of ``prob``; NaN at zero variance.

    Moments are taken about the means under the average of the rows' weights
    (one shift for every row, close to each row's own mean), which removes
    the cancellation of raw moments while keeping the work to matrix-vector
    products.
    """
    average = prob.mean(axis=0)
    xc = x - average @ x
    yc = y - average @ y
    mx = prob @ xc
    my = prob @ yc
    cov = prob @ (xc * yc) - mx * my
    vx = np.maximum(prob @ (xc * xc) - mx * mx, 0.0)
    vy = np.maximum(prob @ (yc * yc) - my * my, 0.0)
    sx = np.sqrt(vx)
    sy = np.sqrt(vy)
    scale_x = np.sqrt(prob @ (xc * xc))
    scale_y = np.sqrt(prob @ (yc * yc))
    # A variance at rounding level of the shifted second moment is zero.
    defined = (sx > 1e-7 * scale_x) & (sy > 1e-7 * scale_y)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(defined, cov / (sx * sy), np.nan)


@dataclass(frozen=True, eq=False)
class _Outcomes:
    """Per-outcome sums of one subject, plus the extra zero-valued outcome."""

    loss: NDArray[np.float64]
    payout: NDArray[np.float64]
    uncovered: NDArray[np.float64]
    residual: NDArray[np.float64]

    @classmethod
    def of(
        cls,
        loss: NDArray[np.float64],
        payout: NDArray[np.float64],
        measure: OutcomeMeasure,
    ) -> _Outcomes:
        residual = loss - payout

        def per_outcome(values: NDArray[np.float64]) -> NDArray[np.float64]:
            return np.append(measure.aggregate(values), 0.0)

        return cls(
            loss=per_outcome(loss),
            payout=per_outcome(payout),
            uncovered=per_outcome(np.maximum(0.0, residual)),
            residual=per_outcome(residual),
        )


def _subject_rows(
    o: _Outcomes, prob: NDArray[np.float64], beta: float
) -> dict[KpiName, NDArray[np.float64]]:
    """Return the eight ``evaluate`` KPIs for every row of ``prob``.

    ``prob`` has one column per outcome plus the extra zero-valued outcome.
    """
    expected_loss = prob @ o.loss
    expected_payout = prob @ o.payout
    var, cvar = _var_cvar_rows(o.uncovered, prob, beta)
    with np.errstate(invalid="ignore", divide="ignore"):
        ratio = np.where(expected_loss == 0, np.nan, expected_payout / expected_loss)
    return {
        KpiName.EXPECTED_LOSS: expected_loss,
        KpiName.EXPECTED_PAYOUT: expected_payout,
        KpiName.EXPECTED_UNCOVERED: prob @ o.uncovered,
        KpiName.VAR_UNCOVERED: var,
        KpiName.CVAR_UNCOVERED: cvar,
        KpiName.RMSE_RESIDUAL: np.sqrt(prob @ (o.residual**2)),
        KpiName.PAYOUT_TO_LOSS_RATIO: ratio,
        KpiName.CORRELATION: _correlation_rows(o.loss, o.payout, prob),
    }


def _replicate_subjects(
    subjects: Sequence[_Outcomes],
    reweighting: _Reweighting,
    resample: YearResample,
    beta: float,
) -> list[dict[KpiName, NDArray[np.float64]]]:
    """KPI replicates of several subjects on one measure, chunk by chunk."""
    parts: list[dict[KpiName, list[NDArray[np.float64]]]] = [{} for _ in subjects]
    for start, stop in _chunks(resample.n_bootstrap, reweighting.n_outcomes):
        prob = reweighting.probabilities(resample.counts(start, stop))
        for subject, part in zip(subjects, parts, strict=True):
            for kpi, values in _subject_rows(subject, prob, beta).items():
                part.setdefault(kpi, []).append(values)
    return [{kpi: np.concatenate(v) for kpi, v in p.items()} for p in parts]


def _chunks(n_bootstrap: int, n_outcomes: int) -> list[tuple[int, int]]:
    """Replicate ranges of about :data:`_CHUNK_CELLS` cells each."""
    size = max(1, _CHUNK_CELLS // max(1, n_outcomes + 1))
    return [(s, min(s + size, n_bootstrap)) for s in range(0, n_bootstrap, size)]


def kpi_replicates(
    loss: ArrayLike,
    payout: ArrayLike,
    measure: OutcomeMeasure,
    row_years: ArrayLike,
    resample: YearResample,
    *,
    beta: float,
) -> dict[KpiName, NDArray[np.float64]]:
    """Bootstrap replicates of the KPIs of one subject (array level).

    The building block of :func:`bootstrap_kpis`, usable without an
    EventSet: per-row loss and payout, the evaluation measure and each row's
    year.

    Parameters
    ----------
    loss, payout : array_like of float
        Per-row loss and payout of the subject, shape ``(n_rows,)``.
    measure : OutcomeMeasure
        Evaluation measure over the same rows.
    row_years : array_like of int
        Year of each row, all among ``resample.years``.
    resample : YearResample
        The replicates.
    beta : float
        VaR/CVaR level, in ``(0, 1)``.

    Returns
    -------
    dict
        For each of the eight ``evaluate`` KPIs (not ``premium``), an array
        of shape ``(B,)``; NaN where the KPI is undefined in a replicate.

    Raises
    ------
    BootstrapError
        If the rows, years and measure do not fit together (module
        docstring).
    InputMismatchError
        If ``loss`` or ``payout`` does not have one value per row, or ``beta``
        is not in ``(0, 1)``.
    """
    level = _check_beta(beta)
    lo = _row_values(loss, measure, "loss")
    pay = _row_values(payout, measure, "payout")
    reweighting = _Reweighting.build(measure, row_years, resample.years)
    (out,) = _replicate_subjects(
        [_Outcomes.of(lo, pay, measure)], reweighting, resample, level
    )
    return out


def _check_beta(beta: object) -> float:
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise InputMismatchError(f"beta must be a real number, got {beta!r}")
    level = float(beta)
    if not (math.isfinite(level) and 0.0 < level < 1.0):
        raise InputMismatchError(f"beta must lie in (0, 1), got {beta!r}")
    return level


def _check_level(level: object) -> float:
    if isinstance(level, bool) or not isinstance(level, Real):
        raise BootstrapError(f"level must be a real number, got {level!r}")
    value = float(level)
    if not (math.isfinite(value) and 0.0 < value < 1.0):
        raise BootstrapError(f"level must lie in (0, 1), got {level!r}")
    return value


def _row_values(
    values: ArrayLike, measure: OutcomeMeasure, name: str
) -> NDArray[np.float64]:
    arr = np.asarray(values, dtype=np.float64)
    if arr.shape != (measure.n_rows,) or not np.all(np.isfinite(arr)):
        raise InputMismatchError(
            f"{name} must be finite with shape ({measure.n_rows},), got {arr.shape}"
        )
    return arr


def percentile_interval(
    replicates: ArrayLike, level: float = DEFAULT_LEVEL
) -> tuple[float, float]:
    """Percentile interval of bootstrap replicates.

    Parameters
    ----------
    replicates : array_like of float
        Replicate values, shape ``(B,)``.
    level : float, default 0.9
        Confidence level, in ``(0, 1)``.

    Returns
    -------
    low, high : float
        The ``(1 - level) / 2`` and ``(1 + level) / 2`` quantiles
        (``numpy.quantile``, linear). NaN, NaN if any replicate is NaN: an
        interval over the defined replicates only would be conditional on
        them.

    Raises
    ------
    BootstrapError
        If ``level`` is not in ``(0, 1)`` or there are no replicates.
    """
    value = _check_level(level)
    arr = np.asarray(replicates, dtype=np.float64)
    if arr.ndim != 1 or arr.size == 0:
        raise BootstrapError("replicates must be a non-empty 1-D array")
    if np.any(np.isnan(arr)):
        return math.nan, math.nan
    low, high = np.quantile(arr, [(1.0 - value) / 2.0, (1.0 + value) / 2.0])
    return float(low), float(high)


# --------------------------------------------------------------------------
# A run's KPI table with confidence intervals
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class KpiBootstrap:
    """A run's KPIs on one sample with their bootstrap replicates.

    Attributes
    ----------
    table : pandas.DataFrame
        ``evaluate.kpis`` output (``records.KPIS``) with the ``ci_*`` columns
        filled.
    replicates : numpy.ndarray
        Shape ``(len(table), B)``: row ``i`` holds the replicates of
        ``table.iloc[i]``; NaN where undefined.
    resample : YearResample
        The replicates' years.
    level : float
        Confidence level of the intervals in ``table``.
    """

    table: pd.DataFrame
    replicates: NDArray[np.float64]
    resample: YearResample
    level: float

    @property
    def n_undefined(self) -> pd.DataFrame:
        """Rows with undefined replicates, and how many.

        Returns
        -------
        pandas.DataFrame
            The ``kpis`` key columns and ``n_undefined`` (> 0), one row per
            KPI whose bounds are null because some replicate is undefined.
        """
        counts = np.isnan(self.replicates).sum(axis=1)
        keep = counts > 0
        out = self.table.loc[keep, list(KPIS.key)].reset_index(drop=True)
        out["n_undefined"] = counts[keep].astype(np.int64)
        return out


def _replicate_premiums(
    reweighting: _Reweighting,
    resample: YearResample,
    payouts: Sequence[tuple[str, NDArray[np.float64]]],
    pricing: Pricing,
) -> NDArray[np.float64]:
    """Premium of each payout in every replicate, shape ``(len(payouts), B)``."""
    out = np.empty((len(payouts), resample.n_bootstrap), dtype=np.float64)
    for start, stop in _chunks(resample.n_bootstrap, reweighting.n_outcomes):
        prob = reweighting.probabilities(resample.counts(start, stop))
        for b in range(stop - start):
            measure = reweighting.replicate_measure(prob[b])
            for i, (_, payout) in enumerate(payouts):
                out[i, start + b] = float(pricing.premium_value(payout, measure))
    return out


def bootstrap_kpis(
    eventset: EventSet,
    scope: Scope,
    results: Sequence[SolveResult],
    *,
    basis: Basis,
    beta: float,
    run_id: str,
    resample: YearResample,
    sample: Sample | None = None,
    pricing: Pricing | None = None,
    level: float = DEFAULT_LEVEL,
) -> KpiBootstrap:
    """KPIs with block-bootstrap confidence intervals over years.

    The point estimates are ``evaluate.kpis(...)`` with the same arguments,
    unchanged. Each KPI is recomputed on every replicate of ``resample``
    (module docstring) and its percentile interval fills ``ci_low`` and
    ``ci_high``; ``ci_level`` and ``n_bootstrap`` are set on every row.

    Parameters
    ----------
    eventset, scope, results, basis, beta, run_id, sample, pricing
        As in :func:`~parametric_insurance_design.evaluate.kpis`.
    resample : YearResample
        Replicates of the evaluation sample's years: ``resample.years`` must
        equal ``sample.years`` (all years for the full sample). Reuse one
        resample for every design compared on the sample, so that
        :func:`paired_difference` can pair them.
    level : float, default 0.9
        Confidence level of the intervals.

    Returns
    -------
    KpiBootstrap
        The table with intervals, and the replicates behind them.

    Raises
    ------
    BootstrapError
        If ``resample`` does not cover the sample's years, an outcome spans
        several years, a replicate cannot be represented on the basis, or the
        vectorised KPIs disagree with ``evaluate.kpis`` (or a KPI is unknown
        to this module).
    ComponentConfigError, EntityMismatchError, InputMismatchError, RecordSchemaError
        As ``evaluate.kpis``.
    """
    ci_level = _check_level(level)
    if not isinstance(resample, YearResample):
        raise BootstrapError(f"resample must be a YearResample, got {resample!r}")
    table = kpis(
        eventset,
        scope,
        results,
        basis=basis,
        beta=beta,
        run_id=run_id,
        sample=sample,
        pricing=pricing,
    )
    ev = _evaluate(eventset, scope, results, basis, sample)
    if not np.array_equal(resample.years, ev.sample.years):
        raise BootstrapError(
            f"the resample covers {resample.n_years} years "
            f"({resample.years[0]} .. {resample.years[-1]}), the sample "
            f"{ev.sample.name!r} {ev.sample.years.size} years; draw it from "
            "Sample.years"
        )
    level_beta = _check_beta(beta)
    measure = ev.measure
    row_years = eventset.events["year"].to_numpy(dtype=np.int64)[ev.sample.rows]
    reweighting = _Reweighting.build(measure, row_years, resample.years)

    reps: dict[tuple[str, str, str, str], NDArray[np.float64]] = {}
    point: dict[tuple[str, str, str, str], float] = {}
    uncovered: dict[tuple[str, str, str, str], NDArray[np.float64]] = {}
    ones = YearResample(
        years=resample.years,
        indices=np.arange(resample.n_years, dtype=np.int32)[None, :],
    )
    ones_prob = reweighting.probabilities(ones.counts())

    def key(subject: _Subject, kpi: KpiName) -> tuple[str, str, str, str]:
        return (subject.problem_id, subject.level.value, subject.subject_id, kpi.value)

    outcomes = [_Outcomes.of(s.loss, s.payout, measure) for s in ev.subjects]
    replicated = _replicate_subjects(outcomes, reweighting, resample, level_beta)
    for subject, o, values in zip(ev.subjects, outcomes, replicated, strict=True):
        at_point = _subject_rows(o, ones_prob, level_beta)
        for kpi, arr in values.items():
            reps[key(subject, kpi)] = arr
            point[key(subject, kpi)] = float(at_point[kpi][0])
        uncovered[key(subject, KpiName.VAR_UNCOVERED)] = o.uncovered

    if pricing is not None:
        priced: list[tuple[_Subject, NDArray[np.float64]]] = [
            (s, s.payout)
            for s in ev.subjects
            if s.level in (KpiLevel.PROBLEM, KpiLevel.PORTFOLIO)
        ]
        premium = _replicate_premiums(
            reweighting,
            resample,
            [(s.subject_id, payout) for s, payout in priced],
            pricing,
        )
        premium_point = _replicate_premiums(
            reweighting, ones, [(s.subject_id, payout) for s, payout in priced], pricing
        )
        for i, (subject, _) in enumerate(priced):
            reps[key(subject, KpiName.PREMIUM)] = premium[i]
            point[key(subject, KpiName.PREMIUM)] = float(premium_point[i, 0])

    rows = table[list(_KEY_COLUMNS)].astype(str).itertuples(index=False, name=None)
    replicates = np.empty((len(table), resample.n_bootstrap), dtype=np.float64)
    expected = table["value"].to_numpy(dtype=np.float64)
    for i, row in enumerate(rows):
        k = (row[0], row[1], row[2], row[3])
        if k not in reps:
            raise BootstrapError(
                f"the bootstrap cannot replicate KPI {k[3]!r} of subject {k[2]!r} "
                f"({k[1]}); add it to bootstrap.py"
            )
        ours, theirs = point[k], float(expected[i])
        if k in uncovered and _is_quantile_step(
            uncovered[k], ones_prob[0], level_beta, ours, theirs
        ):
            # VaR on a step of the distribution: both values are the
            # beta-quantile up to rounding (see _CDF_ATOL); keep evaluate's.
            pass
        else:
            _check_point(k, ours, theirs)
        replicates[i] = reps[k]

    low = np.empty(len(table))
    high = np.empty(len(table))
    for i in range(len(table)):
        low[i], high[i] = percentile_interval(replicates[i], ci_level)
    out = table.copy()
    out["ci_low"] = low
    out["ci_high"] = high
    out["ci_level"] = ci_level
    out["n_bootstrap"] = resample.n_bootstrap
    return KpiBootstrap(
        table=KPIS.validate(out),
        replicates=replicates,
        resample=resample,
        level=ci_level,
    )


def _is_quantile_step(
    values: NDArray[np.float64],
    prob: NDArray[np.float64],
    beta: float,
    a: float,
    b: float,
) -> bool:
    """Whether ``a`` and ``b`` are adjacent atoms split exactly at ``beta``.

    True if both are values of the distribution, no probability lies strictly
    between them, and the cumulative probability of the lower one equals
    ``beta`` within :data:`_TIE_ATOL`: then either is the ``beta``-quantile
    up to rounding in the summation.
    """
    if a == b or math.isnan(a) or math.isnan(b):
        return False
    lo, hi = min(a, b), max(a, b)
    if not (np.any(values == lo) and np.any(values == hi)):
        return False
    p = prob / prob.sum()
    between = float(p[(values > lo) & (values < hi)].sum())
    below = float(p[values <= lo].sum())
    return between <= _TIE_ATOL and abs(below - beta) <= _TIE_ATOL


def _check_point(key: tuple[str, str, str, str], ours: float, theirs: float) -> None:
    """Raise if the vectorised point value differs from ``evaluate.kpis``."""
    if math.isnan(theirs) and math.isnan(ours):
        return
    scale = max(abs(ours), abs(theirs))
    if (
        math.isnan(theirs)
        or math.isnan(ours)
        or abs(ours - theirs) > (_POINT_RTOL * scale + 1e-12)
    ):
        raise BootstrapError(
            f"bootstrap KPI {key[3]!r} of subject {key[2]!r} ({key[1]}) is "
            f"{ours!r} on the evaluation measure, evaluate.kpis gives {theirs!r}; "
            "the formulas have drifted apart"
        )


# --------------------------------------------------------------------------
# Paired differences between designs
# --------------------------------------------------------------------------


def paired_difference(
    a: KpiBootstrap, b: KpiBootstrap, *, level: float | None = None
) -> pd.DataFrame:
    """Paired bootstrap interval of ``KPI(a) - KPI(b)`` for every KPI.

    Both designs must have been bootstrapped with the **same** resample (the
    same years drawn in every replicate), so that each replicate compares
    them on the same resampled years. The interval of the difference is then
    much narrower than the two separate intervals suggest when the designs'
    KPIs move together across years.

    Parameters
    ----------
    a, b : KpiBootstrap
        The two designs on the same sample, e.g. weighted CVaR (``a``) and
        MSE (``b``) of one scope. Their KPI rows are paired on
        :data:`PAIR_KEY`, so they must describe the same subjects (the same
        scope and portfolio).
    level : float, optional
        Confidence level; default ``a.level``.

    Returns
    -------
    pandas.DataFrame
        One row per KPI: :data:`PAIR_KEY`, ``run_id_a``, ``run_id_b``,
        ``value_a``, ``value_b``, ``difference = value_a - value_b``,
        ``ci_low``, ``ci_high`` (percentile interval of the replicate
        differences; null if any replicate is undefined), ``ci_level`` and
        ``n_bootstrap``. Sorted by the key.

    Raises
    ------
    BootstrapError
        If the resamples differ, a KPI row has no partner, or ``level`` is
        not in ``(0, 1)``.
    """
    ci_level = a.level if level is None else _check_level(level)
    if not a.resample.same_as(b.resample):
        raise BootstrapError(
            "the two designs were bootstrapped with different resamples; "
            "pass the same YearResample to both bootstrap_kpis calls"
        )
    key: list[str] = list(PAIR_KEY)
    left = a.table[[*key, "run_id", "value"]].copy()
    left["_ia"] = np.arange(len(left))
    right = b.table[[*key, "run_id", "value"]].copy()
    right["_ib"] = np.arange(len(right))
    merged = left.merge(
        right,
        on=key,
        how="outer",
        suffixes=("_a", "_b"),
        indicator=True,
        validate="one_to_one",
    )
    unpaired = merged[merged["_merge"] != "both"]
    if len(unpaired):
        row = unpaired.iloc[0]
        side = "a" if row["_merge"] == "left_only" else "b"
        raise BootstrapError(
            f"{len(unpaired)} KPI rows have no partner; e.g. kpi {row['kpi']!r} "
            f"of subject {row['subject_id']!r} ({row['level']}) only in design "
            f"{side}. Compare designs with the same subjects (same scope)"
        )
    ia = merged["_ia"].to_numpy(dtype=np.int64)
    ib = merged["_ib"].to_numpy(dtype=np.int64)
    diff = a.replicates[ia] - b.replicates[ib]
    bounds = np.array([percentile_interval(d, ci_level) for d in diff]).reshape(-1, 2)
    out = pd.DataFrame(merged.loc[:, key])
    out["run_id_a"] = merged["run_id_a"].to_numpy()
    out["run_id_b"] = merged["run_id_b"].to_numpy()
    out["value_a"] = merged["value_a"].to_numpy(dtype=np.float64)
    out["value_b"] = merged["value_b"].to_numpy(dtype=np.float64)
    out["difference"] = out["value_a"] - out["value_b"]
    out["ci_low"] = bounds[:, 0]
    out["ci_high"] = bounds[:, 1]
    out["ci_level"] = ci_level
    out["n_bootstrap"] = a.resample.n_bootstrap
    return out.sort_values(key, kind="stable").reset_index(drop=True)
