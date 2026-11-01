"""Design a cover in one call (ADR 0004, Q2).

:func:`design` builds every design problem of a scope and solves each one. It
is a plain composition of the low-level path::

    built = problem.build_problems(eventset, scope, payout, objective, pricing,
                                   constraints, basis=basis, sample=sample)
    results = tuple(solve.solve(b, policy) for b in built)

and gives the same results. The pricing is given once: every built problem
carries it, so :func:`~parametric_insurance_design.solve.solve` records the
exact premium of each solution (``SolveResult.premium``) without being given
it again.

The low-level path stays for LP-level work: inspecting or changing the cvxpy
problem of a :class:`~parametric_insurance_design.problem.BuiltProblem`,
reusing the specs of another run (``build_problems(..., specs=...)``), or
keeping the solved problems when one of them fails.
"""

from __future__ import annotations

from collections.abc import Sequence

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Constraint,
    Objective,
    PayoutStructure,
    Pricing,
    Sample,
    Scope,
    SolveResult,
)
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.problem import build_problems
from parametric_insurance_design.solve import DEFAULT_POLICY, SolverPolicy, solve

__all__ = ["design"]


def design(
    eventset: EventSet,
    scope: Scope,
    payout: PayoutStructure,
    objective: Objective,
    *,
    basis: Basis,
    pricing: Pricing = PurePremium(),  # noqa: B008 (frozen, so safe to share)
    constraints: Sequence[Constraint] = (),
    sample: Sample | None = None,
    policy: SolverPolicy = DEFAULT_POLICY,
) -> tuple[SolveResult, ...]:
    """Design the payout functions of a scope: build every problem, solve each.

    Parameters
    ----------
    eventset : EventSet
        Full EventSet.
    scope : Scope
        Which assets share a design problem and a payout function, e.g.
        ``Individual()`` (one problem per asset), ``Portfolio()`` or
        ``Cluster(ThesisWardClustering(), n_clusters)`` (one joint problem).
    payout : PayoutStructure
        Payout family, e.g. ``StepPayout(attachment, limit, n_bins)``.
    objective : Objective
        What the design minimises, e.g. ``WeightedCVaR(alpha, beta)``,
        ``ExpectedUncovered()`` or ``MSE()``.
    basis : Basis
        Probability basis of the objective, the premium and the constraints.
        Required, so that every call states it.
    pricing : Pricing, default PurePremium()
        Premium of a payout, e.g. ``CostOfCapitalLoad(rate, q)``. Given once:
        each built problem carries it, and each result's ``premium`` is the
        exact premium of its payout under it.
    constraints : sequence of Constraint, default ()
        Extra constraints, e.g. ``(Budget(1.0),)``. Default: none, so the
        premium is unconstrained.
    sample : Sample, optional
        Calibration rows, e.g. the ``train`` sample of
        :func:`~parametric_insurance_design.splits.holdout`. Default: all
        rows.
    policy : SolverPolicy, default DEFAULT_POLICY
        Solver order and acceptance rule
        (:data:`~parametric_insurance_design.solve.DEFAULT_POLICY`).

    Returns
    -------
    tuple of SolveResult
        One per design problem, in the order of the scope's partition: one
        per asset in the individual scope, one (``problem_id ==
        "portfolio"``) in the portfolio and cluster scopes. The same results
        as :func:`~parametric_insurance_design.problem.build_problems`
        followed by :func:`~parametric_insurance_design.solve.solve` with
        ``policy`` on each problem.

    Raises
    ------
    EntityMismatchError
        If the scope's partition is empty or its locations are missing from
        the EventSet.
    InputMismatchError
        If the sample does not fit the EventSet or selects no rows.
    ComponentConfigError
        If a component rejects its input or the basis, or the combination is
        not a convex (DCP) problem.
    SolveError
        If no solver of the policy solves one of the problems
        (:class:`~parametric_insurance_design.solve.InfeasibleError` and
        :class:`~parametric_insurance_design.solve.UnboundedError` for those
        statuses). Its ``problem_id`` names the problem; the problems solved
        before it are not returned. Every problem is built before the first
        is solved, so a build error comes before any solve.

    Examples
    --------
    One payout function per asset, calibrated jointly (the portfolio scope)
    on the first 70 % of the years of the parity fixture, with the tail-risk
    objective and a premium budget of the expected loss (run from the
    repository root):

    >>> import parametric_insurance_design as pid
    >>> es = pid.EventSet.from_parquet("parity/tests/data/thesis_eventset")
    >>> train, test = pid.splits.holdout(es)
    >>> (result,) = pid.design(
    ...     es,
    ...     pid.Portfolio(),
    ...     pid.StepPayout(attachment=20.0, limit=70.0, n_bins=15),
    ...     pid.WeightedCVaR(alpha=0.9, beta=0.95),
    ...     basis=pid.Basis.ANNUAL,
    ...     constraints=(pid.Budget(1.0),),
    ...     sample=train,
    ... )
    >>> result.problem_id, result.theta.shape
    ('portfolio', (9, 15))
    """
    built = build_problems(
        eventset,
        scope,
        payout,
        objective,
        pricing,
        constraints,
        basis=basis,
        sample=sample,
    )
    return tuple(solve(b, policy) for b in built)
