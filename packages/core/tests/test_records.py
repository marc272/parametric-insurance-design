"""Tests for the result-store record schemas (ADR 0002, MAR-61)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from parametric_insurance_design import records
from parametric_insurance_design.errors import RecordSchemaError
from parametric_insurance_design.records import Column, TableSchema


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


def test_tables_are_registered() -> None:
    assert set(records.TABLES) == {"runs", "entities", "payouts", "kpis", "exceedance"}
    for name, schema in records.TABLES.items():
        assert schema.name == name
        assert set(schema.key) <= set(schema.column_names)
        assert schema.arrow_schema().names == list(schema.column_names)


@pytest.mark.parametrize("name", sorted(records.TABLES))
def test_empty_tables_round_trip_parquet(name: str, tmp_path: Path) -> None:
    schema = records.TABLES[name]
    empty = schema.empty()
    assert list(empty.columns) == list(schema.column_names)
    path = tmp_path / f"{name}.parquet"
    pq.write_table(
        pa.Table.from_pandas(empty, schema=schema.arrow_schema(), preserve_index=False),
        path,
    )
    assert pq.read_schema(path).equals(schema.arrow_schema())
    assert schema.validate(pq.read_table(path).to_pandas()).equals(empty)


def test_kpi_rows_round_trip_with_nulls(tmp_path: Path) -> None:
    frame = records.KPIS.from_rows(
        [kpi_row(), kpi_row(kpi="correlation", beta=None, value=None)]
    )
    assert frame["n_bootstrap"].dtype == "Int64"
    assert frame["kpi"].tolist() == ["cvar_uncovered", "correlation"]
    assert np.isnan(frame["value"].iloc[1])
    path = tmp_path / "kpis.parquet"
    table = pa.Table.from_pandas(
        frame, schema=records.KPIS.arrow_schema(), preserve_index=False
    )
    assert table.column("value").null_count == 1
    pq.write_table(table, path)
    assert records.KPIS.validate(pq.read_table(path).to_pandas()).equals(frame)


def test_from_no_rows_is_the_empty_table() -> None:
    assert records.PAYOUTS.from_rows([]).equals(records.PAYOUTS.empty())


def test_validate_reorders_columns() -> None:
    frame = records.KPIS.from_rows([kpi_row()])
    shuffled = cast(pd.DataFrame, frame[list(reversed(frame.columns))])
    assert records.KPIS.validate(shuffled).equals(frame)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"kpi": "sharpe"}, "not in"),
        ({"basis": "monthly"}, "not in"),
        ({"level": "galaxy"}, "not in"),
        ({"eval_split": "dev"}, "not in"),
        ({"run_id": None}, "nulls"),
        ({"run_id": 3}, "str values"),
        ({"fold": 1.5}, "int values"),
        ({"fold": "0"}, "int values"),
        ({"value": float("inf")}, "infinite"),
        ({"value": True}, "float values"),
    ],
)
def test_invalid_values_raise(overrides: dict[str, Any], match: str) -> None:
    with pytest.raises(RecordSchemaError, match=match):
        records.KPIS.from_rows([kpi_row(**overrides)])


def test_duplicate_key_raises() -> None:
    with pytest.raises(RecordSchemaError, match="repeat the key"):
        records.KPIS.from_rows([kpi_row(), kpi_row(value=2.0)])
    # A different beta is a different key.
    assert len(records.KPIS.from_rows([kpi_row(), kpi_row(beta=0.95)])) == 2


def test_from_rows_rejects_missing_and_unknown_keys() -> None:
    row = kpi_row()
    del row["value"]
    with pytest.raises(RecordSchemaError, match=r"missing keys \['value'\]"):
        records.KPIS.from_rows([row])
    with pytest.raises(RecordSchemaError, match=r"unknown keys \['extra'\]"):
        records.KPIS.from_rows([kpi_row(extra=1)])


def test_validate_rejects_bad_frames() -> None:
    frame = records.KPIS.from_rows([kpi_row()])
    with pytest.raises(RecordSchemaError, match="DataFrame"):
        records.KPIS.validate(frame.to_dict())  # type: ignore[arg-type]
    with pytest.raises(RecordSchemaError, match="missing columns"):
        records.KPIS.validate(frame.drop(columns="value"))
    with pytest.raises(RecordSchemaError, match="unknown columns"):
        records.KPIS.validate(frame.assign(extra=1))
    doubled = pd.concat([frame, frame[["value"]]], axis=1)
    with pytest.raises(RecordSchemaError, match="column names repeat"):
        records.KPIS.validate(doubled)


def test_runs_timestamps_are_utc() -> None:
    row = {
        "run_id": "r1",
        "problem_id": "A1",
        "config_hash": "h",
        "source": "single_run",
        "scope": "individual",
        "objective": "weighted_cvar",
        "pricing": "pure",
        "payout": "step",
        "basis": "event_conditional",
        "calibration_split": "full",
        "fold": 0,
        "parameters": "{}",
        "status": "infeasible",
        "solver": None,
        "objective_value": None,
        "premium": None,
        "build_seconds": 0.1,
        "solve_seconds": None,
        "error_type": "InfeasibleError",
        "error_message": "no feasible payout",
        "eventset_checksum": None,
        "package_version": "0.1.0",
        "created_at": datetime(2026, 10, 25, 12, tzinfo=UTC),
    }
    frame = records.RUNS.from_rows([row])
    assert str(frame["created_at"].dtype) == "datetime64[us, UTC]"
    with pytest.raises(RecordSchemaError, match="timestamp values"):
        records.RUNS.from_rows([{**row, "created_at": "2026-10-25"}])
    with pytest.raises(RecordSchemaError, match="not in"):
        records.RUNS.from_rows([{**row, "status": "maybe"}])


def test_bool_columns_and_schema_checks() -> None:
    schema = TableSchema(
        name="flags",
        key=("id",),
        columns=(
            Column("id", "str", "Row id"),
            Column("flag", "bool", "A flag"),
            Column("maybe", "bool", "An optional flag", nullable=True),
        ),
    )
    frame = schema.from_rows(
        [
            {"id": "a", "flag": True, "maybe": None},
            {"id": "b", "flag": np.bool_(False), "maybe": True},
        ]
    )
    assert frame["flag"].dtype == bool
    assert frame["maybe"].dtype == "boolean"
    assert schema.column("flag").kind == "bool"
    with pytest.raises(RecordSchemaError, match="bool values"):
        schema.from_rows([{"id": "a", "flag": 1, "maybe": None}])
    with pytest.raises(ValueError, match="repeats a column"):
        TableSchema("t", (Column("a", "str", ""), Column("a", "str", "")), ("a",))
    with pytest.raises(ValueError, match="key columns missing"):
        TableSchema("t", (Column("a", "str", ""),), ("b",))
