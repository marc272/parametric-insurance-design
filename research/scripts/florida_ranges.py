r"""MAR-203 (C1-F2): near-optimal ranges of the Florida designs' portfolio KPIs.

The Florida rerun (MAR-202, ``research/notes/florida-rerun.md``) compared
designs across scopes and objectives with **one** member of each design's
optimal set: the one the default solver policy returned. Neither the joint
designs (MAR-100, C1 T11, MAR-206) nor the individual designs (MAR-198) are
unique. This script measures, on the MAR-202 holdout runs (read from the
store, never written to), how far the portfolio-level KPIs move across
equally optimal designs, and recomputes MAR-202's contrasts at the ends.
Observations only; the interpretation is the owner's.

Phases (``--phases``):

``individual``
    MAR-198's free-bin method (a) on every holdout individual design (67
    counties): a county's bin without a train row of its index moves no train
    quantity, so every design that differs from the stored one only there,
    within monotonicity and the cap, is exactly optimal (tolerance 0). The
    portfolio KPIs are non-increasing in every payout parameter, so the
    family's ends are "every free parameter at its highest" (``free_hi``,
    smallest KPI) and "at its lowest" (``free_lo``, largest KPI). For the MSE
    designs the smallest eigenvalue of each county's MSE Hessian on its used
    bins is recorded (positive: the used bins' optimum is unique, and the
    free-bin family is the whole optimal set).

``joint``
    Every holdout cluster and portfolio design:

    * the design problem rebuilt on the train years, with the stored design;
      the stored design's objective recomputed in numpy must equal the stored
      run's (rtol :data:`OBJ_RTOL`);
    * ``alt``: the second optimum, the same problem solved with
      ``c1_rq2.ALT_POLICY`` (HiGHS first for LPs, CLARABEL first for QPs);
      MAR-206 family (b);
    * ``free_lo`` / ``free_hi``: the joint design's free-bin ends (MAR-206
      family (b), exact);
    * with ``--near`` (the groups in :data:`NEAR_GROUPS` by default): each
      portfolio KPI of :data:`KPIS` minimised and maximised over the near-
      optimal set (C1 T11's set: the design problem's feasible set with
      objective <= optimum (1 + 1e-5); the MSE constraint in MAR-206's exact
      compact form), MAR-206 family (e)'s programs: the smallest KPI by one
      convex program, the largest by successive linearisation from the stored
      and the ``alt`` design (an inner bound). LP range programs are solved by
      HiGHS first, then CLARABEL (CLARABEL alone took over 15 min on one
      Florida program that HiGHS solved in 30 s); every end is checked in
      numpy against the set, and an iterate outside it is projected (L-inf)
      and rechecked, as in MAR-198 and MAR-206;
    * with ``--payouts`` (:data:`PAYOUT_GROUPS`): C1 T11's per-entity payout
      ranges, the smallest and largest train ``E[pi_j] / E[L_j]`` of each
      county (portfolio) or cluster over the same set, each end checked.

    The optimum of the set is the smaller of the stored and the ``alt``
    design's objectives (numpy).

``contrasts``
    Per (index, pricing, kappa): every design's candidates (stored, alt,
    free-bin ends, near-optimal ends) on the C1 resample of the holdout test
    years (B 1000, seed 0, the MAR-202 resample), and every MAR-202 contrast
    (``c1_combination.contrasts("main")``) at each variant of its terms
    (:func:`variants`). The stored variant must reproduce MAR-202's
    ``holdout_contrasts.csv`` (value and interval, rtol 1e-6).

Full results go to ``--full`` (``results/florida-ranges/``, not committed);
``--phases tables`` writes the committed CSVs (each under 500 kB) and
``ranges_tables.md`` to ``research/data/florida-rerun/``.

Run from the repository root, with the MAR-202 store in
``results/florida/store`` and its EventSets in ``results/florida/eventsets``::

    uv run python research/scripts/florida_ranges.py --phases individual joint \
        --jobs 3
    uv run python research/scripts/florida_ranges.py --phases contrasts tables

Observations only. The interpretation is the owner's.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import pickle
import time
from collections.abc import Callable, Iterable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from itertools import combinations
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Final

import c1_checkpoint as c1
import c1_combination as comb
import c1_rq2 as rq2
import c1_rq2_sensitivities as sens
import cvxpy as cp
import florida_rerun as fr
import individual_nonuniqueness as inu
import numpy as np
import pandas as pd

from parametric_insurance_design import splits
from parametric_insurance_design.basis import outcome_measure
from parametric_insurance_design.bootstrap import (
    kpi_replicates,
    percentile_interval,
    resample_years,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import ExperimentConfig, config_hash
from parametric_insurance_design.experiment.runner import package_versions
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.solve import solve

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
STORE: Final[Path] = fr.STORE
FULL_DIR: Final[Path] = REPO_ROOT / "results" / "florida-ranges"
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "florida-rerun"
MAR202_FULL: Final[Path] = fr.FULL_DIR

RANGE_REL_TOL: Final[float] = rq2.RANGE_REL_TOL
"""The near-optimal set's tolerance: objective <= optimum (1 + 1e-5), C1 T11."""
OBJ_RTOL: Final[float] = 1e-6
"""The stored design's numpy objective must equal the stored run's."""
JOINT_SCOPES: Final[tuple[str, ...]] = ("cluster", "portfolio")
KPIS: Final[tuple[tuple[str, str, float | None], ...]] = (
    ("test", "expected_uncovered", None),
    ("test", "cvar_uncovered", 0.95),
    ("test", "cvar_uncovered", 0.99),
    ("test", "cvar_uncovered", 0.995),
    ("train", "expected_uncovered", None),
    ("train", "cvar_uncovered", 0.99),
)
"""(split, KPI, KPI beta) ranged over each joint design's near-optimal set."""
LABELS: Final[tuple[str, ...]] = ("eu", "cvar@0.95", "cvar@0.99", "cvar@0.995")
EVAL_BETAS: Final[tuple[float, ...]] = (0.95, 0.99, 0.995)
NEAR_GROUPS: Final[tuple[tuple[str, float], ...]] = (("pure", 1.0),)
"""(pricing, kappa) whose joint designs get near-optimal KPI ranges by default:
holdout, pure pricing, kappa 1 first (MAR-203 orchestrator notes)."""
PAYOUT_GROUPS: Final[tuple[tuple[str, float], ...]] = (("pure", 1.0),)
"""(pricing, kappa) whose joint designs get C1 T11's per-entity payout ranges."""


