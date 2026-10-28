"""Pooled out-of-sample KPIs of a k-fold experiment (SPEC §6.1, MAR-151).

Owner: MAR-151. A k-fold experiment stores a run per scope x objective x
fold (MAR-22, ADR 0002 §7 amendment MAR-138), so each scope x objective has
``k`` out-of-sample KPI values, each over ``1/k`` of the years. This module
combines the folds into one out-of-sample KPI per scope x objective, computed
on demand from the result store; nothing is written to the store and no
record table changes (MAR-151 "option A"). Method notes:
``docs/methodology/out-of-sample.md``.

The pooled rule
    * The ``k`` test blocks of ``splits.year_block_kfold`` partition the
      years, so every row (and every year) is evaluated by exactly one
      design: the one calibrated on the other ``k - 1`` blocks.
    * The **pooled payout** of a row is that design's portfolio payout. With
      the row's portfolio loss it forms one out-of-sample sample over **all**
      years, and the pooled KPIs are the ``evaluate`` KPIs of that sample on
      the evaluation measure of all years (``Sample.full``).
    * Only the **portfolio level** is pooled. Entity and design-problem
      subjects are not comparable across folds: the cluster scope's partition
      differs per fold, so "cluster C1" of fold 0 is not that of fold 1.
    * **Paired intervals.** One ``bootstrap.resample_years(all_years, B,
      default_rng(seed))`` (the config's ``bootstrap`` section) is drawn
      once and shared by every design, so differences between designs are
      paired (:func:`pooled_difference`). The replicates are
      ``bootstrap.kpi_replicates`` of the pooled loss and payout, and the
      intervals ``bootstrap.percentile_interval``.
    * **Rejected: the mean of the per-fold KPIs.** A tail KPI (VaR, CVaR)
      from ``1/k`` of the years is noisier than one from all years, and the
      mean of ``k`` CVaRs is not the CVaR of any distribution.

Without re-solving
    Each fold's design is read from the store: ``entities`` gives its
    ``ProblemSpec`` objects, ``payouts`` its levels ``theta``; the payout
    structure, scope, basis and pricing come from the config. A row's test
    payout is ``payout.evaluate(scope.materialise(test_data,
    spec).index, theta)`` on the prepared EventSet split with
    ``splits.year_block_kfold``. Nothing is solved.

No silent failures
    * **Drift guard.** Each fold's portfolio KPIs on its test block are
      recomputed from those payouts and compared with the ``kpis`` rows the
      runner stored (``eval_split = "test"``); a mismatch raises
      :class:`FoldDriftError`. So are stored bin edges that differ from the
      config's payout structure, and a prepared EventSet whose content hash
      differs from the runs' manifests.
    * A run that is not in the store, or a run that is not the expected fold
      of the expected scope x objective (its config hash, sample, ``k``,
      fold, scope and objective are checked), raises
      :class:`PooledKFoldError`.
    * A scope x objective with a failed fold (a failed design problem, so no
      KPIs) is not pooled; it is listed in :attr:`PooledKpis.failed` with the
      reason, never dropped quietly.
    * A KPI undefined in some replicate gets null bounds, with ``ci_level``
      and ``n_bootstrap`` set (as in the ``kpis`` table);
      :attr:`PooledKpis.n_undefined` counts its undefined replicates.
    * The pooled ``premium`` has no interval (``ci_level`` null): the
      bootstrap module replicates premiums only inside ``bootstrap_kpis``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from parametric_insurance_design import splits
from parametric_insurance_design.basis import Basis, OutcomeMeasure, outcome_measure
from parametric_insurance_design.bootstrap import (
    YearResample,
    kpi_replicates,
    percentile_interval,
    resample_years,
)
from parametric_insurance_design.errors import InputMismatchError
from parametric_insurance_design.evaluate import PORTFOLIO_SUBJECT, var_cvar
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import (
    Entity,
    PayoutStructure,
    Pricing,
    ProblemSpec,
    Sample,
    Scope,
)
from parametric_insurance_design.records import (
    ALL_PROBLEMS,
    KpiLevel,
    KpiName,
    Split,
)

__all__ = [
    "KFOLD_SAMPLE",
    "POOLED_COLUMNS",
    "POOLED_KPIS",
    "POOLED_SPLIT",
    "FoldDriftError",
    "PooledDesign",
    "PooledFailure",
    "PooledKFoldError",
    "PooledKpis",
    "pooled_designs",
    "pooled_difference",
    "pooled_kpis",
]

KFOLD_SAMPLE: Final[str] = "kfold"
"""``sample.kind`` of a k-fold config."""

POOLED_SPLIT: Final[str] = "pooled"
"""``eval_split`` of the pooled rows: out of sample, every fold's test block.

