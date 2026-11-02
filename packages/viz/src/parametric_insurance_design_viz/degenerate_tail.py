"""Degenerate tail objectives: read the runner's flags, mark them in figures.

The runner records, in each run manifest's ``problems`` entries, three values
of every design problem on its calibration sample (core
``experiment.runner``, "Degenerate tail objectives"):

* ``p_zero_loss``: ``P(L_o = 0)``, the probability of the outcomes in which
  the design problem has no loss;
* ``tail_outcomes``: for a weighted-CVaR run, how many outcomes the CVaR tail
  holds, ``(1 - beta)`` over the smallest outcome probability;
* ``degenerate_tail``: :data:`EXPECTED_UNCOVERED` when ``beta <=
  P(L_o = 0)``. Then ``VaR_beta(U) = 0`` for every design, so the
  weighted-CVaR objective is a positive multiple of E[U], with the same
  minimisers. :data:`SINGLE_OUTCOME` when the tail holds at most one
  outcome: ``CVaR_beta(U)`` is then the worst outcome, and the objective a
  minimax over outcomes. None otherwise, and for other objectives.

This module reads them (:func:`problem_tails`, :func:`run_degenerate_tail`),
never computes them, and gives the figures and the site bundles one way to
show them:

* :func:`degenerate_tail_table`: the figure-data table
  :data:`DEGENERATE_TAIL_TABLE` (``<name>.degenerate_tail.csv``), one row per
  flagged design problem of the runs a figure reads.
  :func:`with_degenerate_tail` adds it to a figure's data only when a run is
  flagged, so the figures of unflagged runs are unchanged.
* :func:`mark_points` rings a flagged point of a line figure (the
  sensitivity and trade-off figures) with the flag's marker
  (:data:`DEGENERATE_TAIL_MARKERS`); the KPI figures mark a flagged cell, bar
  or curve with the flag's symbol (:data:`DEGENERATE_TAIL_SYMBOLS`).
* :func:`degenerate_tail_notes`: the legend note of each flag drawn
  (:data:`DEGENERATE_TAIL_NOTES`). It states the mechanism, the condition on
  the calibration years, and nothing else. When a marked result also holds
  design problems without the flag (e.g. the individual scope, where only
  some locations have ``beta <= P(L_o = 0)``), the note says so
  (:data:`PARTIAL_NOTE`).

A run whose manifest has no record (solved before the runner recorded it) has
no flag here: :func:`problem_tails` returns None for it, and the figure-data
table cannot list it. Nothing is guessed.

The flag values are those of the core runner's ``DEGENERATE_TAILS``; viz
never imports the runner (``tests/test_imports.py``), so they are repeated
here and a test checks that they agree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.legend import Legend
from matplotlib.lines import Line2D

from parametric_insurance_design_viz import style
from parametric_insurance_design_viz.errors import IncompleteRunError

if TYPE_CHECKING:
    from parametric_insurance_design_viz.reader import RunResult

__all__ = [
    "DEGENERATE_TAILS",
    "DEGENERATE_TAIL_COLOR",
    "DEGENERATE_TAIL_COLUMNS",
    "DEGENERATE_TAIL_MARKERS",
    "DEGENERATE_TAIL_NOTES",
    "DEGENERATE_TAIL_SYMBOLS",
    "DEGENERATE_TAIL_TABLE",
    "DEGENERATE_TAIL_TEXT",
    "EXPECTED_UNCOVERED",
    "PARTIAL_NOTE",
    "SINGLE_OUTCOME",
    "TAIL_KEYS",
    "ProblemTail",
    "degenerate_tail_notes",
    "degenerate_tail_table",
    "group_flag",
    "legend_handles",
    "mark_points",
    "note_legend",
    "problem_tails",
    "run_degenerate_tail",
    "with_degenerate_tail",
]

EXPECTED_UNCOVERED: Final[str] = "expected_uncovered"
"""Flag of a weighted-CVaR problem with ``beta <= P(L_o = 0)``: its
objective is a positive multiple of E[U]."""

SINGLE_OUTCOME: Final[str] = "single_outcome"
"""Flag of a weighted-CVaR problem whose CVaR tail holds at most one
outcome: its objective is a minimax over outcomes."""

DEGENERATE_TAILS: Final[tuple[str, ...]] = (EXPECTED_UNCOVERED, SINGLE_OUTCOME)
"""The flags, first the one a run with both is labelled by."""

TAIL_KEYS: Final[tuple[str, ...]] = ("p_zero_loss", "tail_outcomes", "degenerate_tail")
"""Keys of a run manifest's problem entry that hold the record."""

