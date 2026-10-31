"""Parity harness: compare a result store with the thesis golden tables (MAR-67).

SPEC §7 F-06: on the thesis event set, every objective value and every
portfolio and asset KPI must match the thesis within 1e-4 relative; payout
vectors are compared loosely, because LP optima can be non-unique; every gap
is explained in ``parity/REPORT.md``. This module does the comparing;
:mod:`report` writes the report.

Golden tables
    ``golden/full_optimization_results.csv.gz``
        One row per thesis payout entity and run: ``Approach``, ``Method``,
        ``Source``, ``Asset_ID`` (asset or cluster id), the run parameters
        ``Alpha``, ``Beta``, ``Budget_Loading``, ``N_Bins``, ``N_Clusters``
        (empty where the method doesn't use them), ``Included_Assets`` (a
        Python list literal; the cluster members), and the string-encoded
        arrays ``Payouts`` (step levels) and ``Breakpoints`` (bin edges), as
        numpy prints them.
    ``golden/benchmarking_kpis.csv.gz``
        One row per KPI subject and run: the same key columns, ``Scope``,
        ``Asset`` (an asset, a cluster or ``Portfolio``) and the KPI columns
        of :data:`KPI_COLUMNS`.
    An objective table (optional)
        The thesis tables hold **no objective values**. A table with the key
        columns, ``Problem`` (a ``runs.problem_id``) and ``Objective_Value``
        can be passed to :func:`load_golden`; without one, the objective
        comparison is reported as unavailable. Optional columns
        ``Derivation`` and ``KPI_Source`` say how each value was obtained
        (``golden/golden_objectives.csv``, MAR-68, is such a table).

    Simulation sweeps (MAR-70)
        ``golden/simulation_sweeps/`` holds the thesis noise-level and
        asset-count sweep results, which the thesis kept in memory only,
        regenerated with the thesis code (``scripts/derive_simulation_sweeps.py``):
        tables of the same columns plus the optional key columns
        :data:`EXTRA_PARAMETER_COLUMNS` (``Noise_Value``, ``N_Assets``) and
        :data:`LOCATIONS_COLUMN` (``Location_IDs``, the asset subset as a
        Python list literal). :func:`load_simulation_golden` reads them and
        :meth:`Golden.merge` joins them with the thesis tables.

    Checksums
        :func:`load_golden` records the SHA256 of every file as read and, for
        gzipped files, of the decompressed content too: ``parity/manifest.json``
        records the decompressed thesis CSVs (:func:`check_manifest`).

Matching rules
    A golden record's key is (approach, method, source, parameters). It
    matches the store run whose ``runs.scope`` and ``runs.objective`` are
    the approach and method mapped by :data:`APPROACHES` and
    :data:`METHODS`, and whose ``runs.parameters`` agree with the golden
    parameters (:data:`PARAMETER_COLUMNS`): a golden value must be present
    and equal within ``Tolerances.parameter_rtol``; an empty golden value
    means the store run must not have the parameter. ``fixed_parameters``
    adds conditions every matching run must meet.

    The optional key columns work the same way where the golden row sets
    them: ``noise_level`` and ``n_assets`` must equal the run's, and the
    ``Location_IDs`` subset must equal the run's prepared locations (its
    manifest's ``prepared_eventset.location_ids``, in order). Where a golden
    row leaves one empty (every row of the thesis tables), the run must
    have the value given in ``baseline_parameters`` (e.g. ``noise_level``
    0.3 and ``n_assets`` 9, the thesis config's), or any value if none is
    given. ``run_ids`` restricts the store runs considered at all (e.g. to
    the points of the sweeps compared).

    The ``source`` tag is **not** required to agree by default: the runner's
    cache keeps the tag a run was first written with (MAR-64), so the
    baseline run of every sweep carries one tag only, while the thesis wrote
    the same numbers under every sweep (the golden KPIs of records that
    differ only in ``Source`` are identical). ``strict_source=True``
    requires it. Golden records are still grouped by their source.

    Within a run, a golden payout entity (``Asset_ID``) is matched to the
    store's ``entity_id``, a golden KPI subject (``Asset``) to the
    ``entity`` level row with that ``subject_id``, and ``Portfolio`` to the
    ``portfolio`` level row. Only KPI rows with ``eval_split`` full, fold 0
    and the given basis are used; VaR and CVaR at ``evaluation_beta``.

Comparisons
    * KPI and objective values: ``|ours - golden| <= rtol |golden| + atol``
      (1e-4 and 0 by default). Both undefined (NaN) is a match; one
      undefined is a mismatch.
    * Payout vectors: the largest absolute difference of the levels is
      reported, not asserted. The bin edges must agree within
      ``Tolerances.edge_atol`` (they are fixed by ``N_Bins``; the golden ones
      are printed to 8 decimals).
    * Cluster assignments: the map from cluster id to member assets must be
      equal, labels included.

Everything the harness cannot compare (no matching run, a failed solve, a
missing entity, KPI or objective) is a finding too: nothing is dropped
silently. Store runs that match no golden record are listed, not flagged.
"""

from __future__ import annotations

import ast
import gzip
import hashlib
import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import SolveStatus
from parametric_insurance_design.records import KpiLevel, KpiName, Split

__all__ = [
    "APPROACHES",
    "EXTRA_PARAMETER_COLUMNS",
    "GOLDEN_DIR",
    "KPIS_FILE",
    "KPI_COLUMNS",
    "LOCATIONS_COLUMN",
    "METHODS",
    "PARAMETER_COLUMNS",
    "PORTFOLIO_SUBJECT",
    "RESULTS_FILE",
    "SIMULATION_DIR",
    "Finding",
    "FindingKind",
    "Golden",
    "GoldenFormatError",
    "GoldenKpis",
    "GoldenObjective",
    "GoldenPayout",
    "HarnessError",
    "ParityResult",
    "RecordKey",
    "Tolerances",
    "check_manifest",
    "compare",
    "content_sha256",
    "file_sha256",
    "load_golden",
    "load_simulation_golden",
    "parse_array",
    "parse_assets",
]

PARITY_DIR: Final[Path] = Path(__file__).resolve().parent
GOLDEN_DIR: Final[Path] = PARITY_DIR / "golden"
"""Directory of the committed thesis golden tables."""

RESULTS_FILE: Final[str] = "full_optimization_results.csv.gz"
KPIS_FILE: Final[str] = "benchmarking_kpis.csv.gz"
OBJECTIVES_FILE: Final[str] = "golden_objectives.csv"
"""The golden objective table derived for MAR-68 (in :data:`GOLDEN_DIR`)."""
MANIFEST: Final[Path] = PARITY_DIR / "manifest.json"
"""The parity manifest: SHA256 of the decompressed golden CSVs (MAR-9)."""
SIMULATION_DIR: Final[Path] = GOLDEN_DIR / "simulation_sweeps"
"""The regenerated thesis simulation-sweep tables (MAR-70)."""
SIMULATION_TABLES: Final[tuple[str, str, str]] = (
    "simulation_results",
    "simulation_kpis",
    "simulation_objectives",
)
"""File name prefixes of the simulation tables (results, KPIs, objectives).

Each table is split into shards ``<prefix>_<shard>.csv.gz``, one per sweep
and, for ``n_assets``, per asset count, to stay under the 500 kB file limit;
every shard has the three tables."""

APPROACHES: Final[Mapping[str, str]] = {
    "individual_optimization": "individual",
    "cluster_optimization": "cluster",
    "integrated_portfolio_optimization": "portfolio",
}
"""Thesis ``Approach`` to ``runs.scope``."""

METHODS: Final[Mapping[str, str]] = {
    "pure_basis_risk_minimization": "mse",
    "pure_uncovered_loss_minimization": "expected_uncovered",
    "weighted_cvar_minimization": "weighted_cvar",
}
"""Thesis ``Method`` to ``runs.objective``."""

