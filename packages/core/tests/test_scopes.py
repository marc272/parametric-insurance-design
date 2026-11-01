"""Tests for the individual, portfolio and cluster scopes (MAR-12).

The separately calibrated cluster scope, ``Cluster(joint=False)``, is
MAR-180: one design problem per cluster, on the cluster's index and loss,
with its own budget.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pandas as pd
import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from parametric_insurance_design import splits
from parametric_insurance_design.basis import Basis, outcome_measure
from parametric_insurance_design.bootstrap import (
    bootstrap_kpis,
    paired_difference,
    resample_years,
)
from parametric_insurance_design.clustering import ThesisWardClustering
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import (
    ComponentConfigError,
    EntityMismatchError,
    InputMismatchError,
)
from parametric_insurance_design.evaluate import kpis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import parse_config
from parametric_insurance_design.experiment.runner import prepare_eventset
from parametric_insurance_design.index import (
    PointIndex,
    ValueWeightedIndex,
    location_columns,
)
from parametric_insurance_design.interfaces import (
    DesignProblem,
    Entity,
    Objective,
    Pricing,
    ProblemSpec,
    Sample,
    Scope,
    SolveResult,
)
from parametric_insurance_design.objectives import MSE, ExpectedUncovered
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.records import ALL_PROBLEMS
from parametric_insurance_design.scopes import (
    CLUSTER_PROBLEM_PREFIX,
    PORTFOLIO_PROBLEM_ID,
    Cluster,
    Individual,
    Portfolio,
    cluster_problem_id,
)
from parametric_insurance_design.solve import DEFAULT_POLICY, solve

from .test_design_properties import (
    BASES,
    PROPERTY_SETTINGS,
    Measure,
    OneClusterPerLocation,
    budgets,
    designs,
    homogeneity,
    layouts,
    objectives,
    pricings,
    solver_tol,
    step_payouts,
    tail_factor,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class FixedClustering:
    """Test double: returns a fixed assignment."""

    labels: Mapping[str, int] = field(default_factory=dict)

    def assign(self, eventset: EventSet, n_clusters: int) -> Mapping[str, int]:
        return self.labels


def three_locations(base: EventSet) -> EventSet:
    """The toy EventSet plus a third location C (value 50)."""
    locations = base.locations.copy()
    locations.loc[len(locations)] = {
        "location_id": "C",
        "lat": 27.0,
        "lon": -82.0,
        "value": 50.0,
        "name": "Asset C",
    }
    return EventSet(
        events=base.events,
        locations=locations,
        index=np.column_stack([base.index, [20.0, 40.0, 60.0]]),
        loss=np.column_stack([base.loss, [0.0, 3.0, 8.0]]),
        metadata=base.metadata,
    )


def drop_location(base: EventSet, location_id: str) -> EventSet:
    keep = [i for i, loc in enumerate(base.location_ids) if loc != location_id]
    return EventSet(
        events=base.events,
        locations=base.locations.iloc[keep],
        index=base.index[:, keep],
        loss=base.loss[:, keep],
        metadata=base.metadata,
    )


def test_scope_names_and_types() -> None:
    cluster = Cluster(strategy=ThesisWardClustering(0.9), n_clusters=2)
    assert (Individual.name, Portfolio.name, Cluster.name) == (
        "individual",
        "portfolio",
        "cluster",
    )
    for scope in (Individual(), Portfolio(), cluster):
        assert isinstance(scope, Scope)
    assert isinstance(Individual().index, PointIndex)
    assert isinstance(Portfolio().index, PointIndex)
    assert isinstance(cluster.index, ValueWeightedIndex)


@pytest.mark.parametrize("scope_cls", [Individual, Portfolio])
def test_scopes_reject_a_non_index(scope_cls: type[Scope]) -> None:
    with pytest.raises(ComponentConfigError, match="EntityIndex"):
        scope_cls(index="point")  # type: ignore[call-arg]


# --------------------------------------------------------------------------
# Individual
# --------------------------------------------------------------------------


def test_individual_partition_is_one_problem_per_location(
    toy_eventset: EventSet,
) -> None:
    specs = Individual().partition(toy_eventset)
    assert specs == (
        ProblemSpec("A", (Entity("A", ("A",)),)),
        ProblemSpec("B", (Entity("B", ("B",)),)),
    )


def test_individual_materialise_takes_the_locations_columns(
    toy_eventset: EventSet,
) -> None:
    scope = Individual()
    spec_a, spec_b = scope.partition(toy_eventset)
    problem = scope.materialise(toy_eventset, spec_b)
    np.testing.assert_array_equal(problem.index[:, 0], toy_eventset.index[:, 1])
    np.testing.assert_array_equal(problem.entity_loss[:, 0], toy_eventset.loss[:, 1])
    np.testing.assert_array_equal(problem.loss, toy_eventset.loss[:, 1])
    assert problem.spec is spec_b
    assert scope.materialise(toy_eventset, spec_a).n_entities == 1


def test_individual_materialise_reuses_a_spec_on_other_rows(
    toy_eventset: EventSet,
) -> None:
    # Partition on calibration data, materialise on a test sample.
    scope = Individual()
    spec = scope.partition(toy_eventset)[0]
    test = toy_eventset.filter_threshold(30.0)
    problem = scope.materialise(test, spec)
    assert problem.n_rows == 2
    np.testing.assert_array_equal(problem.index[:, 0], [30.0, 50.0])


def test_individual_materialise_rejects_joint_specs(toy_eventset: EventSet) -> None:
    (spec,) = Portfolio().partition(toy_eventset)
    with pytest.raises(EntityMismatchError, match="individual-scope"):
        Individual().materialise(toy_eventset, spec)
    multi = ProblemSpec("A", (Entity("A", ("A", "B")),))
    with pytest.raises(EntityMismatchError, match="individual-scope"):
        Individual().materialise(toy_eventset, multi)


def test_individual_materialise_rejects_missing_locations(
    toy_eventset: EventSet,
) -> None:
    spec = ProblemSpec("Z", (Entity("Z", ("Z",)),))
    with pytest.raises(EntityMismatchError, match="not in the EventSet"):
        Individual().materialise(toy_eventset, spec)


# --------------------------------------------------------------------------
# Portfolio
# --------------------------------------------------------------------------


def test_portfolio_partition_is_one_problem_with_every_location(
    toy_eventset: EventSet,
) -> None:
    (spec,) = Portfolio().partition(toy_eventset)
    assert spec.problem_id == PORTFOLIO_PROBLEM_ID == "portfolio"
    assert spec.entities == (Entity("A", ("A",)), Entity("B", ("B",)))


def test_portfolio_materialise_sums_the_losses(toy_eventset: EventSet) -> None:
    scope = Portfolio()
    problem = scope.materialise(toy_eventset, scope.partition(toy_eventset)[0])
    np.testing.assert_array_equal(problem.index, toy_eventset.index)
    np.testing.assert_array_equal(problem.entity_loss, toy_eventset.loss)
    np.testing.assert_array_equal(problem.loss, [1.0, 6.0, 16.0])


def test_portfolio_materialise_rejects_multi_location_entities(
    toy_eventset: EventSet,
) -> None:
    spec = ProblemSpec("portfolio", (Entity("C1", ("A", "B")),))
    with pytest.raises(EntityMismatchError, match="one location each"):
        Portfolio().materialise(toy_eventset, spec)


def test_portfolio_materialise_rejects_uncovered_locations(
    toy_eventset: EventSet,
) -> None:
    # A location outside the spec would drop out of the portfolio loss.
    scope = Portfolio()
    (spec,) = scope.partition(toy_eventset)
    with pytest.raises(EntityMismatchError, match=r"not in the spec \['C'\]"):
        scope.materialise(three_locations(toy_eventset), spec)


def test_portfolio_materialise_rejects_missing_locations(
    toy_eventset: EventSet,
) -> None:
    scope = Portfolio()
    (spec,) = scope.partition(toy_eventset)
    with pytest.raises(EntityMismatchError, match=r"not in the EventSet \['B'\]"):
        scope.materialise(drop_location(toy_eventset, "B"), spec)


# --------------------------------------------------------------------------
# Cluster
# --------------------------------------------------------------------------


def test_cluster_partition_numbers_entities_by_label(toy_eventset: EventSet) -> None:
    es = three_locations(toy_eventset)
    scope = Cluster(strategy=FixedClustering({"A": 2, "B": 1, "C": 2}), n_clusters=2)
    (spec,) = scope.partition(es)
    assert spec.problem_id == "portfolio"
    # Entities in label order; locations in EventSet order within a cluster.
    assert spec.entities == (Entity("C1", ("B",)), Entity("C2", ("A", "C")))


def test_cluster_materialise_uses_the_value_weighted_index(
    toy_eventset: EventSet,
) -> None:
    es = three_locations(toy_eventset)
    scope = Cluster(strategy=FixedClustering({"A": 1, "B": 2, "C": 1}), n_clusters=2)
    problem = scope.materialise(es, scope.partition(es)[0])
    # C1 = {A (value 100), C (value 50)}: weights 2/3, 1/3. C2 = {B}.
    np.testing.assert_allclose(
        problem.index[:, 0], (2 * es.index[:, 0] + es.index[:, 2]) / 3, rtol=1e-15
    )
    np.testing.assert_array_equal(problem.index[:, 1], es.index[:, 1])
    np.testing.assert_array_equal(
        problem.entity_loss[:, 0], es.loss[:, 0] + es.loss[:, 2]
    )
    np.testing.assert_array_equal(problem.loss, es.loss.sum(axis=1))


def test_cluster_with_the_thesis_strategy(toy_eventset: EventSet) -> None:
    scope = Cluster(strategy=ThesisWardClustering(beta_tail=0.5), n_clusters=2)
    (spec,) = scope.partition(toy_eventset)
    assert spec.entity_ids == ("C1", "C2")
    assert sorted(spec.location_ids) == ["A", "B"]
    (one,) = Cluster(ThesisWardClustering(0.5), n_clusters=1).partition(toy_eventset)
    assert one.entities == (Entity("C1", ("A", "B")),)


def test_cluster_materialise_reuses_a_spec_on_other_rows(
    toy_eventset: EventSet,
) -> None:
    scope = Cluster(strategy=FixedClustering({"A": 1, "B": 1}), n_clusters=1)
    (spec,) = scope.partition(toy_eventset)
    problem = scope.materialise(toy_eventset.filter_threshold(30.0), spec)
    assert problem.n_rows == 2
    np.testing.assert_array_equal(problem.loss, [6.0, 16.0])


def test_cluster_materialise_rejects_other_locations(toy_eventset: EventSet) -> None:
    scope = Cluster(strategy=FixedClustering({"A": 1, "B": 1}), n_clusters=1)
    (spec,) = scope.partition(toy_eventset)
    with pytest.raises(EntityMismatchError, match="locations differ"):
        scope.materialise(three_locations(toy_eventset), spec)


@pytest.mark.parametrize(
    ("labels", "match"),
    [
        ({"A": 1}, r"missing \['B'\]"),
        ({"A": 1, "B": 2, "Z": 1}, r"unknown \['Z'\]"),
        ({"A": 1, "B": 3}, "labels must be in 1..2"),
        ({"A": 0, "B": 1}, "labels must be in 1..2"),
        ({"A": 1, "B": 1}, r"clusters \[2\] have no locations"),
    ],
)
def test_cluster_partition_rejects_bad_assignments(
    toy_eventset: EventSet, labels: dict[str, int], match: str
) -> None:
    scope = Cluster(strategy=FixedClustering(labels), n_clusters=2)
    with pytest.raises(EntityMismatchError, match=match):
        scope.partition(toy_eventset)


def test_cluster_partition_rejects_too_many_clusters(toy_eventset: EventSet) -> None:
    scope = Cluster(strategy=FixedClustering(), n_clusters=3)
    with pytest.raises(InputMismatchError, match="exceeds"):
        scope.partition(toy_eventset)


@pytest.mark.parametrize("n", [0, -2, True, 1.5, "2"])
def test_cluster_rejects_invalid_n_clusters(n: object) -> None:
    with pytest.raises(ComponentConfigError, match="n_clusters"):
        Cluster(strategy=FixedClustering(), n_clusters=n)  # type: ignore[arg-type]


def test_cluster_n_clusters_becomes_an_int() -> None:
    scope = Cluster(strategy=FixedClustering(), n_clusters=np.int64(2))  # type: ignore[arg-type]
    assert type(scope.n_clusters) is int


def test_cluster_rejects_a_non_strategy() -> None:
    with pytest.raises(ComponentConfigError, match="ClusteringStrategy"):
        Cluster(strategy="ward", n_clusters=2)  # type: ignore[arg-type]


def test_cluster_rejects_a_non_index() -> None:
    with pytest.raises(ComponentConfigError, match="EntityIndex"):
        Cluster(strategy=FixedClustering(), n_clusters=2, index=None)  # type: ignore[arg-type]


def test_cluster_with_point_index_needs_single_location_clusters(
    toy_eventset: EventSet,
) -> None:
    scope = Cluster(
        strategy=FixedClustering({"A": 1, "B": 1}), n_clusters=1, index=PointIndex()
    )
    with pytest.raises(EntityMismatchError, match="single-location"):
        scope.materialise(toy_eventset, scope.partition(toy_eventset)[0])


# --------------------------------------------------------------------------
# Separately calibrated clusters: Cluster(joint=False) (MAR-180)
# --------------------------------------------------------------------------

THREE = {"A": 1, "B": 2, "C": 1}
"""Clusters of :func:`three_locations`: C1 = {A, C}, C2 = {B}."""


def separate(labels: Mapping[str, int] = THREE, n_clusters: int = 2) -> Cluster:
    return Cluster(strategy=FixedClustering(labels), n_clusters=n_clusters, joint=False)


def test_cluster_is_joint_by_default() -> None:
    assert Cluster(strategy=FixedClustering(), n_clusters=2).joint is True
    assert separate().joint is False
    assert Cluster.name == "cluster"  # the same scope name either way


@pytest.mark.parametrize("joint", [1, 0, "false", None, np.bool_(False)])
def test_cluster_rejects_a_non_bool_joint(joint: object) -> None:
    with pytest.raises(ComponentConfigError, match="joint must be a bool"):
        Cluster(strategy=FixedClustering(), n_clusters=2, joint=joint)  # type: ignore[arg-type]


def test_cluster_problem_id() -> None:
    assert CLUSTER_PROBLEM_PREFIX == "cluster:"
    assert cluster_problem_id("C3") == "cluster:C3"


def test_separate_partition_is_one_problem_per_cluster(
    toy_eventset: EventSet,
) -> None:
    es = three_locations(toy_eventset)
    joint = Cluster(strategy=FixedClustering(THREE), n_clusters=2)
    (joint_spec,) = joint.partition(es)
    specs = separate().partition(es)
    # Same clusters, same entities and locations; one spec each, label order.
    assert [s.entities for s in specs] == [(e,) for e in joint_spec.entities]
    assert [s.problem_id for s in specs] == ["cluster:C1", "cluster:C2"]
    assert specs[0].entities == (Entity("C1", ("A", "C")),)
    assert specs[1].entities == (Entity("C2", ("B",)),)


def test_separate_problem_ids_differ_from_every_other_scope(
    toy_eventset: EventSet,
) -> None:
    # The problem ids of a joint=False run are none of: the joint scopes'
    # "portfolio", the aggregate rows' "*", the individual scope's ids (the
    # location ids) or the cluster entity ids.
    es = three_locations(toy_eventset)
    ids = {s.problem_id for s in separate().partition(es)}
    others = {PORTFOLIO_PROBLEM_ID, ALL_PROBLEMS}
    others |= {s.problem_id for s in Individual().partition(es)}
    others |= {s.problem_id for s in Portfolio().partition(es)}
    (joint_spec,) = Cluster(FixedClustering(THREE), n_clusters=2).partition(es)
    others |= {joint_spec.problem_id, *joint_spec.entity_ids}
    assert ids.isdisjoint(others)


def test_separate_materialise_is_the_joint_problem_column_by_column(
    toy_eventset: EventSet,
) -> None:
    es = three_locations(toy_eventset)
    joint = Cluster(strategy=FixedClustering(THREE), n_clusters=2)
    (joint_spec,) = joint.partition(es)
    whole = joint.materialise(es, joint_spec)
    scope = separate()
    for j, spec in enumerate(scope.partition(es)):
        problem = scope.materialise(es, spec)
        assert problem.spec == spec
        np.testing.assert_array_equal(problem.index, whole.index[:, [j]])
        np.testing.assert_array_equal(problem.entity_loss, whole.entity_loss[:, [j]])
        np.testing.assert_array_equal(problem.loss, whole.entity_loss[:, j])


def test_separate_materialise_ignores_other_locations(
    toy_eventset: EventSet,
) -> None:
    # As in the individual scope: a cluster's problem on an EventSet that
    # also holds other locations is the same as on its own locations.
    es = three_locations(toy_eventset)
    scope = separate()
    c2 = scope.partition(es)[1]
    on_all = scope.materialise(es, c2)
    on_b = scope.materialise(drop_location(drop_location(es, "A"), "C"), c2)
    np.testing.assert_array_equal(on_all.index, on_b.index)
    np.testing.assert_array_equal(on_all.loss, on_b.loss)
    np.testing.assert_array_equal(on_b.index[:, 0], es.index[:, 1])


def test_separate_materialise_rejects_a_joint_spec(toy_eventset: EventSet) -> None:
    es = three_locations(toy_eventset)
    (joint_spec,) = Cluster(FixedClustering(THREE), n_clusters=2).partition(es)
    with pytest.raises(EntityMismatchError, match=r"joint=False\) is one entity"):
        separate().materialise(es, joint_spec)


def test_separate_materialise_rejects_a_missing_location(
    toy_eventset: EventSet,
) -> None:
    es = three_locations(toy_eventset)
    c1 = separate().partition(es)[0]
    with pytest.raises(EntityMismatchError):
        separate().materialise(drop_location(es, "C"), c1)


def test_separate_partition_keeps_the_cluster_checks(
    toy_eventset: EventSet,
) -> None:
    with pytest.raises(InputMismatchError, match="exceeds"):
        Cluster(FixedClustering(), n_clusters=3, joint=False).partition(toy_eventset)
    with pytest.raises(EntityMismatchError, match="no locations"):
        separate({"A": 1, "B": 1}).partition(toy_eventset)


def test_one_cluster_separate_is_the_joint_problem(toy_eventset: EventSet) -> None:
    labels = {"A": 1, "B": 1}
    joint = Cluster(FixedClustering(labels), n_clusters=1)
    (joint_spec,) = joint.partition(toy_eventset)
    scope = separate(labels, n_clusters=1)
    (spec,) = scope.partition(toy_eventset)
    assert spec.problem_id == "cluster:C1"
    assert spec.entities == joint_spec.entities
    a = scope.materialise(toy_eventset, spec)
    b = joint.materialise(toy_eventset, joint_spec)
    np.testing.assert_array_equal(a.index, b.index)
    np.testing.assert_array_equal(a.entity_loss, b.entity_loss)


def _solved(
    es: EventSet,
    scope: Scope,
    objective: Objective,
    budget: Budget,
    basis: Basis,
) -> list[SolveResult]:
    built = build_problems(
        es,
        scope,
        StepPayout(20.0, 60.0, 2),
        objective,
        PurePremium(),
        (budget,),
        basis=basis,
    )
    return [solve(b, DEFAULT_POLICY) for b in built]


@pytest.mark.parametrize("basis", BASES)
def test_each_cluster_has_its_own_budget(toy_eventset: EventSet, basis: Basis) -> None:
    # Budget(kappa) under the pure premium: each cluster's premium is at most
    # kappa * E[L_cluster], and the MSE design spends it (binding).
    es = three_locations(toy_eventset)
    scope = separate()
    kappa = 0.3
    results = _solved(es, scope, MSE(), Budget(kappa), basis)
    measure = outcome_measure(es, basis)
    assert len(results) == 2
    for r in results:
        problem = scope.materialise(es, r.spec)
        expected_loss = float(measure.probability @ measure.aggregate(problem.loss))
        assert expected_loss > 0.0
        assert r.premium <= kappa * expected_loss * (1.0 + 1e-6)
        assert r.premium == pytest.approx(kappa * expected_loss, rel=1e-4)


def test_evaluate_and_pair_a_separate_run_across_scopes(
    toy_eventset: EventSet,
) -> None:
    # evaluate.kpis and bootstrap_kpis work for joint=False as for the
    # individual scope (portfolio rows under "*"); the allocation rules split
    # each cluster's payout over its locations; and
    # paired_difference(across_scopes=True) pairs its portfolio rows with
    # the individual and the joint cluster runs'.
    es = three_locations(toy_eventset)
    basis = Basis.EVENT_CONDITIONAL
    runs: dict[str, tuple[Scope, list[SolveResult]]] = {}
    for label, scope in (
        ("individual", Individual()),
        ("joint", Cluster(FixedClustering(THREE), n_clusters=2)),
        ("separate", separate()),
    ):
        runs[label] = (
            scope,
            _solved(es, scope, ExpectedUncovered(), Budget(1.0), basis),
        )

    scope, results = runs["separate"]
    table = kpis(es, scope, results, basis=basis, beta=0.5, run_id="sep")
    problem_ids = {
        level: sorted(set(rows["problem_id"])) for level, rows in table.groupby("level")
    }
    assert problem_ids == {
        "portfolio": [ALL_PROBLEMS],
        "problem": ["cluster:C1", "cluster:C2"],
        "entity": ["cluster:C1", "cluster:C2"],
    }
    entity = table.loc[table["level"] == "entity"]
    assert sorted(set(entity["subject_id"])) == ["C1", "C2"]

    for rule, level in (("value", "location_by_value"), ("loss", "location_by_loss")):
        ruled = kpis(
            es, scope, results, basis=basis, beta=0.5, run_id="sep", allocation=rule
        )
        rows = ruled.loc[ruled["level"] == level]
        owner = dict(zip(rows["subject_id"], rows["problem_id"], strict=True))
        assert owner == {"A": "cluster:C1", "B": "cluster:C2", "C": "cluster:C1"}
        paid = rows.loc[rows["kpi"] == "expected_payout"].set_index("subject_id")
        problems = ruled.loc[
            (ruled["level"] == "problem") & (ruled["kpi"] == "expected_payout")
        ].set_index("subject_id")["value"]
        assert paid.loc[["A", "C"], "value"].sum() == pytest.approx(
            problems["cluster:C1"]
        )
        assert paid.loc["B", "value"] == pytest.approx(problems["cluster:C2"])

    resample = resample_years(Sample.full(es).years, 50, np.random.default_rng(0))
    boots = {
        label: bootstrap_kpis(
            es, s, r, basis=basis, beta=0.5, run_id=label, resample=resample
        ).portfolio_rows()
        for label, (s, r) in runs.items()
    }
    for other, pid in (("individual", ALL_PROBLEMS), ("joint", PORTFOLIO_PROBLEM_ID)):
        diff = paired_difference(boots["separate"], boots[other], across_scopes=True)
        assert len(diff) == len(boots["separate"].table) > 0
        assert set(diff["problem_id_a"]) == {ALL_PROBLEMS}
        assert set(diff["problem_id_b"]) == {pid}


@given(
    eventset=layouts(),
    basis=st.sampled_from(BASES),
    payout=step_payouts(),
    objective=objectives(),
    pricing=pricings(),
    budget=budgets(),
)
@PROPERTY_SETTINGS
def test_one_location_per_cluster_separate_is_the_individual_scope(
    eventset: EventSet,
    basis: Basis,
    payout: StepPayout,
    objective: Objective,
    pricing: Pricing,
    budget: Budget | None,
) -> None:
    """Singleton clusters: each cluster's problem is its location's individual
    problem (same index, loss, cap and budget), so the objective values and
    premiums are the individual scope's."""
    constraints = () if budget is None else (budget,)
    scope = Cluster(
        OneClusterPerLocation(), n_clusters=eventset.n_locations, joint=False
    )
    separate_designs = designs(
        eventset, scope, payout, objective, pricing, constraints, basis
    )
    individual = designs(
        eventset, Individual(), payout, objective, pricing, constraints, basis
    )
    assert [d.result.spec.location_ids for d in separate_designs] == [
        d.result.spec.location_ids for d in individual
    ]
    measure = Measure.of(eventset, basis)
    h = homogeneity(objective)
    for sep, ind in zip(separate_designs, individual, strict=True):
        assert sep.result.problem_id == cluster_problem_id(sep.result.entity_ids[0])
        sp, ip = sep.built.context.problem, ind.built.context.problem
        np.testing.assert_array_equal(sp.index, ip.index)
        np.testing.assert_array_equal(sp.entity_loss, ip.entity_loss)
        np.testing.assert_array_equal(sep.cap, ind.cap)
        tol = solver_tol([sep.result, ind.result])
        obj_tol = (
            tol
            * ind.result.scale**h
            * measure.max_rows_per_outcome**h
            * tail_factor(objective)
            * 2.0
        )
        assert sep.result.objective_value == pytest.approx(
            ind.result.objective_value, abs=obj_tol
        )
        loss_tol = tol * ind.result.scale * measure.max_rows_per_outcome * 2.0
        assert sep.result.premium == pytest.approx(ind.result.premium, abs=loss_tol)


