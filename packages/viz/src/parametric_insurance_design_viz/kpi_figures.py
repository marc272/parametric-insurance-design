"""KPI figures: heatmaps, the performance overview and exceedance curves.

Owner: MAR-111. Ports three figures of the thesis ``plotting.py``
(parametric-insurance-framework):

* :func:`kpi_heatmap` (thesis ``plot_kpi_heatmap``; notebook cells
  "Portfolio-level performance comparison", not a numbered thesis figure):
  one portfolio KPI for every scope x objective, coloured by its change
  against a baseline combination.
* :func:`performance_overview` (thesis ``plot_portfolio_performance_overview``;
  thesis Figure 5.5, numbers in Table A.2): one bar panel per portfolio KPI,
  bars grouped by scope and coloured by objective, with the baseline as a
  dotted line.
* :func:`exceedance_curves` (thesis ``plot_exceedance_curves``; thesis
  Figure 5.6 for the portfolio scope): the portfolio uncovered loss exceeded
  at each return period, one curve per objective, with the VaR return period
  ``1 / (1 - beta)`` marked and the tail beyond it shaded.

Every number comes from the result store: the ``kpis`` table (rows at
``level = "portfolio"``) and the ``exceedance`` table. Nothing is solved and
no payout is re-evaluated, so the figures show exactly what the core's
``evaluate`` module computed for each run, on the run's basis.
:func:`kpi_figures` is the figure builder registered in
:data:`~parametric_insurance_design_viz.command.FIGURE_SETS`.

Which rows are read
-------------------
* **Evaluation split:** the ``test`` rows where every run has them (holdout
  samples, out of sample), else ``full`` (in sample), else ``train``. The
  figure data record the split (``eval_split``). A figure on the ``test``
  or ``train`` rows also states it, in its subtitle (heatmaps, overview)
  or axes title (exceedance): "out of sample (test years)" or "in sample
  (train years)" (:func:`split_note`, MAR-229). A figure on the ``full``
  rows carries no note, so the thesis figures are unchanged. The sweep
  figures choose their split with the same function, :func:`figure_split`
  (MAR-232).
* **Samples:** ``full`` and ``holdout`` runs. The functions that take runs
  (:func:`kpi_table`, :func:`kpi_heatmap`, :func:`performance_overview`,
  :func:`exceedance_curves`) refuse runs of a ``kfold`` sample with
  :class:`KFoldRunsError` (MAR-137): a k-fold experiment is a run per fold
  (MAR-22), so one scope x objective has ``k`` test values, and a figure
  that drew one of them, or their mean, would misstate the result.
* **k-fold configs** (MAR-151): :func:`kpi_figures` draws the heatmaps and
  the performance overview from the **pooled** out-of-sample KPIs that the
  core computes on demand (``experiment.kfold.pooled_kpis``; every year
  evaluated by the design of the fold that held it out, one bootstrap
  resample of all years shared by every design). The ``figures`` command
  passes them as ``FigureContext.pooled_kpis``; :func:`pooled_kpi_table`
  reads them. One pooled row per scope x objective, ``eval_split =
  "pooled"``, and the subtitle names ``k``. The exceedance figures are
  skipped with a stated reason: the pooled rule covers the portfolio KPIs,
  the ``exceedance`` table holds per-fold curves, and the figures never
  re-evaluate payouts.
* **VaR/CVaR level:** the rows at the runs' ``evaluation_beta`` parameter.
* **Curve:** ``event`` on the event bases, ``aep`` on the ``annual`` basis.
  The return-period axis is labelled per basis (MAR-139): years on
  ``annual`` and ``event``, **events** on ``event_conditional`` (the thesis
  convention: ``1 / T`` is a share of the given events).

Confidence intervals
--------------------
A run whose config has a ``bootstrap`` section (MAR-23) stores a
block-bootstrap interval over years with every KPI (``kpis.ci_low``,
``ci_high``, ``ci_level``, ``n_bootstrap``; ``docs/methodology/bootstrap.md``).
The figures draw it where it exists (MAR-148):

* :func:`performance_overview`: an interval bar from ``ci_low`` to
  ``ci_high`` on each bar, and a legend entry with the level and ``B``.
* :func:`kpi_heatmap`: the interval as a third line in each cell, in
  brackets, and a footnote with the level and ``B``.
* A row with null bounds (no bootstrap in the config, or a KPI undefined in
  some replicate) is drawn without an interval, and the figure data say so
  (``ci_drawn``). Without any bounds the figures are the figures drawn
  before MAR-148. Runs whose intervals differ in level or ``B`` are refused
  with :class:`~parametric_insurance_design_viz.errors.InconsistentRunsError`
  (:func:`interval_note`): one legend cannot describe both.
* The interval is drawn as stored. It need not contain the point estimate:
  a percentile interval of a biased statistic, such as CVaR, can lie beside
  it.
* :func:`exceedance_curves` draws no intervals: the ``exceedance`` table
  has no interval columns (``records.EXCEEDANCE``).

Scope labels (MAR-225): rows and legends are labelled by the scope name,
``style.run_scope_name`` of the runs (or ``style.config_scope_name`` of the
configured scope for the pooled k-fold table). A cluster scope calibrated
cluster by cluster (``joint: false``, MAR-180) has ``runs.scope =
"cluster"`` like the joint cluster scope; it is labelled "Cluster scope,
calibrated per cluster" and drawn in its own line style, and a scope grid
never mixes it with joint cluster runs. The ``scope`` column of the figure
data stays ``runs.scope``; ``scope_key`` tells the two apart.

Differences from the thesis code, all deliberate:

* The exceedance curves are drawn at the return periods the runner stored
  (core ``evaluate.DEFAULT_RETURN_PERIODS``: 2, 5, 10, 25, 50, 100, 250),
  not at the thesis' 2, 5, ..., 200, 500, because the figures never
  re-evaluate payouts. The portfolio ``var_uncovered`` KPI is the same lower
  quantile at ``1 / (1 - beta)``, so it is added as the curve point at that
  return period (20 years for the thesis) when the store has no point there.
* A run with a failed design problem has no KPI rows. The cross-scope
  figures (heatmaps, overview) are then skipped and reported as failed,
  where the thesis drew empty cells.
* The heatmap subtitle of the CVaR KPI reads "Tail basis risk"; the thesis
  notebook wrote "Total basis risk" for both KPIs.
* Units come from the EventSet metadata ("[USD]" instead of "[$]").
"""

from __future__ import annotations

import math
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.cm import ScalarMappable
from matplotlib.colors import (
    BoundaryNorm,
    LinearSegmentedColormap,
    ListedColormap,
    Normalize,
)
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import FancyBboxPatch, Rectangle
from numpy.typing import NDArray

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.experiment.kfold import POOLED_COLUMNS, POOLED_SPLIT
from parametric_insurance_design.records import (
    CurveKind,
    CurveQuantity,
    KpiLevel,
    KpiName,
    Split,
)
from parametric_insurance_design_viz import style
from parametric_insurance_design_viz.errors import (
    FigureDataError,
    InconsistentRunsError,
)
from parametric_insurance_design_viz.figure_data import MAIN_TABLE, FigureOutput
from parametric_insurance_design_viz.payout_functions import AxisLabels
from parametric_insurance_design_viz.reader import RunResult

if TYPE_CHECKING:  # command imports this module to register kpi_figures
    from parametric_insurance_design_viz.command import (
        FigureContext,
        SkippedFigure,
    )

__all__ = [
    "CURVE_COLUMNS",
    "HEATMAP_KPIS",
    "KPI_COLUMNS",
    "KPI_LABELS",
    "OVERVIEW_KPIS",
    "POOLED_EXCEEDANCE_REASON",
    "POOLED_KPI_COLUMNS",
    "SPLIT_NOTES",
    "SPLIT_PREFERENCE",
    "Baseline",
    "KFoldRunsError",
    "MissingKpiError",
    "exceedance_curves",
    "figure_split",
    "heatmap_figsize",
    "interval_note",
    "kpi_figures",
    "kpi_heatmap",
    "kpi_label",
    "kpi_table",
    "performance_overview",
    "pooled_kpi_table",
    "return_period_label",
    "split_note",
]

ScopeGrid = Mapping[str, Sequence[RunResult]]
"""Runs per scope key (e.g. ``"individual"``, ``"cluster_2"``), in order."""

SPLIT_PREFERENCE: Final[tuple[str, ...]] = (
    Split.TEST.value,
    Split.FULL.value,
    Split.TRAIN.value,
)
"""Evaluation split read when every run has it, in order of preference."""

SPLIT_NOTES: Final[Mapping[str, str]] = {
    Split.TEST.value: "out of sample (test years)",
    Split.TRAIN.value: "in sample (train years)",
}
"""What a figure on a split of a holdout run says about it (MAR-229).

A figure on the ``test`` or ``train`` rows states the split in its title or
subtitle, and its figure data record it. A figure on the ``full`` rows (every
year, in sample) states nothing, so the thesis figures stay byte-identical;
:func:`split_note` returns None for it."""

KFOLD_SAMPLE: Final[str] = "kfold"
"""``runs.parameters["sample"]`` of a k-fold run, which the figures refuse."""


class MissingKpiError(InconsistentRunsError):
    """A run lacks the KPI row a figure needs (or has several candidates).

    Raised by :func:`figure_split` and the sweep figures (``sweep_figures``
    re-exports it). Defined here since MAR-232, when the split rule became
    one function; it was a :class:`~.errors.VizError` of ``sweep_figures``,
    and is now also an :class:`~.errors.InconsistentRunsError`, which the
    KPI figures raised for a missing split before.
    """