# --------------------------------------------------------------------------
# The MAR-202 holdout runs
# --------------------------------------------------------------------------

Key = tuple[str, str, float]
"""(index, pricing, kappa)."""
Design = tuple[str, str]
"""(scope, design label)."""


def holdout_groups(
    plan: dict[str, Any],
) -> dict[Key, dict[Design, tuple[ExperimentConfig, str]]]:
    """MAR-202's holdout runs per (index, pricing, kappa): (config, run id)."""
    out: dict[Key, dict[Design, tuple[ExperimentConfig, str]]] = {}
    for r in fr.holdout_runs(plan):
        out.setdefault((r.index, r.pricing, r.kappa), {})[(r.scope, r.design)] = (
            r.config,
            r.run_id,
        )
    return out


def _stem(key: Key, design: Design) -> str:
    index, pricing, kappa = key
    return f"{index}_{pricing}_k{kappa:g}_{design[0]}_{design[1]}"


def _solve_range(prob: cp.Problem, lp: bool) -> str:
    """Solve a range program; return ``"<status> (<solver>)"``.

    LPs: HiGHS, then CLARABEL, then CLARABEL with 2,000 iterations. The MSE
    sets (a second-order cone constraint): CLARABEL, then 2,000 iterations.
    A solver error leaves no iterate (variables reset to None).
    """
    attempts: list[tuple[str, dict[str, Any]]] = []
    if lp:
        attempts.append(("HIGHS", {}))
    attempts += [("CLARABEL", {}), ("CLARABEL", {"max_iter": inu.MAX_ITER})]
    status = "not solved"
    for name, opts in attempts:
        try:
            prob.solve(solver=name, **opts)
            status = f"{prob.status} ({name}{'/long' if opts else ''})"
        except cp.error.SolverError as exc:
            for v in prob.variables():
                v.value = None
            status = f"solver_error ({name}): {str(exc)[:60]}"
            continue
        if prob.status == "optimal":
            return status
    return status


# --------------------------------------------------------------------------
# Data of a design on a split
# --------------------------------------------------------------------------


@dataclasses.dataclass
class SplitRows:
    """A split's rows: portfolio loss, measure, years, and the prepared data."""

    sample: Sample
    data: EventSet
    measure: Any
    loss: np.ndarray
    years: np.ndarray


def split_rows(prepared: EventSet, sample: Sample, cfg: ExperimentConfig) -> SplitRows:
    """Return a split's portfolio loss per row and its outcome measure."""
    comps = cfg.to_components()
    data = sample.select(prepared)
    measure = outcome_measure(data, comps.basis, years=sample.years)
    loss = np.asarray(data.loss, dtype=np.float64).sum(axis=1)
    years = data.events["year"].to_numpy(dtype=np.int64)
    return SplitRows(sample, data, measure, loss, years)


def entity_bases(
    cfg: ExperimentConfig, specs: Sequence[Any], data: EventSet
) -> list[list[np.ndarray]]:
    """Each problem's entities' payout basis matrices on ``data``'s rows."""
    comps = cfg.to_components()
    scope = comps.scopes[0]
    out: list[list[np.ndarray]] = []
    for spec in specs:
        problem = scope.materialise(data, spec)
        out.append(
            [
                comps.payout.basis_matrix(problem.index[:, j])
                for j in range(problem.n_entities)
            ]
        )
    return out


def row_payout(bases: list[list[np.ndarray]], thetas: Sequence[np.ndarray]) -> np.ndarray:
    """Portfolio payout per row: the sum over problems and entities."""
    total: np.ndarray | None = None
    for b_p, th_p in zip(bases, thetas, strict=True):
        th = np.atleast_2d(np.asarray(th_p, dtype=np.float64))
        for j, b in enumerate(b_p):
            part = b @ th[j]
            total = part if total is None else total + part
    if total is None:
        raise RuntimeError("a design without entities")
    return total


