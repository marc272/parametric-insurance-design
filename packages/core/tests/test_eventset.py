"""Tests for the EventSet data contract (SPEC §5, MAR-8)."""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from parametric_insurance_design.eventset import (
    EVENTS_FILE,
    LOCATIONS_FILE,
    METADATA_FILE,
    SCHEMA_VERSION,
    VALUES_FILE,
    DuplicateKeyError,
    EventSet,
    EventSetError,
    EventSetMetadata,
    HazardSource,
    InconsistentKeysError,
    IndexDefinition,
    LossDefinition,
    MissingColumnsError,
    NegativeLossError,
    NonFiniteValueError,
    NonPositiveRateError,
    OutOfRangeError,
    Provenance,
    SchemaError,
    ThresholdFilterRecord,
)

# --------------------------------------------------------------------------
# Fixtures
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
            source_checksums={"tracks.nc": "sha256:abc123"},
        ),
        "licence": "CC-BY-4.0",
    }
    fields.update(overrides)
    return EventSetMetadata(**fields)


def make_events(n_events: int = 3, n_draws: int = 2) -> pd.DataFrame:
    rows = [
        {
            "event_id": f"ev{e}",
            "year": e + 1,
            "rate": 1.0 / (100 * n_draws),
            "draw_id": d,
            "scenario_id": "hist",
        }
        for e in range(n_events)
        for d in range(n_draws)
    ]
    return pd.DataFrame(
        rows, columns=["event_id", "year", "rate", "draw_id", "scenario_id"]
    )


def make_locations(n: int = 4) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "location_id": [f"loc{i}" for i in range(n)],
            "lat": np.linspace(25.0, 30.0, n),
            "lon": np.linspace(-82.0, -80.0, n),
            "value": np.arange(1, n + 1, dtype=np.float64) * 1e6,
            "name": [f"Asset {i}" for i in range(n)],
            # Free metadata columns of several types.
            "country": ["US"] * n,
            "floors": np.arange(n, dtype=np.int64),
        }
    )


def make_eventset(seed: int = 0) -> EventSet:
    rng = np.random.default_rng(seed)
    events = make_events()
    locations = make_locations()
    shape = (len(events), len(locations))
    return EventSet(
        events=events,
        locations=locations,
        index=rng.uniform(0.0, 70.0, size=shape),
        loss=rng.uniform(0.0, 1e5, size=shape) * (rng.random(shape) > 0.3),
        metadata=make_metadata(),
    )


@pytest.fixture
def es() -> EventSet:
    return make_eventset()


def parts(es: EventSet) -> dict[str, Any]:
    return {
        "events": es.events.copy(),
        "locations": es.locations.copy(),
        "values": es.to_long(),
        "metadata": es.metadata,
    }


# --------------------------------------------------------------------------
# Construction and model
# --------------------------------------------------------------------------


def test_constructor_normalises_tables_and_matrices(es: EventSet) -> None:
    assert es.n_rows == 6
    assert es.n_locations == 4
    assert es.index.shape == es.loss.shape == (6, 4)
    assert es.index.dtype == es.loss.dtype == np.float64
    assert not es.index.flags.writeable
    assert not es.loss.flags.writeable
    assert list(es.events.columns) == [
        "event_id",
        "year",
        "rate",
        "draw_id",
        "scenario_id",
    ]
    assert es.events["event_id"].dtype == object
    assert es.events["year"].dtype == np.int64
    assert es.events["rate"].dtype == np.float64
    assert isinstance(es.events.index, pd.RangeIndex)
    assert list(es.locations.columns)[:5] == [
        "location_id",
        "lat",
        "lon",
        "value",
        "name",
    ]
    assert es.location_ids == ["loc0", "loc1", "loc2", "loc3"]
    np.testing.assert_array_equal(es.rates, np.full(6, 1.0 / 200))


