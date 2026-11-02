r"""MAR-206: RQ2 sensitivities on the thesis portfolio (C1 addendum).

C1 section 6b (``research/checkpoints/C1.md``, MAR-158) compared joint and
individual calibration on the thesis portfolio. This script runs the
sensitivities that MAR-206 lists, one phase per family, in the order the
issue's orchestrator notes give:

``inaccurate`` (a)
    C1 T11 ranged each entity's train ``E[pi_j] / E[L_j]`` over the joint
    design's near-optimal set (objective within ``RANGE_REL_TOL`` = 1e-5 of
    the optimum). 7 of those range programs (6 entities) ended
    ``optimal_inaccurate`` under CLARABEL and were reported ``n/a``. Here
    both ends of those 6 entities are re-solved with a second solver (HiGHS
    for the LPs, SCS for the programs with the MSE objective's quadratic
    constraint) and, for the MSE, with an exact compact form of the
    quadratic constraint (135 parameters instead of 91,000 outcomes) under
    CLARABEL and SCS. Every solution is checked in numpy against the set
    (objective, budget, payout structure).

``nonunique`` (b)
    Do non-unique joint designs (MAR-100) move C1's **within-scope**
    comparisons (sections 3-5: weighted CVaR minus MSE and minus E[U], in
    the cluster and portfolio scopes, every pricing, kappa, design beta and
    the event-conditional reference column)? Each joint design is replaced
    by (i) a second optimum from another solver order (``c1_rq2.ALT_POLICY``)
    and (ii) the two ends of its exact free-bin family (bins without a train
    row, at their lowest and highest values). The paired differences are
    recomputed on the C1 resample. It also re-derives C1 T6 (per-asset
    payout of joint designs) with the library's named allocation rules
    (``evaluate`` ``allocation="value"`` and ``"loss"``).

``noise`` (c)
    The RQ2 comparison of C1 6b on the thesis EventSet without the noise
    layer, and with the noise common to all assets (the same heteroscedastic
    marginals, one standard-normal draw per row shared by the 9 assets),
    through the runner.

``nclusters`` (d)
    A cluster-count sweep of the cluster scope (n = 1..9, thesis Ward), both
    jointly calibrated (``joint: true``) and cluster by cluster (``joint:
    false``), through the runner.

``joint_ranges`` (e)
    The joint - individual differences ranged over both optimal sets
    together: each joint design's portfolio KPI minimised and maximised over
    its near-optimal set (C1 T11's programs with the KPI as the objective,
    MAR-198's method), against MAR-198's individual ends; and the free-bin
    (empty-bin) directions of the joint scopes separately.

Outputs: full tables to ``--full`` (``results/c1-rq2-sensitivities/``, not
committed); ``--phase tables`` writes the committed CSVs (each < 500 kB) and
``tables.md`` to ``research/data/c1-rq2-sensitivities/``.

Run from the repository root; it reads the C1 store (and, for (e), MAR-198's
full results) and never writes to them::

    uv run python research/scripts/c1_rq2_sensitivities.py --phase inaccurate \
        --c1-store <C1 results>/c1/store
    ...
    uv run python research/scripts/c1_rq2_sensitivities.py --phase tables

Observations only. The interpretation is the owner's.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import c1_checkpoint as c1
import c1_rq2 as rq2
import cvxpy as cp
import numpy as np
import pandas as pd
from individual_nonuniqueness import SplitData

from parametric_insurance_design import splits
from parametric_insurance_design.basis import outcome_measure
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.runner import package_versions, run_key
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.riskmeasures import var_cvar
from parametric_insurance_design.solve import DEFAULT_POLICY, solve

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "c1-rq2-sensitivities"
CONFIG_DIR: Final[Path] = REPO_ROOT / "research" / "configs" / "c1-rq2-sensitivities"
FULL_DIR: Final[Path] = REPO_ROOT / "results" / "c1-rq2-sensitivities"
C1_STORE: Final[Path] = Path(os.environ.get("C1_STORE", str(c1.STORE)))
C1_RQ2_DATA: Final[Path] = REPO_ROOT / "research" / "data" / "c1-rq2"

RANGE_REL_TOL: Final[float] = rq2.RANGE_REL_TOL
CHECK_RTOL: Final[float] = 1e-6
"""A design is in the near-optimal set if the numpy recomputation is within
this (relative) of the set's bounds: MAR-198's ``OBJ_CHECK_RTOL``."""


# --------------------------------------------------------------------------
# The C1 runs
# --------------------------------------------------------------------------

GroupKey = tuple[str, str, str, float, str]
"""(family, eventset, pricing, kappa, design)."""


def c1_groups(
    families: Sequence[str] = ("main",),
    keep: Callable[[c1.RunSpec], bool] = lambda s: True,
) -> dict[GroupKey, dict[str, tuple[ExperimentConfig, str]]]:
    """C1 runs grouped by variant and design: scope -> (config, run id).

    Parameters
    ----------
    families : sequence of str
        C1 families (``"main"``, ``"reference"``).
    keep : callable
        Filter on the C1 run spec.

    Returns
    -------
    dict
        ``(family, eventset, pricing, kappa, design)`` to ``{scope: (config,
        run id)}``.
    """
    specs, _ = c1.plan(list(families))
    checksum = str(load_config(c1.BASE_CONFIG).eventset.checksum)
    out: dict[GroupKey, dict[str, tuple[ExperimentConfig, str]]] = {}
    for s in specs:
        if not keep(s):
            continue
        v = s.variant
        rid = run_key(config_hash(s.config), checksum, policy=DEFAULT_POLICY)
        key = (v.family, v.eventset, v.pricing, v.kappa, s.design)
        out.setdefault(key, {})[s.scope] = (s.config, rid)
    return out


def dense(matrix: object) -> np.ndarray:
    """Return a (possibly sparse) basis matrix as a dense float array."""
    if hasattr(matrix, "toarray"):
        matrix = matrix.toarray()
    return np.asarray(matrix, dtype=np.float64)


def short(h: str) -> str:
    """First 12 hex digits of a ``sha256:`` (or ``derived:``) hash."""
    return h.split(":", 1)[-1][:12]


# --------------------------------------------------------------------------
# A joint design problem's near-optimal set, checked in numpy
# --------------------------------------------------------------------------


class JointSet:
    """A joint (cluster or portfolio) design problem and its near-optimal set.

    The set is the problem's feasible set with ``objective <= optimum + tol *
    |optimum|`` (C1 T11). All quantities are in the problem's scaled units.

    Parameters
    ----------
    built : BuiltProblem
        The design problem, solved (its variables hold the optimum).
    cfg : ExperimentConfig
        The single-run config.
    tol : float
        Relative tolerance of the set.
    """

    def __init__(self, built: BuiltProblem, cfg: ExperimentConfig, tol: float) -> None:
        self.built = built
        self.cfg = cfg
        self.ctx = built.context
        self.tol = tol
        comps = cfg.to_components()
        self.payout = comps.payout
        self.objective = comps.objectives[0]
        self.pricing = comps.pricing
        (self.budget,) = comps.constraints
        problem = self.ctx.problem
        self.basis = [
            dense(self.payout.basis_matrix(problem.index[:, j]))
            for j in range(problem.n_entities)
        ]
        self.theta_opt = np.asarray(self.ctx.theta.value, dtype=np.float64).copy()
        self.optimum = float(np.asarray(built.objective.expression.value))
        mine = self.objective_value(self.theta_opt)
        if not math.isclose(mine, self.optimum, rel_tol=1e-5, abs_tol=1e-12):
            raise RuntimeError(
                f"numpy objective {mine!r} != cvxpy objective {self.optimum!r}"
            )
        self.bound = self.optimum + tol * abs(self.optimum)
        self.constraints = [
            *built.problem.constraints,
            built.objective.expression <= self.bound,
        ]

    @property
    def n_entities(self) -> int:
        """Number of payout entities."""
        return int(self.ctx.problem.n_entities)

    def rows_payout(self, theta: np.ndarray) -> np.ndarray:
        """Objective-level payout per row (scaled) of ``theta`` (scaled)."""
        return np.asarray(
            sum(b @ theta[j] for j, b in enumerate(self.basis)), dtype=np.float64
        )

    def objective_value(self, theta: np.ndarray) -> float:
        """Return the design problem's objective in numpy (scaled units)."""
        measure = self.ctx.measure
        p = np.asarray(measure.probability, dtype=np.float64)
        resid = self.ctx.loss - self.rows_payout(theta)
        name = self.objective.name
        if name == "mse":
            return float(p @ measure.aggregate(resid) ** 2)
        u = measure.aggregate(np.maximum(0.0, resid))
        if name == "expected_uncovered":
            return float(p @ u)
        alpha = float(self.objective.alpha)  # type: ignore[attr-defined]
        beta = float(self.objective.beta)  # type: ignore[attr-defined]
        if alpha == 0.0:
            return float(p @ u)
        return alpha * var_cvar(u, p, beta)[1] + (1.0 - alpha) * float(p @ u)

    def check(self, theta: np.ndarray) -> dict[str, float]:
        """Distance of ``theta`` (scaled) from the set, recomputed in numpy.

        Returns
        -------
        dict
            ``objective_excess``: (objective - optimum) / |optimum| (at most
            ``tol`` inside the set); ``budget_excess``: (premium - budget) /
            budget (at most 0); ``structure_violation``: the largest
            violation of non-negativity, monotonicity and the cap, relative
            to the cap.
        """
        theta = np.asarray(theta, dtype=np.float64)
        value = self.objective_value(theta)
        premium = self.pricing.premium_value(self.rows_payout(theta), self.ctx.measure)
        limit = self.budget.loading * self.ctx.measure.expectation(self.ctx.loss)  # type: ignore[attr-defined]
        worst = 0.0
        for j in range(self.n_entities):
            t = theta[j]
            cap = float(self.ctx.cap[j])
            v = max(
                float(np.max(-t, initial=0.0)),
                float(np.max(-np.diff(t), initial=0.0)),
                float(np.max(t - cap, initial=0.0)),
            ) / max(cap, 1e-12)
            worst = max(worst, v)
        return {
            "objective_excess": (value - self.optimum) / max(abs(self.optimum), 1e-300),
            "budget_excess": (premium - limit) / max(abs(limit), 1e-300),
            "structure_violation": worst,
        }

    def inside(self, check: dict[str, float]) -> bool:
        """Whether a :meth:`check` result lies in the set (``CHECK_RTOL``)."""
        return (
            check["objective_excess"] <= self.tol + CHECK_RTOL
            and check["budget_excess"] <= CHECK_RTOL
            and check["structure_violation"] <= CHECK_RTOL
        )

    def entity_expected_payout(self, j: int) -> cp.Expression:
        """Return the expected payout of entity ``j`` (scaled, cvxpy)."""
        measure = self.ctx.measure
        return measure.probability @ measure.aggregate_expression(
            self.ctx.entity_payout[:, j]
        )

    def entity_ratio(self, theta: np.ndarray, j: int) -> float:
        """``E[pi_j] / E[L_j]`` of ``theta`` (scaled), numpy."""
        measure = self.ctx.measure
        el = measure.expectation(self.ctx.entity_loss[:, j])
        return measure.expectation(self.basis[j] @ theta[j]) / el

    def compact_mse_constraint(self) -> cp.Constraint:
        """Return the MSE set's quadratic constraint in an exact compact form.

        ``f(theta) - f* = d' H d + 2 g' d`` with ``d = theta - theta*``,
        ``H = A' P A`` and ``g = A' P (A theta* - l)``, ``A`` the payout
        basis summed into outcomes. Exact for a quadratic; 135 parameters
        instead of one residual per outcome. Both sides are divided by the
        allowed excess ``tol * |f*|``, so that the right-hand side is 1 (the
        excess is about 1e-10 in scaled units, below a solver's absolute
        tolerance).
        """
        if self.objective.name != "mse":
            raise ValueError("compact form only for the MSE objective")
        measure = self.ctx.measure
        p = np.asarray(measure.probability, dtype=np.float64)
        a = np.hstack([measure.aggregate(b) for b in self.basis])  # entity-major
        h = a.T @ (a * p[:, None])
        resid = a @ self.theta_opt.reshape(-1) - measure.aggregate(self.ctx.loss)
        g = a.T @ (p * resid)
        excess = self.tol * abs(self.optimum)
        w, v = np.linalg.eigh(h / excess)
        w = np.clip(w, 0.0, None)
        r = (v * np.sqrt(w)).T
        d = cp.reshape(self.ctx.theta, (-1,), order="C") - self.theta_opt.reshape(-1)
        return cp.sum_squares(r @ d) + (2.0 / excess) * (g @ d) <= 1.0


