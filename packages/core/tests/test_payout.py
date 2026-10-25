"""Tests for ``payout.py`` (MAR-11): StepPayout and uniform breakpoints.

The expected bins below are derived by hand from the thesis semantics
(``_mapping`` and ``get_payout_for_asset``): half-open bins ``[b_k, b_{k+1})``,
values below the attachment in bin 0, values at or above the limit in the
last bin. The comparison with the thesis functions themselves is in
``parity/tests/test_payout_parity.py``.
"""

from __future__ import annotations

import dataclasses
from typing import cast

import cvxpy as cp
import numpy as np
import pytest

from parametric_insurance_design.errors import (
    ComponentConfigError,
    InputMismatchError,
)
from parametric_insurance_design.interfaces import PayoutStructure
from parametric_insurance_design.payout import (
    THESIS_UPPER_EPS,
    StepPayout,
    uniform_breakpoints,
)

# Thesis defaults: ATTACHEMENT 20, LIMIT 70 (configs/global_settings.yaml).
FIVE = StepPayout(attachment=20.0, limit=70.0, n_bins=5)  # edges 20, 30, ..., 70


# -- uniform_breakpoints -------------------------------------------------------


@pytest.mark.parametrize("n_bins", [1, 2, 5, 15, 20, 25])
def test_uniform_breakpoints_is_thesis_linspace(n_bins: int) -> None:
    edges = uniform_breakpoints(20.0, 70.0, n_bins)
    assert edges.shape == (n_bins + 1,)
    assert edges.dtype == np.float64
    np.testing.assert_array_equal(edges, np.linspace(20.0, 70.0, n_bins + 1))
    assert edges[0] == 20.0
    assert edges[-1] == 70.0


def test_uniform_breakpoints_accepts_ints_and_numpy_scalars() -> None:
    np.testing.assert_array_equal(
        uniform_breakpoints(0, 10, np.int64(2)),  # type: ignore[arg-type]
        [0.0, 5.0, 10.0],
    )
    np.testing.assert_array_equal(
        uniform_breakpoints(np.float64(-1.0), 1, 2), [-1.0, 0.0, 1.0]
    )


@pytest.mark.parametrize(
    ("attachment", "limit", "n_bins", "message"),
    [
        pytest.param(20.0, 70.0, 0, "n_bins must be >= 1", id="zero-bins"),
        pytest.param(20.0, 70.0, -3, "n_bins must be >= 1", id="negative-bins"),
        pytest.param(20.0, 70.0, 2.0, "n_bins must be an int", id="float-bins"),
        pytest.param(20.0, 70.0, True, "n_bins must be an int", id="bool-bins"),
        pytest.param(70.0, 20.0, 5, "attachment must be < limit", id="reversed"),
        pytest.param(20.0, 20.0, 5, "attachment must be < limit", id="empty"),
        pytest.param(np.nan, 70.0, 5, "attachment must be finite", id="nan"),
        pytest.param(20.0, np.inf, 5, "limit must be finite", id="inf"),
        pytest.param("20", 70.0, 5, "attachment must be a real", id="str"),
        pytest.param(20.0, False, 5, "limit must be a real", id="bool"),
    ],
)
def test_uniform_breakpoints_rejects_bad_parameters(
    attachment: object, limit: object, n_bins: object, message: str
) -> None:
    with pytest.raises(ComponentConfigError, match=message):
        uniform_breakpoints(attachment, limit, n_bins)  # type: ignore[arg-type]


# -- construction ---------------------------------------------------------------


def test_step_payout_is_a_payout_structure() -> None:
    assert isinstance(FIVE, PayoutStructure)
    assert StepPayout.name == "step"
    assert FIVE.n_params == 5
    np.testing.assert_array_equal(FIVE.edges, [20.0, 30.0, 40.0, 50.0, 60.0, 70.0])
    assert FIVE.breakpoints is None


def test_edges_are_read_only() -> None:
    with pytest.raises(ValueError, match="read-only"):
        FIVE.edges[0] = 0.0


