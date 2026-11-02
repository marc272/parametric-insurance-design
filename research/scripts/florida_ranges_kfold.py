r"""MAR-203: second optima and free bins of the Florida k-fold designs (pooled).

MAR-202's pooled 5-fold contrasts (index (a) and (b), pure pricing, kappa 1)
use one optimum per fold design. This script does for every k-fold fold run
what ``florida_ranges.py`` does for the holdout runs, without near-optimal
programs:

* joint (cluster, portfolio) fold designs: the second optimum
  (``c1_rq2.ALT_POLICY``) of the fold's design problem on its training years,
  and its free-bin ends; the stored design's numpy objective must equal the
  stored run's;
* individual fold designs: the free-bin ends (MAR-198's method (a));

then pools each candidate over the folds as ``experiment.kfold`` does (every
year evaluated by the fold design that did not see it) and recomputes every
MAR-202 pooled contrast on the pooled resample (B 1000, seed 0) at the
variants of ``florida_ranges.variants``. The stored variant must reproduce
MAR-202's ``kfold_contrasts.csv`` (with the two T14 folds replaced by their
CLARABEL re-solves, ``florida_rerun.py`` phase ``t14``).

Run from the repository root (after ``florida_rerun.py --phases t14
kfold``)::

    uv run python research/scripts/florida_ranges_kfold.py --jobs 3

Writes ``kfold/`` (one pickle per fold run) and ``kfold_contrasts.csv`` to
``results/florida-ranges/``; ``florida_ranges_tables.py`` reads them.
Observations only.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import time
from pathlib import Path
from typing import Any, Final

import c1_checkpoint as c1
import c1_combination as comb
import c1_rq2 as rq2
import c1_rq2_sensitivities as sens
import florida_ranges as frg
import florida_rerun as fr
import individual_nonuniqueness as inu
import numpy as np
import pandas as pd

from parametric_insurance_design import splits
from parametric_insurance_design.basis import Basis, outcome_measure
from parametric_insurance_design.bootstrap import (
    kpi_replicates,
    percentile_interval,
    resample_years,
)
from parametric_insurance_design.experiment.config import ExperimentConfig, config_hash
from parametric_insurance_design.experiment.runner import package_versions
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.solve import solve

KFOLD_DIR: Final[str] = "kfold"


def fold_runs(
    plan: dict[str, Any], full202: Path
) -> dict[tuple[str, str, str, str], list[tuple[ExperimentConfig, str]]]:
    """Every k-fold single run: (index, pricing, scope, design) -> per fold.

    The two T14 folds are their re-solved runs (``t14_replacements.csv``).
    """
    replace = fr._t14_replacements(full202)
    out: dict[tuple[str, str, str, str], list[tuple[ExperimentConfig, str]]] = {}
    for (index, pricing, _, _), cfg in fr.kfold_configs(plan).items():
        for s in cfg.single_runs():
            rid = fr.rid_of(s)
            rid = replace.get(rid, rid)
            design = fr.design_of(s.objectives[0].model_dump(mode="json"))
            key = (index, pricing, s.scopes[0].kind, design)
            out.setdefault(key, []).append((s, rid))
    for runs in out.values():
        runs.sort(key=lambda x: int(getattr(x[0].sample, "fold", -1)))
    return out


def _fold(cfg: ExperimentConfig) -> int:
    return int(getattr(cfg.sample, "fold", -1))


def fold_worker(cfg: ExperimentConfig, rid: str, store_root: str) -> dict[str, Any]:
    """Second optimum (joint) and free-bin ends of one fold design."""
    t0 = time.perf_counter()
    store = ResultStore(Path(store_root))
    stored = rq2._stored(cfg, rid, store)
    comps = cfg.to_components()
    prepared = c1._prepared(cfg)
    k = int(cfg.sample.model_dump()["k"])
    train, _ = splits.year_block_kfold(prepared, k=k)[_fold(cfg)]
    scope = stored.scope.name
    meta: dict[str, Any] = {
        "config_hash": config_hash(cfg),
        "run_id": rid,
        "fold": _fold(cfg),
        "statuses": stored.statuses,
        "solvers": stored.solvers,
    }
    if scope == "individual":
        data = train.select(prepared)
        thetas: dict[str, list[np.ndarray]] = {
            "stored": [],
            "free_lo": [],
            "free_hi": [],
        }
        n_free = 0
        for r in stored.results:
            problem = stored.scope.materialise(data, r.spec)
            b = comps.payout.basis_matrix(problem.index[:, 0])
            th = np.asarray(r.theta, dtype=np.float64)[0]
            cap = float(np.max(problem.entity_loss[:, 0], initial=0.0))
            free = inu.free_bins(b.sum(axis=0))
            n_free += len(free)
            lo, hi = inu.free_bin_bounds(th, free, cap)
            for t in (lo, hi):
                if not np.allclose(b @ t, b @ th, rtol=0, atol=1e-9 * max(cap, 1)):
                    raise RuntimeError(f"{rid}: a free bin has train rows")
            thetas["stored"].append(th)
            thetas["free_lo"].append(lo)
            thetas["free_hi"].append(hi)
        meta["free_bins"] = n_free
        meta["seconds"] = round(time.perf_counter() - t0, 1)
        return {"thetas": thetas, "checks": {}, "meta": meta}
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
    th_stored = np.asarray(res.theta, dtype=np.float64)
    alt = solve(built, rq2.ALT_POLICY, pricing=comps.pricing)
    if alt.theta is None:
        raise RuntimeError(f"{rid}: the alt solve failed ({alt.status})")
    th_alt = np.asarray(alt.theta, dtype=np.float64)
    js = frg.StoredSet(
        built,
        cfg,
        frg.RANGE_REL_TOL,
        {"stored": th_stored / scale, "alt": th_alt / scale},
    )
    design = fr.design_of(cfg.objectives[0].model_dump(mode="json"))
    units = frg._objective_units(design, scale)
    mine = js.optimum_values["stored"] * units
    if not math.isclose(mine, stored.objective_value, rel_tol=frg.OBJ_RTOL):
        raise RuntimeError(
            f"{rid}: numpy objective {mine!r} != stored {stored.objective_value!r}"
        )
    lo, hi, ents = sens.free_bin_family(js, th_stored)
    cand = {"stored": th_stored, "alt": th_alt, "free_lo": lo, "free_hi": hi}
    meta.update(
        alt_solver=alt.solver,
        alt_status=str(alt.status.value),
        objective_stored=mine,
        objective_alt=js.optimum_values["alt"] * units,
        free_bins=sum(len(str(e["free_bins"]).split()) for e in ents),
        rel_tol=frg.RANGE_REL_TOL,
        seconds=round(time.perf_counter() - t0, 1),
    )
    return {
        "thetas": {n: [t] for n, t in cand.items()},
        "checks": {n: js.check(t / scale) for n, t in cand.items()},
        "meta": meta,
    }


def run_folds(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Every k-fold fold design's candidates."""
    tasks = []
    for (index, pricing, scope, design), runs in fold_runs(plan, args.full202).items():
        for cfg, rid in runs:
            name = f"{index}_{pricing}_{scope}_{design}_f{_fold(cfg)}"
            tasks.append((name, fold_worker, (cfg, rid, str(args.store))))
    tasks.sort(key=lambda t: (0 if "portfolio" in t[0] else 1, t[0]))
    failed = frg._run_pool(tasks, args.full / KFOLD_DIR, args.jobs)
    if failed:
        raise RuntimeError("failed:\n" + "\n".join(failed))
    return {"kfold_fold_designs": len(tasks)}


