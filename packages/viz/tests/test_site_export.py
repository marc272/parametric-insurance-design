"""Tests of the site bundle export (MAR-200): format, rules, budget, errors.

The bundles are exported from the ``toy`` stores of ``conftest.py`` (plus a
small sweep store built here) and read back with pyarrow and :mod:`json`,
independently of :func:`~parametric_insurance_design_viz.site_export.read_bundle`.
The committed thesis-fixture bundle under ``site/fixtures/thesis`` is checked
against its manifest and against the parity config it came from.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
from parametric_insurance_design_viz.reader import ResultReader, entity_events
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


def test_map_has_per_location_numbers_where_present(swept: Swept) -> None:
    map_ = arrow(swept.out / "baseline.map.arrow").to_pandas()
    columns = [c for c in swept.manifest["files"] if c["path"] == "baseline.map.arrow"]
    meaning = {c["name"]: c["null_means"] for c in columns[0]["columns"]}
    for scope, level in [("individual", "entity"), ("portfolio", "entity")]:
        rows = map_[map_["scope"] == scope]
        assert set(rows["kpi_level"]) == {level}
        assert rows["expected_loss"].notna().all()
        assert sorted(set(rows["location_id"])) == ["A1", "A2", "A3"]
    cluster = map_[map_["scope"] == "cluster"]
    clustered = cluster.groupby(["run_id", "entity_id"])["location_id"].transform(
        "size"
    )
    multi = cluster[clustered > 1]
    assert len(multi)
    assert multi["kpi_level"].isna().all()
    assert multi["expected_payout"].isna().all()
    assert meaning["expected_payout"].startswith("not available per location")
    toy = swept.toy
    run = ResultReader(toy.store).run(toy.run_id("individual", "mse"))
    expected = run.kpis[
        (run.kpis["level"] == "entity") & (run.kpis["kpi"] == "expected_loss")
    ].set_index("subject_id")["value"]
    mine = map_[map_["run_id"] == run.run_id].set_index("location_id")["expected_loss"]
    assert {str(k): v for k, v in mine.items()} == expected.to_dict()


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
    with pytest.raises(MissingRunError, match="1 of 9 runs are not in the result"):
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


def test_a_kfold_config_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    data = config_dict(sample={"kind": "kfold", "k": 2})
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = load_config(path)
    with pytest.raises(KFoldRunsError, match="k-fold sample"):
        export_site(
            config,
            [],
            store=ResultStore(tmp_path / "store"),
            out_dir=tmp_path / "b",
            eventset=make_eventset(),
        )


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


# -- the committed thesis-fixture bundle ----------------------------------------------


def test_the_committed_thesis_fixture_matches_its_manifest() -> None:
    manifest = read_bundle(THESIS_FIXTURE)
    assert "thesis-fixture data" in manifest["label"]
    assert manifest["config"]["hash"] == config_hash(load_config(THESIS_CONFIG))
    assert manifest["config"]["name"] == "thesis"
    assert manifest["eventset"]["licence"] == "CC-BY-4.0"
    assert len(manifest["runs"]["baseline"]) == 9
    files = [*(f["path"] for f in manifest["files"]), MANIFEST]
    assert sorted(p.name for p in THESIS_FIXTURE.iterdir()) == sorted(files)
    total = sum((THESIS_FIXTURE / f).stat().st_size for f in files)
    assert total < 300_000  # well under the repository's 500 kB file limit
    for entry in manifest["files"]:
        content = read_slice(THESIS_FIXTURE, entry["path"])
        if entry["format"] == "arrow":
            assert isinstance(content, pa.Table)
            assert content.num_rows == entry["rows"]
        else:
            strict_json(THESIS_FIXTURE / entry["path"])