def test_constructor_copies_inputs() -> None:
    events = make_events()
    index = np.ones((6, 4))
    es = EventSet(events, make_locations(), index, np.zeros((6, 4)), make_metadata())
    index[0, 0] = 99.0
    events.loc[0, "rate"] = 5.0
    assert es.index[0, 0] == 1.0
    assert es.events.loc[0, "rate"] == pytest.approx(1.0 / 200)


def test_constructor_accepts_shuffled_index_and_string_dtype() -> None:
    events = make_events().sample(frac=1.0, random_state=1)
    events["event_id"] = events["event_id"].astype("string")
    locations = make_locations().set_index(pd.Index([10, 11, 12, 13]))
    es = EventSet(
        events, locations, np.zeros((6, 4)), np.zeros((6, 4)), make_metadata()
    )
    assert isinstance(es.events.index, pd.RangeIndex)
    assert es.events["event_id"].dtype == object
    assert es.events["event_id"].tolist() == events["event_id"].tolist()


def test_events_may_be_empty() -> None:
    es = EventSet(
        make_events(0),
        make_locations(),
        np.zeros((0, 4)),
        np.zeros((0, 4)),
        make_metadata(),
    )
    assert es.n_rows == 0
    assert es.to_long().empty


def test_repr_and_equals(es: EventSet) -> None:
    assert "n_rows=6" in repr(es)
    assert "n_locations=4" in repr(es)
    assert es.equals(make_eventset())
    assert not es.equals(make_eventset(seed=1))
    assert not es.equals("not an eventset")


def test_to_long_and_from_long_round_trip(es: EventSet) -> None:
    values = es.to_long()
    assert list(values.columns) == [
        "event_id",
        "draw_id",
        "location_id",
        "index",
        "loss",
    ]
    assert len(values) == es.n_rows * es.n_locations
    # Row order of the long table does not matter.
    shuffled = values.sample(frac=1.0, random_state=0)
    rebuilt = EventSet.from_long(es.events, es.locations, shuffled, es.metadata)
    assert rebuilt.equals(es)


# --------------------------------------------------------------------------
# Parquet round trip
# --------------------------------------------------------------------------


def test_parquet_round_trip(es: EventSet, tmp_path: Path) -> None:
    written = es.to_parquet(tmp_path / "es")
    assert sorted(p.name for p in written.iterdir()) == sorted(
        [EVENTS_FILE, LOCATIONS_FILE, VALUES_FILE, METADATA_FILE]
    )
    back = EventSet.from_parquet(written)
    assert back.equals(es)
    pd.testing.assert_frame_equal(back.events, es.events)
    pd.testing.assert_frame_equal(back.locations, es.locations)
    np.testing.assert_array_equal(back.index, es.index)
    np.testing.assert_array_equal(back.loss, es.loss)
    assert back.metadata == es.metadata


def test_parquet_round_trip_after_filter(es: EventSet, tmp_path: Path) -> None:
    filtered = es.filter_threshold(35.0)
    back = EventSet.from_parquet(filtered.to_parquet(tmp_path / "es"))
    assert back.equals(filtered)
    assert back.metadata.filters == filtered.metadata.filters


def test_parquet_round_trip_empty_events(tmp_path: Path) -> None:
    es = EventSet(
        make_events(0),
        make_locations(),
        np.zeros((0, 4)),
        np.zeros((0, 4)),
        make_metadata(),
    )
    assert EventSet.from_parquet(es.to_parquet(tmp_path / "es")).equals(es)


def test_parquet_round_trip_minimal_metadata(tmp_path: Path) -> None:
    md = make_metadata(
        loss=LossDefinition(unit="fraction of value"),
        provenance=Provenance(
            producer="tests",
            producer_version="1",
            created_at=datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=2))),
        ),
    )
    es = dataclasses.replace(make_eventset(), metadata=md)
    assert EventSet.from_parquet(es.to_parquet(tmp_path / "es")).equals(es)