class KFoldRunsError(InconsistentRunsError):
    """The runs are folds of a k-fold sample, which a run-level figure refuses.

    A k-fold experiment stores a run per fold (MAR-22), so one scope x
    objective has ``k`` out-of-sample values. The figure functions that take
    runs refuse them (MAR-137); a k-fold config's KPI figures are drawn from
    the pooled out-of-sample KPIs instead (MAR-151, :func:`kpi_figures`), and
    a k-fold config without them is refused.
    """


HEATMAP_KPIS: Final[tuple[str, ...]] = (
    KpiName.CVAR_UNCOVERED.value,
    KpiName.EXPECTED_UNCOVERED.value,
)
"""KPIs with a heatmap in the figure set (thesis notebook cells 71, 72)."""

OVERVIEW_KPIS: Final[tuple[str, ...]] = HEATMAP_KPIS
"""Panels of the performance overview, top to bottom (thesis Figure 5.5)."""


@dataclass(frozen=True)
class _KpiLabel:
    """How a KPI is named in figures (thesis notebook labels)."""

    symbol: str
    name: str


KPI_LABELS: Final[dict[str, _KpiLabel]] = {
    KpiName.CVAR_UNCOVERED.value: _KpiLabel(r"$CVaR(UL^p)$", "Tail basis risk"),
    KpiName.EXPECTED_UNCOVERED.value: _KpiLabel(r"$E(UL^p)$", "Total basis risk"),
    KpiName.VAR_UNCOVERED.value: _KpiLabel(r"$VaR(UL^p)$", "Uncovered loss VaR"),
    KpiName.RMSE_RESIDUAL.value: _KpiLabel(r"$RMSE(RL^p)$", "Residual loss RMSE"),
}
"""Symbol and name of the KPIs the figures label; others use the KPI name."""

KPI_COLUMNS: Final[tuple[str, ...]] = (
    "scope_key",
    "scope",
    "objective",
    "run_id",
    "eval_split",
    "fold",
    "basis",
    "problem_id",
    "subject_id",
    "kpi",
    "beta",
    "value",
    "ci_low",
    "ci_high",
    "ci_level",
    "n_bootstrap",
)
"""Columns of :func:`kpi_table`. The interval columns are the store's: null
without a bootstrap (MAR-23)."""

CURVE_COLUMNS: Final[tuple[str, ...]] = (
    "scope_key",
    "scope",
    "objective",
    "run_id",
    "eval_split",
    "fold",
    "basis",
    "problem_id",
    "subject_id",
    "quantity",
    "curve",
    "return_period",
    "value",
    "source",
)
"""Columns of the exceedance figure data. ``source`` names the store table."""

POOLED_KPI_COLUMNS: Final[tuple[str, ...]] = (*KPI_COLUMNS, "k")
"""Columns of :func:`pooled_kpi_table` (MAR-151): :data:`KPI_COLUMNS` with
``eval_split = "pooled"``, ``run_id`` the fold runs joined by ``";"``, a null
``fold``, and the number of folds ``k``."""

_CMAP: Final[LinearSegmentedColormap] = LinearSegmentedColormap.from_list(
    "GreenWhiteRed", ["#006837", "#ffffff", "#a50026"]
)
_MINUS: Final[str] = "\N{MINUS SIGN}"  # thesis: a true minus sign
_HEATMAP_TITLE: Final[str] = "Portfolio-level performance comparison"
_CELL_INSET: Final[float] = 0.015
_CORNER_RADIUS: Final[float] = 0.05
_HEATMAP_FONT: Final[float] = 10  # thesis plot_kpi_heatmap label_size default
_HEATMAP_SIZE: Final[float] = 8.0  # inches, square: the thesis 3 x 3 heatmap
_HEATMAP_ROWS: Final[int] = 3  # the rows the square heatmap is laid out for
_HEATMAP_GRID: Final[float] = 0.62  # height share of the cells (top 0.80, bottom 0.18)
_AXIS_TEXT_COLOR: Final[str] = "#444"
_DARK_TEXT: Final[str] = "#0a2540"
_BAR_WIDTH: Final[float] = 0.1
_BAR_SPACING: Final[float] = 0.1
_GROUP_GAP: Final[float] = 0.25
_CI_COLOR: Final[str] = "black"
_CI_LINEWIDTH: Final[float] = 1.0
_CI_CAPSIZE: Final[float] = 3.0
_TAIL_SHADE: Final[str] = "#565758"
_TAIL_ALPHA: Final[float] = 0.15
_EVENT_BASES: Final[frozenset[str]] = frozenset(
    {Basis.EVENT.value, Basis.EVENT_CONDITIONAL.value}
)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def _where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    """Return the rows of ``frame`` where ``mask`` is true."""
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


def kpi_label(kpi: str, *, unit: str | None = None) -> str:
    """Axis label of a KPI, e.g. ``"Tail basis risk $CVaR(UL^p)$ [USD]"``.

    Parameters
    ----------
    kpi : str
        KPI name (``kpis.kpi``).
    unit : str, optional
        Unit appended in brackets.

    Returns
    -------
    str
        The label.
    """
    label = KPI_LABELS.get(kpi)
    text = f"{label.name} {label.symbol}" if label else kpi.replace("_", " ")
    return f"{text} [{unit}]" if unit else text


def split_note(split: str) -> str | None:
    """Return what a figure says about its evaluation split (MAR-229).

    Parameters
    ----------
    split : str
        ``kpis.eval_split`` of the rows a figure shows.

    Returns
    -------
    str or None
        :data:`SPLIT_NOTES` of ``split``, e.g. ``"out of sample (test
        years)"``; None for ``full`` (and any other split), whose figures
        carry no note.
    """
    return SPLIT_NOTES.get(split)


def _split_subtitle(text: str, table: pd.DataFrame) -> str | None:
    """``text`` with the split note of a KPI table, or None without a note."""
    splits = sorted({str(x) for x in table["eval_split"]})
    note = split_note(splits[0]) if len(splits) == 1 else None
    return f"{text}, {note}" if note else None


def _refuse_kfold(runs: Sequence[RunResult]) -> None:
    """Raise :class:`KFoldRunsError` if a run is a fold of a k-fold sample."""
    folds = [r for r in runs if r.parameters.get("sample") == KFOLD_SAMPLE]
    if folds:
        names = "; ".join(
            f"{r.run_id} ({r.scope} x {r.objective}, fold "
            f"{r.parameters.get('fold')} of k={r.parameters.get('k')})"
            for r in folds
        )
        raise KFoldRunsError(
            f"the KPI figures refuse k-fold runs (MAR-137): {names}. A k-fold "
            "experiment has a run per fold; its figures show the pooled "
            "out-of-sample KPIs (MAR-151: experiment.kfold.pooled_kpis, "
            "pooled_kpi_table, or the figures command)"
        )


def _grid(scopes: ScopeGrid) -> tuple[list[str], list[str]]:
    """Check a scope grid; return its scope keys and its objectives.

    Every scope must hold complete runs, of its own scope, one per objective,
    with the same objectives in the same order. No run may be a fold of a
    k-fold sample (:class:`KFoldRunsError`).
    """
    keys = list(scopes)
    if not keys:
        raise InconsistentRunsError("a KPI figure needs at least one scope")
    _refuse_kfold([r for key in keys for r in scopes[key]])
    objectives: list[str] | None = None
    for key in keys:
        runs = tuple(scopes[key])
        if not runs:
            raise InconsistentRunsError(f"scope {key!r} has no runs")
        for run in runs:
            run.require_complete()
        kinds = sorted({style.run_scope_name(r) for r in runs})
        if len(kinds) != 1:
            raise InconsistentRunsError(
                f"scope {key!r} mixes runs of the scopes {kinds}"
            )
        names = [r.objective for r in runs]
        if len(set(names)) != len(names):
            raise InconsistentRunsError(f"scope {key!r} repeats an objective: {names}")
        if objectives is None:
            objectives = names
        elif names != objectives:
            raise InconsistentRunsError(
                f"every scope must have the objectives {objectives} in that "
                f"order; scope {key!r} has {names}"
            )
    return keys, cast(list[str], objectives)