PARAMETER_COLUMNS: Final[Mapping[str, str]] = {
    "Alpha": "alpha",
    "Beta": "beta",
    "Budget_Loading": "budget_loading",
    "N_Bins": "n_bins",
    "N_Clusters": "n_clusters",
}
"""Thesis parameter column to ``runs.parameters`` key (sweep names, MAR-64)."""

EXTRA_PARAMETER_COLUMNS: Final[Mapping[str, str]] = {
    "Noise_Value": "noise_level",
    "N_Assets": "n_assets",
}
"""Optional key columns (simulation sweeps, MAR-70) to ``runs.parameters`` key.

Unlike :data:`PARAMETER_COLUMNS`, an empty or absent value does not require
the run to lack the parameter (every run has both): it stands for the
baseline value (:func:`compare`, ``baseline_parameters``)."""

LOCATIONS_COLUMN: Final[str] = "Location_IDs"
"""Optional key column: the asset subset of an ``n_assets`` sweep record."""

LOCATIONS_KEY: Final[str] = "locations"
"""Name of the subset in :meth:`RecordKey.parameter_text`."""

KPI_COLUMNS: Final[Mapping[str, KpiName]] = {
    "CVaR_Uncovered": KpiName.CVAR_UNCOVERED,
    "VaR_Uncovered": KpiName.VAR_UNCOVERED,
    "E_Uncovered": KpiName.EXPECTED_UNCOVERED,
    "E_Residual": KpiName.RMSE_RESIDUAL,
    "E_Payout_to_E_Loss_Ratio": KpiName.PAYOUT_TO_LOSS_RATIO,
    "Correlation": KpiName.CORRELATION,
}
"""Thesis KPI column to ``kpis.kpi``."""

TAIL_KPIS: Final[frozenset[KpiName]] = frozenset(
    {KpiName.VAR_UNCOVERED, KpiName.CVAR_UNCOVERED}
)
"""KPIs stored with a ``beta``."""

PORTFOLIO_SUBJECT: Final[str] = "Portfolio"
"""Golden ``Asset`` of the portfolio KPI row."""

CLUSTER_APPROACH: Final[str] = "cluster_optimization"

ACCEPTED_STATUSES: Final[frozenset[str]] = frozenset(
    {SolveStatus.OPTIMAL.value, SolveStatus.OPTIMAL_INACCURATE.value}
)

_KEY_COLUMNS: Final[tuple[str, ...]] = ("Approach", "Method", "Source")
_RESULTS_COLUMNS: Final[tuple[str, ...]] = (
    *_KEY_COLUMNS,
    "Asset_ID",
    *PARAMETER_COLUMNS,
    "Included_Assets",
    "Payouts",
    "Breakpoints",
)
_KPIS_COLUMNS: Final[tuple[str, ...]] = (
    *_KEY_COLUMNS,
    "Scope",
    "Asset",
    *PARAMETER_COLUMNS,
    "Included_Assets",
    *KPI_COLUMNS,
)
_OBJECTIVES_COLUMNS: Final[tuple[str, ...]] = (
    *_KEY_COLUMNS,
    *PARAMETER_COLUMNS,
    "Problem",
    "Objective_Value",
)


class HarnessError(ValueError):
    """The harness cannot run on its inputs."""


class GoldenFormatError(HarnessError):
    """A golden table is malformed (missing column, bad array, duplicate key)."""


# --------------------------------------------------------------------------
# Golden tables
# --------------------------------------------------------------------------


def file_sha256(path: str | Path) -> str:
    """Return the SHA256 hex digest of a file.

    Parameters
    ----------
    path : str or pathlib.Path
        The file.

    Returns
    -------
    str
        64 lowercase hex digits.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_sha256(path: str | Path) -> tuple[str, str]:
    """Return the content name and SHA256 of a file, decompressing ``.gz``.

    Parameters
    ----------
    path : str or pathlib.Path
        The file.

    Returns
    -------
    name : str
        The file name without a ``.gz`` suffix.
    digest : str
        SHA256 of the decompressed content for ``.gz`` files, else of the
        file.
    """
    file = Path(path)
    if file.suffix != ".gz":
        return file.name, file_sha256(file)
    digest = hashlib.sha256()
    with gzip.open(file, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return file.stem, digest.hexdigest()


def check_manifest(
    content: Mapping[str, str], manifest: str | Path = MANIFEST
) -> dict[str, str]:
    """Compare golden content checksums with ``parity/manifest.json``.

    Parameters
    ----------
    content : mapping of str to str
        Content name to SHA256 (:attr:`Golden.content_sha256`).
    manifest : str or pathlib.Path, default ``parity/manifest.json``
        The manifest; its ``golden`` entries hold ``sha256`` per CSV name.

    Returns
    -------
    dict of str to str
        Content name to ``"matches"``, ``"differs"`` (with the manifest
        digest) or ``"not in the manifest"``; ``{}`` if there is no manifest.
    """
    path = Path(manifest)
    if not path.is_file():
        return {}
    golden = json.loads(path.read_text(encoding="utf-8")).get("golden", {})
    out: dict[str, str] = {}
    for name, digest in content.items():
        entry = golden.get(name)
        if not isinstance(entry, dict) or "sha256" not in entry:
            out[name] = "not in the manifest"
        elif entry["sha256"] == digest:
            out[name] = "matches"
        else:
            out[name] = f"differs (manifest: {entry['sha256']})"
    return out


def parse_array(text: object) -> np.ndarray:
    r"""Parse an array the thesis stored as a string.

    The thesis wrote numpy arrays with ``str()``: brackets, whitespace
    separated, possibly wrapped over lines and in scientific notation, e.g.
    ``"[0.00000000e+00 2.77558997e+03\n 2.31563400e+04]"``. Comma-separated
    Python lists are accepted too.

    Parameters
    ----------
    text : object
        The cell value.

    Returns
    -------
    numpy.ndarray
        1-D float64 array.

    Raises
    ------
    GoldenFormatError
        If the value is not a bracketed list of numbers.
    """
    if not isinstance(text, str):
        raise GoldenFormatError(f"expected an array string, got {text!r}")
    stripped = text.strip()
    if not (stripped.startswith("[") and stripped.endswith("]")):
        raise GoldenFormatError(f"array string must be bracketed: {text[:60]!r}")
    tokens = stripped[1:-1].replace(",", " ").split()
    try:
        return np.array([float(t) for t in tokens], dtype=np.float64)
    except ValueError as exc:
        raise GoldenFormatError(f"bad number in array {text[:60]!r}: {exc}") from exc


def parse_assets(value: object) -> tuple[str, ...] | None:
    """Parse an ``Included_Assets`` cell.

    Parameters
    ----------
    value : object
        A Python list literal of asset ids (``"['A1', 'A2']"``), or empty
        (NaN, None).

    Returns
    -------
    tuple of str or None
        The asset ids in their order, or None for an empty cell.

    Raises
    ------
    GoldenFormatError
        If the value is not a list of strings.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if not isinstance(value, str):
        raise GoldenFormatError(f"Included_Assets must be a list literal: {value!r}")
    try:
        parsed = ast.literal_eval(value.strip())
    except (ValueError, SyntaxError) as exc:
        raise GoldenFormatError(f"bad Included_Assets {value!r}: {exc}") from exc
    if not isinstance(parsed, list | tuple) or not all(
        isinstance(a, str) for a in parsed
    ):
        raise GoldenFormatError(f"Included_Assets must list strings: {value!r}")
    return tuple(parsed)


def _number(value: object) -> float | None:
    """Return a golden parameter cell as a float, or None if empty."""
    if value is None:
        return None
    if isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise GoldenFormatError(f"parameter must be a number: {value!r}") from exc
    return None if math.isnan(number) else number


