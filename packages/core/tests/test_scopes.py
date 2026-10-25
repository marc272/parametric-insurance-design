"""Tests for the individual, portfolio and cluster scopes (MAR-12)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

import numpy as np
import pytest

from parametric_insurance_design.clustering import ThesisWardClustering
from parametric_insurance_design.errors import (
    ComponentConfigError,
    EntityMismatchError,
    InputMismatchError,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.index import PointIndex, ValueWeightedIndex
from parametric_insurance_design.interfaces import Entity, ProblemSpec, Scope
from parametric_insurance_design.scopes import (
    PORTFOLIO_PROBLEM_ID,
    Cluster,
    Individual,
    Portfolio,
)


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