def test_metadata_json_layout(es: EventSet, tmp_path: Path) -> None:
    es.to_parquet(tmp_path)
    raw = json.loads((tmp_path / METADATA_FILE).read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION == 1
    assert raw["hazard"] == {"name": "IRIS", "release": "v1.0"}
    assert raw["index"] == {"definition": "max wind at the asset", "unit": "m/s"}
    assert raw["loss"] == {"unit": "USD", "currency": "USD"}
    assert raw["n_years"] == 100
    assert raw["provenance"]["created_at"] == "2026-10-25T12:30:00+00:00"
    assert raw["provenance"]["source_checksums"] == {"tracks.nc": "sha256:abc123"}
    assert raw["licence"] == "CC-BY-4.0"
    assert raw["filters"] == []


def test_parquet_schema_types(es: EventSet, tmp_path: Path) -> None:
    es.to_parquet(tmp_path)
    events = pq.read_schema(tmp_path / EVENTS_FILE)
    assert events.field("event_id").type == pa.string()
    assert events.field("year").type == pa.int64()
    assert events.field("rate").type == pa.float64()
    values = pq.read_schema(tmp_path / VALUES_FILE)
    assert values.names == ["event_id", "draw_id", "location_id", "index", "loss"]


def test_to_parquet_refuses_to_overwrite(es: EventSet, tmp_path: Path) -> None:
    es.to_parquet(tmp_path)
    with pytest.raises(FileExistsError, match="overwrite=True"):
        es.to_parquet(tmp_path)
    other = make_eventset(seed=7)
    other.to_parquet(tmp_path, overwrite=True)
    assert EventSet.from_parquet(tmp_path).equals(other)


def test_to_parquet_rejects_file_path(es: EventSet, tmp_path: Path) -> None:
    target = tmp_path / "file"
    target.write_text("x")
    with pytest.raises(FileExistsError, match="not a directory"):
        es.to_parquet(target)


# --------------------------------------------------------------------------
# Threshold filter
# --------------------------------------------------------------------------


def test_filter_threshold_on_index_records_dropped_mass(es: EventSet) -> None:
    # The median row maximum drops half of the rows.
    threshold = float(np.median(es.index.max(axis=1)))
    filtered = es.filter_threshold(threshold)
    keep = (es.index >= threshold).any(axis=1)
    drop = ~keep
    assert 0 < int(drop.sum()) < es.n_rows

    assert filtered.n_rows == int(keep.sum())
    # Rates are never rescaled.
    np.testing.assert_array_equal(filtered.rates, es.rates[keep])
    np.testing.assert_array_equal(filtered.index, es.index[keep])
    np.testing.assert_array_equal(filtered.loss, es.loss[keep])
    assert filtered.events["event_id"].tolist() == (
        es.events.loc[keep, "event_id"].tolist()
    )

    (record,) = filtered.metadata.filters
    assert record.column == "index"
    assert record.threshold == threshold
    assert record.n_rows_before == es.n_rows
    assert record.n_rows_kept == filtered.n_rows
    assert record.n_rows_dropped == int(drop.sum())
    assert record.rate_dropped == pytest.approx(es.rates[drop].sum())
    assert record.expected_loss_dropped == pytest.approx(
        float((es.rates[:, None] * es.loss)[drop].sum())
    )
    assert record.max_index_dropped == pytest.approx(es.index[drop].max())
    assert record.max_index_dropped is not None
    assert record.max_index_dropped < threshold
    assert record.max_loss_dropped == pytest.approx(es.loss[drop].max())
    # Kept + dropped rate mass is the original mass.
    assert filtered.rates.sum() + record.rate_dropped == pytest.approx(es.rates.sum())


def test_filter_threshold_on_loss_and_chaining(es: EventSet) -> None:
    once = es.filter_threshold(1.0, column="loss")
    assert (once.loss >= 1.0).any(axis=1).all()
    twice = once.filter_threshold(60.0)
    assert len(twice.metadata.filters) == 2
    assert [f.column for f in twice.metadata.filters] == ["loss", "index"]
    assert twice.metadata.filters[0] == once.metadata.filters[0]
    assert es.metadata.filters == ()


def test_filter_threshold_dropping_nothing(es: EventSet) -> None:
    filtered = es.filter_threshold(-1.0)
    assert filtered.n_rows == es.n_rows
    (record,) = filtered.metadata.filters
    assert record.n_rows_dropped == 0
    assert record.rate_dropped == 0.0
    assert record.expected_loss_dropped == 0.0
    assert record.max_index_dropped is None
    assert record.max_loss_dropped is None


def test_filter_threshold_dropping_everything(es: EventSet) -> None:
    filtered = es.filter_threshold(1e9)
    assert filtered.n_rows == 0
    assert filtered.metadata.filters[0].rate_dropped == pytest.approx(es.rates.sum())


@pytest.mark.parametrize("threshold", [np.nan, np.inf])
def test_filter_threshold_rejects_non_finite(es: EventSet, threshold: float) -> None:
    with pytest.raises(ValueError, match="finite"):
        es.filter_threshold(threshold)


def test_filter_threshold_rejects_unknown_column(es: EventSet) -> None:
    with pytest.raises(ValueError, match="column"):
        es.filter_threshold(1.0, column="rate")  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Validation: one test group per error class
# --------------------------------------------------------------------------


def test_error_hierarchy() -> None:
    for cls in (
        SchemaError,
        MissingColumnsError,
        DuplicateKeyError,
        NonFiniteValueError,
        InconsistentKeysError,
        OutOfRangeError,
    ):
        assert issubclass(cls, EventSetError)
    assert issubclass(EventSetError, ValueError)
    assert issubclass(NegativeLossError, OutOfRangeError)
    assert issubclass(NonPositiveRateError, OutOfRangeError)


# MissingColumnsError --------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("events", "event_id"),
        ("events", "year"),
        ("events", "rate"),
        ("events", "draw_id"),
        ("events", "scenario_id"),
        ("locations", "location_id"),
        ("locations", "lat"),
        ("locations", "lon"),
        ("locations", "value"),
        ("locations", "name"),
        ("values", "event_id"),
        ("values", "draw_id"),
        ("values", "location_id"),
        ("values", "index"),
        ("values", "loss"),
    ],
)
def test_missing_columns(es: EventSet, table: str, column: str) -> None:
    kwargs = parts(es)
    kwargs[table] = kwargs[table].drop(columns=column)
    with pytest.raises(MissingColumnsError) as info:
        EventSet.from_long(**kwargs)
    assert info.value.table == table
    assert info.value.missing == (column,)