Not a ``records.Split`` value: pooled rows are never written to the store."""

POOLED_KPIS: Final[tuple[KpiName, ...]] = (
    KpiName.EXPECTED_LOSS,
    KpiName.EXPECTED_PAYOUT,
    KpiName.EXPECTED_UNCOVERED,
    KpiName.VAR_UNCOVERED,
    KpiName.CVAR_UNCOVERED,
    KpiName.RMSE_RESIDUAL,
    KpiName.PAYOUT_TO_LOSS_RATIO,
    KpiName.CORRELATION,
    KpiName.PREMIUM,
)
"""KPIs of every pooled design, in table order: ``evaluate.kpis``'s portfolio
KPIs."""

POOLED_COLUMNS: Final[tuple[str, ...]] = (
    "scope_position",
    "scope",
    "objective",
    "run_ids",
    "k",
    "n_years",
    "eval_split",
    "basis",
    "problem_id",
    "level",
    "subject_id",
    "kpi",
    "beta",
    "value",
    "ci_low",
    "ci_high",
    "ci_level",
    "n_bootstrap",
)
"""Columns of :attr:`PooledKpis.table`.

``scope_position`` is the scope's position in ``config.scopes`` (several
scopes may share a kind); ``run_ids`` the fold runs, fold ``0 .. k - 1``,
joined by ``";"``; ``eval_split`` is :data:`POOLED_SPLIT`; ``level`` and
``subject_id`` are ``"portfolio"``; ``problem_id`` is the folds' portfolio
``problem_id`` (``"*"`` for several design problems). The other columns are
those of the ``kpis`` table."""

_BETA_KPIS: Final[frozenset[KpiName]] = frozenset(
    {KpiName.VAR_UNCOVERED, KpiName.CVAR_UNCOVERED}
)

_DRIFT_RTOL: Final[float] = 1e-9
"""Relative tolerance of the drift guard (as ``bootstrap``'s point check)."""

_DRIFT_ATOL: Final[float] = 1e-9
"""Absolute tolerance of the drift guard, loss units."""

_BOUND_RTOL: Final[float] = 1e-12
"""Relative tolerance of the stored bin edges against the payout structure."""


class PooledKFoldError(InputMismatchError):
    """Pooled k-fold KPIs cannot be formed from the config and the store.

    Raised for a config that is not a k-fold experiment over every fold, a
    run missing from the store, or runs that are not the expected folds.
    """


class FoldDriftError(PooledKFoldError):
    """A fold's design, rebuilt from the store, does not reproduce the run.

    The drift guard: a fold's portfolio KPIs on its test block, recomputed
    from the stored design, differ from the stored ``kpis`` rows; or the
    stored bin edges differ from the config's payout structure; or the
    EventSet is not the runs' prepared EventSet.
    """


def _where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    """Return the rows of ``frame`` where ``mask`` is true."""
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class PooledDesign:
    """One scope x objective of a k-fold experiment, pooled over its folds.

    Parameters
    ----------
    scope_position : int
        Position of the scope in ``config.scopes``.
    scope, objective : str
        Component names (``runs.scope``, ``runs.objective``).
    run_ids : tuple of str
        The fold runs, fold ``0 .. k - 1``.
    problem_id : str
        The folds' portfolio ``problem_id``.
    fold : numpy.ndarray of int
        The fold that evaluates each row of the prepared EventSet.
    loss : numpy.ndarray of float
        Portfolio loss of each row.
    payout : numpy.ndarray of float
        Pooled portfolio payout of each row: the payout of the design
        calibrated without the row's year block.
    """

    scope_position: int
    scope: str
    objective: str
    run_ids: tuple[str, ...]
    problem_id: str
    fold: NDArray[np.int64]
    loss: NDArray[np.float64]
    payout: NDArray[np.float64]


@dataclass(frozen=True)
class PooledFailure:
    """A scope x objective that is not pooled because a fold failed.

    Parameters
    ----------
    scope_position : int
        Position of the scope in ``config.scopes``.
    scope, objective : str
        Component names.
    run_ids : tuple of str
        The fold runs, fold ``0 .. k - 1``.
    reason : str
        Which folds failed, and how.
    """

    scope_position: int
    scope: str
    objective: str
    run_ids: tuple[str, ...]
    reason: str


@dataclass(frozen=True, eq=False)
class PooledKpis:
    """Pooled out-of-sample portfolio KPIs of a k-fold experiment.

    Attributes
    ----------
    table : pandas.DataFrame
        Columns :data:`POOLED_COLUMNS`: per pooled design (config order:
        scope-major, then objective) the KPIs :data:`POOLED_KPIS`.
    replicates : numpy.ndarray or None
        Shape ``(len(table), B)``: row ``i`` holds the bootstrap replicates
        of ``table.iloc[i]`` (NaN where undefined, and on the ``premium``
        rows, which are not bootstrapped). None without a ``bootstrap``
        section in the config.
    resample : YearResample or None
        The one resample of all years shared by every design.
    level : float or None
        Confidence level of the intervals.
    k : int
        Number of folds.
    failed : tuple of PooledFailure
        Scope x objective combinations that are not pooled.
    """

    table: pd.DataFrame
    replicates: NDArray[np.float64] | None
    resample: YearResample | None
    level: float | None
    k: int
    failed: tuple[PooledFailure, ...] = ()

    @property
    def n_undefined(self) -> pd.DataFrame:
        """Bootstrapped rows with undefined replicates, and how many.

        Returns
        -------
        pandas.DataFrame
            ``scope_position``, ``scope``, ``objective``, ``kpi`` and
            ``n_undefined`` (> 0); empty without replicates.
        """
        columns = ["scope_position", "scope", "objective", "kpi"]
        if self.replicates is None:
            return pd.DataFrame(columns=[*columns, "n_undefined"])
        bootstrapped = self.table["ci_level"].notna().to_numpy()
        counts = np.isnan(self.replicates).sum(axis=1)
        keep = bootstrapped & (counts > 0)
        out = self.table.loc[keep, columns].reset_index(drop=True)
        out["n_undefined"] = counts[keep].astype(np.int64)
        return out


# --------------------------------------------------------------------------
# Reading the folds' designs
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False)
class _Fold:
    """One fold run of a scope x objective, as stored."""

    run_id: str
    fold: int
    runs: pd.DataFrame
    entities: pd.DataFrame
    payouts: pd.DataFrame
    kpis: pd.DataFrame
    prepared_hash: str

    def failure(self) -> str | None:
        """Why the run has no complete design, or None."""
        bad = _where(self.runs, self.runs["error_type"].notna())
        if bad.empty:
            if self.kpis.empty:
                return f"fold {self.fold} ({self.run_id}) was not evaluated"
            return None
        problems = ", ".join(
            f"{p} ({e})"
            for p, e in zip(bad["problem_id"], bad["error_type"], strict=True)
        )
        return f"fold {self.fold} ({self.run_id}) failed for {problems}"

    def specs(self) -> tuple[ProblemSpec, ...]:
        """Rebuild the fold's design problems, in the order the runner wrote them."""
        specs: list[ProblemSpec] = []
        for problem_id, rows in self.entities.groupby("problem_id", sort=False):
            entities = tuple(
                Entity(str(entity_id), tuple(str(x) for x in group["location_id"]))
                for entity_id, group in rows.groupby("entity_id", sort=False)
            )
            specs.append(ProblemSpec(problem_id=str(problem_id), entities=entities))
        return tuple(specs)

    def theta(self, spec: ProblemSpec, payout: PayoutStructure) -> NDArray[np.float64]:
        """Return the stored levels of a design problem, shape (entities, params).

        Raises
        ------
        FoldDriftError
            If the stored parameters do not fit the payout structure.
        """
        rows = _where(self.payouts, self.payouts["problem_id"] == spec.problem_id)
        n_params = payout.n_params
        lower, upper = payout.parameter_bounds()
        theta = np.empty((len(spec.entities), n_params), dtype=np.float64)
        for j, entity_id in enumerate(spec.entity_ids):
            entity = _where(rows, rows["entity_id"] == entity_id).sort_values(
                "param_index"
            )
            index = entity["param_index"].to_numpy(dtype=np.int64)
            if not np.array_equal(index, np.arange(n_params)):
                raise FoldDriftError(
                    f"run {self.run_id}: entity {entity_id!r} of problem "
                    f"{spec.problem_id!r} has parameters {index.tolist()}, the "
                    f"config's payout structure {n_params}"
                )
            for name, stored, expected in (
                ("lower", entity["lower"], lower),
                ("upper", entity["upper"], upper),
            ):
                if not np.allclose(
                    stored.to_numpy(dtype=np.float64),
                    expected,
                    rtol=_BOUND_RTOL,
                    atol=0.0,
                ):
                    raise FoldDriftError(
                        f"run {self.run_id}: the stored bin edges ({name}) of "
                        f"{spec.problem_id!r}/{entity_id!r} differ from the "
                        "config's payout structure"
                    )
            theta[j] = entity["value"].to_numpy(dtype=np.float64)
        return theta