@dataclass(frozen=True)
class _Layout:
    """Rows and columns of a cross-scope figure: scope keys and objectives."""

    keys: tuple[str, ...]
    objectives: tuple[str, ...]
    scopes: Mapping[str, str]  # scope key -> scope name

    @classmethod
    def of_runs(cls, scopes: ScopeGrid) -> _Layout:
        """Return the layout of a checked scope grid (:func:`_grid`)."""
        keys, objectives = _grid(scopes)
        names = {k: style.run_scope_name(scopes[k][0]) for k in keys}
        return cls(tuple(keys), tuple(objectives), names)

    @classmethod
    def of_table(
        cls, table: pd.DataFrame, names: Mapping[str, str] | None = None
    ) -> _Layout:
        """Return the layout of a KPI table: every scope key with every objective.

        ``names`` maps each scope key to its scope name
        (``style.config_scope_name``); default the table's ``scope`` column
        (``runs.scope``), which reads ``"cluster"`` for both cluster settings.

        Raises
        ------
        InconsistentRunsError
            If the table is empty or not a complete scope x objective grid.
        """
        if table.empty:
            raise InconsistentRunsError("a KPI figure needs at least one row")
        keys = tuple(dict.fromkeys(str(k) for k in table["scope_key"]))
        objectives = tuple(dict.fromkeys(str(o) for o in table["objective"]))
        cells = set(zip(table["scope_key"], table["objective"], strict=True))
        absent = [(k, o) for k in keys for o in objectives if (k, o) not in cells]
        if absent:
            raise InconsistentRunsError(
                f"the KPI table is not a complete scope x objective grid; "
                f"missing {absent}"
            )
        if names is None:
            names = dict(zip(table["scope_key"], table["scope"], strict=True))
        return cls(keys, objectives, {k: str(names[k]) for k in keys})

    def scope_text(self, key: str) -> str:
        """Label of a scope key (see :func:`_scope_text`)."""
        return _scope_label(key, self.scopes[key])

    def default_baseline(self) -> Baseline:
        """:meth:`Baseline.default` of this layout."""
        objective = (
            style.BENCHMARK_OBJECTIVE
            if style.BENCHMARK_OBJECTIVE in self.objectives
            else self.objectives[0]
        )
        return Baseline(scope_key=self.keys[0], objective=objective)

    def baseline_label(self, baseline: Baseline) -> str:
        """:meth:`Baseline.label` of this layout."""
        return (
            f"{self.scope_text(baseline.scope_key).lower()} & "
            f"{style.objective_label(baseline.objective).lower()}"
        )


def _runs(scopes: ScopeGrid) -> list[tuple[str, RunResult]]:
    return [(key, run) for key in scopes for run in scopes[key]]


def figure_split(
    runs: Sequence[RunResult],
    eval_split: str | None = None,
    *,
    tables: Sequence[str] = ("kpis",),
) -> str:
    """Return the evaluation split a figure reads from its runs (MAR-229).

    The one rule of the KPI figures and the sweep figures (``sweep_figures``
    re-exports it; MAR-232). Every row of one figure is read on one split:
    ``eval_split`` if given, else the first of :data:`SPLIT_PREFERENCE`
    (``test``, ``full``, ``train``) on which every complete run has rows. A
    holdout run has ``train`` and ``test`` rows, so its figures read
    ``test`` (out of sample); a full-sample run has ``full`` rows only.

    Parameters
    ----------
    runs : sequence of RunResult
        The figure's runs. Failed runs have no rows and are not considered.
    eval_split : str, optional
        The split to read; it must be one every complete run has.
    tables : sequence of str, default ("kpis",)
        The run tables whose ``eval_split`` column counts: a run has a split
        if one of them has a row on it. The KPI figures pass ``("kpis",
        "exceedance")``.

    Returns
    -------
    str
        The split. Without a complete run no row is read, and it is
        ``eval_split`` or ``"full"``.

    Raises
    ------
    MissingKpiError
        If a complete run lacks ``eval_split``, or the complete runs share
        no split.
    """
    have = [
        (r, set().union(*(set(getattr(r, t)["eval_split"]) for t in tables)))
        for r in runs
        if r.complete
    ]
    common = set.intersection(*(h for _, h in have)) if have else set()
    if eval_split is not None:
        lacking = [(r, h) for r, h in have if eval_split not in h]
        if lacking:
            run, splits = lacking[0]
            raise MissingKpiError(
                f"{len(lacking)} of {len(have)} runs have no KPI rows on the "
                f"{eval_split!r} split, e.g. run {run.run_id} ({run.scope} x "
                f"{run.objective}) has the splits {sorted(splits)}"
            )
        return eval_split
    if not have:
        return "full"
    for split in SPLIT_PREFERENCE:
        if split in common:
            return split
    raise MissingKpiError(
        "the runs of the figure share no evaluation split with KPI rows; "
        f"splits per run: {[(r.run_id, sorted(h)) for r, h in have]}"
    )


def _beta(runs: Sequence[RunResult], beta: float | None) -> float:
    """Return the runs' common ``evaluation_beta``, unless ``beta`` is given."""
    if beta is not None:
        return float(beta)
    levels = {float(r.parameters["evaluation_beta"]) for r in runs}
    if len(levels) != 1:
        raise InconsistentRunsError(
            f"the runs differ in evaluation_beta {sorted(levels)}; pass beta"
        )
    return levels.pop()


def _portfolio_kpi(run: RunResult, kpi: str, split: str, beta: float) -> dict[str, Any]:
    """Return the one portfolio-level row of ``kpi`` of a run."""
    k = run.kpis
    mask = (
        (k["level"] == KpiLevel.PORTFOLIO.value)
        & (k["kpi"] == kpi)
        & (k["eval_split"] == split)
    )
    rows = _where(k, mask)
    if bool(rows["beta"].notna().any()):
        rows = _where(rows, np.isclose(rows["beta"].to_numpy(dtype=float), beta))
    if len(rows) != 1:
        raise InconsistentRunsError(
            f"run {run.run_id} ({run.scope} x {run.objective}) has {len(rows)} "
            f"portfolio rows of KPI {kpi!r} on the {split!r} split"
            + (f" at beta {beta:g}" if len(rows) == 0 else "")
            + "; expected exactly one"
        )
    return cast(dict[str, Any], rows.iloc[0].to_dict())


def kpi_table(
    scopes: ScopeGrid,
    kpis: Sequence[str],
    *,
    eval_split: str | None = None,
    beta: float | None = None,
) -> pd.DataFrame:
    """Return portfolio-level KPI values of a scope x objective grid.

    Parameters
    ----------
    scopes : mapping of str to sequence of RunResult
        Complete runs per scope key, one per objective, the same objectives
        in every scope.
    kpis : sequence of str
        KPI names (``records.KpiName`` values).
    eval_split : str, optional
        Evaluation split; default: the first of :data:`SPLIT_PREFERENCE`
        that every run has.
    beta : float, optional
        Level of VaR/CVaR KPIs; default: the runs' ``evaluation_beta``.

    Returns
    -------
    pandas.DataFrame
        Columns :data:`KPI_COLUMNS`, one row per (scope, objective, KPI), in
        scope, objective, KPI order. A null value stays NaN.

    Raises
    ------
    IncompleteRunError
        If a run has a failed design problem.
    InconsistentRunsError
        If the grid is inconsistent, a KPI is unknown, or a run lacks the
        portfolio row of a KPI (or has several).
    KFoldRunsError
        If a run is a fold of a k-fold sample (an ``InconsistentRunsError``).
    """
    known = {k.value for k in KpiName}
    unknown = [k for k in kpis if k not in known]
    if unknown or not kpis:
        raise InconsistentRunsError(
            f"unknown KPIs {unknown or '(none)'}; known: {sorted(known)}"
        )
    _grid(scopes)
    pairs = _runs(scopes)
    runs = [r for _, r in pairs]
    split = figure_split(runs, eval_split, tables=("kpis", "exceedance"))
    level = _beta(runs, beta)
    rows: list[dict[str, object]] = []
    for key, run in pairs:
        for kpi in kpis:
            row = _portfolio_kpi(run, kpi, split, level)
            rows.append(
                {
                    "scope_key": key,
                    "scope": run.scope,
                    "objective": run.objective,
                    "run_id": run.run_id,
                    "eval_split": split,
                    "fold": int(row["fold"]),
                    "basis": str(row["basis"]),
                    "problem_id": str(row["problem_id"]),
                    "subject_id": str(row["subject_id"]),
                    "kpi": kpi,
                    "beta": row["beta"],
                    "value": row["value"],
                    "ci_low": row["ci_low"],
                    "ci_high": row["ci_high"],
                    "ci_level": row["ci_level"],
                    "n_bootstrap": row["n_bootstrap"],
                }
            )
    table = pd.DataFrame(rows, columns=list(KPI_COLUMNS))
    for column in ("beta", "value", "ci_low", "ci_high", "ci_level"):
        table[column] = table[column].astype(np.float64)
    table["n_bootstrap"] = table["n_bootstrap"].astype("Int64")
    return table


