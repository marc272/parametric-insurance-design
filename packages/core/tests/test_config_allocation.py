"""The evaluation's allocation rule in the config and the runner (MAR-217).

``evaluation.allocation`` (``"none"``, ``"value"``, ``"loss"``) is passed to
``evaluate.kpis`` and ``evaluate.exceedance_curves`` by the runner, so a run
under a rule stores per-location rows (``level = "location_by_value"`` or
``"location_by_loss"``; MAR-100). The default ``"none"`` is left out of every
dump and of the config hash, so every existing config keeps its hash, its run
ids and its stored tables. A rule is hashed: a run under a rule is a cache
entry of its own, never a hit on the ``"none"`` run of the same design.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest
import yaml

from parametric_insurance_design.errors import ConfigError, EntityMismatchError
from parametric_insurance_design.evaluate import Allocation
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.experiment.config import (
    ALLOCATION_RULES,
    EvaluationConfig,
    ExperimentConfig,
    canonical_json,
    config_hash,
    dump_config,
    load_config,
    parse_config,
    to_dict,
)
from parametric_insurance_design.experiment.kfold import pooled_kpis
from parametric_insurance_design.experiment.runner import (
    load_input,
    prepare_eventset,
    run_config,
    run_parameters,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.records import KpiLevel, KpiName

REPO_ROOT = Path(__file__).resolve().parents[3]

LOCATION_LEVELS = {"value": "location_by_value", "loss": "location_by_loss"}

EIGHT_KPIS = {
    KpiName.EXPECTED_LOSS.value,
    KpiName.EXPECTED_PAYOUT.value,
    KpiName.EXPECTED_UNCOVERED.value,
    KpiName.VAR_UNCOVERED.value,
    KpiName.CVAR_UNCOVERED.value,
    KpiName.RMSE_RESIDUAL.value,
    KpiName.PAYOUT_TO_LOSS_RATIO.value,
    KpiName.CORRELATION.value,
}


def toy_dict(
    directory: Path,
    allocation: object = None,
    **changes: Any,  # noqa: ANN401
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "toy",
        "eventset": {"path": str(directory / "eventset")},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 60.0, "n_bins": 2},
        "scopes": [{"kind": "individual"}, {"kind": "portfolio"}],
        "objectives": [{"kind": "mse"}, {"kind": "expected_uncovered"}],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.5},
        "output": {"directory": str(directory / "results")},
    }
    if allocation is not None:
        data["evaluation"]["allocation"] = allocation
    data.update(changes)
    return data


@pytest.fixture
def toy_dir(tmp_path: Path, toy_eventset: EventSet) -> Path:
    toy_eventset.to_parquet(tmp_path / "eventset")
    return tmp_path


# -- schema -----------------------------------------------------------------------


def test_rules_are_the_evaluate_rules() -> None:
    assert ALLOCATION_RULES == tuple(a.value for a in Allocation)
    assert EvaluationConfig(beta=0.5).allocation == "none"


def test_default_is_left_out_of_every_dump(tmp_path: Path) -> None:
    unset = parse_config(toy_dict(tmp_path))
    explicit = parse_config(toy_dict(tmp_path, "none"))
    assert unset == explicit
    for config in (unset, explicit):
        assert config.evaluation.allocation == "none"
        assert "allocation" not in to_dict(config)["evaluation"]
        assert "allocation" not in canonical_json(config)
        assert "allocation" not in dump_config(config)
    assert canonical_json(explicit) == canonical_json(unset)
    assert config_hash(explicit) == config_hash(unset)
    assert dump_config(explicit) == dump_config(unset)


def test_default_drop_keeps_a_custom_grid(tmp_path: Path) -> None:
    data = toy_dict(tmp_path)
    data["evaluation"]["return_periods"] = [2, 10]
    config = parse_config(data)
    assert to_dict(config)["evaluation"] == {"beta": 0.5, "return_periods": [2.0, 10.0]}


@pytest.mark.parametrize("rule", ["value", "loss"])
def test_a_rule_is_dumped_hashed_and_read_back(tmp_path: Path, rule: str) -> None:
    plain = parse_config(toy_dict(tmp_path))
    config = parse_config(toy_dict(tmp_path, rule))
    assert config.evaluation.allocation == rule
    assert to_dict(config)["evaluation"] == {"beta": 0.5, "allocation": rule}
    assert f'"allocation":"{rule}"' in canonical_json(config)
    assert config_hash(config) != config_hash(plain)
    again = parse_config(yaml.safe_load(dump_config(config)))
    assert again == config
    assert config_hash(again) == config_hash(config)


def test_the_two_rules_hash_apart(tmp_path: Path) -> None:
    hashes = {
        config_hash(parse_config(toy_dict(tmp_path, rule))) for rule in ALLOCATION_RULES
    }
    assert len(hashes) == len(ALLOCATION_RULES)


def test_derived_configs_keep_the_rule(tmp_path: Path) -> None:
    data = toy_dict(
        tmp_path,
        "loss",
        objectives=[{"kind": "weighted_cvar", "alpha": 0.5, "beta": 0.9}],
        sweeps=[{"parameter": "alpha", "values": [0.1, 0.9]}],
    )
    config = parse_config(data)
    assert all(s.evaluation.allocation == "loss" for s in config.single_runs())
    assert config.with_parameter("alpha", 0.1).evaluation.allocation == "loss"
    assert config.with_locations(["A"]).evaluation.allocation == "loss"


@pytest.mark.parametrize("rule", ["Value", "bogus", "", None, 1, True, ["value"]])
def test_an_unknown_rule_is_a_config_error(tmp_path: Path, rule: object) -> None:
    data = toy_dict(tmp_path)
    data["evaluation"]["allocation"] = rule
    with pytest.raises(ConfigError) as info:
        parse_config(data, source="test.yaml")
    assert "evaluation.allocation" in str(info.value)


# -- existing configs keep their hashes ------------------------------------------

EXISTING_HASHES: dict[str, tuple[str, int, str]] = {
    "parity/configs/thesis.yaml": (
        "sha256:155d5f8978a1e03056d4e15c8bdf495e0091f25fb4b678275a87a9221a8b280e",
        9,
        "1ab21d813c3fcafe62bd49cd7ab9e7cd1ac74036791140517522e95ce8397b83",
    ),
    "site/configs/explorer.yaml": (
        "sha256:6172c6d9b3ca01f6b3bf9dcbe9527ac4245670904c08eb9dae0134a7edd6d37f",
        3,
        "31261dacf8ac81c71cd6f5448a53dbffa10e1df60e193e791db2ad4118eff9c0",
    ),
    "research/configs/c1/c1_main.yaml": (
        "sha256:d3d05714df2c2f4877a1ecd94b78df2c7a12a9b7b1950a1de47af284fc2e5058",
        9,
        "cff351ec157142829d5ca6e7032af2ab8836e8066cfc74e0bf8407336c0bd690",
    ),
    "research/data/annual-basis-rerun/thesis_annual.yaml": (
        "sha256:4e15b5c2b0b072c254d248312be8e79719b72debfd73c20b21cf3ada3bfe256a",
        9,
        "c8fed89cee83706708580221e70daa8547ba34dfc5ce7a098e212e5637fbf780",
    ),
    "research/data/annual-basis-rerun/thesis_event.yaml": (
        "sha256:6fee9726573808d36a9aed18cad7a96c61ba01f5b4e364ed9e7c81b184b347bc",
        9,
        "083c211c6668486a94ab32bab5b43a8e108e815029bdf88ae1c85bd41f6a3218",
    ),
    "research/data/annual-basis-rerun/thesis_event_conditional.yaml": (
        "sha256:3020bfa3636b2613bc1a8b4548e5131466bb65b7e0f823681acc53731a4eee93",
        9,
        "ee34666eb0422f2a6b1cd3ba97f9b9e9cb5cc25d0bfa41f99bbeaf3b1b1959aa",
    ),
}
"""Every experiment config in the repository: its ``config_hash``, the number
of its single runs, and the SHA-256 of their ``config_hash`` values joined by
newlines. Computed on ``main`` at ``91e309b``, before MAR-217."""


@pytest.mark.parametrize("path", sorted(EXISTING_HASHES))
def test_existing_configs_keep_their_hashes(path: str) -> None:
    file = REPO_ROOT / path
    if not file.is_file():
        pytest.skip(f"{path} is only in a repository checkout")
    config = load_config(file)
    assert config.evaluation.allocation == "none"
    assert "allocation" not in canonical_json(config)
    expected_hash, n_singles, digest = EXISTING_HASHES[path]
    assert config_hash(config) == expected_hash
    singles = [config_hash(s) for s in config.single_runs()]
    assert len(singles) == n_singles
    joined = "\n".join(singles).encode("ascii")
    assert hashlib.sha256(joined).hexdigest() == digest


# -- runner -----------------------------------------------------------------------


def _rows(frame: pd.DataFrame, **equal: str) -> pd.DataFrame:
    """The rows whose columns equal the given strings, index reset."""
    mask = np.ones(len(frame), dtype=bool)
    for column, value in equal.items():
        mask &= (frame[column].astype(str) == value).to_numpy()
    return cast(pd.DataFrame, frame.loc[mask]).reset_index(drop=True)


def _levels(frame: pd.DataFrame) -> set[str]:
    return set(frame["level"].astype(str))


def _without(frame: pd.DataFrame, run_id: str, level: str | None) -> pd.DataFrame:
    """A run's rows other than ``level``, without the ``run_id`` column."""
    run = _rows(frame, run_id=run_id)
    keep = (run["level"].astype(str) != level).to_numpy()
    return (
        cast(pd.DataFrame, run.loc[keep])
        .drop(columns=["run_id"])
        .reset_index(drop=True)
    )