DEGENERATE_TAIL_TABLE: Final[str] = "degenerate_tail"
"""Figure-data key of :func:`degenerate_tail_table`
(``<name>.degenerate_tail.csv``)."""

DEGENERATE_TAIL_COLUMNS: Final[tuple[str, ...]] = (
    "run_id",
    "scope",
    "objective",
    "problem_id",
    "beta",
    "p_zero_loss",
    "tail_outcomes",
    "degenerate_tail",
)
"""Columns of :func:`degenerate_tail_table`. ``beta`` is the objective's
``beta`` (the CVaR level of the design, not the evaluation ``beta``)."""

DEGENERATE_TAIL_NOTES: Final[Mapping[str, str]] = {
    EXPECTED_UNCOVERED: (
        r"Weighted CVaR equals E[U] at the design's $\beta$, because "
        r"$\beta \leq P(L_o = 0)$ on the calibration years"
    ),
    SINGLE_OUTCOME: (
        r"Weighted CVaR is the worst outcome at the design's $\beta$: its "
        "tail holds at most one outcome of the calibration years"
    ),
}
"""Legend note of each flag in figures (matplotlib mathtext). The ``beta``
is the design's CVaR level, not the evaluation ``beta`` of the KPIs."""

DEGENERATE_TAIL_TEXT: Final[Mapping[str, str]] = {
    EXPECTED_UNCOVERED: (
        "Weighted CVaR equals E[U] at the design's β, because β ≤ P(L_o = 0) "
        "on the calibration years: VaR_β of the uncovered loss is 0 for every "
        "design, so the objective is a positive multiple of E[U], with the "
        "same minimisers."
    ),
    SINGLE_OUTCOME: (
        "Weighted CVaR is the worst outcome at the design's β: 1 - β is at "
        "most the "
        "probability of every outcome of the calibration years, so the CVaR "
        "tail holds at most one outcome and the objective is a minimax over "
        "outcomes."
    ),
}
"""Plain-text statement of each flag, for the site bundles."""

PARTIAL_NOTE: Final[str] = " (in some of its design problems)"
"""Appended to a note when a marked result also holds design problems
without the flag."""

DEGENERATE_TAIL_MARKERS: Final[Mapping[str, str]] = {
    EXPECTED_UNCOVERED: "o",
    SINGLE_OUTCOME: "D",
}
"""Ring marker of each flag around a flagged point (:func:`mark_points`)."""

DEGENERATE_TAIL_SYMBOLS: Final[Mapping[str, str]] = {
    EXPECTED_UNCOVERED: "\N{DAGGER}",
    SINGLE_OUTCOME: "\N{DOUBLE DAGGER}",
}
"""Symbol of each flag next to a flagged cell, bar or curve label."""

DEGENERATE_TAIL_COLOR: Final[str] = "black"
"""Edge colour of the rings and hatches."""

_RING_SIZE: Final[float] = 13.0
_RING_WIDTH: Final[float] = 1.2


@dataclass(frozen=True)
class ProblemTail:
    """The degenerate-tail record of one design problem (run manifest).

    Parameters
    ----------
    problem_id : str
        The design problem.
    p_zero_loss : float or None
        ``P(L_o = 0)`` on its calibration sample; None for a failed build.
    tail_outcomes : float or None
        Outcomes in the CVaR tail; None for other objectives.
    degenerate_tail : str or None
        One of :data:`DEGENERATE_TAILS`, or None.
    """

    problem_id: str
    p_zero_loss: float | None
    tail_outcomes: float | None
    degenerate_tail: str | None


def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)  # pyright: ignore[reportArgumentType]


