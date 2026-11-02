"""Payout-function figures: the per-entity grid and the normalised view.

Owner: MAR-110. Ports two figures of the thesis ``plotting.py``
(parametric-insurance-framework):

* :func:`payout_grid` (thesis ``plot_payout_functions_grid``, view
  ``"vanilla"``; thesis Figures 5.1, 5.3 and 5.4): one panel per payout
  entity of a scope, with the calibrated step payout function of every
  objective over the entity's event data (index against loss).
* :func:`normalised_payout` (thesis ``plot_normalized_payout_functions``;
  thesis Figure 5.2 and A.1, A.2): one entity's payout per bin relative to
  the benchmark objective's payout in the same bin, over the event density
  of the entity index.

Both read :class:`~parametric_insurance_design_viz.reader.RunResult` objects
(the result store) and never re-run an optimisation. The event overlays come
from :func:`~parametric_insurance_design_viz.reader.entity_events`, the
run's prepared EventSet; without it the figures show the payout functions
alone. Each figure returns its data as tidy tables
(:class:`~parametric_insurance_design_viz.figure_data.FigureOutput`).

Differences from the thesis code, all deliberate:

* Bins whose benchmark payout is zero to solver precision (``|level| <=``
  :data:`BENCHMARK_ZERO_RTOL` times the benchmark's largest level) have no
  normalised value (NaN). The thesis divided by any non-zero level, so bins
  where both payouts were solver noise showed arbitrary ratios.
* The event density and the tail quantile weight each event row by its
  ``rate``. For the thesis event set (equal rates) this is the thesis'
  unweighted KDE; the quantile is the inverse of the weighted empirical CDF
  rather than numpy's linear interpolation.
* Axis labels name the index generically ("Index") with its unit from the
  EventSet metadata, as the core is hazard-agnostic; the thesis wrote "Wind
  speed".
* The payout axis of :func:`payout_grid` labels its ticks in the money style
  of the other figures (:class:`~.style.MoneyFormatter`: ``0.5M``, ``200k``,
  ``50``; MAR-232). The thesis wrote scientific ticks with an offset text
  such as ``1e7``.

Below the attachment (MAR-178)
------------------------------
:func:`payout_grid` draws each run's payout below the attachment ``b_0`` as
the run's :class:`~parametric_insurance_design.payout.StepPayout` pays it
(:func:`below_attachment_mode`):

* ``"first_bin"`` (the default and the thesis code): the first bin's level,
  so the step extends to the left edge of the axis, as in the thesis. Runs
  whose ``runs.parameters`` have no ``below_attachment`` key, every run
  written before MAR-178 among them, are drawn this way.
* ``"zero"`` (MAR-170, recorded in ``runs.parameters`` since MAR-178): 0, with
  a step up to the first level at ``b_0``. The figure data show it as one
  more row per entity, before its bins: ``param_index`` is
  :data:`~parametric_insurance_design.payout.NO_BIN` (-1), ``lower`` is
  ``-inf``, ``upper`` is ``b_0`` and ``value`` is 0.

:func:`normalised_payout` draws nothing below the attachment in either mode,
as in the thesis; under ``"zero"`` both payouts are 0 there, so their ratio
is undefined anyway.

Joint designs (MAR-218, design review F8)
-----------------------------------------
A run is a joint design (:func:`is_joint_design`) when one of its design
problems calibrates more than one payout entity: the portfolio scope, and
the cluster scope with more than one cluster. Such a problem is identified
only through the sum over its entities, so its per-entity payout functions
are one of several optimal designs, the one the solver returned (see
``docs/concepts/portfolio-calibration.md``, "Per-asset results of joint
designs are not unique"). Unlike per-asset KPIs (``evaluate.kpis``,
``allocation``), payout functions have no allocation rule, so both figures
take a keyword ``joint_entities`` (:data:`JOINT_ENTITIES_MODES`) that applies
whenever a drawn entity belongs to a joint problem:

* ``"caption"`` (the default): the figure carries :data:`JOINT_CAPTION` as its
  title, and its data hold a ``caption`` table (:data:`CAPTION_COLUMNS`, one
  row per joint problem drawn), so the CSVs keep the caption too.
* ``"refuse"``: raise :class:`JointEntitiesError` before drawing.

Figures of runs without a joint problem (the individual scope) are unchanged
in both modes. External outputs (website, posts, examples) show per-entity
payout functions of a joint design only with the caption.

Step helpers (MAR-193)
----------------------
:func:`step_points`, :func:`bin_breakpoints`, :func:`with_zero_rows` and
:func:`shared_attachment_limit` are public, so the payout sweep
(``sweep_figures``) draws and tabulates its step payouts with the same code
as :func:`payout_grid`.
"""

from __future__ import annotations

import math
import textwrap
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final, Literal, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter
from numpy.typing import NDArray
from scipy.stats import gaussian_kde

from parametric_insurance_design.payout import (
    BELOW_ATTACHMENT_MODES,
    NO_BIN,
    BelowAttachment,
)
from parametric_insurance_design_viz import style
from parametric_insurance_design_viz.errors import (
    FigureDataError,
    InconsistentRunsError,
    VizError,
)
from parametric_insurance_design_viz.figure_data import MAIN_TABLE, FigureOutput
from parametric_insurance_design_viz.reader import RunResult

