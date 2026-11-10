r"""MAR-224: solver checks after the Florida rerun (MAR-202).

The Florida rerun (``research/notes/florida-rerun.md``, T14) found two MSE
designs that OSQP stored with status ``optimal``, a zero payout and an
objective 66-67 % above a CLARABEL re-solve, and slow and
``optimal_inaccurate`` solves on index (b), cat-in-a-circle at 75 km. This
script reproduces, profiles and checks them. It never writes to a result
store and never changes ``solve.py``: the solve policy is the owner's call
(``research/notes/solver-check.md``).

Phases (``--phases``):

``attempts``
    Reads every manifest of the Florida result store (``--florida-store``,
    read only) and tabulates the solver attempts of every design problem:
    the solvers tried under ``solve.DEFAULT_POLICY``, their statuses and
    seconds, and the accepted solver's iteration count. Writes
    ``attempts.csv`` (one row per run) to the data directory.
``florida``
    The two non-optimal designs of T14 (index (b), k-fold, pure, kappa 1,
    portfolio MSE, folds 0 and 4), each rebuilt from its config and solved
    afresh (a new cvxpy problem per variant, so nothing is warm-started) by
    OSQP with the default policy's options, OSQP with polishing off, OSQP at
    cvxpy's defaults (``THESIS_POLICY``), CLARABEL at its defaults and
    CLARABEL at :data:`REFERENCE_POLICY`'s tolerances. Records OSQP's
    ``status_polish`` and whether the returned payout parameters are all
    zero. Writes ``florida_osqp.csv``; ``--florida-variants`` reruns some
    variants and keeps the other rows.
``thesis``
    Every MSE design of the committed thesis-portfolio configs (parity, C1,
    the site), rebuilt from its config (:func:`thesis_designs`; set
    ``C1_EVENTSETS`` to the F-12 EventSets). Every QP design is solved three
    times, each on a freshly built problem: with ``solve.DEFAULT_POLICY``,
    with ``solve.THESIS_POLICY`` and with CLARABEL at tight tolerances
    (:data:`REFERENCE_POLICY`); the objectives are compared, and OSQP's
    polish status is recorded for every problem OSQP solved. A design that
    fails to build is recorded with its error. Rows are also appended to
    ``results/mar224/thesis_rows.jsonl``; ``--resume`` keeps them. Writes
    ``thesis_mse.csv``.
``profile``
    Index (b) against index (a) on the slowest Florida family, the
    individual scope under cost of capital (r 0.06, kappa 0.5), E[U] and
    MSE: for a few counties, the problem size, CLARABEL's iterations and
    status, and the conditioning of the data (loss scale, distinct index
    values per bin, distinct yearly payout patterns). Writes
    ``profile.csv``.
``inaccurate``
    Problems the Florida store holds with status ``optimal_inaccurate``,
    re-solved with CLARABEL at its default settings (the stored solve),
    CLARABEL with more iterations, HiGHS, and CLARABEL on a problem built
    with a tenth of the default loss scale; the objective and payout of each
    are compared with the stored ones. Writes ``inaccurate.csv``.
``stores``
    Scans result stores (``--scan-store LABEL=PATH``, repeatable, read only)
    for problems stored by OSQP with an all-zero payout, the signature of
    OSQP's polish failure. Writes ``stores.csv``. Not a default phase.

Committed tables go to ``research/data/solver-check/`` (each < 500 kB);
logs to ``results/mar224/``. Run from the repository root, with the Florida
EventSets where the Florida base configs expect them
(``results/florida/eventsets``)::

    C1_EVENTSETS=<F-12 EventSets> uv run python \
        research/scripts/solver_check.py --jobs 2 \
        --phases attempts thesis florida profile inaccurate \
        --florida-store <MAR-202 worktree>/results/florida/store
    uv run python research/scripts/solver_check.py --phases stores \
        --scan-store florida=<Florida store> --scan-store c1=<C1 store> ...

Observations only. The interpretation is the owner's.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Final

import c1_checkpoint as c1
import c1_rq2 as rq2
import c1_rq2_sensitivities as rqs
import cvxpy as cp
import florida_rerun as fr
import numpy as np
import pandas as pd

from parametric_insurance_design.basis import outcome_measure
from parametric_insurance_design.errors import ParametricInsuranceDesignError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.runner import (
    _samples,
    load_input,
    package_versions,
    prepare_eventset,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.experiment.sweeps import sweep_points
from parametric_insurance_design.problem import (
    BuiltProblem,
    _assemble,
    _default_scale,
    build_context,
    build_problems,
)
from parametric_insurance_design.solve import (
    DEFAULT_POLICY,
    OSQP_OPTIONS,
    THESIS_POLICY,
    SolverPolicy,
    is_qp,
    solve,
)

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "solver-check"
LOG_DIR: Final[Path] = REPO_ROOT / "results" / "mar224"
FLORIDA_STORE: Final[Path] = REPO_ROOT / "results" / "florida" / "store"
PARITY_CONFIG: Final[Path] = REPO_ROOT / "parity" / "configs" / "thesis.yaml"
SITE_CONFIG: Final[Path] = REPO_ROOT / "site" / "configs" / "explorer.yaml"
F12_EVENTSETS: Final[Path] = Path(
    os.environ.get("C1_EVENTSETS", REPO_ROOT / "results" / "c1" / "eventsets")
)

GAP: Final[float] = 1e-3
"""Relative objective gap above which a design counts as not optimal (T14)."""

REFERENCE_POLICY: Final[SolverPolicy] = SolverPolicy(
    lp_solvers=("CLARABEL",),
    qp_solvers=("CLARABEL",),
    solver_options={
        "CLARABEL": {
            "tol_gap_abs": 1e-10,
            "tol_gap_rel": 1e-10,
            "tol_feas": 1e-10,
            "max_iter": 500,
        }
    },
)
"""CLARABEL alone at tight tolerances: the reference optimum of a design."""

POLISH_STATUS: Final[dict[int, str]] = {
    -2: "linsys_error",
    -1: "failed",
    0: "not_performed",
    1: "success",
    2: "no_active_set",
}
"""OSQP 1.x ``info.status_polish`` codes (``osqp_api_constants.h``)."""

T14_HASHES: Final[tuple[str, ...]] = ("5318734bca7e", "8dd6c28a7ed9")
"""The two non-optimal Florida designs of MAR-202 T14 (config hash prefixes)."""

PROFILE_COUNTIES: Final[tuple[str, ...]] = (
    "12003",
    "12081",
    "12107",
    "12001",
    "12015",
    "12099",
)
"""Counties profiled: three inaccurate and three optimal in index (b)'s E[U]."""

