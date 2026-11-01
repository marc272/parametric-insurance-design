r"""MAR-198: the range of the individual scope's portfolio-level KPIs.

C1 (``research/checkpoints/C1.md`` section 6b, observation 32, T11) measured
how wide the optimal set of a **joint** design is. An **individual** design
(9 problems, one per asset) is not unique either: each asset's LP (or QP) can
have several optimal payouts. The 9 per-asset objective values are then
fixed, but the **portfolio-level** KPIs of the individual scope (the RQ2
baseline: the owner's annual uncovered loss summed over the 9 assets) are a
function of the 9 payouts, so they are not fixed by the 9 problems.

For every design of the C1 main line at kappa 1 (pricing pure and cost of
capital r 0.06, q 0.99; designs MSE, E[U], weighted CVaR beta 0.99 and
0.995), this script:

1. rebuilds the 9 individual design problems on the train years from the C1
   config, re-solves each with the default policy (the objective must equal
   the stored C1 run's, rtol 1e-6) and once more with another solver order
   (``c1_rq2.ALT_POLICY``: HiGHS first for LPs, CLARABEL first for QPs);
2. defines the near-optimal set of asset ``i`` as the problem's own feasible
   set with ``objective_i <= optimum_i + RANGE_REL_TOL * |optimum_i|`` (C1
   T11's tolerance, 1e-5 relative) and the individual scope's near-optimal
   set as their product;
3. for each split (train, test) and portfolio KPI (E[U]; CVaR at 0.95, 0.99,
   0.995 of the annual uncovered loss), finds the **smallest** value over the
   set exactly (one convex program: the KPI is convex in the payouts) and the
   **largest** value found by successive linearisation (maximising a convex
   function over a convex set; each step maximises the KPI's linearisation,
   which is separable across the 9 assets, so 9 small programs per step;
   several starts). The largest value found is an inner bound on the true
   maximum. An outer bound is the KPI of the coordinate-wise smallest
   payout parameters over the set (the KPI is non-increasing in every step
   payout parameter; that point need not be in the set);
4. bootstraps the extreme designs' test KPIs on the C1 resample (B 1000,
   seed 0, level 0.9) and recomputes, at the ends of the ranges, the
   paired differences that C1 section 6b (portfolio and cluster minus
   individual) and MAR-182 (``research/notes/c1-combination.md``: the
   combination contrasts) report, after checking that the stored designs
   reproduce their values and intervals.

A validation group repeats the MAR-165 observation (the issue's starting
point): the example config of ``examples/portfolio_calibration.py`` (no noise
layer, ``below_attachment = "zero"``), E[U], pure, kappa 1, with and without
the 20 m/s threshold filter. The two runs have the same per-asset optima and
different portfolio train E[U] (5,330.25 and 5,282.66 USD); both must lie in
the range.

Outputs: the full tables to ``results/mar198/`` (not committed); the
committed ones, each well under 500 kB, to
``research/data/individual-nonuniqueness/``:

* ``ranges.csv``: per (setup, pricing, design, split, KPI): the stored value,
  the smallest and largest value over the near-optimal set, the outer bound,
  the alternative-solver value, statuses, the config hash and tolerance;
* ``asset_ranges.csv``: per asset, its train ``E[pi_i]/E[L_i]`` range over
  its near-optimal set (T11's measure for the individual scope) and the
  largest parameter change of an extreme design against the stored one;
* ``rq2_ends.csv``: C1 section 6b's joint-minus-individual differences with
  the individual design at the stored point and at each end of its range;
* ``contrasts_ends.csv``: MAR-182's contrasts likewise;
* ``summary.json``: inputs, checks, timings.

Run from the repository root (reads the C1 store; never writes to it)::

    uv run python research/scripts/individual_nonuniqueness.py \
        --c1-store <C1 results>/c1/store --jobs 4

Observations only. The interpretation is the owner's.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Final

import c1_checkpoint as c1
import c1_rq2 as rq2
import cvxpy as cp
import numpy as np
import pandas as pd

from parametric_insurance_design import splits
from parametric_insurance_design.bootstrap import (
    bootstrap_kpis,
    percentile_interval,
    resample_years,
)
from parametric_insurance_design.evaluate import kpis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import package_versions, run_key
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import (
    ProblemContext,
    Sample,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.objectives import rockafellar_uryasev
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.riskmeasures import var_cvar
from parametric_insurance_design.solve import DEFAULT_POLICY, solve

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "individual-nonuniqueness"
FULL_DIR: Final[Path] = REPO_ROOT / "results" / "mar198"
FIXTURE: Final[Path] = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"

RANGE_REL_TOL: Final[float] = float(
    os.environ.get("MAR198_REL_TOL", str(rq2.RANGE_REL_TOL))
)
"""Near-optimal set of asset i: objective_i <= optimum_i + tol * |optimum_i|.

C1 T11's 1e-5 by default; the environment variable ``MAR198_REL_TOL`` sets
another one for the tolerance sensitivity (read at import, so that the
spawned workers see it too)."""
PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06")
DESIGNS: Final[tuple[str, ...]] = rq2.DESIGNS
EVAL_BETAS: Final[tuple[float, ...]] = c1.ANNUAL_EVAL_BETAS
KPIS: Final[tuple[tuple[str, float | None], ...]] = (
    ("expected_uncovered", None),
    ("cvar_uncovered", 0.95),
    ("cvar_uncovered", 0.99),
    ("cvar_uncovered", 0.995),
)
"""The portfolio KPIs whose range is measured (``kpi``, KPI beta)."""
SPLITS: Final[tuple[str, ...]] = ("train", "test")
SOLVER: Final[str] = "CLARABEL"
"""Range programs: CLARABEL (as C1 T11), with :data:`MAX_ITER` iterations if
the default limit ends short of ``optimal``. Not HiGHS: on the joint
programs it reported ``optimal`` for points far from the optimum (the stored
design gave a smaller value), so it is not used. A program that ends short
of ``optimal`` keeps CLARABEL's last iterate, repaired onto the set by
:meth:`AssetSet.admit`, and its status: every design is checked against the
near-optimal set and evaluated with the library, so such an end is a member
of the set (an inner point of the range), reported with its status."""
MAX_ITER: Final[int] = 2000
"""CLARABEL iteration limit of the second attempt (default 200)."""
MAX_STARTS: Final[tuple[str, ...]] = ("stored", "alt_solver")
"""Starts of the successive linearisation: the C1 design and the
alternative-solver design."""
MAX_STEPS: Final[int] = 25
"""Successive-linearisation steps per start, at most."""
STEP_RTOL: Final[float] = 1e-9
"""A step that raises the KPI by less than this (relative) ends a start."""
OBJ_CHECK_RTOL: Final[float] = 1e-6
"""A design is accepted as near-optimal if objective_i <= bound_i (1 + this)."""
PROJECT_MARGIN: Final[float] = 1e-6
"""Budget margin of the projection that repairs an infeasible iterate."""
MAR165_TRAIN_EU: Final[dict[str, float]] = {"filter": 5330.25, "no_filter": 5282.66}
"""MAR-165's portfolio train E[U] of the individual E[U] designs (USD)."""


def kpi_label(kpi: str, beta: float | None) -> str:
    """Short label of a portfolio KPI, e.g. ``cvar@0.99`` or ``eu``."""
    return "eu" if beta is None else f"cvar@{beta:g}"


# --------------------------------------------------------------------------
# Groups
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Group:
    """One individual design to measure, and the joint designs to compare.

    Parameters
    ----------
    setup : str
        ``"c1"`` (main line) or ``"mar165_filter"`` / ``"mar165_no_filter"``.
    pricing, design : str
        C1 labels.
    config : ExperimentConfig
        The individual scope's single-run config.
    run_id : str or None
        The C1 run in the store; None for the validation groups (solved here).
    joint : dict
        Scope name to (config, run id) of the C1 joint runs (empty for the
        validation groups).
    """

    setup: str
    pricing: str
    design: str
    config: ExperimentConfig
    run_id: str | None
    joint: dict[str, tuple[ExperimentConfig, str]]


