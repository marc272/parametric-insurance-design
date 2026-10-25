"""Solver policy (SPEC §4.2, §3.1 C3).

Owner: MAR-14. :func:`solve` tries the policy's solvers in order and returns
a :class:`~parametric_insurance_design.interfaces.SolveResult` for the first
acceptable status. If none is acceptable it raises
:class:`~parametric_insurance_design.errors.SolveError` (or a subclass) with
every attempt attached. Nothing is swallowed or skipped (thesis issue C3).

The result types are defined in ``interfaces.py`` and re-exported here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from parametric_insurance_design.errors import (
    InfeasibleError,
    SolveError,
    UnboundedError,
)
from parametric_insurance_design.interfaces import (
    SolverAttempt,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.problem import BuiltProblem

__all__ = [
    "DEFAULT_POLICY",
    "InfeasibleError",
    "SolveError",
    "SolveResult",
    "SolveStatus",
    "SolverAttempt",
    "SolverPolicy",
    "UnboundedError",
    "solve",
]


@dataclass(frozen=True)
class SolverPolicy:
    """Which solvers to try, in which order.

    MAR-14 sets the default values; the fields are fixed by ADR 0002.

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
        20000}}``.
    """

    lp_solvers: tuple[str, ...] = ("CLARABEL", "HIGHS", "SCS")
    qp_solvers: tuple[str, ...] = ("OSQP", "CLARABEL")
    accept_inaccurate: bool = True
    solver_options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


DEFAULT_POLICY: SolverPolicy = SolverPolicy()
"""The default solver policy."""


def solve(built: BuiltProblem, policy: SolverPolicy = DEFAULT_POLICY) -> SolveResult:
    """Solve a built design problem.

    Parameters
    ----------
    built : BuiltProblem
        From ``problem.build_problems``.
    policy : SolverPolicy, optional
        Solver order and acceptance rule.

    Returns
    -------
    SolveResult
        The accepted solution, in loss units.

    Raises
    ------
    SolveError
        If no solver returns an acceptable status. :class:`InfeasibleError`
        and :class:`UnboundedError` for those final statuses.
    """
    raise NotImplementedError("MAR-14")  # pragma: no cover
