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

from parametric_insurance_design.errors import EntityMismatchError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import Entity

__all__ = ["EntityIndex", "PointIndex", "ValueWeightedIndex", "location_columns"]


def location_columns(
    eventset: EventSet, location_ids: Sequence[str]
) -> NDArray[np.intp]:
    """Matrix columns of locations in an EventSet.

    Parameters
    ----------
    eventset : EventSet
        The EventSet.
    location_ids : sequence of str
        Locations to look up.

    Returns
    -------
    numpy.ndarray
        Column positions, in the order of ``location_ids``.

    Raises
    ------
    EntityMismatchError
        If a location is not in the EventSet.
    """
    position = {loc: i for i, loc in enumerate(eventset.location_ids)}
    missing = [loc for loc in location_ids if loc not in position]
    if missing:
        raise EntityMismatchError(f"locations not in the EventSet: {missing}")
    return np.array([position[loc] for loc in location_ids], dtype=np.intp)


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
    """Index at the location of single-location entities.

    Entity ``j`` gets the EventSet ``index`` column of its one location.
    """

    def compute(
        self, eventset: EventSet, entities: Sequence[Entity]
    ) -> NDArray[np.float64]:
        """See :meth:`EntityIndex.compute`.

        Raises
        ------
        EntityMismatchError
            If an entity covers more than one location, or a location not in
            the EventSet.
        """
        multi = [e.entity_id for e in entities if len(e.location_ids) != 1]
        if multi:
            raise EntityMismatchError(
                f"PointIndex needs single-location entities, got {multi}"
            )
        cols = location_columns(eventset, [e.location_ids[0] for e in entities])
        return np.array(eventset.index[:, cols], dtype=np.float64)


@dataclass(frozen=True)
class ValueWeightedIndex(EntityIndex):
    """Value-weighted mean index over each entity's locations.

    The thesis cluster index: entity ``j`` with locations ``i`` gets
    ``xi_j = sum_i w_i W_i`` with ``w_i = value_i / sum_k value_k``, the values
    from ``locations.value``. For a single-location entity this is that
    location's index.
    """

    def compute(
        self, eventset: EventSet, entities: Sequence[Entity]
    ) -> NDArray[np.float64]:
        """See :meth:`EntityIndex.compute`.

        Raises
        ------
        EntityMismatchError
            If an entity covers a location not in the EventSet, or all its
            locations have value 0, so that the weights are undefined (the
            thesis set the index to 0 then).
        """
        values = eventset.locations["value"].to_numpy(dtype=np.float64)
        out = np.empty((eventset.n_rows, len(entities)), dtype=np.float64)
        for j, entity in enumerate(entities):
            cols = location_columns(eventset, entity.location_ids)
            vals = values[cols]
            total = float(vals.sum())
            if total <= 0.0:
                raise EntityMismatchError(
                    f"entity {entity.entity_id!r}: value-weighted index undefined, "
                    "every location has value 0"
                )
            # C-contiguous, as the thesis' np.column_stack: the product then
            # adds in the same order and the index is bit-identical.
            members = np.ascontiguousarray(eventset.index[:, cols])
            out[:, j] = members @ (vals / total)
        return out