def test_missing_columns_on_read(es: EventSet, tmp_path: Path) -> None:
    es.to_parquet(tmp_path)
    table = pq.read_table(tmp_path / EVENTS_FILE).drop_columns(["rate"])
    pq.write_table(table, tmp_path / EVENTS_FILE)
    with pytest.raises(MissingColumnsError, match="rate"):
        EventSet.from_parquet(tmp_path)


# DuplicateKeyError ----------------------------------------------------------


def test_duplicate_event_keys(es: EventSet) -> None:
    events = es.events.copy()
    events.loc[1, "draw_id"] = 0  # (ev0, 0) twice
    with pytest.raises(DuplicateKeyError, match=r"\(event_id, draw_id\)") as info:
        EventSet(events, es.locations, es.index, es.loss, es.metadata)
    assert info.value.table == "events"


def test_duplicate_location_ids(es: EventSet) -> None:
    locations = es.locations.copy()
    locations.loc[3, "location_id"] = "loc0"
    with pytest.raises(DuplicateKeyError, match="location_id") as info:
        EventSet(es.events, locations, es.index, es.loss, es.metadata)
    assert info.value.table == "locations"


def test_duplicate_value_keys(es: EventSet) -> None:
    kwargs = parts(es)
    values = kwargs["values"]
    kwargs["values"] = pd.concat([values, values.iloc[[0]]], ignore_index=True)
    with pytest.raises(DuplicateKeyError) as info:
        EventSet.from_long(**kwargs)
    assert info.value.table == "values"


