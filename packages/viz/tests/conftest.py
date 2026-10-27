"""Fixtures of the viz tests (MAR-110): a small result store built by the runner.

The fixture store is computed at test time from a small synthetic EventSet
(three locations, 60 events) with the core runner, so it is never committed
and always matches the installed core. The tests only *read* it; that the viz
code never solves is checked in ``test_imports.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import numpy as np
import pandas as pd
import pytest
import yaml

from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.runner import (
    load_input,
    prepare_eventset,
    run_config,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore

N_EVENTS = 60
N_YEARS = 60


def make_eventset() -> EventSet:
    """60 events at three locations; loss grows with the index, plus noise."""
    rng = np.random.default_rng(20261027)
    base = rng.uniform(5.0, 75.0, size=N_EVENTS)
    index = np.clip(base[:, None] + rng.normal(0.0, 4.0, (N_EVENTS, 3)), 0.0, None)
    values = np.array([100.0, 60.0, 30.0])
    damage = np.clip((index - 20.0) / 50.0, 0.0, 1.0) ** 2
    loss = damage * values * rng.uniform(0.7, 1.3, (N_EVENTS, 3))
    events = pd.DataFrame(
        {
            "event_id": [f"ev{i}" for i in range(N_EVENTS)],
            "year": np.arange(N_EVENTS) % N_YEARS,
            "rate": np.full(N_EVENTS, 1 / N_YEARS),
            "draw_id": np.zeros(N_EVENTS, dtype=int),
            "scenario_id": ["toy"] * N_EVENTS,
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": ["A1", "A2", "A3"],
            "lat": [25.0, 25.5, 26.0],
            "lon": [-80.0, -80.5, -81.0],
            "value": values,
            "name": ["Asset 1", "Asset 2", "Asset 3"],
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name="toy", release="1"),
        index=IndexDefinition(definition="wind at the asset", unit="m/s"),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=N_YEARS,
        scenario="toy",
        provenance=Provenance(
            producer="viz tests",
            producer_version="0",
            created_at=datetime(2026, 10, 27, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events, locations=locations, index=index, loss=loss, metadata=metadata
    )


def config_dict(**changes: Any) -> dict[str, Any]:  # noqa: ANN401
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "viz-toy",
        "eventset": {"path": "eventset"},
        "threshold": {"value": 20.0, "column": "index"},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 70.0, "n_bins": 5},
        "scopes": [
            {"kind": "individual"},
            {
                "kind": "cluster",
                "n_clusters": 2,
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
            },
            {"kind": "portfolio"},
        ],
        "objectives": [
            {"kind": "mse"},
            {"kind": "expected_uncovered"},
            {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.9},
        ],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.9},
        "output": {"directory": "results"},
    }
    data.update(changes)
    return data


@dataclass(frozen=True)
class Fixture:
    """A config, its result store and what the figures command would pass."""

    path: Path
    config: ExperimentConfig
    store: ResultStore
    run_ids: tuple[str, ...]
    eventset: EventSet  # prepared

    def run_id(self, scope: str, objective: str) -> str:
        for single, run_id in zip(self.config.single_runs(), self.run_ids, strict=True):
            if (single.scopes[0].kind, single.objectives[0].kind) == (scope, objective):
                return run_id
        raise KeyError((scope, objective))


def build_fixture(directory: Path, **changes: Any) -> Fixture:  # noqa: ANN401
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / "eventset").exists():
        make_eventset().to_parquet(directory / "eventset")
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(config_dict(**changes)), encoding="utf-8")
    config = load_config(path)
    run_config(config)
    data = load_input(config)
    run_ids = tuple(
        run_key(config_hash(s), data.checksum) for s in config.single_runs()
    )
    return Fixture(
        path=path,
        config=config,
        store=ResultStore(config.output.directory),
        run_ids=run_ids,
        eventset=prepare_eventset(config, data.eventset),
    )


@pytest.fixture(scope="session")
def toy(tmp_path_factory: pytest.TempPathFactory) -> Fixture:
    """Every scope x objective solved: the complete fixture store."""
    return build_fixture(tmp_path_factory.mktemp("toy"))


@pytest.fixture(scope="session")
def failed(tmp_path_factory: pytest.TempPathFactory) -> Fixture:
    """A cluster scope with more clusters than locations: a failed build."""
    return build_fixture(
        tmp_path_factory.mktemp("failed"),
        scopes=[
            {"kind": "portfolio"},
            {
                "kind": "cluster",
                "n_clusters": 4,
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
            },
        ],
        objectives=[{"kind": "mse"}],
    )
