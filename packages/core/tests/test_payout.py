"""Tests for ``payout.py`` (MAR-11, MAR-170): StepPayout and uniform breakpoints.

The expected bins below are derived by hand from the thesis semantics
(``_mapping`` and ``get_payout_for_asset``): half-open bins ``[b_k, b_{k+1})``,
values below the attachment in bin 0, values at or above the limit in the
last bin. The comparison with the thesis functions themselves is in
``parity/tests/test_payout_parity.py``.

MAR-170 adds ``below_attachment``: ``"first_bin"`` (the default, the semantics
above) or ``"zero"``, where a value below the attachment is in no bin
(``NO_BIN``) and pays nothing. The last section checks the experiment config's
``payout.below_attachment`` and that the hashes of the repository's configs
did not move. The filter invariance that ``"zero"`` buys on the ``event`` and
``annual`` bases is in ``test_filter_invariance.py``.
"""

from __future__ import annotations

import dataclasses
import hashlib
from pathlib import Path
from typing import Any, cast

import cvxpy as cp
import numpy as np
import pytest
import yaml

from parametric_insurance_design.errors import (
    ComponentConfigError,
    ConfigError,
    InputMismatchError,
)
from parametric_insurance_design.experiment.config import (
    StepPayoutConfig,
    canonical_json,
    config_hash,
    dump_config,
    load_config,
    parse_config,
    to_dict,
)
from parametric_insurance_design.experiment.sweeps import sweep_points
from parametric_insurance_design.interfaces import PayoutStructure
from parametric_insurance_design.payout import (
    BELOW_ATTACHMENT_MODES,
    NO_BIN,
    THESIS_UPPER_EPS,
    StepPayout,
    uniform_breakpoints,
)

# Thesis defaults: ATTACHEMENT 20, LIMIT 70 (configs/global_settings.yaml).
FIVE = StepPayout(attachment=20.0, limit=70.0, n_bins=5)  # edges 20, 30, ..., 70
ZERO = StepPayout(attachment=20.0, limit=70.0, n_bins=5, below_attachment="zero")
REPO_ROOT = Path(__file__).resolve().parents[3]


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


def test_last_bin_narrower_than_thesis_eps_is_rejected() -> None:
    # The thesis would clip 1 + 5e-13 to 1 - 5e-13, i.e. into bin 0.
    with pytest.raises(ComponentConfigError, match="last bin"):
        StepPayout(0.0, 1.0 + 5e-13, 2, breakpoints=(0.0, 1.0, 1.0 + 5e-13))
    with pytest.raises(ComponentConfigError, match="last bin"):
        StepPayout(0.0, 1e-10, 1000)
    StepPayout(0.0, 1.0 + 1e-11, 2, breakpoints=(0.0, 1.0, 1.0 + 1e-11))


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


# -- below_attachment (MAR-170) -------------------------------------------------


def test_below_attachment_defaults_to_the_thesis_first_bin() -> None:
    assert BELOW_ATTACHMENT_MODES == ("first_bin", "zero")
    assert FIVE.below_attachment == "first_bin"
    assert StepPayout(20.0, 70.0, 5, below_attachment="first_bin") == FIVE
    assert ZERO != FIVE
    assert hash(ZERO) != hash(FIVE)
    assert dataclasses.replace(FIVE, below_attachment="zero") == ZERO
    assert dataclasses.replace(ZERO, n_bins=2).below_attachment == "zero"
    assert NO_BIN == -1