def test_step_payout_is_frozen_hashable_and_replaceable() -> None:
    same = StepPayout(attachment=20.0, limit=70.0, n_bins=5)
    assert same == FIVE
    assert hash(same) == hash(FIVE)
    assert "_edges" not in repr(FIVE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        FIVE.n_bins = 3  # type: ignore[misc]
    finer = dataclasses.replace(FIVE, n_bins=10)
    assert finer.n_params == 10
    np.testing.assert_array_equal(finer.edges, np.linspace(20.0, 70.0, 11))


def test_explicit_breakpoints() -> None:
    payout = StepPayout(20.0, 70.0, 3, breakpoints=(20, 25, 40, 70))
    assert payout.breakpoints is not None
    assert payout.breakpoints == (20.0, 25.0, 40.0, 70.0)
    assert all(isinstance(b, float) for b in payout.breakpoints)
    np.testing.assert_array_equal(payout.edges, [20.0, 25.0, 40.0, 70.0])
    np.testing.assert_array_equal(
        payout.bin_index([0.0, 24.9, 25.0, 39.9, 40.0, 70.0, 80.0]),
        [0, 0, 1, 1, 2, 2, 2],
    )


@pytest.mark.parametrize(
    ("breakpoints", "message"),
    [
        pytest.param((20.0, 45.0, 70.0), "n_bins \\+ 1 = 4", id="too-short"),
        pytest.param((20.0, 30.0, 40.0, 50.0, 70.0), "n_bins \\+ 1", id="too-long"),
        pytest.param((20.0, 50.0, 40.0, 70.0), "strictly increasing", id="down"),
        pytest.param((20.0, 40.0, 40.0, 70.0), "strictly increasing", id="tie"),
        pytest.param((20.0, np.nan, 50.0, 70.0), "finite", id="nan"),
        pytest.param((21.0, 30.0, 50.0, 70.0), "run from attachment", id="start"),
        pytest.param((20.0, 30.0, 50.0, 69.0), "run from attachment", id="end"),
        pytest.param(("a", "b", "c", "d"), "numeric", id="text"),
    ],
)
def test_explicit_breakpoints_are_validated(
    breakpoints: tuple[float, ...], message: str
) -> None:
    with pytest.raises(ComponentConfigError, match=message):
        StepPayout(20.0, 70.0, 3, breakpoints=breakpoints)


def test_bad_range_raises_on_construction() -> None:
    with pytest.raises(ComponentConfigError, match="n_bins must be >= 1"):
        StepPayout(20.0, 70.0, 0)
    with pytest.raises(ComponentConfigError, match="attachment must be < limit"):
        StepPayout(70.0, 20.0, 5)


def test_parameter_bounds_are_bin_edges() -> None:
    lower, upper = FIVE.parameter_bounds()
    np.testing.assert_array_equal(lower, [20.0, 30.0, 40.0, 50.0, 60.0])
    np.testing.assert_array_equal(upper, [30.0, 40.0, 50.0, 60.0, 70.0])
    lower[0] = -1.0  # copies: the payout structure is unaffected
    assert FIVE.edges[0] == 20.0
    assert FIVE.parameter_bounds()[0][0] == 20.0


# -- bin edges, clipping and out-of-range values --------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        pytest.param(-50.0, 0, id="negative-below-attachment"),
        pytest.param(0.0, 0, id="zero-wind"),
        pytest.param(17.5, 0, id="below-attachment"),
        pytest.param(np.nextafter(20.0, 0.0), 0, id="just-below-attachment"),
        pytest.param(20.0, 0, id="at-attachment"),
        pytest.param(25.0, 0, id="inside-first-bin"),
        pytest.param(np.nextafter(30.0, 0.0), 0, id="just-below-interior-edge"),
        pytest.param(30.0, 1, id="at-interior-edge-is-left-closed"),
        pytest.param(np.nextafter(30.0, 99.0), 1, id="just-above-interior-edge"),
        pytest.param(50.0, 3, id="at-middle-edge"),
        pytest.param(60.0, 4, id="at-last-interior-edge"),
        pytest.param(70.0 - THESIS_UPPER_EPS, 4, id="at-clip-point"),
        pytest.param(np.nextafter(70.0, 0.0), 4, id="just-below-limit"),
        pytest.param(70.0, 4, id="at-limit"),
        pytest.param(71.6, 4, id="above-limit"),
        pytest.param(1e9, 4, id="far-above-limit"),
    ],
)
def test_bin_index_edges_and_clipping(value: float, expected: int) -> None:
    assert FIVE.bin_index([value]).tolist() == [expected]
    row = FIVE.basis_matrix([value])[0]
    assert row.tolist() == [1.0 if k == expected else 0.0 for k in range(5)]


def test_bin_index_keeps_shape() -> None:
    values = np.array([[0.0, 35.0, 70.0], [20.0, 59.9, 1e3]])
    k = FIVE.bin_index(values)
    assert k.shape == (2, 3)
    assert k.dtype == np.intp
    np.testing.assert_array_equal(k, [[0, 1, 4], [0, 3, 4]])
    assert FIVE.bin_index(45.0).tolist() == 2  # 0-d in, 0-d out