def c1_groups() -> list[Group]:
    """Return the C1 main-line groups at kappa 1, pure and r 0.06."""
    specs, _ = c1.plan(["main"])
    checksum = str(load_config(c1.BASE_CONFIG).eventset.checksum)
    members: dict[tuple[str, str], dict[str, tuple[ExperimentConfig, str]]] = {}
    for s in specs:
        v = s.variant
        if v.kappa != 1.0 or v.pricing not in PRICINGS or s.design not in DESIGNS:
            continue
        rid = run_key(config_hash(s.config), checksum, policy=DEFAULT_POLICY)
        members.setdefault((v.pricing, s.design), {})[s.scope] = (s.config, rid)
    out: list[Group] = []
    for pricing in PRICINGS:
        for design in DESIGNS:
            m = members[(pricing, design)]
            cfg, rid = m["individual"]
            joint = {k: m[k] for k in ("portfolio", "cluster")}
            out.append(Group("c1", pricing, design, cfg, rid, joint))
    return out


def mar165_config(threshold: bool) -> ExperimentConfig:
    """Return the MAR-165 example config: individual, E[U], pure, kappa 1."""
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "mar198-mar165-check",
        "eventset": {"path": str(FIXTURE)},
        "basis": "annual",
        "sample": {"kind": "holdout", "train_fraction": 0.7},
        "payout": {
            "attachment": 20.0,
            "limit": 70.0,
            "n_bins": 15,
            "below_attachment": "zero",
        },
        "scopes": [{"kind": "individual"}],
        "objectives": [{"kind": "expected_uncovered"}],
        "pricing": {"kind": "pure"},
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.99},
        "output": {"directory": str(FULL_DIR / "unused-store")},
    }
    if threshold:
        data["threshold"] = {"value": 20.0}
    return parse_config(data)


def validation_groups() -> list[Group]:
    """Return the MAR-165 check groups, with and without the threshold."""
    return [
        Group(f"mar165_{name}", "pure", "eu", mar165_config(flag), None, {})
        for name, flag in (("filter", True), ("no_filter", False))
    ]


def solve_range(prob: cp.Problem) -> str:
    """Solve a range program (:data:`SOLVER`); return its status.

    ``"optimal"``, or the status after the second attempt with
    :data:`MAX_ITER` iterations, suffixed ``"/long"`` when that attempt was
    made.
    """
    try:
        prob.solve(solver=SOLVER)
    except cp.error.SolverError:
        pass
    if prob.status == "optimal":
        return "optimal"
    try:
        prob.solve(solver=SOLVER, max_iter=MAX_ITER)
    except cp.error.SolverError:
        # no iterate to keep: the caller sees theta.value None, or a stale
        # value that admit() rechecks
        for v in prob.variables():
            v.value = None
        return "solver_error/long"
    return f"{prob.status}/long"


def in_set(check: dict[str, float]) -> bool:
    """Whether an :meth:`AssetSet.check` result is inside the near-optimal set."""
    return (
        check["objective_excess"] <= RANGE_REL_TOL + OBJ_CHECK_RTOL
        and check["budget_excess"] <= OBJ_CHECK_RTOL
        and check["structure_violation"] <= OBJ_CHECK_RTOL
    )


def is_optimal(status: str) -> bool:
    """Whether a :func:`solve_range` status is ``optimal``."""
    return status.split("/")[0].split(" ")[0] == "optimal"


# --------------------------------------------------------------------------
# The near-optimal set of one asset
# --------------------------------------------------------------------------


class AssetSet:
    """Asset ``i``'s near-optimal set, with a parametrised linear program.

    Parameters
    ----------
    built : BuiltProblem
        The asset's design problem, already solved (its variables hold the
        optimum).
    """

    def __init__(self, built: BuiltProblem, cfg: ExperimentConfig) -> None:
        self.built = built
        self.cfg = cfg
        self.ctx: ProblemContext = built.context
        self.optimum = float(np.asarray(built.objective.expression.value))
        self.bound = self.optimum + RANGE_REL_TOL * abs(self.optimum)
        self.constraints = [
            *built.problem.constraints,
            built.objective.expression <= self.bound,
        ]
        n = self.ctx.payout_structure.n_params
        self.cost = cp.Parameter(n, name="cost")
        theta = self.ctx.theta[0]
        self.lp = cp.Problem(cp.Minimize(self.cost @ theta), self.constraints)
        # projection onto the set with a margin (repairs a solver's slightly
        # infeasible iterate): the set's own bound (the check allows
        # OBJ_CHECK_RTOL above it), the budget PROJECT_MARGIN inside
        (budget,) = cfg.to_components().constraints
        limit = budget.loading * self.ctx.expected_loss  # type: ignore[attr-defined]
        self.target = cp.Parameter(n, name="target")
        gap = cp.Variable(name="gap")
        self.projection = cp.Problem(
            cp.Minimize(gap),
            [
                *built.problem.constraints,
                built.objective.expression
                <= self.optimum + RANGE_REL_TOL * abs(self.optimum),
                built.premium.expression <= (1.0 - PROJECT_MARGIN) * limit,
                theta - self.target <= gap,
                self.target - theta <= gap,
            ],
        )

    @property
    def scale(self) -> float:
        """The problem's loss scale."""
        return float(self.ctx.scale)

    def minimise(self, cost: np.ndarray) -> tuple[np.ndarray, str]:
        """Minimise ``cost @ theta`` (scaled units) over the set.

        Returns
        -------
        theta : numpy.ndarray
            The minimiser in **loss units**, shape ``(n_params,)``; NaN if the
            program did not end optimal.
        status : str
            cvxpy status.
        """
        c = np.asarray(cost, dtype=np.float64)
        top = float(np.max(np.abs(c), initial=0.0))
        self.cost.value = c / top if top > 0 else c  # same minimiser
        status = solve_range(self.lp)
        if self.ctx.theta.value is None:
            return np.full(self.cost.shape, math.nan), status
        return np.asarray(self.ctx.theta.value)[0] * self.scale, status

    def admit(self, theta_loss: np.ndarray) -> tuple[np.ndarray, str]:
        """Return a design in the set: as given, projected, or NaN.

        Returns
        -------
        theta : numpy.ndarray
            ``theta_loss`` if it passes :meth:`check`; else its projection
            onto the set (with a margin) if that passes; else NaN.
        note : str
            ``""``, ``"projected"`` or ``"outside_set"``.
        """
        theta = np.asarray(theta_loss, dtype=np.float64)
        if not np.all(np.isfinite(theta)):
            return theta, "outside_set"
        if in_set(self.check(theta, self.cfg)):
            return theta, ""
        self.target.value = theta / self.scale
        solve_range(self.projection)
        if self.ctx.theta.value is not None:
            proj = np.asarray(self.ctx.theta.value)[0] * self.scale
            if in_set(self.check(proj, self.cfg)):
                return proj, "projected"
        return np.full_like(theta, math.nan), "outside_set"

    def check(self, theta_loss: np.ndarray, cfg: ExperimentConfig) -> dict[str, float]:
        """Is a design (loss units) in the near-optimal set? Recomputed in numpy.

        Independent of the cvxpy auxiliaries: the objective (MSE, E[U] or
        weighted CVaR of the asset's annual outcomes, ``var_cvar`` for the
        CVaR), the premium (``pricing.premium_value``) against the budget,
        and the payout structure (non-negative, non-decreasing, capped).

        Returns
        -------
        dict
            ``objective_excess``: (objective - optimum) / |optimum|, at most
            ``RANGE_REL_TOL`` inside the set; ``budget_excess``: (premium -
            budget) / budget, at most 0; ``structure_violation``: the largest
            violation of the payout constraints relative to the cap.
        """
        comps = cfg.to_components()
        problem = self.ctx.problem
        measure = self.ctx.measure
        theta = np.asarray(theta_loss, dtype=np.float64)
        payout = np.asarray(comps.payout.basis_matrix(problem.index[:, 0])) @ theta
        loss = problem.entity_loss[:, 0]
        p = measure.probability
        u = measure.aggregate(np.maximum(0.0, loss - payout))
        objective = comps.objectives[0]
        if objective.name == "mse":
            value = float(p @ measure.aggregate(loss - payout) ** 2)
        elif objective.name == "expected_uncovered":
            value = float(p @ u)
        else:
            alpha, beta = objective.alpha, objective.beta  # type: ignore[attr-defined]
            value = alpha * var_cvar(u, p, beta)[1] + (1.0 - alpha) * float(p @ u)
        homogeneity = self.built.objective.homogeneity
        optimum = self.optimum * self.scale**homogeneity
        premium = comps.pricing.premium_value(payout, measure)
        (budget,) = comps.constraints
        limit = budget.loading * measure.expectation(loss)  # type: ignore[attr-defined]
        cap = float(self.ctx.cap[0] * self.scale)
        structure = max(
            float(np.max(-theta, initial=0.0)),
            float(np.max(-np.diff(theta), initial=0.0)),
            float(np.max(theta - cap, initial=0.0)),
        ) / max(cap, 1.0)
        return {
            "objective_excess": (value - optimum) / max(abs(optimum), 1e-300),
            "budget_excess": (premium - limit) / max(abs(limit), 1e-300),
            "structure_violation": structure,
        }


