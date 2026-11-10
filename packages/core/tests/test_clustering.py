"""Tests for the thesis Ward clustering (MAR-12, MAR-172).

Thesis parity on the Miami fixture is in ``parity/tests/test_clustering_parity.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import pdist

from parametric_insurance_design.clustering import (
    FEATURE_NAMES,
    LINKAGE_METHODS,
    ClusteringStrategy,
    DegenerateTailError,
    ThesisWardClustering,
    _weighted_quantile,
    _zscore,
)
from parametric_insurance_design.errors import (
    ComponentConfigError,
    InputMismatchError,
    ParametricInsuranceDesignError,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import load_config
from parametric_insurance_design.experiment.runner import prepare_eventset
from parametric_insurance_design.scopes import Cluster

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"


def make_eventset(
    base: EventSet,
    index: np.ndarray,
    loss: np.ndarray,
    values: list[float],
    rates: np.ndarray | None = None,
) -> EventSet:
    """An EventSet with the given matrices, using ``base``'s metadata."""
    n_rows, n_locations = index.shape
    if rates is None:
        rates = np.full(n_rows, 1.0 / max(n_rows, 1))
    events = pd.DataFrame(
        {
            "event_id": [f"ev{i}" for i in range(n_rows)],
            "year": np.arange(n_rows, dtype=np.int64) % base.metadata.n_years,
            "rate": rates,
            "draw_id": np.zeros(n_rows, dtype=np.int64),
            "scenario_id": ["toy"] * n_rows,
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": [f"L{j}" for j in range(n_locations)],
            "lat": np.zeros(n_locations),
            "lon": np.zeros(n_locations),
            "value": values,
            "name": [f"loc {j}" for j in range(n_locations)],
        }
    )
    return EventSet(
        events=events,
        locations=locations,
        index=index,
        loss=loss,
        metadata=base.metadata,
    )


def two_group_eventset(base: EventSet, n_per_group: int = 3) -> EventSet:
    """Two groups of locations: large, tail-heavy ones and small ones.

    Group 1 (L0..) has high value and carries the portfolio tail; group 2 has
    low value and its losses are driven by a different wind field.
    """
    rng = np.random.default_rng(12345)
    n_rows = 400
    storm_1 = rng.gamma(2.0, 10.0, n_rows)
    storm_2 = rng.gamma(2.0, 10.0, n_rows)
    cols_w, cols_l, values = [], [], []
    for g, (storm, value) in enumerate(((storm_1, 1e8), (storm_2, 1e5))):
        for k in range(n_per_group):
            wind = storm * (1.0 + 0.05 * k) + rng.normal(0.0, 1.0 + g, n_rows)
            cols_w.append(np.maximum(wind, 0.0))
            cols_l.append(value * np.clip((wind - 20.0) / 50.0, 0.0, 1.0) ** 2)
            values.append(value * (1.0 + 0.1 * k))
    return make_eventset(base, np.column_stack(cols_w), np.column_stack(cols_l), values)


# --------------------------------------------------------------------------
# Parameters
# --------------------------------------------------------------------------


def test_is_a_clustering_strategy() -> None:
    strategy = ThesisWardClustering(beta_tail=0.9)
    assert isinstance(strategy, ClusteringStrategy)
    assert strategy.linkage == "ward"
    assert strategy.name == "thesis_ward"


@pytest.mark.parametrize("beta", [0.0, 1.0, -0.1, 1.5, True, "0.9", None])
def test_rejects_invalid_beta_tail(beta: object) -> None:
    with pytest.raises(ComponentConfigError, match="beta_tail"):
        ThesisWardClustering(beta_tail=beta)  # type: ignore[arg-type]


def test_beta_tail_becomes_a_float() -> None:
    strategy = ThesisWardClustering(beta_tail=np.float32(0.5))  # type: ignore[arg-type]
    assert type(strategy.beta_tail) is float


def test_rejects_unknown_linkage() -> None:
    with pytest.raises(ComponentConfigError, match="linkage"):
        ThesisWardClustering(beta_tail=0.9, linkage="kmeans")


# --------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------