INACCURATE_MAX: Final[int] = 12
"""At most this many ``optimal_inaccurate`` problems are re-solved."""


# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------

_PREPARED: dict[str, EventSet] = {}


def short(h: str) -> str:
    """First 12 hex digits of a ``sha256:`` hash (or a ``derived:`` id).

    Parameters
    ----------
    h : str
        The hash.

    Returns
    -------
    str
        The prefix.
    """
    return h.split(":", 1)[-1][:12]


def prepared(config: ExperimentConfig) -> EventSet:
    """Return the run's prepared EventSet, cached per process.

    Parameters
    ----------
    config : ExperimentConfig
        A single-run config.

    Returns
    -------
    EventSet
        ``runner.prepare_eventset`` of the config's input.
    """
    d = config.model_dump(mode="json")
    key = json.dumps(
        [str(config.eventset.path), d["noise"], d["threshold"], d["portfolio"]],
        sort_keys=True,
    )
    if key not in _PREPARED:
        _PREPARED[key] = prepare_eventset(config, load_input(config).eventset)
    return _PREPARED[key]


def build(config: ExperimentConfig) -> list[Any]:
    """Build a single run's design problems as the runner does.

    Parameters
    ----------
    config : ExperimentConfig
        A single-run config (one scope, one objective).

    Returns
    -------
    list of BuiltProblem
        Fresh problems: nothing is warm-started from an earlier solve.
    """
    data = prepared(config)
    train, _ = _samples(config, data)
    comps = config.to_components()
    built = build_problems(
        data,
        comps.scopes[0],
        comps.payout,
        comps.objectives[0],
        comps.pricing,
        comps.constraints,
        basis=comps.basis,
        sample=train,
    )
    return list(built)


def build_scaled(config: ExperimentConfig, problem_id: str, factor: float) -> Any:  # noqa: ANN401
    """Build one design problem with ``factor`` times the default loss scale.

    The same steps as ``problem.build_problems`` for one problem, with
    ``problem.build_context(..., scale=...)``; the objective in loss units
    does not depend on the scale.

    Parameters
    ----------
    config : ExperimentConfig
        A single-run config.
    problem_id : str
        The problem.
    factor : float
        Multiplier of the default scale (the largest objective-level loss).

    Returns
    -------
    BuiltProblem
        The problem.
    """
    data = prepared(config)
    train, _ = _samples(config, data)
    comps = config.to_components()
    rows = train.select(data)
    measure = outcome_measure(rows, comps.basis, years=train.years)
    (spec,) = [s for s in comps.scopes[0].partition(rows) if s.problem_id == problem_id]
    problem = comps.scopes[0].materialise(rows, spec)
    ctx = build_context(
        problem,
        comps.payout,
        measure,
        scale=_default_scale(problem) * factor,
    )
    term, premium, cvx_problem = _assemble(
        ctx, comps.objectives[0], comps.pricing, comps.constraints
    )
    return BuiltProblem(
        context=ctx,
        objective=term,
        premium=premium,
        problem=cvx_problem,
        build_seconds=0.0,
        pricing=comps.pricing,
    )


def osqp_info(built: BuiltProblem) -> dict[str, Any]:
    """OSQP's own record of the last solve of a problem.

    Parameters
    ----------
    built : BuiltProblem
        A problem whose last solve was by OSQP.

    Returns
    -------
    dict
        ``status_polish`` (code and name), iterations, OSQP's status and
        objective, and whether the returned primal vector is all zero.
    """
    stats = built.problem.solver_stats
    extra = stats.extra_stats if stats is not None else None
    info = getattr(extra, "info", None)
    if info is None:
        return {}
    x = np.asarray(extra.x)
    return {
        "status_polish": int(info.status_polish),
        "polish": POLISH_STATUS.get(int(info.status_polish), str(info.status_polish)),
        "osqp_status": str(info.status),
        "osqp_iter": int(info.iter),
        "osqp_obj_val": float(info.obj_val),
        "osqp_x_zero": bool(not np.any(x)),
    }


