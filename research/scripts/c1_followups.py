r"""C1 follow-ups on the thesis portfolio (MAR-205): four RQ1 run families.

Split from MAR-152 items 1, 2, 3 and 5. Observations only; the note is
``research/notes/c1-followups.md``. The grid is
``research/configs/c1-followups/followups.yaml``; every run derives from the
C1 base config ``research/configs/c1/c1_main.yaml`` the way C1's own runs do
(``c1_checkpoint.single_config``).

Families (``--family``):

``budget`` (MAR-152 item 3)
    No runs. Budget use next to the tail KPI in C1's kappa sweep, read from
    the committed C1 tables (``research/data/c1/``).
``coc_q`` (item 1)
    Cost-of-capital pricing with q 0.95 and 0.995 (C1 ran q 0.99 only), r 0.06
    and 0.10, kappa 1, every scope; MSE, E[U] and weighted CVaR at beta 0.99
    and 0.995; test KPIs bootstrapped at KPI beta 0.95, 0.99, 0.995.
``beta_draws`` (item 2)
    Weighted CVaR at beta 0.995, 0.998 and 0.999 on the F-12 EventSets with
    vulnerability draws (``vuln``, ``cic50_vuln``, ``vuln_basins_null``),
    pure and r 0.06 (q 0.99), kappa 1, every scope, next to C1's MSE, E[U] and
    beta 0.99 designs.
``coverage`` (item 4)
    A simulation study of the percentile year-block bootstrap interval of
    CVaR on the annual basis (setup in the YAML and the note).

Runs whose run id is already in the C1 store (``--c1-store``, opened
read-only: this script never writes to it) are read from there; the others
are solved into ``--store``. Phase B bootstraps each (variant, scope) group's
test KPIs on one shared resample (seed 0, B 1000, level 0.9, as C1), so the
designs of a group are paired, and adds the train point KPIs at every KPI
beta.

Outputs: full tables in ``results/c1-followups/full/`` (not committed), slim
ones (portfolio level, under 500 kB) in ``research/data/c1-followups/``.

Run from the repository root::

    C1_STORE=<C1 worktree>/results/c1/store \
    C1_EVENTSETS=<C1 worktree>/results/c1/eventsets \
    uv run python research/scripts/c1_followups.py --family coc_q --jobs 2
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Final

import c1_checkpoint as c1
import numpy as np
import pandas as pd
import yaml

from parametric_insurance_design import splits
from parametric_insurance_design.basis import Basis, OutcomeMeasure, outcome_measure
from parametric_insurance_design.bootstrap import (
    KpiBootstrap,
    bootstrap_kpis,
    kpi_replicates,
    paired_difference,
    percentile_interval,
    resample_years,
)
from parametric_insurance_design.evaluate import evaluate_results, kpis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import RunOutcome, run_key
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.riskmeasures import var_cvar
from parametric_insurance_design.solve import DEFAULT_POLICY

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
GRID: Final[Path] = (
    REPO_ROOT / "research" / "configs" / "c1-followups" / "followups.yaml"
)
C1_DATA: Final[Path] = REPO_ROOT / "research" / "data" / "c1"
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "c1-followups"
STORE: Final[Path] = REPO_ROOT / "results" / "c1-followups" / "store"
FULL_DIR: Final[Path] = REPO_ROOT / "results" / "c1-followups" / "full"
C1_STORE: Final[Path] = Path(
    os.environ.get("C1_STORE", REPO_ROOT / "results" / "c1" / "store")
)
EVENTSETS: Final[Path] = Path(
    os.environ.get("C1_EVENTSETS", REPO_ROOT / "results" / "c1" / "eventsets")
)
SCOPES: Final[tuple[str, ...]] = ("individual", "cluster", "portfolio")
SLIM_KPIS: Final[tuple[str, ...]] = (
    "expected_loss",
    "expected_payout",
    "expected_uncovered",
    "var_uncovered",
    "cvar_uncovered",
    "rmse_residual",
    "premium",
)


def grid() -> dict[str, Any]:
    """Return the follow-up grid (``followups.yaml``)."""
    return yaml.safe_load(GRID.read_text())


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Variant:
    """Everything but the scope and the design."""

    family: str
    eventset: str
    pricing: str
    pricing_spec: tuple[tuple[str, Any], ...]
    kappa: float
    wcvar_betas: tuple[float, ...]
    eval_betas: tuple[float, ...]

    @property
    def key(self) -> str:
        """Short id."""
        return f"{self.family}|{self.eventset}|{self.pricing}|k{self.kappa:g}"


@dataclass(frozen=True)
class RunSpec:
    """One single run: a variant, a scope and a design."""

    variant: Variant
    scope: str
    design: str
    config: ExperimentConfig = field(compare=False)


def variants(family: str, g: dict[str, Any]) -> list[Variant]:
    """Return the variants of one run family."""
    spec = g[family]
    out: list[Variant] = []
    if family == "coc_q":
        for name, pricing in spec["pricings"].items():
            out.append(
                Variant(
                    family,
                    "thesis",
                    name,
                    tuple(sorted(pricing.items())),
                    float(spec["kappa"]),
                    tuple(spec["wcvar_betas"]),
                    tuple(spec["eval_betas"]),
                )
            )
    elif family == "beta_draws":
        for es in spec["eventsets"]:
            for name, pricing in spec["pricings"].items():
                out.append(
                    Variant(
                        family,
                        es,
                        name,
                        tuple(sorted(pricing.items())),
                        float(spec["kappa"]),
                        tuple(spec["wcvar_betas"]),
                        tuple(spec["eval_betas"]),
                    )
                )
    else:
        raise ValueError(f"{family} has no runs")
    return out


def eventset_checksums(names: set[str]) -> dict[str, str]:
    """Content hashes of the F-12 EventSets (raises if one is missing)."""
    out: dict[str, str] = {}
    for name in sorted(names - {"thesis"}):
        path = EVENTSETS / c1.F12_EVENTSETS[name].directory
        if not path.is_dir():
            raise FileNotFoundError(
                f"F-12 EventSet {path} is missing: set C1_EVENTSETS to the C1 "
                "EventSets (research/scripts/c1_build_eventsets.sh)"
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
    """Return the single-run config of one (variant, scope, objective).

    The same derivation as ``c1_checkpoint.single_config``, with the pricing
    taken from the variant, so a run equal to a C1 run has C1's hash.
    """
    data = json.loads(json.dumps(base))
    data["name"] = f"c1-followups-{variant.family}"
    data["basis"] = "annual"
    data["pricing"] = dict(variant.pricing_spec)
    data["constraints"] = [{"kind": "budget", "loading": variant.kappa}]
    data["scopes"] = [s for s in base["scopes"] if s["kind"] == scope]
    data["objectives"] = [objective]
    if variant.eventset != "thesis":
        spec = c1.F12_EVENTSETS[variant.eventset]
        data["eventset"] = {
            "path": str(EVENTSETS / spec.directory),
            "checksum": checksums[variant.eventset],
        }
        data["noise"] = None
        if spec.index == "cat_in_circle":
            data["threshold"] = None
            data["payout"] = c1.CAT_PAYOUT
    return parse_config(data)


def objectives(wcvar_betas: tuple[float, ...]) -> list[tuple[str, dict[str, Any]]]:
    """(design label, objective config) of MSE, E[U] and each weighted CVaR."""
    out: list[tuple[str, dict[str, Any]]] = [
        ("mse", {"kind": "mse"}),
        ("eu", {"kind": "expected_uncovered"}),
    ]
    out += [
        (f"wcvar@{b:g}", {"kind": "weighted_cvar", "alpha": 0.9, "beta": b})
        for b in wcvar_betas
    ]
    return out


def base_dict(store: Path) -> dict[str, Any]:
    """Return the C1 base config as a dict, with the output directory set."""
    base = load_config(c1.BASE_CONFIG).model_dump(mode="json")
    base["output"] = {"directory": str(store)}
    return base


def plan(family: str, store: Path) -> tuple[list[RunSpec], dict[str, str]]:
    """Every single run of a family, and the EventSet checksums."""
    g = grid()
    base = base_dict(store)
    vs = variants(family, g)
    thesis = load_config(c1.BASE_CONFIG).eventset.checksum
    assert thesis is not None
    checksums = {"thesis": thesis, **eventset_checksums({v.eventset for v in vs})}
    specs = [
        RunSpec(v, scope, design, single_config(base, v, scope, obj, checksums))
        for v in vs
        for scope in SCOPES
        for design, obj in objectives(v.wcvar_betas)
    ]
    return specs, checksums


def store_of(run_id: str, mine: ResultStore, c1_store: ResultStore) -> str | None:
    """Root of the store that holds a run (ours first), or None."""
    if mine.has_run(run_id):
        return str(mine.root)
    if c1_store.has_run(run_id):
        return str(c1_store.root)
    return None


def group_worker(
    variant: Variant,
    scope: str,
    members: list[tuple[str, ExperimentConfig, str, str]],
    pairs: list[tuple[str, str]],
) -> tuple[pd.DataFrame, pd.DataFrame, float]:
    """Bootstrap one (variant, scope) group's test KPIs; pair its designs.

    Like ``c1_checkpoint.group_worker``, with a store per member and the
    train point KPIs at every KPI beta (``evaluate.kpis``).
    """
    start = time.perf_counter()
    first = members[0][1]
    prepared = c1._prepared(first)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    assert first.bootstrap is not None
    resample = resample_years(
        test.years, first.bootstrap.n_bootstrap, first.bootstrap.rng()
    )
    level = first.bootstrap.level
    boots: dict[tuple[str, float], KpiBootstrap] = {}
    rows: list[pd.DataFrame] = []
    for design, cfg, run_id, root in members:
        store = ResultStore(Path(root))
        c = cfg.to_components()
        results = c1.rebuild(
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
                c1._check_same(
                    stored.loc[stored["eval_split"] == "test"],
                    boot.table,
                    f"{variant.key} {scope} {design}",
                )
            boots[(design, beta)] = boot
            t = boot.table.loc[boot.table["level"] == "portfolio"].copy()
            t["source"] = "bootstrap"
            t["eval_beta"] = beta
            t["design"] = design
            rows.append(t)
            tr = kpis(
                prepared,
                c.scopes[0],
                results,
                basis=c.basis,
                beta=beta,
                run_id=run_id,
                sample=train,
                pricing=c.pricing,
            )
            tr = tr.loc[tr["level"] == "portfolio"].copy()
            tr["source"] = "train_point"
            tr["eval_beta"] = beta
            tr["design"] = design
            rows.append(tr)
    paired_rows: list[pd.DataFrame] = []
    for a, b in pairs:
        for beta in variant.eval_betas:
            diff = paired_difference(boots[(a, beta)], boots[(b, beta)])
            diff = diff.loc[diff["level"] == "portfolio"].copy()
            diff["design_a"] = a
            diff["design_b"] = b
            diff["eval_beta"] = beta
            paired_rows.append(diff)
    out_k = pd.concat(rows, ignore_index=True)
    out_p = pd.concat(paired_rows, ignore_index=True)
    for frame in (out_k, out_p):
        frame["variant"] = variant.key
        frame["scope"] = scope
    return out_k, out_p, time.perf_counter() - start


def pairs_of(designs: list[str]) -> list[tuple[str, str]]:
    """Weighted CVaR against MSE and E[U]; the higher betas against 0.99."""
    out: list[tuple[str, str]] = []
    for a in (d for d in designs if d.startswith("wcvar")):
        out += [(a, "mse"), (a, "eu")]
        if a != "wcvar@0.99" and "wcvar@0.99" in designs:
            out.append((a, "wcvar@0.99"))
    return out


def _variant_columns(frame: pd.DataFrame, by_key: dict[str, Variant]) -> pd.DataFrame:
    v = frame["variant"].map(by_key)
    frame = frame.drop(columns=["basis"], errors="ignore")
    frame.insert(0, "kappa", v.map(lambda x: x.kappa))
    frame.insert(0, "pricing", v.map(lambda x: x.pricing))
    frame.insert(0, "eventset", v.map(lambda x: x.eventset))
    frame.insert(0, "family", v.map(lambda x: x.family))
    return frame


def run_family(family: str, args: argparse.Namespace) -> None:
    """Solve (where needed), bootstrap and write one run family."""
    t0 = time.perf_counter()
    specs, checksums = plan(family, args.store)
    mine = ResultStore(args.store)
    c1_store = ResultStore(args.c1_store)
    run_ids = [
        run_key(
            config_hash(s.config), checksums[s.variant.eventset], policy=DEFAULT_POLICY
        )
        for s in specs
    ]
    todo: dict[str, ExperimentConfig] = {}
    for s, rid in zip(specs, run_ids, strict=True):
        if store_of(rid, mine, c1_store) is None and rid not in todo:
            todo[rid] = s.config
    n_c1 = sum(
        1 for rid in set(run_ids) if not mine.has_run(rid) and c1_store.has_run(rid)
    )
    print(
        f"{family}: {len(specs)} runs, {len(set(run_ids))} distinct, "
        f"{n_c1} from the C1 store, {len(todo)} to solve",
        flush=True,
    )
    if args.plan_only:
        return

    solve_seconds: dict[str, float] = {}
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futures = {pool.submit(c1.solve_worker, cfg): rid for rid, cfg in todo.items()}
        for i, fut in enumerate(as_completed(futures), 1):
            tables, manifest, seconds = fut.result()
            rid = futures[fut]
            if manifest["run_id"] != rid:
                raise RuntimeError(f"run id mismatch: {manifest['run_id']} != {rid}")
            mine.write_run(tables, manifest)
            solve_seconds[rid] = seconds
            print(f"[A {i}/{len(todo)}] {rid[7:19]} {seconds:.1f}s", flush=True)
    roots: dict[str, str] = {}
    for rid in set(run_ids):
        root = store_of(rid, mine, c1_store)
        if root is None:
            raise RuntimeError(f"run {rid} is in neither store")
        roots[rid] = root
        outcome = RunOutcome.from_manifest(ResultStore(root).manifest(rid), cached=True)
        if not outcome.ok:
            raise RuntimeError(f"run {rid} failed or was not evaluated: {outcome}")
    t_a = time.perf_counter() - t0

    groups: dict[tuple[str, str], list[tuple[str, ExperimentConfig, str, str]]] = {}
    by_key: dict[str, Variant] = {}
    for s, rid in zip(specs, run_ids, strict=True):
        by_key[s.variant.key] = s.variant
        groups.setdefault((s.variant.key, s.scope), []).append(
            (s.design, s.config, rid, roots[rid])
        )
    kpi_frames: list[pd.DataFrame] = []
    paired_frames: list[pd.DataFrame] = []
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {
            pool.submit(
                group_worker,
                by_key[k],
                scope,
                members,
                pairs_of([m[0] for m in members]),
            ): (k, scope)
            for (k, scope), members in groups.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            kp, pa, seconds = fut.result()
            kpi_frames.append(kp)
            paired_frames.append(pa)
            k, scope = futs[fut]
            print(f"[B {i}/{len(futs)}] {k} {scope} {seconds:.1f}s", flush=True)
    t_b = time.perf_counter() - t0 - t_a

    hashes = {rid: config_hash(s.config) for s, rid in zip(specs, run_ids, strict=True)}
    design_of = {
        (s.variant.key, s.scope, s.design): rid
        for s, rid in zip(specs, run_ids, strict=True)
    }
    kp = pd.concat(kpi_frames, ignore_index=True)
    kp["config_hash"] = kp["run_id"].map(hashes)
    kp = _variant_columns(kp, by_key)
    pa = pd.concat(paired_frames, ignore_index=True)
    for side in ("a", "b"):
        pa[f"config_hash_{side}"] = pa.apply(
            lambda r, s=side: hashes[
                design_of[(r["variant"], r["scope"], r[f"design_{s}"])]
            ],
            axis=1,
        )
    pa["relative"] = pa["difference"] / pa["value_b"]
    pa["ci_low_relative"] = pa["ci_low"] / pa["value_b"]
    pa["ci_high_relative"] = pa["ci_high"] / pa["value_b"]
    pa = _variant_columns(pa, by_key)

    run_rows = []
    for s, rid in zip(specs, run_ids, strict=True):
        st = ResultStore(roots[rid])
        r = st.read("runs", run_ids=[rid])
        sk = st.read("kpis", run_ids=[rid])
        train = sk.loc[(sk["level"] == "portfolio") & (sk["eval_split"] == "train")]
        el = float(train.loc[train["kpi"] == "expected_loss", "value"].iloc[0])
        ep = float(train.loc[train["kpi"] == "expected_payout", "value"].iloc[0])
        prem = float(train.loc[train["kpi"] == "premium", "value"].iloc[0])
        budget = s.variant.kappa * el
        run_rows.append(
            {
                "family": family,
                "eventset": s.variant.eventset,
                "pricing": s.variant.pricing,
                "kappa": s.variant.kappa,
                "scope": s.scope,
                "design": s.design,
                "n_problems": len(r),
                "statuses": ",".join(sorted(set(r["status"].astype(str)))),
                "solvers": ",".join(sorted(set(r["solver"].astype(str)))),
                "train_expected_loss": el,
                "train_expected_payout": ep,
                "train_portfolio_premium": prem,
                "sum_problem_premiums": float(r["premium"].sum()),
                "budget": budget,
                "budget_use": float(r["premium"].sum()) / budget,
                "solve_seconds": float(r["solve_seconds"].sum()),
                "store": "c1" if roots[rid] == str(c1_store.root) else "followups",
                "config_hash": hashes[rid],
                "run_id": rid,
            }
        )
    runs = pd.DataFrame(run_rows)

    args.full.mkdir(parents=True, exist_ok=True)
    runs.to_csv(args.full / f"{family}_runs.csv", index=False, float_format="%.10g")
    kp.to_csv(args.full / f"{family}_kpis.csv", index=False, float_format="%.10g")
    pa.to_csv(args.full / f"{family}_paired.csv", index=False, float_format="%.10g")
    summary = {
        "issue": "MAR-205",
        "family": family,
        "grid": str(GRID.relative_to(REPO_ROOT)),
        "base_config": str(c1.BASE_CONFIG.relative_to(REPO_ROOT)),
        "eventset_checksums": checksums,
        "package_version": ResultStore(roots[run_ids[0]]).manifest(run_ids[0])[
            "cache_key"
        ]["package_version"],
        "n_runs": len(specs),
        "n_runs_distinct": len(set(run_ids)),
        "n_runs_from_c1_store": n_c1,
        "n_runs_solved_this_call": len(todo),
        "jobs": args.jobs,
        "seconds": {"solve_phase": round(t_a, 1), "bootstrap_phase": round(t_b, 1)},
        "solve_seconds_per_run": {
            k[7:19]: round(v, 1) for k, v in solve_seconds.items()
        },
    }
    (args.full / f"{family}_summary.json").write_text(
        json.dumps(summary, indent=2) + "\n"
    )
    write_slim(family, args.full, args.out)
    print(f"{family}: done in {time.perf_counter() - t0:.0f}s", flush=True)


def write_slim(family: str, full: Path, out: Path) -> None:
    """Write the committed tables of a run family (portfolio level, < 500 kB)."""
    out.mkdir(parents=True, exist_ok=True)
    runs = pd.read_csv(full / f"{family}_runs.csv")
    runs.to_csv(out / f"{family}_runs.csv", index=False, float_format="%.10g")
    kp = pd.read_csv(full / f"{family}_kpis.csv")
    keep = kp["kpi"].isin(SLIM_KPIS) & (kp["source"].isin(["bootstrap", "train_point"]))
    kp = kp.loc[keep]
    beta_free = ~kp["kpi"].isin(["var_uncovered", "cvar_uncovered"])
    first = kp.groupby(["variant", "scope", "source"])["eval_beta"].transform("min")
    kp = kp.loc[~beta_free | (kp["eval_beta"] == first)]
    cols = [
        "family",
        "eventset",
        "pricing",
        "kappa",
        "scope",
        "design",
        "eval_split",
        "kpi",
        "eval_beta",
        "value",
        "ci_low",
        "ci_high",
    ]
    kp = kp[cols].copy()
    kp["config_hash"] = pd.read_csv(full / f"{family}_kpis.csv").loc[
        kp.index, "config_hash"
    ]
    kp["config_hash"] = kp["config_hash"].str[7:19]
    kp.to_csv(out / f"{family}_kpis.csv", index=False, float_format="%.7g")
    pa = pd.read_csv(full / f"{family}_paired.csv")
    pa = pa.loc[pa["kpi"].isin(SLIM_KPIS)]
    beta_free = ~pa["kpi"].isin(["var_uncovered", "cvar_uncovered"])
    first = pa.groupby(["variant", "scope"])["eval_beta"].transform("min")
    pa = pa.loc[~beta_free | (pa["eval_beta"] == first)]
    pa = pa[
        [
            "family",
            "eventset",
            "pricing",
            "kappa",
            "scope",
            "design_a",
            "design_b",
            "kpi",
            "eval_beta",
            "value_a",
            "value_b",
            "difference",
            "ci_low",
            "ci_high",
            "relative",
            "config_hash_a",
            "config_hash_b",
        ]
    ].copy()
    for side in ("a", "b"):
        pa[f"config_hash_{side}"] = pa[f"config_hash_{side}"].str[7:19]
    pa.to_csv(out / f"{family}_paired.csv", index=False, float_format="%.7g")
    summary = json.loads((full / f"{family}_summary.json").read_text())
    summary.pop("solve_seconds_per_run", None)
    (out / f"{family}_summary.json").write_text(json.dumps(summary, indent=2) + "\n")


# --------------------------------------------------------------------------
# Family "budget": C1's kappa sweep, no runs
# --------------------------------------------------------------------------


def budget_table(out: Path) -> pd.DataFrame:
    """Budget use next to the tail KPI in C1's kappa sweep (family main)."""
    g = grid()["budget"]
    beta = float(g["eval_beta"])
    runs = pd.read_csv(C1_DATA / "runs.csv")
    runs = runs.loc[runs["family"] == g["family"]]
    kp = pd.read_csv(C1_DATA / f"kpis_{g['family']}.csv")
    key = ["pricing", "kappa", "scope", "design"]

    def pick(split: str, source: str, kpi: str, b: float | None) -> pd.DataFrame:
        sel = (kp["eval_split"] == split) & (kp["source"] == source)
        sel &= kp["kpi"] == kpi
        part = kp.loc[sel]
        if b is not None:
            part = part.loc[part["eval_beta"] == b]
        return part.set_index(key)[["value", "ci_low", "ci_high"]]

    t = runs.set_index(key)[
        ["budget", "sum_problem_premiums", "budget_use", "config_hash"]
    ].copy()
    t["train_expected_payout"] = pick("train", "runner", "expected_payout", None)[
        "value"
    ]
    t["train_portfolio_premium"] = pick("train", "runner", "premium", None)["value"]
    t["train_expected_loss"] = pick("train", "runner", "expected_loss", None)["value"]
    t["payout_to_train_loss"] = t["train_expected_payout"] / t["train_expected_loss"]
    t["portfolio_premium_use"] = t["train_portfolio_premium"] / t["budget"]
    t["train_expected_uncovered"] = pick("train", "runner", "expected_uncovered", None)[
        "value"
    ]
    t["train_cvar_uncovered"] = pick("train", "runner", "cvar_uncovered", beta)["value"]
    test_cvar = pick("test", "c1_bootstrap", "cvar_uncovered", beta)
    t["test_cvar_uncovered"] = test_cvar["value"]
    t["test_cvar_ci_low"] = test_cvar["ci_low"]
    t["test_cvar_ci_high"] = test_cvar["ci_high"]
    test_eu = pick("test", "c1_bootstrap", "expected_uncovered", 0.95)
    t["test_expected_uncovered"] = test_eu["value"]
    t["test_expected_payout"] = pick("test", "c1_bootstrap", "expected_payout", 0.95)[
        "value"
    ]
    t["test_premium"] = pick("test", "c1_bootstrap", "premium", 0.95)["value"]
    t["test_premium_to_budget"] = t["test_premium"] / t["budget"]
    t["eval_beta"] = beta
    t = t.reset_index()
    if t.isna().any().any():
        missing = t.columns[t.isna().any()].tolist()
        raise RuntimeError(f"budget table has missing values in {missing}")
    t["config_hash"] = t["config_hash"].str[7:19]
    out.mkdir(parents=True, exist_ok=True)
    t.to_csv(out / "budget_use.csv", index=False, float_format="%.7g")
    return t


