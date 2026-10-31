"""Command-line interface ``parametric-insurance-design`` (SPEC §4.2).

Owner: MAR-66. A thin front end over
:mod:`~parametric_insurance_design.experiment.runner` and
:mod:`~parametric_insurance_design.experiment.sweeps`. It parses arguments,
sets up logging, calls the library and turns the outcome into a summary and
an exit code. Every decision about what runs, what is cached and what is
written stays in the library. Later commands (``export-site``) register
here as further subcommands.

Commands
--------
``parametric-insurance-design run CONFIG``
    Run every scope x objective of the config
    (:func:`~parametric_insurance_design.experiment.runner.run_config`). The
    config's ``sweeps`` are ignored.
``parametric-insurance-design sweep CONFIG``
    Run the config's baseline runs, then its sweeps
    (:func:`~parametric_insurance_design.experiment.sweeps.run_sweeps`).
    ``--parameter P`` (repeatable) runs only the sweeps of those parameters,
    ``--no-baseline`` skips the baseline runs, ``--jobs N`` runs them in
    ``N`` worker processes (default 1; same store contents, MAR-105). A
    worker process that dies is an error (exit code 3).
``parametric-insurance-design figures CONFIG [--out DIR]``
    Draw the config's figures from its result store (MAR-110), with their
    figure-data CSVs, into ``DIR`` (default ``<output.directory>/figures``).
    It reads the EventSet to compute every ``run_id`` and the prepared
    EventSet of the event overlays, and never solves: a run missing from the
    store is an error. ``--skip-missing-sweeps`` (MAR-120) draws the figures
    before every sweep has run: the sweep figures whose points are missing
    are skipped and listed as ``MISSING`` (exit code 1); the single runs
    must still be in the store. ``--transaction-costs TAU,...`` sets the
    costs per contract of the cluster net-advantage figure (default: the
    thesis' 25000,50000,75000,100000,125000). For a k-fold config (MAR-151)
    it first computes the pooled out-of-sample portfolio KPIs from the store
    (:func:`~parametric_insurance_design.experiment.kfold.pooled_kpis`, with
    its drift guard; nothing is solved), passes them as ``pooled_kpis=``,
    reads no sweep points and prints a ``pooled k-fold KPIs`` line (and a
    ``not pooled`` line per scope x objective with a failed fold). The
    figures live in the
    optional package ``parametric-insurance-design-viz``, imported only by
    this command; if it is not installed, the command fails with
    :class:`VizNotInstalledError` (exit code 3). Accepts ``--policy``, ``-v``
    and ``-q``.

Common options of ``run`` and ``sweep``:

``--dry-run``
    Read the config and the EventSet (to compute the input checksum and so
    the ``run_id`` of every run), then print the plan: every run or sweep
    point and whether it would run or is a cache hit. Writes nothing.
``--force``
    Re-execute and overwrite every run, cached or not.
``--retry-failed``
    Re-execute cached runs that have a failed design problem.
``--policy {default,thesis}``
    Solver policy: ``default`` is
    :data:`~parametric_insurance_design.solve.DEFAULT_POLICY`; ``thesis`` is
    :data:`~parametric_insurance_design.solve.THESIS_POLICY` and is for the
    parity gate only (MAR-98). The policy is part of every ``run_id``.
``-v`` / ``-q``
    Logging level on stderr: ``INFO`` by default (one line per run and per
    sweep), ``DEBUG`` with ``-v`` (one line per sweep point), ``WARNING``
    with ``-q``.

The summary goes to stdout, the log to stderr.

Exit codes
----------
====  =====================================================================
Code  Meaning
====  =====================================================================
0     Every run succeeded (or the dry-run plan was printed).
1     The command completed, but at least one run has a failed design
      problem or was not evaluated. The failures are recorded in the store
      and listed in the summary. For ``figures``: a figure was skipped
      because a run it needs failed or, with ``--skip-missing-sweeps``,
      because sweep points it needs are not in the store.
2     Usage error (bad arguments).
3     The library refused the input: an invalid config, an EventSet that
      cannot be read or does not match its checksum, or a result-store
      problem. Nothing is written for the run that raised. For ``figures``
      also: a run missing from the store (a sweep point too, unless
      ``--skip-missing-sweeps``), or the viz package not installed.
4     Internal error (an unexpected exception, i.e. a bug). The traceback is
      logged.
130   Interrupted (Ctrl-C).
====  =====================================================================
"""