def _format_number(value: float) -> str:
    """Short text for a parameter value: integers without a decimal point."""
    return str(int(value)) if value == int(value) else repr(value)


@dataclass(frozen=True)
class RecordKey:
    """What identifies one thesis run: approach, method, source, parameters.

    Parameters
    ----------
    approach : str
        Thesis ``Approach`` (a key of :data:`APPROACHES`).
    method : str
        Thesis ``Method`` (a key of :data:`METHODS`).
    source : str
        Thesis ``Source`` tag, e.g. ``"single_run"`` or ``"alpha_sweep"``.
    parameters : tuple of (str, float or None)
        ``runs.parameters`` names (:data:`PARAMETER_COLUMNS` order) and the
        golden values, None where the thesis left the column empty.
    extras : tuple of (str, float), default ()
        The optional key parameters the row sets
        (:data:`EXTRA_PARAMETER_COLUMNS` order); unset ones are left out.
    locations : tuple of str or None, default None
        The asset subset (:data:`LOCATIONS_COLUMN`), or None if unset.
    """

    approach: str
    method: str
    source: str
    parameters: tuple[tuple[str, float | None], ...]
    extras: tuple[tuple[str, float], ...] = ()
    locations: tuple[str, ...] | None = None

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> RecordKey:
        """Build the key of a golden row.

        Parameters
        ----------
        row : mapping
            A golden row with the key and parameter columns.

        Returns
        -------
        RecordKey
            The key.

        Raises
        ------
        GoldenFormatError
            If the approach or method is unknown or a parameter is not a
            number.
        """
        approach = str(row["Approach"]).strip()
        method = str(row["Method"]).strip()
        source = str(row["Source"]).strip()
        if approach not in APPROACHES:
            raise GoldenFormatError(
                f"unknown Approach {approach!r} (known: {sorted(APPROACHES)})"
            )
        if method not in METHODS:
            raise GoldenFormatError(
                f"unknown Method {method!r} (known: {sorted(METHODS)})"
            )
        parameters = tuple(
            (name, _number(row[column])) for column, name in PARAMETER_COLUMNS.items()
        )
        extras = tuple(
            (name, value)
            for column, name in EXTRA_PARAMETER_COLUMNS.items()
            if (value := _number(row.get(column))) is not None
        )
        locations = parse_assets(row.get(LOCATIONS_COLUMN))
        if locations is not None and not locations:
            raise GoldenFormatError(f"{LOCATIONS_COLUMN} must list at least one asset")
        return cls(approach, method, source, parameters, extras, locations)

    def sort_key(self) -> tuple[object, ...]:
        """Return a total order: unset parameters (None) sort before set ones."""
        return (
            self.source,
            self.approach,
            self.method,
            tuple((n, v is not None, v or 0.0) for n, v in self.parameters),
            self.extras,
            () if self.locations is None else self.locations,
        )

    @property
    def scope(self) -> str:
        """The ``runs.scope`` of the approach."""
        return APPROACHES[self.approach]

    @property
    def objective(self) -> str:
        """The ``runs.objective`` of the method."""
        return METHODS[self.method]

    @property
    def group(self) -> tuple[str, str, str]:
        """The comparison group: (source, approach, method)."""
        return (self.source, self.approach, self.method)

    def parameter_text(self) -> str:
        """Set parameters as ``name=value`` pairs, e.g. ``alpha=0.9, n_bins=15``.

        The optional key parameters follow where set, then the subset as
        ``locations=A1+A4``; a thesis-table key reads as before (MAR-70).
        """
        items = [
            f"{name}={_format_number(value)}"
            for name, value in (*self.parameters, *self.extras)
            if value is not None
        ]
        if self.locations is not None:
            items.append(f"{LOCATIONS_KEY}={'+'.join(self.locations)}")
        return ", ".join(items)

    def label(self) -> str:
        """``approach/method/source/parameters``: the key as one string."""
        return "/".join(
            (self.approach, self.method, self.source, self.parameter_text())
        )


@dataclass(frozen=True, eq=False)
class GoldenPayout:
    """One golden payout entity: a row of the thesis results table."""

    key: RecordKey
    entity_id: str
    included: tuple[str, ...] | None
    levels: np.ndarray
    breakpoints: np.ndarray


@dataclass(frozen=True)
class GoldenKpis:
    """One golden KPI subject: a row of the thesis KPI table."""

    key: RecordKey
    subject: str
    scope: str
    included: tuple[str, ...] | None
    values: Mapping[str, float]


@dataclass(frozen=True)
class GoldenObjective:
    """One golden objective value of a design problem.

    ``derivation`` and ``kpi_source`` say how it was obtained (optional
    columns ``Derivation`` and ``KPI_Source``); empty if not given.
    """

    key: RecordKey
    problem_id: str
    value: float
    derivation: str = ""
    kpi_source: str = ""


@dataclass(frozen=True)
class Golden:
    """The parsed golden tables.

    Parameters
    ----------
    payouts : tuple of GoldenPayout
        Rows of the results table.
    kpis : tuple of GoldenKpis
        Rows of the KPI table.
    objectives : tuple of GoldenObjective or None
        Rows of the objective table; None if there is none.
    files : mapping of str to str
        File name to SHA256 of every table read (for the report).
    content_sha256 : mapping of str to str
        Content name (without ``.gz``) to the SHA256 of the decompressed
        content, for every table read (:func:`content_sha256`).
    """

    payouts: tuple[GoldenPayout, ...]
    kpis: tuple[GoldenKpis, ...]
    objectives: tuple[GoldenObjective, ...] | None
    files: Mapping[str, str] = field(default_factory=dict)
    content_sha256: Mapping[str, str] = field(default_factory=dict)

    def keys(self) -> tuple[RecordKey, ...]:
        """Every record key of the golden tables, sorted."""
        found: set[RecordKey] = {p.key for p in self.payouts}
        found.update(k.key for k in self.kpis)
        found.update(o.key for o in self.objectives or ())
        return tuple(sorted(found, key=RecordKey.sort_key))

    def merge(self, other: Golden) -> Golden:
        """Return both golden data sets as one (e.g. thesis and simulation tables).

        Parameters
        ----------
        other : Golden
            Tables with records of other keys.

        Returns
        -------
        Golden
            The rows of both; the objective table is None only if both lack
            one; the file and content checksums of both.

        Raises
        ------
        GoldenFormatError
            If a record key, with its entity, subject or problem, is in both,
            or the two read files of the same name.
        """
        clash = set(self.files) & set(other.files)
        if clash:
            raise GoldenFormatError(
                f"both golden sets read files named {sorted(clash)}"
            )
        payouts = (*self.payouts, *other.payouts)
        kpis = (*self.kpis, *other.kpis)
        _check_unique(((p.key, p.entity_id) for p in payouts), "merged results")
        _check_unique(((k.key, k.subject) for k in kpis), "merged KPIs")
        objectives: tuple[GoldenObjective, ...] | None = None
        if self.objectives is not None or other.objectives is not None:
            objectives = (*(self.objectives or ()), *(other.objectives or ()))
            _check_unique(
                ((o.key, o.problem_id) for o in objectives), "merged objectives"
            )
        return Golden(
            payouts=payouts,
            kpis=kpis,
            objectives=objectives,
            files={**self.files, **other.files},
            content_sha256={**self.content_sha256, **other.content_sha256},
        )


def _read_table(path: Path, columns: Sequence[str]) -> pd.DataFrame:
    """Read a golden CSV (gzip is detected from the suffix); check its columns."""
    try:
        frame = pd.read_csv(path)
    except (OSError, ValueError) as exc:
        raise GoldenFormatError(f"cannot read golden table {path}: {exc}") from exc
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise GoldenFormatError(f"{path.name} lacks columns {missing}")
    return frame


