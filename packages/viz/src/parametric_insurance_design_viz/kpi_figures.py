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
  figure data record the split.
* **Samples:** ``full`` and ``holdout`` runs. Runs of a ``kfold`` sample are
  refused with :class:`KFoldRunsError` (MAR-137). A k-fold experiment is a
  run per fold (MAR-22), so one scope x objective has ``k`` test values; a
  figure that drew one of them, or their mean without the spread, would
  misstate the result. The figures accept k-fold runs once the rule for
  combining folds is decided together with the confidence intervals
  (MAR-23).
* **VaR/CVaR level:** the rows at the runs' ``evaluation_beta`` parameter.
* **Curve:** ``event`` on the event bases (return periods count events, the
  thesis convention), ``aep`` on the ``annual`` basis.

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
from matplotlib.ticker import FuncFormatter

from parametric_insurance_design.basis import Basis
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
    "SPLIT_PREFERENCE",
    "Baseline",
    "KFoldRunsError",
    "exceedance_curves",
    "kpi_figures",
    "kpi_heatmap",
    "kpi_label",
    "kpi_table",
    "performance_overview",
]

ScopeGrid = Mapping[str, Sequence[RunResult]]
"""Runs per scope key (e.g. ``"individual"``, ``"cluster_2"``), in order."""

SPLIT_PREFERENCE: Final[tuple[str, ...]] = (
    Split.TEST.value,
    Split.FULL.value,
    Split.TRAIN.value,
)
"""Evaluation split read when every run has it, in order of preference."""

KFOLD_SAMPLE: Final[str] = "kfold"
"""``runs.parameters["sample"]`` of a k-fold run, which the figures refuse."""