def problem_tails(run: RunResult) -> tuple[ProblemTail, ...] | None:
    """Return the degenerate-tail record of every design problem of a run.

    Parameters
    ----------
    run : RunResult
        The run.

    Returns
    -------
    tuple of ProblemTail or None
        One per problem entry of the manifest, in its order; None if an
        entry has no record (a run solved before the runner recorded it).

    Raises
    ------
    IncompleteRunError
        If a flag is not one of :data:`DEGENERATE_TAILS`.
    """
    entries = run.manifest.get("problems", [])
    if any(not all(k in p for k in TAIL_KEYS) for p in entries):
        return None
    tails: list[ProblemTail] = []
    for p in entries:
        flag = p["degenerate_tail"]
        if flag is not None and flag not in DEGENERATE_TAILS:
            raise IncompleteRunError(
                f"run {run.run_id}, problem {p['problem_id']}: unknown "
                f"degenerate_tail {flag!r}; expected one of {list(DEGENERATE_TAILS)}"
            )
        tails.append(
            ProblemTail(
                problem_id=str(p["problem_id"]),
                p_zero_loss=_optional_float(p["p_zero_loss"]),
                tail_outcomes=_optional_float(p["tail_outcomes"]),
                degenerate_tail=None if flag is None else str(flag),
            )
        )
    return tuple(tails)


def _strongest(flags: Iterable[str | None]) -> str | None:
    """Return the first of :data:`DEGENERATE_TAILS` among ``flags``, or None."""
    present = set(flags)
    return next((f for f in DEGENERATE_TAILS if f in present), None)


def run_degenerate_tail(run: RunResult) -> str | None:
    """Return the flag of a run: that of its design problems, or None.

    A run with problems of both flags is :data:`EXPECTED_UNCOVERED`; a run
    without a record (:func:`problem_tails` is None) has None.

    Parameters
    ----------
    run : RunResult
        The run.

    Returns
    -------
    str or None
        One of :data:`DEGENERATE_TAILS`, or None.
    """
    tails = problem_tails(run)
    if tails is None:
        return None
    return _strongest(t.degenerate_tail for t in tails)


def _beta(run: RunResult) -> float | None:
    value: Any = run.parameters.get("beta")
    return None if value is None else float(value)


def degenerate_tail_table(runs: Iterable[RunResult]) -> pd.DataFrame:
    """Return the flagged design problems of some runs.

    Parameters
    ----------
    runs : iterable of RunResult
        The runs a figure reads; a repeated run is listed once.

    Returns
    -------
    pandas.DataFrame
        Columns :data:`DEGENERATE_TAIL_COLUMNS`, one row per flagged design
        problem, in run then manifest order; empty if none is flagged.
    """
    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for run in runs:
        if run.run_id in seen:
            continue
        seen.add(run.run_id)
        for tail in problem_tails(run) or ():
            if tail.degenerate_tail is None:
                continue
            rows.append(
                {
                    "run_id": run.run_id,
                    "scope": run.scope,
                    "objective": run.objective,
                    "problem_id": tail.problem_id,
                    "beta": _beta(run),
                    "p_zero_loss": tail.p_zero_loss,
                    "tail_outcomes": tail.tail_outcomes,
                    "degenerate_tail": tail.degenerate_tail,
                }
            )
    return pd.DataFrame(rows, columns=list(DEGENERATE_TAIL_COLUMNS))


def with_degenerate_tail(
    data: Mapping[str, pd.DataFrame], runs: Iterable[RunResult]
) -> dict[str, pd.DataFrame]:
    """Add :data:`DEGENERATE_TAIL_TABLE` to figure data if a run is flagged.

    Parameters
    ----------
    data : mapping of str to pandas.DataFrame
        The figure's tables.
    runs : iterable of RunResult
        The runs the figure reads.

    Returns
    -------
    dict
        ``data``, plus the table when it is not empty.
    """
    out = dict(data)
    table = degenerate_tail_table(runs)
    if not table.empty:
        out[DEGENERATE_TAIL_TABLE] = table
    return out