def _records(frame: pd.DataFrame) -> Iterable[dict[str, Any]]:
    """Rows as dicts with NaN for empty cells."""
    for record in frame.to_dict(orient="records"):
        yield {str(k): v for k, v in record.items()}


def _check_unique(items: Iterable[tuple[object, ...]], what: str) -> None:
    seen: set[tuple[object, ...]] = set()
    for item in items:
        if item in seen:
            raise GoldenFormatError(f"{what} repeats the key {item}")
        seen.add(item)


def load_golden(
    results: str | Path = GOLDEN_DIR / RESULTS_FILE,
    kpis: str | Path = GOLDEN_DIR / KPIS_FILE,
    objectives: str | Path | None = None,
) -> Golden:
    """Read and parse the golden tables.

    Parameters
    ----------
    results : str or pathlib.Path, default ``golden/full_optimization_results.csv.gz``
        The thesis results table (payouts).
    kpis : str or pathlib.Path, default ``golden/benchmarking_kpis.csv.gz``
        The thesis KPI table.
    objectives : str or pathlib.Path, optional
        An objective table (module docstring). The thesis has none.

    Returns
    -------
    Golden
        The parsed tables.

    Raises
    ------
    GoldenFormatError
        If a table cannot be read, lacks a column, holds a malformed value,
        or repeats a key (record key and entity, subject or problem).
    """
    results_path, kpis_path = Path(results), Path(kpis)
    files = {results_path.name: file_sha256(results_path)}
    files[kpis_path.name] = file_sha256(kpis_path)
    content = dict(content_sha256(p) for p in (results_path, kpis_path))

    payouts: list[GoldenPayout] = []
    for i, row in enumerate(_records(_read_table(results_path, _RESULTS_COLUMNS))):
        try:
            payouts.append(
                GoldenPayout(
                    key=RecordKey.from_row(row),
                    entity_id=str(row["Asset_ID"]).strip(),
                    included=parse_assets(row["Included_Assets"]),
                    levels=parse_array(row["Payouts"]),
                    breakpoints=parse_array(row["Breakpoints"]),
                )
            )
        except GoldenFormatError as exc:
            raise GoldenFormatError(f"{results_path.name} row {i}: {exc}") from exc
    _check_unique(((p.key, p.entity_id) for p in payouts), results_path.name)

    kpi_rows: list[GoldenKpis] = []
    for i, row in enumerate(_records(_read_table(kpis_path, _KPIS_COLUMNS))):
        try:
            values: dict[str, float] = {}
            for column in KPI_COLUMNS:
                number = _number(row[column])
                values[column] = math.nan if number is None else number
            kpi_rows.append(
                GoldenKpis(
                    key=RecordKey.from_row(row),
                    subject=str(row["Asset"]).strip(),
                    scope=str(row["Scope"]).strip(),
                    included=parse_assets(row["Included_Assets"]),
                    values=values,
                )
            )
        except GoldenFormatError as exc:
            raise GoldenFormatError(f"{kpis_path.name} row {i}: {exc}") from exc
    _check_unique(((k.key, k.subject) for k in kpi_rows), kpis_path.name)

    objective_rows: list[GoldenObjective] | None = None
    if objectives is not None:
        objectives_path = Path(objectives)
        files[objectives_path.name] = file_sha256(objectives_path)
        name, digest = content_sha256(objectives_path)
        content[name] = digest
        objective_rows = []
        table = _read_table(objectives_path, _OBJECTIVES_COLUMNS)
        for i, row in enumerate(_records(table)):
            try:
                value = _number(row["Objective_Value"])
                objective_rows.append(
                    GoldenObjective(
                        key=RecordKey.from_row(row),
                        problem_id=str(row["Problem"]).strip(),
                        value=math.nan if value is None else value,
                        derivation=_optional_str(row.get("Derivation")) or "",
                        kpi_source=_optional_str(row.get("KPI_Source")) or "",
                    )
                )
            except GoldenFormatError as exc:
                raise GoldenFormatError(
                    f"{objectives_path.name} row {i}: {exc}"
                ) from exc
        _check_unique(
            ((o.key, o.problem_id) for o in objective_rows), objectives_path.name
        )

    return Golden(
        payouts=tuple(payouts),
        kpis=tuple(kpi_rows),
        objectives=None if objective_rows is None else tuple(objective_rows),
        files=files,
        content_sha256=content,
    )


def load_simulation_golden(directory: str | Path = SIMULATION_DIR) -> Golden:
    """Read the regenerated thesis simulation-sweep tables (MAR-70).

    Parameters
    ----------
    directory : str or pathlib.Path, default ``golden/simulation_sweeps``
        Holds the shards of the tables :data:`SIMULATION_TABLES`.

    Returns
    -------
    Golden
        All shards merged, with the noise level, asset count and subset in
        their record keys.

    Raises
    ------
    GoldenFormatError
        If there is no shard, a shard lacks one of its three tables, or as
        for :func:`load_golden`.
    """
    root = Path(directory)
    results, kpis, objectives = SIMULATION_TABLES
    names = sorted(
        p.name.removeprefix(f"{results}_").removesuffix(".csv.gz")
        for p in root.glob(f"{results}_*.csv.gz")
    )
    if not names:
        raise GoldenFormatError(f"no {results}_*.csv.gz in {root}")
    found = {p.name for p in root.glob("simulation_*.csv.gz")}
    expected = {f"{t}_{n}.csv.gz" for t in SIMULATION_TABLES for n in names}
    if found != expected:
        raise GoldenFormatError(
            f"{root}: the shards do not pair up: missing "
            f"{sorted(expected - found)}, unexpected {sorted(found - expected)}"
        )
    merged: Golden | None = None
    for name in names:
        part = load_golden(
            root / f"{results}_{name}.csv.gz",
            root / f"{kpis}_{name}.csv.gz",
            root / f"{objectives}_{name}.csv.gz",
        )
        merged = part if merged is None else merged.merge(part)
    assert merged is not None
    return merged


# --------------------------------------------------------------------------
# Result store side
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Problem:
    """One ``runs`` row: a design problem's status and objective."""

    status: str
    objective_value: float | None
    error_type: str | None


@dataclass(frozen=True, eq=False)
class _Levels:
    """The fitted payout of one entity: levels and bin edges."""

    values: np.ndarray
    edges: np.ndarray

    @classmethod
    def from_params(cls, params: Sequence[tuple[int, float, float, float]]) -> _Levels:
        """Build from ``(param_index, lower, upper, value)`` rows, any order."""
        ordered = sorted(params)
        indices = [p[0] for p in ordered]
        if indices != list(range(len(ordered))):
            raise HarnessError(f"payout param_index values {indices} are not 0..n-1")
        values = np.array([p[3] for p in ordered], dtype=np.float64)
        edges = np.array([p[1] for p in ordered] + [ordered[-1][2]], dtype=np.float64)
        return cls(values, edges)


@dataclass
class _StoreRun:
    """What the harness needs of one committed run."""

    run_id: str
    source: str
    scope: str
    objective: str
    parameters: dict[str, Any]
    config_hash: str = ""
    locations: tuple[str, ...] | None = None
    problems: dict[str, _Problem] = field(default_factory=dict)
    members: dict[str, tuple[str, ...]] = field(default_factory=dict)
    entity_problem: dict[str, str] = field(default_factory=dict)
    payouts: dict[str, _Levels] = field(default_factory=dict)
    kpis: dict[tuple[str, str, str], float] = field(default_factory=dict)

    @property
    def failed(self) -> dict[str, _Problem]:
        """Problems without an accepted status."""
        return {
            pid: p
            for pid, p in self.problems.items()
            if p.status not in ACCEPTED_STATUSES
        }