def solver_record(built: BuiltProblem) -> dict[str, Any]:
    """Return the status, iterations and solve time cvxpy records.

    cvxpy keeps no CLARABEL or HiGHS solution object (``extra_stats`` is
    None for them), so this is what there is: the status, the iteration count
    (CLARABEL: interior-point iterations, default limit 200; HiGHS: simplex
    or IPM iterations) and the solver's own time.

    Parameters
    ----------
    built : BuiltProblem
        A solved problem.

    Returns
    -------
    dict
        ``solver_status``, ``solver_iter``, ``solver_time``.
    """
    stats = built.problem.solver_stats
    iters = getattr(stats, "num_iters", None) if stats is not None else None
    seconds = getattr(stats, "solve_time", None) if stats is not None else None
    return {
        "solver_status": str(built.problem.status),
        "solver_iter": int(iters) if iters is not None else np.nan,
        "solver_time": float(seconds) if seconds is not None else np.nan,
    }


def recorded_hashes() -> set[str]:
    """Every ``sha256:`` config hash in a committed research table.

    Returns
    -------
    set of str
        The hashes (full, with the prefix).
    """
    pattern = re.compile(r"sha256:[0-9a-f]{64}")
    out: set[str] = set()
    for path in (REPO_ROOT / "research" / "data").rglob("*.csv"):
        if "solver-check" in path.parts:
            continue
        out.update(pattern.findall(path.read_text(encoding="utf-8")))
    return out


def _pool(jobs: int) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(max_workers=jobs, mp_context=get_context("spawn"))