def test_single_bin_takes_everything() -> None:
    one = StepPayout(20.0, 70.0, 1)
    np.testing.assert_array_equal(one.bin_index([-1.0, 20.0, 45.0, 70.0, 99.0]), 0)
    np.testing.assert_array_equal(one.basis_matrix([0.0, 99.0]), [[1.0], [1.0]])


def test_limit_where_eps_is_below_resolution_still_uses_last_bin() -> None:
    # 2**15 - 1e-12 rounds back to 2**15: the thesis _mapping would raise
    # IndexError here; get_payout_for_asset (and this module) clamp to the
    # last bin.
    limit = 2.0**15
    assert limit - THESIS_UPPER_EPS == limit
    big = StepPayout(0.0, limit, 4)
    np.testing.assert_array_equal(big.bin_index([0.0, limit, 2 * limit]), [0, 3, 3])


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_index_raises(bad: float) -> None:
    with pytest.raises(InputMismatchError, match="index must be finite"):
        FIVE.bin_index([30.0, bad])
    with pytest.raises(InputMismatchError, match="index must be finite"):
        FIVE.basis_matrix([30.0, bad])
    with pytest.raises(InputMismatchError, match="index must be finite"):
        FIVE.evaluate([[30.0], [bad]], np.ones((1, 5)))


def test_non_numeric_index_raises() -> None:
    with pytest.raises(InputMismatchError, match="numeric"):
        FIVE.bin_index(["thirty"])


# -- basis matrix ---------------------------------------------------------------


def test_basis_matrix_is_one_hot() -> None:
    index = [0.0, 22.0, 30.0, 45.0, 59.0, 65.0, 70.0, 80.0]
    m = FIVE.basis_matrix(index)
    assert m.shape == (8, 5)
    assert m.dtype == np.float64
    np.testing.assert_array_equal(m.sum(axis=1), np.ones(8))
    np.testing.assert_array_equal(np.argmax(m, axis=1), [0, 0, 1, 2, 3, 4, 4, 4])
    assert set(np.unique(m).tolist()) == {0.0, 1.0}


def test_basis_matrix_with_no_rows() -> None:
    assert FIVE.basis_matrix(np.array([], dtype=float)).shape == (0, 5)


def test_basis_matrix_needs_one_entity() -> None:
    with pytest.raises(InputMismatchError, match="1-D"):
        FIVE.basis_matrix([[30.0, 40.0]])


# -- evaluate -------------------------------------------------------------------


def test_evaluate_by_hand() -> None:
    theta = np.array([[0.0, 1.0, 2.0, 3.0, 4.0], [10.0, 10.0, 20.0, 20.0, 50.0]])
    index = np.array([[0.0, 75.0], [30.0, 45.0], [69.0, 20.0]])
    np.testing.assert_array_equal(
        FIVE.evaluate(index, theta), [[0.0, 50.0], [1.0, 20.0], [4.0, 10.0]]
    )


def test_evaluate_equals_basis_matrix_product() -> None:
    rng = np.random.default_rng(11)
    index = rng.uniform(-10.0, 90.0, size=(200, 3))
    index[:5] = [[20.0, 30.0, 70.0]] * 5  # edges
    theta = np.sort(rng.uniform(0.0, 100.0, size=(3, 5)), axis=1)
    out = FIVE.evaluate(index, theta)
    assert out.shape == (200, 3)
    for j in range(3):
        np.testing.assert_array_equal(
            out[:, j], FIVE.basis_matrix(index[:, j]) @ theta[j]
        )


def test_evaluate_monotone_theta_gives_monotone_payout() -> None:
    rng = np.random.default_rng(3)
    index = np.sort(rng.uniform(0.0, 90.0, size=500))[:, None]
    theta = np.cumsum(rng.uniform(0.0, 5.0, size=5))[None, :]
    payout = FIVE.evaluate(index, theta)[:, 0]
    assert np.all(np.diff(payout) >= 0)
    assert payout[0] == theta[0, 0]  # below attachment pays the first level
    assert payout[-1] == theta[0, -1]  # above the limit pays the last level


@pytest.mark.parametrize(
    ("index", "theta", "message"),
    [
        pytest.param(np.zeros(3), np.ones((1, 5)), "index must be 2-D", id="1d"),
        pytest.param(np.zeros((3, 2)), np.ones((1, 5)), "shape \\(2, 5\\)", id="ent"),
        pytest.param(np.zeros((3, 1)), np.ones((1, 4)), "shape \\(1, 5\\)", id="bins"),
        pytest.param(np.zeros((3, 1)), np.ones(5), "theta must be 2-D", id="th1d"),
        pytest.param(
            np.zeros((3, 1)), np.full((1, 5), np.nan), "theta must be finite", id="nan"
        ),
    ],
)
def test_evaluate_rejects_bad_inputs(
    index: np.ndarray, theta: np.ndarray, message: str
) -> None:
    with pytest.raises(InputMismatchError, match=message):
        FIVE.evaluate(index, theta)


