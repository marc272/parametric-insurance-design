"""Solver policy (SPEC §4.2, §3.1 C3).

:func:`solve` tries the policy's solvers in order and returns
a :class:`~parametric_insurance_design.interfaces.SolveResult` for the first
acceptable status. If none is acceptable it raises
:class:`~parametric_insurance_design.errors.SolveError` (or a subclass) with
every attempt attached. Nothing is swallowed or skipped (SPEC §3.1, C3).

The result types are defined in ``interfaces.py`` and re-exported here.

Default policy (:data:`DEFAULT_POLICY`)
    * LPs and other conic problems (E[U], weighted CVaR): ``CLARABEL``, then
      ``HIGHS``, then ``SCS`` with ``max_iters = 20000``. The thesis used
      Clarabel, then SCS with the same iteration limit.
    * QPs (MSE): ``OSQP``, then ``CLARABEL``, as in the thesis. OSQP runs
      with :data:`OSQP_OPTIONS` (``eps_abs = eps_rel = 1e-8``, ``max_iter =
      100000``), not with cvxpy's defaults (``1e-5`` and ``10000``) that the
      thesis used ("OSQP accuracy", below).
    * ``optimal_inaccurate`` is accepted (thesis).

OSQP accuracy
    OSQP is a first-order (ADMM) solver. With cvxpy's default ``eps = 1e-5``
    its solutions violate ``theta >= 0``, monotonicity, the cap and the
    budget by up to about ``1e-5`` in scaled units, and miss the optimal
    payouts by about as much, whenever OSQP's polishing step fails (on
    about a third of the MSE problems). The default policy therefore
    tightens OSQP to ``1e-8``, the accuracy of the interior-point solvers
    (Clarabel, HiGHS), so a solution meets the constraints to about
    ``1e-8`` in scaled units whichever solver of the policy produced it.
    The cost is more ADMM iterations: 8 to 13 times the MSE solve time on
    the parity fixture (``parity/BENCHMARK.md``). The MSE objective values
    there drop by up to ``9.1e-5`` relative, to the true optimum: the thesis
    MSE values carry OSQP's default inaccuracy. KPIs of the MSE payouts move
    more, by up to about 2 % at portfolio level, because the objective is
    flat at its optimum. To reproduce the thesis values, use
    :data:`THESIS_POLICY` (parity gate only).

A problem is a QP when its objective is quadratic but not piecewise linear
and cvxpy recognises the whole problem as a QP; every other problem goes to
the LP list.

The premium of a solution
    :func:`solve` records ``SolveResult.premium`` as ``pricing.premium_value``
    of the realised payout, with the pricing the problem was built with
    (``BuiltProblem.pricing``, which ``problem.build_problems`` sets):
    ``payout_structure.evaluate(index, theta)`` in loss units, summed over
    the entities as ``evaluate.kpis`` sums them, under the problem's
    measure. That is exact, needs no solver, and equals the in-sample
    ``premium`` KPI of the design problem bit for bit. ``solve(built)`` is
    enough. The optional ``pricing`` keyword is checked against it: a
    pricing that differs from the built one (``!=``: the pricing components
    are frozen dataclasses, equal when their class and fields are) raises
    :class:`~parametric_insurance_design.errors.ComponentConfigError` before
    any solver runs. Only a problem assembled by hand without a pricing
    (``BuiltProblem.pricing is None``) falls back: to ``premium_value``
    under the ``pricing`` given, unchecked since there is nothing to check
    it against, or else to the value of the premium term at the solution.
    That value is the pure premium up to rounding, but for a loaded premium
    (``pricing.CostOfCapitalLoad``) the Rockafellar-Uryasev bound at the
    solver's ``zeta``, exact only where the budget binds.

Solvers that are not installed are not called, but they are still recorded
as an attempt with status ``error`` and the message
:data:`NOT_INSTALLED`, so the attempt log shows every solver the policy
named up to the accepted one. This is how the policy copes with HiGHS
missing: cvxpy < 1.8 ships no ``highspy`` (e.g. the core's lowest-direct CI
job, ADR 0002), so the LP chain there is Clarabel, then SCS. If no solver of
the chosen list is installed, :func:`solve` raises :class:`SolveError` before
trying any.

Failure handling
    * An exception that cvxpy raises as :class:`cvxpy.error.SolverError`
      (solver crash, unsupported problem class) is recorded as an attempt
      with status ``solver_error`` and the exception text; the next solver
      is tried. Every other exception propagates unchanged: it is a bug, not
      a solver outcome.
    * A status cvxpy reports that :class:`SolveStatus` does not list (e.g.
      ``infeasible_or_unbounded``) is recorded as ``solver_error`` with the
      raw status in the message.
    * An accepted status without a finite solution is recorded as ``error``.
    * After the last solver, the final status is the most informative status
      among the attempts (:data:`FAILURE_PRECEDENCE`): an infeasibility or
      unboundedness certificate beats a numerical failure. It selects the
      error class: :class:`InfeasibleError`, :class:`UnboundedError`, or
      :class:`SolveError` for everything else.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Final, cast

import cvxpy as cp
import cvxpy.settings
import numpy as np
from cvxpy.error import SolverError
from numpy.typing import NDArray

from parametric_insurance_design.errors import (
    ComponentConfigError,
    ConfigError,
    InfeasibleError,
    SolveError,
    UnboundedError,
)
from parametric_insurance_design.interfaces import (
    Pricing,
    SolverAttempt,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.problem import BuiltProblem

__all__ = [
    "DEFAULT_POLICY",
    "FAILURE_PRECEDENCE",
    "NOT_INSTALLED",
    "OSQP_OPTIONS",
    "THESIS_POLICY",
    "InfeasibleError",
    "SolveError",
    "SolveResult",
    "SolveStatus",
    "SolverAttempt",
    "SolverPolicy",
    "UnboundedError",
    "is_qp",
    "solve",
]

NOT_INSTALLED: Final[str] = "solver not installed"
"""Message of the attempt recorded for a solver that is not installed."""

FAILURE_PRECEDENCE: Final[tuple[SolveStatus, ...]] = (
    SolveStatus.INFEASIBLE,
    SolveStatus.UNBOUNDED,
    SolveStatus.INFEASIBLE_INACCURATE,
    SolveStatus.UNBOUNDED_INACCURATE,
    SolveStatus.OPTIMAL_INACCURATE,
    SolveStatus.USER_LIMIT,
    SolveStatus.SOLVER_ERROR,
    SolveStatus.ERROR,
)
"""Order in which a failure status is reported, most informative first.

