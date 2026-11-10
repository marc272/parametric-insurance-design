"""Re-time the draw-count runtime of MAR-25 on the annual basis (MAR-24).

MAR-25 (``docs/methodology/vulnerability.md``, "Number of draws and runtime")
timed one design LP on the thesis portfolio with 1-50 vulnerability draws on
the event-conditional basis. This script repeats that setup on the
event-conditional and the annual basis, with the thesis noise layer as the
draw generator: ``noise.add_noise`` with ``n_copies`` = number of draws gives
the same rows, the same ``draw_id`` and the same ``rate / n`` convention as
the vulnerability draws, on the committed thesis fixture (no CLIMADA build
needed). Only the loss values differ from MAR-25's.

Setup (MAR-25's): no threshold filter, weighted CVaR (alpha 0.5, beta 0.99),
10-bin step payout on [20, 70], pure premium, ``Budget(1.0)``, the default
solver policy; individual scope on asset A1, and the portfolio scope.

Run from the repository root:

    uv run python research/data/annual-basis-rerun/timing.py 1 10 20 50

Prints one line per (draws, basis, scope) and writes ``timing.csv``.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from parametric_insurance_design.basis import Basis, outcome_measure
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.objectives import WeightedCVaR
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.scopes import Individual, Portfolio
from parametric_insurance_design.solve import solve

HERE = Path(__file__).resolve().parent
FIXTURE = HERE.parents[2] / "parity" / "tests" / "data" / "thesis_eventset"
SEED = 42


def main(draw_counts: list[int]) -> None:
    """Time build + solve for every draw count, basis and scope."""
    base = EventSet.from_parquet(FIXTURE)
    print("fixture", base.content_hash(), base.n_rows, "rows")
    records = []
    for n in draw_counts:
        data = add_noise(
            base,
            level=0.3,
            kind="heteroscedastic",
            n_copies=n,
            rng=np.random.default_rng(SEED),
        )
        for basis in (Basis.EVENT_CONDITIONAL, Basis.ANNUAL):
            n_outcomes = outcome_measure(data, basis).n_outcomes
            first = Individual().partition(data)[:1]  # asset A1
            for scope_name, scope, specs in (
                ("individual A1", Individual(), first),
                ("portfolio", Portfolio(), None),
            ):
                start = time.perf_counter()
                built = build_problems(
                    data,
                    scope,
                    StepPayout(20.0, 70.0, 10),
                    WeightedCVaR(alpha=0.5, beta=0.99),
                    PurePremium(),
                    (Budget(1.0),),
                    basis=basis,
                    specs=specs,
                )
                result = solve(built[0])
                seconds = time.perf_counter() - start
                record = {
                    "draws": n,
                    "rows": data.n_rows,
                    "basis": basis.value,
                    "outcomes": n_outcomes,
                    "scope": scope_name,
                    "seconds": round(seconds, 2),
                    "solver": result.solver,
                    "attempts": "; ".join(
                        f"{a.solver}:{a.status.value}" for a in result.attempts
                    ),
                    "objective_value": result.objective_value,
                }
                print(record, flush=True)
                records.append(record)
    pd.DataFrame.from_records(records).to_csv(
        HERE / "timing.csv", index=False, float_format="%.6g"
    )


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or [1, 10, 20, 50])