# --------------------------------------------------------------------------
# Portfolio KPIs as functions of the 9 payouts
# --------------------------------------------------------------------------


@dataclass
class SplitData:
    """Per-row data of one split: losses, basis matrices, measure.

    ``basis[i]`` maps asset ``i``'s parameters (loss units) to its payout
    per row; ``loss`` is the portfolio loss per row (the sum over the 9
    assets, as ``evaluate`` forms it).
    """

    sample: Sample
    eventset: EventSet
    measure: Any
    loss: np.ndarray
    basis: list[Any]

    def payout(self, thetas: Sequence[np.ndarray]) -> np.ndarray:
        """Portfolio payout per row of 9 parameter vectors (loss units)."""
        return np.asarray(sum(b @ t for b, t in zip(self.basis, thetas, strict=True)))

    def value(
        self, thetas: Sequence[np.ndarray], kpi: str, beta: float | None
    ) -> float:
        """Portfolio KPI (numpy, the ``evaluate`` definition).

        NaN if a parameter is NaN (a failed program).
        """
        if not all(np.all(np.isfinite(t)) for t in thetas):
            return math.nan
        u = self.measure.aggregate(np.maximum(0.0, self.loss - self.payout(thetas)))
        p = self.measure.probability
        if beta is None:
            return float(p @ u)
        return var_cvar(u, p, beta)[1]

    def weights(
        self, thetas: Sequence[np.ndarray], kpi: str, beta: float | None
    ) -> np.ndarray:
        """Row weights ``w`` of a subgradient of the KPI w.r.t. the payout.

        The KPI at ``thetas`` is ``sum_o q_o sum_{e in o} (L_e - pi_e)^+``
        with ``q = p`` (E[U]) or the CVaR tail weights (mass 1 on the worst
        ``1 - beta`` of outcomes, the boundary atom split). Its linearisation
        is ``const - sum_e w_e pi_e`` with ``w_e = q_{o(e)} 1[L_e > pi_e]``.
        """
        resid = self.loss - self.payout(thetas)
        u = self.measure.aggregate(np.maximum(0.0, resid))
        p = np.asarray(self.measure.probability, dtype=np.float64)
        if beta is None:
            q = p
        else:
            order = np.argsort(-u, kind="stable")
            mass = 1.0 - beta
            q = np.zeros_like(p)
            taken = 0.0
            for o in order:
                share = min(p[o], mass - taken)
                if share <= 0:
                    break
                q[o] = share / mass
                taken += share
        active = (resid > 0).astype(np.float64)
        rows = np.asarray(self.measure.outcome_of_row)
        return q[rows] * active


def hessian_min_eig_rel(sd: SplitData, basis: np.ndarray) -> float:
    """Smallest over largest eigenvalue of the MSE Hessian in theta.

    ``A' diag(p) A`` with ``A`` the asset's basis matrix summed into the
    split's outcomes. Positive: the MSE objective is strictly convex in the
    payout parameters, so its optimum is unique.
    """
    a = sd.measure.aggregate(basis)
    h = a.T @ (a * np.asarray(sd.measure.probability)[:, None])
    eig = np.linalg.eigvalsh(h)
    return float(eig[0] / eig[-1]) if eig[-1] > 0 else math.nan


def split_data(
    prepared: EventSet, sample: Sample, cfg: ExperimentConfig, built: Sequence[Any]
) -> SplitData:
    """Per-row data of a split for the 9 individual problems' specs."""
    from parametric_insurance_design.basis import outcome_measure

    comps = cfg.to_components()
    data = sample.select(prepared)
    measure = outcome_measure(data, comps.basis, years=sample.years)
    scope = comps.scopes[0]
    basis = []
    for b in built:
        problem = scope.materialise(data, b.spec)
        basis.append(
            np.asarray(comps.payout.basis_matrix(problem.index[:, 0]), dtype=np.float64)
        )
    loss = np.vstack(list(data.loss.T)).sum(axis=0)
    return SplitData(sample, data, measure, loss, basis)


def joint_minimum(
    sets: Sequence[AssetSet],
    sd: SplitData,
    kpi: str,
    beta: float | None,
    reference: float,
) -> tuple[list[np.ndarray], str]:
    """Smallest portfolio KPI over the product of the near-optimal sets.

    One convex program: the 9 assets' near-optimal constraints, and the
    portfolio KPI of the summed payout on the split's rows (E[U], or CVaR in
    the Rockafellar-Uryasev form), divided by ``reference`` (the stored
    design's KPI) so that the objective is of order one. Each asset's part of
    the solution is then admitted to its set (:meth:`AssetSet.admit`).
    """
    norm = float(max(sd.loss.max(initial=0.0), 1.0))
    payout = sum(
        (b @ s.ctx.theta[0]) * (s.scale / norm)
        for b, s in zip(sd.basis, sets, strict=True)
    )
    u_rows = cp.pos(sd.loss / norm - payout)
    u = sd.measure.aggregate_expression(u_rows)
    p = np.asarray(sd.measure.probability, dtype=np.float64)
    if beta is None:
        goal: cp.Expression = p @ u
    else:
        goal = rockafellar_uryasev(u, p, beta)[0]
    factor = norm / reference if reference > 0 else 1.0
    cons = [c for s in sets for c in s.constraints]
    prob = cp.Problem(cp.Minimize(goal * factor), cons)
    status = solve_range(prob)
    if any(s.ctx.theta.value is None for s in sets):
        return [np.full(s.cost.shape, math.nan) for s in sets], status
    raw = [np.asarray(s.ctx.theta.value)[0] * s.scale for s in sets]
    out: list[np.ndarray] = []
    notes: set[str] = set()
    for s, t in zip(sets, raw, strict=True):
        theta, note = s.admit(t)
        out.append(theta)
        if note:
            notes.add(note)
    return out, status + "".join(f" {n}" for n in sorted(notes))


def linearised_maximum(
    sets: Sequence[AssetSet],
    sd: SplitData,
    kpi: str,
    beta: float | None,
    start: Sequence[np.ndarray],
) -> tuple[list[np.ndarray], float, int, str]:
    """Largest KPI found from ``start`` by successive linearisation.

    Each step maximises the KPI's linearisation at the current design over
    the product set: ``minimise sum_e w_e pi_e``, separable, so one LP per
    asset (cost ``B_i^T w`` in scaled units). The KPI never decreases along
    the steps (it is convex, so it lies above its linearisation).

    Returns
    -------
    thetas, value, steps, status
        The design reached (loss units), its KPI, the number of steps taken
        and ``"optimal"`` or the first failed LP's status.
    """
    notes: set[str] = set()
    current: list[np.ndarray] = []
    for s, t in zip(sets, start, strict=True):
        theta, note = s.admit(np.asarray(t, dtype=np.float64))
        if note == "outside_set":
            return list(start), -math.inf, 0, "start outside_set"
        if note:
            notes.add(f"start {note}")
        current.append(theta)
    value = sd.value(current, kpi, beta)
    for step in range(1, MAX_STEPS + 1):
        w = sd.weights(current, kpi, beta)
        nxt: list[np.ndarray] = []
        for s, b in zip(sets, sd.basis, strict=True):
            cost = (b.T @ w) * s.scale
            theta, status = s.minimise(cost)
            theta, note = s.admit(theta)
            if note == "outside_set":
                return current, value, step, f"{status} {note}"
            if not is_optimal(status) or note:
                notes.add(f"{status} {note}".strip())
            nxt.append(theta)
        new = sd.value(nxt, kpi, beta)
        if new <= value * (1.0 + STEP_RTOL) + 1e-9:
            if new > value:
                current, value = nxt, new
            return current, value, step, ";".join(["optimal", *sorted(notes)])
        current, value = nxt, new
    return current, value, MAX_STEPS, ";".join(["step limit", *sorted(notes)])


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------


