"""``runs.parameters`` records ``cluster_joint`` only when it is False (MAR-225).

``runner.run_parameters`` adds ``cluster_joint: false`` for a cluster scope
with ``joint: false`` (MAR-180), so that readers of the ``runs`` table (the
viz scope keys and labels) can tell a cluster run calibrated cluster by
cluster from the joint cluster scope: ``runs.scope`` is ``"cluster"`` for
both. Joint cluster runs, and runs of every other scope, keep their stored
parameters, and no run id changes: the parameters are not part of
``run_key``. The last test pins both for every experiment config in the
repository, with the digests MAR-178 computed before either change.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import (
    load_input,
    run_config,
    run_key,
    run_parameters,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.experiment.sweeps import sweep_points
from parametric_insurance_design.solve import DEFAULT_POLICY

from .test_run_parameters_below_attachment import EXISTING_RUNS, canonical

REPO_ROOT = Path(__file__).resolve().parents[3]

KEY = "cluster_joint"


def cluster_scope(joint: bool | None) -> dict[str, Any]:
    scope: dict[str, Any] = {
        "kind": "cluster",
        "n_clusters": 2,
        "strategy": {"kind": "thesis_ward", "beta_tail": 0.5},
    }
    if joint is not None:
        scope["joint"] = joint
    return scope


def toy_config(directory: Path, output: Path, joint: bool | None) -> ExperimentConfig:
    return parse_config(
        {
            "schema_version": 1,
            "name": "toy",
            "eventset": {"path": str(directory)},
            "basis": "event_conditional",
            "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
            "scopes": [
                {"kind": "individual"},
                cluster_scope(joint),
                {"kind": "portfolio"},
            ],
            "objectives": [{"kind": "mse"}, {"kind": "expected_uncovered"}],
            "constraints": [{"kind": "budget", "loading": 1.0}],
            "evaluation": {"beta": 0.5},
            "output": {"directory": str(output)},
        }
    )


@pytest.fixture
def toy_dir(tmp_path: Path, toy_eventset: EventSet) -> Path:
    path = tmp_path / "eventset"
    toy_eventset.to_parquet(path)
    return path


@pytest.mark.parametrize("joint", [None, True])
def test_joint_cluster_runs_add_no_key(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet, joint: bool | None
) -> None:
    config = toy_config(toy_dir, tmp_path, joint)
    for single in config.single_runs():
        assert KEY not in run_parameters(single, toy_eventset)


def test_separate_cluster_runs_add_the_key_and_nothing_else(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    joint = toy_config(toy_dir, tmp_path, None).single_runs()
    separate = toy_config(toy_dir, tmp_path, False).single_runs()
    assert len(joint) == len(separate) == 6
    for plain, single in zip(joint, separate, strict=True):
        expected = run_parameters(plain, toy_eventset)
        if single.scopes[0].kind == "cluster":
            expected |= {KEY: False}
        assert run_parameters(single, toy_eventset) == expected
    kinds = [s.scopes[0].kind for s in separate]
    assert kinds.count("cluster") == 2


def stored_parameters(store: ResultStore, run_id: str) -> tuple[dict[str, Any], ...]:
    runs = store.read("runs")
    rows = runs.loc[runs["run_id"] == run_id, "parameters"]
    assert len(rows) >= 1
    return tuple(json.loads(value) for value in rows)


def test_runs_rows_and_manifest_record_the_setting(
    toy_dir: Path, tmp_path: Path
) -> None:
    for joint in (None, True, False):
        output = tmp_path / f"results-{joint}"
        config = toy_config(toy_dir, output, joint)
        data = load_input(config)
        outcomes = run_config(config, data=data)
        assert all(o.ok for o in outcomes)
        store = ResultStore(output)
        for single, outcome in zip(config.single_runs(), outcomes, strict=True):
            # The run id is still the cache key of the config hash and input.
            assert outcome.run_id == run_key(config_hash(single), data.checksum)
            manifest = store.manifest(outcome.run_id)["parameters"]
            separate = joint is False and single.scopes[0].kind == "cluster"
            for params in (*stored_parameters(store, outcome.run_id), manifest):
                if separate:
                    assert params[KEY] is False
                else:
                    assert KEY not in params


def test_joint_runs_store_the_same_parameters_and_ids_as_before(
    toy_dir: Path, tmp_path: Path
) -> None:
    implicit = toy_config(toy_dir, tmp_path / "a", None)
    explicit = toy_config(toy_dir, tmp_path / "b", True)
    ids = [[o.run_id for o in run_config(c)] for c in (implicit, explicit)]
    assert ids[0] == ids[1]
    a = ResultStore(tmp_path / "a").read("runs")
    b = ResultStore(tmp_path / "b").read("runs")
    assert a["parameters"].tolist() == b["parameters"].tolist()


@pytest.mark.parametrize("path", sorted(EXISTING_RUNS))
def test_existing_configs_keep_their_run_ids_and_parameters(path: str) -> None:
    """MAR-178's pinned digests (computed before MAR-178 and MAR-225) still hold."""
    file = REPO_ROOT / path
    if not file.is_file():
        pytest.skip(f"{path} is only in a repository checkout")
    config = load_config(file)
    if not config.eventset.path.is_dir():
        pytest.skip(f"the EventSet of {path} is only in a repository checkout")
    checksum = config.eventset.checksum
    assert checksum is not None
    loaded = EventSet.from_parquet(config.eventset.path)
    subsets: dict[tuple[str, ...] | None, EventSet] = {}

    def located(single: ExperimentConfig) -> EventSet:
        portfolio = single.portfolio
        ids = None if portfolio is None else portfolio.location_ids
        key = None if ids is None else tuple(ids)
        if key not in subsets:
            subsets[key] = loaded if key is None else loaded.select_locations(key)
        return subsets[key]

    runs = list(config.single_runs())
    for sweep in config.sweeps:
        runs.extend(point.config for point in sweep_points(config, sweep.parameter))
    lines = []
    for single in runs:
        params = run_parameters(single, located(single))
        assert KEY not in params
        run_id = run_key(
            config_hash(single),
            checksum,
            package_version="0.0.0+pin",
            policy=DEFAULT_POLICY,
        )
        lines.append(f"{run_id} {canonical(params)}")
    n, digest = EXISTING_RUNS[path]
    assert len(lines) == n
    assert hashlib.sha256("\n".join(lines).encode()).hexdigest() == digest
