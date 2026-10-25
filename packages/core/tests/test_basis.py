"""Tests for the basis and outcome measure contract (ADR 0002, MAR-61)."""

from __future__ import annotations

import cvxpy as cp
import numpy as np
import pytest

from parametric_insurance_design.basis import (
    Basis,
    OutcomeMeasure,
    outcome_measure,
)
from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.eventset import EventSet


def test_basis_values() -> None:
    assert [b.value for b in Basis] == ["event_conditional", "event", "annual"]
    assert Basis("annual") is Basis.ANNUAL


def test_event_conditional_rescales_rates(toy_eventset: EventSet) -> None:
    filtered = toy_eventset.filter_threshold(20.0)  # drops ev1
    measure = outcome_measure(filtered, Basis.EVENT_CONDITIONAL)
    assert measure.basis is Basis.EVENT_CONDITIONAL
    assert measure.is_per_row
    np.testing.assert_allclose(measure.probability, [0.5, 0.5])
    # The measure accepts the string form of the basis too.
    assert outcome_measure(filtered, "event_conditional").n_outcomes == 2  # type: ignore[arg-type]


def test_outcome_measure_needs_rows(toy_eventset: EventSet) -> None:
    empty = toy_eventset.filter_threshold(1e9)
    with pytest.raises(InputMismatchError, match="without rows"):
        outcome_measure(empty, Basis.EVENT_CONDITIONAL)


def test_per_row_measure_aggregates_identically() -> None:
    measure = OutcomeMeasure.per_row(Basis.EVENT, [0.25, 0.75])
    assert (measure.n_rows, measure.n_outcomes) == (2, 2)
    np.testing.assert_array_equal(measure.aggregate([1.0, 2.0]), [1.0, 2.0])
    assert measure.expectation([4.0, 8.0]) == pytest.approx(7.0)
    x = cp.Variable(2)
    assert measure.aggregate_expression(x) is x


def test_grouped_measure_sums_rows_into_outcomes() -> None:
    # Rows 0 and 1 are one year, row 2 another, and a third year has no rows.
    measure = OutcomeMeasure(
        basis=Basis.ANNUAL,
        outcome_of_row=np.array([0, 0, 1]),
        probability=np.array([1 / 3, 1 / 3, 1 / 3]),
    )
    assert not measure.is_per_row
    np.testing.assert_allclose(measure.aggregate([1.0, 2.0, 5.0]), [3.0, 5.0, 0.0])
    np.testing.assert_allclose(
        measure.aggregate(np.array([[1.0, 0.0], [2.0, 1.0], [5.0, 2.0]])),
        [[3.0, 1.0], [5.0, 2.0], [0.0, 0.0]],
    )
    assert measure.expectation([1.0, 2.0, 5.0]) == pytest.approx(8 / 3)


def test_measure_arrays_are_read_only() -> None:
    measure = OutcomeMeasure.per_row(Basis.EVENT, [0.5, 0.5])
    with pytest.raises(ValueError, match="read-only"):
        measure.probability[0] = 1.0


@pytest.mark.parametrize(
    ("rows", "prob", "match"),
    [
        (np.array([[0]]), np.array([1.0]), "1-D integer"),
        (np.array([0.0]), np.array([1.0]), "1-D integer"),
        (np.array([0]), np.array([]), "non-empty"),
        (np.array([0, 2]), np.array([0.5, 0.5]), r"\[0, 2\)"),
        (np.array([-1]), np.array([1.0]), r"\[0, 1\)"),
        (np.array([0, 1]), np.array([1.5, -0.5]), ">= 0"),
        (np.array([0, 1]), np.array([np.nan, 1.0]), "finite"),
        (np.array([0, 1]), np.array([0.5, 0.4]), "sum to 1"),
    ],
)
def test_measure_validation(rows: np.ndarray, prob: np.ndarray, match: str) -> None:
    with pytest.raises(InputMismatchError, match=match):
        OutcomeMeasure(basis=Basis.ANNUAL, outcome_of_row=rows, probability=prob)


def test_aggregate_checks_shapes() -> None:
    measure = OutcomeMeasure.per_row(Basis.EVENT, [0.5, 0.5])
    with pytest.raises(InputMismatchError, match="shape"):
        measure.aggregate([1.0, 2.0, 3.0])
    with pytest.raises(InputMismatchError, match="shape"):
        measure.aggregate_expression(cp.Variable(3))
