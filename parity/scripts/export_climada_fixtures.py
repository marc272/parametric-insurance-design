r"""Export the golden fixtures of the CLIMADA module from the core (MAR-312).

The module ``climada_petals.engine.parametric`` is built in a fork of
``climada_petals``. Its tests never import this repository's core,
``parametric_insurance_design``, and petals accepts only small test files, so
the parity with the thesis-faithful core is a small set of JSON fixtures plus
closed-form cases. The format is ADR 0006 §12 (accepted 2026-11-10); it reuses
the approach of ``export_crc_fixtures.py`` (MAR-245), at a much smaller size.

Outputs, relative to the repository root (``parity/climada/README.md``
describes the format, how a reader compares against it, and every case):

``parity/climada/samples/<name>.json``
    The shared samples, synthetic or hand-made.
``parity/climada/cases/<case_id>.json``
    One case per file. A case names its sample by file.

Run from the repository root::

    uv run python parity/scripts/export_climada_fixtures.py            # write
    uv run python parity/scripts/export_climada_fixtures.py --check    # diff only

``--check`` regenerates the set in memory and compares it with the committed
files (:func:`compare_case`); it writes nothing and exits with status 1 on a
difference. ``parity/tests/test_climada_fixtures.py`` runs the same comparison
in CI. ``--summary`` prints the table of cases.

How the expected values are computed
------------------------------------
* **Design cases from the core** (``kind = "design"``, ``source = "core"``): a
  step payout with ``below_attachment="zero"``, under MSE, E[U] and weighted
  CVaR, on the event and annual bases, in the individual and portfolio
  (``"joint"``) scopes, under the pure premium and the cost-of-capital load.
  The core builds and solves them (``problem.build_problems``,
  ``solve.solve``) under several solver policies, as in the CRC fixtures:

  - LPs: HiGHS (a vertex) and Clarabel at tight tolerances. Uniqueness comes
    from ranging every identified amount over two near-optimal sets
    (:func:`_lp_ranges`). A unique optimum is written as HiGHS's vertex, a
    non-unique one as Clarabel's interior point.
  - QPs: Clarabel at tight tolerances, written, and OSQP as a check.
    Uniqueness is the rank of the outcome-level Hessian (:func:`_qp_unique`).
  - Unidentified levels follow the rule ``fill="lowest"`` (:func:`_fill_lowest`).

* **Closed-form cases** (``source = "closed_form"``): the families the core
  lacks (linear, piecewise linear, binary, and any lower-tail payout), and the
  event basis with frequencies summing to more than 1, where the core raises.
  This script computes them in exact rational arithmetic from the definitions
  of ADR 0006 §3, §5.1, §6 and §7. A design with one free amount has a closed
  form (:func:`_one_amount_design`); a piecewise-linear MSE design is written
  on a sample whose losses lie on the payout curve, so its optimum is the
  curve itself (:func:`_replication_design`).

The generator uses ``parametric_insurance_design`` alone: the CLIMADA stream
stays free of CRC code and data, and of CLIMADA itself.

Determinism and float formatting
--------------------------------
The synthetic samples come from ``numpy.random.default_rng`` with stated
seeds. Documents are written with sorted keys (:func:`render`). Inputs are
written as stored; computed values are rounded to
:data:`SIGNIFICANT_DIGITS` significant digits, and amounts within ``1e-9`` of
the scale of zero are written as 0. On one machine the output is byte-identical
run to run. Between platforms a solver can return another point of a set of
optimal designs, so :func:`compare_case` judges a non-unique design by what
holds for every point of the set.
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
from typing import Any, Final

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
)
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.records import KpiLevel
from parametric_insurance_design.riskmeasures import (
    discrete_distribution,
    lower_quantile,
    sorted_cdf,
    var_cvar,
)
from parametric_insurance_design.solve import SolverPolicy, is_qp, solve

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SCRIPT_PATH: Final[str] = "parity/scripts/export_climada_fixtures.py"
OUT_DIR: Final[Path] = REPO_ROOT / "parity" / "climada"
CORE_SOURCE: Final[str] = "packages/core/src"
RUN_ID: Final[str] = "mar-312"


# --------------------------------------------------------------------------
# The contract's names, in one place (ADR 0006 §2, §3 and §12, accepted)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Fields:
    """Every field name and fixed value of the documents.

    Renaming a field of the contract means changing it here only.
    """

    # a case (§12)
    case_id: str = "case_id"
    kind: str = "kind"
    source: str = "source"
    sample: str = "sample"
    basis: str = "basis"
    scope: str = "scope"
    cover: str = "cover"
    objective: str = "objective"
    pricing: str = "pricing"
    budget: str = "budget"
    limit: str = "limit"
    expected: str = "expected"
    compare_parameters: str = "compare_parameters"
    tolerances: str = "tolerances"
    generator: str = "generator"
    # basis
    route: str = "route"
    n_years: str = "n_years"
    # a sample (§12)
    event_id: str = "event_id"
    frequency: str = "frequency"
    year: str = "year"
    parent: str = "parent"
    unit_id: str = "unit_id"
    index: str = "index"
    loss: str = "loss"
    index_unit: str = "index_unit"
    loss_unit: str = "loss_unit"
    licence: str = "licence"
    # expected (§12)
    objective_value: str = "objective_value"
    premium: str = "premium"
    parameters: str = "parameters"
    unidentified: str = "unidentified"
    unique: str = "unique"
    metrics: str = "metrics"
    either: str = "either"
    # generator (§12)
    script: str = "script"
    core_version: str = "core_version"
    commit: str = "commit"
    # objective, pricing, budget, limit (§6, §12)
    alpha: str = "alpha"
    beta: str = "beta"
    rate: str = "rate"
    q: str = "q"
    ratio: str = "ratio"
    rule: str = "rule"
    # the cover document: the constructor arguments of §2
    payout: str = "payout"
    payout_unit: str = "payout_unit"
    label: str = "label"
    unit: str = "unit"
    tail: str = "tail"
    index_stat: str = "index_stat"
    weight: str = "weight"
    index_parameters: str = "parameters"
    index_source: str = "source"
    breakpoints: str = "breakpoints"
    levels: str = "levels"
    monotone: str = "monotone"
    attachment: str = "attachment"
    exhaustion: str = "exhaustion"
    limit_amount: str = "limit"
    knots: str = "knots"
    trigger: str = "trigger"
    amount: str = "amount"
    free: str = "free"
    grid: str = "grid"
    lower: str = "lower"
    upper: str = "upper"
    # fixed values
    kind_design: str = "design"
    kind_evaluate: str = "evaluate"
    source_core: str = "core"
    source_closed_form: str = "closed_form"
    basis_event: str = "event"
    basis_annual: str = "annual"
    route_catalogue: str = "catalogue"
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
    payout_piecewise_linear: str = "piecewise_linear"
    payout_binary: str = "binary"
    tail_upper: str = "upper"
    tail_lower: str = "lower"
    limit_largest_loss: str = "largest_loss"
    index_kind_table: str = "table"


F: Final[_Fields] = _Fields()
"""The field names of the documents."""


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------

LICENCE: Final[str] = "CC0-1.0"
"""Licence of every sample (ADR 0006 §12, ``parity/climada/README.md``)."""

BUDGET_RATIO: Final[float] = 0.8
"""Premium budget of the design cases: premium <= 0.8 * E[L]."""
REPLICATION_BUDGET_RATIO: Final[float] = 1.2
"""Budget of the piecewise-linear MSE design: it does not bind (its optimum is
the curve the losses lie on)."""
ALPHA: Final[float] = 0.9
"""Weight of the CVaR term of the weighted-CVaR objective."""
DESIGN_BETA: Final[float] = 0.9
"""Tail level of the weighted-CVaR designs."""
TAIL_EXAMPLE_BETA: Final[float] = 0.99
"""Tail level of the one case ADR 0006 §12 gives as its example. On ``s1`` its
tail is a single year: the worst 1 % is less than one year's weight."""
COC_RATE: Final[float] = 0.06
COC_Q: Final[float] = 0.99

STEP_BREAKPOINTS: Final[tuple[float, ...]] = (25.0, 30.0, 36.0, 43.0, 51.0)
"""Breakpoints (m/s) of the step designs. The module's step has as many
breakpoints as levels; the last level is open above."""
CORE_UPPER_EDGE: Final[float] = 60.0
"""The core's step has one more edge. Values at or above it fall into the last
bin too, so it changes no payout and is not written."""

BETAS: Final[tuple[float, ...]] = (0.9, 0.99)
"""The ``_b<beta>`` columns the cases list: a subset of §7's defaults."""
RETURN_PERIODS: Final[tuple[float, ...]] = (2.0, 10.0, 50.0)
"""The ``_rp<T>`` columns the cases list: a subset of §7's defaults."""
LOSS_THRESHOLD: Final[float] = 0.0
"""The ``_l<threshold>`` columns of the closed-form cases."""
PAYOUT_THRESHOLD: Final[Fraction] = Fraction(0)
"""Epsilon of the rates and of ``payout_frequency`` (§7's default)."""

TOLERANCE: Final[float] = 1e-6
"""The tolerance of the contract, stated once (ADR 0006 §12): objective values,
premiums and metrics agree within it, relative; parameters within it times the
scale, absolute. The prototype's parity test uses the same ``RTOL``."""

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
"""Near-optimal tolerances of the ranging LPs (:class:`_Ranges`)."""
PINNED_SHRINK: Final[float] = 0.5
"""An amount whose narrow range is at most this share of its wide one is
pinned: the range is the tolerance's, not an optimal set's."""
PINNED_WIDTH: Final[float] = 1e-7
"""An amount whose narrow range is below this fraction of the scale is pinned."""
UNIQUE_WIDTH: Final[float] = 1e-6
"""Agreement, as a fraction of the scale, of two solvers' amounts at a unique
optimum, and the padding of the ranges an interior solution must lie in."""
EIGEN_RTOL: Final[float] = 1e-10
"""A QP is unique when the smallest eigenvalue of its Hessian on the identified
amounts exceeds this times the largest."""
SELF_CHECK_RTOL: Final[float] = 1e-12
"""Agreement required between the core and this script's own arithmetic."""
REGEN_RTOL_SOLVED: Final[float] = 1e-6
"""Regeneration check: relative tolerance of values that come from a solve."""
REGEN_RTOL_EXACT: Final[float] = 1e-12
"""Regeneration check: relative tolerance of every other float."""

HIGHS_RANGING_OPTIONS: Final[Mapping[str, float]] = {
    "primal_feasibility_tolerance": 1e-10,
    "dual_feasibility_tolerance": 1e-10,
}
"""HiGHS options of the ranging LPs (its defaults are 1e-7)."""
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
"""Clarabel at tight tolerances: written QP solutions, non-unique LP solutions."""
LP_VERTEX_POLICY: Final[SolverPolicy] = SolverPolicy(
    lp_solvers=("HIGHS",), qp_solvers=("CLARABEL",), accept_inaccurate=False
)
"""HiGHS for the LPs: its simplex returns a vertex."""
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


@dataclass(frozen=True)
class SolverSettings:
    """The solver policies of one generation run.

    A test passes other settings to check that the regeneration check does not
    depend on which point of a set of optimal designs a solver returns.
    """

    accurate: SolverPolicy = ACCURATE_POLICY
    vertex: SolverPolicy = LP_VERTEX_POLICY
    qp_check: SolverPolicy = QP_CHECK_POLICY
    ranging: Mapping[str, float | int] = field(
        default_factory=lambda: dict(HIGHS_RANGING_OPTIONS)
    )


# --------------------------------------------------------------------------
# Labels and values
# --------------------------------------------------------------------------