from __future__ import annotations

import argparse
import importlib
import logging
import math
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from importlib.metadata import version
from pathlib import Path
from types import ModuleType
from typing import Final

from parametric_insurance_design.errors import (
    ConfigError,
    ParametricInsuranceDesignError,
)
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    SweepConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.kfold import (
    KFOLD_SAMPLE,
    PooledKpis,
    pooled_kpis,
)
from parametric_insurance_design.experiment.runner import (
    PACKAGE,
    RunInput,
    RunOutcome,
    load_input,
    prepare_eventset,
    run_config,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.experiment.sweeps import (
    SWEEP_SOURCES,
    SweepPoint,
    SweepsOutcome,
    run_sweeps,
    sweep_points,
)
from parametric_insurance_design.solve import (
    DEFAULT_POLICY,
    THESIS_POLICY,
    SolverPolicy,
)

__all__ = [
    "POLICIES",
    "VIZ_DISTRIBUTION",
    "VIZ_MODULE",
    "ExitCode",
    "VizNotInstalledError",
    "build_parser",
    "main",
]

_log = logging.getLogger(__name__)

PROG: Final[str] = "parametric-insurance-design"
"""Name of the command (the console-script entry point)."""

POLICIES: Final[dict[str, SolverPolicy]] = {
    "default": DEFAULT_POLICY,
    "thesis": THESIS_POLICY,
}
"""Solver policies selectable with ``--policy``."""

_LOGGER = "parametric_insurance_design"
_LOG_FORMAT = "%(levelname)s %(name)s: %(message)s"

VIZ_DISTRIBUTION: Final[str] = "parametric-insurance-design-viz"
"""Distribution that holds the figures; never a core dependency."""

VIZ_MODULE: Final[str] = "parametric_insurance_design_viz.command"
"""Module imported lazily by ``figures``; it provides ``write_figures``."""

_VIZ_PACKAGE: Final[str] = VIZ_MODULE.split(".", maxsplit=1)[0]


class VizNotInstalledError(ParametricInsuranceDesignError, ImportError):
    """``figures`` needs the viz package, which cannot be imported.

    The core never depends on the viz package (that would pull matplotlib
    into every install), so the ``figures`` command imports it only when it
    runs (:data:`VIZ_MODULE`).
    """


class ExitCode(IntEnum):
    """Exit codes of the command (module docstring)."""

    OK = 0
    RUNS_FAILED = 1
    USAGE = 2
    INPUT_ERROR = 3
    INTERNAL_ERROR = 4
    INTERRUPTED = 130


# --------------------------------------------------------------------------
# Arguments
# --------------------------------------------------------------------------


def _add_common(parser: argparse.ArgumentParser) -> None:
    """Add the arguments that ``run`` and ``sweep`` share."""
    parser.add_argument("config", type=Path, help="experiment config (YAML)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the plan and the cache hits; run and write nothing",
    )
    redo = parser.add_mutually_exclusive_group()
    redo.add_argument(
        "--force",
        action="store_true",
        help="re-execute and overwrite every run, even if cached",
    )
    redo.add_argument(
        "--retry-failed",
        action="store_true",
        help="re-execute cached runs that have a failure",
    )
    parser.add_argument(
        "--policy",
        choices=tuple(POLICIES),
        default="default",
        help=(
            "solver policy (default: %(default)s); 'thesis' reproduces the "
            "thesis solves and is for the parity gate only"
        ),
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="log every sweep point (DEBUG)",
    )
    verbosity.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="log warnings and errors only",
    )


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser of the command.

    Returns
    -------
    argparse.ArgumentParser
        With the subcommands ``run``, ``sweep`` and ``figures``.
    """
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Design parametric insurance payouts: run experiments and sweeps "
            "from a config file into a result store."
        ),
    )
    parser.add_argument("--version", action="version", version=_version())
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = commands.add_parser(
        "run",
        help="run every scope x objective of a config",
        description=(
            "Run every scope x objective of a config into its result store "
            "(output.directory). The config's sweeps are ignored."
        ),
    )
    _add_common(run)
    run.set_defaults(handler=_run)

    sweep = commands.add_parser(
        "sweep",
        help="run a config's baseline runs and its one-factor-at-a-time sweeps",
        description=(
            "Run a config's baseline runs (scope x objective), then its "
            "one-factor-at-a-time sweeps, into its result store."
        ),
    )
    _add_common(sweep)
    sweep.add_argument(
        "-p",
        "--parameter",
        action="append",
        choices=tuple(SWEEP_SOURCES),
        metavar="PARAMETER",
        help=(
            "run only the sweep of this parameter (repeatable; default: every "
            f"sweep of the config). One of: {', '.join(SWEEP_SOURCES)}"
        ),
    )
    sweep.add_argument(
        "--no-baseline",
        dest="baseline",
        action="store_false",
        help="skip the baseline runs",
    )
    sweep.add_argument(
        "-j",
        "--jobs",
        type=_positive_int,
        default=1,
        metavar="N",
        help="run in N worker processes (default: %(default)s, serial)",
    )
    sweep.set_defaults(handler=_sweep)

    figures = commands.add_parser(
        "figures",
        help="draw a config's figures from its result store",
        description=(
            "Draw a config's figures, with their figure-data CSVs, from its "
            "result store (output.directory). Never solves: run the config "
            f"first. Needs the {VIZ_DISTRIBUTION} package."
        ),
    )
    figures.add_argument("config", type=Path, help="experiment config (YAML)")
    figures.add_argument(
        "--out",
        type=Path,
        default=None,
        metavar="DIR",
        help="output directory (default: <output.directory>/figures)",
    )
    figures.add_argument(
        "--policy",
        choices=tuple(POLICIES),
        default="default",
        help="solver policy the runs were computed with (default: %(default)s)",
    )
    figures.add_argument(
        "--skip-missing-sweeps",
        action="store_true",
        help=(
            "draw the figures before every sweep point is in the store: skip "
            "the sweep figures whose points are missing and list them (exit "
            "code 1); without it a missing point is an error (exit code 3)"
        ),
    )
    figures.add_argument(
        "--transaction-costs",
        type=_costs,
        default=None,
        metavar="TAU,...",
        help=(
            "comma-separated transaction costs per contract (loss units) of "
            "the cluster net-advantage figure (default: the thesis' "
            "25000,50000,75000,100000,125000)"
        ),
    )
    figures_verbosity = figures.add_mutually_exclusive_group()
    figures_verbosity.add_argument(
        "-v", "--verbose", action="store_true", help="log at DEBUG level"
    )
    figures_verbosity.add_argument(
        "-q", "--quiet", action="store_true", help="log warnings and errors only"
    )
    figures.set_defaults(handler=_figures)
    return parser


def _costs(text: str) -> tuple[float, ...]:
    """Parse ``--transaction-costs``: distinct finite numbers >= 0, comma-separated."""
    try:
        values = tuple(float(t) for t in text.split(","))
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"not a comma-separated list of numbers: {text!r}"
        ) from None
    if not all(math.isfinite(v) and v >= 0 for v in values):
        raise argparse.ArgumentTypeError(
            f"transaction costs must be finite and >= 0: {text!r}"
        )
    if len(set(values)) != len(values):
        raise argparse.ArgumentTypeError(f"transaction costs repeat: {text!r}")
    return values


def _positive_int(text: str) -> int:
    """Parse a positive integer argument (``--jobs``)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {value}")
    return value


