"""Clustering strategies for the cluster scope (SPEC §4.2).

Owner: MAR-12. Port of the thesis feature-plus-Ward clustering
(``ClusterLevelIntegratedOptimizationApproach._compute_features`` and
``_cluster_assets`` in the thesis notebook): per location the features log
value, tail share, tail beta, sigma_L and mu_W, z-scored, then hierarchical
clustering with Ward linkage, cut into ``n_clusters`` clusters with scipy's
``fcluster(..., criterion="maxclust")``. Cluster labels are scipy's labels,
as in the thesis (scipy 1.17). New clustering methods are parked (SPEC §9).

scipy < 1.15 cuts most trees into too few clusters with ``maxclust`` (seen
with 1.11 to 1.14), hence the core's ``scipy>=1.15`` floor. :meth:`assign
<ThesisWardClustering.assign>` raises if the cut misses ``n_clusters``.

The features (thesis definitions, ``p`` the row probabilities ``rate / sum
rate`` of the calibration data, ``L_port`` the summed loss over all
locations, the portfolio tail the rows with ``L_port >= VaR_beta(L_port)``):

``log_value``
    ``log(max(value, 1))``.
``tail_share``
    ``E[L_i / (L_port + eps) | tail]``.
``tail_beta_port``
    ``Cov(L_i, L_port | tail) / (Var(L_port | tail) + eps)``.
``sigma_L``
    Standard deviation over the other locations ``j`` of the loss distance
    ``1 - Corr(L_i, L_j)``.
``mu_W``
    Mean over the other locations of the index distance
    ``1 - Corr(W_i, W_j)``.

All moments are weighted by ``p`` (in the tail by ``p`` renormalised on the
tail rows), with ``eps = 1e-12``.

**Row probabilities on every basis.** ``p`` is ``rate / sum(rate)`` over the
calibration rows, the ``event_conditional`` measure, whatever the run's
basis. On the ``event`` basis the "no event" mass, and on the ``annual``
basis the grouping of rows into (year, draw) outcomes, do not enter the
features. This is the thesis definition, ported as is: the thesis has only
the event-conditional measure, and keeping it reproduces the thesis
assignment. The assignment therefore depends on the calibration rows alone,
not on the basis. A threshold filter drops rows, which removes their
probability from ``p``, so it can change the features.

**Degenerate tail.** Losses are ``>= 0``. If at least ``beta_tail`` of ``p``
lies on rows with zero portfolio loss, ``VaR_beta_tail(L_port) = 0`` and the
"tail" would be every row, so ``tail_share`` and ``tail_beta_port`` would be
whole-sample features. :meth:`ThesisWardClustering.features` raises
:class:`DegenerateTailError` in that case instead of falling back silently.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import ClassVar, Final, Protocol, runtime_checkable

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from parametric_insurance_design.errors import ComponentConfigError, InputMismatchError
from parametric_insurance_design.eventset import EventSet

__all__ = [
    "FEATURE_NAMES",
    "LINKAGE_METHODS",
    "ClusteringStrategy",
    "DegenerateTailError",
    "ThesisWardClustering",
]

FEATURE_NAMES: Final[tuple[str, ...]] = (
    "log_value",
    "tail_share",
    "tail_beta_port",
    "sigma_L",
    "mu_W",
)
"""Columns of :meth:`ThesisWardClustering.features`, in the thesis order."""

LINKAGE_METHODS: Final[frozenset[str]] = frozenset(
    {"single", "complete", "average", "weighted", "centroid", "median", "ward"}
)
"""Linkage methods accepted by :class:`ThesisWardClustering` (scipy's)."""

_EPS: Final[float] = 1e-12
"""The thesis' guard against division by zero."""


class DegenerateTailError(InputMismatchError):
    """The portfolio tail of the clustering features would be every row.

    Raised by :meth:`ThesisWardClustering.features` (and so by ``assign``)
    when at least ``beta_tail`` of the row probability has zero portfolio
    loss, so that ``VaR_beta_tail(L_port) = 0``. The tail features would then
    be whole-sample features. A ``beta_tail`` above the zero-loss share
    stated in the message gives a tail of rows with positive portfolio loss,
    unless every row has zero portfolio loss.
    """


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
        Quantile level of the tail features (thesis ``TAIL_QUANTILE_LEVEL``,
        0.90), in ``(0, 1)``.
    linkage : str, default "ward"
        Hierarchical linkage method, one of :data:`LINKAGE_METHODS`. ``"ward"``
        clusters the z-scored features directly; the others use their
        Euclidean distances (thesis).

    Raises
    ------
    ComponentConfigError
        If ``beta_tail`` is not in ``(0, 1)`` or ``linkage`` is unknown.

    Examples
    --------
    >>> strategy = ThesisWardClustering(beta_tail=0.90)
    >>> labels = strategy.assign(eventset, n_clusters=3)  # doctest: +SKIP
    """

    name: ClassVar[str] = "thesis_ward"

    beta_tail: float
    linkage: str = "ward"

    def __post_init__(self) -> None:
        """Validate the parameters."""
        beta = self.beta_tail
        if isinstance(beta, bool) or not isinstance(beta, int | float | np.number):
            raise ComponentConfigError(f"beta_tail must be a number, got {beta!r}")
        if not 0.0 < float(beta) < 1.0:
            raise ComponentConfigError(f"beta_tail must be in (0, 1), got {beta!r}")
        object.__setattr__(self, "beta_tail", float(beta))
        if self.linkage not in LINKAGE_METHODS:
            raise ComponentConfigError(
                f"linkage must be one of {sorted(LINKAGE_METHODS)}, "
                f"got {self.linkage!r}"
            )

    def features(self, eventset: EventSet) -> pd.DataFrame:
        """Compute the thesis clustering features.

        Rows are weighted by their probability ``rate / sum(rate)`` on every
        basis (thesis definition; see the module docstring). The tail is the
        rows with ``L_port >= VaR_beta_tail(L_port)``.

        Parameters
        ----------
        eventset : EventSet
            Calibration data with at least one row.

        Returns
        -------
        pandas.DataFrame
            One row per location (index ``location_id``, EventSet order), the
            columns :data:`FEATURE_NAMES`. Not z-scored.

        Raises
        ------
        InputMismatchError
            If the EventSet has no rows.
        DegenerateTailError
            If ``VaR_beta_tail(L_port) = 0``, i.e. at least ``beta_tail`` of
            the row probability has zero portfolio loss: the tail would be
            every row.
        """
        if eventset.n_rows == 0:
            raise InputMismatchError("cannot compute clustering features on 0 rows")
        p = eventset.rates
        p = p / p.sum()
        # C-contiguous copies, as the thesis' np.column_stack, so that the row
        # sums below add in the same order.
        loss = np.ascontiguousarray(eventset.loss, dtype=np.float64)
        wind = np.ascontiguousarray(eventset.index, dtype=np.float64)

        loss_port = loss.sum(axis=1)
        var_port = _weighted_quantile(loss_port, p, self.beta_tail)
        if var_port <= 0.0:
            # Losses are >= 0, so the tail below would be every row.
            zero_share = float(p[loss_port <= 0.0].sum())
            hint = (
                "choose a beta_tail above that share"
                if (loss_port > 0.0).any()
                else "every row has zero portfolio loss"
            )
            raise DegenerateTailError(
                f"degenerate portfolio tail: {zero_share:.4%} of the row "
                "probability has zero portfolio loss, at least "
                f"beta_tail={self.beta_tail:g}, so VaR_beta_tail(L_port) = 0 and "
                f"the tail features would be whole-sample features; {hint}"
            )
        tail = loss_port >= var_port  # never empty: var_port is a value of it
        p_tail = p[tail]
        p_tail = p_tail / p_tail.sum()
        loss_tail = loss[tail, :]
        loss_port_tail = loss_port[tail]

        dist_loss = 1.0 - _weighted_corr_matrix(loss, p)
        dist_wind = 1.0 - _weighted_corr_matrix(wind, p)
        var_port_tail = _weighted_cov(loss_port_tail, loss_port_tail, p_tail)

        values = eventset.locations["value"].to_numpy(dtype=np.float64)
        n = eventset.n_locations
        rows: list[list[float]] = []
        for i in range(n):
            loss_i_tail = loss_tail[:, i]
            share = _weighted_mean(loss_i_tail / (loss_port_tail + _EPS), p_tail)
            cov = _weighted_cov(loss_i_tail, loss_port_tail, p_tail)
            tail_beta = float(cov / (var_port_tail + _EPS))
            others = [j for j in range(n) if j != i]
            if others:
                sigma_loss = float(np.std(dist_loss[i, others]))
                mu_wind = float(np.mean(dist_wind[i, others]))
            else:
                sigma_loss, mu_wind = 0.0, 0.0
            rows.append(
                [
                    float(np.log(max(float(values[i]), 1.0))),
                    share,
                    tail_beta,
                    sigma_loss,
                    mu_wind,
                ]
            )
        return pd.DataFrame(
            rows,
            index=pd.Index(eventset.location_ids, name="location_id"),
            columns=list(FEATURE_NAMES),
            dtype=np.float64,
        )

    def assign(self, eventset: EventSet, n_clusters: int) -> Mapping[str, int]:
        """Assign every location to a cluster (see :class:`ClusteringStrategy`).

        Parameters
        ----------
        eventset : EventSet
            Calibration data (training sample only, to avoid leakage).
        n_clusters : int
            Number of clusters, ``1 <= n_clusters <= n_locations``.

        Returns
        -------
        dict of str to int
            ``location_id`` to scipy ``fcluster`` label ``1 .. n_clusters``,
            in EventSet location order.

        Raises
        ------
        ComponentConfigError
            If ``n_clusters`` is not an integer >= 1.
        InputMismatchError
            If ``n_clusters`` exceeds the number of locations, the EventSet has
            no rows, or ties in the dendrogram leave fewer than ``n_clusters``
            clusters (the thesis code would fail on the empty cluster).
        DegenerateTailError
            If the features' portfolio tail would be every row (see
            :meth:`features`). Not checked for a single location, which needs
            no features.
        """
        _check_n_clusters(n_clusters, eventset.n_locations)
        ids = eventset.location_ids
        if eventset.n_locations == 1:
            # scipy needs two observations; one location is one cluster.
            if eventset.n_rows == 0:
                raise InputMismatchError("cannot cluster on 0 rows")
            return {ids[0]: 1}
        x = self.features(eventset).to_numpy(dtype=np.float64)
        xz = _zscore(x)
        if self.linkage == "ward":
            tree = linkage(xz, method="ward")
        else:
            tree = linkage(pdist(xz, metric="euclidean"), method=self.linkage)
        labels = fcluster(tree, t=n_clusters, criterion="maxclust")
        found = len(set(labels.tolist()))
        if found != n_clusters:
            raise InputMismatchError(
                f"{self.linkage} linkage yields {found} clusters, not {n_clusters}: "
                "ties in the dendrogram (e.g. locations with identical features)"
                " or scipy < 1.15, whose maxclust cut returns too few clusters"
            )
        return {loc: int(label) for loc, label in zip(ids, labels, strict=True)}


def _check_n_clusters(n_clusters: object, n_locations: int) -> None:
    """Validate a cluster count against the number of locations."""
    if (
        isinstance(n_clusters, bool)
        or not isinstance(n_clusters, int | np.integer)
        or n_clusters < 1
    ):
        raise ComponentConfigError(
            f"n_clusters must be an integer >= 1, got {n_clusters!r}"
        )
    if n_clusters > n_locations:
        raise InputMismatchError(
            f"n_clusters={n_clusters} exceeds the {n_locations} locations"
        )


# --------------------------------------------------------------------------
# Weighted moments, as in the thesis (weights are > 0 and sum to > 0 here)
# --------------------------------------------------------------------------


def _weighted_mean(x: NDArray[np.float64], w: NDArray[np.float64]) -> float:
    """Weighted mean ``sum(w x) / sum(w)``."""
    return float(np.sum(w * x) / float(np.sum(w)))


def _weighted_cov(
    x: NDArray[np.float64], y: NDArray[np.float64], w: NDArray[np.float64]
) -> float:
    """Weighted population covariance."""
    wsum = float(np.sum(w))
    mx = np.sum(w * x) / wsum
    my = np.sum(w * y) / wsum
    return float(np.sum(w * (x - mx) * (y - my)) / wsum)


def _weighted_corr_matrix(
    x: NDArray[np.float64], w: NDArray[np.float64]
) -> NDArray[np.float64]:
    """Weighted correlation of every pair of columns, ones on the diagonal.

    The thesis' pairwise ``_weighted_corr``,
    ``clip(cov / (sqrt(max(var_x, 0) max(var_y, 0)) + eps), -1, 1)``, with the
    same pairwise loop and operation order, so that the results are
    bit-identical. The variances are computed once per column. The loop costs
    ``O(n_locations**2 * n_rows)``.
    """
    n = x.shape[1]
    cols = [np.ascontiguousarray(x[:, i]) for i in range(n)]
    var = [max(_weighted_cov(c, c, w), 0.0) for c in cols]
    corr = np.eye(n)
    for i in range(n):
        for j in range(i + 1, n):
            c = _weighted_cov(cols[i], cols[j], w)
            denom = np.sqrt(var[i] * var[j]) + _EPS
            corr[i, j] = corr[j, i] = float(np.clip(c / denom, -1.0, 1.0))
    return corr


def _weighted_quantile(
    x: NDArray[np.float64], w: NDArray[np.float64], q: float
) -> float:
    """Probability-weighted quantile: smallest ``x`` with ``CDF(x) >= q``."""
    order = np.argsort(x)
    xs = x[order]
    cdf = np.cumsum(w[order])
    cdf = cdf / cdf[-1]
    return float(xs[np.searchsorted(cdf, q, side="left")])


def _zscore(x: NDArray[np.float64]) -> NDArray[np.float64]:
    """Column z-scores with population standard deviation (thesis)."""
    mu = x.mean(axis=0, keepdims=True)
    sd = x.std(axis=0, keepdims=True)
    return (x - mu) / (sd + _EPS)
