r"""Export golden fixtures from the core for the CRC module's tests (MAR-245).

The parametric insurance module ``crc_sdk.parametric`` is built in a fork of
crc-sdk. It never imports this repository's core, ``parametric_insurance_design``,
but where the two overlap its results must match the core's. This script
writes the bridge: small, self-describing JSON cases, one document per case,
that the module's tests read (R-16 and R-17, later R-21). The field names
follow the parity contract of ADR 0005 §8 (draft, MAR-244); they are defined
once, in :data:`F`, so that a rename is one edit.

Outputs, relative to the repository root:

``parity/crc/cases/<case_id>.json``
    One case per file. ``parity/crc/README.md`` describes the format, how a
    reader compares against it, and every case family.

Run from the repository root::

    uv run python parity/scripts/export_crc_fixtures.py            # write
    uv run python parity/scripts/export_crc_fixtures.py --check    # diff only

``--check`` regenerates the cases in memory and compares them with the
committed files (:func:`compare_case`); it writes nothing and exits with
status 1 on a difference. ``parity/tests/test_crc_fixtures.py`` runs the same
comparison in CI. ``--summary`` prints the table of cases.

How the expected values are computed
------------------------------------
* **Design cases** (``kind = "design"``, ``source = "core"``): the core
  builds the design problem (``problem.build_problems``: a ``StepPayout``
  with ``below_attachment="zero"``, the annual basis, a ``Budget``) and
  solves it (``solve.solve``) under several solver policies.

  - LPs (expected uncovered loss, weighted CVaR): HiGHS
    (:data:`LP_VERTEX_POLICY`, a vertex) and Clarabel at tight tolerances
    (:data:`ACCURATE_POLICY`). Whether the optimum is unique is decided by
    ranging every identified amount over two near-optimal sets
    (:func:`_lp_ranges`, :class:`_Ranges`). A unique optimum is written as
    HiGHS's vertex, a non-unique one as Clarabel's interior point, one member
    of the optimal set.
  - QPs (MSE): Clarabel at tight tolerances, written, and OSQP at tight
    tolerances (:data:`QP_CHECK_POLICY`) as a check. Uniqueness follows ADR
    0005 §5.4's rule for the MSE route (:func:`_mse_unique`).
  - The objective values must agree to :data:`SOLVER_AGREEMENT_RTOL`, and the
    core's default policy, run too, to :data:`DEFAULT_AGREEMENT_RTOL`.
* **Fixed covers with a step payout** (``kind = "evaluate"``,
  ``source = "core"``): the core's ``StepPayout.evaluate`` and
  ``evaluate.kpis`` on a hand-set cover.
* **Fixed covers with a linear payout** (``kind = "evaluate"``,
  ``source = "closed_form"``): the core has no linear family, so this script
  computes every value from the closed forms of ADR 0005 §3 and §6 itself, in
  exact rational arithmetic (:func:`_exact_metrics`). Where a metric is also
  a core quantity, the core's risk measures must agree to 1e-12.

The metrics of a core case are the ones the core computes: ``evaluate.kpis``,
``evaluate.exceedance_curves`` and ``riskmeasures.var_cvar``
(:data:`CORE_METRIC_SOURCES`). The closed-form cases carry every metric of
ADR 0005 §6.

Core settings (ADR 0005 §8)
---------------------------
``below_attachment="zero"``; the annual basis; at most one event row per
year. A year without an event row is a draw with index 0 (below the first
breakpoint) and loss 0; the core sees no row for it and pools it into its
zero-loss outcome, which gives the same values. The core caps every amount at
its asset's largest loss on the design sample; the cover template states that
cap as the upper bound of every ``Free`` level, so the module solves the same
problem.

Determinism and float formatting
--------------------------------
The synthetic data come from ``numpy.random.default_rng(SYNTHETIC_SEED)``,
passed explicitly. Documents are written with sorted keys
(:func:`render`). Input values are written as stored (shortest round-trip
``repr``); computed values are rounded to :data:`SIGNIFICANT_DIGITS`
significant digits first, and amounts within ``1e-9`` of the scale of zero are
written as 0 (the module's own rule, ADR 0005 §5.3). The premium, the
metrics and the objective value are those of the written (rounded) levels. On
one machine the output is byte-identical run to run. Between platforms a
solver can return another point of a set of optimal designs, so
:func:`compare_case` compares a non-unique design by what holds for every
point of the set, not by the point itself.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Final, Literal

import cvxpy as cp
import numpy as np
import pandas as pd
from numpy.typing import NDArray

import parametric_insurance_design as pid
from parametric_insurance_design.basis import Basis
from parametric_insurance_design.evaluate import (
    evaluate_results,
    exceedance_curves,
    kpis,
)
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.interfaces import (
    Objective,
    Pricing,
    Scope,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.records import KpiLevel
from parametric_insurance_design.riskmeasures import (
    discrete_distribution,
    lower_quantile,
    sorted_cdf,
    var_cvar,
)
from parametric_insurance_design.solve import (
    DEFAULT_POLICY,
    SolverPolicy,
    is_qp,
    solve,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPT_PATH: Final[str] = "parity/scripts/export_crc_fixtures.py"
CASES_DIR: Final[Path] = REPO_ROOT / "parity" / "crc" / "cases"
THESIS_EVENTSET: Final[Path] = (
    REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
)
CORE_SOURCE: Final[str] = "packages/core/src"


# --------------------------------------------------------------------------
# The contract's names, in one place (ADR 0005 §3, §4.1, §6 and §8, draft)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Fields:
    """Every field name and fixed value of a case document.

    Renaming a field of the contract means changing it here only.
    """

    # top level (§8)
    case_id: str = "case_id"
    kind: str = "kind"
    source: str = "source"
    sample: str = "sample"
    cover: str = "cover"
    objective: str = "objective"
    pricing: str = "pricing"
    budget: str = "budget"
    limit: str = "limit"
    scope: str = "scope"
    expected: str = "expected"
    compare_parameters: str = "compare_parameters"
    tolerances: str = "tolerances"
    generator: str = "generator"
    # sample (§4.1)
    asset_ids: str = "asset_ids"
    period: str = "period"
    probability: str = "probability"
    index: str = "index"
    loss: str = "loss"
    index_unit: str = "index_unit"
    loss_unit: str = "loss_unit"
    # expected (§8)
    objective_value: str = "objective_value"
    premium: str = "premium"
    parameters: str = "parameters"
    unidentified: str = "unidentified"
    unique: str = "unique"
    metrics: str = "metrics"
    either: str = "either"
    # tolerances (§8)
    tol_metrics: str = "metrics"
    # generator (§8)
    script: str = "script"
    core_version: str = "core_version"
    commit: str = "commit"
    # objective, pricing, budget, limit (§5.1, §5.2, §8)
    kind_key: str = "kind"
    alpha: str = "alpha"
    beta: str = "beta"
    rate: str = "rate"
    q: str = "q"
    ratio: str = "ratio"
    amount: str = "amount"
    # cover document (§3)
    asset_id: str = "asset_id"
    payout: str = "payout"
    payout_unit: str = "payout_unit"
    schema_version: str = "schema_version"
    semantics_version: str = "semantics_version"
    aggregation: str = "aggregation"
    hazard_name: str = "hazard_name"
    location: str = "location"
    index_source: str = "source"
    tail: str = "tail"
    unit: str = "unit"
    breakpoints: str = "breakpoints"
    levels: str = "levels"
    monotone: str = "monotone"
    attachment: str = "attachment"
    exhaustion: str = "exhaustion"
    limit_param: str = "limit"
    free: str = "free"
    grid: str = "grid"
    lower: str = "lower"
    upper: str = "upper"
    # fixed values
    kind_design: str = "design"
    kind_evaluate: str = "evaluate"
    source_core: str = "core"
    source_closed_form: str = "closed_form"
    scope_individual: str = "individual"
    scope_joint: str = "joint"
    compare_exact: str = "exact"
    compare_within_ranges: str = "within_ranges"
    compare_none: str = "none"
    objective_mse: str = "mse"
    objective_expected_uncovered: str = "expected_uncovered"
    objective_weighted_cvar: str = "weighted_cvar"
    pricing_pure: str = "pure"
    pricing_cost_of_capital: str = "cost_of_capital"
    payout_step: str = "step"
    payout_linear: str = "linear"
    location_asset: str = "asset"
    cover_schema_version: str = "1.0"
    cover_semantics_version: str = "crc-parametric-cover/1"


F: Final[_Fields] = _Fields()
"""The field names of the case documents."""


def level_name(index: int) -> str:
    """Return the flat parameter name of a step level (ADR 0005 §3).

    Parameters
    ----------
    index : int
        Level number, from 0.

    Returns
    -------
    str
        ``"levels[<index>]"``.
    """
    return f"{F.levels}[{index}]"


def label(value: float) -> str:
    """Return the column label of a parameter value (ADR 0005 §6).

    crc-sdk's return-period column rule (``value_rp2_5``): the plain decimal
    text, trailing zeros and a trailing point removed, the point written as
    an underscore. 0.99 gives ``0_99``, 100.0 gives ``100``, 0.0 gives ``0``.

    Parameters
    ----------
    value : float
        A metric parameter (beta, return period or loss threshold).

    Returns
    -------
    str
        The label.
    """
    text = format(Decimal(str(float(value))), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text.replace(".", "_")


def metric(
    base: str,
    *,
    beta: float | None = None,
    period: float | None = None,
    threshold: float | None = None,
) -> str:
    """Return a metric column name of ADR 0005 §6.

    Parameters
    ----------
    base : str
        The metric, e.g. ``"var_uncovered"``.
    beta, period, threshold : float, optional
        At most one: the level (``_b<beta>``), the return period
        (``_rp<T>``) or the loss threshold (``_l<threshold>``).

    Returns
    -------
    str
        The column name, e.g. ``"var_uncovered_b0_9"``, ``"loss_rp100"``.
    """
    if beta is not None:
        return f"{base}_b{label(beta)}"
    if period is not None:
        return f"{base}_rp{label(period)}"
    if threshold is not None:
        return f"{base}_l{label(threshold)}"
    return base


# --------------------------------------------------------------------------
# Settings of the case matrix
# --------------------------------------------------------------------------

SYNTHETIC_SEED: Final[int] = 20261105
"""Seed of the synthetic data set (``numpy.random.default_rng``)."""

N_SYNTHETIC_YEARS: Final[int] = 150
SYNTHETIC_ASSETS: Final[tuple[str, ...]] = ("A1", "A2", "A3")
SYNTHETIC_VALUES: Final[tuple[float, ...]] = (10_000_000.0, 6_000_000.0, 3_000_000.0)
SYNTHETIC_EDGES: Final[tuple[float, ...]] = (25.0, 30.0, 36.0, 43.0, 51.0, 60.0, 70.0)

THESIS_ASSETS: Final[tuple[str, ...]] = ("A1", "A2", "A9")
"""Assets of the thesis subsample: the three of largest insured value."""
THESIS_LOSS_YEARS: Final[int] = 100
THESIS_ZERO_LOSS_EVENT_YEARS: Final[int] = 30
THESIS_EMPTY_YEARS: Final[int] = 30
THESIS_EDGES: Final[tuple[float, ...]] = (
    30.0,
    35.0,
    40.0,
    45.0,
    50.0,
    55.0,
    60.0,
    65.0,
)

BUDGET_RATIO: Final[float] = 0.8
"""Premium budget of every design case: premium <= 0.8 * E[L]."""
ALPHA: Final[float] = 0.9
"""Weight of the CVaR term of the weighted-CVaR objectives."""
DESIGN_BETAS: Final[tuple[float, ...]] = (0.9, 0.99)
COC_RATE: Final[float] = 0.06
COC_Q: Final[float] = 0.99

BETAS: Final[tuple[float, ...]] = (0.9, 0.95, 0.99)
"""Metric levels: ADR 0005 §6, ``MetricOptions`` defaults."""
RETURN_PERIODS: Final[tuple[float, ...]] = (2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0)
"""Metric return periods in years: ADR 0005 §6, ``MetricOptions`` defaults."""
LOSS_THRESHOLDS: Final[tuple[float, ...]] = (0.0,)
"""Loss thresholds of the false-negative and false-positive rates (§6)."""
PAYOUT_THRESHOLD: Final[Fraction] = Fraction(0)
"""Payout at or below which a year counts as "no payout" (§6)."""

TOLERANCE: Final[float] = 1e-6
"""Every tolerance of a case (ADR 0005 §8)."""

SIGNIFICANT_DIGITS: Final[int] = 12
"""Computed values are rounded to this many significant digits."""
ZERO_AMOUNT: Final[float] = 1e-9
"""Amounts within this fraction of the scale of zero are written as 0."""
SOLVER_AGREEMENT_RTOL: Final[float] = 1e-9
"""Relative agreement required of two accurate solvers' objective values."""
WRITTEN_RTOL: Final[float] = 1e-7
"""Agreement required of the objective at the written (snapped, rounded)
amounts with the solver's, and of the premium with the budget."""
NEAR_OPTIMAL_RTOLS: Final[tuple[float, float]] = (1e-9, 1e-11)
"""Near-optimal tolerances of the ranging LPs, times ``max(1, |optimum|)``
in scaled units: a wide one and a narrow one (:class:`_Ranges`)."""
PINNED_SHRINK: Final[float] = 0.5
"""An amount whose range at the narrow tolerance is at most this share of
its range at the wide one is pinned: the range is the tolerance's, not an
optimal set's."""
PINNED_WIDTH: Final[float] = 1e-7
"""An amount whose narrow range is below this fraction of the scale is
pinned."""
UNIQUE_WIDTH: Final[float] = 1e-6
"""Agreement, as a fraction of the scale, required of two solvers' amounts
at a unique optimum, and the padding of the ranges an interior solution
must lie in."""
HIGHS_RANGING_OPTIONS: Final[Mapping[str, float]] = {
    "primal_feasibility_tolerance": 1e-10,
    "dual_feasibility_tolerance": 1e-10,
}
"""HiGHS options of the ranging LPs (its defaults are 1e-7)."""
MSE_EIGEN_RTOL: Final[float] = 1e-10
"""ADR 0005 §5.4's rule for the MSE route: unique when the smallest
eigenvalue of H on the identified amounts exceeds this times the largest."""
SELF_CHECK_RTOL: Final[float] = 1e-12
"""Agreement required between the core and this script's own arithmetic."""
DEFAULT_AGREEMENT_RTOL: Final[float] = 1e-5
"""Agreement required of the default policy's objective value with the
accurate one. The default policy's OSQP (``eps = 1e-8``) meets a binding
budget only to about 1e-6 relative, which moves the MSE objective by up to
about 1.5e-6 relative: more than a case's tolerance, so the default policy's
solutions are only a check here, never written."""

