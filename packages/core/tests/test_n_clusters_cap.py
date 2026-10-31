"""Tests of the cluster-count cap of ``n_assets`` subsets (MAR-131).

The cluster scope's ``cap_n_clusters`` (default False, the thesis behaviour)
gives an ``n_assets`` subset with fewer locations than ``n_clusters`` the
effective count ``min(n_clusters, len(subset))``. The sweep writes it into
the point's config and records both counts in the sweep manifest; the parity
config does not set the flag and keeps failing at those points.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import yaml

from parametric_insurance_design.cli import ExitCode, main
from parametric_insurance_design.errors import ConfigError, InputMismatchError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ClusterScopeConfig,
    ExperimentConfig,
    canonical_json,
    config_hash,
    dump_config,
    load_config,
    parse_config,
    to_dict,
)
from parametric_insurance_design.experiment.runner import load_input
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.experiment.sweeps import (
    read_sweep_manifests,
    run_sweep,
    sweep_points,
)
from parametric_insurance_design.records import ALL_PROBLEMS

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"

THESIS_SINGLE_RUN_HASHES = (
    "sha256:e2921efb64394b7f36f9deb18c2167ad6dac45ccf4c823340c940051ccc6a807",
    "sha256:7794a200e904deaa0dfc5653bd0ff6f1f176abb58460817227b503020ffb5dd9",
    "sha256:73e24b54ec1dc0f1af243e47d9767fea5469587348efd4b764009e036ec00b97",
    "sha256:2100f064618d6270d623e224bb6e66d063bc600f0f6d879412e448d9a21504a4",
    "sha256:601a28c31e1cba5fd9eb97fc82000f3288fab814d84bfb0c454d51ee779464a7",
    "sha256:0a0969343e560d672e8b7b461b086029037ff2f268c67231b1375e34b9fad264",
    "sha256:3d3e150f1b3722cf7a60659d7cb081cc2698551a22a1241dc4e9db37a557b04b",
    "sha256:2ba236ff3708c72d5a68737d73d4860922839880fd68745bab7744cff820049d",
    "sha256:1a84fd742e94b86d3b30e98cf3cf8e2c8e12a770693bf1f694ef81a4718cf24d",
)
"""``config_hash`` of the 9 thesis single runs.

