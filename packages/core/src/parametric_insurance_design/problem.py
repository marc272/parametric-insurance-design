"""Problem builder: scope x payout x objective x pricing x constraints (SPEC §4.2).

Owner: MAR-14. Replaces the thesis's nine near-duplicate solver methods
(thesis issue C1) with one assembly, fixed by ADR 0002:

1. ``data = sample.select(eventset)`` (default :meth:`Sample.full`).
2. ``measure = outcome_measure(data, basis, years=sample.years)``.
3. ``specs = scope.partition(data)`` unless ``specs`` is given.
4. For each spec: ``problem = scope.materialise(data, spec)`` and
   ``ctx = build_context(problem, payout_structure, measure)``.
5. ``objective_term = objective.build(ctx)``; ``premium = pricing.premium(ctx)``;
   constraints = ``payout_structure.constraints(ctx.theta, ctx.cap)`` +
   ``objective_term.constraints`` + ``premium.constraints`` +
   ``c.build(ctx, premium)`` for each extra constraint.
6. ``cp.Problem(cp.Minimize(objective_term.expression), constraints)``.

Loss scaling and the payout cap are decided in :func:`build_context` (thesis:
scale by the maximum objective-level loss, or 1 if it is <= 1e-6; cap each
entity at its maximum loss). Components never see the scale.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cvxpy as cp

from parametric_insurance_design.basis import Basis, OutcomeMeasure
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Constraint,
    DesignProblem,
    Objective,
    ObjectiveTerm,
    PayoutStructure,
    Pricing,
    ProblemContext,
    ProblemSpec,
    Sample,
    Scope,
    Term,
)

__all__ = ["BuiltProblem", "build_context", "build_problems"]


@dataclass(frozen=True, eq=False)
class BuiltProblem:
    """A design problem assembled and ready to solve.

    Parameters
    ----------
    context : ProblemContext
        Scaled data and variables.
    objective : ObjectiveTerm
        The objective term.
    premium : Term
        The premium term.
    problem : cvxpy.Problem
        The assembled problem.
    build_seconds : float
        Wall time of the assembly.
    """

    context: ProblemContext
    objective: ObjectiveTerm
    premium: Term
    problem: cp.Problem
    build_seconds: float

    @property
    def spec(self) -> ProblemSpec:
        """The design problem's entities."""
        return self.context.problem.spec


def build_context(
    problem: DesignProblem,
    payout_structure: PayoutStructure,
    measure: OutcomeMeasure,
    *,
    scale: float | None = None,
    theta: cp.Variable | None = None,
) -> ProblemContext:
    """Scale a design problem and create its variables.

    Public so that ``robust.py`` can build one context per scenario with a
    shared ``theta`` and the reference scenario's ``scale``.

    Parameters
    ----------
    problem : DesignProblem
        Data in loss units.
    payout_structure : PayoutStructure
        Payout family of every entity.
    measure : OutcomeMeasure
        Measure over the problem's rows.
    scale : float, optional
        Loss scale factor. Default: the thesis rule (see module docstring).
    theta : cvxpy.Variable, optional
        Parameters to reuse, shape ``(n_entities, n_params)``. Default: new.

    Returns
    -------
    ProblemContext
        Scaled data, the cap per entity and the payout expressions.
    """
    raise NotImplementedError("MAR-14")  # pragma: no cover


def build_problems(
    eventset: EventSet,
    scope: Scope,
    payout_structure: PayoutStructure,
    objective: Objective,
    pricing: Pricing,
    constraints: Sequence[Constraint] = (),
    *,
    basis: Basis,
    sample: Sample | None = None,
    specs: Sequence[ProblemSpec] | None = None,
) -> tuple[BuiltProblem, ...]:
    """Assemble every design problem of a scope.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    scope : Scope
        Scope.
    payout_structure : PayoutStructure
        Payout family.
    objective : Objective
        Objective.
    pricing : Pricing
        Pricing used for the premium term.
    constraints : sequence of Constraint, optional
        Extra constraints, e.g. ``(Budget(1.0),)``.
    basis : Basis
        Evaluation basis of the objective, premium and budget.
    sample : Sample, optional
        Calibration rows. Default: all rows.
    specs : sequence of ProblemSpec, optional
        Reuse these specs instead of calling ``scope.partition``.

    Returns
    -------
    tuple of BuiltProblem
        One per design problem, in ``specs`` order.
    """
    raise NotImplementedError("MAR-14")  # pragma: no cover