def _results(
    built: Sequence[BuiltProblem], thetas: Sequence[np.ndarray], label: str
) -> list[SolveResult]:
    """SolveResults (loss units) of a candidate individual design."""
    return [
        SolveResult(
            spec=b.spec,
            payout_structure=b.context.payout_structure,
            theta=np.asarray(t)[None, :],
            status=SolveStatus.OPTIMAL,
            objective_value=math.nan,
            premium=math.nan,
            scale=1.0,
            solver=label,
            attempts=(),
            build_seconds=0.0,
            solve_seconds=0.0,
        )
        for b, t in zip(built, thetas, strict=True)
    ]


def range_worker(group: Group, store_root: str | None) -> dict[str, Any]:
    """Measure one individual design's portfolio-KPI ranges.

    Parameters
    ----------
    group : Group
        The design.
    store_root : str or None
        The C1 result store (None: validation group).

    Returns
    -------
    dict
        ``ranges`` (rows), ``assets`` (rows), ``reps`` (test replicates of
        every candidate and joint design, portfolio level), ``meta``.
    """
    t0 = time.perf_counter()
    cfg = group.config
    comps = cfg.to_components()
    prepared = c1._prepared(cfg)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    store = ResultStore(Path(store_root)) if store_root else None
    stored_results: list[SolveResult] | None = None
    if group.run_id is not None:
        assert store is not None
        stored_results = rq2._stored(cfg, group.run_id, store).results
        specs = [r.spec for r in stored_results]
    else:
        specs = list(comps.scopes[0].partition(train.select(prepared)))
    built = build_problems(
        prepared,
        comps.scopes[0],
        comps.payout,
        comps.objectives[0],
        comps.pricing,
        comps.constraints,
        basis=comps.basis,
        sample=train,
        specs=specs,
    )
    # the alternative solver order first, then the default (the variables
    # keep the default optimum, which the near-optimal sets use)
    alt = [solve(b, rq2.ALT_POLICY, pricing=comps.pricing) for b in built]
    default = [solve(b, DEFAULT_POLICY, pricing=comps.pricing) for b in built]
    if stored_results is None:
        stored_results = default
    for r, s in zip(default, stored_results, strict=True):
        if not np.isclose(r.objective_value, s.objective_value, rtol=1e-6, atol=1e-6):
            raise RuntimeError(
                f"{group.setup} {group.pricing} {group.design} {r.problem_id}: "
                f"re-solved objective {r.objective_value!r} != stored "
                f"{s.objective_value!r}"
            )
    sets = [AssetSet(b, cfg) for b in built]
    sd = {
        "train": split_data(prepared, train, cfg, built),
        "test": split_data(prepared, test, cfg, built),
    }
    cand: dict[str, list[np.ndarray]] = {
        "stored": [np.asarray(r.theta)[0] for r in stored_results],
        "resolved": [np.asarray(r.theta)[0] for r in default],
        "alt_solver": [np.asarray(r.theta)[0] for r in alt],
    }
    meta: dict[str, Any] = {
        "alt_solvers": ",".join(sorted({r.solver for r in alt})),
        "alt_statuses": ",".join(sorted({r.status.value for r in alt})),
        "default_solvers": ",".join(sorted({r.solver for r in default})),
        "alt_objective_rel_diff_max": max(
            abs(a.objective_value - d.objective_value) / max(abs(d.objective_value), 1)
            for a, d in zip(alt, default, strict=True)
        ),
    }

    # outer bound: coordinate-wise smallest parameters over each asset's set
    n = comps.payout.n_params
    low: list[np.ndarray] = []
    low_status: set[str] = set()
    for s in sets:
        vals = np.empty(n)
        for k in range(n):
            e = np.zeros(n)
            e[k] = 1.0
            theta, status = s.minimise(e)
            low_status.add(status)
            vals[k] = theta[k]
        low.append(vals)
    meta["outer_bound_statuses"] = ",".join(sorted(low_status))

    # per-asset train payout-to-loss ranges (T11's measure, individual scope)
    asset_rows: list[dict[str, Any]] = []
    tr = sd["train"]
    for i, s in enumerate(sets):
        b = tr.basis[i]
        el = tr.measure.expectation(tr.eventset.loss[:, i])
        p_rows = tr.measure.probability[np.asarray(tr.measure.outcome_of_row)]
        cost = (b.T @ p_rows) * s.scale  # E[pi_i] in scaled units per theta
        lo_t, st_lo = s.minimise(cost)
        hi_t, st_hi = s.minimise(-cost)

        def ratio(t: np.ndarray, b: np.ndarray = b, el: float = el) -> float:
            if not np.all(np.isfinite(t)):
                return math.nan
            return float(tr.measure.expectation(b @ t) / el)

        asset_rows.append(
            {
                "entity_id": s.built.spec.problem_id,
                "stored_payout_to_loss": ratio(cand["stored"][i]),
                "min_payout_to_loss": ratio(lo_t),
                "max_payout_to_loss": ratio(hi_t),
                "status_min": st_lo,
                "status_max": st_hi,
                "cap": float(s.ctx.cap[0] * s.scale),
                "optimum_loss_units": default[i].objective_value,
                # MSE: the objective is quadratic in theta with Hessian
                # A' diag(p) A (A: the basis summed into outcomes); a smallest
                # eigenvalue > 0 makes the optimum unique
                "mse_hessian_min_eig_rel": hessian_min_eig_rel(tr, b),
            }
        )

    # ranges
    statuses: dict[str, str] = {}
    steps: dict[str, int] = {}
    for split in SPLITS:
        d = sd[split]
        for kpi, beta in KPIS:
            lab = f"{split}|{kpi_label(kpi, beta)}"
            ref = d.value(cand["stored"], kpi, beta)
            thetas, status = joint_minimum(sets, d, kpi, beta, ref)
            cand[f"min|{lab}"] = thetas
            statuses[f"min|{lab}"] = status
            best: tuple[float, list[np.ndarray], int, str] | None = None
            for start in MAX_STARTS:
                if not np.all(np.isfinite(np.concatenate(cand[start]))):
                    continue
                th, val, n_steps, st = linearised_maximum(
                    sets, d, kpi, beta, cand[start]
                )
                if best is None or val > best[0]:
                    best = (val, th, n_steps, st)
            assert best is not None
            cand[f"max|{lab}"] = best[1]
            statuses[f"max|{lab}"] = best[3]
            steps[f"max|{lab}"] = best[2]
            print(
                f"  {group.setup} {group.pricing} {group.design} {lab}: min "
                f"{status}, max {best[3]} ({time.perf_counter() - t0:.0f}s)",
                flush=True,
            )
    # every candidate must be in the near-optimal set: checked in numpy; a
    # candidate outside it (beyond OBJ_CHECK_RTOL) is reported, not used
    checks: dict[str, dict[str, float]] = {}
    for name, th in list(cand.items()):
        if not np.all(np.isfinite(np.concatenate(th))):
            continue
        per = [s.check(t, cfg) for s, t in zip(sets, th, strict=True)]
        checks[name] = {k: max(c[k] for c in per) for k in per[0]}
        if not in_set(checks[name]) and name not in (
            "stored",
            "resolved",
            "alt_solver",
        ):
            del cand[name]
            statuses[name] = statuses.get(name, "") + " outside_set"

    return _finish(
        group,
        prepared,
        train,
        test,
        built,
        sd,
        cand,
        statuses,
        steps,
        low,
        checks,
        asset_rows,
        meta,
        store,
        t0,
        RANGE_REL_TOL,
    )


