"""Risk measures of discrete distributions: VaR, CVaR, lower quantiles.

Owner: MAR-143 (ADR 0002 §10). Pure numpy, below both the problem
components and the evaluation: ``pricing.CostOfCapitalLoad`` prices a
realised payout with :func:`var_cvar`, and ``evaluate`` reports it (KPIs) and
uses :func:`lower_quantile` for the exceedance curves, so both read one
definition. ``evaluate`` re-exports :func:`var_cvar`; it lived there until
MAR-143.

Quantiles on a step of the distribution: strict, as in the thesis
    The VaR is the smallest value whose cumulative probability reaches
    ``beta``, and :func:`lower_quantile` (so :func:`var_cvar` and the
    exceedance curves) compares the cumulative probability with the level
    **exactly**, as the thesis ``calculate_var_cvar`` and
    ``_weighted_quantile`` do. When the level falls exactly on a step of the
    distribution (e.g. ``beta = 0.8`` with 40 equally likely years, or
    ``beta = 0.95`` with a multiple of 20 equally likely events), the summed
    probabilities land a rounding error above or below it, depending on the
    summation order of tied rows (``numpy.argsort`` of tied values, which
    differs between platforms, e.g. Linux and macOS). The result is then
    either of the two adjacent atoms: the exact-arithmetic lower one or the
    next one up. Kept strict so that the parity reports stay byte-identical
    with the thesis golden values (MAR-143, orchestrator decision: option
    B; a tolerance moved 162 ``VaR_Uncovered`` values of the asset-count
    sweep to the lower atom). Making the quantile platform-independent is
    tracked as a follow-up.

    The bootstrap (``bootstrap.py``, MAR-23) does use a tolerance,
    :data:`CDF_ATOL`, in its vectorised VaR, and accepts either adjacent
    atom when it checks its point values against ``evaluate.kpis``.
"""

from __future__ import annotations

import math
from numbers import Real
from typing import Final

import numpy as np
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import PROBABILITY_ATOL
from parametric_insurance_design.errors import ComponentConfigError, InputMismatchError

__all__ = [
    "CDF_ATOL",
    "check_beta",
    "discrete_distribution",
    "lower_quantile",
    "sorted_cdf",
    "var_cvar",
]

CDF_ATOL: Final[float] = 1e-10
"""Tolerance of the bootstrap's VaR on a step (``bootstrap.py`` only).

In the bootstrap's vectorised VaR, a cumulative probability within this of
``beta`` counts as reaching it (the exact-arithmetic quantile).
:func:`lower_quantile` and :func:`var_cvar` do **not** use it: they compare
strictly, as the thesis (module docstring). Far below any probability step
of the data (an outcome of probability ``1e-10`` would need ten billion
equally likely outcomes) and far above the rounding of a cumulative sum of
probabilities (about ``n * 1e-16``)."""


def check_beta(beta: object) -> float:
    """Return ``beta`` as a float if it is a real number in ``(0, 1)``.

    Parameters
    ----------
    beta : object
        Confidence level.

    Returns
    -------
    float
        ``beta``.

    Raises
    ------
    ComponentConfigError
        If ``beta`` is not a real number strictly between 0 and 1.
    """
    if isinstance(beta, bool) or not isinstance(beta, Real):
        raise ComponentConfigError(f"beta must be a real number, got {beta!r}")
    level = float(beta)
    if not (math.isfinite(level) and 0.0 < level < 1.0):
        raise ComponentConfigError(f"beta must lie in (0, 1), got {beta!r}")
    return level