def _optional_float(value: object) -> float | None:
    if value is None or pd.isna(value):  # type: ignore[arg-type]
        return None
    return float(value)  # type: ignore[arg-type]


def _optional_str(value: object) -> str | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    return str(value)


def _load_store(
    store: ResultStore,
    *,
    basis: str,
    evaluation_beta: float,
    run_ids: frozenset[str] | None = None,
    locations: bool = False,
) -> dict[str, _StoreRun]:
    """Index the committed runs of a store by run id.

    ``run_ids`` restricts the runs read; with ``locations`` each run's
    prepared location ids are read from its manifest.
    """
    wanted = None if run_ids is None else sorted(run_ids)
    runs: dict[str, _StoreRun] = {}
    for row in _records(store.read("runs", run_ids=wanted)):
        run_id = str(row["run_id"])
        params = json.loads(str(row["parameters"]))
        if not isinstance(params, dict):
            raise HarnessError(f"run {run_id}: runs.parameters is not a JSON object")
        run = runs.get(run_id)
        if run is None:
            run = runs[run_id] = _StoreRun(
                run_id=run_id,
                source=str(row["source"]),
                scope=str(row["scope"]),
                objective=str(row["objective"]),
                parameters=params,
                config_hash=str(row["config_hash"]),
            )
        run.problems[str(row["problem_id"])] = _Problem(
            status=str(row["status"]),
            objective_value=_optional_float(row["objective_value"]),
            error_type=_optional_str(row["error_type"]),
        )

    members: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in _records(store.read("entities", run_ids=wanted)):
        run = runs[str(row["run_id"])]
        entity_id = str(row["entity_id"])
        problem_id = str(row["problem_id"])
        if run.entity_problem.setdefault(entity_id, problem_id) != problem_id:
            raise HarnessError(
                f"run {run.run_id}: entity {entity_id} is in several problems"
            )
        members[(run.run_id, entity_id)].append(str(row["location_id"]))
    for (run_id, entity_id), member_ids in members.items():
        runs[run_id].members[entity_id] = tuple(member_ids)

    levels: dict[tuple[str, str], list[tuple[int, float, float, float]]] = defaultdict(
        list
    )
    payout_problem: dict[tuple[str, str], str] = {}
    for row in _records(store.read("payouts", run_ids=wanted)):
        index = (str(row["run_id"]), str(row["entity_id"]))
        problem_id = str(row["problem_id"])
        if payout_problem.setdefault(index, problem_id) != problem_id:
            raise HarnessError(
                f"run {index[0]}: entity {index[1]} has payouts in several problems"
            )
        levels[index].append(
            (
                int(row["param_index"]),
                float(row["lower"]),
                float(row["upper"]),
                float(row["value"]),
            )
        )
    for (run_id, entity_id), params in levels.items():
        runs[run_id].payouts[entity_id] = _Levels.from_params(params)

    tail = {k.value for k in TAIL_KPIS}
    wanted_levels = {KpiLevel.ENTITY.value, KpiLevel.PORTFOLIO.value}
    for row in _records(store.read("kpis", run_ids=wanted)):
        level = str(row["level"])
        kpi = str(row["kpi"])
        beta = _optional_float(row["beta"])
        if (
            row["eval_split"] != Split.FULL.value
            or int(row["fold"]) != 0
            or row["basis"] != basis
            or level not in wanted_levels
        ):
            continue
        if kpi in tail:
            if beta is None or not math.isclose(beta, evaluation_beta, rel_tol=1e-12):
                continue
        elif beta is not None:
            continue
        run = runs[str(row["run_id"])]
        subject = str(row["subject_id"])
        index = (level, "" if level == KpiLevel.PORTFOLIO.value else subject, kpi)
        if index in run.kpis:
            raise HarnessError(
                f"run {run.run_id}: several {level} rows for KPI {kpi} of {subject!r}"
            )
        value = _optional_float(row["value"])
        run.kpis[index] = math.nan if value is None else value
    if locations:
        for run in runs.values():
            prepared = store.manifest(run.run_id).get("prepared_eventset") or {}
            ids = prepared.get("location_ids")
            if not isinstance(ids, list):
                raise HarnessError(
                    f"run {run.run_id}: its manifest has no prepared location ids"
                )
            run.locations = tuple(str(i) for i in ids)
    return runs


def _same_value(golden: object, ours: object, rel_tol: float) -> bool:
    """Whether a store parameter equals a golden or fixed value."""
    if isinstance(golden, bool) or isinstance(ours, bool):
        return golden == ours
    if isinstance(golden, int | float) and isinstance(ours, int | float):
        return math.isclose(float(golden), float(ours), rel_tol=rel_tol, abs_tol=0.0)
    return golden == ours


def _matches(
    key: RecordKey,
    run: _StoreRun,
    *,
    fixed: Mapping[str, object],
    strict_source: bool,
    rel_tol: float,
    baseline: Mapping[str, object] | None = None,
) -> bool:
    if run.scope != key.scope or run.objective != key.objective:
        return False
    if strict_source and run.source != key.source:
        return False
    for name, value in key.parameters:
        if value is None:
            if run.parameters.get(name) is not None:
                return False
        elif name not in run.parameters or not _same_value(
            value, run.parameters[name], rel_tol
        ):
            return False
    extras = dict(key.extras)
    for name in EXTRA_PARAMETER_COLUMNS.values():
        want = extras.get(name, (baseline or {}).get(name))
        if want is None:
            continue
        if name not in run.parameters or not _same_value(
            want, run.parameters[name], rel_tol
        ):
            return False
    if key.locations is not None and run.locations != key.locations:
        return False
    return all(
        name in run.parameters and _same_value(value, run.parameters[name], rel_tol)
        for name, value in fixed.items()
    )


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Tolerances:
    """Comparison tolerances (SPEC §7 F-06).

    Parameters
    ----------
    kpi_rtol, kpi_atol : float, default 1e-4 and 0
        KPI values match if ``|ours - golden| <= rtol |golden| + atol``.
    objective_rtol, objective_atol : float, default 1e-4 and 0
        The same for objective values.
    edge_atol : float, default 1e-6
        Bin edges must agree within this (the golden ones have 8 decimals).
    parameter_rtol : float, default 1e-9
        Relative tolerance when matching run parameters.
    """

    kpi_rtol: float = 1e-4
    kpi_atol: float = 0.0
    objective_rtol: float = 1e-4
    objective_atol: float = 0.0
    edge_atol: float = 1e-6
    parameter_rtol: float = 1e-9


class FindingKind(StrEnum):
    """What a finding is about."""

    MISSING_RUN = "missing_run"
    """No store run matches the golden record."""
    AMBIGUOUS_RUN = "ambiguous_run"
    """Several store runs match the golden record."""
    SOLVE_FAILED = "solve_failed"
    """The design problem of a golden entity or KPI has no accepted solution."""
    MISSING_ENTITY = "missing_entity"
    """The matched run has no payouts for a golden entity."""
    PAYOUT_SHAPE = "payout_shape"
    """The number of payout levels or the bin edges differ."""
    MISSING_KPI = "missing_kpi"
    """The matched run has no KPI value for a golden subject."""
    KPI = "kpi"
    """A KPI value is outside the tolerance."""
    MISSING_OBJECTIVE = "missing_objective"
    """The matched run has no objective value for a golden problem."""
    OBJECTIVE = "objective"
    """An objective value is outside the tolerance."""
    CLUSTER_ASSIGNMENT = "cluster_assignment"
    """The cluster members differ."""


