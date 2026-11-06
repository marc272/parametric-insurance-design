"""Shared argument checks (private).

One implementation per check, so that every component validates its
parameters the same way and raises the same error type.
"""

from __future__ import annotations

import math
from typing import TypeVar

import numpy as np
from numpy.typing import ArrayLike, NDArray

from .errors import ParametricInputError

_T = TypeVar("_T", bound=np.generic)


def check_real(
    name: str,
    value: object,
    *,
    low: float = -math.inf,
    high: float = math.inf,
    include_low: bool = True,
    include_high: bool = True,
) -> float:
    """Return ``value`` as a float if it is a finite real number in range.

    Parameters
    ----------
    name : str
        Argument name, for the message.
    value : object
        The value to check. ``bool`` is refused.
    low, high : float
        Bounds of the range.
    include_low, include_high : bool
        Whether the bounds belong to the range.

    Returns
    -------
    float
        ``value``.

    Raises
    ------
    ParametricInputError
        If ``value`` is not a finite real number in the range.
    """
    if isinstance(value, bool) or not isinstance(value, int | float | np.number):
        raise ParametricInputError(f"{name} must be a real number, got {value!r}")
    number = float(value)  # pyright: ignore[reportArgumentType]
    above = number >= low if include_low else number > low
    below = number <= high if include_high else number < high
    if not (math.isfinite(number) and above and below):
        left = "[" if include_low else "("
        right = "]" if include_high else ")"
        raise ParametricInputError(
            f"{name} must be a finite number in {left}{low}, {high}{right}, "
            f"got {value!r}"
        )
    return number


def check_level(name: str, value: object) -> float:
    """Return a probability level in the open interval ``(0, 1)``.

    Parameters
    ----------
    name : str
        Argument name, for the message.
    value : object
        The level, e.g. a CVaR confidence level ``beta``.

    Returns
    -------
    float
        ``value``.

    Raises
    ------
    ParametricInputError
        If ``value`` is not a real number strictly between 0 and 1.
    """
    return check_real(
        name, value, low=0.0, high=1.0, include_low=False, include_high=False
    )


def finite_array(values: ArrayLike, name: str, ndim: int) -> NDArray[np.float64]:
    """Return ``values`` as a finite float array of dimension ``ndim``.

    Parameters
    ----------
    values : array_like
        The values.
    name : str
        Argument name, for the message.
    ndim : int
        The required number of dimensions.

    Returns
    -------
    numpy.ndarray
        A ``float64`` array (a copy if a conversion was needed).

    Raises
    ------
    ParametricInputError
        If the values are not numeric, have another dimension or are not
        finite.
    """
    try:
        arr = np.asarray(values, dtype=np.float64)
    except (TypeError, ValueError) as exc:
        raise ParametricInputError(f"{name} must be numeric: {exc}") from exc
    if arr.ndim != ndim:
        raise ParametricInputError(f"{name} must be {ndim}-D, got shape {arr.shape}")
    if not np.all(np.isfinite(arr)):
        raise ParametricInputError(f"{name} must be finite")
    return arr


def integer_array(values: ArrayLike, name: str) -> NDArray[np.int64]:
    """Return ``values`` as a 1-D ``int64`` array.

    Parameters
    ----------
    values : array_like of int
        The values. Floats are accepted only if they are whole numbers.
    name : str
        Argument name, for the message.

    Returns
    -------
    numpy.ndarray
        A 1-D ``int64`` array.

    Raises
    ------
    ParametricInputError
        If the values are not 1-D whole numbers.
    """
    arr = np.asarray(values)
    if arr.ndim != 1:
        raise ParametricInputError(f"{name} must be 1-D, got shape {arr.shape}")
    if arr.size and not np.issubdtype(arr.dtype, np.integer):
        if not np.issubdtype(arr.dtype, np.floating) or not np.all(
            np.isfinite(arr) & (arr == np.round(arr))
        ):
            raise ParametricInputError(f"{name} must hold whole numbers")
    return arr.astype(np.int64)


def read_only(arr: NDArray[_T]) -> NDArray[_T]:
    """Return a read-only copy of ``arr``."""
    out = np.array(arr, copy=True)
    out.setflags(write=False)
    return out
