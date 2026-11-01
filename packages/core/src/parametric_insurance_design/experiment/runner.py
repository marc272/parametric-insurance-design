"""Run executor with a content-hashed cache (SPEC §4.2, thesis issues C3, C5).

Owner: MAR-64. Executes one configured run end to end and persists it in a
:class:`~parametric_insurance_design.experiment.store.ResultStore`:

1. **Input.** :func:`load_input` reads the EventSet at ``eventset.path`` and
   computes its ``EventSet.content_hash()`` once (the *input checksum*). If
   the config pins ``eventset.checksum``, the two must agree
   (:class:`ChecksumMismatchError`).
2. **Cache.** :func:`run_key` combines the config hash, the input checksum,
   the package version and the solver policy into the ``run_id``. If the
   store already holds that run, the run is skipped (a cache hit).
3. **Prepare** (:func:`prepare_eventset`, thesis order): keep the locations
   of ``portfolio.location_ids`` (``EventSet.select_locations``), apply the
   noise layer with ``NoiseConfig.rng()`` (``noise.add_noise``), then the
   threshold filter (``EventSet.filter_threshold``).
4. **Samples.** ``full``: calibrate and evaluate on every row. ``holdout``:
   calibrate on the training years, evaluate on both samples
   (``splits.holdout``, MAR-22). ``kfold``: one run per fold (see below);
   calibrate on the fold's training years, evaluate on its training and
   test samples (``splits.year_block_kfold``).
5. **Build, solve, evaluate.** ``problem.build_problems``, then
   ``solve.solve`` for every design problem, which carries the run's pricing
   (``BuiltProblem.pricing``, MAR-171), so the recorded premium is
   ``pricing.premium_value`` of the realised payout (MAR-143), then
   ``evaluate.kpis`` and
   ``evaluate.exceedance_curves`` (at ``evaluation.return_periods``, MAR-117)
   when every design problem was solved.
   With a ``bootstrap`` config section (MAR-23), ``bootstrap.bootstrap_kpis``
   replaces ``evaluate.kpis``: the same point values plus block-bootstrap
   confidence intervals in the ``ci_*`` columns, with a fresh generator
   ``BootstrapConfig.rng()`` per evaluation sample. The manifest's
   ``bootstrap`` entry records the settings, the time per sample and the
   KPIs whose bounds are null because some replicate is undefined.
6. **Persist.** One row per design problem in ``runs``, entity membership in
   ``entities``, the fitted levels in ``payouts``, the KPI and exceedance
   tables, and a provenance manifest.

A *run* is one scope with one objective: one of
``ExperimentConfig.single_runs()``. :func:`run_config` runs every one of
them; sweeps (MAR-65) call :func:`run_single` per sweep point with a shared
:class:`RunInput`, so the EventSet is read and hashed once per sweep.

Cache key
---------
``run_id = "sha256:" + sha256(RUN_KEY_DOMAIN || NUL || canonical JSON of
{config_hash, eventset_checksum, package_version, solver_policy})``
(:func:`run_key`). It is also the ``run_id`` of every record (``records``
convention: the run's content hash is its cache key).

* ``config_hash`` is :func:`~.config.config_hash` of the single-run config.
  It leaves out the labels, ``eventset.path``, ``output`` and ``sweeps``;
  a sweep point equal to the baseline therefore shares the baseline's entry.
* ``eventset_checksum`` is the ``content_hash()`` of the EventSet **as
  loaded** from ``eventset.path``, before the location subset, the noise and
  the threshold filter, and before any ``Sample.select``. Every ``runs`` row
  of the run carries it, failed solves included. The prepared EventSet is a
  deterministic function of (loaded EventSet, config, package version), so
  hashing the loaded one is enough to identify the solved data. It is also
  the cheap choice: one hash per sweep instead of one per sweep point, and a
  cache hit needs no preparation at all. The prepared EventSet's own
  ``content_hash()`` is recorded in the manifest (``prepared_eventset``).
* ``package_version`` is the installed ``parametric-insurance-design``
  version. **Any version bump invalidates every cached run**, with or
  without noise. MAR-88 and MAR-92 found that ``TransformRecord.version``
  makes the ``content_hash()`` of noisy and location-subset EventSets change
  with the package version; this key makes that conservative behaviour
  uniform, because the builder, the solver policy defaults and the
  evaluation also change with the code. Versions of third-party packages
  (cvxpy, the solvers, numpy) are recorded in the manifest but are **not**
  part of the key: upgrading them reuses cached runs. Run with
  ``force=True``, or into a new store, to recompute after such an upgrade.
* ``solver_policy`` is the policy's fields (:func:`policy_fingerprint`), so
  a run with another solver order or acceptance rule is a different run.

The ``source`` tag (``"single_run"``, ``"<param>_sweep"``) is not part of
the key: a run computed under one tag is a cache hit under another, and its
``runs`` rows keep the tag it was first written with.

No silent failures
------------------
* A design problem that no solver solves becomes a ``runs`` row with the
  :class:`~parametric_insurance_design.errors.SolveError`'s ``status``, its
  class name in ``error_type`` and its message (which lists every solver
  attempt) in ``error_message``. Its attempts are in the manifest. The other
  design problems of the run are still solved and recorded.
* If building the run fails with a library error (e.g. a component that
  cannot handle the basis, or a cluster scope with more clusters than
  locations), the run gets one ``runs`` row with ``problem_id = "*"``
  (``records.ALL_PROBLEMS``), status ``error`` and the error.
* KPIs and exceedance curves need every design problem (portfolio KPIs
  over a subset would be biased), so a run with a failure has empty ``kpis``
  and ``exceedance`` tables. The manifest says why
  (``evaluation.skipped_reason``).
* A failed run is cached like any other: re-running skips it. Pass
  ``retry_failed=True`` to re-execute runs with a failure, or ``force=True``
  to re-execute every run.
* Any other exception (an input or configuration error, or a bug) propagates
  and nothing is written for that run.

Degenerate tail objectives (MAR-173)
------------------------------------
Every design problem's manifest entry (``problems``) records, on the
calibration measure (the problem's ``OutcomeMeasure``, which carries the
basis and the calibration sample):

* ``p_zero_loss``: ``P(L_o = 0)``, the probability of the outcomes in which
  the design problem has no loss. It depends on the data, not on the design.
* ``tail_outcomes`` (weighted-CVaR runs; ``None`` otherwise):
  ``(1 - beta) / p_min``, with ``p_min`` the smallest positive outcome
  probability: how many outcomes the CVaR tail holds if each has the
  smallest probability. On a measure whose outcomes are equally likely (the
  annual basis always) it is ``(1 - beta) * n_outcomes``.
* ``degenerate_tail`` (:data:`DEGENERATE_TAILS`; ``None`` when not
  degenerate, and for other objectives):

  - ``"expected_uncovered"`` when ``beta <= p_zero_loss``. Then
    ``VaR_beta(U) = 0`` for every design, so the weighted-CVaR objective is
    ``(alpha / (1 - beta) + 1 - alpha) * E[U]``: an E[U] run, with the same
    minimisers (design review MAR-161, F4).
  - ``"single_outcome"`` when ``tail_outcomes <= 1``. Then ``1 - beta`` is at
    most every outcome's probability, so ``CVaR_beta(U)`` is the single worst
    outcome and the objective a minimax over outcomes (F15). If both hold,
    the flag is ``"expected_uncovered"``.

  Both comparisons allow :data:`DEGENERATE_TAIL_ATOL` for the rounding of
  summed probabilities. The flags concern the CVaR term; with ``alpha = 0``
  the objective is E[U] by construction, which the config already says.

The flags are recorded, not raised: the runs are valid, only their reading
changes. The manifest is not part of the cache key, so run ids and config
hashes are unchanged. A failed build (``problem_id = "*"``) records ``None``
for all three.

k-fold: a run per fold
----------------------
A k-fold experiment calibrates once per fold, and the ``runs`` key is
``(run_id, problem_id)`` without the fold. MAR-22 therefore makes each fold a
run of its own: ``ExperimentConfig.single_runs()`` expands a k-fold sample
into one config per fold (``sample.fold`` set), so the fold is part of the
config hash and hence of the ``run_id``. ``runs.fold``, ``kpis.fold`` and
``exceedance.fold`` carry the fold number; the KPI rows of a fold are its
``train`` (in-sample) and ``test`` (out-of-sample) evaluations. A config
whose k-fold sample has no ``fold`` is refused with :class:`ConfigError`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import platform
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from parametric_insurance_design import splits
from parametric_insurance_design.basis import PROBABILITY_ATOL
from parametric_insurance_design.bootstrap import bootstrap_kpis, resample_years
from parametric_insurance_design.errors import (
    ConfigError,
    InputMismatchError,
    ParametricInsuranceDesignError,
    SolveError,
)
from parametric_insurance_design.evaluate import exceedance_curves, kpis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    to_dict,
)
from parametric_insurance_design.experiment.store import ResultStore, RunTables
from parametric_insurance_design.interfaces import (
    Objective,
    Sample,
    SolverAttempt,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.objectives import WeightedCVaR
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.records import (
    ALL_PROBLEMS,
    ENTITIES,
    EXCEEDANCE,
    KPIS,
    PAYOUTS,
    RUNS,
)
from parametric_insurance_design.solve import DEFAULT_POLICY, SolverPolicy, solve

__all__ = [
    "DEGENERATE_TAILS",
    "DEGENERATE_TAIL_ATOL",
    "DEGENERATE_TAIL_EXPECTED_UNCOVERED",
    "DEGENERATE_TAIL_SINGLE_OUTCOME",
    "MANIFEST_FORMAT",
    "PACKAGE",
    "PROVENANCE_PACKAGES",
    "RUN_KEY_DOMAIN",
    "SINGLE_RUN_SOURCE",
    "ChecksumMismatchError",
    "RunInput",
    "RunOutcome",
    "execute",
    "load_input",
    "package_versions",
    "policy_fingerprint",
    "prepare_eventset",
    "run_config",
    "run_key",
    "run_parameters",
    "run_single",
]

_log = logging.getLogger(__name__)

RUN_KEY_DOMAIN: Final[str] = "parametric-insurance-design/run-key/v1"
"""Domain tag that starts the input of :func:`run_key`. A change of the key's
content or canonical form bumps it."""

MANIFEST_FORMAT: Final[str] = "parametric-insurance-design/run-manifest/v1"
"""Value of ``format`` in every run manifest."""

SINGLE_RUN_SOURCE: Final[str] = "single_run"
"""Default ``runs.source`` tag."""

PACKAGE: Final[str] = "parametric-insurance-design"
"""Distribution name of this package, whose version is part of the key."""

PROVENANCE_PACKAGES: Final[tuple[str, ...]] = (
    PACKAGE,
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "pydantic",
    "pyyaml",
    "cvxpy",
    "clarabel",
    "osqp",
    "scs",
    "highspy",
)
"""Distributions whose versions every manifest records (None if absent)."""

DEGENERATE_TAIL_EXPECTED_UNCOVERED: Final[str] = "expected_uncovered"
"""``degenerate_tail`` of a weighted-CVaR problem with ``beta <= P(L_o = 0)``:
its objective is a positive multiple of E[U] (MAR-173)."""

DEGENERATE_TAIL_SINGLE_OUTCOME: Final[str] = "single_outcome"
"""``degenerate_tail`` of a weighted-CVaR problem whose CVaR tail is the
single worst outcome, ``tail_outcomes <= 1`` (MAR-173)."""

DEGENERATE_TAILS: Final[tuple[str, ...]] = (
    DEGENERATE_TAIL_EXPECTED_UNCOVERED,
    DEGENERATE_TAIL_SINGLE_OUTCOME,
)
"""Values of a manifest problem entry's ``degenerate_tail`` besides None."""

