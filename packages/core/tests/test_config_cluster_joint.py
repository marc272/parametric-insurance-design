"""The cluster scope's ``joint`` field in the config and the runner (MAR-180).

``scopes[cluster].joint`` (default True, the thesis) picks one joint design
problem over all clusters; ``false`` calibrates each cluster on its own
(``scopes.Cluster(joint=False)``). True is left out of every dump and of the
config hash, so every existing config keeps its hash, its run ids and its
stored tables; ``false`` is hashed, so a separately calibrated run is a cache
entry of its own.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from parametric_insurance_design.errors import ConfigError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ClusterScopeConfig,
    canonical_json,
    config_hash,
    dump_config,
    load_config,
    parse_config,
    to_dict,
)
from parametric_insurance_design.experiment.runner import run_config
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.records import ALL_PROBLEMS
from parametric_insurance_design.scopes import PORTFOLIO_PROBLEM_ID, Cluster

from .test_config_allocation import EXISTING_HASHES

REPO_ROOT = Path(__file__).resolve().parents[3]


def cluster_scope(joint: object = None, n_clusters: int = 2) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "kind": "cluster",
        "n_clusters": n_clusters,
        "strategy": {"kind": "thesis_ward", "beta_tail": 0.5},
    }
    if joint is not None:
        scope["joint"] = joint
    return scope


def toy_dict(directory: Path, joint: object = None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "name": "toy",
        "eventset": {"path": str(directory / "eventset")},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
        "scopes": [cluster_scope(joint)],
        "objectives": [{"kind": "mse"}],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.5},
        "output": {"directory": str(directory / "results")},
    }


@pytest.fixture
def toy_dir(tmp_path: Path, toy_eventset: EventSet) -> Path:
    toy_eventset.to_parquet(tmp_path / "eventset")
    return tmp_path


# -- schema -----------------------------------------------------------------------


def test_joint_defaults_to_true_and_is_left_out_of_every_dump(tmp_path: Path) -> None:
    unset = parse_config(toy_dict(tmp_path))
    explicit = parse_config(toy_dict(tmp_path, True))
    assert unset == explicit
    for config in (unset, explicit):
        (scope,) = config.scopes
        assert isinstance(scope, ClusterScopeConfig)
        assert scope.joint is True
        assert "joint" not in to_dict(config)["scopes"][0]
        assert '"joint"' not in canonical_json(config)
        assert "joint:" not in dump_config(config)
        built = config.to_components().scopes[0]
        assert isinstance(built, Cluster)
        assert built.joint is True
    assert config_hash(explicit) == config_hash(unset)
    assert dump_config(explicit) == dump_config(unset)


def test_joint_false_is_dumped_hashed_and_built(tmp_path: Path) -> None:
    joint = parse_config(toy_dict(tmp_path))
    separate = parse_config(toy_dict(tmp_path, False))
    assert to_dict(separate)["scopes"][0]["joint"] is False
    assert '"joint":false' in canonical_json(separate)
    assert config_hash(separate) != config_hash(joint)
    built = separate.to_components().scopes[0]
    assert isinstance(built, Cluster)
    assert built.joint is False
    # Round trip through YAML.
    file = tmp_path / "separate.yaml"
    file.write_text(dump_config(separate), encoding="utf-8")
    again = load_config(file)
    assert again == separate
    assert config_hash(again) == config_hash(separate)


@pytest.mark.parametrize("value", ["false", 0, 1, "no"])
def test_joint_must_be_a_bool(tmp_path: Path, value: object) -> None:
    with pytest.raises(ConfigError, match="joint"):
        parse_config(toy_dict(tmp_path, value))


def test_single_runs_and_sweeps_keep_joint_false(tmp_path: Path) -> None:
    data = toy_dict(tmp_path, False)
    data["scopes"] = [{"kind": "individual"}, cluster_scope(False, n_clusters=1)]
    data["objectives"] = [{"kind": "mse"}, {"kind": "expected_uncovered"}]
    config = parse_config(data)
    for single in config.single_runs():
        (scope,) = single.scopes
        if isinstance(scope, ClusterScopeConfig):
            assert scope.joint is False
    point = config.with_parameter("n_clusters", 2)
    cluster = point.scopes[1]
    assert isinstance(cluster, ClusterScopeConfig)
    assert (cluster.n_clusters, cluster.joint) == (2, False)


@pytest.mark.parametrize("path", sorted(EXISTING_HASHES))
def test_existing_configs_keep_their_hashes(path: str) -> None:
    """Every experiment config in the repository: no cluster scope sets
    ``joint``, so its config hash and its single runs' hashes are those
    pinned before MAR-217 and MAR-180."""
    file = REPO_ROOT / path
    if not file.is_file():
        pytest.skip(f"{path} is only in a repository checkout")
    config = load_config(file)
    for scope in config.scopes:
        if isinstance(scope, ClusterScopeConfig):
            assert scope.joint is True
    assert '"joint"' not in canonical_json(config)
    expected_hash, n_singles, digest = EXISTING_HASHES[path]
    assert config_hash(config) == expected_hash
    singles = [config_hash(s) for s in config.single_runs()]
    assert len(singles) == n_singles
    joined = "\n".join(singles).encode("ascii")
    assert hashlib.sha256(joined).hexdigest() == digest


# -- runner -----------------------------------------------------------------------


def test_a_separate_run_is_its_own_cache_entry(toy_dir: Path) -> None:
    joint = parse_config(toy_dict(toy_dir))
    separate = parse_config(toy_dict(toy_dir, False))
    store = ResultStore(toy_dir / "store")
    (j,) = run_config(joint, store=store)
    (s,) = run_config(separate, store=store)
    assert j.ok
    assert s.ok
    assert not s.cached
    assert s.run_id != j.run_id
    assert s.config_hash == config_hash(separate.single_runs()[0])

    runs = store.read("runs")
    problems = {
        rid: sorted(set(rows["problem_id"])) for rid, rows in runs.groupby("run_id")
    }
    assert problems[j.run_id] == [PORTFOLIO_PROBLEM_ID]
    assert problems[s.run_id] == ["cluster:C1", "cluster:C2"]
    assert set(runs.loc[runs["run_id"] == s.run_id, "scope"]) == {"cluster"}

    kpis = store.read("kpis")
    port = kpis.loc[(kpis["run_id"] == s.run_id) & (kpis["level"] == "portfolio")]
    assert len(port) > 0
    assert set(port["problem_id"]) == {ALL_PROBLEMS}
    # A second call finds the run in the cache.
    (again,) = run_config(separate, store=store)
    assert again.cached
    assert again.run_id == s.run_id
