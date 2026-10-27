"""Tests of the parity report generator (MAR-67), on the mini golden."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import harness
import pytest
import report
from harness import Finding, ParityResult

from parametric_insurance_design.experiment.store import ResultStore

INJECTED = {("ind", "A1", 2): 1e-3}  # A1's E_Uncovered, 0.1 % off


def _result(
    mini_golden: Any,  # noqa: ANN401
    store: ResultStore,
    **kwargs: Any,  # noqa: ANN401
) -> ParityResult:
    golden = harness.load_golden(
        mini_golden.results, mini_golden.kpis, mini_golden.objectives
    )
    return harness.compare(golden, store, **kwargs)


def _only(result: ParityResult) -> Finding:
    (finding,) = result.findings
    return finding


def test_clean_report(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store())
    text = report.render(result)
    assert text.startswith("# Parity report\n")
    assert text.endswith("\n")
    for heading in (
        "## Setup",
        "## Overview",
        "## Summary by comparison group",
        "## Findings",
        "## Payout differences (informational)",
        "## Store runs without a golden record (informational)",
    ):
        assert f"\n{heading}\n" in text
    assert "No findings." in text
    assert "`benchmarking_kpis.csv`: `" in text  # golden checksum
    assert "| KPI values | 42 | 42 | 42 | 0 | 0 |" in text
    assert "| Objective values | 2 | 2 | 2 | 0 | 0 |" in text
    assert "| Cluster assignments | 2 | 2 | 2 | 0 | 0 |" in text
    assert report.render(result) == text  # no timestamp: deterministic


def test_summary_has_one_row_per_group(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store(kpi_offsets=INJECTED))
    summary = report.summary_by_group(result)
    assert list(zip(summary["source"], summary["approach"], strict=True)) == [
        ("alpha_sweep", "cluster_optimization"),
        ("budget_loading_sweep", "individual_optimization"),
        ("single_run", "cluster_optimization"),
        ("single_run", "individual_optimization"),
    ]
    row = summary.iloc[3]
    assert (row["kpi_match"], row["kpi_compared"], row["kpi_golden"]) == (17, 18, 18)
    assert row["kpi_max_rel_error"] == pytest.approx(1e-3)
    assert (row["findings"], row["unexplained"]) == (1, 1)
    assert list(summary["records"]) == [1, 1, 1, 1]
    assert list(summary["runs_matched"]) == [1, 1, 1, 1]
    overview = report.overview(result)
    kpi = overview[overview["comparison"] == "KPI values"].iloc[0]
    assert (kpi["match"], kpi["mismatch"]) == (41, 1)


def test_injected_mismatch_appears_with_room_for_an_explanation(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store(kpi_offsets=INJECTED))
    finding = _only(result)
    text = report.render(result)
    assert "1 findings, 0 of them explained, 1 not yet." in text
    line = next(x for x in text.splitlines() if finding.id in x)
    assert "| kpi |" in line
    assert "A1 / E_Uncovered" in line
    assert "| 20 | 20.02 | 1.00e-03 |" in line
    assert line.endswith(f"| {report.PENDING} |")


def test_explanations_by_id_and_by_glob(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = _result(mini_golden, make_store(kpi_offsets=INJECTED))
    finding = _only(result)
    assert finding.path == (
        "kpi/individual_optimization/pure_uncovered_loss_minimization/single_run/"
        "budget_loading=1, n_bins=2/A1/E_Uncovered"
    )
    glob = {"kpi/individual_optimization/*": "Injected | on purpose."}
    assert report.explanation_for(finding, glob) == "Injected | on purpose."
    both = {"kpi/*": "glob text", finding.id: "id text"}
    assert report.explanation_for(finding, both) == "id text"  # id wins
    assert report.explanation_for(finding, {"kpi/cluster*": "no"}) is None
    assert report.explanation_for(finding, {"kpi": "not a glob"}) is None

    text = report.render(result, explanations=glob, notes="Mini golden run.")
    assert "Mini golden run." in text
    assert "1 findings, 1 of them explained, 0 not yet." in text
    assert "Injected \\| on purpose." in text  # pipes escaped in the table
    assert report.PENDING not in text


def test_load_explanations(tmp_path: Path) -> None:
    good = tmp_path / "good.yaml"
    good.write_text(
        "P-0123456789: one\n'kpi/*/weighted_cvar_minimization/*': >-\n  two\n",
        encoding="utf-8",
    )
    assert report.load_explanations(good) == {
        "P-0123456789": "one",
        "kpi/*/weighted_cvar_minimization/*": "two",
    }
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert report.load_explanations(empty) == {}
    for name, text in (("list", "- a\n- b\n"), ("blank", "P-1: ''\n"), ("bad", "a: [")):
        bad = tmp_path / f"{name}.yaml"
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(report.ExplanationsError):
            report.load_explanations(bad)
    with pytest.raises(report.ExplanationsError):
        report.load_explanations(tmp_path / "missing.yaml")


def test_missing_runs_and_unmatched_runs_in_the_report(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, _, dropped = mini_specs()
    result = _result(mini_golden, make_store([individual, dropped]))
    text = report.render(result)
    assert "| Cluster assignments | 2 | 0 | 0 | 0 | 2 |" in text
    assert text.count("| missing_run |") == 2
    summary = report.summary_by_group(result)
    cluster = summary[summary["approach"] == "cluster_optimization"]
    assert list(cluster["runs_matched"]) == [0, 0]

    sources_only = _result(mini_golden, make_store(), sources=["single_run"])
    text = report.render(sources_only)
    assert "- Golden records compared: single_run." in text
    assert "| budget_loading_sweep | individual | mse | 1 |" in text


def test_main_writes_the_report_and_checks_explanations(
    tmp_path: Path,
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = make_store(kpi_offsets=INJECTED)
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
        "--fixed",
        "noise_level=0.3",
        "--fixed",
        "noise_kind=heteroscedastic",
    ]
    assert report.main(args) == 0
    assert out.is_file()
    assert "`noise_level` = 0.3, and" not in out.read_text(encoding="utf-8")
    assert '`noise_level` = 0.3, `noise_kind` = "heteroscedastic"' in out.read_text(
        encoding="utf-8"
    )
    assert "1 findings, 1 without an explanation" in capsys.readouterr().out
    assert report.main([*args, "--check"]) == 1

    explanations = tmp_path / "explanations.yaml"
    explanations.write_text("'kpi/*': injected by the test\n", encoding="utf-8")
    assert report.main([*args, "--check", "--explanations", str(explanations)]) == 0
    assert "injected by the test" in out.read_text(encoding="utf-8")


def test_main_rejects_bad_arguments(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        report.main(["--store", str(tmp_path / "nowhere")])
    with pytest.raises(SystemExit):
        report.main(["--store", str(tmp_path), "--fixed", "noise_level"])
