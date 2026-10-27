"""Result-store reader: what figures read (SPEC §3.1 C6).

Owner: MAR-110. Figures are drawn from the runner's result store
(:class:`~parametric_insurance_design.experiment.store.ResultStore`, MAR-64)
and never re-run an optimisation: computation, then the store, then plotting,
as strictly separate layers. This module is the only place where viz touches
the store.

* :class:`ResultReader` opens a store and returns :class:`RunResult` objects:
  the validated record tables of one committed run, plus its manifest.
  :meth:`ResultReader.runs` reads many runs in bulk, one store read per table
  (MAR-120), and :meth:`ResultReader.kpis` the ``kpis`` table of many runs.
* :meth:`RunResult.problem_specs` rebuilds the run's design problems
  (entity membership) from the ``entities`` table.
* :func:`entity_events` gives the event data under a run's entities (the
  entity index and loss of every event row) for overlays such as the event
  scatter. It reads an EventSet, never the optimiser: the caller passes the
  *prepared* EventSet of the run (location subset, noise and threshold
  applied), and :func:`check_eventset` verifies it against the run's
  manifest.

Failed runs are never skipped silently: :meth:`RunResult.require_complete`
raises :class:`~parametric_insurance_design_viz.errors.IncompleteRunError`,
and :attr:`RunResult.failed_problems` lists what failed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import Entity, ProblemSpec, Scope
from parametric_insurance_design.records import TABLES
from parametric_insurance_design_viz.errors import (
    EventSetMismatchError,
    IncompleteRunError,
    MissingRunError,
)

__all__ = [
    "EVENT_COLUMNS",
    "ResultReader",
    "RunResult",
    "check_eventset",
    "entity_events",
]

EVENT_COLUMNS: tuple[str, ...] = (
    "problem_id",
    "entity_id",
    "row",
    "index",
    "loss",
    "rate",
)
"""Columns of :func:`entity_events`."""


@dataclass(frozen=True, eq=False)
class RunResult:
    """The record tables and manifest of one committed run.

    Parameters
    ----------
    run_id : str
        The run's id.
    runs, entities, payouts, kpis, exceedance : pandas.DataFrame
        The run's rows of each table, validated against the ``records``
        schemas.
    manifest : mapping
        The run's provenance manifest.
    """

    run_id: str
    runs: pd.DataFrame
    entities: pd.DataFrame
    payouts: pd.DataFrame
    kpis: pd.DataFrame
    exceedance: pd.DataFrame
    manifest: Mapping[str, Any]

    def _single(self, column: str) -> str:
        values = self.runs[column].unique().tolist()
        if len(values) != 1:  # pragma: no cover - the runner writes one per run
            raise IncompleteRunError(
                f"run {self.run_id} has {len(values)} values of runs.{column}"
            )
        return str(values[0])

    @property
    def scope(self) -> str:
        """Scope name (``runs.scope``)."""
        return self._single("scope")

    @property
    def objective(self) -> str:
        """Objective name (``runs.objective``)."""
        return self._single("objective")

    @property
    def parameters(self) -> dict[str, Any]:
        """Scalar run parameters (``runs.parameters``, parsed)."""
        data = json.loads(self._single("parameters"))
        if not isinstance(data, dict):  # pragma: no cover - schema convention
            raise IncompleteRunError(f"run {self.run_id}: parameters is not an object")
        return data

    @property
    def failed_problems(self) -> tuple[str, ...]:
        """Design problems without an accepted result, in run order.

        A problem failed when its ``runs`` row records an error. A build
        failure is one row with ``problem_id = "*"``.
        """
        failed = self.runs.loc[self.runs["error_type"].notna(), "problem_id"]
        return tuple(str(p) for p in failed)

    @property
    def complete(self) -> bool:
        """Whether every design problem of the run was solved."""
        return not self.failed_problems

    def require_complete(self) -> None:
        """Raise if a design problem of the run failed.

        Raises
        ------
        IncompleteRunError
            Naming the failed design problems and their error types.
        """
        if self.complete:
            return
        rows = self.runs[self.runs["error_type"].notna()]
        details = ", ".join(
            f"{p} ({e})"
            for p, e in zip(rows["problem_id"], rows["error_type"], strict=True)
        )
        raise IncompleteRunError(
            f"run {self.run_id} ({self.scope} x {self.objective}) has failed "
            f"design problems: {details}"
        )

    @property
    def prepared_eventset_hash(self) -> str | None:
        """``content_hash()`` of the EventSet the run was solved on.

        From the manifest's ``prepared_eventset``; None if the manifest does
        not record it.
        """
        prepared = self.manifest.get("prepared_eventset")
        if not isinstance(prepared, Mapping):
            return None
        value = prepared.get("content_hash")
        return value if isinstance(value, str) else None

    def problem_specs(self) -> tuple[ProblemSpec, ...]:
        """Rebuild the run's design problems from the ``entities`` table.

        Returns
        -------
        tuple of ProblemSpec
            In table order: problems, their entities and each entity's
            locations in the order the runner wrote them.
        """
        specs: list[ProblemSpec] = []
        for problem_id, rows in self.entities.groupby("problem_id", sort=False):
            entities = tuple(
                Entity(str(entity_id), tuple(str(x) for x in group["location_id"]))
                for entity_id, group in rows.groupby("entity_id", sort=False)
            )
            specs.append(ProblemSpec(problem_id=str(problem_id), entities=entities))
        return tuple(specs)

    def entity_order(self) -> tuple[str, ...]:
        """Entity ids in the order of the ``entities`` table, without repeats."""
        return tuple(dict.fromkeys(str(e) for e in self.entities["entity_id"]))


class ResultReader:
    """Read committed runs from a result store.

    Parameters
    ----------
    store : ResultStore, str or pathlib.Path
        The store, or its directory.

    Raises
    ------
    StoreError
        If the directory is not a result store of a version this core reads.
    """

    def __init__(self, store: ResultStore | str | Path) -> None:
        self._store = store if isinstance(store, ResultStore) else ResultStore(store)

    @property
    def store(self) -> ResultStore:
        """The result store."""
        return self._store

    def __repr__(self) -> str:
        """Short description with the store root."""
        return f"ResultReader({str(self._store.root)!r})"

    def run_ids(self) -> tuple[str, ...]:
        """Return the ids of every committed run, sorted."""
        return self._store.run_ids()

    def run(self, run_id: str) -> RunResult:
        """Read one committed run.

        Parameters
        ----------
        run_id : str
            The run's id.

        Returns
        -------
        RunResult
            Its tables and manifest.

        Raises
        ------
        MissingRunError
            If the run is not committed in the store.
        StoreError, RecordSchemaError
            If the store is damaged.
        """
        if not self._store.has_run(run_id):
            raise MissingRunError(
                f"run {run_id} is not in the result store {self._store.root}; "
                "figures read the store and never re-run an optimisation, so "
                "compute it first (parametric-insurance-design run CONFIG)"
            )
        return self._read([run_id])[0]

    def runs(self, run_ids: Iterable[str]) -> tuple[RunResult, ...]:
        """Read several committed runs, in the given order.

        Bulk read (MAR-120): each record table is read once for all the runs
        (one ``ResultStore.read`` per table) and split by ``run_id``, so
        reading many runs costs about as much as their files. The results
        equal those of :meth:`run`, one run at a time.

        Parameters
        ----------
        run_ids : iterable of str
            The runs' ids. A repeated id gives the same result twice.

        Returns
        -------
        tuple of RunResult
            One per id.

        Raises
        ------
        MissingRunError
            If a run is not committed; the message lists every missing one.
        StoreError, RecordSchemaError
            If the store is damaged.
        """
        ids = tuple(run_ids)
        self._require(ids)
        return self._read(ids)

    def kpis(self, run_ids: Iterable[str]) -> pd.DataFrame:
        """Read the ``kpis`` table of several committed runs at once (MAR-120).

        Parameters
        ----------
        run_ids : iterable of str
            The runs' ids.

        Returns
        -------
        pandas.DataFrame
            The validated ``kpis`` rows of those runs, as
            ``ResultStore.read`` returns them: runs in sorted ``run_id``
            order, rows in their written order within a run. The rows of one
            run equal :attr:`RunResult.kpis` of :meth:`run`.

        Raises
        ------
        MissingRunError
            If a run is not committed; the message lists every missing one.
        StoreError, RecordSchemaError
            If the store is damaged.
        """
        ids = tuple(run_ids)
        self._require(ids)
        return self._store.read("kpis", run_ids=ids)

    def _require(self, ids: Sequence[str]) -> None:
        """Raise :class:`MissingRunError` naming every uncommitted run."""
        missing = [r for r in ids if not self._store.has_run(r)]
        if missing:
            raise MissingRunError(
                f"{len(missing)} of {len(ids)} runs are not in the result store "
                f"{self._store.root}: {missing}; figures read the store and "
                "never re-run an optimisation, so compute them first "
                "(parametric-insurance-design run CONFIG)"
            )

    def _read(self, ids: Sequence[str]) -> tuple[RunResult, ...]:
        """Read committed runs: one store read per table, split by run."""
        unique = tuple(dict.fromkeys(ids))
        if not unique:
            return ()
        split = {
            name: _split(self._store.read(name, run_ids=unique), unique)
            for name in TABLES
        }
        results = {
            run_id: RunResult(
                run_id=run_id,
                runs=split["runs"][run_id],
                entities=split["entities"][run_id],
                payouts=split["payouts"][run_id],
                kpis=split["kpis"][run_id],
                exceedance=split["exceedance"][run_id],
                manifest=self._store.manifest(run_id),
            )
            for run_id in unique
        }
        return tuple(results[r] for r in ids)


def _split(frame: pd.DataFrame, run_ids: Sequence[str]) -> dict[str, pd.DataFrame]:
    """Split a table of several runs into one frame per run.

    Each frame keeps the rows of its run in table order, with a fresh
    ``RangeIndex`` and the table's dtypes, as a read of that run alone
    returns it; a run without rows gets an empty frame.
    """
    positions = frame.groupby("run_id", sort=False).indices
    none = np.zeros(0, dtype=np.intp)
    return {
        r: frame.take(positions.get(r, none)).reset_index(drop=True) for r in run_ids
    }


def check_eventset(run: RunResult, eventset: EventSet | str) -> None:
    """Check that an EventSet is the one a run was solved on.

    Parameters
    ----------
    run : RunResult
        The run.
    eventset : EventSet or str
        The prepared EventSet to draw overlays from, or its
        ``content_hash()`` (to hash it once for several runs).

    Raises
    ------
    EventSetMismatchError
        If the run's manifest records no prepared-EventSet hash, or the
        EventSet's ``content_hash()`` differs from it.
    """
    expected = run.prepared_eventset_hash
    if expected is None:
        raise EventSetMismatchError(
            f"run {run.run_id} records no prepared EventSet hash; cannot check "
            "the EventSet for its overlays"
        )
    actual = eventset if isinstance(eventset, str) else eventset.content_hash()
    if actual != expected:
        raise EventSetMismatchError(
            f"the EventSet ({actual}) is not the one run {run.run_id} was solved "
            f"on ({expected}); pass the run's prepared EventSet (location "
            "subset, noise and threshold of its config)"
        )


def entity_events(
    eventset: EventSet, scope: Scope, specs: Sequence[ProblemSpec]
) -> pd.DataFrame:
    """Return the event data under each entity: its index and loss per row.

    The values are those the optimiser saw: ``scope.materialise`` gives the
    entity index (e.g. the value-weighted cluster index) and the entity loss
    (the sum over its locations).

    Parameters
    ----------
    eventset : EventSet
        The run's prepared EventSet.
    scope : Scope
        The run's scope component (e.g. ``config.scopes[0].build()``).
    specs : sequence of ProblemSpec
        The run's design problems (:meth:`RunResult.problem_specs`).

    Returns
    -------
    pandas.DataFrame
        Columns :data:`EVENT_COLUMNS`: one row per (entity, EventSet row),
        with the row's ``rate``.

    Raises
    ------
    EntityMismatchError
        If a spec does not fit the scope or the EventSet.
    """
    rate = eventset.rates
    frames: list[pd.DataFrame] = []
    for spec in specs:
        problem = scope.materialise(eventset, spec)
        for j, entity in enumerate(spec.entities):
            frames.append(
                pd.DataFrame(
                    {
                        "problem_id": spec.problem_id,
                        "entity_id": entity.entity_id,
                        "row": np.arange(problem.n_rows, dtype=np.int64),
                        "index": problem.index[:, j],
                        "loss": problem.entity_loss[:, j],
                        "rate": rate,
                    }
                )
            )
    if not frames:
        return pd.DataFrame({c: [] for c in EVENT_COLUMNS})
    return pd.concat(frames, ignore_index=True)