def _write(frame: pd.DataFrame, name: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    frame.to_csv(path, index=False, float_format="%.10g")
    size = path.stat().st_size
    if size >= 500_000:
        raise RuntimeError(f"{path} is {size} bytes, over the 500 kB limit")
    print(f"wrote {path.relative_to(REPO_ROOT)} ({len(frame)} rows)", flush=True)
    return path


def _map(
    fn: Callable[..., dict[str, Any]], items: Iterable[Any], jobs: int
) -> Iterator[dict[str, Any]]:
    items = list(items)
    if jobs <= 1:
        for item in items:
            yield fn(item)
        return
    with _pool(jobs) as pool:
        futs = [pool.submit(fn, item) for item in items]
        for fut in as_completed(futs):
            yield fut.result()


# --------------------------------------------------------------------------
# Phase attempts: the Florida store's solver attempts
# --------------------------------------------------------------------------


def run_attempts(args: argparse.Namespace) -> dict[str, Any]:
    """Tabulate every solver attempt in the Florida store's manifests.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments (``florida_store``).

    Returns
    -------
    dict
        Summary entries.
    """
    runs = pd.read_csv(REPO_ROOT / "research" / "data" / "florida-rerun" / "runs.csv")
    runs = runs[runs["run_id"].str.startswith("sha256:")]
    rows: list[dict[str, Any]] = []
    for r in runs.itertuples():
        path = Path(args.florida_store) / "manifests" / f"{short(r.run_id)}*"
        (manifest_path,) = list(path.parent.glob(path.name))
        manifest = json.loads(manifest_path.read_text())
        attempts = [
            (a["solver"], a["status"], float(a["seconds"]))
            for p in manifest["problems"]
            for a in p["attempts"]
        ]
        accepted = [p for p in manifest["problems"] if p["status"] is not None]
        iters = [
            p["diagnostics"].get("solver_num_iters")
            for p in accepted
            if p.get("diagnostics")
        ]
        iters = [i for i in iters if i is not None]
        row: dict[str, Any] = {
            "kind": r.kind,
            "eventset": r.eventset,
            "pricing": r.pricing,
            "kappa": r.kappa,
            "scope": r.scope,
            "design": r.design,
            "fold": r.fold,
            "n_problems": len(manifest["problems"]),
            "seconds_total": sum(s for _, _, s in attempts),
        }
        for solver in ("OSQP", "CLARABEL", "HIGHS", "SCS"):
            mine = [(st, s) for sv, st, s in attempts if sv == solver]
            row[f"{solver.lower()}_attempts"] = len(mine)
            row[f"{solver.lower()}_seconds"] = sum(s for _, s in mine)
            row[f"{solver.lower()}_statuses"] = ",".join(
                f"{st}:{n}"
                for st, n in sorted(
                    pd.Series([st for st, _ in mine]).value_counts().items()
                )
            )
        failed = [
            s
            for p in manifest["problems"]
            for a, s in ((a, float(a["seconds"])) for a in p["attempts"])
            if a["status"] not in ("optimal", "optimal_inaccurate")
        ]
        row["seconds_failed_attempts"] = sum(failed)
        row["accepted_solvers"] = ",".join(sorted({str(p["solver"]) for p in accepted}))
        row["accepted_statuses"] = ",".join(
            f"{st}:{n}"
            for st, n in sorted(
                pd.Series([str(p["status"]) for p in accepted]).value_counts().items()
            )
        )
        row["accepted_iters_median"] = float(np.median(iters)) if iters else np.nan
        row["accepted_iters_max"] = float(np.max(iters)) if iters else np.nan
        row["config_hash"] = short(r.config_hash)
        row["run_id"] = short(r.run_id)
        rows.append(row)
    out = pd.DataFrame(rows).sort_values(
        ["kind", "eventset", "pricing", "kappa", "scope", "design", "fold"],
        ignore_index=True,
    )
    _write(out, "attempts.csv")
    osqp_fail = out["osqp_statuses"].str.contains("infeasible|user_limit", regex=True)
    return {
        "attempts_runs": len(out),
        "attempts_runs_with_failed_osqp": int(osqp_fail.sum()),
        "attempts_seconds_total": float(out["seconds_total"].sum()),
        "attempts_seconds_failed": float(out["seconds_failed_attempts"].sum()),
    }


# --------------------------------------------------------------------------
# Phase florida: the two T14 designs
# --------------------------------------------------------------------------

FLORIDA_VARIANTS: Final[dict[str, tuple[str, dict[str, Any]]]] = {
    "osqp_default": ("OSQP", dict(OSQP_OPTIONS)),
    "osqp_no_polish": ("OSQP", {**OSQP_OPTIONS, "polishing": False}),
    "osqp_thesis": ("OSQP", {}),
    "clarabel": ("CLARABEL", {}),
    "clarabel_tight": ("CLARABEL", dict(REFERENCE_POLICY.solver_options["CLARABEL"])),
}
"""Solver and options of each variant; ``osqp_default`` is DEFAULT_POLICY's,
``clarabel_tight`` is :data:`REFERENCE_POLICY`'s."""


def t14_configs() -> dict[str, ExperimentConfig]:
    """Return the single-run configs of the two T14 designs, by hash prefix.

    Returns
    -------
    dict
        Hash prefix to config.
    """
    plan = fr.load_plan()
    out: dict[str, ExperimentConfig] = {}
    for cfg in fr.kfold_configs(plan).values():
        for s in cfg.single_runs():
            h = short(config_hash(s))
            if h in T14_HASHES:
                out[h] = s
    if sorted(out) != sorted(T14_HASHES):
        raise RuntimeError(f"T14 designs not found in the plan: {sorted(out)}")
    return out


def florida_worker(item: tuple[str, str]) -> dict[str, Any]:
    """Solve one T14 design with one variant on a freshly built problem.

    Parameters
    ----------
    item : tuple of str
        (hash prefix, variant name).

    Returns
    -------
    dict
        Status, objective (loss units), payout, OSQP's own record.
    """
    h, variant = item
    cfg = t14_configs()[h]
    (b,) = build(cfg)
    solver, options = FLORIDA_VARIANTS[variant]
    t0 = time.perf_counter()
    b.problem.solve(solver=solver, verbose=False, **options)
    seconds = time.perf_counter() - t0
    theta = np.asarray(b.context.theta.value, dtype=np.float64)
    term = b.objective
    value = float(term.expression.value) * b.context.scale**term.homogeneity
    row: dict[str, Any] = {
        "config_hash": h,
        "fold": int(cfg.sample.model_dump(mode="json")["fold"]),
        "variant": variant,
        "solver": solver,
        "options": json.dumps(options, sort_keys=True),
        "cvxpy_status": b.problem.status,
        "objective": value,
        "theta_all_zero": bool(not np.any(theta)),
        "theta_max_scaled": float(np.max(np.abs(theta))),
        "seconds": round(seconds, 1),
    }
    if solver == "OSQP":
        row.update(osqp_info(b))
    else:
        row.update(solver_record(b))
    return row


def run_florida(args: argparse.Namespace) -> dict[str, Any]:
    """Phase florida (module docstring).

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.

    Returns
    -------
    dict
        Summary entries.
    """
    stored = pd.read_csv(
        REPO_ROOT / "research" / "data" / "florida-rerun" / "solver_check.csv"
    )
    stored["h"] = stored["config_hash"].map(short)
    variants = args.florida_variants or list(FLORIDA_VARIANTS)
    items = [(h, v) for h in T14_HASHES for v in variants]
    out = pd.DataFrame(list(_map(florida_worker, items, args.jobs)))
    previous = OUT_DIR / "florida_osqp.csv"
    if args.florida_variants and previous.exists():
        # A partial rerun replaces its variants and keeps the other rows.
        old = pd.read_csv(previous, dtype={"config_hash": str})
        old = old[~old["variant"].isin(variants)]
        old = old.drop(columns=["rel_gap_vs_clarabel", "stored_objective"])
        out = pd.concat([old, out], ignore_index=True)
    ref = out[out["variant"] == "clarabel"].set_index("config_hash")["objective"]
    out["rel_gap_vs_clarabel"] = (out["objective"] - out["config_hash"].map(ref)) / out[
        "config_hash"
    ].map(ref).abs()
    st = stored.set_index("h")["stored_objective"]
    out["stored_objective"] = out["config_hash"].map(st)
    out = out.sort_values(["config_hash", "variant"], ignore_index=True)
    _write(out, "florida_osqp.csv")
    return {"florida_rows": len(out)}


# --------------------------------------------------------------------------
# Phase thesis: every MSE design of the thesis-portfolio configs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Design:
    """One MSE design (single run) of a committed thesis-portfolio config."""

    source: str
    label: str
    config: ExperimentConfig = field(compare=False)


def _mse(configs: Iterable[ExperimentConfig]) -> list[ExperimentConfig]:
    return [c for c in configs if c.objectives[0].kind == "mse"]


def _swept(cfg: ExperimentConfig, source: str) -> list[Design]:
    out = [
        Design(source, f"base|{s.scopes[0].kind}", s) for s in _mse(cfg.single_runs())
    ]
    for sweep in cfg.sweeps:
        for point in sweep_points(cfg, sweep):
            if point.config.objectives[0].kind != "mse":
                continue
            label = f"{point.parameter}={point.value}|{point.config.scopes[0].kind}"
            if point.location_ids is not None:
                label += f"|{','.join(point.location_ids)}"
            out.append(Design(source, label, point.config))
    return out


def thesis_designs() -> tuple[list[Design], list[str]]:
    """Every MSE design of the committed thesis-portfolio configs.

    Returns
    -------
    designs : list of Design
        Parity (``parity/configs/thesis.yaml`` and its sweeps), the site
        (``site/configs/explorer.yaml`` and its sweeps), C1 (main,
        reference and the F-12 EventSets found under ``C1_EVENTSETS``),
        C1 RQ2's k-fold configs and C1 RQ2 sensitivities' noise and
        cluster-count configs, de-duplicated by config hash (first source
        kept).
    skipped : list of str
        What was not checked, and why.
    """
    designs: list[Design] = []
    skipped: list[str] = []
    designs += _swept(load_config(PARITY_CONFIG), "parity")
    designs += _swept(load_config(SITE_CONFIG), "site")
    specs, _ = c1.plan(["main", "reference"])
    designs += [
        Design(f"c1-{s.variant.family}", f"{s.variant.key}|{s.scope}", s.config)
        for s in specs
        if s.objective == "mse"
    ]
    base = load_config(c1.BASE_CONFIG).model_dump(mode="json")
    base["output"] = {"directory": str(c1.STORE)}
    for v in c1.variants(["f12"]):
        spec = c1.F12_EVENTSETS[v.eventset]
        path = F12_EVENTSETS / spec.directory
        if not path.is_dir():
            skipped.append(f"c1-f12 {v.key}: EventSet {spec.directory} not found")
            continue
        checksums = {v.eventset: EventSet.from_parquet(path).content_hash()}
        for scope in c1.SCOPES:
            cfg = c1.single_config(base, v, scope, {"kind": "mse"}, checksums)
            designs.append(Design("c1-f12", f"{v.key}|{scope}", cfg))
    for (pricing, name), cfg in rq2.kfold_configs().items():
        designs += [
            Design(
                "c1-rq2-kfold",
                f"{pricing}|{name}|{s.scopes[0].kind}|fold{s.sample.model_dump()['fold']}",
                s,
            )
            for s in _mse(cfg.single_runs())
        ]
    sens = rqs.plan_nclusters(rqs.FULL_DIR / "store") + rqs.plan_noise(
        rqs.FULL_DIR, rqs.FULL_DIR / "store"
    )
    designs += [
        Design(
            f"c1-rq2-sens-{s.family}",
            f"{s.variant}|{s.pricing}|{s.scope}",
            s.config,
        )
        for s in sens
        if s.design == "mse"
    ]
    seen: set[str] = set()
    unique: list[Design] = []
    for d in designs:
        h = config_hash(d.config)
        if h in seen:
            continue
        seen.add(h)
        unique.append(d)
    return unique, skipped


def _solve_all(
    cfg: ExperimentConfig, policy: SolverPolicy, label: str
) -> dict[str, Any]:
    built = build(cfg)
    t0 = time.perf_counter()
    results = [solve(b, policy) for b in built]
    seconds = time.perf_counter() - t0
    polish: list[str] = []
    zero_osqp = 0
    iters: list[int] = []
    for b, r in zip(built, results, strict=True):
        if r.solver != "OSQP":
            continue
        info = osqp_info(b)
        polish.append(info["polish"])
        iters.append(info["osqp_iter"])
        zero_osqp += int(info["osqp_x_zero"])
    return {
        f"{label}_objective": float(sum(r.objective_value for r in results)),
        f"{label}_solvers": ",".join(sorted({r.solver for r in results})),
        f"{label}_statuses": ",".join(sorted({r.status.value for r in results})),
        f"{label}_attempts": ";".join(
            "/".join(f"{a.solver}:{a.status.value}" for a in r.attempts)
            for r in results
            if len(r.attempts) > 1
        ),
        f"{label}_osqp_problems": len(polish),
        f"{label}_polish": ",".join(
            f"{k}:{n}" for k, n in sorted(pd.Series(polish).value_counts().items())
        )
        if polish
        else "",
        f"{label}_osqp_x_zero": zero_osqp,
        f"{label}_osqp_iter_max": max(iters) if iters else np.nan,
        f"{label}_theta_all_zero": sum(int(not np.any(r.theta)) for r in results),
        f"{label}_max_violation_scaled": max(
            r.diagnostics["max_constraint_violation_scaled"] for r in results
        ),
        f"{label}_premium": float(sum(r.premium for r in results)),
        f"{label}_seconds": round(seconds, 2),
    }


def thesis_worker(design: Design) -> dict[str, Any]:
    """Check one MSE design (module docstring, phase thesis).

    Parameters
    ----------
    design : Design
        The design.

    Returns
    -------
    dict
        Its provenance, whether it is a QP, and for a QP the three solves.
    """
    cfg = design.config
    d = cfg.model_dump(mode="json")
    row: dict[str, Any] = {
        "source": design.source,
        "label": design.label,
        "scope": cfg.scopes[0].kind,
        "basis": d["basis"],
        "sample": d["sample"]["kind"],
        "fold": d["sample"].get("fold"),
        "pricing": d["pricing"]["kind"],
        "kappa": d["constraints"][0]["loading"],
        "n_locations": len(prepared(cfg).location_ids),
        "config_hash": config_hash(cfg),
    }
    try:
        built = build(cfg)
    except ParametricInsuranceDesignError as exc:
        # The runner records such a run as failed too (e.g. an n_assets
        # subset smaller than the cluster count, without cap_n_clusters).
        row["build_error"] = f"{type(exc).__name__}: {exc}"
        row["qp"] = False
        return row
    row["n_problems"] = len(built)
    row["qp"] = all(is_qp(b.problem) for b in built)
    if not row["qp"]:
        return row
    row.update(_solve_all(cfg, DEFAULT_POLICY, "default"))
    row.update(_solve_all(cfg, THESIS_POLICY, "thesis"))
    row.update(_solve_all(cfg, REFERENCE_POLICY, "reference"))
    ref = row["reference_objective"]
    for label in ("default", "thesis"):
        row[f"{label}_rel_gap"] = (row[f"{label}_objective"] - ref) / abs(ref)
    return row


def run_thesis(args: argparse.Namespace) -> dict[str, Any]:
    """Phase thesis (module docstring).

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.

    Returns
    -------
    dict
        Summary entries.
    """
    designs, skipped = thesis_designs()
    if args.limit:
        designs = designs[: args.limit]
    print(f"thesis: {len(designs)} MSE designs; skipped: {skipped}", flush=True)
    recorded = recorded_hashes()
    # C1 and the site first, parity's large sweeps last; every row is also
    # appended to a log, so an interrupted phase keeps what it has done.
    designs.sort(key=lambda d: d.source == "parity")
    partial = LOG_DIR / "thesis_rows.jsonl"
    rows: list[dict[str, Any]] = []
    if args.resume and partial.exists():
        by_hash = {config_hash(d.config): d for d in designs}
        for line in partial.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            design = by_hash.get(row["config_hash"])
            if design is not None:
                row["source"], row["label"] = design.source, design.label
                rows.append(row)
        done = {r["config_hash"] for r in rows}
        designs = [d for d in designs if config_hash(d.config) not in done]
        print(f"thesis: resumed {len(rows)} rows, {len(designs)} to do", flush=True)
    with partial.open("a", encoding="utf-8") as log:
        for i, row in enumerate(_map(thesis_worker, designs, args.jobs), 1):
            rows.append(row)
            log.write(json.dumps(row, default=str) + "\n")
            log.flush()
            if i % 25 == 0:
                print(f"thesis: {i}/{len(designs)}", flush=True)
    out = pd.DataFrame(rows)
    out["recorded_in_research_data"] = out["config_hash"].isin(recorded)
    out["config_hash"] = out["config_hash"].map(short)
    out = out.sort_values(["source", "label"], ignore_index=True)
    _write(out, "thesis_mse.csv")
    qp = out[out["qp"]]
    return {
        "thesis_designs": len(out),
        "thesis_qp_designs": len(qp),
        "thesis_skipped": skipped,
        "thesis_default_max_rel_gap": float(qp["default_rel_gap"].max()),
        "thesis_thesis_policy_max_rel_gap": float(qp["thesis_rel_gap"].max()),
        "thesis_default_not_optimal": int((qp["default_rel_gap"] > GAP).sum()),
        "thesis_thesis_policy_not_optimal": int((qp["thesis_rel_gap"] > GAP).sum()),
        "thesis_default_linsys_error": int(
            qp["default_polish"].str.contains("linsys_error").sum()
        ),
        "thesis_thesis_policy_linsys_error": int(
            qp["thesis_polish"].str.contains("linsys_error").sum()
        ),
    }


# --------------------------------------------------------------------------
# Phases profile and inaccurate: index (b) under cost of capital
# --------------------------------------------------------------------------


def florida_config(eventset: str, design: str, kappa: float) -> ExperimentConfig:
    """Return a Florida holdout individual-scope config under CoC r 0.06.

    Parameters
    ----------
    eventset : str
        ``"a"`` or ``"cic75"``.
    design : str
        ``"mse"``, ``"eu"``, ``"wcvar@0.99"`` or ``"wcvar@0.995"``.
    kappa : float
        Budget loading.

    Returns
    -------
    ExperimentConfig
        The single-run config (its hash is in ``florida-rerun/runs.csv``).
    """
    plan = fr.load_plan()
    for r in fr.holdout_runs(plan):
        if (
            r.index == eventset
            and r.pricing == "coc_r0.06"
            and r.kappa == kappa
            and r.scope == "individual"
            and r.design == design
        ):
            return r.config
    raise KeyError((eventset, design, kappa))


def conditioning(b: BuiltProblem) -> dict[str, Any]:
    """Return data features of a single-entity problem (conditioning).

    Parameters
    ----------
    b : BuiltProblem
        An individual-scope problem.

    Returns
    -------
    dict
        Rows, outcomes, scale, loss range, distinct index values per bin and
        distinct yearly payout patterns (rows of the yearly basis matrix).
    """
    ctx = b.context
    index = np.asarray(ctx.problem.index)[:, 0]
    basis = ctx.payout_structure.basis_matrix(index)
    measure = ctx.measure
    yearly = np.zeros((measure.n_outcomes, basis.shape[1]))
    np.add.at(yearly, measure.outcome_of_row, basis)
    loss = np.zeros(measure.n_outcomes)
    np.add.at(loss, measure.outcome_of_row, ctx.loss)
    bins = basis.argmax(axis=1)
    paid = basis.any(axis=1)
    per_bin = [len(np.unique(index[paid & (bins == k)])) for k in range(basis.shape[1])]
    data = b.problem.get_problem_data(cp.CLARABEL)[0]
    a = data["A"]
    positive = loss[loss > 0]
    return {
        "n_rows": len(index),
        "n_outcomes": int(measure.n_outcomes),
        "n_vars_solver": int(a.shape[1]),
        "n_cons_solver": int(a.shape[0]),
        "nnz_solver": int(a.nnz),
        "scale": float(ctx.scale),
        "loss_years_positive": len(positive),
        "loss_min_positive_scaled": float(positive.min()) if len(positive) else np.nan,
        "loss_max_scaled": float(loss.max()),
        "index_values_per_bin": ",".join(str(n) for n in per_bin),
        "years_with_payout_row": int(np.count_nonzero(yearly.any(axis=1))),
        "distinct_year_patterns": len(np.unique(yearly, axis=0)),
    }


def profile_worker(item: tuple[str, str, str]) -> dict[str, Any]:
    """Profile one county's problem of one Florida CoC individual design.

    Parameters
    ----------
    item : tuple of str
        (eventset, design, county).

    Returns
    -------
    dict
        Size, conditioning features, CLARABEL's record, and for an MSE
        problem OSQP's (``solve.DEFAULT_POLICY`` tries OSQP first).
    """
    eventset, design, county = item
    cfg = florida_config(eventset, design, 0.5)
    built = {b.spec.problem_id: b for b in build(cfg)}
    b = built[county]
    row: dict[str, Any] = {
        "eventset": eventset,
        "design": design,
        "county": county,
        "config_hash": short(config_hash(cfg)),
        "qp": is_qp(b.problem),
    }
    row.update(conditioning(b))
    t0 = time.perf_counter()
    b.problem.solve(solver="CLARABEL", verbose=False)
    row["clarabel_seconds"] = round(time.perf_counter() - t0, 2)
    row.update(solver_record(b))
    return row


def run_profile(args: argparse.Namespace) -> dict[str, Any]:
    """Phase profile (module docstring).

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.

    Returns
    -------
    dict
        Summary entries.
    """
    items = [
        (es, design, county)
        for es in ("cic75", "a")
        for design in ("eu", "mse")
        for county in PROFILE_COUNTIES
    ]
    out = pd.DataFrame(list(_map(profile_worker, items, args.jobs)))
    out = out.sort_values(["design", "county", "eventset"], ignore_index=True)
    _write(out, "profile.csv")
    return {"profile_rows": len(out)}


INACCURATE_VARIANTS: Final[dict[str, tuple[str, dict[str, Any]]]] = {
    "clarabel_default": ("CLARABEL", {}),
    "clarabel_max_iter_1000": ("CLARABEL", {"max_iter": 1000}),
    "highs": ("HIGHS", {}),
    "clarabel_scale_x0.1": ("CLARABEL", {}),
}
"""Solver and options of each variant; ``clarabel_scale_x0.1`` solves a
problem built with a tenth of the default loss scale (scaled losses up to
10 instead of 1)."""


def inaccurate_items(store_root: Path) -> list[tuple[str, str, float, str, str]]:
    """Return the stored ``optimal_inaccurate`` problems to re-solve.

    Parameters
    ----------
    store_root : Path
        The Florida result store.

    Returns
    -------
    list of tuple
        (eventset, design, kappa, problem id, run id) of individual-scope
        holdout problems, at most :data:`INACCURATE_MAX`, spread over the
        designs.
    """
    store = ResultStore(store_root)
    runs = pd.read_csv(REPO_ROOT / "research" / "data" / "florida-rerun" / "runs.csv")
    runs = runs[
        (runs["kind"] == "holdout")
        & (runs["scope"] == "individual")
        & runs["statuses"].str.contains("optimal_inaccurate")
    ]
    picked: list[tuple[str, str, float, str, str]] = []
    for r in runs.itertuples():
        table = store.read("runs", run_ids=[r.run_id])
        bad = table[table["status"] == "optimal_inaccurate"]["problem_id"].tolist()
        picked += [(r.eventset, r.design, float(r.kappa), p, r.run_id) for p in bad[:2]]
    return picked[:INACCURATE_MAX]


def inaccurate_worker(item: tuple[str, str, float, str, str, str]) -> dict[str, Any]:
    """Re-solve one stored ``optimal_inaccurate`` problem with one variant.

    Parameters
    ----------
    item : tuple
        (eventset, design, kappa, problem id, run id, store root).

    Returns
    -------
    dict
        The variant's status, iterations, objective and payout against the
        stored ones, and against the variant ``clarabel_max_iter_1000``.
    """
    eventset, design, kappa, pid, rid, store_root = item
    cfg = florida_config(eventset, design, kappa)
    store = ResultStore(Path(store_root))
    stored = store.read("runs", run_ids=[rid]).set_index("problem_id").loc[pid]
    payouts = store.read("payouts", run_ids=[rid])
    stored_theta = (
        payouts[payouts["problem_id"] == pid]
        .sort_values(["entity_id", "param_index"])["value"]
        .to_numpy(dtype=np.float64)
    )
    rows: list[dict[str, Any]] = []
    for variant, (solver, options) in INACCURATE_VARIANTS.items():
        if variant == "clarabel_scale_x0.1":
            b = build_scaled(cfg, pid, 0.1)
        else:
            b = {x.spec.problem_id: x for x in build(cfg)}[pid]
        t0 = time.perf_counter()
        b.problem.solve(solver=solver, verbose=False, **options)
        seconds = time.perf_counter() - t0
        term = b.objective
        value = (
            float(term.expression.value) * b.context.scale**term.homogeneity
            if b.problem.status in ("optimal", "optimal_inaccurate")
            else np.nan
        )
        theta = (
            np.asarray(b.context.theta.value).ravel() * b.context.scale
            if b.context.theta.value is not None
            else np.array([])
        )
        row: dict[str, Any] = {
            "eventset": eventset,
            "design": design,
            "kappa": kappa,
            "county": pid,
            "config_hash": short(config_hash(cfg)),
            "variant": variant,
            "status": b.problem.status,
            "seconds": round(seconds, 2),
            "objective": value,
            "stored_status": stored["status"],
            "stored_objective": float(stored["objective_value"]),
            "theta_max": float(theta.max()) if theta.size else np.nan,
        }
        if stored_theta.size == theta.size and theta.size:
            row["max_abs_dtheta_rel"] = float(
                np.max(np.abs(theta - stored_theta)) / max(np.max(stored_theta), 1.0)
            )
        row.update(solver_record(b))
        rows.append(row)
    return {"rows": rows}


def run_inaccurate(args: argparse.Namespace) -> dict[str, Any]:
    """Phase inaccurate (module docstring).

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.

    Returns
    -------
    dict
        Summary entries.
    """
    store = str(args.florida_store)
    items = [(*i, store) for i in inaccurate_items(args.florida_store)]
    print(f"inaccurate: {len(items)} problems", flush=True)
    rows: list[dict[str, Any]] = []
    for res in _map(inaccurate_worker, items, args.jobs):
        rows += res["rows"]
    out = pd.DataFrame(rows)
    out["rel_gap_vs_stored"] = (out["objective"] - out["stored_objective"]) / out[
        "stored_objective"
    ].abs()
    out = out.sort_values(["design", "kappa", "county", "variant"], ignore_index=True)
    _write(out, "inaccurate.csv")
    return {"inaccurate_rows": len(out)}


# --------------------------------------------------------------------------
# Phase stores: the failure's signature in stored designs
# --------------------------------------------------------------------------


def run_stores(args: argparse.Namespace) -> dict[str, Any]:
    """Scan result stores for OSQP-solved problems with an all-zero payout.

    OSQP's failure (note, section 3) returns the solver's initial iterate,
    all zeros, with status ``solved``: every such problem is stored by
    OSQP with payout parameters that are all exactly zero. A zero payout can
    also be a true optimum, so a hit is a candidate, not a proof; no hit
    rules the failure out for the stored designs. Reads each store's
    ``runs`` and ``payouts`` tables (``--scan-store LABEL=PATH``, read
    only).

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments (``scan_store``).

    Returns
    -------
    dict
        Summary entries.
    """
    recorded = recorded_hashes()
    rows: list[dict[str, Any]] = []
    for spec in args.scan_store:
        label, path = spec.split("=", 1)
        root = Path(path)
        for run_file in sorted((root / "runs").glob("*.parquet")):
            runs = pd.read_parquet(run_file)
            payouts = pd.read_parquet(root / "payouts" / run_file.name)
            osqp = runs[runs["solver"] == "OSQP"]
            zero = [
                str(pid)
                for pid in osqp["problem_id"]
                if not np.any(payouts.loc[payouts["problem_id"] == pid, "value"])
            ]
            rows.append(
                {
                    "store": label,
                    "run_id": short(str(runs["run_id"].iloc[0])),
                    "config_hash": short(str(runs["config_hash"].iloc[0])),
                    "recorded_in_research_data": bool(
                        runs["config_hash"].iloc[0] in recorded
                    ),
                    "objective": ",".join(sorted(set(runs["objective"].astype(str)))),
                    "n_problems": len(runs),
                    "n_osqp": len(osqp),
                    "osqp_statuses": ",".join(sorted(set(osqp["status"].astype(str)))),
                    "n_osqp_zero_payout": len(zero),
                    "osqp_zero_payout_problems": ",".join(zero),
                }
            )
    out = pd.DataFrame(rows)
    by_store = out.groupby("store").agg(
        runs=("run_id", "size"),
        recorded=("recorded_in_research_data", "sum"),
        osqp_problems=("n_osqp", "sum"),
        zero_payout=("n_osqp_zero_payout", "sum"),
    )
    _write(out[out["n_osqp"] > 0].reset_index(drop=True), "stores.csv")
    return {
        "stores": {
            k: {c: int(v) for c, v in r.items()} for k, r in by_store.iterrows()
        },
        "zero_payout_runs": sorted(
            f"{r.store}:{r.config_hash}"
            for r in out.itertuples()
            if r.n_osqp_zero_payout
        ),
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

PHASES: Final[dict[str, Callable[[argparse.Namespace], dict[str, Any]]]] = {
    "attempts": run_attempts,
    "florida": run_florida,
    "thesis": run_thesis,
    "profile": run_profile,
    "inaccurate": run_inaccurate,
    "stores": run_stores,
}
DEFAULT_PHASES: Final[tuple[str, ...]] = (
    "attempts",
    "thesis",
    "florida",
    "profile",
    "inaccurate",
)
"""``stores`` needs ``--scan-store`` paths, so it runs only when asked."""


def main(argv: list[str] | None = None) -> int:
    """Run the requested phases.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description="MAR-224 solver checks.")
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument(
        "--phases", nargs="+", default=list(DEFAULT_PHASES), choices=PHASES
    )
    parser.add_argument("--florida-store", type=Path, default=FLORIDA_STORE)
    parser.add_argument(
        "--florida-variants",
        nargs="+",
        choices=list(FLORIDA_VARIANTS),
        help="florida: run only these variants and keep the others' rows",
    )
    parser.add_argument("--limit", type=int, default=0, help="thesis: first n only")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="thesis: keep the rows already in results/mar224/thesis_rows.jsonl",
    )
    parser.add_argument(
        "--scan-store",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="stores: a result store to scan (repeatable)",
    )
    args = parser.parse_args(argv)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for name in args.phases:
        t = time.perf_counter()
        summary = {
            "issue": "MAR-224",
            "package_versions": package_versions(),
            **PHASES[name](args),
            "phase_seconds": round(time.perf_counter() - t, 1),
        }
        path = OUT_DIR / f"summary_{name}.json"
        path.write_text(json.dumps(summary, indent=2, default=str) + "\n")
        print(f"phase {name} done in {summary['phase_seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
