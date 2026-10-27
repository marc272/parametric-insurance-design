"""The adapter regenerates the thesis event-loss table (MAR-20).

Two groups:

- CI-safe (no IRIS): the committed parity fixture
  (``parity/tests/data/thesis_eventset``) matches the pinned digests in
  ``tests/data/thesis_eventset_digest.json``, the comparison helpers of
  ``scripts/thesis_adapter_parity.py`` behave, and the committed adapter
  section of the parity report (``parity/analysis/adapter.md``) agrees with
  the digest file.
- Gated on the IRIS catalogue: the adapter builds the thesis EventSet from
  ``configs/thesis.yaml`` (about 30 s) and must equal the fixture bit for bit:
  event IDs and order, years, rates, draw IDs, locations, ``index`` and
  ``loss``. The catalogue is the config's (``data/iris`` at the repository
  root, written by ``pixi run iris``) or the file named by the environment
  variable ``IRIS_CATALOGUE``. Without it the test is skipped with that
  reason; CI never downloads IRIS.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design_climada.config import load_config

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parents[1]
SCRIPT = PACKAGE / "scripts" / "thesis_adapter_parity.py"
SECTION = REPO / "parity" / "analysis" / "adapter.md"
CATALOGUE_ENV = "IRIS_CATALOGUE"


def _load_script() -> ModuleType:
    name = "thesis_adapter_parity"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses need the module registered
    spec.loader.exec_module(module)
    return module


tap = _load_script()


@pytest.fixture(scope="module")
def fixture() -> EventSet:
    return EventSet.from_parquet(tap.FIXTURE)


@pytest.fixture(scope="module")
def pinned() -> dict:
    return tap.load_digest()


# -- CI-safe: the pinned digests --------------------------------------------


def test_fixture_matches_the_pinned_digest(fixture: EventSet, pinned: dict) -> None:
    ours = tap.digests(fixture)
    assert ours["shape"] == pinned["shape"] == [6057, 9]
    assert ours["location_ids"] == pinned["location_ids"]
    assert ours["sha256"] == pinned["sha256"]
    assert set(pinned["sha256"]) == {
        "event_id",
        "year",
        "rate",
        "draw_id",
        "index",
        "loss",
    }


def test_digest_file_names_the_thesis_source(fixture: EventSet, pinned: dict) -> None:
    source = f"sha256:{pinned['source_csv_sha256']}"
    assert pinned["source_csv_sha256"] == tap.SOURCE_CSV_SHA256
    assert source in fixture.metadata.provenance.source_checksums.values()
    assert tap.digest_record(fixture) == pinned


def test_digest_is_sensitive_to_one_bit(fixture: EventSet) -> None:
    loss = fixture.loss.copy()
    loss[100, 3] = np.nextafter(loss[100, 3], np.inf)
    changed = dataclasses.replace(fixture, loss=loss)
    before, after = tap.digests(fixture)["sha256"], tap.digests(changed)["sha256"]
    assert before["loss"] != after["loss"]
    assert before["index"] == after["index"]


# -- CI-safe: the comparison helpers ----------------------------------------


def test_compare_with_itself_is_identical(fixture: EventSet) -> None:
    checks = tap.compare(fixture, fixture)
    assert [c.name for c in checks] == [
        "Event IDs and order",
        "Years",
        "Rates",
        "Draw IDs",
        "Scenario IDs",
        "Locations",
        "Index (wind, m/s)",
        "Loss (USD)",
    ]
    assert all(c.identical and c.within_tolerance for c in checks)
    assert tap.metadata_differences(fixture, fixture) == []


def test_matrix_check_tolerance() -> None:
    base = np.array([[0.0, 10.0], [20.0, 0.0]])
    assert tap.matrix_check("m", base, base.copy()).identical
    near = base.copy()
    near[0, 1] *= 1 + 5e-7
    check = tap.matrix_check("m", near, base)
    assert not check.identical
    assert check.within_tolerance
    assert "1 differ" in check.detail
    far = base.copy()
    far[1, 0] *= 1 + 2e-6
    assert not tap.matrix_check("m", far, base).within_tolerance
    zero = base.copy()
    zero[1, 1] = 1e-12  # zero in the fixture, not in ours: outside any tolerance
    check = tap.matrix_check("m", zero, base)
    assert not check.within_tolerance
    assert "1 cells zero in only one" in check.detail
    assert not tap.matrix_check("m", base[:1], base).within_tolerance


def test_matrix_check_tells_negative_zero_apart() -> None:
    base = np.zeros((1, 2))
    check = tap.matrix_check("m", -base, base)
    assert not check.identical  # bit for bit, -0.0 is not 0.0
    assert check.within_tolerance


def test_event_order_is_part_of_the_comparison(fixture: EventSet) -> None:
    events = fixture.events.iloc[::-1].reset_index(drop=True)
    flipped = dataclasses.replace(
        fixture, events=events, index=fixture.index[::-1], loss=fixture.loss[::-1]
    )
    checks = {c.name: c for c in tap.compare(flipped, fixture)}
    assert not checks["Event IDs and order"].identical
    assert checks["Event IDs and order"].detail == "same values, different order"
    assert not checks["Loss (USD)"].within_tolerance


def test_metadata_differences_name_nested_fields(fixture: EventSet) -> None:
    meta = dataclasses.replace(fixture.metadata, scenario="other", licence="x")
    other = dataclasses.replace(fixture, metadata=meta)
    assert tap.metadata_differences(other, fixture) == ["licence", "scenario"]
    index = dataclasses.replace(fixture.metadata.index, definition="other")
    other = dataclasses.replace(
        fixture, metadata=dataclasses.replace(fixture.metadata, index=index)
    )
    assert tap.metadata_differences(other, fixture) == ["index.definition"]


# -- CI-safe: the committed report section ----------------------------------


def test_committed_section_agrees_with_the_digest_file(pinned: dict) -> None:
    text = SECTION.read_text(encoding="utf-8")
    assert text.startswith(
        "## Adapter: the CLIMADA pipeline regenerates the thesis event-loss table\n"
    )
    assert "**Result: bit-identical.**" in text
    assert "**differs**" not in text
    for value in pinned["sha256"].values():
        assert f"`{value[:16]}…` | same | same |" in text
    assert "CLIMADA 6.0.1" in text
    assert "`max_dist_inland_km` 1000 km" in text


# -- Gated on IRIS: the build itself ----------------------------------------


@pytest.fixture(scope="module")
def catalogue() -> Path:
    value = os.environ.get(CATALOGUE_ENV)
    path = Path(value) if value else load_config(tap.CONFIG).catalogue
    if not path.is_file():
        pytest.skip(
            f"IRIS catalogue not found at {path}: run `pixi run iris` or set "
            f"{CATALOGUE_ENV} to the merged IRIS_NA_10000Y_merged.txt to rebuild "
            "the thesis EventSet (about 30 s)"
        )
    return path


def test_adapter_regenerates_the_thesis_eventset(catalogue: Path, pinned: dict) -> None:
    parity = tap.run(catalogue=catalogue)
    failed = [f"{c.name}: {c.detail}" for c in parity.checks if not c.identical]
    assert parity.bit_identical, failed
    ours = tap.digests(parity.ours)
    assert ours["shape"] == pinned["shape"]
    assert ours["location_ids"] == pinned["location_ids"]
    assert ours["sha256"] == pinned["sha256"]
    assert parity.result.skipped == ()
    assert "**Result: bit-identical.**" in tap.render(parity)
    assert parity.build_record["n_storms_within_radius"] == 6057
    # MAR-94: both the adapter's build and the fixture record CC BY 4.0.
    assert parity.ours.metadata.licence == "CC-BY-4.0"
    assert parity.fixture.metadata.licence == "CC-BY-4.0"
