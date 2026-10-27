r"""Parity report generator: writes ``parity/REPORT.md`` (MAR-67, SPEC §7 F-06).

The report renders a :class:`harness.ParityResult`:

1. **Setup**: the store, the golden files and their SHA256 (as read and,
   for gzipped files, decompressed, checked against ``parity/manifest.json``),
   the tolerances and the matching settings, so every number has its setup.
2. **Overview**: one row per comparison (KPI values, objective values,
   payout vectors, cluster assignments) with golden, compared, matching and
   mismatching counts.
3. **Summary by comparison group**: one row per golden ``Source`` x
   ``Approach`` x ``Method``.
4. **Matched runs**: the store run of every golden record, with its
   ``config_hash`` (MAR-68).
5. **Objective values** (only with a golden objective table): every golden
   objective, how it was obtained, ours and the relative error (MAR-68).
6. **Findings**: every gap the harness found, with a stable id and an
   explanation column. The parity gate (MAR-18) needs every gap explained.
7. **Payout differences** (informational): the largest payout-level
   differences. They are reported, not asserted, because LP optima can be
   non-unique.
8. **Store runs without a golden record** (informational).
9. Appendices (optional): Markdown files appended verbatim (``--appendix``),
   e.g. an analysis that explains findings (MAR-68).

Compact form (``--compact``, MAR-69)
    For comparisons with many findings (the sweeps), so that the report
    stays under the repository's 500 kB file limit: the findings are grouped
    by record (one heading per record instead of the record columns), their
    explanation cell names an explanation (``E1``, ``E2``, ...) whose text is
    listed once in an *Explanations* section, and the objective table lists
    only the values that do not match (the summary by group gives the largest
    error of every group). The counts, the overview and every finding id are
    the same as in the full form.

Explanations
    The report is generated, so explanations live in a separate YAML file
    (a mapping) and are merged in on every run. A key is either a finding id
    (``P-3f2a9c01be``) or a glob over the finding's path,
    ``kind/approach/method/source/parameters/subject/item`` (e.g.
    ``kpi/integrated_portfolio_optimization/weighted_cvar_minimization/*``).
    An exact id wins; otherwise the first matching glob, in file order.

Command line, from the repository root::

    uv run python parity/report.py --store results/thesis \
        --objectives parity/golden/golden_objectives.csv \
        --explanations parity/explanations.yaml --out parity/REPORT.md

``--check`` exits with status 1 if a finding has no explanation.
``parity/README.md`` gives the command that writes the committed report.
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
    MANIFEST,
    PORTFOLIO_SUBJECT,
    RESULTS_FILE,
    Finding,
    FindingKind,
    HarnessError,
    ParityResult,
    check_manifest,
    compare,
    load_golden,
    load_simulation_golden,
)

from parametric_insurance_design.experiment.store import ResultStore

__all__ = [
    "DEFAULT_REPORT",
    "PENDING",
    "ExplanationsError",
    "explanation_for",
    "explanation_key_for",
    "joint_entity_kpi",
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


def explanation_key_for(
    finding: Finding, explanations: Mapping[str, str]
) -> str | None:
    """Return the key (id or glob) of a finding's explanation, if any.

    Parameters
    ----------
    finding : harness.Finding
        The finding.
    explanations : mapping of str to str
        Finding id or path glob to text (module docstring).

    Returns
    -------
    str or None
        The finding's id if it is a key, else the first glob that matches its
        path, else None.
    """
    if finding.id in explanations:
        return finding.id
    for pattern in explanations:
        if _GLOB_CHARS & set(pattern) and fnmatch.fnmatchcase(finding.path, pattern):
            return pattern
    return None


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
    key = explanation_key_for(finding, explanations)
    return None if key is None else explanations[key]


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


INDIVIDUAL_APPROACH: Final[str] = "individual_optimization"

GATED_KPIS: Final[str] = "KPI values: gated"
"""Overview row of the KPIs the gate judges (MAR-18 criteria, 2026-10-27)."""
UNGATED_KPIS: Final[str] = "KPI values: reported, not gated"
"""Overview row of the entity-level KPIs of joint scopes (MAR-18 answer 4)."""


def joint_entity_kpi(approach: str, subject: str) -> bool:
    """Whether a KPI is entity level in a joint (cluster or portfolio) scope.

    By the owner's MAR-18 criteria (2026-10-27, answer 4) such KPIs are
    reported, not gated, at non-unique optima, when the thesis-payout check
    backs them (the evidence rule of ``run_default_parity.py`` checks that).
    """
    return approach != INDIVIDUAL_APPROACH and subject != PORTFOLIO_SUBJECT


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
        largest level difference over the largest golden level. The KPI
        values are split after their total row into :data:`GATED_KPIS`
        (portfolio level, and entity level in the individual scope) and
        :data:`UNGATED_KPIS` (entity level in the joint scopes,
        :func:`joint_entity_kpi`).
    """
    tol = result.tolerances
    kpi_rule = f"relative error <= {tol.kpi_rtol:g} (atol {tol.kpi_atol:g})"
    kpi_rows = _rows(result.kpis)
    ungated = [r for r in kpi_rows if joint_entity_kpi(r["approach"], r["subject"])]
    gated = [r for r in kpi_rows if not joint_entity_kpi(r["approach"], r["subject"])]
    out: list[Row] = []
    for name, frame, rule in (
        ("KPI values", kpi_rows, kpi_rule),
        (GATED_KPIS, gated, kpi_rule),
        (UNGATED_KPIS, ungated, kpi_rule + ", reported only"),
        (
            "Objective values",
            _rows(result.objectives),
            f"relative error <= {tol.objective_rtol:g} (atol {tol.objective_atol:g})"
            if result.objectives_available
            else "not in the golden data",
        ),
    ):
        rows = frame
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


