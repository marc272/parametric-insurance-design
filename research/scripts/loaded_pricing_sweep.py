"""Thesis baseline under pure and cost-of-capital pricing (MAR-27, SPEC §6.4).

Runs every scope x objective of ``parity/configs/thesis.yaml`` (its sweeps
are ignored) once per pricing: the pure premium and ``CostOfCapitalLoad`` at
``rate`` in {0, 0.06, 0.10} x ``q`` in {0.99, 0.995}. Only ``pricing``
changes; everything else (EventSet, noise, basis ``event_conditional``,
in-sample evaluation, budget ``kappa = 1``) is the thesis config.

Writes ``research/data/mar27-loaded-pricing/headline.csv`` (portfolio-level
KPIs, one row per run, with its config hash and run id) and
``problem_premiums.csv`` (premium and budget use per design problem). The
result store goes to ``--store`` (default ``results/mar27-loaded-pricing``,
git-ignored).

Usage::

    uv run python research/scripts/loaded_pricing_sweep.py [--store DIR]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
    to_dict,
)
from parametric_insurance_design.experiment.runner import load_input, run_config
from parametric_insurance_design.experiment.store import ResultStore

REPO = Path(__file__).resolve().parents[2]
THESIS = REPO / "parity" / "configs" / "thesis.yaml"
OUT = REPO / "research" / "data" / "mar27-loaded-pricing"

PRICINGS: tuple[dict[str, object], ...] = (
    {"kind": "pure"},
    *(
        {"kind": "cost_of_capital", "rate": rate, "q": q}
        for rate in (0.0, 0.06, 0.10)
        for q in (0.99, 0.995)
    ),
)
KPIS = (
    "expected_loss",
    "expected_payout",
    "premium",
    "expected_uncovered",
    "var_uncovered",
    "cvar_uncovered",
    "rmse_residual",
    "correlation",
)


def with_pricing(
    config: ExperimentConfig, pricing: dict[str, object]
) -> ExperimentConfig:
    """Return the config with another ``pricing`` block, re-validated."""
    data = to_dict(config)
    data["pricing"] = pricing
    return parse_config(data)


def label(pricing: dict[str, object]) -> str:
    """Return a short label for a pricing block."""
    if pricing["kind"] == "pure":
        return "pure"
    return f"coc r={pricing['rate']} q={pricing['q']}"


def main() -> None:
    """Run the baseline under every pricing and write the tables."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--store", type=Path, default=REPO / "results" / "mar27-loaded-pricing"
    )
    args = parser.parse_args()
    store = ResultStore(args.store)
    base = load_config(THESIS)
    data = load_input(base)
    headline: list[dict[str, object]] = []
    problems: list[pd.DataFrame] = []
    for pricing in PRICINGS:
        config = with_pricing(base, pricing)
        start = time.perf_counter()
        outcomes = run_config(config, store=store, data=data)
        seconds = time.perf_counter() - start
        print(f"{label(pricing)}: {len(outcomes)} runs, {seconds:.1f} s")
        singles = config.single_runs()
        for single, outcome in zip(singles, outcomes, strict=True):
            if not outcome.ok:
                raise RuntimeError(f"run {outcome.run_id} failed: {outcome.failed}")
            assert outcome.config_hash == config_hash(single)
            runs = store.read("runs", run_ids=[outcome.run_id])
            kpis = store.read("kpis", run_ids=[outcome.run_id])
            portfolio = kpis[kpis["level"] == "portfolio"].set_index("kpi")["value"]
            row: dict[str, object] = {
                "pricing": label(pricing),
                "rate": pricing.get("rate", 0.0),
                "q": pricing.get("q"),
                "scope": runs["scope"].iloc[0],
                "objective": runs["objective"].iloc[0],
                "n_problems": len(runs),
                "config_hash": outcome.config_hash,
                "run_id": outcome.run_id,
            }
            row.update({k: float(portfolio[k]) for k in KPIS})
            prob = kpis[
                (kpis["level"] == "problem")
                & (kpis["kpi"].isin(["premium", "expected_loss"]))
            ]
            wide = prob.pivot(
                index="problem_id", columns="kpi", values="value"
            ).reset_index()
            wide["budget_use"] = wide["premium"] / wide["expected_loss"]
            row["sum_problem_premiums"] = float(wide["premium"].sum())
            row["max_problem_budget_use"] = float(wide["budget_use"].max())
            row["min_problem_budget_use"] = float(wide["budget_use"].min())
            headline.append(row)
            wide.insert(0, "run_id", outcome.run_id)
            wide.insert(0, "config_hash", outcome.config_hash)
            wide.insert(0, "objective", row["objective"])
            wide.insert(0, "scope", row["scope"])
            wide.insert(0, "pricing", row["pricing"])
            problems.append(wide)
    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(headline).to_csv(
        OUT / "headline.csv", index=False, float_format="%.10g"
    )
    pd.concat(problems).to_csv(
        OUT / "problem_premiums.csv", index=False, float_format="%.10g"
    )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
