"""The compact form of the parity report (MAR-69), on the mini golden."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import harness
import report

from parametric_insurance_design.experiment.store import ResultStore

# A1's E_Uncovered 0.1 % off and A1's objective 1 % off: two findings of the
# individual record, plus the failed A2 of the budget-loading record.
KPI = {("ind", "A1", 2): 1e-3}
OBJECTIVE = {"A1": 1e-2}


def _result(
    mini_golden: Any,  # noqa: ANN401
    store: ResultStore,
) -> harness.ParityResult:
    golden = harness.load_golden(
        mini_golden.results, mini_golden.kpis, mini_golden.objectives
    )
    return harness.compare(golden, store)


def _ids(text: str) -> set[str]:
    return set(re.findall(r"^\| `(P-[0-9a-f]{10})` \|", text, flags=re.MULTILINE))


def test_compact_lists_the_same_findings_grouped_by_record(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(
        mini_golden, make_store(kpi_offsets=KPI, objective_offsets=OBJECTIVE)
    )
    assert len(result.findings) >= 2
    explanations = {"kpi/individual_optimization/*": "Kpi text."}
    full = report.render(result, explanations=explanations)
    compact = report.render(result, explanations=explanations, compact=True)
    assert _ids(compact) == _ids(full) == {f.id for f in result.findings}
    # One heading per record; the explanation cell names a label.
    records = {(f.key.label(), f.key.parameter_text()) for f in result.findings}
    headings = re.findall(r"^### .+$", compact.split("## Findings")[1], re.MULTILINE)
    assert len(headings) >= len(records)
    kpi = next(f for f in result.findings if f.kind is harness.FindingKind.KPI)
    row = next(line for line in compact.splitlines() if f"`{kpi.id}`" in line)
    assert row.endswith("| E1 |")
    assert "Kpi text." not in row
    # The text appears once, in the Explanations section.
    assert compact.count("Kpi text.") == 1
    assert "**E1** (`kpi/individual_optimization/*`, 1 findings): Kpi text." in (
        compact
    )
    # The overview is the same in both forms.
    overview = full.split("## Overview")[1].split("\n## ")[0]
    assert overview in compact


def test_compact_objective_table_lists_mismatches_only(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    clean = _result(mini_golden, make_store())
    text = report.render(clean, compact=True)
    section = text.split("## Objective values")[1].split("\n## ")[0]
    assert "Compact form: the 2 of 2 golden objective values that match are" in (
        section
    )
    assert "| Record |" not in section  # nothing to list

    off = _result(mini_golden, make_store(objective_offsets=OBJECTIVE))
    text = report.render(off, compact=True)
    section = text.split("## Objective values")[1].split("\n## ")[0]
    rows = [line for line in section.splitlines() if line.startswith("| ")]
    assert rows[0].startswith("| Record |")
    assert all("| match |" not in line for line in rows)
    assert any("| mismatch |" in line for line in rows)


def test_unexplained_findings_stay_pending(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store(kpi_offsets=KPI))
    text = report.render(result, compact=True)
    assert report.PENDING in text
    assert "## Explanations" in text
    assert "\n\nNone.\n" in text.split("## Explanations")[1].split("\n## ")[0] + "\n"


def test_explanation_key_and_labels(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store(kpi_offsets=KPI))
    finding = next(f for f in result.findings if f.kind is harness.FindingKind.KPI)
    explanations = {
        "unused/*": "Unused.",
        "kpi/*": "Glob.",
        finding.id: "By id.",
    }
    assert report.explanation_key_for(finding, explanations) == finding.id
    assert report.explanation_for(finding, explanations) == "By id."
    del explanations[finding.id]
    assert report.explanation_key_for(finding, explanations) == "kpi/*"
    labels = report.explanation_labels(result, explanations)
    assert labels == {"kpi/*": "E1"}  # unused keys get no label


def test_cli_compact(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    tmp_path: Path,
) -> None:
    store = make_store(kpi_offsets=KPI)
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
        "--compact",
    ]
    assert report.main(args) == 0
    assert "## Explanations" in out.read_text()
    assert report.main([*args, "--check"]) == 1
