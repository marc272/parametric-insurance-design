"""K-12 (MAR-311), question 6: routes to the mean-squared-error design.

The design problem is a quadratic program over the payout levels ``theta``:
minimise ``|| A theta - b ||^2`` subject to ``0 <= theta <= cap``, monotone
levels and the premium budget, with ``A = sqrt(p) G B`` and ``b = sqrt(p) G L``
(annual basis, ``G`` sums events into years, ``B`` is the step basis). The
routes are:

``cvxpy``
    the prototype's ``solve_design`` (cvxpy with Clarabel), the reference;
``highspy``
    HiGHS's own QP solver, through the ``highspy`` package;
``scipy_highs_private``
    the same QP solver through scipy's private ``scipy.optimize._highspy``
    bindings (no new package, but a private interface);
``trust_constr`` and ``slsqp``
    ``scipy.optimize.minimize`` with analytic derivatives;
``lsq_linear``
    ``scipy.optimize.lsq_linear`` on the level increments, with the budget
    handled by a one-dimensional search on its multiplier (bounds only, so the
    cap on the top level is a bound on each increment and is checked after).

Data: the worst-case synthetic generator of ``k12_lp_scale.py`` (every event
lossy), 5 steps, budget 0.8, pure premium, one joint problem. The accuracy is
the objective's relative gap to the cvxpy route on the same data. ``--loaded``
adds a cost-of-capital load (rate 0.3, q 0.99), for ``cvxpy`` and ``highspy``
only, because the other routes have no linear rows for its auxiliaries. Each
run is its own process, for its own peak memory::

    python packages/climada/scripts/k12_mse_routes.py --out mse.json
"""

from __future__ import annotations

import argparse
import importlib
import json
import platform
import resource
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
import scipy
import scipy.optimize._highspy._core as scipy_highs
import scipy.sparse as sp
from k12_lp_scale import build_data  # pyright: ignore[reportMissingImports]
from numpy.typing import NDArray
from scipy.optimize import Bounds, LinearConstraint, brentq, lsq_linear, minimize

import petals_parametric.solvers as solvers
from petals_parametric import MeanSquaredError, StepPayout
from petals_parametric.pricing import CostOfCapitalLoad, PurePremium

BUDGET: Final[float] = 0.8
STEPS: Final[int] = 5
SIZES: Final[tuple[tuple[int, int], ...]] = (
    (1, 10_000),
    (67, 10_000),
    (67, 50_000),
    (1_000, 10_000),
)
ROUTES: Final[tuple[str, ...]] = (
    "cvxpy",
    "highspy",
    "scipy_highs_private",
    "trust_constr",
    "slsqp",
    "lsq_linear",
)
LOAD_RATE: Final[float] = 0.3
LOAD_Q: Final[float] = 0.99


@dataclass(frozen=True, eq=False)
class Qp:
    """The scaled quadratic program of one design problem."""

    a: sp.csr_matrix
    b: NDArray[np.float64]
    ub: NDArray[np.float64]
    monotone: sp.csr_matrix
    premium: NDArray[np.float64]
    rhs: float
    sqrt_p: NDArray[np.float64]
    n_units: int
    norm: float

    def objective(self, theta: NDArray[np.float64]) -> float:
        """Return ``|| A theta - b ||^2 / norm``."""
        residual = self.a @ theta - self.b
        return float(residual @ residual) / self.norm

    def violation(self, theta: NDArray[np.float64]) -> dict[str, float]:
        """Return the largest violation of each kind of constraint."""
        return {
            "bounds": float(
                max(float(np.max(-theta)), float(np.max(theta - self.ub)), 0.0)
            ),
            "monotone": float(max(float(np.max(self.monotone @ theta)), 0.0)),
            "budget_relative": float(
                max(float(self.premium @ theta) / self.rhs - 1.0, 0.0)
            ),
        }


def build_qp(n_units: int, n_events: int, *, budget: float) -> tuple[Qp, Any, Any]:
    """Return the program, the design data and the payout."""
    data, _, _ = build_data(n_units, n_events)
    payout = StepPayout(attachment=25.0, limit=80.0, n_steps=STEPS)
    arr = solvers._scaled(data, payout)
    sqrt_p = np.sqrt(arr.prob)
    a = sp.csr_matrix(sp.diags(sqrt_p) @ arr.group @ arr.basis)
    b = np.asarray(sqrt_p * (arr.group @ arr.loss), dtype=np.float64)
    assert arr.monotone is not None
    qp = Qp(
        a=a,
        b=b,
        ub=np.asarray(arr.caps, dtype=np.float64),
        monotone=sp.csr_matrix(arr.monotone),
        premium=np.asarray(arr.premium_row, dtype=np.float64),
        rhs=budget * arr.expected_loss,
        sqrt_p=sqrt_p,
        n_units=n_units,
        norm=float(b @ b),
    )
    return qp, data, payout