def _check_config(config: ExperimentConfig) -> int:
    """Return ``k`` of a k-fold config over every fold.

    Raises
    ------
    PooledKFoldError
        If the sample is not ``kfold``, or fixes one fold.
    """
    sample = config.sample
    if sample.kind != KFOLD_SAMPLE:
        raise PooledKFoldError(
            f"config {config.name!r} has a {sample.kind!r} sample; pooled "
            "out-of-sample KPIs need a k-fold sample"
        )
    if sample.fold is not None:
        raise PooledKFoldError(
            f"config {config.name!r} fixes fold {sample.fold}; pooling needs "
            f"every fold 0 .. {sample.k - 1} (leave sample.fold unset)"
        )
    return int(sample.k)


def _read_folds(store: ResultStore, run_ids: Sequence[str]) -> dict[str, _Fold]:
    """Read every run's tables once and split them by ``run_id``.

    Raises
    ------
    PooledKFoldError
        If a run is not committed in the store.
    """
    ids = tuple(dict.fromkeys(run_ids))
    missing = [r for r in ids if not store.has_run(r)]
    if missing:
        raise PooledKFoldError(
            f"{len(missing)} of {len(ids)} fold runs are not in the result "
            f"store {store.root}, e.g. {missing[:3]}; pooled KPIs read the "
            "store and never solve, so run the config first "
            "(parametric-insurance-design run CONFIG)"
        )
    tables = {
        name: store.read(name, run_ids=ids)
        for name in ("runs", "entities", "payouts", "kpis")
    }

    def part(name: str, run_id: str) -> pd.DataFrame:
        frame = tables[name]
        return _where(frame, frame["run_id"] == run_id).reset_index(drop=True)

    out: dict[str, _Fold] = {}
    for run_id in ids:
        runs = part("runs", run_id)
        manifest = store.manifest(run_id)
        out[run_id] = _Fold(
            run_id=run_id,
            fold=int(runs["fold"].iloc[0]),
            runs=runs,
            entities=part("entities", run_id),
            payouts=part("payouts", run_id),
            kpis=part("kpis", run_id),
            prepared_hash=str(manifest["prepared_eventset"]["content_hash"]),
        )
    return out


