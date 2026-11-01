r"""Florida rerun (MAR-202, C1-F1): RQ1, RQ2 and the combination on the D2 portfolio.

Question (MAR-202, split from MAR-152 item 4): the C1 analyses, moved from
the 9-asset thesis portfolio to the paper portfolio D2, Florida's 67
counties with the State of Florida as the single owner, for both indices
(a: wind at the county centroid; b: cat-in-a-circle at 75 km), with
``payout.below_attachment: zero``:

* **RQ1 (tail)**: within each scope, weighted CVaR against MSE and E[U]
  (C1.md sections 3, 5);
* **RQ2 (joint calibration)**: within each objective, the cluster and
  portfolio scopes against the individual scope, with the cluster index
  separated from the joint calibration (``cluster_separate``, C1.md 6b.6),
  the payout per county, and, under the load, the portfolio premium split
  into cross-coverage and pricing diversification (``portfolio_matched``,
  C1.md 6b.5);
* **the combination** (MAR-182): portfolio weighted CVaR against individual
  MSE, individual weighted CVaR and portfolio MSE, and the interaction.

The plan is ``research/configs/florida/plan.yaml``; every single run derives
from the base config of its index (``florida_main.yaml``,
``florida_cic75.yaml``) by setting the pricing, kappa, one scope and one
objective (and, for k-fold, the sample). Phases (``--phases``):

``solve``
    Every holdout run and every k-fold fold run through the runner
    (:func:`c1_checkpoint.solve_worker`) in ``--jobs`` processes; the parent
    writes them to ``results/florida/store`` (not committed; cached).
``rq1``
    Per (index, pricing, kappa, scope): the C1 bootstrap of the test KPIs on
    one resample of the holdout test years and the paired differences
    weighted CVaR - MSE and - E[U] (:func:`c1_checkpoint.group_worker`).
``rq2``
    Per (index, pricing, kappa, design): the scopes against each other on
    the same resample, with ``cluster_separate``
    (:func:`c1_rq2.holdout_worker`; no ``_alt`` designs: those are MAR-198's
    question). The pairing across scopes is C1 section 6b.1's
    (``c1_rq2.portfolio_rows``): MAR-179 is not merged.
``combination``
    Per (index, pricing, kappa): the 3 scopes x 4 designs on one resample and
    every contrast of MAR-182 (:func:`c1_combination.holdout_worker`).
``kfold``
    Pooled 5-fold out-of-sample KPIs (MAR-151) at kappa 1, pure and r 0.06,
    and the same contrasts on the one resample of all years (MAR-182's
    k-fold phase, parametrised by index), plus the per-fold KPIs.
``premium``
    Under the load (r 0.06), for every kappa and design: the individual
    design's aggregate premium ``A = P(sum_i pi_i)`` on the train years
    against the sum of its 67 stand-alone premiums, and the derived run
    ``portfolio_matched``: the portfolio design problem with the budget
    ``P(sum_j pi_j) <= A`` (loading ``A / E[L]``, a runner run with a config
    hash of its own). Then portfolio - individual = (portfolio_matched -
    individual: cross-coverage at the individual designs' own aggregate
    premium) + (portfolio - portfolio_matched: the budget that pricing the
    aggregate frees, pricing diversification), paired on the C1 resample.
``guard``
    The clustering's degenerate-tail guard (MAR-172) on every calibration
    sample (holdout train, each k-fold training block): the zero-loss share
    of the row probability against ``beta_tail``; the threshold filter's
    dropped expected loss; every stored run's statuses and solvers; the
    manifest's MAR-173 flags if the manifest has them.

Every phase writes its full tables to ``results/florida/full/`` (not
committed). ``florida_rerun_tables.py`` writes the committed ones (each
under 500 kB) and ``tables.md`` to ``research/data/florida-rerun/``.
Portfolio-level KPIs, plus payout and loss per payout entity (county or
cluster): no per-county uncovered-loss or premium KPI of a joint design
(MAR-98, MAR-100).

Run from the repository root, with the two EventSets in
``results/florida/eventsets/`` (content hashes in the base configs)::

    uv run python research/scripts/florida_rerun.py --jobs 3
    uv run python research/scripts/florida_rerun_tables.py

Observations only. The interpretation is the owner's.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import time
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Final

import c1_checkpoint as c1
import c1_combination as comb
import c1_rq2 as rq2
import numpy as np
import pandas as pd
import yaml

from parametric_insurance_design import splits
from parametric_insurance_design.basis import Basis, outcome_measure
from parametric_insurance_design.bootstrap import (
    KpiBootstrap,
    YearResample,
    bootstrap_kpis,
    kpi_replicates,
    paired_difference,
    resample_years,
)
from parametric_insurance_design.evaluate import kpis as evaluate_kpis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment import kfold
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import (
    RunOutcome,
    package_versions,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.scopes import Cluster
from parametric_insurance_design.solve import DEFAULT_POLICY

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
PLAN: Final[Path] = REPO_ROOT / "research" / "configs" / "florida" / "plan.yaml"
STORE: Final[Path] = REPO_ROOT / "results" / "florida" / "store"
FULL_DIR: Final[Path] = REPO_ROOT / "results" / "florida" / "full"
FAMILY: Final[str] = "florida"
MATCHED: Final[str] = "portfolio_matched"
EVAL_BETAS: Final[tuple[float, ...]] = c1.ANNUAL_EVAL_BETAS
ENTITY_KPIS: Final[frozenset[str]] = frozenset({"expected_payout", "expected_loss"})
"""Entity-level KPIs kept from the RQ2 phase: payout and loss per entity."""


# --------------------------------------------------------------------------
# The plan
# --------------------------------------------------------------------------


def load_plan(path: Path = PLAN) -> dict[str, Any]:
    """Read the plan YAML.

    Parameters
    ----------
    path : pathlib.Path
        ``plan.yaml``.

    Returns
    -------
    dict
        The plan, with ``kappas`` as floats and ``_dir``, the directory the
        base config paths are relative to.
    """
    plan = yaml.safe_load(path.read_text())
    plan["kappas"] = [float(k) for k in plan["kappas"]]
    plan["kfold"]["kappas"] = [float(k) for k in plan["kfold"]["kappas"]]
    plan["_dir"] = str(path.resolve().parent)
    return plan


def base_config(plan: dict[str, Any], index: str) -> dict[str, Any]:
    """Return an index's base config as JSON data, output to :data:`STORE`.

    Parameters
    ----------
    plan : dict
        The plan.
    index : str
        ``"a"`` or ``"cic75"``.

    Returns
    -------
    dict
        ``ExperimentConfig.model_dump(mode="json")`` of the base config.
    """
    cfg = load_config(Path(plan["_dir"]) / plan["indices"][index]["config"])
    data = cfg.model_dump(mode="json")
    data["output"] = {"directory": str(STORE)}
    return data


def design_of(objective: dict[str, Any]) -> str:
    """Design label of an objective config, e.g. ``"wcvar@0.99"``.

    Parameters
    ----------
    objective : dict
        Objective config (``kind`` and parameters).

    Returns
    -------
    str
        ``mse``, ``eu`` or ``wcvar@<beta>``.
    """
    if objective["kind"] == "weighted_cvar":
        return f"wcvar@{float(objective['beta']):g}"
    return {"mse": "mse", "expected_uncovered": "eu"}[objective["kind"]]


def derive(
    base: dict[str, Any],
    plan: dict[str, Any],
    *,
    index: str,
    pricing: str,
    kappa: float,
    scopes: Iterable[str],
    designs: Iterable[str],
    sample: dict[str, Any] | None = None,
    name: str | None = None,
) -> ExperimentConfig:
    """Return the config of one index, pricing and kappa.

    Parameters
    ----------
    base : dict
        :func:`base_config` of the index.
    plan : dict
        The plan.
    index, pricing : str
        Plan labels.
    kappa : float
        Budget loading.
    scopes, designs : iterable of str
        Plan labels, in this order.
    sample : dict, optional
        Sample config; the base config's (holdout) if None.
    name : str, optional
        Config name; ``florida-<index>`` if None.

    Returns
    -------
    ExperimentConfig
        A single run if one scope and one design are given.
    """
    data = json.loads(json.dumps(base))
    data["name"] = name or f"{FAMILY}-{index}"
    data["pricing"] = plan["pricings"][pricing]
    data["constraints"] = [{"kind": "budget", "loading": kappa}]
    by_kind = {s["kind"]: s for s in base["scopes"]}
    data["scopes"] = [by_kind[s] for s in scopes]
    data["objectives"] = [plan["designs"][d] for d in designs]
    if sample is not None:
        data["sample"] = sample
    return parse_config(data)


@dataclass(frozen=True)
class HoldoutRun:
    """One holdout single run of the plan."""

    index: str
    pricing: str
    kappa: float
    scope: str
    design: str
    config: ExperimentConfig
    run_id: str


def checksum_of(config: ExperimentConfig) -> str:
    """Return the EventSet checksum a config pins (raise if it pins none)."""
    if config.eventset.checksum is None:
        raise RuntimeError("every Florida config must pin its EventSet checksum")
    return config.eventset.checksum


def rid_of(config: ExperimentConfig) -> str:
    """Run id of a single-run config under the default policy."""
    return run_key(config_hash(config), checksum_of(config), policy=DEFAULT_POLICY)


def holdout_runs(plan: dict[str, Any]) -> list[HoldoutRun]:
    """Every holdout single run of the plan.

    Parameters
    ----------
    plan : dict
        The plan.

    Returns
    -------
    list of HoldoutRun
        Index, pricing, kappa, scope, design, in plan order.
    """
    out: list[HoldoutRun] = []
    for index in plan["indices"]:
        base = base_config(plan, index)
        for pricing in plan["pricings"]:
            for kappa in plan["kappas"]:
                for scope in plan["scopes"]:
                    for design in plan["designs"]:
                        cfg = derive(
                            base,
                            plan,
                            index=index,
                            pricing=pricing,
                            kappa=kappa,
                            scopes=[scope],
                            designs=[design],
                        )
                        out.append(
                            HoldoutRun(
                                index, pricing, kappa, scope, design, cfg, rid_of(cfg)
                            )
                        )
    return out


def kfold_configs(
    plan: dict[str, Any],
) -> dict[tuple[str, str, float, str], ExperimentConfig]:
    """Return the k-fold experiment configs, keyed by (index, pricing, kappa, set).

    Parameters
    ----------
    plan : dict
        The plan.

    Returns
    -------
    dict
        One experiment config (every scope, the set's objectives, ``kfold``
        sample without a fold) per index, pricing, kappa and objective set.
    """
    kf = plan["kfold"]
    out: dict[tuple[str, str, float, str], ExperimentConfig] = {}
    for index in plan["indices"]:
        base = base_config(plan, index)
        for pricing in kf["pricings"]:
            for kappa in kf["kappas"]:
                for oset, designs in kf["objective_sets"].items():
                    out[(index, pricing, kappa, oset)] = derive(
                        base,
                        plan,
                        index=index,
                        pricing=pricing,
                        kappa=kappa,
                        scopes=plan["scopes"],
                        designs=designs,
                        sample={"kind": "kfold", "k": int(kf["k"])},
                        name=f"{FAMILY}-{index}-kfold",
                    )
    return out


def _pool(jobs: int) -> ProcessPoolExecutor:
    return ProcessPoolExecutor(max_workers=jobs, mp_context=get_context("spawn"))


def _label(key: tuple[Any, ...]) -> str:
    return "|".join(f"{x:g}" if isinstance(x, float) else str(x) for x in key)


def _cost_rank(config: ExperimentConfig) -> tuple[int, int]:
    """Sort key: individual before portfolio before cluster, loads first."""
    scope = {"individual": 0, "portfolio": 1}.get(config.scopes[0].kind, 2)
    return (scope, 0 if config.pricing.kind != "pure" else 1)


def solve_all(
    todo: dict[str, ExperimentConfig], store: ResultStore, jobs: int
) -> dict[str, float]:
    """Solve the runs not yet in the store; the parent writes them.

    Parameters
    ----------
    todo : dict
        Run id to single-run config.
    store : ResultStore
        Target store.
    jobs : int
        Worker processes.

    Returns
    -------
    dict
        Seconds per run (run id prefix).
    """
    missing = {rid: cfg for rid, cfg in todo.items() if not store.has_run(rid)}
    # longest first (the individual scope solves 67 problems; the load makes
    # them slower), so that the pool does not end on one long run
    missing = dict(sorted(missing.items(), key=lambda kv: _cost_rank(kv[1])))
    print(f"{len(todo)} runs, {len(missing)} to solve", flush=True)
    seconds: dict[str, float] = {}
    if not missing:
        return seconds
    with _pool(jobs) as pool:
        futs = {pool.submit(c1.solve_worker, cfg): rid for rid, cfg in missing.items()}
        for i, fut in enumerate(as_completed(futs), 1):
            tables, manifest, sec = fut.result()
            rid = futs[fut]
            if manifest["run_id"] != rid:
                raise RuntimeError(f"run id mismatch: {manifest['run_id']} != {rid}")
            if store.has_run(rid):  # written meanwhile by another process
                print(f"[solve] {rid[7:19]} already in the store", flush=True)
                continue
            store.write_run(tables, manifest)
            seconds[rid[7:19]] = round(sec, 1)
            print(f"[solve {i}/{len(missing)}] {rid[7:19]} {sec:.0f}s", flush=True)
    return seconds


def check_ok(store: ResultStore, run_ids: Iterable[str]) -> None:
    """Raise unless every run is in the store, solved and evaluated."""
    for rid in run_ids:
        outcome = RunOutcome.from_manifest(store.manifest(rid), cached=True)
        if not outcome.ok:
            raise RuntimeError(f"run {rid} failed or was not evaluated: {outcome}")


# --------------------------------------------------------------------------
# Phase solve
# --------------------------------------------------------------------------


def run_solve(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase solve: every holdout and k-fold single run.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    plan : dict
        The plan.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    store = ResultStore(args.store)
    todo: dict[str, ExperimentConfig] = {r.run_id: r.config for r in holdout_runs(plan)}
    n_holdout = len(todo)
    for cfg in kfold_configs(plan).values():
        for s in cfg.single_runs():
            todo[rid_of(s)] = s
    seconds = solve_all(todo, store, args.jobs)
    check_ok(store, todo)
    return {
        "n_holdout_runs": n_holdout,
        "n_kfold_runs": len(todo) - n_holdout,
        "n_solved_this_call": len(seconds),
        "solve_seconds": round(time.perf_counter() - t0, 1),
        "solve_seconds_per_run": seconds,
    }


# --------------------------------------------------------------------------
# Phase rq1: within a scope, across designs (C1 sections 3, 5)
# --------------------------------------------------------------------------


def _variant(
    plan: dict[str, Any], index: str, pricing: str, kappa: float
) -> c1.Variant:
    wcvar = tuple(
        float(o["beta"])
        for o in plan["designs"].values()
        if o["kind"] == "weighted_cvar"
    )
    return c1.Variant(FAMILY, index, "annual", pricing, kappa, wcvar, EVAL_BETAS)


def run_rq1(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase rq1: :func:`c1_checkpoint.group_worker` per (index, pricing, kappa, scope).

    Writes ``rq1_kpis.csv`` and ``rq1_paired.csv`` to ``args.full``.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    plan : dict
        The plan.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    runs = holdout_runs(plan)
    groups: dict[tuple[str, str], list[tuple[str, ExperimentConfig, str]]] = {}
    by_key: dict[str, c1.Variant] = {}
    for r in runs:
        v = _variant(plan, r.index, r.pricing, r.kappa)
        by_key[v.key] = v
        groups.setdefault((v.key, r.scope), []).append((r.design, r.config, r.run_id))
    check_ok(ResultStore(args.store), (r.run_id for r in runs))
    kp: list[pd.DataFrame] = []
    pa: list[pd.DataFrame] = []
    with _pool(args.jobs) as pool:
        futs = {
            pool.submit(c1.group_worker, by_key[k], scope, m, str(args.store)): (
                k,
                scope,
            )
            for (k, scope), m in groups.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            k_, p_, sec = fut.result()
            kp.append(k_)
            pa.append(p_)
            print(f"[rq1 {i}/{len(futs)}] {_label(futs[fut])} {sec:.0f}s", flush=True)
    hashes = {r.run_id: config_hash(r.config) for r in runs}
    design_of_run = {
        (_variant(plan, r.index, r.pricing, r.kappa).key, r.scope, r.design): r.run_id
        for r in runs
    }
    kpis = c1._variant_columns(pd.concat(kp, ignore_index=True), by_key)
    kpis["config_hash"] = kpis["run_id"].map(hashes)
    paired = c1._variant_columns(pd.concat(pa, ignore_index=True), by_key)
    for side in ("a", "b"):
        paired[f"config_hash_{side}"] = [
            hashes[design_of_run[(v, s, d)]]
            for v, s, d in zip(
                paired["variant"],
                paired["scope"],
                paired[f"design_{side}"],
                strict=True,
            )
        ]
    args.full.mkdir(parents=True, exist_ok=True)
    kpis.drop(columns=["variant"]).to_csv(
        args.full / "rq1_kpis.csv", index=False, float_format="%.10g"
    )
    paired.drop(columns=["variant"]).to_csv(
        args.full / "rq1_paired.csv", index=False, float_format="%.10g"
    )
    return {
        "rq1_groups": len(groups),
        "rq1_seconds": round(time.perf_counter() - t0, 1),
    }


# --------------------------------------------------------------------------
# Phase rq2: within a design, across scopes (C1 section 6b)
# --------------------------------------------------------------------------


def rq2_worker(
    index: str,
    pricing: str,
    kappa: float,
    design: str,
    members: dict[str, tuple[ExperimentConfig, str]],
    store_root: str,
) -> tuple[dict[str, pd.DataFrame], float]:
    """:func:`c1_rq2.holdout_worker`, with the KPI table cut to what is used.

    Keeps every portfolio-level row and, per entity, only the payout and the
    loss (beta-free, at the config's evaluation beta): the per-county
    payout shares. The other entity rows are not used and would make the
    full table about a hundred times larger.

    Parameters
    ----------
    index, pricing, design : str
        Plan labels.
    kappa : float
        Budget loading.
    members : dict
        Scope to (single-run config, run id).
    store_root : str
        The result store.

    Returns
    -------
    frames : dict of pandas.DataFrame
        As :func:`c1_rq2.holdout_worker`.
    seconds : float
        Wall time.
    """
    frames, sec = rq2.holdout_worker(
        FAMILY, index, pricing, kappa, design, members, store_root
    )
    k = frames["kpis"]
    beta = members["individual"][0].evaluation.beta
    keep = (k["level"] == "portfolio") | (
        (k["level"] == "entity") & k["kpi"].isin(ENTITY_KPIS) & (k["eval_beta"] == beta)
    )
    frames["kpis"] = pd.DataFrame(k.loc[keep])
    return frames, sec


def run_rq2(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase rq2: scopes against each other per design, with ``cluster_separate``.

    Writes ``rq2_{kpis,paired,runs}.csv`` to ``args.full``.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    plan : dict
        The plan.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    groups: dict[tuple[str, str, float, str], dict[str, tuple[ExperimentConfig, str]]]
    groups = {}
    for r in holdout_runs(plan):
        key = (r.index, r.pricing, r.kappa, r.design)
        groups.setdefault(key, {})[r.scope] = (r.config, r.run_id)
    frames: dict[str, list[pd.DataFrame]] = {}
    with _pool(args.jobs) as pool:
        futs = {
            pool.submit(rq2_worker, *key, m, str(args.store)): key
            for key, m in groups.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            out, sec = fut.result()
            for name, frame in out.items():
                frames.setdefault(name, []).append(frame)
            print(f"[rq2 {i}/{len(futs)}] {_label(futs[fut])} {sec:.0f}s", flush=True)
    args.full.mkdir(parents=True, exist_ok=True)
    for name, parts in frames.items():
        pd.concat(parts, ignore_index=True).to_csv(
            args.full / f"rq2_{name}.csv", index=False, float_format="%.10g"
        )
    return {
        "rq2_groups": len(groups),
        "rq2_seconds": round(time.perf_counter() - t0, 1),
    }


# --------------------------------------------------------------------------
# Phase combination (MAR-182)
# --------------------------------------------------------------------------


def combination_worker(
    index: str,
    pricing: str,
    kappa: float,
    members: dict[comb.Design, tuple[ExperimentConfig, str]],
    store_root: str,
) -> tuple[dict[str, pd.DataFrame], float]:
    """:func:`c1_combination.holdout_worker` for one Florida variant.

    ``c1_combination`` keys its design and contrast lists by C1 family; the
    Florida plan has the main line's designs (MSE, E[U], weighted CVaR beta
    0.99 and 0.995), so the worker runs as ``"main"`` and the ``family``
    column is set to ``"florida"`` afterwards.

    Parameters
    ----------
    index, pricing : str
        Plan labels.
    kappa : float
        Budget loading.
    members : dict
        (scope, design) to (single-run config, run id).
    store_root : str
        The result store.

    Returns
    -------
    frames : dict of pandas.DataFrame
        ``grid``, ``contrasts``, ``runs``.
    seconds : float
        Wall time.
    """
    frames, sec = comb.holdout_worker(
        "main", index, pricing, kappa, members, store_root
    )
    for frame in frames.values():
        frame["family"] = FAMILY
    return frames, sec


def run_combination(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase combination: every MAR-182 contrast on the holdout test years.

    Writes ``combination_{grid,contrasts,runs}.csv`` to ``args.full``, after
    checking the decomposition identity and, if the rq1 and rq2 tables are
    there, that the two-term contrasts and the test KPIs equal theirs.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    plan : dict
        The plan.

    Returns
    -------
    dict
        Summary entries.
    """
    if tuple(plan["designs"]) != comb.DESIGNS["main"]:
        raise RuntimeError("the combination phase needs C1's main-line designs")
    t0 = time.perf_counter()
    groups: dict[
        tuple[str, str, float], dict[comb.Design, tuple[ExperimentConfig, str]]
    ]
    groups = {}
    for r in holdout_runs(plan):
        key = (r.index, r.pricing, r.kappa)
        groups.setdefault(key, {})[(r.scope, r.design)] = (r.config, r.run_id)
    frames: dict[str, list[pd.DataFrame]] = {}
    with _pool(args.jobs) as pool:
        futs = {
            pool.submit(combination_worker, *key, m, str(args.store)): key
            for key, m in groups.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            out, sec = fut.result()
            for name, frame in out.items():
                frames.setdefault(name, []).append(frame)
            print(f"[comb {i}/{len(futs)}] {_label(futs[fut])} {sec:.0f}s", flush=True)
    tables = {n: pd.concat(f, ignore_index=True) for n, f in frames.items()}
    n_dec = comb._check_decomposition(tables["contrasts"])
    checks = {"combination_decompositions_checked": n_dec}
    checks.update(_check_combination(tables, args.full))
    args.full.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(
            args.full / f"combination_{name}.csv", index=False, float_format="%.10g"
        )
    print(f"combination checks: {checks}", flush=True)
    return {
        "combination_groups": len(groups),
        **checks,
        "combination_seconds": round(time.perf_counter() - t0, 1),
    }


def _check_combination(tables: dict[str, pd.DataFrame], full: Path) -> dict[str, int]:
    """Cross-check the combination phase against the rq1 and rq2 phases.

    The three phases bootstrap the same designs on the same resample (the
    C1 resample of the holdout test years), so the combination's test KPIs
    must equal rq1's, its within-scope contrasts rq1's paired differences
    and its within-design contrasts rq2's scope differences. Each check runs
    if that phase's full tables are in ``full``.
    """
    out: dict[str, int] = {}
    con = tables["contrasts"]
    test = con.loc[(con["split"] == "test") & con["term_c"].eq("")].copy()
    test[["scope_a", "design_a"]] = test["term_a"].str.split("/", expand=True)
    test[["scope_b", "design_b"]] = test["term_b"].str.split("/", expand=True)
    test = test.drop_duplicates(
        ["eventset", "pricing", "kappa", "term_a", "term_b", "kpi", "eval_beta"]
    )
    tail_t = test["kpi"].isin(comb.TAIL_KPIS)
    if (full / "rq2_paired.csv").exists():
        rq2p = pd.read_csv(full / "rq2_paired.csv")
        rq2p = rq2p.loc[rq2p["split"] == "test"]
        cross = test.loc[test["design_a"] == test["design_b"]].copy()
        cross["design"] = cross["design_a"]
        k2 = ["eventset", "pricing", "kappa", "design", "scope_a", "scope_b", "kpi"]
        out["combination_contrasts_equal_rq2"] = comb._merge_check(
            cross, rq2p, k2, tail_t.loc[cross.index], "rq2 paired"
        )
    if not (full / "rq1_kpis.csv").exists():
        return out
    grid = tables["grid"]
    rq1k = pd.read_csv(full / "rq1_kpis.csv")
    rq1k = rq1k.loc[(rq1k["source"] == "c1_bootstrap") & (rq1k["eval_split"] == "test")]
    mine = grid.loc[(grid["split"] == "test") & (grid["kpi"] != "budget_use")].copy()
    key = ["eventset", "pricing", "kappa", "scope", "design", "kpi"]
    tail = mine["kpi"].isin(comb.TAIL_KPIS)
    n_kpis = 0
    for part, theirs, k in (
        (
            mine.loc[tail],
            rq1k.loc[rq1k["kpi"].isin(comb.TAIL_KPIS)],
            [*key, "eval_beta"],
        ),
        (
            mine.loc[~tail],
            rq1k.loc[~rq1k["kpi"].isin(comb.TAIL_KPIS)].drop_duplicates(key),
            key,
        ),
    ):
        merged = part.merge(
            theirs[[*k, "value", "ci_low", "ci_high"]],
            on=k,
            suffixes=("", "_rq1"),
            validate="one_to_one",
        )
        if len(merged) != len(part):
            raise RuntimeError(f"{len(part) - len(merged)} KPI rows not in rq1")
        for column in ("value", "ci_low", "ci_high"):
            comb._close(merged[column], merged[f"{column}_rq1"], f"rq1 {column}")
        n_kpis += len(merged)
    rq1p = pd.read_csv(full / "rq1_paired.csv")
    rq1p = rq1p.loc[rq1p["eval_split"] == "test"]
    same = test.loc[test["scope_a"] == test["scope_b"]].copy()
    same["scope"] = same["scope_a"]
    k1 = ["eventset", "pricing", "kappa", "scope", "design_a", "design_b", "kpi"]
    out["combination_contrasts_equal_rq1"] = comb._merge_check(
        same, rq1p, k1, tail_t.loc[same.index], "rq1 paired"
    )
    out["combination_kpi_rows_equal_rq1"] = n_kpis
    return out


# --------------------------------------------------------------------------
# Phase kfold: pooled out-of-sample KPIs and contrasts
# --------------------------------------------------------------------------


def run_kfold(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase kfold: pooled KPIs, MAR-182 contrasts and per-fold KPIs.

    The k-fold phase of ``c1_combination`` (and of ``c1_rq2``), per index:
    for each pricing, every design of the two objective sets on the one
    resample of all years (both sets must draw the same resample: checked),
    then the contrasts, checked against ``kfold.pooled_difference`` where
    both designs sit in one experiment config, and the decomposition.

    Writes ``kfold_{grid,contrasts,folds,runs}.csv`` to ``args.full``.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    plan : dict
        The plan.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    configs = kfold_configs(plan)
    store = ResultStore(args.store)
    grid: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    fold_rows: list[pd.DataFrame] = []
    n_native = 0
    for index in plan["indices"]:
        mine = [c for (i, *_), c in configs.items() if i == index]
        if not mine:
            continue
        first = mine[0]
        prepared = c1._prepared(first)
        measure = outcome_measure(
            prepared, Basis.ANNUAL, years=Sample.full(prepared).years
        )
        row_years = prepared.events["year"].to_numpy(dtype=np.int64)
        for pricing in plan["kfold"]["pricings"]:
            for kappa in plan["kfold"]["kappas"]:
                new, native, runs_, folds_ = _kfold_variant(
                    configs, store, prepared, measure, row_years, index, pricing, kappa
                )
                grid += new["grid"]
                rows += new["contrasts"]
                run_rows += runs_
                fold_rows += folds_
                n_native += comb._check_native(new["contrasts"], native, pricing)
                print(f"[kfold] {index} {pricing} k{kappa:g}", flush=True)
    con = pd.DataFrame(rows)
    n_dec = comb._check_decomposition(con)
    args.full.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(grid).to_csv(
        args.full / "kfold_grid.csv", index=False, float_format="%.10g"
    )
    con.to_csv(args.full / "kfold_contrasts.csv", index=False, float_format="%.10g")
    pd.concat(fold_rows, ignore_index=True).to_csv(
        args.full / "kfold_folds.csv", index=False, float_format="%.10g"
    )
    pd.DataFrame(run_rows).to_csv(args.full / "kfold_runs.csv", index=False)
    return {
        "kfold_k": int(plan["kfold"]["k"]),
        "kfold_experiment_config_hashes": {
            _label(k): config_hash(c) for k, c in configs.items()
        },
        "kfold_runs": len(run_rows),
        "kfold_checked_against_pooled_difference": n_native,
        "kfold_decompositions_checked": n_dec,
        "kfold_seconds": round(time.perf_counter() - t0, 1),
    }


def _kfold_variant(
    configs: dict[tuple[str, str, float, str], ExperimentConfig],
    store: ResultStore,
    prepared: EventSet,
    measure: Any,  # noqa: ANN401
    row_years: np.ndarray,
    index: str,
    pricing: str,
    kappa: float,
) -> tuple[
    dict[str, list[dict[str, Any]]],
    list[tuple[kfold.PooledKpis, dict[comb.Design, tuple[int, str]]]],
    list[dict[str, Any]],
    list[pd.DataFrame],
]:
    """Pool one (index, pricing, kappa) and contrast its designs."""
    boots: dict[float, dict[comb.Design, KpiBootstrap]] = {b: {} for b in EVAL_BETAS}
    hashes: dict[comb.Design, str] = {}
    native: list[tuple[kfold.PooledKpis, dict[comb.Design, tuple[int, str]]]] = []
    run_rows: list[dict[str, Any]] = []
    fold_rows: list[pd.DataFrame] = []
    resample_ref: YearResample | None = None
    labels = {"family": FAMILY, "eventset": index, "pricing": pricing, "kappa": kappa}
    for (i, p, k, _), cfg in configs.items():
        if (i, p, k) != (index, pricing, kappa):
            continue
        exp_hash = config_hash(cfg)
        run_ids: list[str] = []
        for s in cfg.single_runs():
            rid = rid_of(s)
            if not store.has_run(rid):
                raise RuntimeError(f"k-fold run {rid} missing: run the solve phase")
            run_ids.append(rid)
            design = design_of(s.objectives[0].model_dump(mode="json"))
            scope = s.scopes[0].kind
            runs = store.read("runs", run_ids=[rid])
            fold = getattr(s.sample, "fold", None)
            run_rows.append(
                {
                    "kind": "kfold",
                    **labels,
                    "scope": scope,
                    "design": design,
                    "fold": fold,
                    "n_problems": len(runs),
                    "statuses": ",".join(sorted(set(runs["status"].astype(str)))),
                    "solvers": ",".join(sorted(set(runs["solver"].astype(str)))),
                    "budget_use": comb._budget_use(store, rid, kappa),
                    "config_hash": config_hash(s),
                    "run_id": rid,
                    "experiment_config_hash": exp_hash,
                }
            )
            kp = store.read("kpis", run_ids=[rid])
            kp = kp.loc[kp["level"] == "portfolio"].copy()
            kp = kp.assign(**labels, scope=scope, design=design, fold=fold)
            kp["config_hash"] = config_hash(s)
            fold_rows.append(kp)
        pooled = kfold.pooled_kpis(cfg, store, prepared, run_ids)
        if pooled.failed or pooled.resample is None or pooled.level is None:
            raise RuntimeError(f"k-fold {index} {pricing}: not pooled {pooled.failed}")
        if resample_ref is None:
            resample_ref = pooled.resample
        elif not resample_ref.same_as(pooled.resample):
            raise RuntimeError("the k-fold configs drew different resamples")
        designs, failed = kfold.pooled_designs(cfg, store, prepared, run_ids)
        if failed:
            raise RuntimeError(f"k-fold {index} {pricing}: failed {failed}")
        ones = rq2._identity(pooled.resample)
        positions: dict[comb.Design, tuple[int, str]] = {}
        for d in designs:
            key = (d.scope, rq2._design_of(d.objective, cfg))
            positions[key] = (d.scope_position, d.objective)
            hashes[key] = exp_hash
            for beta in EVAL_BETAS:
                reps = kpi_replicates(
                    d.loss, d.payout, measure, row_years, pooled.resample, beta=beta
                )
                point = kpi_replicates(
                    d.loss, d.payout, measure, row_years, ones, beta=beta
                )
                boots[beta][key] = comb._pooled_bootstrap(
                    reps, point, beta, pooled.resample, pooled.level, exp_hash
                )
        native.append((pooled, positions))
    grid: list[dict[str, Any]] = []
    for beta, by_design in boots.items():
        for (scope, design), b in by_design.items():
            for r in comb._grid_rows(b.table, beta).itertuples():
                grid.append(
                    {
                        **labels,
                        "kpi": r.kpi,
                        "value": r.value,
                        "ci_low": r.ci_low,
                        "ci_high": r.ci_high,
                        "eval_beta": r.eval_beta,
                        "split": "pooled",
                        "scope": scope,
                        "design": design,
                        "config_hash": hashes[(scope, design)],
                    }
                )
    contrasts: list[dict[str, Any]] = []
    for beta in EVAL_BETAS:
        new = comb.contrast_rows(
            boots[beta], hashes, comb.contrasts("main"), split="pooled", beta=beta
        )
        for r in new:
            r.update(labels)
        contrasts += new
    return {"grid": grid, "contrasts": contrasts}, native, run_rows, fold_rows


# --------------------------------------------------------------------------
# Phase premium: cross-coverage and pricing diversification (C1 6b.5)
# --------------------------------------------------------------------------


def _train_portfolio(store: ResultStore, rid: str, kpi: str) -> float:
    k = store.read("kpis", run_ids=[rid])
    v = k.loc[
        (k["level"] == "portfolio") & (k["eval_split"] == "train") & (k["kpi"] == kpi),
        "value",
    ].unique()
    if len(v) != 1:
        raise RuntimeError(f"run {rid}: {len(v)} train {kpi} values")
    return float(v[0])


def matched_configs(plan: dict[str, Any], store: ResultStore) -> list[dict[str, Any]]:
    """Return the ``portfolio_matched`` configs: the portfolio problem at budget A.

    For every individual holdout run under the matched pricings: ``A`` is
    its train ``premium`` KPI at the portfolio level (the premium of the
    summed payout of its 67 designs), ``S`` the sum of its design problems'
    premiums (what its 67 budgets constrained). The derived config is the
    portfolio scope with the same design, pricing and sample and the budget
    loading ``A / E[L]`` (train), so that its aggregate premium may be at
    most ``A``.

    Parameters
    ----------
    plan : dict
        The plan.
    store : ResultStore
        The store with the individual runs.

    Returns
    -------
    list of dict
        Per individual run: labels, ``A``, ``S``, ``E[L]``, the loading, the
        derived config and its run id, and the run ids of the individual and
        portfolio runs.
    """
    runs = holdout_runs(plan)
    by = {(r.index, r.pricing, r.kappa, r.scope, r.design): r for r in runs}
    out: list[dict[str, Any]] = []
    bases = {i: base_config(plan, i) for i in plan["indices"]}
    for r in runs:
        if r.scope != "individual" or r.pricing not in plan["derived"].get(
            "portfolio_matched_pricings", []
        ):
            continue
        aggregate = _train_portfolio(store, r.run_id, "premium")
        el = _train_portfolio(store, r.run_id, "expected_loss")
        summed = float(store.read("runs", run_ids=[r.run_id])["premium"].sum())
        loading = aggregate / el
        cfg = derive(
            bases[r.index],
            plan,
            index=r.index,
            pricing=r.pricing,
            kappa=loading,
            scopes=["portfolio"],
            designs=[r.design],
            name=f"{FAMILY}-{r.index}-{MATCHED}",
        )
        out.append(
            {
                "index": r.index,
                "pricing": r.pricing,
                "kappa": r.kappa,
                "design": r.design,
                "aggregate_premium": aggregate,
                "sum_standalone_premiums": summed,
                "train_expected_loss": el,
                "budget": r.kappa * el,
                "matched_loading": loading,
                "config": cfg,
                "run_id": rid_of(cfg),
                "individual_run_id": r.run_id,
                "portfolio_run_id": by[
                    (r.index, r.pricing, r.kappa, "portfolio", r.design)
                ].run_id,
                "individual_config": r.config,
                "portfolio_config": by[
                    (r.index, r.pricing, r.kappa, "portfolio", r.design)
                ].config,
            }
        )
    return out


def premium_worker(item: dict[str, Any], store_root: str) -> tuple[pd.DataFrame, float]:
    """Bootstrap individual, portfolio_matched and portfolio on the C1 resample.

    Parameters
    ----------
    item : dict
        One entry of :func:`matched_configs`.
    store_root : str
        The result store.

    Returns
    -------
    frame : pandas.DataFrame
        Test (paired 90 % intervals) and train (point) differences
        ``portfolio_matched - individual``, ``portfolio - portfolio_matched``
        and ``portfolio - individual``, portfolio-level KPIs, every KPI beta.
    seconds : float
        Wall time.
    """
    start = time.perf_counter()
    store = ResultStore(Path(store_root))
    members = {
        "individual": (item["individual_config"], item["individual_run_id"]),
        MATCHED: (item["config"], item["run_id"]),
        "portfolio": (item["portfolio_config"], item["portfolio_run_id"]),
    }
    cfg0 = item["individual_config"]
    prepared = c1._prepared(cfg0)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    assert cfg0.bootstrap is not None
    resample = resample_years(
        test.years, cfg0.bootstrap.n_bootstrap, cfg0.bootstrap.rng()
    )
    comps = cfg0.to_components()
    designs = {
        name: rq2._stored(cfg, rid, store) for name, (cfg, rid) in members.items()
    }
    rows: list[pd.DataFrame] = []
    for beta in EVAL_BETAS:
        boots: dict[str, KpiBootstrap] = {}
        train_v: dict[str, pd.Series] = {}
        for name, d in designs.items():
            boot = bootstrap_kpis(
                prepared,
                d.scope,
                d.results,
                basis=comps.basis,
                beta=beta,
                run_id=d.run_id,
                resample=resample,
                sample=test,
                pricing=comps.pricing,
                level=cfg0.bootstrap.level,
            )
            boots[name] = rq2.portfolio_rows(boot)
            tr = evaluate_kpis(
                prepared,
                d.scope,
                d.results,
                basis=comps.basis,
                beta=beta,
                run_id=d.run_id,
                sample=train,
                pricing=comps.pricing,
            )
            train_v[name] = tr.loc[tr["level"] == "portfolio"].set_index("kpi")["value"]
        for a, b in (
            (MATCHED, "individual"),
            ("portfolio", MATCHED),
            ("portfolio", "individual"),
        ):
            diff = paired_difference(boots[a], boots[b])
            diff = diff.assign(split="test", scope_a=a, scope_b=b, eval_beta=beta)
            rows.append(diff)
            tr = pd.DataFrame(
                {
                    "kpi": train_v[a].index,
                    "value_a": train_v[a].to_numpy(),
                    "value_b": train_v[b][train_v[a].index].to_numpy(),
                }
            )
            tr["difference"] = tr["value_a"] - tr["value_b"]
            rows.append(tr.assign(split="train", scope_a=a, scope_b=b, eval_beta=beta))
    frame = pd.concat(rows, ignore_index=True)
    frame = frame.assign(
        family=FAMILY,
        eventset=item["index"],
        pricing=item["pricing"],
        kappa=item["kappa"],
        design=item["design"],
        config_hash_a=frame["scope_a"].map(lambda s: designs[s].config_hash),
        config_hash_b=frame["scope_b"].map(lambda s: designs[s].config_hash),
    )
    return frame, time.perf_counter() - start


def run_premium(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase premium: solve the ``portfolio_matched`` runs and pair them.

    Writes ``premium_split.csv`` (the paired differences) and
    ``premiums.csv`` (``A``, ``S``, the credit ``1 - A / S``, the matched
    loading and the runs' premiums and budget use) to ``args.full``.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    plan : dict
        The plan.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    store = ResultStore(args.store)
    items = matched_configs(plan, store)
    seconds = solve_all({i["run_id"]: i["config"] for i in items}, store, args.jobs)
    check_ok(store, (i["run_id"] for i in items))
    frames: list[pd.DataFrame] = []
    with _pool(args.jobs) as pool:
        futs = {pool.submit(premium_worker, it, str(args.store)): it for it in items}
        for n, fut in enumerate(as_completed(futs), 1):
            frame, sec = fut.result()
            frames.append(frame)
            it = futs[fut]
            label = _label((it["index"], it["pricing"], it["kappa"], it["design"]))
            print(f"[premium {n}/{len(futs)}] {label} {sec:.0f}s", flush=True)
    args.full.mkdir(parents=True, exist_ok=True)
    pd.concat(frames, ignore_index=True).to_csv(
        args.full / "premium_split.csv", index=False, float_format="%.10g"
    )
    _premium_rows(items, store).to_csv(
        args.full / "premiums.csv", index=False, float_format="%.10g"
    )
    return {
        "premium_matched_runs": len(items),
        "premium_solved_this_call": len(seconds),
        "premium_seconds": round(time.perf_counter() - t0, 1),
    }


# --------------------------------------------------------------------------
# Phase matched: solve the portfolio_matched runs, write premiums.csv
# --------------------------------------------------------------------------


def _premium_rows(items: list[dict[str, Any]], store: ResultStore) -> pd.DataFrame:
    """One row per individual design under the load: A, S, credit, matched run."""
    rows = []
    for it in items:
        matched = store.read("runs", run_ids=[it["run_id"]])
        port = store.read("runs", run_ids=[it["portfolio_run_id"]])
        rows.append(
            {
                "family": FAMILY,
                "eventset": it["index"],
                "pricing": it["pricing"],
                "kappa": it["kappa"],
                "design": it["design"],
                "train_expected_loss": it["train_expected_loss"],
                "budget": it["budget"],
                "individual_sum_standalone_premiums": it["sum_standalone_premiums"],
                "individual_aggregate_premium": it["aggregate_premium"],
                "pricing_credit": 1.0
                - it["aggregate_premium"] / it["sum_standalone_premiums"],
                "matched_loading": it["matched_loading"],
                "matched_premium": float(matched["premium"].sum()),
                "matched_budget_use": float(matched["premium"].sum())
                / it["aggregate_premium"],
                "matched_status": ",".join(sorted(set(matched["status"].astype(str)))),
                "matched_solver": ",".join(sorted(set(matched["solver"].astype(str)))),
                "portfolio_premium": float(port["premium"].sum()),
                "portfolio_budget_use": float(port["premium"].sum()) / it["budget"],
                "matched_config_hash": config_hash(it["config"]),
                "individual_config_hash": config_hash(it["individual_config"]),
                "portfolio_config_hash": config_hash(it["portfolio_config"]),
                "matched_run_id": it["run_id"],
            }
        )
    return pd.DataFrame(rows)


def run_matched(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase matched: solve the ``portfolio_matched`` runs (C1 section 6b.5).

    Writes ``premiums.csv`` to ``args.full``: per individual design under the
    load, ``A``, ``S``, the credit ``1 - A / S``, the matched loading and
    the matched and portfolio runs' premiums and budget use.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    plan : dict
        The plan.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    store = ResultStore(args.store)
    items = matched_configs(plan, store)
    seconds = solve_all({i["run_id"]: i["config"] for i in items}, store, args.jobs)
    check_ok(store, (i["run_id"] for i in items))
    args.full.mkdir(parents=True, exist_ok=True)
    _premium_rows(items, store).to_csv(
        args.full / "premiums.csv", index=False, float_format="%.10g"
    )
    return {
        "matched_runs": len(items),
        "matched_solved_this_call": len(seconds),
        "matched_seconds": round(time.perf_counter() - t0, 1),
        "matched_solve_seconds_per_run": seconds,
    }


# --------------------------------------------------------------------------
# Phase holdout: every holdout comparison on one resample per variant
# --------------------------------------------------------------------------

PAIRS: Final[tuple[tuple[str, str], ...]] = (
    (rq2.SEPARATE, "individual"),
    ("cluster", rq2.SEPARATE),
    (MATCHED, "individual"),
    ("portfolio", MATCHED),
)
"""Scope pairs of the derived designs: the cluster index part and joint part
(C1 6b.6), cross-coverage and pricing diversification (C1 6b.5)."""


def holdout_worker(
    index: str,
    pricing: str,
    kappa: float,
    members: dict[comb.Design, tuple[ExperimentConfig, str]],
    matched: dict[str, tuple[ExperimentConfig, str]],
    store_root: str,
) -> tuple[dict[str, pd.DataFrame], float]:
    """Bootstrap one variant's designs on one resample; contrast and pair them.

    One worker per (index, pricing, kappa) does what ``c1_combination``'s
    and ``c1_rq2``'s holdout workers and :func:`premium_worker` do together,
    so each design is bootstrapped once: the 3 scopes x 4 designs of the
    plan, the ``cluster_separate`` design of each objective (solved here)
    and, under the load, the ``portfolio_matched`` designs (from the store).
    All on the C1 resample of the holdout test years (B 1000, seed 0).

    Parameters
    ----------
    index, pricing : str
        Plan labels.
    kappa : float
        Budget loading.
    members : dict
        (scope, design) to (single-run config, run id) of the plan's runs.
    matched : dict
        Design to (config, run id) of its ``portfolio_matched`` run; empty
        under pure pricing.
    store_root : str
        The result store.

    Returns
    -------
    frames : dict of pandas.DataFrame
        ``grid`` (train and test portfolio KPIs, budget use), ``contrasts``
        (every ``c1_combination`` contrast, train and test), ``pairs`` (the
        :data:`PAIRS` differences, test with paired intervals, train point
        values), ``entities`` (expected payout and loss per payout entity,
        train and test, at the config's evaluation beta) and ``runs``.
    seconds : float
        Wall time.
    """
    start = time.perf_counter()
    store = ResultStore(Path(store_root))
    cfg0 = members[("individual", "mse")][0]
    prepared = c1._prepared(cfg0)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    assert cfg0.bootstrap is not None
    resample = resample_years(
        test.years, cfg0.bootstrap.n_bootstrap, cfg0.bootstrap.rng()
    )
    level = cfg0.bootstrap.level
    comps = cfg0.to_components()
    basis, price = comps.basis, comps.pricing
    config_beta = cfg0.evaluation.beta

    designs: dict[comb.Design, rq2._Design] = {}
    loadings: dict[comb.Design, float] = {}
    for key, (cfg, rid) in members.items():
        designs[key] = rq2._stored(cfg, rid, store)
        loadings[key] = kappa
    for d in sorted({k[1] for k in members}):
        cl = designs[("cluster", d)]
        scope = cl.scope
        if not isinstance(scope, Cluster):
            raise RuntimeError("the cluster run's scope is not a Cluster")
        joint = [r.spec for r in cl.results]
        if scope.partition(train.select(prepared)) != tuple(joint):
            raise RuntimeError(f"{index} {pricing} k{kappa} {d}: cluster partition")
        designs[(rq2.SEPARATE, d)] = rq2._solved(
            rq2.SEPARATE,
            rq2.SeparateClusters(scope),
            members[("cluster", d)][0],
            prepared,
            train,
            rq2.separate_specs(joint),
            DEFAULT_POLICY,
            cl.config_hash,
        )
        loadings[(rq2.SEPARATE, d)] = kappa
    for d, (cfg, rid) in matched.items():
        designs[(MATCHED, d)] = rq2._stored(cfg, rid, store)
        loadings[(MATCHED, d)] = float(cfg.constraints[0].model_dump()["loading"])

    boots: dict[float, dict[comb.Design, KpiBootstrap]] = {b: {} for b in EVAL_BETAS}
    train_values: dict[float, dict[comb.Design, pd.Series]] = {
        b: {} for b in EVAL_BETAS
    }
    hashes = {k: d.config_hash for k, d in designs.items()}
    grid: list[pd.DataFrame] = []
    entities: list[pd.DataFrame] = []
    run_rows: list[dict[str, Any]] = []
    for key, d in designs.items():
        locs = rq2._entity_locations(d)
        for beta in EVAL_BETAS:
            boot = bootstrap_kpis(
                prepared,
                d.scope,
                d.results,
                basis=basis,
                beta=beta,
                run_id=d.run_id,
                resample=resample,
                sample=test,
                pricing=price,
                level=level,
            )
            pb = rq2.portfolio_rows(boot)
            boots[beta][key] = pb
            tr = evaluate_kpis(
                prepared,
                d.scope,
                d.results,
                basis=basis,
                beta=beta,
                run_id=d.run_id,
                sample=train,
                pricing=price,
            )
            trp = tr.loc[tr["level"] == "portfolio"]
            train_values[beta][key] = trp.set_index("kpi")["value"]
            for split, table in (("test", pb.table), ("train", trp)):
                g = comb._grid_rows(table, beta)
                g["split"], g["scope"], g["design"] = split, key[0], key[1]
                g["config_hash"] = d.config_hash
                grid.append(g)
            if beta != config_beta:
                continue
            te = evaluate_kpis(
                prepared,
                d.scope,
                d.results,
                basis=basis,
                beta=beta,
                run_id=d.run_id,
                sample=test,
                pricing=price,
            )
            for split, table in (("train", tr), ("test", te)):
                e = table.loc[
                    (table["level"] == "entity") & table["kpi"].isin(ENTITY_KPIS),
                    ["subject_id", "kpi", "value"],
                ].copy()
                e["split"], e["scope"], e["design"] = split, key[0], key[1]
                e["entity_locations"] = e["subject_id"].map(locs)
                e["config_hash"] = d.config_hash
                entities.append(e)
        el = float(train_values[config_beta][key]["expected_loss"])
        use = float(sum(r.premium for r in d.results)) / (loadings[key] * el)
        grid.append(
            pd.DataFrame(
                [
                    {
                        "kpi": "budget_use",
                        "value": use,
                        "ci_low": math.nan,
                        "ci_high": math.nan,
                        "eval_beta": math.nan,
                        "split": "train",
                        "scope": key[0],
                        "design": key[1],
                        "config_hash": d.config_hash,
                    }
                ]
            )
        )
        run_rows.append(
            {
                "kind": "holdout" if key[0] in SCOPE_KINDS else "derived",
                "scope": key[0],
                "design": key[1],
                "n_problems": len(d.results),
                "statuses": d.statuses,
                "solvers": d.solvers,
                "budget_use": use,
                "loading": loadings[key],
                "config_hash": d.config_hash,
                "run_id": d.run_id,
                "base_config_hash": (
                    designs[("cluster", key[1])].config_hash
                    if key[0] == rq2.SEPARATE
                    else d.config_hash
                ),
            }
        )

    items = comb.contrasts("main")
    rows: list[dict[str, Any]] = []
    pairs: list[pd.DataFrame] = []
    for beta in EVAL_BETAS:
        rows += comb.contrast_rows(boots[beta], hashes, items, split="test", beta=beta)
        rows += comb.train_contrast_rows(train_values[beta], hashes, items, beta=beta)
        for d in sorted({k[1] for k in members}):
            for a_, b_ in PAIRS:
                a, b = (a_, d), (b_, d)
                if a not in designs or b not in designs:
                    continue
                diff = paired_difference(boots[beta][a], boots[beta][b])
                pairs.append(
                    diff.assign(
                        split="test",
                        scope_a=a_,
                        scope_b=b_,
                        design=d,
                        eval_beta=beta,
                        config_hash_a=hashes[a],
                        config_hash_b=hashes[b],
                    )
                )
                va, vb = train_values[beta][a], train_values[beta][b]
                tr = pd.DataFrame(
                    {"kpi": va.index, "value_a": va.to_numpy(), "value_b": vb[va.index]}
                )
                tr["difference"] = tr["value_a"] - tr["value_b"]
                pairs.append(
                    tr.assign(
                        split="train",
                        scope_a=a_,
                        scope_b=b_,
                        design=d,
                        eval_beta=beta,
                        config_hash_a=hashes[a],
                        config_hash_b=hashes[b],
                    )
                )
    frames = {
        "grid": pd.concat(grid, ignore_index=True),
        "contrasts": pd.DataFrame(rows),
        "pairs": pd.concat(pairs, ignore_index=True),
        "entities": pd.concat(entities, ignore_index=True),
        "runs": pd.DataFrame(run_rows),
    }
    for frame in frames.values():
        frame.insert(0, "kappa", kappa)
        frame.insert(0, "pricing", pricing)
        frame.insert(0, "eventset", index)
        frame.insert(0, "family", FAMILY)
    return frames, time.perf_counter() - start


SCOPE_KINDS: Final[frozenset[str]] = frozenset({"individual", "cluster", "portfolio"})


def _check_pairs(con: pd.DataFrame, pairs: pd.DataFrame) -> int:
    """Raise unless the premium split adds up, on every test row.

    (matched - individual) + (portfolio - matched) must equal portfolio -
    individual, the ``adds_rq2`` or ``rq2_alone`` contrast.
    """
    key = ["eventset", "pricing", "kappa", "design", "kpi", "eval_beta"]
    p = pairs.loc[pairs["split"] == "test"].set_index([*key, "scope_a", "scope_b"])[
        "difference"
    ]
    c = con.loc[(con["split"] == "test") & con["joint_scope"].eq("portfolio")]
    c = c.loc[c["contrast"].isin(["adds_rq2", "rq2_alone"])].copy()
    c["design"] = np.where(
        c["contrast"] == "adds_rq2", c["tail_design"], c["base_design"]
    )
    n = 0
    for r in c.itertuples():
        k = (r.eventset, r.pricing, r.kappa, r.design, r.kpi, r.eval_beta)
        try:
            cross = p[(*k, MATCHED, "individual")]
            diversification = p[(*k, "portfolio", MATCHED)]
        except KeyError:
            continue
        if not math.isclose(
            float(cross + diversification), float(r.value), rel_tol=1e-9, abs_tol=1e-3
        ):
            raise RuntimeError(f"premium split does not add up: {k}")
        n += 1
    return n


def run_holdout(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase holdout: :func:`holdout_worker` per (index, pricing, kappa).

    Needs the ``solve`` and ``matched`` phases. Writes
    ``holdout_{grid,contrasts,pairs,entities,runs}.csv`` to ``args.full``
    after checking the decomposition identity of every contrast and that
    the premium split adds up to portfolio - individual.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    plan : dict
        The plan.

    Returns
    -------
    dict
        Summary entries.
    """
    if tuple(plan["designs"]) != comb.DESIGNS["main"]:
        raise RuntimeError("the holdout phase needs C1's main-line designs")
    t0 = time.perf_counter()
    store = ResultStore(args.store)
    runs = holdout_runs(plan)
    check_ok(store, (r.run_id for r in runs))
    groups: dict[
        tuple[str, str, float], dict[comb.Design, tuple[ExperimentConfig, str]]
    ]
    groups = {}
    for r in runs:
        groups.setdefault((r.index, r.pricing, r.kappa), {})[(r.scope, r.design)] = (
            r.config,
            r.run_id,
        )
    matched: dict[tuple[str, str, float], dict[str, tuple[ExperimentConfig, str]]] = {}
    for it in matched_configs(plan, store):
        if not store.has_run(it["run_id"]):
            raise RuntimeError("portfolio_matched run missing: run the matched phase")
        key = (it["index"], it["pricing"], it["kappa"])
        matched.setdefault(key, {})[it["design"]] = (it["config"], it["run_id"])
    frames: dict[str, list[pd.DataFrame]] = {}
    seconds: dict[str, float] = {}
    with _pool(args.jobs) as pool:
        futs = {
            pool.submit(
                holdout_worker, *key, m, matched.get(key, {}), str(args.store)
            ): key
            for key, m in groups.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            out, sec = fut.result()
            for name, frame in out.items():
                frames.setdefault(name, []).append(frame)
            seconds[_label(futs[fut])] = round(sec, 1)
            print(
                f"[holdout {i}/{len(futs)}] {_label(futs[fut])} {sec:.0f}s", flush=True
            )
    tables = {n: pd.concat(f, ignore_index=True) for n, f in frames.items()}
    n_dec = comb._check_decomposition(tables["contrasts"])
    n_pairs = _check_pairs(tables["contrasts"], tables["pairs"])
    args.full.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(
            args.full / f"holdout_{name}.csv", index=False, float_format="%.10g"
        )
    print(
        f"holdout: {n_dec} decompositions, {n_pairs} premium splits checked", flush=True
    )
    return {
        "holdout_groups": len(groups),
        "holdout_decompositions_checked": n_dec,
        "holdout_premium_splits_checked": n_pairs,
        "holdout_seconds": round(time.perf_counter() - t0, 1),
        "holdout_seconds_per_group": seconds,
    }


# --------------------------------------------------------------------------
# Phase guard: degenerate clustering tail (MAR-172), filters, statuses
# --------------------------------------------------------------------------


def _zero_share(data: EventSet) -> float:
    p = data.rates / data.rates.sum()
    return float(p[data.loss.sum(axis=1) <= 0.0].sum())


def run_guard(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Phase guard: the checks of MAR-202 scope item 5, on every run.

    Writes ``guard_samples.csv`` (zero-loss share per calibration sample)
    and ``guard_runs.csv`` (statuses, solvers, filters and the manifest's
    flags, if any, per stored run) to ``args.full``.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    plan : dict
        The plan.

    Returns
    -------
    dict
        Summary entries.
    """
    store = ResultStore(args.store)
    samples: list[dict[str, Any]] = []
    for index in plan["indices"]:
        cfg = load_config(Path(plan["_dir"]) / plan["indices"][index]["config"])
        raw = c1._input(cfg).eventset
        prepared = c1._prepared(cfg)
        cluster = next(s for s in cfg.scopes if s.kind == "cluster")
        beta_tail = float(cluster.model_dump(mode="json")["strategy"]["beta_tail"])
        filters = [dataclasses.asdict(f) for f in prepared.metadata.filters]
        base = {
            "eventset": index,
            "beta_tail": beta_tail,
            "unfiltered_zero_loss_share": _zero_share(raw),
            "unfiltered_rows": raw.n_rows,
            "filters": json.dumps(filters, default=str),
        }
        train, test = splits.holdout(prepared, train_fraction=0.7)
        parts = [("holdout", -1, "train", train), ("holdout", -1, "test", test)]
        for f, (tr, te) in enumerate(
            splits.year_block_kfold(prepared, k=int(plan["kfold"]["k"]))
        ):
            parts += [("kfold", f, "train", tr), ("kfold", f, "test", te)]
        for split, fold, part, sample in parts:
            data = sample.select(prepared)
            share = _zero_share(data)
            samples.append(
                {
                    **base,
                    "split": split,
                    "fold": fold,
                    "sample": part,
                    "rows": data.n_rows,
                    "zero_loss_share": share,
                    "guard_fires": share >= beta_tail,
                }
            )
    rows: list[dict[str, Any]] = []
    for rid in store.run_ids():
        m = store.manifest(rid)
        rows.append(_guard_row(rid, m))
    args.full.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(samples).to_csv(args.full / "guard_samples.csv", index=False)
    runs = pd.DataFrame(rows)
    runs.to_csv(args.full / "guard_runs.csv", index=False)
    return {
        "guard_samples": len(samples),
        "guard_fires": int(sum(s["guard_fires"] for s in samples)),
        "guard_runs_scanned": len(rows),
    }


def _guard_row(rid: str, manifest: dict[str, Any]) -> dict[str, Any]:
    problems = manifest.get("problems", [])
    flags = manifest.get("flags")
    prepared = manifest.get("prepared_eventset", {})
    return {
        "run_id": rid,
        "config_hash": manifest.get("cache_key", {}).get("config_hash"),
        "statuses": ",".join(sorted({str(p.get("status")) for p in problems})),
        "n_problems": len(problems),
        "evaluated": bool(manifest.get("evaluation", {}).get("evaluated")),
        "flags": json.dumps(flags, default=str) if flags is not None else "",
        "prepared_eventset": json.dumps(prepared, default=str)[:2000],
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

PHASES: Final[tuple[str, ...]] = (
    "solve",
    "matched",
    "holdout",
    "kfold",
    "guard",
    "rq1",
    "rq2",
    "combination",
    "premium",
)
DEFAULT_PHASES: Final[tuple[str, ...]] = (
    "solve",
    "matched",
    "holdout",
    "kfold",
    "guard",
)
"""``rq1``, ``rq2``, ``combination`` and ``premium`` bootstrap the same
designs again, one C1 worker each; ``holdout`` does all of it in one pass.
They are kept to cross-check it (they agreed on the subset run of the note)."""


def main(argv: list[str] | None = None) -> int:
    """Run the requested phases and write the full tables.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description="Florida rerun (MAR-202).")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument(
        "--phases", nargs="+", default=list(DEFAULT_PHASES), choices=PHASES
    )
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--full", type=Path, default=FULL_DIR)
    parser.add_argument("--plan", type=Path, default=PLAN, help="plan YAML")
    parser.add_argument("--plan-only", action="store_true", help="print counts")
    args = parser.parse_args(argv)
    plan = load_plan(args.plan)
    if args.plan_only:
        runs = holdout_runs(plan)
        n_kfold = sum(len(c.single_runs()) for c in kfold_configs(plan).values())
        print(f"{len(runs)} holdout runs, {n_kfold} k-fold runs")
        return 0
    common: dict[str, Any] = {
        "issue": "MAR-202",
        "plan": str(args.plan.resolve().relative_to(REPO_ROOT)),
        "package_versions": package_versions(),
        "solver_policy": "DEFAULT_POLICY",
    }
    args.full.mkdir(parents=True, exist_ok=True)
    runners = {
        "solve": run_solve,
        "matched": run_matched,
        "holdout": run_holdout,
        "rq1": run_rq1,
        "rq2": run_rq2,
        "combination": run_combination,
        "kfold": run_kfold,
        "premium": run_premium,
        "guard": run_guard,
    }
    for name in PHASES:
        if name not in args.phases:
            continue
        t = time.perf_counter()
        summary = {**common, **runners[name](args, plan)}
        summary["phase_seconds"] = round(time.perf_counter() - t, 1)
        (args.full / f"summary_{name}.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
        print(f"phase {name} done in {summary['phase_seconds']}s", flush=True)
    print(f"wrote {args.full}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
