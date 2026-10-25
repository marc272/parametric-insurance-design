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

The builder checks that every assembled problem follows cvxpy's disciplined
convex programming (DCP) rules and raises :class:`ComponentConfigError` if
not, so a non-convex combination fails when it is built, not when it is
solved. Solving is :func:`parametric_insurance_design.solve.solve`'s job.

The MAR-14 issue text names a single ``build_problem``; ADR 0002 fixed the
interface as :func:`build_context` plus :func:`build_problems`, which returns
one :class:`BuiltProblem` per design problem (one per asset in the individual
scope).
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, cast

import cvxpy as cp
import numpy as np
import scipy.sparse as sp

from parametric_insurance_design.basis import Basis, OutcomeMeasure, outcome_measure
from parametric_insurance_design.errors import (
    ComponentConfigError,
    EntityMismatchError,
    InputMismatchError,
)
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

__all__ = ["MIN_SCALE_LOSS", "BuiltProblem", "build_context", "build_problems"]

MIN_SCALE_LOSS: Final[float] = 1e-6
"""Default scaling divides by the maximum loss only above this value (thesis
``scale_factor = max_loss if max_loss > 1e-6 else 1.0``)."""


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


def _default_scale(problem: DesignProblem) -> float:
    """Thesis scaling rule: the maximum objective-level loss, or 1."""
    max_loss = float(problem.loss.max(initial=0.0))
    return max_loss if max_loss > MIN_SCALE_LOSS else 1.0