def _check_fold(
    fold: _Fold,
    single: ExperimentConfig,
    *,
    expected: int,
    k: int,
    scope: str,
    objective: str,
) -> None:
    """Check that a stored run is fold ``expected`` of the scope x objective.

    Raises
    ------
    PooledKFoldError
        If it is another fold, sample, scope or objective, or its config hash
        is not that of ``single`` (e.g. a run of another scope of one kind).
    """
    runs = fold.runs
    params = json.loads(str(runs["parameters"].iloc[0]))
    got = (
        params.get("sample"),
        params.get("k"),
        params.get("fold"),
        set(runs["fold"].tolist()),
        set(runs["scope"]),
        set(runs["objective"]),
    )
    want = (KFOLD_SAMPLE, k, expected, {expected}, {scope}, {objective})
    if got != want:
        raise PooledKFoldError(
            f"run {fold.run_id} is not fold {expected} of k={k} of {scope} x "
            f"{objective}: sample {got[0]!r}, k={got[1]}, fold {got[2]}, "
            f"scope {sorted(got[4])}, objective {sorted(got[5])}"
        )
    hashes = set(runs["config_hash"])
    if hashes != {config_hash(single)}:
        raise PooledKFoldError(
            f"run {fold.run_id} has config hash {sorted(hashes)}, fold {expected} "
            f"of {scope} x {objective} in this config {config_hash(single)}"
        )


# --------------------------------------------------------------------------
# Payouts and KPIs
# --------------------------------------------------------------------------


def _portfolio_loss(data: EventSet) -> NDArray[np.float64]:
    """Portfolio loss per row, summed location by location as ``evaluate``."""
    return np.vstack(list(data.loss.T)).sum(axis=0)