def _finish(
    group: Group,
    prepared: EventSet,
    train: Sample,
    test: Sample,
    built: Sequence[BuiltProblem],
    sd: dict[str, SplitData],
    cand: dict[str, list[np.ndarray]],
    statuses: dict[str, str],
    steps: dict[str, int],
    low: list[np.ndarray] | None,
    checks: dict[str, dict[str, float]],
    asset_rows: list[dict[str, Any]],
    meta: dict[str, Any],
    store: ResultStore | None,
    t0: float,
    rel_tol: float,
) -> dict[str, Any]:
    """Evaluate, bootstrap and tabulate a group's candidate designs.

    Shared by :func:`range_worker` (near-optimal set at ``RANGE_REL_TOL``)
    and :func:`free_bin_worker` (the exact optimal set's free bins,
    ``rel_tol`` 0). ``low`` is the outer-bound point (None: no outer bound).

    Returns
    -------
    dict
        The worker result (see :func:`range_worker`).
    """
    cfg = group.config
    comps = cfg.to_components()
    # evaluate every candidate with the library (portfolio level)
    price = comps.pricing
    scope = comps.scopes[0]
    rows: list[dict[str, Any]] = []
    values: dict[tuple[str, str, str], float] = {}
    for name, th in cand.items():
        if not np.all(np.isfinite(np.concatenate(th))):
            continue
        res = _results(built, th, name)
        for split, sample in (("train", train), ("test", test)):
            for beta in EVAL_BETAS:
                k = kpis(
                    prepared,
                    scope,
                    res,
                    basis=comps.basis,
                    beta=beta,
                    run_id=name,
                    sample=sample,
                    pricing=price,
                )
                port = k.loc[k["level"] == "portfolio"].set_index("kpi")["value"]
                values[(name, split, f"cvar@{beta:g}")] = float(port["cvar_uncovered"])
                values[(name, split, "eu")] = float(port["expected_uncovered"])
                values[(name, split, "expected_payout")] = float(
                    port["expected_payout"]
                )
    # the numpy KPI the search used must equal the library's
    for name, th in cand.items():
        if (name, "train", "eu") not in values:
            continue
        for split in SPLITS:
            for kpi, beta in KPIS:
                mine = sd[split].value(th, kpi, beta)
                lib = values[(name, split, kpi_label(kpi, beta))]
                if not np.isclose(mine, lib, rtol=1e-8, atol=1e-6):
                    raise RuntimeError(
                        f"{group.setup} {group.pricing} {group.design} {name} "
                        f"{split} {kpi_label(kpi, beta)}: numpy {mine!r} != "
                        f"evaluate {lib!r}"
                    )
    for split in SPLITS:
        for kpi, beta in KPIS:
            lab = kpi_label(kpi, beta)
            key = f"{split}|{lab}"
            rows.append(
                {
                    "setup": group.setup,
                    "pricing": group.pricing,
                    "kappa": 1.0,
                    "design": group.design,
                    "split": split,
                    "kpi": lab,
                    "stored": values[("stored", split, lab)],
                    "resolved": values.get(("resolved", split, lab), math.nan),
                    "alt_solver": values.get(("alt_solver", split, lab), math.nan),
                    "min": values.get((f"min|{key}", split, lab), math.nan),
                    "max_found": values.get((f"max|{key}", split, lab), math.nan),
                    "outer_bound_max": math.nan
                    if low is None
                    else sd[split].value(low, kpi, beta),
                    "status_min": statuses[f"min|{key}"],
                    "status_max": statuses[f"max|{key}"],
                    "max_steps": steps[f"max|{key}"],
                    "objective_excess_min": checks.get(f"min|{key}", {}).get(
                        "objective_excess", math.nan
                    ),
                    "objective_excess_max": checks.get(f"max|{key}", {}).get(
                        "objective_excess", math.nan
                    ),
                    "alt_objective_excess": checks.get("alt_solver", {}).get(
                        "objective_excess", math.nan
                    ),
                    "rel_tol": rel_tol,
                    "method": "free_bins" if rel_tol == 0 else "near_optimal_set",
                    "config_hash": config_hash(cfg),
                    "run_id": group.run_id or "",
                }
            )
    # largest parameter change of a candidate against the stored design
    for i, row in enumerate(asset_rows):
        cap = row["cap"] if row["cap"] > 0 else 1.0
        base = cand["stored"][i]
        row["max_param_change_to_cap"] = max(
            float(np.max(np.abs(th[i] - base))) / cap
            for name, th in cand.items()
            if np.all(np.isfinite(th[i]))
        )
        row["alt_param_change_to_cap"] = (
            float(np.max(np.abs(cand["alt_solver"][i] - base)) / cap)
            if "alt_solver" in cand
            else math.nan
        )
        row.update(
            setup=group.setup,
            pricing=group.pricing,
            kappa=1.0,
            design=group.design,
            rel_tol=rel_tol,
            config_hash=config_hash(cfg),
        )

    # test replicates on the C1 resample (portfolio level)
    reps: dict[str, dict[str, np.ndarray]] = {}
    point: dict[str, dict[str, float]] = {}
    if cfg.bootstrap is not None:
        resample = resample_years(
            test.years, cfg.bootstrap.n_bootstrap, cfg.bootstrap.rng()
        )
        level = cfg.bootstrap.level
        designs: dict[str, tuple[Any, list[SolveResult]]] = {
            name: (scope, _results(built, th, name))
            for name, th in cand.items()
            if np.all(np.isfinite(np.concatenate(th)))
            and (name in ("stored", "alt_solver") or "|test|" in name)
        }
        assert store is not None
        for jscope, (jcfg, jrid) in group.joint.items():
            jd = rq2._stored(jcfg, jrid, store)
            designs[f"joint:{jscope}"] = (jd.scope, jd.results)
        for name, (sc, res) in designs.items():
            reps[name], point[name] = {}, {}
            for beta in EVAL_BETAS:
                boot = rq2.portfolio_rows(
                    bootstrap_kpis(
                        prepared,
                        sc,
                        res,
                        basis=comps.basis,
                        beta=beta,
                        run_id=name,
                        resample=resample,
                        sample=test,
                        pricing=price,
                        level=level,
                    )
                )
                tab = boot.table.reset_index(drop=True)
                for kpi_name, lab in (
                    ("cvar_uncovered", f"cvar@{beta:g}"),
                    ("expected_uncovered", "eu"),
                ):
                    (idx,) = np.flatnonzero(tab["kpi"].to_numpy() == kpi_name)
                    reps[name][lab] = boot.replicates[idx]
                    point[name][lab] = float(tab["value"].iloc[idx])
        meta["bootstrap_level"] = level
    # train values of the joint designs (point)
    joint_train: dict[str, dict[str, float]] = {}
    for jscope, (jcfg, jrid) in group.joint.items():
        assert store is not None
        jd = rq2._stored(jcfg, jrid, store)
        joint_train[jscope] = {}
        for beta in EVAL_BETAS:
            k = kpis(
                prepared,
                jd.scope,
                jd.results,
                basis=comps.basis,
                beta=beta,
                run_id=jrid,
                sample=train,
                pricing=price,
            )
            port = k.loc[k["level"] == "portfolio"].set_index("kpi")["value"]
            joint_train[jscope][f"cvar@{beta:g}"] = float(port["cvar_uncovered"])
            joint_train[jscope]["eu"] = float(port["expected_uncovered"])
    meta["seconds"] = round(time.perf_counter() - t0, 1)
    return {
        "group": (group.setup, group.pricing, group.design),
        "ranges": rows,
        "assets": asset_rows,
        "reps": reps,
        "point": point,
        "train_values": {
            name: {
                lab: values[(name, "train", lab)]
                for lab in ("eu", *(f"cvar@{b:g}" for b in EVAL_BETAS))
            }
            for name, th in cand.items()
            if (name, "train", "eu") in values
        },
        "joint_train": joint_train,
        "joint_hash": {k: config_hash(v[0]) for k, v in group.joint.items()},
        "meta": {**meta, "checks": checks},
        "thetas": {name: [t.tolist() for t in th] for name, th in cand.items()},
    }