def _check_scale(scale: object) -> float:
    """Return ``scale`` as a float if it is a finite real number > 0.

    Raises
    ------
    InputMismatchError
        If ``scale`` is not a finite real number > 0.
    """
    if isinstance(scale, bool) or not isinstance(scale, int | float | np.number):
        raise InputMismatchError(f"scale must be a real number, got {scale!r}")
    value = float(scale)
    if not (np.isfinite(value) and value > 0):
        raise InputMismatchError(f"scale must be finite and > 0, got {scale!r}")
    return value


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

    Every loss quantity is divided by the scale: the objective-level loss,
    the entity losses and the cap. The cap of entity ``j`` is its maximum
    loss over the problem's rows (thesis ``max_loss_per_asset``). Entity
    ``j``'s payout is ``basis_matrix(xi[:, j]) @ theta[j]``, with the basis
    matrix stored sparse; the objective-level payout is the sum over
    entities.

    Parameters
    ----------
    problem : DesignProblem
        Data in loss units.
    payout_structure : PayoutStructure
        Payout family of every entity.
    measure : OutcomeMeasure
        Measure over the problem's rows.
    scale : float, optional
        Loss scale factor, finite and > 0. Default: the thesis rule, the
        maximum objective-level loss, or 1 if it is <= :data:`MIN_SCALE_LOSS`.
    theta : cvxpy.Variable, optional
        Parameters to reuse, shape ``(n_entities, n_params)``. Default: a new
        variable named ``"theta"``.

    Returns
    -------
    ProblemContext
        Scaled data, the cap per entity and the payout expressions.

    Raises
    ------
    InputMismatchError
        If ``scale`` is not finite and > 0, ``theta`` has the wrong shape, the
        measure covers another number of rows, or the payout structure's
        basis matrix does not have shape ``(n_rows, n_params)``.
    """
    n_rows, n_entities = problem.n_rows, problem.n_entities
    n_params = payout_structure.n_params
    factor = _default_scale(problem) if scale is None else _check_scale(scale)
    if measure.n_rows != n_rows:
        raise InputMismatchError(
            f"measure covers {measure.n_rows} rows, the problem {n_rows}"
        )
    if theta is None:
        theta = cp.Variable((n_entities, n_params), name="theta")
    elif tuple(theta.shape) != (n_entities, n_params):
        raise InputMismatchError(
            f"theta must have shape {(n_entities, n_params)}, got {tuple(theta.shape)}"
        )
    columns: list[cp.Expression] = []
    for j in range(n_entities):
        basis = np.asarray(payout_structure.basis_matrix(problem.index[:, j]))
        if basis.shape != (n_rows, n_params):
            raise InputMismatchError(
                f"{payout_structure.name} basis matrix must have shape "
                f"{(n_rows, n_params)}, got {basis.shape}"
            )
        columns.append(cast(cp.Expression, sp.csr_matrix(basis) @ theta[j]))
    if n_entities == 1:
        payout = columns[0]
        entity_payout = cp.reshape(payout, (n_rows, 1), order="F")
    else:
        entity_payout = cp.vstack(columns).T
        payout = cast(cp.Expression, cp.sum(entity_payout, axis=1))
    return ProblemContext(
        problem=problem,
        payout_structure=payout_structure,
        measure=measure,
        scale=factor,
        theta=theta,
        entity_payout=entity_payout,
        payout=payout,
        loss=problem.loss / factor,
        entity_loss=problem.entity_loss / factor,
        cap=problem.entity_loss.max(axis=0, initial=0.0) / factor,
    )


def _check_specs(specs: Sequence[ProblemSpec]) -> tuple[ProblemSpec, ...]:
    """Return the specs as a tuple if they are non-empty with unique ids.

    Raises
    ------
    EntityMismatchError
        If there is no spec, an item is not a :class:`ProblemSpec`, or two
        specs share a ``problem_id``.
    """
    out = tuple(specs)
    if not out:
        raise EntityMismatchError("a scope must yield at least one design problem")
    for spec in out:
        if not isinstance(spec, ProblemSpec):
            raise EntityMismatchError(
                f"specs must be ProblemSpec objects, got {spec!r}"
            )
    ids = [spec.problem_id for spec in out]
    repeated = sorted({i for i in ids if ids.count(i) > 1})
    if repeated:
        raise EntityMismatchError(f"problem ids repeat: {repeated}")
    return out


def _assemble(
    ctx: ProblemContext,
    objective: Objective,
    pricing: Pricing,
    constraints: Sequence[Constraint],
) -> tuple[ObjectiveTerm, Term, cp.Problem]:
    """Build the terms, constraints and problem of one context (recipe 5-6).

    Raises
    ------
    ComponentConfigError
        If the assembled problem is not DCP (e.g. a concave objective).
    """
    term = objective.build(ctx)
    premium = pricing.premium(ctx)
    cons: list[cp.Constraint] = [
        *ctx.payout_structure.constraints(ctx.theta, ctx.cap),
        *term.constraints,
        *premium.constraints,
    ]
    for constraint in constraints:
        cons.extend(constraint.build(ctx, premium))
    problem = cp.Problem(cp.Minimize(term.expression), cons)
    if not problem.is_dcp():
        names = [c.name for c in constraints]
        raise ComponentConfigError(
            f"problem {ctx.problem.spec.problem_id!r}: {objective.name} with "
            f"{pricing.name} pricing and constraints {names} is not a convex "
            "(DCP) problem"
        )
    return term, premium, problem


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

    Follows the ADR 0002 recipe (module docstring). ``build_seconds`` of each
    problem covers materialising its data, building the context, the terms
    and the constraints, and the DCP check. The shared steps (sample
    selection, measure, partition) are not attributed to any one problem.
    cvxpy compiles a problem for its solver when it is solved, so that time
    is part of the solve time.

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

    Raises
    ------
    EntityMismatchError
        If there are no specs or two share a ``problem_id``; or (from the
        scope) a spec's locations are missing from the EventSet.
    InputMismatchError
        If the sample does not fit the EventSet or selects no rows.
    ComponentConfigError
        If a component rejects its input or the basis, or the combination is
        not a convex (DCP) problem.
    """
    sample = Sample.full(eventset) if sample is None else sample
    data = sample.select(eventset)
    measure = outcome_measure(data, basis, years=sample.years)
    chosen = _check_specs(scope.partition(data) if specs is None else specs)
    built: list[BuiltProblem] = []
    for spec in chosen:
        start = time.perf_counter()
        problem = scope.materialise(data, spec)
        ctx = build_context(problem, payout_structure, measure)
        term, premium, cvx_problem = _assemble(ctx, objective, pricing, constraints)
        built.append(
            BuiltProblem(
                context=ctx,
                objective=term,
                premium=premium,
                problem=cvx_problem,
                build_seconds=time.perf_counter() - start,
            )
        )
    return tuple(built)