@pytest.mark.parametrize("rule", ["value", "loss"])
def test_a_run_under_a_rule_stores_location_rows(toy_dir: Path, rule: str) -> None:
    level = LOCATION_LEVELS[rule]
    plain = parse_config(toy_dict(toy_dir))
    config = parse_config(toy_dict(toy_dir, rule))
    plain_store = ResultStore(toy_dir / "plain")
    store = ResultStore(toy_dir / rule)
    plain_out = run_config(plain, store=plain_store)
    out = run_config(config, store=store)
    assert all(o.ok for o in (*plain_out, *out))

    kpis = store.read("kpis")
    curves = store.read("exceedance")
    for outcome in out:
        rows = _rows(kpis, run_id=outcome.run_id, level=level)
        assert set(rows["subject_id"]) == {"A", "B"}
        assert set(rows["kpi"]) == EIGHT_KPIS  # no premium per location
        assert len(rows) == 2 * len(EIGHT_KPIS)
        crows = _rows(curves, run_id=outcome.run_id, level=level)
        assert set(crows["subject_id"]) == {"A", "B"}
    other = set(LOCATION_LEVELS.values()) - {level}
    assert not _levels(kpis) & other

    # Every other row is the "none" run's row, in the same order.
    plain_kpis = plain_store.read("kpis")
    plain_curves = plain_store.read("exceedance")
    assert not _levels(plain_kpis) & set(LOCATION_LEVELS.values())
    assert not _levels(plain_curves) & set(LOCATION_LEVELS.values())
    for a, b in zip(plain_out, out, strict=True):
        for ours, theirs in ((kpis, plain_kpis), (curves, plain_curves)):
            pd.testing.assert_frame_equal(
                _without(ours, b.run_id, level), _without(theirs, a.run_id, None)
            )