REGEN_RTOL_SOLVED: Final[float] = 1e-6
"""Regeneration check: relative tolerance of values that come from a solve."""
REGEN_RTOL_EXACT: Final[float] = 1e-12
"""Regeneration check: relative tolerance of every other float."""

CLARABEL_TIGHT: Final[Mapping[str, float | int]] = {
    "tol_gap_abs": 1e-12,
    "tol_gap_rel": 1e-12,
    "tol_feas": 1e-12,
    "tol_ktratio": 1e-10,
    "max_iter": 500,
}
"""Clarabel's settings for the accurate policy (its defaults are 1e-8)."""
ACCURATE_POLICY: Final[SolverPolicy] = SolverPolicy(
    lp_solvers=("CLARABEL",),
    qp_solvers=("CLARABEL",),
    accept_inaccurate=False,
    solver_options={"CLARABEL": CLARABEL_TIGHT},
)
"""Clarabel at tight tolerances: the written QP solutions and non-unique LP
solutions (an interior point of the optimal set)."""
LP_VERTEX_POLICY: Final[SolverPolicy] = SolverPolicy(
    lp_solvers=("HIGHS",), qp_solvers=("CLARABEL",), accept_inaccurate=False
)
"""HiGHS for the LPs: its simplex returns a vertex, the written solution of a
unique LP optimum, and the optimum the ranging LPs start from."""
QP_CHECK_POLICY: Final[SolverPolicy] = SolverPolicy(
    lp_solvers=("OSQP",),
    qp_solvers=("OSQP",),
    accept_inaccurate=False,
    solver_options={
        "OSQP": {
            "eps_abs": 1e-12,
            "eps_rel": 1e-12,
            "max_iter": 2_000_000,
            "polishing": True,
        }
    },
)
"""OSQP at tight tolerances, to check the accurate policy's QP solutions."""

RUN_ID: Final[str] = "mar-245"


@dataclass(frozen=True)
class SolverSettings:
    """The solver policies of one generation run.

    The defaults are the ones the cases are written with. A test passes other
    settings to check that the regeneration check does not depend on which
    point of a set of optimal designs a solver returns.
    """

    accurate: SolverPolicy = ACCURATE_POLICY
    vertex: SolverPolicy = LP_VERTEX_POLICY
    qp_check: SolverPolicy = QP_CHECK_POLICY
    ranging: Mapping[str, float | int] = field(
        default_factory=lambda: dict(HIGHS_RANGING_OPTIONS)
    )


@dataclass(frozen=True)
class GeneratedCase:
    """A case document and what the regeneration check needs to judge it.

    Attributes
    ----------
    document : dict
        The case document.
    evaluate : callable, optional
        Design cases: the core's objective value, premium and metrics (the
        ``expected`` fields, written the same way) of the cover at the given
        levels, shape ``(n_assets, n_levels)``.
    violations : callable, optional
        Design cases: the design constraints the given levels break.
    ranges : tuple of numpy.ndarray, optional
        LP design cases: the wide near-optimal range of every identified
        level, ``(low, high)``, loss units; NaN for unidentified levels.
    identified : numpy.ndarray of bool, optional
        Design cases: which levels are identified, ``(n_assets, n_levels)``.
    """

    document: dict[str, Any]
    evaluate: Callable[[NDArray[np.float64]], dict[str, Any]] | None = None
    violations: Callable[[NDArray[np.float64]], list[str]] | None = None
    ranges: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None
    identified: NDArray[np.bool_] | None = None


# --------------------------------------------------------------------------
# Data sets
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Dataset:
    """Draws of one data set: one per year, with an index and a loss per asset.

    Attributes
    ----------
    name : str
        ``"synthetic"`` or ``"thesis"``; the last part of a case id.
    asset_ids : tuple of str
        The assets, in column order.
    period : numpy.ndarray
        Year label of each draw, strictly increasing, shape ``(n,)``.
    index, loss : numpy.ndarray
        Shape ``(n, n_assets)``. A year without an event has index 0 and
        loss 0 at every asset.
    event_row : numpy.ndarray of bool
        Shape ``(n,)``: whether the core sees an event row for the year.
    edges : tuple of float
        The core's ``StepPayout`` breakpoints ``b_0 < ... < b_n``.
    hazard_name, aggregation, index_unit, loss_unit : str
        The index definition of the cover document and the sample's units.
    values : tuple of float
        Insured value of each asset (for the core's EventSet only).
    licence : str
        Licence of the data the draws come from.
    """

    name: str
    asset_ids: tuple[str, ...]
    period: NDArray[np.int64]
    index: NDArray[np.float64]
    loss: NDArray[np.float64]
    event_row: NDArray[np.bool_]
    edges: tuple[float, ...]
    hazard_name: str
    aggregation: str
    index_unit: str
    loss_unit: str
    values: tuple[float, ...]
    licence: str

    @property
    def n(self) -> int:
        """Number of draws (years)."""
        return int(self.period.shape[0])

    def select(self, asset_ids: Sequence[str]) -> Dataset:
        """Return the data set restricted to some assets, in the given order.

        Years in which none of the chosen assets has an index or a loss keep
        their event row only if the data set had one.
        """
        cols = [self.asset_ids.index(a) for a in asset_ids]
        return replace(
            self,
            asset_ids=tuple(asset_ids),
            index=np.ascontiguousarray(self.index[:, cols]),
            loss=np.ascontiguousarray(self.loss[:, cols]),
            values=tuple(self.values[c] for c in cols),
        )


def synthetic_dataset(rng: np.random.Generator) -> Dataset:
    """Build the seeded synthetic data set.

    Each of the :data:`N_SYNTHETIC_YEARS` years has a storm with probability
    0.7. A storm has an intensity ``22 + Gamma(2, 7)`` m/s; the hazard at
    each asset adds ``N(0, 3)``. The loss is the asset's value times the
    Emanuel-type damage ratio ``v^3 / (1 + v^3)``, ``v = max(h - 25.7, 0) /
    49``, of the hazard ``h``; the index is the hazard plus another
    ``N(0, 3)`` (basis risk), floored at 0. Indices are rounded to 0.01 m/s
    and losses to whole USD. Three indices of A1 are then set onto
    breakpoints to exercise the bin rule: the first storm year's to the first
    breakpoint (25), the second's to an interior breakpoint (36) and the
    third's to the last module breakpoint (60). Years without a storm have
    index 0 and loss 0 and no event row.

    Parameters
    ----------
    rng : numpy.random.Generator
        Source of every draw, in this order: storm occurrence, intensity,
        hazard noise, index noise.

    Returns
    -------
    Dataset
        Assets A1, A2, A3.
    """
    n = N_SYNTHETIC_YEARS
    values = np.asarray(SYNTHETIC_VALUES)
    storm = rng.random(n) < 0.7
    intensity = 22.0 + rng.gamma(shape=2.0, scale=7.0, size=n)
    hazard = intensity[:, None] + rng.normal(0.0, 3.0, size=(n, values.size))
    noisy = hazard + rng.normal(0.0, 3.0, size=(n, values.size))
    v = np.clip((hazard - 25.7) / (74.7 - 25.7), 0.0, None)
    damage = v**3 / (1.0 + v**3)
    index = np.where(storm[:, None], np.round(np.maximum(noisy, 0.0), 2), 0.0)
    loss = np.where(storm[:, None], np.round(damage * values), 0.0)
    storm_years = np.flatnonzero(storm)
    for year, edge in zip(storm_years[:3], (25.0, 36.0, 60.0), strict=True):
        index[year, 0] = edge
    return Dataset(
        name="synthetic",
        asset_ids=SYNTHETIC_ASSETS,
        period=np.arange(n, dtype=np.int64),
        index=index + 0.0,
        loss=loss + 0.0,
        event_row=storm.copy(),
        edges=SYNTHETIC_EDGES,
        hazard_name="synthetic_wind",
        aggregation="annual_maximum",
        index_unit="m/s",
        loss_unit="USD",
        values=SYNTHETIC_VALUES,
        licence="BSD-3-Clause",
    )


