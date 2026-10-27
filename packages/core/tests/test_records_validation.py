"""Value checks of ``TableSchema.validate`` on every column backing (MAR-130).

``validate`` decides a column's value types from its dtype, or from one
``infer_dtype`` pass over an object column, and falls back to checking value by
value only when that doesn't prove the column valid (ADR 0002 §10, amendment
MAR-130). These tests pin down that it accepts and rejects exactly what the
value-by-value check does:

* every rejection of ``test_records.py`` fires again on each backing a frame
  can have: object columns (``from_rows``, pandas 2 Parquet reads), the frame
  of a Parquet round trip, pandas ``string``/nullable dtypes and Arrow-backed
  dtypes;
* a valid frame validates to the same canonical table on each backing;
* the column check equals the reference check on hand-picked and random
  columns (hypothesis, derandomised).
"""

from __future__ import annotations

import decimal
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from parametric_insurance_design import records
from parametric_insurance_design.errors import RecordSchemaError
from parametric_insurance_design.records import (
    Column,
    ColumnKind,
    TableSchema,
    _holds_only,
    _is_kind,
)

PROPERTY_SETTINGS = settings(
    derandomize=True, database=None, deadline=None, print_blob=True
)

KINDS: tuple[ColumnKind, ...] = ("str", "int", "float", "bool")


def kpi_row(**overrides: object) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": "r1",
        "problem_id": "portfolio",
        "eval_split": "test",
        "fold": 0,
        "basis": "annual",
        "level": "location",
        "subject_id": "A1",
        "kpi": "cvar_uncovered",
        "beta": 0.99,
        "value": 1.5,
        "ci_low": None,
        "ci_high": None,
        "ci_level": None,
        "n_bootstrap": None,
    }
    row.update(overrides)
    return row


def _parquet(frame: pd.DataFrame, tmp_path: Path) -> pd.DataFrame:
    path = tmp_path / "frame.parquet"
    pq.write_table(pa.Table.from_pandas(frame, preserve_index=False), path)
    with pq.ParquetFile(path) as handle:
        return handle.read().to_pandas()


def _arrow(frame: pd.DataFrame, tmp_path: Path) -> pd.DataFrame:
    table = pa.Table.from_pandas(frame, preserve_index=False)
    return table.to_pandas(types_mapper=pd.ArrowDtype)


def _nullable(frame: pd.DataFrame, tmp_path: Path) -> pd.DataFrame:
    # pandas "string", Int64, Float64 and boolean dtypes.
    return frame.convert_dtypes()


def _object(frame: pd.DataFrame, tmp_path: Path) -> pd.DataFrame:
    return frame.astype(object)


BACKINGS: dict[str, Callable[[pd.DataFrame, Path], pd.DataFrame]] = {
    "as_built": lambda frame, tmp_path: frame,
    "object": _object,
    "parquet": _parquet,
    "nullable": _nullable,
    "arrow": _arrow,
}
"""Ways a frame with the same values reaches ``validate``."""


def _backed(rows: list[dict[str, Any]], backing: str, tmp_path: Path) -> pd.DataFrame:
    return BACKINGS[backing](pd.DataFrame.from_records(rows), tmp_path)


@pytest.mark.parametrize("backing", sorted(BACKINGS))
def test_valid_frames_validate_to_the_same_table_on_every_backing(
    backing: str, tmp_path: Path
) -> None:
    rows = [
        kpi_row(),
        kpi_row(kpi="correlation", beta=None, value=None, subject_id="A2"),
        kpi_row(fold=2, n_bootstrap=100, ci_low=1.0, ci_high=2.0, ci_level=0.9),
    ]
    expected = records.KPIS.from_rows(rows)
    got = records.KPIS.validate(_backed(rows, backing, tmp_path))
    pd.testing.assert_frame_equal(got, expected)
    assert got.dtypes.equals(expected.dtypes)