def pooled_kpi_table(
    pooled: pd.DataFrame, scope_keys: Sequence[str], kpis: Sequence[str]
) -> pd.DataFrame:
    """Return pooled k-fold KPIs as a figure table (MAR-151).

    Reads the table of the core's ``experiment.kfold.pooled_kpis`` (columns
    ``experiment.kfold.POOLED_COLUMNS``), which the ``figures`` command
    computes for a k-fold config and passes as ``FigureContext.pooled_kpis``.
    Nothing is recomputed here.

    Parameters
    ----------
    pooled : pandas.DataFrame
        ``PooledKpis.table``: one row per pooled design and KPI.
    scope_keys : sequence of str
        Figure key of each configured scope, by position in
        ``config.scopes`` (``style.config_scope_keys``).
    kpis : sequence of str
        KPI names (``records.KpiName`` values).

    Returns
    -------
    pandas.DataFrame
        Columns :data:`POOLED_KPI_COLUMNS`, one row per (pooled design, KPI),
        in the pooled table's design order, then ``kpis`` order.

    Raises
    ------
    InconsistentRunsError
        If a column is missing, a row is not a pooled portfolio row, a scope
        position has no key, a KPI is unknown, or a design lacks a KPI (or
        has several rows of it).
    """
    known = {k.value for k in KpiName}
    unknown = [k for k in kpis if k not in known]
    if unknown or not kpis:
        raise InconsistentRunsError(
            f"unknown KPIs {unknown or '(none)'}; known: {sorted(known)}"
        )
    missing = [c for c in POOLED_COLUMNS if c not in pooled.columns]
    if missing:
        raise InconsistentRunsError(
            f"the pooled KPI table lacks the columns {missing}; pass "
            "experiment.kfold.pooled_kpis(...).table"
        )
    if pooled.empty:
        raise InconsistentRunsError("the pooled KPI table has no rows")
    splits = sorted(set(pooled["eval_split"]))
    levels = sorted(set(pooled["level"]))
    if splits != [POOLED_SPLIT] or levels != [KpiLevel.PORTFOLIO.value]:
        raise InconsistentRunsError(
            f"pooled KPI rows must be {POOLED_SPLIT!r} portfolio rows; got "
            f"eval_split {splits}, level {levels}"
        )
    positions = sorted({int(p) for p in pooled["scope_position"]})
    if positions[0] < 0 or positions[-1] >= len(scope_keys):
        raise InconsistentRunsError(
            f"pooled rows name scope positions {positions}; the config has "
            f"{len(scope_keys)} scopes"
        )
    designs = list(
        dict.fromkeys(
            zip(
                (int(p) for p in pooled["scope_position"]),
                (str(o) for o in pooled["objective"]),
                strict=True,
            )
        )
    )
    rows: list[dict[str, object]] = []
    for position, objective in designs:
        for kpi in kpis:
            match = _where(
                pooled,
                (pooled["scope_position"] == position)
                & (pooled["objective"] == objective)
                & (pooled["kpi"] == kpi),
            )
            if len(match) != 1:
                raise InconsistentRunsError(
                    f"the pooled design {scope_keys[position]} x {objective} has "
                    f"{len(match)} rows of KPI {kpi!r}; expected exactly one"
                )
            row = cast(dict[str, Any], match.iloc[0].to_dict())
            rows.append(
                {
                    "scope_key": scope_keys[position],
                    "scope": str(row["scope"]),
                    "objective": objective,
                    "run_id": str(row["run_ids"]),
                    "eval_split": POOLED_SPLIT,
                    "fold": pd.NA,
                    "basis": str(row["basis"]),
                    "problem_id": str(row["problem_id"]),
                    "subject_id": str(row["subject_id"]),
                    "kpi": kpi,
                    "beta": row["beta"],
                    "value": row["value"],
                    "ci_low": row["ci_low"],
                    "ci_high": row["ci_high"],
                    "ci_level": row["ci_level"],
                    "n_bootstrap": row["n_bootstrap"],
                    "k": int(row["k"]),
                }
            )
    table = pd.DataFrame(rows, columns=list(POOLED_KPI_COLUMNS))
    for column in ("beta", "value", "ci_low", "ci_high", "ci_level"):
        table[column] = table[column].astype(np.float64)
    table["fold"] = table["fold"].astype("Int64")
    table["n_bootstrap"] = table["n_bootstrap"].astype("Int64")
    table["k"] = table["k"].astype(np.int64)
    return table


def _has_interval(table: pd.DataFrame) -> NDArray[np.bool_]:
    """Rows of a :func:`kpi_table` frame whose two bounds are finite."""
    low = table["ci_low"].to_numpy(dtype=np.float64)
    high = table["ci_high"].to_numpy(dtype=np.float64)
    return np.isfinite(low) & np.isfinite(high)


def interval_note(table: pd.DataFrame) -> str | None:
    """Describe the confidence intervals of a :func:`kpi_table` frame.

    Parameters
    ----------
    table : pandas.DataFrame
        Rows with the :data:`KPI_COLUMNS`.

    Returns
    -------
    str or None
        E.g. ``"90% block-bootstrap interval over years (B = 1000)"``; None
        if no row has both bounds.

    Raises
    ------
    InconsistentRunsError
        If the rows with bounds differ in ``ci_level`` or ``n_bootstrap``,
        or lack one of them.
    """
    drawn = _where(table, _has_interval(table))
    if drawn.empty:
        return None
    levels = drawn["ci_level"].to_numpy(dtype=np.float64)
    sizes = (
        drawn["n_bootstrap"]
        .astype("Float64")
        .to_numpy(dtype=np.float64, na_value=np.nan)
    )
    if (
        not np.all(np.isfinite(levels))
        or not np.all(np.isfinite(sizes))
        or np.unique(levels).size != 1
        or np.unique(sizes).size != 1
    ):
        raise InconsistentRunsError(
            "the runs' confidence intervals differ in level or number of "
            f"replicates (ci_level {sorted(set(levels.tolist()))}, n_bootstrap "
            f"{sorted(set(sizes.tolist()))}); draw runs bootstrapped alike"
        )
    return (
        f"{float(levels[0]) * 100:g}% block-bootstrap interval over years "
        f"(B = {int(sizes[0])})"
    )


@dataclass(frozen=True)
class Baseline:
    """The scope x objective combination other values are compared with.

    Parameters
    ----------
    scope_key : str
        Scope key of the baseline, e.g. ``"individual"``.
    objective : str
        Objective of the baseline, e.g. ``"mse"``.
    """

    scope_key: str
    objective: str

    @classmethod
    def default(cls, scopes: ScopeGrid) -> Baseline:
        """Return the first scope with the benchmark objective (``mse``), if any.

        Without the benchmark, the first scope's first objective (the thesis
        heatmap's top-left cell).
        """
        return _Layout.of_runs(scopes).default_baseline()

    def label(self, scopes: ScopeGrid) -> str:
        """Legend text, e.g. "individual scope & residual loss objective"."""
        return (
            f"{_scope_text(self.scope_key, scopes).lower()} & "
            f"{style.objective_label(self.objective).lower()}"
        )


def _scope_text(key: str, scopes: ScopeGrid) -> str:
    """Label of a scope key; repeated kinds keep their key, e.g. "(cluster_2)"."""
    return _scope_label(key, style.run_scope_name(scopes[key][0]))


def _scope_label(key: str, scope: str) -> str:
    """Label of a scope key whose scope name is ``scope``.

    ``scope`` is ``style.run_scope_name`` (or ``style.config_scope_name``):
    a cluster scope calibrated cluster by cluster is
    ``"cluster_separate"``, "Cluster scope, calibrated per cluster"
    (MAR-225), never the joint cluster scope's label.
    """
    label = style.scope_label(scope)
    return label if key == scope else f"{label} ({key})"


def _with_baseline(
    table: pd.DataFrame, baseline: Baseline, kpi: str
) -> tuple[pd.DataFrame, float]:
    """Add ``baseline_value``, ``pct_vs_baseline`` and ``is_baseline``."""
    rows = _where(table, table["kpi"] == kpi).reset_index(drop=True)
    is_base = (rows["scope_key"] == baseline.scope_key) & (
        rows["objective"] == baseline.objective
    )
    if int(np.count_nonzero(is_base.to_numpy())) != 1:
        raise InconsistentRunsError(
            f"the baseline {baseline.scope_key} x {baseline.objective} is not a "
            "combination of the figure"
        )
    ref = float(rows.loc[is_base, "value"].iloc[0])
    values = rows["value"].to_numpy(dtype=np.float64)
    if np.isfinite(ref) and ref != 0.0:
        pct = (values - ref) / ref * 100.0
    else:
        pct = np.full(values.shape, np.nan)
    rows = rows.assign(
        baseline_value=ref, pct_vs_baseline=pct, is_baseline=is_base.to_numpy()
    )
    return rows, ref


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


def _fmt_sci(value: float) -> str:
    """Thesis cell text: plain for exponents -1 to 2, else e.g. ``1.66e6``."""
    if not np.isfinite(value):
        return ""
    if value == 0:
        return "0"
    exp = int(np.floor(np.log10(abs(value))))
    if -1 <= exp <= 2:
        return f"{value:.2f}"
    return f"{value / 10**exp:.2f}e{exp}"


def _fmt_interval(low: float, high: float) -> str:
    """Interval text of a heatmap cell, e.g. ``[1.52e6, 1.80e6]``."""
    return f"[{_fmt_sci(low)}, {_fmt_sci(high)}]"


def _fmt_pct(pct: float) -> str:
    """Signed change in percent with a true minus sign (thesis)."""
    if not np.isfinite(pct):
        return ""
    if abs(pct) < 0.05:
        return "±0.0%"
    sign = "+" if pct > 0 else _MINUS
    return f"{sign}{abs(pct):.1f}%"


def _wrap(text: str, width: int = 18) -> str:
    return "\n".join(textwrap.wrap(text, width=width, break_long_words=False))


def _box(ax: Axes) -> None:
    """Black frame on all four sides (thesis)."""
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)
        spine.set_color("black")


def _titles(
    fig: Figure,
    title: str | None,
    subtitle: str | None,
    *,
    top: float = 0.985,
    second: float = 0.95,
) -> None:
    """Centred title and subtitle at the top of the figure (thesis).

    ``top`` and ``second`` are the heights of the first and second line in
    figure fractions.
    """
    if title:
        fig.text(
            0.5,
            top,
            title,
            ha="center",
            va="top",
            fontsize=style.FONT.title_size,
            fontweight="bold",
        )
    if subtitle:
        fig.text(
            0.5,
            second if title else top,
            subtitle,
            ha="center",
            va="top",
            fontsize=style.FONT.subtitle_size,
        )


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------