def test_location_rows_of_the_portfolio_scope_add_up(toy_dir: Path) -> None:
    config = parse_config(
        toy_dict(
            toy_dir,
            "loss",
            scopes=[{"kind": "portfolio"}],
            objectives=[{"kind": "mse"}],
        )
    )
    store = ResultStore(toy_dir / "loss")
    (outcome,) = run_config(config, store=store)
    kpis = store.read("kpis")
    for kpi in (KpiName.EXPECTED_LOSS, KpiName.EXPECTED_PAYOUT):
        locations = _rows(kpis, kpi=kpi.value, level=KpiLevel.LOCATION_BY_LOSS.value)
        problem = _rows(kpis, kpi=kpi.value, level=KpiLevel.PROBLEM.value)
        assert set(locations["run_id"]) == {outcome.run_id}
        assert len(locations) == 2
        assert len(problem) == 1
        np.testing.assert_allclose(
            locations["value"].to_numpy(np.float64).sum(),
            problem["value"].to_numpy(np.float64)[0],
            rtol=1e-12,
        )


def test_a_rule_is_not_a_cache_hit_on_the_none_run(toy_dir: Path) -> None:
    store = ResultStore(toy_dir / "shared")
    plain = parse_config(toy_dict(toy_dir))
    ruled = parse_config(toy_dict(toy_dir, "value"))
    first = run_config(plain, store=store)
    second = run_config(ruled, store=store)
    assert not any(o.cached for o in first)
    assert not any(o.cached for o in second)
    assert not {o.run_id for o in first} & {o.run_id for o in second}
    # The rule changes the evaluation only: the same designs were solved.
    payouts = store.read("payouts")
    for a, b in zip(first, second, strict=True):
        pd.testing.assert_frame_equal(
            _rows(payouts, run_id=a.run_id).drop(columns=["run_id"]),
            _rows(payouts, run_id=b.run_id).drop(columns=["run_id"]),
        )
    # Each run is then a hit on its own entry, and an explicit "none" on the
    # stored "none" run.
    assert all(o.cached for o in run_config(ruled, store=store))
    explicit = run_config(parse_config(toy_dict(toy_dir, "none")), store=store)
    assert [o.run_id for o in explicit] == [o.run_id for o in first]
    assert all(o.cached for o in explicit)


