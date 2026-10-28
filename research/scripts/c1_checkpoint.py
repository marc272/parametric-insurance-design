r"""Checkpoint C1 (MAR-29): the runs, the bootstrap comparisons and the tables.

Question (SPEC §6, Checkpoint C1): does the weighted-CVaR design still lower
tail basis risk out of sample, under realistic basis risk and loaded pricing,
compared with the MSE and E[U] designs, for each scope?

Every run derives from ``research/configs/c1/c1_main.yaml`` (thesis
portfolio, thesis noise layer, annual basis, holdout split with train
fraction 0.7, bootstrap B = 1000, seed 0, level 0.9, default solver policy).
Three families of variants:

``main``
    The thesis EventSet on the annual basis. Pricing pure, cost of capital
    r = 0.06 and r = 0.10 (q = 0.99); budget loading kappa 0.5, 1, 1.5; the
    weighted-CVaR design (alpha 0.9) at beta 0.95, 0.97, 0.98, 0.99, 0.995;
    the MSE and E[U] designs.
``reference``
    The same on the thesis basis, ``event_conditional`` (evaluation beta 0.95
    as in the thesis), kappa 1, weighted CVaR at the thesis beta 0.95. A
    reference column only.
``f12``
    Provisional realistic-basis-risk sensitivities (F-12) on EventSets built
    by ``research/scripts/c1_build_eventsets.sh``: cat-in-a-circle at 50 km
    without draws; wind at the asset with vulnerability draws (default
    prior); cat-in-a-circle with draws; wind with draws from the prior
    without the basin filter. No noise layer. Annual basis, kappa 1, pure
    and r = 0.06 pricing, weighted CVaR at beta 0.95 and 0.99. The prior
    (MAR-118 Q5) and the radius (Q6) are open, so these are labelled
    provisional.

Phase A solves every single run (one scope x one objective) through the
runner's :func:`~parametric_insurance_design.experiment.runner.execute` in
``--jobs`` worker processes; the parent writes them to a result store
(``results/c1/store``, not committed; cached on re-runs). Phase B rebuilds
each stored design and bootstraps its **test** KPIs at several evaluation
betas on one resample per group (same seed, same test years), so the designs
of a (variant, scope) group are paired: ``paired_difference`` gives weighted
CVaR - MSE and weighted CVaR - E[U]. It checks that its intervals at the
config's evaluation beta equal the ones the runner stored.

Outputs, portfolio-level KPIs only (no per-asset KPIs of joint designs:
MAR-98, MAR-100). The full tables (every KPI, with config hash and run id on
every row) go to ``results/c1/full/`` (not committed). The committed ones,
each under the 500 kB pre-commit limit, go to ``research/data/c1/``
(:func:`write_slim`):

* ``runs.csv``: one row per run (variant, scope, design, config hash, run id,
  statuses, solvers, budget use, solve time);
* ``kpis_<family>.csv``: test KPIs with 90 % intervals at each evaluation
  beta (beta-free KPIs once), and the runner's train KPIs;
* ``paired_<family>.csv``: the paired differences on the test years;
* ``summary.json``: inputs, EventSet checksums, versions, solver policy,
  counts and timings.

``--slim-only`` rewrites the committed tables from the full ones.

Run from the repository root (after ``c1_build_eventsets.sh`` for ``f12``)::

    uv run python research/scripts/c1_checkpoint.py --jobs 3
    uv run python research/scripts/c1_figures.py
"""

from __future__ import annotations