def rebuild_joint(
    cfg: ExperimentConfig, rid: str, store_root: Path, tol: float = RANGE_REL_TOL
) -> tuple[JointSet, Any]:
    """Re-solve a stored C1 joint design on its train years; return its set.

    Raises
    ------
    RuntimeError
        If the re-solved objective differs from the stored run's (rtol 1e-6).
    """
    from parametric_insurance_design.experiment.store import ResultStore

    store = ResultStore(store_root)
    prepared = c1._prepared(cfg)
    train, _ = splits.holdout(prepared, train_fraction=0.7)
    stored = rq2._stored(cfg, rid, store)
    comps = cfg.to_components()
    (built,) = build_problems(
        prepared,
        stored.scope,
        comps.payout,
        comps.objectives[0],
        comps.pricing,
        comps.constraints,
        basis=comps.basis,
        sample=train,
        specs=[r.spec for r in stored.results],
    )
    result = solve(built, DEFAULT_POLICY, pricing=comps.pricing)
    if not np.isclose(
        result.objective_value, stored.objective_value, rtol=1e-6, atol=1e-6
    ):
        raise RuntimeError(
            f"{rid}: re-solved objective {result.objective_value!r} != stored "
            f"{stored.objective_value!r}"
        )
    return JointSet(built, cfg, tol), stored


# --------------------------------------------------------------------------
# Phase (a): the optimal_inaccurate range programs, second solver
# --------------------------------------------------------------------------

SCS_OPTS: Final[dict[str, Any]] = {
    "eps_abs": 1e-9,
    "eps_rel": 1e-9,
    "max_iters": 200_000,
}
CLARABEL_LONG: Final[dict[str, Any]] = {"max_iter": 2000}


def _solve_range(
    js: JointSet,
    j: int,
    sense: str,
    solver: str,
    form: str,
) -> dict[str, Any]:
    """One end of entity ``j``'s range, by ``solver`` on ``form``."""
    goal = cp.Minimize if sense == "min" else cp.Maximize
    if form == "original":
        cons = js.constraints
    else:  # compact MSE constraint
        cons = [*js.built.problem.constraints, js.compact_mse_constraint()]
    prob = cp.Problem(goal(js.entity_expected_payout(j)), cons)
    opts: dict[str, Any] = {}
    if solver == "SCS":
        opts = dict(SCS_OPTS)
    elif solver == "CLARABEL_long":
        opts = dict(CLARABEL_LONG)
    name = "CLARABEL" if solver.startswith("CLARABEL") else solver
    t0 = time.perf_counter()
    js.ctx.theta.value = None
    try:
        prob.solve(solver=name, **opts)
        status = str(prob.status)
    except cp.error.SolverError as exc:
        status = f"solver_error: {str(exc)[:120]}"
    seconds = time.perf_counter() - t0
    row: dict[str, Any] = {
        "sense": sense,
        "solver": solver,
        "form": form,
        "status": status,
        "seconds": round(seconds, 1),
        "ratio": math.nan,
        "objective_excess": math.nan,
        "budget_excess": math.nan,
        "structure_violation": math.nan,
        "in_set": False,
    }
    if js.ctx.theta.value is not None:
        theta = np.asarray(js.ctx.theta.value, dtype=np.float64)
        chk = js.check(theta)
        row.update(chk)
        row["in_set"] = js.inside(chk)
        row["ratio"] = js.entity_ratio(theta, j)
    return row


