"""Sweep figures, premium reallocation and the cluster trade-off (thesis ch. 5).

Owner: MAR-112. Ports the remaining results-chapter figures of the thesis
``plotting.py`` and ``sensitivity_analysis.py``
(parametric-insurance-framework). Every figure reads committed runs from the
result store (:class:`~parametric_insurance_design_viz.reader.ResultReader`)
and never re-runs an optimisation, draws inside the shared
:func:`~parametric_insurance_design_viz.style.style` and returns its data as
tidy tables (:class:`~parametric_insurance_design_viz.figure_data.FigureOutput`).

Figures
-------
:func:`sweep_figures` is the builder the ``figures`` command registers
(``command.FIGURE_SETS``). For each configured sweep it reads the sweep
points the command passes in (:class:`~.command.SweepRun`, computed from the
config's sweeps, MAR-65) and draws, in config order:

============================================  ================================
Figure                                        Thesis
============================================  ================================
``premium_reallocation``                      Figure 5.7
``payout_sweep_<scope>_<entity>_<param>``     Figure 5.8 (individual, A1); the
                                              notebook's cluster (C1) and
                                              portfolio (A1) cells
``sensitivity_<param>``                       Figures 5.9, 5.10, 5.12
``tradeoff_<scope>_<param>``                  Figures 5.11, A.3
``net_advantage_<scope>``                     Figure 5.13
``breakeven_cost_<scope>``                    Figure 5.14
============================================  ================================

* ``premium_reallocation``: each location's share of the total premium
  (expected payout, KPI ``expected_payout`` per entity) under the
  individual and the portfolio scope, both under the weighted-CVaR
  objective, over the insured values (from the prepared EventSet).
* ``payout_sweep_*`` (:data:`PAYOUT_SWEEP_PARAMETERS`): the first entity's
  step payout function at every value of the sweep, for the scope's
  weighted-CVaR run, coloured by value, over the baseline run's event data
  and the scope's residual-loss (``mse``) baseline. Below the attachment
  each run pays as its ``below_attachment`` mode says, drawn and tabulated
  as in the payout grid (MAR-192; ``payout_functions``, "Below the
  attachment"). If the entity belongs to a joint design problem (the
  portfolio scope, a joint cluster scope with more than one cluster;
  ``payout_functions``, "Joint designs"), the figure carries
  :data:`~.payout_functions.JOINT_CAPTION` above its title and a ``caption``
  table (MAR-222, design review F8): its payout functions are one of several
  optimal designs, chosen by the solver. A cluster scope calibrated cluster
  by cluster (``joint: false``) has one entity per problem, so no caption.
* ``sensitivity_<param>``: the portfolio tail basis risk (KPI
  ``cvar_uncovered`` at ``level = "portfolio"``, at the evaluation
  ``beta``) against the swept value, one line per scope x objective except
  :data:`SENSITIVITY_EXCLUDED` (the thesis cells). A scope x objective the
  parameter does not apply to is the flat line of its baseline run, as in
  the thesis. For ``n_assets`` each value is the mean over its location
  subsets (thesis ``_build_kpi_df_n_assets``).
* ``tradeoff_<scope>_<param>`` (:data:`TRADEOFF_PARAMETERS`): portfolio tail
  basis risk against total basis risk (``expected_uncovered``) for the
  portfolio scope's weighted-CVaR run, one marker per value.
* ``net_advantage_<scope>`` and ``breakeven_cost_<scope>`` (the
  ``n_clusters`` sweep of a cluster scope): with the tail-risk penalty
  ``Pi(C) = CVaR(cluster, C) - CVaR(portfolio)`` of clustering against the
  portfolio scope's weighted-CVaR baseline and ``K`` locations, the net
  advantage ``Delta(C; tau) = (K - C) tau - Pi(C)`` for each transaction
  cost ``tau`` per contract, and the break-even cost
  ``tau*(C) = Pi(C) / (K - C)`` for ``C < K``. The costs are a figure option,
  not part of the config (as in the thesis): ``FigureContext.transaction_costs``,
  the ``figures`` command's ``--transaction-costs`` (MAR-120), by default
  :data:`THESIS_TRANSACTION_COSTS`. They measure what the joint cluster
  calibration gains, so a cluster scope calibrated cluster by cluster
  (``joint: false``, ``style.SEPARATE_CLUSTER_SCOPE``) does not get them
  (:data:`SEPARATE_CLUSTER_REASON`, MAR-222).

The thesis notebook's figure arguments that are not in the config (the
weighted-CVaR objective as the focus, the excluded combinations, the default
transaction costs) are the module constants below.

The runs of a sweep are read in bulk, one store read per table for all its
points (:meth:`~parametric_insurance_design_viz.reader.ResultReader.runs`,
MAR-120).

Evaluation split
----------------
The figures that read KPIs (the premium reallocation, the sensitivity,
trade-off, net-advantage and break-even figures) read every KPI of one
figure on one split (:func:`figure_split`, MAR-229; since MAR-232 the KPI
figures' own function, :func:`~.kpi_figures.figure_split`, re-exported
here with :class:`MissingKpiError`): the first of
:data:`~.kpi_figures.SPLIT_PREFERENCE` that every complete run of the figure
has, as the KPI figures choose. A holdout run stores KPI rows on its train
years (``eval_split = "train"``, in sample) and its test years (``"test"``,
out of sample), so its figures show ``test``; a full-sample run has
``full`` rows only. On ``test`` or ``train`` the axes title states the split
(:func:`~.kpi_figures.split_note`, "Out of sample (test years)") and the
figure data gain the :data:`SPLIT_TABLE` table (``<name>.split.csv``). On
``full`` neither, so the thesis figures are unchanged byte for byte. The
payout-sweep figures read no KPI: they show designs, which have no
evaluation split. Before MAR-229 every KPI was read on ``full``, so the
``figures`` command failed on a holdout store with :class:`MissingKpiError`.

No silent failures
------------------
* A figure whose baseline run failed is not drawn: a
  :class:`~.command.SkippedFigure` with ``failed=True`` names the run.
* Sweep points whose run failed (e.g. an ``n_assets`` subset smaller than
  the cluster count) are not drawn. The figure is drawn from the others,
  its figure data lists every point with ``ok = False`` and no value for the
  failed ones, and a :class:`~.command.SkippedFigure` with ``failed=True``
  and the same name says how many points were left out, so the command
  exits 1 (the thesis dropped such points without a trace).
* A figure that does not apply (no individual scope for the premium
  reallocation, no weighted-CVaR objective, the net advantage and
  break-even cost of a cluster scope with ``joint: false``) is a
  ``SkippedFigure`` with ``failed=False``. Without sweeps there are no sweep figures.
* A figure that needs sweep points missing from the store
  (``FigureContext.missing_sweeps``, when the command skips missing points,
  MAR-120) is not drawn: a ``SkippedFigure`` with ``missing=True`` counts the
  missing points and names the first few. Figures whose points are all in
  the store are drawn as usual.
* A run that lacks a KPI row the figure needs raises
  :class:`MissingKpiError`.

Differences from the thesis code, all deliberate:

* Axis labels take their units from the EventSet metadata (e.g. "[USD]"
  instead of "[$]") and name the index generically ("Index").
* The premium shares come from the stored ``expected_payout`` KPI, which is
  the thesis' probability-weighted expected payout on the evaluation basis.
* The payout-sweep figures are one figure per parameter, as the notebook
  wrote them; the thesis PDF arranges four of them on one page.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib import colormaps
from matplotlib.axes import Axes
from matplotlib.cm import ScalarMappable
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
from numpy.typing import NDArray

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.payout import BelowAttachment
from parametric_insurance_design_viz import style
from parametric_insurance_design_viz.errors import (
    InconsistentRunsError,
)
from parametric_insurance_design_viz.figure_data import MAIN_TABLE, FigureOutput
from parametric_insurance_design_viz.kpi_figures import (
    MissingKpiError,
    figure_split,
    split_note,
)
from parametric_insurance_design_viz.payout_functions import (
    STEP_COLUMNS,
    AxisLabels,
    JointEntities,
    below_attachment_mode,
    bin_breakpoints,
    default_xlim,
    joint_caption,
    payout_steps,
    shared_attachment_limit,
    step_points,
    with_zero_rows,
    wrap_joint_caption,
)
from parametric_insurance_design_viz.reader import RunResult

if TYPE_CHECKING:
    from parametric_insurance_design_viz.command import (
        FigureContext,
        ScopeRuns,
        SkippedFigure,
        SweepRun,
    )

__all__ = [
    "BREAKEVEN_COLUMNS",
    "FOCUS_OBJECTIVE",
    "NET_ADVANTAGE_COLUMNS",
    "PAYOUT_SWEEP_PARAMETERS",
    "PENALTY_COLUMNS",
    "POINT_COLUMNS",
    "REALLOCATION_COLUMNS",
    "SENSITIVITY_COLUMNS",
    "SENSITIVITY_EXCLUDED",
    "SEPARATE_CLUSTER_REASON",
    "SPLIT_COLUMNS",
    "SPLIT_TABLE",
    "SWEEP_STEP_COLUMNS",
    "TAIL_KPI",
    "THESIS_TRANSACTION_COSTS",
    "TOTAL_KPI",
    "TRADEOFF_COLUMNS",
    "TRADEOFF_PARAMETERS",
    "MissingKpiError",
    "SweepSeries",
    "breakeven_cost",
    "cluster_penalty",
    "figure_split",
    "kpi_value",
    "net_advantage",
    "parameter_label",
    "parameter_symbol",
    "payout_sweep",
    "premium_reallocation",
    "sensitivity",
    "sweep_figures",
    "tradeoff",
]

FOCUS_OBJECTIVE: Final[str] = "weighted_cvar"
"""The thesis-focus objective of the sweep, reallocation and cluster figures."""

TAIL_KPI: Final[str] = "cvar_uncovered"
"""Tail basis risk: CVaR of the uncovered portfolio loss (thesis
``CVaR_Uncovered``)."""

TOTAL_KPI: Final[str] = "expected_uncovered"
"""Total basis risk: expected uncovered portfolio loss (``E_Uncovered``)."""

PREMIUM_KPI: Final[str] = "expected_payout"
"""Per-entity premium of the reallocation figure (pure pricing)."""

PAYOUT_SWEEP_PARAMETERS: Final[tuple[str, ...]] = (
    "alpha",
    "beta",
    "budget_loading",
    "n_bins",
    "noise_level",
)
"""Sweeps drawn as payout-function sweeps (thesis notebook cells 106-136)."""

TRADEOFF_PARAMETERS: Final[tuple[str, ...]] = (
    "alpha",
    "beta",
    "n_bins",
    "budget_loading",
)
"""Sweeps drawn in the tail-vs-total trade-off plane (thesis cells 154-160)."""

SENSITIVITY_EXCLUDED: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("individual", "mse"),
        ("individual", "expected_uncovered"),
        ("cluster", "mse"),
        ("cluster", "expected_uncovered"),
    }
)
"""(scope, objective) pairs left out of the sensitivity figures (thesis)."""

THESIS_TRANSACTION_COSTS: Final[tuple[float, ...]] = (
    25_000.0,
    50_000.0,
    75_000.0,
    100_000.0,
    125_000.0,
)
"""Transaction costs per contract of the net-advantage figure, loss units
(thesis ``sweeps.yaml`` ``transaction_costs``)."""

SEPARATE_CLUSTER_REASON: Final[str] = (
    "the cluster scope is calibrated cluster by cluster (joint: false): the "
    "net advantage and the break-even cost measure what the joint cluster "
    "calibration gains against the portfolio scope, so they do not apply"
)
"""Why the cluster figures of a ``joint: false`` cluster scope are skipped."""

_PARAMETER_SYMBOLS: Final[dict[str, str]] = {
    "alpha": r"$\alpha$",
    "beta": r"$\beta$",
    "budget_loading": r"$\kappa$",
    "n_bins": r"$n_b$",
    "n_clusters": r"$C$",
    "noise_level": r"$\eta$",
    "n_assets": r"$n_a$",
}

_PARAMETER_NAMES: Final[dict[str, str]] = {
    "alpha": "CVaR weight",
    "beta": "CVaR confidence level",
    "budget_loading": "Budget loading",
    "n_bins": "Number of bins",
    "n_clusters": "Number of clusters",
    "noise_level": "Noise level",
    "n_assets": "Number of assets",
}

SWEEP_STEP_COLUMNS: Final[tuple[str, ...]] = (
    "role",
    "parameter",
    "parameter_value",
    *STEP_COLUMNS,
)
"""Main table of :func:`payout_sweep`: the steps of every drawn run.

