"""Contracts between the core modules (ADR 0002).

This module holds every type that more than one Linear issue implements or
consumes. Its public signatures are fixed by ADR 0002: implementing issues
import from here and never edit this file. Changing it needs an ADR 0002
amendment.

Data flow of one run (``problem.py`` assembles it, see ADR 0002)::

    EventSet --Sample.select--> EventSet (rows of the sample)
        |                         |
        |   basis.outcome_measure(eventset, basis, years=sample.years)
        v                         v
    Scope.partition --> ProblemSpec --Scope.materialise--> DesignProblem
                                                    |
    PayoutStructure.basis_matrix, loss scaling  --> ProblemContext
                                                    |
          Objective.build -> ObjectiveTerm   Pricing.premium -> Term
          PayoutStructure.constraints        Constraint.build(ctx, premium)
                                                    |
                                    cvxpy Problem --solve--> SolveResult

Conventions
    * Rows are EventSet rows (events times draws); ``n_rows`` counts them.
    * An **entity** is something that gets its own payout function (an asset,
      or a cluster of assets). A **design problem** is one optimisation: one
      for each asset in the individual scope, one for the whole portfolio in
      the portfolio and cluster scopes.
    * The objective level of a design problem is the **sum over its
      entities**: ``L_e = sum_j L_{e,j}`` and ``pi_e = sum_j pi_{e,j}``.
    * ``theta`` has shape ``(n_entities, n_params)``. Entity ``j``'s payout is
      ``basis_matrix(xi[:, j]) @ theta[j]``.
    * Inside a :class:`ProblemContext` every loss and payout quantity is
      divided by ``scale`` (numerical conditioning, thesis: the maximum
      objective-level loss). Components work in scaled units and never see
      the scale. :class:`SolveResult` reports loss units again.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import ClassVar

import cvxpy as cp
import numpy as np
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design.basis import Basis, OutcomeMeasure
from parametric_insurance_design.errors import (
    EntityMismatchError,
    InputMismatchError,
)
from parametric_insurance_design.eventset import EventSet

__all__ = [
    "SUCCESS_STATUSES",
    "Constraint",
    "DesignProblem",
    "Entity",
    "Objective",
    "ObjectiveTerm",
    "PayoutStructure",
    "Pricing",
    "ProblemContext",
    "ProblemSpec",
    "Sample",
    "Scope",
    "SolveResult",
    "SolveStatus",
    "SolverAttempt",
    "Term",
]


# --------------------------------------------------------------------------
# Samples
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class Sample:
    """Rows of an EventSet used for calibration or evaluation.

    A sample also lists the simulation years it represents, including years
    without rows, because the annual basis needs them as zero-loss outcomes.
    ``splits.py`` builds train and test samples; :meth:`full` covers
    everything.

    Parameters
    ----------
    name : str
        ``"full"``, ``"train"`` or ``"test"``.
    rows : array_like of bool
        Mask over the parent EventSet's rows, shape ``(n_rows,)``.
    years : array_like of int
        Simulation years the sample represents, unique.
    fold : int, default 0
        Fold number for k-fold splits; 0 otherwise.

    Raises
    ------
    InputMismatchError
        If a field has the wrong type or shape, or years repeat.
    """

    name: str
    rows: NDArray[np.bool_]
    years: NDArray[np.int64]
    fold: int = 0

    def __post_init__(self) -> None:
        """Validate the fields and store read-only copies."""
        if not isinstance(self.name, str) or not self.name:
            raise InputMismatchError("sample name must be a non-empty string")
        rows = np.array(self.rows, copy=True)
        if rows.ndim != 1 or rows.dtype != np.bool_:
            raise InputMismatchError("sample rows must be a 1-D boolean mask")
        years = np.array(self.years, copy=True)
        if years.ndim != 1 or not np.issubdtype(years.dtype, np.integer):
            raise InputMismatchError("sample years must be a 1-D integer array")
        years = np.sort(years.astype(np.int64))
        if np.any(np.diff(years) == 0):
            raise InputMismatchError("sample years must be unique")
        if isinstance(self.fold, bool) or not isinstance(self.fold, int):
            raise InputMismatchError("sample fold must be an int")
        if self.fold < 0:
            raise InputMismatchError("sample fold must be >= 0")
        rows.setflags(write=False)
        years.setflags(write=False)
        object.__setattr__(self, "rows", rows)
        object.__setattr__(self, "years", years)

    @classmethod
    def full(cls, eventset: EventSet) -> Sample:
        """Return the sample of all rows and all years ``0 .. n_years - 1``.

        Parameters
        ----------
        eventset : EventSet
            The EventSet to cover.

        Returns
        -------
        Sample
            Sample named ``"full"``.

        Raises
        ------
        InputMismatchError
            If an event year lies outside ``[0, n_years)`` (the year
            convention of ADR 0002).
        """
        n_years = eventset.metadata.n_years
        observed = eventset.events["year"].to_numpy(dtype=np.int64)
        if observed.size and (observed.min() < 0 or observed.max() >= n_years):
            raise InputMismatchError(
                f"event years must lie in [0, {n_years}) (ADR 0002 year "
                f"convention), got [{observed.min()}, {observed.max()}]"
            )
        return cls(
            name="full",
            rows=np.ones(eventset.n_rows, dtype=np.bool_),
            years=np.arange(n_years, dtype=np.int64),
        )

    @property
    def n_selected(self) -> int:
        """Number of rows in the sample."""
        return int(self.rows.sum())

    def select(self, eventset: EventSet) -> EventSet:
        """Return the EventSet restricted to the sample's rows.

        Metadata is kept unchanged (``n_years`` still refers to the parent);
        use :attr:`years` for the years the sample represents.

        Parameters
        ----------
        eventset : EventSet
            The parent EventSet the mask refers to.

        Returns
        -------
        EventSet
            The selected rows, in their original order.

        Raises
        ------
        InputMismatchError
            If the mask length differs from ``eventset.n_rows``, or a selected
            row's year is not in :attr:`years` (that would leak rows across
            folds).
        """
        if self.rows.shape[0] != eventset.n_rows:
            raise InputMismatchError(
                f"sample {self.name!r} has {self.rows.shape[0]} rows, "
                f"the EventSet has {eventset.n_rows}"
            )
        selected_years = eventset.events["year"].to_numpy(dtype=np.int64)[self.rows]
        stray = np.setdiff1d(selected_years, self.years)
        if stray.size:
            raise InputMismatchError(
                f"sample {self.name!r} selects rows from years outside its year "
                f"set, e.g. {stray[:5].tolist()}"
            )
        return EventSet(
            events=eventset.events.loc[self.rows],
            locations=eventset.locations,
            index=eventset.index[self.rows],
            loss=eventset.loss[self.rows],
            metadata=eventset.metadata,
        )


# --------------------------------------------------------------------------
# Entities and design problems
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Entity:
    """A payout entity: something that gets its own payout function.

    Parameters
    ----------
    entity_id : str
        Unique within its design problem, e.g. ``"A1"`` or ``"C1"``.
    location_ids : tuple of str
        The EventSet locations the entity covers. Non-empty, no repeats.
    """

    entity_id: str
    location_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        """Validate the fields."""
        if not isinstance(self.entity_id, str) or not self.entity_id:
            raise EntityMismatchError("entity_id must be a non-empty string")
        ids = tuple(self.location_ids)
        if not ids:
            raise EntityMismatchError(
                f"entity {self.entity_id!r} must cover at least one location"
            )
        if len(set(ids)) != len(ids):
            raise EntityMismatchError(
                f"entity {self.entity_id!r} repeats a location_id"
            )
        object.__setattr__(self, "location_ids", ids)


@dataclass(frozen=True)
class ProblemSpec:
    """Which entities one design problem calibrates jointly.

    A spec depends on calibration data only through the scope's choices (for
    example cluster assignments). Re-using a spec on another EventSet keeps
    the entities fixed, which out-of-sample evaluation and the robust
    wrappers need.

    Parameters
    ----------
    problem_id : str
        Unique within a run: the asset id in the individual scope,
        ``"portfolio"`` in the portfolio and cluster scopes.
    entities : tuple of Entity
        Non-empty. Entity ids are unique and entities share no location.
    """

    problem_id: str
    entities: tuple[Entity, ...]

    def __post_init__(self) -> None:
        """Validate the fields."""
        if not isinstance(self.problem_id, str) or not self.problem_id:
            raise EntityMismatchError("problem_id must be a non-empty string")
        entities = tuple(self.entities)
        if not entities:
            raise EntityMismatchError(
                f"problem {self.problem_id!r} must have at least one entity"
            )
        ids = [e.entity_id for e in entities]
        if len(set(ids)) != len(ids):
            raise EntityMismatchError(
                f"problem {self.problem_id!r} repeats an entity_id"
            )
        locations = [loc for e in entities for loc in e.location_ids]
        if len(set(locations)) != len(locations):
            raise EntityMismatchError(
                f"problem {self.problem_id!r}: entities overlap in locations"
            )
        object.__setattr__(self, "entities", entities)

    @property
    def entity_ids(self) -> tuple[str, ...]:
        """Entity ids, in order."""
        return tuple(e.entity_id for e in self.entities)

    @property
    def location_ids(self) -> tuple[str, ...]:
        """All covered locations, entity by entity."""
        return tuple(loc for e in self.entities for loc in e.location_ids)


@dataclass(frozen=True, eq=False)
class DesignProblem:
    """Data of one design problem, in loss units.

    Parameters
    ----------
    spec : ProblemSpec
        The entities.
    index : array_like of float
        Entity index ``xi``, shape ``(n_rows, n_entities)``. Finite.
    entity_loss : array_like of float
        Loss per entity (sum over its locations), shape
        ``(n_rows, n_entities)``. Finite and >= 0.

    Raises
    ------
    InputMismatchError
        If the shapes disagree with each other or with ``spec``, or values
        are invalid.
    """

    spec: ProblemSpec
    index: NDArray[np.float64]
    entity_loss: NDArray[np.float64]

    def __post_init__(self) -> None:
        """Validate the fields and store read-only copies."""
        n_entities = len(self.spec.entities)
        index = np.array(self.index, dtype=np.float64, copy=True)
        loss = np.array(self.entity_loss, dtype=np.float64, copy=True)
        for name, arr in (("index", index), ("entity_loss", loss)):
            if arr.ndim != 2 or arr.shape[1] != n_entities:
                raise InputMismatchError(
                    f"{name} must have shape (n_rows, {n_entities}), got {arr.shape}"
                )
            if not np.all(np.isfinite(arr)):
                raise InputMismatchError(f"{name} must be finite")
        if index.shape != loss.shape:
            raise InputMismatchError(
                f"index {index.shape} and entity_loss {loss.shape} differ in shape"
            )
        if np.any(loss < 0):
            raise InputMismatchError("entity_loss must be >= 0")
        index.setflags(write=False)
        loss.setflags(write=False)
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "entity_loss", loss)

    @property
    def n_rows(self) -> int:
        """Number of event rows."""
        return int(self.index.shape[0])

    @property
    def n_entities(self) -> int:
        """Number of entities."""
        return int(self.index.shape[1])

    @property
    def loss(self) -> NDArray[np.float64]:
        """Objective-level loss: the sum over entities, shape ``(n_rows,)``."""
        return self.entity_loss.sum(axis=1)


# --------------------------------------------------------------------------
# Problem context and terms
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class ProblemContext:
    """Everything a component needs to build its part of a design problem.

    Built by ``problem.build_context``. All loss and payout quantities are in
    scaled units (loss divided by ``scale``).

    Parameters
    ----------
    problem : DesignProblem
        The design problem, in loss units.
    payout_structure : PayoutStructure
        The payout structure shared by all entities.
    measure : OutcomeMeasure
        Measure over the problem's rows; carries the basis.
    scale : float
        Loss scale factor, > 0.
    theta : cvxpy.Variable
        Payout parameters, shape ``(n_entities, n_params)``.
    entity_payout : cvxpy.Expression
        Payout per row and entity, shape ``(n_rows, n_entities)``.
    payout : cvxpy.Expression
        Objective-level payout per row, shape ``(n_rows,)``.
    loss : numpy.ndarray
        Objective-level loss per row, shape ``(n_rows,)``.
    entity_loss : numpy.ndarray
        Loss per row and entity, shape ``(n_rows, n_entities)``.
    cap : numpy.ndarray
        Payout cap per entity, shape ``(n_entities,)``.

    Raises
    ------
    InputMismatchError
        If the shapes do not line up.
    """

    problem: DesignProblem
    payout_structure: PayoutStructure
    measure: OutcomeMeasure
    scale: float
    theta: cp.Variable
    entity_payout: cp.Expression
    payout: cp.Expression
    loss: NDArray[np.float64]
    entity_loss: NDArray[np.float64]
    cap: NDArray[np.float64]

    def __post_init__(self) -> None:
        """Check that the shapes line up."""
        n_rows, n_entities = self.problem.n_rows, self.problem.n_entities
        expected = {
            "theta": (
                tuple(self.theta.shape),
                (n_entities, self.payout_structure.n_params),
            ),
            "entity_payout": (tuple(self.entity_payout.shape), (n_rows, n_entities)),
            "payout": (tuple(self.payout.shape), (n_rows,)),
            "loss": (np.shape(self.loss), (n_rows,)),
            "entity_loss": (np.shape(self.entity_loss), (n_rows, n_entities)),
            "cap": (np.shape(self.cap), (n_entities,)),
        }
        for name, (got, want) in expected.items():
            if got != want:
                raise InputMismatchError(f"{name} must have shape {want}, got {got}")
        if self.measure.n_rows != n_rows:
            raise InputMismatchError(
                f"measure covers {self.measure.n_rows} rows, the problem {n_rows}"
            )
        if not (np.isfinite(self.scale) and self.scale > 0):
            raise InputMismatchError(f"scale must be finite and > 0, got {self.scale}")

    @property
    def basis(self) -> Basis:
        """The evaluation basis of the measure."""
        return self.measure.basis

    @property
    def expected_loss(self) -> float:
        """Expected objective-level loss under the measure, scaled units."""
        return self.measure.expectation(self.loss)


@dataclass(frozen=True, eq=False, kw_only=True)
class Term:
    """A scalar cvxpy expression plus the constraints that define it.

    Parameters
    ----------
    expression : cvxpy.Expression
        Scalar expression.
    constraints : tuple of cvxpy.Constraint, optional
        Constraints the expression needs, e.g. epigraph constraints of
        auxiliary variables.
    """

    expression: cp.Expression
    constraints: tuple[cp.Constraint, ...] = ()

    def __post_init__(self) -> None:
        """Check that the expression is scalar."""
        if tuple(self.expression.shape) != ():
            raise InputMismatchError(
                f"term expression must be scalar, got shape {self.expression.shape}"
            )
        object.__setattr__(self, "constraints", tuple(self.constraints))


@dataclass(frozen=True, eq=False, kw_only=True)
class ObjectiveTerm(Term):
    """An objective, decomposed over outcomes.

    The decomposition ``expression == measure.probability @ per_outcome +
    offset`` must hold. It lets the distributionally robust wrapper
    (``robust.py``, R2) re-weight outcomes without knowing the objective.

    Parameters
    ----------
    expression : cvxpy.Expression
        Scalar objective to minimise, scaled units.
    constraints : tuple of cvxpy.Constraint, optional
        Constraints the objective needs.
    per_outcome : cvxpy.Expression
        Shape ``(n_outcomes,)``: the part of the objective for each outcome.
    offset : cvxpy.Expression or float, default 0.0
        Part of the objective that does not depend on outcome weights, e.g.
        ``alpha * zeta`` in the Rockafellar-Uryasev form.
    homogeneity : int, default 1
        Degree ``d`` with ``objective(c * L) = c**d * objective(L)``: 1 for
        E[U] and CVaR, 2 for MSE. Used to report the objective value in loss
        units: ``value * scale**d``.
    components : mapping of str to cvxpy.Expression, optional
        Named scalar parts worth recording, e.g. ``{"cvar": ..., "eu": ...}``,
        with the same homogeneity.
    """

    per_outcome: cp.Expression
    offset: cp.Expression | float = 0.0
    homogeneity: int = 1
    components: Mapping[str, cp.Expression] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Check shapes and the homogeneity degree."""
        super().__post_init__()
        if len(self.per_outcome.shape) != 1:
            raise InputMismatchError(
                f"per_outcome must be 1-D, got shape {self.per_outcome.shape}"
            )
        if self.homogeneity not in (1, 2):
            raise InputMismatchError(
                f"homogeneity must be 1 or 2, got {self.homogeneity}"
            )
        object.__setattr__(self, "components", dict(self.components))