def heatmap_figsize(n_rows: int) -> tuple[float, float]:
    """Return the default size of a KPI heatmap with ``n_rows`` scope rows.

    The thesis heatmap is 8 x 8 inches for three scopes. With fewer rows the
    figure is less high by the rows it lacks, so the cells keep their size
    and the figure has no empty bands above and below them (MAR-232); the
    titles, axis captions and legend bar keep their distances in inches.
    From three rows on it stays 8 x 8, as before.

    Parameters
    ----------
    n_rows : int
        Scope rows, at least 1.

    Returns
    -------
    (float, float)
        Width and height in inches.

    Raises
    ------
    FigureDataError
        If ``n_rows`` is less than 1.
    """
    if n_rows < 1:
        raise FigureDataError(f"a heatmap needs at least one row, got {n_rows}")
    if n_rows >= _HEATMAP_ROWS:
        return (_HEATMAP_SIZE, _HEATMAP_SIZE)
    row = _HEATMAP_GRID * _HEATMAP_SIZE / _HEATMAP_ROWS
    return (_HEATMAP_SIZE, _HEATMAP_SIZE - (_HEATMAP_ROWS - n_rows) * row)


def kpi_heatmap(
    scopes: ScopeGrid,
    kpi: str,
    *,
    baseline: Baseline | None = None,
    eval_split: str | None = None,
    lower_is_better: bool = True,
    n_legend_bins: int = 7,
    figsize: tuple[float, float] | None = None,
    title: str | None = _HEATMAP_TITLE,
    subtitle: str | None = None,
    name: str | None = None,
) -> FigureOutput:
    """Draw one portfolio KPI for every scope x objective as a heatmap.

    Thesis ``plot_kpi_heatmap``: rows are scopes, columns objectives. Each
    cell shows the value and its change against the baseline in percent;
    the colour is that change, green for better and red for worse. A cell
    whose KPI row has bootstrap bounds also shows the interval in brackets,
    explained in a footnote (module docstring, "Confidence intervals").

    Parameters
    ----------
    scopes : mapping of str to sequence of RunResult
        Complete runs per scope key, one per objective, the same objectives
        in every scope; rows top to bottom.
    kpi : str
        KPI name, e.g. ``"cvar_uncovered"``.
    baseline : Baseline, optional
        Reference cell; default :meth:`Baseline.default`.
    eval_split : str, optional
        See :func:`kpi_table`.
    lower_is_better : bool, default True
        Colour decreases green (uncovered-loss KPIs). False flips the scale.
    n_legend_bins : int, default 7
        Colour classes of the legend bar.
    figsize : (float, float), optional
        Figure size in inches. Default :func:`heatmap_figsize`: 8 x 8 (the
        thesis notebook) for three or more scope rows, less high for fewer,
        so a one-row heatmap has no empty bands (MAR-232). A given size is
        laid out as the 8 x 8 one, in figure fractions.
    title, subtitle : str, optional
        Figure titles. Default title "Portfolio-level performance
        comparison"; default subtitle the KPI's name and symbol, followed
        by the split note (:func:`split_note`) on a ``test`` or ``train``
        split (MAR-229).
    name : str, optional
        Figure name; default ``"kpi_heatmap_<kpi>"``.

    Returns
    -------
    FigureOutput
        The figure; main table :data:`KPI_COLUMNS` plus ``baseline_value``,
        ``pct_vs_baseline``, ``is_baseline``, ``row``, ``col`` and
        ``ci_drawn`` (the cell shows the stored interval); and the ``legend``
        table (colour-class edges in percent).

    Raises
    ------
    IncompleteRunError, InconsistentRunsError
        As :func:`kpi_table` and :func:`interval_note`, or if the baseline is
        not in the grid.
    FigureDataError
        If ``n_legend_bins`` is not positive.
    """
    if n_legend_bins < 1:
        raise FigureDataError(f"n_legend_bins must be >= 1, got {n_legend_bins}")
    layout = _Layout.of_runs(scopes)
    table = kpi_table(scopes, [kpi], eval_split=eval_split)
    if subtitle is None:
        subtitle = _split_subtitle(kpi_label(kpi), table)
    return _draw_heatmap(
        layout,
        table,
        kpi,
        baseline=baseline or layout.default_baseline(),
        lower_is_better=lower_is_better,
        n_legend_bins=n_legend_bins,
        figsize=figsize,
        title=title,
        subtitle=subtitle,
        name=name,
    )


def _draw_heatmap(
    layout: _Layout,
    kpi_rows: pd.DataFrame,
    kpi: str,
    *,
    baseline: Baseline,
    lower_is_better: bool = True,
    n_legend_bins: int = 7,
    figsize: tuple[float, float] | None = None,
    title: str | None = _HEATMAP_TITLE,
    subtitle: str | None = None,
    name: str | None = None,
) -> FigureOutput:
    """Draw :func:`kpi_heatmap` from a KPI table and its layout.

    ``kpi_rows`` has the :data:`KPI_COLUMNS` (more columns are kept in the
    figure data), from :func:`kpi_table` or :func:`pooled_kpi_table`.
    """
    if n_legend_bins < 1:
        raise FigureDataError(f"n_legend_bins must be >= 1, got {n_legend_bins}")
    keys, objectives = list(layout.keys), list(layout.objectives)
    table, _ = _with_baseline(kpi_rows, baseline, kpi)
    table = table.assign(
        row=[keys.index(k) for k in table["scope_key"]],
        col=[objectives.index(o) for o in table["objective"]],
        ci_drawn=_has_interval(table),
    )
    note = interval_note(table)
    pct = table["pct_vs_baseline"].to_numpy(dtype=np.float64)
    finite = pct[np.isfinite(pct)]
    max_abs = float(np.max(np.abs(finite))) if finite.size else 1.0
    max_abs = max_abs or 1.0
    cmap = _CMAP if lower_is_better else _CMAP.reversed()
    norm = Normalize(vmin=-max_abs, vmax=max_abs)
    bounds = np.linspace(-max_abs, max_abs, n_legend_bins + 1)
    legend_cmap = ListedColormap(cmap((np.arange(n_legend_bins) + 0.5) / n_legend_bins))
    n_rows, n_cols = len(keys), len(objectives)
    label = KPI_LABELS.get(kpi)
    symbol = label.symbol if label else kpi.replace("_", " ")
    if subtitle is None:
        subtitle = kpi_label(kpi)

    if figsize is None:
        figsize = heatmap_figsize(n_rows)
        scale = _HEATMAP_SIZE / figsize[1]  # the 8-inch layout's inches kept
    else:
        scale = 1.0

    def up(fraction: float) -> float:
        """Return a figure fraction at the 8-inch layout's inches above the bottom."""
        return fraction if scale == 1.0 else fraction * scale

    def down(fraction: float) -> float:
        """Return a figure fraction at the 8-inch layout's inches below the top."""
        return fraction if scale == 1.0 else 1.0 - (1.0 - fraction) * scale

    with style.style():
        fig, ax = plt.subplots(figsize=figsize)
        for record in table.to_dict("records"):
            value = float(record["value"])
            if not np.isfinite(value):
                continue
            change = float(record["pct_vs_baseline"])
            color = cmap(norm(change)) if np.isfinite(change) else cmap(0.5)
            cx, cy = int(record["col"]), (n_rows - 1) - int(record["row"])
            ax.add_patch(
                FancyBboxPatch(
                    (cx - 0.5 + _CELL_INSET, cy - 0.5 + _CELL_INSET),
                    1 - 2 * _CELL_INSET,
                    1 - 2 * _CELL_INSET,
                    boxstyle=f"round,pad=0,rounding_size={_CORNER_RADIUS}",
                    facecolor=color,
                    edgecolor="white",
                    linewidth=1.0,
                )
            )
            r, g, b, _ = color
            luminance = 0.299 * r + 0.587 * g + 0.114 * b
            text_color = "white" if luminance < 0.55 else _DARK_TEXT
            ax.text(
                cx,
                cy + 0.10,
                _fmt_sci(value),
                ha="center",
                va="center",
                fontsize=_HEATMAP_FONT + 6,
                color=text_color,
            )
            change_text = "baseline" if record["is_baseline"] else _fmt_pct(change)
            if change_text:
                ax.text(
                    cx,
                    cy - 0.10,
                    change_text,
                    ha="center",
                    va="center",
                    fontsize=_HEATMAP_FONT,
                    fontstyle="italic",
                    color=text_color,
                )
            if record["ci_drawn"]:
                ax.text(
                    cx,
                    cy - 0.28,
                    _fmt_interval(float(record["ci_low"]), float(record["ci_high"])),
                    ha="center",
                    va="center",
                    fontsize=_HEATMAP_FONT - 1,
                    color=text_color,
                )
        ax.set_xlim(-0.5, n_cols - 0.5)
        ax.set_ylim(-0.5, n_rows - 0.5)
        ax.set_aspect("equal")
        ax.set_xticks(np.arange(n_cols))
        ax.set_xticklabels(
            [_wrap(style.objective_label(o)) for o in objectives],
            fontsize=_HEATMAP_FONT,
        )
        ax.xaxis.tick_top()
        ax.set_yticks(np.arange(n_rows))
        ax.set_yticklabels(
            [_wrap(layout.scope_text(k)) for k in reversed(keys)],
            fontsize=_HEATMAP_FONT,
        )
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(axis="both", length=0, pad=12)
        ax.add_patch(
            Rectangle(
                (-0.5, -0.5),
                n_cols,
                n_rows,
                linewidth=1.5,
                edgecolor="black",
                facecolor="none",
                zorder=10,
            )
        )
        fig.subplots_adjust(left=0.24, right=0.96, top=down(0.80), bottom=up(0.18))

        # Axis captions beside the tick labels, placed from their extents.
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()  # pyright: ignore[reportAttributeAccessIssue]
        to_fig = fig.transFigure.inverted()
        x_top = max(t.get_window_extent(renderer).y1 for t in ax.get_xticklabels())
        y_left = min(t.get_window_extent(renderer).x0 for t in ax.get_yticklabels())
        x_top_fig = to_fig.transform((0, x_top))[1]
        y_left_fig = to_fig.transform((y_left, 0))[0]
        box = ax.get_position()
        fig.text(
            (box.x0 + box.x1) / 2,
            x_top_fig + up(0.025),
            r"Optimization objective $\rightarrow$",
            ha="center",
            va="bottom",
            fontsize=_HEATMAP_FONT,
            fontstyle="italic",
            color=_AXIS_TEXT_COLOR,
        )
        fig.text(
            y_left_fig - 0.025,
            (box.y0 + box.y1) / 2,
            r"$\leftarrow$ Optimization scope",
            ha="center",
            va="center",
            rotation=90,
            fontsize=_HEATMAP_FONT,
            fontstyle="italic",
            color=_AXIS_TEXT_COLOR,
        )

        # Legend bar under the first two columns (thesis).
        left = to_fig.transform(ax.transData.transform((-0.5, 0)))[0]
        right = to_fig.transform(ax.transData.transform((min(1.5, n_cols - 0.5), 0)))[0]
        cax = fig.add_axes((left, up(0.08), right - left, up(0.022)))
        mappable = ScalarMappable(
            norm=BoundaryNorm(bounds, legend_cmap.N), cmap=legend_cmap
        )
        bar = fig.colorbar(
            mappable,
            cax=cax,
            orientation="horizontal",
            boundaries=bounds,
            ticks=[-max_abs, 0.0, max_abs],
            spacing="proportional",
        )
        bar.set_ticklabels([f"{_MINUS}{max_abs:.0f}%", "baseline", f"+{max_abs:.0f}%"])
        bar.ax.tick_params(length=0, labelsize=_HEATMAP_FONT)
        bar.outline.set_visible(False)  # pyright: ignore[reportAttributeAccessIssue]
        bar.dividers.set_color("white")  # pyright: ignore[reportOptionalMemberAccess]
        bar.dividers.set_linewidth(1.5)  # pyright: ignore[reportOptionalMemberAccess]
        cax.set_title(
            f"{symbol} [% vs. baseline]",
            fontsize=_HEATMAP_FONT,
            loc="left",
            pad=8,
        )
        if note:
            fig.text(
                0.5,
                up(0.015),
                f"In brackets: {note}",
                ha="center",
                va="bottom",
                fontsize=_HEATMAP_FONT - 1,
                color=_AXIS_TEXT_COLOR,
            )
        _titles(fig, title, subtitle, top=down(0.985), second=down(0.95))

    legend = pd.DataFrame(
        {
            "class": np.arange(n_legend_bins, dtype=np.int64),
            "lower_pct": bounds[:-1],
            "upper_pct": bounds[1:],
        }
    )
    return FigureOutput(
        name=name or f"kpi_heatmap_{kpi}",
        figure=fig,
        data={MAIN_TABLE: table, "legend": legend},
    )


