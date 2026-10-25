"""Entity index definitions (SPEC §4.2, §6.3).

Owner: MAR-12. Scopes use an :class:`EntityIndex` to turn the EventSet's
per-location ``index`` matrix into the entity index ``xi`` of a design
problem.

* :class:`PointIndex`: each entity covers one location and uses that
  location's index column. This also covers **precomputed** custom indices:
  an adapter writes them into the EventSet ``index`` column (e.g. the
  cat-in-a-circle index of MAR-26, with ``metadata.index`` saying so), and the
  core needs no extra code for them.
* :class:`ValueWeightedIndex`: the value-weighted mean of the members' index
  (the thesis cluster index), weights from ``locations.value``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import Entity

__all__ = ["EntityIndex", "PointIndex", "ValueWeightedIndex"]


class EntityIndex(ABC):
    """Computes the index of payout entities from an EventSet."""

    @abstractmethod
    def compute(
        self, eventset: EventSet, entities: Sequence[Entity]
    ) -> NDArray[np.float64]:
        """Return the entity index.

        Parameters
        ----------
        eventset : EventSet
            Source of the per-location index and location values.
        entities : sequence of Entity
            The entities, in order.

        Returns
        -------
        numpy.ndarray
            Shape ``(n_rows, n_entities)``.

        Raises
        ------
        EntityMismatchError
            If an entity covers a location not in the EventSet, or the index
            is not defined for the entity (e.g. a multi-location entity for
            :class:`PointIndex`).
        """


@dataclass(frozen=True)
class PointIndex(EntityIndex):
    """Index at the location of single-location entities."""

    def compute(
        self, eventset: EventSet, entities: Sequence[Entity]
    ) -> NDArray[np.float64]:
        """See :meth:`EntityIndex.compute`."""
        raise NotImplementedError("MAR-12")  # pragma: no cover


@dataclass(frozen=True)
class ValueWeightedIndex(EntityIndex):
    """Value-weighted mean index over each entity's locations."""

    def compute(
        self, eventset: EventSet, entities: Sequence[Entity]
    ) -> NDArray[np.float64]:
        """See :meth:`EntityIndex.compute`."""
        raise NotImplementedError("MAR-12")  # pragma: no cover