DEGENERATE_TAIL_ATOL: Final[float] = PROBABILITY_ATOL
"""Tolerance of the ``degenerate_tail`` comparisons, for the rounding of
summed probabilities: the outcome measure's own ``PROBABILITY_ATOL``."""


class ChecksumMismatchError(InputMismatchError):
    """The EventSet's content hash differs from the checksum the config pins."""


# --------------------------------------------------------------------------
# Input
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class RunInput:
    """An EventSet as loaded, with its content hash.

    Build it with :meth:`load` or :meth:`from_eventset` (or
    :func:`load_input`), once per config or sweep, and pass it to every
    :func:`run_single` call.

    Parameters
    ----------
    eventset : EventSet
        The EventSet as loaded, before any subset, noise or filter.
    checksum : str
        Its ``content_hash()``.
    path : pathlib.Path or None
        Directory it was read from, if any.
    load_seconds : float
        Wall time of reading and hashing.
    """

    eventset: EventSet
    checksum: str
    path: Path | None
    load_seconds: float

    @classmethod
    def load(
        cls, path: str | Path, *, expected_checksum: str | None = None
    ) -> RunInput:
        """Read an EventSet directory and hash it.

        Parameters
        ----------
        path : str or pathlib.Path
            EventSet directory.
        expected_checksum : str, optional
            The ``content_hash()`` the data must have.

        Returns
        -------
        RunInput
            The EventSet and its checksum.

        Raises
        ------
        ChecksumMismatchError
            If ``expected_checksum`` is given and differs.
        EventSetError
            If the directory is not a valid EventSet.
        """
        start = time.perf_counter()
        eventset = EventSet.from_parquet(path)
        checksum = eventset.content_hash()
        _check_checksum(checksum, expected_checksum, where=str(path))
        return cls(eventset, checksum, Path(path), time.perf_counter() - start)

    @classmethod
    def from_eventset(
        cls, eventset: EventSet, *, expected_checksum: str | None = None
    ) -> RunInput:
        """Hash an EventSet already in memory.

        Parameters
        ----------
        eventset : EventSet
            The EventSet as loaded.
        expected_checksum : str, optional
            The ``content_hash()`` the data must have.

        Returns
        -------
        RunInput
            The EventSet and its checksum, with ``path = None``.

        Raises
        ------
        ChecksumMismatchError
            If ``expected_checksum`` is given and differs.
        """
        start = time.perf_counter()
        checksum = eventset.content_hash()
        _check_checksum(checksum, expected_checksum, where="the given EventSet")
        return cls(eventset, checksum, None, time.perf_counter() - start)