@pytest.mark.parametrize("bad", ["none", "Zero", "", None, 0, False, ["zero"]])
def test_below_attachment_must_be_a_mode(bad: object) -> None:
    with pytest.raises(ComponentConfigError, match="below_attachment must be one"):
        StepPayout(20.0, 70.0, 5, below_attachment=bad)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "first_bin", "zero"),
    [
        pytest.param(-50.0, 0, NO_BIN, id="negative-below-attachment"),
        pytest.param(0.0, 0, NO_BIN, id="zero-wind"),
        pytest.param(17.5, 0, NO_BIN, id="below-attachment"),
        pytest.param(np.nextafter(20.0, 0.0), 0, NO_BIN, id="just-below-attachment"),
        pytest.param(20.0, 0, 0, id="at-attachment-is-bin-0"),
        pytest.param(np.nextafter(20.0, 99.0), 0, 0, id="just-above-attachment"),
        pytest.param(25.0, 0, 0, id="inside-first-bin"),
        pytest.param(30.0, 1, 1, id="at-interior-edge"),
        pytest.param(59.9, 3, 3, id="inside-bin-3"),
        pytest.param(70.0, 4, 4, id="at-limit"),
        pytest.param(1e9, 4, 4, id="far-above-limit"),
    ],
)
def test_bin_membership_in_both_modes(value: float, first_bin: int, zero: int) -> None:
    assert FIVE.bin_index([value]).tolist() == [first_bin]
    assert ZERO.bin_index([value]).tolist() == [zero]
    theta = np.array([[1.0, 2.0, 3.0, 4.0, 5.0]])
    for payout, k in ((FIVE, first_bin), (ZERO, zero)):
        row = payout.basis_matrix([value])[0]
        assert row.tolist() == [1.0 if j == k else 0.0 for j in range(5)]
        paid = payout.evaluate([[value]], theta)[0, 0]
        assert paid == (0.0 if k == NO_BIN else theta[0, k])


def test_zero_mode_bin_index_keeps_shape_and_dtype() -> None:
    values = np.array([[0.0, 35.0, 70.0], [20.0, 19.0, 1e3]])
    k = ZERO.bin_index(values)
    assert k.shape == (2, 3)
    assert k.dtype == np.intp
    np.testing.assert_array_equal(k, [[NO_BIN, 1, 4], [0, NO_BIN, 4]])
    assert ZERO.bin_index(5.0).tolist() == NO_BIN  # 0-d in, 0-d out
    assert ZERO.bin_index(45.0).tolist() == 2


def test_zero_mode_basis_matrix_has_all_zero_rows_below_the_attachment() -> None:
    index = [0.0, 19.99, 20.0, 22.0, 30.0, 45.0, 59.0, 65.0, 70.0, 80.0]
    m = ZERO.basis_matrix(index)
    assert m.shape == (10, 5)
    assert m.dtype == np.float64
    assert set(np.unique(m).tolist()) == {0.0, 1.0}
    # At most one 1 per row: none below the attachment, exactly one elsewhere.
    np.testing.assert_array_equal(m.sum(axis=1), [0, 0, 1, 1, 1, 1, 1, 1, 1, 1])
    np.testing.assert_array_equal(np.argmax(m[2:], axis=1), [0, 0, 1, 2, 3, 4, 4, 4])
    # Above the attachment the two modes agree row by row.
    np.testing.assert_array_equal(m[2:], FIVE.basis_matrix(index)[2:])
    # "first_bin": exactly one 1 in every row (thesis _mapping).
    np.testing.assert_array_equal(FIVE.basis_matrix(index).sum(axis=1), np.ones(10))
    assert ZERO.basis_matrix(np.array([], dtype=float)).shape == (0, 5)
    assert not ZERO.basis_matrix([-1.0, 0.0, 10.0]).any()


def test_zero_mode_evaluate_by_hand() -> None:
    theta = np.array([[0.5, 1.0, 2.0, 3.0, 4.0], [10.0, 10.0, 20.0, 20.0, 50.0]])
    index = np.array([[0.0, 75.0], [30.0, 19.0], [69.0, 20.0], [20.0, -3.0]])
    np.testing.assert_array_equal(
        ZERO.evaluate(index, theta),
        [[0.0, 50.0], [1.0, 0.0], [4.0, 10.0], [0.5, 0.0]],
    )
    np.testing.assert_array_equal(
        FIVE.evaluate(index, theta),
        [[0.5, 50.0], [1.0, 10.0], [4.0, 10.0], [0.5, 10.0]],
    )