def test_weighted_quantile_is_the_smallest_value_with_cdf_at_least_q() -> None:
    x = np.array([3.0, 1.0, 2.0, 4.0])
    w = np.array([0.1, 0.4, 0.2, 0.3])  # sorted: 1 (0.4), 2 (0.6), 3 (0.7), 4 (1.0)
    assert _weighted_quantile(x, w, 0.4) == 1.0
    assert _weighted_quantile(x, w, 0.41) == 2.0
    assert _weighted_quantile(x, w, 0.65) == 3.0
    assert _weighted_quantile(x, w, 0.95) == 4.0


def test_zscore_uses_the_population_standard_deviation() -> None:
    x = np.array([[1.0, 5.0], [3.0, 5.0]])
    np.testing.assert_allclose(_zscore(x), [[-1.0, 0.0], [1.0, 0.0]], atol=1e-11)


def test_features_by_hand(toy_eventset: EventSet) -> None:
    # Rows equally likely; portfolio loss 1, 6, 16. VaR_0.5 = 6, tail rows 2-3.
    features = ThesisWardClustering(beta_tail=0.5).features(toy_eventset)
    assert list(features.columns) == list(FEATURE_NAMES)
    assert features.index.tolist() == ["A", "B"]
    assert features.index.name == "location_id"
    eps = 1e-12
    np.testing.assert_allclose(features["log_value"], np.log([100.0, 50.0]))
    np.testing.assert_allclose(
        features["tail_share"],
        [(4 / (6 + eps) + 10 / (16 + eps)) / 2, (2 / (6 + eps) + 6 / (16 + eps)) / 2],
        rtol=1e-14,
    )
    # Var(L_port | tail) = 25; Cov(L_A, L_port | tail) = 15, Cov(L_B, ...) = 10.
    np.testing.assert_allclose(features["tail_beta_port"], [0.6, 0.4], rtol=1e-12)
    # One other location: sigma_L = 0; index B = index A + 5, so mu_W ~ 0.
    np.testing.assert_array_equal(features["sigma_L"], [0.0, 0.0])
    np.testing.assert_allclose(features["mu_W"], [0.0, 0.0], atol=1e-12)


def test_features_use_the_rates_as_weights(toy_eventset: EventSet) -> None:
    # Putting almost all probability on the last row moves VaR to it.
    es = make_eventset(
        toy_eventset,
        np.array(toy_eventset.index),
        np.array(toy_eventset.loss),
        [100.0, 50.0],
        rates=np.array([0.01, 0.01, 0.98]),
    )
    features = ThesisWardClustering(beta_tail=0.5).features(es)
    np.testing.assert_allclose(
        features["tail_share"], [10 / (16 + 1e-12), 6 / (16 + 1e-12)], rtol=1e-14
    )


def test_log_value_is_floored_at_one(toy_eventset: EventSet) -> None:
    es = make_eventset(
        toy_eventset,
        np.array(toy_eventset.index),
        np.array(toy_eventset.loss),
        [0.5, 0.0],
    )
    features = ThesisWardClustering(beta_tail=0.5).features(es)
    np.testing.assert_array_equal(features["log_value"], [0.0, 0.0])


def test_dependence_features_by_hand(toy_eventset: EventSet) -> None:
    # Three locations: C's wind runs against A and B (correlation -1).
    index = np.array([[10.0, 15.0, 50.0], [30.0, 35.0, 30.0], [50.0, 55.0, 10.0]])
    loss = np.array([[0.0, 1.0, 5.0], [4.0, 2.0, 3.0], [10.0, 6.0, 0.0]])
    es = make_eventset(toy_eventset, index, loss, [100.0, 50.0, 10.0])
    features = ThesisWardClustering(beta_tail=0.5).features(es)
    # Wind distances 1 - corr: A-B 0, A-C 2, B-C 2.
    np.testing.assert_allclose(features["mu_W"], [1.0, 1.0, 2.0], atol=1e-11)
    corr_l = np.corrcoef(loss.T)
    dist_l = 1.0 - corr_l
    expected_sigma = [
        np.std([dist_l[0, 1], dist_l[0, 2]]),
        np.std([dist_l[1, 0], dist_l[1, 2]]),
        np.std([dist_l[2, 0], dist_l[2, 1]]),
    ]
    np.testing.assert_allclose(features["sigma_L"], expected_sigma, rtol=1e-10)