``role`` is ``"sweep"`` for a sweep point or ``"baseline"`` for the
residual-loss baseline (``parameter_value`` empty). A run that pays 0 below
the attachment (``below_attachment = "zero"``) has one more row before its
bins, as in the payout grid's figure data: ``param_index`` is
:data:`~parametric_insurance_design.payout.NO_BIN` (-1), ``lower`` is
``-inf``, ``upper`` is the attachment ``b_0`` and ``value`` is 0."""

POINT_COLUMNS: Final[tuple[str, ...]] = (
    "parameter",
    "parameter_value",
    "subset_index",
    "location_ids",
    "scope",
    "objective",
    "source",
    "run_id",
    "ok",
    "kpi",
    "beta",
    "kpi_value",
)
"""The ``points`` table of :func:`sensitivity`: one row per run read.

``source`` is ``"sweep"`` or ``"baseline"`` (the flat line of a scope x
objective the parameter does not apply to). ``location_ids`` joins an
``n_assets`` subset with ``";"``."""

SENSITIVITY_COLUMNS: Final[tuple[str, ...]] = (
    "parameter",
    "parameter_value",
    "scope",
    "objective",
    "source",
    "n_runs",
    "n_failed",
    "kpi",
    "beta",
    "kpi_value",
)
"""Main table of :func:`sensitivity`: one row per plotted point.

``kpi_value`` is the mean over the ``n_runs - n_failed`` successful runs of
the value (more than one only for ``n_assets``); empty if all failed."""

TRADEOFF_COLUMNS: Final[tuple[str, ...]] = (
    "parameter",
    "parameter_value",
    "scope",
    "objective",
    "run_id",
    "ok",
    "beta",
    TOTAL_KPI,
    TAIL_KPI,
)
"""Main table of :func:`tradeoff`: one row per sweep point."""

REALLOCATION_COLUMNS: Final[tuple[str, ...]] = (
    "entity_id",
    "location_value",
    "objective",
    "individual_run_id",
    "portfolio_run_id",
    "individual_premium",
    "portfolio_premium",
    "individual_share",
    "portfolio_share",
    "reallocation_pp",
)
"""Main table of :func:`premium_reallocation`, in plotted order."""

PENALTY_COLUMNS: Final[tuple[str, ...]] = (
    "n_clusters",
    "run_id",
    "ok",
    "portfolio_run_id",
    "n_locations",
    "beta",
    "cvar_cluster",
    "cvar_portfolio",
    "penalty",
)
"""The tail-risk penalty of clustering, one row per ``n_clusters`` point."""

NET_ADVANTAGE_COLUMNS: Final[tuple[str, ...]] = (
    "n_clusters",
    "transaction_cost",
    "penalty",
    "net_advantage",
    "optimal_n_clusters",
)
"""Main table of :func:`net_advantage`: one row per (cost, cluster count)."""

BREAKEVEN_COLUMNS: Final[tuple[str, ...]] = (
    *PENALTY_COLUMNS,
    "breakeven_cost",
)
"""Main table of :func:`breakeven_cost`: the penalty rows with ``C < K``."""

SPLIT_TABLE: Final[str] = "split"
"""Key of the table that states a figure's evaluation split (MAR-229).

Written as ``<name>.split.csv`` by the figures that read KPIs, when they
read the ``test`` or ``train`` rows of holdout runs; see the module
docstring, "Evaluation split"."""

SPLIT_COLUMNS: Final[tuple[str, ...]] = ("eval_split", "note")
"""Columns of the :data:`SPLIT_TABLE` table: one row, the split
(``kpis.eval_split``) and the note the figure shows
(:func:`~.kpi_figures.split_note`)."""

_FIGSIZE: Final[tuple[float, float]] = (6.0, 6.0)  # thesis sweep cells
_REALLOCATION_FIGSIZE: Final[tuple[float, float]] = (9.0, 7.0)
_CLUSTER_FIGSIZE: Final[tuple[float, float]] = (8.0, 8.0)
_SCATTER_ALPHA: Final[float] = 0.25
_SCATTER_SIZE: Final[float] = 8
_MARKER_COLOR: Final[str] = "#0b356d"  # thesis premium reallocation
_GAIN_COLOR: Final[str] = "#1b7837"
_LOSS_COLOR: Final[str] = "#cc0707"
_FLAT_COLOR: Final[str] = "#9e9e9e"
_VALUE_BAR_COLOR: Final[str] = "#d9d9d9"
_CLUSTER_REGIME: Final[str] = "#2ca02c"
_PORTFOLIO_REGIME: Final[str] = "#d62728"
_REGIME_ALPHA: Final[float] = 0.12
_MINUS: Final[str] = "\N{MINUS SIGN}"
_FLAT_PP: Final[float] = 0.5  # |change| below this many points reads "0"
_ANNOTATE_OFFSET: Final[float] = 7.0  # points, thesis _tick_dist
_CAPTION_GAP: Final[float] = 0.01  # figure fraction between title and caption


# --------------------------------------------------------------------------
# Labels
# --------------------------------------------------------------------------


def parameter_symbol(parameter: str) -> str:
    r"""Return the maths symbol of a sweep parameter (thesis ``_PARAM_SYMBOL``).

    Parameters
    ----------
    parameter : str
        A sweep parameter, e.g. ``"alpha"``.

    Returns
    -------
    str
        E.g. ``r"$\alpha$"``; the parameter name for an unknown one.
    """
    return _PARAMETER_SYMBOLS.get(parameter, parameter.replace("_", " "))


def parameter_label(parameter: str) -> str:
    """Return the panel title of a sweep parameter, e.g. "CVaR weight alpha".

    Parameters
    ----------
    parameter : str
        A sweep parameter.

    Returns
    -------
    str
        Its thesis name and symbol.
    """
    name = _PARAMETER_NAMES.get(parameter, parameter.replace("_", " ").capitalize())
    return f"{name} {parameter_symbol(parameter)}"


def _unit(labels: AxisLabels) -> str:
    return f" [{labels.payout_unit}]" if labels.payout_unit else ""


def _tail_label(labels: AxisLabels) -> str:
    return rf"Tail basis risk $CVaR_{{\beta}}(UL^P)${_unit(labels)}"


def _total_label(labels: AxisLabels) -> str:
    return rf"Total basis risk $E(UL^P)${_unit(labels)}"


def _value_text(value: float) -> str:
    """Format a sweep value as the thesis annotated it (two decimals)."""
    return f"{float(value):.2f}"


def _figure_legend(fig: Figure, handles: list, *, ncol: int, y: float = 0.0) -> None:
    """Legend centred below the figure, without a frame (thesis)."""
    if not handles:
        return
    fig.legend(
        handles,
        [str(h.get_label()) for h in handles],
        loc="upper center",
        bbox_to_anchor=(0.5, y),
        ncol=max(1, ncol),
        frameon=False,
        fontsize=style.FONT.legend_size,
    )


def _below(fig: Figure, ax: Axes, gap: float = 0.01) -> float:
    """Figure height just below an axes and its labels (for a legend under it)."""
    fig.draw_without_rendering()
    box = ax.get_tightbbox()
    if box is None:  # pragma: no cover - a drawn colour bar has a box
        return 0.0
    y0 = fig.transFigure.inverted().transform((0.0, box.y0))[1]
    return float(y0) - gap


def _frame(ax: Axes) -> None:
    """Black frame on all four sides and a square axes box (thesis)."""
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_linewidth(0.8)
        spine.set_color("black")
    ax.set_box_aspect(1)


def _scope_objective_legend(
    fig: Figure, pairs: Sequence[tuple[str, str]], *, y: float = 0.0
) -> None:
    """Two legend rows: scopes (grey, line style) and objectives (colour)."""
    scopes = list(dict.fromkeys(s for s, _ in pairs))
    objectives = list(dict.fromkeys(o for _, o in pairs))
    scope_handles = [
        Line2D(
            [0],
            [0],
            color="grey",
            linestyle=cast(Any, _scope_style(s).linestyle),
            marker=_scope_style(s).marker,
            markersize=5,
            linewidth=1.5,
            label=style.scope_label(s),
        )
        for s in scopes
    ]
    objective_handles = [
        Line2D(
            [0],
            [0],
            color=style.objective_color(o),
            linewidth=1.5,
            label=style.objective_label(o),
        )
        for o in objectives
    ]
    fig.legend(
        scope_handles + objective_handles,
        [str(h.get_label()) for h in scope_handles + objective_handles],
        loc="upper center",
        bbox_to_anchor=(0.5, y),
        ncol=max(len(scope_handles), len(objective_handles), 1),
        frameon=False,
        fontsize=style.FONT.legend_size,
    )


def _scope_style(scope: str) -> style.ScopeStyle:
    return style.SCOPE_STYLES.get(scope, style.ScopeStyle(linestyle="-", marker="o"))


def _baseline_scope_label(run: RunResult) -> str:
    """Lower-case scope label of a run, by its scope name (MAR-225)."""
    return style.scope_label(style.run_scope_name(run)).lower()


def _sweep_cmap(start: float, stop: float) -> LinearSegmentedColormap:
    """Viridis truncated to ``[start, stop]`` (thesis)."""
    base = colormaps["viridis"]
    return LinearSegmentedColormap.from_list(
        f"viridis_{start}_{stop}", base(np.linspace(start, stop, 256))
    )


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def _where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


def _evaluation_beta(run: RunResult) -> float:
    return float(run.parameters["evaluation_beta"])


def _split_table(split: str) -> pd.DataFrame | None:
    """Return the :data:`SPLIT_TABLE` table of a figure, or None on ``full``."""
    note = split_note(split)
    if note is None:
        return None
    return pd.DataFrame(
        [{"eval_split": split, "note": note}], columns=list(SPLIT_COLUMNS)
    )


def _split_heading(split: str) -> str | None:
    """Return the split note as an axes title, capitalised; None on ``full``."""
    note = split_note(split)
    return None if note is None else note[0].upper() + note[1:]


def _split_title(split: str, title: str) -> str:
    """Return ``title`` with the split note on a second line (MAR-229).

    ``title`` alone on ``full``.
    """
    heading = _split_heading(split)
    return title if heading is None else f"{title}\n{heading}"


def _with_split(data: dict[str, pd.DataFrame], split: str) -> dict[str, pd.DataFrame]:
    """Add the :data:`SPLIT_TABLE` table to a figure's data, unless ``full``."""
    table = _split_table(split)
    if table is not None:
        data[SPLIT_TABLE] = table
    return data