@pytest.mark.parametrize("payout", [FIVE, ZERO], ids=["first_bin", "zero"])
def test_evaluate_equals_basis_matrix_product_in_both_modes(
    payout: StepPayout,
) -> None:
    rng = np.random.default_rng(170)
    index = rng.uniform(-10.0, 90.0, size=(300, 3))
    index[:5] = [[20.0, 30.0, 70.0]] * 5  # edges
    index[5:10] = [[np.nextafter(20.0, 0.0), 0.0, -10.0]] * 5  # below
    theta = np.sort(rng.uniform(0.0, 100.0, size=(3, 5)), axis=1)
    out = payout.evaluate(index, theta)
    assert out.shape == (300, 3)
    assert out.dtype == np.float64
    for j in range(3):
        np.testing.assert_array_equal(
            out[:, j], payout.basis_matrix(index[:, j]) @ theta[j]
        )
    below = index < 20.0
    first_level = np.broadcast_to(theta[:, 0], below.shape)
    expected = 0.0 if payout.below_attachment == "zero" else first_level[below]
    np.testing.assert_array_equal(out[below], expected)
    # At and above the attachment the two modes pay the same.
    np.testing.assert_array_equal(out[~below], FIVE.evaluate(index, theta)[~below])


def test_zero_mode_payout_is_monotone_and_starts_at_zero() -> None:
    rng = np.random.default_rng(3)
    index = np.sort(rng.uniform(0.0, 90.0, size=500))[:, None]
    theta = np.cumsum(rng.uniform(0.0, 5.0, size=5))[None, :]
    payout = ZERO.evaluate(index, theta)[:, 0]
    assert np.all(np.diff(payout) >= 0)
    assert payout[0] == 0.0  # below the attachment pays nothing
    assert payout[-1] == theta[0, -1]  # above the limit pays the last level
    assert ZERO.evaluate([[20.0]], theta)[0, 0] == theta[0, 0]


def test_zero_mode_one_bin_explicit_breakpoints_negative_attachment() -> None:
    one = StepPayout(20.0, 70.0, 1, below_attachment="zero")
    np.testing.assert_array_equal(
        one.bin_index([-1.0, 19.0, 20.0, 45.0, 70.0, 99.0]), [-1, -1, 0, 0, 0, 0]
    )
    np.testing.assert_array_equal(one.basis_matrix([0.0, 99.0]), [[0.0], [1.0]])
    explicit = StepPayout(
        20.0, 70.0, 3, breakpoints=(20, 25, 40, 70), below_attachment="zero"
    )
    np.testing.assert_array_equal(
        explicit.bin_index([0.0, 24.9, 25.0, 39.9, 40.0, 70.0, 80.0]),
        [-1, 0, 1, 1, 2, 2, 2],
    )
    negative = StepPayout(-10.0, 10.0, 2, below_attachment="zero")
    np.testing.assert_array_equal(
        negative.bin_index([-10.5, -10.0, -0.1, 0.0, 12.0]), [-1, 0, 0, 1, 1]
    )


def test_both_modes_share_bounds_constraints_and_validation() -> None:
    for got, want in zip(ZERO.parameter_bounds(), FIVE.parameter_bounds(), strict=True):
        np.testing.assert_array_equal(got, want)
    np.testing.assert_array_equal(ZERO.edges, FIVE.edges)
    assert ZERO.n_params == FIVE.n_params == 5
    theta = cp.Variable((2, 5))
    cap = np.array([4.0, 10.0])
    a, b = ZERO.constraints(theta, cap), FIVE.constraints(theta, cap)
    assert [str(c) for c in a] == [str(c) for c in b]
    with pytest.raises(InputMismatchError, match="index must be finite"):
        ZERO.evaluate([[np.nan]], np.ones((1, 5)))
    with pytest.raises(InputMismatchError, match="1-D"):
        ZERO.basis_matrix([[30.0, 40.0]])
    with pytest.raises(ComponentConfigError, match="last bin"):
        StepPayout(0.0, 1e-10, 1000, below_attachment="zero")


# -- the experiment config's payout.below_attachment (MAR-170) ------------------


def experiment(**payout: object) -> dict[str, Any]:
    """A minimal experiment config with the given payout fields added."""
    return {
        "schema_version": 1,
        "name": "below",
        "eventset": {"path": "eventset"},
        "basis": "annual",
        "payout": {"attachment": 20.0, "limit": 70.0, "n_bins": 5, **payout},
        "scopes": [{"kind": "individual"}],
        "objectives": [{"kind": "mse"}, {"kind": "expected_uncovered"}],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.9},
        "sweeps": [{"parameter": "n_bins", "values": [2, 5]}],
        "output": {"directory": "out"},
    }