def discrete_distribution(
    values: ArrayLike, probability: ArrayLike
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Validate a discrete distribution; return it with normalised weights.

    The weights are divided by their sum, as the thesis does, so that
    rounding in the measure does not move the quantiles.

    Parameters
    ----------
    values : array_like of float
        Outcome values, shape ``(n_outcomes,)``.
    probability : array_like of float
        Outcome probabilities, same shape.

    Returns
    -------
    values, probability : numpy.ndarray
        The values, and the probabilities divided by their sum.

    Raises
    ------
    InputMismatchError
        If the arrays are not 1-D of one non-zero length, values are not
        finite, or the probabilities are negative, not finite or do not sum
        to one within :data:`~parametric_insurance_design.basis.PROBABILITY_ATOL`.
    """
    x = np.asarray(values, dtype=np.float64)
    p = np.asarray(probability, dtype=np.float64)
    if x.ndim != 1 or x.size == 0:
        raise InputMismatchError(f"values must be a non-empty 1-D array, got {x.shape}")
    if p.shape != x.shape:
        raise InputMismatchError(
            f"probability must have shape {x.shape}, got {p.shape}"
        )
    if not np.all(np.isfinite(x)):
        raise InputMismatchError("values must be finite")
    if not np.all(np.isfinite(p)) or np.any(p < 0):
        raise InputMismatchError("probability must be finite and >= 0")
    total = float(p.sum())
    if abs(total - 1.0) > PROBABILITY_ATOL:
        raise InputMismatchError(f"probability must sum to 1, got {total!r}")
    return x, p / total


def sorted_cdf(
    x: NDArray[np.float64], p: NDArray[np.float64]
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Values in ascending order, their probabilities and the cumulative sum.

    ``np.argsort`` with its default kind, as the thesis, so that ties are
    summed in the same order on one platform. Across platforms the order of
    ties can differ, which can move a quantile on an exact step (module
    docstring).

    Parameters
    ----------
    x, p : numpy.ndarray
        Values and probabilities, as :func:`discrete_distribution` returns
        them.

    Returns
    -------
    sorted_x, sorted_p, cdf : numpy.ndarray
        The sorted values, their probabilities and the cumulative sum of the
        probabilities.
    """
    order = np.argsort(x)
    sorted_x = x[order]
    sorted_p = p[order]
    return sorted_x, sorted_p, np.cumsum(sorted_p)


def lower_quantile(
    sorted_x: NDArray[np.float64], cdf: NDArray[np.float64], level: float
) -> float:
    """Smallest value whose cumulative probability reaches ``level``.

    The cumulative probability is compared with ``level`` exactly, as in
    the thesis; on an exact step the result depends on the summation order
    of tied values (module docstring). If rounding keeps the last cumulative
    probability below ``level``, the largest value is returned (thesis
    behaviour).

    Parameters
    ----------
    sorted_x, cdf : numpy.ndarray
        Sorted values and cumulative probabilities, from :func:`sorted_cdf`.
    level : float
        Probability level, in ``(0, 1)``.

    Returns
    -------
    float
        The lower ``level``-quantile.
    """
    pos = int(np.searchsorted(cdf, level, side="left"))
    return float(sorted_x[min(pos, sorted_x.shape[0] - 1)])


def var_cvar(
    values: ArrayLike, probability: ArrayLike, beta: float
) -> tuple[float, float]:
    """VaR and CVaR of a discrete distribution (thesis ``calculate_var_cvar``).

    ``VaR_beta`` is the lower ``beta``-quantile: the smallest value ``v``
    with ``P(X <= v) >= beta`` (:func:`lower_quantile`, compared strictly,
    as the thesis; see the module docstring for a ``beta`` exactly on a
    step). ``CVaR_beta``
    is the Rockafellar-Uryasev value ``VaR + E[(X - VaR)^+] / (1 - beta)``,
    i.e. the mean of the worst ``1 - beta`` probability mass, with the atom
    at the VaR split as needed:

    ``CVaR = (sum_{x > VaR} p x + (1 - beta - P(X > VaR)) VaR) / (1 - beta)``,

    and ``CVaR = VaR`` if no mass lies above the VaR.

    Parameters
    ----------
    values : array_like of float
        Outcome values, shape ``(n_outcomes,)``. Finite.
    probability : array_like of float
        Outcome probabilities, same shape, >= 0, summing to one within
        :data:`~parametric_insurance_design.basis.PROBABILITY_ATOL`. They are
        divided by their sum before use, as in the thesis.
    beta : float
        Confidence level in ``(0, 1)``.

    Returns
    -------
    var, cvar : float
        Value-at-risk and conditional value-at-risk at ``beta``.

    Raises
    ------
    ComponentConfigError
        If ``beta`` is not in ``(0, 1)``.
    InputMismatchError
        If the arrays do not form a discrete distribution.

    Examples
    --------
    >>> var_cvar([0.0, 1.0, 2.0, 10.0], [0.25, 0.25, 0.25, 0.25], 0.5)
    (1.0, 6.0)
    """
    level = check_beta(beta)
    x, p = discrete_distribution(values, probability)
    sorted_x, sorted_p, cdf = sorted_cdf(x, p)
    var = lower_quantile(sorted_x, cdf, level)
    tail = sorted_x > var
    tail_prob = float(np.sum(sorted_p[tail]))
    if tail_prob > 0:
        cvar = (
            np.sum(sorted_p[tail] * sorted_x[tail]) + (1 - level - tail_prob) * var
        ) / (1 - level)
    else:
        cvar = var
    return var, float(cvar)
