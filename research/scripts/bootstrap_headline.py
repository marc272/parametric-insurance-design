r"""Headline comparison with 90 % block-bootstrap intervals (MAR-23, SPEC §6.1).

Extends the MAR-22 out-of-sample rerun (``out_of_sample_rerun.py``): the
thesis configuration ``parity/configs/thesis.yaml`` (event-conditional basis,
pure pricing, budget loading 1, 15 bins) on the holdout split (train years
0 .. 6,999, test years 7,000 .. 9,999), for the three scopes and the three
objectives, with a ``bootstrap`` section (seed 0, B = 1000, level 0.9).

For each of the 9 runs the script

1. runs it through the runner (``run_single``) into a result store, which
   stores the KPIs with their intervals (``ci_*`` columns) and gives the
   ``config_hash`` and ``run_id``;
2. recomputes the same run in-process (prepare, split, build, solve) and
   bootstraps its KPIs with ``bootstrap.bootstrap_kpis`` on the same
   resample (the runner's generator: ``BootstrapConfig.rng()`` per sample),
   checking that the intervals equal the stored ones; this gives the
   replicates for
3. the paired differences ``weighted CVaR - MSE`` and ``weighted CVaR -
   E[U]`` within each scope (``bootstrap.paired_difference``), which the
   result store does not hold.

It writes **portfolio-level** rows (``level = "portfolio"``) to
``research/data/bootstrap-headline/``:

* ``kpis.csv``: every KPI on ``train`` and ``test`` with ``ci_low``,
  ``ci_high``, per scope and objective, with ``config_hash`` and ``run_id``;
* ``paired.csv``: the paired differences on ``train`` and ``test``;
* ``summary.json``: inputs, package version, solver policy, bootstrap
  settings and timings.

Run from the repository root::

    uv run python research/scripts/bootstrap_headline.py

The store defaults to ``results/bootstrap-headline`` (not committed).
Re-running reuses it (content-hashed cache); the in-process recomputation
always runs.
"""

from __future__ import annotations