def _fold_payout(
    data: EventSet,
    scope: Scope,
    payout: PayoutStructure,
    designs: Sequence[tuple[ProblemSpec, NDArray[np.float64]]],
) -> NDArray[np.float64]:
    """Portfolio payout per row of ``data``, entity by entity as ``evaluate``."""
    entity_payouts: list[NDArray[np.float64]] = []
    for spec, theta in designs:
        problem = scope.materialise(data, spec)
        values = payout.evaluate(problem.index, theta)
        entity_payouts.extend(values[:, j] for j in range(values.shape[1]))
    return np.vstack(entity_payouts).sum(axis=0)


def _correlation(
    x: NDArray[np.float64], y: NDArray[np.float64], p: NDArray[np.float64]
) -> float:
    """Weighted Pearson correlation; NaN at zero variance (as ``evaluate``)."""
    dev_x = x - np.sum(p * x)
    dev_y = y - np.sum(p * y)
    cov = np.sum(p * dev_x * dev_y)
    std_x = np.sqrt(np.sum(p * dev_x**2))
    std_y = np.sqrt(np.sum(p * dev_y**2))
    if std_x <= 0 or std_y <= 0:
        return math.nan
    return float(cov / (std_x * std_y))


def _point_kpis(
    loss: NDArray[np.float64],
    payout: NDArray[np.float64],
    measure: OutcomeMeasure,
    beta: float,
    pricing: Pricing,
) -> dict[KpiName, float]:
    """Compute the ``evaluate.kpis`` portfolio KPIs of per-row loss and payout.

    The formulas of ``evaluate`` (thesis ``_calculate_entity_kpis``), with
    its public ``var_cvar``; the drift guard checks them against the stored
    KPIs of every fold.
    """
    p = measure.probability / measure.probability.sum()
    residual = loss - payout
    loss_o = measure.aggregate(loss)
    payout_o = measure.aggregate(payout)
    uncovered_o = measure.aggregate(np.maximum(0.0, residual))
    residual_o = measure.aggregate(residual)
    var, cvar = var_cvar(uncovered_o, measure.probability, beta)
    expected_loss = float(np.sum(p * loss_o))
    expected_payout = float(np.sum(p * payout_o))
    return {
        KpiName.EXPECTED_LOSS: expected_loss,
        KpiName.EXPECTED_PAYOUT: expected_payout,
        KpiName.EXPECTED_UNCOVERED: float(np.sum(p * uncovered_o)),
        KpiName.VAR_UNCOVERED: var,
        KpiName.CVAR_UNCOVERED: cvar,
        KpiName.RMSE_RESIDUAL: math.sqrt(float(np.sum(p * residual_o**2))),
        KpiName.PAYOUT_TO_LOSS_RATIO: (
            math.nan if expected_loss == 0 else expected_payout / expected_loss
        ),
        KpiName.CORRELATION: _correlation(loss_o, payout_o, p),
        KpiName.PREMIUM: float(pricing.premium_value(payout, measure)),
    }


def _close(ours: float, stored: float) -> bool:
    """Whether a recomputed KPI equals the stored one (null equals NaN)."""
    if math.isnan(ours) or math.isnan(stored):
        return math.isnan(ours) and math.isnan(stored)
    scale = max(abs(ours), abs(stored))
    return abs(ours - stored) <= _DRIFT_RTOL * scale + _DRIFT_ATOL


def _drift_guard(fold: _Fold, values: Mapping[KpiName, float], beta: float) -> str:
    """Compare a fold's recomputed test KPIs with its stored rows.

    Returns
    -------
    str
        The portfolio ``problem_id`` of the stored rows.

    Raises
    ------
    FoldDriftError
        If a KPI is missing from the store or differs.
    """
    k = fold.kpis
    rows = _where(
        k,
        (k["eval_split"] == Split.TEST.value)
        & (k["level"] == KpiLevel.PORTFOLIO.value),
    )
    problem_ids = sorted(set(rows["problem_id"]))
    if len(problem_ids) != 1:
        raise FoldDriftError(
            f"run {fold.run_id} has portfolio test rows of problems {problem_ids}; "
            "expected one"
        )
    for kpi, ours in values.items():
        match = _where(rows, rows["kpi"] == kpi.value)
        if kpi in _BETA_KPIS:
            match = _where(
                match, np.isclose(match["beta"].to_numpy(dtype=np.float64), beta)
            )
        if len(match) != 1:
            raise FoldDriftError(
                f"run {fold.run_id} has {len(match)} portfolio test rows of KPI "
                f"{kpi.value!r}; expected one"
            )
        raw = match["value"].iloc[0]
        stored = math.nan if pd.isna(raw) else float(raw)
        if not _close(ours, stored):
            raise FoldDriftError(
                f"fold {fold.fold} ({fold.run_id}): portfolio {kpi.value!r} on "
                f"its test block is {ours!r} from the stored design, the store "
                f"holds {stored!r}; the stored design no longer reproduces the "
                "run (drift guard)"
            )
    return problem_ids[0]


