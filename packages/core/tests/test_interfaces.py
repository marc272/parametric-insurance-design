"""Interface-level tests for the ADR 0002 contracts (MAR-61).

These test the shared types and the module layout, not the components: they
keep passing when the implementing issues replace the stubs.
"""

from __future__ import annotations

import importlib
import inspect
import re
from abc import ABC
from typing import cast

import cvxpy as cp
import numpy as np
import pytest

import parametric_insurance_design as pid
from parametric_insurance_design import errors
from parametric_insurance_design.basis import Basis, OutcomeMeasure
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetError,
    OutOfRangeError,
)
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

# Every SPEC §4.2 module, with experiment.py split into a subpackage (ADR 0002).
MODULES = [
    "eventset",
    "index",
    "payout",
    "scopes",
    "clustering",
    "objectives",
    "pricing",
    "problem",
    "solve",
    "evaluate",
    "splits",
    "robust",
    "noise",
    "experiment",
    "experiment.config",
    "experiment.runner",
    "experiment.store",
    "experiment.sweeps",
    # Added by ADR 0002.
    "interfaces",
    "basis",
    "errors",
    "records",
    "constraints",
    "cli",
]


@pytest.mark.parametrize("name", MODULES)
def test_every_module_imports_and_documents_itself(name: str) -> None:
    module = importlib.import_module(f"parametric_insurance_design.{name}")
    assert module.__doc__
    # A one-line summary first; behaviour, not the program's history (no
    # Linear issue IDs). Ownership lives in ADR 0002's ownership map.
    assert module.__doc__.splitlines()[0].strip()
    assert not re.search(r"\bMAR-\d+", module.__doc__)


# (implementation, interface) pairs fixed by ADR 0002.
IMPLEMENTATIONS = [
    ("payout.StepPayout", PayoutStructure),
    ("scopes.Individual", Scope),
    ("scopes.Portfolio", Scope),
    ("scopes.Cluster", Scope),
    ("objectives.MSE", Objective),
    ("objectives.ExpectedUncovered", Objective),
    ("objectives.WeightedCVaR", Objective),
    ("robust.DistributionallyRobust", Objective),
    ("pricing.PurePremium", Pricing),
    ("pricing.CostOfCapitalLoad", Pricing),
    ("constraints.Budget", Constraint),
]


@pytest.mark.parametrize(("path", "interface"), IMPLEMENTATIONS)
def test_components_implement_their_interface(path: str, interface: type) -> None:
    module_name, cls_name = path.split(".")
    cls = getattr(getattr(pid, module_name), cls_name)
    assert issubclass(cls, interface)
    assert not inspect.isabstract(cls)
    assert isinstance(cls.name, str)
    assert cls.name


def test_component_names_are_unique_per_interface() -> None:
    by_interface: dict[type, list[str]] = {}
    for path, interface in IMPLEMENTATIONS:
        module_name, cls_name = path.split(".")
        cls = getattr(getattr(pid, module_name), cls_name)
        by_interface.setdefault(interface, []).append(cls.name)
    for names in by_interface.values():
        assert len(names) == len(set(names))


@pytest.mark.parametrize(
    "interface", [PayoutStructure, Scope, Objective, Pricing, Constraint]
)
def test_interfaces_are_abstract(interface: type) -> None:
    assert issubclass(interface, ABC)
    assert inspect.isabstract(interface)
    with pytest.raises(TypeError):
        interface()


def test_top_level_reexports() -> None:
    assert pid.EventSet is EventSet
    assert pid.Basis is Basis
    assert pid.SolveResult is SolveResult
    assert pid.Sample is Sample
    assert pid.SolveError is errors.SolveError
    for name in pid.__all__:
        assert hasattr(pid, name), name


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cls", "builtin"),
    [
        (errors.ComponentConfigError, ValueError),
        (errors.UnsupportedBasisError, ValueError),
        (errors.ConfigError, ValueError),
        (errors.InputMismatchError, ValueError),
        (errors.EntityMismatchError, ValueError),
        (errors.SolveError, RuntimeError),
        (errors.InfeasibleError, RuntimeError),
        (errors.UnboundedError, RuntimeError),
        (errors.RecordSchemaError, ValueError),
    ],
)
def test_error_hierarchy(cls: type[Exception], builtin: type[Exception]) -> None:
    assert issubclass(cls, errors.ParametricInsuranceDesignError)
    assert issubclass(cls, builtin)