def kpi_value(
    run: RunResult,
    kpi: str,
    *,
    level: str = "portfolio",
    subject_id: str | None = None,
    eval_split: str | None = None,
) -> float:
    """Return one KPI value of a complete run from its ``kpis`` table.

    VaR and CVaR KPIs are read at the run's evaluation ``beta``
    (``runs.parameters.evaluation_beta``), on the run's basis and fold 0.

    Parameters
    ----------
    run : RunResult
        A complete run.
    kpi : str
        KPI name, e.g. ``"cvar_uncovered"``.
    level : str, default "portfolio"
        ``kpis.level``.
    subject_id : str, optional
        ``kpis.subject_id``; needed below the portfolio level.
    eval_split : str, optional
        ``kpis.eval_split``. Default: the run's preferred split
        (:func:`figure_split` of the run): ``test`` for a holdout run,
        ``full`` for a full-sample run (MAR-229; before, always ``full``).

    Returns
    -------
    float
        The value (NaN if the store records it as undefined).

    Raises
    ------
    IncompleteRunError
        If the run has a failed design problem.
    MissingKpiError
        If there is no such row, or more than one.
    """
    run.require_complete()
    if eval_split is None:
        eval_split = figure_split([run])
    kpis = run.kpis
    basis = set(run.runs["basis"])
    mask = (
        (kpis["kpi"] == kpi)
        & (kpis["level"] == level)
        & (kpis["eval_split"] == eval_split)
        & (kpis["fold"] == 0)
        & kpis["basis"].isin(sorted(basis))
    )
    if subject_id is not None:
        mask &= kpis["subject_id"] == subject_id
    rows = _where(kpis, mask)
    if bool(rows["beta"].notna().any()):
        beta = _evaluation_beta(run)
        rows = _where(rows, np.isclose(rows["beta"].to_numpy(float), beta))
    if len(rows) != 1:
        where = f"level {level!r}" + (f", subject {subject_id!r}" if subject_id else "")
        raise MissingKpiError(
            f"run {run.run_id} ({run.scope} x {run.objective}) has {len(rows)} "
            f"{kpi!r} rows at {where}, split {eval_split!r}; expected one"
        )
    value = rows["value"].iloc[0]
    return float("nan") if pd.isna(value) else float(value)


@dataclass(frozen=True, eq=False)
class SweepSeries:
    """One scope x objective of a sweep: its points and its baseline run.

    Parameters
    ----------
    parameter : str
        The swept parameter.
    scope : str
        The scope's figure-name stem (``ScopeRuns.key``).
    baseline : RunResult
        The scope x objective's single run (the config's defaults).
    points : tuple of (SweepRun, RunResult)
        The sweep points of this scope x objective with their runs, in sweep
        order; empty if the parameter does not apply to it.
    missing : tuple of SweepRun, default ()
        Its sweep points that are not in the store (MAR-120), in sweep order;
        not in ``points``.
    """

    parameter: str
    scope: str
    baseline: RunResult
    points: tuple[tuple[SweepRun, RunResult], ...] = ()
    missing: tuple[SweepRun, ...] = ()

    @property
    def swept(self) -> bool:
        """Whether the parameter applies: the series has sweep points."""
        return bool(self.points or self.missing)

    @property
    def scope_kind(self) -> str:
        """The scope kind (``runs.scope``), e.g. ``"cluster"``.

        ``"cluster"`` for both cluster settings; :attr:`scope_name` tells
        them apart.
        """
        return self.baseline.scope

    @property
    def scope_name(self) -> str:
        """The scope name that labels and styles the series (MAR-225).

        ``style.run_scope_name`` of the baseline run: :attr:`scope_kind`, or
        ``"cluster_separate"`` for a cluster scope calibrated cluster by
        cluster (``joint: false``).
        """
        return style.run_scope_name(self.baseline)

    @property
    def objective(self) -> str:
        """The objective (``runs.objective``)."""
        return self.baseline.objective

    @property
    def failed(self) -> tuple[tuple[SweepRun, RunResult], ...]:
        """Points whose run has a failed design problem."""
        return tuple((p, r) for p, r in self.points if not r.complete)

    def sorted_points(self) -> list[tuple[SweepRun, RunResult]]:
        """Points by value (stable, so subsets keep their order)."""
        return sorted(self.points, key=lambda pr: float(pr[0].value))


def _subset_text(point: SweepRun) -> str | None:
    if point.location_ids is None:
        return None
    return ";".join(point.location_ids)


# --------------------------------------------------------------------------
# Premium reallocation (thesis Figure 5.7)
# --------------------------------------------------------------------------


