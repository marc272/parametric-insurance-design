"""Parquet result store (SPEC §4.2, thesis issue C5).

Owner: MAR-64. Persists and reads the tables defined in
:mod:`parametric_insurance_design.records` (``runs``, ``entities``,
``payouts``, ``kpis``, ``exceedance``), one Parquet file per run and table,
written with ``TableSchema.arrow_schema``, plus one provenance manifest per
run (config hash, package versions, input checksum, solver attempts, status
and timings). Tidy tables only: no arrays stored as strings.

Layout
------
::

    <root>/
        STORE.json                 store format and version
        runs/<hex>.parquet         one file per run and table, <hex> being the
        entities/<hex>.parquet     64 hex digits of the run_id "sha256:<hex>"
        payouts/<hex>.parquet
        kpis/<hex>.parquet
        exceedance/<hex>.parquet
        manifests/<hex>.json       provenance; written last (commit marker)

A run is **committed** once its manifest exists. :meth:`ResultStore.write_run`
writes every table file first (each atomically: a temporary file, then
``os.replace``) and the manifest last, so an interrupted write leaves table
files without a manifest. Readers see committed runs only, and
:meth:`ResultStore.uncommitted_runs` lists the leftovers; the next write of
that run replaces them. Every table file of a committed run exists, possibly
with zero rows (e.g. no ``kpis`` for a run with a failed solve).

One file per run keeps writes independent and idempotent: re-running a run
replaces its files, and nothing is read, merged and rewritten. Many small
files are the cost; compacting a finished sweep is a possible follow-up.

The store assumes a single writer per run. Two processes writing the same
``run_id`` at the same time are not coordinated.

Reads keep no state between calls (MAR-128): another process may commit runs
while this one reads, e.g. a ``sweep`` writing while ``figures`` reads, and
every call sees the store as it is on disk. A read of given runs checks only
those runs' manifest files, one ``stat`` each, instead of listing the
``manifests`` directory, and :meth:`ResultStore.read_manifests` reads many
manifests with one open per file.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from parametric_insurance_design.errors import (
    ParametricInsuranceDesignError,
    RecordSchemaError,
)
from parametric_insurance_design.records import (
    ENTITIES,
    EXCEEDANCE,
    KPIS,
    PAYOUTS,
    RUNS,
    TABLES,
    TableSchema,
)

__all__ = [
    "MANIFESTS_DIR",
    "STORE_FILE",
    "STORE_FORMAT",
    "STORE_VERSION",
    "ResultStore",
    "RunExistsError",
    "RunTables",
    "StoreError",
    "run_file_stem",
]

STORE_FORMAT: Final[str] = "parametric-insurance-design/result-store"
"""Value of ``format`` in ``STORE.json``."""

STORE_VERSION: Final[int] = 1
"""Version of the store layout. A layout change bumps it."""

STORE_FILE: Final[str] = "STORE.json"
"""Marker file at the store root."""

MANIFESTS_DIR: Final[str] = "manifests"
"""Directory of the per-run provenance manifests."""

_RUN_ID_PREFIX: Final[str] = "sha256:"
_HEX: Final[frozenset[str]] = frozenset("0123456789abcdef")


class StoreError(ParametricInsuranceDesignError, ValueError):
    """The result store is invalid, or a request does not fit it."""


class RunExistsError(StoreError):
    """A run is already committed and overwriting was not requested."""


def run_file_stem(run_id: str) -> str:
    """Return the file stem of a run: the hex digits of its ``run_id``.

    Parameters
    ----------
    run_id : str
        ``"sha256:"`` followed by 64 lowercase hex digits.

    Returns
    -------
    str
        The 64 hex digits.

    Raises
    ------
    StoreError
        If ``run_id`` does not have that form.
    """
    if not isinstance(run_id, str) or not run_id.startswith(_RUN_ID_PREFIX):
        raise StoreError(f"run_id must look like 'sha256:<64 hex>', got {run_id!r}")
    digest = run_id.removeprefix(_RUN_ID_PREFIX)
    if len(digest) != 64 or not set(digest) <= _HEX:
        raise StoreError(f"run_id must look like 'sha256:<64 hex>', got {run_id!r}")
    return digest


@dataclass(frozen=True, eq=False)
class RunTables:
    """The record tables of one run, validated.

    Parameters
    ----------
    runs, entities, payouts, kpis, exceedance : pandas.DataFrame
        Tables with the ``records`` schemas. ``runs`` must have at least one
        row; the others may be empty. Every row of every table has the same
        ``run_id``.

    Raises
    ------
    RecordSchemaError
        If a table breaks its schema, ``runs`` is empty, or the tables hold
        more than one ``run_id``.
    """

    runs: pd.DataFrame
    entities: pd.DataFrame
    payouts: pd.DataFrame
    kpis: pd.DataFrame
    exceedance: pd.DataFrame

    def __post_init__(self) -> None:
        """Validate every table and check that they share one run_id."""
        ids: set[str] = set()
        for schema in (RUNS, ENTITIES, PAYOUTS, KPIS, EXCEEDANCE):
            frame = schema.validate(getattr(self, schema.name))
            object.__setattr__(self, schema.name, frame)
            ids.update(frame["run_id"].tolist())
        if len(self.runs) == 0:
            raise RecordSchemaError("a run needs at least one row", table="runs")
        if len(ids) != 1:
            raise RecordSchemaError(
                f"the tables of one run must share one run_id, got {sorted(ids)}",
                table="runs",
            )

    @property
    def run_id(self) -> str:
        """The run's id."""
        return str(self.runs["run_id"].iloc[0])

    def items(self) -> tuple[tuple[TableSchema, pd.DataFrame], ...]:
        """Return ``(schema, table)`` pairs in ``records.TABLES`` order."""
        return tuple((schema, getattr(self, name)) for name, schema in TABLES.items())