def test_same_event_id_with_distinct_draws_is_allowed(es: EventSet) -> None:
    assert es.events["event_id"].duplicated().any()


# NonFiniteValueError --------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "column"),
    [
        ("events", "event_id"),
        ("events", "year"),
        ("events", "rate"),
        ("events", "draw_id"),
        ("locations", "lat"),
        ("locations", "name"),
        ("values", "index"),
        ("values", "loss"),
        ("values", "location_id"),
    ],
)
def test_nulls_and_nans_in_tables(es: EventSet, table: str, column: str) -> None:
    kwargs = parts(es)
    frame = kwargs[table].astype({column: object})
    frame.loc[0, column] = None
    kwargs[table] = frame
    with pytest.raises(NonFiniteValueError, match=column) as info:
        EventSet.from_long(**kwargs)
    assert info.value.table == table


@pytest.mark.parametrize("bad", [np.nan, np.inf, -np.inf])
def test_non_finite_floats_in_values(es: EventSet, bad: float) -> None:
    kwargs = parts(es)
    kwargs["values"].loc[3, "index"] = bad
    with pytest.raises(NonFiniteValueError, match="index"):
        EventSet.from_long(**kwargs)


def test_infinite_rate(es: EventSet) -> None:
    events = es.events.copy()
    events.loc[0, "rate"] = np.inf
    with pytest.raises(NonFiniteValueError, match="infinite"):
        EventSet(events, es.locations, es.index, es.loss, es.metadata)


@pytest.mark.parametrize("matrix", ["index", "loss"])
@pytest.mark.parametrize("bad", [np.nan, np.inf])
def test_non_finite_matrices(es: EventSet, matrix: str, bad: float) -> None:
    arrays = {"index": es.index.copy(), "loss": es.loss.copy()}
    arrays[matrix][2, 1] = bad
    with pytest.raises(NonFiniteValueError, match=matrix) as info:
        EventSet(es.events, es.locations, metadata=es.metadata, **arrays)
    assert info.value.table == "matrices"


def test_nan_on_read(es: EventSet, tmp_path: Path) -> None:
    es.to_parquet(tmp_path)
    table = pq.read_table(tmp_path / VALUES_FILE)
    loss = table.column("loss").to_numpy().copy()
    loss[0] = np.nan
    table = table.set_column(table.schema.get_field_index("loss"), "loss", [loss])
    pq.write_table(table, tmp_path / VALUES_FILE)
    with pytest.raises(NonFiniteValueError, match="loss"):
        EventSet.from_parquet(tmp_path)


# NegativeLossError ----------------------------------------------------------


def test_negative_loss_in_matrix(es: EventSet) -> None:
    loss = es.loss.copy()
    loss[0, 0] = -1.0
    with pytest.raises(NegativeLossError, match="negative") as info:
        EventSet(es.events, es.locations, es.index, loss, es.metadata)
    assert info.value.table == "matrices"


def test_negative_loss_in_values(es: EventSet) -> None:
    kwargs = parts(es)
    kwargs["values"].loc[5, "loss"] = -0.5
    with pytest.raises(NegativeLossError) as info:
        EventSet.from_long(**kwargs)
    assert info.value.table == "values"


def test_negative_index_is_allowed(es: EventSet) -> None:
    index = es.index - 100.0
    EventSet(es.events, es.locations, index, es.loss, es.metadata)


# NonPositiveRateError -------------------------------------------------------


@pytest.mark.parametrize("rate", [0.0, -1e-3])
def test_non_positive_rate(es: EventSet, rate: float) -> None:
    events = es.events.copy()
    events.loc[2, "rate"] = rate
    with pytest.raises(NonPositiveRateError, match="<= 0") as info:
        EventSet(events, es.locations, es.index, es.loss, es.metadata)
    assert info.value.table == "events"


# OutOfRangeError (other than loss and rate) --------------------------------