# --------------------------------------------------------------------------
# Family "coverage": a simulation study of the percentile interval
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Population:
    """Per-row portfolio loss and payouts of fixed designs on all years."""

    loss: np.ndarray
    payouts: dict[str, np.ndarray]
    row_year: np.ndarray
    row_draw: np.ndarray
    n_years: int
    n_draws: int
    hashes: dict[str, str]


def annual_measure(
    rows_slot: np.ndarray, n_slots: int
) -> tuple[OutcomeMeasure, np.ndarray]:
    """Build the annual measure of rows with slot ids (``basis._annual_measure``).

    One outcome per occupied (year, draw) slot with probability 1 / n_slots,
    plus one pooled outcome for the empty slots.
    """
    occupied, outcome_of_row = np.unique(rows_slot, return_inverse=True)
    prob = np.full(occupied.size, 1.0 / n_slots)
    n_empty = n_slots - occupied.size
    if n_empty:
        prob = np.append(prob, n_empty / n_slots)
    measure = OutcomeMeasure(
        basis=Basis.ANNUAL,
        outcome_of_row=outcome_of_row.reshape(-1),
        probability=prob,
    )
    return measure, occupied


def point_kpis(
    loss: np.ndarray, payout: np.ndarray, measure: OutcomeMeasure, beta: float
) -> dict[str, float]:
    """CVaR and E[U] of the uncovered loss (``evaluate._subject_kpis``)."""
    unc = measure.aggregate(np.maximum(0.0, loss - payout))
    _, cvar = var_cvar(unc, measure.probability, beta)
    return {
        "cvar_uncovered": float(cvar),
        "expected_uncovered": float(unc @ measure.probability),
    }