__all__ = [
    "BENCHMARK_ZERO_RTOL",
    "CAPTION_COLUMNS",
    "DENSITY_POINTS",
    "JOINT_CAPTION",
    "JOINT_ENTITIES_MODES",
    "MARKER_COLUMNS",
    "STEP_COLUMNS",
    "AxisLabels",
    "JointEntities",
    "JointEntitiesError",
    "below_attachment_mode",
    "bin_breakpoints",
    "is_joint_design",
    "normalised_payout",
    "payout_grid",
    "payout_steps",
    "shared_attachment_limit",
    "step_points",
    "weighted_quantile",
    "with_zero_rows",
]

BENCHMARK_ZERO_RTOL: Final[float] = 1e-6
"""Benchmark levels at most this times its largest level count as zero."""

DENSITY_POINTS: Final[int] = 500
"""Grid points of the event density (thesis: 500)."""

STEP_COLUMNS: Final[tuple[str, ...]] = (
    "run_id",
    "scope",
    "objective",
    "problem_id",
    "entity_id",
    "location_ids",
    "param_index",
    "lower",
    "upper",
    "value",
)
"""Columns of :func:`payout_steps` and of the grid's figure data.

The grid's figure data also have a row with ``param_index`` equal to
:data:`~parametric_insurance_design.payout.NO_BIN` for each entity of a
``"zero"`` run: the index range below the attachment, which pays 0 (see the
module docstring)."""

MARKER_COLUMNS: Final[tuple[str, ...]] = ("entity_id", "marker", "level", "value")
"""Columns of the ``markers`` table: vertical reference lines."""

JointEntities = Literal["caption", "refuse"]
"""How a payout figure treats the per-entity panels of a joint design."""

JOINT_ENTITIES_MODES: Final[tuple[JointEntities, ...]] = ("caption", "refuse")
"""The values of ``joint_entities`` (module docstring, "Joint designs")."""

JOINT_CAPTION: Final[str] = (
    "Joint design: the payout split across entities is not unique. These "
    "per-entity payout functions are one of several optimal designs, chosen "
    "by the solver; read the portfolio level."
)
"""Caption of the per-entity payout panels of a joint design (MAR-218)."""

CAPTION_COLUMNS: Final[tuple[str, ...]] = (
    "scope",
    "problem_id",
    "entity_ids",
    "caption",
)
"""Columns of the ``caption`` table: one row per joint problem drawn;
``entity_ids`` joins its drawn entities, in panel order, with ``";"``."""

_SHADE_ALPHA: Final[float] = 0.15
_SCATTER_ALPHA: Final[float] = 0.25
_SCATTER_SIZE: Final[float] = 8
_DENSITY_ALPHA: Final[float] = 0.25
_PANEL_FONT: Final[float] = 9  # thesis _plot_payout_subfigure axis labels
_LABEL_Y: Final[float] = 0.05  # height of vertical-line labels, axes fraction
_CAPTION_CHAR_WIDTH: Final[float] = 0.55  # mean glyph width, in font sizes


class JointEntitiesError(VizError):
    """A payout figure would show per-entity panels of a joint design.

    Raised under ``joint_entities="refuse"`` (module docstring, "Joint
    designs").
    """


@dataclass(frozen=True)
class AxisLabels:
    """Axis labels of the payout figures.

    Parameters
    ----------
    index_unit : str or None, default None
        Unit of the index, e.g. ``"m/s"`` (EventSet ``metadata.index.unit``).
    payout_unit : str or None, default None
        Unit of losses and payouts, e.g. ``"USD"``.
    """

    index_unit: str | None = None
    payout_unit: str | None = None

    @staticmethod
    def _unit(unit: str | None) -> str:
        return f" [{unit}]" if unit else ""

    def index(self, *, aggregate: bool) -> str:
        """Label of the index axis; ``aggregate`` for multi-location entities."""
        if aggregate:
            return rf"Aggregate index $x^{{(c)}}${self._unit(self.index_unit)}"
        return rf"Index $x${self._unit(self.index_unit)}"

    def payout(self) -> str:
        """Label of the payout axis."""
        return rf"Payout $Y_{{P}}(x)${self._unit(self.payout_unit)}"


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def _where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    """Return the rows of ``frame`` where ``mask`` is true."""
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


def _scope_runs(runs: Sequence[RunResult]) -> tuple[RunResult, ...]:
    """Check that runs are complete, share one scope and differ in objective."""
    runs = tuple(runs)
    if not runs:
        raise InconsistentRunsError("a payout figure needs at least one run")
    for run in runs:
        run.require_complete()
    scopes = sorted({r.scope for r in runs})
    if len(scopes) != 1:
        raise InconsistentRunsError(
            f"a payout figure shows one scope, got runs of scopes {scopes}"
        )
    objectives = [r.objective for r in runs]
    if len(set(objectives)) != len(objectives):
        raise InconsistentRunsError(
            f"a payout figure shows each objective once, got {objectives}"
        )
    members = {r.run_id: _membership(r) for r in runs}
    first = runs[0]
    for run in runs[1:]:
        if members[run.run_id] != members[first.run_id]:
            raise InconsistentRunsError(
                f"runs {first.run_id} and {run.run_id} have different entities: "
                f"{members[first.run_id]} and {members[run.run_id]}"
            )
    return runs


def _membership(run: RunResult) -> dict[str, tuple[str, ...]]:
    """Entity id to its locations, from the ``entities`` table."""
    return {
        entity.entity_id: entity.location_ids
        for spec in run.problem_specs()
        for entity in spec.entities
    }


