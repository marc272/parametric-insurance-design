"""Tests for :meth:`EventSet.content_hash` (MAR-82, SPEC §4.3).

The golden hashes below are asserted in every CI job, including the
lowest-direct (pandas 2.1, pyarrow 15, numpy 1.26) and highest resolutions, so
a hash that depended on a library version would fail in one of them.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design import records
from parametric_insurance_design.eventset import (
    METADATA_FILE,
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
    SchemaError,
    ThresholdFilterRecord,
    TransformRecord,
)

# Golden hashes of canonical serialisation v1. Change them only together with
# the version in the domain tag (see EventSet.content_hash).
GOLDEN_SMALL = "sha256:3ef7f5cdd44a572a8b1f875481fd30e0a95617f9184c91adb4aa049f2b4c876f"
GOLDEN_SMALL_FILTERED = (
    "sha256:d96c4b80e1d31ebdee89cc51e59a20a2161a12ba58861e0f0dfcb123c46716d0"
)
GOLDEN_PARITY_FIXTURE = (
    "sha256:404b0c3a3aefa38965ad3ace2747d308685a67e3b218cb835d45a9ab375294df"
)
# MAR-88: the small EventSet with one transform record (_TRANSFORM below).
GOLDEN_SMALL_TRANSFORMED = (
    "sha256:31b2a85c3deae43ae8dc6c36026dcdece2f9f00f8271493d32b1aacee742796b"
)

PARITY_EVENTSET = (
    Path(__file__).resolve().parents[3]
    / "parity"
    / "tests"
    / "data"
    / "thesis_eventset"
)
HASH_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


# --------------------------------------------------------------------------
# A small deterministic EventSet (no random numbers, exact binary values)
# --------------------------------------------------------------------------


def golden_metadata(**overrides: object) -> EventSetMetadata:
    fields: dict[str, Any] = {
        "hazard": HazardSource(name="IRIS", release="v1.0"),
        "index": IndexDefinition(definition="max wind at the asset", unit="m/s"),
        "loss": LossDefinition(unit="USD", currency="USD"),
        "n_years": 10,
        "scenario": "historical climate",
        "provenance": Provenance(
            producer="tests",
            producer_version="0.0.1",
            created_at=datetime(2026, 10, 25, 12, 30, tzinfo=UTC),
            source_checksums={"tracks.nc": "sha256:abc123", "a.csv": "sha256:def"},
        ),
        "licence": "CC-BY-4.0",
    }
    fields.update(overrides)
    return EventSetMetadata(**fields)


def golden_eventset() -> EventSet:
    """Three events with two draws each at three locations."""
    events = pd.DataFrame(
        {
            "event_id": ["NA_0_1", "NA_0_1", "NA_4_2", "NA_4_2", "NA_9_3", "NA_9_3"],
            "year": [0, 0, 4, 4, 9, 9],
            "rate": [0.05] * 6,
            "draw_id": [0, 1, 0, 1, 0, 1],
            "scenario_id": ["hist"] * 6,
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": ["A1", "A2", "Zürich"],
            "lat": [25.75, 25.5, 47.375],
            "lon": [-80.25, -80.125, 8.5],
            "value": [1e6, 2.5e6, 0.0],
            "name": ["Asset 1", "Asset 2", "Asset ü"],
            "impf_TC": np.array([1, 1, 2], dtype=np.int64),
            "country": ["US", None, "CH"],
            "elevation": [2.5, np.nan, 408.0],
            "insured": [True, False, True],
        }
    )
    grid = np.arange(18, dtype=np.float64).reshape(6, 3)
    return EventSet(
        events=events,
        locations=locations,
        index=grid * 2.5 + 10.0,
        loss=(grid % 4) * 1000.0,
        metadata=golden_metadata(),
    )


@pytest.fixture
def es() -> EventSet:
    return golden_eventset()


def rebuild(es: EventSet, **changes: object) -> EventSet:
    """Return a copy of ``es`` with some fields replaced (and validated)."""
    fields: dict[str, Any] = {
        "events": es.events.copy(),
        "locations": es.locations.copy(),
        "index": es.index.copy(),
        "loss": es.loss.copy(),
        "metadata": es.metadata,
    }
    fields.update(changes)
    return EventSet(**fields)


# --------------------------------------------------------------------------
# Format and golden values
# --------------------------------------------------------------------------


def test_hash_format_fits_runs_eventset_checksum(es: EventSet) -> None:
    value = es.content_hash()
    assert HASH_PATTERN.match(value)
    column = records.RUNS.column("eventset_checksum")
    assert column.kind == "str"
    assert isinstance(value, str)


def test_hash_is_deterministic(es: EventSet) -> None:
    assert es.content_hash() == es.content_hash() == golden_eventset().content_hash()


def test_golden_hash_small(es: EventSet) -> None:
    assert es.content_hash() == GOLDEN_SMALL


def test_golden_hash_small_after_filter(es: EventSet) -> None:
    filtered = es.filter_threshold(30.0)
    assert filtered.n_rows < es.n_rows
    assert filtered.content_hash() == GOLDEN_SMALL_FILTERED


@pytest.mark.skipif(
    not PARITY_EVENTSET.is_dir(),
    reason="parity fixture not present (core installed outside the repository)",
)
def test_golden_hash_parity_fixture(tmp_path: Path) -> None:
    # The committed fixture predates MAR-88: its metadata.json has no
    # "transforms" key. Re-writing it adds "transforms": [], and the hash of
    # both is the MAR-82 golden value.
    raw = json.loads((PARITY_EVENTSET / METADATA_FILE).read_text(encoding="utf-8"))
    assert "transforms" not in raw
    es = EventSet.from_parquet(PARITY_EVENTSET)
    assert es.metadata.transforms == ()
    assert es.content_hash() == GOLDEN_PARITY_FIXTURE
    back = EventSet.from_parquet(es.to_parquet(tmp_path / "es"))
    written = json.loads((tmp_path / "es" / METADATA_FILE).read_text(encoding="utf-8"))
    assert written["transforms"] == []
    assert back.content_hash() == GOLDEN_PARITY_FIXTURE


def test_golden_hash_small_with_transforms(es: EventSet, tmp_path: Path) -> None:
    transformed = rebuild(
        es, metadata=dataclasses.replace(es.metadata, transforms=(_TRANSFORM,))
    )
    assert transformed.content_hash() == GOLDEN_SMALL_TRANSFORMED
    back = EventSet.from_parquet(transformed.to_parquet(tmp_path / "es"))
    assert back.content_hash() == GOLDEN_SMALL_TRANSFORMED


def test_empty_transforms_hash_as_before_mar88(es: EventSet) -> None:
    # An empty "transforms" is left out of the canonical metadata, so every
    # EventSet without transforms keeps its MAR-82 hash.
    assert es.metadata.transforms == ()
    assert es.metadata.to_dict()["transforms"] == []
    assert es.content_hash() == GOLDEN_SMALL


# --------------------------------------------------------------------------
# Invariance: what must not change the hash
# --------------------------------------------------------------------------


def test_hash_equal_across_parquet_round_trip(es: EventSet, tmp_path: Path) -> None:
    back = EventSet.from_parquet(es.to_parquet(tmp_path / "es"))
    assert back.content_hash() == es.content_hash() == GOLDEN_SMALL


def test_hash_equal_across_round_trip_after_filter(
    es: EventSet, tmp_path: Path
) -> None:
    filtered = es.filter_threshold(30.0)
    back = EventSet.from_parquet(filtered.to_parquet(tmp_path / "es"))
    assert back.content_hash() == filtered.content_hash()


def test_hash_equal_across_long_format_and_shuffled_values(es: EventSet) -> None:
    values = es.to_long().sample(frac=1.0, random_state=np.random.RandomState(3))
    back = EventSet.from_long(es.events, es.locations, values, es.metadata)
    assert back.content_hash() == es.content_hash()


def test_hash_ignores_storage_dtypes_and_layout(es: EventSet) -> None:
    events = es.events.astype({"event_id": "string", "year": np.int32})
    events.index = pd.Index(range(10, 10 + len(events)))
    locations = es.locations.astype({"name": "string", "impf_TC": np.int16})
    other = rebuild(
        es,
        events=events,
        locations=locations,
        index=np.asfortranarray(es.index),
        loss=es.loss.astype(np.float32).astype(np.float64),
    )
    assert other.content_hash() == es.content_hash()


def test_hash_ignores_created_at(es: EventSet) -> None:
    provenance = dataclasses.replace(
        es.metadata.provenance,
        created_at=datetime(2030, 1, 1, tzinfo=timezone(timedelta(hours=-5))),
    )
    other = rebuild(
        es, metadata=dataclasses.replace(es.metadata, provenance=provenance)
    )
    assert other.content_hash() == es.content_hash()


def test_hash_ignores_free_column_order(es: EventSet) -> None:
    locations = es.locations[
        [
            *("location_id", "lat", "lon", "value", "name"),
            *("insured", "country", "elevation", "impf_TC"),
        ]
    ]
    assert rebuild(es, locations=locations).content_hash() == es.content_hash()


def test_hash_treats_negative_zero_as_zero(es: EventSet) -> None:
    index = es.index.copy()
    index[0, 0] = 0.0
    zero = rebuild(es, index=index)
    index[0, 0] = -0.0
    negative = rebuild(es, index=index)
    assert zero.equals(negative)
    assert zero.content_hash() == negative.content_hash()


def test_hash_null_representations_agree(es: EventSet) -> None:
    locations = es.locations.copy()
    locations["country"] = pd.array(["US", pd.NA, "CH"], dtype="string")
    assert rebuild(es, locations=locations).content_hash() == es.content_hash()
    locations["country"] = np.array(["US", np.nan, "CH"], dtype=object)
    assert rebuild(es, locations=locations).content_hash() == es.content_hash()


# --------------------------------------------------------------------------
# Sensitivity: one test per field group
# --------------------------------------------------------------------------


def _set(frame: pd.DataFrame, column: str, row: int, value: object) -> pd.DataFrame:
    frame = frame.copy()
    frame.loc[row, column] = value
    return frame


def _matrix(es: EventSet, name: str, value: float) -> np.ndarray:
    matrix = getattr(es, name).copy()
    matrix[2, 1] = value
    return matrix


Change = Callable[[EventSet], EventSet]

VALUE_CHANGES: dict[str, Change] = {
    "index cell": lambda es: rebuild(es, index=_matrix(es, "index", 33.0)),
    "index ulp": lambda es: rebuild(
        es, index=_matrix(es, "index", float(np.nextafter(es.index[2, 1], 99.0)))
    ),
    "loss cell": lambda es: rebuild(es, loss=_matrix(es, "loss", 1.0)),
    "index and loss swapped": lambda es: rebuild(es, index=es.loss, loss=es.index),
}

EVENT_CHANGES: dict[str, Change] = {
    "event_id": lambda es: rebuild(es, events=_set(es.events, "event_id", 1, "X")),
    "year": lambda es: rebuild(es, events=_set(es.events, "year", 1, 5)),
    "rate": lambda es: rebuild(es, events=_set(es.events, "rate", 1, 0.0500001)),
    "draw_id": lambda es: rebuild(es, events=_set(es.events, "draw_id", 1, 7)),
    "scenario_id": lambda es: rebuild(
        es, events=_set(es.events, "scenario_id", 1, "ssp")
    ),
    "row order": lambda es: rebuild(
        es,
        events=es.events.iloc[::-1],
        index=es.index[::-1],
        loss=es.loss[::-1],
    ),
    "row dropped": lambda es: rebuild(
        es, events=es.events.iloc[:-1], index=es.index[:-1], loss=es.loss[:-1]
    ),
}

LOCATION_CHANGES: dict[str, Change] = {
    "location_id": lambda es: rebuild(
        es, locations=_set(es.locations, "location_id", 0, "B1")
    ),
    "lat": lambda es: rebuild(es, locations=_set(es.locations, "lat", 0, 25.5)),
    "lon": lambda es: rebuild(es, locations=_set(es.locations, "lon", 0, -80.0)),
    "value": lambda es: rebuild(es, locations=_set(es.locations, "value", 0, 1.0)),
    "name": lambda es: rebuild(es, locations=_set(es.locations, "name", 0, "A")),
    "free int value": lambda es: rebuild(
        es, locations=_set(es.locations, "impf_TC", 0, 3)
    ),
    "free str value": lambda es: rebuild(
        es, locations=_set(es.locations, "country", 0, "MX")
    ),
    "free str null moved": lambda es: rebuild(
        es,
        locations=_set(_set(es.locations, "country", 1, "US"), "country", 0, None),
    ),
    "free float value": lambda es: rebuild(
        es, locations=_set(es.locations, "elevation", 0, 3.5)
    ),
    "free bool value": lambda es: rebuild(
        es, locations=_set(es.locations, "insured", 1, True)
    ),
    "free column renamed": lambda es: rebuild(
        es, locations=es.locations.rename(columns={"country": "nation"})
    ),
    "free column added": lambda es: rebuild(
        es, locations=es.locations.assign(region=["a", "b", "c"])
    ),
    "free column dropped": lambda es: rebuild(
        es, locations=es.locations.drop(columns=["insured"])
    ),
    "free column kind": lambda es: rebuild(
        es, locations=es.locations.astype({"impf_TC": np.float64})
    ),
    "location order": lambda es: rebuild(
        es,
        locations=es.locations.iloc[::-1],
        index=es.index[:, ::-1],
        loss=es.loss[:, ::-1],
    ),
}


def _metadata(**overrides: object) -> Change:
    return lambda es: rebuild(
        es, metadata=dataclasses.replace(es.metadata, **overrides)
    )


def _provenance(**overrides: object) -> Change:
    return lambda es: rebuild(
        es,
        metadata=dataclasses.replace(
            es.metadata,
            provenance=dataclasses.replace(es.metadata.provenance, **overrides),
        ),
    )


_FILTER = ThresholdFilterRecord(
    column="index",
    threshold=1.0,
    n_rows_before=6,
    n_rows_kept=6,
    rate_dropped=0.0,
    expected_loss_dropped=0.0,
    max_index_dropped=None,
    max_loss_dropped=None,
)

_TRANSFORM = TransformRecord(
    name="noise",
    function="parametric_insurance_design.noise.add_noise",
    version="0.1.0.dev0",
    n_filters_before=0,
    parameters={
        "kind": "heteroscedastic",
        "level": 0.3,
        "n_copies": 2,
        "bounds": [20.0, 70.0],
        "location_ids": ["A1", "A2", "Zürich"],
    },
)


def _transforms(*records: TransformRecord) -> Change:
    return _metadata(transforms=records)


METADATA_CHANGES: dict[str, Change] = {
    "hazard.name": _metadata(hazard=HazardSource(name="STORM", release="v1.0")),
    "hazard.release": _metadata(hazard=HazardSource(name="IRIS", release="v1.1")),
    "index.definition": _metadata(index=IndexDefinition(definition="gust", unit="m/s")),
    "index.unit": _metadata(
        index=IndexDefinition(definition="max wind at the asset", unit="kn")
    ),
    "loss.unit": _metadata(loss=LossDefinition(unit="EUR", currency="USD")),
    "loss.currency": _metadata(loss=LossDefinition(unit="USD")),
    "n_years": _metadata(n_years=11),
    "scenario": _metadata(scenario="ssp5-8.5"),
    "licence": _metadata(licence="CC0-1.0"),
    "filters": _metadata(filters=(_FILTER,)),
    "transforms": _transforms(_TRANSFORM),
    "provenance.producer": _provenance(producer="other"),
    "provenance.producer_version": _provenance(producer_version="0.0.2"),
    "provenance.source_checksums value": _provenance(
        source_checksums={"tracks.nc": "sha256:abc124", "a.csv": "sha256:def"}
    ),
    "provenance.source_checksums key": _provenance(
        source_checksums={"tracks2.nc": "sha256:abc123", "a.csv": "sha256:def"}
    ),
}


def _assert_changes(es: EventSet, change: Change) -> None:
    before = es.content_hash()
    after = change(es).content_hash()
    assert HASH_PATTERN.match(after)
    assert after != before


@pytest.mark.parametrize("change", VALUE_CHANGES.values(), ids=VALUE_CHANGES.keys())
def test_value_change_changes_hash(es: EventSet, change: Change) -> None:
    _assert_changes(es, change)


@pytest.mark.parametrize("change", EVENT_CHANGES.values(), ids=EVENT_CHANGES.keys())
def test_event_change_changes_hash(es: EventSet, change: Change) -> None:
    _assert_changes(es, change)


@pytest.mark.parametrize(
    "change", LOCATION_CHANGES.values(), ids=LOCATION_CHANGES.keys()
)
def test_location_change_changes_hash(es: EventSet, change: Change) -> None:
    _assert_changes(es, change)


@pytest.mark.parametrize(
    "change", METADATA_CHANGES.values(), ids=METADATA_CHANGES.keys()
)
def test_metadata_change_changes_hash(es: EventSet, change: Change) -> None:
    _assert_changes(es, change)


TRANSFORM_CHANGES: dict[str, tuple[TransformRecord, ...]] = {
    "name": (dataclasses.replace(_TRANSFORM, name="vulnerability_draws"),),
    "function": (dataclasses.replace(_TRANSFORM, function="pkg.other"),),
    "version": (dataclasses.replace(_TRANSFORM, version="0.1.0"),),
    "parameter value": (
        dataclasses.replace(
            _TRANSFORM, parameters={**_TRANSFORM.parameters, "level": 0.31}
        ),
    ),
    "parameter added": (
        dataclasses.replace(
            _TRANSFORM, parameters={**_TRANSFORM.parameters, "extra": None}
        ),
    ),
    "location order": (
        dataclasses.replace(
            _TRANSFORM,
            parameters={
                **_TRANSFORM.parameters,
                "location_ids": ["A2", "A1", "Zürich"],
            },
        ),
    ),
    "second record": (_TRANSFORM, _TRANSFORM),
}


@pytest.mark.parametrize(
    "transforms", TRANSFORM_CHANGES.values(), ids=TRANSFORM_CHANGES.keys()
)
def test_transform_change_changes_hash(
    es: EventSet, transforms: tuple[TransformRecord, ...]
) -> None:
    _assert_changes(_transforms(_TRANSFORM)(es), _transforms(*transforms))


def test_transform_position_among_filters_changes_hash(es: EventSet) -> None:
    filtered = es.filter_threshold(0.0)  # keeps every row, records one filter
    before = dataclasses.replace(_TRANSFORM, n_filters_before=0)
    after = dataclasses.replace(_TRANSFORM, n_filters_before=1)
    assert (
        _transforms(before)(filtered).content_hash()
        != _transforms(after)(filtered).content_hash()
    )


def test_every_metadata_field_has_a_sensitivity_test() -> None:
    # A new metadata field must get a test above, or be excluded on purpose.
    excluded = {"provenance.created_at", "schema_version"}  # schema_version: only 1
    covered = {name.split(" ")[0] for name in METADATA_CHANGES} | excluded
    raw = golden_metadata().to_dict()
    fields = set()
    for key, value in raw.items():
        if isinstance(value, dict) and key != "filters":
            fields |= {f"{key}.{sub}" for sub in value}
        else:
            fields.add(key)
    assert fields == covered


def test_framing_separates_adjacent_strings(es: EventSet) -> None:
    # Moving a character between two adjacent strings keeps their
    # concatenation but must change the hash.
    a = rebuild(es, locations=_set(_set(es.locations, "name", 0, "ab"), "name", 1, "c"))
    b = rebuild(es, locations=_set(_set(es.locations, "name", 0, "a"), "name", 1, "bc"))
    assert a.content_hash() != b.content_hash()


# --------------------------------------------------------------------------
# Free locations columns: supported kinds and typed errors
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "column",
    [
        pd.array([1, None, 3], dtype="Int64"),
        pd.array([True, None, False], dtype="boolean"),
        np.array([1, 2, 3], dtype=np.uint32),
        np.array([1, 2, 3], dtype=object),
        np.array([True, False, True], dtype=object),
        np.array([0.5, 1.5, 2.0], dtype=object),
        [None, None, None],
    ],
    ids=[
        *("Int64", "boolean", "uint32"),
        *("object int", "object bool", "object float", "all null"),
    ],
)
def test_supported_free_column_kinds(es: EventSet, column: object) -> None:
    other = rebuild(es, locations=es.locations.assign(extra=column))
    assert HASH_PATTERN.match(other.content_hash())
    assert other.content_hash() != es.content_hash()


def test_nullable_int_and_object_int_hash_alike(es: EventSet) -> None:
    a = rebuild(
        es, locations=es.locations.assign(extra=pd.array([1, 2, 3], dtype="Int64"))
    )
    b = rebuild(es, locations=es.locations.assign(extra=np.array([1, 2, 3])))
    assert a.content_hash() == b.content_hash()


@pytest.mark.parametrize(
    ("column", "match"),
    [
        (pd.to_datetime(["2020-01-01", "2020-01-02", "2020-01-03"]), "datetime64"),
        (pd.Categorical(["a", "b", "a"]), "category"),
        (np.array(["a", 1, 2.5], dtype=object), "mixed"),
        (np.array([1, 2**70, 3], dtype=object), "int64 range"),
        (np.array([b"a", b"b", b"c"], dtype=object), "bytes"),
    ],
    ids=["datetime", "categorical", "mixed", "big int", "bytes"],
)
def test_unsupported_free_column_raises(
    es: EventSet, column: object, match: str
) -> None:
    other = rebuild(es, locations=es.locations.assign(extra=column))
    with pytest.raises(SchemaError, match=match) as info:
        other.content_hash()
    assert "'extra'" in str(info.value)
    assert info.value.table == "locations"