# --------------------------------------------------------------------------
# The thesis fixture: joint=False is MAR-158's cluster_separate design
# --------------------------------------------------------------------------

C1_MAIN = REPO_ROOT / "research" / "configs" / "c1" / "c1_main.yaml"
C1_RQ2_PAYOUTS = REPO_ROOT / "research" / "data" / "c1-rq2" / "entity_payouts.csv"


@dataclass(frozen=True)
class ResearchSeparateClusters(Scope):
    """MAR-158's ``cluster_separate`` scope (``research/scripts/c1_rq2.py``).

    As ``SeparateClusters`` there: the wrapped cluster scope's partition,
    split into one single-entity spec per cluster (``problem_id`` =
    ``entity_id``); the cluster index, and the loss summed over the
    cluster's columns. Copied, because the research script is not importable
    from the core tests.
    """

    name: ClassVar[str] = "cluster_separate"

    cluster: Cluster

    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        return tuple(
            ProblemSpec(problem_id=e.entity_id, entities=(e,))
            for spec in self.cluster.partition(eventset)
            for e in spec.entities
        )

    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        assert len(spec.entities) == 1
        index = self.cluster.index.compute(eventset, spec.entities)
        cols = location_columns(eventset, spec.entities[0].location_ids)
        loss = np.ascontiguousarray(eventset.loss[:, cols]).sum(axis=1)[:, None]
        return DesignProblem(spec=spec, index=index, entity_loss=loss)