def inaccurate_worker(
    pricing: str,
    design: str,
    scope: str,
    entities: list[str],
    member: tuple[ExperimentConfig, str],
    store_root: str,
) -> pd.DataFrame:
    """Both ends of the listed entities' ranges, by every solver and form."""
    cfg, rid = member
    js, stored = rebuild_joint(cfg, rid, Path(store_root))
    ids = [e.entity_id for e in js.ctx.problem.spec.entities]
    lp = js.objective.name != "mse"
    attempts: list[tuple[str, str]] = [("CLARABEL", "original")]
    if lp:
        attempts += [("HIGHS", "original"), ("CLARABEL_long", "original")]
    else:
        attempts += [
            ("SCS", "original"),
            ("CLARABEL", "compact"),
            ("SCS", "compact"),
        ]
    rows: list[dict[str, Any]] = []
    stored_theta = np.vstack([r.theta for r in stored.results]) / js.ctx.scale
    for ent in entities:
        j = ids.index(ent)
        for sense in ("min", "max"):
            for solver, form in attempts:
                row = _solve_range(js, j, sense, solver, form)
                row.update(
                    {
                        "pricing": pricing,
                        "kappa": 1.0,
                        "design": design,
                        "scope": scope,
                        "entity_id": ent,
                        "stored_ratio": js.entity_ratio(stored_theta, j),
                        "rel_tol": RANGE_REL_TOL,
                        "config_hash": config_hash(cfg),
                    }
                )
                rows.append(row)
                print(
                    f"[inaccurate] {pricing} {design} {scope} {ent} {sense} "
                    f"{solver}/{form}: {row['status']} ratio {row['ratio']:.4g} "
                    f"in_set {row['in_set']} ({row['seconds']}s)",
                    flush=True,
                )
    return pd.DataFrame(rows)


def run_inaccurate(args: argparse.Namespace) -> dict[str, Any]:
    """Phase (a): the C1 T11 range programs that ended optimal_inaccurate."""
    t0 = time.perf_counter()
    ranges = pd.read_csv(C1_RQ2_DATA / "payout_ranges.csv")
    bad = ranges.loc[
        (ranges["status_min"] != "optimal") | (ranges["status_max"] != "optimal")
    ]
    groups = c1_groups(
        ["main"],
        lambda s: s.variant.kappa == 1.0 and s.variant.pricing in rq2.RANGE_PRICINGS,
    )
    frames = []
    for (pricing, design, scope), sub in bad.groupby(
        ["pricing", "design", "scope"], sort=False
    ):
        member = groups[("main", "thesis", str(pricing), 1.0, str(design))][str(scope)]
        frames.append(
            inaccurate_worker(
                str(pricing),
                str(design),
                str(scope),
                list(sub["entity_id"]),
                member,
                str(args.c1_store),
            )
        )
    table = pd.concat(frames, ignore_index=True)
    table.to_csv(args.full / "inaccurate.csv", index=False, float_format="%.10g")
    return {
        "inaccurate_entities": len(bad),
        "inaccurate_programs": len(table),
        "inaccurate_seconds": round(time.perf_counter() - t0, 1),
    }


# --------------------------------------------------------------------------
# Phase (b): non-unique joint designs in C1's within-scope comparisons
# --------------------------------------------------------------------------

JOINT_SCOPES: Final[tuple[str, ...]] = ("cluster", "portfolio")
VARIANTS: Final[tuple[str, ...]] = ("stored", "alt", "free_lo", "free_hi")
"""A joint design as stored in C1; its second optimum (``ALT_POLICY``); its
free-bin family with every free parameter at its lowest (largest KPIs) and at
its highest (smallest KPIs)."""
ALLOCATIONS: Final[tuple[str, ...]] = ("value", "loss")
T6_DESIGNS: Final[tuple[str, ...]] = ("mse", "eu", "wcvar@0.99", "wcvar@0.995")
T6_PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06")
COMBOS: Final[tuple[tuple[str, str], ...]] = (
    ("stored", "stored"),
    ("alt", "stored"),
    ("stored", "alt"),
    ("alt", "alt"),
    ("free_hi", "free_lo"),
    ("free_lo", "free_hi"),
)
"""(variant of the weighted-CVaR design, variant of the MSE or E[U] design).
The two free-bin combinations give the smallest and the largest difference
over the two free-bin families (every KPI is non-increasing in every payout
parameter)."""


def free_bin_family(
    js: JointSet, theta_loss: np.ndarray
) -> tuple[np.ndarray, np.ndarray, list[dict[str, Any]]]:
    """Return a joint design's free-bin ends (loss units) and free bins.

    A bin of entity ``j`` without a train row of that entity's index moves no
    train quantity, so every design that differs only there (within
    monotonicity and the cap) is exactly optimal (MAR-198 method (a)).

    Raises
    ------
    RuntimeError
        If an end design pays differently from the stored one on a train row.
    """
    from individual_nonuniqueness import free_bin_bounds, free_bins

    scale = float(js.ctx.scale)
    lo = theta_loss.copy()
    hi = theta_loss.copy()
    rows: list[dict[str, Any]] = []
    for j, ent in enumerate(js.ctx.problem.spec.entities):
        counts = js.basis[j].sum(axis=0)
        free = free_bins(counts)
        cap = float(js.ctx.cap[j]) * scale
        lo[j], hi[j] = free_bin_bounds(theta_loss[j], free, cap)
        for t in (lo[j], hi[j]):
            if not np.allclose(
                js.basis[j] @ t, js.basis[j] @ theta_loss[j], rtol=0, atol=1e-9 * cap
            ):
                raise RuntimeError(f"{ent.entity_id}: a free bin has train rows")
        rows.append(
            {
                "entity_id": ent.entity_id,
                "entity_locations": " ".join(ent.location_ids),
                "free_bins": " ".join(str(k) for k in free),
                "free_param_width_to_cap": float(np.max(hi[j] - lo[j], initial=0.0))
                / cap
                if cap > 0
                else math.nan,
            }
        )
    return lo, hi, rows


def variant_results(stored: rq2._Design, theta: np.ndarray, label: str) -> list[Any]:
    """Return the stored run's results with another ``theta`` (loss units)."""
    import dataclasses

    (r,) = stored.results
    return [dataclasses.replace(r, theta=np.asarray(theta), solver=label, attempts=())]


