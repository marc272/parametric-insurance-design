r"""Rerun the thesis configuration out of sample (MAR-22, SPEC §6.1).

The thesis calibrated and evaluated on the same events (thesis issue M1).
This script reruns ``parity/configs/thesis.yaml`` (3 scopes x 3 objectives,
event-conditional basis, pure pricing, budget loading 1) with three samples,
into one result store:

* ``full``: calibrate and evaluate on every year (the thesis, in sample);
* ``holdout``: calibrate on years 0 .. 6,999, evaluate on those (``train``)
  and on years 7,000 .. 9,999 (``test``), with the thesis ``n_bins`` sweep
  (5, 10, 15, 20, 25) for the overfitting diagnostic;
* ``kfold``: 5 contiguous year blocks of 2,000 years, a run per fold.

Only the ``n_bins`` sweep runs; the other thesis sweeps are not part of this
rerun. The solver policy is ``solve.DEFAULT_POLICY`` (accurate MSE, not the
parity policy). Every run keeps its config hash and ``run_id``.

It writes small CSV summaries of the **portfolio-level** KPIs (``level =
"portfolio"``: the sum over every location and every payout of a run) to
``research/data/out-of-sample-rerun/``:

* ``full.csv``: the in-sample KPIs of the ``full`` runs (every ``n_bins``);
* ``holdout_gap.csv``: ``splits.kpi_gap`` of the holdout runs (train, test,
  gap = test - train) per scope, objective and ``n_bins``;
* ``kfold_gap.csv``: the same per fold of the 5-fold runs (``n_bins`` 15);
* ``summary.json``: inputs, package version, timings, run counts.

Run from the repository root::

    uv run python research/scripts/out_of_sample_rerun.py --jobs 8

The store defaults to ``results/out-of-sample`` (not committed). Re-running
reuses it (content-hashed cache).
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Final

import pandas as pd

from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import load_input
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.experiment.sweeps import run_sweeps
from parametric_insurance_design.records import ALL_PROBLEMS
from parametric_insurance_design.splits import kpi_gap

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
THESIS_CONFIG: Final[Path] = REPO_ROOT / "parity" / "configs" / "thesis.yaml"
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "out-of-sample-rerun"
STORE: Final[Path] = REPO_ROOT / "results" / "out-of-sample"

SAMPLES: Final[dict[str, dict[str, Any]]] = {
    "full": {"kind": "full"},
    "holdout": {"kind": "holdout", "train_fraction": 0.7},
    "kfold": {"kind": "kfold", "k": 5},
}
"""The three samples of the rerun."""

N_BINS_SWEEP: Final[str] = "n_bins"


def variant(base: ExperimentConfig, sample: str, store: Path) -> ExperimentConfig:
    """Return the thesis config with another sample and only the n_bins sweep."""
    data = base.model_dump(mode="json")
    data["name"] = f"thesis-{sample}"
    data["sample"] = SAMPLES[sample]
    data["sweeps"] = [s for s in data["sweeps"] if s["parameter"] == N_BINS_SWEEP]
    data["output"] = {"directory": str(store)}
    return parse_config(data)


def run_table(store: ResultStore, run_ids: set[str]) -> pd.DataFrame:
    """One row per run: scope, objective, n_bins, sample, fold, config hash."""
    runs = store.read("runs")
    runs = runs.loc[runs["run_id"].isin(sorted(run_ids))]
    failed = runs.loc[runs["error_type"].notna()]
    if len(failed):
        raise RuntimeError(f"{len(failed)} design problems failed: {failed}")
    first = runs.drop_duplicates(subset=["run_id"])
    params = first["parameters"].map(json.loads)
    return pd.DataFrame(
        {
            "run_id": first["run_id"].to_numpy(),
            "config_hash": first["config_hash"].to_numpy(),
            "scope": first["scope"].to_numpy(),
            "objective": first["objective"].to_numpy(),
            "n_bins": [p["n_bins"] for p in params],
            "sample": [p["sample"] for p in params],
            "fold": first["fold"].to_numpy(),
        }
    )


def portfolio(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep the portfolio-level rows (the whole run)."""
    keep = (frame["level"] == "portfolio") & (frame["problem_id"] == ALL_PROBLEMS)
    return frame.loc[keep].drop(columns=["level", "problem_id", "subject_id"])


def main(argv: list[str] | None = None) -> int:
    """Run the three samples and write the summaries."""
    parser = argparse.ArgumentParser(
        description="Rerun the thesis config out of sample (MAR-22)."
    )
    parser.add_argument("--jobs", type=int, default=1, help="worker processes")
    parser.add_argument("--store", type=Path, default=STORE, help="result store")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="summary directory")
    args = parser.parse_args(argv)

    base = load_config(THESIS_CONFIG)
    data = load_input(base)
    store = ResultStore(args.store)
    timings: dict[str, float] = {}
    run_ids: dict[str, set[str]] = {}
    for sample in SAMPLES:
        config = variant(base, sample, args.store)
        start = time.perf_counter()
        # k-fold: the baseline only (45 runs); the others with the n_bins sweep.
        outcome = run_sweeps(
            config,
            store=store,
            data=data,
            parameters=[] if sample == "kfold" else [N_BINS_SWEEP],
            jobs=args.jobs,
        )
        timings[sample] = time.perf_counter() - start
        ids = {o.run_id for o in outcome.baseline}
        for sweep in outcome.sweeps:
            ids |= {p.outcome.run_id for p in sweep.points}
        run_ids[sample] = ids
        print(f"{sample}: {len(ids)} runs in {timings[sample]:.0f} s", flush=True)

    kpis = store.read("kpis")
    args.out.mkdir(parents=True, exist_ok=True)
    tables: dict[str, pd.DataFrame] = {}
    for sample, ids in run_ids.items():
        meta = run_table(store, ids)
        rows = kpis.loc[kpis["run_id"].isin(sorted(ids))]
        if sample == "full":
            table = portfolio(rows)[["run_id", "basis", "kpi", "beta", "value"]]
        else:
            table = portfolio(kpi_gap(rows))
            table = table[["run_id", "basis", "kpi", "beta", "train", "test", "gap"]]
        table = meta.merge(table, on="run_id", how="inner", validate="one_to_many")
        if set(table["run_id"]) != set(meta["run_id"]):
            raise RuntimeError(f"{sample}: some runs have no portfolio KPIs")
        table = table.sort_values(
            ["scope", "objective", "n_bins", "fold", "kpi"], kind="stable"
        ).reset_index(drop=True)
        tables[sample] = table
    tables["full"].to_csv(args.out / "full.csv", index=False)
    tables["holdout"].to_csv(args.out / "holdout_gap.csv", index=False)
    tables["kfold"].to_csv(args.out / "kfold_gap.csv", index=False)

    any_run = next(iter(run_ids["full"]))
    manifest = store.manifest(any_run)
    summary = {
        "issue": "MAR-22",
        "config": "parity/configs/thesis.yaml",
        "eventset_checksum": data.checksum,
        "package_version": manifest["cache_key"]["package_version"],
        "solver_policy": manifest["cache_key"]["solver_policy"],
        "prepared_eventset": {
            k: manifest["prepared_eventset"][k] for k in ("n_rows", "n_years")
        },
        "samples": SAMPLES,
        "runs": {s: len(ids) for s, ids in run_ids.items()},
        "seconds": {s: round(t, 1) for s, t in timings.items()},
        "jobs": args.jobs,
    }
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