@dataclass(frozen=True)
class Finding:
    """One gap between the golden data and the store.

    Parameters
    ----------
    kind : FindingKind
        What the finding is about.
    key : RecordKey
        The golden record.
    subject : str
        Entity, KPI subject or problem id; empty for the whole record.
    item : str
        Thesis KPI column, or empty.
    golden, ours : str
        The values compared, as text.
    rel_error : float or None
        ``|ours - golden| / |golden|`` for numeric comparisons.
    detail : str
        Why this is a finding.
    """

    kind: FindingKind
    key: RecordKey
    subject: str = ""
    item: str = ""
    golden: str = ""
    ours: str = ""
    rel_error: float | None = None
    detail: str = ""

    @property
    def path(self) -> str:
        """``kind/approach/method/source/parameters/subject/item``.

        Explanations can name findings by a glob over this path
        (:func:`report.explanation_for`).
        """
        return "/".join((self.kind.value, self.key.label(), self.subject, self.item))

    @property
    def id(self) -> str:
        """Stable id from the path, e.g. ``P-3f2a9c01be``."""
        return "P-" + hashlib.sha256(self.path.encode("utf-8")).hexdigest()[:10]


@dataclass(frozen=True, eq=False)
class ParityResult:
    """Everything one comparison found.

    Parameters
    ----------
    kpis : pandas.DataFrame
        One row per golden KPI value: the key columns (``approach``,
        ``method``, ``source``, ``parameters``), ``subject``, ``kpi`` (thesis
        column), ``golden``, ``ours``, ``abs_error``, ``rel_error`` and
        ``status`` (``match``, ``mismatch`` or ``missing``).
    objectives : pandas.DataFrame
        The same per golden objective value, with ``problem_id``. Empty
        without a golden objective table.
    payouts : pandas.DataFrame
        One row per golden payout entity: the key columns, ``entity_id``,
        ``n_levels``, ``max_abs_diff``, ``max_rel_diff`` (the largest
        absolute difference over the largest golden level), ``edge_diff``
        and ``status`` (``compared``, ``shape`` or ``missing``).
    clusters : pandas.DataFrame
        One row per cluster-approach record: the key columns, ``golden``,
        ``ours`` and ``status`` (``match``, ``mismatch`` or ``missing``).
    findings : tuple of Finding
        Every gap, sorted.
    unmatched_runs : pandas.DataFrame
        Store runs no golden record matched: ``run_id``, ``source``,
        ``scope``, ``objective``, ``parameters``.
    n_store_runs : int
        Committed runs in the store.
    objectives_available : bool
        Whether a golden objective table was given.
    golden_files : mapping of str to str
        Golden file name to SHA256.
    store_root : str
        The store directory.
    tolerances : Tolerances
        The tolerances used.
    basis : str
        The KPI basis compared.
    evaluation_beta : float
        ``beta`` of the VaR and CVaR KPIs compared.
    fixed_parameters : mapping of str to object
        Parameters every matched run had to have.
    strict_source : bool
        Whether ``runs.source`` had to agree.
    sources : tuple of str or None
        The golden sources compared; None for all.
    golden_content : mapping of str to str
        Content name to SHA256 of the decompressed golden tables
        (:attr:`Golden.content_sha256`).
    matched_runs : pandas.DataFrame
        One row per golden record compared: the key columns, ``run_id``,
        ``config_hash`` and ``run_source`` of the matched store run (empty
        if none or several match), ``problems`` and ``failed`` (counts).
    baseline_parameters : mapping of str to object
        The values a run must have for an optional key parameter a golden
        record leaves empty (MAR-70).
    restricted : bool
        Whether only some of the store's runs were considered (``run_ids``);
        ``n_store_runs`` counts those.
    """

    kpis: pd.DataFrame
    objectives: pd.DataFrame
    payouts: pd.DataFrame
    clusters: pd.DataFrame
    findings: tuple[Finding, ...]
    unmatched_runs: pd.DataFrame
    n_store_runs: int
    objectives_available: bool
    golden_files: Mapping[str, str]
    store_root: str
    tolerances: Tolerances
    basis: str
    evaluation_beta: float
    fixed_parameters: Mapping[str, object]
    strict_source: bool
    sources: tuple[str, ...] | None
    golden_content: Mapping[str, str] = field(default_factory=dict)
    matched_runs: pd.DataFrame = field(default_factory=pd.DataFrame)
    baseline_parameters: Mapping[str, object] = field(default_factory=dict)
    restricted: bool = False

    @property
    def ok(self) -> bool:
        """True if there is no finding."""
        return not self.findings


_KEY_OUT: Final[tuple[str, ...]] = ("source", "approach", "method", "parameters")


def _key_fields(key: RecordKey) -> dict[str, str]:
    return {
        "source": key.source,
        "approach": key.approach,
        "method": key.method,
        "parameters": key.parameter_text(),
    }


def _rel_error(golden: float, ours: float) -> float:
    if math.isnan(golden) or math.isnan(ours):
        return math.nan
    diff = abs(ours - golden)
    if golden == 0.0:
        return 0.0 if diff == 0.0 else math.inf
    return diff / abs(golden)


def _within(golden: float, ours: float, rtol: float, atol: float) -> bool:
    if math.isnan(golden) or math.isnan(ours):
        return math.isnan(golden) and math.isnan(ours)
    return abs(ours - golden) <= rtol * abs(golden) + atol


def _text(value: float | None) -> str:
    return "" if value is None else f"{value:.10g}"


def _members_text(members: Mapping[str, Sequence[str]]) -> str:
    return "; ".join(f"{e}={{{', '.join(m)}}}" for e, m in sorted(members.items()))


@dataclass
class _Collector:
    """Rows and findings gathered during :func:`compare`."""

    kpis: list[dict[str, Any]] = field(default_factory=list)
    objectives: list[dict[str, Any]] = field(default_factory=list)
    payouts: list[dict[str, Any]] = field(default_factory=list)
    clusters: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    runs: list[dict[str, Any]] = field(default_factory=list)


def _failure_detail(run: _StoreRun, problem_id: str | None) -> str | None:
    """Why the run has nothing for a problem, if a solve or build failed."""
    failed = run.failed
    if not failed:
        return None
    if problem_id is not None and problem_id in failed:
        p = failed[problem_id]
        return f"problem {problem_id}: status {p.status} ({p.error_type})"
    parts = [f"{pid}: {p.status} ({p.error_type})" for pid, p in sorted(failed.items())]
    return "failed problems in the run: " + "; ".join(parts)


def _compare_payout(
    golden: GoldenPayout, run: _StoreRun, tol: Tolerances, out: _Collector
) -> None:
    base = {**_key_fields(golden.key), "entity_id": golden.entity_id}
    row = {
        **base,
        "n_levels": len(golden.levels),
        "max_abs_diff": math.nan,
        "max_rel_diff": math.nan,
        "edge_diff": math.nan,
    }
    ours = run.payouts.get(golden.entity_id)
    if ours is None:
        failure = _failure_detail(run, run.entity_problem.get(golden.entity_id))
        out.findings.append(
            Finding(
                FindingKind.SOLVE_FAILED if failure else FindingKind.MISSING_ENTITY,
                golden.key,
                subject=golden.entity_id,
                golden=f"{len(golden.levels)} levels",
                detail=failure
                or f"run {run.run_id} has no payouts for entity {golden.entity_id}",
            )
        )
        out.payouts.append({**row, "status": "missing"})
        return
    levels, edges = ours.values, ours.edges
    if len(levels) != len(golden.levels) or len(edges) != len(golden.breakpoints):
        out.findings.append(
            Finding(
                FindingKind.PAYOUT_SHAPE,
                golden.key,
                subject=golden.entity_id,
                golden=f"{len(golden.levels)} levels, {len(golden.breakpoints)} edges",
                ours=f"{len(levels)} levels, {len(edges)} edges",
                detail="the number of payout levels or bin edges differs",
            )
        )
        out.payouts.append({**row, "status": "shape"})
        return
    diff = np.abs(levels - golden.levels)
    max_abs = float(diff.max()) if len(diff) else 0.0
    scale = float(np.abs(golden.levels).max()) if len(diff) else 0.0
    edge_diff = float(np.abs(edges - golden.breakpoints).max()) if len(edges) else 0.0
    row.update(
        max_abs_diff=max_abs,
        max_rel_diff=max_abs / scale if scale > 0 else math.nan,
        edge_diff=edge_diff,
    )
    if not edge_diff <= tol.edge_atol:
        out.findings.append(
            Finding(
                FindingKind.PAYOUT_SHAPE,
                golden.key,
                subject=golden.entity_id,
                golden=np.array2string(golden.breakpoints, precision=6),
                ours=np.array2string(edges, precision=6),
                detail=f"bin edges differ by up to {edge_diff:.3g} "
                f"(tolerance {tol.edge_atol:g})",
            )
        )
        out.payouts.append({**row, "status": "shape"})
        return
    out.payouts.append({**row, "status": "compared"})