# -- constraints (theta >= 0, monotone, cap per entity) -------------------------


def _satisfied(constraints: tuple[cp.Constraint, ...]) -> list[bool]:
    return [bool(c.value()) for c in constraints]


def test_constraints_accept_feasible_theta() -> None:
    theta = cp.Variable((2, 5))
    cons = FIVE.constraints(theta, np.array([4.0, 10.0]))
    assert len(cons) == 3
    theta.value = np.array([[0.0, 0.0, 1.0, 4.0, 4.0], [1.0, 2.0, 3.0, 5.0, 10.0]])
    assert _satisfied(cons) == [True, True, True]


@pytest.mark.parametrize(
    ("row", "broken"),
    [
        pytest.param([-1.0, 0.0, 1.0, 2.0, 3.0], 0, id="negative"),
        pytest.param([0.0, 2.0, 1.0, 2.0, 3.0], 1, id="decreasing"),
        pytest.param([0.0, 1.0, 2.0, 3.0, 4.5], 2, id="above-cap"),
    ],
)
def test_constraints_reject_infeasible_theta(row: list[float], broken: int) -> None:
    theta = cp.Variable((2, 5))
    cons = FIVE.constraints(theta, np.array([4.0, 10.0]))
    theta.value = np.array([row, [0.0, 0.0, 0.0, 0.0, 0.0]])
    assert _satisfied(cons) == [k != broken for k in range(3)]


def test_cap_is_per_entity() -> None:
    theta = cp.Variable((2, 5))
    cons = FIVE.constraints(theta, np.array([4.0, 10.0]))
    theta.value = np.array([[0.0] * 5, [6.0] * 5])  # fine for entity 2 only
    assert _satisfied(cons) == [True, True, True]
    theta.value = np.array([[6.0] * 5, [0.0] * 5])
    assert _satisfied(cons) == [True, True, False]


def test_constraints_bind_in_a_solve() -> None:
    # Ask for a decreasing, negative, over-cap payout; the constraints give the
    # closest monotone, non-negative, capped one.
    theta = cp.Variable((2, 5))
    cap = np.array([3.0, 8.0])
    target = np.array([[9.0, 5.0, 1.0, -2.0, 0.0], [1.0, 2.0, 3.0, 4.0, 20.0]])
    problem = cp.Problem(
        cp.Minimize(cp.sum(cp.abs(theta - target))), list(FIVE.constraints(theta, cap))
    )
    problem.solve(solver=cp.CLARABEL)
    assert problem.status == cp.OPTIMAL
    value = np.asarray(theta.value)
    assert np.all(value >= -1e-7)
    assert np.all(np.diff(value, axis=1) >= -1e-7)
    assert np.all(value <= cap[:, None] + 1e-7)
    np.testing.assert_allclose(value[1], [1.0, 2.0, 3.0, 4.0, 8.0], atol=1e-6)


def test_single_bin_has_no_monotone_constraint() -> None:
    theta = cp.Variable((3, 1))
    cons = StepPayout(20.0, 70.0, 1).constraints(theta, np.ones(3))
    assert len(cons) == 2
    theta.value = np.full((3, 1), 0.5)
    assert _satisfied(cons) == [True, True]


def test_constraints_accept_a_slice_of_a_shared_variable() -> None:
    shared = cp.Variable((4, 5))
    cons = FIVE.constraints(cast(cp.Variable, shared[1:3]), np.array([1.0, 2.0]))
    assert len(cons) == 3


@pytest.mark.parametrize(
    ("shape", "cap", "message"),
    [
        pytest.param((5,), np.ones(1), "theta must have shape", id="1d"),
        pytest.param((2, 4), np.ones(2), "theta must have shape", id="bins"),
        pytest.param((2, 5), np.ones(3), "cap must have shape \\(2,\\)", id="cap"),
        pytest.param((2, 5), np.ones((2, 1)), "cap must be 1-D", id="cap2d"),
        pytest.param((2, 5), np.array([1.0, -1.0]), "cap must be >= 0", id="neg"),
        pytest.param((2, 5), np.array([1.0, np.nan]), "cap must be finite", id="nan"),
    ],
)
def test_constraints_reject_bad_shapes(
    shape: tuple[int, ...], cap: np.ndarray, message: str
) -> None:
    with pytest.raises(InputMismatchError, match=message):
        FIVE.constraints(cp.Variable(shape), cap)
