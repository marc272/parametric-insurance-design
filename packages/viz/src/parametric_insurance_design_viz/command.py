"""The figure set of a config: what ``parametric-insurance-design figures`` draws.

Owner: MAR-110. The core command ``parametric-insurance-design figures
CONFIG`` (``parametric_insurance_design.cli``) imports this module lazily,
works out the ``run_id`` of every single run of the config, of every point
of its sweeps (:class:`SweepRun`, MAR-112) and its prepared EventSet, and
calls :func:`write_figures`. Everything here reads the result store; nothing
solves.

Figure sets
-----------
:data:`FIGURE_SETS` lists the figure builders, in order. Each takes the
:class:`FigureContext` and returns figures and skipped figures. MAR-110
registers the payout figures; MAR-21's later sub-issues (MAR-111, MAR-112)
append their builders to the tuple (append-only, ADR 0002 §10). MAR-112
appends :func:`~parametric_insurance_design_viz.sweep_figures.sweep_figures`
(sweep plots, premium reallocation, tail-vs-total trade-off, cluster net
advantage and break-even; see that module for its figure names).

=======================================  ====================================
Figure                                   Thesis
=======================================  ====================================
``payout_grid_<scope>``                  Figures 5.1 (individual), 5.3
                                         (portfolio), 5.4 (cluster)
``normalised_payout_<scope>_<entity>``   Figure 5.2 (individual, A1), A.1
                                         (portfolio, A1), A.2 (cluster, C1)
``kpi_heatmap_<kpi>``                    Notebook heatmaps (MAR-111)
``performance_overview``                 Figure 5.5 (MAR-111)
``exceedance_<scope>``                   Figure 5.6 (portfolio; MAR-111)
=======================================  ====================================

``<scope>`` is the scope name, with ``_2``, ``_3``, ... appended when a
config lists several scopes of one kind. The normalised figure is drawn for
the first entity of each scope, and only if the config has the benchmark
objective (``mse``).

No silent failures
------------------
* A run that is not in the store raises
  :class:`~parametric_insurance_design_viz.errors.MissingRunError` before
  anything is drawn. That includes every sweep point passed in ``sweeps``:
  the message names the missing points.
* A scope with a failed run draws none of its figures; each is reported as a
  :class:`SkippedFigure` with ``failed=True``, and the command exits with
  status 1.
* A figure that does not apply (no benchmark objective) is reported as a
  :class:`SkippedFigure` with ``failed=False``.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import ExperimentConfig
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design_viz import style
from parametric_insurance_design_viz.errors import (
    InconsistentRunsError,
    MissingRunError,
)
from parametric_insurance_design_viz.figure_data import (
    DEFAULT_DPI,
    FigureOutput,
    WrittenFigure,
    write_figure,
)
from parametric_insurance_design_viz.kpi_figures import kpi_figures
from parametric_insurance_design_viz.payout_functions import (
    AxisLabels,
    normalised_payout,
    payout_grid,
)
from parametric_insurance_design_viz.reader import (
    ResultReader,
    RunResult,
    check_eventset,
    entity_events,
)
from parametric_insurance_design_viz.sweep_figures import sweep_figures

__all__ = [
    "FIGURE_SETS",
    "FigureContext",
    "FigureReport",
    "FigureSet",
    "ScopeRuns",
    "SkippedFigure",
    "SweepRun",
    "payout_figures",
    "write_figures",
]

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SkippedFigure:
    """A figure of the set that was not drawn.

    Parameters
    ----------
    name : str
        The figure's name.
    reason : str
        Why it was not drawn.
    failed : bool
        True if a run it needs failed; False if it does not apply.
    """

    name: str
    reason: str
    failed: bool


@dataclass(frozen=True, eq=False)
class ScopeRuns:
    """The runs of one configured scope, one per objective.

    Parameters
    ----------
    key : str
        Figure-name stem of the scope, e.g. ``"individual"`` or
        ``"cluster_2"``.
    runs : tuple of RunResult
        One per configured objective, in config order.
    events : pandas.DataFrame or None
        :func:`~parametric_insurance_design_viz.reader.entity_events` of the
        scope; None without an EventSet or when a run failed.
    """

    key: str
    runs: tuple[RunResult, ...]
    events: pd.DataFrame | None

    @property
    def failed(self) -> tuple[RunResult, ...]:
        """Runs with a failed design problem."""
        return tuple(r for r in self.runs if not r.complete)

    def failure_reason(self) -> str:
        """Describe the failed runs of the scope."""
        return "; ".join(
            f"run {r.run_id} ({r.scope} x {r.objective}) failed for "
            f"{', '.join(r.failed_problems)}"
            for r in self.failed
        )


@dataclass(frozen=True)
class SweepRun:
    """One point of a configured sweep: which run holds it (MAR-112).

    The ``figures`` command computes these from the config's sweeps
    (``experiment.sweeps.sweep_points`` and ``runner.run_key``, as the dry
    run of ``sweep`` does); viz never imports the sweeps module.

    Parameters
    ----------
    parameter : str
        The swept parameter, e.g. ``"alpha"``.
    value : int or float
        Its value at this point; for ``n_assets`` the subset size.
    run_id : str
        The point's run.
    single : int
        Position in ``config.single_runs()`` of the baseline run the point
        varies (its scope x objective).
    subset_index : int or None, default None
        ``n_assets`` only: the subset's position among the subsets of its
        size.
    location_ids : tuple of str or None, default None
        ``n_assets`` only: the subset.
    """

    parameter: str
    value: int | float
    run_id: str
    single: int
    subset_index: int | None = None
    location_ids: tuple[str, ...] | None = None


@dataclass(frozen=True, eq=False)
class FigureContext:
    """Everything a figure set reads.

    Parameters
    ----------
    config : ExperimentConfig
        The experiment config.
    reader : ResultReader
        The result store.
    scopes : tuple of ScopeRuns
        The single runs, grouped by configured scope, in config order.
    labels : AxisLabels
        Axis labels with the EventSet's units.
    sweeps : tuple of SweepRun, default ()
        Every point of the config's sweeps, in config order (MAR-112). The
        runs are in the store (checked by :func:`write_figures`) but not
        read yet; figure sets read the ones they draw.
    eventset : EventSet or None, default None
        The runs' prepared EventSet, e.g. for location values (MAR-112).
    """

    config: ExperimentConfig
    reader: ResultReader
    scopes: tuple[ScopeRuns, ...]
    labels: AxisLabels
    sweeps: tuple[SweepRun, ...] = ()
    eventset: EventSet | None = None

    def scope_of(self, single: int) -> tuple[ScopeRuns, RunResult]:
        """Return the scope and the run of a single run, by its position.

        Parameters
        ----------
        single : int
            Position in ``config.single_runs()``.

        Returns
        -------
        tuple
            ``(scope runs, run)``.

        Raises
        ------
        InconsistentRunsError
            If there is no single run at that position.
        """
        n_objectives = len(self.config.objectives)
        scope, objective = divmod(single, n_objectives)
        if not 0 <= single < len(self.scopes) * n_objectives:
            raise InconsistentRunsError(
                f"config {self.config.name!r} has no single run {single}"
            )
        runs = self.scopes[scope]
        return runs, runs.runs[objective]


FigureSet = Callable[[FigureContext], Iterable[FigureOutput | SkippedFigure]]
"""A figure builder: the figures (or skipped figures) of a context.

