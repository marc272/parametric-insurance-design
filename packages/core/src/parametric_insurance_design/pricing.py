"""Pricing components (SPEC §4.2, §6.4).

Owners, in sequence (ADR 0002): MAR-13 implements :class:`PurePremium`;
MAR-27 then implements :class:`CostOfCapitalLoad`, starting after MAR-13 is
merged. The interface is
:class:`~parametric_insurance_design.interfaces.Pricing`.

* :class:`PurePremium`: ``Premium = E[pi]`` under the outcome measure.
* :class:`CostOfCapitalLoad`: ``Premium = (1 - r) E[pi] + r CVaR_q(pi)``,
  convex for ``r`` in ``[0, 1]`` (still an LP). ``r = 0`` equals
  :class:`PurePremium`. Uses ``objectives.rockafellar_uryasev``.

A standard-deviation load (SOCP) is optional and would be another class here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import numpy as np
from numpy.typing import ArrayLike

from parametric_insurance_design.basis import OutcomeMeasure
from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.interfaces import Pricing, ProblemContext, Term

__all__ = ["CostOfCapitalLoad", "Pricing", "PurePremium"]


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
        values = np.asarray(payout, dtype=np.float64)
        if values.shape != (measure.n_rows,):
            raise InputMismatchError(
                f"payout must have shape ({measure.n_rows},), got {values.shape}"
            )
        if not np.all(np.isfinite(values)):
            raise InputMismatchError("payout must be finite")
        return measure.expectation(values)


@dataclass(frozen=True)
class CostOfCapitalLoad(Pricing):
    """Expected payout plus a cost-of-capital load on the payout tail.

    Parameters
    ----------
    rate : float
        Load ``r`` in ``[0, 1]``.
    q : float
        CVaR confidence level of the payout tail in ``(0, 1)``.
    """

    name: ClassVar[str] = "cost_of_capital"

    rate: float
    q: float

    def premium(self, ctx: ProblemContext) -> Term:
        """See ``Pricing.premium``."""
        raise NotImplementedError("MAR-27")  # pragma: no cover

    def premium_value(self, payout: ArrayLike, measure: OutcomeMeasure) -> float:
        """See ``Pricing.premium_value``."""
        raise NotImplementedError("MAR-27")  # pragma: no cover
