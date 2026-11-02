"""Extra design-problem constraints (SPEC §6.4).

The interface is :class:`~parametric_insurance_design.interfaces.Constraint`
(ADR 0002).
Payout-family constraints (non-negative, monotone, cap) are not here: they
come from ``PayoutStructure.constraints``.

* :class:`Budget`: ``Premium(pi) <= loading * E[L]`` (thesis
  ``budget_loading``), with E[L] under the same outcome measure.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from numbers import Real
from typing import ClassVar

import cvxpy as cp

from parametric_insurance_design.errors import ComponentConfigError
from parametric_insurance_design.interfaces import Constraint, ProblemContext, Term

__all__ = ["Budget", "Constraint"]


@dataclass(frozen=True)
class Budget(Constraint):
    """Premium budget relative to the expected loss.

    ``Premium(pi) <= kappa * E[L]``, where ``E[L]`` is
    ``ctx.expected_loss``: the objective-level loss under the same outcome
    measure as the premium and the objective. Both sides are in scaled units,
    so the constraint is the thesis budget ``p @ pi <= kappa * p @ L``.

    Parameters
    ----------
    loading : float
        ``kappa >= 0``: the premium may be at most ``kappa * E[L]``.

    Raises
    ------
    ComponentConfigError
        If ``loading`` is not a finite real number >= 0.
    """

    name: ClassVar[str] = "budget"

    loading: float

    def __post_init__(self) -> None:
        """Validate ``loading``."""
        loading = self.loading
        if isinstance(loading, bool) or not isinstance(loading, Real):
            raise ComponentConfigError(
                f"budget loading must be a real number, got {loading!r}"
            )
        if not (math.isfinite(float(loading)) and float(loading) >= 0.0):
            raise ComponentConfigError(
                f"budget loading must be finite and >= 0, got {loading!r}"
            )
        object.__setattr__(self, "loading", float(loading))

    def build(self, ctx: ProblemContext, premium: Term) -> tuple[cp.Constraint, ...]:
        """Build ``premium <= loading * E[L]``.

        Parameters
        ----------
        ctx : ProblemContext
            Scaled problem data and variables.
        premium : Term
            The pricing component's premium; its own constraints are added by
            the builder, not here.

        Returns
        -------
        tuple of cvxpy.Constraint
            The single budget constraint.

        Raises
        ------
        ComponentConfigError
            If the premium expression is not convex, so the budget would not
            be a convex (DCP) constraint.
        """
        if not premium.expression.is_convex():
            raise ComponentConfigError(
                "the budget needs a convex premium expression; got a non-convex one"
            )
        return (premium.expression <= self.loading * ctx.expected_loss,)
