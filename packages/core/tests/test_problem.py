"""Tests for the problem builder (MAR-14, ADR 0002 §3).

The toy EventSet (``conftest.py``) has portfolio loss ``L = (1, 6, 16)`` and
``E[L] = 23/3``. With ``StepPayout(20, 60, 2)`` (edges 20, 40, 60) rows 1 and
2 fall in bin 0 for both locations, row 3 in bin 1, as in the walking
skeleton.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, cast

import cvxpy as cp
import numpy as np
import pytest
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import Basis, OutcomeMeasure, outcome_measure
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import (
    ComponentConfigError,
    EntityMismatchError,
    InputMismatchError,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    DesignProblem,
    Entity,
    Objective,
    ObjectiveTerm,
    ProblemContext,
    ProblemSpec,
    Sample,
)
from parametric_insurance_design.objectives import MSE, ExpectedUncovered
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.problem import (
    MIN_SCALE_LOSS,
    BuiltProblem,
    build_context,
    build_problems,
)
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio

PAYOUT = StepPayout(attachment=20.0, limit=60.0, n_bins=2)
BASIS = Basis.EVENT_CONDITIONAL


@dataclass(frozen=True)
class FixedClusters:
    """Clustering double: a fixed location -> label map."""

    labels: Mapping[str, int]

    def assign(self, eventset: EventSet, n_clusters: int) -> Mapping[str, int]:
        return dict(self.labels)


@dataclass(frozen=True)
class Concave(Objective):
    """Objective double that is not convex: maximises the squared payout."""

    name: ClassVar[str] = "concave"

    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        per_outcome = -cp.square(ctx.payout)
        return ObjectiveTerm(
            expression=ctx.measure.probability @ per_outcome,
            per_outcome=per_outcome,
            homogeneity=2,
        )


@dataclass(frozen=True)
class WrongShapeStep(StepPayout):
    """Payout double whose basis matrix drops a row."""

    def basis_matrix(self, index: ArrayLike) -> NDArray[np.float64]:
        return super().basis_matrix(index)[1:]


def portfolio_problem(eventset: EventSet) -> tuple[DesignProblem, OutcomeMeasure]:
    scope = Portfolio()
    (spec,) = scope.partition(eventset)
    return scope.materialise(eventset, spec), outcome_measure(eventset, BASIS)


def build(
    eventset: EventSet, scope: object = None, **kwargs: object
) -> tuple[BuiltProblem, ...]:
    return build_problems(
        eventset,
        Portfolio() if scope is None else scope,  # type: ignore[arg-type]
        PAYOUT,
        ExpectedUncovered(),
        PurePremium(),
        (Budget(1.0),),
        basis=BASIS,
        **kwargs,  # type: ignore[arg-type]
    )


# -- build_context -------------------------------------------------------------


def test_context_scales_by_the_maximum_loss(toy_eventset: EventSet) -> None:
    problem, measure = portfolio_problem(toy_eventset)
    ctx = build_context(problem, PAYOUT, measure)
    assert ctx.scale == 16.0
    np.testing.assert_allclose(ctx.loss, np.array([1.0, 6.0, 16.0]) / 16)
    np.testing.assert_allclose(ctx.entity_loss, toy_eventset.loss / 16)
    # Cap per entity: its maximum loss (thesis max_loss_per_asset), scaled.
    np.testing.assert_allclose(ctx.cap, np.array([10.0, 6.0]) / 16)
    assert ctx.expected_loss == pytest.approx(23 / 3 / 16)
    assert ctx.theta.shape == (2, 2)
    assert ctx.theta.name() == "theta"


def test_context_payout_expressions_match_evaluate(toy_eventset: EventSet) -> None:
    problem, measure = portfolio_problem(toy_eventset)
    ctx = build_context(problem, PAYOUT, measure)
    theta = np.array([[1.0, 2.0], [3.0, 5.0]])
    ctx.theta.value = theta
    expected = PAYOUT.evaluate(problem.index, theta)
    np.testing.assert_allclose(cast(np.ndarray, ctx.entity_payout.value), expected)
    np.testing.assert_allclose(cast(np.ndarray, ctx.payout.value), expected.sum(axis=1))


def test_single_entity_context_has_a_column_payout(toy_eventset: EventSet) -> None:
    scope = Individual()
    spec = scope.partition(toy_eventset)[1]
    problem = scope.materialise(toy_eventset, spec)
    ctx = build_context(problem, PAYOUT, outcome_measure(toy_eventset, BASIS))
    assert ctx.scale == 6.0
    assert ctx.entity_payout.shape == (3, 1)
    assert ctx.payout.shape == (3,)
    ctx.theta.value = np.array([[2.0, 4.0]])
    np.testing.assert_allclose(cast(np.ndarray, ctx.payout.value), [2.0, 2.0, 4.0])
    np.testing.assert_allclose(
        cast(np.ndarray, ctx.entity_payout.value), [[2.0], [2.0], [4.0]]
    )


def test_tiny_losses_are_not_scaled(toy_eventset: EventSet) -> None:
    problem, measure = portfolio_problem(toy_eventset)
    tiny = DesignProblem(
        spec=problem.spec,
        index=problem.index,
        entity_loss=problem.entity_loss * (MIN_SCALE_LOSS / 100),
    )
    assert build_context(tiny, PAYOUT, measure).scale == 1.0


def test_explicit_scale_and_shared_theta(toy_eventset: EventSet) -> None:
    problem, measure = portfolio_problem(toy_eventset)
    theta = cp.Variable((2, 2))
    ctx = build_context(problem, PAYOUT, measure, scale=4, theta=theta)
    assert ctx.scale == 4.0
    assert ctx.theta is theta
    np.testing.assert_allclose(ctx.loss, np.array([1.0, 6.0, 16.0]) / 4)


@pytest.mark.parametrize("scale", [0.0, -1.0, float("nan"), float("inf"), True, "2"])
def test_invalid_scale_is_refused(toy_eventset: EventSet, scale: object) -> None:
    problem, measure = portfolio_problem(toy_eventset)
    with pytest.raises(InputMismatchError, match="scale"):
        build_context(problem, PAYOUT, measure, scale=scale)  # type: ignore[arg-type]


def test_theta_of_the_wrong_shape_is_refused(toy_eventset: EventSet) -> None:
    problem, measure = portfolio_problem(toy_eventset)
    with pytest.raises(InputMismatchError, match="theta must have shape"):
        build_context(problem, PAYOUT, measure, theta=cp.Variable((2, 3)))


def test_measure_of_other_rows_is_refused(toy_eventset: EventSet) -> None:
    problem, _ = portfolio_problem(toy_eventset)
    measure = OutcomeMeasure.per_row(BASIS, [0.5, 0.5])
    with pytest.raises(InputMismatchError, match="measure covers 2 rows"):
        build_context(problem, PAYOUT, measure)


def test_basis_matrix_of_the_wrong_shape_is_refused(toy_eventset: EventSet) -> None:
    problem, measure = portfolio_problem(toy_eventset)
    payout = WrongShapeStep(attachment=20.0, limit=60.0, n_bins=2)
    with pytest.raises(InputMismatchError, match="basis matrix must have shape"):
        build_context(problem, payout, measure)


# -- build_problems -----------------------------------------------------------


def test_portfolio_builds_one_problem(toy_eventset: EventSet) -> None:
    (built,) = build(toy_eventset)
    assert built.spec.problem_id == "portfolio"
    assert built.spec.entity_ids == ("A", "B")
    assert built.context.scale == 16.0
    assert built.build_seconds > 0
    assert built.problem.is_dcp()
    assert built.objective.homogeneity == 1


def test_individual_builds_one_problem_per_location(toy_eventset: EventSet) -> None:
    built = build(toy_eventset, Individual())
    assert [b.spec.problem_id for b in built] == ["A", "B"]
    # Each problem is scaled by its own maximum loss (thesis, per asset).
    assert [b.context.scale for b in built] == [10.0, 6.0]
    assert [b.context.problem.n_entities for b in built] == [1, 1]


def test_cluster_builds_one_problem_over_clusters(toy_eventset: EventSet) -> None:
    scope = Cluster(FixedClusters({"A": 1, "B": 1}), n_clusters=1)
    (built,) = build(toy_eventset, scope)
    assert built.spec.problem_id == "portfolio"
    assert built.spec.entity_ids == ("C1",)
    np.testing.assert_allclose(built.context.loss, np.array([1.0, 6.0, 16.0]) / 16)


def test_constraints_are_assembled_in_recipe_order(toy_eventset: EventSet) -> None:
    budget = Budget(1.0)
    (built,) = build_problems(
        toy_eventset,
        Portfolio(),
        PAYOUT,
        ExpectedUncovered(),
        PurePremium(),
        (budget, budget),
        basis=BASIS,
    )
    ctx = built.context
    family = PAYOUT.constraints(ctx.theta, ctx.cap)
    cons = built.problem.constraints
    # Payout family (3), objective (0), premium (0), then each extra constraint.
    assert len(cons) == len(family) + 2
    assert [type(c) for c in cons[: len(family)]] == [type(c) for c in family]
    assert all(type(c).__name__ == "Inequality" for c in cons[len(family) :])


@pytest.mark.parametrize(
    "pricing", [PurePremium(), CostOfCapitalLoad(rate=0.1, q=0.9)], ids=repr
)
def test_every_built_problem_carries_its_pricing(
    toy_eventset: EventSet, pricing: PurePremium | CostOfCapitalLoad
) -> None:
    built = build_problems(
        toy_eventset,
        Individual(),
        PAYOUT,
        ExpectedUncovered(),
        pricing,
        (Budget(1.0),),
        basis=BASIS,
    )
    assert len(built) == 2
    # The very object passed in (MAR-171), so solve.solve can price with it.
    assert all(b.pricing is pricing for b in built)


def test_built_problem_pricing_defaults_to_none(toy_eventset: EventSet) -> None:
    (built,) = build(toy_eventset)
    # Assembled by hand from the same parts, without the new field: the
    # constructor of the walking skeleton keeps working (pricing unknown).
    bare = BuiltProblem(
        context=built.context,
        objective=built.objective,
        premium=built.premium,
        problem=built.problem,
        build_seconds=built.build_seconds,
    )
    assert bare.pricing is None
    assert isinstance(built.pricing, PurePremium)


@pytest.mark.parametrize("pricing", ["pure", PurePremium, 1.0])
def test_built_problem_refuses_a_pricing_that_is_not_one(
    toy_eventset: EventSet, pricing: object
) -> None:
    (built,) = build(toy_eventset)
    with pytest.raises(ComponentConfigError, match="pricing must be a Pricing or None"):
        dataclasses.replace(built, pricing=pricing)


def test_mse_is_assembled_as_a_quadratic_objective(toy_eventset: EventSet) -> None:
    (built,) = build_problems(
        toy_eventset, Portfolio(), PAYOUT, MSE(), PurePremium(), basis=BASIS
    )
    assert built.objective.homogeneity == 2
    assert built.problem.is_qp()


def test_specs_are_reused_on_a_sample(toy_eventset: EventSet) -> None:
    train = Sample("train", np.array([True, True, False]), np.array([0, 1]))
    specs = Individual().partition(toy_eventset)
    built = build(toy_eventset, Individual(), sample=train, specs=specs[:1])
    assert [b.spec for b in built] == [specs[0]]
    (only,) = built
    assert only.context.problem.n_rows == 2
    # Scale and cap come from the calibration rows only.
    assert only.context.scale == 4.0
    np.testing.assert_allclose(only.context.measure.probability, [0.5, 0.5])


def test_no_specs_is_refused(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError, match="at least one design problem"):
        build(toy_eventset, specs=())


def test_repeated_problem_ids_are_refused(toy_eventset: EventSet) -> None:
    spec = ProblemSpec("p", (Entity("A", ("A",)),))
    with pytest.raises(EntityMismatchError, match=r"problem ids repeat: \['p'\]"):
        build(toy_eventset, Individual(), specs=(spec, spec))


def test_non_spec_items_are_refused(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError, match="ProblemSpec objects"):
        build(toy_eventset, specs=("portfolio",))


def test_missing_location_is_refused(toy_eventset: EventSet) -> None:
    spec = ProblemSpec("Z", (Entity("Z", ("Z",)),))
    with pytest.raises(EntityMismatchError):
        build(toy_eventset, Individual(), specs=(spec,))


def test_empty_sample_is_refused(toy_eventset: EventSet) -> None:
    empty = Sample("test", np.zeros(3, dtype=bool), np.array([0, 1, 2]))
    with pytest.raises(InputMismatchError, match="without rows"):
        build(toy_eventset, sample=empty)


def test_non_convex_combination_fails_at_build_time(toy_eventset: EventSet) -> None:
    with pytest.raises(ComponentConfigError, match=r"concave .* not a convex \(DCP\)"):
        build_problems(
            toy_eventset,
            Portfolio(),
            PAYOUT,
            Concave(),
            PurePremium(),
            (Budget(1.0),),
            basis=BASIS,
        )
