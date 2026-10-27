"""One-factor-at-a-time sweeps (SPEC §4.2).

Owner: MAR-65. Reproduces the thesis sensitivity design on top of the run
executor (:mod:`~parametric_insurance_design.experiment.runner`): vary one
parameter, hold every other at its baseline value, and run each sweep point
as a cached single run whose ``runs.source`` is the thesis tag
``"<param>_sweep"`` (:data:`SWEEP_SOURCES`).

Sweep points
------------
:func:`sweep_points` expands one :class:`~.config.SweepConfig` of an
experiment config into single-run configs, value by value (for ``n_assets``,
subset by subset), each value with the experiment's scope x objective runs in
``single_runs()`` order:

* **Optimisation parameters** (``alpha``, ``beta``, ``budget_loading``,
  ``n_bins``, ``n_clusters``). A point is
  ``single.with_parameter(parameter, value)``, for the single runs that accept
  the parameter (``single.applies(parameter)``). This is the thesis mapping of
  ``optimization_config.yaml``: ``alpha`` and ``beta`` for the weighted-CVaR
  objective, ``budget_loading`` and ``n_bins`` for every objective,
  ``n_clusters`` for the cluster scope. On the thesis config that gives 3, 3,
  9, 9 and 3 runs per value.
* **``noise_level``** (thesis ``noise_value``) rebuilds the EventSet: a point
  is ``single.with_parameter("noise_level", value)`` for every single run, and
  the runner re-applies the noise layer with a fresh generator from the same
  seed (``prepare_eventset``), as the thesis' ``_build_sim_df`` does per value.
* **``n_assets``** rebuilds the EventSet from location subsets:
  :func:`n_assets_subsets` chooses them as the thesis'
  ``_build_kpi_df_n_assets`` does (``itertools.combinations`` of the
  portfolio in order, and where a size has more than ``max_combinations``
  subsets, ``rng.choice(n_subsets, size=max_combinations, replace=False)``
  with **one** ``numpy.random.default_rng(seed)`` shared by all sizes, in the
  order of the sweep values). A point is ``single.with_locations(subset)``
  for every single run; the runner selects the locations, then applies the
  noise and the threshold (thesis order). The thesis config gives
  9 + 6 x 25 + 9 + 1 = 169 subsets.

The thesis' simulation sweeps (``noise_value``, ``n_assets``) ran every scope
x objective except those a figure cell excluded; that exclusion is a plotting
choice, so every single run is a point here and the figures select.

Sweep membership (decision of MAR-65)
-------------------------------------
The cache key (``run_id``) leaves out the ``source`` tag, so a sweep point
equal to the baseline (e.g. ``alpha = 0.9``, or the ``n_assets`` subset that
is the whole portfolio) is a cache hit, and its ``runs`` rows keep the tag of
the run that computed it first (``"single_run"``). The ``runs`` table
therefore cannot say which sweeps a run belongs to. Options considered:
(a) a ``sweep_points`` record table, which is an ADR 0002 §7 amendment;
(b) a manifest per sweep; (c) matching on ``runs.parameters`` only.

**Chosen: (b), a sweep manifest**, which keeps (c) possible. After a sweep has
run, :func:`run_sweep` writes ``<store root>/sweeps/<hex>.json`` (the hex
digits of :attr:`SweepResult.sweep_id`), listing every point: its value, its
location subset, its scope and objective, its config hash and ``run_id``, the
source tag its ``runs`` rows carry, whether it was a cache hit and whether it
succeeded. :func:`sweep_membership` reads every manifest of a store into one
table that joins the record tables on ``run_id``. Why (b): it needs no change
to the record schemas or the store, it keeps the runner's cache (a baseline
point is computed once), and it states membership explicitly instead of
inferring it from parameters, which cannot tell the ``n_assets`` subsets of
one size apart. (c) keeps working: ``runs.parameters`` names each sweep
parameter (``run_parameters``).

The ``sweeps/`` directory sits next to the store's own layout; the store does
not read it. A manifest is written once all of its points are in the store, so
an interrupted sweep leaves runs but no manifest: run it again and the
finished points are cache hits. The ``sweep_id`` hashes the sweep's parameter,
tag and its points' values, subsets and ``run_id`` values, so it changes with
the config, the input data, the package version and the solver policy (all in
the ``run_id``), and re-running an unchanged sweep rewrites the same file.

So that baseline runs carry ``"single_run"`` whatever the order,
:func:`run_sweeps` runs the experiment's single runs first (``baseline=True``,
as the thesis' ``get_full_results`` did) and then its sweeps.

No silent failures
------------------
A point whose solve or build fails is a run with a failure (the runner
records it), and it stays in the sweep: the manifest marks it ``ok: false``
and :attr:`SweepResult.failed` lists it. The thesis skipped such points (its
results CSVs lack them). An ``n_assets`` value larger than the portfolio
raises :class:`~parametric_insurance_design.errors.ConfigError` instead of
being skipped. Any exception from the runner (an input or configuration
error, or a bug) propagates, and no manifest is written for that sweep.

Parallel execution (MAR-105)
----------------------------
``run_sweeps(..., jobs=N)`` and ``run_sweep(..., jobs=N)`` execute the runs
in ``N`` worker processes (``concurrent.futures.ProcessPoolExecutor`` with
the ``spawn`` start method, so no worker inherits the parent's threads or
locks). ``jobs=1``, the default, is the serial path: :func:`run_single`
point by point, unchanged. With ``N > 1`` the store, the manifests and the
returned outcomes are those of the serial path, apart from wall times and
timestamps:

* **The parent plans and writes, the workers only compute.** For every point
  the parent computes the ``run_id`` and looks the run up in the store, as
  :func:`run_single` does (``force``, ``retry_failed``). Each run left to
  execute goes to a worker, which calls :func:`~.runner.execute` (no store)
  and returns the tables and the manifest. The parent writes them with
  ``ResultStore.write_run`` **in point order**, as the results arrive. The
  store keeps a single writer (it does not coordinate concurrent writers).
* **Duplicate ``run_id`` values are executed once.** Within one dispatch (the
  baseline, or one sweep), a later point with the ``run_id`` of an earlier
  one is not dispatched again: it gets the outcome the serial path would give
  it, a cache hit of the earlier point's run (or, with ``force``, or with
  ``retry_failed`` and a failed run, a re-execution, ``cached=False``, which
  is deterministic and so has the same records). Across dispatches the
  baseline runs first and the sweeps run one after the other, so a point
  equal to the baseline or to a point of an earlier sweep is a cache hit, as
  in the serial path, and keeps its first tag. One pool serves the baseline
  and every sweep of :func:`run_sweeps`.
* **Deterministic.** A run is a pure function of its config, the EventSet
  and the solver policy: every generator is built from a seed in the config
  (``NoiseConfig.rng()``), never shared between runs, so the results do not
  depend on which worker runs a point or when. The EventSet is sent to each
  worker once (the pool initializer), and the worker checks its checksum.
* **No silent failures.** A run that fails to solve or build is recorded by
  the worker exactly as by :func:`run_single` (it is the same
  :func:`~.runner.execute`). An exception raised in a worker (an input or
  configuration error, or a bug) is re-raised in the parent with its type:
  the points before it are in the store, as in the serial path, the pending
  runs are cancelled, the results of later points are discarded, and no
  manifest is written for that sweep. A worker process that dies (killed,
  out of memory, a crash in a solver) raises :class:`SweepWorkerError`
  naming the point; no point is dropped quietly.

Examples
--------
>>> config = load_config("parity/configs/thesis.yaml")  # doctest: +SKIP
>>> outcome = run_sweeps(config, jobs=4)  # doctest: +SKIP
>>> sweep_membership(ResultStore(config.output.directory))  # doctest: +SKIP
"""

