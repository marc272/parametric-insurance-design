"""Objectives (SPEC §4.2, §6).

Owner: MAR-13. The interface is
:class:`~parametric_insurance_design.interfaces.Objective` (ADR 0002).

Every objective works on ``ctx.loss`` and ``ctx.payout`` (scaled, per row),
aggregates per-row quantities into outcomes with
``ctx.measure.aggregate_expression`` and weights them with
``ctx.measure.probability``. That keeps objectives basis-agnostic: the annual
basis (MAR-24) changes the measure, not this file.

With outcome probabilities ``p_o``, outcome loss ``L_o`` and outcome payout
``pi_o`` (sums over the rows of outcome ``o``; one row per outcome on the
``event_conditional`` basis):

* :class:`MSE`: mean squared signed residual
  ``sum_o p_o (L_o - pi_o)^2`` (QP, homogeneity 2).
* :class:`ExpectedUncovered`: ``E[U] = sum_o p_o U_o`` with
  ``U_o = sum_{e in o} (L_e - pi_e)^+`` (LP, homogeneity 1).
* :class:`WeightedCVaR`: ``alpha * CVaR_beta(U) + (1 - alpha) * E[U]`` in the
  Rockafellar-Uryasev form (LP, homogeneity 1).

On the ``event_conditional`` basis these are the thesis formulations
(``pure_basis_risk``, ``pure_uncovered_loss``, ``weighted_cvar``), with
``p`` the rates rescaled to sum to one. Loss scaling and the payout cap are
applied by ``problem.build_context``; objectives never see the scale.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import ClassVar, cast

import cvxpy as cp
import numpy as np
from numpy.typing import NDArray

from parametric_insurance_design.basis import PROBABILITY_ATOL
from parametric_insurance_design.errors import ComponentConfigError, InputMismatchError
from parametric_insurance_design.interfaces import (
    Objective,
    ObjectiveTerm,
    ProblemContext,
)

__all__ = [
    "MSE",
    "ExpectedUncovered",
    "Objective",
    "WeightedCVaR",
    "rockafellar_uryasev",
]


def _check_level(name: str, value: object) -> float:
    """Return ``value`` as a float if it is a real number in ``(0, 1)``.

    Raises
    ------
    ComponentConfigError
        If ``value`` is not a real number strictly between 0 and 1.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ComponentConfigError(f"{name} must be a real number, got {value!r}")
    level = float(value)
    if not (math.isfinite(level) and 0.0 < level < 1.0):
        raise ComponentConfigError(f"{name} must lie in (0, 1), got {value!r}")
    return level


