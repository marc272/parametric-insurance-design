"""Tests for ``pid.design`` (MAR-184, ADR 0004 Q2 option 2D).

``design`` is a plain composition: ``build_problems``, then ``solve(b,
policy)`` for each built problem. Three groups:

- The composition itself, with the two functions replaced by recorders: what
  each receives and what ``design`` returns.
- The same results as the low-level path, compared field by field: on the
  toy EventSet (``conftest.py``) with every keyword set, and on the parity
  fixture (``parity/tests/data/thesis_eventset``, MAR-9) for every scope x
  objective (MAR-184 acceptance).
- Errors pass through, and the docstring example runs.
"""

from __future__ import annotations

import doctest
import inspect
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, NoReturn

import cvxpy as cp
import numpy as np
import pytest

import parametric_insurance_design as pid
from parametric_insurance_design import workflow
from parametric_insurance_design.basis import Basis
from parametric_insurance_design.clustering import ThesisWardClustering
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import (
    InfeasibleError,
    InputMismatchError,
    SolveError,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Constraint,
    Objective,
    Pricing,
    ProblemContext,
    Sample,
    Scope,
    SolveResult,
    SolveStatus,
    Term,
)
from parametric_insurance_design.objectives import MSE, ExpectedUncovered, WeightedCVaR
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio
from parametric_insurance_design.solve import (
    DEFAULT_POLICY,
    THESIS_POLICY,
    SolverPolicy,
    solve,
)
from parametric_insurance_design.splits import holdout

TOY_PAYOUT = StepPayout(attachment=20.0, limit=60.0, n_bins=2)
TIMINGS = frozenset({"solver_solve_time", "solver_setup_time"})
"""Diagnostics that are wall times, so differ between two solves."""


@dataclass(frozen=True)
class MinimumPremium(Constraint):
    """Constraint double: premium >= loading * E[L] (infeasible with Budget)."""

    name: ClassVar[str] = "minimum_premium"
    loading: float

    def build(self, ctx: ProblemContext, premium: Term) -> tuple[cp.Constraint, ...]:
        return (premium.expression >= self.loading * ctx.expected_loss,)


def low_level(
    eventset: EventSet,
    scope: Scope,
    payout: StepPayout,
    objective: Objective,
    pricing: Pricing,
    constraints: Sequence[Constraint],
    *,
    basis: Basis,
    sample: Sample | None = None,
    policy: SolverPolicy = DEFAULT_POLICY,
) -> tuple[SolveResult, ...]:
    """The low-level path that ``design`` composes."""
    built = build_problems(
        eventset,
        scope,
        payout,
        objective,
        pricing,
        constraints,
        basis=basis,
        sample=sample,
    )
    return tuple(solve(b, policy) for b in built)


def assert_same_results(
    got: tuple[SolveResult, ...], want: tuple[SolveResult, ...]
) -> None:
    """Every field equal, bit for bit, except the wall times."""
    assert isinstance(got, tuple)
    assert len(got) == len(want)
    for g, w in zip(got, want, strict=True):
        assert g.spec == w.spec
        assert g.payout_structure == w.payout_structure
        np.testing.assert_array_equal(g.theta, w.theta)
        assert g.status is w.status
        assert g.objective_value == w.objective_value
        assert g.premium == w.premium
        assert g.scale == w.scale
        assert g.solver == w.solver
        assert [(a.solver, a.status, a.message) for a in g.attempts] == [
            (a.solver, a.status, a.message) for a in w.attempts
        ]
        assert g.diagnostics.keys() == w.diagnostics.keys()
        for key in g.diagnostics.keys() - TIMINGS:
            assert g.diagnostics[key] == w.diagnostics[key], key


# -- the composition ---------------------------------------------------------


def test_the_top_level_design_is_the_workflow_function() -> None:
    assert pid.design is workflow.design


def test_the_signature() -> None:
    parameters = inspect.signature(workflow.design).parameters
    positional = [n for n, p in parameters.items() if p.kind is p.POSITIONAL_OR_KEYWORD]
    assert positional == ["eventset", "scope", "payout", "objective"]
    keyword_only = {n: p for n, p in parameters.items() if p.kind is p.KEYWORD_ONLY}
    assert list(keyword_only) == [
        "basis",
        "pricing",
        "constraints",
        "sample",
        "policy",
    ]
    assert keyword_only["basis"].default is inspect.Parameter.empty
    assert keyword_only["pricing"].default == PurePremium()
    assert keyword_only["constraints"].default == ()
    assert keyword_only["sample"].default is None
    assert keyword_only["policy"].default is DEFAULT_POLICY


