"""Tests for the thesis EventSet parity fixture (MAR-9).

Two groups:

- Checks of the committed fixture and golden tables against the manifest and
  the checksums below. They need nothing outside this repository.
- Checks against the thesis repository: recompute the source checksums and
  row/column counts, regenerate the EventSet and compare. They run when
  ``PARITY_THESIS_REPO`` points at a checkout of
  ``parametric-insurance-framework`` and are skipped, with that reason,
  otherwise.
"""

from __future__ import annotations

import dataclasses
import gzip
import importlib.util
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.eventset import EventSet

PARITY_DIR = Path(__file__).resolve().parents[1]
SCRIPT = PARITY_DIR / "scripts" / "convert_thesis_eventset.py"
MANIFEST = PARITY_DIR / "manifest.json"
EVENTSET_DIR = PARITY_DIR / "tests" / "data" / "thesis_eventset"
GOLDEN_DIR = PARITY_DIR / "golden"

# Expected values, stated independently of the manifest so that a manifest
# rewritten together with the fixture still fails here.
SOURCE_CSV = "data/output/climada_transformed_loss_data.csv"
SOURCE_CSV_SHA256 = "8513f5fefdcf6686207df575e6a89d576e5ed935f71b652b4045229caf23ff68"
SOURCE_CSV_ROWS = 6057
SOURCE_CSV_COLUMNS = 22  # Event_ID, Year, 2 portfolio aggregates, 9 x (Wind, Loss)
N_LOCATIONS = 9
N_YEARS = 10_000
N_ALL_ZERO_ROWS = 4762
GOLDEN = {
    "full_optimization_results.csv": (
        "98fe6556ae7b0cc9e5c48e1633ad24860cc8518047617ff2e0bbb18ae114fd31",
        1551,
        12,
    ),
    "benchmarking_kpis.csv": (
        "6e2b9d515a3812e35391233926afb4aa118ac797a19ad99d823bd40a3ac669d6",
        1776,
        17,
    ),
}


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("convert_thesis_eventset", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


conv = _load_script()


@pytest.fixture(scope="module")
def manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def eventset() -> EventSet:
    return EventSet.from_parquet(EVENTSET_DIR)


# -- committed fixture (no thesis repository needed) --------------------------


def test_manifest_records_source_checksum_and_counts(manifest: dict) -> None:
    source = manifest["sources"][SOURCE_CSV]
    assert source["sha256"] == SOURCE_CSV_SHA256
    assert (source["rows"], source["columns"]) == (SOURCE_CSV_ROWS, SOURCE_CSV_COLUMNS)


def test_fixture_files_match_manifest(manifest: dict) -> None:
    expected = manifest["eventset"]["files_sha256"]
    present = sorted(p.name for p in EVENTSET_DIR.iterdir() if p.is_file())
    assert present == sorted(expected)
    for name, digest in expected.items():
        assert conv.sha256_file(EVENTSET_DIR / name) == digest, name


def test_fixture_row_and_column_counts(eventset: EventSet, manifest: dict) -> None:
    assert eventset.n_rows == SOURCE_CSV_ROWS
    assert eventset.n_locations == N_LOCATIONS
    # Every CSV column is accounted for: 4 leading + (Wind, Loss) per asset.
    assert 4 + 2 * eventset.n_locations == SOURCE_CSV_COLUMNS
    assert eventset.index.shape == eventset.loss.shape == (SOURCE_CSV_ROWS, 9)
    assert len(eventset.to_long()) == SOURCE_CSV_ROWS * N_LOCATIONS
    assert eventset.location_ids == [f"A{k}" for k in range(1, 10)]
    entry = manifest["eventset"]
    assert (entry["n_rows"], entry["n_locations"], entry["n_years"]) == (
        SOURCE_CSV_ROWS,
        N_LOCATIONS,
        N_YEARS,
    )
    assert entry["n_values_rows"] == SOURCE_CSV_ROWS * N_LOCATIONS


def test_fixture_semantics(eventset: EventSet) -> None:
    events = eventset.events
    meta = eventset.metadata
    assert meta.n_years == N_YEARS
    np.testing.assert_array_equal(eventset.rates, np.full(SOURCE_CSV_ROWS, 1e-4))
    assert (events["draw_id"].to_numpy() == 0).all()
    assert events["event_id"].is_unique
    assert events["year"].between(0, N_YEARS - 1).all()
    # Event IDs are NA_<year>_<tc>, as written by the thesis CLIMADA engine.
    assert (
        events["event_id"].str.split("_").str[1] == events["year"].astype(str)
    ).all()
    assert (meta.index.unit, meta.loss.unit, meta.loss.currency) == (
        "m/s",
        "USD",
        "USD",
    )
    assert meta.hazard.name == "IRIS"
    assert meta.licence == "CC-BY-4.0"
    assert meta.filters == ()
    # Zero-loss rows are kept, not dropped.
    all_zero = ((eventset.index == 0) & (eventset.loss == 0)).all(axis=1)
    assert int(all_zero.sum()) == N_ALL_ZERO_ROWS
    # CLIMADA stores winds below its 17.5 m/s threshold as 0.
    positive = eventset.index[eventset.index > 0]
    assert positive.min() >= 17.5
    # A loss never exceeds the insured value.
    assert (eventset.loss <= eventset.locations["value"].to_numpy()).all()


def test_fixture_records_source_checksum(eventset: EventSet) -> None:
    checksums = eventset.metadata.provenance.source_checksums
    key = conv.SOURCE_KEY_PREFIX + SOURCE_CSV
    assert checksums[key] == f"sha256:{SOURCE_CSV_SHA256}"


def test_locations_come_from_the_thesis_config(eventset: EventSet) -> None:
    loc = eventset.locations.set_index("location_id")
    assert loc.loc["A1", "name"] == "Brickell_HighRise"
    assert (loc.loc["A1", "lat"], loc.loc["A1", "lon"]) == (25.7617, -80.1918)
    assert loc["value"].to_numpy().sum() == 156_500_000.0
    assert (loc["impf_TC"].to_numpy() == 1).all()


@pytest.mark.parametrize("name", sorted(GOLDEN))
def test_golden_tables(name: str, manifest: dict) -> None:
    digest, rows, columns = GOLDEN[name]
    path = GOLDEN_DIR / f"{name}.gz"
    assert conv.sha256_gzip_content(path) == digest
    table = pd.read_csv(path)
    assert table.shape == (rows, columns)
    entry = manifest["golden"][name]
    assert (entry["sha256"], entry["rows"], entry["columns"]) == (digest, rows, columns)
    assert entry["stored_as"] == f"golden/{name}.gz"


# -- conversion logic on a small synthetic thesis layout ----------------------


def _write_fake_thesis(root: Path, frame: pd.DataFrame | None = None) -> Path:
    (root / "configs").mkdir(parents=True)
    (root / "data" / "output").mkdir(parents=True)
    (root / "src" / "outputs" / "optimization_results").mkdir(parents=True)
    (root / "src" / "outputs" / "benchmarking_results").mkdir(parents=True)
    (root / conv.EXPERIMENT_CONFIG).write_text(
        "ASSETS:\n"
        "  A1: {name: One, lat: 25.0, lon: -80.0, value: 100, impf_TC: 1}\n"
        "  A2: {name: Two, lat: 26.0, lon: -81.0, value: 200, impf_TC: 1}\n",
        encoding="utf-8",
    )
    (root / conv.GLOBAL_SETTINGS).write_text("N_YEARS: 50\n", encoding="utf-8")
    if frame is None:
        frame = pd.DataFrame(
            {
                "Event_ID": ["NA_0_1", "NA_3_0", "NA_7_2"],
                "Year": [0, 3, 7],
                "Portfolio_Total_Loss": [15.0, 0.0, 60.0],
                "Portfolio_Max_Wind": [30.0, 0.0, 45.5],
                "A1_Wind": [30.0, 0.0, 45.5],
                "A1_Loss": [10.0, 0.0, 40.0],
                "A2_Wind": [25.0, 0.0, 20.0],
                "A2_Loss": [5.0, 0.0, 20.0],
            }
        )
    frame.to_csv(root / conv.EVENT_LOSS_CSV, index=False)
    for rel in conv.GOLDEN_SOURCES.values():
        (root / rel).write_text('a,b\n1,"x\ny"\n2,z\n', encoding="utf-8")
    return root


def test_convert_small_layout(tmp_path: Path) -> None:
    repo = _write_fake_thesis(tmp_path / "thesis")
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    result = conv.convert(repo, created_at=stamp)
    es = result.eventset
    assert (es.n_rows, es.n_locations, es.metadata.n_years) == (3, 2, 50)
    np.testing.assert_array_equal(es.rates, np.full(3, 1 / 50))
    np.testing.assert_array_equal(es.index[:, 0], [30.0, 0.0, 45.5])
    np.testing.assert_array_equal(es.loss[:, 1], [5.0, 0.0, 20.0])
    assert es.events["event_id"].tolist() == ["NA_0_1", "NA_3_0", "NA_7_2"]
    assert es.metadata.provenance.created_at == stamp
    csv_digest = conv.sha256_file(repo / conv.EVENT_LOSS_CSV)
    assert result.source_checksums[conv.EVENT_LOSS_CSV] == f"sha256:{csv_digest}"
    assert result.source_counts[conv.EVENT_LOSS_CSV] == (3, 8)
    assert result.checks["Portfolio_Total_Loss"]["rows_differing"] == 0
    assert result.checks["Portfolio_Max_Wind"]["rows_differing"] == 0


def test_inconsistent_aggregates_are_reported(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        {
            "Event_ID": ["NA_0_1"],
            "Year": [0],
            "Portfolio_Total_Loss": [7.5],
            "Portfolio_Max_Wind": [29.0],
            "A1_Wind": [30.0],
            "A1_Loss": [10.0],
            "A2_Wind": [25.0],
            "A2_Loss": [5.0],
        }
    )
    repo = _write_fake_thesis(tmp_path / "thesis", frame)
    checks = conv.convert(repo).checks
    assert checks["Portfolio_Max_Wind"]["rows_differing"] == 1
    assert checks["Portfolio_Total_Loss"]["rows_differing"] == 1
    assert checks["Portfolio_Total_Loss"]["ratios_sum_to_column_in_differing_rows"] == [
        2.0
    ]


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        pytest.param(
            lambda f: f.drop(columns=["A2_Loss"]), "expected layout", id="missing"
        ),
        pytest.param(
            lambda f: f[[*f.columns[:4], "A2_Wind", "A2_Loss", "A1_Wind", "A1_Loss"]],
            "expected layout",
            id="reordered",
        ),
        pytest.param(
            lambda f: f.assign(Event_ID=["NA_0_1", "NA_0_1", "NA_7_2"]),
            "repeat",
            id="duplicate-id",
        ),
        pytest.param(
            lambda f: f.assign(Year=[0, 4, 7]), "Event_ID year", id="year-mismatch"
        ),
    ],
)
def test_bad_layout_raises(
    tmp_path: Path, mutate: Callable[[pd.DataFrame], pd.DataFrame], message: str
) -> None:
    repo = _write_fake_thesis(tmp_path / "thesis")
    frame = pd.read_csv(repo / conv.EVENT_LOSS_CSV)
    mutate(frame).to_csv(repo / conv.EVENT_LOSS_CSV, index=False)
    with pytest.raises(conv.ConversionError, match=message):
        conv.convert(repo)