def pooled_group(
    index: str,
    pricing: str,
    runs: dict[tuple[str, str], list[tuple[ExperimentConfig, str]]],
    full: str,
    store_root: str,
) -> dict[str, Any]:
    """Pool every design's candidates over the folds; contrast them."""
    t0 = time.perf_counter()
    store = ResultStore(Path(store_root))
    cfg0 = runs[("individual", "mse")][0][0]
    prepared = c1._prepared(cfg0)
    k = int(cfg0.sample.model_dump()["k"])
    samples = splits.year_block_kfold(prepared, k=k)
    full_sample = Sample.full(prepared)
    measure = outcome_measure(prepared, Basis.ANNUAL, years=full_sample.years)
    row_years = prepared.events["year"].to_numpy(dtype=np.int64)
    loss = np.asarray(prepared.loss, dtype=np.float64).sum(axis=1)
    assert cfg0.bootstrap is not None
    resample = resample_years(
        full_sample.years, cfg0.bootstrap.n_bootstrap, cfg0.bootstrap.rng()
    )
    level = float(cfg0.bootstrap.level)
    tests = [test.select(prepared) for _, test in samples]
    res: dict[tuple[str, str], dict[str, Any]] = {}
    for d, fold_list in runs.items():
        parts = []
        for cfg, _ in fold_list:
            name = f"{index}_{pricing}_{d[0]}_{d[1]}_f{_fold(cfg)}"
            parts.append(
                pickle.loads((Path(full) / KFOLD_DIR / f"{name}.pkl").read_bytes())
            )
        cands = set.intersection(*(set(p["thetas"]) for p in parts))
        res[d] = {
            "design": d,
            "thetas": {c: [p["thetas"][c] for p in parts] for c in cands},
            "meta": {
                "near": False,
                "hashes": [p["meta"]["config_hash"] for p in parts],
            },
            "parts": parts,
        }
    cache: dict[
        tuple[tuple[str, str], str], tuple[dict[str, float], dict[str, np.ndarray]]
    ] = {}
    bases: dict[tuple[tuple[str, str], int], list[list[np.ndarray]]] = {}

    def get(
        d: tuple[str, str], cand: str
    ) -> tuple[dict[str, float], dict[str, np.ndarray]]:
        if (d, cand) in cache:
            return cache[(d, cand)]
        payout = np.full(prepared.n_rows, np.nan)
        for f, (cfg, rid) in enumerate(runs[d]):
            if (d, f) not in bases:
                specs = [r.spec for r in rq2._stored(cfg, rid, store).results]
                bases[(d, f)] = frg.entity_bases(cfg, specs, tests[f])
            th = res[d]["thetas"][cand][f]
            payout[samples[f][1].rows] = frg.row_payout(bases[(d, f)], th)
        if np.isnan(payout).any():
            raise RuntimeError(f"{d} {cand}: rows without a fold payout")
        out: dict[str, np.ndarray] = {}
        pt: dict[str, float] = {}
        ones = rq2._identity(resample)
        for b in frg.EVAL_BETAS:
            rep = kpi_replicates(loss, payout, measure, row_years, resample, beta=b)
            one = kpi_replicates(loss, payout, measure, row_years, ones, beta=b)
            out[f"cvar@{b:g}"] = np.asarray(rep["cvar_uncovered"])
            out["eu"] = np.asarray(rep["expected_uncovered"])
            pt[f"cvar@{b:g}"] = float(np.asarray(one["cvar_uncovered"])[0])
            pt["eu"] = float(np.asarray(one["expected_uncovered"])[0])
        cache[(d, cand)] = (pt, out)
        return pt, out

    rows: list[dict[str, Any]] = []
    for c in comb.contrasts("main"):
        terms = dict(zip("abcd", c.terms, strict=False))
        if not all(t in res for t in terms.values()):
            continue
        for lab in frg.LABELS:
            kpi = "expected_uncovered" if lab == "eu" else "cvar_uncovered"
            beta = math.nan if lab == "eu" else float(lab.split("@")[1])
            ref = get(c.reference, "stored")[0][lab]
            for vname, choice in frg.variants(c, res, lab).items():
                value = 0.0
                rep = np.zeros(resample.n_bootstrap)
                for t, d in terms.items():
                    pv, rv = get(d, choice[t])
                    value += frg.SIGN[t] * pv[lab]
                    rep = rep + frg.SIGN[t] * rv[lab]
                lo, hi = percentile_interval(rep, level)
                rows.append(
                    frg._ids((index, pricing, 1.0), c, kpi, beta)
                    | {
                        "variant": vname,
                        "candidates": " ".join(f"{t}={choice[t]}" for t in terms),
                        "value": value,
                        "ci_low": lo,
                        "ci_high": hi,
                        "value_ref": ref,
                        "verdict": frg._verdict(value, lo, hi),
                        "missing": "",
                    }
                )
    print(f"[pooled] {index} {pricing} {time.perf_counter() - t0:.0f}s", flush=True)
    return {
        "contrasts": pd.DataFrame(rows),
        "meta": {"seconds": time.perf_counter() - t0},
    }