A list, or a generator that draws one figure at a time (MAR-112), so each
is written and closed before the next is drawn."""


@dataclass(frozen=True)
class FigureReport:
    """What :func:`write_figures` wrote and skipped.

    Parameters
    ----------
    out_dir : pathlib.Path
        The output directory.
    written : tuple of WrittenFigure
        Figures written, in order.
    skipped : tuple of SkippedFigure
        Figures not drawn, in order.
    """

    out_dir: Path
    written: tuple[WrittenFigure, ...]
    skipped: tuple[SkippedFigure, ...]

    @property
    def ok(self) -> bool:
        """True if no figure was skipped because a run failed."""
        return not any(s.failed for s in self.skipped)


def payout_figures(context: FigureContext) -> list[FigureOutput | SkippedFigure]:
    """Payout grid and normalised payout figure of every configured scope.

    Parameters
    ----------
    context : FigureContext
        The config's runs.

    Returns
    -------
    list
        Per scope: ``payout_grid_<key>``, then
        ``normalised_payout_<key>_<first entity>`` (or skipped figures).
    """
    out: list[FigureOutput | SkippedFigure] = []
    benchmark = style.BENCHMARK_OBJECTIVE
    for scope in context.scopes:
        grid = f"payout_grid_{scope.key}"
        normalised = f"normalised_payout_{scope.key}"
        if scope.failed:
            reason = scope.failure_reason()
            out.append(SkippedFigure(grid, reason, failed=True))
            out.append(SkippedFigure(normalised, reason, failed=True))
            continue
        out.append(
            payout_grid(
                scope.runs, events=scope.events, labels=context.labels, name=grid
            )
        )
        if benchmark not in {r.objective for r in scope.runs}:
            out.append(
                SkippedFigure(
                    normalised,
                    f"the config has no {benchmark!r} objective to normalise by",
                    failed=False,
                )
            )
            continue
        entity = scope.runs[0].entity_order()[0]
        out.append(
            normalised_payout(
                scope.runs,
                entity,
                events=scope.events,
                labels=context.labels,
                name=f"{normalised}_{entity}".lower(),
            )
        )
    return out


FIGURE_SETS: Final[tuple[FigureSet, ...]] = (
    payout_figures,
    kpi_figures,
    sweep_figures,
)
"""Figure builders of the ``figures`` command, in order (append-only)."""


def _scope_keys(config: ExperimentConfig) -> list[str]:
    """Figure-name stem per configured scope: its kind, numbered on repeats."""
    kinds = [s.kind for s in config.scopes]
    total = Counter(kinds)
    seen: Counter[str] = Counter()
    keys: list[str] = []
    for kind in kinds:
        seen[kind] += 1
        keys.append(
            kind if total[kind] == 1 or seen[kind] == 1 else f"{kind}_{seen[kind]}"
        )
    return keys


def _labels(eventset: EventSet | None) -> AxisLabels:
    """Axis labels with the EventSet's index and loss units."""
    if eventset is None:
        return AxisLabels()
    metadata = eventset.metadata
    return AxisLabels(index_unit=metadata.index.unit, payout_unit=metadata.loss.unit)