def test_config_default_is_first_bin_and_left_out_of_dumps() -> None:
    unset = parse_config(experiment())
    explicit = parse_config(experiment(below_attachment="first_bin"))
    assert unset.payout.below_attachment == "first_bin"
    assert unset.payout.build() == FIVE
    assert explicit == unset
    for config in (unset, explicit):
        assert "below_attachment" not in to_dict(config)["payout"]
        assert "below_attachment" not in canonical_json(config)
        assert "below_attachment" not in dump_config(config)
    assert canonical_json(explicit) == canonical_json(unset)
    assert config_hash(explicit) == config_hash(unset)
    section = {"attachment": 20.0, "limit": 70.0, "n_bins": 5}
    assert StepPayoutConfig.model_validate(section).model_dump() == {
        "kind": "step",
        **section,
        "breakpoints": None,
    }


def test_config_zero_is_built_dumped_hashed_and_read_back() -> None:
    zero = parse_config(experiment(below_attachment="zero"))
    plain = parse_config(experiment())
    assert zero.payout.below_attachment == "zero"
    assert zero.payout.build() == ZERO
    assert zero.to_components().payout == ZERO
    assert to_dict(zero)["payout"]["below_attachment"] == "zero"
    assert '"below_attachment":"zero"' in canonical_json(zero)
    assert "below_attachment: zero" in dump_config(zero)
    assert config_hash(zero) != config_hash(plain)
    again = parse_config(yaml.safe_load(dump_config(zero)))
    assert again == zero
    assert config_hash(again) == config_hash(zero)
    # Single runs and sweep points keep the mode, with hashes of their own.
    assert all(s.payout.below_attachment == "zero" for s in zero.single_runs())
    assert zero.with_parameter("n_bins", 2).payout.build() == dataclasses.replace(
        ZERO, n_bins=2
    )
    points = sweep_points(zero, "n_bins")
    assert {p.config.payout.below_attachment for p in points} == {"zero"}
    plain_hashes = {config_hash(p.config) for p in sweep_points(plain, "n_bins")}
    assert not plain_hashes & {config_hash(p.config) for p in points}


@pytest.mark.parametrize("bad", ["nothing", "ZERO", 0, None, True, ["zero"]])
def test_config_rejects_other_values(bad: object) -> None:
    with pytest.raises(ConfigError, match=r"payout\.below_attachment"):
        parse_config(experiment(below_attachment=bad))


EXISTING_CONFIGS: dict[str, tuple[int, str]] = {
    "parity/configs/thesis.yaml": (
        1860,
        "82914fded05f23731bc108b102c8106e46a82b571a117cb2e0bf099e54b7541e",
    ),
    "research/data/annual-basis-rerun/thesis_event_conditional.yaml": (
        39,
        "3729f7a82c35fcbd9a4c038b7c7ec46460fed2217edc62894f9bc6f904282799",
    ),
    "research/data/annual-basis-rerun/thesis_event.yaml": (
        39,
        "dc17712cc68f80b92139920059e9742b65b1a3487fdd28cc31c2e328f5b065e4",
    ),
    "research/data/annual-basis-rerun/thesis_annual.yaml": (
        39,
        "d7da8ef99c74e9129c8124dd274dcde1e5a981a41719bb9d47141842fad34a37",
    ),
}
"""Every experiment config in the repository: the number of single runs and
sweep points, and the SHA-256 of their ``config_hash`` values joined by
newlines (single runs first, then each sweep's points in order), computed on
``main`` at ``f74f123``, before MAR-170."""


@pytest.mark.parametrize("path", sorted(EXISTING_CONFIGS))
def test_existing_configs_keep_their_hashes(path: str) -> None:
    file = REPO_ROOT / path
    if not file.is_file():
        pytest.skip(f"{path} is only in a repository checkout")
    assert "below_attachment" not in file.read_text(encoding="utf-8")
    config = load_config(file)
    assert config.payout.below_attachment == "first_bin"
    assert "below_attachment" not in dump_config(config)
    hashes = [config_hash(single) for single in config.single_runs()]
    for sweep in config.sweeps:
        points = sweep_points(config, sweep.parameter)
        hashes.extend(config_hash(point.config) for point in points)
    n, digest = EXISTING_CONFIGS[path]
    assert len(hashes) == n
    assert hashlib.sha256("\n".join(hashes).encode()).hexdigest() == digest