def nonunique_worker(
    family: str,
    pricing: str,
    kappa: float,
    scope: str,
    members: dict[str, tuple[ExperimentConfig, str]],
    store_root: str,
) -> dict[str, pd.DataFrame]:
    """Within-scope paired differences with each joint design's variants.

    Parameters
    ----------
    family, pricing : str
        C1 labels.
    kappa : float
        Budget loading.
    scope : str
        ``"cluster"`` or ``"portfolio"``.
    members : dict
        Design label to (single-run config, run id) of the C1 runs.
    store_root : str
        The C1 result store.

    Returns
    -------
    dict of pandas.DataFrame
        ``designs`` (per design and variant: objective, solver), ``entities``
        (free bins per entity), ``kpis`` (test portfolio KPIs per variant),
        ``paired`` (within-scope differences), ``allocation`` (C1 T6
        re-derived with the named allocation rules; kappa 1 only).
    """
    from parametric_insurance_design.bootstrap import (
        bootstrap_kpis,
        paired_difference,
        resample_years,
    )
    from parametric_insurance_design.evaluate import kpis

    t0 = time.perf_counter()
    cfg0 = next(iter(members.values()))[0]
    prepared = c1._prepared(cfg0)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    assert cfg0.bootstrap is not None
    resample = resample_years(
        test.years, cfg0.bootstrap.n_bootstrap, cfg0.bootstrap.rng()
    )
    level = cfg0.bootstrap.level
    eval_betas = (
        c1.REFERENCE_EVAL_BETAS if family == "reference" else c1.ANNUAL_EVAL_BETAS
    )
    design_rows: list[dict[str, Any]] = []
    entity_rows: list[dict[str, Any]] = []
    kpi_rows: list[pd.DataFrame] = []
    alloc_rows: list[pd.DataFrame] = []
    boots: dict[tuple[str, str, float], Any] = {}
    for design, (cfg, rid) in members.items():
        js, stored = rebuild_joint(cfg, rid, Path(store_root))
        comps = cfg.to_components()
        alt = solve(js.built, rq2.ALT_POLICY, pricing=comps.pricing)
        theta_stored = np.vstack([r.theta for r in stored.results])
        lo, hi, ents = free_bin_family(js, theta_stored)
        thetas = {
            "stored": theta_stored,
            "alt": np.asarray(alt.theta),
            "free_lo": lo,
            "free_hi": hi,
        }
        chash = config_hash(cfg)
        for e in ents:
            entity_rows.append({"design": design, "config_hash": chash, **e})
        for var, th in thetas.items():
            chk = js.check(th / js.ctx.scale)
            design_rows.append(
                {
                    "design": design,
                    "variant": var,
                    "objective_rel_diff": chk["objective_excess"],
                    "budget_excess": chk["budget_excess"],
                    "structure_violation": chk["structure_violation"],
                    "solver": stored.solvers if var != "alt" else alt.solver,
                    "status": stored.statuses if var != "alt" else alt.status.value,
                    "config_hash": chash,
                    "run_id": rid,
                }
            )
            results = variant_results(stored, th, var)
            for beta in eval_betas:
                boot = bootstrap_kpis(
                    prepared,
                    stored.scope,
                    results,
                    basis=comps.basis,
                    beta=beta,
                    run_id=f"{rid}|{var}",
                    resample=resample,
                    sample=test,
                    pricing=comps.pricing,
                    level=level,
                ).portfolio_rows()
                boots[(design, var, beta)] = boot
                t = boot.table.copy()
                t["design"], t["variant"], t["eval_beta"] = design, var, beta
                t["config_hash"] = chash
                kpi_rows.append(t)
            t6 = (
                kappa == 1.0
                and family == "main"
                and pricing in T6_PRICINGS
                and design in T6_DESIGNS
                and var in ("stored", "alt")
            )
            if not t6:
                continue
            for split, sample in (("train", train), ("test", test)):
                for rule in ALLOCATIONS:
                    t = kpis(
                        prepared,
                        stored.scope,
                        results,
                        basis=comps.basis,
                        beta=0.99,
                        run_id=rid,
                        sample=sample,
                        pricing=comps.pricing,
                        allocation=rule,
                    )
                    t = t.loc[
                        t["kpi"].isin(
                            ["expected_payout", "expected_loss", "payout_to_loss_ratio"]
                        )
                    ].copy()
                    t["design"], t["variant"] = design, var
                    t["split"], t["allocation"] = split, rule
                    t["config_hash"] = chash
                    alloc_rows.append(t)
    paired_rows: list[pd.DataFrame] = []
    for a in members:
        if not a.startswith("wcvar"):
            continue
        for b in ("mse", "eu"):
            if b not in members:
                continue
            for va, vb in COMBOS:
                for beta in eval_betas:
                    d = paired_difference(boots[(a, va, beta)], boots[(b, vb, beta)])
                    d["design_a"], d["design_b"] = a, b
                    d["variant_a"], d["variant_b"] = va, vb
                    d["eval_beta"] = beta
                    d["config_hash_a"] = config_hash(members[a][0])
                    d["config_hash_b"] = config_hash(members[b][0])
                    paired_rows.append(d)
    frames = {
        "designs": pd.DataFrame(design_rows),
        "entities": pd.DataFrame(entity_rows),
        "kpis": pd.concat(kpi_rows, ignore_index=True),
        "paired": pd.concat(paired_rows, ignore_index=True),
    }
    if alloc_rows:
        frames["allocation"] = pd.concat(alloc_rows, ignore_index=True)
    for f in frames.values():
        f["family"] = family
        f["pricing"] = pricing
        f["kappa"] = kappa
        f["scope"] = scope
    print(
        f"[nonunique] {family} {pricing} k{kappa:g} {scope} "
        f"{time.perf_counter() - t0:.0f}s",
        flush=True,
    )
    return frames


def pool_run(
    worker: Callable[..., dict[str, pd.DataFrame]],
    tasks: list[tuple[Any, ...]],
    jobs: int,
) -> dict[str, pd.DataFrame]:
    """Run ``worker(*task)`` in ``jobs`` spawned processes; concat frames."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from multiprocessing import get_context

    out: dict[str, list[pd.DataFrame]] = {}
    with ProcessPoolExecutor(max_workers=jobs, mp_context=get_context("spawn")) as pool:
        futs = [pool.submit(worker, *t) for t in tasks]
        for i, fut in enumerate(as_completed(futs), 1):
            for name, frame in fut.result().items():
                out.setdefault(name, []).append(frame)
            print(f"[{i}/{len(futs)}] done", flush=True)
    return {n: pd.concat(f, ignore_index=True) for n, f in out.items()}


def check_paired_against_c1(paired: pd.DataFrame) -> int:
    """Raise unless the stored/stored differences equal C1's paired tables."""
    mine = paired.loc[
        (paired["variant_a"] == "stored") & (paired["variant_b"] == "stored")
    ]
    n = 0
    data = REPO_ROOT / "research" / "data" / "c1"
    for family in ("main", "reference"):
        theirs = pd.read_csv(data / f"paired_{family}.csv")
        theirs = theirs.loc[theirs["eval_split"] == "test"]
        m = mine.loc[mine["family"] == family].merge(
            theirs,
            on=[
                "pricing",
                "kappa",
                "scope",
                "design_a",
                "design_b",
                "kpi",
                "eval_beta",
            ],
            suffixes=("", "_c1"),
        )
        for col in ("difference", "ci_low", "ci_high"):
            ok = np.isclose(m[col], m[f"{col}_c1"], rtol=1e-5, atol=1e-2)
            if not ok.all():
                bad = m.loc[~ok].iloc[0]
                raise RuntimeError(f"{family}: {col} differs from C1: {bad.to_dict()}")
        n += len(m)
    if n == 0:
        raise RuntimeError("no stored/stored row matched C1's paired tables")
    return n


def run_nonunique(args: argparse.Namespace) -> dict[str, Any]:
    """Phase (b): every joint design of C1 sections 3-5 and its variants."""
    t0 = time.perf_counter()
    groups = c1_groups(["main", "reference"], lambda s: s.scope in JOINT_SCOPES)
    by_scope: dict[tuple[str, str, float, str], dict[str, tuple[Any, str]]] = {}
    for (family, _, pricing, kappa, design), members in groups.items():
        for scope, member in members.items():
            by_scope.setdefault((family, pricing, kappa, scope), {})[design] = member
    tasks: list[tuple[Any, ...]] = []
    for (family, pricing, kappa, scope), members in by_scope.items():
        label = f"{family}|{pricing}|{kappa:g}|{scope}"
        if args.only and not any(o in label for o in args.only):
            continue
        tasks.append((family, pricing, kappa, scope, members, str(args.c1_store)))
    tables = pool_run(nonunique_worker, tasks, args.jobs)
    n_checked = check_paired_against_c1(tables["paired"])
    print(f"checked {n_checked} stored differences against C1", flush=True)
    suffix = "_" + "_".join(args.only) if args.only else ""
    for name, table in tables.items():
        table.to_csv(
            args.full / f"nonunique_{name}{suffix}.csv",
            index=False,
            float_format="%.10g",
        )
    return {
        "nonunique_groups": len(tasks),
        "nonunique_rows_checked_against_c1": n_checked,
        "nonunique_seconds": round(time.perf_counter() - t0, 1),
        "alt_policy": {
            "lp_solvers": list(rq2.ALT_POLICY.lp_solvers),
            "qp_solvers": list(rq2.ALT_POLICY.qp_solvers),
        },
    }


# --------------------------------------------------------------------------
# Phases (c) and (d): new runs through the runner, compared across scopes
# --------------------------------------------------------------------------

SENS_PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06")
SENS_DESIGNS: Final[dict[str, dict[str, Any]]] = {
    "mse": {"kind": "mse"},
    "eu": {"kind": "expected_uncovered"},
    "wcvar@0.99": {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.99},
    "wcvar@0.995": {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.995},
}
NOISE_VARIANTS: Final[tuple[str, ...]] = ("none", "common")
N_CLUSTERS: Final[tuple[int, ...]] = (1, 2, 3, 4, 5, 6, 7, 8, 9)
SEP: Final[str] = "cluster_sep"
"""The cluster scope with ``joint: false`` (MAR-180): the same clusters and
index, each cluster its own design problem with its own budget."""
COMMON_NOISE_DIR: Final[str] = "thesis_common_noise"
COMMON_NOISE_FUNCTION: Final[str] = (
    "research/scripts/c1_rq2_sensitivities.py:add_common_noise"
)


@dataclass(frozen=True)
class SensSpec:
    """One single run of phase (c) or (d)."""

    family: str  # "noise" or "nclusters"
    variant: str  # "none", "common"; "n<k>"
    pricing: str
    scope: str  # "individual", "cluster", "cluster_sep", "portfolio"
    design: str
    config: ExperimentConfig

    @property
    def group(self) -> tuple[str, str, str, str]:
        """Bootstrap group: scopes compared on one resample."""
        variant = "all" if self.family == "nclusters" else self.variant
        return (self.family, variant, self.pricing, self.design)

    @property
    def label(self) -> str:
        """Scope label within its group."""
        if self.family == "nclusters" and self.scope in ("cluster", SEP):
            return f"{self.scope}|{self.variant}"
        return self.scope


