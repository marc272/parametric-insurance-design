"""Tests of the site bundle export (MAR-200): format, rules, budget, errors.

The bundles are exported from the ``toy`` stores of ``conftest.py`` (plus a
small sweep store built here) and read back with pyarrow and :mod:`json`,
independently of :func:`~parametric_insurance_design_viz.site_export.read_bundle`.
The committed thesis-fixture bundles under ``site/fixtures/thesis`` and
``site/fixtures/thesis-explorer`` are checked against their manifests and
against the configs they came from.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
import yaml

from parametric_insurance_design import cli
from parametric_insurance_design.experiment.config import (
    CostOfCapitalConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.kfold import (
    POOLED_COLUMNS,
    POOLED_KPIS,
    POOLED_SPLIT,
    PooledKpis,
    pooled_kpis,
)
from parametric_insurance_design.experiment.runner import load_input
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.experiment.sweeps import run_sweeps
from parametric_insurance_design.payout import NO_BIN
from parametric_insurance_design.solve import DEFAULT_POLICY
from parametric_insurance_design_viz import site_export
from parametric_insurance_design_viz.errors import (
    EventSetMismatchError,
    InconsistentRunsError,
    MissingRunError,
)
from parametric_insurance_design_viz.kpi_figures import KFoldRunsError
from parametric_insurance_design_viz.payout_functions import (
    JOINT_CAPTION,
    is_joint_design,
)
from parametric_insurance_design_viz.reader import (
    ResultReader,
    RunResult,
    entity_events,
)
from parametric_insurance_design_viz.site_export import (
    BUNDLE_FORMAT,
    BUNDLE_FORMAT_VERSION,
    MANIFEST,
    BundleBudgetError,
    BundleChecksumError,
    BundleError,
    BundleValueError,
    ExportReport,
    SizeBudget,
    SweepRun,
    export_site,
    read_bundle,
    read_slice,
)

from .conftest import build_fixture, config_dict, make_eventset

if TYPE_CHECKING:
    from conftest import Fixture

REPO = Path(__file__).resolve().parents[3]
THESIS_FIXTURE = REPO / "site" / "fixtures" / "thesis"
THESIS_CONFIG = REPO / "parity" / "configs" / "thesis.yaml"
THESIS_EXPLORER_FIXTURE = REPO / "site" / "fixtures" / "thesis-explorer"
THESIS_EXPLORER_CONFIG = REPO / "site" / "fixtures" / "thesis_explorer.yaml"
SWEEPS = [
    {"parameter": "alpha", "values": [0.5, 0.9]},
    {"parameter": "n_clusters", "values": [1, 2]},
]
EXPECTED_FILES = [
    "runs.json",
    "locations.json",
    "baseline.payouts.arrow",
    "baseline.kpis.arrow",
    "baseline.exceedance.arrow",
    "baseline.map.arrow",
]


def sweep_runs(toy: Fixture) -> tuple[SweepRun, ...]:
    """The sweep points as the ``export-site`` command computes them."""
    data = load_input(toy.config)
    runs = cli._sweep_runs(site_export, toy.config, data, DEFAULT_POLICY)
    return tuple(r for r in runs if isinstance(r, SweepRun))


def export(fixture: Fixture, out: Path, **options: Any) -> ExportReport:  # noqa: ANN401
    return export_site(
        fixture.config,
        fixture.run_ids,
        store=fixture.store,
        out_dir=out,
        eventset=fixture.eventset,
        **options,
    )


def arrow(path: Path) -> pa.Table:
    """Read an Arrow IPC file with pyarrow alone."""
    with pa.memory_map(str(path)) as source:
        return pa.ipc.open_file(source).read_all()


def strict_json(path: Path) -> Any:  # noqa: ANN401
    """Parse a file as strict JSON: NaN and infinities are refused."""

    def refuse(token: str) -> None:
        raise AssertionError(f"{path.name} holds {token}, which strict JSON forbids")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=refuse)


@dataclass(frozen=True)
class Swept:
    toy: Fixture
    sweeps: tuple[SweepRun, ...]
    out: Path
    report: ExportReport

    @property
    def manifest(self) -> dict[str, Any]:
        return strict_json(self.out / MANIFEST)


@pytest.fixture(scope="module")
def swept(tmp_path_factory: pytest.TempPathFactory) -> Swept:
    toy = build_fixture(tmp_path_factory.mktemp("site-swept"), sweeps=SWEEPS)
    run_sweeps(toy.config, store=toy.store, baseline=False)
    sweeps = sweep_runs(toy)
    out = tmp_path_factory.mktemp("site-bundle") / "bundle"
    report = export(toy, out, sweeps=sweeps, label="toy data")
    return Swept(toy=toy, sweeps=sweeps, out=out, report=report)


# -- the bundle and its manifest ----------------------------------------------


def test_writes_the_bundle_and_its_manifest(swept: Swept) -> None:
    manifest = swept.manifest
    names = [f["path"] for f in manifest["files"]]
    assert names == [
        *EXPECTED_FILES,
        "sweep.alpha.payouts.arrow",
        "sweep.alpha.kpis.arrow",
        "sweep.alpha.exceedance.arrow",
    ]
    assert sorted(p.name for p in swept.out.iterdir()) == sorted([*names, MANIFEST])
    assert swept.report.ok
    assert swept.report.removed == ()
    assert [f.path for f in swept.report.files] == names


def test_every_file_matches_its_size_and_checksum(swept: Swept) -> None:
    for entry in swept.manifest["files"]:
        data = (swept.out / entry["path"]).read_bytes()
        assert len(data) == entry["bytes"]
        assert entry["sha256"] == f"sha256:{hashlib.sha256(data).hexdigest()}"
    assert read_bundle(swept.out) == swept.manifest
    total = sum(f["bytes"] for f in swept.manifest["files"])
    assert swept.manifest["budget"]["bundle_bytes"] == total
    assert swept.report.bundle_bytes == total


def test_the_manifest_states_the_setup_and_the_runs(swept: Swept) -> None:
    manifest = swept.manifest
    config = swept.toy.config
    assert manifest["format"] == BUNDLE_FORMAT
    assert manifest["format_version"] == BUNDLE_FORMAT_VERSION
    assert manifest["label"] == "toy data"
    assert manifest["config"]["hash"] == config_hash(config)
    assert manifest["config"]["name"] == config.name
    setup = manifest["setup"]
    assert set(setup) >= {"portfolio", "basis", "basis_risk", "pricing", "split"}
    assert setup["basis"] == "event_conditional"
    assert setup["pricing"] == {"kind": "pure"}
    assert setup["split"] == {"kind": "full", "out_of_sample": False}
    assert setup["basis_risk"]["noise"] is None
    assert setup["basis_risk"]["threshold"] == {"value": 20.0, "column": "index"}
    assert manifest["runs"]["baseline"] == list(swept.toy.run_ids)
    alpha = [p for p in swept.sweeps if p.parameter == "alpha"]
    assert manifest["runs"]["sweeps"] == {
        "alpha": [
            {"value": p.value, "run_id": p.run_id, "single": p.single} for p in alpha
        ]
    }
    assert manifest["runs"]["skipped"] == []
    assert manifest["sweeps_not_exported"] == ["n_clusters"]
    assert manifest["events"]["included"] is False
    eventset = manifest["eventset"]
    assert eventset["prepared_content_hash"] == swept.toy.eventset.content_hash()
    assert eventset["licence"] == "CC0-1.0"
    assert eventset["index"]["unit"] == "m/s"
    assert set(manifest["rules"]) == {
        "infinity",
        "nan",
        "types",
        "arrow",
        "budget",
        "checksums",
    }
    assert manifest["budget"]["max_file_bytes"] == site_export.DEFAULT_MAX_FILE_BYTES
    assert (
        manifest["budget"]["max_bundle_bytes"] == site_export.DEFAULT_MAX_BUNDLE_BYTES
    )


def test_json_files_are_strict_json(swept: Swept) -> None:
    runs = strict_json(swept.out / "runs.json")["runs"]
    exported = {r["run_id"] for r in runs}
    alpha = {p.run_id for p in swept.sweeps if p.parameter == "alpha"}
    assert exported == {*swept.toy.run_ids, *alpha}
    entry = next(r for r in runs if r["run_id"] == swept.toy.run_ids[0])
    assert entry["scope"] == "individual"
    assert entry["scope_key"] == "individual"
    assert entry["objective"] == "mse"
    assert entry["complete"] is True
    assert [p["problem_id"] for p in entry["problems"]] == ["A1", "A2", "A3"]
    assert entry["parameters"]["n_bins"] == 5
    locations = strict_json(swept.out / "locations.json")["locations"]
    assert [loc["location_id"] for loc in locations] == ["A1", "A2", "A3"]
    assert locations[0] == {
        "location_id": "A1",
        "name": "Asset 1",
        "lat": 25.0,
        "lon": -80.0,
        "value": 100.0,
    }


def test_arrow_tables_hold_the_store_rows(swept: Swept) -> None:
    toy = swept.toy
    store = ResultReader(toy.store)
    baseline = store.runs(toy.run_ids)
    payouts = arrow(swept.out / "baseline.payouts.arrow").to_pandas()
    assert len(payouts) == sum(len(r.payouts) for r in baseline)
    kpis = arrow(swept.out / "baseline.kpis.arrow").to_pandas()
    assert len(kpis) == sum(len(r.kpis) for r in baseline)
    exceedance = arrow(swept.out / "baseline.exceedance.arrow").to_pandas()
    assert len(exceedance) == sum(len(r.exceedance) for r in baseline)
    first = baseline[0]
    rows = payouts[payouts["run_id"] == first.run_id].reset_index(drop=True)
    expected = first.payouts.sort_values(
        ["problem_id", "entity_id", "param_index"], kind="stable"
    ).reset_index(drop=True)
    np.testing.assert_array_equal(rows["value"], expected["value"])
    np.testing.assert_array_equal(rows["lower"], expected["lower"])
    assert set(rows["below_attachment"]) == {"first_bin"}
    assert set(rows["objective"]) == {"mse"}
    store_kpis = first.kpis.reset_index(drop=True)
    mine = kpis[kpis["run_id"] == first.run_id].reset_index(drop=True)
    np.testing.assert_array_equal(mine["value"], store_kpis["value"])
    assert list(mine["kpi"]) == list(store_kpis["kpi"])


def test_sweep_tables_carry_the_sweep_value(swept: Swept) -> None:
    alpha = [p for p in swept.sweeps if p.parameter == "alpha"]
    payouts = arrow(swept.out / "sweep.alpha.payouts.arrow").to_pandas()
    assert sorted(set(payouts["sweep_value"])) == [0.5, 0.9]
    assert set(payouts["run_id"]) == {p.run_id for p in alpha}
    assert set(payouts["objective"]) == {"weighted_cvar"}
    kpis = arrow(swept.out / "sweep.alpha.kpis.arrow").to_pandas()
    by_run = kpis.groupby("run_id")["sweep_value"].unique()
    assert {r: list(v) for r, v in by_run.items()} == {
        p.run_id: [float(p.value)] for p in alpha
    }


def test_column_types_follow_the_rules(swept: Swept) -> None:
    for entry in swept.manifest["files"]:
        if entry["format"] != "arrow":
            continue
        table = arrow(swept.out / entry["path"])
        assert table.num_rows == entry["rows"]
        assert [c["name"] for c in entry["columns"]] == table.column_names
        for field, column in zip(table.schema, entry["columns"], strict=True):
            assert not pa.types.is_int64(field.type), (entry["path"], field.name)
            if pa.types.is_dictionary(field.type):
                assert pa.types.is_string(field.type.value_type)
                assert field.type.index_type == pa.int8()  # small dictionaries
            assert column["nulls"] == table.column(field.name).null_count
        assert (swept.out / entry["path"]).read_bytes()[:6] == b"ARROW1"


def test_map_without_allocation_rows_uses_individual_entity_rows_only(
    swept: Swept,
) -> None:
    # The toy config names no allocation rule, so its store has no allocation rows.
    map_ = arrow(swept.out / "baseline.map.arrow").to_pandas()
    columns = [c for c in swept.manifest["files"] if c["path"] == "baseline.map.arrow"]
    meaning = {c["name"]: c["null_means"] for c in columns[0]["columns"]}
    individual = map_[map_["scope"] == "individual"]
    assert set(individual["kpi_level"]) == {"entity"}
    assert set(individual["allocation"]) == {"none"}
    assert individual[list(site_export._MAP_KPIS)].notna().all().all()
    assert sorted(set(individual["location_id"])) == ["A1", "A2", "A3"]
    # Joint designs: every location of every run, and no numbers at all; the
    # portfolio scope's single-location entities are the solver's split (F8).
    for scope in ("cluster", "portfolio"):
        rows = map_[map_["scope"] == scope]
        assert len(rows) == 3 * len(swept.toy.config.objectives), scope
        assert rows["kpi_level"].isna().all(), scope
        assert rows["allocation"].isna().all(), scope
        assert rows[list(site_export._MAP_KPIS)].isna().all().all(), scope
    for name in ("kpi_level", "allocation", *site_export._MAP_KPIS):
        assert meaning[name] == site_export._NOT_PER_LOCATION
    assert meaning["expected_payout"].startswith("not available per location")
    toy = swept.toy
    run = ResultReader(toy.store).run(toy.run_id("individual", "mse"))
    for kpi in site_export._MAP_KPIS:
        expected = run.kpis[(run.kpis["level"] == "entity") & (run.kpis["kpi"] == kpi)]
        mine = map_[map_["run_id"] == run.run_id].set_index("location_id")[kpi]
        assert {str(k): v for k, v in mine.items()} == expected.set_index("subject_id")[
            "value"
        ].to_dict()


def test_the_manifest_records_the_source_of_the_map(swept: Swept) -> None:
    section = swept.manifest["map"]
    assert section["rule"] == site_export._MAP_RULE
    assert section["allocations"] == []
    toy = swept.toy
    assert [r["run_id"] for r in section["runs"]] == list(toy.run_ids)
    for single, entry in zip(toy.config.single_runs(), section["runs"], strict=True):
        scope = single.scopes[0].kind
        assert entry["scope_key"] == scope
        assert entry["objective"] == single.objectives[0].kind
        if scope == "individual":
            assert (entry["kpi_level"], entry["allocation"]) == ("entity", "none")
        else:
            assert (entry["kpi_level"], entry["allocation"]) == (None, None)
    assert swept.manifest["format_version"] == 1


def test_reexport_is_byte_identical(swept: Swept, tmp_path: Path) -> None:
    again = tmp_path / "again"
    export(swept.toy, again, sweeps=swept.sweeps, label="toy data")
    for name in [*(f["path"] for f in swept.manifest["files"]), MANIFEST]:
        assert (again / name).read_bytes() == (swept.out / name).read_bytes(), name


def test_a_previous_bundle_is_replaced(swept: Swept, tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    export(swept.toy, out, sweeps=swept.sweeps)
    report = export(swept.toy, out, sweeps=swept.sweeps, parameters=[])
    assert sorted(report.removed) == sorted(
        f"sweep.alpha.{s}.arrow" for s in ("payouts", "kpis", "exceedance")
    )
    assert sorted(p.name for p in out.iterdir()) == sorted([*EXPECTED_FILES, MANIFEST])
    assert report.manifest["sweeps_not_exported"] == ["alpha", "n_clusters"]
    read_bundle(out)


def test_a_directory_with_other_files_is_refused(toy: Fixture, tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "notes.txt").write_text("mine", encoding="utf-8")
    with pytest.raises(
        BundleError, match=r"not part of a site bundle: \['notes.txt'\]"
    ):
        export(toy, out)
    assert [p.name for p in out.iterdir()] == ["notes.txt"]
    (out / "notes.txt").unlink()
    (out / MANIFEST).write_text('{"format": "something else"}', encoding="utf-8")
    with pytest.raises(BundleError, match="not part of a site bundle"):
        export(toy, out)
    file = tmp_path / "file"
    file.write_text("", encoding="utf-8")
    with pytest.raises(BundleError, match="is not a directory"):
        export(toy, file)


def test_read_bundle_detects_changed_and_missing_files(
    swept: Swept, tmp_path: Path
) -> None:
    out = tmp_path / "bundle"
    export(swept.toy, out, parameters=[])
    path = out / "baseline.kpis.arrow"
    data = bytearray(path.read_bytes())
    data[-20] ^= 0xFF
    path.write_bytes(bytes(data))
    with pytest.raises(BundleChecksumError, match=r"baseline\.kpis\.arrow"):
        read_bundle(out)
    with pytest.raises(BundleChecksumError):
        read_slice(out, "baseline.kpis.arrow")
    path.unlink()
    with pytest.raises(BundleChecksumError, match="is missing"):
        read_bundle(out)
    with pytest.raises(BundleError, match="not a file of the bundle"):
        read_slice(out, "nothing.arrow")
    assert isinstance(read_slice(out, "runs.json"), dict)
    assert isinstance(read_slice(out, "baseline.payouts.arrow"), pa.Table)
    manifest = json.loads((out / MANIFEST).read_text(encoding="utf-8"))
    manifest["format_version"] = 99
    (out / MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BundleError, match="format_version 99"):
        read_bundle(out)
    (out / MANIFEST).write_text("{}", encoding="utf-8")
    with pytest.raises(BundleError, match="is not a"):
        read_bundle(out)
    (out / MANIFEST).unlink()
    with pytest.raises(BundleError, match=r"has no manifest\.json"):
        read_bundle(out)


# -- the infinity rule ---------------------------------------------------------


@pytest.fixture(scope="module")
def zero(tmp_path_factory: pytest.TempPathFactory) -> Fixture:
    """The ``toy`` store with ``below_attachment: zero`` (MAR-170, MAR-178)."""
    payout = {"attachment": 20.0, "limit": 70.0, "n_bins": 5}
    return build_fixture(
        tmp_path_factory.mktemp("site-zero"),
        payout={**payout, "below_attachment": "zero"},
    )


def test_the_zero_row_writes_minus_infinity_as_null(
    zero: Fixture, tmp_path: Path
) -> None:
    out = tmp_path / "bundle"
    report = export(zero, out)
    table = arrow(out / "baseline.payouts.arrow")
    payouts = table.to_pandas()
    zero_rows = payouts[payouts["param_index"] == NO_BIN]
    n_entities = sum(
        len(r.entity_order()) for r in ResultReader(zero.store).runs(zero.run_ids)
    )
    assert len(zero_rows) == n_entities
    assert zero_rows["lower"].isna().all()
    assert (zero_rows["upper"] == 20.0).all()
    assert (zero_rows["value"] == 0.0).all()
    assert set(payouts["below_attachment"]) == {"zero"}
    assert table.column("lower").null_count == n_entities
    others = payouts[payouts["param_index"] != NO_BIN]
    assert others["lower"].notna().all()
    entry = next(
        f for f in report.manifest["files"] if f["path"] == "baseline.payouts.arrow"
    )
    lower = next(c for c in entry["columns"] if c["name"] == "lower")
    assert lower == {
        "name": "lower",
        "type": "double",
        "nulls": n_entities,
        "null_means": "-inf",
    }
    assert "null_means '-inf'" in report.manifest["rules"]["infinity"]
    strict_json(out / MANIFEST)


def test_other_infinities_are_refused() -> None:
    lower = site_export._Col("lower", "float", null="-inf", infinite="-inf")
    frame = pd.DataFrame({"lower": [1.0, np.inf]})
    with pytest.raises(BundleValueError, match="1 infinite value"):
        site_export._encode(frame, [lower], "t.arrow")
    plain = site_export._Col("value", "float")
    with pytest.raises(BundleValueError, match=r"'value' holds 1 infinite"):
        site_export._encode(pd.DataFrame({"value": [-np.inf]}), [plain], "t.arrow")
    with pytest.raises(BundleValueError, match="NaN or infinite"):
        site_export._json_bytes({"a": [1.0, float("inf")]}, "x.json")
    with pytest.raises(ValueError, match="needs null_means"):
        site_export._Col("x", "float", infinite="-inf")


# -- the NaN rule --------------------------------------------------------------


def test_nan_is_null_where_undefined_values_are_allowed() -> None:
    value = site_export._Col("value", "float", null="undefined")
    count = site_export._Col("n", "int", null="no bounds")
    frame = pd.DataFrame(
        {"value": [1.0, np.nan, 3.0], "n": pd.array([1, None, 3], dtype="Int64")}
    )
    table = site_export._encode(frame, [value, count], "t.arrow")
    assert table.column("value").to_pylist() == [1.0, None, 3.0]
    assert table.column("n").type == pa.int32()
    assert table.column("n").to_pylist() == [1, None, 3]
    info = site_export._column_info(table, [value, count])
    assert info[0] == {
        "name": "value",
        "type": "double",
        "nulls": 1,
        "null_means": "undefined",
    }


def test_nan_is_refused_elsewhere() -> None:
    plain = site_export._Col("value", "float")
    with pytest.raises(BundleValueError, match="1 NaN or null value"):
        site_export._encode(pd.DataFrame({"value": [np.nan, 1.0]}), [plain], "t.arrow")
    lower = site_export._Col("lower", "float", null="-inf", infinite="-inf")
    with pytest.raises(BundleValueError, match="NaN or null"):
        site_export._encode(pd.DataFrame({"lower": [np.nan]}), [lower], "t.arrow")
    text = site_export._Col("name", "str")
    with pytest.raises(BundleValueError, match="1 null value"):
        site_export._encode(pd.DataFrame({"name": ["a", None]}), [text], "t.arrow")
    with pytest.raises(BundleValueError, match=r"x\.y\[1\] is nan"):
        site_export._json_bytes({"x": {"y": [0.0, float("nan")]}}, "f.json")
    with pytest.raises(BundleValueError, match="not JSON"):
        site_export._json_bytes({"x": object()}, "f.json")
    with pytest.raises(BundleValueError, match="no column 'value'"):
        site_export._encode(pd.DataFrame({"v": [1.0]}), [plain], "t.arrow")


def test_integers_must_fit_32_bits() -> None:
    count = site_export._Col("n", "int")
    with pytest.raises(BundleValueError, match="not a 32-bit integer"):
        site_export._encode(pd.DataFrame({"n": [2**31]}), [count], "t.arrow")
    with pytest.raises(BundleValueError, match="not a 32-bit integer"):
        site_export._encode(pd.DataFrame({"n": [1.5]}), [count], "t.arrow")


def test_the_store_nulls_of_the_kpis_are_documented(swept: Swept) -> None:
    entry = next(
        f for f in swept.manifest["files"] if f["path"] == "baseline.kpis.arrow"
    )
    meaning = {c["name"]: c["null_means"] for c in entry["columns"]}
    assert meaning["value"].startswith("undefined")
    assert meaning["ci_low"].startswith("no confidence bounds")
    assert meaning["kpi"] is None
    nulls = {c["name"]: c["nulls"] for c in entry["columns"]}
    assert nulls["ci_low"] == entry["rows"]  # no bootstrap section in the toy


# -- the size budget -------------------------------------------------------------


def test_over_the_file_budget_is_an_error(toy: Fixture, tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with pytest.raises(BundleBudgetError, match="over the 1,000-byte file budget"):
        export(toy, out, budget=SizeBudget(max_file_bytes=1_000))
    assert not out.exists()


def test_over_the_bundle_budget_is_an_error(toy: Fixture, tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    with pytest.raises(BundleBudgetError, match="over the 10,000-byte bundle budget"):
        export(toy, out, budget=SizeBudget(max_bundle_bytes=10_000))
    assert not out.exists()
    report = export(toy, out, budget=SizeBudget(max_file_bytes=500_000))
    assert report.manifest["budget"]["max_file_bytes"] == 500_000


@pytest.mark.parametrize("bad", [0, -1, 1.5, True])
def test_the_budget_must_be_positive(bad: object) -> None:
    with pytest.raises(BundleError, match="positive integer"):
        SizeBudget(max_file_bytes=bad)  # pyright: ignore[reportArgumentType]


# -- missing, failed and refused runs -------------------------------------------------


def test_a_missing_run_is_an_error(toy: Fixture, tmp_path: Path) -> None:
    ids = list(toy.run_ids)
    ids[1] = "sha256:" + "0" * 64
    out = tmp_path / "bundle"
    with pytest.raises(MissingRunError, match="1 of 9 single runs are not in"):
        export_site(
            toy.config,
            ids,
            store=toy.store,
            out_dir=out,
            eventset=toy.eventset,
        )
    assert not out.exists()


def test_a_missing_sweep_point_is_an_error(swept: Swept, tmp_path: Path) -> None:
    gone = SweepRun("alpha", 0.7, "sha256:" + "1" * 64, single=2)
    with pytest.raises(MissingRunError, match="not in the result store"):
        export(swept.toy, tmp_path / "b", sweeps=(*swept.sweeps, gone))
    with pytest.raises(InconsistentRunsError, match="name single runs"):
        export(swept.toy, tmp_path / "b", sweeps=(SweepRun("alpha", 0.7, "x", 99),))
    with pytest.raises(InconsistentRunsError, match="no sweep points"):
        export(swept.toy, tmp_path / "b")
    with pytest.raises(InconsistentRunsError, match="9 single runs, got 2"):
        export_site(
            swept.toy.config,
            swept.toy.run_ids[:2],
            store=swept.toy.store,
            out_dir=tmp_path / "b",
            eventset=swept.toy.eventset,
        )
    assert not (tmp_path / "b").exists()


def test_sweep_parameters_are_checked(swept: Swept, tmp_path: Path) -> None:
    with pytest.raises(BundleError, match=r"sweeps \['n_clusters'\] are not exported"):
        export(
            swept.toy, tmp_path / "b", sweeps=swept.sweeps, parameters=["n_clusters"]
        )
    with pytest.raises(BundleError, match=r"has no sweep of \['beta'\]"):
        export(swept.toy, tmp_path / "b", sweeps=swept.sweeps, parameters=["beta"])
    report = export(
        swept.toy, tmp_path / "b", sweeps=swept.sweeps, parameters=["alpha", "alpha"]
    )
    assert list(report.manifest["runs"]["sweeps"]) == ["alpha"]


def test_failed_runs_are_listed_not_dropped(failed: Fixture, tmp_path: Path) -> None:
    out = tmp_path / "bundle"
    report = export(failed, out, include_events=True)
    cluster = failed.run_id("cluster", "mse")
    assert not report.ok
    assert [s.run_id for s in report.skipped] == [cluster]
    assert "design problems failed: *" in report.skipped[0].reason
    manifest = strict_json(out / MANIFEST)
    assert manifest["runs"]["skipped"] == [
        {"run_id": cluster, "reason": report.skipped[0].reason}
    ]
    runs = {r["run_id"]: r for r in strict_json(out / "runs.json")["runs"]}
    assert runs[cluster]["complete"] is False
    assert runs[cluster]["problems"][0]["error_type"] is not None
    for name in ("payouts", "kpis", "exceedance", "map"):
        table = arrow(out / f"baseline.{name}.arrow").to_pandas()
        assert cluster not in set(table["run_id"]), name
        assert len(table), name
    assert manifest["events"]["scopes"] == ["portfolio"]
    events = arrow(out / "baseline.events.arrow").to_pandas()
    assert set(events["scope"]) == {"portfolio"}


def test_a_kfold_config_without_pooled_kpis_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    data = config_dict(sample={"kind": "kfold", "k": 2})
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = load_config(path)
    with pytest.raises(KFoldRunsError, match="pooled out-of-sample KPIs"):
        export_site(
            config,
            [],
            store=ResultStore(tmp_path / "store"),
            out_dir=tmp_path / "b",
            eventset=make_eventset(),
        )
    single = config.single_runs()[1]  # sample.fold = 1
    with pytest.raises(KFoldRunsError, match="fixes k-fold fold 1"):
        export_site(
            single,
            [],
            store=ResultStore(tmp_path / "store"),
            out_dir=tmp_path / "b",
            eventset=make_eventset(),
            pooled_kpis=pd.DataFrame(),
        )
    assert not (tmp_path / "b").exists()


# -- k-fold configs: the pooled out-of-sample KPIs (MAR-208) ------------------------


@dataclass(frozen=True)
class Pooled:
    toy: Fixture
    pooled: PooledKpis
    out: Path
    report: ExportReport

    @property
    def manifest(self) -> dict[str, Any]:
        return strict_json(self.out / MANIFEST)


KFOLD_FILES = [
    "runs.json",
    "locations.json",
    "baseline.payouts.arrow",
    "baseline.pooled_kpis.arrow",
]


def pooled_fixture(directory: Path, **changes: Any) -> tuple[Fixture, PooledKpis]:  # noqa: ANN401
    """A k = 2 toy store and its pooled KPIs, as ``export-site`` computes them."""
    options: dict[str, Any] = {
        "sample": {"kind": "kfold", "k": 2},
        "bootstrap": {"seed": 0, "n_bootstrap": 20, "level": 0.9},
        "sweeps": [{"parameter": "alpha", "values": [0.5]}],
        **changes,
    }
    toy = build_fixture(directory, **options)
    return toy, pooled_kpis(toy.config, toy.store, toy.eventset, toy.run_ids)


@pytest.fixture(scope="module")
def kfold(tmp_path_factory: pytest.TempPathFactory) -> Pooled:
    toy, pooled = pooled_fixture(tmp_path_factory.mktemp("site-kfold"))
    out = tmp_path_factory.mktemp("site-kfold-bundle") / "bundle"
    report = export(toy, out, pooled_kpis=pooled.table, label="toy k-fold")
    return Pooled(toy=toy, pooled=pooled, out=out, report=report)


def test_kfold_bundle_holds_the_pooled_kpis(kfold: Pooled) -> None:
    manifest = read_bundle(kfold.out)
    assert kfold.report.ok
    assert [f["path"] for f in manifest["files"]] == KFOLD_FILES
    assert sorted(p.name for p in kfold.out.iterdir()) == sorted(
        [*KFOLD_FILES, MANIFEST]
    )
    for entry in manifest["files"]:
        data = (kfold.out / entry["path"]).read_bytes()
        assert entry["sha256"] == f"sha256:{hashlib.sha256(data).hexdigest()}"
    table = arrow(kfold.out / "baseline.pooled_kpis.arrow").to_pandas()
    expected = kfold.pooled.table
    assert len(table) == len(expected) == 9 * len(POOLED_KPIS)
    assert list(table.columns) == [c.name for c in site_export._POOLED_KPI_COLUMNS]
    assert set(POOLED_COLUMNS) <= set(table.columns)
    assert set(table["eval_split"]) == {POOLED_SPLIT}
    assert set(table["level"]) == {"portfolio"}
    assert set(table["k"]) == {2}
    assert table["scope_key"].tolist() == [
        ["individual", "cluster", "portfolio"][p] for p in table["scope_position"]
    ]
    np.testing.assert_array_equal(
        table["value"].to_numpy(dtype=float), expected["value"].to_numpy(dtype=float)
    )
    np.testing.assert_array_equal(
        table["ci_low"].to_numpy(dtype=float), expected["ci_low"].to_numpy(dtype=float)
    )
    assert table["run_ids"].tolist() == expected["run_ids"].astype(str).tolist()
    assert set(table["n_bootstrap"].dropna()) == {20}


def test_kfold_bundle_states_the_pooled_rule_and_what_is_left_out(
    kfold: Pooled,
) -> None:
    manifest = kfold.manifest
    ids = list(kfold.toy.run_ids)
    assert "map" not in manifest  # no map slice, so no map section (MAR-216)
    assert manifest["runs"]["baseline"] == ids
    assert manifest["runs"]["sweeps"] == {}
    assert manifest["runs"]["skipped"] == []
    assert manifest["sweeps_not_exported"] == ["alpha"]
    assert manifest["setup"]["split"] == {
        "kind": "kfold",
        "k": 2,
        "fold": None,
        "out_of_sample": True,
    }
    section = manifest["kfold"]
    assert section["k"] == 2
    assert section["eval_split"] == POOLED_SPLIT
    assert "not the mean of the per-fold KPIs" in section["rule"]
    assert section["not_pooled"] == []
    assert [d["run_ids"] for d in section["pooled"]] == [
        ids[i : i + 2] for i in range(0, len(ids), 2)
    ]
    assert section["pooled"][0] == {
        "scope_key": "individual",
        "objective": "mse",
        "run_ids": ids[:2],
    }
    assert set(section["not_exported"]) == {"kpis", "exceedance", "map", "sweeps"}
    runs = strict_json(kfold.out / "runs.json")["runs"]
    assert [r["fold"] for r in runs] == [0, 1] * 9
    assert all(r["calibration_split"] == "train" for r in runs)


def test_kfold_payouts_carry_the_fold(kfold: Pooled) -> None:
    payouts = arrow(kfold.out / "baseline.payouts.arrow").to_pandas()
    assert list(payouts.columns[:5]) == [
        "run_id",
        "scope",
        "scope_key",
        "objective",
        "fold",
    ]
    reader = ResultReader(kfold.toy.store)
    for i, run_id in enumerate(kfold.toy.run_ids):
        rows = payouts.loc[payouts["run_id"] == run_id]
        assert set(rows["fold"]) == {i % 2}
        stored = reader.run(run_id).payouts
        assert len(rows) == len(stored)
        np.testing.assert_allclose(
            np.sort(rows["value"].to_numpy(dtype=float)),
            np.sort(stored["value"].to_numpy(dtype=float)),
        )


def test_kfold_sweeps_and_events_are_refused(kfold: Pooled, tmp_path: Path) -> None:
    table = kfold.pooled.table
    with pytest.raises(BundleError, match="sweeps are not exported"):
        export(kfold.toy, tmp_path / "b", pooled_kpis=table, parameters=["alpha"])
    with pytest.raises(BundleError, match="events are not exported"):
        export(kfold.toy, tmp_path / "b", pooled_kpis=table, include_events=True)
    # A sweep point given anyway is not read: the bundle holds no sweeps.
    report = export(kfold.toy, tmp_path / "c", pooled_kpis=table, sweeps=(SWEEP_POINT,))
    assert report.manifest["runs"]["sweeps"] == {}
    assert not (tmp_path / "b").exists()


SWEEP_POINT = SweepRun(
    parameter="alpha",
    value=0.5,
    run_id="sha256:" + "0" * 64,
    single=0,
    subset_index=None,
    location_ids=None,
)


def test_a_pooled_table_that_does_not_fit_is_refused(
    kfold: Pooled, toy: Fixture, tmp_path: Path
) -> None:
    table = kfold.pooled.table
    out = tmp_path / "b"

    def refused(bad: pd.DataFrame, match: str) -> None:
        with pytest.raises(InconsistentRunsError, match=match):
            export(kfold.toy, out, pooled_kpis=bad)

    refused(table.drop(columns=["ci_low"]), "lacks the columns")
    refused(table.iloc[:0], "at least one")
    refused(table.assign(eval_split="test"), "pooled")
    refused(table.assign(k=3), r"k = \[3\] folds")
    refused(table.assign(run_ids="a;b"), "not the fold runs")
    first = str(table["run_ids"].iloc[0])
    refused(_where(table, table["run_ids"] != first), "lack individual x mse")
    refused(pd.concat([table, table.iloc[[0]]]), "more than once")
    refused(table.assign(scope_position=0), "another scope position")
    assert not out.exists()
    with pytest.raises(InconsistentRunsError, match="k-fold config only"):
        export(toy, out, pooled_kpis=table)


def _where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    return frame.loc[np.asarray(mask, dtype=bool)].reset_index(drop=True)


def test_kfold_designs_with_a_failed_fold_are_listed(tmp_path: Path) -> None:
    toy, pooled = pooled_fixture(
        tmp_path / "store",
        scopes=[
            {"kind": "portfolio"},
            {
                "kind": "cluster",
                "n_clusters": 4,
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
            },
        ],
        objectives=[{"kind": "mse"}],
        sweeps=[],
    )
    assert len(pooled.failed) == 1
    report = export(toy, tmp_path / "b", pooled_kpis=pooled.table)
    assert not report.ok
    cluster = list(toy.run_ids[2:])
    assert [s.run_id for s in report.skipped] == cluster
    manifest = strict_json(tmp_path / "b" / MANIFEST)
    assert manifest["kfold"]["pooled"] == [
        {"scope_key": "portfolio", "objective": "mse", "run_ids": list(toy.run_ids[:2])}
    ]
    [not_pooled] = manifest["kfold"]["not_pooled"]
    assert not_pooled["scope_key"] == "cluster"
    assert not_pooled["run_ids"] == cluster
    assert "folds failed" in not_pooled["reason"]
    payouts = arrow(tmp_path / "b" / "baseline.payouts.arrow").to_pandas()
    assert set(payouts["run_id"]) == set(toy.run_ids[:2])
    # A table that pools the failed design anyway is refused.
    forged = pooled.table.assign(run_ids=";".join(cluster), scope_position=1)
    with pytest.raises(InconsistentRunsError, match="whose folds failed"):
        export(toy, tmp_path / "c", pooled_kpis=pd.concat([pooled.table, forged]))


def test_another_setup_or_eventset_is_refused(toy: Fixture, tmp_path: Path) -> None:
    loaded = toy.config.model_copy(
        update={
            "pricing": CostOfCapitalConfig(kind="cost_of_capital", rate=0.1, q=0.99)
        }
    )
    with pytest.raises(InconsistentRunsError, match="another setup"):
        export_site(
            loaded,
            toy.run_ids,
            store=toy.store,
            out_dir=tmp_path / "b",
            eventset=toy.eventset,
        )
    with pytest.raises(EventSetMismatchError):
        export_site(
            toy.config,
            toy.run_ids,
            store=toy.store,
            out_dir=tmp_path / "b",
            eventset=make_eventset(),
        )
    assert not (tmp_path / "b").exists()


# -- events (opt-in) ------------------------------------------------------------------


def test_events_are_left_out_unless_asked_for(toy: Fixture, tmp_path: Path) -> None:
    plain = export(toy, tmp_path / "plain")
    assert not (tmp_path / "plain" / "baseline.events.arrow").exists()
    assert plain.manifest["events"]["included"] is False
    with_events = export(toy, tmp_path / "events", include_events=True)
    assert with_events.manifest["events"] == {
        "included": True,
        "scopes": ["individual", "cluster", "portfolio"],
        "note": site_export._EVENTS_NOTE,
    }
    events = arrow(tmp_path / "events" / "baseline.events.arrow").to_pandas()
    reader = ResultReader(toy.store)
    expected = 0
    for i, scope in enumerate(toy.config.scopes):
        first = reader.run(toy.run_ids[i * len(toy.config.objectives)])
        expected += len(
            entity_events(toy.eventset, scope.build(), first.problem_specs())
        )
    assert len(events) == expected
    assert set(events.columns) >= {"scope", "entity_id", "index", "loss", "rate"}


# -- the committed thesis-fixture bundles ---------------------------------------------


def check_committed_bundle(root: Path, config_path: Path) -> dict[str, Any]:
    """Check a committed bundle against its manifest and its config.

    Every file is the manifest's (size and SHA-256, via ``read_bundle`` and
    ``read_slice``), the directory holds no other file, the manifest's config
    hash and name are those of ``config_path``, and the data are labelled as
    thesis-fixture data under the event set's licence. Returns the manifest.
    """
    manifest = read_bundle(root)
    config = load_config(config_path)
    assert "thesis-fixture data" in manifest["label"]
    assert manifest["config"]["hash"] == config_hash(config)
    assert manifest["config"]["name"] == config.name
    assert manifest["eventset"]["licence"] == "CC-BY-4.0"
    files = [*(f["path"] for f in manifest["files"]), MANIFEST]
    assert sorted(p.name for p in root.iterdir()) == sorted(files)
    total = sum((root / f).stat().st_size for f in files)
    assert total < 300_000  # well under the repository's 500 kB file limit
    for entry in manifest["files"]:
        content = read_slice(root, entry["path"])
        if entry["format"] == "arrow":
            assert isinstance(content, pa.Table)
            assert arrow(root / entry["path"]).num_rows == entry["rows"]
        else:
            strict_json(root / entry["path"])
    return manifest


def test_the_committed_thesis_fixture_matches_its_manifest() -> None:
    manifest = check_committed_bundle(THESIS_FIXTURE, THESIS_CONFIG)
    assert manifest["config"]["name"] == "thesis"
    assert len(manifest["runs"]["baseline"]) == 9


def test_the_committed_thesis_fixture_has_no_per_site_split_of_joint_designs() -> None:
    # Review finding F8 (MAR-216): the thesis runs have no allocation-rule
    # rows, so only the individual scope has per-location numbers; the joint
    # scopes' rows are null, never the solver's split of a joint design.
    manifest = read_bundle(THESIS_FIXTURE)
    assert manifest["map"]["allocations"] == []
    sources = {
        (r["scope_key"], r["kpi_level"], r["allocation"])
        for r in manifest["map"]["runs"]
    }
    assert sources == {
        ("individual", "entity", "none"),
        ("cluster", None, None),
        ("portfolio", None, None),
    }
    table = arrow(THESIS_FIXTURE / "baseline.map.arrow").to_pandas()
    joint = table[table["scope"] != "individual"]
    assert len(joint) == 54
    assert joint["kpi_level"].isna().all()
    assert joint["allocation"].isna().all()
    numbers = ["expected_loss", "expected_payout", "expected_uncovered"]
    assert joint[numbers].isna().all().all()
    individual = table[table["scope"] == "individual"]
    assert (individual["kpi_level"] == "entity").all()
    assert (individual["allocation"] == "none").all()
    assert individual["expected_payout"].notna().all()


def test_the_committed_thesis_explorer_fixture_matches_its_config() -> None:
    # The one committed bundle with sweeps (MAR-210): the baseline and the
    # alpha and beta sweeps of site/fixtures/thesis_explorer.yaml, each sweep
    # point once, in the config's order, in every sweep table.
    manifest = check_committed_bundle(THESIS_EXPLORER_FIXTURE, THESIS_EXPLORER_CONFIG)
    config = load_config(THESIS_EXPLORER_CONFIG)
    assert manifest["config"]["name"] == "thesis-explorer"
    # In sample, unfiltered: a test fixture, not a bundle to publish.
    assert manifest["setup"]["split"] == {"kind": "full", "out_of_sample": False}
    assert manifest["split_filter"]["eval_split"] is None
    assert manifest["runs"]["skipped"] == []
    [baseline] = manifest["runs"]["baseline"]
    sweeps = {s.parameter: [float(v) for v in s.values] for s in config.sweeps}
    assert sweeps.keys() == {"alpha", "beta"}
    points = manifest["runs"]["sweeps"]
    assert {p: [pt["value"] for pt in points[p]] for p in points} == sweeps
    stems = ["baseline", *(f"sweep.{p}" for p in sweeps)]
    expected = [
        "runs.json",
        "locations.json",
        *(
            f"{stem}.{s}.arrow"
            for stem in stems
            for s in ("payouts", "kpis", "exceedance")
        ),
        "baseline.map.arrow",
    ]
    assert sorted(f["path"] for f in manifest["files"]) == sorted(expected)
    runs_json = strict_json(THESIS_EXPLORER_FIXTURE / "runs.json")
    runs = {r["run_id"] for r in runs_json["runs"]}
    for parameter, values in sweeps.items():
        run_of = {pt["value"]: pt["run_id"] for pt in points[parameter]}
        assert set(run_of.values()) <= runs
        # The baseline's own value is the baseline run.
        baseline_value = getattr(config.objectives[0], parameter)
        assert run_of[baseline_value] == baseline
        for kind in ("payouts", "kpis", "exceedance"):
            table = arrow(THESIS_EXPLORER_FIXTURE / f"sweep.{parameter}.{kind}.arrow")
            by_value = table.to_pandas().groupby("sweep_value")["run_id"].unique()
            assert {v: list(r) for v, r in by_value.items()} == {
                v: [run_of[v]] for v in values
            }
    # One location of the individual scope: its own entity rows on the map.
    assert manifest["map"]["allocations"] == []
    assert [(r["kpi_level"], r["allocation"]) for r in manifest["map"]["runs"]] == [
        ("entity", "none")
    ]
    location_map = arrow(THESIS_EXPLORER_FIXTURE / "baseline.map.arrow").to_pandas()
    assert list(location_map["location_id"]) == ["A1"]
    assert config.portfolio.location_ids == ("A1",)


# -- the split filter (MAR-213) -------------------------------------------------------


SPLIT_TABLES = [
    "baseline.kpis.arrow",
    "baseline.exceedance.arrow",
    "baseline.map.arrow",
    "sweep.alpha.kpis.arrow",
    "sweep.alpha.exceedance.arrow",
]


@dataclass(frozen=True)
class Held:
    """A holdout toy store with an alpha sweep, exported with and without filter."""

    toy: Fixture
    sweeps: tuple[SweepRun, ...]
    plain: Path
    test: Path
    report: ExportReport

    @property
    def manifest(self) -> dict[str, Any]:
        return strict_json(self.test / MANIFEST)


@pytest.fixture(scope="module")
def held(tmp_path_factory: pytest.TempPathFactory) -> Held:
    toy = build_fixture(
        tmp_path_factory.mktemp("site-holdout"),
        sample={"kind": "holdout", "train_fraction": 0.7},
        sweeps=[{"parameter": "alpha", "values": [0.5, 0.9]}],
    )
    run_sweeps(toy.config, store=toy.store, baseline=False)
    sweeps = sweep_runs(toy)
    out = tmp_path_factory.mktemp("site-holdout-bundles")
    export(toy, out / "plain", sweeps=sweeps)
    report = export(toy, out / "test", sweeps=sweeps, eval_split="test")
    return Held(
        toy=toy, sweeps=sweeps, plain=out / "plain", test=out / "test", report=report
    )


def test_the_split_filter_keeps_the_test_rows_only(held: Held) -> None:
    for name in SPLIT_TABLES:
        plain = arrow(held.plain / name).to_pandas()
        test = arrow(held.test / name).to_pandas()
        assert set(plain["eval_split"]) == {"train", "test"}, name
        assert set(test["eval_split"]) == {"test"}, name
        kept = plain.loc[plain["eval_split"] == "test"].reset_index(drop=True)
        pd.testing.assert_frame_equal(
            test.astype(str), kept.astype(str), check_dtype=False
        )


def test_the_split_filter_leaves_the_payouts_alone(held: Held) -> None:
    for name in ("baseline.payouts.arrow", "sweep.alpha.payouts.arrow"):
        assert (held.test / name).read_bytes() == (held.plain / name).read_bytes()
    runs = (held.test / "runs.json").read_bytes()
    assert runs == (held.plain / "runs.json").read_bytes()


def test_the_manifest_records_the_split_filter(held: Held) -> None:
    section = held.manifest["split_filter"]
    assert section["eval_split"] == "test"
    assert section["slices"] == ["kpis", "exceedance", "map"]
    assert section["rule"] == site_export._SPLIT_KEPT.format(split="test")
    removed: dict[str, int] = {}
    for name in SPLIT_TABLES:
        plain = arrow(held.plain / name).to_pandas()
        removed[name] = int((plain["eval_split"] != "test").sum())
        assert removed[name] > 0
    assert section["rows_removed"] == removed
    # What was removed is the train rows of the exported runs in the store.
    baseline = ResultReader(held.toy.store).runs(held.toy.run_ids)
    train = sum(
        int(np.count_nonzero(r.kpis["eval_split"].to_numpy() == "train"))
        for r in baseline
    )
    assert removed["baseline.kpis.arrow"] == train
    plain_section = strict_json(held.plain / MANIFEST)["split_filter"]
    assert plain_section == {
        "eval_split": None,
        "slices": [],
        "rows_removed": {},
        "rule": site_export._SPLIT_NONE,
    }
    assert read_bundle(held.test) == held.manifest
    assert held.manifest["setup"]["split"]["out_of_sample"] is True


def test_the_split_filter_shrinks_only_the_split_slices(held: Held) -> None:
    files = strict_json(held.plain / MANIFEST)["files"]
    plain = {f["path"]: f["bytes"] for f in files}
    assert [f.path for f in held.report.files] == list(plain)
    for file in held.report.files:
        if file.slice in ("kpis", "exceedance", "map"):
            assert file.bytes < plain[file.path], file.path
        else:
            assert file.bytes == plain[file.path], file.path


def test_an_unknown_split_is_refused(held: Held, tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="eval_split must be one of"):
        export(held.toy, tmp_path / "b", eval_split="pooled")
    assert site_export.EVAL_SPLITS == ("full", "train", "test")
    assert not (tmp_path / "b").exists()


def test_a_split_the_runs_lack_is_refused(
    toy: Fixture, held: Held, tmp_path: Path
) -> None:
    with pytest.raises(BundleError, match="no KPI rows of eval_split 'test'"):
        export(toy, tmp_path / "b", eval_split="test")  # a full sample
    with pytest.raises(BundleError, match="no KPI rows of eval_split 'full'"):
        export(held.toy, tmp_path / "b", sweeps=held.sweeps, eval_split="full")
    assert not (tmp_path / "b").exists()
    full = export(toy, tmp_path / "full", eval_split="full")
    assert full.manifest["split_filter"]["rows_removed"]["baseline.kpis.arrow"] == 0


def test_a_kfold_bundle_refuses_the_split_filter(kfold: Pooled, tmp_path: Path) -> None:
    with pytest.raises(BundleError, match="is k-fold"):
        export(
            kfold.toy,
            tmp_path / "b",
            pooled_kpis=kfold.pooled.table,
            eval_split="test",
        )
    assert not (tmp_path / "b").exists()
    assert kfold.manifest["split_filter"]["eval_split"] is None


# -- the map under an allocation rule (MAR-216) ---------------------------------------


def build_allocated(directory: Path, allocation: str, **changes: Any) -> Fixture:  # noqa: ANN401
    """A toy store whose runs were evaluated under an allocation rule.

    The config names the rule in ``evaluation.allocation`` (MAR-217), so the
    stored rows are what the runner writes under it.
    """
    evaluation = {**config_dict()["evaluation"], "allocation": allocation}
    return build_fixture(directory, evaluation=evaluation, **changes)


@dataclass(frozen=True)
class Allocated:
    """A holdout store evaluated under ``allocation="value"``, exported twice."""

    toy: Fixture
    plain: Path
    test: Path

    def manifest(self, which: str = "plain") -> dict[str, Any]:
        return strict_json(getattr(self, which) / MANIFEST)


@pytest.fixture(scope="module")
def allocated(tmp_path_factory: pytest.TempPathFactory) -> Allocated:
    toy = build_allocated(
        tmp_path_factory.mktemp("site-allocated"),
        "value",
        sample={"kind": "holdout", "train_fraction": 0.7},
    )
    out = tmp_path_factory.mktemp("site-allocated-bundles")
    export(toy, out / "plain")
    export(toy, out / "test", eval_split="test")
    return Allocated(toy=toy, plain=out / "plain", test=out / "test")


def stored_location_rows(toy: Fixture, run_id: str, level: str) -> pd.DataFrame:
    """The run's map KPIs at ``level``, one row per (eval_split, location)."""
    kpis = ResultReader(toy.store).run(run_id).kpis
    rows = kpis[(kpis["level"] == level) & kpis["kpi"].isin(site_export._MAP_KPIS)]
    wide = rows.pivot_table(
        index=["eval_split", "subject_id"], columns="kpi", values="value"
    )
    return wide.rename_axis(index=["eval_split", "location_id"], columns=None)