# --------------------------------------------------------------------------
# Component interfaces
# --------------------------------------------------------------------------


class PayoutStructure(ABC):
    """A family of payout functions, linear in its parameters ``theta``.

    Implementations: ``payout.StepPayout`` (MAR-11). Piecewise-linear payouts
    are parked (SPEC §9) but fit: their basis matrix holds hat functions.

    Attributes
    ----------
    name : str
        Short name used in records, e.g. ``"step"``.
    """

    name: ClassVar[str]

    @property
    @abstractmethod
    def n_params(self) -> int:
        """Number of parameters per entity (bins, for a step payout)."""

    @abstractmethod
    def parameter_bounds(self) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        """Index range each parameter applies to.

        Returns
        -------
        lower, upper : numpy.ndarray
            Shape ``(n_params,)`` each. For a step payout, the bin edges
            ``[lower_k, upper_k)``. Stored in the payouts table.
        """

    @abstractmethod
    def basis_matrix(self, index: ArrayLike) -> NDArray[np.float64]:
        """Map index values to the design matrix of one entity.

        Parameters
        ----------
        index : array_like of float
            Index values of one entity, shape ``(n_rows,)``.

        Returns
        -------
        numpy.ndarray
            ``M`` with shape ``(n_rows, n_params)``, so that the entity's
            payout is ``M @ theta_j``.
        """

    @abstractmethod
    def constraints(
        self, theta: cp.Variable, cap: NDArray[np.float64]
    ) -> tuple[cp.Constraint, ...]:
        """Constraints every payout of this family satisfies.

        Parameters
        ----------
        theta : cvxpy.Variable
            Shape ``(n_entities, n_params)``.
        cap : numpy.ndarray
            Maximum payout per entity, shape ``(n_entities,)``, same units as
            ``theta``.

        Returns
        -------
        tuple of cvxpy.Constraint
            For a step payout: ``theta >= 0``, non-decreasing along bins, and
            ``theta[j] <= cap[j]``.
        """

    @abstractmethod
    def evaluate(self, index: ArrayLike, theta: ArrayLike) -> NDArray[np.float64]:
        """Payouts for given index values and parameters.

        Parameters
        ----------
        index : array_like of float
            Shape ``(n_rows, n_entities)``.
        theta : array_like of float
            Shape ``(n_entities, n_params)``.

        Returns
        -------
        numpy.ndarray
            Payout per row and entity, shape ``(n_rows, n_entities)``. Equal
            to ``basis_matrix(index[:, j]) @ theta[j]`` for each entity.
        """


