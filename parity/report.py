r"""Parity report generator: writes ``parity/REPORT.md`` (MAR-67, SPEC §7 F-06).

The report renders a :class:`harness.ParityResult`:

1. **Setup**: the store, the golden files and their SHA256, the
   tolerances and the matching settings, so every number has its setup.
2. **Overview**: one row per comparison (KPI values, objective values,
   payout vectors, cluster assignments) with golden, compared, matching and
   mismatching counts.
3. **Summary by comparison group**: one row per golden ``Source`` x
   ``Approach`` x ``Method``.
4. **Findings**: every gap the harness found, with a stable id and an
   explanation column. The parity gate (MAR-18) needs every gap explained.
5. **Payout differences** (informational): the largest payout-level
   differences. They are reported, not asserted, because LP optima can be
   non-unique.
6. **Store runs without a golden record** (informational).

Explanations
    The report is generated, so explanations live in a separate YAML file
    (a mapping) and are merged in on every run. A key is either a finding id
    (``P-3f2a9c01be``) or a glob over the finding's path,
    ``kind/approach/method/source/parameters/subject/item`` (e.g.
    ``kpi/integrated_portfolio_optimization/weighted_cvar_minimization/*``).
    An exact id wins; otherwise the first matching glob, in file order.

Command line, from the repository root::

    uv run python parity/report.py --store results/thesis \
        --explanations parity/explanations.yaml --out parity/REPORT.md

``--check`` exits with status 1 if a finding has no explanation.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Final

import pandas as pd
import yaml
from harness import (
    GOLDEN_DIR,
    KPIS_FILE,
    RESULTS_FILE,
    Finding,
    FindingKind,
    HarnessError,
    ParityResult,
    compare,
    load_golden,
)

from parametric_insurance_design.experiment.store import ResultStore

__all__ = [
    "DEFAULT_REPORT",
    "PENDING",
    "ExplanationsError",
    "explanation_for",
    "load_explanations",
    "main",
    "overview",
    "render",
    "summary_by_group",
    "write_report",
]

DEFAULT_REPORT: Final[Path] = Path(__file__).resolve().parent / "REPORT.md"
"""Where the parity report goes."""

PENDING: Final[str] = "_Not explained yet._"
"""Explanation cell of a finding without an explanation."""

TOP_PAYOUT_DIFFS: Final[int] = 20
"""How many payout differences the informational section lists."""

_GLOB_CHARS: Final[frozenset[str]] = frozenset("*?[")


class ExplanationsError(HarnessError):
    """The explanations file is not a mapping of strings to strings."""


# --------------------------------------------------------------------------
# Explanations
# --------------------------------------------------------------------------


def load_explanations(path: str | Path) -> dict[str, str]:
    """Read an explanations file.

    Parameters
    ----------
    path : str or pathlib.Path
        A YAML mapping from finding id or path glob to explanation text.
        An empty file is an empty mapping.

    Returns
    -------
    dict of str to str
        The explanations, in file order.

    Raises
    ------
    ExplanationsError
        If the file cannot be read or is not a mapping of strings.
    """
    file = Path(path)
    try:
        data = yaml.safe_load(file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ExplanationsError(f"cannot read explanations {file}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict) or not all(
        isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in data.items()
    ):
        raise ExplanationsError(
            f"{file} must map finding ids or path globs to non-empty text"
        )
    return {str(k): str(v).strip() for k, v in data.items()}


def explanation_for(finding: Finding, explanations: Mapping[str, str]) -> str | None:
    """Return the explanation of a finding, if any.

    Parameters
    ----------
    finding : harness.Finding
        The finding.
    explanations : mapping of str to str
        Finding id or path glob to text (module docstring).

    Returns
    -------
    str or None
        The text for the finding's id, else for the first glob that matches
        its path, else None.
    """
    if finding.id in explanations:
        return explanations[finding.id]
    for pattern, text in explanations.items():
        if _GLOB_CHARS & set(pattern) and fnmatch.fnmatchcase(finding.path, pattern):
            return text
    return None


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


def _cell(value: object) -> str:
    """Return Markdown table cell text: no pipes or line breaks."""
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    lines = [
        "| " + " | ".join(_cell(h) for h in header) + " |",
        "|" + "|".join("---" for _ in header) + "|",
    ]
    lines.extend("| " + " | ".join(_cell(v) for v in row) + " |" for row in rows)
    return "\n".join(lines)


def _sci(value: object) -> str:
    """Return an error in short scientific form; empty if undefined."""
    if not isinstance(value, int | float) or math.isnan(value):
        return ""
    return "inf" if math.isinf(value) else f"{value:.2e}"


Row = dict[str, Any]
Group = tuple[str, str, str]


def _rows(frame: pd.DataFrame) -> list[Row]:
    """Return the rows of a result table as dicts."""
    return [{str(k): v for k, v in r.items()} for r in frame.to_dict("records")]


def _max(rows: Sequence[Row], column: str) -> float:
    """Return the largest defined value of a column; NaN if there is none."""
    values = [
        float(r[column])
        for r in rows
        if isinstance(r[column], int | float) and not math.isnan(r[column])
    ]
    return max(values) if values else math.nan


def _count(rows: Sequence[Row], *statuses: str) -> int:
    return sum(r["status"] in statuses for r in rows)


def overview(result: ParityResult) -> pd.DataFrame:
    """Return one row per comparison: counts and the largest error.

    Parameters
    ----------
    result : harness.ParityResult
        The comparison.

    Returns
    -------
    pandas.DataFrame
        Columns ``comparison``, ``golden``, ``compared``, ``match``,
        ``mismatch``, ``not_compared``, ``max_error`` and ``rule``. For payout
        vectors, ``match`` counts the vectors compared, ``mismatch`` those
        with another shape or other bin edges, and ``max_error`` is the
        largest level difference over the largest golden level.
    """
    tol = result.tolerances
    out: list[Row] = []
    for name, frame, rule in (
        (
            "KPI values",
            result.kpis,
            f"relative error <= {tol.kpi_rtol:g} (atol {tol.kpi_atol:g})",
        ),
        (
            "Objective values",
            result.objectives,
            f"relative error <= {tol.objective_rtol:g} (atol {tol.objective_atol:g})"
            if result.objectives_available
            else "not in the golden data",
        ),
    ):
        rows = _rows(frame)
        compared = [r for r in rows if r["status"] != "missing"]
        out.append(
            {
                "comparison": name,
                "golden": len(rows),
                "compared": len(compared),
                "match": _count(rows, "match"),
                "mismatch": _count(rows, "mismatch"),
                "not_compared": _count(rows, "missing"),
                "max_error": _max(compared, "rel_error"),
                "rule": rule,
            }
        )
    payouts = _rows(result.payouts)
    out.append(
        {
            "comparison": "Payout vectors",
            "golden": len(payouts),
            "compared": _count(payouts, "compared", "shape"),
            "match": _count(payouts, "compared"),
            "mismatch": _count(payouts, "shape"),
            "not_compared": _count(payouts, "missing"),
            "max_error": _max(payouts, "max_rel_diff"),
            "rule": "levels: largest difference reported, not asserted; bin edges "
            f"within {tol.edge_atol:g}",
        }
    )
    clusters = _rows(result.clusters)
    out.append(
        {
            "comparison": "Cluster assignments",
            "golden": len(clusters),
            "compared": _count(clusters, "match", "mismatch"),
            "match": _count(clusters, "match"),
            "mismatch": _count(clusters, "mismatch"),
            "not_compared": _count(clusters, "missing"),
            "max_error": math.nan,
            "rule": "cluster id to members, exactly",
        }
    )
    return pd.DataFrame(out)


def _group(row: Row) -> Group:
    return (str(row["source"]), str(row["approach"]), str(row["method"]))


def summary_by_group(
    result: ParityResult, explanations: Mapping[str, str] | None = None
) -> pd.DataFrame:
    """Return one row per comparison group (source, approach, method).

    Parameters
    ----------
    result : harness.ParityResult
        The comparison.
    explanations : mapping of str to str, optional
        For the count of unexplained findings.

    Returns
    -------
    pandas.DataFrame
        Columns ``source``, ``approach``, ``method``, ``records``,
        ``runs_matched``, ``kpi_match``, ``kpi_compared``, ``kpi_golden``,
        ``kpi_max_rel_error``, ``payouts_compared``, ``payouts_golden``,
        ``payout_max_abs_diff``, ``payout_max_rel_diff``, ``clusters_match``,
        ``clusters_compared``, ``objective_max_rel_error``, ``findings`` and
        ``unexplained``.
    """
    explanations = explanations or {}
    tables = {
        "kpis": _rows(result.kpis),
        "payouts": _rows(result.payouts),
        "objectives": _rows(result.objectives),
        "clusters": _rows(result.clusters),
    }
    records: dict[Group, set[str]] = defaultdict(set)
    by_group: dict[str, dict[Group, list[Row]]] = {}
    for name, rows in tables.items():
        grouped: dict[Group, list[Row]] = defaultdict(list)
        for row in rows:
            grouped[_group(row)].append(row)
            records[_group(row)].add(str(row["parameters"]))
        by_group[name] = grouped
    unmatched: dict[Group, int] = defaultdict(int)
    findings: dict[Group, int] = defaultdict(int)
    unexplained: dict[Group, int] = defaultdict(int)
    for f in result.findings:
        group = f.key.group
        records[group].add(f.key.parameter_text())
        findings[group] += 1
        if explanation_for(f, explanations) is None:
            unexplained[group] += 1
        if f.kind in (FindingKind.MISSING_RUN, FindingKind.AMBIGUOUS_RUN):
            unmatched[group] += 1

    out: list[Row] = []
    for group in sorted(records):
        kpis = by_group["kpis"].get(group, [])
        payouts = by_group["payouts"].get(group, [])
        objectives = by_group["objectives"].get(group, [])
        clusters = by_group["clusters"].get(group, [])
        compared_kpis = [r for r in kpis if r["status"] != "missing"]
        compared_payouts = [r for r in payouts if r["status"] == "compared"]
        compared_objectives = [r for r in objectives if r["status"] != "missing"]
        out.append(
            {
                "source": group[0],
                "approach": group[1],
                "method": group[2],
                "records": len(records[group]),
                "runs_matched": len(records[group]) - unmatched[group],
                "kpi_match": _count(kpis, "match"),
                "kpi_compared": len(compared_kpis),
                "kpi_golden": len(kpis),
                "kpi_max_rel_error": _max(compared_kpis, "rel_error"),
                "payouts_compared": len(compared_payouts),
                "payouts_golden": len(payouts),
                "payout_max_abs_diff": _max(compared_payouts, "max_abs_diff"),
                "payout_max_rel_diff": _max(compared_payouts, "max_rel_diff"),
                "clusters_match": _count(clusters, "match"),
                "clusters_compared": _count(clusters, "match", "mismatch"),
                "objective_max_rel_error": _max(compared_objectives, "rel_error"),
                "findings": findings[group],
                "unexplained": unexplained[group],
            }
        )
    return pd.DataFrame(out)


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def _setup(result: ParityResult) -> str:
    tol = result.tolerances
    fixed = result.fixed_parameters
    sources = result.sources
    matching = (
        "- Matching: a golden record (approach, method, source, parameters) "
        "matches the store run with the mapped scope and objective whose "
        "`runs.parameters` hold the same `alpha`, `beta`, `budget_loading`, "
        "`n_bins` and `n_clusters` (an empty golden value: the run has no such "
        f"parameter; relative tolerance {tol.parameter_rtol:g})"
    )
    if fixed:
        matching += ", and " + ", ".join(
            f"`{k}` = {json.dumps(v)}" for k, v in fixed.items()
        )
    matching += ". " + (
        "The `source` tag must agree."
        if result.strict_source
        else "The `source` tag need not agree: the runner's cache keeps the tag a "
        "run was first written with."
    )
    lines = [
        "## Setup",
        "",
        f"- Result store: `{result.store_root}`, {result.n_store_runs} committed "
        f"runs, {result.n_store_runs - len(result.unmatched_runs)} of them matched "
        "by a golden record.",
        "- Golden files (SHA256 of the files as read):",
        *(f"  - `{name}`: `{digest}`" for name, digest in result.golden_files.items()),
        "- Golden records compared: "
        + ("all sources." if sources is None else ", ".join(sources) + "."),
        matching,
        f"- KPIs: basis `{result.basis}`, eval split `full`, fold 0, VaR and CVaR "
        f"at beta {result.evaluation_beta:g}. A KPI matches if |ours - golden| <= "
        f"{tol.kpi_rtol:g} |golden| + {tol.kpi_atol:g}; both undefined is a match.",
        "- Objective values: "
        + (
            f"|ours - golden| <= {tol.objective_rtol:g} |golden| + "
            f"{tol.objective_atol:g}."
            if result.objectives_available
            else "the golden data hold none, so none are compared."
        ),
        "- Payout vectors: the largest absolute difference of the levels is "
        "reported, not asserted (LP optima can be non-unique). Bin edges must "
        f"agree within {tol.edge_atol:g}.",
        "- Cluster assignments: the map from cluster id to members must be equal.",
    ]
    return "\n".join(lines)


def _overview_md(result: ParityResult, explanations: Mapping[str, str]) -> str:
    rows = [
        (
            r["comparison"],
            r["golden"],
            r["compared"],
            r["match"],
            r["mismatch"],
            r["not_compared"],
            _sci(r["max_error"]),
            r["rule"],
        )
        for r in _rows(overview(result))
    ]
    n = len(result.findings)
    explained = sum(
        explanation_for(f, explanations) is not None for f in result.findings
    )
    verdict = (
        "No findings."
        if n == 0
        else f"{n} findings, {explained} of them explained, {n - explained} not yet."
    )
    header = (
        "Comparison",
        "Golden",
        "Compared",
        "Match",
        "Mismatch",
        "Not compared",
        "Largest rel. error",
        "Rule",
    )
    return "\n".join(
        [
            "## Overview",
            "",
            verdict,
            "",
            _table(header, rows),
            "",
            "For payout vectors, *Match* counts the vectors compared, *Mismatch* "
            "those with another shape or other bin edges, and the largest error is "
            "the largest level difference over the largest golden level.",
        ]
    )


def _summary_md(result: ParityResult, explanations: Mapping[str, str]) -> str:
    rows = [
        (
            r["source"],
            r["approach"],
            r["method"],
            f"{r['runs_matched']} / {r['records']}",
            f"{r['kpi_match']} / {r['kpi_compared']} / {r['kpi_golden']}",
            _sci(r["kpi_max_rel_error"]),
            f"{r['payouts_compared']} / {r['payouts_golden']}",
            _sci(r["payout_max_abs_diff"]),
            _sci(r["payout_max_rel_diff"]),
            f"{r['clusters_match']} / {r['clusters_compared']}"
            if r["approach"] == "cluster_optimization"
            else "",
            _sci(r["objective_max_rel_error"]),
            r["findings"],
            r["unexplained"],
        )
        for r in _rows(summary_by_group(result, explanations))
    ]
    header = (
        "Source",
        "Approach",
        "Method",
        "Records",
        "KPIs",
        "Max KPI rel. error",
        "Payouts",
        "Max payout diff",
        "Max payout rel. diff",
        "Clusters equal",
        "Max objective rel. error",
        "Findings",
        "Unexplained",
    )
    return "\n".join(
        [
            "## Summary by comparison group",
            "",
            "*Records*: golden parameter points with a matched run / all. *KPIs*: "
            "matching / compared / golden values. *Payouts*: compared / golden "
            "entities, with the largest level difference (USD) and that "
            "difference over the largest golden level.",
            "",
            _table(header, rows),
        ]
    )


def _findings_md(result: ParityResult, explanations: Mapping[str, str]) -> str:
    lines = [
        "## Findings",
        "",
        "Every gap between the golden data and the store. Explain each one in "
        "the explanations file, by id or by a glob over its path "
        "(`kind/approach/method/source/parameters/subject/item`), and "
        "regenerate the report.",
        "",
    ]
    if not result.findings:
        lines.append("None.")
        return "\n".join(lines)
    rows = [
        (
            f"`{f.id}`",
            f.kind.value,
            f"{f.key.approach} / {f.key.method} / {f.key.source}",
            f.key.parameter_text(),
            " / ".join(x for x in (f.subject, f.item) if x),
            f.golden,
            f.ours,
            _sci(f.rel_error),
            f.detail,
            explanation_for(f, explanations) or PENDING,
        )
        for f in result.findings
    ]
    header = (
        "ID",
        "Kind",
        "Record",
        "Parameters",
        "Subject / item",
        "Golden",
        "Ours",
        "Rel. error",
        "Detail",
        "Explanation",
    )
    lines.append(_table(header, rows))
    return "\n".join(lines)


def _payouts_md(result: ParityResult) -> str:
    compared = [r for r in _rows(result.payouts) if r["status"] == "compared"]
    lines = [
        "## Payout differences (informational)",
        "",
        "Payout levels are not asserted: LP optima can be non-unique. "
        f"The {TOP_PAYOUT_DIFFS} largest level differences, by their size relative "
        "to the largest golden level:",
        "",
    ]
    if not compared:
        lines.append("No payout vectors were compared.")
        return "\n".join(lines)

    def size(row: Row) -> tuple[float, float]:
        rel, diff = float(row["max_rel_diff"]), float(row["max_abs_diff"])
        return (-math.inf if math.isnan(rel) else rel, diff)

    top = sorted(compared, key=size, reverse=True)[:TOP_PAYOUT_DIFFS]
    rows = [
        (
            f"{r['approach']} / {r['method']} / {r['source']}",
            r["parameters"],
            r["entity_id"],
            r["n_levels"],
            f"{float(r['max_abs_diff']):.6g}",
            _sci(r["max_rel_diff"]),
        )
        for r in top
    ]
    header = (
        "Record",
        "Parameters",
        "Entity",
        "Levels",
        "Max abs. diff (USD)",
        "Rel. to max level",
    )
    lines.append(_table(header, rows))
    return "\n".join(lines)


def _unmatched_md(result: ParityResult) -> str:
    lines = ["## Store runs without a golden record (informational)", ""]
    counts: dict[Group, int] = defaultdict(int)
    for r in _rows(result.unmatched_runs):
        counts[(str(r["source"]), str(r["scope"]), str(r["objective"]))] += 1
    if not counts:
        lines.append("None.")
        return "\n".join(lines)
    rows = [(*k, n) for k, n in sorted(counts.items())]
    lines.append(_table(("Source", "Scope", "Objective", "Runs"), rows))
    return "\n".join(lines)


def render(
    result: ParityResult,
    *,
    explanations: Mapping[str, str] | None = None,
    title: str = "Parity report",
    notes: str | None = None,
) -> str:
    """Render the parity report as Markdown.

    Parameters
    ----------
    result : harness.ParityResult
        The comparison.
    explanations : mapping of str to str, optional
        Finding id or path glob to explanation (module docstring).
    title : str, default "Parity report"
        The top heading.
    notes : str, optional
        Free text placed under the title (e.g. how the store was produced).

    Returns
    -------
    str
        The report, ending with a newline. It holds no timestamp, so the
        same inputs give the same text.
    """
    explanations = explanations or {}
    parts = [
        f"# {title}",
        "",
        "<!-- Generated by parity/report.py (MAR-67). Do not edit by hand: put "
        "explanations in the explanations file and regenerate. -->",
        "",
        "Parity of the new engine with the thesis golden tables (SPEC §7 F-06, "
        "gate MAR-18). Every gap is listed under *Findings* and needs an "
        "explanation.",
    ]
    if notes:
        parts += ["", notes.strip()]
    for section in (
        _setup(result),
        _overview_md(result, explanations),
        _summary_md(result, explanations),
        _findings_md(result, explanations),
        _payouts_md(result),
        _unmatched_md(result),
    ):
        parts += ["", section]
    return "\n".join(parts) + "\n"


def write_report(
    result: ParityResult,
    path: str | Path = DEFAULT_REPORT,
    *,
    explanations: Mapping[str, str] | None = None,
    title: str = "Parity report",
    notes: str | None = None,
) -> Path:
    """Render the report and write it to ``path``.

    Parameters
    ----------
    result : harness.ParityResult
        The comparison.
    path : str or pathlib.Path, default ``parity/REPORT.md``
        Output file.
    explanations : mapping of str to str, optional
        As for :func:`render`.
    title : str, default "Parity report"
        As for :func:`render`.
    notes : str, optional
        As for :func:`render`.

    Returns
    -------
    pathlib.Path
        The file written.
    """
    out = Path(path)
    out.write_text(
        render(result, explanations=explanations, title=title, notes=notes),
        encoding="utf-8",
    )
    return out


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def _fixed(items: Sequence[str]) -> dict[str, object]:
    """Parse ``NAME=VALUE`` items; VALUE is JSON if it parses, else a string."""
    fixed: dict[str, object] = {}
    for item in items:
        name, sep, raw = item.partition("=")
        if not sep or not name:
            raise ValueError(f"--fixed needs NAME=VALUE, got {item!r}")
        try:
            fixed[name] = json.loads(raw)
        except json.JSONDecodeError:
            fixed[name] = raw
    return fixed


def main(argv: Sequence[str] | None = None) -> int:
    """Compare a result store with the golden tables and write the report.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments (default: ``sys.argv[1:]``); ``--help`` lists them.

    Returns
    -------
    int
        0, or 1 with ``--check`` if a finding has no explanation.
    """
    parser = argparse.ArgumentParser(
        description="Compare a result store with the thesis golden tables and "
        "write the parity report."
    )
    parser.add_argument("--store", required=True, help="result store directory")
    parser.add_argument(
        "--results",
        default=str(GOLDEN_DIR / RESULTS_FILE),
        help="golden results table (default: the committed thesis table)",
    )
    parser.add_argument(
        "--kpis",
        default=str(GOLDEN_DIR / KPIS_FILE),
        help="golden KPI table (default: the committed thesis table)",
    )
    parser.add_argument("--objectives", help="optional golden objective table (CSV)")
    parser.add_argument("--out", default=str(DEFAULT_REPORT), help="report file")
    parser.add_argument("--explanations", help="YAML file of explanations")
    parser.add_argument(
        "--fixed",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="runs.parameters value every matching run must have (JSON value)",
    )
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        metavar="SOURCE",
        help="compare only golden records with this Source (repeatable)",
    )
    parser.add_argument(
        "--strict-source", action="store_true", help="require runs.source to agree"
    )
    parser.add_argument("--notes", help="text placed under the report title")
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit with status 1 if a finding has no explanation",
    )
    args = parser.parse_args(argv)

    store_dir = Path(args.store)
    if not store_dir.is_dir():
        parser.error(f"--store {store_dir} is not a directory")
    try:
        fixed = _fixed(args.fixed)
    except ValueError as exc:
        parser.error(str(exc))
    golden = load_golden(args.results, args.kpis, args.objectives)
    explanations = load_explanations(args.explanations) if args.explanations else {}
    result = compare(
        golden,
        ResultStore(store_dir),
        fixed_parameters=fixed,
        strict_source=args.strict_source,
        sources=args.sources,
    )
    out = write_report(result, args.out, explanations=explanations, notes=args.notes)
    unexplained = [
        f for f in result.findings if explanation_for(f, explanations) is None
    ]
    print(
        f"wrote {out}: {len(result.findings)} findings, "
        f"{len(unexplained)} without an explanation"
    )
    return 1 if args.check and unexplained else 0


if __name__ == "__main__":
    sys.exit(main())