def test_bad_configs_raise(tmp_path: Path) -> None:
    repo = _write_fake_thesis(tmp_path / "thesis")
    (repo / conv.GLOBAL_SETTINGS).write_text("N_YEARS: 0\n", encoding="utf-8")
    with pytest.raises(conv.ConversionError, match="N_YEARS"):
        conv.convert(repo)
    (repo / conv.GLOBAL_SETTINGS).write_text("N_YEARS: 50\n", encoding="utf-8")
    (repo / conv.EXPERIMENT_CONFIG).write_text(
        "ASSETS:\n  A1: {name: One, lat: 25.0, lon: -80.0}\n", encoding="utf-8"
    )
    with pytest.raises(conv.ConversionError, match="lacks value, impf_TC"):
        conv.convert(repo)
    (repo / conv.EXPERIMENT_CONFIG).write_text("- not a mapping\n", encoding="utf-8")
    with pytest.raises(conv.ConversionError, match="YAML mapping"):
        conv.convert(repo)


def test_resolve_thesis_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(conv.THESIS_REPO_ENV, raising=False)
    with pytest.raises(conv.ConversionError, match="no thesis repository"):
        conv.resolve_thesis_repo(None)
    with pytest.raises(conv.ConversionError, match="does not hold"):
        conv.resolve_thesis_repo(tmp_path)
    repo = _write_fake_thesis(tmp_path / "thesis")
    monkeypatch.setenv(conv.THESIS_REPO_ENV, str(repo))
    assert conv.resolve_thesis_repo(None) == repo.resolve()


