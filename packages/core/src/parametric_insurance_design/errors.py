"""Error hierarchy of the core library (ADR 0002).

Every error the core raises on purpose derives from
:class:`ParametricInsuranceDesignError`, so callers can catch the whole library
with one ``except`` clause. Each error also derives from the closest built-in
(``ValueError`` or ``RuntimeError``), so code that catches those keeps working.

::

    ParametricInsuranceDesignError
    ├── ComponentConfigError (ValueError)      invalid component parameters
    │   └── UnsupportedBasisError              component cannot use this basis
    ├── ConfigError (ValueError)               invalid experiment configuration
    ├── InputMismatchError (ValueError)        arrays, ids or samples do not line up
    │   └── EntityMismatchError                missing or mismatched entities
    ├── SolveError (RuntimeError)              no acceptable solver result
    │   ├── InfeasibleError
    │   └── UnboundedError
    └── RecordSchemaError (ValueError)         result-store table breaks its schema

EventSet validation errors live in :mod:`parametric_insurance_design.eventset`
and derive from :class:`~parametric_insurance_design.eventset.EventSetError`
(a ``ValueError``). Since MAR-82, ``EventSetError`` also derives from
:class:`ParametricInsuranceDesignError`, so one ``except`` catches the whole library.

Changing this module needs an ADR 0002 amendment. An implementing module may
define further subclasses of these classes in its own file.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from parametric_insurance_design.interfaces import SolverAttempt, SolveStatus

__all__ = [
    "ComponentConfigError",
    "ConfigError",
    "EntityMismatchError",
    "InfeasibleError",
    "InputMismatchError",
    "ParametricInsuranceDesignError",
    "RecordSchemaError",
    "SolveError",
    "UnboundedError",
    "UnsupportedBasisError",
]


class ParametricInsuranceDesignError(Exception):
    """Base class for every error the core library raises on purpose."""


class ComponentConfigError(ParametricInsuranceDesignError, ValueError):
    """A component got invalid parameters.

    Examples: ``beta`` outside ``(0, 1)`` for a CVaR objective, ``n_bins < 1``
    for a step payout, or a negative budget loading.
    """


class UnsupportedBasisError(ComponentConfigError):
    """A component does not support the requested evaluation basis."""


class ConfigError(ParametricInsuranceDesignError, ValueError):
    """An experiment configuration is invalid (unknown keys, bad values)."""


class InputMismatchError(ParametricInsuranceDesignError, ValueError):
    """Inputs do not line up.

    Raised for wrong array shapes, unknown or repeated ids, or a sample whose
    rows and years do not belong together.
    """


class EntityMismatchError(InputMismatchError):
    """Entities are missing, repeated or do not match between inputs.

    The thesis dropped such groups silently (thesis issue C3). The core raises
    instead.
    """


class SolveError(ParametricInsuranceDesignError, RuntimeError):
    """No solver returned an acceptable result for a design problem.

    Parameters
    ----------
    message : str
        Human-readable description.
    problem_id : str
        The design problem that failed.
    status : SolveStatus
        Final status after every solver attempt.
    attempts : sequence of SolverAttempt, optional
        Every solver tried, in order, with its status, time and message.

    Attributes
    ----------
    problem_id : str
        The design problem that failed.
    status : SolveStatus
        Final status after every solver attempt.
    attempts : tuple of SolverAttempt
        Every solver tried, in order.
    """

    def __init__(
        self,
        message: str,
        *,
        problem_id: str,
        status: SolveStatus,
        attempts: Sequence[SolverAttempt] = (),
    ) -> None:
        super().__init__(f"[{problem_id}] {message} (status: {status})")
        self.problem_id = problem_id
        self.status = status
        self.attempts = tuple(attempts)


class InfeasibleError(SolveError):
    """The design problem is infeasible."""


class UnboundedError(SolveError):
    """The design problem is unbounded."""


class RecordSchemaError(ParametricInsuranceDesignError, ValueError):
    """A result-store table does not match its record schema.

    Parameters
    ----------
    message : str
        Human-readable description.
    table : str
        Name of the table, e.g. ``"runs"``.

    Attributes
    ----------
    table : str
        Name of the table.
    """

    def __init__(self, message: str, *, table: str) -> None:
        super().__init__(f"[{table}] {message}")
        self.table = table