def pooled_designs(
    config: ExperimentConfig,
    store: ResultStore,
    eventset: EventSet,
    run_ids: Sequence[str],
) -> tuple[tuple[PooledDesign, ...], tuple[PooledFailure, ...]]:
    """Every scope x objective's pooled out-of-sample payouts (no KPIs yet).

    Parameters
    ----------
    config : ExperimentConfig
        The k-fold experiment config (``sample.kind = "kfold"``, ``fold``
        unset).
    store : ResultStore
        The store holding its runs.
    eventset : EventSet
        The runs' **prepared** EventSet (``runner.prepare_eventset``).
    run_ids : sequence of str
        The ``run_id`` of each of ``config.single_runs()``, in that order
        (scope-major, objective, then fold).

    Returns
    -------
    designs : tuple of PooledDesign
        One per scope x objective whose folds are all complete, in config
        order. Each fold's design passed the drift guard.
    failed : tuple of PooledFailure
        The others, with the reason.

    Raises
    ------
    PooledKFoldError
        If the config is not a k-fold experiment over every fold, ``run_ids``
        does not match its single runs, a run is not in the store or is not
        the expected fold.
    FoldDriftError
        If the EventSet is not the runs' prepared EventSet, or a fold's
        stored design does not reproduce its stored test KPIs.
    SplitError
        If the EventSet cannot be split into ``k`` year blocks.
    """
    k = _check_config(config)
    singles = config.single_runs()
    ids = tuple(run_ids)
    if len(ids) != len(singles):
        raise PooledKFoldError(
            f"config {config.name!r} has {len(singles)} single runs "
            f"({len(config.scopes)} scopes x {len(config.objectives)} objectives "
            f"x {k} folds), got {len(ids)} run ids"
        )
    folds = _read_folds(store, ids)
    eventset_hash = eventset.content_hash()
    for fold in folds.values():
        if fold.prepared_hash != eventset_hash:
            raise FoldDriftError(
                f"run {fold.run_id} was solved on the prepared EventSet "
                f"{fold.prepared_hash}, the given EventSet is {eventset_hash}; "
                "pass runner.prepare_eventset(config, input)"
            )

    components = config.to_components()
    beta = float(config.evaluation.beta)
    samples = splits.year_block_kfold(eventset, k=k)
    test_data = [test.select(eventset) for _, test in samples]
    test_measures = [
        outcome_measure(data, Basis(components.basis), years=test.years)
        for data, (_, test) in zip(test_data, samples, strict=True)
    ]
    fold_of_row = np.full(eventset.n_rows, -1, dtype=np.int64)
    for f, (_, test) in enumerate(samples):
        if np.any(fold_of_row[test.rows] >= 0):  # pragma: no cover - splits invariant
            raise PooledKFoldError("the test blocks of the folds overlap")
        fold_of_row[test.rows] = f
    if np.any(fold_of_row < 0):  # pragma: no cover - splits invariant
        raise PooledKFoldError("the test blocks of the folds miss rows")
    loss = _portfolio_loss(eventset)

    designs: list[PooledDesign] = []
    failed: list[PooledFailure] = []
    n_objectives = len(config.objectives)
    for i in range(len(config.scopes)):
        scope = components.scopes[i]
        for j in range(n_objectives):
            objective = components.objectives[j]
            start = (i * n_objectives + j) * k
            fold_ids = ids[start : start + k]
            for f, run_id in enumerate(fold_ids):
                _check_fold(
                    folds[run_id],
                    singles[start + f],
                    expected=f,
                    k=k,
                    scope=scope.name,
                    objective=objective.name,
                )
            reasons = [r for r in (folds[run_id].failure() for run_id in fold_ids) if r]
            if reasons:
                failed.append(
                    PooledFailure(
                        i, scope.name, objective.name, fold_ids, "; ".join(reasons)
                    )
                )
                continue
            payout = np.full(eventset.n_rows, np.nan, dtype=np.float64)
            problem_ids: set[str] = set()
            for f, run_id in enumerate(fold_ids):
                fold = folds[run_id]
                designs_f = [
                    (spec, fold.theta(spec, components.payout)) for spec in fold.specs()
                ]
                data = test_data[f]
                fold_payout = _fold_payout(data, scope, components.payout, designs_f)
                values = _point_kpis(
                    _portfolio_loss(data),
                    fold_payout,
                    test_measures[f],
                    beta,
                    components.pricing,
                )
                problem_ids.add(_drift_guard(fold, values, beta))
                payout[samples[f][1].rows] = fold_payout
            designs.append(
                PooledDesign(
                    scope_position=i,
                    scope=scope.name,
                    objective=objective.name,
                    run_ids=fold_ids,
                    problem_id=(
                        problem_ids.pop() if len(problem_ids) == 1 else ALL_PROBLEMS
                    ),
                    fold=fold_of_row,
                    loss=loss,
                    payout=payout,
                )
            )
    return tuple(designs), tuple(failed)