MAR-131 left them unchanged. MAR-117 changed them on purpose: the parity
config now sets the thesis return-period grid (``evaluation.return_periods``);
``test_return_periods.py`` pins the hashes before MAR-117 and shows that the
grid is the only difference."""

CLUSTER: dict[str, Any] = {
    "kind": "cluster",
    "n_clusters": 3,
    "strategy": {"kind": "thesis_ward", "beta_tail": 0.5},
}


def three_location_eventset(base: EventSet) -> EventSet:
    """Six events in six years at three locations with distinct tails."""
    index = np.array(
        [
            [10.0, 15.0, 12.0],
            [25.0, 40.0, 22.0],
            [30.0, 50.0, 28.0],
            [45.0, 35.0, 55.0],
            [55.0, 58.0, 30.0],
            [60.0, 25.0, 65.0],
        ]
    )
    loss = np.array(
        [
            [0.0, 1.0, 0.0],
            [2.0, 6.0, 1.0],
            [3.0, 9.0, 2.0],
            [7.0, 4.0, 12.0],
            [10.0, 12.0, 3.0],
            [14.0, 2.0, 18.0],
        ]
    )
    n_rows = index.shape[0]
    events = pd.DataFrame(
        {
            "event_id": [f"ev{i}" for i in range(n_rows)],
            "year": np.arange(n_rows, dtype=np.int64),
            "rate": np.full(n_rows, 1.0 / n_rows),
            "draw_id": np.zeros(n_rows, dtype=np.int64),
            "scenario_id": ["toy"] * n_rows,
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": ["A", "B", "C"],
            "lat": [25.0, 26.0, 27.0],
            "lon": [-80.0, -81.0, -82.0],
            "value": [100.0, 50.0, 80.0],
            "name": ["Asset A", "Asset B", "Asset C"],
        }
    )
    return EventSet(
        events=events,
        locations=locations,
        index=index,
        loss=loss,
        metadata=replace(base.metadata, n_years=n_rows),
    )


@pytest.fixture
def eventset_dir(tmp_path: Path, toy_eventset: EventSet) -> Path:
    path = tmp_path / "eventset"
    three_location_eventset(toy_eventset).to_parquet(path)
    return path


def experiment(
    eventset_path: Path, output: Path, *, cap: bool | None, sizes: list[int]
) -> ExperimentConfig:
    cluster = dict(CLUSTER)
    if cap is not None:
        cluster["cap_n_clusters"] = cap
    return parse_config(
        {
            "schema_version": 1,
            "name": "cap",
            "eventset": {"path": str(eventset_path)},
            "basis": "event_conditional",
            "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
            "scopes": [{"kind": "portfolio"}, cluster],
            "objectives": [{"kind": "mse"}],
            "constraints": [{"kind": "budget", "loading": 1.0}],
            "evaluation": {"beta": 0.5},
            "sweeps": [{"parameter": "n_assets", "values": sizes}],
            "output": {"directory": str(output)},
        }
    )


# -- the config field -----------------------------------------------------------


def test_cap_defaults_to_the_thesis_behaviour_and_is_left_out_of_dumps(
    tmp_path: Path,
) -> None:
    unset = experiment(tmp_path, tmp_path, cap=None, sizes=[1])
    explicit = experiment(tmp_path, tmp_path, cap=False, sizes=[1])
    cluster = unset.scopes[1]
    assert isinstance(cluster, ClusterScopeConfig)
    assert cluster.cap_n_clusters is False
    assert "cap_n_clusters" not in to_dict(unset)["scopes"][1]
    assert "cap_n_clusters" not in canonical_json(unset)
    assert "cap_n_clusters" not in dump_config(unset)
    assert canonical_json(explicit) == canonical_json(unset)
    assert config_hash(explicit) == config_hash(unset)


def test_cap_true_is_dumped_hashed_and_read_back(tmp_path: Path) -> None:
    capped = experiment(tmp_path, tmp_path, cap=True, sizes=[1])
    plain = experiment(tmp_path, tmp_path, cap=None, sizes=[1])
    assert to_dict(capped)["scopes"][1]["cap_n_clusters"] is True
    assert '"cap_n_clusters":true' in canonical_json(capped)
    assert config_hash(capped) != config_hash(plain)
    again = parse_config(yaml.safe_load(dump_config(capped)))
    assert again == capped
    assert config_hash(again) == config_hash(capped)
    # Derived configs keep the flag.
    (single, *_) = [s for s in capped.single_runs() if s.scopes[0].kind == "cluster"]
    assert single.scopes[0] == capped.scopes[1]


@pytest.mark.parametrize("value", ["yes", 1, None])
def test_cap_must_be_a_bool(tmp_path: Path, value: object) -> None:
    with pytest.raises(ConfigError, match="cap_n_clusters"):
        parse_config(
            {
                **to_dict(experiment(tmp_path, tmp_path, cap=None, sizes=[1])),
                "scopes": [{**CLUSTER, "cap_n_clusters": value}],
            }
        )


@pytest.mark.parametrize(
    ("cap", "n_locations", "expected"),
    [(True, 1, 1), (True, 2, 2), (True, 3, 3), (True, 9, 3), (False, 1, 3)],
)
def test_effective_n_clusters(cap: bool, n_locations: int, expected: int) -> None:
    scope = ClusterScopeConfig.model_validate({**CLUSTER, "cap_n_clusters": cap})
    assert scope.effective_n_clusters(n_locations) == expected
    assert scope.effective_n_clusters(np.int64(n_locations)) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize("n_locations", [0, -1, True, 2.0, "2"])
def test_effective_n_clusters_refuses_bad_counts(n_locations: object) -> None:
    scope = ClusterScopeConfig.model_validate({**CLUSTER, "cap_n_clusters": True})
    with pytest.raises(ConfigError, match="n_locations"):
        scope.effective_n_clusters(n_locations)  # type: ignore[arg-type]


# -- the parity config ------------------------------------------------------------


def test_parity_config_is_unchanged() -> None:
    text = PARITY_CONFIG.read_text(encoding="utf-8")
    assert "cap_n_clusters" not in text
    config = load_config(PARITY_CONFIG)
    (cluster,) = [s for s in config.scopes if isinstance(s, ClusterScopeConfig)]
    assert cluster.cap_n_clusters is False
    assert tuple(config_hash(s) for s in config.single_runs()) == (
        THESIS_SINGLE_RUN_HASHES
    )
    # Its n_assets sweep keeps n_clusters = 3 on the 1- and 2-asset subsets,
    # so those points still fail to build, as in the thesis.
    points = sweep_points(config, "n_assets")
    small = [p for p in points if p.scope == "cluster" and p.value < 3]
    # (9 one-asset + 25 two-asset subsets) x 3 objectives: the 102 failures.
    assert len(small) == 102
    assert {p.config.scopes[0].n_clusters for p in small} == {3}  # type: ignore[union-attr]
    assert all(p.n_clusters_requested is None for p in points)
    assert all(not p.n_clusters_capped for p in points)


# -- sweep points ---------------------------------------------------------------


@pytest.mark.parametrize("cap", [True, False])
def test_points_of_1_2_and_3_asset_subsets(
    eventset_dir: Path, tmp_path: Path, cap: bool
) -> None:
    config = experiment(eventset_dir, tmp_path, cap=cap, sizes=[1, 2, 3])
    points = sweep_points(config, "n_assets", location_ids=["A", "B", "C"])
    cluster = [p for p in points if p.scope == "cluster"]
    assert [p.value for p in cluster] == [1, 1, 1, 2, 2, 2, 3]
    counts = [p.config.scopes[0].n_clusters for p in cluster]  # type: ignore[union-attr]
    if cap:
        assert counts == [1, 1, 1, 2, 2, 2, 3]
        assert [p.n_clusters_requested for p in cluster] == [3] * 7
        assert [p.n_clusters_effective for p in cluster] == counts
        assert [p.n_clusters_capped for p in cluster] == [True] * 6 + [False]
        # The 3-asset subset is the whole portfolio: the baseline run.
        (baseline,) = [s for s in config.single_runs() if s.scopes[0].kind == "cluster"]
        assert config_hash(cluster[-1].config) == config_hash(
            baseline.with_locations(["A", "B", "C"])
        )
    else:
        assert counts == [3] * 7
        assert all(p.n_clusters_requested is None for p in cluster)
    portfolio = [p for p in points if p.scope == "portfolio"]
    assert all(p.n_clusters_requested is None for p in portfolio)


# -- running ----------------------------------------------------------------------


def test_capped_sweep_runs_and_records_the_effective_count(
    eventset_dir: Path, tmp_path: Path
) -> None:
    config = experiment(eventset_dir, tmp_path / "out", cap=True, sizes=[1, 2, 3])
    store = ResultStore(tmp_path / "out")
    result = run_sweep(config, "n_assets", load_input(config), store)
    assert result.ok, [p.outcome.failed for p in result.failed]

    (manifest,) = read_sweep_manifests(store)
    entries = [e for e in manifest["points"] if e["scope"] == "cluster"]
    assert [len(e["location_ids"]) for e in entries] == [1, 1, 1, 2, 2, 2, 3]
    assert [e["n_clusters_requested"] for e in entries] == [3] * 7
    assert [e["n_clusters_effective"] for e in entries] == [1, 1, 1, 2, 2, 2, 3]
    assert all(
        "n_clusters_requested" not in e
        for e in manifest["points"]
        if e["scope"] == "portfolio"
    )

    entities = store.read("entities")
    for entry in entries:
        run = store.manifest(entry["run_id"])
        scope = run["config"]["scopes"][0]
        assert scope["cap_n_clusters"] is True
        assert scope["n_clusters"] == entry["n_clusters_effective"]
        assert run["parameters"]["n_clusters"] == entry["n_clusters_effective"]
        assert run["parameters"]["n_assets"] == len(entry["location_ids"])
        mine = entities.loc[entities["run_id"] == entry["run_id"], "entity_id"]
        assert len(set(mine)) == entry["n_clusters_effective"]
    runs = store.read("runs")
    cluster_runs = runs[runs["scope"] == "cluster"]
    assert sorted(json.loads(p)["n_clusters"] for p in cluster_runs["parameters"]) == [
        1,
        1,
        1,
        2,
        2,
        2,
        3,
    ]


def test_uncapped_sweep_fails_on_small_subsets_as_the_thesis(
    eventset_dir: Path, tmp_path: Path
) -> None:
    config = experiment(eventset_dir, tmp_path / "out", cap=None, sizes=[1, 2, 3])
    store = ResultStore(tmp_path / "out")
    result = run_sweep(config, "n_assets", load_input(config), store)
    failed = [(p.point.scope, p.point.value) for p in result.failed]
    assert failed == [("cluster", 1)] * 3 + [("cluster", 2)] * 3
    runs = store.read("runs")
    errors = runs[runs["problem_id"] == ALL_PROBLEMS]
    assert set(errors["error_type"]) == {InputMismatchError.__name__}
    (manifest,) = read_sweep_manifests(store)
    assert not any("n_clusters_requested" in e for e in manifest["points"])


# -- the command ------------------------------------------------------------------


def test_cli_n_assets_sweep_exits_0_with_the_cap(
    eventset_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    results: dict[bool, ExitCode] = {}
    for cap in (False, True):
        config = experiment(
            eventset_dir, tmp_path / f"out-{cap}", cap=cap, sizes=[1, 2]
        )
        path = tmp_path / f"cap-{cap}.yaml"
        path.write_text(dump_config(config), encoding="utf-8")
        results[cap] = ExitCode(main(["sweep", str(path), "-p", "n_assets", "-q"]))
    capsys.readouterr()
    assert results == {False: ExitCode.RUNS_FAILED, True: ExitCode.OK}