def free_bins(counts: np.ndarray) -> list[int]:
    """Bins without a train row (their parameter moves no train quantity)."""
    return [int(k) for k in np.flatnonzero(np.asarray(counts) == 0)]


def free_bin_bounds(
    theta: np.ndarray, free: Sequence[int], cap: float
) -> tuple[np.ndarray, np.ndarray]:
    """Return the design with every free bin at its lowest and highest value.

    A free bin's parameter can take any value between the nearest used
    bins' parameters below and above it (0 and the cap at the ends), by
    monotonicity: every such design pays the same on every train row, so it
    has the same objective, premium and budget use, and is optimal.

    Returns
    -------
    lo, hi : numpy.ndarray
        ``theta`` with every free parameter at its lowest (highest) value.
    """
    lo, hi = theta.copy(), theta.copy()
    used = [k for k in range(len(theta)) if k not in set(free)]
    for k in free:
        below = [theta[j] for j in used if j < k]
        above = [theta[j] for j in used if j > k]
        lo[k] = max(below) if below else 0.0
        hi[k] = min(above) if above else cap
    return lo, hi


def free_bin_worker(group: Group, store_root: str | None) -> dict[str, Any]:
    """Measure the ranges over the exact optimal set's free bins (tolerance 0).

    Every design that changes only the parameters of bins without a train
    row (within monotonicity and the cap) pays the same on every train row
    as the C1 design, so it is optimal too, for every objective and pricing
    (all of them see the train rows only). The portfolio KPIs are
    non-increasing in every parameter, so the design with every free
    parameter at its highest value has the smallest KPI of this family and
    the one with every free parameter at its lowest the largest, on every
    split and KPI. On train the two equal the C1 design's (to rounding). This
    is a subset of the optimal set, so its range is an inner bound of the
    optimal set's (for MSE, the whole set when the Hessian restricted to the
    used bins is positive definite: ``asset_ranges.csv``).

    Parameters
    ----------
    group : Group
        The design.
    store_root : str or None
        The C1 result store (None: validation group, solved here).

    Returns
    -------
    dict
        As :func:`range_worker`.
    """
    t0 = time.perf_counter()
    cfg = group.config
    comps = cfg.to_components()
    prepared = c1._prepared(cfg)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    store = ResultStore(Path(store_root)) if store_root else None
    specs = list(comps.scopes[0].partition(train.select(prepared)))
    built = build_problems(
        prepared,
        comps.scopes[0],
        comps.payout,
        comps.objectives[0],
        comps.pricing,
        comps.constraints,
        basis=comps.basis,
        sample=train,
        specs=specs,
    )
    if group.run_id is not None:
        assert store is not None
        stored_results = rq2._stored(cfg, group.run_id, store).results
    else:
        stored_results = [
            solve(b, DEFAULT_POLICY, pricing=comps.pricing) for b in built
        ]
    sd = {
        "train": split_data(prepared, train, cfg, built),
        "test": split_data(prepared, test, cfg, built),
    }
    stored = [np.asarray(r.theta)[0] for r in stored_results]
    lo_all: list[np.ndarray] = []
    hi_all: list[np.ndarray] = []
    asset_rows: list[dict[str, Any]] = []
    for i, b in enumerate(built):
        counts = np.asarray(sd["train"].basis[i]).sum(axis=0)
        free = free_bins(counts)
        cap = float(b.context.cap[0] * b.context.scale)
        lo, hi = free_bin_bounds(stored[i], free, cap)
        for t in (lo, hi):
            tr = sd["train"].basis[i]
            if not np.allclose(tr @ t, tr @ stored[i], rtol=0, atol=1e-9 * cap):
                raise RuntimeError(f"{b.spec.problem_id}: a free bin has train rows")
        lo_all.append(lo)
        hi_all.append(hi)
        test_counts = np.asarray(sd["test"].basis[i]).sum(axis=0)
        asset_rows.append(
            {
                "entity_id": b.spec.problem_id,
                "free_bins": " ".join(str(k) for k in free),
                "free_bins_test_rows": int(sum(test_counts[k] for k in free)),
                "free_param_width_to_cap": float(np.max(hi - lo, initial=0.0)) / cap
                if cap > 0
                else math.nan,
                "cap": cap,
                "mse_hessian_min_eig_rel_used_bins": hessian_min_eig_rel(
                    sd["train"],
                    np.asarray(sd["train"].basis[i])[
                        :, [k for k in range(len(counts)) if k not in free]
                    ],
                ),
            }
        )
    cand: dict[str, list[np.ndarray]] = {"stored": stored}
    statuses: dict[str, str] = {}
    steps: dict[str, int] = {}
    for split in SPLITS:
        for kpi, beta in KPIS:
            lab = f"{split}|{kpi_label(kpi, beta)}"
            cand[f"min|{lab}"] = hi_all
            cand[f"max|{lab}"] = lo_all
            statuses[f"min|{lab}"] = "exact (free bins at their highest)"
            statuses[f"max|{lab}"] = "exact (free bins at their lowest)"
            steps[f"max|{lab}"] = 0
    meta: dict[str, Any] = {"method": "free_bins"}
    return _finish(
        group,
        prepared,
        train,
        test,
        built,
        sd,
        cand,
        statuses,
        steps,
        None,
        {},
        asset_rows,
        meta,
        store,
        t0,
        0.0,
    )


# --------------------------------------------------------------------------
# Comparisons at the ends of the ranges
# --------------------------------------------------------------------------

LABELS: Final[tuple[str, ...]] = tuple(kpi_label(k, b) for k, b in KPIS)
END_SIDES: Final[tuple[str, ...]] = ("stored", "min", "max")
"""Which individual design: the C1 one, or the one at either end of the
range of the KPI being compared (``min``: smallest KPI; ``max``: largest
found)."""
CONTRAST_TERMS: Final[dict[str, tuple[tuple[str, str, int], ...]]] = {
    "both": (("J", "W", 1), ("I", "O", -1)),
    "adds_rq2": (("J", "W", 1), ("I", "W", -1)),
    "rq1_alone": (("I", "W", 1), ("I", "O", -1)),
    "rq2_alone": (("J", "O", 1), ("I", "O", -1)),
    "interaction": (("J", "W", 1), ("J", "O", -1), ("I", "W", -1), ("I", "O", 1)),
}
"""MAR-182's contrasts that contain an individual design, as signed terms
(scope, objective role, sign). ``adds_rq1`` has none and is not affected."""


def _candidate(side: str, split: str, lab: str) -> str:
    """Candidate name of the individual design at ``side`` of a range."""
    return "stored" if side == "stored" else f"{side}|{split}|{lab}"