def _compare_kpis(
    golden: GoldenKpis, run: _StoreRun, tol: Tolerances, out: _Collector
) -> None:
    portfolio = golden.subject == PORTFOLIO_SUBJECT
    level = KpiLevel.PORTFOLIO.value if portfolio else KpiLevel.ENTITY.value
    lookup = (level, "" if portfolio else golden.subject)
    base = {**_key_fields(golden.key), "subject": golden.subject}
    missing: list[str] = []
    for column, kpi in KPI_COLUMNS.items():
        want = golden.values[column]
        index = (*lookup, kpi.value)
        if index not in run.kpis:
            missing.append(column)
            out.kpis.append(
                {
                    **base,
                    "kpi": column,
                    "golden": want,
                    "ours": math.nan,
                    "abs_error": math.nan,
                    "rel_error": math.nan,
                    "status": "missing",
                }
            )
            continue
        got = run.kpis[index]
        ok = _within(want, got, tol.kpi_rtol, tol.kpi_atol)
        rel = _rel_error(want, got)
        out.kpis.append(
            {
                **base,
                "kpi": column,
                "golden": want,
                "ours": got,
                "abs_error": abs(got - want),
                "rel_error": rel,
                "status": "match" if ok else "mismatch",
            }
        )
        if not ok:
            out.findings.append(
                Finding(
                    FindingKind.KPI,
                    golden.key,
                    subject=golden.subject,
                    item=column,
                    golden=_text(want),
                    ours=_text(got),
                    rel_error=None if math.isnan(rel) else rel,
                    detail="outside the tolerance"
                    if not (math.isnan(want) or math.isnan(got))
                    else "defined on one side only",
                )
            )
    if missing:
        problem = None if portfolio else run.entity_problem.get(golden.subject)
        failure = _failure_detail(run, problem)
        out.findings.append(
            Finding(
                FindingKind.SOLVE_FAILED if failure else FindingKind.MISSING_KPI,
                golden.key,
                subject=golden.subject,
                item="" if len(missing) == len(KPI_COLUMNS) else ",".join(missing),
                detail=failure
                or f"run {run.run_id} has no {level} KPI rows for {golden.subject} "
                f"({', '.join(missing)})",
            )
        )


def _compare_objective(
    golden: GoldenObjective, run: _StoreRun, tol: Tolerances, out: _Collector
) -> None:
    base = {
        **_key_fields(golden.key),
        "problem_id": golden.problem_id,
        "derivation": golden.derivation,
        "kpi_source": golden.kpi_source,
    }
    problem = run.problems.get(golden.problem_id)
    if problem is None or problem.objective_value is None:
        failure = _failure_detail(run, golden.problem_id)
        out.findings.append(
            Finding(
                FindingKind.SOLVE_FAILED if failure else FindingKind.MISSING_OBJECTIVE,
                golden.key,
                subject=golden.problem_id,
                golden=_text(golden.value),
                detail=failure
                or f"run {run.run_id} has no objective value for {golden.problem_id}",
            )
        )
        out.objectives.append(
            {
                **base,
                "golden": golden.value,
                "ours": math.nan,
                "abs_error": math.nan,
                "rel_error": math.nan,
                "status": "missing",
            }
        )
        return
    got = problem.objective_value
    ok = _within(golden.value, got, tol.objective_rtol, tol.objective_atol)
    rel = _rel_error(golden.value, got)
    out.objectives.append(
        {
            **base,
            "golden": golden.value,
            "ours": got,
            "abs_error": abs(got - golden.value),
            "rel_error": rel,
            "status": "match" if ok else "mismatch",
        }
    )
    if not ok:
        out.findings.append(
            Finding(
                FindingKind.OBJECTIVE,
                golden.key,
                subject=golden.problem_id,
                golden=_text(golden.value),
                ours=_text(got),
                rel_error=None if math.isnan(rel) else rel,
                detail="outside the tolerance",
            )
        )


def _golden_clusters(
    key: RecordKey, payouts: Sequence[GoldenPayout], kpis: Sequence[GoldenKpis]
) -> dict[str, tuple[str, ...]]:
    """Cluster id to members, from the results rows (else the KPI rows)."""
    members: dict[str, tuple[str, ...]] = {}
    for p in payouts:
        if p.included is not None:
            members[p.entity_id] = p.included
    if not members:
        for k in kpis:
            if k.subject != PORTFOLIO_SUBJECT and k.included is not None:
                members[k.subject] = k.included
    for entity, assets in members.items():
        if not assets:
            raise GoldenFormatError(f"{key.label()}: cluster {entity} has no assets")
    return members


def _compare_clusters(
    key: RecordKey,
    golden: Mapping[str, tuple[str, ...]],
    run: _StoreRun | None,
    out: _Collector,
) -> None:
    golden_sets = {e: tuple(sorted(m)) for e, m in golden.items()}
    row = {**_key_fields(key), "golden": _members_text(golden_sets), "ours": ""}
    if run is None:
        out.clusters.append({**row, "status": "missing"})
        return
    ours = {e: tuple(sorted(m)) for e, m in run.members.items()}
    row["ours"] = _members_text(ours)
    if ours == golden_sets:
        out.clusters.append({**row, "status": "match"})
        return
    out.clusters.append({**row, "status": "mismatch"})
    out.findings.append(
        Finding(
            FindingKind.CLUSTER_ASSIGNMENT,
            key,
            golden=row["golden"],
            ours=row["ours"] or "(no entities)",
            detail=(
                "same partition, different cluster labels"
                if sorted(ours.values()) == sorted(golden_sets.values())
                else "the clusters differ"
            ),
        )
    )


def _frame(rows: list[dict[str, Any]], columns: Sequence[str]) -> pd.DataFrame:
    frame = pd.DataFrame(rows, columns=list(columns))
    sort = [c for c in (*_KEY_OUT, "entity_id", "subject", "problem_id", "kpi")]
    sort = [c for c in sort if c in frame.columns]
    return frame.sort_values(sort, kind="stable").reset_index(drop=True)


