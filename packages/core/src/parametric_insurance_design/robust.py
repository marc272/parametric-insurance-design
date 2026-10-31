"""Robust design under uncertainty (SPEC §6.5).

Owners, in sequence (ADR 0002): MAR-34 implements R1
(:func:`build_scenario_robust`); MAR-35 then implements R2
(:class:`DistributionallyRobust`), only if D6 = yes at checkpoint C1.

R1, scenario-robust: ``min_theta max_k F_k(theta)`` in epigraph form. One
:class:`~parametric_insurance_design.interfaces.ProblemContext` per scenario
EventSet, built with ``problem.build_context`` and a **shared** ``theta``;
the specs come from the reference scenario; the premium and the extra
constraints are built on the reference context.

R2, distributionally robust: wraps an objective and takes the worst case over
outcome weights in a ball around ``measure.probability``, using the
objective's decomposition ``probability @ per_outcome + offset``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import ClassVar, Literal

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Constraint,
    Objective,
    ObjectiveTerm,
    PayoutStructure,
    Pricing,
    ProblemContext,
    Sample,
    Scope,
)
from parametric_insurance_design.problem import BuiltProblem

__all__ = ["DistributionallyRobust", "build_scenario_robust"]


def build_scenario_robust(
    scenarios: Sequence[EventSet],
    scope: Scope,
    payout_structure: PayoutStructure,
    objective: Objective,
    pricing: Pricing,
    constraints: Sequence[Constraint] = (),
    *,
    basis: Basis,
    reference: int = 0,
    samples: Sequence[Sample] | None = None,
) -> tuple[BuiltProblem, ...]:
    """Assemble the R1 scenario-robust design problems.

    Parameters
    ----------
    scenarios : sequence of EventSet
        Scenario EventSets ``S_0 .. S_K`` with the same locations.
    scope : Scope
        Scope; it partitions the reference scenario.
    payout_structure : PayoutStructure
        Payout family.
    objective : Objective
        Objective ``F_k`` evaluated on every scenario.
    pricing : Pricing
        Pricing, applied on the reference scenario.
    constraints : sequence of Constraint, optional
        Extra constraints, built on the reference scenario.
    basis : Basis
        Evaluation basis.
    reference : int, default 0
        Index of the reference scenario.
    samples : sequence of Sample, optional
        Calibration sample per scenario. Default: all rows.

    Returns
    -------
    tuple of BuiltProblem
        One per design problem, solvable with ``solve.solve``. With one
        scenario the solution equals the nominal one.
    """
    raise NotImplementedError("MAR-34")  # pragma: no cover


@dataclass(frozen=True)
class DistributionallyRobust(Objective):
    """Worst case of an objective over outcome weights near the empirical ones.

    Parameters
    ----------
    inner : Objective
        The nominal objective.
    radius : float
        Radius ``rho >= 0`` of the ambiguity ball; ``0`` is the nominal case.
    ball : {"tv", "chi2"}, default "tv"
        Total variation (LP) or chi-squared (SOCP) ball.
    """

    name: ClassVar[str] = "distributionally_robust"

    inner: Objective
    radius: float
    ball: Literal["tv", "chi2"] = "tv"

    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        """See ``Objective.build``."""
        raise NotImplementedError("MAR-35")  # pragma: no cover
