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

from numpy.typing import ArrayLike

from parametric_insurance_design.basis import OutcomeMeasure
from parametric_insurance_design.interfaces import Pricing, ProblemContext, Term

__all__ = ["CostOfCapitalLoad", "Pricing", "PurePremium"]


@dataclass(frozen=True)
class PurePremium(Pricing):
    """Expected payout."""

    name: ClassVar[str] = "pure"

    def premium(self, ctx: ProblemContext) -> Term:
        """See ``Pricing.premium``."""
        raise NotImplementedError("MAR-13")  # pragma: no cover

    def premium_value(self, payout: ArrayLike, measure: OutcomeMeasure) -> float:
        """See ``Pricing.premium_value``."""
        raise NotImplementedError("MAR-13")  # pragma: no cover


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