def _check_checksum(actual: str, expected: str | None, *, where: str) -> None:
    """Raise :class:`ChecksumMismatchError` if a pinned checksum differs."""
    if expected is not None and actual != expected:
        raise ChecksumMismatchError(
            f"EventSet content hash of {where} is {actual}, the config pins "
            f"eventset.checksum {expected}"
        )


def load_input(config: ExperimentConfig) -> RunInput:
    """Read the config's EventSet (``eventset.path``) and check its checksum.

    Parameters
    ----------
    config : ExperimentConfig
        The config.

    Returns
    -------
    RunInput
        The EventSet as loaded, with its content hash.

    Raises
    ------
    ChecksumMismatchError
        If ``eventset.checksum`` is set and differs from the content hash.
    EventSetError
        If the directory is not a valid EventSet.
    """
    return RunInput.load(
        config.eventset.path, expected_checksum=config.eventset.checksum
    )


def prepare_eventset(config: ExperimentConfig, eventset: EventSet) -> EventSet:
    """Apply the config's location subset, noise layer and threshold filter.

    In the thesis order: ``select_locations`` (if ``portfolio.location_ids``
    is set), ``add_noise`` with a fresh ``NoiseConfig.rng()`` (if ``noise``
    is set; every location in subset order, as the thesis draws asset by
    asset), then ``filter_threshold`` (if ``threshold`` is set).

    Parameters
    ----------
    config : ExperimentConfig
        The config.
    eventset : EventSet
        The EventSet as loaded.

    Returns
    -------
    EventSet
        The data to calibrate and evaluate on. Each step appends its record
        to the metadata (``transforms``, ``filters``).

    Raises
    ------
    EventSetError
        If a configured location is not in the EventSet.
    """
    data = eventset
    if config.portfolio.location_ids is not None:
        data = data.select_locations(list(config.portfolio.location_ids))
    if config.noise is not None:
        noise = config.noise
        data = add_noise(
            data,
            level=noise.level,
            kind=noise.kind,
            n_copies=noise.n_copies,
            rng=noise.rng(),
            bounds=noise.bounds,
        )
    if config.threshold is not None:
        data = data.filter_threshold(
            config.threshold.value, column=config.threshold.column
        )
    return data


# --------------------------------------------------------------------------
# Keys, parameters, provenance
# --------------------------------------------------------------------------