DESIGN_OBJECTIVES: dict[str, dict[str, Any]] = {
    "mse": {"kind": "mse"},
    "eu": {"kind": "expected_uncovered"},
    "wcvar@0.99": {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.99},
}
"""The C1 designs of ``c1_main.yaml``, by their ``c1-rq2`` labels."""


@pytest.fixture(scope="module")
def c1_main() -> dict[str, Any]:
    """``c1_main.yaml`` with its cluster scope only and no bootstrap."""
    if not C1_MAIN.is_file():
        pytest.skip("the C1 config and the parity fixture are only in a checkout")
    data = yaml.safe_load(C1_MAIN.read_text(encoding="utf-8"))
    data["eventset"]["path"] = str(
        (C1_MAIN.parent / data["eventset"]["path"]).resolve()
    )
    data["scopes"] = [s for s in data["scopes"] if s["kind"] == "cluster"]
    del data["bootstrap"]
    return data


@pytest.fixture(scope="module")
def c1_prepared(c1_main: dict[str, Any]) -> EventSet:
    """The thesis fixture prepared as the C1 runs (noise, threshold)."""
    raw = EventSet.from_parquet(Path(c1_main["eventset"]["path"]))
    return prepare_eventset(parse_config(copy.deepcopy(c1_main)), raw)


