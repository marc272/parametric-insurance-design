"""Pricing components (SPEC §4.2, §6.4).

Owners, in sequence (ADR 0002): MAR-13 implemented :class:`PurePremium`;
MAR-27 implemented :class:`CostOfCapitalLoad`. The interface is
:class:`~parametric_insurance_design.interfaces.Pricing`.

* :class:`PurePremium`: ``Premium = E[pi]`` under the outcome measure.
* :class:`CostOfCapitalLoad`: ``Premium = (1 - r) E[pi] + r CVaR_q(pi)``
  (thesis issue M4), convex for ``r`` in ``[0, 1]`` (still an LP). ``r = 0``
  is exactly :class:`PurePremium`. The CVaR uses
  ``objectives.rockafellar_uryasev``.

Both price the objective-level payout of one design problem, aggregated into
outcomes by the measure: ``pi_o = sum_{e in o} pi_e`` (one row per outcome on
the ``event_conditional`` basis). How a run's portfolio premium is formed from
a pricing is ``evaluate.kpis``'s business; see ``docs/methodology/pricing.md``.

A standard-deviation load (SOCP) is not implemented; it would be another
class here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import ClassVar, cast

import cvxpy as cp
import numpy as np
from cvxpy.transforms.partial_optimize import partial_optimize
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import OutcomeMeasure
from parametric_insurance_design.errors import ComponentConfigError, InputMismatchError
from parametric_insurance_design.evaluate import var_cvar
from parametric_insurance_design.interfaces import Pricing, ProblemContext, Term
from parametric_insurance_design.objectives import rockafellar_uryasev

__all__ = ["CostOfCapitalLoad", "Pricing", "PurePremium"]


def _check_payout(payout: ArrayLike, measure: OutcomeMeasure) -> NDArray[np.float64]:
    """Return ``payout`` as a float array if it is finite with one entry per row.

    Raises
    ------
    InputMismatchError
        If ``payout`` is not 1-D with ``measure.n_rows`` entries, or not
        finite.
    """
    values = np.asarray(payout, dtype=np.float64)
    if values.shape != (measure.n_rows,):
        raise InputMismatchError(
            f"payout must have shape ({measure.n_rows},), got {values.shape}"
        )
    if not np.all(np.isfinite(values)):
        raise InputMismatchError("payout must be finite")
    return values


@dataclass(frozen=True)
class PurePremium(Pricing):
    """Expected payout: ``Premium = E[pi] = sum_o p_o pi_o``.

    ``pi_o`` is the objective-level payout summed over the rows of outcome
    ``o`` (one row per outcome on the ``event_conditional`` basis, which is
    the thesis premium ``sum_e p_e pi_e``). Linear in ``theta``; adds no
    constraints.
    """

    name: ClassVar[str] = "pure"

    def premium(self, ctx: ProblemContext) -> Term:
        """Return the expected objective-level payout under ``ctx.measure``.

        Parameters
        ----------
        ctx : ProblemContext
            Scaled problem data and variables.

        Returns
        -------
        Term
            Affine scalar ``probability @ aggregate(ctx.payout)``, scaled
            units, without constraints.
        """
        per_outcome = ctx.measure.aggregate_expression(ctx.payout)
        return Term(expression=ctx.measure.probability @ per_outcome)

    def premium_value(self, payout: ArrayLike, measure: OutcomeMeasure) -> float:
        """Return the expected value of a realised payout.

        Parameters
        ----------
        payout : array_like of float
            Objective-level payout per row, shape ``(n_rows,)``.
        measure : OutcomeMeasure
            Measure over the same rows.

        Returns
        -------
        float
            ``probability @ aggregate(payout)``, same units as ``payout``.

        Raises
        ------
        InputMismatchError
            If ``payout`` is not 1-D with ``measure.n_rows`` entries, or not
            finite.
        """
        return measure.expectation(_check_payout(payout, measure))


@dataclass(frozen=True)
class CostOfCapitalLoad(Pricing):
    """Expected payout plus a cost-of-capital load on the payout tail.

    ``Premium = (1 - r) E[pi] + r CVaR_q(pi)`` (SPEC §6.4, thesis issue M4),
    with ``pi_o`` the objective-level payout of outcome ``o`` and ``CVaR_q``
    the mean of the worst ``1 - q`` probability mass of ``pi`` (the exact
    discrete CVaR, :func:`~parametric_insurance_design.evaluate.var_cvar`).
    The load ``r (CVaR_q(pi) - E[pi])`` prices the risk capital a writer
    holds against the payout tail, so a tail-heavy payout costs more than
    its expected value: ``E[pi] <= Premium <= CVaR_q(pi)``.

    Convex in the payout for ``r`` in ``[0, 1]`` (a non-negative mix of a
    linear and a convex function), so the budget ``Premium <= kappa E[L]``
    keeps the design problem an LP (QP with the MSE objective). Positively
    homogeneous of degree 1, so loss scaling carries through.

    ``r = 0`` returns :class:`PurePremium`'s term itself (no auxiliary
    variable), so it gives the same problem, solution and premium as
    :class:`PurePremium`.

    Parameters
    ----------
    rate : float
        Cost-of-capital rate ``r`` in ``[0, 1]``. Paper defaults 0.06-0.10.
    q : float
        CVaR confidence level of the payout tail, in ``(0, 1)``. Paper
        default 0.99.

    Raises
    ------
    ComponentConfigError
        If ``rate`` is not a real number in ``[0, 1]`` or ``q`` not a real
        number in ``(0, 1)``.

    Notes
    -----
    In the problem the CVaR is the Rockafellar-Uryasev minimum
    ``min_zeta zeta + E[(pi - zeta)^+] / (1 - q)``
    (:func:`~parametric_insurance_design.objectives.rockafellar_uryasev`).
    It is wrapped in a cvxpy partial minimisation over ``zeta``
    (``cvxpy.transforms.partial_optimize``): cvxpy inlines the auxiliaries
    ``zeta`` and ``u_o >= pi_o - zeta``, ``u_o >= 0`` into the LP when it
    compiles the problem, so the LP is exactly the Rockafellar-Uryasev one.
    The wrapper makes the term's value at a solution the CVaR itself, not the
    Rockafellar-Uryasev bound at whatever ``zeta`` the solver returned (only
    tight when the budget binds), so ``SolveResult.premium`` is the true
    loaded premium of the solution, budget binding or not, and is defined
    without a budget. Reading that value solves the small inner LP over
    ``zeta`` with ``theta`` fixed, with cvxpy's default solver.
    """

    name: ClassVar[str] = "cost_of_capital"

    rate: float
    q: float

    def __post_init__(self) -> None:
        """Validate ``rate`` and ``q`` (also outside the config path)."""
        rate = _real("rate", self.rate)
        if not 0.0 <= rate <= 1.0:
            raise ComponentConfigError(f"rate must lie in [0, 1], got {self.rate!r}")
        q = _real("q", self.q)
        if not 0.0 < q < 1.0:
            raise ComponentConfigError(f"q must lie in (0, 1), got {self.q!r}")
        object.__setattr__(self, "rate", rate)
        object.__setattr__(self, "q", q)

    def premium(self, ctx: ProblemContext) -> Term:
        """Return ``(1 - r) E[pi] + r CVaR_q(pi)`` of ``ctx.payout``.

        Parameters
        ----------
        ctx : ProblemContext
            Scaled problem data and variables.

        Returns
        -------
        Term
            Convex scalar premium, scaled units, without constraints of its
            own (the Rockafellar-Uryasev auxiliaries live inside the partial
            minimisation; class notes). With ``rate = 0`` it is
            :class:`PurePremium`'s affine term.
        """
        pure = PurePremium().premium(ctx)
        if self.rate == 0.0:
            return pure
        per_outcome = ctx.measure.aggregate_expression(ctx.payout)
        cvar, _, zeta = rockafellar_uryasev(
            per_outcome, ctx.measure.probability, self.q
        )
        inner = cp.Problem(cp.Minimize(cvar))
        tail = partial_optimize(
            inner,
            opt_vars=[zeta],
            dont_opt_vars=[v for v in inner.variables() if v.id != zeta.id],
        )
        expression = cast(
            cp.Expression, (1.0 - self.rate) * pure.expression + self.rate * tail
        )
        return Term(expression=expression)

    def premium_value(self, payout: ArrayLike, measure: OutcomeMeasure) -> float:
        """Return the loaded premium of a realised payout.

        Parameters
        ----------
        payout : array_like of float
            Objective-level payout per row, shape ``(n_rows,)``.
        measure : OutcomeMeasure
            Measure over the same rows.

        Returns
        -------
        float
            ``(1 - r) E[pi] + r CVaR_q(pi)`` over the measure's outcomes,
            same units as ``payout``; ``E[pi]`` (bit for bit
            :meth:`PurePremium.premium_value`) if ``rate = 0``.

        Raises
        ------
        InputMismatchError
            If ``payout`` is not 1-D with ``measure.n_rows`` entries, or not
            finite.
        """
        values = _check_payout(payout, measure)
        expected = measure.expectation(values)
        if self.rate == 0.0:
            return expected
        _, cvar = var_cvar(measure.aggregate(values), measure.probability, self.q)
        return (1.0 - self.rate) * expected + self.rate * cvar


def _real(name: str, value: object) -> float:
    """Return ``value`` as a float if it is a finite real number.

    Raises
    ------
    ComponentConfigError
        If ``value`` is a bool, not a real number, or not finite.
    """
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ComponentConfigError(f"{name} must be a real number, got {value!r}")
    out = float(value)
    if not math.isfinite(out):
        raise ComponentConfigError(f"{name} must be finite, got {value!r}")
    return out
