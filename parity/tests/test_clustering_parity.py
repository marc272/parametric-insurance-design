"""Parity of the cluster scope with the thesis clustering (MAR-12).

Acceptance: on the fixture, cluster assignments match the thesis for
``n_clusters = 1 .. 9``.

The thesis clustered on its prepared data: the event-loss table with the
heteroscedastic noise layer (13 draws, seed 42) and the 20 m/s threshold
filter. :func:`thesis_pipeline_eventset` builds the same data as an EventSet
from the MAR-9 fixture with the core's noise layer (``noise.add_noise``,
MAR-10), which reproduces the thesis noise draw for draw. The
``no_noise`` dataset leaves the noise out and checks the clustering alone.

Two groups:

- Against committed files only (CI-runnable): the core's assignments equal
  ``parity/golden/thesis_cluster_assignments.json`` (derived from the thesis
  code by ``parity/scripts/derive_thesis_clusters.py``) and the
  ``Included_Assets`` of every cluster row in the thesis results table
  ``parity/golden/full_optimization_results.csv.gz``.
- Against the thesis code: run when ``PARITY_THESIS_REPO`` points at a
  checkout of ``parametric-insurance-framework``, skipped otherwise.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.clustering import FEATURE_NAMES, ThesisWardClustering
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.scopes import Cluster

PARITY_DIR = Path(__file__).resolve().parents[1]
EVENTSET_DIR = PARITY_DIR / "tests" / "data" / "thesis_eventset"
GOLDEN_JSON = PARITY_DIR / "golden" / "thesis_cluster_assignments.json"
THESIS_RESULTS = PARITY_DIR / "golden" / "full_optimization_results.csv.gz"
SCRIPT = PARITY_DIR / "scripts" / "derive_thesis_clusters.py"
N_CLUSTERS = range(1, 10)
THESIS_ASSETS = [f"A{k}" for k in range(1, 10)]
FEATURE_RTOL = 1e-12


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    return json.loads(GOLDEN_JSON.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def fixture_eventset() -> EventSet:
    return EventSet.from_parquet(EVENTSET_DIR)


def thesis_pipeline_eventset(
    eventset: EventSet, settings: dict[str, Any], *, noise: bool = True
) -> EventSet:
    """The thesis data preparation, on an EventSet.

    The core's port of the thesis noise layer (``noise.add_noise``, MAR-10:
    ``n_draws`` event-major copies, rates divided by ``n_draws``, losses
    times the heteroscedastic lognormal factor drawn asset by asset from
    ``default_rng(random_seed)``), then the threshold filter keeping the rows
    where some asset's wind reaches ``threshold``. With ``noise=False`` only
    the filter is applied.
    """
    if noise:
        assert settings["noise_type"] == "heteroscedastic"
        eventset = add_noise(
            eventset,
            level=settings["noise_value"],
            kind="heteroscedastic",
            n_copies=int(settings["n_draws"]),
            rng=np.random.default_rng(seed=settings["random_seed"]),
            location_ids=THESIS_ASSETS,  # the thesis draws asset by asset
        )
    return eventset.filter_threshold(settings["threshold"])


@pytest.fixture(scope="module")
def datasets(fixture_eventset: EventSet, golden: dict[str, Any]) -> dict[str, EventSet]:
    settings = golden["settings"]
    return {
        "thesis_pipeline": thesis_pipeline_eventset(fixture_eventset, settings),
        "no_noise": thesis_pipeline_eventset(fixture_eventset, settings, noise=False),
    }


@pytest.fixture(scope="module")
def strategy(golden: dict[str, Any]) -> ThesisWardClustering:
    settings = golden["settings"]
    return ThesisWardClustering(
        beta_tail=settings["beta_tail"], linkage=settings["linkage"]
    )


def thesis_results_assignments() -> dict[int, dict[str, set[int]]]:
    """Cluster labels per asset in the thesis results table, by n_clusters."""
    df = pd.read_csv(THESIS_RESULTS)
    df = df[df["Approach"] == "cluster_optimization"]
    out: dict[int, dict[str, set[int]]] = {}
    for _, row in df.iterrows():
        k = int(cast(Any, row["N_Clusters"]))
        label = int(str(row["Asset_ID"]).removeprefix("C"))
        for asset in ast.literal_eval(cast(str, row["Included_Assets"])):
            out.setdefault(k, {}).setdefault(asset, set()).add(label)
    return out


# --------------------------------------------------------------------------
# Committed files only
# --------------------------------------------------------------------------


def test_golden_file_is_complete(golden: dict[str, Any]) -> None:
    assert set(golden["datasets"]) == {"thesis_pipeline", "no_noise"}
    for data in golden["datasets"].values():
        assert set(data["assignments"]) == {str(k) for k in N_CLUSTERS}
        for k, labels in data["assignments"].items():
            assert list(labels) == THESIS_ASSETS
            assert set(labels.values()) == set(range(1, int(k) + 1))
        assert list(data["features"]) == THESIS_ASSETS


def test_golden_matches_thesis_results_table(golden: dict[str, Any]) -> None:
    # The derived golden file agrees with the clusters the thesis optimised.
    thesis = thesis_results_assignments()
    assert set(thesis) == set(N_CLUSTERS)
    for k in N_CLUSTERS:
        expected = golden["datasets"]["thesis_pipeline"]["assignments"][str(k)]
        assert thesis[k] == {a: {c} for a, c in expected.items()}, k


@pytest.mark.parametrize("dataset", ["thesis_pipeline", "no_noise"])
def test_row_counts_match_thesis(
    datasets: dict[str, EventSet], golden: dict[str, Any], dataset: str
) -> None:
    assert datasets[dataset].n_rows == golden["datasets"][dataset]["n_rows"]


@pytest.mark.parametrize("dataset", ["thesis_pipeline", "no_noise"])
def test_features_match_thesis(
    datasets: dict[str, EventSet],
    golden: dict[str, Any],
    strategy: ThesisWardClustering,
    dataset: str,
) -> None:
    ours = strategy.features(datasets[dataset])
    expected = pd.DataFrame(golden["datasets"][dataset]["features"]).T
    assert list(ours.columns) == list(FEATURE_NAMES)
    np.testing.assert_allclose(
        ours.loc[THESIS_ASSETS].to_numpy(),
        expected.loc[THESIS_ASSETS, list(FEATURE_NAMES)].to_numpy(dtype=float),
        rtol=FEATURE_RTOL,
        atol=0.0,
    )


@pytest.mark.parametrize("dataset", ["thesis_pipeline", "no_noise"])
@pytest.mark.parametrize("n_clusters", N_CLUSTERS)
def test_assignments_match_thesis(
    datasets: dict[str, EventSet],
    golden: dict[str, Any],
    strategy: ThesisWardClustering,
    dataset: str,
    n_clusters: int,
) -> None:
    ours = dict(strategy.assign(datasets[dataset], n_clusters))
    assert ours == golden["datasets"][dataset]["assignments"][str(n_clusters)]


@pytest.mark.parametrize("n_clusters", N_CLUSTERS)
def test_cluster_scope_entities_match_thesis_results(
    datasets: dict[str, EventSet], strategy: ThesisWardClustering, n_clusters: int
) -> None:
    # The scope's entities C<label> hold the thesis' Included_Assets, in order.
    (spec,) = Cluster(strategy=strategy, n_clusters=n_clusters).partition(
        datasets["thesis_pipeline"]
    )
    df = pd.read_csv(THESIS_RESULTS)
    df = df[
        (df["Approach"] == "cluster_optimization")
        & (df["Source"] == "n_clusters_sweep")
        & (df["N_Clusters"] == n_clusters)
    ]
    for method, rows in df.groupby("Method"):
        expected = {
            row["Asset_ID"]: tuple(ast.literal_eval(cast(str, row["Included_Assets"])))
            for _, row in rows.iterrows()
        }
        got = {e.entity_id: e.location_ids for e in spec.entities}
        assert got == expected, method


def test_cluster_index_is_value_weighted_mean_wind(
    datasets: dict[str, EventSet], strategy: ThesisWardClustering
) -> None:
    # Thesis _prepare_cluster_problem_data: Wc @ (vals / vals.sum()).
    data = datasets["thesis_pipeline"]
    scope = Cluster(strategy=strategy, n_clusters=3)
    problem = scope.materialise(data, scope.partition(data)[0])
    values = data.locations.set_index("location_id")["value"]
    cols = {loc: i for i, loc in enumerate(data.location_ids)}
    for j, entity in enumerate(problem.spec.entities):
        vals = values.loc[list(entity.location_ids)].to_numpy(dtype=float)
        wc = np.column_stack([data.index[:, cols[a]] for a in entity.location_ids])
        lc = np.column_stack([data.loss[:, cols[a]] for a in entity.location_ids])
        np.testing.assert_array_equal(problem.index[:, j], wc @ (vals / vals.sum()))
        np.testing.assert_array_equal(problem.entity_loss[:, j], lc.sum(axis=1))


# --------------------------------------------------------------------------
# Against the thesis code
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def thesis_repo() -> Path:
    value = os.environ.get("PARITY_THESIS_REPO")
    if not value:
        pytest.skip(
            "PARITY_THESIS_REPO is not set: set it to a checkout of "
            "parametric-insurance-framework to run the clustering against the "
            "thesis code"
        )
    return Path(value)


@pytest.fixture(scope="module")
def derive_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("derive_thesis_clusters", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def thesis(derive_script: ModuleType, thesis_repo: Path) -> Any:  # noqa: ANN401
    return derive_script.load_thesis(thesis_repo)


@pytest.fixture(scope="module")
def thesis_frames(
    derive_script: ModuleType,
    thesis: Any,  # noqa: ANN401
) -> dict[str, pd.DataFrame]:
    return {
        name: derive_script.thesis_frame(thesis, name)
        for name in derive_script.DATASETS
    }


def test_thesis_settings_match_golden(
    thesis: Any,  # noqa: ANN401
    golden: dict[str, Any],
) -> None:
    assert thesis.settings == golden["settings"]
    assert thesis.assets == THESIS_ASSETS


@pytest.mark.parametrize("dataset", ["thesis_pipeline", "no_noise"])
def test_eventset_reproduces_thesis_frame(
    datasets: dict[str, EventSet],
    thesis_frames: dict[str, pd.DataFrame],
    dataset: str,
) -> None:
    # The EventSet rebuild of the thesis data preparation is bit-identical.
    frame = thesis_frames[dataset]
    data = datasets[dataset]
    assert data.n_rows == len(frame)
    np.testing.assert_array_equal(data.events["event_id"], frame["Event_ID"])
    np.testing.assert_array_equal(data.rates, frame["probability"])
    for i, asset in enumerate(data.location_ids):
        np.testing.assert_array_equal(data.loss[:, i], frame[f"{asset}_Loss"])
        np.testing.assert_array_equal(data.index[:, i], frame[f"{asset}_Wind"])


@pytest.mark.parametrize("dataset", ["thesis_pipeline", "no_noise"])
def test_against_thesis_code(
    derive_script: ModuleType,
    thesis: Any,  # noqa: ANN401
    thesis_frames: dict[str, pd.DataFrame],
    datasets: dict[str, EventSet],
    golden: dict[str, Any],
    strategy: ThesisWardClustering,
    dataset: str,
) -> None:
    frame = thesis_frames[dataset]
    expected_features = derive_script.thesis_features(thesis, frame)
    ours = strategy.features(datasets[dataset])
    np.testing.assert_array_equal(
        ours.loc[THESIS_ASSETS].to_numpy(),
        expected_features.loc[THESIS_ASSETS, list(FEATURE_NAMES)].to_numpy(),
    )
    expected = derive_script.thesis_assignments(thesis, frame)
    for k in N_CLUSTERS:
        assert dict(strategy.assign(datasets[dataset], k)) == expected[k], k
        assert expected[k] == golden["datasets"][dataset]["assignments"][str(k)], k