def assert_map_matches(
    map_: pd.DataFrame, toy: Fixture, run_id: str, level: str
) -> None:
    """Every map number of the run is its stored per-location KPI value."""
    mine = map_[map_["run_id"] == run_id].set_index(["eval_split", "location_id"])
    stored = stored_location_rows(toy, run_id, level)
    assert len(mine) == len(stored) > 0
    for kpi in site_export._MAP_KPIS:
        for key, value in stored[kpi].items():
            assert mine.loc[key, kpi] == value, (run_id, key, kpi)


def test_a_joint_scope_under_a_rule_exports_per_site_cover_labelled_with_it(
    allocated: Allocated,
) -> None:
    toy = allocated.toy
    map_ = arrow(allocated.plain / "baseline.map.arrow").to_pandas()
    assert set(map_["scope"]) == {"individual", "cluster", "portfolio"}
    assert set(map_["kpi_level"]) == {"location_by_value"}
    assert set(map_["allocation"]) == {"value"}
    assert set(map_["eval_split"]) == {"train", "test"}
    for run_id in toy.run_ids:
        assert_map_matches(map_, toy, run_id, "location_by_value")
        assert (map_["run_id"] == run_id).sum() == 2 * 3  # 2 splits x 3 sites
    # The portfolio scope's per-site payout is its one design problem's payout
    # split by insured value, not the solver's entity split.
    values = {"A1": 100.0, "A2": 60.0, "A3": 30.0}
    portfolio = map_[map_["scope"] == "portfolio"]
    value = portfolio["location_id"].astype(str).map(values)
    ratio = portfolio["expected_payout"] / value
    for _, group in ratio.groupby([portfolio["run_id"], portfolio["eval_split"]]):
        np.testing.assert_allclose(group, group.iloc[0], rtol=1e-12)
    manifest = allocated.manifest()
    assert manifest["map"]["allocations"] == ["value"]
    assert [r["run_id"] for r in manifest["map"]["runs"]] == list(toy.run_ids)
    for entry in manifest["map"]["runs"]:
        assert (entry["kpi_level"], entry["allocation"]) == (
            "location_by_value",
            "value",
        )


