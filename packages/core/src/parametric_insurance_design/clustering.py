"""Clustering strategies for the cluster scope (SPEC §4.2).

Owner: MAR-12. Port of the thesis feature-plus-Ward clustering: features log
value, tail share, tail beta, sigma_L and mu_W, z-scored, Ward linkage. New
clustering methods are parked (SPEC §9).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from parametric_insurance_design.eventset import EventSet

__all__ = ["ClusteringStrategy", "ThesisWardClustering"]


@runtime_checkable
class ClusteringStrategy(Protocol):
    """Assigns locations to clusters."""

    def assign(self, eventset: EventSet, n_clusters: int) -> Mapping[str, int]:
        """Assign every location to a cluster.

        Parameters
        ----------
        eventset : EventSet
            Calibration data (training sample only, to avoid leakage).
        n_clusters : int
            Number of clusters, ``1 <= n_clusters <= n_locations``.

        Returns
        -------
        mapping of str to int
            ``location_id`` to cluster label ``1 .. n_clusters``. Labels are
            deterministic and follow the thesis ordering.
        """
        ...


@dataclass(frozen=True)
class ThesisWardClustering:
    """The thesis clustering: risk features, z-scores, Ward linkage.

    Parameters
    ----------
    beta_tail : float
        Quantile level of the tail features (thesis ``TAIL_QUANTILE_LEVEL``).
    linkage : str, default "ward"
        Hierarchical linkage method.
    """

    beta_tail: float
    linkage: str = "ward"

    def assign(self, eventset: EventSet, n_clusters: int) -> Mapping[str, int]:
        """See :meth:`ClusteringStrategy.assign`."""
        raise NotImplementedError("MAR-12")  # pragma: no cover