def _content_lines(result: ParityResult, manifest: str | Path | None) -> list[str]:
    """Return setup lines: decompressed-content SHA256 and the manifest check."""
    content = dict(result.golden_content)
    if not content:
        return []
    checks = {} if manifest is None else check_manifest(content, manifest)
    where = "" if manifest is None else Path(manifest).name
    lines = ["- Golden content (SHA256 of the decompressed CSV):"]
    for name, digest in content.items():
        status = checks.get(name)
        if status is None:
            suffix = ""
        elif status == "not in the manifest":
            suffix = f" (not in `{where}`)"
        else:
            suffix = f" ({status} `{where}`)"
        lines.append(f"  - `{name}`: `{digest}`{suffix}")
    return lines


def _setup(
    result: ParityResult,
    manifest: str | Path | None = None,
    setup_notes: Sequence[str] = (),
) -> str:
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
    baseline = result.baseline_parameters
    matching += (
        ". A record of a simulation sweep also names its `noise_level`, or its "
        "`n_assets` and asset subset (`locations`, the run's prepared "
        "locations), which the run must have"
    )
    if baseline:
        matching += "; a record that names neither needs the baseline " + ", ".join(
            f"`{k}` = {json.dumps(v)}" for k, v in baseline.items()
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
        + ("runs of the sweeps compared" if result.restricted else "runs")
        + f", {result.n_store_runs - len(result.unmatched_runs)} of them matched "
        "by a golden record.",
        "- Golden files (SHA256 of the files as read):",
        *(f"  - `{name}`: `{digest}`" for name, digest in result.golden_files.items()),
        *_content_lines(result, manifest),
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
        *(f"- {note.strip()}" for note in setup_notes if note.strip()),
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
    ungated = sum(
        f.kind is FindingKind.KPI and joint_entity_kpi(f.key.approach, f.subject)
        for f in result.findings
    )
    verdict += (
        f" {ungated} of the findings are entity-level KPIs in a joint scope "
        f"(*{UNGATED_KPIS}*): by the owner's MAR-18 criteria (2026-10-27, answer "
        "4) they are reported, not gated, where the thesis-payout check backs "
        "them (an explanation that claims an alternative optimum must have that "
        "verdict for its record); the gate judges objectives, portfolio-level "
        "KPIs, the entity-level KPIs of the individual scope (*"
        f"{GATED_KPIS}*), payout bin edges and cluster assignments."
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


def _matched_runs_md(result: ParityResult, findings_only: bool = False) -> str:
    lines = [
        "## Matched runs",
        "",
        "The store run each golden record was compared with. A run's "
        "`config_hash` identifies its configuration (MAR-64); its `run_id` "
        "adds the input checksum, package version and solver policy.",
        "",
    ]
    rows = _rows(result.matched_runs)
    if not rows:
        lines.append("No golden records were compared.")
        return "\n".join(lines)
    if findings_only:
        cited = {(f.key.label(), f.key.parameter_text()) for f in result.findings}
        listed = [
            r
            for r in rows
            if int(r["candidates"]) != 1
            or int(r["failed"])
            or (
                "/".join((r["approach"], r["method"], r["source"], r["parameters"])),
                r["parameters"],
            )
            in cited
        ]
        lines += [
            f"Only the {len(listed)} of {len(rows)} records with a finding, a "
            "failed problem or not exactly one matched run are listed (the "
            "full table would exceed the file-size limit); the sweep manifest "
            "named in the setup (in the result store) lists the `config_hash` and "
            "`run_id` of every sweep point.",
            "",
        ]
        rows = listed
        if not rows:
            return "\n".join(lines)
    table = [
        (
            f"{r['approach']} / {r['method']} / {r['source']}",
            r["parameters"],
            f"`{r['config_hash']}`" if r["config_hash"] else "",
            f"`{str(r['run_id'])[:19]}…`" if r["run_id"] else "",
            r["run_source"],
            f"{int(r['problems']) - int(r['failed'])} / {int(r['problems'])}",
            "" if int(r["candidates"]) == 1 else f"{int(r['candidates'])} runs match",
        )
        for r in rows
    ]
    header = (
        "Record",
        "Parameters",
        "config_hash",
        "run_id",
        "Run source",
        "Problems solved",
        "Note",
    )
    lines.append(_table(header, table))
    return "\n".join(lines)


def _objectives_md(result: ParityResult, compact: bool = False) -> str:
    lines = ["## Objective values", ""]
    if not result.objectives_available:
        lines.append("No golden objective table was given; nothing compared.")
        return "\n".join(lines)
    rows = _rows(result.objectives)
    lines += [
        "One row per golden design problem. *Derivation*: how the golden value "
        "was obtained (`a_golden_kpis`: from the golden KPI row named in "
        "*KPI source*; `b_thesis_code`: recomputed with the thesis code); "
        "see `golden/golden_objectives.json`. Ours is `runs.objective_value` "
        "in loss units.",
        "",
    ]
    if not rows:
        lines.append("No golden objective values for the records compared.")
        return "\n".join(lines)
    if compact:
        listed = [r for r in rows if r["status"] != "match"]
        lines.append(
            f"Compact form: the {len(rows) - len(listed)} of {len(rows)} golden "
            "objective values that match are not listed (the summary by "
            "comparison group gives the largest relative error of each group)."
        )
        if not listed:
            return "\n".join(lines)
        lines.append("")
        rows = listed
    table = [
        (
            f"{r['approach']} / {r['method']} / {r['source']}",
            r["parameters"],
            r["problem_id"],
            r["derivation"],
            r["kpi_source"],
            _num(r["golden"]),
            _num(r["ours"]),
            _sci(r["rel_error"]),
            r["status"],
        )
        for r in rows
    ]
    header = (
        "Record",
        "Parameters",
        "Problem",
        "Derivation",
        "KPI source",
        "Golden",
        "Ours",
        "Rel. error",
        "Status",
    )
    lines.append(_table(header, table))
    return "\n".join(lines)


def _num(value: object) -> str:
    """Return a value with 10 significant digits; empty if undefined."""
    if not isinstance(value, int | float) or math.isnan(value):
        return ""
    return f"{value:.10g}"


def explanation_labels(
    result: ParityResult, explanations: Mapping[str, str]
) -> dict[str, str]:
    """Label the explanations the findings use: ``E1``, ``E2``, ... in file order.

    Parameters
    ----------
    result : harness.ParityResult
        The comparison.
    explanations : mapping of str to str
        Finding id or path glob to text.

    Returns
    -------
    dict of str to str
        Explanation key to label, for the keys at least one finding uses.
    """
    used = {explanation_key_for(f, explanations) for f in result.findings}
    keys = [k for k in explanations if k in used]
    return {key: f"E{i}" for i, key in enumerate(keys, start=1)}


def _findings_compact_md(result: ParityResult, explanations: Mapping[str, str]) -> str:
    labels = explanation_labels(result, explanations)
    lines = [
        "## Findings",
        "",
        "Every gap between the golden data and the store, grouped by golden "
        "record. Explain each one in the explanations file, by id or by a glob "
        "over its path (`kind/approach/method/source/parameters/subject/item`), "
        "and regenerate the report. *Explanation* names the text in the "
        "*Explanations* section below.",
    ]
    if not result.findings:
        lines += ["", "None."]
        return "\n".join(lines)
    header = (
        "ID",
        "Kind",
        "Subject / item",
        "Golden",
        "Ours",
        "Rel. error",
        "Detail",
        "Explanation",
    )
    by_record: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for f in result.findings:
        by_record[(f.key.label(), f.key.parameter_text())].append(f)
    for findings in by_record.values():
        key = findings[0].key
        lines += [
            "",
            f"### {key.approach} / {key.method} / {key.source}: "
            f"{key.parameter_text() or 'no parameters'}",
            "",
        ]
        rows = []
        for f in findings:
            label = labels.get(explanation_key_for(f, explanations) or "")
            rows.append(
                (
                    f"`{f.id}`",
                    f.kind.value,
                    " / ".join(x for x in (f.subject, f.item) if x),
                    f.golden,
                    f.ours,
                    _sci(f.rel_error),
                    f.detail,
                    label or PENDING,
                )
            )
        lines.append(_table(header, rows))
    return "\n".join(lines)


def _explanations_md(result: ParityResult, explanations: Mapping[str, str]) -> str:
    labels = explanation_labels(result, explanations)
    counts: dict[str, int] = defaultdict(int)
    for f in result.findings:
        key = explanation_key_for(f, explanations)
        if key is not None:
            counts[key] += 1
    lines = [
        "## Explanations",
        "",
        "The explanations the findings above use, from the explanations file "
        "(key: a finding id or a glob over the finding path).",
    ]
    if not labels:
        lines += ["", "None."]
        return "\n".join(lines)
    for key, label in labels.items():
        lines += [
            "",
            f"**{label}** (`{key}`, {counts[key]} findings): {explanations[key]}",
        ]
    return "\n".join(lines)


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
    appendices: Sequence[str] = (),
    manifest: str | Path | None = MANIFEST,
    setup_notes: Sequence[str] = (),
    compact: bool = False,
    sections: Sequence[str] = (),
    matched_findings_only: bool = False,
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
    appendices : sequence of str, optional
        Markdown texts appended at the end, in order (e.g. an analysis that
        the explanations cite).
    manifest : str or pathlib.Path or None, default ``parity/manifest.json``
        Manifest to check the golden content SHA256 against; None to skip.
    setup_notes : sequence of str, optional
        Extra bullet points for the setup section (e.g. the solver policy).
    compact : bool, default False
        The compact form (module docstring): findings grouped by record with
        explanation labels, an *Explanations* section, and only the
        objective values that do not match.
    sections : sequence of str, optional
        Markdown sections placed after the summary by comparison group (e.g.
        the index of the per-sweep reports, MAR-70).
    matched_findings_only : bool, default False
        List only the matched runs of records with a finding, a failed
        problem or not exactly one match (the asset-count sweep has 1,521
        records, MAR-70).

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
        _setup(result, manifest, setup_notes),
        _overview_md(result, explanations),
        _summary_md(result, explanations),
        *(s.strip() for s in sections if s.strip()),
        _matched_runs_md(result, matched_findings_only),
        _objectives_md(result, compact),
        *(
            (
                _findings_compact_md(result, explanations),
                _explanations_md(result, explanations),
            )
            if compact
            else (_findings_md(result, explanations),)
        ),
        _payouts_md(result),
        _unmatched_md(result),
        *(a.strip() for a in appendices if a.strip()),
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
    appendices: Sequence[str] = (),
    manifest: str | Path | None = MANIFEST,
    setup_notes: Sequence[str] = (),
    compact: bool = False,
    sections: Sequence[str] = (),
    matched_findings_only: bool = False,
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
    appendices : sequence of str, optional
        As for :func:`render`.
    manifest : str or pathlib.Path or None, default ``parity/manifest.json``
        As for :func:`render`.
    setup_notes : sequence of str, optional
        As for :func:`render`.
    compact : bool, default False
        As for :func:`render`.
    sections : sequence of str, optional
        As for :func:`render`.
    matched_findings_only : bool, default False
        As for :func:`render`.

    Returns
    -------
    pathlib.Path
        The file written.
    """
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        render(
            result,
            explanations=explanations,
            title=title,
            notes=notes,
            appendices=appendices,
            manifest=manifest,
            setup_notes=setup_notes,
            compact=compact,
            sections=sections,
            matched_findings_only=matched_findings_only,
        ),
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


def _read_text(parser: argparse.ArgumentParser, path: str) -> str:
    """Read a text file given on the command line, or exit with an error."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        parser.error(f"cannot read {path}: {exc}")


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
    parser.add_argument(
        "--simulation-golden",
        metavar="DIR",
        help="also read the regenerated simulation-sweep tables in DIR "
        "(golden/simulation_sweeps, MAR-70)",
    )
    parser.add_argument(
        "--baseline",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="value of noise_level or n_assets a run must have when a golden "
        "record leaves it empty (JSON value; MAR-70)",
    )
    parser.add_argument("--notes", help="text placed under the report title")
    parser.add_argument(
        "--notes-file", help="file whose text is placed under the report title"
    )
    parser.add_argument(
        "--appendix",
        action="append",
        default=[],
        metavar="FILE",
        help="Markdown file appended to the report (repeatable)",
    )
    parser.add_argument(
        "--setup-note",
        action="append",
        default=[],
        metavar="TEXT",
        help="extra bullet point for the setup section (repeatable)",
    )
    parser.add_argument(
        "--manifest",
        default=str(MANIFEST),
        help="manifest to check the golden content SHA256 against",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="compact form: findings grouped by record, explanations listed "
        "once, only the objective values that do not match",
    )
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
        baseline = _fixed(args.baseline)
    except ValueError as exc:
        parser.error(str(exc))
    notes = args.notes
    if args.notes_file:
        notes = "\n\n".join(
            x for x in (notes, _read_text(parser, args.notes_file)) if x
        )
    appendices = [_read_text(parser, path) for path in args.appendix]
    golden = load_golden(args.results, args.kpis, args.objectives)
    if args.simulation_golden:
        golden = golden.merge(load_simulation_golden(args.simulation_golden))
    explanations = load_explanations(args.explanations) if args.explanations else {}
    result = compare(
        golden,
        ResultStore(store_dir),
        fixed_parameters=fixed,
        strict_source=args.strict_source,
        sources=args.sources,
        baseline_parameters=baseline,
    )
    out = write_report(
        result,
        args.out,
        explanations=explanations,
        notes=notes,
        appendices=appendices,
        manifest=args.manifest,
        setup_notes=args.setup_note,
        compact=args.compact,
    )
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