# Every value rejection of test_records.py, plus the null, NaN and type
# rejections a frame read from Parquet can still carry.
REJECTIONS: list[tuple[list[dict[str, Any]], str]] = [
    ([kpi_row(kpi="sharpe")], "has values \\['sharpe'\\] not in"),
    ([kpi_row(), kpi_row(basis="monthly", subject_id="A2")], "'monthly'\\] not in"),
    ([kpi_row(level="galaxy")], "not in"),
    ([kpi_row(eval_split="dev")], "not in"),
    ([kpi_row(run_id=None)], "'run_id' has 1 nulls"),
    ([kpi_row(), kpi_row(subject_id=None)], "'subject_id' has 1 nulls"),
    ([kpi_row(fold=None)], "'fold' has 1 nulls"),
    ([kpi_row(run_id=3)], "'run_id' must hold str values"),
    ([kpi_row(subject_id=b"A1")], "'subject_id' must hold str values"),
    ([kpi_row(fold=1.5)], "'fold' must hold int values"),
    ([kpi_row(fold="0")], "'fold' must hold int values"),
    ([kpi_row(value=float("inf"))], "'value' has infinite values"),
    ([kpi_row(), kpi_row(value=-np.inf, subject_id="A2")], "infinite values"),
    ([kpi_row(value=True)], "'value' must hold float values"),
    ([kpi_row(value="1.5")], "'value' must hold float values"),
    ([kpi_row(n_bootstrap=1.5)], "'n_bootstrap' must hold int values"),
    ([kpi_row(), kpi_row(value=2.0)], "1 rows repeat the key"),
]


@pytest.mark.parametrize("backing", sorted(BACKINGS))
@pytest.mark.parametrize(("rows", "match"), REJECTIONS)
def test_every_rejection_fires_on_every_backing(
    rows: list[dict[str, Any]], match: str, backing: str, tmp_path: Path
) -> None:
    with pytest.raises(RecordSchemaError, match=match):
        records.KPIS.from_rows(rows)
    try:
        frame = _backed(rows, backing, tmp_path)
    except (pa.ArrowException, TypeError, ValueError):
        pytest.skip(f"these values have no {backing} backing")
    with pytest.raises(RecordSchemaError, match=match):
        records.KPIS.validate(frame)


def test_nan_in_a_non_nullable_float_column_is_a_null(tmp_path: Path) -> None:
    rows = [
        {
            "run_id": "r1",
            "problem_id": "A1",
            "entity_id": "A1",
            "param_index": 0,
            "lower": float("nan"),
            "upper": 1.0,
            "value": 2.0,
        }
    ]
    for backing in BACKINGS:
        with pytest.raises(RecordSchemaError, match="'lower' has 1 nulls"):
            records.PAYOUTS.validate(_backed(rows, backing, tmp_path))


def _flags() -> TableSchema:
    return TableSchema(
        name="flags",
        key=("id",),
        columns=(
            Column("id", "str", "Row id"),
            Column("flag", "bool", "A flag"),
            Column("maybe", "bool", "An optional flag", nullable=True),
            Column("at", "timestamp", "A time", nullable=True),
        ),
    )


@pytest.mark.parametrize("backing", sorted(BACKINGS))
def test_bool_and_timestamp_columns_on_every_backing(
    backing: str, tmp_path: Path
) -> None:
    schema = _flags()
    at = datetime(2026, 10, 27, tzinfo=UTC)
    rows = [
        {"id": "a", "flag": True, "maybe": None, "at": at},
        {"id": "b", "flag": False, "maybe": True, "at": at},
    ]
    expected = schema.from_rows(rows)
    frame = _backed(rows, backing, tmp_path)
    if backing in ("object", "arrow"):
        # Neither an object column of datetimes nor an Arrow timestamp column
        # has the DatetimeTZDtype the timestamp check requires (as before).
        with pytest.raises(RecordSchemaError, match="'at' must hold timestamp"):
            schema.validate(frame)
        return
    pd.testing.assert_frame_equal(schema.validate(frame), expected)
    for bad, match in [
        ({"flag": 1}, "'flag' must hold bool values"),
        ({"maybe": "yes"}, "'maybe' must hold bool values"),
        ({"flag": None}, "'flag' has 1 nulls"),
        ({"at": "2026-10-27"}, "'at' must hold timestamp values"),
    ]:
        bad_rows = [rows[0], {**rows[1], **bad}]
        with pytest.raises(RecordSchemaError, match=match):
            schema.from_rows(bad_rows)
        try:
            bad_frame = _backed(bad_rows, backing, tmp_path)
        except (pa.ArrowException, TypeError, ValueError):
            continue
        with pytest.raises(RecordSchemaError, match=match):
            schema.validate(bad_frame)


# -- the column check against the reference ----------------------------------


def _reference(present: pd.Series, kind: ColumnKind) -> bool:
    return all(_is_kind(v, kind) for v in present)


def _present(values: pd.Series) -> pd.Series:
    return values.loc[~values.isna()]