def thesis_dataset(eventset: EventSet) -> Dataset:
    """Subsample the committed thesis fixture: at most one event row per year.

    From the fixture's years, in year order, take the first
    :data:`THESIS_LOSS_YEARS` years with exactly one event row and a loss
    at one of :data:`THESIS_ASSETS` at least; the first
    :data:`THESIS_ZERO_LOSS_EVENT_YEARS` years with exactly one event row and
    no loss at any of them; and the first :data:`THESIS_EMPTY_YEARS` years
    without an event row. Years with several event rows are never taken,
    because the module has one draw per year (ADR 0005 §8). Index and loss
    are the fixture's values as stored; a year without a row has index 0 and
    loss 0.

    Parameters
    ----------
    eventset : EventSet
        The thesis parity fixture, ``parity/tests/data/thesis_eventset``.

    Returns
    -------
    Dataset
        Assets A1, A2, A9; 160 years.
    """
    cols = [eventset.location_ids.index(a) for a in THESIS_ASSETS]
    years = eventset.events["year"].to_numpy(dtype=np.int64)
    if np.any(eventset.events["draw_id"].to_numpy(dtype=np.int64) != 0):
        raise ValueError("the thesis fixture must have no draws")
    unique_years, counts = np.unique(years, return_counts=True)
    single = set(unique_years[counts == 1].tolist())
    order = np.argsort(years, kind="stable")
    loss_rows: list[int] = []
    zero_rows: list[int] = []
    for row in order.tolist():
        if int(years[row]) not in single:
            continue
        if float(eventset.loss[row, cols].max()) > 0.0:
            loss_rows.append(row)
        else:
            zero_rows.append(row)
    rows = loss_rows[:THESIS_LOSS_YEARS] + zero_rows[:THESIS_ZERO_LOSS_EVENT_YEARS]
    occupied = set(unique_years.tolist())
    empty = [y for y in range(eventset.metadata.n_years) if y not in occupied][
        :THESIS_EMPTY_YEARS
    ]
    if (
        len(rows) != THESIS_LOSS_YEARS + THESIS_ZERO_LOSS_EVENT_YEARS
        or len(empty) != THESIS_EMPTY_YEARS
    ):
        raise ValueError("the thesis fixture has too few qualifying years")
    row_of_year = {int(years[r]): r for r in rows}
    period = np.array(sorted([*row_of_year, *empty]), dtype=np.int64)
    n = period.size
    index = np.zeros((n, len(cols)), dtype=np.float64)
    loss = np.zeros((n, len(cols)), dtype=np.float64)
    event_row = np.zeros(n, dtype=np.bool_)
    for k, year in enumerate(period.tolist()):
        row = row_of_year.get(year)
        if row is None:
            continue
        index[k] = eventset.index[row, cols]
        loss[k] = eventset.loss[row, cols]
        event_row[k] = True
    value_of = dict(
        zip(
            eventset.locations["location_id"].tolist(),
            eventset.locations["value"].to_numpy(dtype=np.float64).tolist(),
            strict=True,
        )
    )
    return Dataset(
        name="thesis",
        asset_ids=THESIS_ASSETS,
        period=period,
        index=index,
        loss=loss,
        event_row=event_row,
        edges=THESIS_EDGES,
        hazard_name="max_sustained_wind",
        aggregation="annual_maximum",
        index_unit=str(eventset.metadata.index.unit),
        loss_unit=str(eventset.metadata.loss.unit),
        values=tuple(float(value_of[a]) for a in THESIS_ASSETS),
        licence=str(eventset.metadata.licence),
    )


def core_eventset(data: Dataset) -> EventSet:
    """Build the core EventSet of a data set: one row per year with an event.

    Years are numbered by position (``0 .. n - 1``), ``n_years = n``, and
    every row has rate ``1 / n`` and ``draw_id`` 0, so the annual basis gives
    every year probability ``1 / n``; years without a row are the core's
    zero-loss outcome.

    Parameters
    ----------
    data : Dataset
        The draws.

    Returns
    -------
    EventSet
        Its locations are ``data.asset_ids``.
    """
    rows = np.flatnonzero(data.event_row)
    n = data.n
    events = pd.DataFrame(
        {
            "event_id": [f"{data.name}-{int(data.period[r])}" for r in rows],
            "year": rows.astype(np.int64),
            "rate": np.full(rows.size, 1.0 / n),
            "draw_id": np.zeros(rows.size, dtype=np.int64),
            "scenario_id": [data.name] * rows.size,
        }
    )
    m = len(data.asset_ids)
    locations = pd.DataFrame(
        {
            "location_id": list(data.asset_ids),
            "lat": [0.0] * m,
            "lon": [0.0] * m,
            "value": list(data.values),
            "name": list(data.asset_ids),
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name=data.name, release=f"MAR-245 {data.name} draws"),
        index=IndexDefinition(definition=data.hazard_name, unit=data.index_unit),
        loss=LossDefinition(unit=data.loss_unit, currency=data.loss_unit),
        n_years=n,
        scenario=f"MAR-245 fixture draws ({data.name}), one row per year at most",
        provenance=Provenance(
            producer=SCRIPT_PATH,
            producer_version=pid.__version__,
            created_at=datetime(2026, 11, 5, tzinfo=UTC),
        ),
        licence=data.licence,
    )
    return EventSet(events, locations, data.index[rows], data.loss[rows], metadata)


def step_payout(data: Dataset) -> pid.StepPayout:
    """Return the core payout family of a data set (nothing below attachment)."""
    edges = data.edges
    return pid.StepPayout(
        attachment=edges[0],
        limit=edges[-1],
        n_bins=len(edges) - 1,
        breakpoints=edges,
        below_attachment="zero",
    )


# --------------------------------------------------------------------------
# Payout and risk arithmetic of the module's definitions (ADR 0005 §3, §6)
# --------------------------------------------------------------------------


def step_bins(
    index: NDArray[np.float64], breakpoints: Sequence[float]
) -> NDArray[np.intp]:
    """Return the module's bin of each index value, -1 below the first breakpoint.

    ADR 0005 §3: level ``k`` for ``b_k <= x < b_{k+1}``, the last level for
    ``x >= b_{n-1}``, nothing below ``b_0`` (upper tail).
    """
    edges = np.asarray(breakpoints, dtype=np.float64)
    return (np.searchsorted(edges, index, side="right") - 1).astype(np.intp)