def rq2_ends(
    out: dict[tuple[str, str, str], dict[str, Any]], level: float
) -> pd.DataFrame:
    """C1 section 6b's joint-minus-individual differences, at the range ends.

    Parameters
    ----------
    out : dict
        Worker results keyed by (setup, pricing, design).
    level : float
        Interval level.

    Returns
    -------
    pandas.DataFrame
        One row per (split, pricing, design, joint scope, KPI, end).
    """
    rows: list[dict[str, Any]] = []
    for (setup, pricing, design), r in out.items():
        if setup != "c1":
            continue
        for jscope in ("portfolio", "cluster"):
            joint = f"joint:{jscope}"
            for lab in LABELS:
                for side in END_SIDES:
                    base = {
                        "pricing": pricing,
                        "kappa": 1.0,
                        "design": design,
                        "scope_a": jscope,
                        "scope_b": "individual",
                        "individual_at": side,
                        "kpi": lab,
                        "hash_a": r["joint_hash"][jscope],
                        "hash_b": r["ranges"][0]["config_hash"],
                    }
                    name = _candidate(side, "train", lab)
                    if name in r["train_values"]:
                        jv = r["joint_train"][jscope][lab]
                        ind = r["train_values"][name][lab]
                        rows.append(
                            {
                                **base,
                                "split": "train",
                                "value_a": jv,
                                "value_b": ind,
                                "difference": jv - ind,
                                "ci_low": math.nan,
                                "ci_high": math.nan,
                            }
                        )
                    name = _candidate(side, "test", lab)
                    if name in r["reps"]:
                        d = r["reps"][joint][lab] - r["reps"][name][lab]
                        lo, hi = percentile_interval(d, level)
                        jv, ind = r["point"][joint][lab], r["point"][name][lab]
                        rows.append(
                            {
                                **base,
                                "split": "test",
                                "value_a": jv,
                                "value_b": ind,
                                "difference": jv - ind,
                                "ci_low": lo,
                                "ci_high": hi,
                            }
                        )
    frame = pd.DataFrame(rows)
    frame["rel"] = frame["difference"] / frame["value_b"]
    return frame


def _contrast_value(
    out: dict[tuple[str, str, str], dict[str, Any]],
    pricing: str,
    jscope: str,
    role: dict[str, str],
    terms: tuple[tuple[str, str, int], ...],
    end: str,
    split: str,
    lab: str,
) -> tuple[float, np.ndarray | None] | None:
    """Return a contrast's point value and replicates, individual terms at ``end``.

    None if a design at that end is missing.
    """
    value = 0.0
    reps: np.ndarray | None = None
    for scope, rl, sign in terms:
        r = out[("c1", pricing, role[rl])]
        if scope == "J":
            name = f"joint:{jscope}"
        elif end == "stored":
            name = "stored"
        else:
            lower = (end == "low") == (sign > 0)
            name = _candidate("min" if lower else "max", split, lab)
        if split == "train":
            src = (
                r["joint_train"][jscope]
                if scope == "J"
                else r["train_values"].get(name)
            )
            if src is None:
                return None
            value += sign * src[lab]
        else:
            if name not in r["reps"]:
                return None
            value += sign * r["point"][name][lab]
            term = sign * r["reps"][name][lab]
            reps = term if reps is None else reps + term
    return value, reps


def contrasts_ends(
    out: dict[tuple[str, str, str], dict[str, Any]], level: float
) -> pd.DataFrame:
    """MAR-182's contrasts with the individual terms at the range ends.

    ``low``: every individual term taken at the end that lowers the contrast
    (``min`` for a ``+`` term, ``max`` for a ``-`` term); ``high``: the
    reverse. The near-optimal sets of different individual designs are
    independent, so on the point values these are the contrast's range over
    them (the ``max`` ends being inner bounds). The intervals are those of
    the designs at the ends.

    Parameters
    ----------
    out : dict
        Worker results keyed by (setup, pricing, design).
    level : float
        Interval level.

    Returns
    -------
    pandas.DataFrame
        One row per (split, pricing, contrast, joint scope, tail design, base
        design, KPI, end).
    """
    rows: list[dict[str, Any]] = []
    for pricing in PRICINGS:
        for jscope in ("portfolio", "cluster"):
            for tail in ("wcvar@0.99", "wcvar@0.995"):
                for base in ("mse", "eu"):
                    role = {"W": tail, "O": base}
                    for lab in LABELS:
                        for contrast, terms in CONTRAST_TERMS.items():
                            for end in ("stored", "low", "high"):
                                for split in SPLITS:
                                    got = _contrast_value(
                                        out,
                                        pricing,
                                        jscope,
                                        role,
                                        terms,
                                        end,
                                        split,
                                        lab,
                                    )
                                    if got is None:
                                        continue
                                    value, reps = got
                                    lo, hi = (
                                        percentile_interval(reps, level)
                                        if reps is not None
                                        else (math.nan, math.nan)
                                    )
                                    used = {t[:2] for t in terms}
                                    rows.append(
                                        {
                                            "split": split,
                                            "pricing": pricing,
                                            "kappa": 1.0,
                                            "contrast": contrast,
                                            "joint_scope": jscope
                                            if any(t[0] == "J" for t in terms)
                                            else "",
                                            "tail_design": tail
                                            if any(u[1] == "W" for u in used)
                                            else "",
                                            "base_design": base
                                            if any(u[1] == "O" for u in used)
                                            else "",
                                            "kpi": lab,
                                            "individual_at": end,
                                            "value": value,
                                            "ci_low": lo,
                                            "ci_high": hi,
                                        }
                                    )
    frame = pd.DataFrame(rows)
    # a contrast without a joint term, or without one of the roles, repeats
    # over the unused loop variable (MAR-182 leaves that column empty)
    key = [c for c in frame.columns if c not in ("value", "ci_low", "ci_high")]
    return frame.drop_duplicates(subset=key).reset_index(drop=True)


def _kpi_key(frame: pd.DataFrame) -> pd.Series:
    """Map MAR-158/MAR-182 (kpi, eval_beta) rows onto this script's labels."""
    eu = frame["kpi"] == "expected_uncovered"
    lab = "cvar@" + frame["eval_beta"].map(lambda b: f"{b:g}" if pd.notna(b) else "")
    return lab.where(~eu, "eu")


def _close(m: pd.DataFrame, columns: Sequence[str], what: str) -> None:
    """Raise unless ``m[c]`` equals ``m[c + '_pub']`` for every column."""
    for c in columns:
        x, y = m[c].to_numpy(float), m[f"{c}_pub"].to_numpy(float)
        if not np.allclose(x, y, rtol=1e-5, atol=1e-2, equal_nan=True):
            worst = int(np.nanargmax(np.abs(x - y)))
            raise RuntimeError(f"{what} {c} differs: {m.iloc[worst].to_dict()}")