def test_the_split_filter_keeps_the_test_rows_of_the_allocated_map(
    allocated: Allocated,
) -> None:
    plain = arrow(allocated.plain / "baseline.map.arrow").to_pandas()
    test = arrow(allocated.test / "baseline.map.arrow").to_pandas()
    assert set(test["eval_split"]) == {"test"}
    assert set(test["kpi_level"]) == {"location_by_value"}
    kept = plain.loc[plain["eval_split"] == "test"].reset_index(drop=True)
    pd.testing.assert_frame_equal(test.astype(str), kept.astype(str), check_dtype=False)
    manifest = allocated.manifest("test")
    removed = manifest["split_filter"]["rows_removed"]["baseline.map.arrow"]
    assert removed == int((plain["eval_split"] != "test").sum()) > 0
    assert manifest["map"] == allocated.manifest()["map"]


def test_the_loss_rule_is_labelled_as_such(tmp_path: Path) -> None:
    toy = build_allocated(
        tmp_path / "store",
        "loss",
        scopes=[{"kind": "portfolio"}],
        objectives=[{"kind": "mse"}],
    )
    report = export(toy, tmp_path / "bundle")
    map_ = arrow(tmp_path / "bundle" / "baseline.map.arrow").to_pandas()
    assert set(map_["kpi_level"]) == {"location_by_loss"}
    assert set(map_["allocation"]) == {"loss"}
    assert_map_matches(map_, toy, toy.run_ids[0], "location_by_loss")
    assert report.manifest["map"]["allocations"] == ["loss"]
    assert report.manifest["map"]["runs"][0]["kpi_level"] == "location_by_loss"


