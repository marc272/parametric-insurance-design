"""K-12 (MAR-311), question 5: time and memory of the design LP.

Solves the prototype's linear program (one joint "portfolio" problem, weighted
CVaR with ``alpha = 0.9``, ``beta = 0.95``, pure premium, ``budget = 1.0``,
5 steps) for 1, 67 and 1,000 units by 10,000 and 50,000 events, with
``scipy.optimize.linprog(method="highs")``. Each configuration runs in its own
process, so that its peak resident memory is its own.

The data are synthetic and are built to be the largest case: every event has a
loss (no shortfall variable is dropped). An event touches
``max(1, ceil(0.05 * n_units))`` adjacent units; its index is uniform on 25 to
80 and its loss at a touched unit is ``(index - 25)^2`` times lognormal noise.
There are two events per simulation year on average, and the annual basis has
one outcome per year.

``--seconds`` splits the time into the assembly, the HiGHS run and everything
``linprog`` does around it. Run from any environment with numpy, scipy, pandas
and the prototype on ``PYTHONPATH``::

    python packages/climada/scripts/k12_lp_scale.py --out lp.json
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import resource
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Final

import numpy as np
import scipy
import scipy.optimize._highspy._highs_wrapper as wrapper

import petals_parametric.solvers as solvers
from petals_parametric import OutcomeMeasure, StepPayout, WeightedCVaR, outcome_measure
from petals_parametric.pricing import PurePremium
from petals_parametric.solvers import DesignData, solve_design

UNITS: Final[tuple[int, ...]] = (1, 67, 1_000)
EVENTS: Final[tuple[int, ...]] = (10_000, 50_000)
SEED: Final[int] = 311


class TimedHighs(wrapper._h._Highs):
    """HiGHS that records how long its ``run`` took."""

    elapsed: float = 0.0

    def run(self, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        """Run HiGHS and record the wall time."""
        start = time.perf_counter()
        status = super().run(*args, **kwargs)
        TimedHighs.elapsed = time.perf_counter() - start
        return status


def build_data(
    n_units: int, n_events: int
) -> tuple[DesignData, OutcomeMeasure, dict[str, Any]]:
    """Return one design problem with every event lossy (module docstring)."""
    rng = np.random.default_rng([SEED, n_units, n_events])
    n_years = n_events // 2
    hit = max(1, math.ceil(0.05 * n_units))
    start = rng.integers(0, n_units - hit + 1, size=n_events)
    index_at_hit = rng.uniform(25.0, 80.0, size=(n_events, hit))
    noise = rng.lognormal(0.0, 0.5, size=(n_events, hit))
    rows = np.repeat(np.arange(n_events), hit)
    columns = (start[:, None] + np.arange(hit)).ravel()
    index = np.zeros((n_events, n_units))
    loss = np.zeros((n_events, n_units))
    index[rows, columns] = index_at_hit.ravel()
    loss[rows, columns] = (index_at_hit.ravel() - 25.0) ** 2 * noise.ravel() + 1e-6
    event_year = np.sort(rng.integers(0, n_years, size=n_events))
    measure = outcome_measure(
        event_year,
        np.full(n_events, 1.0 / n_years),
        basis="annual",
        years=np.arange(n_years),
        n_catalogue_years=n_years,
    )
    data = DesignData("portfolio", index, loss, measure)
    return data, measure, {"n_years": n_years, "units_touched_per_event": hit}


def run_one(n_units: int, n_events: int) -> dict[str, Any]:
    """Solve one configuration and return its timings and memory."""
    build_start = time.perf_counter()
    data, measure, setup = build_data(n_units, n_events)
    build_seconds = time.perf_counter() - build_start

    wrapper._h._Highs = TimedHighs
    real_linprog = solvers.linprog
    linprog_seconds = {"value": 0.0}

    def timed_linprog(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        start = time.perf_counter()
        result = real_linprog(*args, **kwargs)
        linprog_seconds["value"] = time.perf_counter() - start
        return result

    solvers.linprog = timed_linprog
    payout = StepPayout(attachment=25.0, limit=80.0, n_steps=5)
    solution = solve_design(
        data,
        payout,
        WeightedCVaR(alpha=0.9, beta=0.95),
        PurePremium(),
        1.0,
    )
    scale_mb = 1024.0**2 if platform.system() == "Darwin" else 1024.0
    peak_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / scale_mb
    # theta (m K) + u (lossy events) + zeta + v (outcomes with loss + pool).
    n_outcomes = measure.n_outcomes
    n_variables = n_units * 5 + n_events + 1 + n_outcomes + 1
    linprog_total = linprog_seconds["value"]
    highs_run = TimedHighs.elapsed
    return {
        "n_units": n_units,
        "n_events": n_events,
        **setup,
        "n_outcomes": n_outcomes,
        "n_variables_about": n_variables,
        "dense_inputs_mb": float(data.index.nbytes + data.loss.nbytes) / 1024.0**2,
        "seconds_build_inputs": build_seconds,
        "seconds_solve_design": solution.info.seconds,
        "seconds_linprog": linprog_total,
        "seconds_highs_run": highs_run,
        "seconds_linprog_minus_highs": linprog_total - highs_run,
        "iterations": solution.info.iterations,
        "peak_rss_mb": peak_mb,
        "objective_value": solution.objective_value,
        "scipy": scipy.__version__,
        "numpy": np.__version__,
        "python": platform.python_version(),
    }


def main() -> None:
    """Run every configuration in a process of its own and write the results."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--one", nargs=2, type=int, metavar=("UNITS", "EVENTS"))
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--units", nargs="*", type=int, default=list(UNITS))
    parser.add_argument("--events", nargs="*", type=int, default=list(EVENTS))
    args = parser.parse_args()
    if args.one:
        print(json.dumps(run_one(args.one[0], args.one[1])))
        return
    rows = []
    for n_units in args.units:
        for n_events in args.events:
            command = [
                sys.executable,
                str(Path(__file__).resolve()),
                "--one",
                str(n_units),
                str(n_events),
            ]
            try:
                done = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=args.timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                row = {
                    "n_units": n_units,
                    "n_events": n_events,
                    "timed_out_after_seconds": args.timeout,
                    "scipy": scipy.__version__,
                }
            else:
                if done.returncode != 0:
                    row = {
                        "n_units": n_units,
                        "n_events": n_events,
                        "error": done.stderr[-800:],
                        "scipy": scipy.__version__,
                    }
                else:
                    row = json.loads(done.stdout.strip().splitlines()[-1])
            print(json.dumps(row), flush=True)
            rows.append(row)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=1) + "\n")


if __name__ == "__main__":
    main()