import argparse
import json
import time
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
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import (
    load_input,
    prepare_eventset,
    run_single,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.solve import DEFAULT_POLICY, solve

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
THESIS_CONFIG: Final[Path] = REPO_ROOT / "parity" / "configs" / "thesis.yaml"
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "bootstrap-headline"
STORE: Final[Path] = REPO_ROOT / "results" / "bootstrap-headline"

SAMPLE: Final[dict[str, Any]] = {"kind": "holdout", "train_fraction": 0.7}
BOOTSTRAP: Final[dict[str, Any]] = {"seed": 0, "n_bootstrap": 1000, "level": 0.9}
COMPARISONS: Final[tuple[tuple[str, str], ...]] = (
    ("weighted_cvar", "mse"),
    ("weighted_cvar", "expected_uncovered"),
)
"""Paired differences ``a - b`` reported within each scope."""

CI_COLUMNS: Final[list[str]] = ["ci_low", "ci_high", "ci_level", "n_bootstrap"]


def headline_config(base: ExperimentConfig, store: Path) -> ExperimentConfig:
    """Return the thesis config on the holdout split, with intervals, no sweeps."""
    data = base.model_dump(mode="json")
    data["name"] = "thesis-holdout-bootstrap"
    data["sample"] = SAMPLE
    data["bootstrap"] = BOOTSTRAP
    data["sweeps"] = []
    data["output"] = {"directory": str(store)}
    return parse_config(data)


def recompute(run: ExperimentConfig, data: Any) -> dict[str, KpiBootstrap]:  # noqa: ANN401
    """Re-run one config in-process; bootstrap each evaluation sample."""
    prepared = prepare_eventset(run, data.eventset)
    train, test = splits.holdout(prepared, train_fraction=SAMPLE["train_fraction"])
    c = run.to_components()
    scope, objective = c.scopes[0], c.objectives[0]
    built = build_problems(
        prepared,
        scope,
        c.payout,
        objective,
        c.pricing,
        c.constraints,
        basis=c.basis,
        sample=train,
    )
    results = [solve(p, DEFAULT_POLICY) for p in built]
    assert run.bootstrap is not None
    out: dict[str, KpiBootstrap] = {}
    for sample in (train, test):
        out[sample.name] = bootstrap_kpis(
            prepared,
            scope,
            results,
            basis=c.basis,
            beta=run.evaluation.beta,
            run_id="in-process",
            resample=resample_years(
                sample.years, run.bootstrap.n_bootstrap, run.bootstrap.rng()
            ),
            sample=sample,
            pricing=c.pricing,
            level=run.bootstrap.level,
        )
    return out


def check_same_intervals(stored: pd.DataFrame, mine: pd.DataFrame) -> None:
    """Raise unless the runner's stored intervals equal the in-process ones."""
    key = ["eval_split", "level", "subject_id", "kpi"]
    merged = stored.merge(mine, on=key, suffixes=("", "_mine"), validate="one_to_one")
    if len(merged) != len(stored) or len(merged) != len(mine):
        raise RuntimeError("stored and in-process KPI rows differ")
    for column in ["value", *CI_COLUMNS]:
        a = merged[column].to_numpy(dtype=np.float64, na_value=np.nan)
        b = merged[f"{column}_mine"].to_numpy(dtype=np.float64, na_value=np.nan)
        if not np.allclose(a, b, rtol=1e-9, atol=0, equal_nan=True):
            raise RuntimeError(f"stored and in-process {column} differ")


def main(argv: list[str] | None = None) -> int:
    """Run the 9 holdout runs with intervals and write the summaries."""
    parser = argparse.ArgumentParser(
        description="Headline comparison with 90 % block-bootstrap intervals (MAR-23)."
    )
    parser.add_argument("--store", type=Path, default=STORE, help="result store")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="summary directory")
    args = parser.parse_args(argv)

    base = load_config(THESIS_CONFIG)
    data = load_input(base)
    store = ResultStore(args.store)
    config = headline_config(base, args.store)

    kpi_rows: list[pd.DataFrame] = []
    boots: dict[tuple[str, str], dict[str, KpiBootstrap]] = {}
    timings: list[dict[str, Any]] = []
    for run in config.single_runs():
        scope, objective = run.scopes[0].kind, run.objectives[0].kind
        start = time.perf_counter()
        outcome = run_single(run, data, store)
        run_seconds = time.perf_counter() - start
        if not outcome.ok:
            raise RuntimeError(f"{scope} x {objective} failed: {outcome}")
        manifest = store.manifest(outcome.run_id)
        stored = store.read("kpis", run_ids=[outcome.run_id])
        start = time.perf_counter()
        mine = recompute(run, data)
        recompute_seconds = time.perf_counter() - start
        check_same_intervals(
            stored, pd.concat([b.table for b in mine.values()], ignore_index=True)
        )
        boots[(scope, objective)] = mine
        table = stored.loc[stored["level"] == "portfolio"].copy()
        table.insert(0, "objective", objective)
        table.insert(0, "scope", scope)
        table.insert(0, "config_hash", config_hash(run))
        kpi_rows.append(table)
        timings.append(
            {
                "scope": scope,
                "objective": objective,
                "cached": outcome.cached,
                "run_seconds": round(run_seconds, 2),
                "bootstrap_seconds": {
                    s["sample"]: round(s["seconds"], 2)
                    for s in manifest["bootstrap"]["samples"]
                },
                "recompute_seconds": round(recompute_seconds, 2),
                "n_without_bounds": {
                    s["sample"]: s["n_without_bounds"]
                    for s in manifest["bootstrap"]["samples"]
                },
            }
        )
        print(f"{scope} x {objective}: {outcome.run_id[:19]}", flush=True)

    kpis = pd.concat(kpi_rows, ignore_index=True)
    kpis = pd.DataFrame(
        kpis[
            [
                "scope",
                "objective",
                "eval_split",
                "kpi",
                "beta",
                "value",
                *CI_COLUMNS,
                "config_hash",
                "run_id",
            ]
        ]
    ).sort_values(["scope", "objective", "eval_split", "kpi"], kind="stable")

    paired_rows: list[pd.DataFrame] = []
    for scope in dict.fromkeys(s for s, _ in boots):
        for a, b in COMPARISONS:
            for split in ("train", "test"):
                diff = paired_difference(
                    boots[(scope, a)][split], boots[(scope, b)][split]
                )
                diff = diff.loc[diff["level"] == "portfolio"].copy()
                diff.insert(0, "objective_b", b)
                diff.insert(0, "objective_a", a)
                diff.insert(0, "scope", scope)
                paired_rows.append(diff)
    paired = pd.concat(paired_rows, ignore_index=True)
    paired = paired[
        [
            "scope",
            "objective_a",
            "objective_b",
            "eval_split",
            "kpi",
            "beta",
            "value_a",
            "value_b",
            "difference",
            *CI_COLUMNS,
        ]
    ]

    args.out.mkdir(parents=True, exist_ok=True)
    kpis.to_csv(args.out / "kpis.csv", index=False)
    paired.to_csv(args.out / "paired.csv", index=False)
    any_run = str(kpis["run_id"].iloc[0])
    manifest = store.manifest(any_run)
    summary = {
        "issue": "MAR-23",
        "config": "parity/configs/thesis.yaml",
        "sample": SAMPLE,
        "bootstrap": BOOTSTRAP,
        "eventset_checksum": data.checksum,
        "package_version": manifest["cache_key"]["package_version"],
        "solver_policy": manifest["cache_key"]["solver_policy"],
        "prepared_eventset": {
            k: manifest["prepared_eventset"][k] for k in ("n_rows", "n_years")
        },
        "comparisons": [f"{a} - {b}" for a, b in COMPARISONS],
        "timings": timings,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