def _exported(toy: Fixture, scope: str, kpis: pd.DataFrame) -> site_export._Exported:
    run = ResultReader(toy.store).run(toy.run_id(scope, "mse"))
    return site_export._Exported(replace(run, kpis=kpis), scope)


def _kpis(toy: Fixture, scope: str) -> pd.DataFrame:
    return ResultReader(toy.store).run(toy.run_id(scope, "mse")).kpis


def test_rows_at_the_plain_location_level_are_refused(allocated: Allocated) -> None:
    kpis = _kpis(allocated.toy, "portfolio")
    plain = kpis.assign(level=kpis["level"].replace("location_by_value", "location"))
    with pytest.raises(BundleError, match="level 'location', which is reserved"):
        site_export._map([_exported(allocated.toy, "portfolio", plain)])


def test_rows_of_several_rules_are_refused(allocated: Allocated) -> None:
    kpis = _kpis(allocated.toy, "portfolio")
    by_value = kpis[kpis["level"] == "location_by_value"]
    both = pd.concat(
        [kpis, by_value.assign(level="location_by_loss")], ignore_index=True
    )
    with pytest.raises(BundleError, match="several allocation rules"):
        site_export._map([_exported(allocated.toy, "portfolio", both)])


def test_allocation_rows_missing_a_location_are_refused(allocated: Allocated) -> None:
    kpis = _kpis(allocated.toy, "cluster")
    gap = (kpis["level"] == "location_by_value") & (kpis["subject_id"] == "A2")
    gap &= kpis["eval_split"] == "test"
    with pytest.raises(BundleError, match="rows for 5 of its 6"):
        site_export._map([_exported(allocated.toy, "cluster", _where(kpis, ~gap))])