from __future__ import annotations

import dataclasses
import hashlib
import itertools
import json
import logging
import multiprocessing
import os
import time
from collections.abc import Iterator, Mapping, Sequence
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from parametric_insurance_design.errors import (
    ConfigError,
    ParametricInsuranceDesignError,
)
from parametric_insurance_design.experiment.config import (
    SWEEP_PARAMETERS,
    ExperimentConfig,
    SweepConfig,
    config_hash,
)
from parametric_insurance_design.experiment.runner import (
    PACKAGE,
    SINGLE_RUN_SOURCE,
    ChecksumMismatchError,
    RunInput,
    RunOutcome,
    execute,
    load_input,
    package_versions,
    policy_fingerprint,
    run_config,
    run_key,
    run_single,
)
from parametric_insurance_design.experiment.store import (
    ResultStore,
    RunTables,
    StoreError,
)
from parametric_insurance_design.solve import DEFAULT_POLICY, SolverPolicy

__all__ = [
    "MEMBERSHIP_COLUMNS",
    "SWEEPS_DIR",
    "SWEEP_ID_DOMAIN",
    "SWEEP_MANIFEST_FORMAT",
    "SWEEP_SOURCES",
    "SweepPoint",
    "SweepPointResult",
    "SweepResult",
    "SweepWorkerError",
    "SweepsOutcome",
    "n_assets_subsets",
    "read_sweep_manifests",
    "run_sweep",
    "run_sweeps",
    "sweep_id",
    "sweep_membership",
    "sweep_points",
]

_log = logging.getLogger(__name__)

SWEEP_MANIFEST_FORMAT: Final[str] = "parametric-insurance-design/sweep-manifest/v1"
"""Value of ``format`` in every sweep manifest."""

SWEEP_ID_DOMAIN: Final[str] = "parametric-insurance-design/sweep-id/v1"
"""Domain tag that starts the input of :func:`sweep_id`."""