def _version() -> str:
    """Return ``"<prog> <version>"`` for ``--version``."""
    return f"{PROG} {version(PACKAGE)}"


# --------------------------------------------------------------------------
# Output helpers
# --------------------------------------------------------------------------


def _out(line: str = "") -> None:
    """Print one line of the summary to stdout."""
    print(line)


def _short(run_id: str) -> str:
    """``"sha256:"`` and the first 12 hex digits of a run id."""
    return run_id[: len("sha256:") + 12]


def _label(config: ExperimentConfig) -> str:
    """``"<scope> x <objective>"`` of a single-run config."""
    return f"{config.scopes[0].kind} x {config.objectives[0].kind}"


def _point_label(point: SweepPoint) -> str:
    """Describe a sweep point: its value (and subset), scope and objective.

    A point whose cluster count was capped at its subset size (MAR-131) also
    shows the cap, e.g. ``n_assets=2 [A,B] (n_clusters 3->2) cluster x mse``
    (MAR-150), so a dry run never hides it.
    """
    value = f"{point.parameter}={point.value!r}"
    if point.location_ids is not None:
        value += f" [{','.join(point.location_ids)}]"
    if point.n_clusters_capped:
        value += (
            f" (n_clusters {point.n_clusters_requested}->{point.n_clusters_effective})"
        )
    return f"{value} {point.scope} x {point.objective}"


