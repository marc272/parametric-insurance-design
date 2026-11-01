"""Design parametric insurance payout functions.

The core library of the parametric-insurance-design project. It holds no
hazard-model dependency; adapters for hazard sources live in separate
distributions. By convention it is imported as ``pid``::

    import parametric_insurance_design as pid

    es = pid.EventSet.from_parquet("parity/tests/data/thesis_eventset")
    train, test = pid.splits.holdout(es)
    results = pid.design(
        es,
        pid.Portfolio(),
        pid.StepPayout(attachment=20.0, limit=70.0, n_bins=15),
        pid.WeightedCVaR(alpha=0.9, beta=0.95),
        basis=pid.Basis.ANNUAL,
        constraints=(pid.Budget(1.0),),
        sample=train,
    )

The top level is a curated list (ADR 0004, Q2; ADR 0002 §1), grouped by the
library's two stories:

* **Tail-risk objective:** ``MSE``, ``ExpectedUncovered``, ``WeightedCVaR``;
  the payout family ``StepPayout``; the pricing ``PurePremium`` and
  ``CostOfCapitalLoad``, and the premium ``Budget``.
* **Portfolio calibration:** the scopes ``Individual``, ``Portfolio`` and
  ``Cluster``, and the clustering ``ThesisWardClustering``.
* **One call:** :func:`design` builds and solves every design problem of a
  scope.
* **Data contract and shared types:** ``EventSet``, ``EventSetMetadata``,
  ``Basis``, ``OutcomeMeasure``, ``Sample``, ``Entity``, ``ProblemSpec``,
  ``DesignProblem``, ``SolveResult``, ``SolveStatus``,
  ``ParametricInsuranceDesignError`` and ``SolveError``.

Everything else is reached through its module, which is imported here:
evaluation (``pid.evaluate``, ``pid.splits``, ``pid.bootstrap``,
``pid.riskmeasures``), the low-level path (``pid.problem.build_problems``,
then ``pid.solve.solve`` for each problem) and the extension points
(``pid.interfaces``, ``pid.records``, ``pid.errors``).

Two library modules are not imported here, so they are off the top level and
are imported by their full names: ``parametric_insurance_design.noise``, the
thesis noise layer (the SPEC §6.3 baseline), and
``parametric_insurance_design.robust``, the robust designs of SPEC §6.5,
which aren't implemented yet. Neither are the command line (``cli``) and the
experiment layer (``parametric_insurance_design.experiment``).
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
    objectives,
    payout,
    pricing,
    problem,
    records,
    riskmeasures,
    scopes,
    solve,
    splits,
    workflow,
)
from parametric_insurance_design.basis import Basis, OutcomeMeasure
from parametric_insurance_design.clustering import ThesisWardClustering
from parametric_insurance_design.constraints import Budget
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
from parametric_insurance_design.objectives import MSE, ExpectedUncovered, WeightedCVaR
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio
from parametric_insurance_design.workflow import design

__all__ = [
    "MSE",
    "Basis",
    "Budget",
    "Cluster",
    "CostOfCapitalLoad",
    "DesignProblem",
    "Entity",
    "EventSet",
    "EventSetMetadata",
    "ExpectedUncovered",
    "Individual",
    "OutcomeMeasure",
    "ParametricInsuranceDesignError",
    "Portfolio",
    "ProblemSpec",
    "PurePremium",
    "Sample",
    "SolveError",
    "SolveResult",
    "SolveStatus",
    "StepPayout",
    "ThesisWardClustering",
    "WeightedCVaR",
    "__version__",
    "basis",
    "bootstrap",
    "clustering",
    "constraints",
    "design",
    "errors",
    "evaluate",
    "eventset",
    "index",
    "interfaces",
    "objectives",
    "payout",
    "pricing",
    "problem",
    "records",
    "riskmeasures",
    "scopes",
    "solve",
    "splits",
    "workflow",
]

__version__: str = version("parametric-insurance-design")