def compare(
    golden: Golden,
    store: ResultStore,
    *,
    tolerances: Tolerances | None = None,
    fixed_parameters: Mapping[str, object] | None = None,
    strict_source: bool = False,
    sources: Iterable[str] | None = None,
    basis: Basis | str = Basis.EVENT_CONDITIONAL,
    evaluation_beta: float = 0.95,
    baseline_parameters: Mapping[str, object] | None = None,
    run_ids: Iterable[str] | None = None,
) -> ParityResult:
    """Compare a result store with the golden tables (module docstring).

    Parameters
    ----------
    golden : Golden
        From :func:`load_golden`.
    store : ResultStore
        The store to check; only committed runs are read.
    tolerances : Tolerances, optional
        Default: ``Tolerances()``.
    fixed_parameters : mapping, optional
        ``runs.parameters`` values every matching run must have, e.g.
        ``{"n_assets": 9, "noise_level": 0.3}``.
    strict_source : bool, default False
        Require ``runs.source`` to equal the golden ``Source``.
    sources : iterable of str, optional
        Compare only the golden records with these ``Source`` tags (e.g.
        ``["single_run"]`` before the sweeps are run). Default: every record.
    basis : Basis or str, default "event_conditional"
        KPI basis to compare (the thesis evaluated event-conditionally).
    evaluation_beta : float, default 0.95
        ``beta`` of the VaR and CVaR KPIs (thesis ``BENCHMARK_BETA``).
    baseline_parameters : mapping, optional
        For each optional key parameter (:data:`EXTRA_PARAMETER_COLUMNS`:
        ``noise_level``, ``n_assets``), the value a run must have when a
        golden record leaves it empty, e.g. ``{"noise_level": 0.3,
        "n_assets": 9}``. Without it, such a record matches any value.
    run_ids : iterable of str, optional
        Consider only these store runs (each must be committed). Default:
        every committed run.

    Returns
    -------
    ParityResult
        The comparison tables and every finding.

    Raises
    ------
    HarnessError
        If the store holds data the harness cannot read unambiguously (e.g.
        two KPI rows for one subject), or a golden cluster has no members.
    StoreError
        If a run of ``run_ids`` is not in the store.
    """
    tol = Tolerances() if tolerances is None else tolerances
    fixed = dict(fixed_parameters or {})
    baseline = dict(baseline_parameters or {})
    unknown = sorted(set(baseline) - set(EXTRA_PARAMETER_COLUMNS.values()))
    if unknown:
        raise HarnessError(
            f"baseline_parameters names no optional key parameter: {unknown}"
        )
    basis_value = Basis(basis).value
    restrict = None if run_ids is None else frozenset(run_ids)
    wanted = None if sources is None else frozenset(sources)
    keys = [k for k in golden.keys() if wanted is None or k.source in wanted]
    runs = _load_store(
        store,
        basis=basis_value,
        evaluation_beta=evaluation_beta,
        run_ids=restrict,
        locations=any(k.locations is not None for k in keys),
    )
    by_kind: dict[tuple[str, str], list[_StoreRun]] = defaultdict(list)
    for run in runs.values():
        by_kind[(run.scope, run.objective)].append(run)

    payouts_by_key: dict[RecordKey, list[GoldenPayout]] = defaultdict(list)
    for p in golden.payouts:
        payouts_by_key[p.key].append(p)
    kpis_by_key: dict[RecordKey, list[GoldenKpis]] = defaultdict(list)
    for k in golden.kpis:
        kpis_by_key[k.key].append(k)
    objectives_by_key: dict[RecordKey, list[GoldenObjective]] = defaultdict(list)
    for o in golden.objectives or ():
        objectives_by_key[o.key].append(o)

    out = _Collector()
    matched: set[str] = set()
    for key in keys:
        candidates = sorted(
            run.run_id
            for run in by_kind[(key.scope, key.objective)]
            if _matches(
                key,
                run,
                fixed=fixed,
                strict_source=strict_source,
                rel_tol=tol.parameter_rtol,
                baseline=baseline,
            )
        )
        matched.update(candidates)
        run = runs[candidates[0]] if len(candidates) == 1 else None
        out.runs.append(
            {
                **_key_fields(key),
                "run_id": "" if run is None else run.run_id,
                "config_hash": "" if run is None else run.config_hash,
                "run_source": "" if run is None else run.source,
                "problems": 0 if run is None else len(run.problems),
                "failed": 0 if run is None else len(run.failed),
                "candidates": len(candidates),
            }
        )
        if run is None:
            kind = FindingKind.AMBIGUOUS_RUN if candidates else FindingKind.MISSING_RUN
            detail = (
                f"{len(candidates)} runs match: {', '.join(candidates)}"
                if candidates
                else f"no run with scope {key.scope}, objective {key.objective} "
                "and these parameters"
            )
            out.findings.append(Finding(kind, key, detail=detail))
            for p in payouts_by_key[key]:
                out.payouts.append(
                    {
                        **_key_fields(key),
                        "entity_id": p.entity_id,
                        "n_levels": len(p.levels),
                        "max_abs_diff": math.nan,
                        "max_rel_diff": math.nan,
                        "edge_diff": math.nan,
                        "status": "missing",
                    }
                )
            for k in kpis_by_key[key]:
                for column in KPI_COLUMNS:
                    out.kpis.append(
                        {
                            **_key_fields(key),
                            "subject": k.subject,
                            "kpi": column,
                            "golden": k.values[column],
                            "ours": math.nan,
                            "abs_error": math.nan,
                            "rel_error": math.nan,
                            "status": "missing",
                        }
                    )
            for o in objectives_by_key[key]:
                out.objectives.append(
                    {
                        **_key_fields(key),
                        "problem_id": o.problem_id,
                        "derivation": o.derivation,
                        "kpi_source": o.kpi_source,
                        "golden": o.value,
                        "ours": math.nan,
                        "abs_error": math.nan,
                        "rel_error": math.nan,
                        "status": "missing",
                    }
                )
        else:
            for p in payouts_by_key[key]:
                _compare_payout(p, run, tol, out)
            for k in kpis_by_key[key]:
                _compare_kpis(k, run, tol, out)
            for o in objectives_by_key[key]:
                _compare_objective(o, run, tol, out)
        if key.approach == CLUSTER_APPROACH:
            members = _golden_clusters(key, payouts_by_key[key], kpis_by_key[key])
            if members:
                _compare_clusters(key, members, run, out)

    value_columns = ("golden", "ours", "abs_error", "rel_error", "status")
    unmatched = [
        {
            "run_id": run.run_id,
            "source": run.source,
            "scope": run.scope,
            "objective": run.objective,
            "parameters": json.dumps(run.parameters, sort_keys=True),
        }
        for run_id, run in sorted(runs.items())
        if run_id not in matched
    ]
    return ParityResult(
        kpis=_frame(out.kpis, (*_KEY_OUT, "subject", "kpi", *value_columns)),
        objectives=_frame(
            out.objectives,
            (*_KEY_OUT, "problem_id", "derivation", "kpi_source", *value_columns),
        ),
        payouts=_frame(
            out.payouts,
            (
                *_KEY_OUT,
                "entity_id",
                "n_levels",
                "max_abs_diff",
                "max_rel_diff",
                "edge_diff",
                "status",
            ),
        ),
        clusters=_frame(out.clusters, (*_KEY_OUT, "golden", "ours", "status")),
        findings=tuple(
            sorted(
                out.findings,
                key=lambda f: (f.key.sort_key(), f.kind.value, f.subject, f.item),
            )
        ),
        unmatched_runs=pd.DataFrame(
            unmatched,
            columns=["run_id", "source", "scope", "objective", "parameters"],
        ),
        n_store_runs=len(runs),
        objectives_available=golden.objectives is not None,
        golden_files=dict(golden.files),
        store_root=str(store.root),
        tolerances=tol,
        basis=basis_value,
        evaluation_beta=evaluation_beta,
        fixed_parameters=fixed,
        strict_source=strict_source,
        sources=None if wanted is None else tuple(sorted(wanted)),
        golden_content=dict(golden.content_sha256),
        matched_runs=_frame(
            out.runs,
            (
                *_KEY_OUT,
                "run_id",
                "config_hash",
                "run_source",
                "problems",
                "failed",
                "candidates",
            ),
        ),
        baseline_parameters=baseline,
        restricted=restrict is not None,
    )
