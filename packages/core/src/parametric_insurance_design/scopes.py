"""Scopes: individual, portfolio and cluster (SPEC §4.2, §6).

Owner: MAR-12. The interface is
:class:`~parametric_insurance_design.interfaces.Scope` (ADR 0002).

* :class:`Individual`: one design problem per location (``problem_id`` =
  ``location_id``), one entity each.
* :class:`Portfolio`: one design problem (``problem_id = "portfolio"``),
  one entity per location, objective on the summed loss and payout.
* :class:`Cluster`: one design problem (``"portfolio"``), one entity per
  cluster (``entity_id`` = ``"C1"``, ``"C2"``, ...), index from
  :class:`~parametric_insurance_design.index.ValueWeightedIndex`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Final

from parametric_insurance_design.clustering import ClusteringStrategy
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.index import (
    EntityIndex,
    PointIndex,
    ValueWeightedIndex,
)
from parametric_insurance_design.interfaces import DesignProblem, ProblemSpec, Scope

__all__ = ["PORTFOLIO_PROBLEM_ID", "Cluster", "Individual", "Portfolio", "Scope"]

PORTFOLIO_PROBLEM_ID: Final[str] = "portfolio"
"""``problem_id`` of the single design problem of joint scopes."""


@dataclass(frozen=True)
class Individual(Scope):
    """One design problem per location.

    Parameters
    ----------
    index : EntityIndex, default PointIndex()
        Entity index definition.
    """

    name: ClassVar[str] = "individual"

    index: EntityIndex = field(default_factory=PointIndex)

    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        """See ``Scope.partition``."""
        raise NotImplementedError("MAR-12")  # pragma: no cover

    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        """See ``Scope.materialise``."""
        raise NotImplementedError("MAR-12")  # pragma: no cover


@dataclass(frozen=True)
class Portfolio(Scope):
    """All locations jointly, one payout entity per location.

    Parameters
    ----------
    index : EntityIndex, default PointIndex()
        Entity index definition.
    """

    name: ClassVar[str] = "portfolio"

    index: EntityIndex = field(default_factory=PointIndex)

    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        """See ``Scope.partition``."""
        raise NotImplementedError("MAR-12")  # pragma: no cover

    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        """See ``Scope.materialise``."""
        raise NotImplementedError("MAR-12")  # pragma: no cover


@dataclass(frozen=True)
class Cluster(Scope):
    """All locations jointly, one payout entity per cluster.

    Parameters
    ----------
    strategy : ClusteringStrategy
        How locations are grouped.
    n_clusters : int
        Number of clusters.
    index : EntityIndex, default ValueWeightedIndex()
        Entity index definition.
    """

    name: ClassVar[str] = "cluster"

    strategy: ClusteringStrategy
    n_clusters: int
    index: EntityIndex = field(default_factory=ValueWeightedIndex)

    def partition(self, eventset: EventSet) -> tuple[ProblemSpec, ...]:
        """See ``Scope.partition``."""
        raise NotImplementedError("MAR-12")  # pragma: no cover

    def materialise(self, eventset: EventSet, spec: ProblemSpec) -> DesignProblem:
        """See ``Scope.materialise``."""
        raise NotImplementedError("MAR-12")  # pragma: no cover