@pytest.mark.parametrize(
    ("table", "column", "bad"),
    [
        ("events", "draw_id", -1),
        ("locations", "lat", 90.5),
        ("locations", "lat", -91.0),
        ("locations", "lon", 180.5),
        ("locations", "lon", -181.0),
        ("locations", "value", -1.0),
    ],
)
def test_out_of_range(es: EventSet, table: str, column: str, bad: float) -> None:
    kwargs = parts(es)
    kwargs[table].loc[0, column] = bad
    with pytest.raises(OutOfRangeError, match=column):
        EventSet.from_long(**kwargs)


@pytest.mark.parametrize("n_years", [0, -5])
def test_non_positive_n_years(n_years: int) -> None:
    with pytest.raises(OutOfRangeError, match="n_years"):
        make_metadata(n_years=n_years)


# InconsistentKeysError ------------------------------------------------------


def test_values_refer_to_unknown_event(es: EventSet) -> None:
    kwargs = parts(es)
    kwargs["values"].loc[0, "event_id"] = "ghost"
    with pytest.raises(InconsistentKeysError, match="ghost"):
        EventSet.from_long(**kwargs)


def test_values_refer_to_unknown_draw(es: EventSet) -> None:
    kwargs = parts(es)
    kwargs["values"].loc[0, "draw_id"] = 9
    with pytest.raises(InconsistentKeysError, match="not in events"):
        EventSet.from_long(**kwargs)


def test_values_refer_to_unknown_location(es: EventSet) -> None:
    kwargs = parts(es)
    kwargs["values"].loc[0, "location_id"] = "nowhere"
    with pytest.raises(InconsistentKeysError, match="nowhere"):
        EventSet.from_long(**kwargs)


def test_values_miss_pairs(es: EventSet) -> None:
    kwargs = parts(es)
    kwargs["values"] = kwargs["values"].drop(index=[5, 6]).reset_index(drop=True)
    with pytest.raises(InconsistentKeysError, match="2 are missing") as info:
        EventSet.from_long(**kwargs)
    # The first missing pair is row 1 (ev0, draw 1), location 1.
    assert "event_id='ev0', draw_id=1, location_id='loc1'" in str(info.value)


@pytest.mark.parametrize("shape", [(5, 4), (6, 3)])
def test_matrix_shape_mismatch(es: EventSet, shape: tuple[int, int]) -> None:
    with pytest.raises(InconsistentKeysError, match="shape"):
        EventSet(es.events, es.locations, np.zeros(shape), np.zeros(shape), es.metadata)


# SchemaError ----------------------------------------------------------------


def test_matrix_must_be_two_dimensional(es: EventSet) -> None:
    with pytest.raises(SchemaError, match="two-dimensional"):
        EventSet(es.events, es.locations, np.zeros(24), es.loss, es.metadata)


def test_matrix_must_be_numeric(es: EventSet) -> None:
    with pytest.raises(SchemaError, match="numeric"):
        EventSet(es.events, es.locations, es.index.astype(str), es.loss, es.metadata)
    with pytest.raises(SchemaError, match="numeric"):
        EventSet(
            es.events,
            es.locations,
            es.index > 1,  # type: ignore[arg-type]
            es.loss,
            es.metadata,
        )


def test_unexpected_event_column(es: EventSet) -> None:
    events = es.events.assign(track_id="x")
    with pytest.raises(SchemaError, match="unexpected columns: track_id"):
        EventSet(events, es.locations, es.index, es.loss, es.metadata)


def test_unexpected_values_column(es: EventSet) -> None:
    kwargs = parts(es)
    kwargs["values"] = kwargs["values"].assign(extra=1.0)
    with pytest.raises(SchemaError, match="unexpected columns: extra"):
        EventSet.from_long(**kwargs)