def _outcome_status(outcome: RunOutcome) -> str:
    """``ok`` or ``FAILED`` with the failed design problems."""
    if outcome.ok:
        return "ok"
    if outcome.failed:
        return f"FAILED ({', '.join(outcome.failed)})"
    return "FAILED (not evaluated)"


def _outcome_line(label: str, outcome: RunOutcome) -> str:
    """One summary line for an executed or cached run."""
    how = "cached" if outcome.cached else "ran"
    return f"  {how:<7}{_short(outcome.run_id)}  {label}  {_outcome_status(outcome)}"


# --------------------------------------------------------------------------
# Dry run
# --------------------------------------------------------------------------


@dataclass
class _Planner:
    """Tells, for a dry run, whether each run would execute or hit the cache.

    Mirrors the cache decision of
    :func:`~parametric_insurance_design.experiment.runner.run_single`, and
    tracks the runs planned earlier in the same command (a sweep point equal
    to a baseline run is a cache hit once the baseline has run).
    """

    data: RunInput
    store: ResultStore
    policy: SolverPolicy
    force: bool
    retry_failed: bool

    def __post_init__(self) -> None:
        self.planned: set[str] = set()
        self.n_run = 0
        self.n_cached = 0

    def line(self, config: ExperimentConfig, label: str) -> str:
        """Plan one single-run config and return its plan line."""
        run_id = run_key(config_hash(config), self.data.checksum, policy=self.policy)
        status = self._status(run_id)
        self.planned.add(run_id)
        if status.startswith("cached"):
            self.n_cached += 1
        else:
            self.n_run += 1
        return f"  {status:<24}{_short(run_id)}  {label}"

    def _status(self, run_id: str) -> str:
        if self.force:
            return "run (--force)"
        if run_id in self.planned:
            return "cached (planned above)"
        if not self.store.has_run(run_id):
            return "run"
        cached = RunOutcome.from_manifest(self.store.manifest(run_id), cached=True)
        if cached.ok:
            return "cached"
        if self.retry_failed:
            return "run (--retry-failed)"
        return "cached (failed)"

    def total(self) -> str:
        """Return the closing line of the plan."""
        n = self.n_run + self.n_cached
        return f"plan: {n} runs, {self.n_run} to run, {self.n_cached} cached"