import argparse
import json
import os
import time
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from parametric_insurance_design import splits
from parametric_insurance_design.bootstrap import (
    KpiBootstrap,
    bootstrap_kpis,
    paired_difference,
    resample_years,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import (
    RunInput,
    RunOutcome,
    execute,
    load_input,
    prepare_eventset,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore, RunTables
from parametric_insurance_design.interfaces import (
    Entity,
    ProblemSpec,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.solve import DEFAULT_POLICY

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
BASE_CONFIG: Final[Path] = REPO_ROOT / "research" / "configs" / "c1" / "c1_main.yaml"
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "c1"
STORE: Final[Path] = REPO_ROOT / "results" / "c1" / "store"
FULL_DIR: Final[Path] = REPO_ROOT / "results" / "c1" / "full"
EVENTSETS: Final[Path] = Path(
    os.environ.get("C1_EVENTSETS", REPO_ROOT / "results" / "c1" / "eventsets")
)

PRICINGS: Final[dict[str, dict[str, Any]]] = {
    "pure": {"kind": "pure"},
    "coc_r0.06": {"kind": "cost_of_capital", "rate": 0.06, "q": 0.99},
    "coc_r0.10": {"kind": "cost_of_capital", "rate": 0.10, "q": 0.99},
}
MAIN_KAPPAS: Final[tuple[float, ...]] = (0.5, 1.0, 1.5)
MAIN_BETAS: Final[tuple[float, ...]] = (0.95, 0.97, 0.98, 0.99, 0.995)
ANNUAL_EVAL_BETAS: Final[tuple[float, ...]] = (0.95, 0.99, 0.995)
REFERENCE_EVAL_BETAS: Final[tuple[float, ...]] = (0.95, 0.99)
F12_BETAS: Final[tuple[float, ...]] = (0.95, 0.99)
F12_PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06")
SCOPES: Final[tuple[str, ...]] = ("individual", "cluster", "portfolio")

CAT_PAYOUT: Final[dict[str, Any]] = {
    "kind": "step",
    "attachment": 0.0,
    "limit": 6.0,
    "n_bins": 6,
    "breakpoints": [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
}
"""One bin per Saffir-Simpson category (packages/climada/README.md)."""


@dataclass(frozen=True)
class F12EventSet:
    """A provisional F-12 EventSet and how C1 runs on it."""

    directory: str
    index: str  # "wind" (index a) or "cat_in_circle" (index b)
    label: str


F12_EVENTSETS: Final[dict[str, F12EventSet]] = {
    "cic50": F12EventSet(
        "thesis-iris-cat-in-circle-50km",
        "cat_in_circle",
        "cat-in-a-circle 50 km, base vulnerability (no draws)",
    ),
    "vuln": F12EventSet(
        "thesis-iris-vulnerability",
        "wind",
        "wind at the asset, 10 vulnerability draws (default prior, 17 events)",
    ),
    "cic50_vuln": F12EventSet(
        "thesis-iris-cat-in-circle-50km-vulnerability",
        "cat_in_circle",
        "cat-in-a-circle 50 km, 10 vulnerability draws (default prior)",
    ),
    "vuln_basins_null": F12EventSet(
        "thesis-iris-vulnerability-basins-null",
        "wind",
        "wind at the asset, 10 draws, prior without basin filter (19 events)",
    ),
}


@dataclass(frozen=True)
class Variant:
    """Everything but the scope and the design."""

    family: str
    eventset: str
    basis: str
    pricing: str
    kappa: float
    wcvar_betas: tuple[float, ...]
    eval_betas: tuple[float, ...]

    @property
    def key(self) -> str:
        """Short id."""
        return (
            f"{self.family}|{self.eventset}|{self.basis}|{self.pricing}|k{self.kappa:g}"
        )


@dataclass(frozen=True)
class RunSpec:
    """One single run: a variant, a scope and a design."""

    variant: Variant
    scope: str
    objective: str
    objective_beta: float | None
    config: ExperimentConfig = field(compare=False)

    @property
    def design(self) -> str:
        """Design label, e.g. ``wcvar@0.99``."""
        if self.objective == "weighted_cvar":
            return f"wcvar@{self.objective_beta:g}"
        return {"mse": "mse", "expected_uncovered": "eu"}[self.objective]


def variants(families: Iterable[str]) -> list[Variant]:
    """Return the C1 variants of the requested families."""
    out: list[Variant] = []
    fams = set(families)
    if "main" in fams:
        for pricing in PRICINGS:
            for kappa in MAIN_KAPPAS:
                out.append(
                    Variant(
                        "main",
                        "thesis",
                        "annual",
                        pricing,
                        kappa,
                        MAIN_BETAS,
                        ANNUAL_EVAL_BETAS,
                    )
                )
    if "reference" in fams:
        for pricing in PRICINGS:
            out.append(
                Variant(
                    "reference",
                    "thesis",
                    "event_conditional",
                    pricing,
                    1.0,
                    (0.95,),
                    REFERENCE_EVAL_BETAS,
                )
            )
    if "f12" in fams:
        for name in F12_EVENTSETS:
            for pricing in F12_PRICINGS:
                out.append(
                    Variant(
                        "f12",
                        name,
                        "annual",
                        pricing,
                        1.0,
                        F12_BETAS,
                        ANNUAL_EVAL_BETAS,
                    )
                )
    return out


def eventset_checksums(names: Iterable[str]) -> dict[str, str]:
    """Content hashes of the F-12 EventSets (raises if one is missing)."""
    out: dict[str, str] = {}
    for name in names:
        if name == "thesis":
            continue
        path = EVENTSETS / F12_EVENTSETS[name].directory
        if not path.is_dir():
            raise FileNotFoundError(
                f"F-12 EventSet {path} is missing: run "
                "research/scripts/c1_build_eventsets.sh, or pass --families "
                "main reference to leave the F-12 sensitivities out"
            )
        out[name] = EventSet.from_parquet(path).content_hash()
    return out


def single_config(
    base: dict[str, Any],
    variant: Variant,
    scope: str,
    objective: dict[str, Any],
    checksums: dict[str, str],
) -> ExperimentConfig:
    """Return the single-run config of one (variant, scope, objective)."""
    data = json.loads(json.dumps(base))
    data["name"] = f"c1-{variant.family}"
    data["basis"] = variant.basis
    data["pricing"] = PRICINGS[variant.pricing]
    data["constraints"] = [{"kind": "budget", "loading": variant.kappa}]
    data["scopes"] = [s for s in base["scopes"] if s["kind"] == scope]
    data["objectives"] = [objective]
    if variant.family == "reference":
        data["evaluation"] = {"beta": 0.95}
    if variant.eventset != "thesis":
        spec = F12_EVENTSETS[variant.eventset]
        data["eventset"] = {
            "path": str(EVENTSETS / spec.directory),
            "checksum": checksums[variant.eventset],
        }
        data["noise"] = None
        if spec.index == "cat_in_circle":
            data["threshold"] = None
            data["payout"] = CAT_PAYOUT
    return parse_config(data)


def plan(families: Sequence[str]) -> tuple[list[RunSpec], dict[str, str]]:
    """Return every single run of the requested families."""
    base_config = load_config(BASE_CONFIG)
    base = base_config.model_dump(mode="json")
    base["output"] = {"directory": str(STORE)}
    vs = variants(families)
    checksums = eventset_checksums({v.eventset for v in vs})
    specs: list[RunSpec] = []
    for v in vs:
        for scope in SCOPES:
            objectives: list[tuple[str, float | None, dict[str, Any]]] = [
                ("mse", None, {"kind": "mse"}),
                ("expected_uncovered", None, {"kind": "expected_uncovered"}),
            ]
            objectives += [
                (
                    "weighted_cvar",
                    b,
                    {"kind": "weighted_cvar", "alpha": 0.9, "beta": b},
                )
                for b in v.wcvar_betas
            ]
            for name, beta, obj in objectives:
                cfg = single_config(base, v, scope, obj, checksums)
                specs.append(RunSpec(v, scope, name, beta, cfg))
    return specs, checksums


# --------------------------------------------------------------------------
# Worker-side caches (one per process)
# --------------------------------------------------------------------------

_INPUTS: dict[str, RunInput] = {}
_PREPARED: dict[str, EventSet] = {}


def _input(config: ExperimentConfig) -> RunInput:
    key = str(config.eventset.path)
    if key not in _INPUTS:
        _INPUTS[key] = load_input(config)
    return _INPUTS[key]


def _prepared(config: ExperimentConfig) -> EventSet:
    d = config.model_dump(mode="json")
    key = json.dumps(
        [str(config.eventset.path), d["noise"], d["threshold"], d["portfolio"]],
        sort_keys=True,
    )
    if key not in _PREPARED:
        _PREPARED[key] = prepare_eventset(config, _input(config).eventset)
    return _PREPARED[key]


def solve_worker(
    config: ExperimentConfig,
) -> tuple[RunTables, dict[str, Any], float]:
    """Execute one run (no store); return its tables, manifest and seconds."""
    start = time.perf_counter()
    tables, manifest = execute(config, _input(config), policy=DEFAULT_POLICY)
    return tables, manifest, time.perf_counter() - start


def rebuild(
    config: ExperimentConfig,
    runs: pd.DataFrame,
    payouts: pd.DataFrame,
    entities: pd.DataFrame,
) -> list[SolveResult]:
    """Rebuild a stored run's design problems as SolveResults (loss units)."""
    structure = config.to_components().payout
    out: list[SolveResult] = []
    for row in runs.itertuples():
        pid = row.problem_id
        ent = entities[entities["problem_id"] == pid]
        order = list(dict.fromkeys(ent["entity_id"]))
        spec = ProblemSpec(
            pid,
            tuple(
                Entity(e, tuple(ent.loc[ent["entity_id"] == e, "location_id"]))
                for e in order
            ),
        )
        pay = payouts[payouts["problem_id"] == pid]
        theta = np.vstack(
            [
                pay[pay["entity_id"] == e]
                .sort_values("param_index")["value"]
                .to_numpy(dtype=np.float64)
                for e in order
            ]
        )
        out.append(
            SolveResult(
                spec=spec,
                payout_structure=structure,
                theta=theta,
                status=SolveStatus(row.status),
                objective_value=float(row.objective_value),
                premium=float(row.premium),
                scale=1.0,
                solver=str(row.solver),
                attempts=(),
                build_seconds=float(row.build_seconds),
                solve_seconds=float(row.solve_seconds),
            )
        )
    return out


def _check_same(stored: pd.DataFrame, mine: pd.DataFrame, where: str) -> None:
    """Raise unless the runner's stored test intervals equal the recomputed ones."""
    key = ["level", "subject_id", "kpi"]
    merged = stored.merge(mine, on=key, suffixes=("", "_mine"), validate="one_to_one")
    if len(merged) != len(stored) or len(merged) != len(mine):
        raise RuntimeError(f"{where}: stored and recomputed KPI rows differ")
    for column in ("value", "ci_low", "ci_high"):
        a = merged[column].to_numpy(dtype=np.float64, na_value=np.nan)
        b = merged[f"{column}_mine"].to_numpy(dtype=np.float64, na_value=np.nan)
        if not np.allclose(a, b, rtol=1e-9, atol=1e-9, equal_nan=True):
            raise RuntimeError(f"{where}: stored and recomputed {column} differ")


def group_worker(
    variant: Variant,
    scope: str,
    members: list[tuple[str, ExperimentConfig, str]],
    store_root: str,
) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Bootstrap the test KPIs of one (variant, scope) group; pair the designs."""
    start = time.perf_counter()
    store = ResultStore(Path(store_root))
    first = members[0][1]
    prepared = _prepared(first)
    _, test = splits.holdout(prepared, train_fraction=0.7)
    assert first.bootstrap is not None
    resample = resample_years(
        test.years, first.bootstrap.n_bootstrap, first.bootstrap.rng()
    )
    level = first.bootstrap.level
    boots: dict[tuple[str, float], KpiBootstrap] = {}
    kpi_rows: list[pd.DataFrame] = []
    for design, cfg, run_id in members:
        c = cfg.to_components()
        results = rebuild(
            cfg,
            store.read("runs", run_ids=[run_id]),
            store.read("payouts", run_ids=[run_id]),
            store.read("entities", run_ids=[run_id]),
        )
        stored = store.read("kpis", run_ids=[run_id])
        for beta in variant.eval_betas:
            boot = bootstrap_kpis(
                prepared,
                c.scopes[0],
                results,
                basis=c.basis,
                beta=beta,
                run_id=run_id,
                resample=resample,
                sample=test,
                pricing=c.pricing,
                level=level,
            )
            if beta == cfg.evaluation.beta:
                _check_same(
                    stored.loc[stored["eval_split"] == "test"],
                    boot.table,
                    f"{variant.key} {scope} {design}",
                )
            boots[(design, beta)] = boot
            t = boot.table.loc[boot.table["level"] == "portfolio"].copy()
            t["source"] = "c1_bootstrap"
            t["eval_beta"] = beta
            t["design"] = design
            kpi_rows.append(t)
        # the runner's own train and test rows at the config's evaluation beta
        s = stored.loc[stored["level"] == "portfolio"].copy()
        s["source"] = "runner"
        s["eval_beta"] = cfg.evaluation.beta
        s["design"] = design
        kpi_rows.append(s)
    paired_rows: list[pd.DataFrame] = []
    designs = [m[0] for m in members]
    for a in (d for d in designs if d.startswith("wcvar")):
        for b in ("mse", "eu"):
            for beta in variant.eval_betas:
                diff = paired_difference(boots[(a, beta)], boots[(b, beta)])
                diff = diff.loc[diff["level"] == "portfolio"].copy()
                diff["design_a"] = a
                diff["design_b"] = b
                diff["eval_beta"] = beta
                paired_rows.append(diff)
    kpis = pd.concat(kpi_rows, ignore_index=True)
    paired = pd.concat(paired_rows, ignore_index=True)
    for frame in (kpis, paired):
        frame["variant"] = variant.key
        frame["scope"] = scope
    return kpis, paired, time.perf_counter() - start


def _variant_columns(frame: pd.DataFrame, by_key: dict[str, Variant]) -> pd.DataFrame:
    """Add the variant's fields as columns."""
    v = frame["variant"].map(by_key)
    # the kpis table has its own evaluation ``basis`` column: the variant's
    frame = frame.drop(columns=["basis"], errors="ignore")
    frame.insert(0, "kappa", v.map(lambda x: x.kappa))
    frame.insert(0, "pricing", v.map(lambda x: x.pricing))
    frame.insert(0, "basis", v.map(lambda x: x.basis))
    frame.insert(0, "eventset", v.map(lambda x: x.eventset))
    frame.insert(0, "family", v.map(lambda x: x.family))
    return frame


SLIM_KPIS: Final[tuple[str, ...]] = (
    "expected_loss",
    "expected_payout",
    "expected_uncovered",
    "var_uncovered",
    "cvar_uncovered",
    "rmse_residual",
    "correlation",
    "premium",
)
SLIM_PAIRED_KPIS: Final[tuple[str, ...]] = (
    "expected_payout",
    "expected_uncovered",
    "var_uncovered",
    "cvar_uncovered",
    "rmse_residual",
    "premium",
)
TAIL_KPIS: Final[tuple[str, ...]] = ("var_uncovered", "cvar_uncovered")
GROUP_KEY: Final[list[str]] = [
    "family",
    "eventset",
    "basis",
    "pricing",
    "kappa",
    "scope",
]


def _one_beta(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the beta-free KPIs once (at the group's lowest evaluation beta)."""
    keys = [*GROUP_KEY, *(c for c in ("source", "eval_split") if c in frame)]
    first = frame.groupby(keys)["eval_beta"].transform("min")
    keep = frame["kpi"].isin(TAIL_KPIS) | (frame["eval_beta"] == first)
    return pd.DataFrame(frame.loc[keep])


def write_slim(full: Path, out: Path) -> None:
    """Write the committed tables, each under the 500 kB pre-commit limit.

    The full tables in ``full`` (not committed) hold every KPI, with run ids
    and config hashes on every row. The committed ones keep the
    portfolio-level KPIs the checkpoint uses (test rows of the C1 bootstrap,
    train rows of the runner), the beta-free KPIs once, one file per family;
    ``runs.csv`` maps every (family, eventset, basis, pricing, kappa, scope,
    design) to its config hash and run id.
    """
    out.mkdir(parents=True, exist_ok=True)
    runs = pd.read_csv(full / "runs.csv")
    runs.to_csv(out / "runs.csv", index=False, float_format="%.10g")
    kpis = pd.read_csv(full / "kpis.csv")
    kpis = kpis.loc[
        kpis["kpi"].isin(SLIM_KPIS)
        & (
            (kpis["source"] == "c1_bootstrap")
            | ((kpis["source"] == "runner") & (kpis["eval_split"] == "train"))
        )
    ]
    kpis = _one_beta(kpis).drop(
        columns=["beta", "ci_level", "n_bootstrap", "run_id", "config_hash"]
    )
    paired = pd.read_csv(full / "paired.csv")
    paired = _one_beta(paired.loc[paired["kpi"].isin(SLIM_PAIRED_KPIS)]).drop(
        columns=[
            "relative",
            "ci_low_relative",
            "ci_high_relative",
            "ci_level",
            "n_bootstrap",
            "config_hash_a",
            "config_hash_b",
            "run_id_a",
            "run_id_b",
        ]
    )
    for family in sorted(set(runs["family"])):
        for name, frame in (("kpis", kpis), ("paired", paired)):
            part = frame.loc[frame["family"] == family]
            part.to_csv(out / f"{name}_{family}.csv", index=False, float_format="%.7g")
    summary = json.loads((full / "summary.json").read_text())
    summary["committed_tables"] = {
        "runs.csv": "every run: config_hash, run_id, solvers, statuses, budget use",
        "kpis_<family>.csv": "portfolio KPIs: test (C1 bootstrap), train (runner)",
        "paired_<family>.csv": "paired differences on the test years",
        "full tables": "results/c1/full/ (not committed), written by this script",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Plan, solve, bootstrap and write the C1 tables."""
    parser = argparse.ArgumentParser(description="Checkpoint C1 runs (MAR-29).")
    parser.add_argument("--jobs", type=int, default=3, help="worker processes")
    parser.add_argument(
        "--families",
        nargs="+",
        default=["main", "reference", "f12"],
        choices=["main", "reference", "f12"],
    )
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--full", type=Path, default=FULL_DIR, help="full tables")
    parser.add_argument("--plan-only", action="store_true", help="print counts")
    parser.add_argument(
        "--slim-only",
        action="store_true",
        help="only rewrite the committed tables from the full ones",
    )
    args = parser.parse_args(argv)
    if args.slim_only:
        write_slim(args.full, args.out)
        return 0

    t0 = time.perf_counter()
    specs, checksums = plan(args.families)
    store = ResultStore(args.store)
    thesis_checksum = load_config(BASE_CONFIG).eventset.checksum
    assert thesis_checksum is not None
    sums = {"thesis": thesis_checksum, **checksums}
    run_ids = [
        run_key(config_hash(s.config), sums[s.variant.eventset], policy=DEFAULT_POLICY)
        for s in specs
    ]
    todo: dict[str, ExperimentConfig] = {}
    for s, rid in zip(specs, run_ids, strict=True):
        if not store.has_run(rid) and rid not in todo:
            todo[rid] = s.config
    print(
        f"{len(specs)} runs planned, {len(set(run_ids))} distinct, "
        f"{len(todo)} to solve",
        flush=True,
    )
    if args.plan_only:
        return 0

    # Phase A: solve, the parent writes.
    solve_seconds: dict[str, float] = {}
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futures = {pool.submit(solve_worker, cfg): rid for rid, cfg in todo.items()}
        for i, fut in enumerate(as_completed(futures), 1):
            tables, manifest, seconds = fut.result()
            rid = futures[fut]
            if manifest["run_id"] != rid:
                raise RuntimeError(f"run id mismatch: {manifest['run_id']} != {rid}")
            store.write_run(tables, manifest)
            solve_seconds[rid] = seconds
            print(f"[A {i}/{len(todo)}] {rid[7:19]} {seconds:.1f}s", flush=True)
    for rid in set(run_ids):
        outcome = RunOutcome.from_manifest(store.manifest(rid), cached=True)
        if not outcome.ok:
            raise RuntimeError(f"run {rid} failed or was not evaluated: {outcome}")
    t_a = time.perf_counter() - t0

    # Phase B: bootstrap per (variant, scope) group.
    groups: dict[tuple[str, str], list[tuple[str, ExperimentConfig, str]]] = {}
    by_key: dict[str, Variant] = {}
    for s, rid in zip(specs, run_ids, strict=True):
        by_key[s.variant.key] = s.variant
        groups.setdefault((s.variant.key, s.scope), []).append(
            (s.design, s.config, rid)
        )
    kpi_frames: list[pd.DataFrame] = []
    paired_frames: list[pd.DataFrame] = []
    group_seconds: dict[str, float] = {}
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {
            pool.submit(group_worker, by_key[k], scope, members, str(args.store)): (
                k,
                scope,
            )
            for (k, scope), members in groups.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            kp, pa, seconds = fut.result()
            kpi_frames.append(kp)
            paired_frames.append(pa)
            k, scope = futs[fut]
            group_seconds[f"{k}|{scope}"] = round(seconds, 1)
            print(f"[B {i}/{len(futs)}] {k} {scope} {seconds:.1f}s", flush=True)
    t_b = time.perf_counter() - t0 - t_a

    # Tables.
    hashes = {rid: config_hash(s.config) for s, rid in zip(specs, run_ids, strict=True)}
    design_of = {
        (s.variant.key, s.scope, s.design): rid
        for s, rid in zip(specs, run_ids, strict=True)
    }
    kpis = pd.concat(kpi_frames, ignore_index=True)
    kpis["config_hash"] = kpis["run_id"].map(hashes)
    kpis = _variant_columns(kpis, by_key)
    kpis = kpis[
        [
            "family",
            "eventset",
            "basis",
            "pricing",
            "kappa",
            "scope",
            "design",
            "source",
            "eval_split",
            "kpi",
            "eval_beta",
            "beta",
            "value",
            "ci_low",
            "ci_high",
            "ci_level",
            "n_bootstrap",
            "config_hash",
            "run_id",
        ]
    ].sort_values(
        ["family", "eventset", "basis", "pricing", "kappa", "scope", "design"],
        kind="stable",
    )
    paired = pd.concat(paired_frames, ignore_index=True)
    paired["config_hash_a"] = paired.apply(
        lambda r: hashes[design_of[(r["variant"], r["scope"], r["design_a"])]], axis=1
    )
    paired["config_hash_b"] = paired.apply(
        lambda r: hashes[design_of[(r["variant"], r["scope"], r["design_b"])]], axis=1
    )
    paired["relative"] = paired["difference"] / paired["value_b"]
    paired["ci_low_relative"] = paired["ci_low"] / paired["value_b"]
    paired["ci_high_relative"] = paired["ci_high"] / paired["value_b"]
    paired = _variant_columns(paired, by_key)
    paired = paired[
        [
            "family",
            "eventset",
            "basis",
            "pricing",
            "kappa",
            "scope",
            "design_a",
            "design_b",
            "eval_split",
            "kpi",
            "eval_beta",
            "value_a",
            "value_b",
            "difference",
            "ci_low",
            "ci_high",
            "relative",
            "ci_low_relative",
            "ci_high_relative",
            "ci_level",
            "n_bootstrap",
            "config_hash_a",
            "config_hash_b",
            "run_id_a",
            "run_id_b",
        ]
    ]

    run_rows = []
    all_runs = store.read("runs", run_ids=sorted(set(run_ids)))
    stored_kpis = store.read("kpis", run_ids=sorted(set(run_ids)))
    for s, rid in zip(specs, run_ids, strict=True):
        r = all_runs.loc[all_runs["run_id"] == rid]
        train = stored_kpis.loc[
            (stored_kpis["run_id"] == rid)
            & (stored_kpis["level"] == "portfolio")
            & (stored_kpis["eval_split"] == "train")
        ]
        el = float(train.loc[train["kpi"] == "expected_loss", "value"].iloc[0])
        run_rows.append(
            {
                "family": s.variant.family,
                "eventset": s.variant.eventset,
                "basis": s.variant.basis,
                "pricing": s.variant.pricing,
                "kappa": s.variant.kappa,
                "scope": s.scope,
                "design": s.design,
                "objective": s.objective,
                "objective_beta": s.objective_beta,
                "n_problems": len(r),
                "statuses": ",".join(sorted(set(r["status"].astype(str)))),
                "solvers": ",".join(sorted(set(r["solver"].astype(str)))),
                "sum_problem_premiums": float(r["premium"].sum()),
                "budget": s.variant.kappa * el,
                "budget_use": float(r["premium"].sum()) / (s.variant.kappa * el),
                "solve_seconds": float(r["solve_seconds"].sum()),
                "build_seconds": float(r["build_seconds"].sum()),
                "config_hash": hashes[rid],
                "run_id": rid,
            }
        )
    runs = pd.DataFrame(run_rows)

    args.full.mkdir(parents=True, exist_ok=True)
    runs.to_csv(args.full / "runs.csv", index=False, float_format="%.10g")
    kpis.to_csv(args.full / "kpis.csv", index=False, float_format="%.10g")
    paired.to_csv(args.full / "paired.csv", index=False, float_format="%.10g")
    manifest = store.manifest(run_ids[0])
    summary = {
        "issue": "MAR-29",
        "base_config": str(BASE_CONFIG.relative_to(REPO_ROOT)),
        "families": list(args.families),
        "pricings": PRICINGS,
        "main_kappas": MAIN_KAPPAS,
        "main_wcvar_betas": MAIN_BETAS,
        "annual_eval_betas": ANNUAL_EVAL_BETAS,
        "reference_eval_betas": REFERENCE_EVAL_BETAS,
        "f12_wcvar_betas": F12_BETAS,
        "f12_pricings": F12_PRICINGS,
        "f12_eventsets": {
            k: {
                "directory": v.directory,
                "index": v.index,
                "label": v.label,
                "content_hash": checksums.get(k),
            }
            for k, v in F12_EVENTSETS.items()
        },
        "thesis_eventset_checksum": thesis_checksum,
        "package_version": manifest["cache_key"]["package_version"],
        "solver_policy": manifest["cache_key"]["solver_policy"],
        "n_runs_planned": len(specs),
        "n_runs_distinct": len(set(run_ids)),
        "n_runs_solved_this_call": len(todo),
        "jobs": args.jobs,
        "seconds": {"solve_phase": round(t_a, 1), "bootstrap_phase": round(t_b, 1)},
        "solve_seconds_per_run": {
            k[7:19]: round(v, 1) for k, v in solve_seconds.items()
        },
        "bootstrap_seconds_per_group": group_seconds,
    }
    (args.full / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    write_slim(args.full, args.out)
    print(
        f"wrote {args.full} and {args.out} in {time.perf_counter() - t0:.0f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