TYPED_COLUMNS: list[pd.Series] = [
    pd.Series(["a", "b"], dtype=object),
    pd.Series(["a", None], dtype="string"),
    pd.Series(["a", None], dtype=pd.ArrowDtype(pa.string())),
    pd.Series(["a", None], dtype=pd.ArrowDtype(pa.large_string())),
    pd.Series(["a", "b"], dtype="category"),
    pd.Series([b"a", b"b"], dtype=object),
    pd.Series([1, 2], dtype=np.int64),
    pd.Series([1, 2], dtype=np.uint8),
    pd.Series([1.5, np.nan], dtype=np.float32),
    pd.Series([1, None], dtype="Int64"),
    pd.Series([1.5, None], dtype="Float64"),
    pd.Series([1, None], dtype=pd.ArrowDtype(pa.int64())),
    pd.Series([1.5, None], dtype=pd.ArrowDtype(pa.float64())),
    pd.Series([True, False], dtype=bool),
    pd.Series([True, None], dtype="boolean"),
    pd.Series([True, None], dtype=pd.ArrowDtype(pa.bool_())),
    pd.Series([1 + 2j], dtype=np.complex128),
    pd.Series([decimal.Decimal("1.5")], dtype=object),
    pd.Series([np.timedelta64(1, "s")], dtype=object),
    pd.Series(pd.to_timedelta([1, 2], unit="s")),
    pd.Series(pd.to_datetime(["2026-10-27"])),
    pd.Series([np.str_("a"), "b"], dtype=object),
    pd.Series([np.bool_(True), False], dtype=object),
    pd.Series([np.int64(1), 2.5, np.float32(3)], dtype=object),
    pd.Series([1, True], dtype=object),
    pd.Series([1.0, np.bool_(False)], dtype=object),
    pd.Series(["a", 1], dtype=object),
    pd.Series([["a"], ("b",)], dtype=object),
    pd.Series([], dtype=object),
    pd.Series([], dtype=np.float64),
]


@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize(
    "values",
    TYPED_COLUMNS,
    ids=[f"{i}-{s.dtype}" for i, s in enumerate(TYPED_COLUMNS)],
)
def test_column_check_equals_the_reference_on_typed_columns(
    values: pd.Series, kind: ColumnKind
) -> None:
    present = _present(values)
    assert _holds_only(present, kind) == _reference(present, kind)


def test_timestamp_check_is_by_dtype() -> None:
    aware = pd.Series(pd.to_datetime(["2026-10-27"], utc=True))
    naive = pd.Series(pd.to_datetime(["2026-10-27"]))
    assert _holds_only(aware, "timestamp")
    assert not _holds_only(naive, "timestamp")
    assert not _holds_only(pd.Series(["2026-10-27"]), "timestamp")
    assert _holds_only(pd.Series([], dtype=object), "timestamp")


SCALARS = st.one_of(
    st.none(),
    st.just(np.nan),
    st.just(pd.NA),
    st.text(max_size=3),
    st.text(max_size=3).map(np.str_),
    st.binary(max_size=2),
    st.integers(-(2**70), 2**70),
    st.integers(-(2**31), 2**31).map(np.int64),
    st.integers(0, 255).map(np.uint8),
    st.floats(allow_nan=True, allow_infinity=True),
    st.floats(width=32).map(np.float32),
    st.booleans(),
    st.booleans().map(np.bool_),
    st.just(decimal.Decimal("1.5")),
    st.just(1 + 1j),
    st.just(np.timedelta64(3, "s")),
    st.just(datetime(2026, 10, 27, tzinfo=UTC)),
    st.just(["a"]),
)


@settings(PROPERTY_SETTINGS, max_examples=400)
@given(values=st.lists(SCALARS, max_size=6))
def test_column_check_equals_the_reference_on_random_object_columns(
    values: list[object],
) -> None:
    series = pd.Series(values, dtype=object)
    present = _present(series)
    for kind in KINDS:
        assert _holds_only(present, kind) == _reference(present, kind), kind


@settings(PROPERTY_SETTINGS, max_examples=100)
@given(
    values=st.lists(st.one_of(st.none(), st.text(max_size=3)), max_size=6),
    allowed=st.frozensets(st.text(max_size=3), max_size=4),
)
def test_allowed_values_check_names_the_same_values(
    values: list[str | None], allowed: frozenset[str]
) -> None:
    schema = TableSchema(
        name="t",
        key=("i",),
        columns=(
            Column("i", "int", "Row number"),
            Column("s", "str", "A value", nullable=True, allowed=allowed),
        ),
    )
    frame = pd.DataFrame(
        {"i": range(len(values)), "s": pd.Series(values, dtype=object)}
    )
    bad = sorted({v for v in values if v is not None and v not in allowed})
    for candidate in (frame, frame.astype({"s": "string"})):
        if bad:
            with pytest.raises(RecordSchemaError) as info:
                schema.validate(candidate)
            assert f"has values {bad} not in {sorted(allowed)}" in str(info.value)
        else:
            assert schema.validate(candidate)["s"].tolist() == values