def label(value: float) -> str:
    """Return the column label of a parameter value (ADR 0006 §7).

    Parameters
    ----------
    value : float
        A metric parameter.

    Returns
    -------
    str
        The decimal text with trailing zeros removed and the point written as
        an underscore: 0.99 gives ``0_99``, 100.0 gives ``100``.
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
    """Return a metric column name of ADR 0006 §7.

    Parameters
    ----------
    base : str
        The metric, e.g. ``"var_uncovered"``.
    beta, period, threshold : float, optional
        At most one: the level, the return period or the loss threshold.

    Returns
    -------
    str
        The column, e.g. ``"var_uncovered_b0_9"``.
    """
    if beta is not None:
        return f"{base}_b{label(beta)}"
    if period is not None:
        return f"{base}_rp{label(period)}"
    if threshold is not None:
        return f"{base}_l{label(threshold)}"
    return base


def level_name(index: int) -> str:
    """Return the flat parameter name of a level (ADR 0006 §12)."""
    return f"{F.levels}[{index}]"


def out(value: float | Fraction) -> float:
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


def exact(value: float) -> Fraction:
    """Return the exact value of a decimal input such as 0.0625."""
    return Fraction(str(value))


# --------------------------------------------------------------------------
# Bases, samples and outcomes (ADR 0006 §5.1)
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class BasisSpec:
    """The basis of a case: the event basis, or catalogue years.

    Attributes
    ----------
    kind : str
        :attr:`_Fields.basis_event` or :attr:`_Fields.basis_annual`.
    n_years : int, optional
        The years of the catalogue route.
    """

    kind: str
    n_years: int | None = None

    @property
    def is_event(self) -> bool:
        """Whether this is the event basis."""
        return self.kind == F.basis_event

    @property
    def core(self) -> Basis:
        """The core's basis of the same name."""
        return Basis.EVENT if self.is_event else Basis.ANNUAL

    def document(self) -> dict[str, Any]:
        """Return the case's ``basis`` block."""
        if self.is_event:
            return {F.kind: F.basis_event}
        return {
            F.kind: F.basis_annual,
            F.route: F.route_catalogue,
            F.n_years: self.n_years,
        }


EVENT_BASIS: Final[BasisSpec] = BasisSpec(F.basis_event)


@dataclass(frozen=True, eq=False)
class Outcomes:
    """The outcomes of a sample under a basis (ADR 0006 §5.1).

    Attributes
    ----------
    groups : tuple of tuple of int
        The events of each outcome, as positions. On the annual basis one
        outcome per year, years without an event included. On the event basis
        one outcome per event, and an empty last outcome for the missing mass
        where the frequencies sum to less than 1.
    weights : tuple of Fraction
        The weight of each outcome, exact.
    missing_mass : bool
        Whether the last outcome is the missing mass of the event basis.
    """

    groups: tuple[tuple[int, ...], ...]
    weights: tuple[Fraction, ...]
    missing_mass: bool

    def summed(self, per_event: Sequence[Any]) -> list[Any]:
        """Sum per-event values into outcomes; an empty outcome gets 0."""
        return [
            sum((per_event[e] for e in group), Fraction(0)) for group in self.groups
        ]

    def float_weights(self) -> NDArray[np.float64]:
        """Return the weights as floats."""
        return np.array([float(w) for w in self.weights], dtype=np.float64)

    def kept(self) -> list[bool]:
        """Return which outcomes are events of the file (§7, the FPR's denominator)."""
        return [not (self.missing_mass and not g) for g in self.groups]


@dataclass(frozen=True, eq=False)
class SampleData:
    """One shared sample: ``samples/<name>.json`` (ADR 0006 §12).

    Attributes
    ----------
    name : str
        The file's stem; the last part of a case id.
    event_id : tuple of int
        Event ids.
    frequency : tuple of float
        Frequency of each event, per year; decimals, exact in ``str``.
    year : tuple of int, optional
        Catalogue year of each event; None if the sample has none.
    unit_id : tuple of str
        Units, in column order.
    index, loss : numpy.ndarray
        Shape ``(n_events, n_units)``.
    index_unit, loss_unit : str
        Units of measure.
    tail : str
        The tail of the sample's covers.
    """

    name: str
    event_id: tuple[int, ...]
    frequency: tuple[float, ...]
    year: tuple[int, ...] | None
    unit_id: tuple[str, ...]
    index: NDArray[np.float64]
    loss: NDArray[np.float64]
    index_unit: str
    loss_unit: str
    tail: str = F.tail_upper

    def __post_init__(self) -> None:
        """Check that the fields fit together."""
        n, m = len(self.event_id), len(self.unit_id)
        if self.index.shape != (n, m) or self.loss.shape != (n, m):
            raise ValueError(f"{self.name}: index and loss must have shape {(n, m)}")
        if len(self.frequency) != n or len(set(self.event_id)) != n:
            raise ValueError(f"{self.name}: event ids and frequencies do not fit")
        if self.year is not None and len(self.year) != n:
            raise ValueError(f"{self.name}: years do not fit")

    @property
    def n_events(self) -> int:
        """Number of events."""
        return len(self.event_id)

    @property
    def total_frequency(self) -> Fraction:
        """Sum of the frequencies, exact."""
        return sum((exact(f) for f in self.frequency), Fraction(0))

    @property
    def scale(self) -> float:
        """The scale of the set: the largest total loss of one event, at least 1."""
        return max(1.0, float(self.loss.sum(axis=1).max()))

    def outcomes(self, basis: BasisSpec) -> Outcomes:
        """Return the outcomes and their exact weights under ``basis``."""
        if basis.is_event:
            groups = [(e,) for e in range(self.n_events)]
            weights = [exact(f) for f in self.frequency]
            rest = 1 - sum(weights, Fraction(0))
            if rest > 0:
                return Outcomes(
                    tuple([*groups, ()]), tuple([*weights, rest]), missing_mass=True
                )
            return Outcomes(tuple(groups), tuple(weights), missing_mass=False)
        if self.year is None or basis.n_years is None:
            raise ValueError(f"{self.name}: the annual basis needs years")
        n_years = basis.n_years
        if not all(0 <= y < n_years for y in self.year):
            raise ValueError(f"{self.name}: a year is outside the catalogue")
        if any(exact(f) != Fraction(1, n_years) for f in self.frequency):
            raise ValueError(f"{self.name}: annual frequencies must be 1 / n_years")
        by_year: dict[int, list[int]] = {}
        for e, y in enumerate(self.year):
            by_year.setdefault(y, []).append(e)
        groups_y = tuple(tuple(by_year.get(y, ())) for y in range(n_years))
        return Outcomes(groups_y, (Fraction(1, n_years),) * n_years, missing_mass=False)

    def document(self) -> dict[str, Any]:
        """Return the sample's JSON document."""
        return {
            F.event_id: list(self.event_id),
            F.frequency: list(self.frequency),
            F.year: None if self.year is None else list(self.year),
            F.parent: None,
            F.unit_id: list(self.unit_id),
            F.index: [[float(x) + 0.0 for x in row] for row in self.index],
            F.loss: [[float(x) + 0.0 for x in row] for row in self.loss],
            F.index_unit: self.index_unit,
            F.loss_unit: self.loss_unit,
            F.licence: LICENCE,
        }


def quantile_atoms(
    values: Sequence[Any], weights: Sequence[Fraction], level: Fraction
) -> tuple[Any, ...]:
    """Return ``VaR_level``, or both atoms when the level lies on a step.

    ADR 0006 §5.1: the smallest ``x`` whose exceedance weight is at most ``1 -
    level``. The weights are exact, so a level exactly on a step is known, and
    then a floating-point sum can land on either side of it: both neighbouring
    atoms are returned, the lower first.

    Parameters
    ----------
    values : sequence of float or Fraction
        Outcome values.
    weights : sequence of Fraction
        Their weights.
    level : Fraction
        The level, in ``(0, 1)``.

    Returns
    -------
    tuple
        ``(quantile,)`` or ``(lower_atom, upper_atom)``.
    """
    mass: dict[Any, Fraction] = {}
    for value, weight in zip(values, weights, strict=True):
        mass[value] = mass.get(value, Fraction(0)) + weight
    atoms = sorted(mass)
    allowed = 1 - level
    above = sum(mass.values(), Fraction(0))
    for i, atom in enumerate(atoms):
        above -= mass[atom]
        if above <= allowed:
            if above == allowed and i + 1 < len(atoms):
                return (atom, atoms[i + 1])
            return (atom,)
    return (atoms[-1],)


def exact_cvar(
    values: Sequence[Any], weights: Sequence[Fraction], level: Fraction
) -> Any:  # noqa: ANN401
    """``CVaR = VaR + E[(X - VaR)^+] / (1 - level)`` (ADR 0006 §5.1)."""
    var = quantile_atoms(values, weights, level)[0]
    excess = sum(
        (w * max(v - var, 0) for v, w in zip(values, weights, strict=True)),
        Fraction(0),
    )
    return var + excess / (1 - level)


def tail_weights(
    values: Sequence[Fraction], weights: Sequence[Fraction], level: Fraction
) -> list[Fraction]:
    """Return the CVaR weights of ``values`` (ADR 0005 §6, "Tail weights")."""
    var = quantile_atoms(values, weights, level)[0]
    above = sum(
        (w for v, w in zip(values, weights, strict=True) if v > var), Fraction(0)
    )
    at = sum((w for v, w in zip(values, weights, strict=True) if v == var), Fraction(0))
    remaining = (1 - level) - above
    return [
        w if v > var else (remaining * w / at if v == var else Fraction(0))
        for v, w in zip(values, weights, strict=True)
    ]


def _metric_value(atoms: Sequence[Any]) -> float | dict[str, list[float]]:
    """Return a VaR-type metric: one value, or ``{"either": [lower, upper]}``."""
    if len(atoms) == 1:
        return out(atoms[0])
    return {F.either: [out(atoms[0]), out(atoms[1])]}


# --------------------------------------------------------------------------
# The samples
# --------------------------------------------------------------------------

S1_SEED: Final[int] = 20261110
"""Seed of ``s1`` (``numpy.random.default_rng``)."""
S2_SEED: Final[int] = 20261111
"""Seed of ``s2``."""
S1_YEARS: Final[int] = 40
S1_EVENTS: Final[int] = 32
S2_EVENTS: Final[int] = 30
S2_FREQUENCIES: Final[tuple[float, ...]] = (0.01, 0.02, 0.025, 0.04, 0.05)
SYNTHETIC_UNITS: Final[tuple[str, ...]] = ("u1", "u2")
SYNTHETIC_VALUES: Final[NDArray[np.float64]] = np.array([10_000_000.0, 6_000_000.0])