def test_parameters_and_manifest_record_a_rule_only(
    toy_dir: Path, toy_eventset: EventSet
) -> None:
    for rule in ("none", "value", "loss"):
        config = parse_config(toy_dict(toy_dir, rule))
        store = ResultStore(toy_dir / f"m-{rule}")
        for single, outcome in zip(
            config.single_runs(), run_config(config, store=store), strict=True
        ):
            params = run_parameters(single, toy_eventset)
            runs = store.read("runs")
            stored = [
                json.loads(p)
                for p in runs.loc[runs["run_id"] == outcome.run_id, "parameters"]
            ]
            manifest = store.manifest(outcome.run_id)
            if rule == "none":
                assert "allocation" not in params
                assert all("allocation" not in p for p in stored)
                assert "allocation" not in manifest["parameters"]
                assert set(manifest["evaluation"]) == {
                    "evaluated",
                    "skipped_reason",
                    "beta",
                }
                assert "allocation" not in manifest["config"]["evaluation"]
            else:
                assert params["allocation"] == rule
                assert all(p["allocation"] == rule for p in stored)
                assert manifest["parameters"]["allocation"] == rule
                assert manifest["evaluation"]["allocation"] == rule
                assert manifest["config"]["evaluation"]["allocation"] == rule


def test_a_rule_without_value_shares_fails_loudly(toy_dir: Path) -> None:
    """A joint problem whose locations all have value 0 cannot be split by value."""
    eventset = EventSet.from_parquet(toy_dir / "eventset")
    locations = eventset.locations.assign(value=0.0)
    zero = EventSet(
        events=eventset.events,
        locations=locations,
        index=eventset.index,
        loss=eventset.loss,
        metadata=eventset.metadata,
    )
    zero.to_parquet(toy_dir / "zero")
    data = toy_dict(
        toy_dir, "value", scopes=[{"kind": "portfolio"}], objectives=[{"kind": "mse"}]
    )
    data["eventset"] = {"path": str(toy_dir / "zero")}
    store = ResultStore(toy_dir / "zero-results")
    with pytest.raises(EntityMismatchError, match="value 0"):
        run_config(parse_config(data), store=store)
    assert store.read("kpis").empty