def _planner(config: ExperimentConfig, args: argparse.Namespace) -> _Planner:
    """Read the input and open the store for a dry run."""
    data = load_input(config)
    store = ResultStore(config.output.directory)
    _out(f"dry run: {config.name!r}, store {store.root}")
    _out(f"input checksum {data.checksum}, policy {args.policy!r}")
    return _Planner(data, store, POLICIES[args.policy], args.force, args.retry_failed)


def _plan_run(config: ExperimentConfig, args: argparse.Namespace) -> ExitCode:
    """Print the plan of ``run``."""
    planner = _planner(config, args)
    _out("runs:")
    for single in config.single_runs():
        _out(planner.line(single, _label(single)))
    _out(planner.total())
    return ExitCode.OK


def _plan_sweep(config: ExperimentConfig, args: argparse.Namespace) -> ExitCode:
    """Print the plan of ``sweep``."""
    planner = _planner(config, args)
    if args.baseline:
        _out("baseline:")
        for single in config.single_runs():
            _out(planner.line(single, _label(single)))
    for spec in _selected_sweeps(config, args.parameter):
        points = sweep_points(
            config, spec, location_ids=planner.data.eventset.location_ids
        )
        _out(f"sweep {spec.parameter} ({len(points)} points):")
        for point in points:
            _out(planner.line(point.config, _point_label(point)))
    _out(planner.total())
    return ExitCode.OK


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def _selected_sweeps(
    config: ExperimentConfig, parameters: Sequence[str] | None
) -> list[SweepConfig]:
    """Return the config's sweeps to run, in config order.

    Raises
    ------
    ConfigError
        If the config has no sweeps, or none of a requested parameter.
    """
    if not config.sweeps:
        raise ConfigError(
            f"config {config.name!r} has no sweeps; use 'run' for its single runs"
        )
    listed = [s.parameter for s in config.sweeps]
    unknown = [p for p in parameters or () if p not in listed]
    if unknown:
        raise ConfigError(f"the config has no sweep of {unknown} (it has {listed})")
    return [s for s in config.sweeps if parameters is None or s.parameter in parameters]


def _exit_for(outcomes: Iterable[RunOutcome]) -> ExitCode:
    """``OK`` if every run succeeded, else ``RUNS_FAILED``."""
    return ExitCode.OK if all(o.ok for o in outcomes) else ExitCode.RUNS_FAILED


def _run(config: ExperimentConfig, args: argparse.Namespace) -> ExitCode:
    """``run``: every scope x objective of the config."""
    if args.dry_run:
        return _plan_run(config, args)
    singles = config.single_runs()
    outcomes = run_config(
        config,
        policy=POLICIES[args.policy],
        force=args.force,
        retry_failed=args.retry_failed,
    )
    _out(f"run {config.name!r} into {config.output.directory}:")
    for single, outcome in zip(singles, outcomes, strict=True):
        _out(_outcome_line(_label(single), outcome))
    n_failed = sum(not o.ok for o in outcomes)
    n_cached = sum(o.cached for o in outcomes)
    _out(f"{len(outcomes)} runs: {n_cached} cached, {n_failed} failed")
    return _exit_for(outcomes)