def test_features_reject_an_empty_eventset(toy_eventset: EventSet) -> None:
    empty = toy_eventset.filter_threshold(1e6)
    with pytest.raises(InputMismatchError, match="0 rows"):
        ThesisWardClustering(beta_tail=0.9).features(empty)


# --------------------------------------------------------------------------
# Degenerate tail (MAR-172, review F9)
# --------------------------------------------------------------------------


def zero_loss_eventset(base: EventSet, rates: list[float]) -> EventSet:
    """Four rows, two locations; only the last row has a portfolio loss.

    The rates are binary fractions summing to 1, so the cumulative
    probabilities, and hence the quantiles, are exact.
    """
    index = np.array([[5.0, 6.0], [10.0, 12.0], [15.0, 14.0], [40.0, 50.0]])
    loss = np.array([[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [4.0, 6.0]])
    return make_eventset(base, index, loss, [100.0, 50.0], rates=np.array(rates))


@pytest.mark.parametrize(
    ("rates", "beta_tail", "share"),
    [
        # Zero-loss probability 0.75: equal to beta_tail (VaR_0.75 = 0) ...
        ([0.25, 0.25, 0.25, 0.25], 0.75, "75.0000%"),
        # ... and above it.
        ([0.25, 0.25, 0.25, 0.25], 0.5, "75.0000%"),
        # By probability, not by row count: 3 of 4 rows (75 %) but 87.5 %.
        ([0.25, 0.25, 0.375, 0.125], 0.8, "87.5000%"),
    ],
)
def test_degenerate_tail_raises(
    toy_eventset: EventSet, rates: list[float], beta_tail: float, share: str
) -> None:
    es = zero_loss_eventset(toy_eventset, rates)
    strategy = ThesisWardClustering(beta_tail=beta_tail)
    with pytest.raises(DegenerateTailError) as info:
        strategy.features(es)
    message = str(info.value)
    assert f"{share} of the row probability has zero portfolio loss" in message
    assert f"beta_tail={beta_tail:g}" in message
    assert "choose a beta_tail above that share" in message
    with pytest.raises(DegenerateTailError):
        strategy.assign(es, 2)


@pytest.mark.parametrize(
    ("rates", "beta_tail"),
    [
        # Zero-loss probability 0.75, just below beta_tail.
        ([0.25, 0.25, 0.25, 0.25], 0.8),
        # 3 of 4 rows (75 % >= 0.75) have no loss, but only 37.5 % of the mass.
        ([0.125, 0.125, 0.125, 0.625], 0.75),
    ],
)
def test_tail_below_the_zero_loss_mass_is_the_loss_rows(
    toy_eventset: EventSet, rates: list[float], beta_tail: float
) -> None:
    es = zero_loss_eventset(toy_eventset, rates)
    features = ThesisWardClustering(beta_tail=beta_tail).features(es)
    # The tail is the last row only (portfolio loss 10).
    np.testing.assert_allclose(
        features["tail_share"], [4 / (10 + 1e-12), 6 / (10 + 1e-12)], rtol=1e-14
    )


def test_all_zero_loss_is_a_degenerate_tail(toy_eventset: EventSet) -> None:
    es = make_eventset(
        toy_eventset,
        np.array(toy_eventset.index),
        np.zeros_like(np.array(toy_eventset.loss)),
        [100.0, 50.0],
    )
    with pytest.raises(DegenerateTailError, match="every row has zero portfolio loss"):
        ThesisWardClustering(beta_tail=0.5).features(es)


def test_degenerate_tail_error_is_a_library_input_error() -> None:
    assert issubclass(DegenerateTailError, InputMismatchError)
    assert issubclass(DegenerateTailError, ParametricInsuranceDesignError)
    assert issubclass(DegenerateTailError, ValueError)


def test_cluster_scope_raises_on_a_degenerate_tail(toy_eventset: EventSet) -> None:
    # The runner records a library error raised while building as a failed run.
    es = zero_loss_eventset(toy_eventset, [0.25, 0.25, 0.25, 0.25])
    scope = Cluster(strategy=ThesisWardClustering(beta_tail=0.75), n_clusters=2)
    with pytest.raises(DegenerateTailError):
        scope.partition(es)


def test_single_location_needs_no_tail(toy_eventset: EventSet) -> None:
    # One location is one cluster without features, even with no tail.
    es = make_eventset(
        toy_eventset, np.array([[1.0], [2.0]]), np.array([[0.0], [0.0]]), [10.0]
    )
    assert dict(ThesisWardClustering(0.9).assign(es, 1)) == {"L0": 1}


# --------------------------------------------------------------------------
# The thesis data are not degenerate (MAR-172): today's assignment, pinned
# --------------------------------------------------------------------------

THESIS_ASSIGNMENTS: dict[int, str] = {
    1: "111111111",
    2: "112222222",
    3: "112222333",
    4: "112222343",
    5: "112222354",
    6: "112233465",
    7: "112234576",
    8: "112345687",
    9: "123456789",
}
"""Labels of A1 .. A9 by ``n_clusters``, on the thesis data (beta_tail 0.9).

Equal to ``parity/golden/thesis_cluster_assignments.json`` (thesis code).
"""


@pytest.fixture(scope="module")
def thesis_data() -> EventSet:
    """The parity fixture prepared as the parity config does (noise, filter)."""
    config = load_config(PARITY_CONFIG)
    return prepare_eventset(config, EventSet.from_parquet(PARITY_EVENTSET))


@pytest.mark.skipif(
    not PARITY_EVENTSET.is_dir(),
    reason="the parity fixture is only in a repository checkout",
)
def test_thesis_assignment_is_pinned(thesis_data: EventSet) -> None:
    p = thesis_data.rates / thesis_data.rates.sum()
    loss_port = np.ascontiguousarray(thesis_data.loss).sum(axis=1)
    # 32 % of the probability has zero portfolio loss, far below beta_tail 0.9.
    assert float(p[loss_port == 0.0].sum()) == pytest.approx(0.3209, abs=1e-4)
    strategy = ThesisWardClustering(beta_tail=0.9)
    assert thesis_data.location_ids == [f"A{k}" for k in range(1, 10)]
    for k, expected in THESIS_ASSIGNMENTS.items():
        labels = strategy.assign(thesis_data, k)
        assert "".join(str(labels[a]) for a in thesis_data.location_ids) == expected


@pytest.mark.skipif(
    not PARITY_EVENTSET.is_dir(),
    reason="the parity fixture is only in a repository checkout",
)
def test_unfiltered_thesis_fixture_is_not_degenerate() -> None:
    # The fixture without noise or filter: 88 % of the probability has zero
    # portfolio loss, just below beta_tail 0.9, so VaR_0.9 > 0.
    raw = EventSet.from_parquet(PARITY_EVENTSET)
    p = raw.rates / raw.rates.sum()
    loss_port = np.ascontiguousarray(raw.loss).sum(axis=1)
    assert float(p[loss_port == 0.0].sum()) == pytest.approx(0.8801, abs=1e-4)
    features = ThesisWardClustering(beta_tail=0.9).features(raw)
    assert features.notna().all().all()
    # At a beta_tail below the zero-loss share the tail would be every row.
    with pytest.raises(DegenerateTailError, match=r"88\.0\d{3}% of the row"):
        ThesisWardClustering(beta_tail=0.85).features(raw)


# --------------------------------------------------------------------------
# Assignment
# --------------------------------------------------------------------------


def test_assign_follows_scipy_ward_on_z_scored_features(
    toy_eventset: EventSet,
) -> None:
    es = two_group_eventset(toy_eventset)
    strategy = ThesisWardClustering(beta_tail=0.9)
    xz = _zscore(strategy.features(es).to_numpy())
    tree = linkage(xz, method="ward")
    for k in range(1, es.n_locations + 1):
        labels = fcluster(tree, t=k, criterion="maxclust")
        expected = dict(zip(es.location_ids, labels.tolist(), strict=True))
        assert dict(strategy.assign(es, k)) == expected


def test_assign_separates_the_two_groups(toy_eventset: EventSet) -> None:
    es = two_group_eventset(toy_eventset)
    labels = ThesisWardClustering(beta_tail=0.9).assign(es, 2)
    assert list(labels) == es.location_ids
    assert len({labels["L0"], labels["L1"], labels["L2"]}) == 1
    assert len({labels["L3"], labels["L4"], labels["L5"]}) == 1
    assert labels["L0"] != labels["L3"]


def test_assign_extremes(toy_eventset: EventSet) -> None:
    es = two_group_eventset(toy_eventset)
    strategy = ThesisWardClustering(beta_tail=0.9)
    assert set(strategy.assign(es, 1).values()) == {1}
    assert sorted(strategy.assign(es, es.n_locations).values()) == list(
        range(1, es.n_locations + 1)
    )


def test_assign_is_deterministic(toy_eventset: EventSet) -> None:
    es = two_group_eventset(toy_eventset)
    strategy = ThesisWardClustering(beta_tail=0.9)
    first = [dict(strategy.assign(es, k)) for k in range(1, 7)]
    again = [dict(ThesisWardClustering(0.9).assign(es, k)) for k in range(1, 7)]
    assert first == again


@pytest.mark.parametrize("method", sorted(LINKAGE_METHODS - {"ward"}))
def test_other_linkages_use_euclidean_distances(
    toy_eventset: EventSet, method: str
) -> None:
    es = two_group_eventset(toy_eventset)
    strategy = ThesisWardClustering(beta_tail=0.9, linkage=method)
    xz = _zscore(strategy.features(es).to_numpy())
    labels = fcluster(
        linkage(pdist(xz, metric="euclidean"), method=method),
        t=2,
        criterion="maxclust",
    )
    assert len(set(labels.tolist())) == 2
    expected = dict(zip(es.location_ids, labels.tolist(), strict=True))
    assert dict(strategy.assign(es, 2)) == expected


def test_single_location_is_one_cluster(toy_eventset: EventSet) -> None:
    es = make_eventset(
        toy_eventset, np.array([[1.0], [2.0]]), np.array([[0.0], [1.0]]), [10.0]
    )
    assert dict(ThesisWardClustering(0.9).assign(es, 1)) == {"L0": 1}


def test_single_location_has_no_dependence_features(toy_eventset: EventSet) -> None:
    # One zero-loss row of three, below beta_tail: VaR_0.5 = 1, tail rows 2-3.
    es = make_eventset(
        toy_eventset,
        np.array([[1.0], [2.0], [3.0]]),
        np.array([[0.0], [1.0], [3.0]]),
        [10.0],
    )
    features = ThesisWardClustering(0.5).features(es)
    assert features.loc["L0", "sigma_L"] == 0.0
    assert features.loc["L0", "mu_W"] == 0.0
    assert features.loc["L0", "tail_beta_port"] == pytest.approx(1.0)  # L_i = L_port


def test_single_location_with_no_rows_is_rejected(toy_eventset: EventSet) -> None:
    es = make_eventset(toy_eventset, np.zeros((0, 1)), np.zeros((0, 1)), [10.0])
    with pytest.raises(InputMismatchError, match="0 rows"):
        ThesisWardClustering(0.9).assign(es, 1)


@pytest.mark.parametrize("n", [0, -1, True, 2.0, "2"])
def test_assign_rejects_invalid_n_clusters(toy_eventset: EventSet, n: object) -> None:
    with pytest.raises(ComponentConfigError, match="n_clusters"):
        ThesisWardClustering(0.9).assign(toy_eventset, n)  # type: ignore[arg-type]


def test_assign_rejects_more_clusters_than_locations(toy_eventset: EventSet) -> None:
    with pytest.raises(InputMismatchError, match="exceeds"):
        ThesisWardClustering(0.9).assign(toy_eventset, 3)


def test_assign_rejects_an_empty_eventset(toy_eventset: EventSet) -> None:
    with pytest.raises(InputMismatchError, match="0 rows"):
        ThesisWardClustering(0.9).assign(toy_eventset.filter_threshold(1e6), 1)


def test_ties_that_merge_clusters_raise(toy_eventset: EventSet) -> None:
    # Two pairs of identical locations: at most two distinct clusters exist.
    index = np.array(toy_eventset.index)
    loss = np.array(toy_eventset.loss)
    es = make_eventset(
        toy_eventset,
        np.column_stack([index[:, 0], index[:, 0], index[:, 1], index[:, 1]]),
        np.column_stack([loss[:, 0], loss[:, 0], loss[:, 1], loss[:, 1]]),
        [100.0, 100.0, 50.0, 50.0],
    )
    strategy = ThesisWardClustering(beta_tail=0.5)
    assert sorted(set(strategy.assign(es, 2).values())) == [1, 2]
    with pytest.raises(InputMismatchError, match="ties"):
        strategy.assign(es, 3)
