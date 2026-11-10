"""Errors of the parametric insurance module.

Every error derives from :class:`ParametricError`. Input errors are also
:class:`ValueError` and a missing optional dependency is also an
:class:`ImportError`, so callers that catch the built-in types keep working.
"""

from __future__ import annotations

__all__ = [
    "CalibrationError",
    "MissingDependencyError",
    "ParametricError",
    "ParametricInputError",
]


class ParametricError(Exception):
    """Base class of the module's errors."""


class ParametricInputError(ParametricError, ValueError):
    """An argument is invalid, or two inputs do not match.

    Examples: index values that are not finite, an ``Impact`` whose events
    are not the index's events, or frequencies that do not fit the annual
    basis.
    """


class CalibrationError(ParametricError, RuntimeError):
    """A design problem could not be solved.

    Parameters
    ----------
    message : str
        What went wrong.
    problem_id : str
        The design problem: a unit id, or ``"portfolio"``.
    status : str, optional
        The solver's status, if it returned one.
    """

    def __init__(
        self, message: str, *, problem_id: str, status: str | None = None
    ) -> None:
        super().__init__(f"design problem {problem_id!r}: {message}")
        self.problem_id = problem_id
        self.status = status


class MissingDependencyError(ParametricError, ImportError):
    """An optional dependency that the requested feature needs is missing."""