class Scope(ABC):
    """Maps locations to payout entities and design problems.

    Implementations: ``scopes.Individual``, ``scopes.Portfolio`` and
    ``scopes.Cluster`` (MAR-12).

    Attributes
    ----------
    name : str
        Short name used in records, e.g. ``"individual"``.
    """

    name: ClassVar[str]

    @abstractmethod
    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        """Decide the design problems and their entities.

        Parameters
        ----------
        eventset : EventSet
            Calibration data. The cluster scope clusters on it, so pass the
            training sample only.

        Returns
        -------
        tuple of ProblemSpec
            One per design problem, with unique ``problem_id``.
        """

    @abstractmethod
    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        """Build a design problem's data from an EventSet.

        Parameters
        ----------
        eventset : EventSet
            Any EventSet with the spec's locations, e.g. a test sample.
        spec : ProblemSpec
            Usually from :meth:`partition` on the calibration data.

        Returns
        -------
        DesignProblem
            Entity index (e.g. the value-weighted mean index for clusters)
            and entity losses.

        Raises
        ------
        EntityMismatchError
            If the EventSet lacks a location of the spec.
        """


class Objective(ABC):
    """Builds the quantity a design problem minimises.

    Implementations: ``objectives.MSE``, ``objectives.ExpectedUncovered`` and
    ``objectives.WeightedCVaR`` (MAR-13); ``robust.DistributionallyRobust``
    wraps one (MAR-35).

    Objectives are basis-agnostic: they aggregate per-row quantities with
    ``ctx.measure`` and raise :class:`UnsupportedBasisError` only if they
    cannot handle ``ctx.basis``.

    Attributes
    ----------
    name : str
        Short name used in records, e.g. ``"weighted_cvar"``.
    """

    name: ClassVar[str]

    @abstractmethod
    def build(self, ctx: ProblemContext) -> ObjectiveTerm:
        """Build the objective.

        Parameters
        ----------
        ctx : ProblemContext
            Scaled problem data and variables.

        Returns
        -------
        ObjectiveTerm
            The objective to minimise, decomposed over outcomes.
        """