def test_basis_is_required_and_keyword_only(toy_eventset: EventSet) -> None:
    args = (toy_eventset, Portfolio(), TOY_PAYOUT, ExpectedUncovered())
    with pytest.raises(TypeError, match="basis"):
        pid.design(*args)  # pyright: ignore[reportCallIssue]
    with pytest.raises(TypeError):
        pid.design(*args, Basis.EVENT)  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize("keywords", ["defaults", "all"])
def test_design_builds_once_then_solves_each_problem_with_the_policy(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch, keywords: str
) -> None:
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    built = (object(), object(), object())
    results = (object(), object(), object())

    def record_build(*args: Any, **kwargs: Any) -> tuple[object, ...]:  # noqa: ANN401
        calls.append(("build_problems", args, kwargs))
        return built

    def record_solve(*args: Any, **kwargs: Any) -> object:  # noqa: ANN401
        calls.append(("solve", args, kwargs))
        return results[built.index(args[0])]

    monkeypatch.setattr(workflow, "build_problems", record_build)
    monkeypatch.setattr(workflow, "solve", record_solve)
    scope, objective = Individual(), WeightedCVaR(alpha=0.9, beta=0.5)
    if keywords == "defaults":
        pricing, constraints, sample, policy = PurePremium(), (), None, DEFAULT_POLICY
        got = pid.design(toy_eventset, scope, TOY_PAYOUT, objective, basis=Basis.ANNUAL)
    else:
        pricing = CostOfCapitalLoad(rate=0.1, q=0.5)
        constraints = (Budget(1.5),)
        sample, _ = holdout(toy_eventset)
        policy = THESIS_POLICY
        got = pid.design(
            toy_eventset,
            scope,
            TOY_PAYOUT,
            objective,
            basis=Basis.ANNUAL,
            pricing=pricing,
            constraints=constraints,
            sample=sample,
            policy=policy,
        )
    assert got == results  # a tuple, in the order of the built problems
    build, *solves = calls
    assert build[0] == "build_problems"
    args, kwargs = build[1], build[2]
    assert args[:4] == (toy_eventset, scope, TOY_PAYOUT, objective)
    assert args[4] == pricing
    assert tuple(args[5]) == constraints
    assert kwargs == {"basis": Basis.ANNUAL, "sample": sample}
    # The pricing reaches solve only through the built problem (MAR-171).
    assert solves == [("solve", (b, policy), {}) for b in built]
    assert all(s[1][1] is policy for s in solves)