def test_main_writes_fixture_golden_and_manifest(tmp_path: Path) -> None:
    repo = _write_fake_thesis(tmp_path / "thesis")
    out = tmp_path / "out"
    args = [
        "--thesis-repo",
        str(repo),
        "--eventset-dir",
        str(out / "es"),
        "--golden-dir",
        str(out / "golden"),
        "--manifest",
        str(out / "manifest.json"),
        "--created-at",
        "2026-01-01T00:00:00+00:00",
    ]
    assert conv.main(args) == 0
    written = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert written["thesis_commit"] is None  # not a git checkout
    assert written["eventset"]["n_rows"] == 3
    for name, entry in written["golden"].items():
        gz = out / "golden" / f"{name}.gz"
        assert (
            gzip.decompress(gz.read_bytes())
            == (repo / entry["thesis_path"]).read_bytes()
        )
        assert (entry["rows"], entry["columns"]) == (2, 2)
    first = (out / "golden" / "benchmarking_kpis.csv.gz").read_bytes()
    with pytest.raises(FileExistsError):
        conv.main(args)
    assert conv.main([*args, "--overwrite"]) == 0
    # Gzip output is reproducible (mtime 0, no file name).
    assert (out / "golden" / "benchmarking_kpis.csv.gz").read_bytes() == first
    es = EventSet.from_parquet(out / "es")
    assert es.n_rows == 3