def solve_cvxpy(qp: Qp, data: Any, payout: Any, pricing: Any) -> dict[str, Any]:  # noqa: ANN401
    """Solve with the prototype's cvxpy route."""
    solution = solvers.solve_design(
        data, payout, MeanSquaredError(), pricing, qp.rhs / _expected(data)
    )
    theta = solution.levels.reshape(-1) / data.scale
    return {
        "theta": theta,
        "status": solution.info.status,
        "iterations": solution.info.iterations,
    }


def _expected(data: Any) -> float:  # noqa: ANN401
    """Return ``E[L]`` in scaled units: the divisor between budget and bound."""
    scaled = data.total_loss / data.scale
    return float(data.measure.event_probability @ scaled)


def _rows(matrix: Any) -> int:  # noqa: ANN401 (any scipy sparse matrix)
    """Return the number of rows of a sparse matrix."""
    return int(matrix.shape[0])


def _highs_model(
    qp: Qp,
    core: Any,  # noqa: ANN401
    *,
    loaded: Any = None,  # noqa: ANN401
) -> tuple[Any, Any, NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Return HiGHS's LP and Hessian, with the budget's and load's linear rows."""
    n = qp.ub.size
    hessian = sp.csc_matrix(sp.tril(2.0 * (qp.a.T @ qp.a) / qp.norm, format="csc"))
    cost = -2.0 * (qp.a.T @ qp.b) / qp.norm
    lower = np.zeros(n)
    upper = np.array(qp.ub, copy=True)
    if loaded is None:
        rows = sp.vstack([qp.monotone, sp.csr_matrix(qp.premium[None, :])]).tocsr()
        rhs = np.append(np.zeros(_rows(qp.monotone)), qp.rhs)
    else:
        pays, prob, rate, level = loaded
        active = pays.getnnz(axis=1) > 0
        extra = int(active.sum())
        n_new = 1 + extra
        size = n + n_new
        tail_rows = sp.hstack(
            [
                pays[active],
                sp.csr_matrix(-np.ones((extra, 1))),
                -sp.identity(extra, format="csr"),
            ]
        )
        budget_row = sp.csr_matrix(
            np.concatenate(
                [
                    (1.0 - rate) * qp.premium,
                    [rate],
                    rate / (1.0 - level) * prob[active],
                ]
            )[None, :]
        )
        monotone = sp.hstack([qp.monotone, sp.csr_matrix((_rows(qp.monotone), n_new))])
        rows = sp.vstack([monotone, tail_rows, budget_row]).tocsr()
        rhs = np.concatenate([np.zeros(_rows(qp.monotone) + extra), [qp.rhs]])
        cost = np.append(cost, np.zeros(n_new))
        lower = np.concatenate([lower, [-np.inf], np.zeros(extra)])
        upper = np.concatenate([upper, np.full(n_new, np.inf)])
        hessian = sp.csc_matrix(
            (
                hessian.data,
                hessian.indices,
                np.append(hessian.indptr, np.full(n_new, hessian.nnz)),
            ),
            shape=(size, size),
        )
    columns = rows.tocsc()
    lp = core.HighsLp()
    lp.num_col_ = cost.size
    lp.num_row_ = _rows(rows)
    lp.col_cost_ = cost
    lp.col_lower_ = lower
    lp.col_upper_ = upper
    lp.row_lower_ = np.full(_rows(rows), -np.inf)
    lp.row_upper_ = rhs
    lp.a_matrix_.format_ = core.MatrixFormat.kColwise
    lp.a_matrix_.num_col_ = cost.size
    lp.a_matrix_.num_row_ = _rows(rows)
    lp.a_matrix_.start_ = columns.indptr
    lp.a_matrix_.index_ = columns.indices
    lp.a_matrix_.value_ = columns.data
    hess = core.HighsHessian()
    hess.dim_ = _rows(hessian)
    hess.format_ = core.HessianFormat.kTriangular
    hess.start_ = hessian.indptr
    hess.index_ = hessian.indices
    hess.value_ = hessian.data
    return lp, hess, cost, lower, upper


def solve_highs(qp: Qp, core: Any, make: Any, *, loaded: Any = None) -> dict[str, Any]:  # noqa: ANN401
    """Solve with a HiGHS binding's QP solver."""
    lp, hess, _, _, _ = _highs_model(qp, core, loaded=loaded)
    highs = make()
    highs.setOptionValue("output_flag", False)
    highs.passModel(lp)
    highs.passHessian(hess)
    status = highs.run()
    info = highs.getInfo()
    model_status = highs.getModelStatus()
    theta = np.asarray(highs.getSolution().col_value, dtype=np.float64)[: qp.ub.size]
    return {
        "theta": theta,
        "status": str(model_status),
        "run_status": str(status),
        "iterations": int(info.qp_iteration_count),
    }


def solve_trust_constr(qp: Qp) -> dict[str, Any]:
    """Solve with ``trust-constr``."""
    n = qp.ub.size
    hessian = sp.csr_matrix(2.0 * (qp.a.T @ qp.a) / qp.norm)
    fun = qp.objective
    jac = lambda t: 2.0 * (qp.a.T @ (qp.a @ t - qp.b)) / qp.norm  # noqa: E731
    rows = sp.vstack([qp.monotone, sp.csr_matrix(qp.premium[None, :])]).tocsr()
    rhs = np.append(np.zeros(_rows(qp.monotone)), qp.rhs)
    result = minimize(
        fun,
        np.zeros(n),
        jac=jac,
        hess=lambda _: hessian,
        method="trust-constr",
        bounds=Bounds(np.zeros(n), qp.ub),  # pyright: ignore[reportArgumentType]
        constraints=[LinearConstraint(rows, -np.inf, rhs)],  # pyright: ignore[reportArgumentType]
        options={"gtol": 1e-9, "xtol": 1e-12, "barrier_tol": 1e-9, "maxiter": 20_000},
    )
    return {
        "theta": np.asarray(result.x, dtype=np.float64),
        "status": str(result.status),
        "iterations": int(result.nit),
        "message": str(result.message),
    }


def solve_slsqp(qp: Qp) -> dict[str, Any]:
    """Solve with ``SLSQP``."""
    n = qp.ub.size
    monotone = qp.monotone.toarray()
    jac = lambda t: 2.0 * (qp.a.T @ (qp.a @ t - qp.b)) / qp.norm  # noqa: E731
    constraints = [
        {"type": "ineq", "fun": lambda t: -(monotone @ t), "jac": lambda _: -monotone},
        {
            "type": "ineq",
            "fun": lambda t: np.array([qp.rhs - float(qp.premium @ t)]),
            "jac": lambda _: -qp.premium[None, :],
        },
    ]
    result = minimize(
        qp.objective,
        np.zeros(n),
        jac=jac,
        method="SLSQP",
        bounds=np.column_stack([np.zeros(n), qp.ub]),
        constraints=constraints,
        options={"ftol": 1e-13, "maxiter": 3_000},
    )
    return {
        "theta": np.asarray(result.x, dtype=np.float64),
        "status": str(result.status),
        "iterations": int(result.nit),
        "message": str(result.message),
    }


def solve_lsq_linear(qp: Qp) -> dict[str, Any]:
    """Solve with ``lsq_linear`` on the increments, searching the multiplier."""
    block = np.tril(np.ones((STEPS, STEPS)))
    increments = sp.block_diag([block] * qp.n_units, format="csr")
    design = sp.csr_matrix(qp.a @ increments)
    upper = qp.ub
    solves = {"count": 0}

    def theta_of(lam: float) -> NDArray[np.float64]:
        solves["count"] += 1
        result = lsq_linear(
            design,
            qp.b - 0.5 * lam * qp.sqrt_p,
            bounds=(np.zeros(upper.size), upper),
            method="trf",
            lsq_solver="lsmr",
            tol=1e-12,
            max_iter=2_000,
        )
        return np.asarray(increments @ result.x, dtype=np.float64)

    theta = theta_of(0.0)
    multiplier = 0.0
    if float(qp.premium @ theta) > qp.rhs:
        high = 1e-4
        while float(qp.premium @ theta_of(high)) > qp.rhs and high < 1e6:
            high *= 4.0
        root: Any = brentq(
            lambda lam: float(qp.premium @ theta_of(lam)) - qp.rhs,
            0.0,
            high,
            xtol=1e-12,
            rtol=1e-10,  # pyright: ignore[reportArgumentType]
        )
        multiplier = float(root)
        theta = theta_of(multiplier)
    return {
        "theta": theta,
        "status": "search finished",
        "iterations": solves["count"],
        "multiplier": multiplier,
    }


def run_one(
    route: str, n_units: int, n_events: int, *, loaded: bool, budget: float
) -> dict[str, Any]:
    """Run one route on one size; return timing, accuracy and memory."""
    qp, data, payout = build_qp(n_units, n_events, budget=budget)
    pricing = CostOfCapitalLoad(LOAD_RATE, LOAD_Q) if loaded else PurePremium()
    load_data = None
    if loaded:
        arr = solvers._scaled(data, payout)
        load_data = (
            sp.csr_matrix(arr.group @ arr.basis),
            arr.prob,
            LOAD_RATE,
            LOAD_Q,
        )
    start = time.perf_counter()
    if route == "cvxpy":
        result = solve_cvxpy(qp, data, payout, pricing)
    elif route == "highspy":
        highspy = importlib.import_module("highspy")
        result = solve_highs(qp, highspy, highspy.Highs, loaded=load_data)
    elif route == "scipy_highs_private":
        result = solve_highs(qp, scipy_highs, scipy_highs._Highs, loaded=load_data)
    elif route == "trust_constr":
        result = solve_trust_constr(qp)
    elif route == "slsqp":
        result = solve_slsqp(qp)
    elif route == "lsq_linear":
        result = solve_lsq_linear(qp)
    else:
        raise ValueError(f"unknown route {route!r}")
    seconds = time.perf_counter() - start
    theta = result.pop("theta")
    scale_mb = 1024.0**2 if platform.system() == "Darwin" else 1024.0
    return {
        "route": route,
        "n_units": n_units,
        "n_events": n_events,
        "n_levels": int(qp.ub.size),
        "n_outcomes": int(qp.b.size),
        "budget": budget,
        "pricing": "cost of capital" if loaded else "pure premium",
        "objective": qp.objective(theta),
        "violation": qp.violation(theta),
        "seconds": seconds,
        "peak_rss_mb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / scale_mb,
        "scipy": scipy.__version__,
        **result,
    }


def main() -> None:
    """Run every route on every size, each in a process of its own."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--one", nargs=3, metavar=("ROUTE", "UNITS", "EVENTS"))
    parser.add_argument("--loaded", action="store_true")
    parser.add_argument("--budget", type=float, default=BUDGET)
    parser.add_argument("--timeout", type=float, default=900.0)
    args = parser.parse_args()
    if args.one:
        row = run_one(
            args.one[0],
            int(args.one[1]),
            int(args.one[2]),
            loaded=args.loaded,
            budget=args.budget,
        )
        print(json.dumps(row))
        return
    plan = [(route, *size, False) for size in SIZES for route in ROUTES]
    plan += [("cvxpy", 67, 10_000, True), ("highspy", 67, 10_000, True)]
    rows: list[dict[str, Any]] = []
    for route, n_units, n_events, loaded in plan:
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--one",
            route,
            str(n_units),
            str(n_events),
            "--budget",
            str(args.budget),
        ]
        if loaded:
            command.append("--loaded")
        label = {"route": route, "n_units": n_units, "n_events": n_events}
        if loaded:
            label["pricing"] = "cost of capital"
        try:
            done = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            row = {**label, "timed_out_after_seconds": args.timeout}
        else:
            if done.returncode != 0:
                row = {**label, "error": done.stderr[-800:]}
            else:
                row = json.loads(done.stdout.strip().splitlines()[-1])
        print(json.dumps(row), flush=True)
        rows.append(row)
    for row in rows:
        reference = [
            r
            for r in rows
            if r["route"] == "cvxpy"
            and r["n_units"] == row["n_units"]
            and r["n_events"] == row["n_events"]
            and r.get("pricing") == row.get("pricing")
        ]
        if "objective" in row and reference and "objective" in reference[0]:
            row["relative_gap_to_cvxpy"] = (
                row["objective"] - reference[0]["objective"]
            ) / reference[0]["objective"]
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(rows, indent=1) + "\n")


if __name__ == "__main__":
    main()
