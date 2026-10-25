"""Tests of the Parquet result store (MAR-64)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from parametric_insurance_design.errors import RecordSchemaError
from parametric_insurance_design.experiment.store import (
    MANIFESTS_DIR,
    STORE_FILE,
    STORE_FORMAT,
    STORE_VERSION,
    ResultStore,
    RunExistsError,
    RunTables,
    StoreError,
    run_file_stem,
)
from parametric_insurance_design.records import (
    ENTITIES,
    EXCEEDANCE,
    KPIS,
    PAYOUTS,
    RUNS,
    TABLES,
)

RUN_A = "sha256:" + "a" * 64
RUN_B = "sha256:" + "b" * 64


def runs_row(
    run_id: str, problem_id: str = "portfolio", **over: object
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "run_id": run_id,
        "problem_id": problem_id,
        "config_hash": "sha256:" + "c" * 64,
        "source": "single_run",
        "scope": "portfolio",
        "objective": "expected_uncovered",
        "pricing": "pure",
        "payout": "step",
        "basis": "event_conditional",
        "calibration_split": "full",
        "fold": 0,
        "parameters": '{"n_bins":2}',
        "status": "optimal",
        "solver": "CLARABEL",
        "objective_value": 1.5,
        "premium": 2.0,
        "build_seconds": 0.01,
        "solve_seconds": 0.02,
        "error_type": None,
        "error_message": None,
        "eventset_checksum": "sha256:" + "e" * 64,
        "package_version": "0.1.0.dev0",
        "created_at": datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
    }
    row.update(over)
    return row


def make_tables(run_id: str, *, with_kpis: bool = True) -> RunTables:
    kpis = KPIS.from_rows(
        [
            {
                "run_id": run_id,
                "problem_id": "portfolio",
                "eval_split": "full",
                "fold": 0,
                "basis": "event_conditional",
                "level": "problem",
                "subject_id": "portfolio",
                "kpi": "cvar_uncovered",
                "beta": 0.95,
                "value": 3.0,
                "ci_low": None,
                "ci_high": None,
                "ci_level": None,
                "n_bootstrap": None,
            }
        ]
        if with_kpis
        else []
    )
    return RunTables(
        runs=RUNS.from_rows(
            [
                runs_row(run_id, "A"),
                runs_row(
                    run_id,
                    "B",
                    status="infeasible",
                    solver=None,
                    objective_value=None,
                    premium=None,
                    error_type="InfeasibleError",
                    error_message="no solver returned an acceptable result",
                ),
            ]
        ),
        entities=ENTITIES.from_rows(
            [
                {"run_id": run_id, "problem_id": p, "entity_id": p, "location_id": p}
                for p in ("A", "B")
            ]
        ),
        payouts=PAYOUTS.from_rows(
            {
                "run_id": run_id,
                "problem_id": "A",
                "entity_id": "A",
                "param_index": k,
                "lower": 20.0 + 20 * k,
                "upper": 40.0 + 20 * k,
                "value": float(k),
            }
            for k in range(2)
        ),
        kpis=kpis,
        exceedance=EXCEEDANCE.empty(),
    )


def manifest(run_id: str, **extra: object) -> dict[str, Any]:
    return {"run_id": run_id, "note": "test", **extra}


# -- run ids ----------------------------------------------------------------


def test_run_file_stem_is_the_hex_digest() -> None:
    assert run_file_stem(RUN_A) == "a" * 64


@pytest.mark.parametrize(
    "bad", ["a" * 64, "sha256:" + "A" * 64, "sha256:abc", "md5:" + "a" * 64, 3]
)
def test_run_file_stem_rejects_other_forms(bad: object) -> None:
    with pytest.raises(StoreError, match="sha256"):
        run_file_stem(bad)  # type: ignore[arg-type]


# -- RunTables --------------------------------------------------------------


def test_run_tables_validate_and_share_one_run_id() -> None:
    tables = make_tables(RUN_A)
    assert tables.run_id == RUN_A
    assert [schema.name for schema, _ in tables.items()] == list(TABLES)


def test_run_tables_need_a_runs_row() -> None:
    tables = make_tables(RUN_A)
    with pytest.raises(RecordSchemaError, match="at least one row"):
        RunTables(
            runs=RUNS.empty(),
            entities=tables.entities,
            payouts=tables.payouts,
            kpis=tables.kpis,
            exceedance=tables.exceedance,
        )


def test_run_tables_refuse_two_run_ids() -> None:
    a, b = make_tables(RUN_A), make_tables(RUN_B)
    with pytest.raises(RecordSchemaError, match="one run_id"):
        RunTables(
            runs=a.runs,
            entities=b.entities,
            payouts=a.payouts,
            kpis=a.kpis,
            exceedance=a.exceedance,
        )


def test_run_tables_validate_each_schema() -> None:
    a = make_tables(RUN_A)
    with pytest.raises(RecordSchemaError, match="kpis"):
        RunTables(
            runs=a.runs,
            entities=a.entities,
            payouts=a.payouts,
            kpis=a.payouts,
            exceedance=a.exceedance,
        )


# -- writing and reading ----------------------------------------------------


def test_new_store_is_empty_and_creates_nothing(tmp_path: Path) -> None:
    store = ResultStore(tmp_path / "store")
    assert store.run_ids() == ()
    assert store.uncommitted_runs() == ()
    assert not store.has_run(RUN_A)
    for name, schema in TABLES.items():
        assert store.read(name).equals(schema.empty())
    assert not (tmp_path / "store").exists()
    assert repr(store) == f"ResultStore({str(tmp_path / 'store')!r})"


def test_round_trip_of_every_table(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    tables = make_tables(RUN_A)
    store.write_run(tables, manifest(RUN_A))
    assert store.has_run(RUN_A)
    assert store.run_ids() == (RUN_A,)
    info = json.loads((tmp_path / STORE_FILE).read_text())
    assert info == {"format": STORE_FORMAT, "version": STORE_VERSION}
    for schema, frame in tables.items():
        back = store.read(schema.name)
        assert back.equals(frame), schema.name
        path = tmp_path / schema.name / f"{'a' * 64}.parquet"
        assert pq.read_schema(path).equals(schema.arrow_schema())
    assert store.manifest(RUN_A) == manifest(RUN_A)


def test_failed_rows_keep_status_and_error(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    store.write_run(make_tables(RUN_A), manifest(RUN_A))
    runs = store.read("runs").set_index("problem_id")
    assert runs.loc["B", "status"] == "infeasible"
    assert runs.loc["B", "error_type"] == "InfeasibleError"
    assert pd.isna(runs.loc["B", "objective_value"])


def test_payouts_are_tidy_numbers(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    store.write_run(make_tables(RUN_A), manifest(RUN_A))
    payouts = store.read("payouts")
    assert payouts["value"].dtype == "float64"
    assert payouts["param_index"].tolist() == [0, 1]
    assert not any(isinstance(v, str) for v in payouts["value"])


def test_read_selects_runs_in_sorted_order(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    store.write_run(make_tables(RUN_B), manifest(RUN_B))
    store.write_run(make_tables(RUN_A, with_kpis=False), manifest(RUN_A))
    assert store.run_ids() == (RUN_A, RUN_B)
    assert store.read("runs")["run_id"].tolist() == [RUN_A, RUN_A, RUN_B, RUN_B]
    assert store.read("runs", run_ids=[RUN_B])["run_id"].unique().tolist() == [RUN_B]
    assert store.read("kpis")["run_id"].tolist() == [RUN_B]
    assert len(store.read("kpis", run_ids=[RUN_A])) == 0


def test_read_refuses_unknown_tables_and_runs(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    store.write_run(make_tables(RUN_A), manifest(RUN_A))
    with pytest.raises(StoreError, match="unknown table"):
        store.read("results")
    with pytest.raises(StoreError, match="not in the store"):
        store.read("runs", run_ids=[RUN_B])


def test_committed_run_is_not_overwritten_by_default(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    store.write_run(make_tables(RUN_A), manifest(RUN_A))
    with pytest.raises(RunExistsError):
        store.write_run(make_tables(RUN_A, with_kpis=False), manifest(RUN_A))
    assert len(store.read("kpis")) == 1


def test_overwrite_replaces_a_run(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    store.write_run(make_tables(RUN_A), manifest(RUN_A))
    store.write_run(
        make_tables(RUN_A, with_kpis=False),
        manifest(RUN_A, note="again"),
        overwrite=True,
    )
    assert len(store.read("kpis")) == 0
    assert store.manifest(RUN_A)["note"] == "again"


def test_manifest_must_name_the_run(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    with pytest.raises(StoreError, match="differs"):
        store.write_run(make_tables(RUN_A), manifest(RUN_B))
    with pytest.raises(StoreError, match="not valid JSON"):
        store.write_run(make_tables(RUN_A), manifest(RUN_A, bad=float("nan")))
    with pytest.raises(StoreError, match="not valid JSON"):
        store.write_run(make_tables(RUN_A), manifest(RUN_A, bad=object()))
    assert store.run_ids() == ()


def test_interrupted_write_is_invisible_and_listed(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    store.write_run(make_tables(RUN_A), manifest(RUN_A))
    store.write_run(make_tables(RUN_B), manifest(RUN_B))
    (tmp_path / MANIFESTS_DIR / f"{'b' * 64}.json").unlink()  # crash before commit
    assert store.run_ids() == (RUN_A,)
    assert store.uncommitted_runs() == (RUN_B,)
    assert store.read("runs")["run_id"].unique().tolist() == [RUN_A]
    store.write_run(make_tables(RUN_B), manifest(RUN_B))  # the re-run commits
    assert store.uncommitted_runs() == ()


def test_manifest_of_unknown_or_damaged_run(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    with pytest.raises(StoreError, match="not in the store"):
        store.manifest(RUN_A)
    store.write_run(make_tables(RUN_A), manifest(RUN_A))
    path = tmp_path / MANIFESTS_DIR / f"{'a' * 64}.json"
    path.write_text("[1, 2]")
    with pytest.raises(StoreError, match="JSON object"):
        store.manifest(RUN_A)
    path.write_text("{")
    with pytest.raises(StoreError, match="not valid JSON"):
        store.manifest(RUN_A)


def test_missing_table_file_of_committed_run_is_an_error(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    store.write_run(make_tables(RUN_A), manifest(RUN_A))
    (tmp_path / "payouts" / f"{'a' * 64}.parquet").unlink()
    with pytest.raises(StoreError, match="damaged"):
        store.read("payouts")


def test_file_with_another_schema_is_an_error(tmp_path: Path) -> None:
    store = ResultStore(tmp_path)
    store.write_run(make_tables(RUN_A), manifest(RUN_A))
    path = tmp_path / "payouts" / f"{'a' * 64}.parquet"
    pq.write_table(pa.table({"run_id": [RUN_A], "value": ["1.0"]}), path)
    with pytest.raises(RecordSchemaError, match="schema"):
        store.read("payouts")


def test_store_marker_is_checked(tmp_path: Path) -> None:
    (tmp_path / STORE_FILE).write_text(
        json.dumps({"format": STORE_FORMAT, "version": 99})
    )
    with pytest.raises(StoreError, match="this version reads"):
        ResultStore(tmp_path)
    (tmp_path / STORE_FILE).write_text("not json")
    with pytest.raises(StoreError, match="not valid JSON"):
        ResultStore(tmp_path)


def test_root_must_be_a_directory(tmp_path: Path) -> None:
    file = tmp_path / "file"
    file.write_text("x")
    with pytest.raises(StoreError, match="not a directory"):
        ResultStore(file)