def shared_attachment_limit(runs: Sequence[RunResult]) -> tuple[float, float]:
    """Return the attachment and limit that the runs of one figure share.

    Used by every payout-function figure, the payout grid, the normalised
    payout and the payout sweep (``sweep_figures``), to place the reference
    lines and the default axis range.

    Parameters
    ----------
    runs : sequence of RunResult
        The runs drawn into one figure.

    Returns
    -------
    (float, float)
        ``(attachment, limit)`` from the runs' ``runs.parameters``.

    Raises
    ------
    InconsistentRunsError
        If the runs differ in attachment or limit, or ``runs`` is empty.
    """
    pairs = {
        (float(r.parameters["attachment"]), float(r.parameters["limit"])) for r in runs
    }
    if len(pairs) != 1:
        raise InconsistentRunsError(
            "the runs of one figure must share attachment and limit, got "
            f"{sorted(pairs)}"
        )
    return pairs.pop()


def below_attachment_mode(run: RunResult) -> BelowAttachment:
    """Return what a run's step payout pays below the attachment.

    Read from ``runs.parameters``: the runner records ``below_attachment``
    only when it is not the default ``"first_bin"`` (MAR-178), so a run
    without the key pays the first bin's level there. The run's manifest
    config must agree. A ``"zero"`` run written before MAR-178 has the mode
    in its config but not in its parameters; its run id did not change, so
    re-running it is a cache hit and keeps the old parameters. Drawing it as
    ``"first_bin"`` would be wrong, so it raises instead.

    Parameters
    ----------
    run : RunResult
        A run.

    Returns
    -------
    {"first_bin", "zero"}
        The mode
        (:data:`~parametric_insurance_design.payout.BelowAttachment`).

    Raises
    ------
    FigureDataError
        If the recorded value is not a mode.
    InconsistentRunsError
        If ``runs.parameters`` and the payout of the manifest's config
        disagree, e.g. a ``"zero"`` run written before MAR-178.
    """
    recorded = run.parameters.get("below_attachment", "first_bin")
    if recorded not in BELOW_ATTACHMENT_MODES:
        raise FigureDataError(
            f"run {run.run_id}: runs.parameters records below_attachment "
            f"{recorded!r}, not one of {list(BELOW_ATTACHMENT_MODES)}"
        )
    config = run.manifest.get("config")
    payout = config.get("payout") if isinstance(config, Mapping) else None
    if isinstance(payout, Mapping):
        configured = payout.get("below_attachment", "first_bin")
        if configured != recorded:
            raise InconsistentRunsError(
                f"run {run.run_id}: its config pays {configured!r} below the "
                f"attachment, but runs.parameters says {recorded!r}. A run "
                "written before MAR-178 does not record 'zero' in its "
                "parameters; recompute it (`parametric-insurance-design run "
                "--force`, or a new result store) to draw it"
            )
    return cast(BelowAttachment, recorded)


def is_joint_design(run: RunResult) -> bool:
    """Return whether a run has a design problem with several payout entities.

    The per-entity payout functions of such a problem are one of several
    optimal designs (design review F8; module docstring, "Joint designs").

    Parameters
    ----------
    run : RunResult
        A run.

    Returns
    -------
    bool
        True for the portfolio scope and a cluster scope with more than one
        cluster; False for the individual scope.
    """
    return any(len(spec.entities) > 1 for spec in run.problem_specs())


def _check_joint_mode(joint_entities: str) -> None:
    """Raise if ``joint_entities`` is not one of :data:`JOINT_ENTITIES_MODES`."""
    if joint_entities not in JOINT_ENTITIES_MODES:
        raise FigureDataError(
            f"joint_entities must be one of {list(JOINT_ENTITIES_MODES)}, "
            f"got {joint_entities!r}"
        )


def _joint_caption(
    run: RunResult,
    entity_ids: Sequence[str],
    joint_entities: JointEntities,
    *,
    figure: str,
) -> pd.DataFrame | None:
    """Return the ``caption`` table of the drawn entities, or None.

    One row per joint problem (more than one entity) with a drawn entity;
    None if no drawn entity belongs to one. Under ``"refuse"`` such entities
    raise instead.

    Raises
    ------
    JointEntitiesError
        Under ``"refuse"``, if a drawn entity belongs to a joint problem.
    """
    rows: list[dict[str, str]] = []
    for spec in run.problem_specs():
        if len(spec.entities) < 2:
            continue
        ids = {entity.entity_id for entity in spec.entities}
        drawn = [e for e in entity_ids if e in ids]
        if not drawn:
            continue
        if joint_entities == "refuse":
            raise JointEntitiesError(
                f"{figure}: scope {run.scope!r} is a joint design (problem "
                f"{spec.problem_id!r} calibrates {len(spec.entities)} entities "
                "jointly), so its per-entity payout functions are one of "
                "several optimal designs, chosen by the solver. Pass "
                "joint_entities='caption' to draw them with a caption that "
                "says so, or read the portfolio-level KPIs"
            )
        rows.append(
            {
                "scope": run.scope,
                "problem_id": spec.problem_id,
                "entity_ids": ";".join(drawn),
                "caption": JOINT_CAPTION,
            }
        )
    if not rows:
        return None
    return pd.DataFrame(rows, columns=list(CAPTION_COLUMNS))