def _check_sweeps(
    config: ExperimentConfig, reader: ResultReader, sweeps: Sequence[SweepRun]
) -> None:
    """Check that every sweep point names a single run and is in the store.

    Raises
    ------
    InconsistentRunsError
        If a point's ``single`` is not a position in ``config.single_runs()``.
    MissingRunError
        If points are not in the store; the message counts them per sweep
        and names the first few.
    """
    n_singles = len(config.single_runs())
    bad = [p for p in sweeps if not 0 <= p.single < n_singles]
    if bad:
        raise InconsistentRunsError(
            f"config {config.name!r} has {n_singles} single runs; sweep points "
            f"name single runs {sorted({p.single for p in bad})}"
        )
    missing = [p for p in sweeps if not reader.store.has_run(p.run_id)]
    if not missing:
        return
    per_sweep = Counter(p.parameter for p in missing)
    totals = Counter(p.parameter for p in sweeps)
    counts = ", ".join(f"{k} {n}/{totals[k]}" for k, n in per_sweep.items())
    examples = "; ".join(
        f"{p.parameter}={p.value!r} (single run {p.single}) {p.run_id}"
        for p in missing[:5]
    )
    raise MissingRunError(
        f"{len(missing)} of {len(sweeps)} sweep points are not in the result "
        f"store {reader.store.root} ({counts}), e.g. {examples}; figures read "
        "the store and never re-run an optimisation, so run the sweeps first "
        "(parametric-insurance-design sweep CONFIG)"
    )


