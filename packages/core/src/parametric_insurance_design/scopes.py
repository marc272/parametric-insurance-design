"""Scopes: individual, portfolio and cluster (SPEC §4.2, §6).

The interface is
:class:`~parametric_insurance_design.interfaces.Scope` (ADR 0002). A scope
maps locations to payout entities and design problems; the objective of a
design problem is on the sum over its entities (``L_e = sum_j L_{e,j}``,
``pi_e = sum_j pi_{e,j}``), and every design problem has one budget.

* :class:`Individual`: one design problem per location (``problem_id`` =
  ``location_id``), one entity each (``entity_id`` = ``location_id``).
* :class:`Portfolio`: one design problem (``problem_id = "portfolio"``),
  one entity per location (``entity_id`` = ``location_id``), objective on the
  summed loss and payout.
* :class:`Cluster`: one entity per cluster (``entity_id`` = ``"C1"``,
  ``"C2"``, ...), index from
  :class:`~parametric_insurance_design.index.ValueWeightedIndex`. With
  ``joint=True`` (the default, the thesis) one design problem
  (``"portfolio"``) over all clusters; with ``joint=False`` one design
  problem per cluster (``problem_id`` = ``"cluster:C1"``, ...), each with
  its own budget on its cluster's loss, as the individual scope per
  location. The two settings have the same clusters and the same index, so
  comparing them isolates the joint calibration, and comparing
  ``joint=False`` with :class:`Individual` isolates the cluster index.

An entity's loss is the sum of its locations' losses. Entities list their
locations in EventSet order, and clusters are numbered by the strategy's
labels (thesis: ``C<label>``).

``partition`` runs on calibration data only; ``materialise`` re-uses a spec on
any EventSet with the same locations, e.g. a test sample.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import ClassVar, Final

import numpy as np
from numpy.typing import NDArray

from parametric_insurance_design.clustering import ClusteringStrategy
from parametric_insurance_design.errors import (
    ComponentConfigError,
    EntityMismatchError,
    InputMismatchError,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.index import (
    EntityIndex,
    PointIndex,
    ValueWeightedIndex,
    location_columns,
)
from parametric_insurance_design.interfaces import (
    DesignProblem,
    Entity,
    ProblemSpec,
    Scope,
)

__all__ = [
    "CLUSTER_PROBLEM_PREFIX",
    "PORTFOLIO_PROBLEM_ID",
    "Cluster",
    "Individual",
    "Portfolio",
    "Scope",
    "cluster_problem_id",
]

PORTFOLIO_PROBLEM_ID: Final[str] = "portfolio"
"""``problem_id`` of the single design problem of joint scopes."""

CLUSTER_PROBLEM_PREFIX: Final[str] = "cluster:"
"""Prefix of the ``problem_id`` of a separately calibrated cluster
(``Cluster(joint=False)``): ``"cluster:" + entity_id``, e.g. ``"cluster:C1"``.