class Pricing(ABC):
    """Prices a payout: the premium in the budget constraint.

    Implementations: ``pricing.PurePremium`` (MAR-13) and
    ``pricing.CostOfCapitalLoad`` (MAR-27).

    Attributes
    ----------
    name : str
        Short name used in records, e.g. ``"pure"``.
    """

    name: ClassVar[str]

    @abstractmethod
    def premium(self, ctx: ProblemContext) -> Term:
        """Premium of the objective-level payout ``ctx.payout``.

        Parameters
        ----------
        ctx : ProblemContext
            Scaled problem data and variables.

        Returns
        -------
        Term
            Convex scalar premium expression, scaled units.
        """

    @abstractmethod
    def premium_value(self, payout: ArrayLike, measure: OutcomeMeasure) -> float:
        """Premium of a realised payout, for evaluation and records.

        Parameters
        ----------
        payout : array_like of float
            Objective-level payout per row, shape ``(n_rows,)``.
        measure : OutcomeMeasure
            Measure over the same rows.

        Returns
        -------
        float
            The premium, same units as ``payout``.
        """


class Constraint(ABC):
    """An extra constraint on a design problem, e.g. the budget.

    Implementations: ``constraints.Budget`` (MAR-13). Payout-family
    constraints (non-negative, monotone, cap) come from
    :meth:`PayoutStructure.constraints` and are always added.

    Attributes
    ----------
    name : str
        Short name used in records, e.g. ``"budget"``.
    """

    name: ClassVar[str]

    @abstractmethod
    def build(self, ctx: ProblemContext, premium: Term) -> tuple[cp.Constraint, ...]:
        """Build the constraints.

        Parameters
        ----------
        ctx : ProblemContext
            Scaled problem data and variables.
        premium : Term
            The pricing component's premium; its own constraints are added by
            the builder, not here.

        Returns
        -------
        tuple of cvxpy.Constraint
        """