``optimal_inaccurate`` is a failure only if the policy does not accept it."""

_INFEASIBLE: Final = frozenset(
    {SolveStatus.INFEASIBLE, SolveStatus.INFEASIBLE_INACCURATE}
)
_UNBOUNDED: Final = frozenset({SolveStatus.UNBOUNDED, SolveStatus.UNBOUNDED_INACCURATE})


OSQP_OPTIONS: Final[Mapping[str, Any]] = MappingProxyType(
    {"eps_abs": 1e-8, "eps_rel": 1e-8, "max_iter": 100_000}
)
"""Default OSQP options: interior-point accuracy for MSE solutions.

cvxpy's defaults are ``eps_abs = eps_rel = 1e-5`` and ``max_iter = 10000``.
The parity MSE problems need up to about 15,000 iterations at ``1e-8`` and the
engine's property tests up to about 25,000; ``max_iter`` leaves room above
that. If OSQP still stops at the limit, it reports ``optimal_inaccurate``
(accepted by default) or ``user_limit`` (Clarabel is tried next). Polishing
stays on (cvxpy's default)."""


def _default_options() -> Mapping[str, Mapping[str, Any]]:
    """Default solver options: :data:`OSQP_OPTIONS` and the thesis SCS limit."""
    return {"OSQP": dict(OSQP_OPTIONS), "SCS": {"max_iters": 20000}}


@dataclass(frozen=True)
class SolverPolicy:
    """Which solvers to try, in which order.

    Parameters
    ----------
    lp_solvers : tuple of str
        cvxpy solver names for LPs (and other conic problems), tried in order.
    qp_solvers : tuple of str
        cvxpy solver names for QPs (the MSE objective), tried in order.
    accept_inaccurate : bool
        Whether ``optimal_inaccurate`` counts as success (thesis: yes).
    solver_options : mapping of str to mapping, optional
        Keyword arguments per solver name, e.g. ``{"SCS": {"max_iters":
        20000}}``. Default: :data:`OSQP_OPTIONS` for OSQP (module docstring) and that
        SCS limit (thesis). Passing a mapping replaces the default as a
        whole, so a solver left out runs with cvxpy's defaults. Stored
        read-only.

    Raises
    ------
    ConfigError
        If a solver list is empty, repeats a name or names a solver cvxpy
        does not know, or an option key is not a cvxpy solver name. Options
        for a solver outside both lists are allowed and unused.

    Notes
    -----
    A policy can be pickled, e.g. to send it to a worker process:
    it is pickled as its class and fields, with the options as plain dicts,
    and unpickling calls the class again, so the copy is validated and its
    options are read-only again. The copy is equal to the original and has
    the same fingerprint (``experiment.runner.policy_fingerprint``), so the
    same run ids. :func:`copy.copy` and :func:`copy.deepcopy` work the same
    way.
    """

    lp_solvers: tuple[str, ...] = ("CLARABEL", "HIGHS", "SCS")
    qp_solvers: tuple[str, ...] = ("OSQP", "CLARABEL")
    accept_inaccurate: bool = True
    solver_options: Mapping[str, Mapping[str, Any]] = field(
        default_factory=_default_options
    )

    def __post_init__(self) -> None:
        """Validate the solver names and freeze the options."""
        known = set(cvxpy.settings.SOLVERS)
        for name in ("lp_solvers", "qp_solvers"):
            solvers = tuple(getattr(self, name))
            if not solvers:
                raise ConfigError(f"{name} must name at least one solver")
            if not all(isinstance(s, str) for s in solvers):
                raise ConfigError(f"{name} must hold solver names, got {solvers!r}")
            if len(set(solvers)) != len(solvers):
                raise ConfigError(f"{name} repeats a solver: {solvers!r}")
            unknown = sorted(set(solvers) - known)
            if unknown:
                raise ConfigError(f"{name}: cvxpy knows no solver {unknown}")
            object.__setattr__(self, name, solvers)
        if not isinstance(self.accept_inaccurate, bool):
            raise ConfigError(
                f"accept_inaccurate must be a bool, got {self.accept_inaccurate!r}"
            )
        unknown = sorted(set(self.solver_options) - known)
        if unknown:
            raise ConfigError(f"solver_options: cvxpy knows no solver {unknown}")
        frozen = {k: MappingProxyType(dict(v)) for k, v in self.solver_options.items()}
        object.__setattr__(self, "solver_options", MappingProxyType(frozen))

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle the policy as its class and fields (class docstring, Notes).

        ``MappingProxyType`` cannot be pickled, so the options go as plain
        dicts; :func:`_rebuild_policy` freezes them again.
        """
        values = {
            f.name: getattr(self, f.name) for f in dataclasses.fields(self) if f.init
        }
        values["solver_options"] = {
            solver: dict(options) for solver, options in self.solver_options.items()
        }
        return (_rebuild_policy, (type(self), values))

    @property
    def accepted(self) -> frozenset[SolveStatus]:
        """Statuses that produce a :class:`SolveResult`."""
        if self.accept_inaccurate:
            return frozenset({SolveStatus.OPTIMAL, SolveStatus.OPTIMAL_INACCURATE})
        return frozenset({SolveStatus.OPTIMAL})

    def solvers_for(self, problem: cp.Problem) -> tuple[str, ...]:
        """Return the solver list for a problem: QP or LP (see :func:`is_qp`).

        Parameters
        ----------
        problem : cvxpy.Problem
            The problem to solve.

        Returns
        -------
        tuple of str
            :attr:`qp_solvers` for a QP, :attr:`lp_solvers` otherwise.
        """
        return self.qp_solvers if is_qp(problem) else self.lp_solvers


def _rebuild_policy(cls: type[SolverPolicy], values: dict[str, Any]) -> SolverPolicy:
    """Unpickle a :class:`SolverPolicy`: call its class with its fields."""
    return cls(**values)


DEFAULT_POLICY: SolverPolicy = SolverPolicy()
"""The default solver policy (module docstring)."""

THESIS_POLICY: SolverPolicy = SolverPolicy(solver_options={"SCS": {"max_iters": 20000}})
"""Solver policy that reproduces the thesis solves; for the parity gate only.

The same solver lists and acceptance rule as :data:`DEFAULT_POLICY`, with
OSQP at cvxpy's defaults (``eps_abs = eps_rel =
1e-5``, ``max_iter = 10000``) as in the thesis. Its MSE solutions carry
that inaccuracy (module docstring, "OSQP accuracy"); use
:data:`DEFAULT_POLICY` for everything but comparing with the thesis."""


def is_qp(problem: cp.Problem) -> bool:
    """Whether a problem is a quadratic, not a linear, program.

    Parameters
    ----------
    problem : cvxpy.Problem
        The problem.

    Returns
    -------
    bool
        True if the objective is quadratic but not piecewise linear and the
        problem as a whole is a QP for cvxpy.
    """
    expr = problem.objective.expr
    return bool(expr.is_quadratic() and not expr.is_pwl() and problem.is_qp())


def _status(raw: object) -> tuple[SolveStatus, str | None]:
    """Map a cvxpy status to :class:`SolveStatus`, with a message if unknown."""
    try:
        return SolveStatus(str(raw)), None
    except ValueError:
        return SolveStatus.SOLVER_ERROR, f"unrecognised cvxpy status {raw!r}"


def _try(built: BuiltProblem, solver: str, options: Mapping[str, Any]) -> SolverAttempt:
    """Call one solver and record the outcome; only SolverError is caught."""
    problem = built.problem
    start = time.perf_counter()
    try:
        problem.solve(solver=solver, verbose=False, **options)
    except SolverError as exc:
        return SolverAttempt(
            solver,
            SolveStatus.SOLVER_ERROR,
            time.perf_counter() - start,
            f"{type(exc).__name__}: {exc}",
        )
    seconds = time.perf_counter() - start
    status, message = _status(problem.status)
    return SolverAttempt(solver, status, seconds, message)


def _has_finite_solution(built: BuiltProblem) -> bool:
    """Whether theta and the objective have finite values."""
    theta = built.context.theta.value
    value = built.objective.expression.value
    return (
        theta is not None
        and value is not None
        and bool(np.all(np.isfinite(theta)))
        and bool(np.isfinite(value))
    )


def _value(expression: cp.Expression) -> float:
    """Return the value of a solved scalar expression as a float.

    Only called after :func:`_has_finite_solution`, so every expression of
    the problem has a value.
    """
    return float(cast(Any, expression.value))


def _diagnostics(built: BuiltProblem) -> dict[str, float]:
    """Objective components in loss units, plus solver statistics."""
    ctx, term, problem = built.context, built.objective, built.problem
    unscale = ctx.scale**term.homogeneity
    out = {name: _value(expr) * unscale for name, expr in term.components.items()}
    stats = problem.solver_stats
    for name in ("solve_time", "setup_time", "num_iters"):
        value = getattr(stats, name, None) if stats is not None else None
        if value is not None:
            out[f"solver_{name}"] = float(value)
    violations = [
        float(np.max(c.violation(), initial=0.0)) for c in problem.constraints
    ]
    out["max_constraint_violation_scaled"] = max(violations, default=0.0)
    return out


def _pricing(built: BuiltProblem, pricing: Pricing | None) -> Pricing | None:
    """Return the pricing whose ``premium_value`` :func:`solve` records, if any.

    ``built.pricing`` unless ``pricing`` is given; a given ``pricing`` must
    equal it (module docstring, "The premium of a solution").

    Raises
    ------
    ComponentConfigError
        If ``pricing`` is not a :class:`Pricing`, or differs from
        ``built.pricing``.
    """
    if pricing is None:
        return built.pricing
    if not isinstance(pricing, Pricing):
        raise ComponentConfigError(f"pricing must be a Pricing, got {pricing!r}")
    built_with = built.pricing
    if built_with is not None and pricing is not built_with and pricing != built_with:
        raise ComponentConfigError(
            f"problem {built.spec.problem_id!r} was built with pricing "
            f"{built_with!r}, not {pricing!r}; solve(built) records the premium "
            "under the built pricing"
        )
    return pricing


def _premium(
    built: BuiltProblem, theta: NDArray[np.float64], pricing: Pricing | None
) -> float:
    """Premium of the solution in loss units (module docstring).

    ``theta`` is in loss units. With a pricing (from :func:`_pricing`),
    ``premium_value`` of the realised objective-level payout, summed over
    the entities one vector after the other as ``evaluate`` does; otherwise
    the premium term's value times ``scale``.
    """
    ctx = built.context
    if pricing is None:
        return _value(built.premium.expression) * ctx.scale
    entity_payout = ctx.payout_structure.evaluate(ctx.problem.index, theta)
    payout = np.vstack(list(entity_payout.T)).sum(axis=0)
    return float(pricing.premium_value(payout, ctx.measure))


def _result(
    built: BuiltProblem, attempts: list[SolverAttempt], pricing: Pricing | None
) -> SolveResult:
    """Package the accepted solution in loss units."""
    ctx, term = built.context, built.objective
    value = built.context.theta.value
    assert value is not None  # guarded by _has_finite_solution
    theta = np.asarray(value, dtype=np.float64) * ctx.scale
    accepted = attempts[-1]
    return SolveResult(
        spec=built.spec,
        payout_structure=ctx.payout_structure,
        theta=theta,
        status=accepted.status,
        objective_value=_value(term.expression) * ctx.scale**term.homogeneity,
        premium=_premium(built, theta, pricing),
        scale=ctx.scale,
        solver=accepted.solver,
        attempts=tuple(attempts),
        build_seconds=built.build_seconds,
        solve_seconds=sum(a.seconds for a in attempts),
        diagnostics=_diagnostics(built),
    )


def _failure(problem_id: str, attempts: list[SolverAttempt]) -> SolveError:
    """Build the error for a problem that no solver solved acceptably."""
    statuses = {a.status for a in attempts}
    final = next(s for s in FAILURE_PRECEDENCE if s in statuses)
    log = "; ".join(
        f"{a.solver}: {a.status.value}" + (f" ({a.message})" if a.message else "")
        for a in attempts
    )
    message = f"no solver returned an acceptable result [{log}]"
    cls = (
        InfeasibleError
        if final in _INFEASIBLE
        else UnboundedError
        if final in _UNBOUNDED
        else SolveError
    )
    return cls(message, problem_id=problem_id, status=final, attempts=attempts)


def solve(
    built: BuiltProblem,
    policy: SolverPolicy = DEFAULT_POLICY,
    *,
    pricing: Pricing | None = None,
) -> SolveResult:
    """Solve a built design problem.

    Parameters
    ----------
    built : BuiltProblem
        From ``problem.build_problems``.
    policy : SolverPolicy, optional
        Solver order and acceptance rule.
    pricing : Pricing, optional
        Not needed: the premium is ``premium_value`` of the solution's
        realised payout under ``built.pricing``, the pricing
        ``build_problems`` built it with, exact and without a solver call.
        If given, it must equal ``built.pricing``. For a problem without a pricing
        (``built.pricing is None``, assembled by hand) it is the pricing of
        the premium, unchecked; without either, the premium is the premium
        term's value (module docstring, "The premium of a solution").

    Returns
    -------
    SolveResult
        The accepted solution, in loss units: ``theta * scale``, the
        objective value times ``scale ** homogeneity``, and the premium
        (``pricing`` above). ``solve_seconds`` is the wall time of every
        attempt, including cvxpy's compilation. ``diagnostics`` holds the
        objective components (loss units), the accepted solver's statistics
        (``solver_solve_time``, ``solver_setup_time``, ``solver_num_iters``
        where it reports them) and the largest constraint violation in scaled
        units (``max_constraint_violation_scaled``).

    Raises
    ------
    SolveError
        If no solver returns an acceptable status, or no solver of the chosen
        list is installed. :class:`InfeasibleError` and
        :class:`UnboundedError` for those final statuses. ``attempts`` holds
        every solver of the list, in order.
    ComponentConfigError
        If ``pricing`` is given but is not a :class:`Pricing`, or differs
        from ``built.pricing``; raised before any solver runs.
    """
    pricing = _pricing(built, pricing)
    problem_id = built.spec.problem_id
    solvers = policy.solvers_for(built.problem)
    installed = set(cp.installed_solvers())
    if not installed.intersection(solvers):
        raise SolveError(
            f"none of the policy's solvers {list(solvers)} is installed "
            f"(installed: {sorted(installed)})",
            problem_id=problem_id,
            status=SolveStatus.ERROR,
        )
    attempts: list[SolverAttempt] = []
    for solver in solvers:
        if solver not in installed:
            attempts.append(
                SolverAttempt(solver, SolveStatus.ERROR, 0.0, NOT_INSTALLED)
            )
            continue
        attempt = _try(built, solver, policy.solver_options.get(solver, {}))
        if attempt.status in policy.accepted and not _has_finite_solution(built):
            attempt = SolverAttempt(
                solver,
                SolveStatus.ERROR,
                attempt.seconds,
                f"status {attempt.status.value!r} without a finite solution",
            )
        attempts.append(attempt)
        if attempt.status in policy.accepted:
            return _result(built, attempts, pricing)
    raise _failure(problem_id, attempts)
