"""Walking skeleton: the ADR 0002 interfaces compose end to end (MAR-61).

Trivial implementations of every component interface are wired together on
the three-event toy EventSet, following the assembly recipe that
``problem.build_problems`` implements (ADR 0002): sample -> measure -> scope
-> context -> objective, premium and constraints -> cvxpy problem -> solve ->
SolveResult -> evaluation on another sample -> result-store records.

The doubles live here, not in the library, so this test keeps passing while
the real components replace the stubs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar, cast

import cvxpy as cp
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from numpy.typing import ArrayLike, NDArray

import parametric_insurance_design as pid
from parametric_insurance_design import records
from parametric_insurance_design.basis import Basis, OutcomeMeasure, outcome_measure
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    SUCCESS_STATUSES,
    Constraint,
    DesignProblem,
    Entity,
    Objective,
    ObjectiveTerm,
    PayoutStructure,
    Pricing,
    ProblemContext,
    ProblemSpec,
    Sample,
    Scope,
    SolverAttempt,
    SolveResult,
    SolveStatus,
    Term,
)
from parametric_insurance_design.problem import BuiltProblem

# --------------------------------------------------------------------------
# Trivial implementations
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ToyStep(PayoutStructure):
    """Step payout on fixed edges; out-of-range values clip into end bins."""

    name: ClassVar[str] = "toy_step"
    edges: tuple[float, ...] = (20.0, 40.0, 60.0)

    @property
    def n_params(self) -> int:
        return len(self.edges) - 1

    def parameter_bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        e = np.asarray(self.edges)
        return e[:-1], e[1:]

    def basis_matrix(self, index: ArrayLike) -> NDArray[np.float64]:
        x = np.asarray(index, dtype=np.float64)
        e = np.asarray(self.edges)
        k = np.searchsorted(e, np.clip(x, e[0], e[-1] - 1e-12), side="right") - 1
        m = np.zeros((x.shape[0], self.n_params))
        m[np.arange(x.shape[0]), k] = 1.0
        return m

    def constraints(
        self, theta: cp.Variable, cap: NDArray[np.float64]
    ) -> tuple[cp.Constraint, ...]:
        return (
            theta >= 0,
            cp.diff(theta, axis=1) >= 0,
            theta <= np.repeat(cap[:, None], self.n_params, axis=1),
        )

    def evaluate(self, index: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        xi = np.asarray(index, dtype=np.float64)
        th = np.asarray(theta, dtype=np.float64)
        return np.column_stack(
            [self.basis_matrix(xi[:, j]) @ th[j] for j in range(xi.shape[1])]
        )


@dataclass(frozen=True)
class ToyPortfolio(Scope):
    """One design problem; one entity per location; point index."""

    name: ClassVar[str] = "toy_portfolio"

    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        entities = tuple(Entity(loc, (loc,)) for loc in eventset.location_ids)
        return (ProblemSpec("portfolio", entities),)

    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        cols = [eventset.location_ids.index(e.location_ids[0]) for e in spec.entities]
        return DesignProblem(
            spec=spec, index=eventset.index[:, cols], entity_loss=eventset.loss[:, cols]
        )


@dataclass(frozen=True)
class ToyExpectedUncovered(Objective):
    """E[(L - pi)^+], aggregated with the measure."""

    name: ClassVar[str] = "toy_expected_uncovered"

    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        uncovered = cp.pos(ctx.loss - ctx.payout)
        per_outcome = ctx.measure.aggregate_expression(uncovered)
        return ObjectiveTerm(
            expression=ctx.measure.probability @ per_outcome,
            per_outcome=per_outcome,
            components={"expected_uncovered": ctx.measure.probability @ per_outcome},
        )


@dataclass(frozen=True)
class ToyPure(Pricing):
    """Premium = expected payout."""

    name: ClassVar[str] = "toy_pure"

    def premium(self, ctx: ProblemContext) -> Term:
        return Term(
            expression=ctx.measure.probability
            @ ctx.measure.aggregate_expression(ctx.payout)
        )

    def premium_value(self, payout: ArrayLike, measure: OutcomeMeasure) -> float:
        return measure.expectation(payout)


@dataclass(frozen=True)
class ToyBudget(Constraint):
    """Premium <= loading * E[L]."""

    name: ClassVar[str] = "toy_budget"
    loading: float

    def build(self, ctx: ProblemContext, premium: Term) -> tuple[cp.Constraint, ...]:
        return (premium.expression <= self.loading * ctx.expected_loss,)


# --------------------------------------------------------------------------
# The ADR 0002 assembly recipe (what problem.py and solve.py implement)
# --------------------------------------------------------------------------


def toy_build_context(
    problem: DesignProblem, payout: PayoutStructure, measure: OutcomeMeasure
) -> ProblemContext:
    scale = float(problem.loss.max()) if problem.loss.max() > 1e-6 else 1.0
    theta = cp.Variable((problem.n_entities, payout.n_params))
    columns = [
        payout.basis_matrix(problem.index[:, j]) @ theta[j]
        for j in range(problem.n_entities)
    ]
    entity_payout = cp.vstack(columns).T
    return ProblemContext(
        problem=problem,
        payout_structure=payout,
        measure=measure,
        scale=scale,
        theta=theta,
        entity_payout=entity_payout,
        payout=cast(cp.Expression, cp.sum(entity_payout, axis=1)),
        loss=problem.loss / scale,
        entity_loss=problem.entity_loss / scale,
        cap=problem.entity_loss.max(axis=0) / scale,
    )


def toy_calibrate(
    eventset: EventSet,
    scope: Scope,
    payout: PayoutStructure,
    objective: Objective,
    pricing: Pricing,
    constraints: tuple[Constraint, ...],
    *,
    basis: Basis,
    sample: Sample | None = None,
) -> list[SolveResult]:
    sample = sample if sample is not None else Sample.full(eventset)
    data = sample.select(eventset)
    measure = outcome_measure(data, basis, years=sample.years)
    results = []
    for spec in scope.partition(data):
        start = time.perf_counter()
        ctx = toy_build_context(scope.materialise(data, spec), payout, measure)
        term = objective.build(ctx)
        premium = pricing.premium(ctx)
        cons = [
            *payout.constraints(ctx.theta, ctx.cap),
            *term.constraints,
            *premium.constraints,
            *(c for con in constraints for c in con.build(ctx, premium)),
        ]
        built = BuiltProblem(
            context=ctx,
            objective=term,
            premium=premium,
            problem=cp.Problem(cp.Minimize(term.expression), cons),
            build_seconds=time.perf_counter() - start,
        )
        results.append(toy_solve(built))
    return results


def value_of(expression: cp.Expression) -> float:
    value = expression.value
    assert value is not None
    return float(value)


def toy_solve(built: BuiltProblem) -> SolveResult:
    ctx, term, premium, problem = (
        built.context,
        built.objective,
        built.premium,
        built.problem,
    )
    problem.solve(solver=cp.CLARABEL)
    status = SolveStatus(problem.status)
    assert status in SUCCESS_STATUSES
    theta = ctx.theta.value
    assert theta is not None
    attempt = SolverAttempt("CLARABEL", status, problem.solver_stats.solve_time or 0.0)
    unscale = ctx.scale**term.homogeneity
    return SolveResult(
        spec=built.spec,
        payout_structure=ctx.payout_structure,
        theta=theta * ctx.scale,
        status=status,
        objective_value=value_of(term.expression) * unscale,
        premium=value_of(premium.expression) * ctx.scale,
        scale=ctx.scale,
        solver="CLARABEL",
        attempts=(attempt,),
        build_seconds=built.build_seconds,
        solve_seconds=attempt.seconds,
        diagnostics={k: value_of(v) * unscale for k, v in term.components.items()},
    )


def expected_uncovered(
    eventset: EventSet, scope: Scope, result: SolveResult, sample: Sample
) -> float:
    """Evaluate a result on a sample through the numpy side of the interfaces."""
    data = sample.select(eventset)
    measure = outcome_measure(data, Basis.EVENT_CONDITIONAL, years=sample.years)
    problem = scope.materialise(data, result.spec)
    payout = result.payouts(problem).sum(axis=1)
    return measure.expectation(np.maximum(problem.loss - payout, 0.0))


def calibrate(eventset: EventSet, loading: float) -> list[SolveResult]:
    return toy_calibrate(
        eventset,
        ToyPortfolio(),
        ToyStep(),
        ToyExpectedUncovered(),
        ToyPure(),
        (ToyBudget(loading),),
        basis=Basis.EVENT_CONDITIONAL,
    )


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

# Toy portfolio loss is L = (1, 6, 16), so E[L] = 23/3. Events 1 and 2 fall in
# bin 0 for both entities, event 3 in bin 1.


def test_slack_budget_covers_every_loss(toy_eventset: EventSet) -> None:
    (result,) = calibrate(toy_eventset, loading=2.0)
    assert result.problem_id == "portfolio"
    assert result.entity_ids == ("A", "B")
    assert result.theta.shape == (2, 2)
    assert result.objective_value == pytest.approx(0.0, abs=1e-6)
    assert result.premium <= 2.0 * 23 / 3 + 1e-6


def test_zero_budget_pays_nothing(toy_eventset: EventSet) -> None:
    (result,) = calibrate(toy_eventset, loading=0.0)
    np.testing.assert_allclose(result.theta, 0.0, atol=1e-6)
    assert result.objective_value == pytest.approx(23 / 3, rel=1e-6)


def test_binding_budget_matches_hand_solution(toy_eventset: EventSet) -> None:
    # With 2s + t <= 23 (s: bin-0 payout, t: bin-1 payout), the optimum covers
    # event 3 fully (t = 16) and spends the rest on bin 0 (s = 3.5), leaving
    # E[U] = (6 - 3.5) / 3.
    (result,) = calibrate(toy_eventset, loading=1.0)
    assert result.objective_value == pytest.approx(2.5 / 3, rel=1e-5)
    assert result.premium == pytest.approx(23 / 3, rel=1e-5)
    levels = result.theta.sum(axis=0)
    np.testing.assert_allclose(levels, [3.5, 16.0], rtol=1e-5)
    # Payout-family constraints hold in loss units.
    assert np.all(result.theta >= -1e-7)
    assert np.all(np.diff(result.theta, axis=1) >= -1e-7)
    assert np.all(result.theta <= toy_eventset.loss.max(axis=0)[:, None] + 1e-6)


def test_cvxpy_and_numpy_paths_agree(toy_eventset: EventSet) -> None:
    # The objective built from cvxpy expressions equals the KPI recomputed
    # from SolveResult.payouts with numpy, in loss units.
    (result,) = calibrate(toy_eventset, loading=1.0)
    full = Sample.full(toy_eventset)
    value = expected_uncovered(toy_eventset, ToyPortfolio(), result, full)
    assert value == pytest.approx(result.objective_value, rel=1e-6)
    assert result.diagnostics["expected_uncovered"] == pytest.approx(
        result.objective_value, rel=1e-6
    )
    payout = result.payouts(ToyPortfolio().materialise(toy_eventset, result.spec))
    measure = outcome_measure(toy_eventset, Basis.EVENT_CONDITIONAL)
    assert ToyPure().premium_value(payout.sum(axis=1), measure) == pytest.approx(
        result.premium, rel=1e-6
    )


def test_calibrate_on_train_evaluate_on_test(toy_eventset: EventSet) -> None:
    train = Sample("train", np.array([True, True, False]), np.array([0, 1]))
    test = Sample("test", np.array([False, False, True]), np.array([2]))
    scope = ToyPortfolio()
    (result,) = toy_calibrate(
        toy_eventset,
        scope,
        ToyStep(),
        ToyExpectedUncovered(),
        ToyPure(),
        (ToyBudget(10.0),),
        basis=Basis.EVENT_CONDITIONAL,
        sample=train,
    )
    # In sample: both training events fall in bin 0 and are covered.
    assert result.objective_value == pytest.approx(0.0, abs=1e-6)
    assert expected_uncovered(toy_eventset, scope, result, train) == pytest.approx(
        0.0, abs=1e-6
    )
    # Out of sample: bin 1 was never seen in training, so the spec reused on
    # the test sample pays whatever the optimiser left there (>= bin 0 level).
    oos = expected_uncovered(toy_eventset, scope, result, test)
    assert 0.0 <= oos <= 16.0 + 1e-6


def test_results_fill_the_record_tables(toy_eventset: EventSet, tmp_path: Path) -> None:
    (result,) = calibrate(toy_eventset, loading=1.0)
    run_id = "toy-run"
    lower, upper = result.payout_structure.parameter_bounds()
    tables = {
        "runs": records.RUNS.from_rows(
            [
                {
                    "run_id": run_id,
                    "problem_id": result.problem_id,
                    "config_hash": "cfg",
                    "source": "single_run",
                    "scope": ToyPortfolio.name,
                    "objective": ToyExpectedUncovered.name,
                    "pricing": ToyPure.name,
                    "payout": ToyStep.name,
                    "basis": Basis.EVENT_CONDITIONAL.value,
                    "calibration_split": records.Split.FULL.value,
                    "fold": 0,
                    "parameters": json.dumps({"loading": 1.0}, sort_keys=True),
                    "status": result.status.value,
                    "solver": result.solver,
                    "objective_value": result.objective_value,
                    "premium": result.premium,
                    "build_seconds": result.build_seconds,
                    "solve_seconds": result.solve_seconds,
                    "error_type": None,
                    "error_message": None,
                    "eventset_checksum": None,
                    "package_version": pid.__version__,
                    "created_at": datetime.now(UTC),
                }
            ]
        ),
        "entities": records.ENTITIES.from_rows(
            {
                "run_id": run_id,
                "problem_id": result.problem_id,
                "entity_id": entity.entity_id,
                "location_id": loc,
            }
            for entity in result.spec.entities
            for loc in entity.location_ids
        ),
        "payouts": records.PAYOUTS.from_rows(
            {
                "run_id": run_id,
                "problem_id": result.problem_id,
                "entity_id": entity_id,
                "param_index": k,
                "lower": float(lower[k]),
                "upper": float(upper[k]),
                "value": float(result.theta[j, k]),
            }
            for j, entity_id in enumerate(result.entity_ids)
            for k in range(result.payout_structure.n_params)
        ),
        "kpis": records.KPIS.from_rows(
            [
                {
                    "run_id": run_id,
                    "problem_id": result.problem_id,
                    "eval_split": records.Split.FULL.value,
                    "fold": 0,
                    "basis": Basis.EVENT_CONDITIONAL.value,
                    "level": records.KpiLevel.PROBLEM.value,
                    "subject_id": result.problem_id,
                    "kpi": records.KpiName.EXPECTED_UNCOVERED.value,
                    "beta": None,
                    "value": result.objective_value,
                    "ci_low": None,
                    "ci_high": None,
                    "ci_level": None,
                    "n_bootstrap": None,
                }
            ]
        ),
    }
    assert len(tables["payouts"]) == 4
    assert len(tables["entities"]) == 2
    for name, frame in tables.items():
        schema = records.TABLES[name]
        path = tmp_path / f"{name}.parquet"
        pq.write_table(
            pa.Table.from_pandas(
                frame, schema=schema.arrow_schema(), preserve_index=False
            ),
            path,
        )
        back = schema.validate(pq.read_table(path).to_pandas())
        assert back.equals(frame), name
