"""Compare the thesis designs calibrated on the three bases (MAR-24).

Reads the result stores of the three configs in this directory (written by
``parametric-insurance-design sweep <config> -p beta``), rebuilds every
stored design from its ``payouts`` and ``entities`` rows, and evaluates it
with ``evaluate.kpis`` on the **annual** basis (and on its own basis), on the
full sample. Writes ``comparison.csv`` next to this file and prints a
Markdown summary.

Run from the repository root, after the three sweeps:

    uv run python research/data/annual-basis-rerun/compare.py

Observations only; the interpretation belongs to checkpoint C1 (MAR-29).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.evaluate import kpis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    load_config,
)
from parametric_insurance_design.experiment.runner import (
    load_input,
    prepare_eventset,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import (
    Entity,
    ProblemSpec,
    Scope,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.pricing import PurePremium

HERE = Path(__file__).resolve().parent
BASES = ("event_conditional", "event", "annual")
BETAS = (0.95, 0.99)
KPIS = (
    "expected_uncovered",
    "cvar_uncovered",
    "var_uncovered",
    "rmse_residual",
    "payout_to_loss_ratio",
    "premium",
)


def rebuild(
    config: ExperimentConfig,
    runs: pd.DataFrame,
    payouts: pd.DataFrame,
    entities: pd.DataFrame,
) -> list[SolveResult]:
    """Rebuild the stored design problems of one run as SolveResults."""
    structure = config.to_components().payout
    out = []
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
                pay[pay["entity_id"] == e].sort_values("param_index")["value"]
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


def portfolio_kpis(
    eventset: EventSet,
    scope: Scope,
    results: list[SolveResult],
    basis: Basis,
    beta: float,
) -> dict[str, float]:
    """Return the portfolio-level KPIs of a run on one basis."""
    table = kpis(
        eventset,
        scope,
        results,
        basis=basis,
        beta=beta,
        run_id="x",
        pricing=PurePremium(),
    )
    rows = table[table["level"] == "portfolio"]
    return {k: float(rows.loc[rows["kpi"] == k, "value"].iloc[0]) for k in KPIS}


def main() -> None:
    """Evaluate every stored design and write ``comparison.csv``."""
    records = []
    prepared = None
    for name in BASES:
        config = load_config(HERE / f"thesis_{name}.yaml")
        if prepared is None:
            data = load_input(config)
            prepared = prepare_eventset(config, data.eventset)
        store = ResultStore(config.output.directory)
        runs = store.read("runs")
        payouts = store.read("payouts")
        entities = store.read("entities")
        scopes = {s.kind: s.build() for s in config.scopes}
        for run_id, group in runs.groupby("run_id", sort=False):
            first = group.iloc[0]
            params = json.loads(first["parameters"])
            results = rebuild(
                config,
                group,
                payouts[payouts["run_id"] == run_id],
                entities[entities["run_id"] == run_id],
            )
            scope = scopes[first["scope"]]
            record = {
                "calibrated_on": name,
                "scope": first["scope"],
                "objective": first["objective"],
                "objective_beta": params.get("beta"),
                "source": first["source"],
                "config_hash": first["config_hash"],
                "run_id": run_id,
                "solvers": ",".join(sorted(set(group["solver"].astype(str)))),
                "solve_seconds": float(group["solve_seconds"].sum()),
                "build_seconds": float(group["build_seconds"].sum()),
                "n_problems": len(group),
            }
            for beta in BETAS:
                own = portfolio_kpis(prepared, scope, results, Basis(name), beta)
                annual = portfolio_kpis(prepared, scope, results, Basis.ANNUAL, beta)
                for k in KPIS:
                    if k in ("cvar_uncovered", "var_uncovered") or beta == BETAS[0]:
                        suffix = f"@{beta}" if "var" in k else ""
                        record[f"own.{k}{suffix}"] = own[k]
                        record[f"annual.{k}{suffix}"] = annual[k]
            records.append(record)
    frame = pd.DataFrame.from_records(records)
    frame.to_csv(HERE / "comparison.csv", index=False, float_format="%.6g")
    print(frame.drop(columns=["run_id"]).to_string(index=False, float_format="%.4g"))


if __name__ == "__main__":
    main()
