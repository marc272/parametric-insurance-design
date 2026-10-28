"""Design parametric insurance payout functions.

The core library of the parametric-insurance-design project. It holds no
hazard-model dependency; adapters for hazard sources live in separate
distributions. By convention it is imported as ``pid``::

    import parametric_insurance_design as pid

    es = pid.EventSet.from_parquet("data/eventsets/iris-florida")
    payout = pid.payout.StepPayout(attachment=20.0, limit=70.0, n_bins=20)

The data contract and the shared types are re-exported at the top level.
Components live in their modules (``pid.payout``, ``pid.scopes``,
``pid.objectives``, ...), which are all imported here, so this file does not
change when a module gains a class (ADR 0002).
"""

from importlib.metadata import version

from parametric_insurance_design import (
    basis,
    bootstrap,
    clustering,
    constraints,
    errors,
    evaluate,
    eventset,
    index,
    interfaces,
    noise,
    objectives,
    payout,
    pricing,
    problem,
    records,
    riskmeasures,
    robust,
    scopes,
    solve,
    splits,
)
from parametric_insurance_design.basis import Basis, OutcomeMeasure
from parametric_insurance_design.errors import (
    ParametricInsuranceDesignError,
    SolveError,
)
from parametric_insurance_design.eventset import EventSet, EventSetMetadata
from parametric_insurance_design.interfaces import (
    DesignProblem,
    Entity,
    ProblemSpec,
    Sample,
    SolveResult,
    SolveStatus,
)

__all__ = [
    "Basis",
    "DesignProblem",
    "Entity",
    "EventSet",
    "EventSetMetadata",
    "OutcomeMeasure",
    "ParametricInsuranceDesignError",
    "ProblemSpec",
    "Sample",
    "SolveError",
    "SolveResult",
    "SolveStatus",
    "__version__",
    "basis",
    "bootstrap",
    "clustering",
    "constraints",
    "errors",
    "evaluate",
    "eventset",
    "index",
    "interfaces",
    "noise",
    "objectives",
    "payout",
    "pricing",
    "problem",
    "records",
    "riskmeasures",
    "robust",
    "scopes",
    "solve",
    "splits",
]

__version__: str = version("parametric-insurance-design")