def add_common_noise(
    eventset: EventSet,
    *,
    level: float,
    n_copies: int,
    rng: np.random.Generator,
    bounds: tuple[float, float],
) -> EventSet:
    """Return the thesis noise layer with one draw per row shared by all assets.

    Same as :func:`parametric_insurance_design.noise.add_noise` with
    ``kind="heteroscedastic"`` (event-major copies, ``rate / n_copies``,
    a mean-one lognormal factor per location whose log-sd ramps with the
    location's index between ``bounds``), except that one standard-normal
    draw ``z`` per output row is shared by every location:
    ``factor_j = exp(-sigma_j**2 / 2 + sigma_j * z)``. Each asset's noise has
    the per-asset layer's marginal distribution; across assets it is
    comonotone instead of independent. Research only (MAR-206); not a
    library function.

    Parameters
    ----------
    eventset : EventSet
        Input without draws.
    level : float
        Noise level eta.
    n_copies : int
        Copies per event row.
    rng : numpy.random.Generator
        Source of the shared draws.
    bounds : tuple of float
        Index range over which the log-sd ramps from 0 to ``level``.

    Returns
    -------
    EventSet
        ``n_copies * n_rows`` rows, with a ``noise_common`` transform record.
    """
    import dataclasses

    from parametric_insurance_design.eventset import TransformRecord

    if (eventset.events["draw_id"].to_numpy() != 0).any():
        raise ValueError("add_common_noise needs an EventSet without draws")
    low, high = bounds
    n_rows = eventset.n_rows
    n = n_rows * n_copies
    source = np.repeat(np.arange(n_rows), n_copies)
    events = eventset.events.iloc[source].reset_index(drop=True)
    events["draw_id"] = np.tile(np.arange(n_copies), n_rows)
    events["rate"] = events["rate"] / n_copies
    index = eventset.index[source]
    loss = eventset.loss[source]
    z = rng.standard_normal(size=n)
    for j in range(loss.shape[1]):
        r = np.clip((index[:, j] - low) / (high - low), 0.0, 1.0)
        sigma = np.sqrt(np.log(1.0 + (level * r) ** 2))
        loss[:, j] = loss[:, j] * np.exp(-0.5 * sigma**2 + sigma * z)
    record = TransformRecord(
        name="noise_common",
        function=COMMON_NOISE_FUNCTION,
        version=package_versions().get("parametric-insurance-design", "unknown"),
        n_filters_before=len(eventset.metadata.filters),
        parameters={
            "kind": "heteroscedastic, one draw per row shared by all locations",
            "level": level,
            "n_copies": n_copies,
            "bounds": [low, high],
            "location_ids": list(eventset.location_ids),
        },
    )
    metadata = dataclasses.replace(
        eventset.metadata, transforms=(*eventset.metadata.transforms, record)
    )
    return EventSet(
        events=events,
        locations=eventset.locations,
        index=index,
        loss=loss,
        metadata=metadata,
    )


def build_common_noise(full: Path) -> tuple[Path, str]:
    """Write the common-noise thesis EventSet (seed 42, eta 0.3, 13 copies).

    Returns
    -------
    path, checksum
        Its directory and content hash.
    """
    base = load_config(c1.BASE_CONFIG)
    assert base.noise is not None
    assert base.portfolio.location_ids is not None
    raw = c1._input(base).eventset
    data = raw.select_locations(list(base.portfolio.location_ids))
    noisy = add_common_noise(
        data,
        level=base.noise.level,
        n_copies=base.noise.n_copies,
        rng=base.noise.rng(),
        bounds=tuple(base.noise.bounds),  # type: ignore[arg-type]
    )
    path = full / "eventsets" / COMMON_NOISE_DIR
    noisy.to_parquet(path, overwrite=True)
    return path, noisy.content_hash()


def single(
    base: dict[str, Any],
    pricing: str,
    scope: dict[str, Any],
    design: str,
    store: Path,
) -> ExperimentConfig:
    """One single run (one scope, one objective) at kappa 1."""
    from parametric_insurance_design.experiment.config import parse_config

    data = json.loads(json.dumps(base))
    data["pricing"] = c1.PRICINGS[pricing]
    data["constraints"] = [{"kind": "budget", "loading": 1.0}]
    data["scopes"] = [scope]
    data["objectives"] = [SENS_DESIGNS[design]]
    data["output"] = {"directory": str(store)}
    return parse_config(data)


def _cluster_scope(base: dict[str, Any], n: int, joint: bool) -> dict[str, Any]:
    (cl,) = [s for s in base["scopes"] if s["kind"] == "cluster"]
    out = json.loads(json.dumps(cl))
    out["n_clusters"] = n
    out["joint"] = joint
    return out


def plan_noise(full: Path, store: Path) -> list[SensSpec]:
    """Phase (c): no noise layer and common noise, every scope, kappa 1."""
    specs: list[SensSpec] = []
    for variant in NOISE_VARIANTS:
        cfg = load_config(CONFIG_DIR / f"noise_{variant}.yaml")
        base = cfg.model_dump(mode="json")
        base["eventset"]["path"] = str(cfg.eventset.path)
        if variant == "common":
            path, checksum = build_common_noise(full)
            if str(path.resolve()) != str(Path(cfg.eventset.path).resolve()):
                raise RuntimeError(
                    f"common-noise EventSet at {path}, config says {cfg.eventset.path}"
                )
            if checksum != cfg.eventset.checksum:
                raise RuntimeError(
                    f"common-noise EventSet checksum {checksum} != config "
                    f"{cfg.eventset.checksum}: update noise_common.yaml"
                )
        scopes = {
            "individual": {"kind": "individual"},
            "cluster": _cluster_scope(base, 3, True),
            SEP: _cluster_scope(base, 3, False),
            "portfolio": {"kind": "portfolio"},
        }
        for pricing in SENS_PRICINGS:
            for scope, sd in scopes.items():
                for design in SENS_DESIGNS:
                    specs.append(
                        SensSpec(
                            "noise",
                            variant,
                            pricing,
                            scope,
                            design,
                            single(base, pricing, sd, design, store),
                        )
                    )
    return specs


def plan_nclusters(store: Path) -> list[SensSpec]:
    """Phase (d): the cluster scope at n = 1..9, joint and not, kappa 1.

    The base is C1's main config with the C1 run name, so that n = 3,
    ``joint: true`` is C1's cluster run (same config hash).
    """
    base = load_config(c1.BASE_CONFIG).model_dump(mode="json")
    base["name"] = "c1-main"
    base["eventset"]["path"] = str(load_config(c1.BASE_CONFIG).eventset.path)
    specs: list[SensSpec] = []
    for n in N_CLUSTERS:
        for joint in (True, False):
            sd = _cluster_scope(base, n, joint)
            for pricing in SENS_PRICINGS:
                for design in SENS_DESIGNS:
                    specs.append(
                        SensSpec(
                            "nclusters",
                            f"n{n}",
                            pricing,
                            "cluster" if joint else SEP,
                            design,
                            single(base, pricing, sd, design, store),
                        )
                    )
    return specs


