"""``runs.parameters`` records ``below_attachment`` only under ``"zero"`` (MAR-178).

``runner.run_parameters`` adds the key ``below_attachment`` when the payout's
mode is not the default ``"first_bin"`` (MAR-170), so that readers of the
``runs`` table (the viz payout figures) can tell what a run pays below the
attachment. Runs of the default mode keep their stored parameters, and no run
id changes: the parameters are not part of ``run_key``. The last test pins
both for every experiment config in the repository.
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

REPO_ROOT = Path(__file__).resolve().parents[3]


def toy_config(
    eventset_path: Path, output: Path, below_attachment: str | None
) -> ExperimentConfig:
    payout: dict[str, Any] = {"attachment": 20.0, "limit": 60.0, "n_bins": 2}
    if below_attachment is not None:
        payout["below_attachment"] = below_attachment
    return parse_config(
        {
            "schema_version": 1,
            "name": "toy",
            "eventset": {"path": str(eventset_path)},
            "basis": "event_conditional",
            "payout": payout,
            "scopes": [{"kind": "individual"}, {"kind": "portfolio"}],
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


@pytest.mark.parametrize("mode", [None, "first_bin"])
def test_default_mode_adds_no_key(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet, mode: str | None
) -> None:
    config = toy_config(toy_dir, tmp_path, mode)
    for single in config.single_runs():
        params = run_parameters(single, toy_eventset)
        assert "below_attachment" not in params
        assert set(params) == {
            "attachment",
            "limit",
            "n_bins",
            "n_assets",
            "evaluation_beta",
            "sample",
            "budget_loading",
        }


def test_zero_mode_adds_the_key_and_nothing_else(
    toy_dir: Path, tmp_path: Path, toy_eventset: EventSet
) -> None:
    default = toy_config(toy_dir, tmp_path, None).single_runs()
    zero = toy_config(toy_dir, tmp_path, "zero").single_runs()
    assert len(default) == len(zero) == 4
    for plain, single in zip(default, zero, strict=True):
        expected = run_parameters(plain, toy_eventset) | {"below_attachment": "zero"}
        assert run_parameters(single, toy_eventset) == expected


def stored_parameters(store: ResultStore, run_id: str) -> tuple[dict[str, Any], ...]:
    runs = store.read("runs")
    rows = runs.loc[runs["run_id"] == run_id, "parameters"]
    assert len(rows) >= 1
    return tuple(json.loads(value) for value in rows)


def test_runs_rows_and_manifest_record_the_mode(toy_dir: Path, tmp_path: Path) -> None:
    for mode in (None, "first_bin", "zero"):
        output = tmp_path / f"results-{mode}"
        config = toy_config(toy_dir, output, mode)
        data = load_input(config)
        outcomes = run_config(config, data=data)
        assert all(o.ok for o in outcomes)
        store = ResultStore(output)
        for single, outcome in zip(config.single_runs(), outcomes, strict=True):
            # The run id is still the cache key of the config hash and input.
            assert outcome.run_id == run_key(config_hash(single), data.checksum)
            manifest = store.manifest(outcome.run_id)["parameters"]
            for params in (*stored_parameters(store, outcome.run_id), manifest):
                if mode == "zero":
                    assert params["below_attachment"] == "zero"
                else:
                    assert "below_attachment" not in params


def test_default_and_explicit_first_bin_runs_are_the_same_runs(
    toy_dir: Path, tmp_path: Path
) -> None:
    implicit = toy_config(toy_dir, tmp_path / "a", None)
    explicit = toy_config(toy_dir, tmp_path / "b", "first_bin")
    zero = toy_config(toy_dir, tmp_path / "c", "zero")
    ids = {
        name: [o.run_id for o in run_config(config)]
        for name, config in (("implicit", implicit), ("explicit", explicit))
    }
    assert ids["implicit"] == ids["explicit"]
    zero_ids = [o.run_id for o in run_config(zero)]
    assert not set(zero_ids) & set(ids["implicit"])
    a = ResultStore(tmp_path / "a").read("runs")
    b = ResultStore(tmp_path / "b").read("runs")
    assert a["parameters"].tolist() == b["parameters"].tolist()


EXISTING_RUNS: dict[str, tuple[int, str]] = {
    "parity/configs/thesis.yaml": (
        1860,
        "484492866ef68b215ba8cf98b4b7e9692e81f33f962f1c0803c66ab72d28cac9",
    ),
    "research/configs/c1/c1_main.yaml": (
        9,
        "c6331f069e0e0504c29d328ea3e5f750e628dcd940859a4fc67ee26ff56834dc",
    ),
    "research/data/annual-basis-rerun/thesis_annual.yaml": (
        39,
        "5495cb76fefae30db1bb6952be959601b2208b2314068d7a23b11ebd524d91dd",
    ),
    "research/data/annual-basis-rerun/thesis_event.yaml": (
        39,
        "5adfd29a105f6c4c129e47dcac9d0ca57ca9e2cb4b65619eb9a7177c3df099b7",
    ),
    "research/data/annual-basis-rerun/thesis_event_conditional.yaml": (
        39,
        "d7dd46e54fe902656ddde95539d7dad173159a971f728c79342445c4a857c57e",
    ),
}
"""Every experiment config in the repository: the number of single runs and
sweep points, and the SHA-256 of one line per run, ``"<run_id> <parameters>"``
joined by newlines (single runs first, then each sweep's points in order).
``run_id`` is ``run_key`` of the run's config hash and the config's pinned
EventSet checksum, with package version ``0.0.0+pin`` and ``DEFAULT_POLICY``;
``parameters`` is ``run_parameters`` as the ``runs`` table stores it
(canonical JSON), with ``n_assets`` from the loaded EventSet's subset of the
run's locations. Computed on ``main`` at ``103ec17``, before MAR-178."""


def canonical(value: object) -> str:
    """The canonical JSON of ``runs.parameters`` (the runner's form)."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


@pytest.mark.parametrize("path", sorted(EXISTING_RUNS))
def test_existing_configs_keep_their_run_ids_and_parameters(path: str) -> None:
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
        assert single.payout.below_attachment == "first_bin"
        params = run_parameters(single, located(single))
        assert "below_attachment" not in params
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