SWEEPS_DIR: Final[str] = "sweeps"
"""Directory of the sweep manifests, under the result-store root."""

_THESIS_NAMES: Final[Mapping[str, str]] = {"noise_level": "noise_value"}
"""Sweep parameters whose thesis name differs (``sweeps.yaml``)."""

SWEEP_SOURCES: Final[Mapping[str, str]] = {
    parameter: f"{_THESIS_NAMES.get(parameter, parameter)}_sweep"
    for parameter in SWEEP_PARAMETERS
}
"""``runs.source`` tag of each sweep parameter, as in the thesis results.

``"<param>_sweep"`` with the thesis parameter name, so ``noise_level`` is
tagged ``"noise_value_sweep"``.
"""

MEMBERSHIP_COLUMNS: Final[tuple[str, ...]] = (
    "sweep_id",
    "parameter",
    "source",
    "point",
    "value",
    "subset_index",
    "location_ids",
    "scope",
    "objective",
    "config_hash",
    "run_id",
    "run_source",
    "cached",
    "ok",
)
"""Columns of :func:`sweep_membership`, in order."""


# --------------------------------------------------------------------------
# Points
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepPoint:
    """One run of a sweep.

    Parameters
    ----------
    parameter : str
        The swept parameter (:data:`~.config.SWEEP_PARAMETERS`).
    value : int or float
        Its value at this point; for ``n_assets`` the subset size.
    config : ExperimentConfig
        The point's single-run config (one scope, one objective, no sweeps).
    location_ids : tuple of str or None, default None
        ``n_assets`` only: the location subset, in portfolio order.
    subset_index : int or None, default None
        ``n_assets`` only: position of the subset among the chosen subsets of
        its size (0-based, in sampling order).
    """

    parameter: str
    value: int | float
    config: ExperimentConfig
    location_ids: tuple[str, ...] | None = None
    subset_index: int | None = None

    @property
    def scope(self) -> str:
        """Kind of the point's scope (``individual``, ``cluster``, ...)."""
        return self.config.scopes[0].kind

    @property
    def objective(self) -> str:
        """Kind of the point's objective (``mse``, ``weighted_cvar``, ...)."""
        return self.config.objectives[0].kind


def n_assets_subsets(
    location_ids: Sequence[str],
    sizes: Sequence[int],
    *,
    max_combinations: int | None = None,
    seed: int | None = None,
) -> tuple[tuple[tuple[str, ...], ...], ...]:
    """Choose the location subsets of an ``n_assets`` sweep, as the thesis does.

    For each size ``n`` in ``sizes`` order: every ``itertools.combinations``
    of ``location_ids`` of size ``n``, in that order; if there are more than
    ``max_combinations``, the subsets at
    ``rng.choice(n_subsets, size=max_combinations, replace=False)``, in the
    order drawn. One generator, ``numpy.random.default_rng(seed)``, serves
    every size (thesis ``_build_kpi_df_n_assets``).

    Parameters
    ----------
    location_ids : sequence of str
        The portfolio, in order.
    sizes : sequence of int
        Subset sizes, each in ``1 .. len(location_ids)``.
    max_combinations : int or None, default None
        At most this many subsets per size; None takes all.
    seed : int or None, default None
        Seed of the sampling; required with ``max_combinations``.

    Returns
    -------
    tuple of tuple of tuple of str
        Per size, in ``sizes`` order, the chosen subsets.

    Raises
    ------
    ConfigError
        If a size is outside ``1 .. len(location_ids)``, the locations repeat,
        ``max_combinations`` is below 1, or it is given without a seed.
    """
    ids = list(location_ids)
    if len(set(ids)) != len(ids):
        raise ConfigError(f"n_assets sweep: the locations repeat: {ids}")
    bad = [n for n in sizes if not 1 <= n <= len(ids)]
    if bad:
        raise ConfigError(
            f"n_assets sweep sizes must lie in 1..{len(ids)} "
            f"(the portfolio size), got {bad}"
        )
    if max_combinations is not None:
        if max_combinations < 1:
            raise ConfigError(f"max_combinations must be >= 1, got {max_combinations}")
        if seed is None:
            raise ConfigError("an n_assets sweep with max_combinations needs a seed")
    rng = np.random.default_rng(seed)
    chosen: list[tuple[tuple[str, ...], ...]] = []
    for n in sizes:
        combos = list(itertools.combinations(ids, n))
        if max_combinations is not None and len(combos) > max_combinations:
            picks = rng.choice(len(combos), size=max_combinations, replace=False)
            combos = [combos[int(i)] for i in picks]
        chosen.append(tuple(combos))
    return tuple(chosen)


def _find_sweep(config: ExperimentConfig, sweep: SweepConfig | str) -> SweepConfig:
    """Return ``sweep`` itself, or the config's sweep of that parameter."""
    if isinstance(sweep, SweepConfig):
        return sweep
    for candidate in config.sweeps:
        if candidate.parameter == sweep:
            return candidate
    listed = [s.parameter for s in config.sweeps]
    raise ConfigError(f"the config has no {sweep!r} sweep (it has {listed})")