def solve_runs(
    specs: Sequence[SensSpec], store_root: Path, jobs: int
) -> dict[str, str]:
    """Solve every spec not yet in the store; return config hash -> run id.

    Raises
    ------
    RuntimeError
        If a run failed or was not evaluated (it is recorded in the store).
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from multiprocessing import get_context

    from parametric_insurance_design.experiment.runner import RunOutcome
    from parametric_insurance_design.experiment.store import ResultStore

    store = ResultStore(store_root)
    rid_of: dict[str, str] = {}
    todo: dict[str, ExperimentConfig] = {}
    for s in specs:
        h = config_hash(s.config)
        checksum = s.config.eventset.checksum
        assert checksum is not None
        rid = run_key(h, checksum, policy=DEFAULT_POLICY)
        rid_of[h] = rid
        if not store.has_run(rid) and rid not in todo:
            todo[rid] = s.config
    print(
        f"{len(specs)} runs, {len(set(rid_of.values()))} distinct, "
        f"{len(todo)} to solve",
        flush=True,
    )
    with ProcessPoolExecutor(max_workers=jobs, mp_context=get_context("spawn")) as pool:
        futs = {pool.submit(c1.solve_worker, cfg): rid for rid, cfg in todo.items()}
        for i, fut in enumerate(as_completed(futs), 1):
            tables, manifest, seconds = fut.result()
            rid = futs[fut]
            if manifest["run_id"] != rid:
                raise RuntimeError(f"run id mismatch: {manifest['run_id']} != {rid}")
            store.write_run(tables, manifest)
            print(f"[solve {i}/{len(todo)}] {rid[7:19]} {seconds:.1f}s", flush=True)
    failed = []
    for rid in set(rid_of.values()):
        outcome = RunOutcome.from_manifest(store.manifest(rid), cached=True)
        if not outcome.ok:
            failed.append(f"{rid}: {outcome}")
    if failed:
        raise RuntimeError("failed runs (recorded in the store):\n" + "\n".join(failed))
    return rid_of


SENS_PAIRS: Final[dict[str, tuple[tuple[str, str], ...]]] = {
    "noise": (
        ("portfolio", "individual"),
        ("cluster", "individual"),
        (SEP, "individual"),
        ("cluster", SEP),
        ("cluster", "portfolio"),
    ),
}


def _nclusters_pairs(labels: Sequence[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for n in N_CLUSTERS:
        j, s = f"cluster|n{n}", f"{SEP}|n{n}"
        if j in labels and s in labels:
            out += [
                (j, "individual"),
                (s, "individual"),
                (j, s),
                (j, "portfolio"),
                (s, "portfolio"),
            ]
    return out


def sens_group_worker(
    group: tuple[str, str, str, str],
    members: dict[str, tuple[ExperimentConfig, str, str]],
) -> dict[str, pd.DataFrame]:
    """Bootstrap one group's scopes on one resample; compare across scopes.

    Parameters
    ----------
    group : tuple of str
        (family, variant, pricing, design).
    members : dict
        Scope label to (single-run config, run id, store root).

    Returns
    -------
    dict of pandas.DataFrame
        ``kpis`` (train and test portfolio KPIs), ``paired`` (test: paired
        90 % intervals; train: point differences), ``runs`` (per run:
        problems, statuses, solvers, objective, budget use), ``entities``
        (the payout entities and their train ``E[pi]/E[L]``).
    """
    from parametric_insurance_design.bootstrap import (
        bootstrap_kpis,
        paired_difference,
        resample_years,
    )
    from parametric_insurance_design.evaluate import kpis
    from parametric_insurance_design.experiment.store import ResultStore

    t0 = time.perf_counter()
    family = group[0]
    cfg0 = members["individual"][0]
    prepared = c1._prepared(cfg0)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    assert cfg0.bootstrap is not None
    resample = resample_years(
        test.years, cfg0.bootstrap.n_bootstrap, cfg0.bootstrap.rng()
    )
    level = cfg0.bootstrap.level
    kpi_rows: list[pd.DataFrame] = []
    run_rows: list[dict[str, Any]] = []
    ent_rows: list[pd.DataFrame] = []
    boots: dict[tuple[str, float], Any] = {}
    for label, (cfg, rid, root) in members.items():
        if c1._prepared(cfg).content_hash() != prepared.content_hash():
            raise RuntimeError(f"{group} {label}: another prepared EventSet")
        d = rq2._stored(cfg, rid, ResultStore(Path(root)))
        comps = cfg.to_components()
        runs = ResultStore(Path(root)).read("runs", run_ids=[rid])
        run_rows.append(
            {
                "scope": label,
                "n_problems": len(d.results),
                "statuses": d.statuses,
                "solvers": d.solvers,
                "objective_value": d.objective_value,
                "sum_problem_premiums": float(runs["premium"].sum()),
                "config_hash": d.config_hash,
                "run_id": rid,
                "store": "c1" if root != str(FULL_DIR / "store") else "mar206",
            }
        )
        for beta in c1.ANNUAL_EVAL_BETAS:
            boot = bootstrap_kpis(
                prepared,
                d.scope,
                d.results,
                basis=comps.basis,
                beta=beta,
                run_id=rid,
                resample=resample,
                sample=test,
                pricing=comps.pricing,
                level=level,
            )
            boots[(label, beta)] = boot.portfolio_rows()
            tr = kpis(
                prepared,
                d.scope,
                d.results,
                basis=comps.basis,
                beta=beta,
                run_id=rid,
                sample=train,
                pricing=comps.pricing,
            )
            for split, table in (("test", boot.table), ("train", tr)):
                t = table.loc[table["level"] == "portfolio"].copy()
                t["split"], t["eval_beta"], t["scope"] = split, beta, label
                t["config_hash"] = d.config_hash
                kpi_rows.append(t)
            if beta == 0.99:
                e = tr.loc[
                    (tr["level"] == "entity")
                    & (tr["kpi"].isin(["expected_payout", "expected_loss"]))
                ].copy()
                locs = {
                    en.entity_id: " ".join(en.location_ids)
                    for r in d.results
                    for en in r.spec.entities
                }
                e["entity_locations"] = e["subject_id"].map(locs)
                e["scope"], e["config_hash"] = label, d.config_hash
                ent_rows.append(e)
    allk = pd.concat(kpi_rows, ignore_index=True)
    labels = list(members)
    pairs = (
        _nclusters_pairs(labels) if family == "nclusters" else list(SENS_PAIRS[family])
    )
    paired_rows: list[pd.DataFrame] = []
    for a, b in pairs:
        if a not in members or b not in members:
            continue
        for beta in c1.ANNUAL_EVAL_BETAS:
            diff = paired_difference(
                boots[(a, beta)], boots[(b, beta)], across_scopes=True
            )
            diff["split"] = "test"
            port = allk.loc[(allk["split"] == "train") & (allk["eval_beta"] == beta)]
            va = port.loc[port["scope"] == a].set_index("kpi")["value"]
            vb = port.loc[port["scope"] == b].set_index("kpi")["value"]
            tr = pd.DataFrame(
                {"kpi": va.index, "value_a": va.to_numpy(), "value_b": vb[va.index]}
            )
            tr["difference"] = tr["value_a"] - tr["value_b"]
            tr["split"] = "train"
            for f in (diff, tr):
                f["scope_a"], f["scope_b"], f["eval_beta"] = a, b, beta
                f["config_hash_a"] = config_hash(members[a][0])
                f["config_hash_b"] = config_hash(members[b][0])
                paired_rows.append(f)
    frames = {
        "kpis": allk,
        "paired": pd.concat(paired_rows, ignore_index=True),
        "runs": pd.DataFrame(run_rows),
        "entities": pd.concat(ent_rows, ignore_index=True),
    }
    for f in frames.values():
        f["family"], f["variant"], f["pricing"], f["design"] = group
    print(f"[group] {'|'.join(group)} {time.perf_counter() - t0:.0f}s", flush=True)
    return frames


def run_sens(args: argparse.Namespace, family: str) -> dict[str, Any]:
    """Phases (c) and (d): solve the runs, then bootstrap per group."""
    t0 = time.perf_counter()
    store = args.full / "store"
    specs = plan_noise(args.full, store) if family == "noise" else plan_nclusters(store)
    if args.only:
        specs = [s for s in specs if any(o in "|".join(s.group) for o in args.only)]
    rid_of = solve_runs(specs, store, args.jobs)
    t_solve = time.perf_counter() - t0
    groups: dict[tuple[str, str, str, str], dict[str, tuple[Any, str, str]]] = {}
    for s in specs:
        h = config_hash(s.config)
        groups.setdefault(s.group, {})[s.label] = (s.config, rid_of[h], str(store))
    if family == "nclusters":
        c1g = c1_groups(
            ["main"],
            lambda s: (
                s.variant.kappa == 1.0
                and s.variant.pricing in SENS_PRICINGS
                and s.scope in ("individual", "portfolio")
            ),
        )
        for (_, _, pricing, design), members in groups.items():
            for scope in ("individual", "portfolio"):
                cfg, rid = c1g[("main", "thesis", pricing, 1.0, design)][scope]
                members[scope] = (cfg, rid, str(args.c1_store))
    tasks = [(g, m) for g, m in groups.items()]
    tables = pool_run(sens_group_worker, tasks, args.jobs)
    suffix = "_" + "_".join(args.only) if args.only else ""
    for name, table in tables.items():
        table.to_csv(
            args.full / f"{family}_{name}{suffix}.csv",
            index=False,
            float_format="%.10g",
        )
    return {
        f"{family}_runs": len(specs),
        f"{family}_groups": len(groups),
        f"{family}_solve_seconds": round(t_solve, 1),
        f"{family}_seconds": round(time.perf_counter() - t0, 1),
    }


# --------------------------------------------------------------------------
# Phase (e): joint - individual over both optimal sets
# --------------------------------------------------------------------------

MAR198_FULL: Final[Path] = Path(
    os.environ.get("MAR198_FULL", str(REPO_ROOT / "results" / "mar198"))
)
E_KPIS: Final[tuple[tuple[str, str, float | None], ...]] = (
    ("test", "expected_uncovered", None),
    ("test", "cvar_uncovered", 0.95),
    ("test", "cvar_uncovered", 0.99),
    ("test", "cvar_uncovered", 0.995),
    ("train", "cvar_uncovered", 0.99),
)
"""(split, KPI, KPI beta) whose range over each joint design's near-optimal
set is measured: every test KPI of C1 6b, and the in-sample tail."""
ALL_LABELS: Final[tuple[str, ...]] = ("eu", "cvar@0.95", "cvar@0.99", "cvar@0.995")
PROJECT_MARGIN: Final[float] = 1e-6


def klabel(kpi: str, beta: float | None) -> str:
    """Return MAR-198's KPI label, e.g. ``"cvar@0.99"`` or ``"eu"``."""
    return "eu" if beta is None else f"cvar@{beta:g}"


