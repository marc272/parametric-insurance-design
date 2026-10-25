"""Tests for the entity index definitions (MAR-12)."""

from __future__ import annotations

import numpy as np
import pytest

from parametric_insurance_design.errors import EntityMismatchError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.index import (
    EntityIndex,
    PointIndex,
    ValueWeightedIndex,
    location_columns,
)
from parametric_insurance_design.interfaces import Entity


def with_values(eventset: EventSet, values: list[float]) -> EventSet:
    locations = eventset.locations.copy()
    locations["value"] = values
    return EventSet(
        events=eventset.events,
        locations=locations,
        index=eventset.index,
        loss=eventset.loss,
        metadata=eventset.metadata,
    )


def test_location_columns_keep_the_requested_order(toy_eventset: EventSet) -> None:
    cols = location_columns(toy_eventset, ["B", "A", "B"])
    assert cols.tolist() == [1, 0, 1]
    assert cols.dtype == np.intp


def test_location_columns_reject_unknown_locations(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError, match="'C'"):
        location_columns(toy_eventset, ["A", "C"])


def test_indices_are_entity_indices() -> None:
    assert isinstance(PointIndex(), EntityIndex)
    assert isinstance(ValueWeightedIndex(), EntityIndex)


def test_point_index_takes_each_entitys_column(toy_eventset: EventSet) -> None:
    entities = [Entity("b", ("B",)), Entity("a", ("A",))]
    xi = PointIndex().compute(toy_eventset, entities)
    np.testing.assert_array_equal(xi, [[15.0, 10.0], [35.0, 30.0], [55.0, 50.0]])
    assert xi.dtype == np.float64
    assert xi.flags.writeable  # a copy, not a view of the read-only EventSet


def test_point_index_rejects_multi_location_entities(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError, match="single-location"):
        PointIndex().compute(toy_eventset, [Entity("ab", ("A", "B"))])


def test_point_index_rejects_unknown_locations(toy_eventset: EventSet) -> None:
    with pytest.raises(EntityMismatchError, match="not in the EventSet"):
        PointIndex().compute(toy_eventset, [Entity("c", ("C",))])


def test_value_weighted_index_by_hand(toy_eventset: EventSet) -> None:
    # Values 100 and 50: weights 2/3 and 1/3.
    xi = ValueWeightedIndex().compute(toy_eventset, [Entity("C1", ("A", "B"))])
    expected = (2 * np.array([10.0, 30.0, 50.0]) + np.array([15.0, 35.0, 55.0])) / 3
    np.testing.assert_allclose(xi[:, 0], expected, rtol=1e-15)
    assert xi.shape == (3, 1)


def test_value_weighted_index_of_one_location_is_its_index(
    toy_eventset: EventSet,
) -> None:
    entities = [Entity("C1", ("B",)), Entity("C2", ("A",))]
    np.testing.assert_array_equal(
        ValueWeightedIndex().compute(toy_eventset, entities),
        PointIndex().compute(toy_eventset, entities),
    )


def test_value_weighted_index_ignores_zero_value_members(
    toy_eventset: EventSet,
) -> None:
    es = with_values(toy_eventset, [0.0, 50.0])
    xi = ValueWeightedIndex().compute(es, [Entity("C1", ("A", "B"))])
    np.testing.assert_array_equal(xi[:, 0], es.index[:, 1])


def test_value_weighted_index_rejects_all_zero_values(toy_eventset: EventSet) -> None:
    es = with_values(toy_eventset, [0.0, 0.0])
    with pytest.raises(EntityMismatchError, match="value 0"):
        ValueWeightedIndex().compute(es, [Entity("C1", ("A", "B"))])


def test_value_weighted_index_rejects_unknown_locations(
    toy_eventset: EventSet,
) -> None:
    with pytest.raises(EntityMismatchError, match="not in the EventSet"):
        ValueWeightedIndex().compute(toy_eventset, [Entity("C1", ("A", "Z"))])