# -- against the thesis repository (local only) -------------------------------


@pytest.fixture(scope="module")
def thesis_repo() -> Path:
    value = os.environ.get(conv.THESIS_REPO_ENV)
    if not value:
        pytest.skip(
            f"{conv.THESIS_REPO_ENV} is not set; set it to a checkout of "
            f"{conv.THESIS_REPO_URL} to recompute the source checksums and "
            "regenerate the fixture"
        )
    repo = Path(value).expanduser()
    if not (repo / SOURCE_CSV).is_file():
        pytest.fail(f"{conv.THESIS_REPO_ENV}={value} does not hold {SOURCE_CSV}")
    return repo


def test_thesis_source_checksums(thesis_repo: Path, manifest: dict) -> None:
    assert conv.sha256_file(thesis_repo / SOURCE_CSV) == SOURCE_CSV_SHA256
    for rel, entry in manifest["sources"].items():
        assert conv.sha256_file(thesis_repo / rel) == entry["sha256"], rel
    for name, (digest, _, _) in GOLDEN.items():
        rel = conv.GOLDEN_SOURCES[name]
        assert conv.sha256_file(thesis_repo / rel) == digest, rel


def test_thesis_source_counts(thesis_repo: Path) -> None:
    frame = pd.read_csv(thesis_repo / SOURCE_CSV)
    assert frame.shape == (SOURCE_CSV_ROWS, SOURCE_CSV_COLUMNS)


def test_thesis_golden_bytes_identical(thesis_repo: Path) -> None:
    for name, rel in conv.GOLDEN_SOURCES.items():
        stored = gzip.decompress((GOLDEN_DIR / f"{name}.gz").read_bytes())
        assert stored == (thesis_repo / rel).read_bytes(), name


def test_thesis_regeneration_matches_fixture(
    thesis_repo: Path, eventset: EventSet
) -> None:
    committed = eventset.metadata.provenance
    regenerated = conv.convert(thesis_repo, created_at=committed.created_at).eventset
    # The producer version may move on; the data and the sources may not.
    provenance = dataclasses.replace(
        regenerated.metadata.provenance, producer_version=committed.producer_version
    )
    regenerated = dataclasses.replace(
        regenerated,
        metadata=dataclasses.replace(regenerated.metadata, provenance=provenance),
    )
    assert regenerated.equals(eventset)
    # Bit-identical to the thesis notebook's parse of the CSV.
    frame = pd.read_csv(thesis_repo / SOURCE_CSV)
    winds = frame[[f"A{k}_Wind" for k in range(1, 10)]].to_numpy()
    losses = frame[[f"A{k}_Loss" for k in range(1, 10)]].to_numpy()
    assert np.array_equal(eventset.index, winds)
    assert np.array_equal(eventset.loss, losses)