def _parse_manifest(path: Path, raw: bytes) -> dict[str, Any]:
    """Decode a manifest file's UTF-8 bytes into a JSON object."""
    text = raw.decode("utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise StoreError(f"manifest {path} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise StoreError(f"manifest {path} must hold a JSON object")
    return data


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write ``data`` to ``path`` through a temporary file and ``os.replace``."""
    tmp = path.with_name(f".{path.name}.tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _atomic_write_parquet(path: Path, frame: pd.DataFrame, schema: TableSchema) -> None:
    """Write a validated table to ``path`` atomically."""
    table = pa.Table.from_pandas(
        frame, schema=schema.arrow_schema(), preserve_index=False
    )
    tmp = path.with_name(f".{path.name}.tmp")
    pq.write_table(table, tmp)
    os.replace(tmp, path)


class ResultStore:
    """A directory of result tables and run manifests (module docstring).

    Opening a store does not create anything; the first
    :meth:`write_run` creates the directories and ``STORE.json``.

    Parameters
    ----------
    root : str or pathlib.Path
        Store directory, e.g. ``config.output.directory``.

    Raises
    ------
    StoreError
        If ``root`` exists but is not a directory, or its ``STORE.json`` names
        another format or version.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        if self._root.exists() and not self._root.is_dir():
            raise StoreError(f"result store {self._root} is not a directory")
        marker = self._root / STORE_FILE
        if marker.is_file():
            try:
                info = json.loads(marker.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise StoreError(f"{marker} is not valid JSON: {exc}") from exc
            expected = {"format": STORE_FORMAT, "version": STORE_VERSION}
            if info != expected:
                raise StoreError(
                    f"{marker} describes {info!r}; this version reads {expected!r}"
                )

    @property
    def root(self) -> Path:
        """The store directory."""
        return self._root

    def __repr__(self) -> str:
        """Short description with the root directory."""
        return f"ResultStore({str(self._root)!r})"

    # -- paths --------------------------------------------------------------

    def _table_path(self, table: str, run_id: str) -> Path:
        return self._root / table / f"{run_file_stem(run_id)}.parquet"

    def _manifest_path(self, run_id: str) -> Path:
        return self._root / MANIFESTS_DIR / f"{run_file_stem(run_id)}.json"

    # -- queries ------------------------------------------------------------

    def has_run(self, run_id: str) -> bool:
        """Whether a run is committed (its manifest exists).

        Parameters
        ----------
        run_id : str
            The run's id.

        Returns
        -------
        bool
            True if the run is committed.
        """
        return self._manifest_path(run_id).is_file()

    def _is_committed(self, run_id: str) -> bool:
        """Like :meth:`has_run`, but False for a malformed ``run_id``.

        :meth:`read` reports malformed ids among the runs not in the store,
        as it did when it compared against :meth:`run_ids`.
        """
        try:
            stem = run_file_stem(run_id)
        except StoreError:
            return False
        # os.path on a str: a third of the cost of Path.is_file per run.
        return os.path.isfile(os.path.join(self._root, MANIFESTS_DIR, f"{stem}.json"))

    def run_ids(self) -> tuple[str, ...]:
        """Return the ids of every committed run, sorted.

        Returns
        -------
        tuple of str
            ``"sha256:<hex>"`` ids.
        """
        directory = self._root / MANIFESTS_DIR
        if not directory.is_dir():
            return ()
        return tuple(
            sorted(
                f"{_RUN_ID_PREFIX}{p.stem}"
                for p in directory.glob("*.json")
                if not p.name.startswith(".")
            )
        )

    def uncommitted_runs(self) -> tuple[str, ...]:
        """Return the ids of runs with table files but no manifest.

        These are left over from an interrupted write. Readers ignore them,
        and writing the run again replaces them.

        Returns
        -------
        tuple of str
            Sorted run ids.
        """
        committed = set(self.run_ids())
        found: set[str] = set()
        for table in TABLES:
            directory = self._root / table
            if directory.is_dir():
                found.update(
                    f"{_RUN_ID_PREFIX}{p.stem}"
                    for p in directory.glob("*.parquet")
                    if not p.name.startswith(".")
                )
        return tuple(sorted(found - committed))

    def manifest(self, run_id: str) -> dict[str, Any]:
        """Return the provenance manifest of a committed run.

        Parameters
        ----------
        run_id : str
            The run's id.

        Returns
        -------
        dict
            The manifest as written by :meth:`write_run`.

        Raises
        ------
        StoreError
            If the run is not committed or its manifest is not valid JSON.
        """
        path = self._manifest_path(run_id)
        if not path.is_file():
            raise StoreError(f"run {run_id} is not in the store {self._root}")
        return _parse_manifest(path, path.read_bytes())

    def read_manifests(self, run_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        """Return the provenance manifests of several committed runs.

        Bulk form of :meth:`manifest` (MAR-128): each manifest file is opened
        once, without a separate existence check, and every missing run is
        named in one error.

        Parameters
        ----------
        run_ids : iterable of str
            The runs' ids. A repeated id is read once.

        Returns
        -------
        dict
            ``run_id`` to manifest, in the order of first appearance in
            ``run_ids``. Each manifest equals :meth:`manifest` of that run.

        Raises
        ------
        StoreError
            If a run is not committed (the message lists every one), a
            ``run_id`` is malformed, or a manifest is not a valid JSON
            object.
        """
        manifests: dict[str, dict[str, Any]] = {}
        missing: list[str] = []
        for run_id in dict.fromkeys(run_ids):
            path = self._manifest_path(run_id)
            try:
                raw = path.read_bytes()
            except (FileNotFoundError, IsADirectoryError, NotADirectoryError):
                missing.append(run_id)
                continue
            manifests[run_id] = _parse_manifest(path, raw)
        if missing:
            raise StoreError(f"runs not in the store {self._root}: {sorted(missing)}")
        return manifests

    def read(self, table: str, *, run_ids: Iterable[str] | None = None) -> pd.DataFrame:
        """Read one table over committed runs.

        Parameters
        ----------
        table : str
            A name in ``records.TABLES``.
        run_ids : iterable of str, optional
            Runs to read. Default: every committed run.

        Returns
        -------
        pandas.DataFrame
            The validated table, runs in sorted ``run_id`` order and rows in
            their written order within a run.

        Raises
        ------
        StoreError
            If the table name is unknown, a requested run is not committed,
            or a committed run lacks its file for this table.
        RecordSchemaError
            If a file does not match the table schema.
        """
        if table not in TABLES:
            raise StoreError(f"unknown table {table!r} (tables: {', '.join(TABLES)})")
        schema = TABLES[table]
        if run_ids is None:
            wanted = self.run_ids()
        else:
            # Check only the requested runs (MAR-128): one stat per run, no
            # listing and no cache, so runs that another process commits
            # between two reads are seen.
            wanted = tuple(sorted(set(run_ids)))
            missing = [r for r in wanted if not self._is_committed(r)]
            if missing:
                raise StoreError(f"runs not in the store {self._root}: {missing}")
        parts: list[pa.Table] = []
        arrow_schema = schema.arrow_schema()
        for run_id in wanted:
            path = self._table_path(table, run_id)
            if not path.is_file():
                raise StoreError(
                    f"committed run {run_id} has no {table!r} file ({path}); "
                    "the store is damaged"
                )
            # ParquetFile.read: half the time of pq.read_table, which goes
            # through the dataset API, for the same table (MAR-128).
            with pq.ParquetFile(path) as handle:
                part = handle.read()
            if not part.schema.equals(arrow_schema):
                raise RecordSchemaError(
                    f"{path} has schema {part.schema}, expected {arrow_schema}",
                    table=table,
                )
            parts.append(part)
        if not parts:
            return schema.empty()
        frame = pa.concat_tables(parts).to_pandas()
        return schema.validate(frame)

    # -- writing ------------------------------------------------------------

    def write_run(
        self,
        tables: RunTables,
        manifest: Mapping[str, Any],
        *,
        overwrite: bool = False,
    ) -> None:
        """Write the tables and the manifest of one run, manifest last.

        Parameters
        ----------
        tables : RunTables
            The run's validated tables.
        manifest : mapping
            JSON-serialisable provenance. Its ``run_id`` must equal the
            tables' run id.
        overwrite : bool, default False
            Replace a committed run. The run is uncommitted (manifest
            removed) before its files are replaced.

        Raises
        ------
        RunExistsError
            If the run is committed and ``overwrite`` is False.
        StoreError
            If the manifest's ``run_id`` differs from the tables' or the
            manifest is not JSON-serialisable.
        """
        run_id = tables.run_id
        if manifest.get("run_id") != run_id:
            raise StoreError(
                f"manifest run_id {manifest.get('run_id')!r} differs from the "
                f"tables' run_id {run_id!r}"
            )
        try:
            payload = json.dumps(
                dict(manifest), indent=2, sort_keys=True, allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise StoreError(f"manifest of {run_id} is not valid JSON: {exc}") from exc
        manifest_path = self._manifest_path(run_id)
        if manifest_path.is_file():
            if not overwrite:
                raise RunExistsError(f"run {run_id} is already in {self._root}")
            manifest_path.unlink()
        self._ensure_layout()
        for schema, frame in tables.items():
            _atomic_write_parquet(self._table_path(schema.name, run_id), frame, schema)
        _atomic_write_bytes(manifest_path, payload)

    def _ensure_layout(self) -> None:
        """Create the directories and ``STORE.json`` if they are missing."""
        self._root.mkdir(parents=True, exist_ok=True)
        for name in (*TABLES, MANIFESTS_DIR):
            (self._root / name).mkdir(exist_ok=True)
        marker = self._root / STORE_FILE
        if not marker.is_file():
            info = {"format": STORE_FORMAT, "version": STORE_VERSION}
            _atomic_write_bytes(marker, (json.dumps(info, indent=2) + "\n").encode())