def performance_overview(
    scopes: ScopeGrid,
    *,
    kpis: Sequence[str] = OVERVIEW_KPIS,
    baseline: Baseline | None = None,
    eval_split: str | None = None,
    labels: AxisLabels | None = None,
    figsize: tuple[float, float] | None = (6.0, 8.0),
    name: str = "performance_overview",
) -> FigureOutput:
    """Draw portfolio KPIs as bars grouped by scope, one panel per KPI.

    Thesis ``plot_portfolio_performance_overview`` (Figure 5.5): within each
    scope group one bar per objective in its colour; a dotted line marks the
    baseline's value. A bar whose KPI row has bootstrap bounds carries an
    interval bar from ``ci_low`` to ``ci_high`` (module docstring,
    "Confidence intervals"). On a ``test`` or ``train`` split a subtitle
    states it ("Portfolio KPIs, out of sample (test years)", MAR-229).

    Parameters
    ----------
    scopes : mapping of str to sequence of RunResult
        Complete runs per scope key, one per objective, the same objectives
        in every scope; groups left to right.
    kpis : sequence of str, default :data:`OVERVIEW_KPIS`
        One panel per KPI, top to bottom.
    baseline : Baseline, optional
        Dotted reference; default :meth:`Baseline.default`.
    eval_split : str, optional
        See :func:`kpi_table`.
    labels : AxisLabels, optional
        Its ``payout_unit`` labels the KPI axes.
    figsize : (float, float), optional
        Figure size in inches; default (6, 8) (thesis notebook). None sizes
        by the number of scopes and panels, as the thesis default.
    name : str, default "performance_overview"
        Figure name.

    Returns
    -------
    FigureOutput
        The figure; main table :data:`KPI_COLUMNS` plus ``baseline_value``,
        ``pct_vs_baseline``, ``is_baseline``, ``bar_x`` (bar position) and
        ``ci_drawn`` (the bar carries the stored interval).

    Raises
    ------
    IncompleteRunError, InconsistentRunsError
        As :func:`kpi_table` and :func:`interval_note`, or if the baseline is
        not in the grid.
    """
    layout = _Layout.of_runs(scopes)
    table = kpi_table(scopes, kpis, eval_split=eval_split)
    return _draw_overview(
        layout,
        table,
        kpis,
        baseline=baseline or layout.default_baseline(),
        labels=labels,
        figsize=figsize,
        name=name,
        subtitle=_split_subtitle("Portfolio KPIs", table),
    )


def _draw_overview(
    layout: _Layout,
    table: pd.DataFrame,
    kpis: Sequence[str],
    *,
    baseline: Baseline,
    labels: AxisLabels | None = None,
    figsize: tuple[float, float] | None = (6.0, 8.0),
    name: str = "performance_overview",
    subtitle: str | None = None,
) -> FigureOutput:
    """Draw :func:`performance_overview` from a KPI table and its layout.

    ``table`` has the :data:`KPI_COLUMNS` (from :func:`kpi_table` or
    :func:`pooled_kpi_table`). A ``subtitle`` is drawn above the panels.
    """
    keys, objectives = list(layout.keys), list(layout.objectives)
    labels = labels or AxisLabels()
    note = interval_note(table)
    interval_handle: Any = None
    span = (len(objectives) - 1) * _BAR_SPACING
    centres = np.arange(len(keys)) * (span + _GROUP_GAP)
    offsets = (np.arange(len(objectives)) - (len(objectives) - 1) / 2) * _BAR_SPACING
    size = figsize or (max(6.0, 2.0 * len(keys) + 2.0), 3.0 * len(kpis))
    panels: list[pd.DataFrame] = []

    with style.style():
        fig, axes = plt.subplots(nrows=len(kpis), ncols=1, figsize=size, squeeze=False)
        for i, kpi in enumerate(kpis):
            ax = axes[i, 0]
            rows, ref = _with_baseline(table, baseline, kpi)
            x = [
                float(centres[keys.index(k)] + offsets[objectives.index(o)])
                for k, o in zip(rows["scope_key"], rows["objective"], strict=True)
            ]
            rows = rows.assign(bar_x=x, ci_drawn=_has_interval(rows))
            panels.append(rows)
            ax.bar(
                rows["bar_x"],
                rows["value"],
                width=_BAR_WIDTH,
                color=[style.objective_color(o) for o in rows["objective"]],
                edgecolor="none",
            )
            with_ci = _where(rows, rows["ci_drawn"])
            if not with_ci.empty:
                interval_handle = _interval_bars(ax, with_ci)
            if np.isfinite(ref):
                ax.axhline(y=ref, color="black", linestyle=":", linewidth=1.0, zorder=0)
            ax.set_xticks(centres)
            ax.set_xticklabels(
                [layout.scope_text(k) for k in keys], fontsize=style.FONT.tick_size
            )
            ax.set_xlim(
                centres[0] - span / 2 - _BAR_WIDTH, centres[-1] + span / 2 + _BAR_WIDTH
            )
            ax.set_ylabel(
                kpi_label(kpi, unit=labels.payout_unit),
                fontsize=style.FONT.label_size,
                labelpad=10,
            )
            ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
            _box(ax)
        top = 0.97 if subtitle is None else 0.93
        fig.subplots_adjust(left=0.14, right=0.98, top=top, bottom=0.14, hspace=0.35)
        _titles(fig, None, subtitle)
        objective_handles = [
            Rectangle((0, 0), 1, 1, color=style.objective_color(o)) for o in objectives
        ]
        fig.legend(
            objective_handles,
            [style.objective_label(o) for o in objectives],
            loc="upper center",
            bbox_to_anchor=(0.5, 0.075),
            ncol=len(objectives),
            frameon=False,
            fontsize=style.FONT.legend_size,
        )
        reference_handles: list[Any] = [
            Line2D([0], [0], color="grey", linestyle=":", linewidth=1.0)
        ]
        reference_labels = [f"Baseline ({layout.baseline_label(baseline)})"]
        if interval_handle is not None and note is not None:
            reference_handles.append(interval_handle)
            reference_labels.append(note)
        fig.legend(
            reference_handles,
            reference_labels,
            loc="upper center",
            bbox_to_anchor=(0.5, 0.035),
            ncol=1 if len(reference_handles) == 1 else 2,
            frameon=False,
            fontsize=style.FONT.legend_size,
        )

    main = pd.concat(panels, ignore_index=True)
    return FigureOutput(name=name, figure=fig, data={MAIN_TABLE: main})