def test_eventset_errors_stay_value_errors() -> None:
    # ADR 0002 proposes EventSetError also derive from the core base; until
    # that eventset.py amendment lands, it is only a ValueError.
    assert issubclass(EventSetError, ValueError)


def test_solve_error_carries_attempts() -> None:
    attempt = SolverAttempt("CLARABEL", SolveStatus.INFEASIBLE, 0.1, "infeasible")
    err = errors.InfeasibleError(
        "no feasible payout",
        problem_id="portfolio",
        status=SolveStatus.INFEASIBLE,
        attempts=[attempt],
    )
    assert err.problem_id == "portfolio"
    assert err.status is SolveStatus.INFEASIBLE
    assert err.attempts == (attempt,)
    assert "[portfolio]" in str(err)
    assert "infeasible" in str(err)
    rec = errors.RecordSchemaError("bad", table="runs")
    assert rec.table == "runs"
    assert str(rec) == "[runs] bad"


# --------------------------------------------------------------------------
# Samples
# --------------------------------------------------------------------------


def test_full_sample_covers_all_rows_and_years(toy_eventset: EventSet) -> None:
    sample = Sample.full(toy_eventset)
    assert sample.name == "full"
    assert sample.fold == 0
    assert sample.n_selected == 3
    np.testing.assert_array_equal(sample.years, [0, 1, 2])
    assert sample.select(toy_eventset).equals(toy_eventset)
    with pytest.raises(ValueError, match="read-only"):
        sample.rows[0] = False


def test_sample_select_keeps_row_order_and_metadata(toy_eventset: EventSet) -> None:
    sample = Sample("test", np.array([True, False, True]), np.array([2, 0]), fold=2)
    np.testing.assert_array_equal(sample.years, [0, 2])
    data = sample.select(toy_eventset)
    assert data.events["event_id"].tolist() == ["ev1", "ev3"]
    assert data.metadata == toy_eventset.metadata


def test_sample_select_rejects_leakage(toy_eventset: EventSet) -> None:
    sample = Sample("train", np.array([True, True, True]), np.array([0, 1]))
    with pytest.raises(errors.InputMismatchError, match="outside its year set"):
        sample.select(toy_eventset)


def test_sample_select_rejects_wrong_length(toy_eventset: EventSet) -> None:
    sample = Sample("train", np.array([True, True]), np.array([1, 2]))
    with pytest.raises(errors.InputMismatchError, match="2 rows"):
        sample.select(toy_eventset)


def test_full_sample_enforces_year_convention(toy_eventset: EventSet) -> None:
    events = toy_eventset.events.assign(year=[1, 2, 3])
    # Since MAR-82 (ADR 0002 §9 amendment) the EventSet itself rejects years
    # outside [0, n_years).
    with pytest.raises(OutOfRangeError, match="year"):
        EventSet(
            events=events,
            locations=toy_eventset.locations,
            index=toy_eventset.index,
            loss=toy_eventset.loss,
            metadata=toy_eventset.metadata,
        )
    # Sample.full keeps its own guard: bypass validation to reach it.
    object.__setattr__(toy_eventset, "events", events)
    with pytest.raises(errors.InputMismatchError, match="year convention"):
        Sample.full(toy_eventset)


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"name": ""}, "name"),
        ({"rows": np.array([1, 0])}, "boolean"),
        ({"years": np.array([1.0, 2.0])}, "integer"),
        ({"years": np.array([1, 1])}, "unique"),
        ({"fold": -1}, ">= 0"),
        ({"fold": True}, "int"),
    ],
)
def test_sample_validation(kwargs: dict[str, object], match: str) -> None:
    fields: dict[str, object] = {
        "name": "train",
        "rows": np.array([True, False]),
        "years": np.array([1, 2]),
    }
    fields.update(kwargs)
    with pytest.raises(errors.InputMismatchError, match=match):
        Sample(**fields)  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Entities and design problems