def test_an_undefined_allocated_number_is_refused(allocated: Allocated) -> None:
    kpis = _kpis(allocated.toy, "portfolio")
    hole = (kpis["level"] == "location_by_value") & (kpis["kpi"] == "expected_payout")
    kpis = kpis.assign(value=kpis["value"].where(~hole))
    with pytest.raises(BundleValueError, match="undefined expected loss"):
        site_export._map([_exported(allocated.toy, "portfolio", kpis)])


def test_a_joint_scope_never_falls_back_to_its_entity_rows(toy: Fixture) -> None:
    # Not even when its entities cover one location each (the portfolio scope).
    for scope in ("portfolio", "cluster"):
        run = ResultReader(toy.store).run(toy.run_id(scope, "mse"))
        assert "entity" in set(run.kpis["level"])
        rows, sources = site_export._map([site_export._Exported(run, scope)])
        assert len(rows) == 3
        columns = ["kpi_level", "allocation", *site_export._MAP_KPIS]
        assert rows.loc[:, columns].isna().to_numpy().all()
        assert (sources[0]["kpi_level"], sources[0]["allocation"]) == (None, None)


# -- joint designs: the payouts' joint flag (MAR-222) ----------------------------


def joint_problems(run: RunResult) -> dict[str, bool]:
    """Per design problem of a run: whether it has more than one entity."""
    return {s.problem_id: len(s.entities) > 1 for s in run.problem_specs()}