def _storms(
    rng: np.random.Generator, n: int
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return ``n`` synthetic storms: index (m/s) and loss (USD) at the two units.

    A storm has intensity 22 + Gamma(2, 7). The hazard at ``u1`` adds N(0, 3);
    at ``u2`` it is 0.85 of the intensity plus N(0, 3). The loss is the unit's
    value times v³ / (1 + v³), v = max(h - 25.7, 0) / 49. The index is the
    hazard plus another N(0, 3), floored at 0, so index and loss differ.
    Indices are rounded to 0.01 m/s and losses to whole USD.
    """
    storm = 22.0 + rng.gamma(2.0, 7.0, n)
    hazard = np.column_stack(
        [storm + rng.normal(0.0, 3.0, n), 0.85 * storm + rng.normal(0.0, 3.0, n)]
    )
    index = np.round(np.maximum(hazard + rng.normal(0.0, 3.0, (n, 2)), 0.0), 2)
    v = np.maximum(hazard - 25.7, 0.0) / 49.0
    damage = v**3 / (1.0 + v**3)
    return index + 0.0, np.round(SYNTHETIC_VALUES * damage) + 0.0


def s1_sample() -> SampleData:
    """Return ``s1``: 32 events in 40 years, several in some years, two units.

    Every frequency is 1/40, so the sample fits the annual basis and, summing
    to 0.8, the core's event basis. Five indices sit exactly on breakpoints,
    and the index of ``u2`` stays below the last one, so its last level is
    unidentified.
    """
    rng = np.random.default_rng(S1_SEED)
    year = np.sort(rng.integers(0, S1_YEARS, S1_EVENTS))
    index, loss = _storms(rng, S1_EVENTS)
    index[3, 0], index[4, 0], index[5, 0] = 25.0, 36.0, 51.0
    index[6, 1], index[7, 1] = 30.0, 43.0
    index[:, 1] = np.minimum(index[:, 1], 50.5)
    return SampleData(
        name="s1",
        event_id=tuple(1001 + 7 * i for i in range(S1_EVENTS)),
        frequency=(1.0 / S1_YEARS,) * S1_EVENTS,
        year=tuple(int(y) for y in year),
        unit_id=SYNTHETIC_UNITS,
        index=index,
        loss=loss,
        index_unit="m/s",
        loss_unit="USD",
    )


def s2_sample() -> SampleData:
    """Return ``s2``: 30 events with non-uniform frequencies summing to below 1.

    It has no years, so it fits the event basis only.

    Raises
    ------
    ValueError
        If the frequencies sum to more than 1 (the core's event basis needs
        at most 1).
    """
    rng = np.random.default_rng(S2_SEED)
    choices = rng.integers(0, len(S2_FREQUENCIES), S2_EVENTS)
    frequency = tuple(S2_FREQUENCIES[int(c)] for c in choices)
    index, loss = _storms(rng, S2_EVENTS)
    index[2, 0], index[8, 0] = 30.0, 43.0
    index[5, 1] = 36.0
    sample = SampleData(
        name="s2",
        event_id=tuple(2003 + 11 * i for i in range(S2_EVENTS)),
        frequency=frequency,
        year=None,
        unit_id=SYNTHETIC_UNITS,
        index=index,
        loss=loss,
        index_unit="m/s",
        loss_unit="USD",
    )
    if sample.total_frequency > 1:
        raise ValueError("s2's frequencies must sum to at most 1")
    return sample


def _table(*rows: Sequence[float]) -> NDArray[np.float64]:
    """Return hand-made rows as an array of shape ``(n_events, n_units)``."""
    return np.array(rows, dtype=np.float64)


def h1_sample() -> SampleData:
    """Return ``h1``: hand-made, 14 events in 16 years, one unit.

    Years 3 and 8 hold two events, one large and one small, so an over-payment
    in one and a shortfall in the other don't offset. Thresholds of the covers
    sit on index values.
    """
    year = (0, 1, 2, 3, 3, 4, 6, 7, 8, 8, 10, 11, 13, 14)
    index = (40, 64, 50, 175, 80, 30, 120, 100, 210, 64, 90, 150, 55, 260)
    loss = (0, 120, 20, 900, 60, 15, 300, 150, 1500, 40, 0, 650, 30, 1800)
    return SampleData(
        name="h1",
        event_id=tuple(range(31, 45)),
        frequency=(0.0625,) * 14,
        year=year,
        unit_id=("u1",),
        index=_table(*[[float(x)] for x in index]),
        loss=_table(*[[float(x)] for x in loss]),
        index_unit="mm/day",
        loss_unit="EUR",
    )


def h2_sample() -> SampleData:
    """Return ``h2``: hand-made, 12 events whose frequencies sum to 3.2, one unit.

    The core raises on it. The rows are out of order of severity. From the top
    of the severity the cumulative frequency passes through 0.02, 0.1 and 0.5:
    the tail levels of the cases, so those quantiles lie on steps.
    """
    rows = (
        (100, 150, 0.1),
        (20, 0, 0.8),
        (260, 1800, 0.005),
        (64, 40, 0.4),
        (175, 900, 0.03),
        (50, 0, 0.5),
        (210, 1500, 0.005),
        (35, 10, 0.75),
        (150, 650, 0.05),
        (90, 0, 0.25),
        (120, 300, 0.3),
        (190, 1200, 0.01),
    )
    return SampleData(
        name="h2",
        event_id=tuple(51 + i for i in range(len(rows))),
        frequency=tuple(r[2] for r in rows),
        year=None,
        unit_id=("u1",),
        index=_table(*[[float(r[0])] for r in rows]),
        loss=_table(*[[float(r[1])] for r in rows]),
        index_unit="mm/day",
        loss_unit="EUR",
    )


def h3_sample() -> SampleData:
    """Return ``h3``: hand-made, 8 events, two units, frequencies summing to 2.0."""
    rows = (
        (32, 26, 100, 0, 0.6),
        (45, 30, 800, 150, 0.4),
        (28, 52, 40, 900, 0.3),
        (61, 44, 2500, 700, 0.1),
        (36, 36, 300, 300, 0.25),
        (22, 18, 0, 0, 0.2),
        (51, 38, 1400, 350, 0.1),
        (30, 25, 120, 50, 0.05),
    )
    return SampleData(
        name="h3",
        event_id=tuple(71 + 3 * i for i in range(len(rows))),
        frequency=tuple(r[4] for r in rows),
        year=None,
        unit_id=SYNTHETIC_UNITS,
        index=_table(*[[float(r[0]), float(r[1])] for r in rows]),
        loss=_table(*[[float(r[2]), float(r[3])] for r in rows]),
        index_unit="m/s",
        loss_unit="USD",
    )


def h4_sample() -> SampleData:
    """Return ``h4``: hand-made drought index (lower tail), 12 events in 20 years."""
    index = (0.5, -0.4, -1.0, -1.2, -1.5, -1.8, -2.0, -2.4, -3.0, -3.5, -0.9, -0.2)
    loss = (0, 0, 30, 60, 120, 200, 350, 600, 900, 1100, 20, 0)
    year = (1, 2, 4, 5, 6, 8, 9, 11, 12, 14, 16, 18)
    return SampleData(
        name="h4",
        event_id=tuple(201 + i for i in range(12)),
        frequency=(0.05,) * 12,
        year=year,
        unit_id=("u1",),
        index=_table(*[[x] for x in index]),
        loss=_table(*[[float(x)] for x in loss]),
        index_unit="1",
        loss_unit="EUR",
        tail=F.tail_lower,
    )


def h5_sample() -> SampleData:
    """Return ``h5``: losses lie on a piecewise-linear curve, 10 events in 20 years.

    The curve is the one of :data:`H5_PIECEWISE`, with nothing below its first
    knot, so a piecewise-linear MSE design has the curve as its optimum.
    """
    index = (40.0, 50.0, 65.0, 80.0, 100.0, 120.0, 147.5, 175.0, 200.0, 45.0)
    loss = (0.0, 50.0, 150.0, 250.0, 475.0, 700.0, 950.0, 1200.0, 1200.0, 0.0)
    year = (0, 2, 3, 5, 7, 8, 11, 13, 16, 18)
    return SampleData(
        name="h5",
        event_id=tuple(301 + i for i in range(10)),
        frequency=(0.05,) * 10,
        year=year,
        unit_id=("u1",),
        index=_table(*[[x] for x in index]),
        loss=_table(*[[x] for x in loss]),
        index_unit="mm/day",
        loss_unit="EUR",
    )


def core_eventset(sample: SampleData, basis: BasisSpec) -> EventSet:
    """Build the core's EventSet of a sample: one row per event.

    Parameters
    ----------
    sample : SampleData
        The sample.
    basis : BasisSpec
        The annual basis uses the sample's years. The event basis needs a year
        structure only formally, so it gets one year.

    Returns
    -------
    EventSet
        Its rates are the sample's frequencies.
    """
    n = sample.n_events
    if basis.is_event:
        n_years, years = 1, np.zeros(n, dtype=np.int64)
    elif basis.n_years is not None and sample.year is not None:
        n_years, years = basis.n_years, np.asarray(sample.year, dtype=np.int64)
    else:
        raise ValueError(f"{sample.name}: the annual basis needs years")
    events = pd.DataFrame(
        {
            "event_id": [f"{sample.name}-{e}" for e in sample.event_id],
            "year": years,
            "rate": np.asarray(sample.frequency, dtype=np.float64),
            "draw_id": np.zeros(n, dtype=np.int64),
            "scenario_id": [sample.name] * n,
        }
    )
    m = len(sample.unit_id)
    locations = pd.DataFrame(
        {
            "location_id": list(sample.unit_id),
            "lat": [0.0] * m,
            "lon": [float(j) for j in range(m)],
            "value": [float(v) for v in SYNTHETIC_VALUES[:m]],
            "name": list(sample.unit_id),
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name=sample.name, release="MAR-312 synthetic sample"),
        index=IndexDefinition(definition="synthetic", unit=sample.index_unit),
        loss=LossDefinition(unit=sample.loss_unit, currency=sample.loss_unit),
        n_years=n_years,
        scenario=f"MAR-312 fixture sample {sample.name}",
        provenance=Provenance(
            producer=SCRIPT_PATH,
            producer_version=pid.__version__,
            created_at=datetime(2026, 11, 10, tzinfo=UTC),
        ),
        licence=LICENCE,
    )
    return EventSet(
        events, locations, sample.index.copy(), sample.loss.copy(), metadata
    )


# --------------------------------------------------------------------------
# Payouts and covers (ADR 0006 §3)
# --------------------------------------------------------------------------


def free_amount() -> dict[str, Any]:
    """Return the marker of a free amount: ``Free(lower=0.0)``."""
    return {F.free: {F.grid: None, F.lower: 0.0, F.upper: None}}


@dataclass(frozen=True)
class Payout:
    """A payout function with its thresholds and amounts, in index units.

    Attributes
    ----------
    family : str
        ``"step"``, ``"linear"``, ``"piecewise_linear"`` or ``"binary"``.
    tail : str
        ``"upper"`` or ``"lower"``.
    thresholds : tuple of float
        Step: breakpoints. Linear: attachment, exhaustion. Piecewise linear:
        knots. Binary: the trigger. In order of increasing severity.
    amounts : tuple of float
        Step and piecewise linear: levels. Linear: the limit. Binary: the
        amount.
    """

    family: str
    tail: str
    thresholds: tuple[float, ...]
    amounts: tuple[float, ...]

    @property
    def token(self) -> str:
        """The payout's part of a case id."""
        family = self.family.replace("_", "-")
        return family if self.tail == F.tail_upper else f"{family}-{self.tail}"

    @property
    def amount_names(self) -> tuple[str, ...]:
        """The flat names of the amounts (ADR 0006 §12)."""
        if self.family == F.payout_linear:
            return (F.limit_amount,)
        if self.family == F.payout_binary:
            return (F.amount,)
        return tuple(level_name(k) for k in range(len(self.amounts)))

    def document(self, *, free: bool = False) -> dict[str, Any]:
        """Return the payout document, with free amounts if ``free``."""
        amounts: list[Any] = (
            [free_amount() for _ in self.amounts] if free else list(self.amounts)
        )
        thresholds = list(self.thresholds)
        doc: dict[str, Any] = {F.kind: self.family, F.tail: self.tail}
        if self.family == F.payout_step:
            doc |= {F.breakpoints: thresholds, F.levels: amounts, F.monotone: True}
        elif self.family == F.payout_linear:
            doc |= {
                F.attachment: thresholds[0],
                F.exhaustion: thresholds[1],
                F.limit_amount: amounts[0],
            }
        elif self.family == F.payout_piecewise_linear:
            doc |= {F.knots: thresholds, F.levels: amounts, F.monotone: True}
        elif self.family == F.payout_binary:
            doc |= {F.trigger: thresholds[0], F.amount: amounts[0]}
        else:
            raise ValueError(f"unknown family {self.family!r}")
        return doc

    def basis(self, x: Fraction) -> list[Fraction]:
        """Return the payout's basis at index ``x``: linear in the amounts, exact.

        Parameters
        ----------
        x : Fraction
            An index value.

        Returns
        -------
        list of Fraction
            One value per amount; the payout is their product with the amounts.
        """
        sign = 1 if self.tail == F.tail_upper else -1
        s = sign * x
        points = [sign * exact(t) for t in self.thresholds]
        n = len(self.amounts)
        zero, one = Fraction(0), Fraction(1)
        out_basis = [zero] * n
        if self.family == F.payout_binary:
            out_basis[0] = one if s >= points[0] else zero
        elif self.family == F.payout_linear:
            share = (s - points[0]) / (points[1] - points[0])
            out_basis[0] = min(max(share, zero), one)
        elif self.family == F.payout_step:
            k = sum(1 for b in points if s >= b) - 1
            if k >= 0:
                out_basis[k] = one
        elif self.family == F.payout_piecewise_linear:
            k = sum(1 for c in points if s >= c) - 1
            if k >= n - 1:
                out_basis[n - 1] = one
            elif k >= 0:
                share = (s - points[k]) / (points[k + 1] - points[k])
                out_basis[k], out_basis[k + 1] = 1 - share, share
        else:
            raise ValueError(f"unknown family {self.family!r}")
        return out_basis

    def exact_amounts(self) -> list[Fraction]:
        """Return the amounts as exact values."""
        return [exact(a) for a in self.amounts]


def cover_document(
    sample: SampleData,
    payout: Mapping[str, Any],
    limit: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Return the cover document: the constructor arguments of ADR 0006 §2.

    Parameters
    ----------
    sample : SampleData
        Its units, and the index's unit and tail.
    payout : mapping
        One payout document for every unit, or a mapping by unit id.
    limit : mapping, optional
        The limit's document.

    Returns
    -------
    dict
        ``ParametricCover``'s fields, with the ``IndexDefinition`` nested.
    """
    return {
        F.index: {
            F.kind: F.index_kind_table,
            F.unit: sample.index_unit,
            F.tail: sample.tail,
            F.index_stat: None,
            F.weight: None,
            F.index_source: "synthetic",
            F.index_parameters: None,
        },
        F.payout: dict(payout),
        F.unit_id: list(sample.unit_id),
        F.payout_unit: sample.loss_unit,
        F.limit: None if limit is None else dict(limit),
        F.label: None,
    }


def _tolerances() -> dict[str, float]:
    return {
        F.objective_value: TOLERANCE,
        F.premium: TOLERANCE,
        F.metrics: TOLERANCE,
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
    """Return the last commit that changed the core's source, ``+dirty`` if edited."""
    commit = _git("log", "-1", "--format=%H", "--", CORE_SOURCE)
    if not commit:
        return "unknown"
    status = _git("status", "--porcelain", "--", CORE_SOURCE)
    return f"{commit}+dirty" if status else commit


def _generator(commit: str) -> dict[str, str]:
    return {F.script: SCRIPT_PATH, F.core_version: pid.__version__, F.commit: commit}


# --------------------------------------------------------------------------
# Objectives and pricing of the case matrix
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ObjectiveSpec:
    """One objective: its id token, core object and document."""

    token: str
    core: Objective
    document: Mapping[str, Any]


@dataclass(frozen=True)
class PricingSpec:
    """One pricing: its id token, core object, document and exact parameters."""

    token: str
    core: Pricing
    document: Mapping[str, Any]
    coc: tuple[Fraction, Fraction] | None


def _weighted_cvar(beta: float) -> ObjectiveSpec:
    """Return the weighted CVaR at tail level ``beta``."""
    return ObjectiveSpec(
        f"wcvar-b{label(beta)}",
        pid.WeightedCVaR(alpha=ALPHA, beta=beta),
        {F.kind: F.objective_weighted_cvar, F.alpha: ALPHA, F.beta: beta},
    )


def objectives() -> dict[str, ObjectiveSpec]:
    """Return MSE, expected uncovered loss and the weighted CVaRs by short name."""
    return {
        "mse": ObjectiveSpec("mse", pid.MSE(), {F.kind: F.objective_mse}),
        "eu": ObjectiveSpec(
            "eu", pid.ExpectedUncovered(), {F.kind: F.objective_expected_uncovered}
        ),
        "wcvar": _weighted_cvar(DESIGN_BETA),
        "wcvar-b0_99": _weighted_cvar(TAIL_EXAMPLE_BETA),
    }


def pricings() -> dict[str, PricingSpec]:
    """Return the pure premium and the cost-of-capital load by id token."""
    return {
        "pure": PricingSpec("pure", pid.PurePremium(), {F.kind: F.pricing_pure}, None),
        "coc": PricingSpec(
            "coc",
            pid.CostOfCapitalLoad(rate=COC_RATE, q=COC_Q),
            {F.kind: F.pricing_cost_of_capital, F.rate: COC_RATE, F.q: COC_Q},
            (exact(COC_RATE), exact(COC_Q)),
        ),
    }


def _objective_value(
    objective: Objective,
    outcomes: Outcomes,
    loss: NDArray[np.float64],
    payout: NDArray[np.float64],
) -> float:
    """Return the objective at per-event loss and payout (ADR 0006 §6.2)."""
    p = outcomes.float_weights()
    uncovered = np.maximum(loss - payout, 0.0)
    loss_o = np.array(outcomes.summed(loss.tolist()), dtype=np.float64)
    payout_o = np.array(outcomes.summed(payout.tolist()), dtype=np.float64)
    uncovered_o = np.array(outcomes.summed(uncovered.tolist()), dtype=np.float64)
    if isinstance(objective, pid.MSE):
        return float(p @ (loss_o - payout_o) ** 2)
    if isinstance(objective, pid.ExpectedUncovered):
        return float(p @ uncovered_o)
    if isinstance(objective, pid.WeightedCVaR):
        _, cvar = var_cvar(uncovered_o, p, objective.beta)
        return objective.alpha * cvar + (1.0 - objective.alpha) * float(p @ uncovered_o)
    raise TypeError(f"no objective formula for {objective!r}")


# --------------------------------------------------------------------------
# Core metrics
# --------------------------------------------------------------------------


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


def step_values(
    index: NDArray[np.float64], levels: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Return the step payout at each event (ADR 0006 §3, upper tail)."""
    edges = np.asarray(STEP_BREAKPOINTS, dtype=np.float64)
    k = (np.searchsorted(edges, index, side="right") - 1).astype(np.intp)
    return np.where(k < 0, 0.0, levels[np.maximum(k, 0)])


def core_metrics(
    sample: SampleData,
    basis: BasisSpec,
    eventset: EventSet,
    scope: Scope,
    results: Sequence[SolveResult],
    pricing: Pricing,
    problem_units: Sequence[tuple[int, ...]],
) -> dict[str, dict[str, Any]]:
    """Compute the metrics of every design problem with the core.

    Every value comes from the core: ``evaluate.kpis``,
    ``evaluate.exceedance_curves`` and ``riskmeasures.var_cvar``. This script
    recomputes the plain ones and the quantile atoms from the sample's layout
    and requires agreement, so the sample's outcomes and the core's match.

    Parameters
    ----------
    sample : SampleData
        The sample.
    basis : BasisSpec
        The basis.
    eventset : EventSet
        The core's data.
    scope : Scope
        The scope of the results.
    results : sequence of SolveResult
        One result per design problem.
    pricing : Pricing
        The pricing of the premium.
    problem_units : sequence of tuple of int
        The unit positions of each design problem.

    Returns
    -------
    dict
        Problem id -> column -> value; None for an undefined value;
        ``{"either": [lower, upper]}`` for a quantile on a step.
    """
    outcomes = sample.outcomes(basis)
    weights = outcomes.weights
    p = outcomes.float_weights()
    tables = {
        beta: kpis(
            eventset,
            scope,
            results,
            basis=basis.core,
            beta=beta,
            run_id=RUN_ID,
            pricing=pricing,
        )
        for beta in BETAS
    }
    ev = evaluate_results(eventset, scope, results, basis=basis.core)
    measure = ev.measure
    curves = exceedance_curves(
        eventset,
        scope,
        results,
        basis=basis.core,
        run_id=RUN_ID,
        return_periods=RETURN_PERIODS,
    )
    curves = curves[curves["curve"] == ("event" if basis.is_event else "aep")]
    scale = sample.scale
    found: dict[str, dict[str, Any]] = {}

    def kpi_row(beta: float, problem_id: str, name: str) -> float | None:
        table = tables[beta]
        rows = table[
            (table["level"] == KpiLevel.PROBLEM.value)
            & (table["subject_id"] == problem_id)
            & (table["kpi"] == name)
        ]
        if len(rows) != 1:
            raise AssertionError(f"expected one {name} row, got {len(rows)}")
        value = float(np.asarray(rows["value"], dtype=np.float64)[0])
        return None if math.isnan(value) else value

    for result, units in zip(results, problem_units, strict=True):
        problem_id = result.problem_id
        subject = next(
            s
            for s in ev.subjects
            if s.level is KpiLevel.PROBLEM and s.subject_id == problem_id
        )
        loss = sample.loss[:, list(units)].sum(axis=1)
        payout = np.sum(
            [
                step_values(sample.index[:, j], result.theta[position])
                for position, j in enumerate(units)
            ],
            axis=0,
        )
        for ours, core, name in (
            (loss, subject.loss, "loss"),
            (payout, subject.payout, "payout"),
        ):
            if not np.allclose(ours, core, rtol=SELF_CHECK_RTOL, atol=1e-6):
                raise AssertionError(f"{problem_id}: the {name} per event differ")
        uncovered = np.maximum(loss - payout, 0.0)
        loss_o = [float(x) for x in outcomes.summed(loss.tolist())]
        payout_o = [float(x) for x in outcomes.summed(payout.tolist())]
        uncovered_o = [float(x) for x in outcomes.summed(uncovered.tolist())]
        residual_o = np.asarray(loss_o) - np.asarray(payout_o)

        metrics: dict[str, Any] = {}
        plain = {
            "expected_loss": float(p @ np.asarray(loss_o)),
            "expected_payout": float(p @ np.asarray(payout_o)),
            "expected_uncovered": float(p @ np.asarray(uncovered_o)),
            "rmse": math.sqrt(float(p @ residual_o**2)),
        }
        first = BETAS[0]
        for name, kpi in (
            ("expected_loss", "expected_loss"),
            ("expected_payout", "expected_payout"),
            ("premium", "premium"),
            ("expected_uncovered", "expected_uncovered"),
            ("payout_to_loss_ratio", "payout_to_loss_ratio"),
            ("rmse", "rmse_residual"),
            ("correlation", "correlation"),
        ):
            value = kpi_row(first, problem_id, kpi)
            if name in plain:
                if value is None:
                    raise AssertionError(f"{name} is undefined")
                _check_close(name, value, plain[name], scale)
            metrics[metric(name)] = None if value is None else out(value)
        premium = kpi_row(first, problem_id, "premium")
        if premium is None:
            raise AssertionError("the premium is always defined")

        for beta in BETAS:
            var = kpi_row(beta, problem_id, "var_uncovered")
            cvar = kpi_row(beta, problem_id, "cvar_uncovered")
            if var is None or cvar is None:
                raise AssertionError("VaR and CVaR are always defined")
            atoms = quantile_atoms(uncovered_o, weights, exact(beta))
            _check_atom(f"var_uncovered at {beta}", var, atoms, scale)
            metrics[metric("var_uncovered", beta=beta)] = _metric_value(atoms)
            metrics[metric("cvar_uncovered", beta=beta)] = out(cvar)

        loss_core = measure.aggregate(subject.loss)
        payout_core = measure.aggregate(subject.payout)
        net_core = loss_core - payout_core + premium
        for beta in BETAS:
            var, cvar = var_cvar(loss_core, measure.probability, beta)
            atoms = quantile_atoms(loss_o, weights, exact(beta))
            _check_atom(f"var_loss at {beta}", var, atoms, scale)
            metrics[metric("var_loss", beta=beta)] = _metric_value(atoms)
            metrics[metric("cvar_loss", beta=beta)] = out(cvar)
            if basis.is_event:
                # ADR 0006 §7: null, the premium is annual and an event isn't.
                metrics[metric("var_net_loss", beta=beta)] = None
                metrics[metric("cvar_net_loss", beta=beta)] = None
                continue
            var, cvar = var_cvar(net_core, measure.probability, beta)
            net_o = [float(x) + premium for x in residual_o]
            atoms = quantile_atoms(net_o, weights, exact(beta))
            _check_atom(f"var_net_loss at {beta}", var, atoms, scale)
            metrics[metric("var_net_loss", beta=beta)] = _metric_value(atoms)
            metrics[metric("cvar_net_loss", beta=beta)] = out(cvar)

        x_net, p_net = discrete_distribution(net_core, measure.probability)
        sorted_net, _, cdf_net = sorted_cdf(x_net, p_net)
        subject_curves = curves[
            (curves["level"] == KpiLevel.PROBLEM.value)
            & (curves["subject_id"] == problem_id)
        ]
        for period in RETURN_PERIODS:
            level = 1 - 1 / exact(period)
            for base, per_outcome in (
                ("loss", loss_o),
                ("payout", payout_o),
                ("uncovered", uncovered_o),
            ):
                rows = subject_curves[
                    (subject_curves["quantity"] == base)
                    & (subject_curves["return_period"] == period)
                ]
                if len(rows) != 1:
                    raise AssertionError(f"expected one {base} curve at {period}")
                core_value = float(np.asarray(rows["value"], dtype=np.float64)[0])
                atoms = quantile_atoms(per_outcome, weights, level)
                _check_atom(f"{base}_rp{period}", core_value, atoms, scale)
                metrics[metric(base, period=period)] = _metric_value(atoms)
            if basis.is_event:
                metrics[metric("net_loss", period=period)] = None
                continue
            core_net = lower_quantile(sorted_net, cdf_net, 1.0 - 1.0 / period)
            net_o = [float(x) + premium for x in residual_o]
            atoms = quantile_atoms(net_o, weights, level)
            _check_atom(f"net_loss_rp{period}", core_net, atoms, scale)
            metrics[metric("net_loss", period=period)] = _metric_value(atoms)
        found[problem_id] = metrics
    return found


# --------------------------------------------------------------------------
# Design cases from the core
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneratedCase:
    """A case document and what the regeneration check needs to judge it.

    Attributes
    ----------
    document : dict
        The case document.
    scale : float
        The scale of its sample.
    evaluate : callable, optional
        Core design cases: the objective, premium and metrics at given levels,
        shape ``(n_units, n_levels)``, as the ``expected`` fields.
    violations : callable, optional
        Core design cases: the design constraints the given levels break.
    ranges : tuple of numpy.ndarray, optional
        LP design cases: the wide near-optimal range of every identified level
        ``(low, high)``, loss units; NaN for unidentified levels.
    identified : numpy.ndarray of bool, optional
        Core design cases: which levels are identified.
    """

    document: dict[str, Any]
    scale: float
    evaluate: Callable[[NDArray[np.float64]], dict[str, Any]] | None = None
    violations: Callable[[NDArray[np.float64]], list[str]] | None = None
    ranges: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None
    identified: NDArray[np.bool_] | None = None


@dataclass(frozen=True)
class _Ranges:
    """Ranges of the identified amounts over two near-optimal sets, scaled units.

    ``low`` and ``high`` are taken at the wide tolerance, ``narrow`` (a width) at
    the narrow one; NaN for unidentified amounts.
    """

    low: NDArray[np.float64]
    high: NDArray[np.float64]
    narrow: NDArray[np.float64]

    def unique(self, identified: NDArray[np.bool_]) -> bool:
        """Whether every identified amount is pinned to a point."""
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

    Call right after the problem was solved with :data:`LP_VERTEX_POLICY`. At
    a unique optimum a range is the tolerance over the objective's slope, so
    it shrinks with the tolerance; on a set of optimal designs it keeps the
    set's width.

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


def _qp_unique(built: BuiltProblem, identified: NDArray[np.bool_]) -> bool:
    """Whether the Hessian of an MSE problem on the identified amounts is definite.

    H = C' diag(p) C, where C holds each identified amount's basis summed into
    outcomes (the columns of every unit side by side).
    """
    ctx = built.context
    columns = np.column_stack(
        [
            ctx.payout_structure.basis_matrix(ctx.problem.index[:, j])[:, identified[j]]
            for j in range(identified.shape[0])
        ]
    )
    grouped = ctx.measure.aggregate(np.asarray(columns, dtype=np.float64))
    hessian = grouped.T @ np.diag(ctx.measure.probability) @ grouped
    eigen = np.linalg.eigvalsh(hessian)
    return bool(eigen.min() > EIGEN_RTOL * eigen.max())


def _snap(theta: NDArray[np.float64], scale: float) -> NDArray[np.float64]:
    """Write amounts within :data:`ZERO_AMOUNT` of the scale of zero as 0."""
    return np.where(np.abs(theta) <= ZERO_AMOUNT * scale, 0.0, theta) + 0.0


def _fill_lowest(
    theta: NDArray[np.float64], identified: NDArray[np.bool_]
) -> NDArray[np.float64]:
    """Set the unidentified levels by the rule ``fill="lowest"`` (ADR 0006 §6.5).

    The previous identified level of the unit (the levels are monotone), or 0
    if there is none. The design stays exactly optimal and feasible.
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
    return math.isclose(a, b, rel_tol=rtol, abs_tol=rtol)


def _identified(sample: SampleData, n_levels: int) -> NDArray[np.bool_]:
    """Whether each (unit, level) has an event in its bin (ADR 0006 §6.5)."""
    identified = np.zeros((len(sample.unit_id), n_levels), dtype=bool)
    edges = np.asarray(STEP_BREAKPOINTS, dtype=np.float64)
    for j in range(identified.shape[0]):
        k = np.searchsorted(edges, sample.index[:, j], side="right") - 1
        identified[j, k[k >= 0]] = True
    return identified


@dataclass(frozen=True, eq=False)
class _Solved:
    """The solution of one design problem."""

    chosen: SolveResult
    unique: bool
    qp: bool
    ranges: _Ranges | None


def _solve_problem(
    build: Callable[[], BuiltProblem],
    identified: NDArray[np.bool_],
    where: str,
    settings: SolverSettings,
) -> _Solved:
    """Solve one design problem as the module docstring says.

    Raises
    ------
    AssertionError
        If two accurate solvers disagree, or an interior solution lies outside
        the ranges.
    """
    first = build()
    ctx = first.context
    for j in range(identified.shape[0]):
        columns = np.asarray(ctx.payout_structure.basis_matrix(ctx.problem.index[:, j]))
        if not np.array_equal(columns.sum(axis=0) > 0, identified[j]):
            raise AssertionError(f"{where}: the core's bins and the sample's differ")
    ranges: _Ranges | None = None
    qp = is_qp(first.problem)
    if qp:
        accurate = solve(first, settings.accurate)
        check = solve(build(), settings.qp_check)
        unique = _qp_unique(first, identified)
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
    if not _rel_close(
        accurate.objective_value, check.objective_value, SOLVER_AGREEMENT_RTOL
    ):
        raise AssertionError(
            f"{where}: solvers disagree: {accurate.objective_value!r} "
            f"({accurate.solver}) vs {check.objective_value!r} ({check.solver})"
        )
    if unique:
        gap = np.abs(accurate.theta - check.theta)[identified]
        if np.any(gap > UNIQUE_WIDTH * chosen.scale):
            raise AssertionError(f"{where}: unique, but the solvers' amounts differ")
    return _Solved(chosen=chosen, unique=unique, qp=qp, ranges=ranges)


def design_case(
    sample: SampleData,
    basis: BasisSpec,
    scope_name: str,
    objective: ObjectiveSpec,
    pricing: PricingSpec,
    commit: str,
    settings: SolverSettings,
) -> GeneratedCase:
    """Build one design case: the core designs a step cover on ``sample``.

    Parameters
    ----------
    sample : SampleData
        The sample.
    basis : BasisSpec
        The basis. An event-basis sample's frequencies must sum to at most 1.
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
        The document, with what the regeneration check needs.
    """
    joint = scope_name == F.scope_joint
    n_units = len(sample.unit_id)
    n_levels = len(STEP_BREAKPOINTS)
    edges = (*STEP_BREAKPOINTS, CORE_UPPER_EDGE)
    payout = pid.StepPayout(
        attachment=edges[0],
        limit=edges[-1],
        n_bins=n_levels,
        breakpoints=edges,
        below_attachment="zero",
    )
    eventset = core_eventset(sample, basis)
    scope: Scope = pid.Portfolio() if joint else pid.Individual()
    constraints = (pid.Budget(BUDGET_RATIO),)
    where = f"{sample.name}/{basis.kind}/{scope_name}/{objective.token}/{pricing.token}"
    case_id = (
        f"step-{objective.token}-{pricing.token}-{basis.kind}-{scope_name}-"
        f"{sample.name}"
    )

    def build_all() -> tuple[BuiltProblem, ...]:
        return build_problems(
            eventset,
            scope,
            payout,
            objective.core,
            pricing.core,
            constraints,
            basis=basis.core,
        )

    identified = _identified(sample, n_levels)
    problem_units: list[tuple[int, ...]] = (
        [tuple(range(n_units))] if joint else [(j,) for j in range(n_units)]
    )
    solved: list[_Solved] = []
    for position, units in enumerate(problem_units):
        solved.append(
            _solve_problem(
                lambda position=position: build_all()[position],
                identified[list(units)],
                f"{where}/{position}",
                settings,
            )
        )
    scale = sample.scale
    outcomes = sample.outcomes(basis)
    p = outcomes.float_weights()

    theta = np.vstack([_snap(s.chosen.theta, s.chosen.scale) for s in solved])
    theta = np.vectorize(out)(theta).astype(np.float64)
    theta = _fill_lowest(theta, identified)
    caps = sample.loss.max(axis=0)

    def results_at(levels: NDArray[np.float64]) -> list[SolveResult]:
        return [
            replace(s.chosen, theta=levels[list(units)])
            for s, units in zip(solved, problem_units, strict=True)
        ]

    def payout_of(
        levels: NDArray[np.float64], units: tuple[int, ...]
    ) -> NDArray[np.float64]:
        return np.sum(
            [step_values(sample.index[:, j], levels[j]) for j in units], axis=0
        )

    def problem_values(
        levels: NDArray[np.float64],
    ) -> tuple[list[float], list[float], list[dict[str, Any]]]:
        """Objective, premium and metrics of every design problem at ``levels``."""
        results = results_at(levels)
        metrics = core_metrics(
            sample,
            basis,
            eventset,
            scope,
            results,
            pricing.core,
            problem_units,
        )
        values: list[float] = []
        premiums: list[float] = []
        rows: list[dict[str, Any]] = []
        for result, units in zip(results, problem_units, strict=True):
            loss = sample.loss[:, list(units)].sum(axis=1)
            values.append(
                out(
                    _objective_value(
                        objective.core, outcomes, loss, payout_of(levels, units)
                    )
                )
            )
            row = metrics[result.problem_id]
            premiums.append(float(row[metric("premium")]))
            rows.append(row)
        return values, premiums, rows

    def by_unit(values: Sequence[Any]) -> Any:  # noqa: ANN401
        """One value in the joint scope; a mapping by unit in the individual one."""
        if joint:
            return values[0]
        return dict(zip(sample.unit_id, values, strict=True))

    def evaluate(levels: NDArray[np.float64]) -> dict[str, Any]:
        """Return the objective, premium and metrics of the cover at ``levels``."""
        values, premiums, rows = problem_values(levels)
        return {
            F.objective_value: by_unit(values),
            F.premium: by_unit(premiums),
            F.metrics: by_unit(rows),
        }

    def violations(levels: NDArray[np.float64]) -> list[str]:
        """Return the design constraints that ``levels`` break."""
        tol = ZERO_AMOUNT * scale
        found = []
        if levels.min() < -tol:
            found.append(f"a level is negative: {levels.min()!r}")
        if np.diff(levels, axis=1).min() < -tol:
            found.append("the levels are not monotone")
        if np.any(levels > caps[:, None] + tol):
            found.append("a level is above its unit's largest loss")
        _, premiums, _ = problem_values(levels)
        for premium, units in zip(premiums, problem_units, strict=True):
            loss_o = outcomes.summed(sample.loss[:, list(units)].sum(axis=1).tolist())
            budget = BUDGET_RATIO * float(p @ np.asarray(loss_o, dtype=np.float64))
            if premium > budget * (1.0 + WRITTEN_RTOL):
                found.append(f"premium {premium!r} above the budget {budget!r}")
        return found

    values, _, _ = problem_values(theta)
    for value, s in zip(values, solved, strict=True):
        if not _rel_close(value, s.chosen.objective_value, WRITTEN_RTOL):
            raise AssertionError(
                f"{where}: objective at the written amounts {value!r}, "
                f"solver {s.chosen.objective_value!r}"
            )
    broken = violations(theta)
    if broken:
        raise AssertionError(f"{where}: the written amounts break {broken}")

    unique = all(s.unique for s in solved)
    qp = solved[0].qp
    names = tuple(level_name(k) for k in range(n_levels))
    evaluation = evaluate(theta)
    step = Payout(
        F.payout_step,
        F.tail_upper,
        STEP_BREAKPOINTS,
        (0.0,) * n_levels,
    ).document(free=True)
    limit = {F.rule: F.limit_largest_loss}
    compare = (
        F.compare_exact
        if unique
        else (F.compare_none if qp else F.compare_within_ranges)
    )
    document = {
        F.case_id: case_id,
        F.kind: F.kind_design,
        F.source: F.source_core,
        F.sample: f"samples/{sample.name}.json",
        F.basis: basis.document(),
        F.scope: scope_name,
        F.cover: cover_document(sample, step, limit),
        F.objective: dict(objective.document),
        F.pricing: dict(pricing.document),
        F.budget: {F.ratio: BUDGET_RATIO},
        F.limit: limit,
        F.expected: {
            F.objective_value: evaluation[F.objective_value],
            F.premium: evaluation[F.premium],
            F.parameters: {
                u: {name: out(theta[j, k]) for k, name in enumerate(names)}
                for j, u in enumerate(sample.unit_id)
            },
            F.unidentified: {
                u: [name for k, name in enumerate(names) if not identified[j, k]]
                for j, u in enumerate(sample.unit_id)
            },
            F.unique: unique,
            F.metrics: evaluation[F.metrics],
        },
        F.compare_parameters: compare,
        F.tolerances: _tolerances(),
        F.generator: _generator(commit),
    }
    wide: tuple[NDArray[np.float64], NDArray[np.float64]] | None = None
    if not qp:
        low = np.vstack([s.ranges.low * s.chosen.scale for s in solved if s.ranges])
        high = np.vstack([s.ranges.high * s.chosen.scale for s in solved if s.ranges])
        wide = (low, high)
    return GeneratedCase(
        document=document,
        scale=scale,
        evaluate=evaluate,
        violations=violations,
        ranges=wide,
        identified=identified,
    )


# --------------------------------------------------------------------------
# Closed-form cases
# --------------------------------------------------------------------------


def _exact_metrics(
    outcomes: Outcomes,
    loss: Sequence[Fraction],
    payout: Sequence[Fraction],
    coc: tuple[Fraction, Fraction] | None,
    *,
    is_event: bool,
) -> dict[str, Any]:
    """Every metric column the cases list, exact (ADR 0006 §7).

    Parameters
    ----------
    outcomes : Outcomes
        The outcomes and their weights.
    loss, payout : sequence of Fraction
        Per event.
    coc : tuple of Fraction, optional
        ``(rate, q)``; None for the pure premium.
    is_event : bool
        The event basis: the net-loss columns are null, and the false-positive
        rate's denominator holds the file's events only.

    Returns
    -------
    dict
        Column -> an exact value, a tuple of atoms for a quantile, or None.
    """
    zero = Fraction(0)
    uncovered_e = [max(lo - pi, zero) for lo, pi in zip(loss, payout, strict=True)]
    loss_o = outcomes.summed(loss)
    payout_o = outcomes.summed(payout)
    uncovered_o = outcomes.summed(uncovered_e)
    residual_o = [lo - pi for lo, pi in zip(loss_o, payout_o, strict=True)]
    w = outcomes.weights

    def expect(values: Iterable[Fraction]) -> Fraction:
        return sum((wi * v for wi, v in zip(w, values, strict=True)), zero)

    e_loss, e_payout, e_unc = expect(loss_o), expect(payout_o), expect(uncovered_o)
    if coc is None:
        premium = e_payout
    else:
        rate, q = coc
        premium = (1 - rate) * e_payout + rate * exact_cvar(payout_o, w, q)
    net_o = [r + premium for r in residual_o]
    m: dict[str, Any] = {
        metric("expected_loss"): e_loss,
        metric("expected_payout"): e_payout,
        metric("premium"): premium,
        metric("expected_uncovered"): e_unc,
        metric("coverage_ratio"): None if e_loss == 0 else 1 - e_unc / e_loss,
        metric("payout_to_loss_ratio"): None if e_loss == 0 else e_payout / e_loss,
        metric("payout_frequency"): expect(
            Fraction(int(pi > PAYOUT_THRESHOLD)) for pi in payout_o
        ),
    }
    for beta in BETAS:
        level = exact(beta)
        tw = tail_weights(loss_o, w, level)
        denominator = sum((t * lo for t, lo in zip(tw, loss_o, strict=True)), zero)
        covered = sum(
            (t * (lo - un) for t, lo, un in zip(tw, loss_o, uncovered_o, strict=True)),
            zero,
        )
        m[metric("tail_coverage", beta=beta)] = (
            None if denominator == 0 else covered / denominator
        )
        cvar_loss = exact_cvar(loss_o, w, level)
        m[metric("cvar_uncovered_to_loss", beta=beta)] = (
            None if cvar_loss == 0 else exact_cvar(uncovered_o, w, level) / cvar_loss
        )
    kept = outcomes.kept()
    big = [lo > exact(LOSS_THRESHOLD) for lo in loss_o]
    paid = [pi > PAYOUT_THRESHOLD for pi in payout_o]
    weight_big = sum((wi for wi, b in zip(w, big, strict=True) if b), zero)
    weight_small = sum(
        (wi for wi, b, k in zip(w, big, kept, strict=True) if not b and k), zero
    )
    false_negative = sum(
        (wi for wi, b, pi in zip(w, big, paid, strict=True) if b and not pi), zero
    )
    false_positive = sum(
        (
            wi
            for wi, b, pi, k in zip(w, big, paid, kept, strict=True)
            if pi and not b and k
        ),
        zero,
    )
    m[metric("false_negative_rate", threshold=LOSS_THRESHOLD)] = (
        None if weight_big == 0 else false_negative / weight_big
    )
    m[metric("false_positive_rate", threshold=LOSS_THRESHOLD)] = (
        None if weight_small == 0 else false_positive / weight_small
    )
    m[metric("rmse")] = math.sqrt(expect(r * r for r in residual_o))
    total = sum(w, zero)
    mean_loss, mean_payout = e_loss / total, e_payout / total
    cov = expect(
        (lo - mean_loss) * (pi - mean_payout)
        for lo, pi in zip(loss_o, payout_o, strict=True)
    )
    var_l = expect((lo - mean_loss) ** 2 for lo in loss_o)
    var_p = expect((pi - mean_payout) ** 2 for pi in payout_o)
    m[metric("correlation")] = (
        None
        if var_l == 0 or var_p == 0
        else float(cov) / math.sqrt(float(var_l * var_p))
    )
    for beta in BETAS:
        level = exact(beta)
        columns: list[tuple[str, list[Fraction]]] = [
            ("uncovered", uncovered_o),
            ("loss", loss_o),
        ]
        if is_event:
            m[metric("var_net_loss", beta=beta)] = None
            m[metric("cvar_net_loss", beta=beta)] = None
        else:
            columns.append(("net_loss", net_o))
        for base, values in columns:
            m[metric(f"var_{base}", beta=beta)] = quantile_atoms(values, w, level)
            m[metric(f"cvar_{base}", beta=beta)] = exact_cvar(values, w, level)
    for period in RETURN_PERIODS:
        level = 1 - 1 / exact(period)
        columns = [("loss", loss_o), ("payout", payout_o), ("uncovered", uncovered_o)]
        if is_event:
            m[metric("net_loss", period=period)] = None
        else:
            columns.append(("net_loss", net_o))
        for base, values in columns:
            m[metric(base, period=period)] = quantile_atoms(values, w, level)
    return m


def _written(value: object) -> object:
    """Float form of an exact metric: atoms become one value or ``either``."""
    if value is None:
        return None
    if isinstance(value, tuple):
        return _metric_value(value)
    if isinstance(value, Fraction | float):
        return out(value)
    raise TypeError(f"cannot write {value!r}")


def _check_with_core_measures(
    columns: Mapping[str, Any],
    outcomes: Outcomes,
    loss_o: Sequence[Fraction],
    uncovered_o: Sequence[Fraction],
    scale: float,
) -> None:
    """Check VaR and CVaR against the core, where the weights are a distribution.

    Frequencies that sum to more than 1 have no counterpart in the core.

    Raises
    ------
    AssertionError
        If the core's risk measures and the exact values differ.
    """
    if sum(outcomes.weights, Fraction(0)) != 1:
        return
    p = outcomes.float_weights()
    for base, values in (("loss", loss_o), ("uncovered", uncovered_o)):
        floats = np.array([float(v) for v in values], dtype=np.float64)
        for beta in BETAS:
            var, cvar = var_cvar(floats, p, beta)
            atoms = [float(a) for a in columns[metric(f"var_{base}", beta=beta)]]
            _check_atom(f"var_{base} at {beta}", var, atoms, scale)
            own = float(columns[metric(f"cvar_{base}", beta=beta)])
            _check_close(f"cvar_{base} at {beta}", cvar, own, scale)


def evaluate_case(
    sample: SampleData,
    basis: BasisSpec,
    scope_name: str,
    payout: Payout | Mapping[str, Payout],
    pricing: PricingSpec,
    commit: str,
    token: str | None = None,
) -> GeneratedCase:
    """Build a closed-form evaluation of a fixed cover (ADR 0006 §3, §5.1, §7).

    Parameters
    ----------
    sample : SampleData
        The sample.
    basis : BasisSpec
        The basis.
    scope_name : {"individual", "joint"}
        Individual: metrics per unit. Joint: metrics of the total.
    payout : Payout or mapping of str to Payout
        One payout for every unit, or one per unit.
    pricing : PricingSpec
        The pricing.
    commit : str
        The generator block's commit.
    token : str, optional
        The payout's part of the case id, for a mapping by unit.

    Returns
    -------
    GeneratedCase
        The document.
    """
    joint = scope_name == F.scope_joint
    n_units = len(sample.unit_id)
    per_unit: list[Payout] = [
        payout if isinstance(payout, Payout) else payout[u] for u in sample.unit_id
    ]
    index = [[exact(float(x)) for x in sample.index[:, j]] for j in range(n_units)]
    loss = [[exact(float(x)) for x in sample.loss[:, j]] for j in range(n_units)]
    payouts: list[list[Fraction]] = []
    for j, p in enumerate(per_unit):
        amounts = p.exact_amounts()
        payouts.append(
            [
                sum(
                    (a * b for a, b in zip(amounts, p.basis(x), strict=True)),
                    Fraction(0),
                )
                for x in index[j]
            ]
        )
    outcomes = sample.outcomes(basis)
    columns: list[dict[str, Any]] = []
    if joint:
        groups: list[tuple[int, ...]] = [tuple(range(n_units))]
    else:
        groups = [(j,) for j in range(n_units)]
    for units in groups:
        loss_e = [
            sum(row, Fraction(0)) for row in zip(*[loss[j] for j in units], strict=True)
        ]
        payout_e = [
            sum(row, Fraction(0))
            for row in zip(*[payouts[j] for j in units], strict=True)
        ]
        exact_columns = _exact_metrics(
            outcomes, loss_e, payout_e, pricing.coc, is_event=basis.is_event
        )
        _check_with_core_measures(
            exact_columns,
            outcomes,
            outcomes.summed(loss_e),
            outcomes.summed(
                [
                    max(lo - pi, Fraction(0))
                    for lo, pi in zip(loss_e, payout_e, strict=True)
                ]
            ),
            sample.scale,
        )
        columns.append({name: _written(v) for name, v in exact_columns.items()})
    premiums = [c[metric("premium")] for c in columns]

    def by_unit(values: Sequence[Any]) -> Any:  # noqa: ANN401
        return values[0] if joint else dict(zip(sample.unit_id, values, strict=True))

    payout_doc: Mapping[str, Any]
    if isinstance(payout, Payout):
        payout_doc = payout.document()
        name = payout.token if token is None else token
    else:
        payout_doc = {u: payout[u].document() for u in sample.unit_id}
        if token is None:
            raise ValueError("a payout by unit needs a token")
        name = token
    case_id = f"{name}-fixed-{pricing.token}-{basis.kind}-{scope_name}-{sample.name}"
    document = {
        F.case_id: case_id,
        F.kind: F.kind_evaluate,
        F.source: F.source_closed_form,
        F.sample: f"samples/{sample.name}.json",
        F.basis: basis.document(),
        F.scope: scope_name,
        F.cover: cover_document(sample, payout_doc, None),
        F.objective: None,
        F.pricing: dict(pricing.document),
        F.budget: None,
        F.limit: None,
        F.expected: {
            F.objective_value: None,
            F.premium: by_unit(premiums),
            F.parameters: None,
            F.unidentified: None,
            F.unique: None,
            F.metrics: by_unit(columns),
        },
        F.compare_parameters: F.compare_none,
        F.tolerances: _tolerances(),
        F.generator: _generator(commit),
    }
    return GeneratedCase(document=document, scale=sample.scale)


def _exact_objective(
    objective: Objective,
    outcomes: Outcomes,
    loss: Sequence[Fraction],
    payout: Sequence[Fraction],
) -> Fraction:
    """Return the objective at per-event loss and payout, exact (§6.2)."""
    zero = Fraction(0)
    uncovered_e = [max(lo - pi, zero) for lo, pi in zip(loss, payout, strict=True)]
    uncovered_o = outcomes.summed(uncovered_e)
    w = outcomes.weights

    def expect(values: Iterable[Fraction]) -> Fraction:
        return sum((wi * v for wi, v in zip(w, values, strict=True)), zero)

    if isinstance(objective, pid.MSE):
        residual = [
            lo - pi
            for lo, pi in zip(
                outcomes.summed(loss), outcomes.summed(payout), strict=True
            )
        ]
        return expect(r * r for r in residual)
    if isinstance(objective, pid.ExpectedUncovered):
        return expect(uncovered_o)
    if isinstance(objective, pid.WeightedCVaR):
        cvar = exact_cvar(uncovered_o, w, exact(objective.beta))
        alpha = exact(objective.alpha)
        return alpha * cvar + (1 - alpha) * expect(uncovered_o)
    raise TypeError(f"no closed form for the objective {objective!r}")


def _one_amount_design(
    sample: SampleData,
    basis: BasisSpec,
    payout: Payout,
    objective: ObjectiveSpec,
    pricing: PricingSpec,
    commit: str,
) -> GeneratedCase:
    """Build a closed-form design of a cover with one free amount, on one unit.

    The payout of event ``e`` is ``A b_e`` with a basis value ``b_e`` in
    ``[0, 1]``. The premium is ``c A``: ``c = E[b]``, or ``(1 - r) E[b] + r
    CVaR_q(b)`` under the load (CVaR is positively homogeneous). With the
    limit ``largest_loss`` and the budget, ``A`` ranges over ``[0, A_max]``,
    ``A_max = min(cap, budget / c)``.

    * E[U] and weighted CVaR do not increase in ``A``, so ``A_max`` is optimal.
      It is the only optimum when some event with ``b_e > 0`` has ``L_e >=
      A_max b_e``; otherwise nothing changes near ``A_max``.
    * MSE is a quadratic in ``A``, smallest at ``E[bL] / E[b²]`` over outcomes,
      clipped to ``[0, A_max]``, and unique.

    Parameters
    ----------
    sample : SampleData
        One unit.
    basis : BasisSpec
        The basis; frequencies may sum to more than 1 on the event basis.
    payout : Payout
        A linear or binary payout; its amount is free.
    objective, pricing : ObjectiveSpec, PricingSpec
        The case's objective and pricing.
    commit : str
        The generator block's commit.

    Returns
    -------
    GeneratedCase
        The document.
    """
    if len(sample.unit_id) != 1 or len(payout.amounts) != 1:
        raise ValueError("a one-amount design has one unit and one amount")
    zero = Fraction(0)
    index = [exact(float(x)) for x in sample.index[:, 0]]
    loss = [exact(float(x)) for x in sample.loss[:, 0]]
    basis_e = [payout.basis(x)[0] for x in index]
    if not any(b != 0 for b in basis_e):
        raise ValueError("the amount must be identified")
    outcomes = sample.outcomes(basis)
    w = outcomes.weights
    basis_o = outcomes.summed(basis_e)
    loss_o = outcomes.summed(loss)

    def expect(values: Iterable[Fraction]) -> Fraction:
        return sum((wi * v for wi, v in zip(w, values, strict=True)), zero)

    if pricing.coc is None:
        unit_premium = expect(basis_o)
    else:
        rate, q = pricing.coc
        unit_premium = (1 - rate) * expect(basis_o) + rate * exact_cvar(basis_o, w, q)
    budget = exact(BUDGET_RATIO) * expect(loss_o)
    cap = max(loss)
    bound = min(cap, budget / unit_premium)
    if isinstance(objective.core, pid.MSE):
        fit = expect(b * lo for b, lo in zip(basis_o, loss_o, strict=True)) / expect(
            b * b for b in basis_o
        )
        amount, unique = min(max(fit, zero), bound), True
    else:
        amount = bound
        unique = any(
            b > 0 and lo >= bound * b for b, lo in zip(basis_e, loss, strict=True)
        )
    payout_e = [amount * b for b in basis_e]
    value = _exact_objective(objective.core, outcomes, loss, payout_e)
    exact_columns = _exact_metrics(
        outcomes, loss, payout_e, pricing.coc, is_event=basis.is_event
    )
    columns = {name: _written(v) for name, v in exact_columns.items()}
    unit = sample.unit_id[0]
    limit = {F.rule: F.limit_largest_loss}
    case_id = (
        f"{payout.token}-{objective.token}-{pricing.token}-{basis.kind}-"
        f"{F.scope_individual}-{sample.name}"
    )
    document = {
        F.case_id: case_id,
        F.kind: F.kind_design,
        F.source: F.source_closed_form,
        F.sample: f"samples/{sample.name}.json",
        F.basis: basis.document(),
        F.scope: F.scope_individual,
        F.cover: cover_document(sample, payout.document(free=True), limit),
        F.objective: dict(objective.document),
        F.pricing: dict(pricing.document),
        F.budget: {F.ratio: BUDGET_RATIO},
        F.limit: limit,
        F.expected: {
            F.objective_value: {unit: out(value)},
            F.premium: {unit: columns[metric("premium")]},
            F.parameters: {unit: {payout.amount_names[0]: out(amount)}},
            F.unidentified: {unit: []},
            F.unique: unique,
            F.metrics: {unit: columns},
        },
        F.compare_parameters: F.compare_exact if unique else F.compare_none,
        F.tolerances: _tolerances(),
        F.generator: _generator(commit),
    }
    return GeneratedCase(document=document, scale=sample.scale)


def _replication_design(
    sample: SampleData,
    basis: BasisSpec,
    payout: Payout,
    objective: ObjectiveSpec,
    pricing: PricingSpec,
    commit: str,
) -> GeneratedCase:
    """Build the closed-form MSE design of a payout whose curve the losses lie on.

    If every event's loss equals the payout at its index, the objective is 0
    at those amounts, its minimum; the budget does not bind. The Hessian's rank
    says whether the amounts are the only optimum.

    Parameters
    ----------
    sample : SampleData
        One unit, with every loss on the curve.
    basis : BasisSpec
        The basis.
    payout : Payout
        A piecewise-linear payout, with the amounts of the curve.
    objective, pricing : ObjectiveSpec, PricingSpec
        MSE and the pure premium.
    commit : str
        The generator block's commit.

    Returns
    -------
    GeneratedCase
        The document.

    Raises
    ------
    ValueError
        If a loss is off the curve, or the design's premium exceeds the budget.
    """
    if not isinstance(objective.core, pid.MSE) or pricing.coc is not None:
        raise ValueError("the replication design is MSE under the pure premium")
    zero = Fraction(0)
    index = [exact(float(x)) for x in sample.index[:, 0]]
    loss = [exact(float(x)) for x in sample.loss[:, 0]]
    amounts = payout.exact_amounts()
    bases = [payout.basis(x) for x in index]
    payout_e = [
        sum((a * b for a, b in zip(amounts, row, strict=True)), zero) for row in bases
    ]
    if payout_e != loss:
        raise ValueError("every loss must lie on the curve")
    outcomes = sample.outcomes(basis)
    columns_exact = _exact_metrics(
        outcomes, loss, payout_e, None, is_event=basis.is_event
    )
    ratio = exact(REPLICATION_BUDGET_RATIO)
    if (
        columns_exact[metric("premium")]
        > ratio * columns_exact[metric("expected_loss")]
    ):
        raise ValueError("the budget must not bind")
    n = len(amounts)
    grouped = np.array(
        [
            [float(sum((bases[e][k] for e in g), zero)) for k in range(n)]
            for g in outcomes.groups
        ],
        dtype=np.float64,
    )
    hessian = grouped.T @ np.diag(outcomes.float_weights()) @ grouped
    eigen = np.linalg.eigvalsh(hessian)
    unique = bool(eigen.min() > EIGEN_RTOL * eigen.max())
    if not unique:
        raise ValueError("the replication design must be unique")
    unit = sample.unit_id[0]
    limit = {F.rule: F.limit_largest_loss}
    columns = {name: _written(v) for name, v in columns_exact.items()}
    case_id = (
        f"{payout.token}-{objective.token}-{pricing.token}-{basis.kind}-"
        f"{F.scope_individual}-{sample.name}"
    )
    document = {
        F.case_id: case_id,
        F.kind: F.kind_design,
        F.source: F.source_closed_form,
        F.sample: f"samples/{sample.name}.json",
        F.basis: basis.document(),
        F.scope: F.scope_individual,
        F.cover: cover_document(sample, payout.document(free=True), limit),
        F.objective: dict(objective.document),
        F.pricing: dict(pricing.document),
        F.budget: {F.ratio: REPLICATION_BUDGET_RATIO},
        F.limit: limit,
        F.expected: {
            F.objective_value: {unit: 0.0},
            F.premium: {unit: columns[metric("premium")]},
            F.parameters: {
                unit: {
                    name: out(a)
                    for name, a in zip(payout.amount_names, amounts, strict=True)
                }
            },
            F.unidentified: {unit: []},
            F.unique: True,
            F.metrics: {unit: columns},
        },
        F.compare_parameters: F.compare_exact,
        F.tolerances: _tolerances(),
        F.generator: _generator(commit),
    }
    return GeneratedCase(document=document, scale=sample.scale)


# --------------------------------------------------------------------------
# The case matrix
# --------------------------------------------------------------------------

H1_LINEAR: Final[Payout] = Payout(
    F.payout_linear, F.tail_upper, (50.0, 150.0), (1000.0,)
)
H1_BINARY: Final[Payout] = Payout(F.payout_binary, F.tail_upper, (100.0,), (500.0,))
H1_PIECEWISE: Final[Payout] = Payout(
    F.payout_piecewise_linear,
    F.tail_upper,
    (50.0, 80.0, 120.0, 175.0),
    (50.0, 250.0, 700.0, 1200.0),
)
H2_STEP: Final[Payout] = Payout(
    F.payout_step,
    F.tail_upper,
    (50.0, 80.0, 120.0, 175.0),
    (40.0, 200.0, 600.0, 1300.0),
)
H4_LOWER: Final[tuple[Payout, ...]] = (
    Payout(
        F.payout_step,
        F.tail_lower,
        (-1.0, -1.5, -2.0, -3.0),
        (40.0, 120.0, 400.0, 900.0),
    ),
    Payout(F.payout_linear, F.tail_lower, (-1.0, -3.0), (800.0,)),
    Payout(
        F.payout_piecewise_linear,
        F.tail_lower,
        (-1.0, -2.0, -3.0),
        (30.0, 350.0, 900.0),
    ),
    Payout(F.payout_binary, F.tail_lower, (-1.5,), (400.0,)),
)
H3_STEP: Final[Mapping[str, Payout]] = {
    "u1": Payout(
        F.payout_step, F.tail_upper, (30.0, 45.0, 60.0), (100.0, 800.0, 2500.0)
    ),
    "u2": Payout(F.payout_step, F.tail_upper, (25.0, 36.0, 50.0), (50.0, 300.0, 900.0)),
}
"""A joint fixed cover whose payout differs by unit."""
S1_LINEAR: Final[Payout] = Payout(
    F.payout_linear, F.tail_upper, (30.0, 60.0), (1_000_000.0,)
)
H2_BINARY_HIGH: Final[Payout] = Payout(
    F.payout_binary, F.tail_upper, (210.0,), (1800.0,)
)
"""A trigger high enough that the limit binds, not the budget."""
H5_PIECEWISE: Final[Payout] = H1_PIECEWISE
"""The curve the losses of ``h5`` lie on."""
SCOPES: Final[tuple[str, ...]] = (F.scope_individual, F.scope_joint)
MATRIX_OBJECTIVES: Final[tuple[str, ...]] = ("mse", "eu", "wcvar")
"""The objectives of the core's case matrix, by short name."""


@dataclass(frozen=True)
class FixtureSet:
    """The generated set: sample documents and cases, by file name."""

    samples: dict[str, dict[str, Any]]
    cases: dict[str, GeneratedCase]


def build_set(
    commit: str | None = None, settings: SolverSettings | None = None
) -> FixtureSet:
    """Generate the whole set.

    Parameters
    ----------
    commit : str, optional
        The generator block's commit; by default :func:`core_commit`.
    settings : SolverSettings, optional
        The solver policies; by default those the set is written with.

    Returns
    -------
    FixtureSet
        Every sample and case.
    """
    commit = core_commit() if commit is None else commit
    settings = SolverSettings() if settings is None else settings
    s1, s2, h1, h2, h3, h4, h5 = (
        s1_sample(),
        s2_sample(),
        h1_sample(),
        h2_sample(),
        h3_sample(),
        h4_sample(),
        h5_sample(),
    )
    samples = {f"{s.name}.json": s.document() for s in (s1, s2, h1, h2, h3, h4, h5)}
    annual_s1 = BasisSpec(F.basis_annual, S1_YEARS)
    annual_h1 = BasisSpec(F.basis_annual, 16)
    annual_h4 = BasisSpec(F.basis_annual, 20)
    annual_h5 = BasisSpec(F.basis_annual, 20)
    obj, pri = objectives(), pricings()
    generated: list[GeneratedCase] = []
    # From the core: step x objective x basis x scope x pricing.
    for sample, basis in ((s1, annual_s1), (s2, EVENT_BASIS)):
        for scope_name in SCOPES:
            for name in MATRIX_OBJECTIVES:
                for pricing in pri.values():
                    generated.append(
                        design_case(
                            sample,
                            basis,
                            scope_name,
                            obj[name],
                            pricing,
                            commit,
                            settings,
                        )
                    )
    generated.append(
        design_case(
            s1,
            annual_s1,
            F.scope_joint,
            obj["wcvar-b0_99"],
            pri["pure"],
            commit,
            settings,
        )
    )
    individual = F.scope_individual
    # Closed form: fixed covers of the families the core lacks.
    for payout in (H1_LINEAR, H1_PIECEWISE, H1_BINARY):
        generated.append(
            evaluate_case(h1, annual_h1, individual, payout, pri["pure"], commit)
        )
        generated.append(
            evaluate_case(h1, EVENT_BASIS, individual, payout, pri["coc"], commit)
        )
    # Closed form: the event basis with frequencies summing to more than 1.
    for payout, token in (
        (H2_STEP, "pure"),
        (H1_LINEAR, "pure"),
        (H1_PIECEWISE, "coc"),
        (H1_BINARY, "pure"),
    ):
        generated.append(
            evaluate_case(h2, EVENT_BASIS, individual, payout, pri[token], commit)
        )
    # Closed form: joint fixed covers, one family and one payout per unit.
    generated.append(
        evaluate_case(s1, annual_s1, F.scope_joint, S1_LINEAR, pri["pure"], commit)
    )
    generated.append(
        evaluate_case(
            h3, EVENT_BASIS, F.scope_joint, H3_STEP, pri["coc"], commit, token="step"
        )
    )
    # Closed form: the lower tail, every family.
    for payout in H4_LOWER:
        generated.append(
            evaluate_case(h4, annual_h4, individual, payout, pri["pure"], commit)
        )
    # Closed form: designs with one free amount.
    for sample, basis, payout, objective, pricing in (
        (h1, annual_h1, H1_BINARY, "mse", "pure"),
        (h2, EVENT_BASIS, H1_BINARY, "wcvar", "coc"),
        (h2, EVENT_BASIS, H2_BINARY_HIGH, "eu", "pure"),
        (h1, annual_h1, H1_LINEAR, "eu", "pure"),
        (h2, EVENT_BASIS, H1_LINEAR, "mse", "coc"),
        (h1, EVENT_BASIS, H1_LINEAR, "wcvar", "pure"),
    ):
        generated.append(
            _one_amount_design(
                sample, basis, payout, obj[objective], pri[pricing], commit
            )
        )
    # Closed form: a piecewise-linear MSE design whose optimum is the curve.
    generated.append(
        _replication_design(
            h5, annual_h5, H5_PIECEWISE, obj["mse"], pri["pure"], commit
        )
    )
    cases = {f"{c.document[F.case_id]}.json": c for c in generated}
    if len(cases) != len(generated):
        raise ValueError("two cases share an id")
    return FixtureSet(samples=samples, cases=cases)


# --------------------------------------------------------------------------
# Canonical text
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
"""Objects at most this wide are written on one line."""


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
    """Render a document as canonical JSON text.

    Keys sorted, two-space indentation; arrays of scalars on one line, so a
    sample's ``index`` and ``loss`` have one event per line, and objects that
    fit in :data:`INLINE_WIDTH` characters too; floats as their shortest
    round-trip ``repr``; a final newline.

    Parameters
    ----------
    document : mapping
        A document.

    Returns
    -------
    str
        The file's text.
    """
    return _render(dict(document), 0) + "\n"


# --------------------------------------------------------------------------
# The regeneration check
# --------------------------------------------------------------------------

UNITLESS_METRICS: Final[tuple[str, ...]] = (
    "coverage_ratio",
    "payout_to_loss_ratio",
    "payout_frequency",
    "correlation",
    "tail_coverage_b",
    "cvar_uncovered_to_loss_b",
    "false_negative_rate_l",
    "false_positive_rate_l",
)
"""Metrics without a loss unit; a name ending in ``_b`` or ``_l`` is a prefix."""


def metric_is_unitless(column: str) -> bool:
    """Whether a metric column has no loss unit."""
    return any(
        column == name or (name[-2:] in ("_b", "_l") and column.startswith(name))
        for name in UNITLESS_METRICS
    )


def _floor(path: tuple[str, ...], case: Mapping[str, Any], scale: float) -> float:
    """Absolute tolerance unit of the float at ``path``."""
    if len(path) < 2 or path[0] != F.expected:
        return scale
    if path[1] == F.objective_value:
        objective = case.get(F.objective) or {}
        return scale**2 if objective.get(F.kind) == F.objective_mse else scale
    if path[1] == F.metrics and metric_is_unitless(path[-1]):
        return 1.0
    return scale


def compare_documents(
    committed: Mapping[str, Any],
    regenerated: Mapping[str, Any],
    scale: float,
    *,
    skip: Iterable[tuple[str, ...]] = (),
    rtol: float | None = None,
) -> list[str]:
    """Compare a committed document with its regeneration; return the differences.

    Everything but floats must be equal, except ``generator.commit``. Floats
    agree within :data:`REGEN_RTOL_SOLVED` (the ``expected`` block of a core
    design) or :data:`REGEN_RTOL_EXACT` (everything else), relative, with the
    same tolerance times the scale as an absolute floor. A quantile written as
    ``{"either": [lower, upper]}`` on one side matches a single value on the
    other if that value matches one of the two atoms.

    Parameters
    ----------
    committed, regenerated : mapping
        The two documents.
    scale : float
        The sample's scale.
    skip : iterable of tuple of str, optional
        Paths not to compare.
    rtol : float, optional
        One relative tolerance for every float.

    Returns
    -------
    list of str
        One line per difference; empty if they agree.
    """
    problems: list[str] = []
    solved = (
        regenerated.get(F.kind) == F.kind_design
        and regenerated.get(F.source) == F.source_core
    )
    skipped = set(skip)

    def tol(path: tuple[str, ...]) -> float:
        if rtol is not None:
            return rtol
        in_expected = bool(path) and path[0] == F.expected
        return REGEN_RTOL_SOLVED if solved and in_expected else REGEN_RTOL_EXACT

    def close(a: float, b: float, path: tuple[str, ...]) -> bool:
        value = tol(path)
        return math.isclose(
            a, b, rel_tol=value, abs_tol=value * _floor(path, regenerated, scale)
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
design is not unique: judged by :func:`compare_case`, not compared."""


def levels_of(document: Mapping[str, Any], n_levels: int) -> NDArray[np.float64]:
    """Return a step design's ``expected.parameters`` as ``(n_units, n_levels)``."""
    parameters = document[F.expected][F.parameters]
    names = [level_name(k) for k in range(n_levels)]
    return np.array(
        [
            [float(parameters[u][n]) for n in names]
            for u in document[F.cover][F.unit_id]
        ],
        dtype=np.float64,
    )


def _unidentified_paths(document: Mapping[str, Any]) -> list[tuple[str, ...]]:
    """Paths of the unidentified levels in ``expected.parameters``."""
    base = (F.expected, F.parameters)
    return [
        (*base, unit, name)
        for unit, names in document[F.expected][F.unidentified].items()
        for name in names
    ]


def compare_case(committed: Mapping[str, Any], generated: GeneratedCase) -> list[str]:
    """Judge a committed case against its regeneration; return the differences.

    Closed-form cases and the inputs of every case are compared with
    :func:`compare_documents`. A core design is judged in three more ways,
    which hold whichever point of a set of optimal designs a solver returns:

    1. The committed values are the core's at the committed levels.
    2. The committed levels are an optimal design of the regenerated problem:
       they meet every constraint, and their objective agrees with the
       regenerated optimum within :data:`REGEN_RTOL_SOLVED`.
    3. They lie within the regenerated ranges (LP cases), widened by
       :data:`UNIQUE_WIDTH` of the scale.

    Only a unique design has its identified levels, premium and metrics also
    compared with the regenerated ones.

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
    scale = generated.scale
    if generated.evaluate is None or generated.violations is None:
        return compare_documents(committed, regenerated, scale)
    if generated.identified is None:
        raise ValueError("a core design needs its identified levels")
    unique = (
        regenerated[F.compare_parameters] == F.compare_exact
        and committed.get(F.compare_parameters) == F.compare_exact
    )
    problems = compare_documents(
        committed,
        regenerated,
        scale,
        skip=_unidentified_paths(regenerated) if unique else SOLVER_POINT_FIELDS,
    )
    try:
        levels = levels_of(committed, generated.identified.shape[1])
    except (KeyError, TypeError, ValueError) as exc:
        return [*problems, f"{F.expected}/{F.parameters}: unreadable ({exc!r})"]
    evaluated = generated.evaluate(levels)
    keys = (F.objective_value, F.premium, F.metrics)
    problems += compare_documents(
        {**committed, F.expected: {k: committed[F.expected].get(k) for k in keys}},
        {**regenerated, F.expected: evaluated},
        scale,
        rtol=REGEN_RTOL_EXACT,
    )
    problems += [
        f"{F.expected}/{F.parameters}: {v}" for v in generated.violations(levels)
    ]
    mse = (regenerated[F.objective] or {}).get(F.kind) == F.objective_mse
    floor = scale**2 if mse else scale
    at_levels = evaluated[F.objective_value]
    optimum = regenerated[F.expected][F.objective_value]
    pairs = (
        [(at_levels, optimum)]
        if isinstance(optimum, float)
        else [(at_levels[u], optimum[u]) for u in optimum]
    )
    for at, best in pairs:
        if not math.isclose(
            float(at),
            float(best),
            rel_tol=REGEN_RTOL_SOLVED,
            abs_tol=REGEN_RTOL_SOLVED * floor,
        ):
            problems.append(
                f"{F.expected}/{F.parameters}: objective {at!r} at the committed "
                f"levels, regenerated optimum {best!r}"
            )
    if generated.ranges is not None:
        low, high = generated.ranges
        pad = UNIQUE_WIDTH * scale
        outside = generated.identified & ((levels < low - pad) | (levels > high + pad))
        for j, k in zip(*np.nonzero(outside), strict=True):
            problems.append(
                f"{F.expected}/{F.parameters}: unit {j} level {int(k)} = "
                f"{levels[j, k]!r} outside [{low[j, k]!r}, {high[j, k]!r}]"
            )
    return problems


def summary(fixtures: FixtureSet, sizes: Mapping[str, int]) -> str:
    """Return a Markdown table of the cases: kind, source, comparison, size."""
    lines = [
        "| Case | Kind | Source | Scope | Basis | Compare parameters | Size (bytes) |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, case in fixtures.cases.items():
        doc = case.document
        lines.append(
            f"| `{doc[F.case_id]}` | {doc[F.kind]} | {doc[F.source]} | {doc[F.scope]} "
            f"| {doc[F.basis][F.kind]} | {doc[F.compare_parameters]} "
            f"| {sizes[f'cases/{name}']:,} |"
        )
    lines.append(
        f"| **Total ({len(sizes)} files)** | | | | | | **{sum(sizes.values()):,}** |"
    )
    return "\n".join(lines)


def texts_of(fixtures: FixtureSet) -> dict[str, str]:
    """Return the file texts of a set, by path relative to ``parity/climada``."""
    texts = {f"samples/{n}": render(doc) for n, doc in fixtures.samples.items()}
    texts |= {f"cases/{n}": render(c.document) for n, c in fixtures.cases.items()}
    return texts


def main(argv: Sequence[str] | None = None) -> int:
    """Write the set, or with ``--check`` compare it with the committed one.

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
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    parser.add_argument("--summary", action="store_true", help="print the case table")
    args = parser.parse_args(argv)
    fixtures = build_set()
    texts = texts_of(fixtures)
    out_dir: Path = args.out
    committed_files = {
        str(p.relative_to(out_dir))
        for folder in ("samples", "cases")
        for p in (out_dir / folder).glob("*.json")
    }
    if args.check:
        problems = [f"missing: {n}" for n in sorted(set(texts) - committed_files)]
        problems += [
            f"not generated: {n}" for n in sorted(committed_files - set(texts))
        ]
        identical = 0
        for name in sorted(set(texts) & committed_files):
            text = (out_dir / name).read_text(encoding="utf-8")
            identical += text == texts[name]
            committed = json.loads(text)
            if name.startswith("samples/"):
                diffs = compare_documents(
                    committed,
                    fixtures.samples[name.removeprefix("samples/")],
                    1.0,
                )
            else:
                diffs = compare_case(
                    committed, fixtures.cases[name.removeprefix("cases/")]
                )
            problems += [f"{name}: {d}" for d in diffs]
        print(f"{identical} of {len(texts)} files byte-identical")
        for line in problems:
            print(line)
        return 1 if problems else 0
    for folder in ("samples", "cases"):
        (out_dir / folder).mkdir(parents=True, exist_ok=True)
    for stale in committed_files - set(texts):
        (out_dir / stale).unlink()
    for name, text in texts.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    sizes = {name: len(text.encode("utf-8")) for name, text in texts.items()}
    if args.summary:
        print(summary(fixtures, sizes))
    print(f"wrote {len(texts)} files, {sum(sizes.values()):,} bytes, to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