# --------------------------------------------------------------------------
# Solve results
# --------------------------------------------------------------------------


class SolveStatus(StrEnum):
    """Status of a solve. Values equal cvxpy's status strings.

    ``ERROR`` marks a failure without a solver status, e.g. an exception while
    building the problem.
    """

    OPTIMAL = "optimal"
    OPTIMAL_INACCURATE = "optimal_inaccurate"
    INFEASIBLE = "infeasible"
    INFEASIBLE_INACCURATE = "infeasible_inaccurate"
    UNBOUNDED = "unbounded"
    UNBOUNDED_INACCURATE = "unbounded_inaccurate"
    USER_LIMIT = "user_limit"
    SOLVER_ERROR = "solver_error"
    ERROR = "error"


SUCCESS_STATUSES: frozenset[SolveStatus] = frozenset(
    {SolveStatus.OPTIMAL, SolveStatus.OPTIMAL_INACCURATE}
)
"""Statuses a :class:`SolveResult` may carry. Whether ``optimal_inaccurate``
is accepted is the solver policy's choice (``solve.py``)."""


@dataclass(frozen=True)
class SolverAttempt:
    """One solver call.

    Parameters
    ----------
    solver : str
        cvxpy solver name, e.g. ``"CLARABEL"``.
    status : SolveStatus
        Status the call ended with.
    seconds : float
        Wall time of the call.
    message : str or None, optional
        Exception text or solver message, if any.
    """

    solver: str
    status: SolveStatus
    seconds: float
    message: str | None = None