def point_kpis(rows: SplitRows, payout: np.ndarray) -> dict[str, float]:
    """Portfolio E[U] and CVaR at :data:`EVAL_BETAS` (the ``evaluate`` definition)."""
    from parametric_insurance_design.riskmeasures import var_cvar

    u = rows.measure.aggregate(np.maximum(0.0, rows.loss - payout))
    p = np.asarray(rows.measure.probability, dtype=np.float64)
    out = {"eu": float(p @ u)}
    for b in EVAL_BETAS:
        out[f"cvar@{b:g}"] = float(var_cvar(u, p, b)[1])
    return out


# --------------------------------------------------------------------------
# Phase individual: MAR-198's free-bin method on the 67 counties
# --------------------------------------------------------------------------


def individual_worker(
    key: Key, design: str, cfg: ExperimentConfig, rid: str, store_root: str
) -> dict[str, Any]:
    """Free-bin ends of one individual design; per-county records.

    Returns
    -------
    dict
        ``thetas`` (candidate -> list of per-county parameter vectors, loss
        units), ``point`` (candidate -> split -> label -> value), ``counties``
        (rows), ``meta``.
    """
    t0 = time.perf_counter()
    store = ResultStore(Path(store_root))
    stored = rq2._stored(cfg, rid, store)
    prepared = c1._prepared(cfg)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    specs = [r.spec for r in stored.results]
    rows = {"train": split_rows(prepared, train, cfg), "test": split_rows(prepared, test, cfg)}
    bases = {s: entity_bases(cfg, specs, rows[s].data) for s in rows}
    scope = cfg.to_components().scopes[0]
    theta = [np.asarray(r.theta, dtype=np.float64)[0] for r in stored.results]
    lo_all, hi_all, counties = [], [], []
    for i, spec in enumerate(specs):
        b_tr = bases["train"][i][0]
        counts = b_tr.sum(axis=0)
        free = inu.free_bins(counts)
        problem = scope.materialise(rows["train"].data, spec)
        cap = float(np.max(problem.entity_loss[:, 0], initial=0.0))
        if np.any(theta[i] > cap * (1 + 1e-6) + 1e-6):
            raise RuntimeError(f"{spec.problem_id}: stored payout above the cap")
        lo, hi = inu.free_bin_bounds(theta[i], free, cap)
        for t in (lo, hi):
            if not np.allclose(b_tr @ t, b_tr @ theta[i], rtol=0, atol=1e-9 * max(cap, 1)):
                raise RuntimeError(f"{spec.problem_id}: a free bin has train rows")
        lo_all.append(lo)
        hi_all.append(hi)
        used = [k for k in range(len(counts)) if k not in set(free)]
        eig = math.nan
        if design == "mse" and used:
            a = rows["train"].measure.aggregate(b_tr[:, used])
            h = a.T @ (a * np.asarray(rows["train"].measure.probability)[:, None])
            w = np.linalg.eigvalsh(h)
            eig = float(w[0] / w[-1]) if w[-1] > 0 else math.nan
        counties.append(
            {
                "county": spec.problem_id,
                "free_bins": " ".join(str(k) for k in free),
                "n_free_bins": len(free),
                "free_bins_test_rows": int(
                    sum(bases["test"][i][0][:, k].sum() for k in free)
                ),
                "free_param_width_to_cap": (
                    float(np.max(hi - lo, initial=0.0)) / cap if cap > 0 else math.nan
                ),
                "cap": cap,
                "mse_hessian_min_eig_rel_used_bins": eig,
            }
        )
    thetas = {"stored": theta, "free_lo": lo_all, "free_hi": hi_all}
    point = {
        name: {s: point_kpis(rows[s], row_payout(bases[s], th)) for s in rows}
        for name, th in thetas.items()
    }
    for s in rows:
        if not math.isclose(
            point["free_lo"][s]["eu"] if s == "test" else point["stored"][s]["eu"],
            point["free_lo"][s]["eu"] if s == "test" else point["free_lo"][s]["eu"],
        ):
            raise RuntimeError("train KPIs of a free-bin end differ")  # pragma: no cover
    return {
        "key": key,
        "design": ("individual", design),
        "thetas": thetas,
        "point": point,
        "counties": counties,
        "meta": {
            "config_hash": config_hash(cfg),
            "run_id": rid,
            "statuses": stored.statuses,
            "solvers": stored.solvers,
            "seconds": round(time.perf_counter() - t0, 1),
        },
    }


# --------------------------------------------------------------------------
# Phase joint: alt, free bins, near-optimal KPI and payout ranges
# --------------------------------------------------------------------------