def _interval_bars(ax: Axes, rows: pd.DataFrame) -> Any:  # noqa: ANN401
    """Draw the stored intervals of ``rows`` at their ``bar_x``.

    Drawn as a symmetric error bar about the interval's midpoint, so that the
    whole interval ``[ci_low, ci_high]`` is shown whether or not it contains
    the point estimate. Returns the matplotlib container, a legend handle.
    """
    low = rows["ci_low"].to_numpy(dtype=np.float64)
    high = rows["ci_high"].to_numpy(dtype=np.float64)
    return ax.errorbar(
        rows["bar_x"].to_numpy(dtype=np.float64),
        (low + high) / 2.0,
        yerr=(high - low) / 2.0,
        fmt="none",
        ecolor=_CI_COLOR,
        elinewidth=_CI_LINEWIDTH,
        capsize=_CI_CAPSIZE,
        zorder=3,
    )


def _default_curve(basis: str) -> str:
    """``event`` on the event bases, ``aep`` on the annual basis."""
    return CurveKind.EVENT.value if basis in _EVENT_BASES else CurveKind.AEP.value


def _return_period_unit(basis: str) -> str:
    """Return the unit of the return period on a basis (core ``evaluate``, MAR-139).

    ``events`` on ``event_conditional`` (``1 / T`` is a share of the given
    events), ``years`` on ``annual`` (exactly) and ``event`` (the mean
    recurrence interval in years).
    """
    return "events" if basis == Basis.EVENT_CONDITIONAL.value else "years"


def return_period_label(basis: str) -> str:
    """Axis label of the return period on a basis (MAR-117, MAR-139).

    Parameters
    ----------
    basis : str
        ``records`` basis value of the curves.

    Returns
    -------
    str
        ``"Return period $RP$ [events]"`` on ``event_conditional``,
        ``"Return period $RP$ [years]"`` on ``annual`` and ``event``.
    """
    return rf"Return period $RP$ [{_return_period_unit(basis)}]"


def _curve_rows(
    run: RunResult, key: str, split: str, quantity: str, curve: str | None
) -> pd.DataFrame:
    """Return the portfolio-level exceedance rows of one run."""
    e = run.exceedance
    mask = (
        (e["level"] == KpiLevel.PORTFOLIO.value)
        & (e["eval_split"] == split)
        & (e["quantity"] == quantity)
    )
    rows = _where(e, mask)
    if rows.empty:
        raise InconsistentRunsError(
            f"run {run.run_id} ({run.scope} x {run.objective}) has no portfolio "
            f"exceedance rows of {quantity!r} on the {split!r} split"
        )
    bases = sorted(set(rows["basis"]))
    kind = curve or _default_curve(bases[0])
    rows = _where(rows, rows["curve"] == kind)
    if rows.empty or len(set(rows["subject_id"])) != 1:
        raise InconsistentRunsError(
            f"run {run.run_id} needs exactly one portfolio {kind!r} curve of "
            f"{quantity!r}; found subjects {sorted(set(rows['subject_id']))}"
        )
    rows = rows.sort_values("return_period", kind="stable")
    return pd.DataFrame(
        {
            "scope_key": key,
            "scope": run.scope,
            "objective": run.objective,
            "run_id": run.run_id,
            "eval_split": split,
            "fold": rows["fold"].to_numpy(dtype=np.int64),
            "basis": rows["basis"].to_numpy(),
            "problem_id": rows["problem_id"].to_numpy(),
            "subject_id": rows["subject_id"].to_numpy(),
            "quantity": quantity,
            "curve": kind,
            "return_period": rows["return_period"].to_numpy(dtype=np.float64),
            "value": rows["value"].to_numpy(dtype=np.float64),
            "source": "exceedance",
        },
        columns=list(CURVE_COLUMNS),
    )


def exceedance_curves(
    runs: Sequence[RunResult],
    *,
    scope_key: str | None = None,
    quantity: str = CurveQuantity.UNCOVERED.value,
    curve: str | None = None,
    eval_split: str | None = None,
    beta: float | None = None,
    labels: AxisLabels | None = None,
    figsize: tuple[float, float] = (8.0, 6.0),
    name: str | None = None,
) -> FigureOutput:
    """Draw the portfolio exceedance curves of one scope, one per objective.

    Thesis ``plot_exceedance_curves`` (Figure 5.6): the portfolio value of
    ``quantity`` exceeded on average once per return period, from the
    store's ``exceedance`` table, on a log return-period axis. A dashed line
    marks the VaR return period ``1 / (1 - beta)``; the tail beyond it,
    where CVaR acts, is shaded. The return period is in years on the
    ``annual`` and ``event`` bases and in events on ``event_conditional``,
    and the axis says which (:func:`return_period_label`).

    For the uncovered loss on the ``event`` or ``aep`` curve, the
    portfolio ``var_uncovered`` KPI at ``beta`` is the same quantile at
    ``1 / (1 - beta)``; it is added as that curve point (``source =
    "kpis"``) when that return period lies inside the stored range but is
    not one of the stored points.

    On a ``test`` or ``train`` split the axes title states it
    (:func:`split_note`, MAR-229); the ``eval_split`` column of the figure
    data records it on every split.

    Parameters
    ----------
    runs : sequence of RunResult
        Complete runs of one scope, one per objective, in legend order.
    scope_key : str, optional
        Scope key for the figure data and the default name; default the
        runs' scope name (``style.run_scope_name``).
    quantity : str, default "uncovered"
        ``records.CurveQuantity`` value.
    curve : str, optional
        ``records.CurveKind`` value; default ``event`` on the event bases and
        ``aep`` on the annual basis.
    eval_split : str, optional
        See :func:`kpi_table`.
    beta : float, optional
        VaR level of the marked return period; default the runs'
        ``evaluation_beta``.
    labels : AxisLabels, optional
        Its ``payout_unit`` labels the value axis, after the prefix of the
        axis range: ``[M USD]`` from one million (the thesis), ``[k USD]``
        from one thousand, else ``[USD]``. The ticks are labelled in that
        prefix with the decimals they need (``style.MoneyFormatter``,
        MAR-197).
    figsize : (float, float), default (8, 6)
        Figure size in inches (thesis notebook).
    name : str, optional
        Figure name; default ``"exceedance_<scope_key>"``.

    Returns
    -------
    FigureOutput
        The figure; main table :data:`CURVE_COLUMNS`, one row per plotted
        point; ``markers`` (the VaR return period, its unit and level).

    Raises
    ------
    IncompleteRunError
        If a run has a failed design problem.
    InconsistentRunsError
        If the runs mix scopes or bases, repeat an objective, lack the curve,
        or disagree on its return periods.
    KFoldRunsError
        If a run is a fold of a k-fold sample (an ``InconsistentRunsError``).
    """
    runs = tuple(runs)
    if not runs:
        raise InconsistentRunsError("an exceedance figure needs at least one run")
    key = scope_key or style.run_scope_name(runs[0])
    _grid({key: runs})
    labels = labels or AxisLabels()
    split = figure_split(runs, eval_split, tables=("kpis", "exceedance"))
    level = _beta(runs, beta)
    # rounded so that e.g. beta 0.95 gives 20, not 19.999999999999982
    var_period = float(f"{1.0 / (1.0 - level):.12g}") if level < 1.0 else math.inf
    frames = [_curve_rows(r, key, split, quantity, curve) for r in runs]
    periods = {tuple(f["return_period"]) for f in frames}
    if len(periods) != 1:
        raise InconsistentRunsError(
            f"the runs' exceedance curves have different return periods: "
            f"{sorted(periods)}"
        )
    kinds = {str(f["curve"].iloc[0]) for f in frames}
    if len(kinds) != 1:
        raise InconsistentRunsError(f"the runs mix curve kinds {sorted(kinds)}")
    kind = kinds.pop()
    stored = np.asarray(next(iter(periods)), dtype=np.float64)
    add_var = (
        quantity == CurveQuantity.UNCOVERED.value
        and kind in {CurveKind.EVENT.value, CurveKind.AEP.value}
        and bool(stored[0] < var_period < stored[-1])  # inside the stored range
        and not np.any(np.isclose(stored, var_period))
    )
    if add_var:
        for i, run in enumerate(runs):
            row = _portfolio_kpi(run, KpiName.VAR_UNCOVERED.value, split, level)
            point = (
                frames[i]
                .iloc[[0]]
                .assign(
                    return_period=var_period, value=float(row["value"]), source="kpis"
                )
            )
            frames[i] = (
                pd.concat([frames[i], point], ignore_index=True)
                .sort_values("return_period", kind="stable")
                .reset_index(drop=True)
            )
    table = pd.concat(frames, ignore_index=True)
    bases = sorted({str(b) for b in table["basis"]})
    if len(bases) != 1:
        raise InconsistentRunsError(f"the runs mix evaluation bases {bases}")
    unit = _return_period_unit(bases[0])
    all_periods = np.unique(table["return_period"].to_numpy(dtype=np.float64))
    lo, hi = float(all_periods[0]), float(all_periods[-1])
    scope = style.run_scope_name(runs[0])
    linestyle = style.SCOPE_STYLES.get(scope, style.ScopeStyle("-", "o"))

    with style.style():
        fig, ax = plt.subplots(figsize=figsize)
        if lo <= var_period < hi:
            ax.axvspan(var_period, hi, color=_TAIL_SHADE, alpha=_TAIL_ALPHA, zorder=0)
            ax.axvline(var_period, color="black", linestyle="--", linewidth=1.0)
            ax.text(
                var_period * 0.97,
                0.5,
                rf"$VaR_{{\beta = {level:g}}}$ ($RP\ {var_period:g}$ {unit})",
                transform=ax.get_xaxis_transform(),
                rotation=90,
                ha="right",
                va="center",
                fontsize=style.FONT.tick_size,
            )
        for frame in frames:
            objective = str(frame["objective"].iloc[0])
            ax.plot(
                frame["return_period"],
                frame["value"],
                color=style.objective_color(objective),
                linestyle=linestyle.linestyle,
                marker=linestyle.marker,
                markersize=5,
                linewidth=1.5,
                label=style.objective_label(objective),
                zorder=2,
            )
        ax.set_xscale("log")
        ax.set_xticks(list(all_periods))
        ax.set_xticklabels([f"{t:g}" for t in all_periods])
        ax.minorticks_off()
        ax.set_xlim(lo, hi)
        ax.set_xlabel(return_period_label(bases[0]))
        ax.set_ylim(bottom=0)
        # Thesis ``format_millions`` (``1.5M``) in millions; k or plain units
        # below, with the decimals the ticks need (MAR-197).
        prefix = style.money_prefix(max(abs(v) for v in ax.get_ylim()))
        value_unit = " ".join(u for u in (prefix, labels.payout_unit) if u)
        ax.set_ylabel(
            _curve_label(quantity) + (f" [{value_unit}]" if value_unit else "")
        )
        ax.yaxis.set_major_formatter(style.MoneyFormatter(prefix))
        _box(ax)
        note = split_note(split)
        if note is not None:
            ax.set_title(note[0].upper() + note[1:], fontsize=style.FONT.label_size)
        fig.tight_layout()
        objectives = [str(f["objective"].iloc[0]) for f in frames]
        handles = [  # lines without markers, as the thesis legend
            Line2D(
                [0],
                [0],
                color=style.objective_color(o),
                linestyle=cast(Any, linestyle.linestyle),
                linewidth=1.5,
            )
            for o in objectives
        ]
        fig.legend(
            handles,
            [style.objective_label(o) for o in objectives],
            loc="upper center",
            bbox_to_anchor=(0.5, 0.0),
            ncol=len(handles),
            frameon=False,
            fontsize=style.FONT.legend_size,
        )

    markers = pd.DataFrame(
        [
            {
                "marker": "var_return_period",
                "beta": level,
                "return_period": var_period,
                "unit": unit,
                "drawn": bool(lo <= var_period < hi),
            }
        ]
    )
    return FigureOutput(
        name=name or f"exceedance_{key}",
        figure=fig,
        data={MAIN_TABLE: table, "markers": markers},
    )


