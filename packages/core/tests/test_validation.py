"""Tests for the shared parameter checks (``_validation.py``, MAR-177)."""

from __future__ import annotations

import math
from fractions import Fraction

import numpy as np
import pytest

from parametric_insurance_design._validation import check_n_clusters, check_real
from parametric_insurance_design.errors import (
    ComponentConfigError,
    InputMismatchError,
)

OPEN_UNIT = {"low": 0.0, "high": 1.0, "include_low": False, "include_high": False}


# --------------------------------------------------------------------------
# check_real
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value", [0.5, 1, np.float32(0.25), np.float64(0.75), np.int64(0), Fraction(1, 3)]
)
def test_check_real_returns_a_float(value: object) -> None:
    out = check_real("x", value)
    assert type(out) is float
    assert out == float(value)  # type: ignore[arg-type]


@pytest.mark.parametrize("value", [True, np.bool_(False), "0.5", None, 1j, [0.5]])
def test_check_real_rejects_a_non_real(value: object) -> None:
    with pytest.raises(ComponentConfigError, match=r"^x must be a real number, got "):
        check_real("x", value)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_check_real_without_bounds_rejects_a_non_finite_value(value: float) -> None:
    with pytest.raises(ComponentConfigError) as info:
        check_real("limit", value)
    assert str(info.value) == f"limit must be finite, got {value!r}"


@pytest.mark.parametrize(
    ("kwargs", "value", "message"),
    [
        ({"low": 0.0}, -0.1, "loading must be finite and >= 0, got -0.1"),
        ({"low": 0.0}, math.nan, "loading must be finite and >= 0, got nan"),
        ({"low": 0.0}, math.inf, "loading must be finite and >= 0, got inf"),
        (
            {"low": 0.0, "include_low": False},
            0.0,
            "loading must be finite and > 0, got 0.0",
        ),
        ({"high": 2.0}, 2.5, "loading must be finite and <= 2, got 2.5"),
        (
            {"high": 2.0, "include_high": False},
            2.0,
            "loading must be finite and < 2, got 2.0",
        ),
        ({"high": 2.0}, -math.inf, "loading must be finite and <= 2, got -inf"),
    ],
)
def test_check_real_with_one_bound(
    kwargs: dict[str, object], value: float, message: str
) -> None:
    with pytest.raises(ComponentConfigError) as info:
        check_real("loading", value, **kwargs)  # type: ignore[arg-type]
    assert str(info.value) == message


def test_check_real_with_one_bound_accepts_the_bound_when_included() -> None:
    assert check_real("loading", 0, low=0.0) == 0.0
    assert check_real("loading", 2, high=2.0) == 2.0


@pytest.mark.parametrize(
    ("kwargs", "value", "message"),
    [
        ({"low": 0.0, "high": 1.0}, -0.01, "p must lie in [0, 1], got -0.01"),
        ({"low": 0.0, "high": 1.0}, 1.5, "p must lie in [0, 1], got 1.5"),
        (OPEN_UNIT, 0.0, "p must lie in (0, 1), got 0.0"),
        (OPEN_UNIT, 1, "p must lie in (0, 1), got 1"),
        (
            {"low": 0.0, "high": 1.0, "include_high": False},
            1.0,
            "p must lie in [0, 1), got 1.0",
        ),
        (
            {"low": 0.5, "high": 2.5, "include_low": False},
            0.5,
            "p must lie in (0.5, 2.5], got 0.5",
        ),
        (OPEN_UNIT, math.nan, "p must be finite, got nan"),
        ({"low": 0.0, "high": 1.0}, math.inf, "p must be finite, got inf"),
    ],
)
def test_check_real_with_two_bounds(
    kwargs: dict[str, object], value: float, message: str
) -> None:
    with pytest.raises(ComponentConfigError) as info:
        check_real("p", value, **kwargs)  # type: ignore[arg-type]
    assert str(info.value) == message


def test_check_real_with_two_bounds_accepts_included_ends() -> None:
    assert check_real("p", 0, low=0.0, high=1.0) == 0.0
    assert check_real("p", 1, low=0.0, high=1.0) == 1.0
    assert check_real("p", 0.5, **OPEN_UNIT) == 0.5  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["2", 0.0, math.nan])
def test_check_real_raises_the_given_error_type(value: object) -> None:
    with pytest.raises(InputMismatchError, match="scale"):
        check_real("scale", value, low=0.0, include_low=False, error=InputMismatchError)


# --------------------------------------------------------------------------
# check_n_clusters
# --------------------------------------------------------------------------


@pytest.mark.parametrize("n", [1, 3, np.int64(2), np.int32(4)])
def test_check_n_clusters_returns_an_int(n: object) -> None:
    out = check_n_clusters(n)
    assert type(out) is int
    assert out == n


@pytest.mark.parametrize("n", [0, -1, True, 2.0, "2", None])
def test_check_n_clusters_rejects_a_non_count(n: object) -> None:
    with pytest.raises(ComponentConfigError) as info:
        check_n_clusters(n, 5)
    assert str(info.value) == f"n_clusters must be an integer >= 1, got {n!r}"


def test_check_n_clusters_against_the_locations() -> None:
    assert check_n_clusters(3, 3) == 3
    with pytest.raises(InputMismatchError) as info:
        check_n_clusters(4, 3)
    assert str(info.value) == "n_clusters=4 exceeds the 3 locations"
    assert check_n_clusters(4) == 4  # no location count, no upper check