def payout_steps(runs: Sequence[RunResult]) -> pd.DataFrame:
    """Return the fitted step payout functions of runs as one tidy table.

    Parameters
    ----------
    runs : sequence of RunResult
        Complete runs.

    Returns
    -------
    pandas.DataFrame
        Columns :data:`STEP_COLUMNS`, one row per (run, entity, bin), bins
        in ``param_index`` order. ``location_ids`` joins the entity's
        locations with ``";"``.

    Raises
    ------
    IncompleteRunError
        If a run has a failed design problem.
    InconsistentRunsError
        If an entity's bins are not contiguous.
    """
    frames: list[pd.DataFrame] = []
    for run in runs:
        run.require_complete()
        members = _membership(run)
        payouts = run.payouts.sort_values(
            ["problem_id", "entity_id", "param_index"], kind="stable"
        )
        frame = payouts.assign(
            scope=run.scope,
            objective=run.objective,
            location_ids=[";".join(members.get(e, ())) for e in payouts["entity_id"]],
        )
        frames.append(frame.loc[:, list(STEP_COLUMNS)])
    if not frames:
        return pd.DataFrame({c: [] for c in STEP_COLUMNS})
    steps = pd.concat(frames, ignore_index=True)
    for key, bins in steps.groupby(["run_id", "entity_id"], sort=False):
        run_id, entity_id = cast(tuple[str, str], key)
        lower = bins["lower"].to_numpy()
        upper = bins["upper"].to_numpy()
        if not np.allclose(lower[1:], upper[:-1], rtol=0.0, atol=1e-9):
            raise InconsistentRunsError(
                f"run {run_id}, entity {entity_id}: payout bins are not contiguous"
            )
    return steps


def with_zero_rows(
    steps: pd.DataFrame, modes: Mapping[str, BelowAttachment]
) -> pd.DataFrame:
    """Return step figure data with the zero rows below the attachment.

    The figure data of the payout grid and the payout sweep (MAR-178,
    MAR-192; module docstring, "Below the attachment"). Each entity of a run
    whose mode is ``"zero"`` gets one row before its bins, a copy of its
    first bin with ``param_index = NO_BIN``, ``lower = -inf``,
    ``upper = b_0`` and ``value = 0``.

    Parameters
    ----------
    steps : pandas.DataFrame
        Step table with at least the columns ``run_id``, ``entity_id``,
        ``param_index``, ``lower``, ``upper`` and ``value``, each entity's
        bins in order (e.g. from :func:`payout_steps`).
    modes : mapping of str to BelowAttachment
        Each run's ``below_attachment`` mode by ``run_id``
        (:func:`below_attachment_mode`); must cover every run in ``steps``.

    Returns
    -------
    pandas.DataFrame
        ``steps`` itself when every mode is ``"first_bin"``; otherwise a new
        table with the zero rows inserted and a fresh ``RangeIndex``.

    Raises
    ------
    FigureDataError
        If a run in ``steps`` has no mode in ``modes``.
    """
    unknown = sorted(set(steps["run_id"]) - set(modes))
    if unknown:
        raise FigureDataError(f"no below_attachment mode for runs {unknown}")
    if all(mode == "first_bin" for mode in modes.values()):
        return steps
    parts: list[pd.DataFrame] = []
    for key, bins in steps.groupby(["run_id", "entity_id"], sort=False):
        run_id, _ = cast(tuple[str, str], key)
        if modes[run_id] == "zero":
            parts.append(
                bins.iloc[[0]].assign(
                    param_index=NO_BIN,
                    lower=-np.inf,
                    upper=float(bins["lower"].iloc[0]),
                    value=0.0,
                )
            )
        parts.append(bins)
    return pd.concat(parts, ignore_index=True)


def bin_breakpoints(bins: pd.DataFrame) -> NDArray[np.float64]:
    """Return the breakpoints ``b_0 .. b_n`` of one entity's bins.

    Parameters
    ----------
    bins : pandas.DataFrame
        The ``n`` bins of one run's entity, in ``param_index`` order, with
        columns ``lower`` and ``upper`` (rows of :func:`payout_steps`).

    Returns
    -------
    ndarray of float
        ``n + 1`` breakpoints: every bin's ``lower``, then the last
        ``upper``.

    Raises
    ------
    FigureDataError
        If ``bins`` is empty.
    """
    if bins.empty:
        raise FigureDataError("an entity needs at least one bin for its breakpoints")
    lower = bins["lower"].to_numpy(dtype=np.float64)
    return np.append(lower, float(bins["upper"].iloc[-1]))


def weighted_quantile(
    values: NDArray[np.float64], weights: NDArray[np.float64], level: float
) -> float:
    """Return the ``level`` quantile of a weighted sample.

    The smallest value whose cumulative weight share reaches ``level``
    (inverse of the weighted empirical CDF).

    Parameters
    ----------
    values : ndarray of float
        Sample, finite.
    weights : ndarray of float
        Non-negative weights with a positive sum, same shape.
    level : float
        In ``[0, 1]``.

    Returns
    -------
    float
        The quantile.

    Raises
    ------
    FigureDataError
        If the sample is empty, the shapes differ, the weights are invalid or
        ``level`` is outside ``[0, 1]``.
    """
    v = np.asarray(values, dtype=np.float64)
    w = np.asarray(weights, dtype=np.float64)
    if v.ndim != 1 or v.shape != w.shape or v.size == 0:
        raise FigureDataError("weighted_quantile needs two equal-length 1-d arrays")
    if not 0.0 <= level <= 1.0:
        raise FigureDataError(f"quantile level must be in [0, 1], got {level}")
    if np.any(w < 0) or not np.all(np.isfinite(w)) or w.sum() <= 0:
        raise FigureDataError("weights must be finite, >= 0 and not all zero")
    order = np.argsort(v, kind="stable")
    share = np.cumsum(w[order]) / w.sum()
    position = int(np.searchsorted(share, level - 1e-12, side="left"))
    return float(v[order][min(position, v.size - 1)])