def degenerate_tail_notes(groups: Iterable[Sequence[RunResult]]) -> dict[str, str]:
    """Return the legend note of each flag among some marked results.

    Parameters
    ----------
    groups : iterable of sequence of RunResult
        The runs behind each marked result (one run per point, cell or bar;
        several for a mean over runs or over folds).

    Returns
    -------
    dict
        Flag to note (:data:`DEGENERATE_TAIL_NOTES`), in
        :data:`DEGENERATE_TAILS` order, for the flags of the groups. A note
        ends with :data:`PARTIAL_NOTE` when a group marked with the flag
        holds a design problem, or a run, without it.
    """
    partial: dict[str, bool] = {}
    for group in groups:
        records = [problem_tails(r) for r in group]
        flag = _strongest(t.degenerate_tail for tails in records for t in tails or ())
        if flag is None:
            continue
        every = all(
            tails is not None and all(t.degenerate_tail == flag for t in tails)
            for tails in records
        )
        partial[flag] = partial.get(flag, False) or not every
    return {
        flag: DEGENERATE_TAIL_NOTES[flag] + (PARTIAL_NOTE if partial[flag] else "")
        for flag in DEGENERATE_TAILS
        if flag in partial
    }


def group_flag(group: Sequence[RunResult]) -> str | None:
    """Return the flag that marks a result read from ``group``'s runs."""
    return _strongest(run_degenerate_tail(r) for r in group)


def mark_points(
    ax: Axes,
    xs: Sequence[float],
    ys: Sequence[float],
    flags: Sequence[str | None],
) -> None:
    """Ring each flagged point with its flag's marker.

    Parameters
    ----------
    ax : matplotlib.axes.Axes
        The axes.
    xs, ys : sequence of float
        The points.
    flags : sequence of str or None
        The flag of each point (None: not flagged, not ringed).
    """
    for flag in DEGENERATE_TAILS:
        chosen = [i for i, f in enumerate(flags) if f == flag]
        if not chosen:
            continue
        ax.plot(
            [xs[i] for i in chosen],
            [ys[i] for i in chosen],
            linestyle="none",
            marker=DEGENERATE_TAIL_MARKERS[flag],
            markersize=_RING_SIZE,
            markerfacecolor="none",
            markeredgecolor=DEGENERATE_TAIL_COLOR,
            markeredgewidth=_RING_WIDTH,
            zorder=5,
        )


def legend_handles(notes: Mapping[str, str]) -> tuple[list[Line2D], list[str]]:
    """Return the ring handles and labels of the notes of :func:`mark_points`."""
    handles = [
        Line2D(
            [0],
            [0],
            linestyle="none",
            marker=DEGENERATE_TAIL_MARKERS[flag],
            markersize=_RING_SIZE * 0.7,
            markerfacecolor="none",
            markeredgecolor=DEGENERATE_TAIL_COLOR,
            markeredgewidth=_RING_WIDTH,
        )
        for flag in notes
    ]
    return handles, list(notes.values())


def note_legend(
    fig: Figure,
    notes: Mapping[str, str],
    *,
    symbols: bool = False,
    below: Legend | None = None,
) -> Legend | None:
    """Draw the notes as a one-column legend centred under the figure.

    Parameters
    ----------
    fig : matplotlib.figure.Figure
        The figure.
    notes : mapping of str to str
        :func:`degenerate_tail_notes`.
    symbols : bool, default False
        Start each note with its flag's symbol (:data:`DEGENERATE_TAIL_SYMBOLS`,
        the KPI figures) instead of the ring of :func:`mark_points`.
    below : matplotlib.legend.Legend, optional
        A legend under the figure to draw the notes beneath; default at the
        bottom edge of the figure.

    Returns
    -------
    matplotlib.legend.Legend or None
        The legend; None, and nothing drawn, without notes.
    """
    if not notes:
        return None
    y = 0.0
    if below is not None:
        fig.draw_without_rendering()
        box = below.get_window_extent()
        y = float(fig.transFigure.inverted().transform((0.0, box.y0))[1])
    if symbols:
        handles: list[Line2D] = [Line2D([], [], linestyle="none") for _ in notes]
        labels = [f"{DEGENERATE_TAIL_SYMBOLS[f]} {n}" for f, n in notes.items()]
        spacing: dict[str, float] = {"handlelength": 0.0, "handletextpad": 0.0}
    else:
        handles, labels = legend_handles(notes)
        spacing = {}
    return fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, y),
        ncol=1,
        frameon=False,
        fontsize=style.FONT.legend_size - 2,
        **spacing,
    )