def _canonical(value: object) -> str:
    """Canonical JSON: sorted keys, no whitespace, ASCII, no NaN."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def policy_fingerprint(policy: SolverPolicy) -> dict[str, Any]:
    """Return the solver policy's fields as JSON values.

    Parameters
    ----------
    policy : SolverPolicy
        The policy.

    Returns
    -------
    dict
        ``lp_solvers``, ``qp_solvers``, ``accept_inaccurate`` and
        ``solver_options``.

    Raises
    ------
    ConfigError
        If a solver option is not JSON-serialisable (it could not be part of
        the cache key).
    """
    fingerprint = {
        "lp_solvers": list(policy.lp_solvers),
        "qp_solvers": list(policy.qp_solvers),
        "accept_inaccurate": policy.accept_inaccurate,
        "solver_options": {
            name: dict(options) for name, options in policy.solver_options.items()
        },
    }
    try:
        _canonical(fingerprint)
    except (TypeError, ValueError) as exc:
        raise ConfigError(
            f"solver options must be JSON values to enter the cache key: {exc}"
        ) from exc
    return fingerprint


def _package_version() -> str:
    """Return the installed version of this package."""
    return version(PACKAGE)


def run_key(
    config_hash: str,
    eventset_checksum: str,
    *,
    package_version: str | None = None,
    policy: SolverPolicy = DEFAULT_POLICY,
) -> str:
    """Return the cache key and ``run_id`` of a run (module docstring).

    Parameters
    ----------
    config_hash : str
        :func:`~.config.config_hash` of the single-run config.
    eventset_checksum : str
        ``content_hash()`` of the EventSet as loaded.
    package_version : str, optional
        Default: the installed ``parametric-insurance-design`` version.
    policy : SolverPolicy, optional
        Solver policy of the run.

    Returns
    -------
    str
        ``"sha256:"`` and 64 lowercase hex digits.
    """
    payload = {
        "config_hash": config_hash,
        "eventset_checksum": eventset_checksum,
        "package_version": (
            _package_version() if package_version is None else package_version
        ),
        "solver_policy": policy_fingerprint(policy),
    }
    data = RUN_KEY_DOMAIN.encode("utf-8") + b"\0" + _canonical(payload).encode("ascii")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def run_parameters(config: ExperimentConfig, eventset: EventSet) -> dict[str, Any]:
    """Return the scalar parameters of a single run (``runs.parameters``).

    Keys that name a sweep parameter (:data:`~.config.SWEEP_PARAMETERS`) use
    that name, so a sweep's ``runs`` rows can be read without parsing the
    config. A key is present only when its component is configured.

    ``below_attachment`` (MAR-178) is present only when the payout's mode is
    not the default ``"first_bin"``, i.e. for ``"zero"`` (MAR-170), so that
    readers of the ``runs`` table, such as the viz payout figures, can tell
    what the payout pays below the attachment. A run without the key pays
    the first bin's level there. Leaving the default out keeps the stored
    parameters of every ``"first_bin"`` run as they were before MAR-178 (the
    MAR-131/MAR-170 pattern). The parameters are not part of :func:`run_key`,
    so no run id changes either way.

    Parameters
    ----------
    config : ExperimentConfig
        A single-run config.
    eventset : EventSet
        The prepared EventSet (for ``n_assets``).

    Returns
    -------
    dict
        ``attachment``, ``limit``, ``n_bins``, ``n_assets``,
        ``evaluation_beta``, ``sample``; ``below_attachment`` (``"zero"``
        payout); ``train_fraction`` (holdout);
        ``k``, ``fold`` (k-fold); ``n_clusters``, ``beta_tail``, ``linkage``
        (cluster scope); ``scope_index`` (if set); ``alpha``, ``beta`` (weighted CVaR);
        ``pricing_rate``, ``pricing_q`` (cost of capital); ``budget_loading``
        (budget); ``noise_kind``, ``noise_level``, ``n_copies``,
        ``noise_seed``, ``noise_low``, ``noise_high`` (noise); ``threshold``,
        ``threshold_column`` (threshold).
    """
    payout = config.payout
    params: dict[str, Any] = {
        "attachment": payout.attachment,
        "limit": payout.limit,
        "n_bins": payout.n_bins,
        "n_assets": eventset.n_locations,
        "evaluation_beta": config.evaluation.beta,
        "sample": config.sample.kind,
    }
    if payout.below_attachment != "first_bin":
        params["below_attachment"] = payout.below_attachment
    sample = config.sample
    if sample.kind == "holdout":
        params["train_fraction"] = sample.train_fraction
    elif sample.kind == "kfold":
        params["k"] = sample.k
        params["fold"] = sample.fold
    for scope in config.scopes:
        if scope.index is not None:
            params["scope_index"] = scope.index
        if scope.kind == "cluster":
            params["n_clusters"] = scope.n_clusters
            params["beta_tail"] = scope.strategy.beta_tail
            params["linkage"] = scope.strategy.linkage
    for objective in config.objectives:
        if objective.kind == "weighted_cvar":
            params["alpha"] = objective.alpha
            params["beta"] = objective.beta
    pricing = config.pricing
    if pricing.kind == "cost_of_capital":
        params["pricing_rate"] = pricing.rate
        params["pricing_q"] = pricing.q
    for constraint in config.constraints:
        if constraint.kind == "budget":
            params["budget_loading"] = constraint.loading
    if config.noise is not None:
        noise = config.noise
        params.update(
            noise_kind=noise.kind,
            noise_level=noise.level,
            n_copies=noise.n_copies,
            noise_seed=noise.seed,
            noise_low=noise.bounds[0],
            noise_high=noise.bounds[1],
        )
    if config.threshold is not None:
        params["threshold"] = config.threshold.value
        params["threshold_column"] = config.threshold.column
    return params


def package_versions() -> dict[str, str | None]:
    """Return the installed versions of :data:`PROVENANCE_PACKAGES`.

    Returns
    -------
    dict
        Distribution name to version, None if it is not installed (e.g.
        ``highspy`` with cvxpy < 1.8).
    """
    out: dict[str, str | None] = {}
    for name in PROVENANCE_PACKAGES:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None
    return out


def _json_number(value: float) -> float | None:
    """Return a finite float, or None (JSON has no NaN or infinity)."""
    number = float(value)
    return number if math.isfinite(number) else None


# --------------------------------------------------------------------------
# Execution
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class RunOutcome:
    """Summary of one run, executed or found in the cache.

    Parameters
    ----------
    run_id : str
        The run's id (cache key).
    config_hash : str
        Hash of the single-run config.
    eventset_checksum : str
        Content hash of the input EventSet.
    source : str
        ``runs.source`` tag the run was written with.
    cached : bool
        True if the run was already in the store and was not executed.
    statuses : mapping of str to SolveStatus
        Status per design problem (``"*"`` for a build failure).
    failed : tuple of str
        Design problems without an accepted result, in run order. A status
        alone does not tell: ``optimal_inaccurate`` is a failure when the
        solver policy refuses it.
    evaluated : bool
        Whether KPIs and exceedance curves were written.
    """

    run_id: str
    config_hash: str
    eventset_checksum: str
    source: str
    cached: bool
    statuses: Mapping[str, SolveStatus] = field(default_factory=dict)
    failed: tuple[str, ...] = ()
    evaluated: bool = False

    @property
    def ok(self) -> bool:
        """True if every design problem was solved and the run evaluated."""
        return not self.failed and self.evaluated

    @classmethod
    def from_manifest(cls, manifest: Mapping[str, Any], *, cached: bool) -> RunOutcome:
        """Summarise a run from its manifest.

        Parameters
        ----------
        manifest : mapping
            A manifest written by :func:`execute`.
        cached : bool
            Whether the run came from the cache.

        Returns
        -------
        RunOutcome
            The summary.
        """
        key = manifest["cache_key"]
        return cls(
            run_id=manifest["run_id"],
            config_hash=key["config_hash"],
            eventset_checksum=key["eventset_checksum"],
            source=manifest["source"],
            cached=cached,
            statuses={
                p["problem_id"]: SolveStatus(p["status"]) for p in manifest["problems"]
            },
            failed=tuple(
                p["problem_id"]
                for p in manifest["problems"]
                if p["error_type"] is not None
            ),
            evaluated=bool(manifest["evaluation"]["evaluated"]),
        )


def _check_single(config: ExperimentConfig) -> None:
    """Refuse a config with several scopes or objectives."""
    if len(config.scopes) != 1 or len(config.objectives) != 1:
        raise ConfigError(
            "a run has one scope and one objective; got "
            f"{len(config.scopes)} scopes and {len(config.objectives)} objectives "
            "(use ExperimentConfig.single_runs() or run_config())"
        )


def _samples(
    config: ExperimentConfig, eventset: EventSet
) -> tuple[Sample, tuple[Sample, ...]]:
    """Calibration sample and evaluation samples of a run."""
    sample = config.sample
    if sample.kind == "full":
        full = Sample.full(eventset)
        return full, (full,)
    if sample.kind == "holdout":
        train, test = splits.holdout(eventset, train_fraction=sample.train_fraction)
        return train, (train, test)
    if sample.fold is None:
        raise ConfigError(
            "a k-fold run needs sample.fold: each fold is a run of its own "
            "(use ExperimentConfig.single_runs() or run_config())"
        )
    train, test = splits.year_block_kfold(eventset, k=sample.k)[sample.fold]
    return train, (train, test)


def _undefined_counts(table: pd.DataFrame) -> dict[str, int]:
    """``{"level/subject_id/kpi": n_undefined}`` of ``KpiBootstrap.n_undefined``."""
    return {
        f"{level}/{subject}/{kpi}": int(n)
        for level, subject, kpi, n in zip(
            table["level"],
            table["subject_id"],
            table["kpi"],
            table["n_undefined"],
            strict=True,
        )
    }


def _attempts(attempts: tuple[SolverAttempt, ...]) -> list[dict[str, Any]]:
    """Solver attempts as JSON values."""
    return [
        {
            "solver": a.solver,
            "status": SolveStatus(a.status).value,
            "seconds": _json_number(a.seconds),
            "message": a.message,
        }
        for a in attempts
    ]


_NO_TAIL_RECORD: Final[Mapping[str, Any]] = {
    "p_zero_loss": None,
    "tail_outcomes": None,
    "degenerate_tail": None,
}
"""Tail record of a run-level failure (``problem_id = "*"``): no measure."""


def _tail_record(problem: BuiltProblem, objective: Objective) -> dict[str, Any]:
    """Return a design problem's ``p_zero_loss``, ``tail_outcomes`` and flag.

    See the module docstring, "Degenerate tail objectives".

    Parameters
    ----------
    problem : BuiltProblem
        The design problem, built on the calibration sample.
    objective : Objective
        The run's objective.

    Returns
    -------
    dict
        ``p_zero_loss`` (float), ``tail_outcomes`` (float, or None if the
        objective is not :class:`~parametric_insurance_design.objectives.WeightedCVaR`)
        and ``degenerate_tail`` (one of :data:`DEGENERATE_TAILS`, or None).
    """
    measure = problem.context.measure
    # Unscaled losses are >= 0, so an outcome sum is 0 only if every row is 0.
    outcome_loss = measure.aggregate(problem.context.problem.loss)
    p_zero = float(measure.probability[outcome_loss == 0.0].sum())
    record: dict[str, Any] = {
        "p_zero_loss": p_zero,
        "tail_outcomes": None,
        "degenerate_tail": None,
    }
    if not isinstance(objective, WeightedCVaR):
        return record
    positive = measure.probability[measure.probability > 0.0]
    tail = (1.0 - objective.beta) / float(positive.min())
    record["tail_outcomes"] = tail
    if objective.beta <= p_zero + DEGENERATE_TAIL_ATOL:
        record["degenerate_tail"] = DEGENERATE_TAIL_EXPECTED_UNCOVERED
    elif tail <= 1.0 + DEGENERATE_TAIL_ATOL:
        record["degenerate_tail"] = DEGENERATE_TAIL_SINGLE_OUTCOME
    return record


def execute(
    config: ExperimentConfig,
    data: RunInput,
    *,
    source: str = SINGLE_RUN_SOURCE,
    policy: SolverPolicy = DEFAULT_POLICY,
) -> tuple[RunTables, dict[str, Any]]:
    """Execute one run without touching a store.

    Parameters
    ----------
    config : ExperimentConfig
        A single-run config (one scope, one objective).
    data : RunInput
        The EventSet as loaded, with its checksum.
    source : str, default "single_run"
        ``runs.source`` tag, e.g. ``"alpha_sweep"``.
    policy : SolverPolicy, optional
        Solver policy.

    Returns
    -------
    tables : RunTables
        The run's records.
    manifest : dict
        The run's provenance (JSON values).

    Raises
    ------
    ConfigError
        If the config has several scopes or objectives, or a k-fold sample
        without ``fold``.
    ChecksumMismatchError
        If the config pins a checksum that ``data`` does not have.
    EventSetError
        If preparing the EventSet fails (e.g. an unknown location).
    """
    _check_single(config)
    _check_checksum(
        data.checksum, config.eventset.checksum, where=str(data.path or "the input")
    )
    start = time.perf_counter()
    created_at = datetime.now(UTC)
    package_version = _package_version()
    chash = config_hash(config)
    run_id = run_key(
        chash, data.checksum, package_version=package_version, policy=policy
    )

    prepared = prepare_eventset(config, data.eventset)
    prepared_hash = prepared.content_hash()
    prepare_seconds = time.perf_counter() - start
    calibration, evaluation_samples = _samples(config, prepared)
    components = config.to_components()
    scope, objective = components.scopes[0], components.objectives[0]
    params = run_parameters(config, prepared)

    base = {
        "run_id": run_id,
        "config_hash": chash,
        "source": source,
        "scope": scope.name,
        "objective": objective.name,
        "pricing": components.pricing.name,
        "payout": components.payout.name,
        "basis": components.basis.value,
        "calibration_split": calibration.name,
        "fold": calibration.fold,
        "parameters": _canonical(params),
        "eventset_checksum": data.checksum,
        "package_version": package_version,
        "created_at": created_at,
    }
    runs: list[dict[str, Any]] = []
    problems: list[dict[str, Any]] = []
    entity_rows: list[dict[str, Any]] = []
    payout_rows: list[dict[str, Any]] = []
    results: list[SolveResult] = []

    build_start = time.perf_counter()
    built: tuple[BuiltProblem, ...] = ()
    try:
        built = build_problems(
            prepared,
            scope,
            components.payout,
            objective,
            components.pricing,
            components.constraints,
            basis=components.basis,
            sample=calibration,
        )
    except ParametricInsuranceDesignError as exc:
        seconds = time.perf_counter() - build_start
        _log.warning("run %s: building failed: %s", run_id, exc)
        runs.append(_failure_row(base, ALL_PROBLEMS, SolveStatus.ERROR, exc, seconds))
        problems.append(
            _problem_log(
                ALL_PROBLEMS,
                SolveStatus.ERROR,
                tail=_NO_TAIL_RECORD,
                exc=exc,
                build=seconds,
            )
        )
    build_seconds = time.perf_counter() - build_start

    solve_start = time.perf_counter()
    for problem in built:
        spec = problem.spec
        tail = _tail_record(problem, objective)
        if tail["degenerate_tail"] is not None:
            _log.info(
                "run %s, problem %s: degenerate tail (%s): beta %s, "
                "P(L_o = 0) %.6g, tail outcomes %.6g",
                run_id,
                spec.problem_id,
                tail["degenerate_tail"],
                getattr(objective, "beta", None),
                tail["p_zero_loss"],
                tail["tail_outcomes"],
            )
        entity_rows.extend(
            {
                "run_id": run_id,
                "problem_id": spec.problem_id,
                "entity_id": entity.entity_id,
                "location_id": location_id,
            }
            for entity in spec.entities
            for location_id in entity.location_ids
        )
        try:
            # The problem carries the run's pricing (MAR-171), so the premium
            # is pricing.premium_value of the realised payout (MAR-143).
            result = solve(problem, policy)
        except SolveError as exc:
            _log.warning("run %s: %s", run_id, exc)
            runs.append(
                _failure_row(
                    base, spec.problem_id, exc.status, exc, problem.build_seconds
                )
            )
            problems.append(
                _problem_log(
                    spec.problem_id,
                    exc.status,
                    tail=tail,
                    exc=exc,
                    build=problem.build_seconds,
                )
            )
            continue
        results.append(result)
        runs.append(_success_row(base, result))
        problems.append(
            _problem_log(spec.problem_id, result.status, tail=tail, result=result)
        )
        lower, upper = result.payout_structure.parameter_bounds()
        payout_rows.extend(
            {
                "run_id": run_id,
                "problem_id": result.problem_id,
                "entity_id": entity_id,
                "param_index": k,
                "lower": float(lower[k]),
                "upper": float(upper[k]),
                "value": float(result.theta[j, k]),
            }
            for j, entity_id in enumerate(result.entity_ids)
            for k in range(result.payout_structure.n_params)
        )
    solve_seconds = time.perf_counter() - solve_start

    evaluate_start = time.perf_counter()
    kpi_frames: list[pd.DataFrame] = []
    curve_frames: list[pd.DataFrame] = []
    skipped: str | None = None
    bootstrap_log: list[dict[str, Any]] = []
    if not built:
        skipped = "building the design problems failed"
    elif len(results) != len(built):
        skipped = (
            f"{len(built) - len(results)} of {len(built)} design problems "
            "failed; KPIs need every design problem"
        )
    else:
        for sample in evaluation_samples:
            if config.bootstrap is None:
                kpi_frames.append(
                    kpis(
                        prepared,
                        scope,
                        results,
                        basis=components.basis,
                        beta=config.evaluation.beta,
                        run_id=run_id,
                        sample=sample,
                        pricing=components.pricing,
                    )
                )
            else:
                boot_start = time.perf_counter()
                boot = bootstrap_kpis(
                    prepared,
                    scope,
                    results,
                    basis=components.basis,
                    beta=config.evaluation.beta,
                    run_id=run_id,
                    resample=resample_years(
                        sample.years,
                        config.bootstrap.n_bootstrap,
                        config.bootstrap.rng(),
                    ),
                    sample=sample,
                    pricing=components.pricing,
                    level=config.bootstrap.level,
                )
                kpi_frames.append(boot.table)
                bootstrap_log.append(
                    {
                        "sample": sample.name,
                        "fold": sample.fold,
                        "n_without_bounds": int(
                            np.isnan(boot.table["ci_low"].to_numpy(np.float64)).sum()
                        ),
                        "n_undefined": _undefined_counts(boot.n_undefined),
                        "seconds": time.perf_counter() - boot_start,
                    }
                )
            curve_frames.append(
                exceedance_curves(
                    prepared,
                    scope,
                    results,
                    basis=components.basis,
                    run_id=run_id,
                    return_periods=config.evaluation.return_periods,
                    sample=sample,
                )
            )
    evaluate_seconds = time.perf_counter() - evaluate_start

    tables = RunTables(
        runs=RUNS.from_rows(runs),
        entities=ENTITIES.from_rows(entity_rows),
        payouts=PAYOUTS.from_rows(payout_rows),
        kpis=pd.concat(kpi_frames, ignore_index=True) if kpi_frames else KPIS.empty(),
        exceedance=(
            pd.concat(curve_frames, ignore_index=True)
            if curve_frames
            else EXCEEDANCE.empty()
        ),
    )
    metadata = prepared.metadata.to_dict()
    manifest: dict[str, Any] = {
        "format": MANIFEST_FORMAT,
        "run_id": run_id,
        "source": source,
        "created_at": created_at.isoformat(),
        "cache_key": {
            "domain": RUN_KEY_DOMAIN,
            "config_hash": chash,
            "eventset_checksum": data.checksum,
            "package_version": package_version,
            "solver_policy": policy_fingerprint(policy),
        },
        "config": to_dict(config),
        "parameters": params,
        "input": {
            "path": None if data.path is None else str(data.path),
            "content_hash": data.checksum,
            "n_rows": data.eventset.n_rows,
            "n_locations": data.eventset.n_locations,
        },
        "prepared_eventset": {
            "content_hash": prepared_hash,
            "n_rows": prepared.n_rows,
            "n_locations": prepared.n_locations,
            "n_years": prepared.metadata.n_years,
            "location_ids": list(prepared.location_ids),
            "transforms": metadata["transforms"],
            "filters": metadata["filters"],
        },
        "samples": {
            "calibration": {"name": calibration.name, "fold": calibration.fold},
            "evaluation": [
                {"name": s.name, "fold": s.fold} for s in evaluation_samples
            ],
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": package_versions(),
        },
        "problems": problems,
        "evaluation": {
            "evaluated": skipped is None,
            "skipped_reason": skipped,
            "beta": config.evaluation.beta,
        },
        "bootstrap": (
            None
            if config.bootstrap is None
            else {
                "seed": config.bootstrap.seed,
                "n_bootstrap": config.bootstrap.n_bootstrap,
                "level": config.bootstrap.level,
                "samples": bootstrap_log,
            }
        ),
        "timings": {
            "load_seconds": data.load_seconds,
            "prepare_seconds": prepare_seconds,
            "build_seconds": build_seconds,
            "solve_seconds": solve_seconds,
            "evaluate_seconds": evaluate_seconds,
            "total_seconds": time.perf_counter() - start,
        },
    }
    return tables, manifest


def _error_attempts(exc: Exception | None) -> tuple[SolverAttempt, ...]:
    """Return the solver attempts of a :class:`SolveError`; none otherwise."""
    return exc.attempts if isinstance(exc, SolveError) else ()


def _failure_row(
    base: Mapping[str, Any],
    problem_id: str,
    status: SolveStatus,
    exc: Exception,
    build_seconds: float | None,
) -> dict[str, Any]:
    """Return the ``runs`` row of a failed design problem (or a failed build)."""
    attempts = _error_attempts(exc)
    return {
        **base,
        "problem_id": problem_id,
        "status": SolveStatus(status).value,
        "solver": None,
        "objective_value": None,
        "premium": None,
        "build_seconds": build_seconds,
        "solve_seconds": sum(a.seconds for a in attempts) if attempts else None,
        "error_type": type(exc).__name__,
        "error_message": str(exc),
    }


def _success_row(base: Mapping[str, Any], result: SolveResult) -> dict[str, Any]:
    """Return the ``runs`` row of a solved design problem."""
    return {
        **base,
        "problem_id": result.problem_id,
        "status": result.status.value,
        "solver": result.solver,
        "objective_value": result.objective_value,
        "premium": result.premium,
        "build_seconds": result.build_seconds,
        "solve_seconds": result.solve_seconds,
        "error_type": None,
        "error_message": None,
    }


def _problem_log(
    problem_id: str,
    status: SolveStatus,
    *,
    tail: Mapping[str, Any],
    result: SolveResult | None = None,
    exc: Exception | None = None,
    build: float | None = None,
) -> dict[str, Any]:
    """Manifest entry of one design problem: status, attempts, diagnostics.

    ``tail`` (:func:`_tail_record`) adds ``p_zero_loss``, ``tail_outcomes``
    and ``degenerate_tail`` (MAR-173).
    """
    if result is not None:
        return {
            "problem_id": problem_id,
            "status": SolveStatus(status).value,
            "solver": result.solver,
            "scale": result.scale,
            "objective_value": result.objective_value,
            "premium": result.premium,
            "build_seconds": result.build_seconds,
            "solve_seconds": result.solve_seconds,
            "attempts": _attempts(result.attempts),
            "diagnostics": {
                k: _json_number(v) for k, v in sorted(result.diagnostics.items())
            },
            "error_type": None,
            "error_message": None,
            **tail,
        }
    attempts = _error_attempts(exc)
    return {
        "problem_id": problem_id,
        "status": SolveStatus(status).value,
        "solver": None,
        "scale": None,
        "objective_value": None,
        "premium": None,
        "build_seconds": build,
        "solve_seconds": sum(a.seconds for a in attempts) if attempts else None,
        "attempts": _attempts(attempts),
        "diagnostics": {},
        "error_type": type(exc).__name__,
        "error_message": str(exc),
        **tail,
    }


def run_single(
    config: ExperimentConfig,
    data: RunInput,
    store: ResultStore,
    *,
    source: str = SINGLE_RUN_SOURCE,
    policy: SolverPolicy = DEFAULT_POLICY,
    force: bool = False,
    retry_failed: bool = False,
) -> RunOutcome:
    """Run one single-run config, unless the store already holds it.

    This is the entry point for sweeps: one call per sweep point, with the
    point's config (``with_parameter``, ``with_locations``, then
    ``single_runs()``) and a :class:`RunInput` shared by every point.

    Parameters
    ----------
    config : ExperimentConfig
        A single-run config (one scope, one objective).
    data : RunInput
        The EventSet as loaded, with its checksum.
    store : ResultStore
        Where the run is looked up and written.
    source : str, default "single_run"
        ``runs.source`` tag for a newly executed run.
    policy : SolverPolicy, optional
        Solver policy; part of the cache key.
    force : bool, default False
        Execute and overwrite even if the run is cached.
    retry_failed : bool, default False
        Execute and overwrite a cached run that has a failed design problem
        or was not evaluated.

    Returns
    -------
    RunOutcome
        ``cached=True`` if the store already held the run.

    Raises
    ------
    ConfigError, ChecksumMismatchError, EventSetError
        As for :func:`execute`.
    StoreError
        If the store cannot be read or written.
    """
    _check_single(config)
    _check_checksum(
        data.checksum, config.eventset.checksum, where=str(data.path or "the input")
    )
    run_id = run_key(config_hash(config), data.checksum, policy=policy)
    exists = store.has_run(run_id)
    if exists and not force:
        outcome = RunOutcome.from_manifest(store.manifest(run_id), cached=True)
        if not (retry_failed and not outcome.ok):
            _log.info("run %s: cached in %s", run_id, store.root)
            return outcome
    tables, manifest = execute(config, data, source=source, policy=policy)
    store.write_run(tables, manifest, overwrite=exists)
    outcome = RunOutcome.from_manifest(manifest, cached=False)
    _log.info(
        "run %s: %s x %s, %d problems, %d failed, written to %s",
        run_id,
        tables.runs["scope"].iloc[0],
        tables.runs["objective"].iloc[0],
        len(outcome.statuses),
        len(outcome.failed),
        store.root,
    )
    return outcome


def run_config(
    config: ExperimentConfig,
    *,
    store: ResultStore | None = None,
    data: RunInput | None = None,
    source: str = SINGLE_RUN_SOURCE,
    policy: SolverPolicy = DEFAULT_POLICY,
    force: bool = False,
    retry_failed: bool = False,
) -> tuple[RunOutcome, ...]:
    """Run every scope x objective of a config (not its sweeps).

    Parameters
    ----------
    config : ExperimentConfig
        The config; its ``sweeps`` are ignored (MAR-65 runs them).
    store : ResultStore, optional
        Default: ``ResultStore(config.output.directory)``.
    data : RunInput, optional
        Default: :func:`load_input` of the config.
    source : str, default "single_run"
        ``runs.source`` tag.
    policy : SolverPolicy, optional
        Solver policy.
    force, retry_failed : bool, default False
        As for :func:`run_single`.

    Returns
    -------
    tuple of RunOutcome
        One per ``config.single_runs()`` entry, in that order.
    """
    store = ResultStore(config.output.directory) if store is None else store
    data = load_input(config) if data is None else data
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
        for single in config.single_runs()
    )