def _kpi_args(label: str) -> tuple[str, float | None]:
    if label == "eu":
        return "expected_uncovered", None
    return "cvar_uncovered", float(label.split("@")[1])


class JointRanger:
    """Range programs over one joint design's near-optimal set (scaled).

    The set is C1 T11's (:class:`JointSet`), with the MSE objective's
    quadratic constraint in the exact compact form
    (:meth:`JointSet.compact_mse_constraint`).

    Parameters
    ----------
    js : JointSet
        The design problem, re-solved.
    """

    def __init__(self, js: JointSet) -> None:
        self.js = js
        ctx = js.ctx
        if js.objective.name == "mse":
            objective_cons = [js.compact_mse_constraint()]
        else:
            objective_cons = [js.built.objective.expression <= js.bound]
        self.constraints = [*js.built.problem.constraints, *objective_cons]
        shape = tuple(ctx.theta.shape)
        self.cost = cp.Parameter(shape, name="cost")
        self.lp = cp.Problem(
            cp.Minimize(cp.sum(cp.multiply(self.cost, ctx.theta))), self.constraints
        )
        limit = js.budget.loading * ctx.measure.expectation(ctx.loss)  # type: ignore[attr-defined]
        self.target = cp.Parameter(shape, name="target")
        gap = cp.Variable(name="gap")
        self.projection = cp.Problem(
            cp.Minimize(gap),
            [
                *js.built.problem.constraints,
                *objective_cons,
                js.built.premium.expression <= (1.0 - PROJECT_MARGIN) * limit,
                ctx.theta - self.target <= gap,
                self.target - ctx.theta <= gap,
            ],
        )

    @property
    def scale(self) -> float:
        """The problem's loss scale."""
        return float(self.js.ctx.scale)

    def _theta(self) -> np.ndarray | None:
        value = self.js.ctx.theta.value
        return None if value is None else np.asarray(value, dtype=np.float64).copy()

    def admit(self, theta: np.ndarray) -> tuple[np.ndarray | None, str]:
        """Return ``theta`` (scaled) if in the set, else its projection, else None."""
        from individual_nonuniqueness import solve_range

        if not np.all(np.isfinite(theta)):
            return None, "outside_set"
        if self.js.inside(self.js.check(theta)):
            return theta, ""
        self.target.value = theta
        self.js.ctx.theta.value = None
        solve_range(self.projection)
        proj = self._theta()
        if proj is not None and self.js.inside(self.js.check(proj)):
            return proj, "projected"
        return None, "outside_set"

    def minimise_kpi(
        self, sd: SplitData, beta: float | None, reference: float
    ) -> tuple[np.ndarray | None, str]:
        """Smallest portfolio KPI of a split over the set (one convex program)."""
        from individual_nonuniqueness import solve_range

        from parametric_insurance_design.objectives import rockafellar_uryasev

        ctx = self.js.ctx
        norm = float(max(sd.loss.max(initial=0.0), 1.0))
        payout = sum(
            (b @ ctx.theta[j]) * (self.scale / norm) for j, b in enumerate(sd.basis)
        )
        u = sd.measure.aggregate_expression(cp.pos(sd.loss / norm - payout))
        p = np.asarray(sd.measure.probability, dtype=np.float64)
        goal = p @ u if beta is None else rockafellar_uryasev(u, p, beta)[0]
        factor = norm / reference if reference > 0 else 1.0
        prob = cp.Problem(cp.Minimize(goal * factor), self.constraints)
        ctx.theta.value = None
        status = solve_range(prob)
        raw = self._theta()
        if raw is None:
            return None, status
        theta, note = self.admit(raw)
        return theta, f"{status} {note}".strip()

    def maximise_kpi(
        self, sd: SplitData, kpi: str, beta: float | None, start: np.ndarray
    ) -> tuple[np.ndarray | None, int, str]:
        """Largest KPI found by successive linearisation from ``start`` (scaled)."""
        from individual_nonuniqueness import MAX_STEPS, STEP_RTOL, solve_range

        current, note = self.admit(start)
        if current is None:
            return None, 0, "start outside_set"
        notes = {f"start {note}"} if note else set()
        value = sd.value(list(current * self.scale), kpi, beta)
        for step in range(1, MAX_STEPS + 1):
            w = sd.weights(list(current * self.scale), kpi, beta)
            cost = np.vstack([b.T @ w for b in sd.basis])
            top = float(np.max(np.abs(cost), initial=0.0))
            self.cost.value = cost / top if top > 0 else cost
            self.js.ctx.theta.value = None
            status = solve_range(self.lp)
            raw = self._theta()
            nxt, note = (None, "no iterate") if raw is None else self.admit(raw)
            if nxt is None:
                return current, step, ";".join(["stopped " + status, *sorted(notes)])
            if status != "optimal" or note:
                notes.add(f"{status} {note}".strip())
            new = sd.value(list(nxt * self.scale), kpi, beta)
            if new <= value * (1.0 + STEP_RTOL) + 1e-9:
                if new > value:
                    current = nxt
                return current, step, ";".join(["optimal", *sorted(notes)])
            current, value = nxt, new
        return current, MAX_STEPS, ";".join(["step limit", *sorted(notes)])


def joint_split(
    js: JointSet, cfg: ExperimentConfig, prepared: EventSet, sample: Sample
) -> SplitData:
    """Return MAR-198's ``SplitData`` for a joint design's entities on a split."""
    comps = cfg.to_components()
    data = sample.select(prepared)
    measure = outcome_measure(data, comps.basis, years=sample.years)
    problem = comps.scopes[0].materialise(data, js.ctx.problem.spec)
    basis = [
        dense(comps.payout.basis_matrix(problem.index[:, j]))
        for j in range(problem.n_entities)
    ]
    loss = np.asarray(data.loss, dtype=np.float64).sum(axis=1)
    return SplitData(sample, data, measure, loss, basis)