def population(args: argparse.Namespace) -> Population:
    """Rebuild the coverage designs from the C1 store on all years."""
    g = grid()["coverage"]
    base = base_dict(args.store)
    c1_store = ResultStore(args.c1_store)
    thesis = load_config(c1.BASE_CONFIG).eventset.checksum
    assert thesis is not None
    payouts: dict[str, np.ndarray] = {}
    hashes: dict[str, str] = {}
    loss: np.ndarray | None = None
    prepared: EventSet | None = None
    for d in g["designs"]:
        label = f"{d['pricing']}:{d['design']}"
        if d["design"] == "none":
            continue
        v = Variant(
            "main",
            "thesis",
            d["pricing"],
            tuple(sorted(c1.PRICINGS[d["pricing"]].items())),
            float(g["kappa"]),
            (),
            (),
        )
        design = d["design"]
        obj = dict(objectives((float(design.split("@")[1]),) if "@" in design else ()))
        cfg = single_config(base, v, g["scope"], obj[design], {"thesis": thesis})
        rid = run_key(config_hash(cfg), thesis, policy=DEFAULT_POLICY)
        if not c1_store.has_run(rid):
            raise RuntimeError(f"{label}: run {rid} is not in the C1 store")
        results = c1.rebuild(
            cfg,
            c1_store.read("runs", run_ids=[rid]),
            c1_store.read("payouts", run_ids=[rid]),
            c1_store.read("entities", run_ids=[rid]),
        )
        prepared = c1._prepared(cfg)
        c = cfg.to_components()
        ev = evaluate_results(prepared, c.scopes[0], results, basis=Basis.ANNUAL)
        port = ev.subjects[-1]
        if port.level != "portfolio":
            raise RuntimeError(f"{label}: last subject is {port.level}")
        if loss is None:
            loss = port.loss
        elif not np.array_equal(loss, port.loss):
            raise RuntimeError(f"{label}: portfolio loss differs between designs")
        payouts[label] = port.payout
        hashes[label] = config_hash(cfg)
    assert loss is not None
    assert prepared is not None
    for d in g["designs"]:
        if d["design"] == "none":
            payouts[f"{d['pricing']}:none"] = np.zeros_like(loss)
            hashes[f"{d['pricing']}:none"] = "-"
    n_years = prepared.metadata.n_years
    p = outcome_measure(prepared, Basis.ANNUAL).probability
    n_draws = round(1.0 / (p[0] * n_years))
    return Population(
        loss=loss,
        payouts=payouts,
        row_year=prepared.events["year"].to_numpy(dtype=np.int64),
        row_draw=prepared.events["draw_id"].to_numpy(dtype=np.int64),
        n_years=n_years,
        n_draws=n_draws,
        hashes=hashes,
    )