class KFoldRunsError(InconsistentRunsError):
    """The runs are folds of a k-fold sample, which the KPI figures refuse.

    A k-fold experiment stores a run per fold (MAR-22), so one scope x
    objective has ``k`` out-of-sample values. The KPI figures don't combine
    folds yet (MAR-137): the rule, e.g. the mean over folds with the
    per-fold spread, is decided with the confidence intervals (MAR-23).
    Draw the figures from a ``holdout`` (or ``full``) run instead.
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
)
"""Columns of :func:`kpi_table`."""

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

_CMAP: Final[LinearSegmentedColormap] = LinearSegmentedColormap.from_list(
    "GreenWhiteRed", ["#006837", "#ffffff", "#a50026"]
)
_MINUS: Final[str] = "\N{MINUS SIGN}"  # thesis: a true minus sign
_HEATMAP_TITLE: Final[str] = "Portfolio-level performance comparison"
_CELL_INSET: Final[float] = 0.015
_CORNER_RADIUS: Final[float] = 0.05
_HEATMAP_FONT: Final[float] = 10  # thesis plot_kpi_heatmap label_size default
_AXIS_TEXT_COLOR: Final[str] = "#444"
_DARK_TEXT: Final[str] = "#0a2540"
_BAR_WIDTH: Final[float] = 0.1
_BAR_SPACING: Final[float] = 0.1
_GROUP_GAP: Final[float] = 0.25
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
            "experiment has a run per fold, and the rule for combining folds "
            "is decided with the confidence intervals (MAR-23); draw the "
            "figures from a holdout run"
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
        kinds = sorted({r.scope for r in runs})
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


def _runs(scopes: ScopeGrid) -> list[tuple[str, RunResult]]:
    return [(key, run) for key in scopes for run in scopes[key]]


def _eval_split(runs: Sequence[RunResult], eval_split: str | None) -> str:
    """Return the split every run has: ``eval_split`` or the preferred one."""
    have = [set(r.kpis["eval_split"]) | set(r.exceedance["eval_split"]) for r in runs]
    common = set.intersection(*have) if have else set()
    if eval_split is not None:
        if eval_split not in common:
            raise InconsistentRunsError(
                f"not every run has KPI rows on the {eval_split!r} split"
            )
        return eval_split
    for split in SPLIT_PREFERENCE:
        if split in common:
            return split
    raise InconsistentRunsError(
        "the runs share no evaluation split with KPI rows; "
        f"splits per run: {[sorted(h) for h in have]}"
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
    split = _eval_split(runs, eval_split)
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
                }
            )
    table = pd.DataFrame(rows, columns=list(KPI_COLUMNS))
    for column in ("beta", "value", "ci_low", "ci_high"):
        table[column] = table[column].astype(np.float64)
    return table


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
        keys, objectives = _grid(scopes)
        objective = (
            style.BENCHMARK_OBJECTIVE
            if style.BENCHMARK_OBJECTIVE in objectives
            else objectives[0]
        )
        return cls(scope_key=keys[0], objective=objective)

    def label(self, scopes: ScopeGrid) -> str:
        """Legend text, e.g. "individual scope & residual loss objective"."""
        return (
            f"{_scope_text(self.scope_key, scopes).lower()} & "
            f"{style.objective_label(self.objective).lower()}"
        )


def _scope_text(key: str, scopes: ScopeGrid) -> str:
    """Label of a scope key; repeated kinds keep their key, e.g. "(cluster_2)"."""
    scope = scopes[key][0].scope
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


def _millions(value: float, _pos: object = None) -> str:
    """Thesis ``format_millions`` without the currency sign: ``1.5M``."""
    return f"{value * 1e-6:.1f}M"


def _box(ax: Axes) -> None:
    """Black frame on all four sides (thesis)."""
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)
        spine.set_color("black")


def _titles(fig: Figure, title: str | None, subtitle: str | None) -> None:
    """Centred title and subtitle at the top of the figure (thesis)."""
    if title:
        fig.text(
            0.5,
            0.985,
            title,
            ha="center",
            va="top",
            fontsize=style.FONT.title_size,
            fontweight="bold",
        )
    if subtitle:
        fig.text(
            0.5,
            0.95 if title else 0.985,
            subtitle,
            ha="center",
            va="top",
            fontsize=style.FONT.subtitle_size,
        )


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------


def kpi_heatmap(
    scopes: ScopeGrid,
    kpi: str,
    *,
    baseline: Baseline | None = None,
    eval_split: str | None = None,
    lower_is_better: bool = True,
    n_legend_bins: int = 7,
    figsize: tuple[float, float] = (8.0, 8.0),
    title: str | None = _HEATMAP_TITLE,
    subtitle: str | None = None,
    name: str | None = None,
) -> FigureOutput:
    """Draw one portfolio KPI for every scope x objective as a heatmap.

    Thesis ``plot_kpi_heatmap``: rows are scopes, columns objectives. Each
    cell shows the value and its change against the baseline in percent;
    the colour is that change, green for better and red for worse.

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
    figsize : (float, float), default (8, 8)
        Figure size in inches (thesis notebook).
    title, subtitle : str, optional
        Figure titles. Default title "Portfolio-level performance
        comparison"; default subtitle the KPI's name and symbol.
    name : str, optional
        Figure name; default ``"kpi_heatmap_<kpi>"``.

    Returns
    -------
    FigureOutput
        The figure; main table :data:`KPI_COLUMNS` plus ``baseline_value``,
        ``pct_vs_baseline``, ``is_baseline``, ``row`` and ``col``; and the
        ``legend`` table (colour-class edges in percent).

    Raises
    ------
    IncompleteRunError, InconsistentRunsError
        As :func:`kpi_table`, or if the baseline is not in the grid.
    FigureDataError
        If ``n_legend_bins`` is not positive.
    """
    if n_legend_bins < 1:
        raise FigureDataError(f"n_legend_bins must be >= 1, got {n_legend_bins}")
    keys, objectives = _grid(scopes)
    baseline = baseline or Baseline.default(scopes)
    table, _ = _with_baseline(
        kpi_table(scopes, [kpi], eval_split=eval_split), baseline, kpi
    )
    table = table.assign(
        row=[keys.index(k) for k in table["scope_key"]],
        col=[objectives.index(o) for o in table["objective"]],
    )
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
            [_wrap(_scope_text(k, scopes)) for k in reversed(keys)],
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
        fig.subplots_adjust(left=0.24, right=0.96, top=0.80, bottom=0.18)

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
            x_top_fig + 0.025,
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
        cax = fig.add_axes((left, 0.08, right - left, 0.022))
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
        _titles(fig, title, subtitle)

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
    baseline's value.

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
        ``pct_vs_baseline``, ``is_baseline`` and ``bar_x`` (bar position).

    Raises
    ------
    IncompleteRunError, InconsistentRunsError
        As :func:`kpi_table`, or if the baseline is not in the grid.
    """
    keys, objectives = _grid(scopes)
    baseline = baseline or Baseline.default(scopes)
    labels = labels or AxisLabels()
    table = kpi_table(scopes, kpis, eval_split=eval_split)
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
            rows = rows.assign(bar_x=x)
            panels.append(rows)
            ax.bar(
                rows["bar_x"],
                rows["value"],
                width=_BAR_WIDTH,
                color=[style.objective_color(o) for o in rows["objective"]],
                edgecolor="none",
            )
            if np.isfinite(ref):
                ax.axhline(y=ref, color="black", linestyle=":", linewidth=1.0, zorder=0)
            ax.set_xticks(centres)
            ax.set_xticklabels(
                [_scope_text(k, scopes) for k in keys], fontsize=style.FONT.tick_size
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
        fig.subplots_adjust(left=0.14, right=0.98, top=0.97, bottom=0.14, hspace=0.35)
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
        fig.legend(
            [Line2D([0], [0], color="grey", linestyle=":", linewidth=1.0)],
            [f"Baseline ({baseline.label(scopes)})"],
            loc="upper center",
            bbox_to_anchor=(0.5, 0.035),
            frameon=False,
            fontsize=style.FONT.legend_size,
        )

    main = pd.concat(panels, ignore_index=True)
    return FigureOutput(name=name, figure=fig, data={MAIN_TABLE: main})


def _default_curve(basis: str) -> str:
    """``event`` on the event bases, ``aep`` on the annual basis."""
    return CurveKind.EVENT.value if basis in _EVENT_BASES else CurveKind.AEP.value


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
    where CVaR acts, is shaded.

    For the uncovered loss on the ``event`` or ``aep`` curve, the
    portfolio ``var_uncovered`` KPI at ``beta`` is the same quantile at
    ``1 / (1 - beta)``; it is added as that curve point (``source =
    "kpis"``) when that return period lies inside the stored range but is
    not one of the stored points.

    Parameters
    ----------
    runs : sequence of RunResult
        Complete runs of one scope, one per objective, in legend order.
    scope_key : str, optional
        Scope key for the figure data and the default name; default the
        runs' scope.
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
        Its ``payout_unit`` labels the value axis.
    figsize : (float, float), default (8, 6)
        Figure size in inches (thesis notebook).
    name : str, optional
        Figure name; default ``"exceedance_<scope_key>"``.

    Returns
    -------
    FigureOutput
        The figure; main table :data:`CURVE_COLUMNS`, one row per plotted
        point; ``markers`` (the VaR return period and level).

    Raises
    ------
    IncompleteRunError
        If a run has a failed design problem.
    InconsistentRunsError
        If the runs mix scopes, repeat an objective, lack the curve, or
        disagree on its return periods.
    KFoldRunsError
        If a run is a fold of a k-fold sample (an ``InconsistentRunsError``).
    """
    runs = tuple(runs)
    if not runs:
        raise InconsistentRunsError("an exceedance figure needs at least one run")
    key = scope_key or runs[0].scope
    _grid({key: runs})
    labels = labels or AxisLabels()
    split = _eval_split(runs, eval_split)
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
    all_periods = np.unique(table["return_period"].to_numpy(dtype=np.float64))
    lo, hi = float(all_periods[0]), float(all_periods[-1])
    scope = runs[0].scope
    linestyle = style.SCOPE_STYLES.get(scope, style.ScopeStyle("-", "o"))

    with style.style():
        fig, ax = plt.subplots(figsize=figsize)
        if lo <= var_period < hi:
            ax.axvspan(var_period, hi, color=_TAIL_SHADE, alpha=_TAIL_ALPHA, zorder=0)
            ax.axvline(var_period, color="black", linestyle="--", linewidth=1.0)
            ax.text(
                var_period * 0.97,
                0.5,
                rf"$VaR_{{\beta = {level:g}}}$ ($RP\ {var_period:g}y$)",
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
        ax.set_xlabel(r"Return period $RP$ [years]")
        unit = f" [M {labels.payout_unit}]" if labels.payout_unit else " [M]"
        ax.set_ylabel(_curve_label(quantity) + unit)
        ax.yaxis.set_major_formatter(FuncFormatter(_millions))
        ax.set_ylim(bottom=0)
        _box(ax)
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
        an exceedance figure if a run of its scope failed.

    Raises
    ------
    KFoldRunsError
        If the config's sample is ``kfold``: its runs are a run per fold, and
        the KPI figures refuse folds (MAR-137). Nothing is drawn.
    """
    # Imported here: command imports this module to register the builder.
    from parametric_insurance_design_viz.command import SkippedFigure

    sample = context.config.sample
    if sample.kind == "kfold":  # KFOLD_SAMPLE, as a literal for narrowing
        raise KFoldRunsError(
            f"config {context.config.name!r} has a k-fold sample (k={sample.k}): "
            "the KPI figures refuse k-fold runs (MAR-137). A k-fold experiment "
            "has a run per fold, and the rule for combining folds is decided "
            "with the confidence intervals (MAR-23); draw the figures from a "
            "holdout config"
        )
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