def test_payout_rows_of_joint_designs_are_marked(swept: Swept) -> None:
    reader = ResultReader(swept.toy.store)
    for name in ("baseline.payouts.arrow", "sweep.alpha.payouts.arrow"):
        payouts = arrow(swept.out / name)
        assert payouts.schema.field("joint").type == pa.bool_()
        assert payouts.column("joint").null_count == 0
        frame = payouts.to_pandas()
        # the toy's cluster scope has two clusters: joint, like the portfolio
        assert set(frame["scope"]) == {"individual", "cluster", "portfolio"}
        for (run_id, problem_id), rows in frame.groupby(["run_id", "problem_id"]):
            expected = joint_problems(reader.run(str(run_id)))[str(problem_id)]
            assert set(rows["joint"]) == {expected}, (name, run_id, problem_id)
        assert frame["joint"].tolist() == (frame["scope"] != "individual").tolist()
        entry = next(f for f in swept.manifest["files"] if f["path"] == name)
        assert entry["columns"][-1] == {
            "name": "joint",
            "type": "bool",
            "nulls": 0,
            "null_means": None,
        }


def test_the_manifest_records_the_joint_designs(swept: Swept) -> None:
    section = swept.manifest["joint"]
    assert section["rule"] == site_export._JOINT_RULE
    assert section["caption"] == JOINT_CAPTION
    runs = strict_json(swept.out / "runs.json")["runs"]
    reader = ResultReader(swept.toy.store)
    expected = [r["run_id"] for r in runs if is_joint_design(reader.run(r["run_id"]))]
    assert section["runs"] == expected
    assert {r["scope"] for r in runs if r["run_id"] in expected} == {
        "cluster",
        "portfolio",
    }
    assert swept.manifest["format_version"] == 1