def check_measure(pop: Population, args: argparse.Namespace) -> None:
    """Our dataset measure on the holdout test years equals the library's."""
    g = grid()["coverage"]
    years = np.arange(int(0.7 * pop.n_years), pop.n_years)
    rows = np.flatnonzero(np.isin(pop.row_year, years))
    slot = (pop.row_year[rows] - years[0]) * pop.n_draws + pop.row_draw[rows]
    measure, _ = annual_measure(slot, years.size * pop.n_draws)
    stored = pd.read_csv(C1_DATA / "kpis_main.csv")
    for d in g["designs"]:
        if d["design"] == "none":
            continue
        label = f"{d['pricing']}:{d['design']}"
        for beta in g["eval_betas"]:
            ours = point_kpis(
                pop.loss[rows], pop.payouts[label][rows], measure, float(beta)
            )
            ref = stored.loc[
                (stored["pricing"] == d["pricing"])
                & (stored["kappa"] == g["kappa"])
                & (stored["scope"] == g["scope"])
                & (stored["design"] == d["design"])
                & (stored["eval_split"] == "test")
                & (stored["source"] == "c1_bootstrap")
                & (stored["kpi"] == "cvar_uncovered")
                & (stored["eval_beta"] == beta),
                "value",
            ]
            if len(ref) != 1 or not np.isclose(
                ours["cvar_uncovered"], float(ref.iloc[0]), rtol=1e-6
            ):
                raise RuntimeError(
                    f"{label} beta {beta}: test CVaR {ours['cvar_uncovered']} "
                    f"differs from C1's {ref.tolist()}"
                )
    print("coverage: dataset measure reproduces C1's test CVaR", flush=True)


