r"""Export golden fixtures from the core for the CRC module's tests (MAR-245, MAR-255).

The parametric insurance module ``crc_sdk.parametric`` is built in a fork of
crc-sdk. It never imports this repository's core, ``parametric_insurance_design``,
but where the two overlap its results must match the core's. This script
writes the bridge: small, self-describing JSON cases, one document per case,
that the module's tests read (R-14 to R-17, later R-21). The field names
follow the parity contract of ADR 0005 §8 (accepted 2026-11-06, MAR-244);
they are defined once, in :data:`F`, so that a rename is one edit. The
out-of-sample fields, which §8 does not define, are named after §2 and §6
(``holdout``, ``train_fraction``, ``fold``, ``premium_basis``).

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
  - Unidentified levels are written by ADR 0005 §5.4's default fill rule,
    ``"lowest"`` (:func:`_fill_lowest`).
* **Out-of-sample design cases** (``split = {"kind": "holdout", ...}``): the
  core's ``splits.holdout`` splits the draws into year blocks; the core
  designs on the first block, as above, and evaluates the design on the
  second with the design premium (ADR 0005 §6, decision 9:
  ``premium_basis = "design"``).
* **Fixed covers with a step payout** (``kind = "evaluate"``,
  ``source = "core"``): the core's ``StepPayout.evaluate`` and
  ``evaluate.kpis`` on a hand-set cover.
* **Fixed covers with a linear, binary or piecewise-linear payout**
  (``kind = "evaluate"``, ``source = "closed_form"``): the core has none of
  these families, so this script computes every value from the closed forms
  of ADR 0005 §3 and §6 itself, in exact rational arithmetic
  (:func:`_exact_metrics`), on hand-made samples and on the synthetic sample.
  Where a metric is also a core quantity, the core's risk measures must agree
  to 1e-12; a binary payout must also equal the core's one-bin step payout.

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
import itertools
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
    Sample,
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
from parametric_insurance_design.splits import holdout, year_block_kfold

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPT_PATH: Final[str] = "parity/scripts/export_crc_fixtures.py"
CASES_DIR: Final[Path] = REPO_ROOT / "parity" / "crc" / "cases"
THESIS_EVENTSET: Final[Path] = (
    REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
)
CORE_SOURCE: Final[str] = "packages/core/src"


# --------------------------------------------------------------------------
# The contract's names, in one place (ADR 0005 §3, §4.1, §6 and §8, accepted)
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
    # out of sample (beyond §8; names from §2 ``holdout``, ``year_block_kfold``
    # and the plan's ``FreshDraws(n_draws, seed=...)``, §4.4's
    # ``fresh_draws``, and §6's table)
    split: str = "split"
    evaluation_sample: str = "evaluation_sample"
    train_fraction: str = "train_fraction"
    k: str = "k"
    n_draws: str = "n_draws"
    seed: str = "seed"
    out_of_sample: str = "out_of_sample"
    fold: str = "fold"
    premium_basis: str = "premium_basis"
    # metric options (beyond §8; §6's ``MetricOptions`` and its arguments)
    metric_options: str = "metric_options"
    betas: str = "betas"
    return_periods: str = "return_periods"
    loss_thresholds: str = "loss_thresholds"
    payout_threshold: str = "payout_threshold"
    # the grid route (beyond §8; §5.3's ``DesignResult.profile``)
    profile: str = "profile"
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
    knots: str = "knots"
    trigger: str = "trigger"
    amount_param: str = "amount"
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
    # The registry keys of PiecewiseLinearPayout and BinaryPayout: ADR 0005
    # §3 names "linear" and "step" only; these follow their pattern (the
    # class name without "Payout", in snake case).
    payout_piecewise_linear: str = "piecewise_linear"
    payout_binary: str = "binary"
    location_asset: str = "asset"
    split_holdout: str = "holdout"
    split_kfold: str = "kfold"
    split_fresh_draws: str = "fresh_draws"
    premium_basis_design: str = "design"
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

TRAIN_FRACTION: Final[float] = 0.7
"""Holdout of the out-of-sample cases: the first 70 % of the years design."""
HOLDOUT_OBJECTIVES: Final[tuple[str, ...]] = ("mse", "wcvar-b0_9")
"""Objectives of the out-of-sample cases (a QP and an LP), by id token."""

N_SHORT_YEARS: Final[int] = 52
"""Years of the short synthetic data set: the first 52 years of the synthetic
one. 52 is not a multiple of :data:`KFOLD_K`, so the k-fold blocks are uneven
(11, 11, 10, 10, 10), as ``numpy.array_split`` makes them."""
KFOLD_K: Final[int] = 5
"""Folds of the k-fold cases (the core's ``splits.year_block_kfold``)."""
KFOLD_CASES: Final[tuple[tuple[str, str], ...]] = (("mse", "pure"),)
"""(objective, pricing) id tokens of the k-fold cases: one design per fold."""
FRESH_SEED: Final[int] = 20261106
"""Seed of the fresh draws (``numpy.random.default_rng``): the synthetic
process again, from another generator."""
N_FRESH_DRAWS: Final[int] = 50
"""Draws of the fresh sample."""
FRESH_CASES: Final[tuple[tuple[str, str], ...]] = (
    ("mse", "pure"),
    ("wcvar-b0_9", "coc"),
)
"""(objective, pricing) id tokens of the fresh-draw cases (a QP and an LP)."""
BINARY_TRIGGER: Final[float] = 36.0
"""Fixed trigger (m/s) of the binary design cases: an index of A1 sits on it."""
BINARY_CASES: Final[tuple[tuple[str, str], ...]] = (
    ("mse", "pure"),
    ("wcvar-b0_9", "coc"),
)
"""(objective, pricing) id tokens of the binary designs with a fixed trigger."""
GRID_TRIGGERS: Final[tuple[float, ...]] = (30.0, 33.0, 36.0, 40.0, 45.0, 51.0)
"""Grid (m/s) of the free trigger of the grid-route cases (ADR 0005 §5.3)."""
GRID_CASES: Final[tuple[tuple[str, str], ...]] = (
    ("mse", "coc"),
    ("eu", "pure"),
)
"""(objective, pricing) id tokens of the grid-route cases (a QP and an LP)."""
GRID_MARGIN: Final[float] = 1e-4
"""The best grid candidate must beat every other by this much, relative, so
no tie rule decides it (ADR 0005 §5.3 leaves the tie tolerance open)."""
LOWER_STEP_BREAKPOINTS: Final[tuple[float, ...]] = (-1.0, -1.5, -2.0, -3.0)
"""Breakpoints of the lower-tail step covers on the hand-made SPEI sample, in
index units, in order of increasing severity."""
LOWER_STEP_LEVELS: Final[tuple[float, ...]] = (100.0, 250.0, 500.0, 900.0)
"""Levels (EUR) of the fixed lower-tail step cover."""
LOWER_STEP_CASES: Final[tuple[tuple[str, str], ...]] = (("wcvar-b0_9", "pure"),)
"""(objective, pricing) id tokens of the lower-tail step designs."""

BETAS: Final[tuple[float, ...]] = (0.9, 0.95, 0.99)
"""Metric levels: ADR 0005 §6, ``MetricOptions`` defaults."""
RETURN_PERIODS: Final[tuple[float, ...]] = (2.0, 5.0, 10.0, 25.0, 50.0, 100.0, 250.0)
"""Metric return periods in years: ADR 0005 §6, ``MetricOptions`` defaults."""
LOSS_THRESHOLDS: Final[tuple[float, ...]] = (0.0,)
"""Loss thresholds of the false-negative and false-positive rates (§6)."""
PAYOUT_THRESHOLD: Final[float] = 0.0
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
        Design cases: the core's objective value, premium and metrics, in
        sample and out of sample (the ``expected`` fields, written the same
        way), of the cover at the given levels, shape ``(n_assets,
        n_levels)``.
    violations : callable, optional
        Design cases: the design constraints the given levels break.
    ranges : tuple of numpy.ndarray, optional
        LP design cases: the wide near-optimal range of every identified
        level, ``(low, high)``, loss units; NaN for unidentified levels.
    identified : numpy.ndarray of bool, optional
        Design cases: which levels are identified, ``(n_assets, n_levels)``.
    amount_names : tuple of str, optional
        Design cases: the parameter name of each level, in column order;
        default ``levels[0]``, ``levels[1]``, ... (a step payout).
    shape_parameters : mapping, optional
        Grid-route cases: the chosen value of each free shape parameter. It
        is a grid value, compared exactly whether or not the design is
        unique (the best candidate is strictly best, :data:`GRID_MARGIN`).
    """

    document: dict[str, Any]
    evaluate: Callable[[NDArray[np.float64]], dict[str, Any]] | None = None
    violations: Callable[[NDArray[np.float64]], list[str]] | None = None
    ranges: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None
    identified: NDArray[np.bool_] | None = None
    amount_names: tuple[str, ...] | None = None
    shape_parameters: Mapping[str, float] | None = None


@dataclass(frozen=True)
class MetricOptions:
    """ADR 0005 §6's ``MetricOptions``: the parameters of the metric columns.

    The defaults are §6's. A case with the defaults writes its
    ``metric_options`` as null; any other case writes them out.

    Attributes
    ----------
    betas : tuple of float
        Levels β in (0, 1) of the ``_b<β>`` columns.
    return_periods : tuple of float
        Return periods T > 1, in years, of the ``_rp<T>`` columns.
    loss_thresholds : tuple of float
        Loss thresholds (loss units) of the ``_l<threshold>`` columns.
    payout_threshold : float
        ε (payout units): a year with a payout of at most ε counts as "no
        payout" in the false-negative and false-positive rates.
    """

    betas: tuple[float, ...] = BETAS
    return_periods: tuple[float, ...] = RETURN_PERIODS
    loss_thresholds: tuple[float, ...] = LOSS_THRESHOLDS
    payout_threshold: float = PAYOUT_THRESHOLD

    def __post_init__(self) -> None:
        """Check the values and that no two columns share a label (§6)."""
        if not all(0.0 < b < 1.0 for b in self.betas):
            raise ValueError(f"betas must lie in (0, 1): {self.betas!r}")
        if not all(t > 1.0 and math.isfinite(t) for t in self.return_periods):
            raise ValueError(f"return periods must exceed 1: {self.return_periods!r}")
        if not all(math.isfinite(x) for x in self.loss_thresholds):
            raise ValueError(f"loss thresholds must be finite: {self.loss_thresholds}")
        if not (math.isfinite(self.payout_threshold) and self.payout_threshold >= 0):
            raise ValueError(f"invalid payout threshold {self.payout_threshold!r}")
        for values in (self.betas, self.return_periods, self.loss_thresholds):
            if len({label(v) for v in values}) != len(values):
                raise ValueError(f"metric labels collide: {values!r}")

    @property
    def is_default(self) -> bool:
        """Whether these are ADR 0005 §6's defaults."""
        return self == MetricOptions()

    def document(self) -> dict[str, Any] | None:
        """Return the ``metric_options`` block: null for the defaults."""
        if self.is_default:
            return None
        return {
            F.betas: [float(b) for b in self.betas],
            F.return_periods: [float(t) for t in self.return_periods],
            F.loss_thresholds: [float(x) for x in self.loss_thresholds],
            F.payout_threshold: float(self.payout_threshold),
        }


HANDMADE_OPTIONS: Final[MetricOptions] = MetricOptions(
    betas=(0.5, 0.8, 0.975),
    return_periods=(2.5, 4.0, 20.0, 1000.0),
    loss_thresholds=(150.0, 262.5),
    payout_threshold=50.0,
)
"""Non-default options on the hand-made rainfall sample. 150 EUR is a loss
of the sample and 50 EUR a payout of the piecewise-linear cover (at its first
knot), so both boundaries are tested: a loss equal to the loss threshold is
not above it, and a payout equal to the payout threshold is no payout. 262.5
and 2.5 test the decimal label."""
SYNTHETIC_OPTIONS: Final[MetricOptions] = MetricOptions(
    betas=(0.75, 0.975),
    return_periods=(2.5, 20.0, 1000.0),
    loss_thresholds=(0.0, 100_000.0, 1_000_000.0),
    payout_threshold=10_000.0,
)
"""Non-default options on the short synthetic sample. 10,000 USD is the
piecewise-linear cover's payout at its first knot, 25 m/s, where an index
of A1 sits."""


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
        The core's ``StepPayout`` breakpoints ``b_0 < ... < b_n``, on the
        severity (below).
    hazard_name, aggregation, index_unit, loss_unit : str
        The index definition of the cover document and the sample's units.
    values : tuple of float
        Insured value of each asset (for the core's EventSet only).
    licence : str
        Licence of the data the draws come from.
    tail : {"upper", "lower"}
        The severe side of the index (ADR 0005 §3). The core has no lower
        tail, so it works on the severity ``s = -x`` of a lower-tail index
        ``x``: its step payout on ``s`` with breakpoints ``-b`` is the
        module's lower-tail step on ``x`` with breakpoints ``b``.
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
    tail: Literal["upper", "lower"] = "upper"

    @property
    def n(self) -> int:
        """Number of draws (years)."""
        return int(self.period.shape[0])

    @property
    def sign(self) -> float:
        """1 for the upper tail, -1 for the lower: ``severity = sign * index``."""
        return 1.0 if self.tail == "upper" else -1.0

    @property
    def severity(self) -> NDArray[np.float64]:
        """The index on the severity scale, ``(n, n_assets)``: what the core sees."""
        return self.sign * self.index + 0.0

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

    def draws(self, positions: NDArray[np.int64]) -> Dataset:
        """Return the data set restricted to some draws, by position.

        Parameters
        ----------
        positions : numpy.ndarray of int
            Positions ``0 .. n - 1``, increasing.

        Returns
        -------
        Dataset
            The draws at those positions, with their periods.
        """
        if positions.size == 0 or np.any(np.diff(positions) <= 0):
            raise ValueError("positions must be non-empty and increasing")
        return replace(
            self,
            period=self.period[positions].copy(),
            index=np.ascontiguousarray(self.index[positions]),
            loss=np.ascontiguousarray(self.loss[positions]),
            event_row=self.event_row[positions].copy(),
        )


def synthetic_dataset(
    rng: np.random.Generator,
    *,
    n: int = N_SYNTHETIC_YEARS,
    on_breakpoints: bool = True,
    name: str = "synthetic",
) -> Dataset:
    """Build the seeded synthetic data set.

    Each of the ``n`` years has a storm with probability 0.7. A storm has an
    intensity ``22 + Gamma(2, 7)`` m/s; the hazard at each asset adds
    ``N(0, 3)``. The loss is the asset's value times the Emanuel-type damage
    ratio ``v^3 / (1 + v^3)``, ``v = max(h - 25.7, 0) / 49``, of the hazard
    ``h``; the index is the hazard plus another ``N(0, 3)`` (basis risk),
    floored at 0. Indices are rounded to 0.01 m/s and losses to whole USD.
    With ``on_breakpoints``, three indices of A1 are then set onto
    breakpoints to exercise the bin rule: the first storm year's to the first
    breakpoint (25), the second's to an interior breakpoint (36) and the
    third's to the last module breakpoint (60). Years without a storm have
    index 0 and loss 0 and no event row.

    Parameters
    ----------
    rng : numpy.random.Generator
        Source of every draw, in this order: storm occurrence, intensity,
        hazard noise, index noise.
    n : int, default :data:`N_SYNTHETIC_YEARS`
        Number of years (draws).
    on_breakpoints : bool, default True
        Whether to set three indices of A1 onto breakpoints. The fresh draws
        are the plain process, without it.
    name : str, default "synthetic"
        The data set's name.

    Returns
    -------
    Dataset
        Assets A1, A2, A3.
    """
    values = np.asarray(SYNTHETIC_VALUES)
    storm = rng.random(n) < 0.7
    intensity = 22.0 + rng.gamma(shape=2.0, scale=7.0, size=n)
    hazard = intensity[:, None] + rng.normal(0.0, 3.0, size=(n, values.size))
    noisy = hazard + rng.normal(0.0, 3.0, size=(n, values.size))
    v = np.clip((hazard - 25.7) / (74.7 - 25.7), 0.0, None)
    damage = v**3 / (1.0 + v**3)
    index = np.where(storm[:, None], np.round(np.maximum(noisy, 0.0), 2), 0.0)
    loss = np.where(storm[:, None], np.round(damage * values), 0.0)
    if on_breakpoints:
        storm_years = np.flatnonzero(storm)
        for year, edge in zip(storm_years[:3], (25.0, 36.0, 60.0), strict=True):
            index[year, 0] = edge
    return Dataset(
        name=name,
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
    zero-loss outcome. The core's index is the severity
    (:attr:`Dataset.severity`), the index itself for the upper tail.

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
    return EventSet(events, locations, data.severity[rows], data.loss[rows], metadata)


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


def _return_level(period: float) -> Fraction:
    """Return the quantile level ``1 - 1/T`` of a return period, exact (§6)."""
    return 1 - 1 / _fraction(period)


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


@dataclass(frozen=True)
class SplitSpec:
    """The out-of-sample split of a design case (ADR 0005 §4.4 and §6).

    Attributes
    ----------
    kind : str
        :attr:`_Fields.split_holdout`, :attr:`_Fields.split_kfold` or
        :attr:`_Fields.split_fresh_draws`.
    train_fraction : float, optional
        Holdout: the share of the years that design.
    k, fold : int, optional
        k-fold: the number of folds and the fold (``0 .. k - 1``).
    fresh : Dataset, optional
        Fresh draws: the evaluation sample, drawn from the same process as
        the design sample with another generator.
    seed : int, optional
        Fresh draws: the seed of that generator.
    """

    kind: str
    train_fraction: float | None = None
    k: int | None = None
    fold: int = 0
    fresh: Dataset | None = None
    seed: int | None = None

    def document(self) -> dict[str, Any]:
        """Return the case's ``split`` block."""
        if self.kind == F.split_holdout and self.train_fraction is not None:
            return {
                F.kind_key: F.split_holdout,
                F.train_fraction: float(self.train_fraction),
            }
        if self.kind == F.split_kfold and self.k is not None:
            return {F.fold: int(self.fold), F.k: int(self.k), F.kind_key: F.split_kfold}
        if (
            self.kind == F.split_fresh_draws
            and self.fresh is not None
            and self.seed is not None
        ):
            return {
                F.kind_key: F.split_fresh_draws,
                F.n_draws: self.fresh.n,
                F.seed: int(self.seed),
            }
        raise ValueError(f"incomplete split {self!r}")

    @property
    def token(self) -> str:
        """The case id's suffix: ``-holdout``, ``-kfold5-fold2``, ``-fresh``."""
        if self.kind == F.split_kfold:
            return f"-{F.split_kfold}{self.k}-{F.fold}{self.fold}"
        if self.kind == F.split_fresh_draws:
            return "-fresh"
        return f"-{self.kind}"


def _split_document(split: SplitSpec | None) -> dict[str, Any] | None:
    """Return the split block: null in sample (ADR 0005 §4.4)."""
    return None if split is None else split.document()


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
    """Return the step cover of asset ``j``; breakpoints: the core's ``b[:-1]``.

    The core's breakpoints are on the severity; the cover's are in index
    units, ``-b`` for the lower tail (decreasing index values).
    """
    payout = {
        F.breakpoints: [data.sign * float(b) + 0.0 for b in data.edges[:-1]],
        F.kind_key: F.payout_step,
        F.levels: list(levels),
        F.monotone: True,
        F.tail: data.tail,
    }
    index = _index_document(
        data.hazard_name, data.aggregation, data.index_unit, data.tail
    )
    return _cover_document(data.asset_ids[j], index, payout, data.loss_unit)


def _binary_cover(
    data: Dataset,
    j: int,
    amount: float | dict[str, Any],
    trigger: float | dict[str, Any],
) -> dict[str, Any]:
    """Return the binary cover of asset ``j`` (ADR 0005 §3).

    ``trigger`` is a number in index units or a ``Free`` marker; ``amount``
    a number or a ``Free`` marker.
    """
    payout = {
        F.amount_param: amount,
        F.kind_key: F.payout_binary,
        F.tail: data.tail,
        F.trigger: trigger,
    }
    index = _index_document(
        data.hazard_name, data.aggregation, data.index_unit, data.tail
    )
    return _cover_document(data.asset_ids[j], index, payout, data.loss_unit)


def binary_edges(severity: float) -> tuple[float, float]:
    """Return the core's one-bin step edges of a binary trigger, on the severity.

    A binary payout is a step with one breakpoint, the trigger. The core's
    step payout needs a second edge; values at or above it fall into the bin
    too, so any edge above the trigger gives the same payout.
    """
    return (float(severity), float(severity) + 1.0)


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
    *,
    sample: Sample | None = None,
    premium: float | None = None,
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
        Loss and payout of the subject per draw of ``sample``.
    sample : Sample, optional
        The core's evaluation sample (a holdout block); default all years.
    premium : float, optional
        A stated premium: the ``premium`` column and the net loss use it
        instead of the premium priced on ``sample``. Out-of-sample metrics of
        a design use the design premium (ADR 0005 §6, decision 9).

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

    stated = premium
    for i, beta in enumerate(BETAS):
        table = kpis(
            eventset,
            scope,
            results,
            basis=Basis.ANNUAL,
            beta=beta,
            run_id=RUN_ID,
            sample=sample,
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
                value = (
                    stated
                    if name == "premium" and stated is not None
                    else kpi_row(table, kpi)
                )
                if name in plain:
                    if value is None:
                        raise AssertionError(f"{name} is undefined")
                    _check_close(name, value, plain[name], scale)
                out_metrics[metric(name)] = None if value is None else out(value)
            premium = stated if stated is not None else kpi_row(table, "premium")
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

    ev = evaluate_results(eventset, scope, results, basis=Basis.ANNUAL, sample=sample)
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
        sample=sample,
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
    years = eventset.metadata.n_years if sample is None else sample.years.size
    if n != years:
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
        k = step_bins(data.severity[:, j], breakpoints)
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
        k = step_bins(data.severity[:, j], breakpoints)
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


def _fill_lowest(
    theta: NDArray[np.float64], identified: NDArray[np.bool_]
) -> NDArray[np.float64]:
    """Set the unidentified levels by ADR 0005 §5.4's default rule, ``"lowest"``.

    An unidentified level changes nothing on the design sample, so any value
    the constraints allow is optimal. The rule takes the smallest: under
    ``monotone`` the previous identified level, or 0 (the lower bound) if
    there is none. The design stays exactly optimal and feasible. Out of
    sample a draw can fall into such a bin, so the value matters there.

    Parameters
    ----------
    theta : numpy.ndarray
        Levels, ``(n_assets, n_levels)``, monotone in each row.
    identified : numpy.ndarray of bool
        Which levels are identified, the same shape.

    Returns
    -------
    numpy.ndarray
        A copy with every unidentified level filled.
    """
    filled = theta.copy()
    for j in range(filled.shape[0]):
        previous = 0.0
        for k in range(filled.shape[1]):
            if identified[j, k]:
                previous = float(filled[j, k])
            else:
                filled[j, k] = previous
    return filled


def _rel_close(a: float, b: float, rtol: float) -> bool:
    return math.isclose(a, b, rel_tol=rtol, abs_tol=0.0) or a == b


def amount_names(family: str, n_levels: int) -> tuple[str, ...]:
    """Return the flat names of a design template's amounts (ADR 0005 §3).

    ``levels[0]`` ... for a step payout, ``amount`` for a binary one.
    """
    if family == F.payout_step:
        return tuple(level_name(k) for k in range(n_levels))
    if family == F.payout_binary and n_levels == 1:
        return (F.amount_param,)
    raise ValueError(f"no amounts for {family!r} with {n_levels} levels")


def payout_token(family: str, tail: str, *, grid: bool = False) -> str:
    """Return the payout part of a case id.

    ``step`` for an upper-tail step (the MAR-245 ids), otherwise the family
    and the tail: ``step-lower``, ``binary-upper``; ``-grid`` is added when
    a shape parameter is free on a grid.
    """
    if family == F.payout_step and tail == "upper" and not grid:
        return "step"
    token = f"{family.replace('_', '-')}-{tail}"
    return f"{token}-grid" if grid else token


@dataclass(frozen=True)
class BinaryOptimum:
    """The closed-form optimum of a binary design with a fixed trigger."""

    amount: float
    objective_value: float
    amount_bound: float


def binary_optimum(
    objective: Objective,
    pricing: Pricing,
    loss: NDArray[np.float64],
    triggered: NDArray[np.bool_],
    cap: float,
) -> BinaryOptimum:
    """Solve the one-amount design of a binary payout in closed form.

    The payout is ``A`` in the triggered draws and 0 elsewhere, over
    equally likely draws, with ``0 <= A <= cap`` and the budget ``P <= 0.8
    E[L]`` (:data:`BUDGET_RATIO`). The premium is linear in ``A``: ``P =
    c A`` with ``c = p`` (pure premium, ``p`` the triggered share) or ``c =
    (1 - r) p + r min(1, p / (1 - q))`` (cost of capital, since ``CVaR_q``
    of a payout that is ``A`` with probability ``p`` is ``A min(1, p / (1 -
    q))``). So ``A`` ranges over ``[0, A_max]``, ``A_max = min(cap, budget /
    c)``.

    * E[U] and weighted CVaR do not increase in ``A`` (the uncovered loss of
      every draw does not), so ``A_max`` is optimal.
    * MSE is a quadratic in ``A``, smallest at the mean loss of the
      triggered draws, clipped to ``[0, A_max]``.

    With no triggered draw the amount changes nothing; it is 0.

    Parameters
    ----------
    objective : Objective
        The core's ``MSE``, ``ExpectedUncovered`` or ``WeightedCVaR``.
    pricing : Pricing
        The core's ``PurePremium`` or ``CostOfCapitalLoad``.
    loss : numpy.ndarray
        Loss per draw.
    triggered : numpy.ndarray of bool
        Whether each draw is at or beyond the trigger.
    cap : float
        The amount's upper bound.

    Returns
    -------
    BinaryOptimum
        An optimal amount, the objective value there, and ``A_max``.
    """
    p = float(np.mean(triggered))
    budget = BUDGET_RATIO * float(np.mean(loss))
    if isinstance(pricing, pid.PurePremium):
        unit_premium = p
    elif isinstance(pricing, pid.CostOfCapitalLoad):
        unit_premium = (1.0 - pricing.rate) * p + pricing.rate * min(
            1.0, p / (1.0 - pricing.q)
        )
    else:
        raise TypeError(f"no closed form for the pricing {pricing!r}")
    bound = cap if unit_premium == 0.0 else min(cap, budget / unit_premium)
    if p == 0.0:
        amount = 0.0
    elif isinstance(objective, pid.MSE):
        amount = min(max(float(np.mean(loss[triggered])), 0.0), bound)
    elif isinstance(objective, pid.ExpectedUncovered | pid.WeightedCVaR):
        amount = bound
    else:
        raise TypeError(f"no closed form for the objective {objective!r}")
    value = _objective_value(objective, loss, np.where(triggered, amount, 0.0))
    return BinaryOptimum(amount=amount, objective_value=value, amount_bound=bound)


def design_case(
    data: Dataset,
    scope_name: str,
    objective: ObjectiveSpec,
    pricing: PricingSpec,
    commit: str,
    settings: SolverSettings,
    *,
    split: SplitSpec | None = None,
    family: str = F.payout_step,
) -> GeneratedCase:
    """Build one design case: the core designs a step or binary cover on ``data``.

    Parameters
    ----------
    data : Dataset
        The draws, restricted to the case's assets (one for the individual
        scope, several for the joint scope). Its ``edges`` are the core's
        step breakpoints on the severity; for a binary cover, the trigger's
        one-bin edges (:func:`binary_edges`).
    scope_name : {"individual", "joint"}
        ``Individual()`` or ``Portfolio()`` in the core.
    objective, pricing : ObjectiveSpec, PricingSpec
        The case's objective and pricing.
    commit : str
        The generator block's commit.
    settings : SolverSettings
        The solver policies.
    split : SplitSpec, optional
        An out-of-sample case. Holdout and k-fold: the core's
        ``splits.holdout`` or ``splits.year_block_kfold`` splits the draws;
        the core designs on the design block (the case's ``sample``) and
        evaluates the design on the held-out block (its
        ``evaluation_sample``). Fresh draws: the core designs on every draw
        and evaluates the design on the fresh sample, another EventSet with
        the same asset. Either way with the design premium. Default: design
        and evaluate on every draw.
    family : str, default "step"
        The template's payout family: :attr:`_Fields.payout_step`, or
        :attr:`_Fields.payout_binary`, a fixed trigger and a free amount,
        which the core designs as its one-bin step from the trigger.

    Returns
    -------
    GeneratedCase
        The case document, with what the regeneration check needs: the core's
        evaluation of any levels, the constraints they break, and the ranges.
    """
    joint = scope_name == F.scope_joint
    if joint == (len(data.asset_ids) == 1):
        raise ValueError("individual cases have one asset, joint cases several")
    binary = family == F.payout_binary
    if binary and (joint or len(data.edges) != 2):
        raise ValueError("a binary design is individual, with one trigger")
    if family not in (F.payout_step, F.payout_binary):
        raise ValueError(f"the core designs no {family!r} payout")
    eventset = core_eventset(data)
    payout = step_payout(data)
    scope: Scope = pid.Portfolio() if joint else pid.Individual()
    constraints = (pid.Budget(BUDGET_RATIO),)
    train: Sample | None = None
    test: Sample | None = None
    eval_eventset = eventset
    design_data, eval_data = data, None
    if split is not None:
        if split.kind == F.split_fresh_draws:
            if split.fresh is None or split.fresh.asset_ids != data.asset_ids:
                raise ValueError("fresh draws need a sample of the same assets")
            eval_data = split.fresh
            eval_eventset = core_eventset(split.fresh)
        else:
            # The core's EventSet numbers the years by position
            # (core_eventset), so the years of a block are the positions of
            # its draws.
            if split.kind == F.split_holdout and split.train_fraction is not None:
                train, test = holdout(eventset, train_fraction=split.train_fraction)
            elif split.kind == F.split_kfold and split.k is not None:
                train, test = year_block_kfold(eventset, k=split.k)[split.fold]
            else:
                raise ValueError(f"incomplete split {split.kind!r}")
            if test.fold != split.fold:
                raise AssertionError("the core's fold and the split's differ")
            design_data = data.draws(train.years)
            eval_data = data.draws(test.years)

    def build() -> BuiltProblem:
        (built,) = build_problems(
            eventset,
            scope,
            payout,
            objective.core,
            pricing.core,
            constraints,
            basis=Basis.ANNUAL,
            sample=train,
        )
        return built

    first = build()
    qp = is_qp(first.problem)
    identified = _identified(design_data)
    rows = (Sample.full(eventset) if train is None else train).select(eventset)
    for j in range(len(data.asset_ids)):
        core_columns = payout.basis_matrix(rows.index[:, j]).sum(axis=0) > 0
        if not np.array_equal(core_columns, identified[j]):
            raise AssertionError("the core's bins and the module's bin rule differ")
    split_token = "" if split is None else f"/{split.token[1:]}"
    where = (
        f"{data.name}/{family}/{scope_name}/{objective.token}/{pricing.token}"
        f"{split_token}"
    )
    ranges: _Ranges | None = None
    if qp:
        accurate = solve(first, settings.accurate)
        check = solve(build(), settings.qp_check)
        unique = _mse_unique(design_data, identified)
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
    theta = _fill_lowest(theta, identified)
    loss_draws = design_data.loss.sum(axis=1)
    caps = design_data.loss.max(axis=0)
    budget = BUDGET_RATIO * float(np.mean(loss_draws))

    def payout_of(on: Dataset, levels: NDArray[np.float64]) -> NDArray[np.float64]:
        payout_draws = np.zeros(on.n)
        for j in range(len(on.asset_ids)):
            payout_draws = payout_draws + step_values(
                on.severity[:, j], on.edges[:-1], levels[j]
            )
        return payout_draws

    def in_sample(levels: NDArray[np.float64]) -> dict[str, Any]:
        """Return the metrics of the cover at ``levels`` on the design sample."""
        return core_metrics(
            eventset,
            scope,
            (replace(chosen, theta=levels),),
            pricing.core,
            _Draws(loss_draws, payout_of(design_data, levels)),
            sample=train,
        )

    def evaluate(levels: NDArray[np.float64]) -> dict[str, Any]:
        """Return the objective, premium and metrics of the cover at ``levels``."""
        metrics = in_sample(levels)
        value = _objective_value(
            objective.core, loss_draws, payout_of(design_data, levels)
        )
        oos: dict[str, Any] | None = None
        if eval_data is not None and split is not None:
            oos = {
                F.fold: split.fold,
                F.premium_basis: F.premium_basis_design,
                F.metrics: core_metrics(
                    eval_eventset,
                    scope,
                    (replace(chosen, theta=levels),),
                    pricing.core,
                    _Draws(eval_data.loss.sum(axis=1), payout_of(eval_data, levels)),
                    sample=test,
                    premium=metrics[metric("premium")],
                ),
            }
        return {
            F.objective_value: out(value),
            F.premium: metrics[metric("premium")],
            F.metrics: metrics,
            F.out_of_sample: oos,
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
        premium = in_sample(levels)[metric("premium")]
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

    names = amount_names(family, theta.shape[1])
    if binary:
        # The one-amount problem has a closed form (binary_optimum); the
        # core's optimum must agree with it.
        triggered = design_data.severity[:, 0] >= data.edges[0]
        closed = binary_optimum(
            objective.core, pricing.core, loss_draws, triggered, float(caps[0])
        )
        if not math.isclose(
            evaluation[F.objective_value],
            closed.objective_value,
            rel_tol=WRITTEN_RTOL,
            abs_tol=ZERO_AMOUNT * scale * (scale if qp else 1.0),
        ):
            raise AssertionError(
                f"{where}: the core's optimum {evaluation[F.objective_value]!r}, "
                f"the closed form's {closed.objective_value!r}"
            )
        covers = [_binary_cover(data, 0, _free(caps[0]), data.sign * data.edges[0])]
    else:
        covers = [
            _step_cover(data, j, [_free(caps[j])] * theta.shape[1])
            for j in range(len(data.asset_ids))
        ]
    parameters = [
        {name: out(theta[j, k]) for k, name in enumerate(names)}
        for j in range(len(data.asset_ids))
    ]
    unidentified = [
        [name for k, name in enumerate(names) if not identified[j, k]]
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
    case_id = (
        f"{payout_token(family, data.tail)}-{objective.token}-{pricing.token}-"
        f"{scope_name}-{data.name}{'' if split is None else split.token}"
    )
    document = {
        F.case_id: case_id,
        F.kind: F.kind_design,
        F.source: F.source_core,
        F.sample: _sample_document(design_data),
        F.split: _split_document(split),
        F.evaluation_sample: (
            None if eval_data is None else _sample_document(eval_data)
        ),
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
            F.out_of_sample: evaluation[F.out_of_sample],
            F.profile: None,
        },
        F.metric_options: None,
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
        amount_names=names,
    )


def grid_design_case(
    data: Dataset,
    objective: ObjectiveSpec,
    pricing: PricingSpec,
    commit: str,
    settings: SolverSettings,
    *,
    grid: Sequence[float],
) -> GeneratedCase:
    """Build a grid-route design case: a binary cover with a free trigger.

    ADR 0005 §5.3's grid route: a ``BinaryPayout`` whose trigger is
    ``Free`` on a grid and whose amount is ``Free``. At each grid candidate
    the core designs the amount (:func:`design_case` with the one-bin step
    from that trigger, an LP or QP, checked against :func:`binary_optimum`);
    the best candidate wins. It must beat every other by
    :data:`GRID_MARGIN`, relative, so no tie rule decides it. The case is
    the best candidate's, with the trigger written as the template's
    ``Free`` marker, the chosen trigger added to ``expected.parameters`` and
    the objective at every candidate in ``expected.profile``.

    Parameters
    ----------
    data : Dataset
        The draws of one asset.
    objective, pricing : ObjectiveSpec, PricingSpec
        The case's objective and pricing.
    commit : str
        The generator block's commit.
    settings : SolverSettings
        The solver policies.
    grid : sequence of float
        The trigger's candidates in index units, increasing.

    Returns
    -------
    GeneratedCase
        The best candidate's case, with ``shape_parameters`` set.
    """
    if len(data.asset_ids) != 1 or list(grid) != sorted(set(grid)) or len(grid) < 2:
        raise ValueError("a grid case has one asset and an increasing grid")
    candidates = [
        design_case(
            replace(data, edges=binary_edges(data.sign * t)),
            F.scope_individual,
            objective,
            pricing,
            commit,
            settings,
            family=F.payout_binary,
        )
        for t in grid
    ]
    values = [float(c.document[F.expected][F.objective_value]) for c in candidates]
    best = int(np.argmin(values))
    floor = case_scale(candidates[best].document)
    floor = floor**2 if isinstance(objective.core, pid.MSE) else floor
    gap = min(v for i, v in enumerate(values) if i != best) - values[best]
    if gap <= GRID_MARGIN * max(abs(values[best]), ZERO_AMOUNT * floor):
        raise AssertionError(
            f"{data.name}/{objective.token}/{pricing.token}: the best grid "
            f"candidate {grid[best]} beats the next by only {gap!r}"
        )
    chosen = candidates[best]
    document = json.loads(json.dumps(chosen.document))
    trigger = float(grid[best])
    payout = document[F.cover][F.payout]
    payout[F.trigger] = {
        F.free: {
            F.grid: [float(t) for t in grid],
            F.lower: float(min(grid)),
            F.upper: float(max(grid)),
        }
    }
    expected = document[F.expected]
    expected[F.parameters] = {**expected[F.parameters], F.trigger: trigger}
    expected[F.profile] = [
        {F.objective_value: v, F.parameters: {F.trigger: float(t)}}
        for t, v in zip(grid, values, strict=True)
    ]
    document[F.case_id] = (
        f"{payout_token(F.payout_binary, data.tail, grid=True)}-{objective.token}-"
        f"{pricing.token}-{F.scope_individual}-{data.name}"
    )
    return replace(chosen, document=document, shape_parameters={F.trigger: trigger})


# --------------------------------------------------------------------------
# Fixed covers: step (core); linear, binary, piecewise linear (closed form)
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
    payout_draws = step_values(data.severity[:, 0], data.edges[:-1], levels)
    metrics = core_metrics(
        eventset, scope, (result,), pricing.core, _Draws(loss, payout_draws)
    )
    cover = _step_cover(data, 0, [float(v) for v in levels])
    return {
        F.case_id: f"step-fixed-{pricing.token}-{F.scope_individual}-{data.name}",
        F.kind: F.kind_evaluate,
        F.source: F.source_core,
        F.sample: _sample_document(data),
        F.split: None,
        F.evaluation_sample: None,
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
            F.out_of_sample: None,
            F.profile: None,
        },
        F.metric_options: None,
        F.compare_parameters: F.compare_none,
        F.tolerances: _tolerances(),
        F.generator: _generator(commit),
    }


@dataclass(frozen=True)
class ClosedFormSample:
    """A sample of one asset for the closed-form cases (ADR 0005 §4.1).

    Attributes
    ----------
    name : str
        The data set, the last part of a case id: ``"handmade"`` or
        ``"synthetic"``.
    tail : {"upper", "lower"}
        The severe side of its index; the covers on it share it.
    hazard_name, aggregation, index_unit, loss_unit : str
        The index definition of the cover document and the sample's units.
    period, index, loss : tuple
        One value per draw (year), each draw of probability ``1 / n``.
    """

    name: str
    tail: Literal["upper", "lower"]
    hazard_name: str
    aggregation: str
    index_unit: str
    loss_unit: str
    period: tuple[int, ...]
    index: tuple[float, ...]
    loss: tuple[float, ...]


@dataclass(frozen=True)
class ClosedFormCover:
    """A fixed cover of a family the core does not have (ADR 0005 §3).

    Attributes
    ----------
    family : str
        The payout kind: :attr:`_Fields.payout_linear`,
        :attr:`_Fields.payout_binary`, :attr:`_Fields.payout_piecewise_linear`
        or :attr:`_Fields.payout_step` (the core's step has no lower tail).
    parameters : mapping
        The payout document's parameters, thresholds in index units (in
        order of increasing severity) and amounts in payout units, e.g.
        ``{"trigger": 100.0, "amount": 500.0}``.
    pricings : tuple of str
        The pricing tokens of its cases (:data:`CLOSED_FORM_PRICINGS`).
    options : MetricOptions
        The metric columns of its cases; non-default options add the id
        suffix ``-options``.
    """

    family: str
    parameters: Mapping[str, float | tuple[float, ...]]
    pricings: tuple[str, ...]
    options: MetricOptions = field(default_factory=MetricOptions)


HANDMADE_SAMPLES: Final[Mapping[str, ClosedFormSample]] = {
    "upper": ClosedFormSample(
        name="handmade",
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
    ),
    "lower": ClosedFormSample(
        name="handmade",
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
    ),
}
"""The hand-made samples (20 years each): rainfall (upper tail), drought
index (lower tail)."""

CLOSED_FORM_COVERS: Final[Mapping[str, tuple[ClosedFormCover, ...]]] = {
    "handmade-upper": (
        ClosedFormCover(
            F.payout_linear,
            {F.attachment: 50.0, F.exhaustion: 150.0, F.limit_param: 1000.0},
            ("pure", "coc"),
        ),
        ClosedFormCover(
            F.payout_binary,
            {F.trigger: 100.0, F.amount_param: 500.0},
            ("pure", "coc"),
        ),
        ClosedFormCover(
            F.payout_piecewise_linear,
            {
                F.knots: (50.0, 80.0, 120.0, 175.0),
                F.levels: (50.0, 250.0, 700.0, 1200.0),
            },
            ("pure", "coc"),
        ),
        ClosedFormCover(
            F.payout_piecewise_linear,
            {
                F.knots: (50.0, 80.0, 120.0, 175.0),
                F.levels: (50.0, 250.0, 700.0, 1200.0),
            },
            ("pure",),
            HANDMADE_OPTIONS,
        ),
    ),
    "handmade-lower": (
        ClosedFormCover(
            F.payout_linear,
            {F.attachment: -1.0, F.exhaustion: -3.0, F.limit_param: 800.0},
            ("pure",),
        ),
        ClosedFormCover(
            F.payout_binary, {F.trigger: -1.5, F.amount_param: 400.0}, ("pure",)
        ),
        ClosedFormCover(
            F.payout_piecewise_linear,
            {F.knots: (-1.0, -2.0, -3.0), F.levels: (100.0, 400.0, 800.0)},
            ("pure",),
        ),
        ClosedFormCover(
            F.payout_step,
            {F.breakpoints: LOWER_STEP_BREAKPOINTS, F.levels: LOWER_STEP_LEVELS},
            ("pure",),
        ),
    ),
    "synthetic-upper": (
        ClosedFormCover(
            F.payout_linear,
            {F.attachment: 36.0, F.exhaustion: 60.0, F.limit_param: 2_500_000.0},
            ("pure",),
        ),
        ClosedFormCover(
            F.payout_binary,
            {F.trigger: 36.0, F.amount_param: 500_000.0},
            ("pure",),
        ),
        ClosedFormCover(
            F.payout_piecewise_linear,
            {
                F.knots: (25.0, 36.0, 51.0, 60.0),
                F.levels: (10_000.0, 100_000.0, 1_200_000.0, 2_500_000.0),
            },
            ("pure", "coc"),
        ),
    ),
    "synthetic52-upper": (
        ClosedFormCover(
            F.payout_piecewise_linear,
            {
                F.knots: (25.0, 36.0, 51.0, 60.0),
                F.levels: (10_000.0, 100_000.0, 1_200_000.0, 2_500_000.0),
            },
            ("pure",),
            SYNTHETIC_OPTIONS,
        ),
    ),
}
"""The fixed covers of the closed-form cases, by ``<data>-<tail>`` of their
sample. Thresholds sit on index values of the samples (rx1day 50, 100, 120,
175; SPEI -1, -1.5, -2, -3; synthetic wind 25, 36 and 60), so the cases test
ADR 0005 §3's boundary rule: a threshold belongs to the more severe side."""

CLOSED_FORM_PRICINGS: Final[Mapping[str, tuple[Fraction, Fraction] | None]] = {
    "pure": None,
    "coc": (Fraction("0.1"), Fraction("0.9")),
}
"""Pricing of the closed-form cases: pure, and a load of rate 0.1 at q 0.9."""


def synthetic_closed_form_sample(data: Dataset) -> ClosedFormSample:
    """Return the synthetic data set's first asset as a closed-form sample.

    These are the draws of the core cases' asset A1, as written there, so the
    closed-form cases put ADR 0005 §6's new metrics on the same realistic
    sample (150 years, 30 % without a storm, basis risk between index and
    loss).
    """
    return ClosedFormSample(
        name=data.name,
        tail="upper",
        hazard_name=data.hazard_name,
        aggregation=data.aggregation,
        index_unit=data.index_unit,
        loss_unit=data.loss_unit,
        period=tuple(int(p) for p in data.period),
        index=tuple(float(x) + 0.0 for x in data.index[:, 0]),
        loss=tuple(float(x) + 0.0 for x in data.loss[:, 0]),
    )


def _param(cover: ClosedFormCover, name: str) -> Fraction:
    """Return a scalar parameter of a fixed cover, exact."""
    value = cover.parameters[name]
    if isinstance(value, tuple):
        raise ValueError(f"{name} of {cover.family} is a scalar")
    return _fraction(value)


def _params(cover: ClosedFormCover, name: str) -> list[Fraction]:
    """Return a vector parameter (knots, levels) of a fixed cover, exact."""
    value = cover.parameters[name]
    if not isinstance(value, tuple):
        raise ValueError(f"{name} of {cover.family} is a vector")
    return [_fraction(v) for v in value]


def _check_closed_form_cover(cover: ClosedFormCover, tail: str) -> None:
    """Validate a hand-set cover as ADR 0005 §3 does at construction.

    Raises
    ------
    ValueError
        If thresholds don't increase in severity, an amount is negative, or
        piecewise-linear levels are not monotone or don't match the knots.
    """
    sign = 1 if tail == "upper" else -1
    if cover.family == F.payout_step:
        breakpoints = [sign * b for b in _params(cover, F.breakpoints)]
        levels = _params(cover, F.levels)
        if (
            len(breakpoints) < 1
            or len(breakpoints) != len(levels)
            or any(b <= a for a, b in itertools.pairwise(breakpoints))
            or any(b < a for a, b in itertools.pairwise(levels))
            or levels[0] < 0
        ):
            raise ValueError(f"invalid step cover {cover.parameters!r}")
    elif cover.family == F.payout_linear:
        a = sign * _param(cover, F.attachment)
        e = sign * _param(cover, F.exhaustion)
        if not a < e or _param(cover, F.limit_param) < 0:
            raise ValueError(f"invalid linear cover {cover.parameters!r}")
    elif cover.family == F.payout_binary:
        _param(cover, F.trigger)
        if _param(cover, F.amount_param) < 0:
            raise ValueError(f"invalid binary cover {cover.parameters!r}")
    elif cover.family == F.payout_piecewise_linear:
        knots = [sign * c for c in _params(cover, F.knots)]
        levels = _params(cover, F.levels)
        if (
            len(knots) < 2
            or len(knots) != len(levels)
            or any(b <= a for a, b in itertools.pairwise(knots))
            or any(b < a for a, b in itertools.pairwise(levels))
            or levels[0] < 0
        ):
            raise ValueError(f"invalid piecewise-linear cover {cover.parameters!r}")
    else:
        raise ValueError(f"no closed form for the payout kind {cover.family!r}")


def _exact_payout(cover: ClosedFormCover, tail: str, x: Fraction) -> Fraction:
    """Return a fixed cover's payout at index value ``x``, exact (ADR 0005 §3).

    On the severity ``s`` (``x`` or ``-x``), with the thresholds mapped the
    same way; a severity equal to a threshold belongs to the more severe
    side.

    * step: ``levels[k]`` for ``b_k <= s < b_{k+1}``, the last level for
      ``s >= b_{n-1}``, 0 for ``s < b_0``;
    * linear: ``limit * clip((s - a) / (e - a), 0, 1)``;
    * binary: ``amount`` for ``s >= t``, else 0;
    * piecewise linear: 0 for ``s < c_0``; the linear interpolation of the
      points ``(c_k, y_k)`` on ``[c_0, c_{m-1}]``; ``y_{m-1}`` for
      ``s >= c_{m-1}``.
    """
    sign = 1 if tail == "upper" else -1
    s = sign * x
    zero = Fraction(0)
    if cover.family == F.payout_step:
        b = [sign * v for v in _params(cover, F.breakpoints)]
        reached = [k for k in range(len(b)) if b[k] <= s]
        return _params(cover, F.levels)[reached[-1]] if reached else zero
    if cover.family == F.payout_linear:
        a = sign * _param(cover, F.attachment)
        e = sign * _param(cover, F.exhaustion)
        share = min(max((s - a) / (e - a), zero), Fraction(1))
        return _param(cover, F.limit_param) * share
    if cover.family == F.payout_binary:
        trigger = sign * _param(cover, F.trigger)
        return _param(cover, F.amount_param) if s >= trigger else zero
    if cover.family == F.payout_piecewise_linear:
        c = [sign * k for k in _params(cover, F.knots)]
        y = _params(cover, F.levels)
        if s < c[0]:
            return zero
        if s >= c[-1]:
            return y[-1]
        k = max(i for i in range(len(c) - 1) if c[i] <= s)
        return y[k] + (y[k + 1] - y[k]) * (s - c[k]) / (c[k + 1] - c[k])
    raise ValueError(f"no closed form for the payout kind {cover.family!r}")


def _payout_document(cover: ClosedFormCover, tail: str) -> dict[str, Any]:
    """Return the payout block of a fixed cover's document (ADR 0005 §3)."""
    document: dict[str, Any] = {F.kind_key: cover.family, F.tail: tail}
    for name, value in cover.parameters.items():
        if isinstance(value, tuple):
            document[name] = [float(v) for v in value]
        else:
            document[name] = float(value)
    if cover.family in (F.payout_piecewise_linear, F.payout_step):
        document[F.monotone] = True
    return document


def _check_binary_with_core(
    cover: ClosedFormCover, sample: ClosedFormSample, payout: NDArray[np.float64]
) -> None:
    """Check a binary payout against the core's one-bin step payout.

    A binary payout is a step payout with one breakpoint, the trigger: the
    core's ``StepPayout`` with ``below_attachment="zero"`` and one bin that
    starts at the trigger, on the severity.
    """
    sign = 1.0 if sample.tail == "upper" else -1.0
    trigger = sign * float(_param(cover, F.trigger))
    core = pid.StepPayout(
        attachment=trigger, limit=trigger + 1.0, n_bins=1, below_attachment="zero"
    )
    severity = sign * np.asarray(sample.index, dtype=np.float64)
    amount = float(_param(cover, F.amount_param))
    core_payout = core.basis_matrix(severity) @ np.array([amount])
    if not np.array_equal(core_payout, payout):
        raise AssertionError("the binary payout differs from the core's one-bin step")


def _check_step_with_core(
    cover: ClosedFormCover, sample: ClosedFormSample, payout: NDArray[np.float64]
) -> None:
    """Check a fixed step payout against the core's ``StepPayout``.

    The core has no lower tail; on the severity ``s = -x``, with breakpoints
    ``-b`` and one more edge above the last (it changes no payout), its
    step payout with ``below_attachment="zero"`` is the module's lower-tail
    step.
    """
    sign = 1.0 if sample.tail == "upper" else -1.0
    edges = [sign * float(b) for b in _params(cover, F.breakpoints)]
    edges.append(edges[-1] + 1.0)
    core = pid.StepPayout(
        attachment=edges[0],
        limit=edges[-1],
        n_bins=len(edges) - 1,
        breakpoints=tuple(edges),
        below_attachment="zero",
    )
    severity = sign * np.asarray(sample.index, dtype=np.float64)
    levels = np.asarray([float(v) for v in _params(cover, F.levels)])
    core_payout = core.basis_matrix(severity) @ levels
    if not np.array_equal(core_payout, payout):
        raise AssertionError("the step payout differs from the core's StepPayout")


def _exact_metrics(
    loss: Sequence[Fraction],
    payout: Sequence[Fraction],
    coc: tuple[Fraction, Fraction] | None,
    options: MetricOptions,
) -> dict[str, Any]:
    """Every metric of ADR 0005 §6, exact, over equally likely draws.

    The premium is priced on the sample: ``E[pi]``, or ``(1 - r) E[pi] + r
    CVaR_q(pi)`` with ``coc = (r, q)``. The columns are those of
    ``options``.
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
    for beta in options.betas:
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
    epsilon = _fraction(options.payout_threshold)
    for threshold in options.loss_thresholds:
        ell = _fraction(threshold)
        big = [lo > ell for lo in loss]
        paid = [pi > epsilon for pi in payout]
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
    for beta in options.betas:
        level = _fraction(beta)
        for base, values in (
            ("uncovered", uncovered),
            ("net_loss", net),
            ("loss", loss),
        ):
            m[metric(f"var_{base}", beta=beta)] = quantile_atoms(values, level)
            m[metric(f"cvar_{base}", beta=beta)] = _exact_cvar(values, level)
    for period in options.return_periods:
        level = _return_level(period)
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
    options: MetricOptions,
) -> None:
    """Check the core's risk measures against the exact values where they overlap.

    VaR and CVaR at every β (``riskmeasures.var_cvar``) and the return-period
    quantiles at every T (``riskmeasures.lower_quantile``).
    """
    p = np.full(loss.size, 1.0 / loss.size)
    scale = max(1.0, float(loss.max()))
    uncovered = np.maximum(loss - payout, 0.0)
    net = loss - payout + premium
    for beta in options.betas:
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
    for base, values in (
        ("loss", loss),
        ("payout", payout),
        ("uncovered", uncovered),
        ("net_loss", net),
    ):
        sorted_x, _, cdf = sorted_cdf(*discrete_distribution(values, p))
        for period in options.return_periods:
            core = lower_quantile(sorted_x, cdf, 1.0 - 1.0 / period)
            atoms = [float(a) for a in m[metric(base, period=period)]]
            _check_atom(f"{base}_rp{label(period)}", core, atoms, scale)
    _check_close(
        "expected_loss", float(p @ loss), float(m[metric("expected_loss")]), scale
    )
    _check_close(
        "expected_payout", float(p @ payout), float(m[metric("expected_payout")]), scale
    )


def closed_form_case(
    sample: ClosedFormSample, cover: ClosedFormCover, pricing_token: str, commit: str
) -> dict[str, Any]:
    """Build a closed-form evaluation case of a fixed cover on one asset.

    Parameters
    ----------
    sample : ClosedFormSample
        The draws.
    cover : ClosedFormCover
        A linear, binary or piecewise-linear cover with the sample's tail.
    pricing_token : {"pure", "coc"}
        The pricing (:data:`CLOSED_FORM_PRICINGS`).
    commit : str
        The generator block's commit.

    Returns
    -------
    dict
        The case document, every metric of ADR 0005 §6 in exact arithmetic.
    """
    _check_closed_form_cover(cover, sample.tail)
    coc = CLOSED_FORM_PRICINGS[pricing_token]
    options = cover.options
    x = [_fraction(v) for v in sample.index]
    loss = [_fraction(v) for v in sample.loss]
    payout = [_exact_payout(cover, sample.tail, xi) for xi in x]
    payout_floats = np.asarray([float(v) for v in payout], dtype=np.float64)
    if cover.family == F.payout_binary:
        _check_binary_with_core(cover, sample, payout_floats)
    if cover.family == F.payout_step:
        _check_step_with_core(cover, sample, payout_floats)
    exact = _exact_metrics(loss, payout, coc, options)
    premium = float(exact[metric("premium")])
    _check_closed_form_with_core(
        exact,
        np.asarray(sample.loss, dtype=np.float64),
        payout_floats,
        premium,
        options,
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
    n = len(sample.period)
    sample_doc = {
        F.asset_ids: ["A1"],
        F.period: list(sample.period),
        F.probability: [1.0 / n] * n,
        F.index: [[float(v)] for v in sample.index],
        F.loss: [[float(v)] for v in sample.loss],
        F.index_unit: sample.index_unit,
        F.loss_unit: sample.loss_unit,
    }
    index_doc = _index_document(
        sample.hazard_name, sample.aggregation, sample.index_unit, sample.tail
    )
    payout_doc = _payout_document(cover, sample.tail)
    family = cover.family.replace("_", "-")
    suffix = "" if options.is_default else "-options"
    return {
        F.case_id: (
            f"{family}-{sample.tail}-fixed-{pricing_token}-{F.scope_individual}-"
            f"{sample.name}{suffix}"
        ),
        F.kind: F.kind_evaluate,
        F.source: F.source_closed_form,
        F.sample: sample_doc,
        F.split: None,
        F.evaluation_sample: None,
        F.cover: _cover_document("A1", index_doc, payout_doc, sample.loss_unit),
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
            F.out_of_sample: None,
            F.profile: None,
        },
        F.metric_options: options.document(),
        F.compare_parameters: F.compare_none,
        F.tolerances: _tolerances(),
        F.generator: _generator(commit),
    }


def closed_form_matrix(
    synthetic: Dataset, short: Dataset
) -> tuple[tuple[ClosedFormSample, ClosedFormCover], ...]:
    """Return every (sample, cover) pair of the closed-form cases, in case order.

    Parameters
    ----------
    synthetic, short : Dataset
        The synthetic data set and its short version; their first asset is
        the realistic sample.
    """
    samples = {
        "handmade-upper": HANDMADE_SAMPLES["upper"],
        "handmade-lower": HANDMADE_SAMPLES["lower"],
        "synthetic-upper": synthetic_closed_form_sample(synthetic),
        "synthetic52-upper": synthetic_closed_form_sample(short),
    }
    return tuple(
        (sample, cover)
        for key, sample in samples.items()
        for cover in CLOSED_FORM_COVERS[key]
    )


# --------------------------------------------------------------------------
# All cases
# --------------------------------------------------------------------------


def datasets() -> tuple[Dataset, Dataset]:
    """Return the synthetic data set and the thesis subsample."""
    synthetic = synthetic_dataset(np.random.default_rng(SYNTHETIC_SEED))
    thesis = thesis_dataset(EventSet.from_parquet(THESIS_EVENTSET))
    return synthetic, thesis


def short_dataset(synthetic: Dataset) -> Dataset:
    """Return the short synthetic data set: asset A1 in the first 52 years.

    The k-fold, fresh-draw, binary and grid-route cases design on it, to keep
    the cases small. Its first storm years hold the three indices set onto
    breakpoints (25, 36 and 60 m/s).
    """
    a1 = synthetic.select(synthetic.asset_ids[:1])
    short = a1.draws(np.arange(N_SHORT_YEARS, dtype=np.int64))
    return replace(short, name=f"synthetic{N_SHORT_YEARS}")


def fresh_dataset() -> Dataset:
    """Return the fresh draws: the synthetic process again, asset A1.

    :data:`N_FRESH_DRAWS` years from ``numpy.random.default_rng(FRESH_SEED)``,
    by :func:`synthetic_dataset` without the indices set onto breakpoints.
    The periods are draw numbers, ``0 .. n - 1``, as in a Monte Carlo sample.
    """
    fresh = synthetic_dataset(
        np.random.default_rng(FRESH_SEED),
        n=N_FRESH_DRAWS,
        on_breakpoints=False,
        name="synthetic-fresh",
    )
    return fresh.select(fresh.asset_ids[:1])


def handmade_dataset(sample: ClosedFormSample, breakpoints: Sequence[float]) -> Dataset:
    """Return a hand-made sample as a data set the core can design on.

    Every year has an event row (its loss may be 0). ``breakpoints`` are the
    step cover's, in index units and in order of increasing severity; the
    core's edges are their severities and one more edge above the last (it
    changes no payout).
    """
    sign = 1.0 if sample.tail == "upper" else -1.0
    edges = [sign * float(b) + 0.0 for b in breakpoints]
    edges.append(edges[-1] + 1.0)
    n = len(sample.period)
    return Dataset(
        name=sample.name,
        asset_ids=("A1",),
        period=np.asarray(sample.period, dtype=np.int64),
        index=np.asarray(sample.index, dtype=np.float64).reshape(n, 1),
        loss=np.asarray(sample.loss, dtype=np.float64).reshape(n, 1),
        event_row=np.ones(n, dtype=np.bool_),
        edges=tuple(edges),
        hazard_name=sample.hazard_name,
        aggregation=sample.aggregation,
        index_unit=sample.index_unit,
        loss_unit=sample.loss_unit,
        values=(float(max(sample.loss)),),
        licence="BSD-3-Clause",
        tail=sample.tail,
    )


def _specs_by_token(
    wanted: Iterable[tuple[str, str]],
) -> list[tuple[ObjectiveSpec, PricingSpec]]:
    """Return the (objective, pricing) specs of some id-token pairs, in order."""
    by_objective = {o.token: o for o in objectives()}
    by_pricing = {p.token: p for p in pricings()}
    return [(by_objective[o], by_pricing[p]) for o, p in wanted]


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
    synthetic, thesis = datasets()
    for data in (synthetic, thesis):
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
        for objective in objectives():
            if objective.token not in HOLDOUT_OBJECTIVES:
                continue
            for pricing in pricings():
                cases.append(
                    design_case(
                        individual,
                        F.scope_individual,
                        objective,
                        pricing,
                        commit,
                        settings,
                        split=SplitSpec(F.split_holdout, train_fraction=TRAIN_FRACTION),
                    )
                )
    short = short_dataset(synthetic)
    for sample, cover in closed_form_matrix(
        synthetic.select(synthetic.asset_ids[:1]), short
    ):
        for token in cover.pricings:
            cases.append(GeneratedCase(closed_form_case(sample, cover, token, commit)))
    for objective, pricing in _specs_by_token(KFOLD_CASES):
        for fold in range(KFOLD_K):
            split = SplitSpec(F.split_kfold, k=KFOLD_K, fold=fold)
            cases.append(
                design_case(
                    short,
                    F.scope_individual,
                    objective,
                    pricing,
                    commit,
                    settings,
                    split=split,
                )
            )
    fresh = fresh_dataset()
    for objective, pricing in _specs_by_token(FRESH_CASES):
        split = SplitSpec(F.split_fresh_draws, fresh=fresh, seed=FRESH_SEED)
        cases.append(
            design_case(
                short,
                F.scope_individual,
                objective,
                pricing,
                commit,
                settings,
                split=split,
            )
        )
    binary = replace(short, edges=binary_edges(BINARY_TRIGGER))
    for objective, pricing in _specs_by_token(BINARY_CASES):
        cases.append(
            design_case(
                binary,
                F.scope_individual,
                objective,
                pricing,
                commit,
                settings,
                family=F.payout_binary,
            )
        )
    for objective, pricing in _specs_by_token(GRID_CASES):
        cases.append(
            grid_design_case(
                short, objective, pricing, commit, settings, grid=GRID_TRIGGERS
            )
        )
    lower = handmade_dataset(HANDMADE_SAMPLES["lower"], LOWER_STEP_BREAKPOINTS)
    for objective, pricing in _specs_by_token(LOWER_STEP_CASES):
        cases.append(
            design_case(lower, F.scope_individual, objective, pricing, commit, settings)
        )
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
    if path[1] == F.objective_value or (
        path[1] == F.profile and path[-1] == F.objective_value
    ):
        objective = case.get(F.objective) or {}
        return scale**2 if objective.get(F.kind_key) == F.objective_mse else scale
    if path[1] == F.metrics and len(path) > 2 and metric_is_unitless(path[2]):
        return 1.0
    if (
        path[1] == F.out_of_sample
        and len(path) > 3
        and path[2] == F.metrics
        and metric_is_unitless(path[3])
    ):
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
    (F.expected, F.out_of_sample, F.metrics),
)
"""The fields that are one solver's point of a set of optimal designs when a
design is not unique: they are judged by :func:`compare_case`, not compared."""


def levels_of(
    document: Mapping[str, Any],
    shape: tuple[int, int],
    names: Sequence[str] | None = None,
) -> NDArray[np.float64]:
    """Return a design case's ``expected.parameters`` as an array of levels.

    Parameters
    ----------
    document : mapping
        A design case.
    shape : tuple of int
        ``(n_assets, n_levels)``.
    names : sequence of str, optional
        The parameter name of each level; default ``levels[k]``.

    Returns
    -------
    numpy.ndarray
        The levels (amounts), one row per asset in ``asset_ids`` order.
    """
    names = [level_name(k) for k in range(shape[1])] if names is None else names
    parameters = document[F.expected][F.parameters]
    if document[F.scope] == F.scope_joint:
        rows = [parameters[a] for a in document[F.sample][F.asset_ids]]
    else:
        rows = [parameters]
    levels = np.array(
        [[float(row[name]) for name in names] for row in rows],
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
       premium and every metric, out of sample too, must agree within
       :data:`REGEN_RTOL_EXACT`.
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
        levels = levels_of(
            committed, generated.identified.shape, generated.amount_names
        )
    except (KeyError, TypeError, ValueError) as exc:
        return [*problems, f"{F.expected}/{F.parameters}: unreadable ({exc!r})"]
    for name, value in (generated.shape_parameters or {}).items():
        # A grid value; the levels are judged at it (evaluate, violations).
        written = committed[F.expected][F.parameters].get(name)
        if written != value:
            problems.append(
                f"{F.expected}/{F.parameters}/{name}: {written!r}, "
                f"regenerated {value!r}"
            )
    evaluated = generated.evaluate(levels)
    keys = (F.objective_value, F.premium, F.metrics, F.out_of_sample)
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
        names = generated.amount_names or tuple(
            level_name(k) for k in range(levels.shape[1])
        )
        for j, k in zip(*np.nonzero(outside), strict=True):
            problems.append(
                f"{F.expected}/{F.parameters}: asset {j} {names[int(k)]} = "
                f"{levels[j, k]!r} outside the range [{low[j, k]!r}, {high[j, k]!r}]"
            )
    return problems


def summary(
    documents: Mapping[str, Mapping[str, Any]], sizes: Mapping[str, int]
) -> str:
    """Return a Markdown table of the cases: kind, source, comparison, size."""
    lines = [
        "| Case | Kind | Source | Scope | Split | Compare parameters | Unique "
        "| Size (bytes) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    total = 0
    for name, doc in documents.items():
        size = sizes[name]
        total += size
        unique = doc[F.expected][F.unique]
        split = doc[F.split]
        lines.append(
            f"| `{doc[F.case_id]}` | {doc[F.kind]} | {doc[F.source]} | "
            f"{doc[F.scope]} | {'—' if split is None else split[F.kind_key]} | "
            f"{doc[F.compare_parameters]} | "
            f"{'—' if unique is None else str(unique).lower()} | {size:,} |"
        )
    lines.append(f"| **Total ({len(documents)} cases)** | | | | | | | **{total:,}** |")
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