def sweep_points(
    config: ExperimentConfig,
    sweep: SweepConfig | str,
    *,
    location_ids: Sequence[str] | None = None,
) -> tuple[SweepPoint, ...]:
    """Expand one sweep of an experiment into its single-run points.

    Parameters
    ----------
    config : ExperimentConfig
        The experiment (its scopes x objectives are the baseline runs).
    sweep : SweepConfig or str
        The sweep, or the parameter of one of ``config.sweeps``.
    location_ids : sequence of str, optional
        ``n_assets`` only, when ``config.portfolio.location_ids`` is None: the
        EventSet's locations in order (``RunInput.eventset.location_ids``).
        Ignored when the config lists its portfolio.

    Returns
    -------
    tuple of SweepPoint
        Value-major (subset-major for ``n_assets``), then the applicable
        single runs in ``config.single_runs()`` order (module docstring).

    Raises
    ------
    ConfigError
        If the config has no such sweep, a value gives an invalid config, no
        single run accepts the parameter, or an ``n_assets`` sweep has no
        portfolio to choose from or sizes beyond it.
    """
    spec = _find_sweep(config, sweep)
    parameter = spec.parameter
    singles = [s for s in config.single_runs() if s.applies(parameter)]
    if not singles:
        raise ConfigError(f"no run of {config.name!r} accepts {parameter!r}")
    points: list[SweepPoint] = []
    if parameter != "n_assets":
        for value in spec.values:
            points.extend(
                SweepPoint(parameter, value, single.with_parameter(parameter, value))
                for single in singles
            )
        return tuple(points)

    portfolio = config.portfolio.location_ids
    if portfolio is None:
        if location_ids is None:
            raise ConfigError(
                "an n_assets sweep over all locations needs the EventSet's location_ids"
            )
        portfolio = tuple(location_ids)
    sizes = [int(v) for v in spec.values]
    subsets = n_assets_subsets(
        portfolio, sizes, max_combinations=spec.max_combinations, seed=spec.seed
    )
    for size, chosen in zip(sizes, subsets, strict=True):
        for index, subset in enumerate(chosen):
            points.extend(
                SweepPoint(
                    parameter,
                    size,
                    single.with_locations(subset),
                    location_ids=subset,
                    subset_index=index,
                )
                for single in singles
            )
    return tuple(points)


# --------------------------------------------------------------------------
# Running
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SweepPointResult:
    """A sweep point with the outcome of its run.

    Parameters
    ----------
    point : SweepPoint
        The point.
    outcome : RunOutcome
        Its run, executed or found in the cache. ``outcome.source`` is the
        tag its ``runs`` rows carry, which is ``"single_run"`` (or another
        sweep's tag) when the point was a cache hit.
    """

    point: SweepPoint
    outcome: RunOutcome


@dataclass(frozen=True)
class SweepResult:
    """Summary of one sweep.

    Parameters
    ----------
    sweep_id : str
        :func:`sweep_id` of the sweep; names its manifest.
    parameter : str
        The swept parameter.
    source : str
        Its ``runs.source`` tag (:data:`SWEEP_SOURCES`).
    points : tuple of SweepPointResult
        Every point, in :func:`sweep_points` order.
    manifest_path : pathlib.Path
        Where the sweep manifest was written.
    seconds : float
        Wall time of the sweep.
    """

    sweep_id: str
    parameter: str
    source: str
    points: tuple[SweepPointResult, ...]
    manifest_path: Path
    seconds: float

    @property
    def n_cached(self) -> int:
        """Number of points that were cache hits."""
        return sum(p.outcome.cached for p in self.points)

    @property
    def failed(self) -> tuple[SweepPointResult, ...]:
        """Points whose run has a failure or was not evaluated."""
        return tuple(p for p in self.points if not p.outcome.ok)

    @property
    def ok(self) -> bool:
        """True if every point's run succeeded."""
        return not self.failed


@dataclass(frozen=True)
class SweepsOutcome:
    """What :func:`run_sweeps` did.

    Parameters
    ----------
    baseline : tuple of RunOutcome
        The experiment's single runs (empty with ``baseline=False``).
    sweeps : tuple of SweepResult
        One per sweep run, in config order.
    """

    baseline: tuple[RunOutcome, ...]
    sweeps: tuple[SweepResult, ...]