def _sweep(config: ExperimentConfig, args: argparse.Namespace) -> ExitCode:
    """``sweep``: the baseline runs, then the sweeps."""
    if args.dry_run:
        return _plan_sweep(config, args)
    _selected_sweeps(config, args.parameter)
    outcome: SweepsOutcome = run_sweeps(
        config,
        parameters=args.parameter,
        baseline=args.baseline,
        policy=POLICIES[args.policy],
        force=args.force,
        retry_failed=args.retry_failed,
        jobs=args.jobs,
    )
    _out(f"sweep {config.name!r} into {config.output.directory}:")
    if outcome.baseline:
        _out("baseline:")
        for single, run in zip(config.single_runs(), outcome.baseline, strict=True):
            _out(_outcome_line(_label(single), run))
    for result in outcome.sweeps:
        _out(
            f"sweep {result.parameter}: {len(result.points)} points, "
            f"{result.n_cached} cached, {len(result.failed)} failed, "
            f"{result.seconds:.1f} s; manifest {result.manifest_path}"
        )
        for failed in result.failed:
            _out(_outcome_line(_point_label(failed.point), failed.outcome))
    runs = [*outcome.baseline, *(p.outcome for s in outcome.sweeps for p in s.points)]
    _out(f"{len(runs)} runs: {sum(not r.ok for r in runs)} failed")
    return _exit_for(runs)


def _import_viz() -> ModuleType:
    """Import :data:`VIZ_MODULE` lazily: the core's only route to viz.

    Raises
    ------
    VizNotInstalledError
        If the viz package, or one of its dependencies, cannot be imported.
    """
    try:
        return importlib.import_module(VIZ_MODULE)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing == VIZ_MODULE or VIZ_MODULE.startswith(f"{missing}."):
            raise VizNotInstalledError(
                f"the figures command needs the {VIZ_DISTRIBUTION} package, "
                f"which is not installed; install it, e.g. 'pip install "
                f"{VIZ_DISTRIBUTION}' (in this repository: 'uv sync')",
                name=_VIZ_PACKAGE,
            ) from exc
        raise VizNotInstalledError(
            f"the {VIZ_DISTRIBUTION} package cannot be imported: its "
            f"dependency {missing!r} is missing; reinstall {VIZ_DISTRIBUTION}",
            name=missing or None,
        ) from exc


def _sweep_runs(
    viz: ModuleType, config: ExperimentConfig, data: RunInput, policy: SolverPolicy
) -> list[object]:
    """Every point of the config's sweeps as a viz ``SweepRun`` (MAR-112).

    The ``run_id`` of a point is computed as ``sweep`` (and its dry run)
    does, so no sweep manifest is needed. ``sweep_points`` lists the points
    value-major, then the single runs the parameter applies to in
    ``single_runs()`` order; that order names each point's baseline run.

    Raises
    ------
    ConfigError
        If a point does not match the scope x objective of its baseline run
        (a broken invariant of ``sweep_points``).
    """
    singles = config.single_runs()
    out: list[object] = []
    for spec in config.sweeps:
        applies = [i for i, s in enumerate(singles) if s.applies(spec.parameter)]
        points = sweep_points(config, spec, location_ids=data.eventset.location_ids)
        for number, point in enumerate(points):
            single = applies[number % len(applies)]
            base = singles[single]
            if (point.scope, point.objective) != (
                base.scopes[0].kind,
                base.objectives[0].kind,
            ):
                raise ConfigError(  # pragma: no cover - sweep_points invariant
                    f"sweep {spec.parameter} point {number} ({point.scope} x "
                    f"{point.objective}) does not follow single run {single}"
                )
            out.append(
                viz.SweepRun(
                    parameter=spec.parameter,
                    value=point.value,
                    run_id=run_key(
                        config_hash(point.config), data.checksum, policy=policy
                    ),
                    single=single,
                    subset_index=point.subset_index,
                    location_ids=point.location_ids,
                )
            )
    return out