def joint_range_worker(
    pricing: str,
    design: str,
    scope: str,
    member: tuple[ExperimentConfig, str],
    store_root: str,
) -> dict[str, Any]:
    """Range one joint design's portfolio KPIs over its near-optimal set.

    Returns
    -------
    dict
        ``rows`` (per split and KPI: stored, alt, min, max found, statuses),
        ``reps`` (test replicates of every candidate on the C1 resample),
        ``point`` (candidate -> split -> label -> value), ``meta``.
    """
    from parametric_insurance_design.bootstrap import kpi_replicates, resample_years
    from parametric_insurance_design.evaluate import kpis

    t0 = time.perf_counter()
    cfg, rid = member
    comps = cfg.to_components()
    js, stored = rebuild_joint(cfg, rid, Path(store_root))
    ranger = JointRanger(js)
    prepared = c1._prepared(cfg)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    sd = {
        "train": joint_split(js, cfg, prepared, train),
        "test": joint_split(js, cfg, prepared, test),
    }
    scale = ranger.scale
    stored_theta = np.vstack([r.theta for r in stored.results])
    alt = solve(js.built, rq2.ALT_POLICY, pricing=comps.pricing)
    lo, hi, _ = free_bin_family(js, stored_theta)
    cand: dict[str, np.ndarray] = {
        "stored": stored_theta,
        "alt": np.asarray(alt.theta, dtype=np.float64),
        "free_lo": lo,
        "free_hi": hi,
    }
    statuses: dict[str, str] = {}
    steps: dict[str, int] = {}
    for split, kpi, beta in E_KPIS:
        lab = f"{split}|{klabel(kpi, beta)}"
        ref = sd[split].value(list(stored_theta), kpi, beta)
        th, st = ranger.minimise_kpi(sd[split], beta, ref)
        statuses[f"min|{lab}"] = st
        if th is not None:
            cand[f"min|{lab}"] = th * scale
        best: tuple[float, np.ndarray | None, int, str] = (-math.inf, None, 0, "")
        for start_name in ("stored", "alt"):
            th, n, st = ranger.maximise_kpi(
                sd[split], kpi, beta, cand[start_name] / scale
            )
            if th is None:
                st = f"{start_name}: {st}"
                if best[1] is None:
                    best = (-math.inf, None, n, st)
                continue
            v = sd[split].value(list(th * scale), kpi, beta)
            if v > best[0]:
                best = (v, th, n, f"{start_name}: {st}")
        statuses[f"max|{lab}"] = best[3]
        steps[f"max|{lab}"] = best[2]
        if best[1] is not None:
            cand[f"max|{lab}"] = best[1] * scale
        print(
            f"[joint_ranges] {pricing} {design} {scope} {lab}: "
            f"{statuses[f'min|{lab}']} / {statuses[f'max|{lab}']} "
            f"({time.perf_counter() - t0:.0f}s)",
            flush=True,
        )
    # every candidate: in the set (or the alt/free designs), point values
    point: dict[str, dict[str, dict[str, float]]] = {}
    checks: dict[str, dict[str, float]] = {}
    for name, th in cand.items():
        checks[name] = js.check(th / scale)
        point[name] = {
            split: {
                lab: sd[split].value(list(th), *_kpi_args(lab)) for lab in ALL_LABELS
            }
            for split in ("train", "test")
        }
    # numpy KPIs equal the library's for the stored design
    for split, sample in (("train", train), ("test", test)):
        for beta in c1.ANNUAL_EVAL_BETAS:
            k = kpis(
                prepared,
                stored.scope,
                stored.results,
                basis=comps.basis,
                beta=beta,
                run_id=rid,
                sample=sample,
                pricing=comps.pricing,
            )
            port = k.loc[k["level"] == "portfolio"].set_index("kpi")["value"]
            for lab, kname in (
                (f"cvar@{beta:g}", "cvar_uncovered"),
                ("eu", "expected_uncovered"),
            ):
                if not np.isclose(point["stored"][split][lab], port[kname], rtol=1e-8):
                    raise RuntimeError(f"{split} {lab}: numpy != evaluate.kpis")
    # test replicates on the C1 resample
    assert cfg.bootstrap is not None
    resample = resample_years(
        test.years, cfg.bootstrap.n_bootstrap, cfg.bootstrap.rng()
    )
    tsd = sd["test"]
    row_years = tsd.eventset.events["year"].to_numpy(dtype=np.int64)
    reps: dict[str, np.ndarray] = {}
    for name, th in cand.items():
        if not (name in ("stored", "alt", "free_lo", "free_hi") or "|test|" in name):
            continue
        payout = tsd.payout(list(th))
        for beta in c1.ANNUAL_EVAL_BETAS:
            r = kpi_replicates(
                tsd.loss, payout, tsd.measure, row_years, resample, beta=beta
            )
            reps[f"{name}||cvar@{beta:g}"] = np.asarray(r["cvar_uncovered"])
            reps[f"{name}||eu"] = np.asarray(r["expected_uncovered"])
    rows = []
    for split, kpi, beta in E_KPIS:
        lab = klabel(kpi, beta)
        key = f"{split}|{lab}"
        rows.append(
            {
                "pricing": pricing,
                "kappa": 1.0,
                "design": design,
                "scope": scope,
                "split": split,
                "kpi": lab,
                "stored": point["stored"][split][lab],
                "alt": point["alt"][split][lab],
                "free_lo": point["free_lo"][split][lab],
                "free_hi": point["free_hi"][split][lab],
                "min": point.get(f"min|{key}", {}).get(split, {}).get(lab, math.nan),
                "max_found": point.get(f"max|{key}", {})
                .get(split, {})
                .get(lab, math.nan),
                "status_min": statuses[f"min|{key}"],
                "status_max": statuses[f"max|{key}"],
                "max_steps": steps[f"max|{key}"],
                "objective_excess_min": checks.get(f"min|{key}", {}).get(
                    "objective_excess", math.nan
                ),
                "objective_excess_max": checks.get(f"max|{key}", {}).get(
                    "objective_excess", math.nan
                ),
                "alt_objective_excess": checks["alt"]["objective_excess"],
                "rel_tol": RANGE_REL_TOL,
                "config_hash": config_hash(cfg),
                "run_id": rid,
            }
        )
    return {
        "group": (pricing, design, scope),
        "rows": rows,
        "reps": reps,
        "point": point,
        "checks": checks,
        "thetas": {k: v.tolist() for k, v in cand.items()},
        "seconds": round(time.perf_counter() - t0, 1),
    }


def _save_joint(full: Path, out: dict[str, Any]) -> None:
    pricing, design, scope = out["group"]
    stem = f"joint_{pricing}_{design}_{scope}"
    np.savez_compressed(full / "joint" / f"reps_{stem}.npz", **out.pop("reps"))
    (full / "joint" / f"result_{stem}.json").write_text(
        json.dumps(out, indent=1, default=float) + "\n"
    )


def run_joint_ranges(args: argparse.Namespace) -> dict[str, Any]:
    """Phase (e), part 1: range every joint design (kappa 1, pure and r 0.06)."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    from multiprocessing import get_context

    t0 = time.perf_counter()
    (args.full / "joint").mkdir(parents=True, exist_ok=True)
    groups = c1_groups(
        ["main"],
        lambda s: (
            s.variant.kappa == 1.0
            and s.variant.pricing in T6_PRICINGS
            and s.design in T6_DESIGNS
            and s.scope in JOINT_SCOPES
        ),
    )
    tasks = []
    for (_, _, pricing, _, design), members in groups.items():
        for scope, member in members.items():
            label = f"{pricing}|{design}|{scope}"
            if args.only and not any(o in label for o in args.only):
                continue
            stem = f"joint_{pricing}_{design}_{scope}"
            if (args.full / "joint" / f"result_{stem}.json").exists():
                print(f"cached {label}", flush=True)
                continue
            tasks.append((pricing, design, scope, member, str(args.c1_store)))
    with ProcessPoolExecutor(
        max_workers=args.jobs, mp_context=get_context("spawn")
    ) as pool:
        futs = [pool.submit(joint_range_worker, *t) for t in tasks]
        for i, fut in enumerate(as_completed(futs), 1):
            out = fut.result()
            _save_joint(args.full, out)
            print(f"[{i}/{len(futs)}] {out['group']} {out['seconds']}s", flush=True)
    return {
        "joint_ranges_designs": len(tasks),
        "joint_ranges_seconds": round(time.perf_counter() - t0, 1),
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

PHASES: Final[dict[str, Callable[[argparse.Namespace], dict[str, Any]]]] = {
    "inaccurate": run_inaccurate,
    "nonunique": run_nonunique,
    "noise": lambda a: run_sens(a, "noise"),
    "nclusters": lambda a: run_sens(a, "nclusters"),
    "joint_ranges": run_joint_ranges,
}


def main(argv: list[str] | None = None) -> int:
    """Run one phase and write its full tables and summary.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description="C1 RQ2 sensitivities (MAR-206).")
    parser.add_argument("--phase", required=True, choices=sorted(PHASES))
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--c1-store", type=Path, default=C1_STORE)
    parser.add_argument("--full", type=Path, default=FULL_DIR)
    parser.add_argument("--only", nargs="*", default=None, help="subset filter")
    args = parser.parse_args(argv)
    args.full.mkdir(parents=True, exist_ok=True)
    summary = {
        "issue": "MAR-206",
        "phase": args.phase,
        "package_versions": package_versions(),
        **PHASES[args.phase](args),
    }
    (args.full / f"summary_{args.phase}.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(f"wrote {args.full}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