def _canonical(value: object) -> str:
    """Canonical JSON: sorted keys, no whitespace, ASCII, no NaN."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def _point_key(point: SweepPoint) -> dict[str, Any]:
    """Return the JSON fields that place a point within its sweep."""
    return {
        "value": point.value,
        "subset_index": point.subset_index,
        "location_ids": (
            None if point.location_ids is None else list(point.location_ids)
        ),
    }


def sweep_id(parameter: str, points: Sequence[tuple[SweepPoint, str]]) -> str:
    """Return the id of a sweep: a hash of its tag and its points' runs.

    Parameters
    ----------
    parameter : str
        The swept parameter.
    points : sequence of (SweepPoint, str)
        Every point with its ``run_id``, in sweep order.

    Returns
    -------
    str
        ``"sha256:"`` and 64 lowercase hex digits. It changes with anything
        that changes a ``run_id`` (config, input data, package version,
        solver policy), and with the values and subsets.
    """
    payload = {
        "parameter": parameter,
        "source": SWEEP_SOURCES[parameter],
        "points": [{**_point_key(p), "run_id": run_id} for p, run_id in points],
    }
    data = SWEEP_ID_DOMAIN.encode("utf-8") + b"\0" + _canonical(payload).encode()
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _manifest_path(store: ResultStore, sweep_id_: str) -> Path:
    """``<root>/sweeps/<hex>.json`` of a sweep id."""
    return store.root / SWEEPS_DIR / f"{sweep_id_.removeprefix('sha256:')}.json"


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write JSON through a temporary file and ``os.replace``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    data = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# Parallel execution (MAR-105)
# --------------------------------------------------------------------------


class SweepWorkerError(ParametricInsuranceDesignError, RuntimeError):
    """A worker process of a parallel sweep died before returning its run.

    Raised by :func:`run_sweep` and :func:`run_sweeps` with ``jobs > 1``
    when the process pool breaks (a worker was killed, ran out of memory or
    crashed in native code), or a worker returned another run than it was
    given. The points before the failed one are in the store; no manifest is
    written for the sweep. Run it again: the finished points are cache hits.
    """


_worker_data: RunInput | None = None
"""The :class:`RunInput` of this worker process (set by :func:`_init_worker`)."""


def _init_worker(data: RunInput) -> None:
    """Pool initializer: keep the shared input in the worker process."""
    global _worker_data
    _worker_data = data


@dataclass(frozen=True)
class _PolicyFields:
    """A :class:`SolverPolicy` as picklable values.

    ``SolverPolicy`` stores its options as read-only ``MappingProxyType``
    objects, which cannot be pickled, so a policy goes to a worker as its
    class and fields and is rebuilt there (its ``__post_init__`` validates
    and freezes them again).
    """

    cls: type[SolverPolicy]
    fields: dict[str, Any]

    @classmethod
    def of(cls, policy: SolverPolicy) -> _PolicyFields:
        """Take a policy apart."""
        fields = {f.name: getattr(policy, f.name) for f in dataclasses.fields(policy)}
        fields["solver_options"] = {
            solver: dict(options) for solver, options in policy.solver_options.items()
        }
        return cls(type(policy), fields)

    def policy(self) -> SolverPolicy:
        """Rebuild the policy."""
        return self.cls(**self.fields)


def _execute_in_worker(
    config: ExperimentConfig, checksum: str, source: str, policy: _PolicyFields
) -> tuple[RunTables, dict[str, Any]]:
    """Execute one run in a worker process, without touching the store."""
    data = _worker_data
    if data is None or data.checksum != checksum:
        raise SweepWorkerError(
            "worker process has no input or another input than the parent "
            f"(expected EventSet {checksum})"
        )
    return execute(config, data, source=source, policy=policy.policy())


@dataclass(frozen=True, eq=False)
class _Workers:
    """A process pool bound to the :class:`RunInput` its workers hold."""

    executor: ProcessPoolExecutor
    data: RunInput
    jobs: int


def _check_jobs(jobs: int) -> int:
    """Return ``jobs`` if it is a positive int, else raise ConfigError."""
    if isinstance(jobs, bool) or not isinstance(jobs, int) or jobs < 1:
        raise ConfigError(f"jobs must be a positive integer, got {jobs!r}")
    return jobs


@contextmanager
def _workers(jobs: int, data: RunInput) -> Iterator[_Workers | None]:
    """Yield a pool of ``jobs`` worker processes holding ``data``, or None.

    None for ``jobs == 1`` (the serial path). The pool uses the ``spawn``
    start method on every platform. On exit, pending runs are cancelled and
    the pool waits for the running ones.
    """
    if _check_jobs(jobs) == 1:
        yield None
        return
    executor = ProcessPoolExecutor(
        max_workers=jobs,
        mp_context=multiprocessing.get_context("spawn"),
        initializer=_init_worker,
        initargs=(data,),
    )
    try:
        yield _Workers(executor, data, jobs)
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def _check_input(config: ExperimentConfig, data: RunInput) -> None:
    """Refuse a run whose config pins another checksum than ``data`` has.

    The check :func:`run_single` makes before its cache lookup.
    """
    expected = config.eventset.checksum
    if expected is not None and data.checksum != expected:
        raise ChecksumMismatchError(
            f"EventSet content hash of {data.path or 'the input'} is "
            f"{data.checksum}, the config pins eventset.checksum {expected}"
        )


def _run_all(
    configs: Sequence[ExperimentConfig],
    data: RunInput,
    store: ResultStore,
    *,
    source: str,
    policy: SolverPolicy,
    force: bool,
    retry_failed: bool,
    workers: _Workers | None,
) -> tuple[RunOutcome, ...]:
    """Run single-run configs in order, serially or on ``workers``.

    Serially, :func:`run_single` per config. On workers, the parallel path of
    the module docstring: the same outcomes, and the same store contents
    apart from wall times and timestamps.
    """
    if workers is None:
        return tuple(
            run_single(
                single,
                data,
                store,
                source=source,
                policy=policy,
                force=force,
                retry_failed=retry_failed,
            )
            for single in configs
        )
    if workers.data is not data:  # an internal error: the pool is private
        raise ValueError("the worker pool holds another RunInput than the sweep")
    sent_policy = _PolicyFields.of(policy)
    if policy_fingerprint(sent_policy.policy()) != policy_fingerprint(policy):
        raise SweepWorkerError(f"cannot send the solver policy {policy!r} to a worker")
    outcomes: list[RunOutcome | None] = [None] * len(configs)
    first: dict[str, int] = {}  # run_id -> index of its first point
    duplicates: list[tuple[int, int]] = []  # (index, index of the first point)
    pending: list[tuple[int, str, bool, Future[tuple[RunTables, dict[str, Any]]]]] = []
    # An error while planning point k (a pinned checksum, an unreadable
    # manifest) is raised once the runs before k are written, as serially.
    planning_error: Exception | None = None
    try:
        for index, single in enumerate(configs):
            try:
                _check_input(single, data)
                run_id = run_key(config_hash(single), data.checksum, policy=policy)
                if run_id in first:
                    duplicates.append((index, first[run_id]))
                    continue
                first[run_id] = index
                exists = store.has_run(run_id)
                cached = (
                    RunOutcome.from_manifest(store.manifest(run_id), cached=True)
                    if exists and not force
                    else None
                )
            except Exception as exc:
                planning_error = exc
                break
            if cached is not None and not (retry_failed and not cached.ok):
                _log.info("run %s: cached in %s", run_id, store.root)
                outcomes[index] = cached
                continue
            future = workers.executor.submit(
                _execute_in_worker, single, data.checksum, source, sent_policy
            )
            pending.append((index, run_id, exists, future))
        for index, run_id, exists, future in pending:
            try:
                tables, manifest = future.result()
            except BrokenProcessPool as exc:
                raise SweepWorkerError(
                    f"a worker process died while running point {index} "
                    f"(run {run_id}, {configs[index].scopes[0].kind} x "
                    f"{configs[index].objectives[0].kind}); the points before "
                    f"it are in {store.root}"
                ) from exc
            if manifest.get("run_id") != run_id or tables.run_id != run_id:
                raise SweepWorkerError(
                    f"point {index}: a worker returned run "
                    f"{manifest.get('run_id')}, expected {run_id}"
                )
            store.write_run(tables, manifest, overwrite=exists)
            outcome = RunOutcome.from_manifest(manifest, cached=False)
            outcomes[index] = outcome
            _log.info(
                "run %s: %s x %s, %d problems, %d failed, written to %s",
                run_id,
                tables.runs["scope"].iloc[0],
                tables.runs["objective"].iloc[0],
                len(outcome.statuses),
                len(outcome.failed),
                store.root,
            )
    except BaseException:
        for *_, future in pending:
            future.cancel()
        raise
    if planning_error is not None:
        raise planning_error
    for index, earlier in duplicates:
        outcome = outcomes[earlier]
        if outcome is not None:  # else caught by the check below
            # The serial path finds the earlier point's run in the store; it
            # re-executes it with force, or with retry_failed if it failed.
            rerun = force or (retry_failed and not outcome.ok)
            outcomes[index] = dataclasses.replace(outcome, cached=not rerun)
    done = [o for o in outcomes if o is not None]
    if len(done) != len(configs):
        raise SweepWorkerError(
            f"{len(configs) - len(done)} of {len(configs)} runs have no outcome"
        )
    return tuple(done)


def run_sweep(
    config: ExperimentConfig,
    sweep: SweepConfig | str,
    data: RunInput,
    store: ResultStore,
    *,
    policy: SolverPolicy = DEFAULT_POLICY,
    force: bool = False,
    retry_failed: bool = False,
    jobs: int = 1,
) -> SweepResult:
    """Run every point of one sweep and write its manifest.

    Parameters
    ----------
    config : ExperimentConfig
        The experiment.
    sweep : SweepConfig or str
        The sweep, or the parameter of one of ``config.sweeps``.
    data : RunInput
        The EventSet as loaded, shared by every point.
    store : ResultStore
        Where runs are looked up and written, and the manifest goes.
    policy : SolverPolicy, optional
        Solver policy; part of every ``run_id``.
    force, retry_failed : bool, default False
        As for :func:`~.runner.run_single`.
    jobs : int, default 1
        Worker processes. 1 runs the points one by one in this process;
        more runs them in parallel with the same store contents and outcomes
        (module docstring, "Parallel execution").

    Returns
    -------
    SweepResult
        The points with their outcomes; failed points included.

    Raises
    ------
    ConfigError
        As for :func:`sweep_points`, and from the runner; also if ``jobs`` is
        not a positive integer.
    ChecksumMismatchError, EventSetError, StoreError
        From the runner.
    SweepWorkerError
        With ``jobs > 1``, if a worker process dies.
    """
    with _workers(jobs, data) as workers:
        return _run_sweep(
            config,
            sweep,
            data,
            store,
            policy=policy,
            force=force,
            retry_failed=retry_failed,
            workers=workers,
        )


def _run_sweep(
    config: ExperimentConfig,
    sweep: SweepConfig | str,
    data: RunInput,
    store: ResultStore,
    *,
    policy: SolverPolicy,
    force: bool,
    retry_failed: bool,
    workers: _Workers | None,
) -> SweepResult:
    """Run one sweep, serially or on ``workers``; see :func:`run_sweep`."""
    start = time.perf_counter()
    spec = _find_sweep(config, sweep)
    parameter = spec.parameter
    source = SWEEP_SOURCES[parameter]
    points = sweep_points(config, spec, location_ids=data.eventset.location_ids)
    _log.info(
        "sweep %s: %d points%s",
        parameter,
        len(points),
        "" if workers is None else f" on {workers.jobs} worker processes",
    )
    # Serially, each point runs as it is logged; on workers, every point has
    # run (in parallel) before the points are logged.
    outcomes: Iterator[RunOutcome] = (
        (
            run_single(
                point.config,
                data,
                store,
                source=source,
                policy=policy,
                force=force,
                retry_failed=retry_failed,
            )
            for point in points
        )
        if workers is None
        else iter(
            _run_all(
                [point.config for point in points],
                data,
                store,
                source=source,
                policy=policy,
                force=force,
                retry_failed=retry_failed,
                workers=workers,
            )
        )
    )
    results: list[SweepPointResult] = []
    for number, (point, outcome) in enumerate(
        zip(points, outcomes, strict=True), start=1
    ):
        results.append(SweepPointResult(point, outcome))
        _log.debug(
            "sweep %s: point %d/%d (%s=%r, %s x %s) %s",
            parameter,
            number,
            len(points),
            parameter,
            point.value,
            point.scope,
            point.objective,
            "cached" if outcome.cached else "run",
        )
    identity = sweep_id(parameter, [(r.point, r.outcome.run_id) for r in results])
    path = _manifest_path(store, identity)
    seconds = time.perf_counter() - start
    result = SweepResult(identity, parameter, source, tuple(results), path, seconds)
    _write_json(path, _manifest(config, spec, data, policy, result))
    _log.info(
        "sweep %s: %d points, %d cached, %d failed, %.1f s; manifest %s",
        parameter,
        len(results),
        result.n_cached,
        len(result.failed),
        seconds,
        path,
    )
    return result


def _manifest(
    config: ExperimentConfig,
    spec: SweepConfig,
    data: RunInput,
    policy: SolverPolicy,
    result: SweepResult,
) -> dict[str, Any]:
    """Return the JSON manifest of a finished sweep."""
    return {
        "format": SWEEP_MANIFEST_FORMAT,
        "sweep_id": result.sweep_id,
        "parameter": result.parameter,
        "source": result.source,
        "sweep": spec.model_dump(mode="json"),
        "experiment": config.name,
        "base_config_hash": config_hash(config),
        "eventset_checksum": data.checksum,
        "package_version": package_versions()[PACKAGE],
        "solver_policy": policy_fingerprint(policy),
        "created_at": datetime.now(UTC).isoformat(),
        "seconds": result.seconds,
        "n_points": len(result.points),
        "n_cached": result.n_cached,
        "n_failed": len(result.failed),
        "points": [
            {
                "point": number,
                **_point_key(r.point),
                "scope": r.point.scope,
                "objective": r.point.objective,
                "config_hash": r.outcome.config_hash,
                "run_id": r.outcome.run_id,
                "run_source": r.outcome.source,
                "cached": r.outcome.cached,
                "ok": r.outcome.ok,
                "failed": list(r.outcome.failed),
            }
            for number, r in enumerate(result.points)
        ],
    }


def run_sweeps(
    config: ExperimentConfig,
    *,
    store: ResultStore | None = None,
    data: RunInput | None = None,
    parameters: Sequence[str] | None = None,
    baseline: bool = True,
    policy: SolverPolicy = DEFAULT_POLICY,
    force: bool = False,
    retry_failed: bool = False,
    jobs: int = 1,
) -> SweepsOutcome:
    """Run an experiment's baseline runs, then its sweeps.

    Parameters
    ----------
    config : ExperimentConfig
        The experiment, with its ``sweeps``.
    store : ResultStore, optional
        Default: ``ResultStore(config.output.directory)``.
    data : RunInput, optional
        Default: :func:`~.runner.load_input` of the config, read once.
    parameters : sequence of str, optional
        Run only the sweeps of these parameters (in config order). Default:
        every sweep of the config.
    baseline : bool, default True
        Run the experiment's single runs first (``"single_run"`` tag), so a
        sweep point equal to the baseline is a cache hit tagged as in the
        thesis whatever the order of commands.
    policy : SolverPolicy, optional
        Solver policy.
    force, retry_failed : bool, default False
        As for :func:`~.runner.run_single`.
    jobs : int, default 1
        Worker processes, shared by the baseline and every sweep. 1 is the
        serial path; more gives the same store contents and outcomes
        (module docstring, "Parallel execution"). The baseline finishes
        before the first sweep starts, and each sweep before the next.

    Returns
    -------
    SweepsOutcome
        The baseline outcomes and one :class:`SweepResult` per sweep.

    Raises
    ------
    ConfigError
        If ``parameters`` names a sweep the config does not have, and as for
        :func:`run_sweep`.
    SweepWorkerError
        With ``jobs > 1``, if a worker process dies.
    """
    if parameters is not None:
        listed = {s.parameter for s in config.sweeps}
        unknown = [p for p in parameters if p not in listed]
        if unknown:
            raise ConfigError(
                f"the config has no sweep of {unknown} (it has {sorted(listed)})"
            )
    _check_jobs(jobs)
    store = ResultStore(config.output.directory) if store is None else store
    data = load_input(config) if data is None else data
    options: dict[str, Any] = {
        "policy": policy,
        "force": force,
        "retry_failed": retry_failed,
    }
    with _workers(jobs, data) as workers:
        if not baseline:
            base: tuple[RunOutcome, ...] = ()
        elif workers is None:
            base = run_config(config, store=store, data=data, **options)
        else:
            base = _run_all(
                config.single_runs(),
                data,
                store,
                source=SINGLE_RUN_SOURCE,
                workers=workers,
                **options,
            )
        sweeps = tuple(
            _run_sweep(config, spec, data, store, workers=workers, **options)
            for spec in config.sweeps
            if parameters is None or spec.parameter in parameters
        )
    return SweepsOutcome(base, sweeps)


# --------------------------------------------------------------------------
# Reading membership
# --------------------------------------------------------------------------


def read_sweep_manifests(store: ResultStore) -> tuple[dict[str, Any], ...]:
    """Read every sweep manifest of a store.

    Parameters
    ----------
    store : ResultStore
        The store.

    Returns
    -------
    tuple of dict
        The manifests, sorted by ``parameter`` then ``sweep_id``.

    Raises
    ------
    StoreError
        If a manifest is not valid JSON or has another format.
    """
    directory = store.root / SWEEPS_DIR
    if not directory.is_dir():
        return ()
    manifests = []
    for path in sorted(directory.glob("*.json")):  # leftovers end in .tmp
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StoreError(f"{path} is not valid JSON: {exc}") from exc
        if not isinstance(manifest, dict) or (
            manifest.get("format") != SWEEP_MANIFEST_FORMAT
        ):
            raise StoreError(f"{path} is not a {SWEEP_MANIFEST_FORMAT} manifest")
        manifests.append(manifest)
    return tuple(sorted(manifests, key=lambda m: (m["parameter"], m["sweep_id"])))


def sweep_membership(store: ResultStore) -> pd.DataFrame:
    """Return which runs belong to which sweep, from the sweep manifests.

    Parameters
    ----------
    store : ResultStore
        The store.

    Returns
    -------
    pandas.DataFrame
        One row per sweep point, columns :data:`MEMBERSHIP_COLUMNS`. Join it
        with the record tables on ``run_id``. ``location_ids`` is a tuple of
        str (``n_assets``) or None; ``subset_index`` is None outside
        ``n_assets``. ``run_source`` is the tag of the run's ``runs`` rows,
        ``source`` the sweep's tag.

    Raises
    ------
    StoreError
        As for :func:`read_sweep_manifests`.
    """
    rows = [
        {
            "sweep_id": manifest["sweep_id"],
            "parameter": manifest["parameter"],
            "source": manifest["source"],
            **{key: point[key] for key in MEMBERSHIP_COLUMNS[3:]},
        }
        for manifest in read_sweep_manifests(store)
        for point in manifest["points"]
    ]
    frame = pd.DataFrame(rows, columns=list(MEMBERSHIP_COLUMNS))
    frame["location_ids"] = [
        None if ids is None else tuple(ids) for ids in frame["location_ids"]
    ]
    frame["subset_index"] = frame["subset_index"].astype("Int64")
    return frame