def _entity_events(events: pd.DataFrame | None, entity_id: str) -> pd.DataFrame | None:
    """Return the event rows of one entity, or None without event data."""
    if events is None:
        return None
    rows = _where(events, events["entity_id"] == entity_id)
    return rows if len(rows) else None


# --------------------------------------------------------------------------
# Drawing helpers
# --------------------------------------------------------------------------


def _default_xlim(attachment: float, limit: float) -> tuple[float, float]:
    """Thesis axis range: 20 % of the payout range on either side (10 to 80)."""
    margin = 0.2 * (limit - attachment)
    return attachment - margin, limit + margin


def step_points(
    breakpoints: NDArray[np.float64],
    levels: NDArray[np.float64],
    xlim: tuple[float, float],
    mode: BelowAttachment,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Return the points of a step payout for ``ax.step(where="post")``.

    The payout grid and the payout sweep (``sweep_figures``) draw every
    step payout function with these points. Above the limit the payout is
    the last level (``StepPayout`` clips the index into the last bin).
    Below the attachment it is the first level under ``mode="first_bin"``
    (clipped into the first bin, as in the thesis) and 0 under ``"zero"``,
    which draws a step at the attachment ``b_0``. The steps extend to the
    axis edges, or to the outer breakpoints if those lie outside ``xlim``.

    Parameters
    ----------
    breakpoints : ndarray of float
        ``b_0 .. b_n``, increasing (:func:`bin_breakpoints`).
    levels : ndarray of float
        The ``n`` payout levels, one per bin.
    xlim : (float, float)
        The axis range.
    mode : {"first_bin", "zero"}
        What the step payout pays below the attachment
        (:func:`below_attachment_mode`).

    Returns
    -------
    x, y : ndarray of float
        ``n + 3`` points each: the left edge, the breakpoints and the right
        edge, with the payout from each point to the next.

    Raises
    ------
    FigureDataError
        If ``levels`` is empty or ``breakpoints`` does not have one more
        element than ``levels``.
    """
    if len(levels) == 0 or len(breakpoints) != len(levels) + 1:
        raise FigureDataError(
            f"{len(breakpoints)} breakpoints do not bound {len(levels)} levels"
        )
    left = min(xlim[0], float(breakpoints[0]))
    right = max(xlim[1], float(breakpoints[-1]))
    below = 0.0 if mode == "zero" else levels[0]
    x = np.concatenate([[left], breakpoints, [right]])
    y = np.concatenate([[below], levels, [levels[-1], levels[-1]]])
    return x, y


def _reference_lines(
    ax: Axes, attachment: float, limit: float, *, fontsize: float
) -> None:
    """Dashed attachment and limit lines with rotated labels (thesis).

    Labels sit 5 % above the bottom of the axes (thesis: at 5 % of the upper
    y limit, which leaves the axes when the y range does not start near 0).
    """
    for x, label in ((attachment, r"Attachment $x_-$"), (limit, r"Limit $x^-$")):
        ax.axvline(x=x, color="grey", linestyle="--", linewidth=1)
        ax.text(
            x,
            _LABEL_Y,
            label,
            transform=ax.get_xaxis_transform(),
            rotation=90,
            verticalalignment="bottom",
            horizontalalignment="right",
            fontsize=fontsize,
            color="black",
        )


def _figure_legend(fig: Figure, handles: list, labels: list[str], *, ncol: int) -> None:
    """Legend centred below the axes, without a frame (thesis)."""
    if not handles:
        return
    fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.0),
        ncol=max(1, ncol),
        frameon=False,
        fontsize=style.FONT.legend_size,
    )


def _draw_caption(fig: Figure) -> None:
    """Draw :data:`JOINT_CAPTION` as the figure title, wrapped to its width.

    Lines of about equal length, as few as fit the figure width. Call before
    ``tight_layout``, which leaves room for it.
    """
    size = style.FONT.subtitle_size
    fits = max(20, int(fig.get_figwidth() * 72.0 / (size * _CAPTION_CHAR_WIDTH)))
    n_lines = math.ceil(len(JOINT_CAPTION) / fits)
    fig.suptitle(
        textwrap.fill(JOINT_CAPTION, width=math.ceil(len(JOINT_CAPTION) / n_lines) + 8),
        fontsize=size,
        fontstyle="italic",
    )


def _entity_title(entity_id: str, locations: tuple[str, ...]) -> str:
    """Panel title: the entity id, plus its locations if it has several."""
    if locations == (entity_id,):
        return entity_id
    return f"{entity_id}  [{', '.join(locations)}]"


# --------------------------------------------------------------------------
# Figures
# --------------------------------------------------------------------------


def payout_grid(
    runs: Sequence[RunResult],
    *,
    events: pd.DataFrame | None = None,
    entity_ids: Sequence[str] | None = None,
    ncols: int = 3,
    panel_size: tuple[float, float] = (5.0, 4.0),
    shade_objective: str | None = "weighted_cvar",
    labels: AxisLabels | None = None,
    xlim: tuple[float, float] | None = None,
    name: str | None = None,
    joint_entities: JointEntities = "caption",
) -> FigureOutput:
    """Draw the calibrated payout functions of a scope, one panel per entity.

    Thesis ``plot_payout_functions_grid`` (view ``"vanilla"``).

    Parameters
    ----------
    runs : sequence of RunResult
        Complete runs of one scope, one per objective, in legend order.
    events : pandas.DataFrame, optional
        :func:`~parametric_insurance_design_viz.reader.entity_events` of the
        runs; drawn as a grey scatter of index against loss.
    entity_ids : sequence of str, optional
        Entities to draw, in panel order. Default: every entity, in the
        order of the first run's ``entities`` table.
    ncols : int, default 3
        Panels per row.
    panel_size : (float, float), default (5, 4)
        Width and height of one panel in inches.
    shade_objective : str or None, default "weighted_cvar"
        Objective whose payout function is shaded underneath.
    labels : AxisLabels, optional
        Axis labels (units). Default: no units.
    xlim : (float, float), optional
        Index axis range. Default: 20 % of the payout range on either side
        of attachment and limit (the thesis 10 to 80 for 20 and 70).
    name : str, optional
        Figure name. Default ``"payout_grid_<scope>"``.
    joint_entities : {"caption", "refuse"}, default "caption"
        Panels of a joint design's entities (:func:`is_joint_design`):
        draw them under :data:`JOINT_CAPTION`, or refuse them (module
        docstring, "Joint designs").

    Returns
    -------
    FigureOutput
        The figure, its steps (main table, :data:`STEP_COLUMNS`; for a
        ``"zero"`` run each entity also has its zero row below the
        attachment, see the module docstring), the ``markers`` table
        (attachment and limit), with ``events`` the ``events`` table it
        scatters and, for a joint design, the ``caption`` table
        (:data:`CAPTION_COLUMNS`).

    Raises
    ------
    IncompleteRunError
        If a run has a failed design problem.
    InconsistentRunsError
        If the runs mix scopes, repeat an objective, differ in entities,
        attachment or limit, or an entity is unknown; or a run's parameters
        and config disagree on what it pays below the attachment
        (:func:`below_attachment_mode`).
    FigureDataError
        If a run records an unknown ``below_attachment`` mode, or
        ``joint_entities`` is not a mode.
    JointEntitiesError
        Under ``joint_entities="refuse"``, if a drawn entity belongs to a
        joint design problem.
    """
    _check_joint_mode(joint_entities)
    runs = _scope_runs(runs)
    labels = labels or AxisLabels()
    attachment, limit = shared_attachment_limit(runs)
    modes: dict[str, BelowAttachment] = {
        run.run_id: below_attachment_mode(run) for run in runs
    }
    xlim = xlim or _default_xlim(attachment, limit)
    members = _membership(runs[0])
    order = runs[0].entity_order()
    if entity_ids is None:
        entity_ids = order
    unknown = [e for e in entity_ids if e not in members]
    if unknown or not entity_ids:
        raise InconsistentRunsError(
            f"entities {unknown or '(none)'} are not entities of the runs ({order})"
        )
    entity_ids = tuple(entity_ids)
    caption = _joint_caption(runs[0], entity_ids, joint_entities, figure="payout_grid")
    steps = payout_steps(runs)
    steps = _where(steps, steps["entity_id"].isin(entity_ids)).reset_index(drop=True)
    scope = runs[0].scope
    ncols = max(1, min(ncols, len(entity_ids)))
    nrows = math.ceil(len(entity_ids) / ncols)

    with style.style():
        fig, axes = plt.subplots(
            nrows=nrows,
            ncols=ncols,
            figsize=(panel_size[0] * ncols, panel_size[1] * nrows),
            squeeze=False,
        )
        for i, entity_id in enumerate(entity_ids):
            ax = axes[divmod(i, ncols)]
            aggregate = len(members[entity_id]) > 1
            rows = _entity_events(events, entity_id)
            if rows is not None:
                ax.scatter(
                    rows["index"],
                    rows["loss"],
                    alpha=_SCATTER_ALPHA,
                    color=style.EVENT_COLOR,
                    s=_SCATTER_SIZE,
                    label=(
                        "Underlying cluster event data"
                        if aggregate
                        else "Underlying event data"
                    ),
                    rasterized=True,
                )
            for run in runs:
                bins = _where(
                    steps,
                    (steps["run_id"] == run.run_id) & (steps["entity_id"] == entity_id),
                )
                x, y = step_points(
                    bin_breakpoints(bins),
                    bins["value"].to_numpy(dtype=np.float64),
                    xlim,
                    modes[run.run_id],
                )
                color = style.objective_color(run.objective)
                ax.step(
                    x,
                    y,
                    where="post",
                    color=color,
                    linewidth=2,
                    label=style.objective_label(run.objective),
                    zorder=2,
                )
                if run.objective == shade_objective:
                    ax.fill_between(
                        x,
                        y,
                        step="post",
                        color=color,
                        alpha=_SHADE_ALPHA,
                        linewidth=0,
                        zorder=1.5,
                    )
            _reference_lines(ax, attachment, limit, fontsize=10)
            ax.set_xlim(*xlim)
            ax.set_title(
                _entity_title(entity_id, members[entity_id]),
                fontsize=style.FONT.label_size,
            )
            ax.set_xlabel(labels.index(aggregate=aggregate), fontsize=_PANEL_FONT)
            ax.set_ylabel(labels.payout(), fontsize=_PANEL_FONT)
            ax.yaxis.set_major_formatter(style.MoneyFormatter())
        for j in range(len(entity_ids), nrows * ncols):
            axes[divmod(j, ncols)].set_axis_off()
        if caption is not None:
            _draw_caption(fig)
        fig.tight_layout()
        handles, legend_labels = axes[0, 0].get_legend_handles_labels()
        _figure_legend(fig, handles, legend_labels, ncol=len(handles))

    markers = pd.DataFrame(
        [
            {"entity_id": e, "marker": m, "level": None, "value": v}
            for e in entity_ids
            for m, v in (("attachment", attachment), ("limit", limit))
        ],
        columns=list(MARKER_COLUMNS),
    )
    data: dict[str, pd.DataFrame] = {
        MAIN_TABLE: with_zero_rows(steps, modes),
        "markers": markers,
    }
    if events is not None:
        data["events"] = _where(
            events, events["entity_id"].isin(entity_ids)
        ).reset_index(drop=True)
    if caption is not None:
        data["caption"] = caption
    return FigureOutput(name=name or f"payout_grid_{scope}", figure=fig, data=data)


def _normalised_levels(
    breakpoints: NDArray[np.float64],
    levels: NDArray[np.float64],
    bench_breakpoints: NDArray[np.float64],
    bench_levels: NDArray[np.float64],
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Benchmark level at each bin midpoint, and the level relative to it in %.

    The benchmark bin of a midpoint is found as in the thesis
    (``searchsorted`` on the benchmark breakpoints, clipped). Benchmark
    levels that are zero to solver precision give NaN.
    """
    mid = 0.5 * (breakpoints[:-1] + breakpoints[1:])
    k = np.searchsorted(bench_breakpoints, mid, side="right") - 1
    k = np.clip(k, 0, bench_levels.size - 1)
    bench = bench_levels[k]
    scale = float(np.max(np.abs(bench_levels))) if bench_levels.size else 0.0
    zero = np.abs(bench) <= BENCHMARK_ZERO_RTOL * scale
    with np.errstate(divide="ignore", invalid="ignore"):
        relative = np.where(zero, np.nan, levels / np.where(zero, 1.0, bench) * 100.0)
    return bench, relative


def _density(
    rows: pd.DataFrame | None,
) -> pd.DataFrame:
    """Rate-weighted Gaussian KDE of an entity's index on a grid.

    Empty if there are fewer than two distinct index values (the KDE is
    undefined there).
    """
    columns = {"index": [], "density": []}
    if rows is None:
        return pd.DataFrame(columns)
    x = rows["index"].to_numpy(dtype=np.float64)
    w = rows["rate"].to_numpy(dtype=np.float64)
    keep = np.isfinite(x) & (w > 0)
    x, w = x[keep], w[keep]
    if np.unique(x).size < 2:
        return pd.DataFrame(columns)
    kde = gaussian_kde(x, weights=w)
    grid = np.linspace(x.min(), x.max(), DENSITY_POINTS)
    return pd.DataFrame({"index": grid, "density": kde(grid)})


def normalised_payout(
    runs: Sequence[RunResult],
    entity_id: str,
    *,
    events: pd.DataFrame | None = None,
    benchmark: str = style.BENCHMARK_OBJECTIVE,
    tail_level: float | None = None,
    figsize: tuple[float, float] = (8.0, 6.0),
    labels: AxisLabels | None = None,
    xlim: tuple[float, float] | None = None,
    name: str | None = None,
    joint_entities: JointEntities = "caption",
) -> FigureOutput:
    """Draw one entity's payout per bin relative to the benchmark objective.

    Thesis ``plot_normalized_payout_functions``: each objective's level in a
    bin divided by the benchmark's level in the same bin, in percent, so the
    benchmark is the flat 100 % line. With ``events``, the entity's event
    density is drawn on a second axis and its ``tail_level`` quantile is
    marked. The ratios are drawn from the attachment to the limit only, in
    both ``below_attachment`` modes (module docstring).

    Parameters
    ----------
    runs : sequence of RunResult
        Complete runs of one scope, one per objective, including the
        benchmark; in legend order.
    entity_id : str
        The entity, e.g. ``"A1"`` or ``"C1"``.
    events : pandas.DataFrame, optional
        :func:`~parametric_insurance_design_viz.reader.entity_events` of the
        runs.
    benchmark : str, default "mse"
        Objective to normalise by (thesis: the residual loss objective).
    tail_level : float, optional
        Level of the marked index quantile. Default: the runs'
        ``evaluation_beta`` parameter (thesis ``BENCHMARK_BETA``).
    figsize : (float, float), default (8, 6)
        Figure size in inches.
    labels : AxisLabels, optional
        Axis labels (units). Default: no units.
    xlim : (float, float), optional
        Index axis range; default as :func:`payout_grid`.
    name : str, optional
        Figure name. Default ``"normalised_payout_<scope>_<entity>"``
        (lowercase).
    joint_entities : {"caption", "refuse"}, default "caption"
        If the entity belongs to a joint design problem
        (:func:`is_joint_design`): draw it under :data:`JOINT_CAPTION`, or
        refuse it (module docstring, "Joint designs").

    Returns
    -------
    FigureOutput
        The figure; its main table (:data:`STEP_COLUMNS` plus
        ``benchmark_value`` and ``relative_pct``), ``density`` (index,
        density; empty without events), ``markers`` (attachment, limit
        and, with events, the tail quantile) and, for an entity of a joint
        design, ``caption`` (:data:`CAPTION_COLUMNS`).

    Raises
    ------
    IncompleteRunError
        If a run has a failed design problem.
    InconsistentRunsError
        If the runs are inconsistent (:func:`payout_grid`), the benchmark
        objective is missing or the entity is unknown.
    FigureDataError
        If ``joint_entities`` is not a mode.
    JointEntitiesError
        Under ``joint_entities="refuse"``, if the entity belongs to a joint
        design problem.
    """
    _check_joint_mode(joint_entities)
    runs = _scope_runs(runs)
    labels = labels or AxisLabels()
    by_objective = {r.objective: r for r in runs}
    if benchmark not in by_objective:
        raise InconsistentRunsError(
            f"normalising needs a run of the benchmark objective {benchmark!r}; "
            f"got {sorted(by_objective)}"
        )
    members = _membership(runs[0])
    if entity_id not in members:
        raise InconsistentRunsError(
            f"{entity_id!r} is not an entity of the runs ({runs[0].entity_order()})"
        )
    caption = _joint_caption(
        runs[0], (entity_id,), joint_entities, figure="normalised_payout"
    )
    attachment, limit = shared_attachment_limit(runs)
    xlim = xlim or _default_xlim(attachment, limit)
    if tail_level is None:
        levels = {float(r.parameters["evaluation_beta"]) for r in runs}
        if len(levels) != 1:
            raise InconsistentRunsError(
                f"the runs differ in evaluation_beta {sorted(levels)}; pass tail_level"
            )
        tail_level = levels.pop()
    steps = payout_steps(runs)
    steps = _where(steps, steps["entity_id"] == entity_id).reset_index(drop=True)
    bench_bins = _where(steps, steps["run_id"] == by_objective[benchmark].run_id)
    bench_bp = bin_breakpoints(bench_bins)
    bench_levels = bench_bins["value"].to_numpy(dtype=np.float64)
    rows = _entity_events(events, entity_id)
    aggregate = len(members[entity_id]) > 1
    tables: list[pd.DataFrame] = []

    with style.style():
        fig, ax = plt.subplots(figsize=figsize)
        density = _density(rows)
        ax2 = ax.twinx()
        if len(density):
            ax2.fill_between(
                density["index"],
                density["density"],
                alpha=_DENSITY_ALPHA,
                color=style.EVENT_COLOR,
                label="Event density",
            )
            ax2.plot(
                density["index"],
                density["density"],
                color=style.EVENT_COLOR,
                alpha=_DENSITY_ALPHA,
                linewidth=1,
            )
        ax2.set_ylabel("Density", fontsize=style.FONT.label_size)
        ax2.set_ylim(bottom=0)
        ax2.set_zorder(ax.get_zorder() - 1)
        ax.patch.set_visible(False)

        for run in runs:
            bins = _where(steps, steps["run_id"] == run.run_id)
            bp = bin_breakpoints(bins)
            bench, relative = _normalised_levels(
                bp, bins["value"].to_numpy(dtype=np.float64), bench_bp, bench_levels
            )
            tables.append(bins.assign(benchmark_value=bench, relative_pct=relative))
            ax.step(
                bp,
                np.append(relative, relative[-1]),
                where="post",
                color=style.objective_color(run.objective),
                linewidth=1.5,
                label=style.objective_label(run.objective),
                zorder=2,
            )
        _reference_lines(ax, attachment, limit, fontsize=style.FONT.tick_size)
        marker_rows = [
            {
                "entity_id": entity_id,
                "marker": "attachment",
                "level": None,
                "value": attachment,
            },
            {"entity_id": entity_id, "marker": "limit", "level": None, "value": limit},
        ]
        if rows is not None:
            quantile = weighted_quantile(
                rows["index"].to_numpy(dtype=np.float64),
                rows["rate"].to_numpy(dtype=np.float64),
                tail_level,
            )
            marker_rows.append(
                {
                    "entity_id": entity_id,
                    "marker": "tail_quantile",
                    "level": tail_level,
                    "value": quantile,
                }
            )
            ax.axvline(x=quantile, color="black", linestyle="--", linewidth=1)
            ax.text(
                quantile,
                _LABEL_Y,
                f"{round(tail_level * 100):d}% Quantile",
                transform=ax.get_xaxis_transform(),
                rotation=90,
                verticalalignment="bottom",
                horizontalalignment="right",
                fontsize=style.FONT.tick_size,
                color="black",
            )
        ax.set_xlim(*xlim)
        ax.set_xlabel(labels.index(aggregate=aggregate))
        ax.set_ylabel(r"Payout $Y_P(x)$ relative to benchmark [%]")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
        if caption is not None:
            _draw_caption(fig)
        fig.tight_layout()
        handles, legend_labels = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        _figure_legend(fig, handles + h2, legend_labels + l2, ncol=3)

    main = pd.concat(tables, ignore_index=True)
    markers = pd.DataFrame(marker_rows, columns=list(MARKER_COLUMNS))
    scope = runs[0].scope
    data = {MAIN_TABLE: main, "density": density, "markers": markers}
    if caption is not None:
        data["caption"] = caption
    return FigureOutput(
        name=name or f"normalised_payout_{scope}_{entity_id}".lower(),
        figure=fig,
        data=data,
    )
