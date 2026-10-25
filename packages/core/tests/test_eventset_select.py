"""Tests for :meth:`EventSet.select_locations` (MAR-92).

The location subset of ``portfolio.location_ids`` and of each ``n_assets``
sweep point (MAR-63). The last group checks the subsets the thesis
``n_assets`` sweep chose on the parity fixture against the thesis column
selection.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import itertools
import os
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.errors import ParametricInsuranceDesignError
from parametric_insurance_design.eventset import (
    SELECT_LOCATIONS_TRANSFORM,
    DuplicateKeyError,
    EventSet,
    EventSetError,
    EventSetMetadata,
    HazardSource,
    InconsistentKeysError,
    IndexDefinition,
    LossDefinition,
    Provenance,
    SchemaError,
    TransformRecord,
)
from parametric_insurance_design.experiment.config import load_config

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"
PARITY_CONFIG = REPO_ROOT / "parity" / "configs" / "thesis.yaml"
THESIS_REPO_ENV = "PARITY_THESIS_REPO"
THESIS_MODULE = "src/utils/data_processing.py"
THESIS_CSV = "data/output/climada_transformed_loss_data.csv"
FUNCTION = "parametric_insurance_design.eventset.EventSet.select_locations"


# --------------------------------------------------------------------------
# A small EventSet with draws and free location columns
# --------------------------------------------------------------------------


def make_metadata(**overrides: object) -> EventSetMetadata:
    fields: dict[str, Any] = {
        "hazard": HazardSource(name="IRIS", release="v1.0"),
        "index": IndexDefinition(definition="max wind at the asset", unit="m/s"),
        "loss": LossDefinition(unit="USD", currency="USD"),
        "n_years": 100,
        "scenario": "historical climate",
        "provenance": Provenance(
            producer="tests",
            producer_version="0.0.1",
            created_at=datetime(2026, 10, 25, 12, 30, tzinfo=UTC),
        ),
        "licence": "CC-BY-4.0",
    }
    fields.update(overrides)
    return EventSetMetadata(**fields)


def make_eventset(
    n_events: int = 3, n_draws: int = 2, n_locations: int = 4
) -> EventSet:
    events = pd.DataFrame(
        {
            "event_id": [f"ev{e}" for e in range(n_events) for _ in range(n_draws)],
            "year": [e + 1 for e in range(n_events) for _ in range(n_draws)],
            "rate": [1.0 / (100 * n_draws)] * (n_events * n_draws),
            "draw_id": [d for _ in range(n_events) for d in range(n_draws)],
            "scenario_id": ["hist"] * (n_events * n_draws),
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": [f"loc{i}" for i in range(n_locations)],
            "lat": np.linspace(25.0, 30.0, n_locations),
            "lon": np.linspace(-82.0, -80.0, n_locations),
            "value": np.arange(1, n_locations + 1, dtype=np.float64) * 1e6,
            "name": [f"Asset {i}" for i in range(n_locations)],
            # Free metadata columns of several kinds.
            "country": ["US"] * n_locations,
            "floors": np.arange(n_locations, dtype=np.int64),
        }
    )
    shape = (len(events), n_locations)
    # Distinct values per cell, so that a wrong column shows.
    cells = np.arange(shape[0] * shape[1], dtype=np.float64).reshape(shape)
    return EventSet(
        events=events,
        locations=locations,
        index=cells + 0.5,
        loss=cells * 10.0,
        metadata=make_metadata(),
    )


@pytest.fixture
def es() -> EventSet:
    return make_eventset()


def same_data(a: EventSet, b: EventSet) -> bool:
    """Equal tables and matrices; the metadata may differ."""
    return (
        a.events.equals(b.events)
        and a.locations.equals(b.locations)
        and np.array_equal(a.index, b.index)
        and np.array_equal(a.loss, b.loss)
    )


# --------------------------------------------------------------------------
# Order, content and metadata
# --------------------------------------------------------------------------


def test_keeps_columns_and_locations_in_the_given_order(es: EventSet) -> None:
    ids = ["loc3", "loc0", "loc2"]
    sub = es.select_locations(ids)
    assert sub.location_ids == ids
    assert sub.n_locations == 3
    np.testing.assert_array_equal(sub.index, es.index[:, [3, 0, 2]])
    np.testing.assert_array_equal(sub.loss, es.loss[:, [3, 0, 2]])
    expected = es.locations.iloc[[3, 0, 2]].reset_index(drop=True)
    pd.testing.assert_frame_equal(sub.locations, expected)
    # Free metadata columns travel with their rows, in their column order.
    assert list(sub.locations.columns) == list(es.locations.columns)
    assert sub.locations["floors"].tolist() == [3, 0, 2]
    assert sub.locations["floors"].dtype == np.int64


def test_keeps_every_event_row(es: EventSet) -> None:
    sub = es.select_locations(["loc1"])
    pd.testing.assert_frame_equal(sub.events, es.events)
    assert sub.n_rows == es.n_rows
    np.testing.assert_array_equal(sub.rates, es.rates)
    # Rows that lose all their loss in the subset are kept (zero-loss rows).
    assert sub.index.shape == (es.n_rows, 1)


def test_single_location_keeps_two_dimensional_matrices(es: EventSet) -> None:
    sub = es.select_locations(["loc2"])
    assert sub.index.ndim == 2
    np.testing.assert_array_equal(sub.loss[:, 0], es.loss[:, 2])


def test_appends_a_transform_record_and_keeps_the_metadata(es: EventSet) -> None:
    sub = es.select_locations(["loc2", "loc0"])
    (record,) = sub.metadata.transforms
    assert record == TransformRecord(
        name=SELECT_LOCATIONS_TRANSFORM,
        function=FUNCTION,
        version=version("parametric-insurance-design"),
        n_filters_before=0,
        parameters={"location_ids": ["loc2", "loc0"], "n_locations_before": 4},
    )
    assert SELECT_LOCATIONS_TRANSFORM == "select_locations"
    # Everything else in the metadata is unchanged.
    assert dataclasses.replace(sub.metadata, transforms=()) == es.metadata


def test_keeps_filters_and_earlier_transforms(es: EventSet) -> None:
    earlier = TransformRecord(
        name="noise",
        function="parametric_insurance_design.noise.add_noise",
        version="0.1.0",
        n_filters_before=0,
        parameters={"level": 0.3},
    )
    base = EventSet(
        events=es.events,
        locations=es.locations,
        index=es.index,
        loss=es.loss,
        metadata=dataclasses.replace(es.metadata, transforms=(earlier,)),
    )
    filtered = base.filter_threshold(10.0)
    sub = filtered.select_locations(["loc1", "loc3"])
    assert sub.metadata.filters == filtered.metadata.filters
    assert sub.metadata.transforms[0] == earlier
    assert sub.metadata.transforms[1].name == SELECT_LOCATIONS_TRANSFORM
    assert sub.metadata.transforms[1].n_filters_before == 1
    # A filter after the subset keeps the record's place among the filters.
    later = sub.filter_threshold(20.0)
    assert len(later.metadata.filters) == 2
    assert later.metadata.transforms == sub.metadata.transforms


def test_every_call_records_even_the_identity(es: EventSet) -> None:
    same = es.select_locations(es.location_ids)
    assert same_data(same, es)
    assert len(same.metadata.transforms) == 1
    assert same.content_hash() != es.content_hash()


def test_accepts_any_sequence_of_ids(es: EventSet) -> None:
    expected = es.select_locations(["loc1", "loc0"])
    for ids in (
        ("loc1", "loc0"),
        np.array(["loc1", "loc0"]),
        pd.Index(["loc1", "loc0"]),
        pd.Series(["loc1", "loc0"]),
    ):
        sub = es.select_locations(ids)  # pyright: ignore[reportArgumentType]
        assert sub.equals(expected)
    # numpy strings are recorded as plain str, so the record survives JSON.
    record = es.select_locations(np.array(["loc1"])).metadata.transforms[0]  # pyright: ignore[reportArgumentType]
    assert type(record.parameters["location_ids"][0]) is str


def test_does_not_change_the_input(es: EventSet) -> None:
    before = make_eventset()
    ids = ["loc3", "loc1"]
    sub = es.select_locations(ids)
    ids.append("loc0")
    assert es.equals(before)
    assert sub.metadata.transforms[0].parameters["location_ids"] == ["loc3", "loc1"]
    assert not np.shares_memory(sub.index, es.index)
    assert not sub.index.flags.writeable


def test_eventset_without_event_rows() -> None:
    empty = make_eventset(n_events=0)
    sub = empty.select_locations(["loc2", "loc1"])
    assert sub.n_rows == 0
    assert sub.index.shape == (0, 2)
    assert sub.location_ids == ["loc2", "loc1"]


# --------------------------------------------------------------------------
# Errors: nothing is dropped silently
# --------------------------------------------------------------------------


def test_empty_selection_is_an_error(es: EventSet) -> None:
    # An EventSet holds at least one location (constructor rule), so an empty
    # subset is refused rather than returned.
    with pytest.raises(SchemaError, match="at least one location"):
        es.select_locations([])
    with pytest.raises(SchemaError, match="at least one location"):
        es.select_locations(np.array([], dtype=str))  # pyright: ignore[reportArgumentType]


def test_unknown_ids_are_an_error(es: EventSet) -> None:
    with pytest.raises(InconsistentKeysError, match=r"2 location_ids .*'nope', 'A1'"):
        es.select_locations(["loc0", "nope", "A1"])


def test_repeated_ids_are_an_error(es: EventSet) -> None:
    with pytest.raises(DuplicateKeyError, match=r"repeat 2 ids, e.g. 'loc1', 'loc0'"):
        es.select_locations(["loc1", "loc0", "loc1", "loc0", "loc1"])


def test_a_single_string_is_an_error(es: EventSet) -> None:
    # A str is a sequence of characters; refuse it rather than look up "l", "o".
    with pytest.raises(SchemaError, match="not the string 'loc0'"):
        es.select_locations("loc0")


def test_non_string_ids_are_an_error(es: EventSet) -> None:
    with pytest.raises(
        SchemaError, match=r"must be strings; 2 are not, e\.g\. 0, None"
    ):
        es.select_locations(["loc0", 0, None])  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize("ids", [[], ["nope"], ["loc0", "loc0"], "loc0", [1]], ids=repr)
def test_errors_are_library_and_value_errors(es: EventSet, ids: object) -> None:
    with pytest.raises(EventSetError) as info:
        es.select_locations(ids)  # pyright: ignore[reportArgumentType]
    assert isinstance(info.value, ParametricInsuranceDesignError)
    assert isinstance(info.value, ValueError)
    assert info.value.table == "locations"


# --------------------------------------------------------------------------
# Round trips and the content hash
# --------------------------------------------------------------------------


def test_parquet_round_trip(es: EventSet, tmp_path: Path) -> None:
    sub = es.filter_threshold(5.0).select_locations(["loc3", "loc1"])
    back = EventSet.from_parquet(sub.to_parquet(tmp_path / "subset"))
    assert back.equals(sub)
    assert back.content_hash() == sub.content_hash()


def test_permutation_round_trip(es: EventSet) -> None:
    order = ["loc2", "loc0", "loc3", "loc1"]
    shuffled = es.select_locations(order)
    back = shuffled.select_locations(es.location_ids)
    assert same_data(back, es)
    assert [t.parameters["location_ids"] for t in back.metadata.transforms] == [
        order,
        es.location_ids,
    ]


def test_subsets_compose(es: EventSet) -> None:
    twice = es.select_locations(["loc3", "loc1", "loc0"]).select_locations(
        ["loc0", "loc3"]
    )
    once = es.select_locations(["loc0", "loc3"])
    assert same_data(twice, once)
    assert twice.metadata.transforms[1].parameters["n_locations_before"] == 3


def test_content_hash_reflects_the_subset(es: EventSet) -> None:
    sub = es.select_locations(["loc1", "loc2"])
    assert sub.content_hash() == es.select_locations(["loc1", "loc2"]).content_hash()
    assert sub.content_hash() != es.content_hash()
    assert sub.content_hash() != es.select_locations(["loc2", "loc1"]).content_hash()
    # The record makes a subset differ from the same data built directly.
    direct = EventSet(
        events=sub.events,
        locations=sub.locations,
        index=sub.index,
        loss=sub.loss,
        metadata=es.metadata,
    )
    assert same_data(direct, sub)
    assert direct.content_hash() != sub.content_hash()


# --------------------------------------------------------------------------
# Thesis n_assets sweep on the parity fixture (MAR-92 acceptance)
# --------------------------------------------------------------------------


def thesis_n_assets_choices(
    assets: list[str], values: list[int], max_combos_per_n: int | None, seed: int
) -> list[tuple[str, ...]]:
    """The asset subsets of the thesis ``n_assets`` sweep, in thesis order.

    A copy of the subset choice in the thesis
    ``sensitivity_analysis._build_kpi_df_n_assets`` (portfolio view, no asset
    filter): ``itertools.combinations`` over the asset list, and, where there
    are more than ``max_combos_per_n``, a sample drawn with one generator
    shared by all sizes.
    """
    rng = np.random.default_rng(seed)
    chosen: list[tuple[str, ...]] = []
    for n in values:
        if n < 1 or n > len(assets):
            continue
        combos = list(itertools.combinations(assets, n))
        if max_combos_per_n and len(combos) > max_combos_per_n:
            idx = rng.choice(len(combos), size=max_combos_per_n, replace=False)
            combos = [combos[i] for i in idx]
        chosen.extend(combos)
    return chosen


def thesis_matrices(
    frame: pd.DataFrame, asset_ids: tuple[str, ...]
) -> tuple[np.ndarray, np.ndarray]:
    """The thesis solver's index and loss matrices of a sub-portfolio frame.

    As in the notebook's ``_get_asset_parameter_values``: column ``j`` is
    ``<asset_ids[j]>_Wind`` (index) and ``<asset_ids[j]>_Loss`` (loss).
    """
    index = np.column_stack(
        [frame[f"{a}_Wind"].to_numpy(dtype=float) for a in asset_ids]
    )
    loss = np.column_stack(
        [frame[f"{a}_Loss"].to_numpy(dtype=float) for a in asset_ids]
    )
    return index, loss


@pytest.fixture(scope="module")
def parity_choices() -> tuple[EventSet, list[tuple[str, ...]]]:
    if not (PARITY_EVENTSET.is_dir() and PARITY_CONFIG.is_file()):
        pytest.skip("the parity fixture is only in a repository checkout")
    config = load_config(PARITY_CONFIG)
    (sweep,) = [s for s in config.sweeps if s.parameter == "n_assets"]
    assets = config.portfolio.location_ids
    assert assets is not None
    assert sweep.seed is not None
    choices = thesis_n_assets_choices(
        list(assets),
        [int(v) for v in sweep.values],
        sweep.max_combinations,
        sweep.seed,
    )
    return EventSet.from_parquet(PARITY_EVENTSET), choices


def test_thesis_n_assets_choices(
    parity_choices: tuple[EventSet, list[tuple[str, ...]]],
) -> None:
    eventset, choices = parity_choices
    # Thesis sweep: n = 1..9 over A1..A9, at most 25 subsets per size.
    sizes = [len(c) for c in choices]
    assert [sizes.count(n) for n in range(1, 10)] == [9, 25, 25, 25, 25, 25, 25, 9, 1]
    # Every subset lists its assets in asset-list order (combinations).
    position = {a: j for j, a in enumerate(eventset.location_ids)}
    assert all(
        [position[a] for a in c] == sorted(position[a] for a in c) for c in choices
    )


def test_parity_subsets_match_thesis_columns(
    parity_choices: tuple[EventSet, list[tuple[str, ...]]],
) -> None:
    eventset, choices = parity_choices
    # The fixture's columns are the thesis A<k>_Wind and A<k>_Loss columns,
    # bit-identical (parity/README.md), so this wide frame is the thesis
    # simulation frame before the noise layer.
    frame = pd.DataFrame(
        {
            f"{a}_{kind}": matrix[:, j]
            for j, a in enumerate(eventset.location_ids)
            for kind, matrix in (("Wind", eventset.index), ("Loss", eventset.loss))
        }
    )
    for combo in choices:
        sub = eventset.select_locations(combo)
        index, loss = thesis_matrices(frame, combo)
        assert sub.location_ids == list(combo)
        np.testing.assert_array_equal(sub.index, index, strict=True)
        np.testing.assert_array_equal(sub.loss, loss, strict=True)
        assert sub.events.equals(eventset.events)
        assert sub.locations["value"].tolist() == [
            eventset.locations.set_index("location_id").at[a, "value"] for a in combo
        ]


def _thesis_repo() -> Path:
    value = os.environ.get(THESIS_REPO_ENV)
    if not value:
        pytest.skip(
            f"{THESIS_REPO_ENV} is not set: set it to a checkout of "
            "parametric-insurance-framework to compare with the thesis code"
        )
    return Path(value)


def _load_thesis_module(repo: Path) -> ModuleType:
    path = repo / THESIS_MODULE
    if not path.is_file():
        raise FileNotFoundError(f"{repo} does not hold {THESIS_MODULE}")
    spec = importlib.util.spec_from_file_location("thesis_data_processing", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The thesis calls DataFrame.drop(inplace=True), which pandas 3.1 deprecates.
@pytest.mark.filterwarnings("ignore:The inplace keyword in DataFrame.drop")
def test_parity_subsets_match_thesis_create_sub_portfolio(
    parity_choices: tuple[EventSet, list[tuple[str, ...]]],
) -> None:
    repo = _thesis_repo()
    thesis = _load_thesis_module(repo)
    raw = pd.read_csv(repo / THESIS_CSV)
    eventset, choices = parity_choices
    assert raw["Event_ID"].tolist() == eventset.events["event_id"].tolist()
    for combo in choices:
        frame = thesis.create_sub_portfolio(raw, list(combo))
        index, loss = thesis_matrices(frame, combo)
        sub = eventset.select_locations(combo)
        np.testing.assert_array_equal(sub.index, index, strict=True)
        np.testing.assert_array_equal(sub.loss, loss, strict=True)