def test_a_build_error_comes_before_any_solve(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("design must not solve after a build error")

    monkeypatch.setattr(workflow, "solve", refuse)
    # A sample of another EventSet: its mask has one row too many.
    sample = Sample(
        name="train",
        rows=np.ones(toy_eventset.n_rows + 1, dtype=bool),
        years=np.arange(toy_eventset.metadata.n_years),
    )
    with pytest.raises(InputMismatchError):
        pid.design(
            toy_eventset,
            Individual(),
            TOY_PAYOUT,
            ExpectedUncovered(),
            basis=Basis.ANNUAL,
            sample=sample,
        )


def test_a_failed_solve_raises_with_its_problem_id(toy_eventset: EventSet) -> None:
    with pytest.raises(SolveError) as info:
        pid.design(
            toy_eventset,
            Individual(),
            TOY_PAYOUT,
            ExpectedUncovered(),
            basis=Basis.EVENT_CONDITIONAL,
            constraints=(Budget(1.0), MinimumPremium(2.0)),
        )
    assert isinstance(info.value, InfeasibleError)
    assert info.value.problem_id == "A"  # the first problem of the scope
    assert info.value.status is SolveStatus.INFEASIBLE


# -- the same results as the low-level path ----------------------------------


@pytest.mark.parametrize("scope", [Individual(), Portfolio()], ids=["ind", "port"])
@pytest.mark.parametrize("basis", list(Basis), ids=lambda b: b.value)
def test_design_equals_the_low_level_path_on_the_toy(
    toy_eventset: EventSet, scope: Scope, basis: Basis
) -> None:
    pricing = CostOfCapitalLoad(rate=0.1, q=0.5)
    constraints = (Budget(1.5),)
    train, _ = holdout(toy_eventset)
    for sample, policy in [(None, DEFAULT_POLICY), (train, THESIS_POLICY)]:
        got = pid.design(
            toy_eventset,
            scope,
            TOY_PAYOUT,
            ExpectedUncovered(),
            basis=basis,
            pricing=pricing,
            constraints=constraints,
            sample=sample,
            policy=policy,
        )
        want = low_level(
            toy_eventset,
            scope,
            TOY_PAYOUT,
            ExpectedUncovered(),
            pricing,
            constraints,
            basis=basis,
            sample=sample,
            policy=policy,
        )
        assert [r.problem_id for r in got] == (
            ["A", "B"] if isinstance(scope, Individual) else ["portfolio"]
        )
        assert_same_results(got, want)


def test_the_pricing_is_given_once(toy_eventset: EventSet) -> None:
    # The loaded premium of each result is the exact premium of its payout
    # (MAR-171), not the Rockafellar-Uryasev bound of the premium term.
    pricing = CostOfCapitalLoad(rate=0.5, q=0.5)
    (result,) = pid.design(
        toy_eventset,
        Portfolio(),
        TOY_PAYOUT,
        ExpectedUncovered(),
        basis=Basis.ANNUAL,
        pricing=pricing,
        constraints=(Budget(1.0),),
    )
    (built,) = build_problems(
        toy_eventset,
        Portfolio(),
        TOY_PAYOUT,
        ExpectedUncovered(),
        pricing,
        (Budget(1.0),),
        basis=Basis.ANNUAL,
    )
    # premium_value of the realised objective-level payout, summed over the
    # entities as solve and evaluate.kpis sum them (test_solve_premium.py).
    ctx = built.context
    entity = ctx.payout_structure.evaluate(ctx.problem.index, result.theta)
    payout = np.vstack(list(entity.T)).sum(axis=0)
    assert result.premium == pricing.premium_value(payout, ctx.measure)


REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
needs_fixture = pytest.mark.skipif(
    not PARITY_EVENTSET.is_dir(),
    reason="the parity fixture is only in a repository checkout",
)

# The thesis default configuration (as in test_solve.py), without the noise
# layer, so the nine combinations solve in seconds.
ATTACHMENT, LIMIT, N_BINS = 20.0, 70.0, 15
SCOPES: dict[str, Scope] = {
    "individual": Individual(),
    "portfolio": Portfolio(),
    "cluster": Cluster(ThesisWardClustering(beta_tail=0.9), 3),
}
OBJECTIVES: dict[str, Objective] = {
    "mse": MSE(),
    "expected_uncovered": ExpectedUncovered(),
    "weighted_cvar": WeightedCVaR(alpha=0.9, beta=0.95),
}
N_PROBLEMS = {"individual": 9, "portfolio": 1, "cluster": 1}


@pytest.fixture(scope="module")
def fixture_data() -> EventSet:
    """The parity fixture, filtered at the attachment (thesis: 20 m/s)."""
    return EventSet.from_parquet(PARITY_EVENTSET).filter_threshold(ATTACHMENT)


@needs_fixture
@pytest.mark.parametrize("objective", list(OBJECTIVES))
@pytest.mark.parametrize("scope", list(SCOPES))
def test_design_equals_build_problems_then_solve_on_the_fixture(
    fixture_data: EventSet, scope: str, objective: str
) -> None:
    payout = StepPayout(attachment=ATTACHMENT, limit=LIMIT, n_bins=N_BINS)
    constraints = (Budget(1.0),)
    got = pid.design(
        fixture_data,
        SCOPES[scope],
        payout,
        OBJECTIVES[objective],
        basis=Basis.EVENT_CONDITIONAL,
        constraints=constraints,
    )
    want = low_level(
        fixture_data,
        SCOPES[scope],
        payout,
        OBJECTIVES[objective],
        PurePremium(),
        constraints,
        basis=Basis.EVENT_CONDITIONAL,
    )
    assert len(got) == N_PROBLEMS[scope]
    assert_same_results(got, want)


@needs_fixture
def test_the_docstring_example_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(REPO_ROOT)  # the example reads the fixture by its path
    outcome = doctest.testmod(workflow, raise_on_error=True)
    assert outcome.attempted > 0
    assert outcome.failed == 0