def _figures(config: ExperimentConfig, args: argparse.Namespace) -> ExitCode:
    """``figures``: draw the config's figures from its result store."""
    viz = _import_viz()
    data = load_input(config)
    policy = POLICIES[args.policy]
    run_ids = [
        run_key(config_hash(single), data.checksum, policy=policy)
        for single in config.single_runs()
    ]
    kfold = config.sample.kind == KFOLD_SAMPLE
    # A k-fold config's figures read no sweep points (MAR-151).
    sweeps = [] if kfold else _sweep_runs(viz, config, data, policy)
    out_dir: Path = (
        args.out if args.out is not None else config.output.directory / "figures"
    )
    store = ResultStore(config.output.directory)
    prepared = prepare_eventset(config, data.eventset)
    options: dict[str, object] = {}
    if args.skip_missing_sweeps:
        options["skip_missing_sweeps"] = True
    if args.transaction_costs is not None:
        options["transaction_costs"] = args.transaction_costs
    pooled: PooledKpis | None = None
    if kfold:
        pooled = pooled_kpis(config, store, prepared, run_ids)
        options["pooled_kpis"] = pooled.table
    report = viz.write_figures(
        config,
        run_ids,
        store=store,
        out_dir=out_dir,
        eventset=prepared,
        sweeps=sweeps,
        **options,
    )
    _out(f"figures {config.name!r} from {config.output.directory} into {out_dir}:")
    if pooled is not None:
        n_designs = len(config.scopes) * len(config.objectives)
        intervals = (
            "no intervals (no bootstrap section)"
            if pooled.resample is None
            else f"B = {pooled.resample.n_bootstrap}, level {pooled.level:g}"
        )
        _out(
            f"  pooled k-fold KPIs (k = {pooled.k}): "
            f"{n_designs - len(pooled.failed)} of {n_designs} scope x objective "
            f"pooled over every fold's test block; {intervals}"
        )
        for failure in pooled.failed:
            _out(
                f"  not pooled: {failure.scope} x {failure.objective}: {failure.reason}"
            )
    if sweeps:
        n_missing = len(report.missing_sweeps)
        _out(
            f"  read {len(sweeps) - n_missing} sweep points of "
            f"{len(config.sweeps)} sweeps"
            + (f"; {n_missing} not in the store, skipped" if n_missing else "")
        )
    for written in report.written:
        tables = ", ".join(p.name for p in written.tables.values())
        _out(f"  wrote   {written.image.name}  ({tables})")
    for skipped in report.skipped:
        how = (
            "MISSING" if skipped.missing else "FAILED" if skipped.failed else "skipped"
        )
        _out(f"  {how:<8}{skipped.name}: {skipped.reason}")
    n_failed = sum(s.failed for s in report.skipped)
    n_missing_figures = sum(s.missing for s in report.skipped)
    _out(
        f"{len(report.written)} figures written, {len(report.skipped)} skipped "
        f"({n_failed} because a run failed"
        + (
            f", {n_missing_figures} because sweep points are missing"
            if n_missing_figures
            else ""
        )
        + ")"
    )
    return ExitCode.OK if report.ok else ExitCode.RUNS_FAILED


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _configure_logging(args: argparse.Namespace) -> logging.Handler:
    """Send the package's log to stderr at the requested level."""
    level = logging.DEBUG if args.verbose else logging.WARNING if args.quiet else None
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logger = logging.getLogger(_LOGGER)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO if level is None else level)
    return handler


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments without the program name. Default: ``sys.argv[1:]``.

    Returns
    -------
    int
        The exit code (:class:`ExitCode`).
    """
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help, --version (0) and usage errors (2)
        return int(exc.code) if isinstance(exc.code, int) else ExitCode.USAGE
    logger = logging.getLogger(_LOGGER)
    level = logger.level
    handler = _configure_logging(args)
    command: Callable[[ExperimentConfig, argparse.Namespace], ExitCode] = args.handler
    try:
        return int(command(load_config(args.config), args))
    except (ParametricInsuranceDesignError, OSError) as exc:
        _log.error("%s: %s", type(exc).__name__, exc)
        return ExitCode.INPUT_ERROR
    except KeyboardInterrupt:
        _log.error("interrupted; finished runs are in the store")
        return ExitCode.INTERRUPTED
    except Exception:
        _log.exception("internal error")
        return ExitCode.INTERNAL_ERROR
    finally:
        logger.removeHandler(handler)
        logger.setLevel(level)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