# --------------------------------------------------------------------------


def two_entity_spec() -> ProblemSpec:
    return ProblemSpec("portfolio", (Entity("C1", ("A",)), Entity("C2", ("B", "C"))))


def test_problem_spec_accessors() -> None:
    spec = two_entity_spec()
    assert spec.entity_ids == ("C1", "C2")
    assert spec.location_ids == ("A", "B", "C")
    # Lists are accepted at runtime and stored as tuples.
    listed = ProblemSpec("p", [Entity("A", ["A"])])  # type: ignore[arg-type]
    assert listed.entities == (Entity("A", ("A",)),)


@pytest.mark.parametrize(
    "build",
    [
        lambda: Entity("", ("A",)),
        lambda: Entity("A", ()),
        lambda: Entity("A", ("A", "A")),
        lambda: ProblemSpec("", (Entity("A", ("A",)),)),
        lambda: ProblemSpec("p", ()),
        lambda: ProblemSpec("p", (Entity("A", ("A",)), Entity("A", ("B",)))),
        lambda: ProblemSpec("p", (Entity("A", ("A",)), Entity("B", ("A",)))),
    ],
    ids=[
        "empty-entity-id",
        "no-locations",
        "repeated-location",
        "empty-problem-id",
        "no-entities",
        "repeated-entity",
        "overlapping-entities",
    ],
)
def test_entity_validation(build: object) -> None:
    with pytest.raises(errors.EntityMismatchError):
        build()  # type: ignore[operator]


def test_design_problem_sums_entities() -> None:
    problem = DesignProblem(
        spec=two_entity_spec(),
        index=np.array([[1.0, 2.0], [3.0, 4.0]]),
        entity_loss=np.array([[1.0, 2.0], [0.0, 5.0]]),
    )
    assert (problem.n_rows, problem.n_entities) == (2, 2)
    np.testing.assert_array_equal(problem.loss, [3.0, 5.0])


@pytest.mark.parametrize(
    ("index", "loss", "match"),
    [
        (np.ones((2, 3)), np.ones((2, 2)), "index must have shape"),
        (np.ones((2, 2)), np.ones(2), "entity_loss must have shape"),
        (np.ones((2, 2)), np.ones((3, 2)), "differ in shape"),
        (np.full((2, 2), np.nan), np.ones((2, 2)), "finite"),
        (np.ones((2, 2)), -np.ones((2, 2)), ">= 0"),
    ],
)
def test_design_problem_validation(
    index: np.ndarray, loss: np.ndarray, match: str
) -> None:
    with pytest.raises(errors.InputMismatchError, match=match):
        DesignProblem(spec=two_entity_spec(), index=index, entity_loss=loss)


# --------------------------------------------------------------------------
# Context, terms and results (with a minimal payout structure)
# --------------------------------------------------------------------------


class OneParam(PayoutStructure):
    name = "one_param"

    @property
    def n_params(self) -> int:
        return 1

    def parameter_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return np.array([0.0]), np.array([1.0])

    def basis_matrix(self, index: object) -> np.ndarray:
        return np.ones((np.asarray(index).shape[0], 1))

    def constraints(self, theta: cp.Variable, cap: np.ndarray) -> tuple:
        return (theta >= 0,)

    def evaluate(self, index: object, theta: object) -> np.ndarray:
        xi = np.asarray(index, dtype=float)
        return np.ones_like(xi) * np.asarray(theta, dtype=float)[:, 0]


def one_entity_problem() -> DesignProblem:
    return DesignProblem(
        spec=ProblemSpec("A", (Entity("A", ("A",)),)),
        index=np.array([[1.0], [2.0]]),
        entity_loss=np.array([[1.0], [3.0]]),
    )