@pytest.mark.parametrize(
    ("table", "column", "values"),
    [
        ("events", "year", [1.5, 2.0, 3.0, 4.0, 5.0, 6.0]),
        ("events", "rate", ["a", "b", "c", "d", "e", "f"]),
        ("events", "rate", [True] * 6),
        ("events", "event_id", [1, 2, 3, 4, 5, 6]),
        ("locations", "location_id", [1, 2, 3, 4]),
    ],
)
def test_wrong_column_types(
    es: EventSet, table: str, column: str, values: list[Any]
) -> None:
    kwargs = parts(es)
    kwargs[table] = kwargs[table].assign(**{column: values})
    with pytest.raises(SchemaError, match=column):
        EventSet.from_long(**kwargs)


def test_tables_must_be_dataframes(es: EventSet) -> None:
    with pytest.raises(SchemaError, match="DataFrame"):
        EventSet(
            es.events.to_dict(),  # type: ignore[arg-type]
            es.locations,
            es.index,
            es.loss,
            es.metadata,
        )


def test_column_names_must_be_unique_strings(es: EventSet) -> None:
    locations = es.locations.copy()
    locations[0] = 1
    with pytest.raises(SchemaError, match="strings"):
        EventSet(es.events, locations, es.index, es.loss, es.metadata)
    events = pd.concat([es.events, es.events[["rate"]]], axis=1)
    with pytest.raises(SchemaError, match="unique"):
        EventSet(events, es.locations, es.index, es.loss, es.metadata)


def test_at_least_one_location(es: EventSet) -> None:
    with pytest.raises(SchemaError, match="at least one location"):
        EventSet(
            es.events,
            es.locations.iloc[0:0],
            np.zeros((6, 0)),
            np.zeros((6, 0)),
            es.metadata,
        )


def test_metadata_type_is_checked(es: EventSet) -> None:
    with pytest.raises(SchemaError, match="EventSetMetadata"):
        EventSet(
            es.events,
            es.locations,
            es.index,
            es.loss,
            es.metadata.to_dict(),  # type: ignore[arg-type]
        )


def test_missing_files(es: EventSet, tmp_path: Path) -> None:
    es.to_parquet(tmp_path)
    (tmp_path / VALUES_FILE).unlink()
    with pytest.raises(SchemaError, match=VALUES_FILE):
        EventSet.from_parquet(tmp_path)


def test_invalid_metadata_json(es: EventSet, tmp_path: Path) -> None:
    es.to_parquet(tmp_path)
    (tmp_path / METADATA_FILE).write_text("{not json", encoding="utf-8")
    with pytest.raises(SchemaError, match="invalid JSON"):
        EventSet.from_parquet(tmp_path)
    (tmp_path / METADATA_FILE).write_text("[]", encoding="utf-8")
    with pytest.raises(SchemaError, match="JSON object"):
        EventSet.from_parquet(tmp_path)


def _edit_metadata(path: Path, edit: Callable[[dict[str, Any]], object]) -> None:
    raw = json.loads((path / METADATA_FILE).read_text(encoding="utf-8"))
    edit(raw)
    (path / METADATA_FILE).write_text(json.dumps(raw), encoding="utf-8")


@pytest.mark.parametrize("version", [2, 0, "1", None])
def test_unsupported_schema_version_on_read(
    es: EventSet, tmp_path: Path, version: object
) -> None:
    es.to_parquet(tmp_path)
    _edit_metadata(tmp_path, lambda raw: raw.update(schema_version=version))
    with pytest.raises(SchemaError, match="schema_version"):
        EventSet.from_parquet(tmp_path)


def test_unsupported_schema_version_in_memory() -> None:
    with pytest.raises(SchemaError, match="schema_version"):
        make_metadata(schema_version=2)
    with pytest.raises(SchemaError, match="schema_version"):
        make_metadata(schema_version="1")