def rockafellar_uryasev(
    values: cp.Expression, probability: NDArray[np.float64], beta: float
) -> tuple[cp.Expression, cp.Expression, cp.Variable]:
    """Rockafellar-Uryasev form of ``CVaR_beta`` over outcomes.

    Shared by :class:`WeightedCVaR` and ``pricing.CostOfCapitalLoad``.

    ``CVaR_beta(X) = min_zeta zeta + E[(X - zeta)^+] / (1 - beta)`` for a
    discrete ``X`` with outcome probabilities ``probability`` (Rockafellar
    and Uryasev, 2000). The expression returned is the function being
    minimised; it equals ``CVaR_beta(values)`` only once ``zeta`` is
    minimised over, so the caller must put it (with a positive weight) into a
    minimisation. ``excess`` is written with ``cvxpy.pos``, so it needs no
    extra constraints: cvxpy adds the epigraph variables
    ``u >= values - zeta``, ``u >= 0`` of the thesis itself.

    Parameters
    ----------
    values : cvxpy.Expression
        Outcome values, shape ``(n_outcomes,)``. Convex in the variables, for
        the result to be convex.
    probability : numpy.ndarray
        Outcome probabilities, shape ``(n_outcomes,)``, finite, >= 0 and
        summing to one within
        :data:`~parametric_insurance_design.basis.PROBABILITY_ATOL`.
    beta : float
        Confidence level in ``(0, 1)``. ``beta = 0.95`` is the mean of the
        worst 5 % of outcomes.

    Returns
    -------
    cvar : cvxpy.Expression
        Scalar ``zeta + probability @ excess``. Minimising over ``zeta``
        gives ``CVaR_beta(values)``.
    excess : cvxpy.Expression
        Shape ``(n_outcomes,)``: ``pos(values - zeta) / (1 - beta)``.
    zeta : cvxpy.Variable
        The scalar auxiliary (the VaR at the optimum).

    Raises
    ------
    ComponentConfigError
        If ``beta`` is not in ``(0, 1)``.
    InputMismatchError
        If ``values`` is not 1-D, or ``probability`` does not match it or is
        not a probability vector.
    """
    level = _check_level("beta", beta)
    if len(values.shape) != 1:
        raise InputMismatchError(
            f"values must be 1-D (one entry per outcome), got shape {values.shape}"
        )
    prob = np.asarray(probability, dtype=np.float64)
    if prob.shape != tuple(values.shape):
        raise InputMismatchError(
            f"probability must have shape {tuple(values.shape)}, got {prob.shape}"
        )
    if not np.all(np.isfinite(prob)) or np.any(prob < 0):
        raise InputMismatchError("probability must be finite and >= 0")
    total = float(prob.sum())
    if abs(total - 1.0) > PROBABILITY_ATOL:
        raise InputMismatchError(f"probability must sum to 1, got {total!r}")
    zeta = cp.Variable(name="cvar_zeta")
    excess = cp.pos(values - zeta) / (1.0 - level)
    cvar = zeta + prob @ excess
    return cvar, excess, zeta


def _uncovered_per_outcome(ctx: ProblemContext) -> cp.Expression:
    """Outcome uncovered loss ``U_o = sum_{e in o} (L_e - pi_e)^+``."""
    uncovered = cp.pos(ctx.loss - ctx.payout)
    return ctx.measure.aggregate_expression(uncovered)


def _expectation(ctx: ProblemContext, per_outcome: cp.Expression) -> cp.Expression:
    """Probability-weighted sum of an outcome expression."""
    return ctx.measure.probability @ per_outcome


@dataclass(frozen=True)
class MSE(Objective):
    """Mean squared signed residual (thesis ``pure_basis_risk``).

    ``sum_o p_o (L_o - pi_o)^2`` with the signed residual of each outcome, so
    over-payment counts as much as under-payment. A QP; homogeneity 2.

    On a basis that groups rows into outcomes (``annual``), the residual of
    an outcome is the outcome's loss minus its payout, summed over its rows
    before squaring. On ``event_conditional`` each row is an outcome, which
    is the thesis objective ``sum_e p_e (L_e - pi_e)^2``.
    """

    name: ClassVar[str] = "mse"

    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        """Build ``E[(L - pi)^2]`` over outcomes.

        Parameters
        ----------
        ctx : ProblemContext
            Scaled problem data and variables.

        Returns
        -------
        ObjectiveTerm
            ``per_outcome`` is the squared outcome residual, ``offset`` is 0,
            ``homogeneity`` is 2 and ``components`` holds ``"mse"``.
        """
        residual = ctx.measure.aggregate_expression(ctx.loss - ctx.payout)
        per_outcome = cp.square(residual)
        expression = _expectation(ctx, per_outcome)
        return ObjectiveTerm(
            expression=expression,
            per_outcome=per_outcome,
            homogeneity=2,
            components={"mse": expression},
        )


