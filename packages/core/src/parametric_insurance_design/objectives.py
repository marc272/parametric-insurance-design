"""Objectives (SPEC §4.2, §6).

Owner: MAR-13. The interface is
:class:`~parametric_insurance_design.interfaces.Objective` (ADR 0002).

Every objective works on ``ctx.loss`` and ``ctx.payout`` (scaled, per row),
aggregates per-row quantities into outcomes with
``ctx.measure.aggregate_expression`` and weights them with
``ctx.measure.probability``. That keeps objectives basis-agnostic: the annual
basis (MAR-24) changes the measure, not this file.

* :class:`MSE`: mean squared signed residual ``E[(L - pi)^2]`` (QP).
* :class:`ExpectedUncovered`: ``E[U]`` with ``U = (L - pi)^+`` (LP).
* :class:`WeightedCVaR`: ``alpha * CVaR_beta(U) + (1 - alpha) * E[U]``
  (Rockafellar-Uryasev LP).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import cvxpy as cp
import numpy as np
from numpy.typing import NDArray

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


def rockafellar_uryasev(
    values: cp.Expression, probability: NDArray[np.float64], beta: float
) -> tuple[cp.Expression, cp.Expression, cp.Variable]:
    """Rockafellar-Uryasev form of ``CVaR_beta`` over outcomes.

    Shared by :class:`WeightedCVaR` and ``pricing.CostOfCapitalLoad``.

    Parameters
    ----------
    values : cvxpy.Expression
        Outcome values, shape ``(n_outcomes,)``.
    probability : numpy.ndarray
        Outcome probabilities, shape ``(n_outcomes,)``.
    beta : float
        Confidence level in ``(0, 1)``.

    Returns
    -------
    cvar : cvxpy.Expression
        Scalar ``zeta + probability @ excess``. Minimising over ``zeta``
        gives ``CVaR_beta(values)``.
    excess : cvxpy.Expression
        Shape ``(n_outcomes,)``: ``pos(values - zeta) / (1 - beta)``.
    zeta : cvxpy.Variable
        The scalar auxiliary (the VaR at the optimum).
    """
    raise NotImplementedError("MAR-13")  # pragma: no cover


@dataclass(frozen=True)
class MSE(Objective):
    """Mean squared signed residual (thesis ``pure_basis_risk``)."""

    name: ClassVar[str] = "mse"

    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        """See ``Objective.build``."""
        raise NotImplementedError("MAR-13")  # pragma: no cover


@dataclass(frozen=True)
class ExpectedUncovered(Objective):
    """Expected uncovered loss (thesis ``pure_uncovered_loss``)."""

    name: ClassVar[str] = "expected_uncovered"

    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        """See ``Objective.build``."""
        raise NotImplementedError("MAR-13")  # pragma: no cover


@dataclass(frozen=True)
class WeightedCVaR(Objective):
    """Weighted CVaR of the uncovered loss (thesis ``weighted_cvar``).

    Parameters
    ----------
    alpha : float
        Weight of the CVaR term in ``[0, 1]``; ``alpha = 0`` gives E[U].
    beta : float
        CVaR confidence level in ``(0, 1)``.
    """

    name: ClassVar[str] = "weighted_cvar"

    alpha: float
    beta: float

    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        """See ``Objective.build``."""
        raise NotImplementedError("MAR-13")  # pragma: no cover