def write_figures(
    config: ExperimentConfig,
    run_ids: Sequence[str],
    *,
    store: ResultStore,
    out_dir: str | Path,
    eventset: EventSet | None = None,
    sweeps: Sequence[SweepRun] = (),
    figure_sets: Sequence[FigureSet] = FIGURE_SETS,
    dpi: int = DEFAULT_DPI,
) -> FigureReport:
    """Draw the figure set of a config from its result store.

    Parameters
    ----------
    config : ExperimentConfig
        The experiment config.
    run_ids : sequence of str
        The ``run_id`` of each of ``config.single_runs()``, in that order.
    store : ResultStore
        The result store holding the runs.
    out_dir : str or pathlib.Path
        Where to write the images and their figure-data CSVs.
    eventset : EventSet, optional
        The prepared EventSet of the runs (location subset, noise and
        threshold applied), for the event overlays. It must match every
        run's manifest. Without it the figures show no event data.
    sweeps : sequence of SweepRun, default ()
        Every point of the config's sweeps (MAR-112), for the sweep figures.
        Each must be in the store.
    figure_sets : sequence of FigureSet, default :data:`FIGURE_SETS`
        Figure builders to run.
    dpi : int, default :data:`~.figure_data.DEFAULT_DPI`
        Image resolution.

    Returns
    -------
    FigureReport
        Figures written and skipped.

    Raises
    ------
    InconsistentRunsError
        If ``run_ids`` does not match the config's single runs, or a sweep
        point names no single run of the config.
    MissingRunError
        If a run, or a sweep point's run, is not in the store.
    EventSetMismatchError
        If ``eventset`` is not the runs' prepared EventSet.
    """
    singles = config.single_runs()
    ids = tuple(run_ids)
    if len(ids) != len(singles):
        raise InconsistentRunsError(
            f"config {config.name!r} has {len(singles)} single runs, got "
            f"{len(ids)} run ids"
        )
    reader = ResultReader(store)
    results = reader.runs(ids)
    points = tuple(sweeps)
    _check_sweeps(config, reader, points)
    n_objectives = len(config.objectives)
    eventset_hash = eventset.content_hash() if eventset is not None else None
    scopes: list[ScopeRuns] = []
    for i, (key, scope_config) in enumerate(
        zip(_scope_keys(config), config.scopes, strict=True)
    ):
        runs = results[i * n_objectives : (i + 1) * n_objectives]
        events = None
        if eventset is not None and eventset_hash is not None:
            for run in runs:
                check_eventset(run, eventset_hash)
            if all(r.complete for r in runs):
                events = entity_events(
                    eventset, scope_config.build(), runs[0].problem_specs()
                )
        scopes.append(ScopeRuns(key=key, runs=runs, events=events))
    context = FigureContext(
        config=config,
        reader=reader,
        scopes=tuple(scopes),
        labels=_labels(eventset),
        sweeps=points,
        eventset=eventset,
    )
    directory = Path(out_dir)
    written: list[WrittenFigure] = []
    skipped: list[SkippedFigure] = []
    for figure_set in figure_sets:
        for item in figure_set(context):
            if isinstance(item, SkippedFigure):
                level = logging.WARNING if item.failed else logging.INFO
                _log.log(level, "figure %s skipped: %s", item.name, item.reason)
                skipped.append(item)
                continue
            files = write_figure(item, directory, dpi=dpi)
            _log.info("figure %s written to %s", item.name, files.image)
            written.append(files)
    return FigureReport(
        out_dir=directory, written=tuple(written), skipped=tuple(skipped)
    )
