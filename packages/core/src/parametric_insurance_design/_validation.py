"""Shared parameter checks of the core components (private).

One implementation per check, so that every component reports a bad
parameter with the same error type and the same wording:

* :func:`check_real`: a real number, finite, optionally in an interval.
  Used for ``beta`` (``riskmeasures``, ``objectives``), ``alpha``
  (``objectives``), the budget loading (``constraints``), ``rate`` and ``q``
  (``pricing``), the attachment and limit (``payout``), ``beta_tail``
  (``clustering``) and the loss scale (``problem``).
* :func:`check_n_clusters`: a cluster count, an integer >= 1 and, given the
  number of locations, at most that. Used by ``scopes.Cluster`` and
  ``clustering.ThesisWardClustering.assign``.

Pure Python and numpy; imports only ``errors``, so every module of the core
can use it.
"""

from __future__ import annotations

import math
from numbers import Real

import numpy as np

from parametric_insurance_design.errors import (
    ComponentConfigError,
    InputMismatchError,
    ParametricInsuranceDesignError,
)

__all__ = ["check_n_clusters", "check_real"]


def _interval(low: float, high: float, include_low: bool, include_high: bool) -> str:
    """Format a bounded interval, e.g. ``(0, 1)`` or ``[0, 1]``."""
    left = "[" if include_low else "("
    right = "]" if include_high else ")"
    return f"{left}{low:g}, {high:g}{right}"


def check_real(
    name: str,
    value: object,
    *,
    low: float | None = None,
    high: float | None = None,
    include_low: bool = True,
    include_high: bool = True,
    error: type[ParametricInsuranceDesignError] = ComponentConfigError,
) -> float:
    """Return ``value`` as a float if it is a finite real number in range.

    The checks, in order, and their messages (``<v>`` is ``repr(value)``):

    1. ``value`` is a real number (:class:`numbers.Real`, numpy's included)
       and not a bool: else ``"<name> must be a real number, got <v>"``.
    2. Without ``low`` and ``high``: ``value`` is finite, else
       ``"<name> must be finite, got <v>"``.
    3. With one bound, e.g. ``low=0``: ``value`` is finite and in range, else
       ``"<name> must be finite and >= 0, got <v>"`` (``>``, ``<=`` or
       ``<`` as the bound says).
    4. With both bounds: ``value`` is finite, else
       ``"<name> must be finite, got <v>"``, and in the interval, else
       ``"<name> must lie in [0, 1], got <v>"`` (round brackets for an
       excluded end).

    Parameters
    ----------
    name : str
        The parameter's name as the message shows it, e.g. ``"beta"`` or
        ``"budget loading"``.
    value : object
        The value to check.
    low, high : float, optional
        Bounds of the allowed range; ``None`` leaves that side open.
    include_low, include_high : bool, default True
        Whether the bound itself is allowed.
    error : type, default ComponentConfigError
        The error raised, a subclass of ``ParametricInsuranceDesignError``.

    Returns
    -------
    float
        ``float(value)``.

    Raises
    ------
    ParametricInsuranceDesignError
        Of type ``error``, if a check fails.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise error(f"{name} must be a real number, got {value!r}")
    out = float(value)
    finite = math.isfinite(out)
    above = low is None or (out >= low if include_low else out > low)
    below = high is None or (out <= high if include_high else out < high)
    if low is not None and high is not None:
        if not finite:
            raise error(f"{name} must be finite, got {value!r}")
        if not (above and below):
            interval = _interval(low, high, include_low, include_high)
            raise error(f"{name} must lie in {interval}, got {value!r}")
        return out
    if low is not None:
        requirement = f" and {'>=' if include_low else '>'} {low:g}"
    elif high is not None:
        requirement = f" and {'<=' if include_high else '<'} {high:g}"
    else:
        requirement = ""
    if not (finite and above and below):
        raise error(f"{name} must be finite{requirement}, got {value!r}")
    return out


def check_n_clusters(n_clusters: object, n_locations: int | None = None) -> int:
    """Return a cluster count as an int if it is valid.

    Parameters
    ----------
    n_clusters : object
        The cluster count: an integer (numpy's included, not a bool) >= 1.
    n_locations : int, optional
        The number of locations to cluster; ``n_clusters`` may not exceed it.
        ``None`` skips this check.

    Returns
    -------
    int
        ``int(n_clusters)``.

    Raises
    ------
    ComponentConfigError
        If ``n_clusters`` is not an integer >= 1.
    InputMismatchError
        If ``n_clusters`` exceeds ``n_locations``.
    """
    if (
        isinstance(n_clusters, bool)
        or not isinstance(n_clusters, int | np.integer)
        or n_clusters < 1
    ):
        raise ComponentConfigError(
            f"n_clusters must be an integer >= 1, got {n_clusters!r}"
        )
    if n_locations is not None and n_clusters > n_locations:
        raise InputMismatchError(
            f"n_clusters={n_clusters} exceeds the {n_locations} locations"
        )
    return int(n_clusters)