def coverage(args: argparse.Namespace) -> None:
    """Run the coverage simulation and write its tables."""
    t0 = time.perf_counter()
    g = grid()["coverage"]
    pop = population(args)
    check_measure(pop, args)
    labels = list(pop.payouts)
    betas = [float(b) for b in g["eval_betas"]]
    kpi_names = list(g["kpis"])
    level = float(g["level"])
    # the truth: every year once
    full_slot = pop.row_year * pop.n_draws + pop.row_draw
    full_measure, _ = annual_measure(full_slot, pop.n_years * pop.n_draws)
    truth = {
        (lab, b): point_kpis(pop.loss, pop.payouts[lab], full_measure, b)
        for lab in labels
        for b in betas
    }
    rows_by_year = [np.flatnonzero(pop.row_year == y) for y in range(pop.n_years)]
    rng = np.random.default_rng(int(g["seed"]))
    records: list[dict[str, Any]] = []
    pairs = [(f"{p}:{a}", f"{p}:{b}") for p, a, b in (tuple(x) for x in g["paired"])]
    for n in g["n_years"]:
        n = int(n)
        for rep in range(int(g["n_replications"])):
            drawn = rng.integers(0, pop.n_years, size=n)
            parts = [rows_by_year[y] for y in drawn]
            rows = np.concatenate(parts)
            new_year = np.repeat(np.arange(n), [p.size for p in parts])
            slot = new_year * pop.n_draws + pop.row_draw[rows]
            measure, _ = annual_measure(slot, n * pop.n_draws)
            resample = resample_years(np.arange(n), int(g["n_bootstrap"]), rng)
            for b in betas:
                reps: dict[str, dict[str, np.ndarray]] = {}
                points: dict[str, dict[str, float]] = {}
                for lab in labels:
                    pay = pop.payouts[lab][rows]
                    r = kpi_replicates(
                        pop.loss[rows], pay, measure, new_year, resample, beta=b
                    )
                    reps[lab] = {k: np.asarray(r[k]) for k in r}  # type: ignore[index]
                    points[lab] = point_kpis(pop.loss[rows], pay, measure, b)
                subjects = [(lab, None) for lab in labels] + list(pairs)
                for a, other in subjects:
                    for k in kpi_names:
                        if k == "expected_uncovered" and b != betas[0]:
                            continue
                        if other is None:
                            rr = reps[a][k]
                            est = points[a][k]
                            true = truth[(a, b)][k]
                        else:
                            rr = reps[a][k] - reps[other][k]
                            est = points[a][k] - points[other][k]
                            true = truth[(a, b)][k] - truth[(other, b)][k]
                        lo, hi = percentile_interval(rr, level)
                        records.append(
                            {
                                "n_years": n,
                                "replication": rep,
                                "subject": a if other is None else f"{a} - {other}",
                                "kpi": k,
                                "eval_beta": b,
                                "true": true,
                                "estimate": est,
                                "ci_low": lo,
                                "ci_high": hi,
                                "covered": bool(lo <= true <= hi),
                                "miss_low": bool(true < lo),
                                "miss_high": bool(true > hi),
                            }
                        )
            if (rep + 1) % 25 == 0:
                print(
                    f"[coverage n={n}] {rep + 1}/{g['n_replications']} "
                    f"{time.perf_counter() - t0:.0f}s",
                    flush=True,
                )
    rec = pd.DataFrame(records)
    args.full.mkdir(parents=True, exist_ok=True)
    rec.to_csv(args.full / "coverage_replications.csv", index=False)
    summ = (
        rec.groupby(["n_years", "subject", "kpi", "eval_beta"], sort=False)
        .agg(
            n_replications=("covered", "size"),
            coverage=("covered", "mean"),
            miss_low=("miss_low", "mean"),
            miss_high=("miss_high", "mean"),
            true=("true", "first"),
            mean_estimate=("estimate", "mean"),
            mean_ci_low=("ci_low", "mean"),
            mean_ci_high=("ci_high", "mean"),
        )
        .reset_index()
    )
    summ["coverage_se"] = np.sqrt(
        summ["coverage"] * (1 - summ["coverage"]) / summ["n_replications"]
    )
    summ["relative_bias"] = (summ["mean_estimate"] - summ["true"]) / summ["true"]
    summ["mean_width_relative"] = (summ["mean_ci_high"] - summ["mean_ci_low"]) / summ[
        "true"
    ].abs()
    hashes = {lab: pop.hashes[lab] for lab in labels}

    def hash_of(subject: str) -> str:
        return " / ".join(
            hashes[s.strip()][7:19] if hashes[s.strip()] != "-" else "-"
            for s in subject.split(" - ")
        )

    summ["config_hash"] = summ["subject"].map(hash_of)
    args.out.mkdir(parents=True, exist_ok=True)
    summ.to_csv(args.out / "coverage.csv", index=False, float_format="%.6g")
    info = {
        "issue": "MAR-205",
        "family": "coverage",
        "grid": str(GRID.relative_to(REPO_ROOT)),
        "settings": g,
        "population": {
            "n_years": pop.n_years,
            "n_draws": pop.n_draws,
            "n_rows": int(pop.loss.size),
        },
        "config_hashes": hashes,
        "seconds": round(time.perf_counter() - t0, 1),
    }
    (args.out / "coverage_summary.json").write_text(json.dumps(info, indent=2) + "\n")
    print(f"coverage: done in {time.perf_counter() - t0:.0f}s", flush=True)