class StoredSet(sens.JointSet):
    """MAR-206's :class:`JointSet` around a given optimum, without re-solving.

    The default-policy re-solve of the joint design (MAR-206) is replaced by
    a numpy check of the stored design: its objective, recomputed in numpy,
    must equal the stored run's. The set's optimum is the smallest numpy
    objective of the candidate optima given.
    """

    def __init__(  # noqa: PLR0913
        self,
        built: BuiltProblem,
        cfg: ExperimentConfig,
        tol: float,
        optima: dict[str, np.ndarray],
    ) -> None:
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
            sens.dense(self.payout.basis_matrix(problem.index[:, j]))
            for j in range(problem.n_entities)
        ]
        values = {k: self.objective_value(v) for k, v in optima.items()}
        best = min(values, key=lambda k: values[k])
        self.optimum_from = best
        self.optimum_values = values
        self.theta_opt = np.asarray(optima[best], dtype=np.float64).copy()
        self.optimum = values[best]
        self.bound = self.optimum + tol * abs(self.optimum)
        self.constraints = [
            *built.problem.constraints,
            built.objective.expression <= self.bound,
        ]


def _lp_ranger(js: StoredSet, lp: bool) -> sens.JointRanger:
    """MAR-206's ranger with this script's solver order (:func:`_solve_range`)."""
    inu.solve_range = lambda prob: _solve_range(prob, lp)  # type: ignore[assignment]
    return sens.JointRanger(js)


def _objective_units(design: str, scale: float) -> float:
    """Factor from the scaled objective to the stored run's (loss units)."""
    return scale**2 if design == "mse" else scale


def joint_worker(  # noqa: PLR0912, PLR0915
    key: Key,
    design: Design,
    cfg: ExperimentConfig,
    rid: str,
    store_root: str,
    near: bool,
    payouts: bool,
) -> dict[str, Any]:
    """Second optimum, free-bin ends and (optionally) near-optimal ranges.

    Returns
    -------
    dict
        ``thetas`` (candidate -> one parameter matrix, loss units), ``point``
        (candidate -> split -> label -> value), ``checks`` (candidate -> set
        check), ``statuses``, ``entities`` (rows: free bins, payout ratios and
        ranges), ``meta``.
    """
    t0 = time.perf_counter()
    store = ResultStore(Path(store_root))
    stored = rq2._stored(cfg, rid, store)
    comps = cfg.to_components()
    prepared = c1._prepared(cfg)
    train, test = splits.holdout(prepared, train_fraction=0.7)
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
    scale = float(built.context.scale)
    (res,) = stored.results
    theta_stored = np.asarray(res.theta, dtype=np.float64)
    t_alt = time.perf_counter()
    alt = solve(built, rq2.ALT_POLICY, pricing=comps.pricing)
    alt_seconds = time.perf_counter() - t_alt
    if alt.theta is None:
        raise RuntimeError(f"{rid}: the alt solve failed ({alt.status})")
    theta_alt = np.asarray(alt.theta, dtype=np.float64)
    js = StoredSet(
        built,
        cfg,
        RANGE_REL_TOL,
        {"stored": theta_stored / scale, "alt": theta_alt / scale},
    )
    units = _objective_units(design[1], scale)
    stored_numpy = js.optimum_values["stored"] * units
    if not math.isclose(stored_numpy, stored.objective_value, rel_tol=OBJ_RTOL):
        raise RuntimeError(
            f"{rid}: numpy objective {stored_numpy!r} != stored "
            f"{stored.objective_value!r}"
        )
    lo, hi, ents = sens.free_bin_family(js, theta_stored)
    cand: dict[str, np.ndarray] = {
        "stored": theta_stored,
        "alt": theta_alt,
        "free_lo": lo,
        "free_hi": hi,
    }
    statuses: dict[str, str] = {}
    steps: dict[str, int] = {}
    seconds: dict[str, float] = {}
    rows = {"train": split_rows(prepared, train, cfg), "test": split_rows(prepared, test, cfg)}
    lp = design[1] != "mse"
    if near or payouts:
        ranger = _lp_ranger(js, lp)
    if near:
        sd = {
            s: sens.joint_split(js, cfg, prepared, rows[s].sample) for s in ("train", "test")
        }
        for split, kpi, beta in KPIS:
            lab = f"{split}|{sens.klabel(kpi, beta)}"
            t = time.perf_counter()
            ref = sd[split].value(list(theta_stored), kpi, beta)
            th, st = ranger.minimise_kpi(sd[split], beta, ref)
            statuses[f"min|{lab}"] = st
            if th is not None:
                cand[f"min|{lab}"] = th * scale
            best: tuple[float, np.ndarray | None, int, str] = (-math.inf, None, 0, "")
            for start in ("stored", "alt"):
                th, n, st = ranger.maximise_kpi(sd[split], kpi, beta, cand[start] / scale)
                if th is None:
                    if best[1] is None:
                        best = (-math.inf, None, n, f"{start}: {st}")
                    continue
                v = sd[split].value(list(th * scale), kpi, beta)
                if v > best[0]:
                    best = (v, th, n, f"{start}: {st}")
            statuses[f"max|{lab}"] = best[3]
            steps[f"max|{lab}"] = best[2]
            if best[1] is not None:
                cand[f"max|{lab}"] = best[1] * scale
            seconds[lab] = round(time.perf_counter() - t, 1)
            print(
                f"[joint] {_stem(key, design)} {lab}: {statuses[f'min|{lab}']} / "
                f"{best[3]} ({seconds[lab]:.0f}s)",
                flush=True,
            )
    # per-entity payout ratios of every candidate, and C1 T11's ranges
    m = js.ctx.measure
    p = np.asarray(m.probability, dtype=np.float64)
    ratio_cost = [np.asarray(m.aggregate(b)).T @ p for b in js.basis]
    entity_rows: list[dict[str, Any]] = []
    for j, e in enumerate(ents):
        row = dict(e)
        for name in ("stored", "alt", "free_lo", "free_hi"):
            row[f"ratio_{name}"] = js.entity_ratio(cand[name] / scale, j)
        row["train_expected_loss"] = float(
            m.expectation(js.ctx.entity_loss[:, j]) * scale
        )
        entity_rows.append(row)
    if payouts:
        t = time.perf_counter()
        for j, row in enumerate(entity_rows):
            for sense, sign in (("min", 1.0), ("max", -1.0)):
                c = np.zeros(ranger.cost.shape)
                c[j] = sign * ratio_cost[j]
                top = float(np.max(np.abs(c), initial=0.0))
                ranger.cost.value = c / top if top > 0 else c
                js.ctx.theta.value = None
                st = _solve_range(ranger.lp, lp)
                raw = ranger._theta()
                th, note = (None, "no iterate") if raw is None else ranger.admit(raw)
                row[f"status_{sense}"] = f"{st} {note}".strip()
                row[f"ratio_{sense}"] = (
                    math.nan if th is None else js.entity_ratio(th, j)
                )
        seconds["payouts"] = round(time.perf_counter() - t, 1)
        print(f"[joint] {_stem(key, design)} payouts ({seconds['payouts']:.0f}s)", flush=True)
    checks = {name: js.check(th / scale) for name, th in cand.items()}
    bases = {s: entity_bases(cfg, [res.spec], rows[s].data) for s in rows}
    point = {
        name: {s: point_kpis(rows[s], row_payout(bases[s], [th])) for s in rows}
        for name, th in cand.items()
    }
    return {
        "key": key,
        "design": design,
        "thetas": cand,
        "point": point,
        "checks": checks,
        "statuses": statuses,
        "steps": steps,
        "entities": entity_rows,
        "meta": {
            "config_hash": config_hash(cfg),
            "run_id": rid,
            "statuses": stored.statuses,
            "solvers": stored.solvers,
            "stored_objective": stored.objective_value,
            "alt_solver": alt.solver,
            "alt_status": str(alt.status.value),
            "alt_seconds": round(alt_seconds, 1),
            "optimum_from": js.optimum_from,
            "objective_stored": js.optimum_values["stored"] * units,
            "objective_alt": js.optimum_values["alt"] * units,
            "rel_tol": RANGE_REL_TOL,
            "near": near,
            "payouts": payouts,
            "seconds": round(time.perf_counter() - t0, 1),
            "range_seconds": seconds,
        },
    }