# -- k-fold -----------------------------------------------------------------------

N_YEARS = 40


def kfold_eventset() -> EventSet:
    """40 events in 40 years at three locations; loss grows with the index."""
    rng = np.random.default_rng(20261101)
    base = rng.uniform(5.0, 75.0, size=N_YEARS)
    index = np.clip(base[:, None] + rng.normal(0.0, 4.0, (N_YEARS, 3)), 0.0, None)
    values = np.array([100.0, 60.0, 30.0])
    loss = np.clip((index - 20.0) / 50.0, 0.0, 1.0) ** 2 * values
    events = pd.DataFrame(
        {
            "event_id": [f"ev{i}" for i in range(N_YEARS)],
            "year": np.arange(N_YEARS),
            "rate": np.full(N_YEARS, 1 / N_YEARS),
            "draw_id": np.zeros(N_YEARS, dtype=int),
            "scenario_id": ["toy"] * N_YEARS,
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
            producer="core allocation tests",
            producer_version="0",
            created_at=datetime(2026, 11, 1, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events, locations=locations, index=index, loss=loss, metadata=metadata
    )


def kfold_config(directory: Path, rule: str, output: str) -> ExperimentConfig:
    return parse_config(
        {
            "schema_version": 1,
            "name": "kfold-allocation",
            "eventset": {"path": str(directory / "kfold-eventset")},
            "basis": "event_conditional",
            "sample": {"kind": "kfold", "k": 2},
            "payout": {"attachment": 20.0, "limit": 70.0, "n_bins": 3},
            "scopes": [{"kind": "portfolio"}],
            "objectives": [{"kind": "mse"}],
            "constraints": [{"kind": "budget", "loading": 1.0}],
            "evaluation": {"beta": 0.9, "allocation": rule},
            "output": {"directory": str(directory / output)},
        }
    )


def test_kfold_folds_store_location_rows_and_pooling_stays_at_the_portfolio(
    tmp_path: Path,
) -> None:
    kfold_eventset().to_parquet(tmp_path / "kfold-eventset")
    pooled: dict[str, pd.DataFrame] = {}
    for rule in ("none", "value"):
        config = kfold_config(tmp_path, rule, f"kfold-{rule}")
        store = ResultStore(config.output.directory)
        data = load_input(config)
        outcomes = run_config(config, store=store, data=data)
        assert len(outcomes) == 2
        assert all(o.ok for o in outcomes)
        kpis = store.read("kpis")
        location = _rows(kpis, level=KpiLevel.LOCATION_BY_VALUE.value)
        if rule == "none":
            assert location.empty
        else:
            # Every fold stores its location rows, in and out of sample.
            got = set(
                zip(
                    location["fold"],
                    location["eval_split"],
                    location["subject_id"],
                    strict=True,
                )
            )
            assert got == {
                (f, s, loc)
                for f in (0, 1)
                for s in ("train", "test")
                for loc in ("A1", "A2", "A3")
            }
        result = pooled_kpis(
            config,
            store,
            prepare_eventset(config, data.eventset),
            [o.run_id for o in outcomes],
        )
        # Pooling is at the portfolio level whatever the rule (kfold.py).
        assert set(result.table["level"]) == {KpiLevel.PORTFOLIO.value}
        pooled[rule] = result.table.drop(columns=["run_ids"])
    pd.testing.assert_frame_equal(pooled["none"], pooled["value"])