@pytest.mark.parametrize(
    ("edit", "match"),
    [
        (lambda raw: raw.pop("licence"), "lacks keys: licence"),
        (lambda raw: raw.update(colour="blue"), "unknown keys: colour"),
        (lambda raw: raw["hazard"].pop("release"), "hazard lacks keys"),
        (lambda raw: raw["loss"].update(scale=1), "loss has unknown keys"),
        (lambda raw: raw.update(hazard="IRIS"), "hazard must be a JSON object"),
        (lambda raw: raw.update(n_years=10.5), "n_years must be an int"),
        (lambda raw: raw.update(scenario=""), "scenario"),
        (lambda raw: raw.update(licence=3), "licence"),
        (lambda raw: raw["provenance"].update(created_at=5), "ISO 8601"),
        (
            lambda raw: raw["provenance"].update(created_at="yesterday"),
            "not ISO 8601",
        ),
        (
            lambda raw: raw["provenance"].update(created_at="2026-10-25T12:00:00"),
            "timezone-aware",
        ),
        (
            lambda raw: raw["provenance"].update(source_checksums=["a"]),
            "mapping",
        ),
        (
            lambda raw: raw["provenance"].update(source_checksums={"a": ""}),
            "source_checksums",
        ),
        (lambda raw: raw.update(filters={}), "filters must be a list"),
        (lambda raw: raw.update(filters=[{"column": "index"}]), "filters"),
    ],
)
def test_malformed_metadata_on_read(
    es: EventSet,
    tmp_path: Path,
    edit: Callable[[dict[str, Any]], object],
    match: str,
) -> None:
    es.to_parquet(tmp_path)
    _edit_metadata(tmp_path, edit)
    with pytest.raises(SchemaError, match=match):
        EventSet.from_parquet(tmp_path)


def test_metadata_without_optional_keys_reads(tmp_path: Path) -> None:
    es = make_eventset()
    es.to_parquet(tmp_path)

    def strip(raw: dict[str, Any]) -> None:
        raw.pop("filters")
        raw["loss"].pop("currency")
        raw["provenance"].pop("source_checksums")

    _edit_metadata(tmp_path, strip)
    back = EventSet.from_parquet(tmp_path)
    assert back.metadata.loss.currency is None
    assert back.metadata.provenance.source_checksums == {}
    assert back.metadata.filters == ()


def test_metadata_field_types_in_memory() -> None:
    with pytest.raises(SchemaError, match="hazard must be a HazardSource"):
        make_metadata(hazard="IRIS")
    with pytest.raises(SchemaError, match="filters"):
        make_metadata(filters=("x",))
    with pytest.raises(SchemaError, match="created_at must be a datetime"):
        Provenance("p", "1", "2026-10-25")  # type: ignore[arg-type]
    with pytest.raises(SchemaError, match="currency"):
        LossDefinition(unit="USD", currency="")
    with pytest.raises(SchemaError, match=r"index\.unit"):
        IndexDefinition(definition="wind", unit=" ")


def _record(**overrides: object) -> ThresholdFilterRecord:
    fields: dict[str, Any] = {
        "column": "index",
        "threshold": 33.0,
        "n_rows_before": 10,
        "n_rows_kept": 4,
        "rate_dropped": 0.06,
        "expected_loss_dropped": 12.5,
        "max_index_dropped": 32.9,
        "max_loss_dropped": 1000.0,
    }
    fields.update(overrides)
    return ThresholdFilterRecord(**fields)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"column": "rate"}, "column"),
        ({"n_rows_before": -1}, "n_rows_before"),
        ({"n_rows_kept": 1.0}, "n_rows_kept"),
        ({"n_rows_kept": 11}, "exceeds"),
        ({"threshold": float("nan")}, "threshold must be finite"),
        ({"rate_dropped": "0.1"}, "rate_dropped must be a number"),
        ({"max_index_dropped": True}, "max_index_dropped must be a number"),
    ],
)
def test_threshold_filter_record_validation(
    overrides: dict[str, Any], match: str
) -> None:
    with pytest.raises(SchemaError, match=match):
        _record(**overrides)


def test_threshold_filter_record_coerces_ints() -> None:
    record = _record(threshold=33, max_loss_dropped=None)
    assert isinstance(record.threshold, float)
    assert record.max_loss_dropped is None
    assert record.n_rows_dropped == 6