# --------------------------------------------------------------------------
# Running the workers
# --------------------------------------------------------------------------


def _run_pool(
    tasks: list[tuple[str, Callable[..., dict[str, Any]], tuple[Any, ...]]],
    out_dir: Path,
    jobs: int,
) -> list[str]:
    """Run ``fn(*args)`` per task in ``jobs`` processes; pickle each result.

    A task whose pickle exists is skipped. Failures are recorded (and raised
    after the others end): nothing is dropped silently.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    todo = [t for t in tasks if not (out_dir / f"{t[0]}.pkl").is_file()]
    print(f"{len(tasks)} tasks, {len(todo)} to run", flush=True)
    failed: list[str] = []
    queue = list(reversed(todo))
    with ProcessPoolExecutor(max_workers=jobs, mp_context=get_context("spawn")) as pool:
        running: dict[Future[Any], str] = {}

        def fill() -> None:
            while queue and len(running) < jobs:
                name, fn, args = queue.pop()
                running[pool.submit(fn, *args)] = name

        fill()
        done = 0
        while running:
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for fut in finished:
                name = running.pop(fut)
                done += 1
                try:
                    out = fut.result()
                except Exception as exc:  # recorded, raised after the others end
                    failed.append(f"{name}: {exc!r}")
                    print(f"[{done}/{len(todo)}] FAILED {name}: {exc!r}", flush=True)
                    continue
                tmp = out_dir / f"{name}.tmp"
                tmp.write_bytes(pickle.dumps(out))
                tmp.replace(out_dir / f"{name}.pkl")
                sec = out["meta"]["seconds"]
                print(f"[{done}/{len(todo)}] {name} {sec:.0f}s", flush=True)
            fill()
    return failed


def _selected(key: Key, only: Sequence[str] | None) -> bool:
    label = "|".join(f"{x:g}" if isinstance(x, float) else str(x) for x in key)
    return not only or any(o in label for o in only)


def run_individual(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase individual: free-bin ends of every holdout individual design."""
    tasks = []
    for key, members in holdout_groups(plan).items():
        if not _selected(key, args.only):
            continue
        for (scope, design), (cfg, rid) in members.items():
            if scope != "individual":
                continue
            tasks.append(
                (
                    _stem(key, (scope, design)),
                    individual_worker,
                    (key, design, cfg, rid, str(args.store)),
                )
            )
    failed = _run_pool(tasks, args.full / "individual", args.jobs)
    if failed:
        raise RuntimeError("failed:\n" + "\n".join(failed))
    return {"individual_designs": len(tasks)}