def pooled_kpis(
    config: ExperimentConfig,
    store: ResultStore,
    eventset: EventSet,
    run_ids: Sequence[str],
) -> PooledKpis:
    """Pooled out-of-sample portfolio KPIs of a k-fold experiment, with CIs.

    The pooled rule, the drift guard and the intervals are described in the
    module docstring. Nothing is solved and nothing is written.

    Parameters
    ----------
    config : ExperimentConfig
        The k-fold experiment config. Its ``evaluation.beta``, basis and
        pricing define the KPIs; its ``bootstrap`` section (seed, ``B``,
        level) the intervals. Without a ``bootstrap`` section the table has
        point values only (null ``ci_*`` columns).
    store : ResultStore
        The store holding its runs.
    eventset : EventSet
        The runs' prepared EventSet.
    run_ids : sequence of str
        The ``run_id`` of each of ``config.single_runs()``, in that order.

    Returns
    -------
    PooledKpis
        The table, the replicates behind its intervals and the designs that
        are not pooled.

    Raises
    ------
    PooledKFoldError, FoldDriftError, SplitError
        As :func:`pooled_designs`.
    BootstrapError
        If a replicate cannot be represented on the basis (e.g. the ``event``
        basis with more than one event per year on average).
    """
    designs, failed = pooled_designs(config, store, eventset, run_ids)
    k = _check_config(config)
    components = config.to_components()
    basis = Basis(components.basis)
    beta = float(config.evaluation.beta)
    full = Sample.full(eventset)
    measure = outcome_measure(eventset, basis, years=full.years)
    row_years = eventset.events["year"].to_numpy(dtype=np.int64)
    boot = config.bootstrap
    resample = (
        None
        if boot is None
        else resample_years(full.years, boot.n_bootstrap, boot.rng())
    )
    level = None if boot is None else float(boot.level)

    rows: list[dict[str, Any]] = []
    replicate_rows: list[NDArray[np.float64]] = []
    for design in designs:
        values = _point_kpis(
            design.loss, design.payout, measure, beta, components.pricing
        )
        reps: Mapping[KpiName, NDArray[np.float64]] = {}
        if resample is not None:
            reps = kpi_replicates(
                design.loss, design.payout, measure, row_years, resample, beta=beta
            )
        for kpi in POOLED_KPIS:
            value = values[kpi]
            low = high = math.nan
            ci_level: float | None = None
            n_bootstrap: int | None = None
            if resample is not None and level is not None:
                if kpi in reps:
                    replicate_rows.append(reps[kpi])
                    low, high = percentile_interval(reps[kpi], level)
                    ci_level, n_bootstrap = level, resample.n_bootstrap
                else:  # premium: not bootstrapped (module docstring)
                    replicate_rows.append(
                        np.full(resample.n_bootstrap, np.nan, dtype=np.float64)
                    )
            rows.append(
                {
                    "scope_position": design.scope_position,
                    "scope": design.scope,
                    "objective": design.objective,
                    "run_ids": ";".join(design.run_ids),
                    "k": k,
                    "n_years": int(full.years.size),
                    "eval_split": POOLED_SPLIT,
                    "basis": basis.value,
                    "problem_id": design.problem_id,
                    "level": KpiLevel.PORTFOLIO.value,
                    "subject_id": PORTFOLIO_SUBJECT,
                    "kpi": kpi.value,
                    "beta": beta if kpi in _BETA_KPIS else math.nan,
                    "value": value,
                    "ci_low": low,
                    "ci_high": high,
                    "ci_level": math.nan if ci_level is None else ci_level,
                    "n_bootstrap": n_bootstrap,
                }
            )
    table = pd.DataFrame(rows, columns=list(POOLED_COLUMNS))
    table["scope_position"] = table["scope_position"].astype(np.int64)
    table["k"] = table["k"].astype(np.int64)
    table["n_years"] = table["n_years"].astype(np.int64)
    for column in ("beta", "value", "ci_low", "ci_high", "ci_level"):
        table[column] = table[column].astype(np.float64)
    table["n_bootstrap"] = table["n_bootstrap"].astype("Int64")
    replicates = (
        None
        if resample is None
        else (
            np.vstack(replicate_rows)
            if replicate_rows
            else np.empty((0, resample.n_bootstrap), dtype=np.float64)
        )
    )
    return PooledKpis(
        table=table,
        replicates=replicates,
        resample=resample,
        level=level,
        k=k,
        failed=failed,
    )


