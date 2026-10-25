# Solve-time baseline (MAR-14)

Wall times of the core engine (`problem.build_problems` + `solve.solve`) for the nine scope × objective combinations on the parity fixture, with the thesis default configuration. These are a baseline for later changes (annual basis, robust design, larger event sets), not a performance claim.

Owner: MAR-14 (ADR 0002 ownership map). Recorded 2026-10-25. Updated by MAR-98 (2026-10-25): the default policy now runs OSQP at `eps_abs = eps_rel = 1e-8`, which changes the MSE rows.

## Setup

- **Data:** `parity/tests/data/thesis_eventset` (MAR-9) after the thesis data preparation: heteroscedastic noise layer, η = 0.3, 13 copies, `default_rng(42)`, drawn asset by asset (`noise.add_noise`, MAR-10), then the 20 m/s threshold filter (`EventSet.filter_threshold(20.0)`). **13,897 rows × 9 assets.** Basis `event_conditional` (thesis parity).
- **Thesis defaults** (`configs/experiment_config.yaml`, `configs/global_settings.yaml` of `parametric-insurance-framework`): `StepPayout(attachment=20, limit=70, n_bins=15)`, `PurePremium`, `Budget(1.0)`, `WeightedCVaR(alpha=0.9, beta=0.95)`, `Cluster(ThesisWardClustering(beta_tail=0.9), n_clusters=3)`.
- **Solver policy:** `DEFAULT_POLICY`: LP chain CLARABEL → HIGHS → SCS (SCS `max_iters=20000`), QP chain OSQP → CLARABEL (OSQP `eps_abs = eps_rel = 1e-8`, `max_iter = 100000`, MAR-98), `optimal_inaccurate` accepted. Every combination below was solved by the first solver of its chain with status `optimal`.
- **Timing:** median of 5 runs. *Build* is `build_problems` for all problems of the scope (sample selection, measure, partition including the clustering, materialise, context, terms, DCP check). *Solve* is the sum of `SolveResult.solve_seconds` (wall time of `Problem.solve`, including cvxpy's compilation). *Total* is build plus solve, wall clock.
- **Machine:** Apple M4 (arm64), macOS 15.7, Python 3.12.11, single process.

## Baseline: workspace lock

cvxpy 1.9.3, numpy 2.5.4, scipy 1.18.1, clarabel 0.11.1, osqp 1.1.3, scs 3.3.1, highspy 1.15.1.

| Scope | Objective | Problems | Solver | Build (s) | Solve (s) | Total (s) |
|---|---|---:|---|---:|---:|---:|
| individual | MSE | 9 | OSQP | 0.018 | 1.96 | 1.99 |
| individual | E[U] | 9 | CLARABEL | 0.021 | 1.04 | 1.08 |
| individual | weighted CVaR | 9 | CLARABEL | 0.025 | 3.47 | 3.51 |
| portfolio | MSE | 1 | OSQP | 0.016 | 4.97 | 4.99 |
| portfolio | E[U] | 1 | CLARABEL | 0.014 | 0.28 | 0.29 |
| portfolio | weighted CVaR | 1 | CLARABEL | 0.014 | 0.60 | 0.62 |
| cluster | MSE | 1 | OSQP | 0.014 | 1.27 | 1.28 |
| cluster | E[U] | 1 | CLARABEL | 0.012 | 0.13 | 0.14 |
| cluster | weighted CVaR | 1 | CLARABEL | 0.014 | 0.37 | 0.38 |

All nine take about 14 s together. Building is negligible; the portfolio MSE QP and the individual scope's nine weighted-CVaR LPs dominate.

**Before MAR-98** (OSQP at cvxpy's defaults, `eps_abs = eps_rel = 1e-5`, `max_iter = 10000`, as in the thesis) the MSE solves took 0.25 s (individual, Σ 9), 0.37 s (portfolio) and 0.15 s (cluster), and all nine about 7 s. The tighter tolerance costs about 15,000 OSQP iterations instead of 900 on the portfolio MSE and 1,300 instead of 75 on each individual one: 8 to 13 times the MSE solve time. In exchange the MSE solutions meet `θ ≥ 0`, monotonicity, the cap and the budget to ≤ 4.4e-10 in scaled units (before: up to 3.8e-6 on this fixture and 8.2e-6 on the engine's property tests).

## CLIMADA-env stack (no HiGHS)

cvxpy 1.6.0, numpy 1.26.4, scipy 1.15.3, clarabel 0.11.1, osqp 1.1.3, scs 3.3.1; HiGHS not installed (ADR 0002: cvxpy < 1.8 ships no `highspy`). Same solvers chosen, same objective values to ≤ 1e-9 relative.

With scipy 1.15.0 or 1.15.1 (core's declared floor is `scipy>=1.15`), the three weighted-CVaR combinations fail before any solver runs: cvxpy reshapes their sparse problem data (more than 2^31 entries), and those scipy versions overflow int32 indices (`ValueError: negative axis 0 index`). scipy 1.15.2 fixes it. The fixture test marks these cases as a strict expected failure on scipy < 1.15.2; raising the floor is a proposed follow-up.

| Scope | Objective | Solver | Build (s) | Solve (s) | Total (s) |
|---|---|---|---:|---:|---:|
| individual | MSE | OSQP | 0.022 | 0.25 | 0.28 |
| individual | E[U] | CLARABEL | 0.021 | 1.02 | 1.05 |
| individual | weighted CVaR | CLARABEL | 0.025 | 4.72 | 4.75 |
| portfolio | MSE | OSQP | 0.020 | 0.46 | 0.48 |
| portfolio | E[U] | CLARABEL | 0.019 | 0.30 | 0.32 |
| portfolio | weighted CVaR | CLARABEL | 0.020 | 1.17 | 1.19 |
| cluster | MSE | OSQP | 0.027 | 0.28 | 0.32 |
| cluster | E[U] | CLARABEL | 0.033 | 0.27 | 0.31 |
| cluster | weighted CVaR | CLARABEL | 0.022 | 0.77 | 0.80 |

This table was recorded before MAR-98, with OSQP at cvxpy's defaults. MAR-98 re-measured only the MSE rows, in the pixi env as locked today (`packages/climada`, MAR-71), which no longer resolves the stack above: cvxpy 1.9.3, numpy 2.3.5, scipy 1.15.2, osqp 1.1.3. Solve times 2.41 s (individual), 4.83 s (portfolio) and 1.36 s (cluster); objective values equal to the workspace lock's to 1e-15 relative.

## Other solvers (workspace lock, median of 3; SCS a single run)

Solve time (s) when the chain is a single solver. *Δ obj* is the relative change of the objective value against the default policy's (for the individual scope, the sum over its nine problems).

| Scope | Objective | HIGHS | Δ obj | CLARABEL (QP) | Δ obj | SCS | Δ obj |
|---|---|---:|---:|---:|---:|---:|---:|
| individual | MSE | | | 0.48 | +5.2e-6 | 0.48 | −2e-10 |
| individual | E[U] | 1.22 | −1.5e-9 | | | 20.65 | −5.4e-4 |
| individual | weighted CVaR | 5.57 | +3.7e-10 | | | 6.74 | +2.3e-7 |
| portfolio | MSE | | | 0.19 | +7.7e-6 | 0.24 | −3.4e-8 |
| portfolio | E[U] | 0.95 | +3e-10 | | | 2.08 | −1.5e-3 |
| portfolio | weighted CVaR | 2.55 | +1.5e-9 | | | 1.54 | +9.8e-6 |
| cluster | MSE | | | 0.08 | +6.4e-6 | 0.08 | −1.7e-6 |
| cluster | E[U] | 0.33 | +1.8e-9 | | | 1.61 | −1.9e-5 |
| cluster | weighted CVaR | 1.07 | +5e-11 | | | 1.26 | +9.9e-7 |

Clarabel is the fastest LP solver here, which supports it as the first LP choice. SCS is a last resort: on E[U] it is slow, and its lower objective values come from constraint violations at its default tolerance, not from better solutions.

The MSE columns were re-measured by MAR-98 against the new default (OSQP at `1e-8`). Clarabel solves the MSE QPs 4 to 26 times faster than that OSQP, but at its default tolerances it stops 5e-6 to 8e-6 relative above OSQP's optimum. A high-accuracy Clarabel solve (`tol_gap_abs = tol_gap_rel = tol_feas = 1e-12`) agrees with the new OSQP default to ≤ 4.2e-8 relative on all eleven MSE problems.

## Observations against the thesis (for MAR-68)

These are observations, not the parity verdict; that is MAR-68 and the gate MAR-18.

The thesis `single_run` payouts of `parity/golden/full_optimization_results.csv.gz` were evaluated with numpy on the same 13,897 rows (thesis objective formulas, `event_conditional` probabilities) and compared with the objective values of the core's solutions. Default policy, workspace lock:

| Scope | Objective | Core objective (loss units) | Relative to the thesis payouts | max \|Δθ\| / max \|θ\| |
|---|---|---:|---:|---:|
| individual (Σ 9) | MSE | 6.915743e+11 | −1.7e-8 | 9.2e-6 |
| individual (Σ 9) | E[U] | 1.933253e+05 | +4.1e-10 | 3.7e-8 |
| individual (Σ 9) | weighted CVaR | 2.446390e+06 | −8.8e-10 | 1.6e-3 |
| portfolio | MSE | 6.063693e+11 | −9.1e-5 | 7.1e-4 |
| portfolio | E[U] | 8.566023e+04 | +2.2e-9 | 1.5e-6 |
| portfolio | weighted CVaR | 9.722835e+05 | −1.2e-9 | 1.6e-3 |
| cluster | MSE | 6.761546e+11 | −4.7e-6 | 9.7e-5 |
| cluster | E[U] | 1.021042e+05 | −2.0e-9 | 4.2e-8 |
| cluster | weighted CVaR | 1.181435e+06 | +9.3e-10 | 3.2e-4 |

- The six E[U] and weighted-CVaR objective values agree with the thesis payouts to ≤ 3e-9 relative, far inside the F-06 tolerance (1e-4). The weighted-CVaR payouts differ by up to 1.6e-3 of the largest payout at equal objective value: those LP optima are not unique, which F-06 already allows for.
- **MSE: the core is now more accurate than the thesis, and lower by up to 9.1e-5 relative (MAR-98).** The thesis ran OSQP at cvxpy's defaults (`eps = 1e-5` in scaled units). Before MAR-98 the core did the same and reproduced the thesis MSE values to ~1e-11 (−8.6e-15, −1.2e-11 and −1.0e-11 for individual, portfolio and cluster), inaccuracy included: the thesis individual MSE payouts of A2, A3 and A4, and the core's, exceeded the budget by about 1e-4 relative. With OSQP at `1e-8` the core's MSE solutions meet the budget and the payout family to ≤ 4.4e-10 in scaled units, and their objective values lie 1.7e-8 (individual, Σ 9), 4.7e-6 (cluster) and 9.1e-5 (portfolio) below the values of the thesis payouts. A high-accuracy Clarabel solve confirms these are the optima (≤ 4.2e-8 relative), so the gap is the thesis's OSQP inaccuracy. The portfolio gap is inside the F-06 tolerance (1e-4) but close to it. To reproduce the thesis MSE values instead, run with `solve.THESIS_POLICY` (the pre-MAR-98 default, OSQP at cvxpy's defaults; `test_solve.py::test_thesis_policy_reproduces_the_thesis_mse_solves`). Which of the two the parity gate compares is a question for MAR-68/MAR-18.
- **The MSE KPIs move much more than the MSE objective values.** A quadratic objective is flat at its optimum, so an objective error of ε relative allows payout errors of order √ε. Against a high-accuracy Clarabel solve, the portfolio MSE payouts at cvxpy's OSQP defaults are off by 1.7e-4 of the largest loss, and their expected uncovered loss by 1.8e-2 relative (cluster: 4.2e-5 and 3.4e-3); at `1e-8`, by 2.2e-7 and 2.6e-5 (cluster: 4.1e-7 and 1.9e-5). On top of that, the split of a joint payout across the entities of a portfolio or cluster problem is not unique for MSE, which depends only on the summed payout. The parity harness (MAR-67, `compare(..., sources=["single_run"])`, default tolerances) on the nine single runs of `parity/configs/thesis.yaml` reports 10 KPI mismatches with OSQP at cvxpy's defaults (all portfolio weighted CVaR, the non-unique LP optima above) and 80 with the new default: the same 10, plus 18 of 24 cluster-MSE and 52 of 60 portfolio-MSE KPIs. The largest are per-entity KPIs (up to 0.86 relative, VaR of the uncovered loss); at portfolio level the portfolio-MSE run's E[U] and VaR differ by 1.8e-2 and 1.9e-2. The individual-MSE KPIs stay within 1e-4 (≤ 9.7e-5).

## How to reproduce

From the repository root, with the script below saved outside the repository (it is not committed: `parity/scripts/` belongs to other issues):

```bash
uv run python benchmark_engine.py 5            # default policy
uv run python benchmark_engine.py 3 highs      # or clarabel-qp, scs
uv run python benchmark_engine.py 5 osqp-cvxpy-defaults mse   # MSE before MAR-98
```

<details>
<summary><code>benchmark_engine.py</code></summary>

```python
"""Solve-time baseline of the nine scope x objective combinations (MAR-14)."""

import statistics
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.clustering import ThesisWardClustering
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.objectives import MSE, ExpectedUncovered, WeightedCVaR
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio
from parametric_insurance_design.solve import SolverPolicy, solve

REPEATS = int(sys.argv[1]) if len(sys.argv) > 1 else 5
POLICY = {
    "default": SolverPolicy(),
    "highs": SolverPolicy(lp_solvers=("HIGHS",)),
    "clarabel-qp": SolverPolicy(qp_solvers=("CLARABEL",)),
    "scs": SolverPolicy(lp_solvers=("SCS",), qp_solvers=("SCS",)),
    # Before MAR-98: OSQP at cvxpy's defaults (eps 1e-5), as in the thesis.
    "osqp-cvxpy-defaults": SolverPolicy(solver_options={"SCS": {"max_iters": 20000}}),
}[sys.argv[2] if len(sys.argv) > 2 else "default"]
ONLY = sys.argv[3].split(",") if len(sys.argv) > 3 else None  # e.g. "mse"
ALPHA, BETA = 0.9, 0.95

eventset = add_noise(
    EventSet.from_parquet(Path("parity/tests/data/thesis_eventset")),
    level=0.3,
    kind="heteroscedastic",
    n_copies=13,
    rng=np.random.default_rng(42),
    location_ids=[f"A{k}" for k in range(1, 10)],
).filter_threshold(20.0)
p = eventset.rates / eventset.rates.sum()
golden = pd.read_csv("parity/golden/full_optimization_results.csv.gz")
golden = golden[golden.Source == "single_run"]
SCOPES = {
    "individual": ("individual_optimization", Individual()),
    "portfolio": ("integrated_portfolio_optimization", Portfolio()),
    "cluster": ("cluster_optimization", Cluster(ThesisWardClustering(0.9), 3)),
}
OBJECTIVES = {
    "mse": ("pure_basis_risk_minimization", MSE()),
    "expected_uncovered": ("pure_uncovered_loss_minimization", ExpectedUncovered()),
    "weighted_cvar": ("weighted_cvar_minimization", WeightedCVaR(ALPHA, BETA)),
}
PAYOUT = StepPayout(attachment=20.0, limit=70.0, n_bins=15)


def numpy_objective(name, loss, payout):
    """Thesis objective formulas, event_conditional probabilities."""
    if name == "mse":
        return float(p @ (loss - payout) ** 2)
    u = np.maximum(loss - payout, 0.0)
    if name == "expected_uncovered":
        return float(p @ u)
    order = np.argsort(u, kind="stable")
    var = u[order][np.searchsorted(np.cumsum(p[order]), BETA)]
    cvar = var + float(p @ np.maximum(u - var, 0.0)) / (1 - BETA)
    return ALPHA * cvar + (1 - ALPHA) * float(p @ u)


for sname, (sthesis, scope) in SCOPES.items():
    for oname, (othesis, objective) in OBJECTIVES.items():
        if ONLY and oname not in ONLY:
            continue
        builds, solves, totals = [], [], []
        for _ in range(REPEATS):
            start = time.perf_counter()
            built = build_problems(
                eventset,
                scope,
                PAYOUT,
                objective,
                PurePremium(),
                (Budget(1.0),),
                basis=Basis.EVENT_CONDITIONAL,
            )
            builds.append(time.perf_counter() - start)
            results = [solve(b, POLICY) for b in built]
            totals.append(time.perf_counter() - start)
            solves.append(sum(r.solve_seconds for r in results))
        rows = golden[(golden.Approach == sthesis) & (golden.Method == othesis)]
        ours = theirs = dtheta = 0.0
        for b, r in zip(built, results, strict=True):
            prob = b.context.problem
            theta = np.vstack(
                [
                    np.fromstring(
                        rows[rows.Asset_ID == e].Payouts.iloc[0].strip("[]"), sep=" "
                    )
                    for e in r.entity_ids
                ]
            )
            ours += r.objective_value
            dtheta = max(dtheta, np.abs(r.theta - theta).max() / np.abs(theta).max())
            paid = PAYOUT.evaluate(prob.index, theta).sum(axis=1)
            theirs += numpy_objective(oname, prob.loss, paid)
        print(
            f"| {sname} | {oname} | {len(built)} "
            f"| {'/'.join(sorted({r.solver for r in results}))} "
            f"| {statistics.median(builds):.3f} | {statistics.median(solves):.2f} "
            f"| {statistics.median(totals):.2f} | {ours:.6e} "
            f"| {(ours - theirs) / theirs:+.1e} | {dtheta:.1e} |"
        )
```

</details>

The same nine combinations run in CI as `packages/core/tests/test_solve.py::test_nine_combinations_solve_on_the_fixture`, which checks status, solver, constraints and the numpy recomputation of every objective value, but not timings.