def _pct(x: float) -> str:
    return f"{100 * x:+.1f} %"


def family_tables(family: str, out: Path) -> None:
    """Write ``tables_<family>.md`` from the committed tables of a run family.

    Two tables: per run, the budget use, the payout ratio and the train and
    test CVaR(U) at every KPI beta; per pair of designs, the relative paired
    difference in test CVaR(U) at every KPI beta with its 90 % interval
    (``*``: the interval excludes zero).
    """
    runs = pd.read_csv(out / f"{family}_runs.csv")
    kp = pd.read_csv(out / f"{family}_kpis.csv")
    pa = pd.read_csv(out / f"{family}_paired.csv")
    betas = sorted(set(kp.loc[kp["kpi"] == "cvar_uncovered", "eval_beta"]))
    cv = kp.loc[kp["kpi"] == "cvar_uncovered"]
    lines = [
        f"# {family}: generated by research/scripts/c1_followups.py --tables",
        "",
        "Money in thousands (USD). Train values are in-sample point values; test",
        "values carry 90 % year-block bootstrap intervals (B = 1000).",
        "",
        "## Runs",
        "",
        "| EventSet | Pricing | Scope | Design | Budget use | E[π]/E[L] train | "
        + " | ".join(f"Train CVaR {b:g}" for b in betas)
        + " | "
        + " | ".join(f"Test CVaR {b:g} [CI]" for b in betas)
        + " | Hash | Status |",
        "|" + "---|" * (8 + 2 * len(betas)),
    ]
    for r in runs.itertuples():
        sel = (
            (cv["eventset"] == r.eventset)
            & (cv["pricing"] == r.pricing)
            & (cv["scope"] == r.scope)
            & (cv["design"] == r.design)
        )
        cells = []
        for split in ("train", "test"):
            for b in betas:
                row = cv.loc[sel & (cv["eval_split"] == split) & (cv["eval_beta"] == b)]
                if len(row) != 1:
                    raise RuntimeError(f"{r} {split} {b}: {len(row)} CVaR rows")
                v = row.iloc[0]
                if split == "train":
                    cells.append(f"{v['value'] / 1e3:,.1f}")
                else:
                    cells.append(
                        f"{v['value'] / 1e3:,.1f} [{v['ci_low'] / 1e3:,.1f}, "
                        f"{v['ci_high'] / 1e3:,.1f}]"
                    )
        ratio = r.train_expected_payout / r.train_expected_loss
        lines.append(
            f"| {r.eventset} | {r.pricing} | {r.scope} | {r.design} | "
            f"{r.budget_use:.3f} | {ratio:.3f} | "
            + " | ".join(cells)
            + f" | `{str(r.config_hash)[7:19]}` | {r.statuses} |"
        )
    lines += [
        "",
        "## Paired differences in test CVaR(U), a - b, relative to b",
        "",
        "| EventSet | Pricing | Scope | a - b | "
        + " | ".join(f"KPI β {b:g}" for b in betas)
        + " | Hash a / b |",
        "|" + "---|" * (5 + len(betas)),
    ]
    pc = pa.loc[pa["kpi"] == "cvar_uncovered"]
    for (es, pr, sc, a, b_), grp in pc.groupby(
        ["eventset", "pricing", "scope", "design_a", "design_b"], sort=False
    ):
        cells = []
        for b in betas:
            row = grp.loc[grp["eval_beta"] == b].iloc[0]
            lo = row["ci_low"] / row["value_b"]
            hi = row["ci_high"] / row["value_b"]
            star = "*" if (row["ci_low"] > 0 or row["ci_high"] < 0) else ""
            cells.append(
                f"{_pct(row['relative'])}{star} [{_pct(lo)}, {_pct(hi)}]"
                if row["value_b"] != 0
                else f"{row['difference']:,.0f} (b = 0)"
            )
        h = grp.iloc[0]
        lines.append(
            f"| {es} | {pr} | {sc} | {a} - {b_} | "
            + " | ".join(cells)
            + f" | `{h['config_hash_a']}` / `{h['config_hash_b']}` |"
        )
    (out / f"tables_{family}.md").write_text("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    """Run one follow-up family."""
    parser = argparse.ArgumentParser(description="C1 follow-ups (MAR-205).")
    parser.add_argument(
        "--family",
        required=True,
        choices=["budget", "coc_q", "beta_draws", "coverage"],
    )
    parser.add_argument("--jobs", type=int, default=2, help="worker processes")
    parser.add_argument("--store", type=Path, default=STORE)
    parser.add_argument("--c1-store", type=Path, default=C1_STORE)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--full", type=Path, default=FULL_DIR)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--slim-only", action="store_true")
    parser.add_argument(
        "--tables", action="store_true", help="only write tables_<family>.md"
    )
    args = parser.parse_args(argv)
    if args.family == "budget":
        budget_table(args.out)
    elif args.family == "coverage":
        coverage(args)
    elif args.tables:
        family_tables(args.family, args.out)
    elif args.slim_only:
        write_slim(args.family, args.full, args.out)
        family_tables(args.family, args.out)
    else:
        run_family(args.family, args)
        family_tables(args.family, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