def step_values(
    index: NDArray[np.float64],
    breakpoints: Sequence[float],
    levels: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Return a step payout's value per draw (ADR 0005 §3, upper tail)."""
    k = step_bins(index, breakpoints)
    return np.where(k < 0, 0.0, levels[np.maximum(k, 0)])


def quantile_atoms(values: Sequence[Any], level: Fraction) -> tuple[Any, ...]:
    """Return the lower ``level``-quantile of equally likely draws, or both atoms.

    ADR 0005 §6: ``VaR_beta`` is the smallest ``x`` with ``P(X <= x) >= beta``.
    The cumulative probabilities are counted exactly (``k / n``). When the
    level falls exactly on a step of the distribution (``P(X <= x) = beta``
    for an atom ``x`` below the largest one), a floating-point sum can land
    on either side of it, so both neighbouring atoms are returned, the lower
    first (ADR 0005 §8). Otherwise the one quantile.

    Parameters
    ----------
    values : sequence of float or Fraction
        The draws, each of probability ``1 / len(values)``.
    level : fractions.Fraction
        The level in ``(0, 1)``.

    Returns
    -------
    tuple
        ``(quantile,)`` or ``(lower_atom, upper_atom)``.
    """
    ordered = sorted(values)
    n = len(ordered)
    distinct: list[Any] = []
    cumulative: list[Fraction] = []
    for k, value in enumerate(ordered, start=1):
        if distinct and value == distinct[-1]:
            cumulative[-1] = Fraction(k, n)
        else:
            distinct.append(value)
            cumulative.append(Fraction(k, n))
    for i, cum in enumerate(cumulative):
        if cum >= level:
            if cum == level and i + 1 < len(distinct):
                return (distinct[i], distinct[i + 1])
            return (distinct[i],)
    return (distinct[-1],)


def _fraction(value: float) -> Fraction:
    """Return the exact value of a decimal parameter such as 0.99."""
    return Fraction(str(value))


def _exact_var(values: Sequence[Fraction], level: Fraction) -> Fraction:
    """Lower quantile of equally likely draws, exact (the module's VaR)."""
    return quantile_atoms(values, level)[0]


def _exact_cvar(values: Sequence[Fraction], level: Fraction) -> Fraction:
    """``CVaR_beta = VaR + E[(X - VaR)^+] / (1 - beta)``, exact (§6)."""
    var = _exact_var(values, level)
    n = len(values)
    excess = sum((max(v - var, Fraction(0)) for v in values), Fraction(0)) / n
    return var + excess / (1 - level)


def _exact_tail_weights(loss: Sequence[Fraction], level: Fraction) -> list[Fraction]:
    """Return the CVaR_beta weights of the loss (§6, "Tail weights"), exact."""
    n = len(loss)
    var = _exact_var(loss, level)
    above = Fraction(sum(1 for x in loss if x > var), n)
    at = [x == var for x in loss]
    n_at = sum(at)
    remaining = 1 - level - above
    return [
        Fraction(1, n) if x > var else (remaining / n_at if a else Fraction(0))
        for x, a in zip(loss, at, strict=True)
    ]


# --------------------------------------------------------------------------
# Output values: rounding and the documents' building blocks
# --------------------------------------------------------------------------


def out(value: float) -> float:
    """Round a computed value to :data:`SIGNIFICANT_DIGITS`; ``-0.0`` -> ``0.0``.

    Raises
    ------
    ValueError
        If the value is not finite.
    """
    x = float(value)
    if not math.isfinite(x):
        raise ValueError(f"cannot write a non-finite value: {x!r}")
    rounded = float(f"{x:.{SIGNIFICANT_DIGITS}g}")
    return 0.0 if rounded == 0.0 else rounded


def _metric_value(atoms: Sequence[float]) -> float | dict[str, list[float]]:
    """Return a VaR-type metric: one value, or ``{"either": [lower, upper]}``."""
    if len(atoms) == 1:
        return out(atoms[0])
    return {F.either: [out(atoms[0]), out(atoms[1])]}


def _sample_document(data: Dataset) -> dict[str, Any]:
    """Return the sample block (ADR 0005 §4.1); ``index``, ``loss``: (n, n_assets)."""
    n = data.n
    return {
        F.asset_ids: list(data.asset_ids),
        F.period: [int(p) for p in data.period],
        F.probability: [1.0 / n] * n,
        F.index: [[float(x) + 0.0 for x in row] for row in data.index],
        F.loss: [[float(x) + 0.0 for x in row] for row in data.loss],
        F.index_unit: data.index_unit,
        F.loss_unit: data.loss_unit,
    }


def _index_document(
    hazard_name: str, aggregation: str, unit: str, tail: str
) -> dict[str, Any]:
    """Return the cover's index definition (ADR 0005 §3)."""
    return {
        F.aggregation: aggregation,
        F.hazard_name: hazard_name,
        F.location: {F.kind_key: F.location_asset},
        F.index_source: None,
        F.tail: tail,
        F.unit: unit,
    }


def _cover_document(
    asset_id: str, index: dict[str, Any], payout: dict[str, Any], payout_unit: str
) -> dict[str, Any]:
    """Return a cover document (ADR 0005 §3)."""
    return {
        F.asset_id: asset_id,
        F.index: index,
        F.payout: payout,
        F.payout_unit: payout_unit,
        F.schema_version: F.cover_schema_version,
        F.semantics_version: F.cover_semantics_version,
    }


def _free(upper: float) -> dict[str, Any]:
    """Return a ``Free`` amount marker with bounds ``[0, upper]`` (ADR 0005 §3)."""
    return {F.free: {F.grid: None, F.lower: 0.0, F.upper: float(upper)}}


def _step_cover(data: Dataset, j: int, levels: Sequence[Any]) -> dict[str, Any]:
    """Return the step cover of asset ``j``; breakpoints: the core's ``b[:-1]``."""
    payout = {
        F.breakpoints: [float(b) for b in data.edges[:-1]],
        F.kind_key: F.payout_step,
        F.levels: list(levels),
        F.monotone: True,
        F.tail: "upper",
    }
    index = _index_document(
        data.hazard_name, data.aggregation, data.index_unit, "upper"
    )
    return _cover_document(data.asset_ids[j], index, payout, data.loss_unit)


def _tolerances() -> dict[str, float]:
    return {
        F.objective_value: TOLERANCE,
        F.premium: TOLERANCE,
        F.tol_metrics: TOLERANCE,
        F.parameters: TOLERANCE,
    }


def _git(*args: str) -> str | None:
    """Run git in the repository; None if git or the history is unavailable."""
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip()


def core_commit() -> str:
    """Return the last commit that changed the core's source, ``+dirty`` if edited.

    The core's source is :data:`CORE_SOURCE`. ``"unknown"`` without git.
    """
    commit = _git("log", "-1", "--format=%H", "--", CORE_SOURCE)
    if not commit:
        return "unknown"
    status = _git("status", "--porcelain", "--", CORE_SOURCE)
    return f"{commit}+dirty" if status else commit


def _generator(commit: str) -> dict[str, str]:
    return {F.script: SCRIPT_PATH, F.core_version: pid.__version__, F.commit: commit}


# --------------------------------------------------------------------------
# Core metrics of one subject
# --------------------------------------------------------------------------

CORE_METRIC_SOURCES: Final[Mapping[str, str]] = {
    "expected_loss": "evaluate.kpis: expected_loss",
    "expected_payout": "evaluate.kpis: expected_payout",
    "premium": "evaluate.kpis: premium (pricing.premium_value)",
    "expected_uncovered": "evaluate.kpis: expected_uncovered",
    "payout_to_loss_ratio": "evaluate.kpis: payout_to_loss_ratio",
    "rmse": "evaluate.kpis: rmse_residual",
    "correlation": "evaluate.kpis: correlation",
    "var_uncovered_b<beta>": "evaluate.kpis: var_uncovered at beta",
    "cvar_uncovered_b<beta>": "evaluate.kpis: cvar_uncovered at beta",
    "var_loss_b<beta>, cvar_loss_b<beta>": "riskmeasures.var_cvar of the loss",
    "var_net_loss_b<beta>, cvar_net_loss_b<beta>": (
        "riskmeasures.var_cvar of loss - payout + premium"
    ),
    "loss_rp<T>, payout_rp<T>, uncovered_rp<T>": (
        "evaluate.exceedance_curves, curve aep"
    ),
    "net_loss_rp<T>": "riskmeasures.lower_quantile of loss - payout + premium",
}
"""Where each metric of a core case comes from (README, "Metrics")."""


@dataclass(frozen=True)
class _Draws:
    """Per-draw loss and payout of one subject, in the fixture's own layout."""

    loss: NDArray[np.float64]
    payout: NDArray[np.float64]


def _check_close(name: str, core: float, own: float, scale: float) -> None:
    """Raise if the core and this script's arithmetic disagree."""
    if not math.isclose(
        core, own, rel_tol=SELF_CHECK_RTOL, abs_tol=SELF_CHECK_RTOL * scale
    ):
        raise AssertionError(f"{name}: core {core!r}, recomputed {own!r}")


def _check_atom(name: str, core: float, atoms: Sequence[float], scale: float) -> None:
    """Raise unless the core's quantile is one of the expected atoms."""
    if not any(
        math.isclose(core, a, rel_tol=SELF_CHECK_RTOL, abs_tol=SELF_CHECK_RTOL * scale)
        for a in atoms
    ):
        raise AssertionError(f"{name}: core {core!r} is none of {list(atoms)!r}")


def core_metrics(
    eventset: EventSet,
    scope: Scope,
    results: Sequence[SolveResult],
    pricing: Pricing,
    draws: _Draws,
) -> dict[str, Any]:
    """Compute the metrics of a run's problem-level subject with the core.

    The subject is the design problem: the asset in the individual scope, the
    sum over the assets in the joint (portfolio) scope. Every value comes
    from the core (:data:`CORE_METRIC_SOURCES`). This script recomputes the
    plain ones and the quantile atoms from ``draws`` (the fixture's layout:
    every year a draw, years without a row included) and requires agreement,
    so the fixture's draws and the core's outcomes are known to match.

    Parameters
    ----------
    eventset : EventSet
        The core's data.
    scope : Scope
        The scope of the results.
    results : sequence of SolveResult
        One result (one design problem).
    pricing : Pricing
        The pricing of the premium.
    draws : _Draws
        Loss and payout of the subject per draw.

    Returns
    -------
    dict
        Column name -> value; ``None`` for an undefined value;
        ``{"either": [lower, upper]}`` for a quantile on a step.
    """
    if len(results) != 1:
        raise ValueError("one design problem per case")
    problem_id = results[0].problem_id
    loss, payout = draws.loss, draws.payout
    scale = max(1.0, float(loss.max(initial=0.0)))
    uncovered = np.maximum(loss - payout, 0.0)
    n = loss.size
    out_metrics: dict[str, Any] = {}

    def kpi_row(table: pd.DataFrame, name: str) -> float | None:
        rows = table[
            (table["level"] == KpiLevel.PROBLEM.value)
            & (table["subject_id"] == problem_id)
            & (table["kpi"] == name)
        ]
        if len(rows) != 1:
            raise AssertionError(f"expected one {name} row, got {len(rows)}")
        value = float(np.asarray(rows["value"], dtype=np.float64)[0])
        return None if math.isnan(value) else value

    premium: float | None = None
    for i, beta in enumerate(BETAS):
        table = kpis(
            eventset,
            scope,
            results,
            basis=Basis.ANNUAL,
            beta=beta,
            run_id=RUN_ID,
            pricing=pricing,
        )
        if i == 0:
            plain = {
                "expected_loss": float(np.mean(loss)),
                "expected_payout": float(np.mean(payout)),
                "expected_uncovered": float(np.mean(uncovered)),
                "rmse": math.sqrt(float(np.mean((loss - payout) ** 2))),
            }
            for name, kpi in (
                ("expected_loss", "expected_loss"),
                ("expected_payout", "expected_payout"),
                ("premium", "premium"),
                ("expected_uncovered", "expected_uncovered"),
                ("payout_to_loss_ratio", "payout_to_loss_ratio"),
                ("rmse", "rmse_residual"),
                ("correlation", "correlation"),
            ):
                value = kpi_row(table, kpi)
                if name in plain:
                    if value is None:
                        raise AssertionError(f"{name} is undefined")
                    _check_close(name, value, plain[name], scale)
                out_metrics[metric(name)] = None if value is None else out(value)
            premium = kpi_row(table, "premium")
        var = kpi_row(table, "var_uncovered")
        cvar = kpi_row(table, "cvar_uncovered")
        if var is None or cvar is None:
            raise AssertionError("VaR and CVaR are always defined")
        atoms = quantile_atoms(uncovered.tolist(), _fraction(beta))
        _check_atom(f"var_uncovered at {beta}", var, atoms, scale)
        out_metrics[metric("var_uncovered", beta=beta)] = _metric_value(atoms)
        out_metrics[metric("cvar_uncovered", beta=beta)] = out(cvar)
    if premium is None:
        raise AssertionError("the premium is always defined")

    ev = evaluate_results(eventset, scope, results, basis=Basis.ANNUAL)
    subject = next(s for s in ev.subjects if s.level is KpiLevel.PROBLEM)
    measure = ev.measure
    loss_o = measure.aggregate(subject.loss)
    payout_o = measure.aggregate(subject.payout)
    net_o = loss_o - payout_o + premium
    net = loss - payout + premium
    for base, outcome, per_draw in (
        ("loss", loss_o, loss),
        ("net_loss", net_o, net),
    ):
        for beta in BETAS:
            var, cvar = var_cvar(outcome, measure.probability, beta)
            atoms = quantile_atoms(per_draw.tolist(), _fraction(beta))
            _check_atom(f"var_{base} at {beta}", var, atoms, scale)
            out_metrics[metric(f"var_{base}", beta=beta)] = _metric_value(atoms)
            out_metrics[metric(f"cvar_{base}", beta=beta)] = out(cvar)

    curves = exceedance_curves(
        eventset,
        scope,
        results,
        basis=Basis.ANNUAL,
        run_id=RUN_ID,
        return_periods=RETURN_PERIODS,
    )
    curves = curves[
        (curves["level"] == KpiLevel.PROBLEM.value)
        & (curves["subject_id"] == problem_id)
        & (curves["curve"] == "aep")
    ]
    x_net, p_net = discrete_distribution(net_o, measure.probability)
    sorted_net, _, cdf_net = sorted_cdf(x_net, p_net)
    for period in RETURN_PERIODS:
        level = Fraction(int(period) - 1, int(period))
        for base, quantity, per_draw in (
            ("loss", "loss", loss),
            ("payout", "payout", payout),
            ("uncovered", "uncovered", uncovered),
        ):
            rows = curves[
                (curves["quantity"] == quantity) & (curves["return_period"] == period)
            ]
            if len(rows) != 1:
                raise AssertionError(f"expected one {quantity} curve value at {period}")
            core_value = float(np.asarray(rows["value"], dtype=np.float64)[0])
            atoms = quantile_atoms(per_draw.tolist(), level)
            _check_atom(f"{base}_rp{period}", core_value, atoms, scale)
            out_metrics[metric(base, period=period)] = _metric_value(atoms)
        core_net = lower_quantile(sorted_net, cdf_net, 1.0 - 1.0 / period)
        atoms = quantile_atoms(net.tolist(), level)
        _check_atom(f"net_loss_rp{period}", core_net, atoms, scale)
        out_metrics[metric("net_loss", period=period)] = _metric_value(atoms)
    if n != eventset.metadata.n_years:
        raise AssertionError("every year must be a draw")
    return out_metrics


# --------------------------------------------------------------------------
# Design cases
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ObjectiveSpec:
    """One objective of the case matrix: its id token, core object, document."""

    token: str
    core: Objective
    document: Mapping[str, Any]


@dataclass(frozen=True)
class PricingSpec:
    """One pricing of the case matrix: its id token, core object, document."""

    token: str
    core: Pricing
    document: Mapping[str, Any]


def objectives() -> tuple[ObjectiveSpec, ...]:
    """MSE, expected uncovered loss, weighted CVaR at beta 0.9 and 0.99."""
    out_specs = [
        ObjectiveSpec("mse", pid.MSE(), {F.kind_key: F.objective_mse}),
        ObjectiveSpec(
            "eu", pid.ExpectedUncovered(), {F.kind_key: F.objective_expected_uncovered}
        ),
    ]
    for beta in DESIGN_BETAS:
        out_specs.append(
            ObjectiveSpec(
                f"wcvar-b{label(beta)}",
                pid.WeightedCVaR(alpha=ALPHA, beta=beta),
                {F.kind_key: F.objective_weighted_cvar, F.alpha: ALPHA, F.beta: beta},
            )
        )
    return tuple(out_specs)


def pricings() -> tuple[PricingSpec, ...]:
    """Return the pure premium and the cost-of-capital load (rate 0.06, q 0.99)."""
    return (
        PricingSpec("pure", pid.PurePremium(), {F.kind_key: F.pricing_pure}),
        PricingSpec(
            "coc",
            pid.CostOfCapitalLoad(rate=COC_RATE, q=COC_Q),
            {F.kind_key: F.pricing_cost_of_capital, F.rate: COC_RATE, F.q: COC_Q},
        ),
    )


def _objective_value(
    objective: Objective, loss: NDArray[np.float64], payout: NDArray[np.float64]
) -> float:
    """Return the objective at a payout, over equally likely draws (§5.1)."""
    p = np.full(loss.size, 1.0 / loss.size)
    uncovered = np.maximum(loss - payout, 0.0)
    if isinstance(objective, pid.MSE):
        return float(p @ (loss - payout) ** 2)
    if isinstance(objective, pid.ExpectedUncovered):
        return float(p @ uncovered)
    if isinstance(objective, pid.WeightedCVaR):
        _, cvar = var_cvar(uncovered, p, objective.beta)
        return objective.alpha * cvar + (1.0 - objective.alpha) * float(p @ uncovered)
    raise TypeError(f"no objective formula for {objective!r}")


def _identified(data: Dataset) -> NDArray[np.bool_]:
    """Whether each (asset, level) has a design draw in its bin, ``(m, n_bins)``."""
    breakpoints = data.edges[:-1]
    n_bins = len(breakpoints)
    out_mask = np.zeros((len(data.asset_ids), n_bins), dtype=np.bool_)
    for j in range(len(data.asset_ids)):
        k = step_bins(data.index[:, j], breakpoints)
        out_mask[j, np.unique(k[k >= 0])] = True
    return out_mask


@dataclass(frozen=True)
class _Ranges:
    """Ranges of the identified amounts over two near-optimal sets, scaled units.

    ``low`` and ``high`` are taken at the wide tolerance of
    :data:`NEAR_OPTIMAL_RTOLS`, ``narrow`` (a width) at the narrow one; NaN
    for unidentified amounts.
    """

    low: NDArray[np.float64]
    high: NDArray[np.float64]
    narrow: NDArray[np.float64]

    def unique(self, identified: NDArray[np.bool_]) -> bool:
        """Whether every identified amount is pinned to a point.

        An amount is pinned when its range shrinks with the tolerance (the
        narrow width is at most :data:`PINNED_SHRINK` of the wide one), as at a
        unique vertex, where the width is the tolerance over the objective's
        slope; or when its narrow width is below :data:`PINNED_WIDTH`. On a
        set of optimal designs the width stays the set's own width.
        """
        wide = (self.high - self.low)[identified]
        narrow = self.narrow[identified]
        pinned = (narrow <= PINNED_SHRINK * wide) | (narrow <= PINNED_WIDTH)
        return bool(np.all(pinned))


def _lp_ranges(
    built: BuiltProblem,
    identified: NDArray[np.bool_],
    options: Mapping[str, float | int],
) -> _Ranges:
    """Range every identified amount over two near-optimal sets, scaled units.

    Call right after the problem was solved with :data:`LP_VERTEX_POLICY`.
    For each tolerance ``rtol`` of :data:`NEAR_OPTIMAL_RTOLS` and each
    identified amount, the smallest and largest value over ``{feasible theta :
    objective <= optimum + rtol * max(1, |optimum|)}``, solved with HiGHS at
    ``options`` (:data:`HIGHS_RANGING_OPTIONS` by default).

    Raises
    ------
    RuntimeError
        If a ranging LP is not solved to optimality.
    """
    theta = built.context.theta
    expression = built.objective.expression
    optimum = float(np.asarray(expression.value))
    weights = cp.Parameter(theta.shape)
    found: list[tuple[NDArray[np.float64], NDArray[np.float64]]] = []
    for rtol in NEAR_OPTIMAL_RTOLS:
        tol = rtol * max(1.0, abs(optimum))
        problem = cp.Problem(
            cp.Minimize(cp.sum(cp.multiply(weights, theta))),
            [*built.problem.constraints, expression <= optimum + tol],
        )
        low = np.full(theta.shape, np.nan)
        high = np.full(theta.shape, np.nan)
        for j, k in zip(*np.nonzero(identified), strict=True):
            for sign, target in ((1.0, low), (-1.0, high)):
                w = np.zeros(theta.shape)
                w[j, k] = sign
                weights.value = w
                problem.solve(solver="HIGHS", **options)
                if problem.status != cp.OPTIMAL or theta.value is None:
                    raise RuntimeError(f"ranging LP at rtol {rtol}: {problem.status}")
                target[j, k] = float(np.asarray(theta.value)[j, k])
        found.append((low, high))
    (low, high), (narrow_low, narrow_high) = found
    return _Ranges(low=low, high=high, narrow=narrow_high - narrow_low)


def _mse_unique(data: Dataset, identified: NDArray[np.bool_]) -> bool:
    """Apply ADR 0005 §5.4's MSE rule: H = B' diag(p) B positive definite.

    H is taken over the identified amounts only.
    """
    breakpoints = data.edges[:-1]
    n_bins = len(breakpoints)
    columns = []
    for j in range(len(data.asset_ids)):
        k = step_bins(data.index[:, j], breakpoints)
        for b in range(n_bins):
            if identified[j, b]:
                columns.append((k == b).astype(np.float64))
    basis = np.column_stack(columns)
    hessian = basis.T @ basis / data.n
    eigen = np.linalg.eigvalsh(hessian)
    return bool(eigen.min() > MSE_EIGEN_RTOL * eigen.max())


def _snap(theta: NDArray[np.float64], scale: float) -> NDArray[np.float64]:
    """Write amounts within :data:`ZERO_AMOUNT` of the scale of zero as 0."""
    return np.where(np.abs(theta) <= ZERO_AMOUNT * scale, 0.0, theta) + 0.0


def _rel_close(a: float, b: float, rtol: float) -> bool:
    return math.isclose(a, b, rel_tol=rtol, abs_tol=0.0) or a == b


def design_case(
    data: Dataset,
    scope_name: str,
    objective: ObjectiveSpec,
    pricing: PricingSpec,
    commit: str,
    settings: SolverSettings,
) -> GeneratedCase:
    """Build one design case: the core designs a step cover on ``data``.

    Parameters
    ----------
    data : Dataset
        The draws, restricted to the case's assets (one for the individual
        scope, several for the joint scope).
    scope_name : {"individual", "joint"}
        ``Individual()`` or ``Portfolio()`` in the core.
    objective, pricing : ObjectiveSpec, PricingSpec
        The case's objective and pricing.
    commit : str
        The generator block's commit.
    settings : SolverSettings
        The solver policies.

    Returns
    -------
    GeneratedCase
        The case document, with what the regeneration check needs: the core's
        evaluation of any levels, the constraints they break, and the ranges.
    """
    joint = scope_name == F.scope_joint
    if joint == (len(data.asset_ids) == 1):
        raise ValueError("individual cases have one asset, joint cases several")
    eventset = core_eventset(data)
    payout = step_payout(data)
    scope: Scope = pid.Portfolio() if joint else pid.Individual()
    constraints = (pid.Budget(BUDGET_RATIO),)

    def build() -> BuiltProblem:
        (built,) = build_problems(
            eventset,
            scope,
            payout,
            objective.core,
            pricing.core,
            constraints,
            basis=Basis.ANNUAL,
        )
        return built

    first = build()
    qp = is_qp(first.problem)
    identified = _identified(data)
    for j in range(len(data.asset_ids)):
        core_columns = payout.basis_matrix(eventset.index[:, j]).sum(axis=0) > 0
        if not np.array_equal(core_columns, identified[j]):
            raise AssertionError("the core's bins and the module's bin rule differ")
    where = f"{data.name}/{scope_name}/{objective.token}/{pricing.token}"
    ranges: _Ranges | None = None
    if qp:
        accurate = solve(first, settings.accurate)
        check = solve(build(), settings.qp_check)
        unique = _mse_unique(data, identified)
        chosen = accurate
    else:
        check = solve(first, settings.vertex)
        ranges = _lp_ranges(first, identified, settings.ranging)
        accurate = solve(build(), settings.accurate)
        unique = ranges.unique(identified)
        interior = accurate.theta[identified] / accurate.scale
        inside = (interior >= ranges.low[identified] - UNIQUE_WIDTH) & (
            interior <= ranges.high[identified] + UNIQUE_WIDTH
        )
        if not np.all(inside):
            raise AssertionError(f"{where}: Clarabel's solution is outside the ranges")
        chosen = check if unique else accurate
    default = solve(build(), DEFAULT_POLICY)
    for other, rtol in (
        (check, SOLVER_AGREEMENT_RTOL),
        (default, DEFAULT_AGREEMENT_RTOL),
    ):
        if not _rel_close(accurate.objective_value, other.objective_value, rtol):
            raise AssertionError(
                f"{where}: solvers disagree: {accurate.objective_value!r} "
                f"({accurate.solver}) vs {other.objective_value!r} ({other.solver})"
            )
    scale = chosen.scale
    if unique:
        gap = np.abs(accurate.theta - check.theta)[identified]
        if np.any(gap > UNIQUE_WIDTH * scale):
            raise AssertionError(f"{where}: unique, but the solvers' amounts differ")
    theta = np.vectorize(out)(_snap(chosen.theta, scale)).astype(np.float64)
    loss_draws = data.loss.sum(axis=1)
    caps = data.loss.max(axis=0)
    budget = BUDGET_RATIO * float(np.mean(loss_draws))

    def evaluate(levels: NDArray[np.float64]) -> dict[str, Any]:
        """Return the objective, premium and metrics of the cover at ``levels``."""
        payout_draws = np.zeros(data.n)
        for j in range(len(data.asset_ids)):
            payout_draws = payout_draws + step_values(
                data.index[:, j], data.edges[:-1], levels[j]
            )
        metrics = core_metrics(
            eventset,
            scope,
            (replace(chosen, theta=levels),),
            pricing.core,
            _Draws(loss_draws, payout_draws),
        )
        value = _objective_value(objective.core, loss_draws, payout_draws)
        return {
            F.objective_value: out(value),
            F.premium: metrics[metric("premium")],
            F.metrics: metrics,
        }

    def violations(levels: NDArray[np.float64]) -> list[str]:
        """Return the design constraints that ``levels`` break (ADR 0005 §5.2)."""
        tol = ZERO_AMOUNT * scale
        found = []
        if levels.min() < -tol:
            found.append(f"a level is negative: {levels.min()!r}")
        if levels.shape[1] > 1 and np.diff(levels, axis=1).min() < -tol:
            found.append("the levels are not monotone")
        if np.any(levels > caps[:, None] + tol):
            found.append("a level is above its asset's cap")
        premium = evaluate(levels)[F.premium]
        if premium > budget * (1.0 + WRITTEN_RTOL):
            found.append(f"premium {premium!r} above the budget {budget!r}")
        return found

    evaluation = evaluate(theta)
    if not _rel_close(
        evaluation[F.objective_value], chosen.objective_value, WRITTEN_RTOL
    ):
        raise AssertionError(
            f"{where}: objective at the written amounts "
            f"{evaluation[F.objective_value]!r}, solver {chosen.objective_value!r}"
        )
    broken = violations(theta)
    if broken:
        raise AssertionError(f"{where}: the written amounts break {broken}")

    covers = [
        _step_cover(data, j, [_free(caps[j])] * theta.shape[1])
        for j in range(len(data.asset_ids))
    ]
    parameters = [
        {level_name(k): out(theta[j, k]) for k in range(theta.shape[1])}
        for j in range(len(data.asset_ids))
    ]
    unidentified = [
        [level_name(k) for k in range(theta.shape[1]) if not identified[j, k]]
        for j in range(len(data.asset_ids))
    ]
    compare = (
        F.compare_exact
        if unique
        else (F.compare_none if qp else F.compare_within_ranges)
    )
    if joint:
        cover_doc: Any = covers
        parameters_doc: Any = dict(zip(data.asset_ids, parameters, strict=True))
        unidentified_doc: Any = dict(zip(data.asset_ids, unidentified, strict=True))
    else:
        cover_doc, parameters_doc, unidentified_doc = (
            covers[0],
            parameters[0],
            unidentified[0],
        )
    case_id = f"step-{objective.token}-{pricing.token}-{scope_name}-{data.name}"
    document = {
        F.case_id: case_id,
        F.kind: F.kind_design,
        F.source: F.source_core,
        F.sample: _sample_document(data),
        F.cover: cover_doc,
        F.objective: dict(objective.document),
        F.pricing: dict(pricing.document),
        F.budget: {F.ratio: BUDGET_RATIO},
        F.limit: None,
        F.scope: scope_name,
        F.expected: {
            F.objective_value: evaluation[F.objective_value],
            F.premium: evaluation[F.premium],
            F.parameters: parameters_doc,
            F.unidentified: unidentified_doc,
            F.unique: unique,
            F.metrics: evaluation[F.metrics],
        },
        F.compare_parameters: compare,
        F.tolerances: _tolerances(),
        F.generator: _generator(commit),
    }
    wide = None if ranges is None else (ranges.low * scale, ranges.high * scale)
    return GeneratedCase(
        document=document,
        evaluate=evaluate,
        violations=violations,
        ranges=wide,
        identified=identified,
    )


# --------------------------------------------------------------------------
# Fixed covers: step (core) and linear (closed form)
# --------------------------------------------------------------------------

FIXED_LEVELS: Final[Mapping[str, tuple[float, ...]]] = {
    "synthetic": (
        100_000.0,
        300_000.0,
        700_000.0,
        1_500_000.0,
        3_000_000.0,
        4_500_000.0,
    ),
    "thesis": (
        250_000.0,
        1_000_000.0,
        2_000_000.0,
        3_500_000.0,
        5_000_000.0,
        7_500_000.0,
        10_000_000.0,
    ),
}
"""Hand-set levels of the fixed step covers (asset A1)."""


def fixed_step_case(data: Dataset, pricing: PricingSpec, commit: str) -> dict[str, Any]:
    """Build an evaluation case: the core evaluates a fixed step cover on ``data``."""
    if len(data.asset_ids) != 1:
        raise ValueError("fixed covers are on one asset")
    eventset = core_eventset(data)
    payout = step_payout(data)
    scope = pid.Individual()
    (spec,) = scope.partition(eventset)
    levels = np.asarray(FIXED_LEVELS[data.name], dtype=np.float64)
    result = SolveResult(
        spec=spec,
        payout_structure=payout,
        theta=levels[None, :],
        status=SolveStatus.OPTIMAL,
        objective_value=math.nan,
        premium=math.nan,
        scale=1.0,
        solver="none (a fixed cover)",
        attempts=(),
        build_seconds=0.0,
        solve_seconds=0.0,
    )
    loss = data.loss[:, 0]
    payout_draws = step_values(data.index[:, 0], data.edges[:-1], levels)
    metrics = core_metrics(
        eventset, scope, (result,), pricing.core, _Draws(loss, payout_draws)
    )
    cover = _step_cover(data, 0, [float(v) for v in levels])
    return {
        F.case_id: f"step-fixed-{pricing.token}-{F.scope_individual}-{data.name}",
        F.kind: F.kind_evaluate,
        F.source: F.source_core,
        F.sample: _sample_document(data),
        F.cover: cover,
        F.objective: None,
        F.pricing: dict(pricing.document),
        F.budget: None,
        F.limit: None,
        F.scope: F.scope_individual,
        F.expected: {
            F.objective_value: None,
            F.premium: metrics[metric("premium")],
            F.parameters: None,
            F.unidentified: None,
            F.unique: None,
            F.metrics: metrics,
        },
        F.compare_parameters: F.compare_none,
        F.tolerances: _tolerances(),
        F.generator: _generator(commit),
    }


@dataclass(frozen=True)
class LinearCase:
    """A hand-made sample and a fixed linear cover (ADR 0005 §3)."""

    name: str
    tail: Literal["upper", "lower"]
    hazard_name: str
    aggregation: str
    index_unit: str
    loss_unit: str
    period: tuple[int, ...]
    index: tuple[float, ...]
    loss: tuple[float, ...]
    attachment: float
    exhaustion: float
    limit: float


LINEAR_CASES: Final[tuple[LinearCase, ...]] = (
    LinearCase(
        name="upper",
        tail="upper",
        hazard_name="rx1day",
        aggregation="annual_maximum",
        index_unit="mm/day",
        loss_unit="EUR",
        period=tuple(range(2001, 2021)),
        index=(
            64.0,
            12.0,
            150.0,
            88.0,
            35.0,
            50.0,
            110.0,
            48.0,
            75.0,
            160.0,
            55.0,
            130.0,
            95.0,
            210.0,
            60.0,
            70.0,
            120.0,
            80.0,
            175.0,
            100.0,
        ),
        loss=(
            0.0,
            0.0,
            1000.0,
            300.0,
            0.0,
            40.0,
            450.0,
            0.0,
            150.0,
            900.0,
            0.0,
            650.0,
            400.0,
            1800.0,
            120.0,
            200.0,
            700.0,
            260.0,
            1400.0,
            500.0,
        ),
        attachment=50.0,
        exhaustion=150.0,
        limit=1000.0,
    ),
    LinearCase(
        name="lower",
        tail="lower",
        hazard_name="spei3",
        aggregation="annual_minimum",
        index_unit="1",
        loss_unit="EUR",
        period=tuple(range(2001, 2021)),
        index=(
            0.5,
            -1.25,
            -2.0,
            0.25,
            -0.5,
            -3.5,
            -1.0,
            -1.5,
            1.0,
            -2.75,
            -0.75,
            -3.0,
            0.0,
            -1.75,
            -2.25,
            0.75,
            -0.25,
            -4.0,
            -1.5,
            -2.5,
        ),
        loss=(
            0.0,
            50.0,
            300.0,
            0.0,
            0.0,
            900.0,
            0.0,
            150.0,
            0.0,
            700.0,
            20.0,
            800.0,
            0.0,
            250.0,
            450.0,
            0.0,
            0.0,
            1100.0,
            100.0,
            500.0,
        ),
        attachment=-1.0,
        exhaustion=-3.0,
        limit=800.0,
    ),
)
"""The closed-form cases' samples and covers (20 years each)."""

CLOSED_FORM_PRICINGS: Final[Mapping[str, tuple[Fraction, Fraction] | None]] = {
    "pure": None,
    "coc": (Fraction("0.1"), Fraction("0.9")),
}
"""Pricing of the closed-form cases: pure, and a load of rate 0.1 at q 0.9."""


def _linear_payout(case: LinearCase, x: Fraction) -> Fraction:
    """``limit * clip((s - a) / (e - a), 0, 1)`` on the severity ``s`` (§3)."""
    sign = 1 if case.tail == "upper" else -1
    s, a, e = (
        sign * x,
        sign * _fraction(case.attachment),
        sign * _fraction(case.exhaustion),
    )
    share = min(max((s - a) / (e - a), Fraction(0)), Fraction(1))
    return _fraction(case.limit) * share


def _exact_metrics(
    loss: Sequence[Fraction],
    payout: Sequence[Fraction],
    coc: tuple[Fraction, Fraction] | None,
) -> dict[str, Any]:
    """Every metric of ADR 0005 §6, exact, over equally likely draws.

    The premium is priced on the sample: ``E[pi]``, or ``(1 - r) E[pi] + r
    CVaR_q(pi)`` with ``coc = (r, q)``.
    """
    n = len(loss)
    zero = Fraction(0)

    def mean(xs: Iterable[Fraction]) -> Fraction:
        return sum(xs, zero) / n

    uncovered = [max(lo - pi, zero) for lo, pi in zip(loss, payout, strict=True)]
    residual = [lo - pi for lo, pi in zip(loss, payout, strict=True)]
    e_loss, e_payout, e_unc = mean(loss), mean(payout), mean(uncovered)
    if coc is None:
        premium = e_payout
    else:
        rate, q = coc
        premium = (1 - rate) * e_payout + rate * _exact_cvar(payout, q)
    net = [r + premium for r in residual]
    m: dict[str, Any] = {
        metric("expected_loss"): e_loss,
        metric("expected_payout"): e_payout,
        metric("premium"): premium,
        metric("expected_uncovered"): e_unc,
        metric("coverage_ratio"): None if e_loss == 0 else 1 - e_unc / e_loss,
        metric("payout_to_loss_ratio"): None if e_loss == 0 else e_payout / e_loss,
    }
    for beta in BETAS:
        level = _fraction(beta)
        weights = _exact_tail_weights(loss, level)
        denominator = sum((w * lo for w, lo in zip(weights, loss, strict=True)), zero)
        covered = sum(
            (w * min(pi, lo) for w, pi, lo in zip(weights, payout, loss, strict=True)),
            zero,
        )
        m[metric("tail_coverage", beta=beta)] = (
            None if denominator == 0 else covered / denominator
        )
        cvar_loss = _exact_cvar(loss, level)
        m[metric("cvar_uncovered_to_loss", beta=beta)] = (
            None if cvar_loss == 0 else _exact_cvar(uncovered, level) / cvar_loss
        )
    for threshold in LOSS_THRESHOLDS:
        ell = _fraction(threshold)
        big = [lo > ell for lo in loss]
        paid = [pi > PAYOUT_THRESHOLD for pi in payout]
        n_big = sum(big)
        m[metric("false_negative_rate", threshold=threshold)] = (
            None
            if n_big == 0
            else Fraction(
                sum(b and not p for b, p in zip(big, paid, strict=True)), n_big
            )
        )
        m[metric("false_positive_rate", threshold=threshold)] = (
            None
            if n_big == n
            else Fraction(
                sum(p and not b for b, p in zip(big, paid, strict=True)), n - n_big
            )
        )
    m[metric("rmse")] = math.sqrt(mean(r * r for r in residual))
    cov = mean(
        (lo - e_loss) * (pi - e_payout) for lo, pi in zip(loss, payout, strict=True)
    )
    var_l = mean((lo - e_loss) ** 2 for lo in loss)
    var_p = mean((pi - e_payout) ** 2 for pi in payout)
    m[metric("correlation")] = (
        None
        if var_l == 0 or var_p == 0
        else float(cov) / math.sqrt(float(var_l * var_p))
    )
    for beta in BETAS:
        level = _fraction(beta)
        for base, values in (
            ("uncovered", uncovered),
            ("net_loss", net),
            ("loss", loss),
        ):
            m[metric(f"var_{base}", beta=beta)] = quantile_atoms(values, level)
            m[metric(f"cvar_{base}", beta=beta)] = _exact_cvar(values, level)
    for period in RETURN_PERIODS:
        level = Fraction(int(period) - 1, int(period))
        for base, values in (
            ("loss", loss),
            ("payout", payout),
            ("uncovered", uncovered),
            ("net_loss", net),
        ):
            m[metric(base, period=period)] = quantile_atoms(values, level)
    return m


def _write_exact(value: object) -> object:
    """Float form of an exact metric: atoms become one value or ``either``."""
    if value is None:
        return None
    if isinstance(value, tuple):
        return _metric_value([float(v) for v in value])
    if isinstance(value, Fraction | float | int):
        return out(float(value))
    raise TypeError(f"not a metric value: {value!r}")


def _check_closed_form_with_core(
    m: Mapping[str, Any],
    loss: NDArray[np.float64],
    payout: NDArray[np.float64],
    premium: float,
) -> None:
    """Check the core's risk measures against the exact values where they overlap."""
    p = np.full(loss.size, 1.0 / loss.size)
    scale = max(1.0, float(loss.max()))
    uncovered = np.maximum(loss - payout, 0.0)
    net = loss - payout + premium
    for beta in BETAS:
        for base, values in (
            ("uncovered", uncovered),
            ("net_loss", net),
            ("loss", loss),
        ):
            var, cvar = var_cvar(values, p, beta)
            atoms = [float(a) for a in m[metric(f"var_{base}", beta=beta)]]
            _check_atom(f"var_{base}", var, atoms, scale)
            _check_close(
                f"cvar_{base}", cvar, float(m[metric(f"cvar_{base}", beta=beta)]), scale
            )
    _check_close(
        "expected_loss", float(p @ loss), float(m[metric("expected_loss")]), scale
    )
    _check_close(
        "expected_payout", float(p @ payout), float(m[metric("expected_payout")]), scale
    )


def linear_case(case: LinearCase, pricing_token: str, commit: str) -> dict[str, Any]:
    """Build a closed-form evaluation case of a fixed linear cover."""
    coc = CLOSED_FORM_PRICINGS[pricing_token]
    x = [_fraction(v) for v in case.index]
    loss = [_fraction(v) for v in case.loss]
    payout = [_linear_payout(case, xi) for xi in x]
    exact = _exact_metrics(loss, payout, coc)
    premium = float(exact[metric("premium")])
    _check_closed_form_with_core(
        exact,
        np.asarray(case.loss, dtype=np.float64),
        np.asarray([float(v) for v in payout], dtype=np.float64),
        premium,
    )
    metrics = {name: _write_exact(value) for name, value in exact.items()}
    if coc is None:
        pricing_doc: dict[str, Any] = {F.kind_key: F.pricing_pure}
    else:
        pricing_doc = {
            F.kind_key: F.pricing_cost_of_capital,
            F.rate: float(coc[0]),
            F.q: float(coc[1]),
        }
    n = len(case.period)
    sample = {
        F.asset_ids: ["A1"],
        F.period: list(case.period),
        F.probability: [1.0 / n] * n,
        F.index: [[float(v)] for v in case.index],
        F.loss: [[float(v)] for v in case.loss],
        F.index_unit: case.index_unit,
        F.loss_unit: case.loss_unit,
    }
    payout_doc = {
        F.attachment: float(case.attachment),
        F.exhaustion: float(case.exhaustion),
        F.kind_key: F.payout_linear,
        F.limit_param: float(case.limit),
        F.tail: case.tail,
    }
    index_doc = _index_document(
        case.hazard_name, case.aggregation, case.index_unit, case.tail
    )
    return {
        F.case_id: (
            f"linear-{case.name}-fixed-{pricing_token}-{F.scope_individual}-handmade"
        ),
        F.kind: F.kind_evaluate,
        F.source: F.source_closed_form,
        F.sample: sample,
        F.cover: _cover_document("A1", index_doc, payout_doc, case.loss_unit),
        F.objective: None,
        F.pricing: pricing_doc,
        F.budget: None,
        F.limit: None,
        F.scope: F.scope_individual,
        F.expected: {
            F.objective_value: None,
            F.premium: out(premium),
            F.parameters: None,
            F.unidentified: None,
            F.unique: None,
            F.metrics: metrics,
        },
        F.compare_parameters: F.compare_none,
        F.tolerances: _tolerances(),
        F.generator: _generator(commit),
    }


# --------------------------------------------------------------------------
# All cases
# --------------------------------------------------------------------------


def datasets() -> tuple[Dataset, Dataset]:
    """Return the synthetic data set and the thesis subsample."""
    synthetic = synthetic_dataset(np.random.default_rng(SYNTHETIC_SEED))
    thesis = thesis_dataset(EventSet.from_parquet(THESIS_EVENTSET))
    return synthetic, thesis


def build_cases(
    commit: str | None = None, settings: SolverSettings | None = None
) -> dict[str, GeneratedCase]:
    """Build every case.

    Parameters
    ----------
    commit : str, optional
        The generator block's commit; default :func:`core_commit`.
    settings : SolverSettings, optional
        The solver policies; default ``SolverSettings()``, the ones the cases
        are written with.

    Returns
    -------
    dict
        File name (``<case_id>.json``) -> case, in case order.
    """
    commit = core_commit() if commit is None else commit
    settings = SolverSettings() if settings is None else settings
    cases: list[GeneratedCase] = []
    for data in datasets():
        individual = data.select(data.asset_ids[:1])
        for objective in objectives():
            for pricing in pricings():
                for scope_name, chosen in (
                    (F.scope_individual, individual),
                    (F.scope_joint, data),
                ):
                    cases.append(
                        design_case(
                            chosen, scope_name, objective, pricing, commit, settings
                        )
                    )
        for pricing in pricings():
            cases.append(GeneratedCase(fixed_step_case(individual, pricing, commit)))
    for case in LINEAR_CASES:
        tokens = ("pure", "coc") if case.tail == "upper" else ("pure",)
        for token in tokens:
            cases.append(GeneratedCase(linear_case(case, token, commit)))
    out_cases: dict[str, GeneratedCase] = {}
    for case in cases:
        name = f"{case.document[F.case_id]}.json"
        if name in out_cases:
            raise ValueError(f"case ids repeat: {name}")
        out_cases[name] = case
    return out_cases


def build_documents(commit: str | None = None) -> dict[str, dict[str, Any]]:
    """Build every case document (:func:`build_cases`, documents only).

    Parameters
    ----------
    commit : str, optional
        The generator block's commit; default :func:`core_commit`.

    Returns
    -------
    dict
        File name (``<case_id>.json``) -> document, in case order.
    """
    return {name: case.document for name, case in build_cases(commit).items()}


# --------------------------------------------------------------------------
# Rendering and comparing
# --------------------------------------------------------------------------


def _scalar(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON has no non-finite numbers")
        return repr(value + 0.0)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    raise TypeError(f"not a JSON scalar: {value!r}")


def _is_scalar(value: object) -> bool:
    return value is None or isinstance(value, bool | int | float | str)


INLINE_WIDTH: Final[int] = 72
"""Objects and arrays of objects at most this wide are written on one line."""


def _inline(value: object) -> str | None:
    """One-line form of a value; None if it holds a list of non-scalars."""
    if isinstance(value, dict):
        parts = []
        for key in sorted(value):
            text = _inline(value[key])
            if text is None:
                return None
            parts.append(f"{json.dumps(key, ensure_ascii=False)}: {text}")
        return "{" + ", ".join(parts) + "}"
    if isinstance(value, list):
        if all(_is_scalar(v) for v in value):
            return "[" + ", ".join(_scalar(v) for v in value) + "]"
        return None
    return _scalar(value)


def _render(value: object, indent: int) -> str:
    pad = "  " * (indent + 1)
    end = "  " * indent
    if isinstance(value, list) and all(_is_scalar(v) for v in value):
        return "[" + ", ".join(_scalar(v) for v in value) + "]"
    if isinstance(value, dict | list):
        short = _inline(value)
        if short is not None and len(short) <= INLINE_WIDTH:
            return short
    if isinstance(value, dict):
        if not value:
            return "{}"
        items = [
            f"{pad}{_scalar(key)}: {_render(value[key], indent + 1)}"
            for key in sorted(value)
        ]
        return "{\n" + ",\n".join(items) + "\n" + end + "}"
    if isinstance(value, list):
        rows = [pad + _render(v, indent + 1) for v in value]
        return "[\n" + ",\n".join(rows) + "\n" + end + "]"
    return _scalar(value)


def render(document: Mapping[str, Any]) -> str:
    """Render a case document as canonical JSON text.

    Keys sorted, two-space indentation; arrays of scalars on one line (so a
    sample's ``index`` and ``loss`` have one draw per line), and objects that
    fit in :data:`INLINE_WIDTH` characters too; floats as their shortest
    round-trip ``repr``; a final newline.

    Parameters
    ----------
    document : mapping
        A case document.

    Returns
    -------
    str
        The file's text.
    """
    return _render(dict(document), 0) + "\n"


UNITLESS_METRICS: Final[tuple[str, ...]] = (
    "coverage_ratio",
    "payout_to_loss_ratio",
    "correlation",
    "tail_coverage_b",
    "cvar_uncovered_to_loss_b",
    "false_negative_rate_l",
    "false_positive_rate_l",
)
"""Metrics without a unit (ratios, rates, the correlation); a name ending in
``_b``, ``_l`` is a prefix of the labelled columns. Every other metric is in
loss units."""


def metric_is_unitless(column: str) -> bool:
    """Whether a metric column has no unit (a ratio, a rate or the correlation)."""
    return any(
        column == name or (name[-2:] in ("_b", "_l") and column.startswith(name))
        for name in UNITLESS_METRICS
    )


def case_scale(case: Mapping[str, Any]) -> float:
    """Return the scale of a case: the largest loss of a draw, summed over assets.

    It is the core's (and the module's) scaling of the design problem, and
    the unit of the absolute tolerances of ``README.md``. At least 1.
    """
    return max(1.0, max(math.fsum(row) for row in case[F.sample][F.loss]))


def _floor(path: tuple[str, ...], case: Mapping[str, Any]) -> float:
    """Absolute tolerance unit of the float at ``path``: the scale, its square or 1."""
    scale = case_scale(case)
    if len(path) < 2 or path[0] != F.expected:
        return scale
    if path[1] == F.objective_value:
        objective = case.get(F.objective) or {}
        return scale**2 if objective.get(F.kind_key) == F.objective_mse else scale
    if path[1] == F.metrics and len(path) > 2 and metric_is_unitless(path[2]):
        return 1.0
    return scale


def compare_documents(
    committed: Mapping[str, Any],
    regenerated: Mapping[str, Any],
    *,
    skip: Iterable[tuple[str, ...]] = (),
    rtol: float | None = None,
) -> list[str]:
    """Compare a committed case with its regeneration; return the differences.

    Everything but floats must be equal, except ``generator.commit``, which
    names the code a file was generated from and so differs between
    checkouts. Floats must agree within :data:`REGEN_RTOL_SOLVED` (values of a
    design case's ``expected`` block, which come from a solve) or
    :data:`REGEN_RTOL_EXACT` (everything else), relative, with the same
    tolerance times the case's scale (its largest loss; its square for an MSE
    objective; 1 for unitless metrics) as an absolute floor. A quantile
    written as ``{"either": [lower, upper]}`` on one side matches a single
    value on the other if that value matches one of the two atoms.

    Parameters
    ----------
    committed, regenerated : mapping
        The two documents.
    skip : iterable of tuple of str, optional
        Paths not to compare, e.g. ``("expected", "parameters")``.
    rtol : float, optional
        One relative tolerance for every float, instead of the two above.

    Returns
    -------
    list of str
        One line per difference; empty if they agree.
    """
    problems: list[str] = []
    solved = regenerated.get(F.kind) == F.kind_design
    skipped = set(skip)

    def tol(path: tuple[str, ...]) -> float:
        if rtol is not None:
            return rtol
        in_expected = bool(path) and path[0] == F.expected
        return REGEN_RTOL_SOLVED if solved and in_expected else REGEN_RTOL_EXACT

    def close(a: float, b: float, path: tuple[str, ...]) -> bool:
        rtol = tol(path)
        return math.isclose(
            a, b, rel_tol=rtol, abs_tol=rtol * _floor(path, regenerated)
        )

    def walk(a: object, b: object, path: tuple[str, ...]) -> None:
        where = "/".join(path) or "<root>"
        if path == (F.generator, F.commit) or path in skipped:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            if set(a) == {F.either} or set(b) == {F.either}:
                atoms_a = a[F.either] if set(a) == {F.either} else None
                atoms_b = b[F.either] if set(b) == {F.either} else None
                if atoms_a is not None and atoms_b is not None:
                    walk(atoms_a, atoms_b, path)
                    return
                problems.append(f"{where}: {a!r} != {b!r}")
                return
            if set(a) != set(b):
                problems.append(f"{where}: keys {sorted(set(a) ^ set(b))} differ")
                return
            for key in sorted(a):
                walk(a[key], b[key], (*path, key))
            return
        if isinstance(a, dict) != isinstance(b, dict):
            single, either = (b, a) if isinstance(a, dict) else (a, b)
            atoms = either.get(F.either) if isinstance(either, dict) else None
            if (
                isinstance(single, float)
                and isinstance(atoms, list)
                and any(close(single, float(x), path) for x in atoms)
            ):
                return
            problems.append(f"{where}: {a!r} != {b!r}")
            return
        if isinstance(a, list) and isinstance(b, list):
            if len(a) != len(b):
                problems.append(f"{where}: lengths {len(a)} != {len(b)}")
                return
            for i, (x, y) in enumerate(zip(a, b, strict=True)):
                walk(x, y, (*path, str(i)))
            return
        if isinstance(a, float) and isinstance(b, float):
            if not close(a, b, path):
                problems.append(f"{where}: {a!r} != {b!r}")
            return
        if type(a) is not type(b) or a != b:
            problems.append(f"{where}: {a!r} != {b!r}")

    walk(dict(committed), dict(regenerated), ())
    return problems


SOLVER_POINT_FIELDS: Final[tuple[tuple[str, ...], ...]] = (
    (F.expected, F.parameters),
    (F.expected, F.premium),
    (F.expected, F.metrics),
)
"""The fields that are one solver's point of a set of optimal designs when a
design is not unique: they are judged by :func:`compare_case`, not compared."""


def levels_of(
    document: Mapping[str, Any], shape: tuple[int, int]
) -> NDArray[np.float64]:
    """Return a design case's ``expected.parameters`` as an array of levels.

    Parameters
    ----------
    document : mapping
        A design case.
    shape : tuple of int
        ``(n_assets, n_levels)``.

    Returns
    -------
    numpy.ndarray
        The levels, one row per asset in ``asset_ids`` order.
    """
    parameters = document[F.expected][F.parameters]
    if document[F.scope] == F.scope_joint:
        rows = [parameters[a] for a in document[F.sample][F.asset_ids]]
    else:
        rows = [parameters]
    levels = np.array(
        [[float(row[level_name(k)]) for k in range(shape[1])] for row in rows],
        dtype=np.float64,
    )
    if levels.shape != shape:
        raise ValueError(f"levels of shape {levels.shape}, expected {shape}")
    return levels


def _unidentified_paths(document: Mapping[str, Any]) -> list[tuple[str, ...]]:
    """Paths of a design case's unidentified levels in ``expected.parameters``.

    An unidentified level changes nothing on the sample, so any value the
    constraints allow is optimal, and a solver's choice is not compared.
    """
    unidentified = document[F.expected][F.unidentified]
    base = (F.expected, F.parameters)
    if document[F.scope] == F.scope_joint:
        return [(*base, a, name) for a, names in unidentified.items() for name in names]
    return [(*base, name) for name in unidentified]


def compare_case(committed: Mapping[str, Any], generated: GeneratedCase) -> list[str]:
    """Judge a committed case against its regeneration; return the differences.

    Evaluate cases and the inputs of every case are compared with
    :func:`compare_documents`. A design case is judged in three more ways,
    which hold whichever point of a set of optimal designs a solver returns:

    1. **The committed values are the core's at the committed levels.** The
       core evaluates ``expected.parameters`` again; the objective value, the
       premium and every metric must agree within :data:`REGEN_RTOL_EXACT`.
    2. **The committed levels are an optimal design of the regenerated
       problem.** They meet every constraint (bounds, monotonicity, cap,
       budget), and their objective value agrees with the regenerated optimum
       within :data:`REGEN_RTOL_SOLVED`.
    3. **They lie within the regenerated ranges** (LP cases), widened by
       :data:`UNIQUE_WIDTH` times the scale.

    Only a unique design (``"exact"`` on both sides) has its identified levels, premium
    and metrics also compared with the regenerated ones. A non-unique one has
    no such reference: a solver on another platform can return another point
    of the same optimal set.

    Parameters
    ----------
    committed : mapping
        The committed document.
    generated : GeneratedCase
        Its regeneration.

    Returns
    -------
    list of str
        One line per difference; empty if the case passes.
    """
    regenerated = generated.document
    if generated.evaluate is None or generated.violations is None:
        return compare_documents(committed, regenerated)
    if generated.identified is None:
        raise ValueError("a design case needs its identified levels")
    unique = (
        regenerated[F.compare_parameters] == F.compare_exact
        and committed.get(F.compare_parameters) == F.compare_exact
    )
    problems = compare_documents(
        committed,
        regenerated,
        skip=_unidentified_paths(regenerated) if unique else SOLVER_POINT_FIELDS,
    )
    try:
        levels = levels_of(committed, generated.identified.shape)
    except (KeyError, TypeError, ValueError) as exc:
        return [*problems, f"{F.expected}/{F.parameters}: unreadable ({exc!r})"]
    evaluated = generated.evaluate(levels)
    keys = (F.objective_value, F.premium, F.metrics)
    problems += compare_documents(
        {**committed, F.expected: {k: committed[F.expected].get(k) for k in keys}},
        {**regenerated, F.expected: evaluated},
        rtol=REGEN_RTOL_EXACT,
    )
    problems += [
        f"{F.expected}/{F.parameters}: {v}" for v in generated.violations(levels)
    ]
    objective = regenerated[F.objective] or {}
    scale = case_scale(regenerated)
    floor = scale**2 if objective.get(F.kind_key) == F.objective_mse else scale
    at_levels = float(evaluated[F.objective_value])
    optimum = float(regenerated[F.expected][F.objective_value])
    if not math.isclose(
        at_levels,
        optimum,
        rel_tol=REGEN_RTOL_SOLVED,
        abs_tol=REGEN_RTOL_SOLVED * floor,
    ):
        problems.append(
            f"{F.expected}/{F.parameters}: objective {at_levels!r} at the committed "
            f"levels, regenerated optimum {optimum!r}"
        )
    if generated.ranges is not None:
        low, high = generated.ranges
        pad = UNIQUE_WIDTH * scale
        outside = generated.identified & ((levels < low - pad) | (levels > high + pad))
        for j, k in zip(*np.nonzero(outside), strict=True):
            problems.append(
                f"{F.expected}/{F.parameters}: asset {j} {level_name(int(k))} = "
                f"{levels[j, k]!r} outside the range [{low[j, k]!r}, {high[j, k]!r}]"
            )
    return problems


def summary(
    documents: Mapping[str, Mapping[str, Any]], sizes: Mapping[str, int]
) -> str:
    """Return a Markdown table of the cases: kind, source, comparison, size."""
    lines = [
        "| Case | Kind | Source | Scope | Compare parameters | Unique | Size (bytes) |",
        "|---|---|---|---|---|---|---|",
    ]
    total = 0
    for name, doc in documents.items():
        size = sizes[name]
        total += size
        unique = doc[F.expected][F.unique]
        lines.append(
            f"| `{doc[F.case_id]}` | {doc[F.kind]} | {doc[F.source]} | "
            f"{doc[F.scope]} | {doc[F.compare_parameters]} | "
            f"{'—' if unique is None else str(unique).lower()} | {size:,} |"
        )
    lines.append(f"| **Total ({len(documents)} cases)** | | | | | | **{total:,}** |")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the cases, or with ``--check`` compare them with the committed ones.

    Parameters
    ----------
    argv : sequence of str, optional
        Command-line arguments (default ``sys.argv[1:]``).

    Returns
    -------
    int
        0 on success; 1 if ``--check`` finds a difference.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=CASES_DIR, help="output directory")
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    parser.add_argument("--summary", action="store_true", help="print the case table")
    args = parser.parse_args(argv)
    cases = build_cases()
    documents = {name: case.document for name, case in cases.items()}
    texts = {name: render(doc) for name, doc in documents.items()}
    out_dir: Path = args.out
    if args.check:
        committed = {p.name for p in out_dir.glob("*.json")}
        problems = [f"missing: {n}" for n in sorted(set(texts) - committed)]
        problems += [f"not generated: {n}" for n in sorted(committed - set(texts))]
        identical = 0
        for name in sorted(set(texts) & committed):
            text = (out_dir / name).read_text(encoding="utf-8")
            identical += text == texts[name]
            diffs = compare_case(json.loads(text), cases[name])
            problems += [f"{name}: {d}" for d in diffs]
        print(f"{identical} of {len(texts)} cases byte-identical")
        for line in problems:
            print(line)
        return 1 if problems else 0
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.json"):
        if stale.name not in texts:
            stale.unlink()
    for name, text in texts.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    sizes = {name: len(text.encode("utf-8")) for name, text in texts.items()}
    if args.summary:
        print(summary(documents, sizes))
    print(f"wrote {len(texts)} cases, {sum(sizes.values()):,} bytes, to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