@dataclass(frozen=True)
class ExpectedUncovered(Objective):
    """Expected uncovered loss (thesis ``pure_uncovered_loss``).

    ``E[U] = sum_o p_o U_o`` with ``U_o = sum_{e in o} (L_e - pi_e)^+``:
    over-payment is not rewarded. An LP; homogeneity 1.
    """

    name: ClassVar[str] = "expected_uncovered"

    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        """Build ``E[U]`` over outcomes.

        Parameters
        ----------
        ctx : ProblemContext
            Scaled problem data and variables.

        Returns
        -------
        ObjectiveTerm
            ``per_outcome`` is ``U_o``, ``offset`` is 0, ``homogeneity`` is 1
            and ``components`` holds ``"expected_uncovered"``.
        """
        per_outcome = _uncovered_per_outcome(ctx)
        expression = _expectation(ctx, per_outcome)
        return ObjectiveTerm(
            expression=expression,
            per_outcome=per_outcome,
            homogeneity=1,
            components={"expected_uncovered": expression},
        )


@dataclass(frozen=True)
class WeightedCVaR(Objective):
    """Weighted CVaR of the uncovered loss (thesis ``weighted_cvar``).

    ``alpha * CVaR_beta(U) + (1 - alpha) * E[U]``, with ``CVaR_beta`` in the
    Rockafellar-Uryasev form (:func:`rockafellar_uryasev`) over the outcome
    uncovered losses ``U_o``. An LP; homogeneity 1.

    The outcome decomposition is ``per_outcome = alpha * excess + (1 - alpha)
    * U`` and ``offset = alpha * zeta``. With ``alpha = 0`` no CVaR auxiliary
    is created and the term is exactly :class:`ExpectedUncovered`'s.

    Parameters
    ----------
    alpha : float
        Weight of the CVaR term in ``[0, 1]``; ``alpha = 0`` gives E[U].
    beta : float
        CVaR confidence level in ``(0, 1)``.

    Raises
    ------
    ComponentConfigError
        If ``alpha`` is not in ``[0, 1]`` or ``beta`` not in ``(0, 1)``.
    """

    name: ClassVar[str] = "weighted_cvar"

    alpha: float
    beta: float

    def __post_init__(self) -> None:
        """Validate ``alpha`` and ``beta``."""
        alpha = self.alpha
        if isinstance(alpha, bool) or not isinstance(alpha, Real):
            raise ComponentConfigError(f"alpha must be a real number, got {alpha!r}")
        if not (math.isfinite(float(alpha)) and 0.0 <= float(alpha) <= 1.0):
            raise ComponentConfigError(f"alpha must lie in [0, 1], got {alpha!r}")
        beta = _check_level("beta", self.beta)
        object.__setattr__(self, "alpha", float(alpha))
        object.__setattr__(self, "beta", beta)

    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        """Build ``alpha * CVaR_beta(U) + (1 - alpha) * E[U]`` over outcomes.

        Parameters
        ----------
        ctx : ProblemContext
            Scaled problem data and variables.

        Returns
        -------
        ObjectiveTerm
            ``homogeneity`` is 1. ``components`` holds
            ``"expected_uncovered"`` and, if ``alpha > 0``, ``"cvar"`` (the
            Rockafellar-Uryasev expression, equal to ``CVaR_beta(U)`` at the
            optimum).
        """
        uncovered = _uncovered_per_outcome(ctx)
        expected = _expectation(ctx, uncovered)
        if self.alpha == 0.0:
            return ObjectiveTerm(
                expression=expected,
                per_outcome=uncovered,
                homogeneity=1,
                components={"expected_uncovered": expected},
            )
        cvar, excess, zeta = rockafellar_uryasev(
            uncovered, ctx.measure.probability, self.beta
        )
        alpha = self.alpha
        per_outcome = alpha * excess + (1.0 - alpha) * uncovered
        offset = cast(cp.Expression, alpha * zeta)
        return ObjectiveTerm(
            expression=_expectation(ctx, per_outcome) + offset,
            per_outcome=per_outcome,
            offset=offset,
            homogeneity=1,
            components={"cvar": cvar, "expected_uncovered": expected},
        )