The prefix keeps these ids apart from the ids of the other scopes: the
joint scopes' ``"portfolio"``, the aggregate rows' ``"*"``
(``records.ALL_PROBLEMS``), the individual scope's location ids (unless a
location is itself named ``"cluster:C<k>"``) and the cluster entity ids
``"C<k>"``, so a problem-level KPI row (``subject_id`` = ``problem_id``) and
an entity-level row of the same cluster have different subjects.
"""


def cluster_problem_id(entity_id: str) -> str:
    """Return the ``problem_id`` of a separately calibrated cluster.

    Parameters
    ----------
    entity_id : str
        The cluster's entity id, e.g. ``"C1"``.

    Returns
    -------
    str
        :data:`CLUSTER_PROBLEM_PREFIX` + ``entity_id``, e.g. ``"cluster:C1"``.
    """
    return CLUSTER_PROBLEM_PREFIX + entity_id


@dataclass(frozen=True)
class Individual(Scope):
    """One design problem per location.

    Parameters
    ----------
    index : EntityIndex, default PointIndex()
        Entity index definition.

    Raises
    ------
    ComponentConfigError
        If ``index`` is not an :class:`EntityIndex`.
    """

    name: ClassVar[str] = "individual"

    index: EntityIndex = field(default_factory=PointIndex)

    def __post_init__(self) -> None:
        """Validate the parameters."""
        _check_index(self.index)

    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        """One spec per location, in EventSet order (see ``Scope.partition``).

        Parameters
        ----------
        eventset : EventSet
            Calibration data.

        Returns
        -------
        tuple of ProblemSpec
            ``problem_id`` and ``entity_id`` equal the ``location_id``.
        """
        return tuple(
            ProblemSpec(problem_id=loc, entities=(Entity(loc, (loc,)),))
            for loc in eventset.location_ids
        )

    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        """Build one location's design problem (see ``Scope.materialise``).

        The EventSet may hold other locations; they are not part of this
        design problem.

        Raises
        ------
        EntityMismatchError
            If the spec is not one entity with one location, or that location
            is not in the EventSet.
        """
        if len(spec.entities) != 1 or len(spec.entities[0].location_ids) != 1:
            raise EntityMismatchError(
                f"problem {spec.problem_id!r}: an individual-scope spec has one "
                "entity with one location"
            )
        return _materialise(eventset, spec, self.index)


@dataclass(frozen=True)
class Portfolio(Scope):
    """All locations jointly, one payout entity per location.

    Parameters
    ----------
    index : EntityIndex, default PointIndex()
        Entity index definition.

    Raises
    ------
    ComponentConfigError
        If ``index`` is not an :class:`EntityIndex`.
    """

    name: ClassVar[str] = "portfolio"

    index: EntityIndex = field(default_factory=PointIndex)

    def __post_init__(self) -> None:
        """Validate the parameters."""
        _check_index(self.index)

    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        """One spec with one entity per location (see ``Scope.partition``).

        Parameters
        ----------
        eventset : EventSet
            Calibration data.

        Returns
        -------
        tuple of ProblemSpec
            One spec, ``problem_id = "portfolio"``, entities in EventSet
            order with ``entity_id`` = ``location_id``.
        """
        entities = tuple(Entity(loc, (loc,)) for loc in eventset.location_ids)
        return (ProblemSpec(problem_id=PORTFOLIO_PROBLEM_ID, entities=entities),)

    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        """Build the portfolio design problem (see ``Scope.materialise``).

        Raises
        ------
        EntityMismatchError
            If an entity covers more than one location, or the spec and the
            EventSet do not cover the same locations (an uncovered location
            would drop out of the portfolio loss silently).
        """
        multi = [e.entity_id for e in spec.entities if len(e.location_ids) != 1]
        if multi:
            raise EntityMismatchError(
                f"problem {spec.problem_id!r}: portfolio-scope entities have one "
                f"location each, not {multi}"
            )
        _check_covers_all(eventset, spec)
        return _materialise(eventset, spec, self.index)


@dataclass(frozen=True)
class Cluster(Scope):
    """One payout entity per cluster, calibrated jointly or cluster by cluster.

    Parameters
    ----------
    strategy : ClusteringStrategy
        How locations are grouped, e.g.
        :class:`~parametric_insurance_design.clustering.ThesisWardClustering`.
    n_clusters : int
        Number of clusters, >= 1 (and at most the number of locations).
    index : EntityIndex, default ValueWeightedIndex()
        Entity index definition.
    joint : bool, default True
        True (the thesis): one design problem over all clusters
        (``problem_id = "portfolio"``), objective and budget on the
        portfolio's summed loss and payout. False: one design problem per
        cluster (``problem_id`` = :func:`cluster_problem_id` of its entity
        id), each on its cluster's index and summed loss, with its own
        objective and budget (``kappa * E[L_cluster]`` under a
        :class:`~parametric_insurance_design.constraints.Budget`), as the
        individual scope does per location. Same clusters and same index
        either way.

    Raises
    ------
    ComponentConfigError
        If ``strategy`` is not a :class:`ClusteringStrategy`, ``n_clusters`` is
        not an integer >= 1, ``index`` is not an :class:`EntityIndex`, or
        ``joint`` is not a bool.

    Notes
    -----
    ``name`` is ``"cluster"`` for both settings (``runs.scope``); the
    experiment config records ``joint: false`` and so the config hash.
    """

    name: ClassVar[str] = "cluster"

    strategy: ClusteringStrategy
    n_clusters: int
    index: EntityIndex = field(default_factory=ValueWeightedIndex)
    joint: bool = True

    def __post_init__(self) -> None:
        """Validate the parameters."""
        if not isinstance(self.strategy, ClusteringStrategy):
            raise ComponentConfigError(
                f"strategy must be a ClusteringStrategy, got {self.strategy!r}"
            )
        n = self.n_clusters
        if isinstance(n, bool) or not isinstance(n, int | np.integer) or n < 1:
            raise ComponentConfigError(f"n_clusters must be an integer >= 1, got {n!r}")
        object.__setattr__(self, "n_clusters", int(n))
        _check_index(self.index)
        if not isinstance(self.joint, bool):
            raise ComponentConfigError(f"joint must be a bool, got {self.joint!r}")

    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        """Cluster the locations into design problems (see ``Scope.partition``).

        Parameters
        ----------
        eventset : EventSet
            Calibration data. The strategy clusters on it, so pass the
            training sample only.

        Returns
        -------
        tuple of ProblemSpec
            Entities ``C1 .. C<n_clusters>`` in label order, each listing its
            locations in EventSet order. ``joint=True``: one spec,
            ``problem_id = "portfolio"``, with every entity. ``joint=False``:
            one single-entity spec per cluster, in label order,
            ``problem_id`` = :func:`cluster_problem_id` (``"cluster:C1"``,
            ...).

        Raises
        ------
        InputMismatchError
            If ``n_clusters`` exceeds the number of locations.
        EntityMismatchError
            If the strategy's assignment misses or adds a location, uses a
            label outside ``1 .. n_clusters``, or leaves a cluster empty.
        """
        ids = eventset.location_ids
        if self.n_clusters > len(ids):
            raise InputMismatchError(
                f"n_clusters={self.n_clusters} exceeds the {len(ids)} locations"
            )
        assignment = dict(self.strategy.assign(eventset, self.n_clusters))
        missing = [loc for loc in ids if loc not in assignment]
        extra = sorted(set(assignment) - set(ids))
        if missing or extra:
            raise EntityMismatchError(
                f"cluster assignment does not match the EventSet locations: "
                f"missing {missing}, unknown {extra}"
            )
        labels = range(1, self.n_clusters + 1)
        bad = {loc: c for loc, c in assignment.items() if c not in labels}
        if bad:
            raise EntityMismatchError(
                f"cluster labels must be in 1..{self.n_clusters}, got {bad}"
            )
        members = {c: tuple(loc for loc in ids if assignment[loc] == c) for c in labels}
        empty = [c for c, locs in members.items() if not locs]
        if empty:
            raise EntityMismatchError(f"clusters {empty} have no locations")
        entities = tuple(Entity(f"C{c}", members[c]) for c in labels)
        if not self.joint:
            return tuple(
                ProblemSpec(problem_id=cluster_problem_id(e.entity_id), entities=(e,))
                for e in entities
            )
        return (ProblemSpec(problem_id=PORTFOLIO_PROBLEM_ID, entities=entities),)

    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        """Build a cluster design problem (see ``Scope.materialise``).

        ``joint=True``: the spec covers every location of the EventSet.
        ``joint=False``: the spec is one cluster; the EventSet may hold other
        locations, which are not part of this design problem.

        Raises
        ------
        EntityMismatchError
            ``joint=True``: if the spec and the EventSet do not cover the same
            locations. ``joint=False``: if the spec is not one entity, or a
            location of it is not in the EventSet. Either: if the index is
            undefined for an entity.
        """
        if self.joint:
            _check_covers_all(eventset, spec)
        elif len(spec.entities) != 1:
            raise EntityMismatchError(
                f"problem {spec.problem_id!r}: a separately calibrated cluster "
                f"(joint=False) is one entity, not {list(spec.entity_ids)}"
            )
        return _materialise(eventset, spec, self.index)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _check_index(index: object) -> None:
    """Check that a scope got an entity index definition."""
    if not isinstance(index, EntityIndex):
        raise ComponentConfigError(f"index must be an EntityIndex, got {index!r}")


def _check_covers_all(eventset: EventSet, spec: ProblemSpec) -> None:
    """Joint scopes: the spec covers exactly the EventSet's locations."""
    covered = set(spec.location_ids)
    present = eventset.location_ids
    missing = sorted(covered - set(present))
    uncovered = [loc for loc in present if loc not in covered]
    if missing or uncovered:
        raise EntityMismatchError(
            f"problem {spec.problem_id!r}: spec and EventSet locations differ: "
            f"not in the EventSet {missing}, not in the spec {uncovered}"
        )


def _entity_loss(eventset: EventSet, entities: Sequence[Entity]) -> NDArray[np.float64]:
    """Loss per entity: the sum over its locations, ``(n_rows, n_entities)``."""
    out = np.empty((eventset.n_rows, len(entities)), dtype=np.float64)
    for j, entity in enumerate(entities):
        cols = location_columns(eventset, entity.location_ids)
        # C-contiguous, as the thesis' np.column_stack, for the same summation
        # order (bit-identical cluster losses).
        out[:, j] = np.ascontiguousarray(eventset.loss[:, cols]).sum(axis=1)
    return out


def _materialise(
    eventset: EventSet, spec: ProblemSpec, index: EntityIndex
) -> DesignProblem:
    """Entity index and entity losses of a spec on an EventSet."""
    loss = _entity_loss(eventset, spec.entities)
    xi = index.compute(eventset, spec.entities)
    return DesignProblem(spec=spec, index=xi, entity_loss=loss)