def check_pooled(con: pd.DataFrame, mar202: pd.DataFrame) -> int:
    """Raise unless the stored variant reproduces MAR-202's pooled contrasts."""
    mine = con.loc[con["variant"] == "stored"].copy()
    theirs = mar202.loc[mar202["split"] == "pooled"].copy()
    keys = [
        "eventset",
        "pricing",
        "contrast",
        "joint_scope",
        "tail_design",
        "base_design",
        "kpi",
        "eval_beta",
    ]
    for f in (mine, theirs):
        for kk in ("joint_scope", "tail_design", "base_design"):
            f[kk] = f[kk].fillna("").astype(str)
        f["eval_beta"] = f["eval_beta"].fillna(-1.0)
    theirs = theirs.loc[theirs["kpi"].isin(["expected_uncovered", "cvar_uncovered"])]
    theirs = theirs.drop_duplicates(keys)
    m = mine.merge(theirs, on=keys, suffixes=("", "_202"), validate="one_to_one")
    if len(m) != len(mine):
        raise RuntimeError(f"{len(mine) - len(m)} pooled rows have no MAR-202 row")
    for col in ("value", "ci_low", "ci_high"):
        ok = np.isclose(m[col], m[f"{col}_202"], rtol=1e-6, atol=1.0)
        if not ok.all():
            raise RuntimeError(f"{col} differs: {m.loc[~ok].iloc[0].to_dict()}")
    return len(m)