@pytest.mark.parametrize("design", sorted(DESIGN_OBJECTIVES))
def test_separate_is_the_c1_rq2_cluster_separate_design(
    c1_main: dict[str, Any], c1_prepared: EventSet, design: str
) -> None:
    """The C1 main line (annual basis, holdout 0.7, pure pricing, kappa 1)
    with ``joint: false`` in the config gives MAR-158's ``cluster_separate``
    designs (objective values within 1e-6 relative) and their test expected
    payout per cluster in ``research/data/c1-rq2/entity_payouts.csv``."""
    data = copy.deepcopy(c1_main)
    data["objectives"] = [DESIGN_OBJECTIVES[design]]
    joint_config = parse_config(copy.deepcopy(data))
    data["scopes"][0]["joint"] = False
    components = parse_config(data).to_components()
    scope = components.scopes[0]
    joint = joint_config.to_components().scopes[0]
    assert isinstance(scope, Cluster)
    assert not scope.joint
    assert isinstance(joint, Cluster)
    assert joint.joint

    train, test = splits.holdout(c1_prepared, train_fraction=0.7)

    def solved(s: Scope) -> list[SolveResult]:
        built = build_problems(
            c1_prepared,
            s,
            components.payout,
            components.objectives[0],
            components.pricing,
            components.constraints,
            basis=components.basis,
            sample=train,
        )
        return [solve(b, DEFAULT_POLICY) for b in built]

    ours = solved(scope)
    theirs = solved(ResearchSeparateClusters(joint))
    assert [r.problem_id for r in ours] == ["cluster:C1", "cluster:C2", "cluster:C3"]
    for a, b in zip(ours, theirs, strict=True):
        assert a.spec.entities == b.spec.entities
        assert a.objective_value == pytest.approx(b.objective_value, rel=1e-6)

    ref = pd.read_csv(C1_RQ2_PAYOUTS)
    ref = ref.loc[
        (ref["split"] == "test")
        & (ref["pricing"] == "pure")
        & (ref["kappa"].astype(float) == 1.0)
        & (ref["design"] == design)
        & (ref["scope"] == "cluster_separate")
    ].set_index("entity_id")
    test_data = test.select(c1_prepared)
    measure = outcome_measure(test_data, components.basis, years=test.years)
    for r in ours:
        (entity_id,) = r.entity_ids
        problem = scope.materialise(test_data, r.spec)
        locations = " ".join(problem.spec.location_ids)
        assert locations == ref.loc[entity_id, "entity_locations"]
        payout = r.payouts(problem)[:, 0]
        expected = float(measure.probability @ measure.aggregate(payout))
        # The CSV holds 7 significant digits.
        assert expected == pytest.approx(
            float(ref.loc[entity_id, "expected_payout"]), rel=1e-5
        )