def premium_reallocation(
    individual: RunResult,
    portfolio: RunResult,
    *,
    location_values: Mapping[str, float] | None = None,
    labels: AxisLabels | None = None,
    figsize: tuple[float, float] = _REALLOCATION_FIGSIZE,
    name: str = "premium_reallocation",
    eval_split: str | None = None,
) -> FigureOutput:
    """Draw each location's premium share under the individual and portfolio scope.

    Thesis ``plot_premium_reallocation``: the premium of an entity is its
    expected payout (KPI ``expected_payout``); its share is that over the
    sum across entities. Locations are sorted by insured value (largest
    first), drawn as grey bars on a second axis, with the change in
    percentage points annotated (green gain, red loss, grey within 0.5 pp).

    Parameters
    ----------
    individual, portfolio : RunResult
        Complete runs of the individual and the portfolio scope under one
        objective; both must cover the same single-location entities.
    location_values : mapping of str to float, optional
        Insured value per location (EventSet ``locations.value``). Without
        it the entities keep the run's order and no bars are drawn.
    labels : AxisLabels, optional
        Units.
    figsize : (float, float), default (9, 7)
        Figure size in inches.
    name : str, default "premium_reallocation"
        Figure name.
    eval_split : str, optional
        Evaluation split of the premiums; default :func:`figure_split` of
        the two runs (MAR-229).

    Returns
    -------
    FigureOutput
        Main table :data:`REALLOCATION_COLUMNS`; on a ``test`` or ``train``
        split also :data:`SPLIT_TABLE`, and the axes title states the split.

    Raises
    ------
    IncompleteRunError
        If a run failed.
    InconsistentRunsError
        If the runs differ in objective or entities, or the totals are not
        positive.
    MissingKpiError
        If an entity lacks its ``expected_payout`` row, or the runs share
        no split.
    """
    labels = labels or AxisLabels()
    for run in (individual, portfolio):
        run.require_complete()
    split = figure_split((individual, portfolio), eval_split)
    if individual.objective != portfolio.objective:
        raise InconsistentRunsError(
            f"premium reallocation compares one objective, got "
            f"{individual.objective!r} and {portfolio.objective!r}"
        )
    entities = individual.entity_order()
    if sorted(entities) != sorted(portfolio.entity_order()):
        raise InconsistentRunsError(
            f"runs {individual.run_id} and {portfolio.run_id} cover different "
            f"entities: {entities} and {portfolio.entity_order()}"
        )
    if location_values is not None:
        missing = [e for e in entities if e not in location_values]
        if missing:
            raise InconsistentRunsError(
                f"no insured value for {missing} in the EventSet locations"
            )
        entities = tuple(
            sorted(entities, key=lambda e: -float(location_values[e]))  # stable
        )
    ind = np.array(
        [
            kpi_value(
                individual,
                PREMIUM_KPI,
                level="entity",
                subject_id=e,
                eval_split=split,
            )
            for e in entities
        ]
    )
    pf = np.array(
        [
            kpi_value(
                portfolio, PREMIUM_KPI, level="entity", subject_id=e, eval_split=split
            )
            for e in entities
        ]
    )
    if not (np.nansum(ind) > 0 and np.nansum(pf) > 0):
        raise InconsistentRunsError(
            "premium reallocation needs a positive total premium in both runs"
        )
    ind_share = ind / np.nansum(ind)
    pf_share = pf / np.nansum(pf)
    delta = (pf_share - ind_share) * 100.0
    values = (
        np.array([float(location_values[e]) for e in entities])
        if location_values is not None
        else np.full(len(entities), np.nan)
    )
    table = pd.DataFrame(
        {
            "entity_id": list(entities),
            "location_value": values,
            "objective": individual.objective,
            "individual_run_id": individual.run_id,
            "portfolio_run_id": portfolio.run_id,
            "individual_premium": ind,
            "portfolio_premium": pf,
            "individual_share": ind_share,
            "portfolio_share": pf_share,
            "reallocation_pp": delta,
        },
        columns=list(REALLOCATION_COLUMNS),
    )
    marker_ind = _scope_style(individual.scope).marker
    marker_pf = _scope_style(portfolio.scope).marker
    x = np.arange(len(entities))

    with style.style():
        fig, ax1 = plt.subplots(figsize=figsize)
        handles: list = [
            Line2D(
                [0],
                [0],
                marker=m,
                linestyle="none",
                markerfacecolor=_MARKER_COLOR,
                markeredgecolor=_MARKER_COLOR,
                markersize=9,
                label=f"{style.scope_label(r.scope)} & "
                f"{style.objective_label(r.objective).lower()}",
            )
            for r, m in ((individual, marker_ind), (portfolio, marker_pf))
        ]
        ax2 = None
        if location_values is not None:
            ax2 = ax1.twinx()
            scale = 1e6
            bars = values / scale
            ax2.bar(x, bars, color=_VALUE_BAR_COLOR, edgecolor="none", width=0.7)
            ax2.set_ylabel(f"Insured value [{_scaled_unit(labels, 'M')}]")
            ax2.set_ylim(0, float(np.nanmax(bars)) * 1.25 if len(bars) else 1.0)
            ax1.set_zorder(ax2.get_zorder() + 1)
            ax1.patch.set_visible(False)
            handles.append(
                Patch(
                    facecolor=_VALUE_BAR_COLOR, edgecolor="none", label="Insured value"
                )
            )
        for xi, si, sp, d in zip(x, ind_share, pf_share, delta, strict=True):
            flat = abs(d) < _FLAT_PP
            color = _FLAT_COLOR if flat else _GAIN_COLOR if d > 0 else _LOSS_COLOR
            ax1.plot([xi, xi], [si, sp], color=color, linewidth=1.5, zorder=1)
            for share, marker in ((si, marker_ind), (sp, marker_pf)):
                ax1.scatter(
                    xi, share, marker=marker, s=70, color=_MARKER_COLOR, zorder=2
                )
            text = "0" if flat else f"{'+' if d > 0 else _MINUS}{abs(d):.0f}pp"
            ax1.annotate(
                text,
                (xi, max(si, sp)),
                xytext=(0, 8),
                textcoords="offset points",
                va="bottom",
                ha="center",
                fontsize=style.FONT.tick_size,
                color="#555555" if flat else color,
            )
        ax1.set_xticks(x)
        ax1.set_xticklabels(list(entities))
        ax1.set_xlim(-0.6, len(entities) - 0.4)
        ax1.set_xlabel(
            "Assets (sorted by value)" if location_values is not None else "Assets"
        )
        ax1.set_ylabel("Share of total portfolio premium budget")
        ax1.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v * 100:.0f}%"))
        top = float(np.nanmax(np.concatenate([ind_share, pf_share])))
        ax1.set_ylim(0, top * 1.18)
        title = _split_heading(split)
        if title is not None:
            ax1.set_title(title, fontsize=style.FONT.label_size)
        _frame(ax1)
        if ax2 is not None:
            _frame(ax2)
        fig.tight_layout()
        _figure_legend(fig, handles, ncol=2)
    return FigureOutput(
        name=name, figure=fig, data=_with_split({MAIN_TABLE: table}, split)
    )


def _scaled_unit(labels: AxisLabels, prefix: str) -> str:
    return f"{prefix} {labels.payout_unit}" if labels.payout_unit else prefix


# --------------------------------------------------------------------------
# Payout-function sweep (thesis Figure 5.8)
# --------------------------------------------------------------------------