@dataclass(frozen=True, eq=False)
class SolveResult:
    """Accepted solution of one design problem, in loss units.

    Failures never produce a SolveResult: they raise
    :class:`~parametric_insurance_design.errors.SolveError`.

    Parameters
    ----------
    spec : ProblemSpec
        The design problem's entities.
    payout_structure : PayoutStructure
        The payout family ``theta`` belongs to.
    theta : array_like of float
        Payout parameters, shape ``(n_entities, n_params)``, loss units.
    status : SolveStatus
        One of :data:`SUCCESS_STATUSES`.
    objective_value : float
        Objective value in loss units.
    premium : float
        Premium of the solution, loss units.
    scale : float
        Loss scale factor the problem was solved with.
    solver : str
        Solver that produced the accepted result.
    attempts : sequence of SolverAttempt
        Every solver call, in order, the accepted one last.
    build_seconds, solve_seconds : float
        Wall times of building and solving.
    diagnostics : mapping of str to float, optional
        Named objective components (loss units) and solver statistics.

    Raises
    ------
    InputMismatchError
        If ``theta`` does not fit the spec and payout structure, or the
        status is not a success.
    """

    spec: ProblemSpec
    payout_structure: PayoutStructure
    theta: NDArray[np.float64]
    status: SolveStatus
    objective_value: float
    premium: float
    scale: float
    solver: str
    attempts: tuple[SolverAttempt, ...]
    build_seconds: float
    solve_seconds: float
    diagnostics: Mapping[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the fields and store read-only copies."""
        status = SolveStatus(self.status)
        if status not in SUCCESS_STATUSES:
            raise InputMismatchError(
                f"a SolveResult needs a success status, got {status.value!r}; "
                "failures raise SolveError"
            )
        theta = np.array(self.theta, dtype=np.float64, copy=True)
        want = (len(self.spec.entities), self.payout_structure.n_params)
        if theta.shape != want:
            raise InputMismatchError(f"theta must have shape {want}, got {theta.shape}")
        if not np.all(np.isfinite(theta)):
            raise InputMismatchError("theta must be finite")
        theta.setflags(write=False)
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "theta", theta)
        object.__setattr__(self, "attempts", tuple(self.attempts))
        object.__setattr__(self, "diagnostics", dict(self.diagnostics))

    @property
    def problem_id(self) -> str:
        """The design problem's id."""
        return self.spec.problem_id

    @property
    def entity_ids(self) -> tuple[str, ...]:
        """Entity ids, aligned with the rows of :attr:`theta`."""
        return self.spec.entity_ids

    def payouts(self, problem: DesignProblem) -> NDArray[np.float64]:
        """Payouts of this solution on a design problem's data.

        Parameters
        ----------
        problem : DesignProblem
            Data for the same spec, e.g. materialised on a test sample.

        Returns
        -------
        numpy.ndarray
            Payout per row and entity, shape ``(n_rows, n_entities)``.

        Raises
        ------
        EntityMismatchError
            If the problem's entities differ from this result's.
        """
        if problem.spec != self.spec:
            raise EntityMismatchError(
                f"result for {self.problem_id!r} cannot be applied to problem "
                f"{problem.spec.problem_id!r} with different entities"
            )
        return self.payout_structure.evaluate(problem.index, self.theta)