def _cost(task: tuple[str, Any, tuple[Any, ...]]) -> tuple[int, int, int]:
    """Longest first: near-optimal ranges, index (b), portfolio, CoC."""
    key, design = task[2][0], task[2][1]
    near, payouts = task[2][5], task[2][6]
    return (
        -(int(near) + 2 * int(payouts)),
        0 if key[0] == "cic75" else 1,
        0 if design[0] == "portfolio" else 1,
    )


def run_joint(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase joint: every holdout cluster and portfolio design."""
    near_groups = {(p, float(k)) for p, k in args.near}
    payout_groups = {(p, float(k)) for p, k in args.payouts}
    tasks = []
    for key, members in holdout_groups(plan).items():
        if not _selected(key, args.only):
            continue
        for (scope, design), (cfg, rid) in members.items():
            if scope not in JOINT_SCOPES:
                continue
            near = (key[1], key[2]) in near_groups
            payouts = (key[1], key[2]) in payout_groups
            if args.near_scopes and scope not in args.near_scopes:
                near = payouts = False
            stem = _stem(key, (scope, design))
            tasks.append(
                (
                    stem,
                    joint_worker,
                    (key, (scope, design), cfg, rid, str(args.store), near, payouts),
                )
            )
    tasks.sort(key=_cost)
    failed = _run_pool(tasks, args.full / "joint", args.jobs)
    if failed:
        raise RuntimeError("failed:\n" + "\n".join(failed))
    return {"joint_designs": len(tasks)}


# --------------------------------------------------------------------------
# Phase contrasts
# --------------------------------------------------------------------------


def load_results(full: Path) -> dict[tuple[Key, Design], dict[str, Any]]:
    """Every pickled individual and joint result, by (group, design)."""
    out: dict[tuple[Key, Design], dict[str, Any]] = {}
    for sub in ("individual", "joint"):
        for path in sorted((full / sub).glob("*.pkl")):
            r = pickle.loads(path.read_bytes())
            out[(tuple(r["key"]), tuple(r["design"]))] = r  # type: ignore[index]
    return out


SIGN: Final[dict[str, float]] = {"a": 1.0, "b": -1.0, "c": -1.0, "d": 1.0}
"""Sign of each term in ``a - b`` or ``(a - b) - (c - d)``."""


def _end(r: dict[str, Any], low: bool, sign: float, lab: str, near: bool) -> str:
    """Candidate of a design that lowers (``low``) a contrast's term."""
    want_small = (sign > 0) == low  # a + term lowers the contrast if small
    if near and r["design"][0] in JOINT_SCOPES:
        name = f"{'min' if want_small else 'max'}|test|{lab}"
        if name in r["thetas"]:
            return name
        return "MISSING:" + name
    return "free_hi" if want_small else "free_lo"


def variants(
    c: comb.Contrast,
    res: dict[Design, dict[str, Any]],
    lab: str,
) -> dict[str, dict[str, str]]:
    """Each variant of a contrast: term letter -> candidate name.

    ``stored``; ``alt`` (every joint term at its second optimum) and, for a
    contrast with two joint terms, ``alt:<letter>`` (only that term);
    ``free_low`` / ``free_high`` (every term at the free-bin end that lowers
    / raises the contrast), and the same with only the joint terms
    (``free_*_joint``) or only the individual terms (``free_*_individual``);
    ``near_low`` / ``near_high`` (joint terms at their near-optimal ends for
    the KPI, individual terms at their free-bin ends) and ``near_*_joint``
    (individual terms stored), where every joint term has near-optimal ends.
    """
    terms = dict(zip("abcd", c.terms, strict=False))
    joint = [t for t, d in terms.items() if d[0] in JOINT_SCOPES]
    ind = [t for t, d in terms.items() if d[0] not in JOINT_SCOPES]
    base = dict.fromkeys(terms, "stored")
    out: dict[str, dict[str, str]] = {"stored": dict(base)}
    if joint:
        out["alt"] = {**base, **dict.fromkeys(joint, "alt")}
        if len(joint) > 1:
            for t in joint:
                out[f"alt:{t}"] = {**base, t: "alt"}
    for side, low in (("low", True), ("high", False)):
        ends = {t: _end(res[d], low, SIGN[t], lab, near=False) for t, d in terms.items()}
        out[f"free_{side}"] = ends
        if joint and ind:
            out[f"free_{side}_joint"] = {**base, **{t: ends[t] for t in joint}}
            out[f"free_{side}_individual"] = {**base, **{t: ends[t] for t in ind}}
        if joint and all(res[terms[t]]["meta"].get("near") for t in joint):
            near = {t: _end(res[d], low, SIGN[t], lab, near=True) for t, d in terms.items()}
            out[f"near_{side}"] = near
            if ind:
                out[f"near_{side}_joint"] = {**base, **{t: near[t] for t in joint}}
    return out


def _verdict(value: float, lo: float, hi: float) -> str:
    if lo > 0:
        return "above zero"
    if hi < 0:
        return "below zero"
    return "contains zero"


def contrast_group(  # noqa: PLR0914
    key: Key,
    members: dict[Design, tuple[ExperimentConfig, str]],
    res: dict[Design, dict[str, Any]],
) -> dict[str, pd.DataFrame]:
    """Every MAR-202 contrast of one group at every variant (test, paired)."""
    t0 = time.perf_counter()
    cfg0 = members[("individual", "mse")][0]
    prepared = c1._prepared(cfg0)
    _, test = splits.holdout(prepared, train_fraction=0.7)
    rows = split_rows(prepared, test, cfg0)
    assert cfg0.bootstrap is not None
    resample = resample_years(test.years, cfg0.bootstrap.n_bootstrap, cfg0.bootstrap.rng())
    level = float(cfg0.bootstrap.level)
    reps: dict[tuple[Design, str], dict[str, np.ndarray]] = {}
    point: dict[tuple[Design, str], dict[str, float]] = {}
    bases: dict[Design, list[list[np.ndarray]]] = {}

    def get(d: Design, cand: str) -> tuple[dict[str, float], dict[str, np.ndarray]]:
        if (d, cand) not in reps:
            r = res[d]
            if cand not in r["thetas"]:
                raise KeyError(cand)
            if d not in bases:
                specs = [x.spec for x in rq2._stored(*members[d], STORE_REF[0]).results]
                bases[d] = entity_bases(members[d][0], specs, rows.data)
            th = r["thetas"][cand]
            th_list = th if d[0] == "individual" else [th]
            pay = row_payout(bases[d], th_list)
            out: dict[str, np.ndarray] = {}
            for b in EVAL_BETAS:
                k = kpi_replicates(rows.loss, pay, rows.measure, rows.years, resample, beta=b)
                out[f"cvar@{b:g}"] = np.asarray(k["cvar_uncovered"])
                out["eu"] = np.asarray(k["expected_uncovered"])
            reps[(d, cand)] = out
            point[(d, cand)] = point_kpis(rows, pay)
        return point[(d, cand)], reps[(d, cand)]

    hashes = {d: config_hash(members[d][0]) for d in members}
    out_rows: list[dict[str, Any]] = []
    for c in comb.contrasts("main"):
        terms = dict(zip("abcd", c.terms, strict=False))
        for lab in LABELS:
            kpi = "expected_uncovered" if lab == "eu" else "cvar_uncovered"
            beta = math.nan if lab == "eu" else float(lab.split("@")[1])
            ref = get(c.reference, "stored")[0][lab]
            for vname, choice in variants(c, res, lab).items():
                missing = [x for x in choice.values() if x.startswith("MISSING")]
                if missing:
                    out_rows.append(
                        {"variant": vname, "missing": ";".join(missing)}
                        | _ids(key, c, kpi, beta)
                    )
                    continue
                value = 0.0
                rep = np.zeros(resample.n_bootstrap)
                for t, d in terms.items():
                    pv, rv = get(d, choice[t])
                    value += SIGN[t] * pv[lab]
                    rep = rep + SIGN[t] * rv[lab]
                lo, hi = percentile_interval(rep, level)
                out_rows.append(
                    _ids(key, c, kpi, beta)
                    | {
                        "variant": vname,
                        "candidates": " ".join(f"{t}={choice[t]}" for t in terms),
                        "value": value,
                        "ci_low": lo,
                        "ci_high": hi,
                        "value_ref": ref,
                        "verdict": _verdict(value, lo, hi),
                        "missing": "",
                        **{f"hash_{t}": hashes[d][7:19] for t, d in terms.items()},
                    }
                )
    print(f"[contrasts] {key} {time.perf_counter() - t0:.0f}s", flush=True)
    return {"contrasts": pd.DataFrame(out_rows)}


STORE_REF: list[ResultStore] = []


def _ids(key: Key, c: comb.Contrast, kpi: str, beta: float) -> dict[str, Any]:
    return {
        "eventset": key[0],
        "pricing": key[1],
        "kappa": key[2],
        "contrast": c.name,
        "joint_scope": c.joint_scope,
        "tail_design": c.tail_design,
        "base_design": c.base_design,
        "kpi": kpi,
        "eval_beta": beta,
    }


def _contrast_task(
    key: Key, members: dict[Design, tuple[ExperimentConfig, str]], full: str, store: str
) -> dict[str, Any]:
    STORE_REF[:] = [ResultStore(Path(store))]
    allres = load_results(Path(full))
    res = {d: allres[(key, d)] for d in members if (key, d) in allres}
    if len(res) != len(members):
        missing = sorted(set(members) - set(res))
        raise RuntimeError(f"{key}: no ranges for {missing}")
    t0 = time.perf_counter()
    out = contrast_group(key, members, res)
    out["meta"] = {"seconds": round(time.perf_counter() - t0, 1)}  # type: ignore[assignment]
    return out  # type: ignore[return-value]


def check_stored(con: pd.DataFrame, mar202: pd.DataFrame) -> int:
    """Raise unless the stored variant reproduces MAR-202's test contrasts."""
    mine = con.loc[con["variant"] == "stored"].copy()
    theirs = mar202.loc[mar202["split"] == "test"].copy()
    keys = [
        "eventset",
        "pricing",
        "kappa",
        "contrast",
        "joint_scope",
        "tail_design",
        "base_design",
        "kpi",
        "eval_beta",
    ]
    for f in (mine, theirs):
        for k in ("joint_scope", "tail_design", "base_design"):
            f[k] = f[k].fillna("").astype(str)
        f["eval_beta"] = f["eval_beta"].fillna(-1.0)
    theirs = theirs.loc[theirs["kpi"].isin(["expected_uncovered", "cvar_uncovered"])]
    theirs = theirs.drop_duplicates(keys)
    m = mine.merge(theirs, on=keys, suffixes=("", "_202"), validate="one_to_one")
    if len(m) != len(mine):
        raise RuntimeError(f"{len(mine) - len(m)} stored rows have no MAR-202 row")
    for col in ("value", "ci_low", "ci_high"):
        ok = np.isclose(m[col], m[f"{col}_202"], rtol=1e-6, atol=1.0)
        if not ok.all():
            bad = m.loc[~ok].iloc[0]
            raise RuntimeError(f"{col} differs from MAR-202: {bad.to_dict()}")
    return len(m)


def run_contrasts(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase contrasts: every group's MAR-202 contrasts at every variant."""
    groups = holdout_groups(plan)
    avail = load_results(args.full)
    tasks = []
    for key, members in groups.items():
        if not _selected(key, args.only):
            continue
        if not all((key, d) in avail for d in members):
            print(f"[contrasts] skip {key}: not every design ranged", flush=True)
            continue
        name = "contrasts_" + "_".join(f"{x:g}" if isinstance(x, float) else x for x in key)
        tasks.append((name, _contrast_task, (key, members, str(args.full), str(args.store))))
    cache = args.full / "contrast_groups"
    for t in tasks:  # a group is recomputed whenever its inputs may have changed
        (cache / f"{t[0]}.pkl").unlink(missing_ok=True)
    failed = _run_pool(tasks, cache, args.jobs)
    if failed:
        raise RuntimeError("failed:\n" + "\n".join(failed))
    frames = [pickle.loads(p.read_bytes())["contrasts"] for p in sorted(cache.glob("*.pkl"))]
    con = pd.concat(frames, ignore_index=True)
    mar202 = pd.read_csv(MAR202_FULL / "holdout_contrasts.csv")
    n = check_stored(con, mar202)
    con.to_csv(args.full / "contrasts.csv", index=False, float_format="%.10g")
    print(f"[contrasts] {n} stored rows equal MAR-202's", flush=True)
    return {"contrast_groups": len(frames), "contrast_rows_checked_against_mar202": n}


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def _pairs(values: Iterable[str]) -> list[tuple[str, float]]:
    out = []
    for v in values:
        p, k = v.split(":")
        out.append((p, float(k)))
    return out


def main(argv: list[str] | None = None) -> int:
    """Run the requested phases and write a summary per phase.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description="Florida near-optimal ranges (MAR-203).")
    parser.add_argument(
        "--phases",
        nargs="+",
        required=True,
        choices=["individual", "joint", "contrasts", "tables"],
    )
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--full", type=Path, default=FULL_DIR)
    parser.add_argument("--plan", type=Path, default=fr.PLAN)
    parser.add_argument("--only", nargs="*", default=None, help="group label filter")
    parser.add_argument(
        "--near",
        nargs="*",
        default=[f"{p}:{k:g}" for p, k in NEAR_GROUPS],
        help="pricing:kappa groups with near-optimal KPI ranges",
    )
    parser.add_argument(
        "--payouts",
        nargs="*",
        default=[f"{p}:{k:g}" for p, k in PAYOUT_GROUPS],
        help="pricing:kappa groups with per-entity payout ranges",
    )
    parser.add_argument(
        "--near-scopes", nargs="*", default=None, help="limit ranges to these scopes"
    )
    args = parser.parse_args(argv)
    args.near = _pairs(args.near)
    args.payouts = _pairs(args.payouts)
    plan = fr.load_plan(args.plan)
    args.full.mkdir(parents=True, exist_ok=True)
    runners: dict[str, Callable[[argparse.Namespace, dict[str, Any]], dict[str, Any]]] = {
        "individual": run_individual,
        "joint": run_joint,
        "contrasts": run_contrasts,
    }
    for name in ("individual", "joint", "contrasts", "tables"):
        if name not in args.phases:
            continue
        t = time.perf_counter()
        if name == "tables":
            import florida_ranges_tables

            summary = florida_ranges_tables.write(args.full, OUT_DIR)
        else:
            summary = runners[name](args, plan)
        summary = {
            "issue": "MAR-203",
            "package_versions": package_versions(),
            **summary,
            "phase_seconds": round(time.perf_counter() - t, 1),
        }
        (args.full / f"summary_{name}.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
        print(f"phase {name} done in {summary['phase_seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
