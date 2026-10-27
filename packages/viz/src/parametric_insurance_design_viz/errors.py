"""Errors of the viz package.

Owner: MAR-110. Every error derives from the core's
:class:`~parametric_insurance_design.errors.ParametricInsuranceDesignError`
(ADR 0002 §6: new subclasses live in the owning module), so callers, and the
``parametric-insurance-design`` command, can catch the whole library with one
class.
"""

from __future__ import annotations

from parametric_insurance_design.errors import ParametricInsuranceDesignError

__all__ = [
    "EventSetMismatchError",
    "FigureDataError",
    "IncompleteRunError",
    "InconsistentRunsError",
    "MissingRunError",
    "VizError",
]


class VizError(ParametricInsuranceDesignError, ValueError):
    """Base class of the viz errors: a figure cannot be drawn from its inputs."""


class MissingRunError(VizError):
    """A requested run is not committed in the result store.

    Figures read the store and never re-run an optimisation (SPEC §3.1 C6), so
    the run has to be computed first, e.g. with
    ``parametric-insurance-design run CONFIG``.
    """


class IncompleteRunError(VizError):
    """A run has a failed design problem, so it has no complete result."""


class InconsistentRunsError(VizError):
    """Runs drawn into one figure disagree, e.g. on their entities or bins."""


class EventSetMismatchError(VizError):
    """The EventSet given for an overlay is not the one the run was solved on."""


class FigureDataError(VizError):
    """The data of a figure cannot be written (bad name or table)."""
