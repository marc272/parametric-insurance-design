"""Extra design-problem constraints (SPEC §6.4).

Owner: MAR-13. The interface is
:class:`~parametric_insurance_design.interfaces.Constraint` (ADR 0002).
Payout-family constraints (non-negative, monotone, cap) are not here: they
come from ``PayoutStructure.constraints``.

* :class:`Budget`: ``Premium(pi) <= loading * E[L]`` (thesis
  ``budget_loading``), with E[L] under the same outcome measure.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import cvxpy as cp

from parametric_insurance_design.interfaces import Constraint, ProblemContext, Term

__all__ = ["Budget", "Constraint"]


@dataclass(frozen=True)
class Budget(Constraint):
    """Premium budget relative to the expected loss.

    Parameters
    ----------
    loading : float
        ``kappa >= 0``: the premium may be at most ``kappa * E[L]``.
    """

    name: ClassVar[str] = "budget"

    loading: float

    def build(self, ctx: ProblemContext, premium: Term) -> tuple[cp.Constraint, ...]:
        """See ``Constraint.build``."""
        raise NotImplementedError("MAR-13")  # pragma: no cover