def make_context(**overrides: object) -> ProblemContext:
    problem = one_entity_problem()
    theta = cp.Variable((1, 1))
    entity_payout = np.ones((2, 1)) @ theta[0][None, :]
    fields: dict[str, object] = {
        "problem": problem,
        "payout_structure": OneParam(),
        "measure": OutcomeMeasure.per_row(Basis.EVENT_CONDITIONAL, [0.5, 0.5]),
        "scale": 3.0,
        "theta": theta,
        "entity_payout": entity_payout,
        "payout": cast(cp.Expression, cp.sum(entity_payout, axis=1)),
        "loss": problem.loss / 3.0,
        "entity_loss": problem.entity_loss / 3.0,
        "cap": np.array([1.0]),
    }
    fields.update(overrides)
    return ProblemContext(**fields)  # type: ignore[arg-type]


def test_context_properties() -> None:
    ctx = make_context()
    assert ctx.basis is Basis.EVENT_CONDITIONAL
    assert ctx.expected_loss == pytest.approx((1 / 3 + 1) / 2)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"theta": cp.Variable((1, 2))}, "theta"),
        ({"loss": np.ones(3)}, "loss"),
        ({"cap": np.ones(2)}, "cap"),
        ({"measure": OutcomeMeasure.per_row(Basis.EVENT, [1.0])}, "measure"),
        ({"scale": 0.0}, "scale"),
    ],
)
def test_context_validation(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(errors.InputMismatchError, match=match):
        make_context(**overrides)


def test_terms() -> None:
    x = cp.Variable(2)
    total = cast(cp.Expression, cp.sum(x))
    term = Term(expression=total, constraints=[x >= 0])  # type: ignore[arg-type]
    assert isinstance(term.constraints, tuple)
    assert len(term.constraints) == 1
    obj = ObjectiveTerm(expression=total, per_outcome=x, homogeneity=2)
    assert isinstance(obj.offset, float)
    assert dict(obj.components) == {}
    with pytest.raises(errors.InputMismatchError, match="scalar"):
        Term(expression=x)
    with pytest.raises(errors.InputMismatchError, match="1-D"):
        ObjectiveTerm(expression=total, per_outcome=total)
    with pytest.raises(errors.InputMismatchError, match="homogeneity"):
        ObjectiveTerm(expression=total, per_outcome=x, homogeneity=3)


def make_result(**overrides: object) -> SolveResult:
    fields: dict[str, object] = {
        "spec": one_entity_problem().spec,
        "payout_structure": OneParam(),
        "theta": [[2.0]],
        "status": "optimal",
        "objective_value": 0.5,
        "premium": 2.0,
        "scale": 3.0,
        "solver": "CLARABEL",
        "attempts": [SolverAttempt("CLARABEL", SolveStatus.OPTIMAL, 0.01)],
        "build_seconds": 0.0,
        "solve_seconds": 0.01,
    }
    fields.update(overrides)
    return SolveResult(**fields)  # type: ignore[arg-type]


def test_solve_result_accessors_and_payouts() -> None:
    result = make_result()
    assert result.status is SolveStatus.OPTIMAL
    assert result.problem_id == "A"
    assert result.entity_ids == ("A",)
    assert isinstance(result.attempts, tuple)
    np.testing.assert_array_equal(result.payouts(one_entity_problem()), [[2.0], [2.0]])
    other = DesignProblem(
        spec=ProblemSpec("B", (Entity("B", ("B",)),)),
        index=np.ones((1, 1)),
        entity_loss=np.ones((1, 1)),
    )
    with pytest.raises(errors.EntityMismatchError):
        result.payouts(other)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"status": "infeasible"}, "success status"),
        ({"theta": [[1.0, 2.0]]}, "shape"),
        ({"theta": [[np.inf]]}, "finite"),
    ],
)
def test_solve_result_validation(overrides: dict[str, object], match: str) -> None:
    with pytest.raises(errors.InputMismatchError, match=match):
        make_result(**overrides)


def test_solve_status_values_match_cvxpy() -> None:
    for status in SolveStatus:
        if status is not SolveStatus.ERROR:
            assert getattr(cp, status.name) == status.value
    assert {SolveStatus.OPTIMAL, SolveStatus.OPTIMAL_INACCURATE} == SUCCESS_STATUSES