def _curve_label(quantity: str) -> str:
    """Value-axis label of an exceedance curve (thesis wording)."""
    return {
        CurveQuantity.UNCOVERED.value: r"Portfolio uncovered losses $UL^P$",
        CurveQuantity.LOSS.value: r"Portfolio losses $L^P$",
        CurveQuantity.PAYOUT.value: r"Portfolio payouts $Y^P$",
    }.get(quantity, quantity)


# --------------------------------------------------------------------------
# Figure set
# --------------------------------------------------------------------------


def kpi_figures(context: FigureContext) -> list[FigureOutput | SkippedFigure]:
    """KPI heatmaps, performance overview and exceedance curves of a config.

    Parameters
    ----------
    context : FigureContext
        The config's runs.

    Returns
    -------
    list
        ``kpi_heatmap_<kpi>`` for each of :data:`HEATMAP_KPIS`, then
        ``performance_overview``, then ``exceedance_<scope key>`` per scope.
        A cross-scope figure is skipped (``failed=True``) if any run failed;
        an exceedance figure if a run of its scope failed. For a k-fold
        config (MAR-151) the cross-scope figures show the pooled KPIs of
        ``context.pooled_kpis`` and every exceedance figure is skipped
        (``failed=False``, or ``True`` if a fold of its scope failed).

    Raises
    ------
    KFoldRunsError
        If the config's sample is ``kfold`` and ``context.pooled_kpis`` is
        None. Nothing is drawn.
    InconsistentRunsError
        If the pooled KPI table does not fit the config (:func:`pooled_kpi_table`).
    """
    # Imported here: command imports this module to register the builder.
    from parametric_insurance_design_viz.command import SkippedFigure

    sample = context.config.sample
    if sample.kind == "kfold":  # KFOLD_SAMPLE, as a literal for narrowing
        return _pooled_figures(context, sample.k)
    out: list[FigureOutput | SkippedFigure] = []
    failed = [s for s in context.scopes if s.failed]
    grid = {s.key: s.runs for s in context.scopes}
    cross = [f"kpi_heatmap_{k}" for k in HEATMAP_KPIS] + ["performance_overview"]
    if failed:
        reason = "; ".join(s.failure_reason() for s in failed)
        out.extend(SkippedFigure(n, reason, failed=True) for n in cross)
    else:
        for kpi in HEATMAP_KPIS:
            out.append(kpi_heatmap(grid, kpi))
        out.append(performance_overview(grid, labels=context.labels))
    for scope in context.scopes:
        name = f"exceedance_{scope.key}"
        if scope.failed:
            out.append(SkippedFigure(name, scope.failure_reason(), failed=True))
            continue
        out.append(
            exceedance_curves(
                scope.runs, scope_key=scope.key, labels=context.labels, name=name
            )
        )
    return out


POOLED_EXCEEDANCE_REASON: Final[str] = (
    "k-fold config: the exceedance curves are not pooled (MAR-151). The pooled "
    "rule covers the portfolio KPIs; the exceedance table holds one curve per "
    "fold, over 1/k of the years, and the figures never re-evaluate payouts"
)
"""Why :func:`kpi_figures` skips the exceedance figures of a k-fold config."""


def _pooled_figures(
    context: FigureContext, k: int
) -> list[FigureOutput | SkippedFigure]:
    """Draw the KPI figures of a k-fold config from its pooled KPIs (MAR-151)."""
    from parametric_insurance_design_viz.command import SkippedFigure

    pooled = context.pooled_kpis
    if pooled is None:
        raise KFoldRunsError(
            f"config {context.config.name!r} has a k-fold sample (k={k}): its KPI "
            "figures show the pooled out-of-sample KPIs (MAR-151), and none were "
            "given. Compute them with experiment.kfold.pooled_kpis and pass "
            "pooled_kpis=...table (the figures command does this)"
        )
    out: list[FigureOutput | SkippedFigure] = []
    failed = [s for s in context.scopes if s.failed]
    cross = [f"kpi_heatmap_{kpi}" for kpi in HEATMAP_KPIS] + ["performance_overview"]
    if failed:
        reason = "; ".join(s.failure_reason() for s in failed)
        out.extend(SkippedFigure(n, reason, failed=True) for n in cross)
    else:
        keys = [s.key for s in context.scopes]
        kpis = list(dict.fromkeys([*HEATMAP_KPIS, *OVERVIEW_KPIS]))
        table = pooled_kpi_table(pooled, keys, kpis)
        names = [style.config_scope_name(c) for c in context.config.scopes]
        layout = _Layout.of_table(table, dict(zip(keys, names, strict=True)))
        if layout.keys != tuple(keys):
            raise InconsistentRunsError(
                f"the pooled KPIs cover the scopes {list(layout.keys)}; the "
                f"config has {keys}"
            )
        expected = tuple(o.kind for o in context.config.objectives)
        if layout.objectives != expected:
            raise InconsistentRunsError(
                f"the pooled KPIs cover the objectives {list(layout.objectives)}; "
                f"the config has {list(expected)}"
            )
        folds = sorted({int(n) for n in table["k"]})
        if folds != [k]:
            raise InconsistentRunsError(
                f"the pooled KPIs are over k = {folds} folds; the config has k = {k}"
            )
        setup = f"pooled out of sample over k = {k} folds"
        baseline = layout.default_baseline()
        for kpi in HEATMAP_KPIS:
            out.append(
                _draw_heatmap(
                    layout,
                    _where(table, table["kpi"] == kpi),
                    kpi,
                    baseline=baseline,
                    subtitle=f"{kpi_label(kpi)}, {setup}",
                    name=f"kpi_heatmap_{kpi}",
                )
            )
        out.append(
            _draw_overview(
                layout,
                _where(table, table["kpi"].isin(OVERVIEW_KPIS)),
                OVERVIEW_KPIS,
                baseline=baseline,
                labels=context.labels,
                subtitle=f"Portfolio KPIs, {setup}",
            )
        )
    for scope in context.scopes:
        name = f"exceedance_{scope.key}"
        if scope.failed:
            out.append(SkippedFigure(name, scope.failure_reason(), failed=True))
        else:
            out.append(SkippedFigure(name, POOLED_EXCEEDANCE_REASON, failed=False))
    return out