def check_against_published(
    rq2_frame: pd.DataFrame, con: pd.DataFrame
) -> tuple[dict[str, int], pd.DataFrame]:
    """Raise unless the stored-design rows equal MAR-158's and MAR-182's CSVs.

    Returns
    -------
    counts : dict
        Rows checked.
    ref : pandas.DataFrame
        MAR-182's ``value_ref`` (the denominator of its relative values) per
        contrast row.
    """
    data = REPO_ROOT / "research" / "data"
    sp = pd.read_csv(data / "c1-rq2" / "scope_paired.csv")
    sp = sp.loc[
        (sp["kappa"] == 1)
        & sp["pricing"].isin(PRICINGS)
        & (sp["scope_b"] == "individual")
        & sp["scope_a"].isin(["portfolio", "cluster"])
        & sp["split"].isin(SPLITS)
        & sp["kpi"].isin(["cvar_uncovered", "expected_uncovered"])
    ].copy()
    sp["lab"] = _kpi_key(sp)
    sp = sp.drop(columns=["kpi", "kappa", "scope_b"])
    mine = rq2_frame.loc[rq2_frame["individual_at"] == "stored"]
    m = mine.merge(
        sp,
        left_on=["split", "pricing", "design", "scope_a", "kpi"],
        right_on=["split", "pricing", "design", "scope_a", "lab"],
        suffixes=("", "_pub"),
        validate="one_to_one",
    )
    if len(m) != len(mine):
        raise RuntimeError(f"{len(mine) - len(m)} RQ2 rows have no MAR-158 row")
    _close(m, ("difference", "ci_low", "ci_high"), "RQ2 (MAR-158)")
    n_rq2 = len(m)
    cs = pd.concat(
        [
            pd.read_csv(data / "c1-combination" / "contrasts.csv"),
            pd.read_csv(data / "c1-combination" / "contrasts_train.csv"),
        ],
        ignore_index=True,
    )
    cs = cs.loc[
        (cs["kappa"] == 1)
        & cs["pricing"].isin(PRICINGS)
        & cs["split"].isin(SPLITS)
        & cs["contrast"].isin(list(CONTRAST_TERMS))
        & cs["kpi"].isin(["cvar_uncovered", "expected_uncovered"])
    ].copy()
    cs["lab"] = _kpi_key(cs)
    roles = ["joint_scope", "tail_design", "base_design"]
    cs[roles] = cs[roles].fillna("")
    cs = cs.drop(columns=["kpi", "kappa"])
    mine = con.loc[con["individual_at"] == "stored"]
    key = ["split", "pricing", "contrast", "joint_scope", "tail_design", "base_design"]
    m = mine.merge(
        cs,
        left_on=[*key, "kpi"],
        right_on=[*key, "lab"],
        suffixes=("", "_pub"),
        validate="one_to_one",
    )
    if len(m) != len(mine):
        raise RuntimeError(f"{len(mine) - len(m)} contrast rows have no MAR-182 row")
    _close(m, ("value", "ci_low", "ci_high"), "contrast (MAR-182)")
    ref = m[[*key, "kpi", "value_ref", "hash_a", "hash_b", "hash_c", "hash_d"]]
    return {"rq2_rows_checked": n_rq2, "contrast_rows_checked": len(m)}, ref


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Measure the ranges, compare, write the full tables.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description="MAR-198 individual ranges.")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--c1-store", type=Path, default=c1.STORE)
    parser.add_argument("--full", type=Path, default=FULL_DIR)
    parser.add_argument(
        "--only", nargs="*", default=None, help="setup|pricing|design keys to run"
    )
    parser.add_argument(
        "--method",
        choices=["near_optimal_set", "free_bins"],
        default="near_optimal_set",
        help="near-optimal set at RANGE_REL_TOL, or the exact free-bin family",
    )
    parser.add_argument(
        "--compare-only",
        action="store_true",
        help="skip the solves: reload the saved worker results from --full",
    )
    args = parser.parse_args(argv)
    t0 = time.perf_counter()
    if args.compare_only:
        return write_tables(load_results(args.full), args.full, t0)
    groups = [*c1_groups(), *validation_groups()]
    if args.only:
        groups = [g for g in groups if f"{g.setup}|{g.pricing}|{g.design}" in args.only]
    store = ResultStore(args.c1_store)
    for g in groups:
        for rid in [g.run_id, *(v[1] for v in g.joint.values())]:
            if rid is not None and not store.has_run(rid):
                raise RuntimeError(f"C1 run {rid} is not in {args.c1_store}")
    args.full.mkdir(parents=True, exist_ok=True)
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    worker = free_bin_worker if args.method == "free_bins" else range_worker
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {
            pool.submit(worker, g, str(args.c1_store) if g.run_id else None): g
            for g in groups
        }
        failed: dict[str, str] = {}
        for i, fut in enumerate(as_completed(futs), 1):
            g = futs[fut]
            try:
                r = fut.result()
            except Exception as exc:  # recorded and re-raised after the loop
                failed[f"{g.setup}|{g.pricing}|{g.design}"] = repr(exc)
                print(
                    f"[{i}/{len(futs)}] FAILED {g.setup} {g.pricing} {g.design}: "
                    f"{exc!r}",
                    flush=True,
                )
                continue
            out[r["group"]] = r
            print(
                f"[{i}/{len(futs)}] {g.setup} {g.pricing} {g.design} "
                f"{r['meta']['seconds']:.0f}s",
                flush=True,
            )
            stem = f"{g.setup}_{g.pricing}_{g.design}"
            np.savez_compressed(
                args.full / f"reps_{stem}.npz",
                **{
                    f"{name}||{lab}": arr
                    for name, d in r["reps"].items()
                    for lab, arr in d.items()
                },
            )
            (args.full / f"result_{stem}.json").write_text(
                json.dumps({k: v for k, v in r.items() if k != "reps"}, default=str)
            )
    if failed:
        (args.full / "failed.json").write_text(json.dumps(failed, indent=2) + "\n")
        raise RuntimeError(f"{len(failed)} groups failed: {sorted(failed)}")
    return write_tables(out, args.full, t0)


def load_results(full: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    """Reload the worker results that :func:`main` saved in ``full``.

    Parameters
    ----------
    full : Path
        The full-table directory.

    Returns
    -------
    dict
        Worker results keyed by (setup, pricing, design).
    """
    out: dict[tuple[str, str, str], dict[str, Any]] = {}
    for path in sorted(full.glob("result_*.json")):
        r = json.loads(path.read_text())
        key = (str(r["group"][0]), str(r["group"][1]), str(r["group"][2]))
        reps: dict[str, dict[str, np.ndarray]] = {}
        with np.load(full / f"reps_{path.stem.removeprefix('result_')}.npz") as z:
            for k in z.files:
                name, lab = k.split("||")
                reps.setdefault(name, {})[lab] = z[k]
        r["group"], r["reps"] = key, reps
        out[key] = r
    return out


def write_tables(
    out: dict[tuple[str, str, str], dict[str, Any]], full: Path, t0: float
) -> int:
    """Write the full tables and the comparisons from the worker results.

    Parameters
    ----------
    out : dict
        Worker results keyed by (setup, pricing, design).
    full : Path
        Output directory.
    t0 : float
        Start time (``time.perf_counter``).

    Returns
    -------
    int
        Exit status.
    """
    args = argparse.Namespace(full=full)
    ranges = pd.DataFrame([row for r in out.values() for row in r["ranges"]])
    assets = pd.DataFrame([row for r in out.values() for row in r["assets"]])
    ranges.to_csv(args.full / "ranges.csv", index=False, float_format="%.10g")
    assets.to_csv(args.full / "asset_ranges.csv", index=False, float_format="%.10g")
    summary: dict[str, Any] = {
        "issue": "MAR-198",
        "base_config": str(c1.BASE_CONFIG.relative_to(REPO_ROOT)),
        "rel_tol": RANGE_REL_TOL,
        "obj_check_rtol": OBJ_CHECK_RTOL,
        "solver": SOLVER,
        "max_iter": MAX_ITER,
        "max_steps": MAX_STEPS,
        "max_starts": list(MAX_STARTS),
        "alt_policy": {
            "lp_solvers": list(rq2.ALT_POLICY.lp_solvers),
            "qp_solvers": list(rq2.ALT_POLICY.qp_solvers),
        },
        "package_versions": package_versions(),
        "groups": {
            "|".join(k): {kk: vv for kk, vv in r["meta"].items() if kk != "checks"}
            for k, r in out.items()
        },
        "candidate_checks": {"|".join(k): r["meta"]["checks"] for k, r in out.items()},
    }
    check = ranges.loc[
        ranges["setup"].str.startswith("mar165")
        & (ranges["split"] == "train")
        & (ranges["kpi"] == "eu")
    ]
    summary["mar165"] = {
        str(row.setup): {
            "stored": float(row.stored),  # type: ignore[arg-type]
            "min": float(row.min),  # type: ignore[arg-type]
            "max_found": float(row.max_found),  # type: ignore[arg-type]
            "observed_in_range": {
                k: bool(float(row.min) - 0.01 <= x <= float(row.max_found) + 0.01)  # type: ignore[arg-type]
                for k, x in MAR165_TRAIN_EU.items()
            },
        }
        for row in check.itertuples()
    }
    if all(("c1", p, d) in out for p in PRICINGS for d in DESIGNS):
        level = float(out[("c1", PRICINGS[0], DESIGNS[0])]["meta"]["bootstrap_level"])
        rq2_frame = rq2_ends(out, level)
        con = contrasts_ends(out, level)
        counts, ref = check_against_published(rq2_frame, con)
        key = [
            "split",
            "pricing",
            "contrast",
            "joint_scope",
            "tail_design",
            "base_design",
            "kpi",
        ]
        con = con.merge(ref, on=key, how="left", validate="many_to_one")
        for c in ("value", "ci_low", "ci_high"):
            con[f"rel_{c}"] = con[c] / con["value_ref"]
        summary.update(counts)
        rq2_frame.to_csv(args.full / "rq2_ends.csv", index=False, float_format="%.10g")
        con.to_csv(args.full / "contrasts_ends.csv", index=False, float_format="%.10g")
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    (args.full / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(f"wrote {args.full}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