def pooled_difference(
    pooled: PooledKpis,
    a: tuple[int, str],
    b: tuple[int, str],
    *,
    level: float | None = None,
) -> pd.DataFrame:
    """Paired bootstrap interval of ``KPI(a) - KPI(b)`` of two pooled designs.

    Both designs were resampled with the same years in every replicate (the
    one resample of :func:`pooled_kpis`), so each replicate compares them on
    the same resampled years.

    Parameters
    ----------
    pooled : PooledKpis
        Pooled KPIs with replicates (a config with a ``bootstrap`` section).
    a, b : tuple of (int, str)
        ``(scope_position, objective)`` of the two designs, e.g. ``(0,
        "weighted_cvar")`` and ``(0, "mse")``.
    level : float, optional
        Confidence level; default ``pooled.level``.

    Returns
    -------
    pandas.DataFrame
        One row per KPI of :data:`POOLED_KPIS`: ``kpi``, ``beta``,
        ``value_a``, ``value_b``, ``difference = value_a - value_b``,
        ``ci_low``, ``ci_high`` (null if a replicate is undefined, and for
        ``premium``), ``ci_level`` and ``n_bootstrap``.

    Raises
    ------
    PooledKFoldError
        If ``pooled`` has no replicates or a design is not in its table.
    BootstrapError
        If ``level`` is not in ``(0, 1)``.
    """
    if pooled.replicates is None or pooled.resample is None or pooled.level is None:
        raise PooledKFoldError(
            "pooled KPIs without a bootstrap have no replicates; add a "
            "bootstrap section to the config"
        )
    ci_level = pooled.level if level is None else float(level)
    table = pooled.table

    def rows_of(design: tuple[int, str]) -> pd.DataFrame:
        position, objective = design
        mask = (table["scope_position"] == position) & (table["objective"] == objective)
        rows = _where(table, mask)
        if rows.empty:
            pairs = zip(table["scope_position"], table["objective"], strict=True)
            raise PooledKFoldError(
                f"design scope {position} x {objective} is not pooled; pooled "
                f"designs: {sorted(set(pairs))}"
            )
        return rows

    rows_a, rows_b = rows_of(a), rows_of(b)
    reps = pooled.replicates
    out: list[dict[str, Any]] = []
    for kpi in POOLED_KPIS:
        ia = _position(table, rows_a, kpi)
        ib = _position(table, rows_b, kpi)
        low, high = percentile_interval(reps[ia] - reps[ib], ci_level)
        value_a = float(table["value"].iloc[ia])
        value_b = float(table["value"].iloc[ib])
        bootstrapped = not math.isnan(float(table["ci_level"].iloc[ia]))
        out.append(
            {
                "kpi": kpi.value,
                "beta": float(table["beta"].iloc[ia]),
                "value_a": value_a,
                "value_b": value_b,
                "difference": value_a - value_b,
                "ci_low": low,
                "ci_high": high,
                "ci_level": ci_level if bootstrapped else math.nan,
                "n_bootstrap": pooled.resample.n_bootstrap if bootstrapped else None,
            }
        )
    frame = pd.DataFrame(out)
    frame["n_bootstrap"] = frame["n_bootstrap"].astype("Int64")
    return frame


def _position(table: pd.DataFrame, rows: pd.DataFrame, kpi: KpiName) -> int:
    """Row position in ``table`` of one design's ``kpi``."""
    match = _where(rows, rows["kpi"] == kpi.value)
    return int(np.flatnonzero(table.index == match.index[0])[0])