def _sweep_step_xy(
    bins: pd.DataFrame, xlim: tuple[float, float], mode: BelowAttachment
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Step points of one run's bins over the whole axis.

    The payout grid's step points (:func:`~.payout_functions.step_points`):
    above the limit the last level; below the attachment the first level
    under ``"first_bin"`` and 0 under ``"zero"``, with a step at ``b_0``.
    """
    levels = bins["value"].to_numpy(dtype=np.float64)
    return step_points(bin_breakpoints(bins), levels, xlim, mode)


def _sweep_caption(
    series: SweepSeries,
    runs: Sequence[RunResult],
    entity_id: str,
    joint_entities: JointEntities,
) -> pd.DataFrame | None:
    """Return the ``caption`` table of a payout sweep, or None.

    Decided for every drawn sweep point
    (:func:`~.payout_functions.joint_caption`), since a sweep point may in
    principle change the design problems: one row
    (:data:`~.payout_functions.CAPTION_COLUMNS`) per distinct joint problem
    of the entity among the points; None if the entity belongs to a joint
    problem at no point.

    Raises
    ------
    FigureDataError
        If ``joint_entities`` is not a mode.
    JointEntitiesError
        Under ``"refuse"``, if the entity belongs to a joint problem at a
        point.
    """
    figure = f"payout_sweep of the {series.parameter} sweep of {series.scope}"
    tables = [
        table
        for run in runs
        if (table := joint_caption(run, (entity_id,), joint_entities, figure=figure))
        is not None
    ]
    if not tables:
        return None
    return pd.concat(tables, ignore_index=True).drop_duplicates(ignore_index=True)


def _draw_sweep_caption(fig: Figure, ax: Axes) -> None:
    """Draw :data:`~.payout_functions.JOINT_CAPTION` above the axes title.

    The payout grid's wrapped caption
    (:func:`~.payout_functions.wrap_joint_caption`) in its style. Call after
    the layout is final; the PNG is saved with a tight bounding box, which
    takes the caption in.
    """
    fig.draw_without_rendering()
    box = ax.get_tightbbox()
    top = 1.0 if box is None else fig.transFigure.inverted().transform((0.0, box.y1))[1]
    fig.text(
        0.5,
        float(top) + _CAPTION_GAP,
        wrap_joint_caption(fig),
        ha="center",
        va="bottom",
        fontsize=style.FONT.subtitle_size,
        fontstyle="italic",
    )


def payout_sweep(
    series: SweepSeries,
    entity_id: str,
    *,
    benchmark: RunResult | None = None,
    events: pd.DataFrame | None = None,
    labels: AxisLabels | None = None,
    figsize: tuple[float, float] = _FIGSIZE,
    name: str | None = None,
    joint_entities: JointEntities = "caption",
) -> FigureOutput:
    """Draw one entity's payout function at every value of a sweep.

    Thesis ``plot_parameter_sweep`` (view ``"vanilla"``): the step payout
    function of each sweep point, coloured by the swept value (a truncated
    viridis colour bar), over the entity's event data and the residual-loss
    baseline (red, dashed).

    Below the attachment ``b_0`` each run is drawn as its step payout pays
    there (:func:`~.payout_functions.below_attachment_mode`, MAR-192), as in
    :func:`~.payout_functions.payout_grid`: the first bin's level under
    ``"first_bin"`` (the default and the thesis), 0 under ``"zero"``, with a
    step up to the first level at ``b_0``.

    If the entity belongs to a joint design problem (more than one entity:
    the portfolio scope, a joint cluster scope with more than one cluster;
    :func:`~.payout_functions.is_joint_design`), its payout functions are
    one of several optimal designs, chosen by the solver (design review F8,
    MAR-222). As in :func:`~.payout_functions.payout_grid`, the figure then
    carries :data:`~.payout_functions.JOINT_CAPTION` above its title, or is
    refused. Figures of other entities are unchanged.

    Parameters
    ----------
    series : SweepSeries
        The sweep of one scope x objective; failed points are not drawn.
    entity_id : str
        The entity, e.g. ``"A1"`` or ``"C1"``.
    benchmark : RunResult, optional
        The scope's baseline run of the benchmark objective (``mse``).
    events : pandas.DataFrame, optional
        :func:`~parametric_insurance_design_viz.reader.entity_events` of the
        baseline runs; the entity's rows are scattered.
    labels : AxisLabels, optional
        Units.
    figsize : (float, float), default (6, 6)
        Figure size in inches.
    name : str, optional
        Default ``"payout_sweep_<scope>_<entity>_<parameter>"`` (lowercase).
    joint_entities : {"caption", "refuse"}, default "caption"
        If the entity belongs to a joint design problem at any drawn sweep
        point: draw it under :data:`~.payout_functions.JOINT_CAPTION`, or
        refuse it (``payout_functions``, "Joint designs").

    Returns
    -------
    FigureOutput
        Main table :data:`SWEEP_STEP_COLUMNS` (for a ``"zero"`` run also its
        zero row below the attachment); ``events`` with the scatter when
        ``events`` is given; for an entity of a joint design the ``caption``
        table (:data:`~.payout_functions.CAPTION_COLUMNS`, one row per
        distinct joint problem among the drawn points; one row when the
        sweep leaves the problems unchanged).

    Raises
    ------
    InconsistentRunsError
        If no point succeeded, the entity is missing from a drawn run, or the
        runs differ in attachment and limit; or a drawn run's parameters and
        config disagree on what it pays below the attachment, e.g. a
        ``"zero"`` run written before MAR-178
        (:func:`~.payout_functions.below_attachment_mode`).
    FigureDataError
        If a drawn run records an unknown ``below_attachment`` mode, or
        ``joint_entities`` is not a mode.
    JointEntitiesError
        Under ``joint_entities="refuse"``, if the entity belongs to a joint
        design problem.
    """
    labels = labels or AxisLabels()
    ok = [(p, r) for p, r in series.sorted_points() if r.complete]
    if not ok:
        raise InconsistentRunsError(
            f"the {series.parameter} sweep of {series.scope} x {series.objective} "
            "has no successful point to draw"
        )
    runs = [r for _, r in ok]
    caption = _sweep_caption(series, runs, entity_id, joint_entities)
    drawn = runs + ([benchmark] if benchmark is not None else [])
    attachment, limit = shared_attachment_limit(drawn)
    modes: dict[str, BelowAttachment] = {
        run.run_id: below_attachment_mode(run) for run in drawn
    }
    xlim = default_xlim(attachment, limit)
    steps = payout_steps(drawn)
    steps = _where(steps, steps["entity_id"] == entity_id).reset_index(drop=True)
    lacking = sorted({r.run_id for r in drawn} - set(steps["run_id"]))
    if lacking:
        raise InconsistentRunsError(f"entity {entity_id!r} is not in runs {lacking}")
    value_of = {r.run_id: p.value for p, r in ok}
    table = with_zero_rows(steps, modes)
    table = table.assign(
        role=[
            "baseline" if benchmark is not None and rid == benchmark.run_id else "sweep"
            for rid in table["run_id"]
        ],
        parameter=series.parameter,
        parameter_value=[value_of.get(rid) for rid in table["run_id"]],
    ).loc[:, list(SWEEP_STEP_COLUMNS)]
    values = np.array([float(p.value) for p, _ in ok])
    aggregate = len(set(steps["location_ids"].iloc[0].split(";"))) > 1
    symbol = parameter_symbol(series.parameter)
    rows = None
    if events is not None:
        rows = _where(events, events["entity_id"] == entity_id).reset_index(drop=True)

    with style.style():
        fig, ax = plt.subplots(figsize=figsize)
        if rows is not None and len(rows):
            ax.scatter(
                rows["index"],
                rows["loss"],
                alpha=_SCATTER_ALPHA,
                color=style.EVENT_COLOR,
                s=_SCATTER_SIZE,
                label="Underlying event data",
                rasterized=True,
            )
        if benchmark is not None:
            bins = _where(steps, steps["run_id"] == benchmark.run_id)
            x, y = _sweep_step_xy(bins, xlim, modes[benchmark.run_id])
            ax.step(
                x,
                y,
                where="post",
                color="red",
                linestyle="--",
                linewidth=1.5,
                label=f"Baseline ({_baseline_scope_label(benchmark)} & "
                f"{style.objective_label(benchmark.objective).lower()})",
            )
        cmap = _sweep_cmap(0.0, 0.9)
        colorbar = len(np.unique(values)) > 1
        norm = Normalize(vmin=float(values.min()), vmax=float(values.max()))
        for (point, run), value in zip(ok, values, strict=True):
            bins = _where(steps, steps["run_id"] == run.run_id)
            x, y = _sweep_step_xy(bins, xlim, modes[run.run_id])
            ax.step(
                x,
                y,
                where="post",
                color=cmap(norm(value) if colorbar else 0.0),
                linewidth=1.5,
                label=None if colorbar else f"{symbol} = {point.value}",
            )
        for x0, text in ((attachment, r"Attachment $x_-$"), (limit, r"Limit $x^-$")):
            ax.axvline(x=x0, color="grey", linestyle="--", linewidth=1)
            ax.text(
                x0,
                0.05,
                text,
                transform=ax.get_xaxis_transform(),
                rotation=90,
                va="bottom",
                ha="right",
                fontsize=style.FONT.tick_size - 1,
            )
        ax.set_xlim(*xlim)
        ax.set_xlabel(labels.index(aggregate=aggregate))
        ax.set_ylabel(labels.payout())
        ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
        ax.set_title(parameter_label(series.parameter), fontsize=style.FONT.label_size)
        if colorbar:
            bar = fig.colorbar(
                ScalarMappable(norm=norm, cmap=cmap),
                ax=ax,
                orientation="horizontal",
                location="bottom",
                pad=0.14,
                shrink=0.5,
                aspect=25,
            )
            bar.set_label(symbol)
            unique = sorted(set(values.tolist()))
            if len(unique) <= 8:
                bar.set_ticks(unique)
            below = _below(fig, bar.ax)
        else:
            fig.tight_layout()
            below = 0.0
        handles, _ = ax.get_legend_handles_labels()
        _figure_legend(fig, handles, ncol=2, y=below)
        if caption is not None:
            _draw_sweep_caption(fig, ax)

    data = {MAIN_TABLE: table}
    if rows is not None:
        data["events"] = rows
    if caption is not None:
        data["caption"] = caption
    entity = entity_id.lower()
    default = f"payout_sweep_{series.scope}_{entity}_{series.parameter}"
    return FigureOutput(name=name or default.lower(), figure=fig, data=data)


# --------------------------------------------------------------------------
# Sensitivity of the tail basis risk (thesis Figures 5.9, 5.10, 5.12)
# --------------------------------------------------------------------------


def _point_rows(series: SweepSeries, kpi: str, split: str) -> list[dict[str, object]]:
    """``points`` rows of one series: every sweep run, or its baseline."""
    rows: list[dict[str, object]] = []
    base = {
        "parameter": series.parameter,
        "scope": series.scope,
        "objective": series.objective,
        "kpi": kpi,
    }
    if not series.points:
        run = series.baseline
        rows.append(
            {
                **base,
                "parameter_value": None,
                "subset_index": None,
                "location_ids": None,
                "source": "baseline",
                "run_id": run.run_id,
                "ok": run.complete,
                "beta": _evaluation_beta(run) if kpi == TAIL_KPI else None,
                "kpi_value": (
                    kpi_value(run, kpi, eval_split=split) if run.complete else None
                ),
            }
        )
        return rows
    for point, run in series.sorted_points():
        rows.append(
            {
                **base,
                "parameter_value": point.value,
                "subset_index": point.subset_index,
                "location_ids": _subset_text(point),
                "source": "sweep",
                "run_id": run.run_id,
                "ok": run.complete,
                "beta": _evaluation_beta(run) if kpi == TAIL_KPI else None,
                "kpi_value": (
                    kpi_value(run, kpi, eval_split=split) if run.complete else None
                ),
            }
        )
    return rows


def sensitivity(
    parameter: str,
    series: Sequence[SweepSeries],
    *,
    values: Sequence[float] | None = None,
    kpi: str = TAIL_KPI,
    labels: AxisLabels | None = None,
    figsize: tuple[float, float] = _FIGSIZE,
    name: str | None = None,
    eval_split: str | None = None,
) -> FigureOutput:
    """Draw a portfolio KPI against the swept value, per scope x objective.

    Thesis ``plot_sensitivity_analysis``. A series without points (the
    parameter does not apply to it) is drawn flat at its baseline value
    over ``values``. Several points of one value (``n_assets`` subsets)
    are averaged; failed points are left out of the mean and counted.

    Parameters
    ----------
    parameter : str
        The swept parameter.
    series : sequence of SweepSeries
        The lines, in legend order. Their baselines must be complete.
    values : sequence of float, optional
        The sweep's values, for the flat lines. Default: every value of the
        series' points.
    kpi : str, default "cvar_uncovered"
        Portfolio-level KPI on the vertical axis.
    labels : AxisLabels, optional
        Units.
    figsize : (float, float), default (6, 6)
        Figure size in inches.
    name : str, optional
        Default ``"sensitivity_<parameter>"``.
    eval_split : str, optional
        Evaluation split of the KPI; default :func:`figure_split` of the
        runs read (MAR-229).

    Returns
    -------
    FigureOutput
        Main table :data:`SENSITIVITY_COLUMNS`; ``points``
        (:data:`POINT_COLUMNS`), one row per run read; on a ``test`` or
        ``train`` split also :data:`SPLIT_TABLE`, and the axes title states
        the split.

    Raises
    ------
    IncompleteRunError
        If a flat line's baseline run failed.
    InconsistentRunsError
        If there are no series, or a series is of another parameter.
    MissingKpiError
        If a run lacks the KPI, or the runs share no split.
    """
    labels = labels or AxisLabels()
    if not series:
        raise InconsistentRunsError(f"the {parameter} sensitivity has no lines")
    other = sorted({s.parameter for s in series} - {parameter})
    if other:
        raise InconsistentRunsError(
            f"the {parameter} sensitivity got series of {other}"
        )
    for s in series:
        if not s.points:
            s.baseline.require_complete()
    if values is None:
        values = sorted({float(p.value) for s in series for p, _ in s.points})
    read = [s.baseline for s in series if not s.points]
    read += [r for s in series for _, r in s.points]
    split = figure_split(read, eval_split)
    point_rows = [row for s in series for row in _point_rows(s, kpi, split)]
    points = pd.DataFrame(point_rows, columns=list(POINT_COLUMNS))
    lines: list[dict[str, object]] = []
    for s in series:
        mine = _where(
            points, (points["scope"] == s.scope) & (points["objective"] == s.objective)
        )
        beta = _evaluation_beta(s.baseline) if kpi == TAIL_KPI else None
        if not s.points:
            flat = float(cast(float, mine["kpi_value"].iloc[0]))
            lines.extend(
                {
                    "parameter": parameter,
                    "parameter_value": v,
                    "scope": s.scope,
                    "objective": s.objective,
                    "source": "baseline",
                    "n_runs": 1,
                    "n_failed": 0,
                    "kpi": kpi,
                    "beta": beta,
                    "kpi_value": flat,
                }
                for v in values
            )
            continue
        for value, group in mine.groupby("parameter_value", sort=True):
            good = _where(group, group["ok"].astype(bool))["kpi_value"].to_numpy(
                dtype=float
            )
            lines.append(
                {
                    "parameter": parameter,
                    "parameter_value": value,
                    "scope": s.scope,
                    "objective": s.objective,
                    "source": "sweep",
                    "n_runs": len(group),
                    "n_failed": int(len(group) - len(good)),
                    "kpi": kpi,
                    "beta": beta,
                    "kpi_value": float(np.mean(good)) if len(good) else None,
                }
            )
    table = pd.DataFrame(lines, columns=list(SENSITIVITY_COLUMNS))

    with style.style():
        fig, ax = plt.subplots(figsize=figsize)
        for s in series:
            line = _where(
                table, (table["scope"] == s.scope) & (table["objective"] == s.objective)
            )
            line = line.dropna(subset=["kpi_value"])
            scope_style = _scope_style(s.scope_name)
            ax.plot(
                line["parameter_value"].astype(float),
                line["kpi_value"].astype(float),
                color=style.objective_color(s.objective),
                linestyle=scope_style.linestyle,
                marker=scope_style.marker,
                linewidth=1.5,
                markersize=5,
            )
        ax.set_xlabel(parameter_symbol(parameter))
        ax.set_ylabel(
            _tail_label(labels)
            if kpi == TAIL_KPI
            else f"{kpi.replace('_', ' ').capitalize()}{_unit(labels)}"
        )
        ax.ticklabel_format(axis="y", style="sci", scilimits=(0, 0))
        ax.set_title(
            _split_title(split, parameter_label(parameter)),
            fontsize=style.FONT.label_size,
        )
        _frame(ax)
        fig.tight_layout()
        _scope_objective_legend(fig, [(s.scope_name, s.objective) for s in series])
    return FigureOutput(
        name=name or f"sensitivity_{parameter}",
        figure=fig,
        data=_with_split({MAIN_TABLE: table, "points": points}, split),
    )


# --------------------------------------------------------------------------
# Tail vs. total basis risk (thesis Figures 5.11, A.3)
# --------------------------------------------------------------------------


def tradeoff(
    series: SweepSeries,
    *,
    labels: AxisLabels | None = None,
    annotate_every: int = 2,
    figsize: tuple[float, float] = _FIGSIZE,
    name: str | None = None,
    eval_split: str | None = None,
) -> FigureOutput:
    """Draw tail against total basis risk along one sweep.

    Thesis ``plot_tail_risk_vs_accuracy``: one marker per sweep value at
    (total basis risk, tail basis risk) of the portfolio, joined in value
    order; every ``annotate_every``-th value is written next to its marker,
    alternating sides of the curve.

    Parameters
    ----------
    series : SweepSeries
        One scope x objective's sweep; failed points are not drawn.
    labels : AxisLabels, optional
        Units.
    annotate_every : int, default 2
        Annotate every n-th point (thesis: every second); 0 for none.
    figsize : (float, float), default (6, 6)
        Figure size in inches.
    name : str, optional
        Default ``"tradeoff_<scope>_<parameter>"``.
    eval_split : str, optional
        Evaluation split of the KPIs; default :func:`figure_split` of the
        sweep runs (MAR-229).

    Returns
    -------
    FigureOutput
        Main table :data:`TRADEOFF_COLUMNS`; on a ``test`` or ``train`` split
        also :data:`SPLIT_TABLE`, and the axes title states the split.

    Raises
    ------
    InconsistentRunsError
        If no point succeeded.
    MissingKpiError
        If a run lacks a KPI, or the runs share no split.
    """
    labels = labels or AxisLabels()
    split = figure_split([r for _, r in series.points], eval_split)
    rows = [
        {
            "parameter": series.parameter,
            "parameter_value": point.value,
            "scope": series.scope,
            "objective": series.objective,
            "run_id": run.run_id,
            "ok": run.complete,
            "beta": _evaluation_beta(run),
            TOTAL_KPI: (
                kpi_value(run, TOTAL_KPI, eval_split=split) if run.complete else None
            ),
            TAIL_KPI: (
                kpi_value(run, TAIL_KPI, eval_split=split) if run.complete else None
            ),
        }
        for point, run in series.sorted_points()
    ]
    table = pd.DataFrame(rows, columns=list(TRADEOFF_COLUMNS))
    drawn = _where(table, table["ok"].astype(bool)).reset_index(drop=True)
    if drawn.empty:
        raise InconsistentRunsError(
            f"the {series.parameter} sweep of {series.scope} x {series.objective} "
            "has no successful point to draw"
        )
    scope_style = _scope_style(series.scope_name)
    color = style.objective_color(series.objective)

    with style.style():
        fig, ax = plt.subplots(figsize=figsize)
        xs = drawn[TOTAL_KPI].to_numpy(dtype=float)
        ys = drawn[TAIL_KPI].to_numpy(dtype=float)
        ax.plot(
            xs,
            ys,
            color=color,
            linestyle=scope_style.linestyle,
            marker=scope_style.marker,
            markersize=7,
            linewidth=1.5,
            zorder=2,
        )
        ax.set_xlabel(_total_label(labels))
        ax.set_ylabel(_tail_label(labels))
        ax.ticklabel_format(axis="both", style="sci", scilimits=(0, 0))
        ax.set_title(
            _split_title(split, parameter_label(series.parameter)),
            fontsize=style.FONT.label_size,
        )
        _frame(ax)
        fig.tight_layout()
        if annotate_every > 0:
            _annotate_curve(
                ax, xs, ys, drawn["parameter_value"].tolist(), annotate_every
            )
        _scope_objective_legend(fig, [(series.scope_name, series.objective)])
    return FigureOutput(
        name=name or f"tradeoff_{series.scope}_{series.parameter}",
        figure=fig,
        data=_with_split({MAIN_TABLE: table}, split),
    )


def _annotate_curve(
    ax: Axes,
    xs: NDArray[np.float64],
    ys: NDArray[np.float64],
    values: Sequence[object],
    every: int,
) -> None:
    """Write values next to the curve, perpendicular to it (thesis)."""
    display = ax.transData.transform(np.column_stack([xs, ys]))
    n = len(display)
    for i, value in enumerate(values):
        if i % every:
            continue
        prev_i, next_i = max(i - 1, 0), min(i + 1, n - 1)
        tx, ty = display[next_i] - display[prev_i]
        norm = float(np.hypot(tx, ty))
        px, py = (0.0, 1.0) if norm == 0.0 else (-ty / norm, tx / norm)
        sign = 1.0 if (i // every) % 2 == 0 else -1.0
        ox, oy = sign * _ANNOTATE_OFFSET * px, sign * _ANNOTATE_OFFSET * py
        ax.annotate(
            _value_text(float(cast(float, value))),
            xy=(xs[i], ys[i]),
            xytext=(ox, oy),
            textcoords="offset points",
            fontsize=style.FONT.tick_size - 1,
            ha="left" if ox > 0.5 else "right" if ox < -0.5 else "center",
            va="bottom" if oy > 0.5 else "top" if oy < -0.5 else "center",
            zorder=4,
        )


# --------------------------------------------------------------------------
# Cluster net advantage and break-even (thesis Figures 5.13, 5.14)
# --------------------------------------------------------------------------


def _n_locations(run: RunResult) -> int:
    return len(set(run.entities["location_id"]))


def cluster_penalty(
    series: SweepSeries, benchmark: RunResult, *, eval_split: str | None = None
) -> pd.DataFrame:
    """Return the tail-risk penalty of clustering at each cluster count.

    ``Pi(C) = CVaR(cluster scope at C clusters) - CVaR(benchmark)``, both
    the portfolio tail basis risk (thesis ``_get_cluster_tail_penalty``).

    Parameters
    ----------
    series : SweepSeries
        The ``n_clusters`` sweep of a cluster scope x objective.
    benchmark : RunResult
        The portfolio scope's baseline run of the same objective.
    eval_split : str, optional
        Evaluation split of the CVaRs; default :func:`figure_split` of the
        benchmark and the sweep runs (MAR-229).

    Returns
    -------
    pandas.DataFrame
        Columns :data:`PENALTY_COLUMNS`, by cluster count; failed points have
        ``ok = False`` and no values.

    Raises
    ------
    IncompleteRunError
        If the benchmark failed.
    InconsistentRunsError
        If the series is not an ``n_clusters`` sweep, the objectives differ,
        or the runs cover different numbers of locations.
    MissingKpiError
        If a run lacks the CVaR, or the runs share no split.
    """
    if series.parameter != "n_clusters":
        raise InconsistentRunsError(
            f"the cluster penalty needs an n_clusters sweep, got {series.parameter}"
        )
    benchmark.require_complete()
    if benchmark.objective != series.objective:
        raise InconsistentRunsError(
            f"the cluster penalty compares one objective, got {series.objective!r} "
            f"and {benchmark.objective!r}"
        )
    k = _n_locations(benchmark)
    split = _cluster_split(series, benchmark, eval_split)
    port = kpi_value(benchmark, TAIL_KPI, eval_split=split)
    rows: list[dict[str, object]] = []
    for point, run in series.sorted_points():
        if run.complete and _n_locations(run) != k:
            raise InconsistentRunsError(
                f"run {run.run_id} covers {_n_locations(run)} locations, the "
                f"benchmark {benchmark.run_id} {k}"
            )
        cvar = kpi_value(run, TAIL_KPI, eval_split=split) if run.complete else None
        rows.append(
            {
                "n_clusters": int(point.value),
                "run_id": run.run_id,
                "ok": run.complete,
                "portfolio_run_id": benchmark.run_id,
                "n_locations": k,
                "beta": _evaluation_beta(benchmark),
                "cvar_cluster": cvar,
                "cvar_portfolio": port,
                "penalty": None if cvar is None else cvar - port,
            }
        )
    return pd.DataFrame(rows, columns=list(PENALTY_COLUMNS))


def _cluster_split(
    series: SweepSeries, benchmark: RunResult, eval_split: str | None
) -> str:
    """:func:`figure_split` of the benchmark and the sweep runs (MAR-229)."""
    return figure_split([benchmark, *(r for _, r in series.points)], eval_split)


def net_advantage(
    series: SweepSeries,
    benchmark: RunResult,
    *,
    transaction_costs: Sequence[float] = THESIS_TRANSACTION_COSTS,
    labels: AxisLabels | None = None,
    figsize: tuple[float, float] = _CLUSTER_FIGSIZE,
    name: str | None = None,
    eval_split: str | None = None,
) -> FigureOutput:
    """Draw the net advantage of clustering over the portfolio scope.

    Thesis ``plot_cluster_net_advantage``: ``Delta(C; tau) = (K - C) tau -
    Pi(C)``, the transaction-cost saving of ``C`` cluster contracts instead
    of ``K`` minus the tail-risk penalty (:func:`cluster_penalty`), one
    curve per cost ``tau`` (colour bar), with the break-even line
    ``Delta = 0``.

    Parameters
    ----------
    series : SweepSeries
        The ``n_clusters`` sweep of a cluster scope x objective.
    benchmark : RunResult
        The portfolio scope's baseline run of the same objective.
    transaction_costs : sequence of float, default :data:`THESIS_TRANSACTION_COSTS`
        Costs per contract, loss units; the ``figures`` command passes
        ``FigureContext.transaction_costs`` (MAR-120).
    labels : AxisLabels, optional
        Units.
    figsize : (float, float), default (8, 8)
        Figure size in inches.
    name : str, optional
        Default ``"net_advantage_<scope>"``.
    eval_split : str, optional
        See :func:`cluster_penalty`.

    Returns
    -------
    FigureOutput
        Main table :data:`NET_ADVANTAGE_COLUMNS` (successful points only);
        ``penalty`` (:data:`PENALTY_COLUMNS`, every point); on a ``test`` or
        ``train`` split also :data:`SPLIT_TABLE`, and the axes title states
        the split.

    Raises
    ------
    InconsistentRunsError
        As :func:`cluster_penalty`; also without costs or successful points.
    """
    labels = labels or AxisLabels()
    costs = sorted(float(c) for c in transaction_costs)
    if not costs:
        raise InconsistentRunsError("the net advantage needs transaction costs")
    split = _cluster_split(series, benchmark, eval_split)
    penalty = cluster_penalty(series, benchmark, eval_split=split)
    ok = _where(penalty, penalty["ok"].astype(bool)).reset_index(drop=True)
    if ok.empty:
        raise InconsistentRunsError(
            f"the n_clusters sweep of {series.scope} has no successful point"
        )
    k = int(penalty["n_locations"].iloc[0])
    c = ok["n_clusters"].to_numpy(dtype=int)
    pi = ok["penalty"].to_numpy(dtype=float)
    rows: list[dict[str, object]] = []
    curves: list[tuple[float, NDArray[np.float64]]] = []
    for tau in costs:
        delta = (k - c) * tau - pi
        best = int(c[int(np.argmax(delta))])
        curves.append((tau, delta))
        rows.extend(
            {
                "n_clusters": int(ci),
                "transaction_cost": tau,
                "penalty": float(p),
                "net_advantage": float(d),
                "optimal_n_clusters": best,
            }
            for ci, p, d in zip(c, pi, delta, strict=True)
        )
    table = pd.DataFrame(rows, columns=list(NET_ADVANTAGE_COLUMNS))
    cmap = _sweep_cmap(0.15, 0.85)
    norm = Normalize(vmin=costs[0], vmax=costs[-1] if len(costs) > 1 else costs[0] + 1)

    with style.style():
        fig, ax = plt.subplots(figsize=figsize)
        for tau, delta in curves:
            ax.plot(
                c,
                delta,
                color=cmap(norm(tau)),
                marker="o",
                markersize=4,
                linewidth=1.6,
                zorder=3,
            )
        ax.axhline(0.0, color="black", linestyle="--", linewidth=1.2, zorder=2)
        ax.set_xlim(0.5, k + 0.5)
        ax.set_xticks(range(1, k + 1))
        ax.set_xlabel(r"Number of clusters $C$")
        ax.set_ylabel(rf"Net advantage $\Delta(C;\tau)${_unit(labels)}")
        ax.yaxis.set_major_formatter(style.MoneyFormatter())
        title = _split_heading(split)
        if title is not None:
            ax.set_title(title, fontsize=style.FONT.label_size)
        _frame(ax)
        bar = fig.colorbar(
            ScalarMappable(norm=norm, cmap=cmap),
            ax=ax,
            orientation="horizontal",
            location="bottom",
            pad=0.1,
            shrink=0.5,
            aspect=25,
        )
        bar.set_label(rf"Transaction cost $\tau$ per contract{_unit(labels)}")
        bar.set_ticks(costs)
        bar.set_ticklabels(style.MoneyFormatter().format_ticks(list(costs)))
        handle = Line2D(
            [0],
            [0],
            color="black",
            linestyle="--",
            linewidth=1.2,
            label=r"Break-even ($\Delta = 0$)",
        )
        _figure_legend(fig, [handle], ncol=1, y=_below(fig, bar.ax))
    return FigureOutput(
        name=name or f"net_advantage_{series.scope}",
        figure=fig,
        data=_with_split({MAIN_TABLE: table, "penalty": penalty}, split),
    )


def breakeven_cost(
    series: SweepSeries,
    benchmark: RunResult,
    *,
    labels: AxisLabels | None = None,
    figsize: tuple[float, float] = _CLUSTER_FIGSIZE,
    name: str | None = None,
    eval_split: str | None = None,
) -> FigureOutput:
    """Draw the break-even transaction cost of clustering.

    Thesis ``plot_cluster_breakeven_cost``: ``tau*(C) = Pi(C) / (K - C)``
    for ``C < K``. Above the curve clustering is cheaper overall (green),
    below it the portfolio scope (red).

    Parameters
    ----------
    series : SweepSeries
        The ``n_clusters`` sweep of a cluster scope x objective.
    benchmark : RunResult
        The portfolio scope's baseline run of the same objective.
    labels : AxisLabels, optional
        Units.
    figsize : (float, float), default (8, 8)
        Figure size in inches.
    name : str, optional
        Default ``"breakeven_cost_<scope>"``.
    eval_split : str, optional
        See :func:`cluster_penalty`.

    Returns
    -------
    FigureOutput
        Main table :data:`BREAKEVEN_COLUMNS`, the points with ``C < K``
        (failed ones with no values); on a ``test`` or ``train`` split also
        :data:`SPLIT_TABLE`, and the axes title states the split.

    Raises
    ------
    InconsistentRunsError
        As :func:`cluster_penalty`; also without a successful point below
        ``K``.
    """
    labels = labels or AxisLabels()
    split = _cluster_split(series, benchmark, eval_split)
    penalty = cluster_penalty(series, benchmark, eval_split=split)
    k = int(penalty["n_locations"].iloc[0])
    table = penalty[penalty["n_clusters"] < k].reset_index(drop=True)
    breakeven = [
        None if not ok else float(p) / (k - int(n))
        for ok, p, n in zip(
            table["ok"].astype(bool), table["penalty"], table["n_clusters"], strict=True
        )
    ]
    table = table.assign(breakeven_cost=breakeven).loc[:, list(BREAKEVEN_COLUMNS)]
    drawn = table.dropna(subset=["breakeven_cost"])
    if drawn.empty:
        raise InconsistentRunsError(
            f"the n_clusters sweep of {series.scope} has no successful point "
            f"below the {k} locations"
        )
    x = drawn["n_clusters"].to_numpy(dtype=int)
    y = drawn["breakeven_cost"].to_numpy(dtype=float)

    with style.style():
        fig, ax = plt.subplots(figsize=figsize)
        ax.plot(x, y, color="black", marker="o", markersize=5, linewidth=1.8, zorder=3)
        top = float(np.nanmax(y)) * 1.15 if np.nanmax(y) > 0 else 1.0
        bottom = min(0.0, float(np.nanmin(y)) * 1.15)
        ax.set_xlim(0.5, k + 0.5)
        ax.set_ylim(bottom, top)
        ax.fill_between(x, y, top, color=_CLUSTER_REGIME, alpha=_REGIME_ALPHA, zorder=0)
        ax.fill_between(
            x, bottom, y, color=_PORTFOLIO_REGIME, alpha=_REGIME_ALPHA, zorder=0
        )
        ax.set_xticks(range(1, k + 1))
        ax.set_xlabel(r"Number of clusters $C$")
        ax.set_ylabel(rf"Break-even cost per contract $\tau^*(C)${_unit(labels)}")
        ax.yaxis.set_major_formatter(style.MoneyFormatter())
        title = _split_heading(split)
        if title is not None:
            ax.set_title(title, fontsize=style.FONT.label_size)
        _frame(ax)
        fig.tight_layout()
        handles = [
            Patch(
                facecolor=_CLUSTER_REGIME,
                alpha=_REGIME_ALPHA,
                label="Cluster scope regime",
            ),
            Patch(
                facecolor=_PORTFOLIO_REGIME,
                alpha=_REGIME_ALPHA,
                label="Portfolio scope regime",
            ),
        ]
        _figure_legend(fig, handles, ncol=2)
    return FigureOutput(
        name=name or f"breakeven_cost_{series.scope}",
        figure=fig,
        data=_with_split({MAIN_TABLE: table}, split),
    )


# --------------------------------------------------------------------------
# The figure set
# --------------------------------------------------------------------------


def _series(
    context: FigureContext, parameter: str
) -> list[tuple[ScopeRuns, SweepSeries]]:
    """Every single run of the config with its points of one sweep.

    The runs of the sweep's points are read in bulk, one store read per
    table (MAR-120). Points in ``context.missing_sweeps`` are not read; each
    series lists them as ``missing``.
    """
    absent = {p.run_id for p in context.missing_sweeps}
    mine = [p for p in context.sweeps if p.parameter == parameter]
    present = [p.run_id for p in mine if p.run_id not in absent]
    unique = tuple(dict.fromkeys(present))
    runs = dict(zip(unique, context.reader.runs(unique), strict=True))
    points: dict[int, list[SweepRun]] = {}
    for point in mine:
        points.setdefault(point.single, []).append(point)
    out: list[tuple[ScopeRuns, SweepSeries]] = []
    n_singles = len(context.config.single_runs())
    for single in range(n_singles):
        scope, baseline = context.scope_of(single)
        these = points.get(single, [])
        out.append(
            (
                scope,
                SweepSeries(
                    parameter=parameter,
                    scope=scope.key,
                    baseline=baseline,
                    points=tuple(
                        (p, runs[p.run_id]) for p in these if p.run_id not in absent
                    ),
                    missing=tuple(p for p in these if p.run_id in absent),
                ),
            )
        )
    return out


def _missing_points(name: str, series: Sequence[SweepSeries]) -> SkippedFigure | None:
    """Skip a figure whose sweep points are not all in the store (MAR-120)."""
    from parametric_insurance_design_viz.command import SkippedFigure

    missing = [(s, p) for s in series for p in s.missing]
    if not missing:
        return None
    total = sum(len(s.points) + len(s.missing) for s in series)
    examples = "; ".join(
        f"{p.parameter}={p.value!r} {s.scope} x {s.objective} run {p.run_id}"
        for s, p in missing[:3]
    )
    parameters = " ".join(
        f"--parameter {x}" for x in dict.fromkeys(p.parameter for _, p in missing)
    )
    return SkippedFigure(
        name,
        f"{len(missing)} of its {total} sweep points are not in the result "
        f"store, e.g. {examples}; run them first (parametric-insurance-design "
        f"sweep CONFIG {parameters})",
        failed=False,
        missing=True,
    )


def _failed_points(name: str, series: Sequence[SweepSeries]) -> list[SkippedFigure]:
    """Report a figure drawn without failed points (failed ``SkippedFigure``)."""
    from parametric_insurance_design_viz.command import SkippedFigure

    failed = [(s, p, r) for s in series for p, r in s.failed]
    if not failed:
        return []
    total = sum(len(s.points) for s in series)
    examples = "; ".join(
        f"{p.parameter}={p.value!r} {s.scope} x {s.objective} run {r.run_id} "
        f"({', '.join(r.failed_problems)})"
        for s, p, r in failed[:3]
    )
    return [
        SkippedFigure(
            name,
            f"drawn without {len(failed)} of {total} sweep points whose run "
            f"failed (listed with ok = False in its figure data), e.g. {examples}",
            failed=True,
        )
    ]


def _baseline_failed(name: str, runs: Sequence[RunResult]) -> SkippedFigure | None:
    from parametric_insurance_design_viz.command import SkippedFigure

    failed = [r for r in runs if not r.complete]
    if not failed:
        return None
    return SkippedFigure(
        name,
        "; ".join(
            f"run {r.run_id} ({r.scope} x {r.objective}) failed for "
            f"{', '.join(r.failed_problems)}"
            for r in failed
        ),
        failed=True,
    )


def _location_values(eventset: EventSet | None) -> dict[str, float] | None:
    if eventset is None:
        return None
    locations = eventset.locations
    return {
        str(k): float(v)
        for k, v in zip(locations["location_id"], locations["value"], strict=True)
    }


def _focus(scopes: Sequence[ScopeRuns], kind: str) -> list[tuple[ScopeRuns, RunResult]]:
    """Every scope of a kind with its run of the focus objective."""
    return [
        (scope, run)
        for scope in scopes
        for run in scope.runs
        if run.scope == kind and run.objective == FOCUS_OBJECTIVE
    ]


def _premium_figure(context: FigureContext) -> Iterator[FigureOutput | SkippedFigure]:
    from parametric_insurance_design_viz.command import SkippedFigure

    name = "premium_reallocation"
    individual = _focus(context.scopes, "individual")
    portfolio = _focus(context.scopes, "portfolio")
    if not individual or not portfolio:
        yield SkippedFigure(
            name,
            f"the config needs an individual and a portfolio scope with the "
            f"{FOCUS_OBJECTIVE!r} objective",
            failed=False,
        )
        return
    runs = (individual[0][1], portfolio[0][1])
    failed = _baseline_failed(name, runs)
    if failed is not None:
        yield failed
        return
    yield premium_reallocation(
        *runs,
        location_values=_location_values(context.eventset),
        labels=context.labels,
        name=name,
    )


def _payout_sweeps(
    context: FigureContext, rows: Sequence[tuple[ScopeRuns, SweepSeries]]
) -> Iterator[FigureOutput | SkippedFigure]:
    for scope, s in rows:
        if s.objective != FOCUS_OBJECTIVE or not s.swept:
            continue
        # a failed baseline has no entities: its skip names the scope only
        entity = s.baseline.entity_order()[0] if s.baseline.complete else None
        parts = [scope.key, entity, s.parameter]
        name = "payout_sweep_" + "_".join(x for x in parts if x).lower()
        benchmark = next(
            (r for r in scope.runs if r.objective == style.BENCHMARK_OBJECTIVE), None
        )
        failed = _baseline_failed(
            name, [s.baseline] + ([benchmark] if benchmark else [])
        )
        if failed is not None:
            yield failed
            continue
        missing = _missing_points(name, [s])
        if missing is not None:
            yield missing
            continue
        yield payout_sweep(
            s,
            cast(str, entity),  # the baseline is complete, so it has entities
            benchmark=benchmark,
            events=scope.events,
            labels=context.labels,
            name=name,
        )
        yield from _failed_points(name, [s])


def _sensitivity_figure(
    context: FigureContext,
    parameter: str,
    rows: Sequence[tuple[ScopeRuns, SweepSeries]],
) -> Iterator[FigureOutput | SkippedFigure]:
    name = f"sensitivity_{parameter}"
    series = [
        s for _, s in rows if (s.scope_kind, s.objective) not in SENSITIVITY_EXCLUDED
    ]
    flat = [s.baseline for s in series if not s.swept]
    failed = _baseline_failed(name, flat)
    if failed is not None:
        yield failed
        return
    missing = _missing_points(name, series)
    if missing is not None:
        yield missing
        return
    values = sorted(
        {float(p.value) for p in context.sweeps if p.parameter == parameter}
    )
    yield sensitivity(
        parameter, series, values=values, labels=context.labels, name=name
    )
    yield from _failed_points(name, series)


def _tradeoff_figures(
    context: FigureContext, rows: Sequence[tuple[ScopeRuns, SweepSeries]]
) -> Iterator[FigureOutput | SkippedFigure]:
    for scope, s in rows:
        if (s.scope_kind, s.objective) != ("portfolio", FOCUS_OBJECTIVE):
            continue
        if not s.swept:
            continue
        name = f"tradeoff_{scope.key}_{s.parameter}"
        missing = _missing_points(name, [s])
        if missing is not None:
            yield missing
            continue
        if all(not r.complete for _, r in s.points):
            yield _all_failed(name, s)
            continue
        yield tradeoff(s, labels=context.labels, name=name)
        yield from _failed_points(name, [s])


def _all_failed(name: str, s: SweepSeries) -> SkippedFigure:
    from parametric_insurance_design_viz.command import SkippedFigure

    return SkippedFigure(
        name,
        f"every one of the {len(s.points)} {s.parameter} sweep points of "
        f"{s.scope} x {s.objective} failed",
        failed=True,
    )


def _cluster_figures(
    context: FigureContext, rows: Sequence[tuple[ScopeRuns, SweepSeries]]
) -> Iterator[FigureOutput | SkippedFigure]:
    from parametric_insurance_design_viz.command import SkippedFigure

    portfolio = _focus(context.scopes, "portfolio")
    for scope, s in rows:
        if (s.scope_kind, s.objective) != ("cluster", FOCUS_OBJECTIVE) or not s.swept:
            continue
        names = (f"net_advantage_{scope.key}", f"breakeven_cost_{scope.key}")
        if s.scope_name == style.SEPARATE_CLUSTER_SCOPE:
            yield from (
                SkippedFigure(n, SEPARATE_CLUSTER_REASON, failed=False) for n in names
            )
            continue
        if not portfolio:
            yield from (
                SkippedFigure(
                    n,
                    f"the config has no portfolio scope with the {FOCUS_OBJECTIVE!r} "
                    "objective to compare the cluster scope with",
                    failed=False,
                )
                for n in names
            )
            continue
        benchmark = portfolio[0][1]
        failed = _baseline_failed(names[0], [benchmark])
        if failed is not None:
            yield from (SkippedFigure(n, failed.reason, failed=True) for n in names)
            continue
        k = _n_locations(benchmark)
        all_failed = bool(s.points) and all(not r.complete for _, r in s.points)
        missing = _missing_points(names[0], [s])
        if missing is not None:
            yield missing
        elif all_failed:
            yield _all_failed(names[0], s)
        else:
            yield net_advantage(
                s,
                benchmark,
                transaction_costs=context.transaction_costs,
                labels=context.labels,
                name=names[0],
            )
            yield from _failed_points(names[0], [s])
        # the break-even figure needs only the points below K
        missing_below = tuple(p for p in s.missing if int(p.value) < k)
        missing = _missing_points(
            names[1], [SweepSeries(s.parameter, s.scope, s.baseline, (), missing_below)]
        )
        if missing is not None:
            yield missing
            continue
        if all_failed:
            yield _all_failed(names[1], s)
            continue
        below = [(p, r) for p, r in s.points if int(p.value) < k and r.complete]
        if not below:
            yield SkippedFigure(
                names[1],
                f"no successful n_clusters point below the {k} locations",
                failed=False,
            )
            continue
        yield breakeven_cost(s, benchmark, labels=context.labels, name=names[1])
        below_k = tuple((p, r) for p, r in s.points if int(p.value) < k)
        yield from _failed_points(
            names[1], [SweepSeries(s.parameter, s.scope, s.baseline, below_k)]
        )


def sweep_figures(context: FigureContext) -> Iterator[FigureOutput | SkippedFigure]:
    """Draw the MAR-112 figure set: reallocation, sweeps, trade-off, clusters.

    Registered in ``command.FIGURE_SETS``. See the module docstring for the
    figures and how failures are reported.

    Parameters
    ----------
    context : FigureContext
        The config's runs and its sweep points (``context.sweeps``).

    Yields
    ------
    FigureOutput or SkippedFigure
        One at a time, so each is written and closed before the next is
        drawn: ``premium_reallocation``, then per configured sweep (config
        order) its payout sweeps, its sensitivity, its trade-offs and, for
        ``n_clusters``, the net advantage and break-even figures.
    """
    yield from _premium_figure(context)
    if not context.sweeps:
        return
    swept = list(dict.fromkeys(p.parameter for p in context.sweeps))
    order = [s.parameter for s in context.config.sweeps if s.parameter in swept]
    order += [p for p in swept if p not in order]
    for parameter in order:
        # one sweep's runs at a time bounds the memory
        rows = _series(context, parameter)
        if parameter in PAYOUT_SWEEP_PARAMETERS:
            yield from _payout_sweeps(context, rows)
        yield from _sensitivity_figure(context, parameter, rows)
        if parameter in TRADEOFF_PARAMETERS:
            yield from _tradeoff_figures(context, rows)
        if parameter == "n_clusters":
            yield from _cluster_figures(context, rows)