def test_a_separately_calibrated_cluster_scope_is_not_joint(tmp_path: Path) -> None:
    cluster = {
        "kind": "cluster",
        "n_clusters": 2,
        "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
    }
    toy = build_fixture(
        tmp_path / "store",
        scopes=[{"kind": "individual"}, {**cluster, "joint": False}, cluster],
        objectives=[{"kind": "mse"}],
    )
    report = export(toy, tmp_path / "bundle")
    payouts = arrow(tmp_path / "bundle" / "baseline.payouts.arrow").to_pandas()
    flags = payouts.groupby("scope_key")["joint"].unique()
    assert {k: list(v) for k, v in flags.items()} == {
        "individual": [False],
        "cluster_separate": [False],
        "cluster": [True],
    }
    assert report.manifest["joint"]["runs"] == [toy.run_ids[2]]


def test_kfold_payouts_are_marked_too(kfold: Pooled) -> None:
    payouts = arrow(kfold.out / "baseline.payouts.arrow").to_pandas()
    assert payouts["joint"].tolist() == (payouts["scope"] != "individual").tolist()
    section = kfold.manifest["joint"]
    assert section["caption"] == JOINT_CAPTION
    reader = ResultReader(kfold.toy.store)
    assert section["runs"] == [
        r for r in kfold.toy.run_ids if is_joint_design(reader.run(r))
    ]
    assert len(section["runs"]) == 12  # cluster and portfolio, 3 objectives, 2 folds


def test_boolean_columns_follow_the_rules() -> None:
    flag = site_export._Col("joint", "bool")
    table = site_export._encode(
        pd.DataFrame({"joint": [True, np.bool_(False)]}), [flag], "t.arrow"
    )
    assert table.column("joint").type == pa.bool_()
    assert table.column("joint").to_pylist() == [True, False]
    with pytest.raises(BundleValueError, match="1 null value"):
        site_export._encode(pd.DataFrame({"joint": [True, None]}), [flag], "t.arrow")
    with pytest.raises(BundleValueError, match="not a boolean"):
        site_export._encode(pd.DataFrame({"joint": [1, 0]}), [flag], "t.arrow")
    nullable = site_export._Col("joint", "bool", null="unknown")
    table = site_export._encode(
        pd.DataFrame({"joint": [True, None]}), [nullable], "t.arrow"
    )
    assert table.column("joint").to_pylist() == [True, None]
