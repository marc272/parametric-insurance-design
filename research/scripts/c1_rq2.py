r"""Checkpoint C1, portfolio addendum (MAR-158, RQ2): joint vs individual calibration.

Question (MAR-158): at the same budget, does joint calibration (portfolio or
cluster scope) lower the owner's shortfall against individual calibration,
out of sample, under each objective (MSE, E[U], weighted CVaR), under
realistic basis risk and loaded pricing?

The C1 grid (``c1_checkpoint.py``) compares objectives *within* a scope. This
script compares the scopes with each other, per objective, and reuses the C1
designs: it reads them from the C1 result store (``results/c1/store``,
not committed) and solves nothing it can reuse. Two phases:

``holdout``
    For every main-line variant (pricing pure, cost of capital r 0.06 and
    0.10 with q 0.99; kappa 0.5, 1, 1.5) and design (MSE, E[U], weighted
    CVaR beta 0.99 and 0.995), and for the provisional F-12 variants of C1
    section 6 (four EventSets, pure and r 0.06, kappa 1; MSE, E[U], weighted
    CVaR beta 0.99; the F-12 EventSets in ``results/c1/eventsets``):

    * rebuilds the individual, cluster and portfolio designs of the C1 run;
    * solves one **derived** design, ``cluster_separate``: the cluster
      scope's three entities (same clusters, same value-weighted index) each
      calibrated on its own with its own budget kappa * E[L_cluster]. With
      it the cluster-vs-individual difference splits into an index part
      (``cluster_separate`` - ``individual``) and a joint-calibration part
      (``cluster`` - ``cluster_separate``). Not a runner run: its id is
      ``derived:`` + the SHA-256 of the base cluster run's config hash and
      the derivation (``runs.csv``);
    * at kappa 1 on the main line, re-solves the cluster and portfolio
      designs with another solver order (``ALT_POLICY``: HiGHS first for LPs,
      CLARABEL first for QPs), to see whether the per-asset payout split of
      a joint design is unique (MAR-100) and whether a second optimum moves
      the test KPIs;
    * bootstraps the **test** KPIs of all of them at KPI beta 0.95, 0.99 and
      0.995 on **one** year resample (B = 1000, seed 0: the C1 resample), so
      differences between scopes are paired, and checks the C1 scopes'
      point values and intervals against the C1 tables;
    * evaluates the train KPIs (in sample, point values).

    ``bootstrap.paired_difference`` pairs KPI rows on ``PAIR_KEY``, which
    includes ``problem_id``: the individual scope's portfolio rows have
    ``problem_id = "*"`` (several design problems), the joint scopes'
    ``"portfolio"``, so it refuses to pair them as they are. The script
    restricts both ``KpiBootstrap`` objects to their portfolio-level rows
    and gives both the same ``problem_id`` label (:func:`portfolio_rows`),
    then calls ``paired_difference`` unchanged: its resample check still
    applies, and the replicates are not touched. No library code changes.

``kfold``
    Year-block 5-fold runs (MAR-22) of the same design problems at kappa 1,
    pricing pure and r 0.06, through the runner (store
    ``results/c1-rq2/store``, not committed), and their **pooled**
    out-of-sample KPIs (MAR-151, ``experiment.kfold.pooled_kpis``: every
    year evaluated by the design that did not see it; one resample of all
    10,000 years shared by every design). Cross-scope differences come from
    ``kfold.pooled_difference`` at the config's evaluation beta (0.99) and
    from ``kpi_replicates`` of ``pooled_designs`` at 0.95 and 0.995. The
    per-fold train and test KPIs that the runner stored are kept too.

``ranges``
    How unique is a joint design's split across entities (MAR-100, MAR-161
    F8)? For the cluster and portfolio designs at kappa 1 (pure and r 0.06):
    re-solve the C1 design problem, then minimise and maximise each entity's
    train expected payout over the designs whose objective is within
    ``RANGE_REL_TOL`` of the optimum.

Outputs (portfolio-level KPIs, plus **payout per entity only**: no per-asset
uncovered-loss or premium KPIs of joint designs, MAR-98, MAR-100). The full
tables go to ``results/c1-rq2/full/`` (not committed); the committed ones,
each under the 500 kB pre-commit limit, to ``research/data/c1-rq2/``:

* ``scope_kpis.csv``: portfolio KPIs per split (train, test, pooled), design
  and scope, with intervals (test, pooled);
* ``scope_paired.csv``: scope differences (test and pooled: paired 90 %
  intervals; train: point differences);
* ``entity_payouts.csv``: expected payout and expected loss per payout
  entity (asset or cluster), train and test, with shares;
* ``premiums.csv``: aggregate premium against the sum of the design
  problems' premiums, expected payout, budget;
* ``kfold_folds.csv``: the k-fold runs' per-fold portfolio KPIs;
* ``payout_ranges.csv``: the ``ranges`` phase;
* ``scope_kpis_f12.csv``, ``scope_paired_f12.csv``: the F-12 rows;
* ``runs.csv``: every design (config hash or ``derived:`` id, statuses,
  solvers), C1, derived and k-fold;
* ``summary.json``: inputs, checks, timings (merged from the full tables'
  ``summary_<phase>.json``).

Run from the repository root, after ``c1_checkpoint.py`` (its store)::

    uv run python research/scripts/c1_rq2.py --jobs 4
    uv run python research/scripts/c1_rq2_tables.py

Observations only. The interpretation is the owner's (MAR-29 section 8).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Any, ClassVar, Final

import c1_checkpoint as c1
import cvxpy as cp
import numpy as np
import pandas as pd

from parametric_insurance_design import splits
from parametric_insurance_design.basis import Basis, outcome_measure
from parametric_insurance_design.bootstrap import (
    KpiBootstrap,
    YearResample,
    bootstrap_kpis,
    kpi_replicates,
    paired_difference,
    percentile_interval,
    resample_years,
)
from parametric_insurance_design.errors import EntityMismatchError
from parametric_insurance_design.evaluate import kpis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment import kfold
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import package_versions, run_key
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.index import location_columns
from parametric_insurance_design.interfaces import (
    DesignProblem,
    ProblemSpec,
    Sample,
    Scope,
    SolveResult,
)
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.records import ALL_PROBLEMS, KpiName
from parametric_insurance_design.scopes import Cluster
from parametric_insurance_design.solve import DEFAULT_POLICY, SolverPolicy, solve

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
C1_FULL: Final[Path] = REPO_ROOT / "results" / "c1" / "full"
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "c1-rq2"
FULL_DIR: Final[Path] = REPO_ROOT / "results" / "c1-rq2" / "full"
KFOLD_STORE: Final[Path] = REPO_ROOT / "results" / "c1-rq2" / "store"

DESIGNS: Final[tuple[str, ...]] = ("mse", "eu", "wcvar@0.99", "wcvar@0.995")
F12_DESIGNS: Final[tuple[str, ...]] = ("mse", "eu", "wcvar@0.99")
"""The F-12 family has no weighted-CVaR beta 0.995 design (C1 section 6)."""
EVAL_BETAS: Final[tuple[float, ...]] = c1.ANNUAL_EVAL_BETAS
SCOPES: Final[tuple[str, ...]] = c1.SCOPES
SEPARATE: Final[str] = "cluster_separate"
ALT_SUFFIX: Final[str] = "_alt"
PAIRS: Final[tuple[tuple[str, str], ...]] = (
    ("portfolio", "individual"),
    ("cluster", "individual"),
    ("cluster", "portfolio"),
    (SEPARATE, "individual"),
    ("cluster", SEPARATE),
    ("portfolio" + ALT_SUFFIX, "portfolio"),
    ("cluster" + ALT_SUFFIX, "cluster"),
)
"""Scope differences ``a - b``; the ``_alt`` pairs exist at kappa 1 only."""
PORTFOLIO_KPIS: Final[tuple[str, ...]] = (
    "expected_loss",
    "expected_payout",
    "expected_uncovered",
    "var_uncovered",
    "cvar_uncovered",
    "rmse_residual",
    "correlation",
    "premium",
)
TAIL_KPIS: Final[frozenset[str]] = frozenset({"var_uncovered", "cvar_uncovered"})
ALT_POLICY: Final[SolverPolicy] = SolverPolicy(
    lp_solvers=("HIGHS", "CLARABEL", "SCS"), qp_solvers=("CLARABEL", "OSQP")
)
"""Another solver order, to probe the uniqueness of joint designs (MAR-100)."""
KFOLD_K: Final[int] = 5
KFOLD_PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06")
KFOLD_OBJECTIVE_SETS: Final[dict[str, list[dict[str, Any]]]] = {
    "a": [
        {"kind": "mse"},
        {"kind": "expected_uncovered"},
        {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.99},
    ],
    "b": [{"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.995}],
}
"""Two k-fold configs per pricing: ``pooled_difference`` keys a design by
objective name, so the two weighted-CVaR betas go into separate configs (one
resample each, drawn from the same seed over the same years: checked)."""
OBJECTIVE_DESIGN: Final[dict[tuple[str, float | None], str]] = {
    ("mse", None): "mse",
    ("expected_uncovered", None): "eu",
    ("weighted_cvar", 0.99): "wcvar@0.99",
    ("weighted_cvar", 0.995): "wcvar@0.995",
}


# --------------------------------------------------------------------------
# The derived scope: the cluster entities, calibrated one by one
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SeparateClusters(Scope):
    """The cluster scope's entities, each its own design problem (research only).

    Same partition and index as the wrapped :class:`Cluster`, but one design
    problem (and so one budget) per cluster, ``problem_id`` = the cluster's
    ``entity_id``. Not a library scope: it exists to separate the index
    effect of the cluster scope from its joint calibration (MAR-158 item 6).

    Parameters
    ----------
    cluster : Cluster
        The cluster scope of the C1 run.
    """

    name: ClassVar[str] = SEPARATE

    cluster: Cluster

    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        """One spec per cluster of ``cluster.partition``.

        Parameters
        ----------
        eventset : EventSet
            Calibration data.

        Returns
        -------
        tuple of ProblemSpec
            One single-entity spec per cluster.
        """
        return separate_specs(self.cluster.partition(eventset))

    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        """One cluster's design problem: value-weighted index, summed loss.

        Parameters
        ----------
        eventset : EventSet
            Any EventSet with the cluster's locations.
        spec : ProblemSpec
            A single-entity spec.

        Returns
        -------
        DesignProblem
            The cluster's index and loss.

        Raises
        ------
        EntityMismatchError
            If the spec has more than one entity.
        """
        if len(spec.entities) != 1:
            raise EntityMismatchError(
                f"problem {spec.problem_id!r}: one cluster per design problem"
            )
        index = self.cluster.index.compute(eventset, spec.entities)
        cols = location_columns(eventset, spec.entities[0].location_ids)
        loss = np.ascontiguousarray(eventset.loss[:, cols]).sum(axis=1)[:, None]
        return DesignProblem(spec=spec, index=index, entity_loss=loss)


def separate_specs(joint: Sequence[ProblemSpec]) -> tuple[ProblemSpec, ...]:
    """Split joint cluster specs into one single-entity spec per cluster.

    Parameters
    ----------
    joint : sequence of ProblemSpec
        The cluster scope's specs.

    Returns
    -------
    tuple of ProblemSpec
        ``problem_id`` = ``entity_id``.
    """
    return tuple(
        ProblemSpec(problem_id=e.entity_id, entities=(e,))
        for spec in joint
        for e in spec.entities
    )


def derived_hash(base_hash: str, derivation: str) -> str:
    """Id of a derived (non-runner) design: hash of its base and derivation.

    Parameters
    ----------
    base_hash : str
        Config hash of the C1 run it derives from.
    derivation : str
        What was changed, e.g. ``"cluster_separate"``.

    Returns
    -------
    str
        ``derived:<sha256 hex>``.
    """
    payload = json.dumps(
        {"base_config_hash": base_hash, "derivation": derivation}, sort_keys=True
    )
    return "derived:" + hashlib.sha256(payload.encode()).hexdigest()


# --------------------------------------------------------------------------
# Pairing across scopes
# --------------------------------------------------------------------------


def portfolio_rows(boot: KpiBootstrap) -> KpiBootstrap:
    """Keep a bootstrap's portfolio-level rows, with a common ``problem_id``.

    ``paired_difference`` pairs rows on ``PAIR_KEY``, which includes
    ``problem_id``: ``"*"`` for a scope with several design problems,
    ``"portfolio"`` for a joint scope. Both sides get :data:`ALL_PROBLEMS`;
    the replicates and the resample are unchanged.

    Parameters
    ----------
    boot : KpiBootstrap
        A run's bootstrap.

    Returns
    -------
    KpiBootstrap
        Its portfolio-level rows only.
    """
    mask = (boot.table["level"] == "portfolio").to_numpy()
    table = boot.table.loc[mask].copy().reset_index(drop=True)
    table["problem_id"] = ALL_PROBLEMS
    return KpiBootstrap(
        table=table,
        replicates=boot.replicates[mask],
        resample=boot.resample,
        level=boot.level,
    )


# --------------------------------------------------------------------------
# Phase holdout
# --------------------------------------------------------------------------


@dataclass
class _Design:
    """One design of a group: scope object, results and provenance."""

    label: str
    scope: Scope
    results: list[SolveResult]
    config_hash: str
    run_id: str
    statuses: str
    solvers: str
    objective_value: float


def _stored(cfg: ExperimentConfig, rid: str, store: ResultStore) -> _Design:
    scope = cfg.to_components().scopes[0]
    runs = store.read("runs", run_ids=[rid])
    results = c1.rebuild(
        cfg,
        runs,
        store.read("payouts", run_ids=[rid]),
        store.read("entities", run_ids=[rid]),
    )
    return _Design(
        label=scope.name,
        scope=scope,
        results=results,
        config_hash=config_hash(cfg),
        run_id=rid,
        statuses=",".join(sorted({str(r.status.value) for r in results})),
        solvers=",".join(sorted({r.solver for r in results})),
        objective_value=float(runs["objective_value"].sum()),
    )


def _solved(
    label: str,
    scope: Scope,
    cfg: ExperimentConfig,
    prepared: EventSet,
    train: Sample,
    specs: Sequence[ProblemSpec],
    policy: SolverPolicy,
    base_hash: str,
) -> _Design:
    comps = cfg.to_components()
    built = build_problems(
        prepared,
        scope,
        comps.payout,
        comps.objectives[0],
        comps.pricing,
        comps.constraints,
        basis=comps.basis,
        sample=train,
        specs=list(specs),
    )
    results = [solve(b, policy, pricing=comps.pricing) for b in built]
    dh = derived_hash(base_hash, label)
    return _Design(
        label=label,
        scope=scope,
        results=results,
        config_hash=dh,
        run_id=dh,
        statuses=",".join(sorted({str(r.status.value) for r in results})),
        solvers=",".join(sorted({r.solver for r in results})),
        objective_value=float(sum(r.objective_value for r in results)),
    )


def _entity_locations(design: _Design) -> dict[str, str]:
    return {
        e.entity_id: " ".join(e.location_ids)
        for r in design.results
        for e in r.spec.entities
    }


def holdout_worker(
    family: str,
    eventset: str,
    pricing: str,
    kappa: float,
    design: str,
    members: dict[str, tuple[ExperimentConfig, str]],
    store_root: str,
) -> tuple[dict[str, pd.DataFrame], float]:
    """Bootstrap one (variant, design) group across scopes.

    Parameters
    ----------
    family, eventset : str
        C1 variant labels, e.g. ``"main"``, ``"thesis"``; ``"f12"``, ``"vuln"``.
    pricing, design : str
        C1 labels, e.g. ``"coc_r0.06"``, ``"wcvar@0.99"``.
    kappa : float
        Budget loading.
    members : dict
        Scope name to (single-run config, run id) of the C1 runs.
    store_root : str
        The C1 result store.

    Returns
    -------
    frames : dict of pandas.DataFrame
        ``kpis``, ``paired``, ``entities``, ``premiums``, ``runs``.
    seconds : float
        Wall time.
    """
    start = time.perf_counter()
    store = ResultStore(Path(store_root))
    cfg0 = members["individual"][0]
    prepared = c1._prepared(cfg0)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    assert cfg0.bootstrap is not None
    resample = resample_years(
        test.years, cfg0.bootstrap.n_bootstrap, cfg0.bootstrap.rng()
    )
    level = cfg0.bootstrap.level

    designs: dict[str, _Design] = {}
    for scope in SCOPES:
        cfg, rid = members[scope]
        designs[scope] = _stored(cfg, rid, store)
    cl_cfg = members["cluster"][0]
    cluster_scope = designs["cluster"].scope
    assert isinstance(cluster_scope, Cluster)
    joint_specs = [r.spec for r in designs["cluster"].results]
    if cluster_scope.partition(train.select(prepared)) != tuple(joint_specs):
        raise RuntimeError(
            f"{family} {eventset} {pricing} k{kappa} {design}: the cluster "
            "partition on the train "
            "years differs from the stored C1 cluster run"
        )
    designs[SEPARATE] = _solved(
        SEPARATE,
        SeparateClusters(cluster_scope),
        cl_cfg,
        prepared,
        train,
        separate_specs(joint_specs),
        DEFAULT_POLICY,
        designs["cluster"].config_hash,
    )
    if family == "main" and kappa == 1.0:
        for scope in ("cluster", "portfolio"):
            base = designs[scope]
            designs[scope + ALT_SUFFIX] = _solved(
                scope + ALT_SUFFIX,
                base.scope,
                members[scope][0],
                prepared,
                train,
                [r.spec for r in base.results],
                ALT_POLICY,
                base.config_hash,
            )

    comps = cfg0.to_components()
    basis, price = comps.basis, comps.pricing
    kpi_rows: list[pd.DataFrame] = []
    boots: dict[tuple[str, float], KpiBootstrap] = {}
    for label, d in designs.items():
        locs = _entity_locations(d)
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
            boots[(label, beta)] = boot
            tr = kpis(
                prepared,
                d.scope,
                d.results,
                basis=basis,
                beta=beta,
                run_id=d.run_id,
                sample=train,
                pricing=price,
            )
            for split, table in (("test", boot.table), ("train", tr)):
                t = table.copy()
                t["split"] = split
                t["eval_beta"] = beta
                t["scope"] = label
                t["config_hash"] = d.config_hash
                t["entity_locations"] = t["subject_id"].map(locs)
                kpi_rows.append(t)
    allk = pd.concat(kpi_rows, ignore_index=True)

    paired_rows: list[pd.DataFrame] = []
    for a, b in PAIRS:
        if a not in designs or b not in designs:
            continue
        for beta in EVAL_BETAS:
            diff = paired_difference(
                portfolio_rows(boots[(a, beta)]), portfolio_rows(boots[(b, beta)])
            )
            diff["split"] = "test"
            diff["scope_a"], diff["scope_b"] = a, b
            diff["eval_beta"] = beta
            diff["config_hash_a"] = designs[a].config_hash
            diff["config_hash_b"] = designs[b].config_hash
            paired_rows.append(diff)
            # train: in sample, point differences
            port = allk.loc[
                (allk["split"] == "train")
                & (allk["eval_beta"] == beta)
                & (allk["level"] == "portfolio")
            ]
            va = port.loc[port["scope"] == a].set_index("kpi")["value"]
            vb = port.loc[port["scope"] == b].set_index("kpi")["value"]
            tr = pd.DataFrame(
                {"kpi": va.index, "value_a": va.to_numpy(), "value_b": vb[va.index]}
            )
            tr["difference"] = tr["value_a"] - tr["value_b"]
            tr["split"] = "train"
            tr["scope_a"], tr["scope_b"] = a, b
            tr["eval_beta"] = beta
            tr["config_hash_a"] = designs[a].config_hash
            tr["config_hash_b"] = designs[b].config_hash
            paired_rows.append(tr)
    paired = pd.concat(paired_rows, ignore_index=True)

    run_rows = [
        {
            "scope": d.label,
            "n_problems": len(d.results),
            "statuses": d.statuses,
            "solvers": d.solvers,
            "objective_value": d.objective_value,
            "sum_problem_premiums_solver": float(sum(r.premium for r in d.results)),
            "config_hash": d.config_hash,
            "run_id": d.run_id,
            "base_config_hash": (
                designs["cluster"].config_hash
                if d.label in (SEPARATE, "cluster" + ALT_SUFFIX)
                else designs["portfolio"].config_hash
                if d.label == "portfolio" + ALT_SUFFIX
                else d.config_hash
            ),
        }
        for d in designs.values()
    ]
    frames = {"kpis": allk, "paired": paired, "runs": pd.DataFrame(run_rows)}
    for frame in frames.values():
        frame["family"] = family
        frame["eventset"] = eventset
        frame["pricing"] = pricing
        frame["kappa"] = kappa
        frame["design"] = design
    return frames, time.perf_counter() - start


def _check_against_c1(kp: pd.DataFrame, full: Path) -> int:
    """Raise unless the C1 scopes' test values and intervals equal C1's."""
    c1k = pd.read_csv(full / "kpis.csv")
    c1k = c1k.loc[(c1k["source"] == "c1_bootstrap") & (c1k["eval_split"] == "test")]
    mine = kp.loc[
        (kp["split"] == "test")
        & (kp["level"] == "portfolio")
        & kp["scope"].isin(SCOPES)
        & kp["kpi"].isin(PORTFOLIO_KPIS)
    ]
    key = [
        "family",
        "eventset",
        "pricing",
        "kappa",
        "scope",
        "design",
        "eval_beta",
        "kpi",
    ]
    merged = mine.merge(
        c1k[[*key, "value", "ci_low", "ci_high"]],
        on=key,
        suffixes=("", "_c1"),
        validate="one_to_one",
    )
    if len(merged) != len(mine):
        raise RuntimeError(
            f"{len(mine) - len(merged)} test rows have no C1 counterpart"
        )
    for column in ("value", "ci_low", "ci_high"):
        a = merged[column].to_numpy(dtype=np.float64)
        b = merged[f"{column}_c1"].to_numpy(dtype=np.float64)
        if not np.allclose(a, b, rtol=1e-8, atol=1e-6, equal_nan=True):
            worst = int(np.nanargmax(np.abs(a - b)))
            raise RuntimeError(
                f"test {column} differs from C1: {merged.iloc[worst][key].to_dict()}"
                f" {a[worst]!r} vs {b[worst]!r}"
            )
    return len(merged)


def run_holdout(args: argparse.Namespace, family: str) -> dict[str, Any]:
    """Phase holdout: cross-scope comparisons on the C1 test years.

    Writes ``holdout_<family>_{kpis,paired,runs}.csv`` to ``args.full``.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    family : str
        C1 family, ``"main"`` or ``"f12"``.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    specs, checksums = c1.plan([family])
    sums = {"thesis": str(load_config(c1.BASE_CONFIG).eventset.checksum), **checksums}
    groups: dict[
        tuple[str, str, str, float, str], dict[str, tuple[ExperimentConfig, str]]
    ] = {}
    for s in specs:
        v = s.variant
        if s.design not in (DESIGNS if v.family == "main" else F12_DESIGNS):
            continue
        rid = run_key(config_hash(s.config), sums[v.eventset], policy=DEFAULT_POLICY)
        key = (v.family, v.eventset, v.pricing, v.kappa, s.design)
        groups.setdefault(key, {})[s.scope] = (s.config, rid)
    store = ResultStore(args.c1_store)
    for members in groups.values():
        for _, rid in members.values():
            if not store.has_run(rid):
                raise RuntimeError(
                    f"C1 run {rid} is not in {args.c1_store}: run c1_checkpoint.py"
                )
    frames: dict[str, list[pd.DataFrame]] = {}
    seconds: dict[str, float] = {}
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {
            pool.submit(holdout_worker, *key, m, str(args.c1_store)): key
            for key, m in groups.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            out, sec = fut.result()
            for name, frame in out.items():
                frames.setdefault(name, []).append(frame)
            label = "|".join(f"{x:g}" if isinstance(x, float) else x for x in futs[fut])
            seconds[label] = round(sec, 1)
            print(f"[holdout {i}/{len(futs)}] {label} {sec:.0f}s", flush=True)
    args.full.mkdir(parents=True, exist_ok=True)
    tables = {n: pd.concat(f, ignore_index=True) for n, f in frames.items()}
    n_checked = _check_against_c1(tables["kpis"], args.c1_full)
    print(f"checked {n_checked} test rows against the C1 tables", flush=True)
    for name, table in tables.items():
        table.to_csv(
            args.full / f"holdout_{family}_{name}.csv",
            index=False,
            float_format="%.10g",
        )
    return {
        "holdout_groups": len(groups),
        "holdout_rows_checked_against_c1": n_checked,
        "holdout_seconds": round(time.perf_counter() - t0, 1),
        "holdout_seconds_per_group": seconds,
    }


# --------------------------------------------------------------------------
# Phase kfold
# --------------------------------------------------------------------------


def kfold_configs() -> dict[tuple[str, str], ExperimentConfig]:
    """Return the k-fold experiment configs, keyed by (pricing, objective set).

    Returns
    -------
    dict
        One config per pricing and objective set, all three scopes, kappa 1.
    """
    base = load_config(c1.BASE_CONFIG).model_dump(mode="json")
    base["output"] = {"directory": str(KFOLD_STORE)}
    out: dict[tuple[str, str], ExperimentConfig] = {}
    for pricing in KFOLD_PRICINGS:
        for name, objectives in KFOLD_OBJECTIVE_SETS.items():
            data = json.loads(json.dumps(base))
            data["name"] = "c1-rq2-kfold"
            data["description"] = (
                "MAR-158 (C1 RQ2): the C1 main line at kappa 1 on a year-block "
                "5-fold split, for pooled out-of-sample KPIs (MAR-151)."
            )
            data["sample"] = {"kind": "kfold", "k": KFOLD_K}
            data["pricing"] = c1.PRICINGS[pricing]
            data["constraints"] = [{"kind": "budget", "loading": 1.0}]
            data["objectives"] = objectives
            out[(pricing, name)] = parse_config(data)
    return out


def _design_of(objective: str, cfg: ExperimentConfig) -> str:
    beta: float | None = None
    for o in cfg.objectives:
        dumped = o.model_dump(mode="json")
        if dumped["kind"] == objective and objective == "weighted_cvar":
            beta = float(dumped["beta"])
    return OBJECTIVE_DESIGN[(objective, beta)]


def _identity(resample: YearResample) -> YearResample:
    return YearResample(
        years=resample.years,
        indices=np.arange(resample.n_years, dtype=np.int32)[None, :],
    )


def run_kfold(args: argparse.Namespace) -> dict[str, Any]:
    """Phase kfold: k-fold runs and pooled cross-scope differences.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    configs = kfold_configs()
    checksum = str(load_config(c1.BASE_CONFIG).eventset.checksum)
    store = ResultStore(args.kfold_store)
    single: dict[tuple[str, str], list[tuple[ExperimentConfig, str]]] = {}
    todo: dict[str, ExperimentConfig] = {}
    for key, cfg in configs.items():
        runs = []
        for s in cfg.single_runs():
            rid = run_key(config_hash(s), checksum, policy=DEFAULT_POLICY)
            runs.append((s, rid))
            if not store.has_run(rid):
                todo[rid] = s
        single[key] = runs
    print(f"kfold: {sum(map(len, single.values()))} runs, {len(todo)} to solve")
    ctx = get_context("spawn")
    solve_seconds: dict[str, float] = {}
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {pool.submit(c1.solve_worker, cfg): rid for rid, cfg in todo.items()}
        for i, fut in enumerate(as_completed(futs), 1):
            tables, manifest, sec = fut.result()
            rid = futs[fut]
            if manifest["run_id"] != rid:
                raise RuntimeError(f"run id mismatch: {manifest['run_id']} != {rid}")
            store.write_run(tables, manifest)
            solve_seconds[rid[7:19]] = round(sec, 1)
            print(f"[kfold {i}/{len(todo)}] {rid[7:19]} {sec:.0f}s", flush=True)
    t_solve = time.perf_counter() - t0

    first = next(iter(configs.values()))
    prepared = c1._prepared(first)
    full = Sample.full(prepared)
    measure = outcome_measure(prepared, Basis.ANNUAL, years=full.years)
    row_years = prepared.events["year"].to_numpy(dtype=np.int64)
    pooled_rows: list[dict[str, Any]] = []
    paired_rows: list[dict[str, Any]] = []
    fold_rows: list[pd.DataFrame] = []
    run_rows: list[dict[str, Any]] = []
    replicates: dict[tuple[str, str, str, float], dict[KpiName, np.ndarray]] = {}
    resample_ref: YearResample | None = None
    for (pricing, oset), cfg in configs.items():
        run_ids = [rid for _, rid in single[(pricing, oset)]]
        pooled = kfold.pooled_kpis(cfg, store, prepared, run_ids)
        if pooled.failed:
            raise RuntimeError(f"k-fold {pricing}/{oset}: failed {pooled.failed}")
        assert pooled.resample is not None
        assert pooled.level is not None
        if resample_ref is None:
            resample_ref = pooled.resample
        elif not resample_ref.same_as(pooled.resample):
            raise RuntimeError("the k-fold configs drew different resamples")
        exp_hash = config_hash(cfg)
        scope_names = [s.kind for s in cfg.scopes]
        for row in pooled.table.itertuples():
            pooled_rows.append(
                {
                    "pricing": pricing,
                    "kappa": 1.0,
                    "design": _design_of(str(row.objective), cfg),
                    "scope": str(row.scope),
                    "kpi": str(row.kpi),
                    "eval_beta": cfg.evaluation.beta,
                    "value": row.value,
                    "ci_low": row.ci_low,
                    "ci_high": row.ci_high,
                    "config_hash": exp_hash,
                    "source": "pooled_kpis",
                }
            )
        objectives = sorted(set(pooled.table["objective"]))
        for objective in objectives:
            design = _design_of(objective, cfg)
            pos = {name: i for i, name in enumerate(scope_names)}
            for a, b in PAIRS[:3]:
                diff = kfold.pooled_difference(
                    pooled, (pos[a], objective), (pos[b], objective)
                )
                for d in diff.itertuples():
                    paired_rows.append(
                        {
                            "pricing": pricing,
                            "kappa": 1.0,
                            "design": design,
                            "split": "pooled",
                            "scope_a": a,
                            "scope_b": b,
                            "kpi": d.kpi,
                            "eval_beta": cfg.evaluation.beta,
                            "value_a": d.value_a,
                            "value_b": d.value_b,
                            "difference": d.difference,
                            "ci_low": d.ci_low,
                            "ci_high": d.ci_high,
                            "config_hash_a": exp_hash,
                            "config_hash_b": exp_hash,
                            "source": "pooled_difference",
                        }
                    )
        # other KPI betas: kpi_replicates of the pooled payouts, same resample.
        # CVaR only: at a step of the distribution the bootstrap's VaR point
        # (CDF tolerance) may differ from evaluate's strict VaR (MAR-143)
        designs, _ = kfold.pooled_designs(cfg, store, prepared, run_ids)
        ones = _identity(pooled.resample)
        for d in designs:
            design = _design_of(d.objective, cfg)
            for beta in EVAL_BETAS:
                reps = kpi_replicates(
                    d.loss, d.payout, measure, row_years, pooled.resample, beta=beta
                )
                point = kpi_replicates(
                    d.loss, d.payout, measure, row_years, ones, beta=beta
                )
                replicates[(pricing, design, d.scope, beta)] = reps
                for kpi in (KpiName.CVAR_UNCOVERED,):
                    low, high = percentile_interval(reps[kpi], pooled.level)
                    pooled_rows.append(
                        {
                            "pricing": pricing,
                            "kappa": 1.0,
                            "design": design,
                            "scope": d.scope,
                            "kpi": kpi.value,
                            "eval_beta": beta,
                            "value": float(point[kpi][0]),
                            "ci_low": low,
                            "ci_high": high,
                            "config_hash": exp_hash,
                            "source": "kpi_replicates",
                        }
                    )
        # per-fold KPIs the runner stored (train in sample, test out of sample)
        for s, rid in single[(pricing, oset)]:
            k = store.read("kpis", run_ids=[rid])
            k = k.loc[k["level"] == "portfolio"].copy()
            obj = s.objectives[0].model_dump(mode="json")
            design = OBJECTIVE_DESIGN[(obj["kind"], obj.get("beta"))]
            k["pricing"], k["kappa"], k["design"] = pricing, 1.0, design
            k["scope"] = s.scopes[0].kind
            k["config_hash"] = config_hash(s)
            fold_rows.append(k)
            r = store.read("runs", run_ids=[rid])
            run_rows.append(
                {
                    "kind": "kfold",
                    "pricing": pricing,
                    "kappa": 1.0,
                    "design": design,
                    "scope": s.scopes[0].kind,
                    "fold": getattr(s.sample, "fold", None),
                    "n_problems": len(r),
                    "statuses": ",".join(sorted(set(r["status"].astype(str)))),
                    "solvers": ",".join(sorted(set(r["solver"].astype(str)))),
                    "sum_problem_premiums_solver": float(r["premium"].sum()),
                    "config_hash": config_hash(s),
                    "run_id": rid,
                    "experiment_config_hash": exp_hash,
                }
            )
    # pooled differences at 0.95 and 0.995 (and 0.99, which must equal
    # pooled_difference): replicate differences on the one resample
    assert resample_ref is not None
    level = float(first.bootstrap.level) if first.bootstrap else 0.9
    hashes = {
        (p, _design_of(str(o), cfg)): config_hash(cfg)
        for (p, _), cfg in configs.items()
        for o in {ob.model_dump(mode="json")["kind"] for ob in cfg.objectives}
    }
    for (pricing, design, scope, beta), reps in replicates.items():
        for a, b in PAIRS[:3]:
            if scope != a:
                continue
            other = replicates[(pricing, design, b, beta)]
            for kpi in (KpiName.CVAR_UNCOVERED,):
                low, high = percentile_interval(reps[kpi] - other[kpi], level)
                paired_rows.append(
                    {
                        "pricing": pricing,
                        "kappa": 1.0,
                        "design": design,
                        "split": "pooled",
                        "scope_a": a,
                        "scope_b": b,
                        "kpi": kpi.value,
                        "eval_beta": beta,
                        "ci_low": low,
                        "ci_high": high,
                        "config_hash_a": hashes.get((pricing, design)),
                        "config_hash_b": hashes.get((pricing, design)),
                        "source": "kpi_replicates",
                    }
                )
    args.full.mkdir(parents=True, exist_ok=True)
    pooled_t = pd.DataFrame(pooled_rows)
    paired_t = pd.DataFrame(paired_rows)
    _fill_points(paired_t, pooled_t)
    pooled_t.to_csv(args.full / "kfold_pooled.csv", index=False, float_format="%.10g")
    paired_t.to_csv(args.full / "kfold_paired.csv", index=False, float_format="%.10g")
    pd.concat(fold_rows, ignore_index=True).to_csv(
        args.full / "kfold_folds.csv", index=False, float_format="%.10g"
    )
    pd.DataFrame(run_rows).to_csv(args.full / "kfold_runs.csv", index=False)
    return {
        "kfold_k": KFOLD_K,
        "kfold_pricings": list(KFOLD_PRICINGS),
        "kfold_runs": len(run_rows),
        "kfold_solved_this_call": len(todo),
        "kfold_experiment_config_hashes": {
            f"{p}|{o}": config_hash(c) for (p, o), c in configs.items()
        },
        "kfold_seconds": {
            "solve_phase": round(t_solve, 1),
            "total": round(time.perf_counter() - t0, 1),
        },
        "kfold_solve_seconds_per_run": solve_seconds,
    }


def _fill_points(paired: pd.DataFrame, pooled: pd.DataFrame) -> None:
    """Fill value_a/b and difference of the kpi_replicates pairs; check 0.99."""
    pts = pooled.loc[pooled["source"] == "kpi_replicates"].set_index(
        ["pricing", "design", "scope", "kpi", "eval_beta"]
    )["value"]
    mask = paired["source"] == "kpi_replicates"
    for i in paired.index[mask]:
        r = paired.loc[i]
        a = pts[(r["pricing"], r["design"], r["scope_a"], r["kpi"], r["eval_beta"])]
        b = pts[(r["pricing"], r["design"], r["scope_b"], r["kpi"], r["eval_beta"])]
        paired.loc[i, ["value_a", "value_b", "difference"]] = [a, b, a - b]
    key = ["pricing", "design", "scope_a", "scope_b", "kpi", "eval_beta"]
    lib = paired.loc[paired["source"] == "pooled_difference"].set_index(key)
    mine = paired.loc[mask].set_index(key)
    common = lib.index.intersection(mine.index)
    if len(common) == 0:
        raise RuntimeError("no pooled differences to cross-check at beta 0.99")
    for column in ("difference", "ci_low", "ci_high"):
        x = lib.loc[common, column].to_numpy(dtype=np.float64)
        y = mine.loc[common, column].to_numpy(dtype=np.float64)
        if not np.allclose(x, y, rtol=1e-9, atol=1e-6):
            raise RuntimeError(
                f"kpi_replicates and pooled_difference disagree: {column}"
            )


# --------------------------------------------------------------------------
# Phase ranges: how unique is a joint design's split across entities?
# --------------------------------------------------------------------------

RANGE_REL_TOL: Final[float] = 1e-5
"""Near-optimal set of a range problem: objective <= optimum * (1 + tol)."""
RANGE_PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06")


def range_worker(
    pricing: str,
    design: str,
    members: dict[str, tuple[ExperimentConfig, str]],
    store_root: str,
) -> tuple[pd.DataFrame, float]:
    """Smallest and largest train payout of each entity over the optimal set.

    Rebuilds the C1 joint design problems (cluster and portfolio scopes,
    kappa 1) on the train years and re-solves them with the default policy
    (the objective must equal the stored run's). Then, for each entity, it
    minimises and maximises the entity's train expected payout subject to the
    design problem's constraints and ``objective <= optimum * (1 +
    RANGE_REL_TOL)`` (CLARABEL). A range much wider than zero means the
    stored split is one member of a set of (near-)optimal splits (MAR-100,
    MAR-161 F8).

    Parameters
    ----------
    pricing, design : str
        C1 labels.
    members : dict
        Scope name to (single-run config, run id) of the C1 runs.
    store_root : str
        The C1 result store.

    Returns
    -------
    frame : pandas.DataFrame
        One row per (scope, entity): the stored, smallest and largest train
        ``E[pi_j] / E[L_j]``, and the range problems' statuses.
    seconds : float
        Wall time.
    """
    start = time.perf_counter()
    store = ResultStore(Path(store_root))
    rows: list[dict[str, Any]] = []
    for scope in ("cluster", "portfolio"):
        cfg, rid = members[scope]
        prepared = c1._prepared(cfg)
        train, _ = splits.holdout(prepared, train_fraction=0.7)
        stored = _stored(cfg, rid, store)
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
                f"{pricing} {design} {scope}: re-solved objective "
                f"{result.objective_value!r} != stored {stored.objective_value!r}"
            )
        ctx = built.context
        optimum = float(np.asarray(built.objective.expression.value))
        bound = optimum + RANGE_REL_TOL * abs(optimum)
        constraints = [*built.problem.constraints, built.objective.expression <= bound]
        stored_theta = np.vstack([r.theta for r in stored.results])
        measure = ctx.measure
        for j, entity in enumerate(ctx.problem.spec.entities):
            expected = measure.probability @ measure.aggregate_expression(
                ctx.entity_payout[:, j]
            )
            el_scaled = measure.expectation(ctx.entity_loss[:, j])
            ends: dict[str, tuple[float, str]] = {}
            for sense, goal in (("min", cp.Minimize), ("max", cp.Maximize)):
                prob = cp.Problem(goal(expected), constraints)
                prob.solve(solver="CLARABEL")
                ok = prob.status == "optimal" and prob.value is not None
                value = float(np.asarray(prob.value)) if ok else math.nan
                ends[sense] = (value / el_scaled, str(prob.status))
            pay = comps.payout.evaluate(
                ctx.problem.index[:, [j]], stored_theta[[j]]
            ).ravel()
            el = measure.expectation(ctx.problem.entity_loss[:, j])
            rows.append(
                {
                    "pricing": pricing,
                    "kappa": 1.0,
                    "design": design,
                    "scope": scope,
                    "entity_id": entity.entity_id,
                    "entity_locations": " ".join(entity.location_ids),
                    "stored_payout_to_loss": measure.expectation(pay) / el,
                    "min_payout_to_loss": ends["min"][0],
                    "max_payout_to_loss": ends["max"][0],
                    "status_min": ends["min"][1],
                    "status_max": ends["max"][1],
                    "rel_tol": RANGE_REL_TOL,
                    "config_hash": stored.config_hash,
                }
            )
    return pd.DataFrame(rows), time.perf_counter() - start


def run_ranges(args: argparse.Namespace) -> dict[str, Any]:
    """Phase ranges: per-entity payout ranges over the optimal set (kappa 1).

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    specs, _ = c1.plan(["main"])
    checksum = str(load_config(c1.BASE_CONFIG).eventset.checksum)
    groups: dict[tuple[str, str], dict[str, tuple[ExperimentConfig, str]]] = {}
    for s in specs:
        v = s.variant
        if v.kappa != 1.0 or v.pricing not in RANGE_PRICINGS or s.design not in DESIGNS:
            continue
        rid = run_key(config_hash(s.config), checksum, policy=DEFAULT_POLICY)
        groups.setdefault((v.pricing, s.design), {})[s.scope] = (s.config, rid)
    frames: list[pd.DataFrame] = []
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {
            pool.submit(range_worker, p, d, m, str(args.c1_store)): (p, d)
            for (p, d), m in groups.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            frame, sec = fut.result()
            frames.append(frame)
            p, d = futs[fut]
            print(f"[ranges {i}/{len(futs)}] {p} {d} {sec:.0f}s", flush=True)
    table = pd.concat(frames, ignore_index=True)
    bad = table.loc[
        (table["status_min"] != "optimal") | (table["status_max"] != "optimal")
    ]
    table.to_csv(args.full / "ranges.csv", index=False, float_format="%.10g")
    return {
        "ranges_groups": len(groups),
        "ranges_rel_tol": RANGE_REL_TOL,
        "ranges_not_optimal": len(bad),
        "ranges_seconds": round(time.perf_counter() - t0, 1),
    }


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


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
    parser = argparse.ArgumentParser(description="C1 RQ2 addendum (MAR-158).")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument(
        "--phases",
        nargs="+",
        default=["holdout", "kfold", "ranges"],
        choices=["holdout", "kfold", "ranges"],
    )
    parser.add_argument(
        "--families",
        nargs="+",
        default=["main", "f12"],
        choices=["main", "f12"],
        help="C1 families of the holdout phase",
    )
    parser.add_argument("--c1-store", type=Path, default=c1.STORE)
    parser.add_argument("--c1-full", type=Path, default=C1_FULL)
    parser.add_argument("--kfold-store", type=Path, default=KFOLD_STORE)
    parser.add_argument("--full", type=Path, default=FULL_DIR)
    args = parser.parse_args(argv)
    common: dict[str, Any] = {
        "issue": "MAR-158",
        "base_config": str(c1.BASE_CONFIG.relative_to(REPO_ROOT)),
        "designs": list(DESIGNS),
        "f12_designs": list(F12_DESIGNS),
        "eval_betas": list(EVAL_BETAS),
        "alt_policy": {
            "lp_solvers": list(ALT_POLICY.lp_solvers),
            "qp_solvers": list(ALT_POLICY.qp_solvers),
        },
        "package_versions": package_versions(),
    }
    args.full.mkdir(parents=True, exist_ok=True)
    # one summary per phase (and family), so that phases can run separately
    parts: list[tuple[str, Any]] = []
    if "holdout" in args.phases:
        parts += [
            (f"holdout_{f}", lambda f=f: run_holdout(args, f)) for f in args.families
        ]
    if "kfold" in args.phases:
        parts.append(("kfold", lambda: run_kfold(args)))
    if "ranges" in args.phases:
        parts.append(("ranges", lambda: run_ranges(args)))
    for name, run in parts:
        summary = {**common, **run()}
        (args.full / f"summary_{name}.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
    print(f"wrote {args.full}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
