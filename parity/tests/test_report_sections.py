"""Tests of the report sections added for MAR-68, on the mini golden.

Matched runs with their ``config_hash``, the objective-value table with the
derivation of each golden value, decompressed-content checksums checked
against a manifest, setup notes, appendices, and the new CLI options.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import harness
import report

from parametric_insurance_design.experiment.store import ResultStore


def _result(mini_golden: Any, store: ResultStore) -> harness.ParityResult:  # noqa: ANN401
    golden = harness.load_golden(
        mini_golden.results, mini_golden.kpis, mini_golden.objectives
    )
    return harness.compare(golden, store)


def test_matched_runs_carry_the_config_hash(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store())
    runs = result.matched_runs
    assert len(runs) == 4
    assert set(runs["config_hash"]) == {"sha256:" + "0" * 64}
    assert list(runs["candidates"]) == [1, 1, 1, 1]
    text = report.render(result)
    assert "\n## Matched runs\n" in text
    assert f"`sha256:{'0' * 64}`" in text


def test_objective_section_lists_the_derivation(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store())
    assert list(result.objectives.columns[:6]) == [
        "source",
        "approach",
        "method",
        "parameters",
        "problem_id",
        "derivation",
    ]
    text = report.render(result)
    section = text.split("\n## Objective values\n", 1)[1].split("\n## ", 1)[0]
    assert section.count("| match |") == 2

    golden = harness.load_golden(mini_golden.results, mini_golden.kpis)
    without = report.render(harness.compare(golden, make_store()))
    assert "No golden objective table was given" in without


def test_content_checksums_and_manifest(
    tmp_path: Path,
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store())
    name, digest = harness.content_sha256(mini_golden.kpis)
    assert result.golden_content[name] == digest
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"golden": {name: {"sha256": digest}}}))
    text = report.render(result, manifest=manifest)
    assert f"`{name}`: `{digest}` (matches `manifest.json`)" in text
    assert "(not in `manifest.json`)" in text  # the other two tables
    assert "(matches" not in report.render(result, manifest=None)


def test_setup_notes_and_appendices(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store())
    text = report.render(
        result,
        setup_notes=["Solver policy: thesis.", " "],
        appendices=["## Appendix: A\n\nbody\n", ""],
    )
    setup = text.split("\n## Setup\n", 1)[1].split("\n## ", 1)[0]
    assert "\n- Solver policy: thesis." in setup
    assert text.endswith("## Appendix: A\n\nbody\n")


def test_cli_notes_file_appendix_and_setup_note(
    tmp_path: Path,
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    store = make_store()
    notes = tmp_path / "notes.md"
    notes.write_text("From a file.", encoding="utf-8")
    appendix = tmp_path / "appendix.md"
    appendix.write_text("## Appendix: X\n\ntext", encoding="utf-8")
    out = tmp_path / "REPORT.md"
    args = [
        "--store",
        str(store.root),
        "--results",
        str(mini_golden.results),
        "--kpis",
        str(mini_golden.kpis),
        "--objectives",
        str(mini_golden.objectives),
        "--out",
        str(out),
        "--notes",
        "Inline.",
        "--notes-file",
        str(notes),
        "--appendix",
        str(appendix),
        "--setup-note",
        "Policy note.",
        "--manifest",
        str(tmp_path / "none.json"),
    ]
    assert report.main(args) == 0
    text = out.read_text(encoding="utf-8")
    assert "Inline.\n\nFrom a file." in text
    assert "\n- Policy note.\n" in text
    assert text.endswith("## Appendix: X\n\ntext\n")