def run_pooled(args: argparse.Namespace, plan: dict[str, Any]) -> dict[str, Any]:
    """Pooled contrasts at every variant, per (index, pricing)."""
    runs = fold_runs(plan, args.full202)
    groups: dict[tuple[str, str], dict[tuple[str, str], list[Any]]] = {}
    for (index, pricing, scope, design), r in runs.items():
        groups.setdefault((index, pricing), {})[(scope, design)] = r
    tasks = [
        (f"pooled_{i}_{p}", pooled_group, (i, p, g, str(args.full), str(args.store)))
        for (i, p), g in groups.items()
    ]
    cache = args.full / "kfold_groups"
    for t in tasks:
        (cache / f"{t[0]}.pkl").unlink(missing_ok=True)
    failed = frg._run_pool(tasks, cache, min(args.jobs, len(tasks)))
    if failed:
        raise RuntimeError("failed:\n" + "\n".join(failed))
    con = pd.concat(
        [
            pickle.loads((cache / f"{t[0]}.pkl").read_bytes())["contrasts"]
            for t in tasks
        ],
        ignore_index=True,
    )
    n = check_pooled(con, pd.read_csv(args.full202 / "kfold_contrasts.csv"))
    con.to_csv(args.full / "kfold_contrasts.csv", index=False, float_format="%.10g")
    print(f"[pooled] {n} stored rows equal MAR-202's", flush=True)
    return {"pooled_groups": len(tasks), "pooled_rows_checked_against_mar202": n}


def main(argv: list[str] | None = None) -> int:
    """Run the fold and pooled phases."""
    parser = argparse.ArgumentParser(
        description="Florida k-fold second optima (MAR-203)."
    )
    parser.add_argument(
        "--phases", nargs="+", default=["folds", "pooled"], choices=["folds", "pooled"]
    )
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--store", type=Path, default=frg.STORE)
    parser.add_argument("--full", type=Path, default=frg.FULL_DIR)
    parser.add_argument("--full202", type=Path, default=fr.FULL_DIR)
    parser.add_argument("--plan", type=Path, default=fr.PLAN)
    args = parser.parse_args(argv)
    plan = fr.load_plan(args.plan)
    for name, fn in (("folds", run_folds), ("pooled", run_pooled)):
        if name not in args.phases:
            continue
        t = time.perf_counter()
        summary = {
            "issue": "MAR-203",
            "package_versions": package_versions(),
            **fn(args, plan),
            "phase_seconds": round(time.perf_counter() - t, 1),
        }
        (args.full / f"summary_kfold_{name}.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
        print(f"phase {name} done in {summary['phase_seconds']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
