"""Site bundles: what ``parametric-insurance-design export-site`` writes.

Owner: MAR-200 (W-01a). The website (``site/``, Quarto + OJS, ADR 0003)
never solves and never reads the result store: it reads one **bundle** per
config, a directory of small files that this module exports from the store.
The core command ``parametric-insurance-design export-site CONFIG``
(``parametric_insurance_design.cli``) imports this module lazily, works out
the ``run_id`` of every single run and sweep point of the config (as
``figures`` does) and calls :func:`export_site`. Like the figures, the export
reads the store and never solves: a run missing from the store is an error
(:class:`~parametric_insurance_design_viz.errors.MissingRunError`).

Bundle layout
-------------
One file per slice, so a page loads only what it shows. JSON for the
manifest and the small indexes, uncompressed Arrow IPC (the file format,
``.arrow``; Quarto OJS reads it with ``FileAttachment(...).arrow()``) for the
tables:

==============================  ==============================================
File                            Content
==============================  ==============================================
``manifest.json``               :func:`export_site` "Manifest" below
``runs.json``                   every exported run: scope, objective,
                                parameters, splits, per-problem status
``locations.json``              the portfolio's locations: id, name,
                                coordinates, value (the prepared EventSet)
``baseline.payouts.arrow``      payout grids of the config's single runs: one
                                row per (run, entity, bin)
``baseline.kpis.arrow``         the ``kpis`` rows of the single runs
``baseline.exceedance.arrow``   the ``exceedance`` rows of the single runs
``baseline.map.arrow``          per (run, location): its entity and its
                                expected loss, payout and uncovered loss,
                                with their source (``kpi_level``,
                                ``allocation``; "Map" below)
``baseline.events.arrow``       opt-in (``include_events``): the event data
                                under each entity, the figures' ``events``
                                table
``sweep.<p>.payouts.arrow``     as ``baseline.*``, for every point of the
``sweep.<p>.kpis.arrow``        config's sweep of parameter ``<p>``, with the
``sweep.<p>.exceedance.arrow``  point's value in ``sweep_value``
==============================  ==============================================

Only the sweeps of :data:`SITE_SWEEP_PARAMETERS` (the explorers' alpha, beta,
budget loading kappa and bin count) are exported. The manifest lists the
config's other sweeps under ``sweeps_not_exported``.

k-fold configs (MAR-208)
------------------------
A k-fold config stores a run per scope x objective x fold (MAR-22), so each
scope x objective has ``k`` out-of-sample values, each over ``1/k`` of the
years. Its bundle shows the **pooled** out-of-sample portfolio KPIs that the
core computes on demand (``experiment.kfold.pooled_kpis``, every year
evaluated by the design calibrated without it; MAR-151), as the ``figures``
command does. The ``export-site`` command computes them and passes their
table as ``pooled_kpis=``; :func:`export_site` checks it against the runs.
A k-fold bundle holds:

==============================  ==============================================
File                            Content
==============================  ==============================================
``runs.json``                   every fold run, with its ``fold``
``locations.json``              as above
``baseline.payouts.arrow``      each fold's payout grid, with a ``fold``
                                column (one design per fold)
``baseline.pooled_kpis.arrow``  the pooled table: one row per pooled scope x
                                objective and KPI (``eval_split = "pooled"``,
                                portfolio level, ``run_ids`` the fold runs
                                joined by ``";"``), with ``scope_key``
==============================  ==============================================

and a ``kfold`` section in the manifest: ``k``, the pooled designs and those
not pooled (a failed fold), the pooled rule, and the slices left out with the
reason: the per-fold ``kpis``, ``exceedance`` and ``map`` rows (each over
``1/k`` of the years; the pooled rule covers the portfolio KPIs only) and the
sweeps (the pooled rule covers the single runs). Non-k-fold manifests have
no ``kfold`` key.

Map (MAR-216)
-------------
``evaluate`` writes per-location KPI rows only under an explicit allocation
rule, which splits each design problem's payout across its locations, at
``level = "location_by_value"`` or ``"location_by_loss"`` (MAR-100); it
never writes the reserved plain ``location`` level. A location's numbers in
``baseline.map.arrow`` come from

* the run's ``location_by_<rule>`` rows, if it has them: ``kpi_level`` is
  that level and ``allocation`` the rule (``value`` or ``loss``);
* else, in the **individual scope only**, its entity's rows (one location
  per design problem, so the payout is the location's own):
  ``kpi_level = "entity"``, ``allocation = "none"``;
* else nothing: a joint design (cluster or portfolio scope) without
  allocation rows has null numbers, ``kpi_level`` and ``allocation`` for
  every location. Its entity rows are one of several optimal splits of the
  design problem's payout, the one the solver returned (MAR-100), and are
  never shown as per-location cover (review finding F8). Its portfolio and
  problem KPIs are in ``baseline.kpis.arrow`` as for every run.

The manifest records the source of every run's numbers under ``map``:
``rule`` (the text above), ``allocations`` (the rules of the per-location
rows in the bundle, sorted) and ``runs`` (per baseline run: ``run_id``,
``scope_key``, ``objective``, ``kpi_level``, ``allocation``; both null for a
joint design without allocation rows). The key is additive, so the format
version stays 1; a k-fold bundle, which has no map, has no ``map`` key. A run
with plain ``location`` rows, with rows of several rules, or whose allocation
rows miss a location in one of its evaluations is refused
(:class:`BundleError`). The split filter applies to the map rows as to the
other split slices; the ``map`` section is per run, so it is unaffected.

Rules (stated in the manifest, under ``rules``)
-----------------------------------------------
* **Infinity.** Strict JSON has no infinities, and Arrow JS hands them to
  the page as ``-Infinity``, which charts cannot place. The one infinite
  value the export knows is the lower edge ``-inf`` of the zero row of a
  ``below_attachment = "zero"`` run (``param_index = -1``, MAR-178): it is
  written as **null**, in both formats, and the column's entry in the
  manifest says that its nulls mean ``-inf``. Any other infinite value is
  refused (:class:`BundleValueError`).
* **NaN.** Never written. In a column whose store schema allows undefined
  values (e.g. ``kpis.value``, a correlation with zero variance) it is
  written as **null**, and the manifest gives the column's null count and
  what its nulls mean; anywhere else it is refused
  (:class:`BundleValueError`). A column has at most one meaning of null.
* **Integers** are 32-bit (Arrow JS reads 64-bit integers as ``BigInt``,
  which charts do not accept); a value out of range is refused. Strings are
  dictionary-encoded UTF-8, with the narrowest index type.
* **Events** (about 6 MB per grid on the thesis set, MAR-110) are left out
  unless ``include_events``.
* **Size budget** (:class:`SizeBudget`): every file, the manifest included,
  must fit ``max_file_bytes`` and the data files together
  ``max_bundle_bytes``. Over budget is a :class:`BundleBudgetError` raised
  before anything is written, never a truncation.

Split filter (MAR-213)
----------------------
A holdout run stores its KPIs and exceedance curves on the train years
(``eval_split = "train"``, in sample) and on the test years (``"test"``, out
of sample). ``eval_split="test"`` (``export-site --split test``) keeps only
the rows of that evaluation split in the ``kpis``, ``exceedance`` and ``map``
slices of the baseline and of every sweep, so a published bundle holds
out-of-sample numbers only (the publication rule, AGENTS.md). The payout
tables are unaffected: a design has no split. The manifest records the
filter under ``split_filter``: the split kept (null without a filter), the
slices it applies to and the rows it removed per file. Every exported run
must hold rows of the split kept, else :class:`BundleError` (e.g. ``"test"``
of a ``full``-sample config); a k-fold bundle, which holds the pooled
out-of-sample KPIs only, refuses the filter (:class:`BundleError`).

No silent failures
------------------
* A k-fold config without ``pooled_kpis``, or one that fixes
  ``sample.fold``, is refused
  (:class:`~parametric_insurance_design_viz.kpi_figures.KFoldRunsError`). A
  pooled table that does not match the fold runs (other ``k``, unknown or
  missing designs, a design pooled over a failed fold, a duplicate KPI row)
  is an :class:`~parametric_insurance_design_viz.errors.InconsistentRunsError`.
  Sweeps or events asked of a k-fold config are a :class:`BundleError`.
  A scope x objective with a failed fold is listed under
  ``kfold.not_pooled``, and its failed fold runs under ``runs.skipped``.
* A run with a failed design problem is listed in the manifest
  (``runs.skipped``) and in ``runs.json`` (``complete: false``, with the
  failed problems), and none of its rows are exported;
  :attr:`ExportReport.ok` is False.
* A sweep parameter that is not exported or not configured is an error
  (:class:`BundleError`).
* An output directory holding files that are not part of a bundle is
  refused; a previous bundle there is replaced: the files its manifest lists
  are removed and nothing else.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any, Final, Literal, cast

import numpy as np
import pandas as pd
import pyarrow as pa

from parametric_insurance_design.evaluate import ALLOCATION_LEVELS, Allocation
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    to_dict,
)
from parametric_insurance_design.experiment.kfold import (
    POOLED_COLUMNS,
    POOLED_SPLIT,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.payout import NO_BIN
from parametric_insurance_design.records import KpiLevel, Split
from parametric_insurance_design.scopes import Individual
from parametric_insurance_design_viz.command import SweepRun
from parametric_insurance_design_viz.errors import (
    InconsistentRunsError,
    MissingRunError,
    VizError,
)
from parametric_insurance_design_viz.kpi_figures import KFoldRunsError
from parametric_insurance_design_viz.payout_functions import (
    below_attachment_mode,
    payout_steps,
)
from parametric_insurance_design_viz.reader import (
    ResultReader,
    RunResult,
    check_eventset,
    entity_events,
)

__all__ = [
    "BUNDLE_FORMAT",
    "BUNDLE_FORMAT_VERSION",
    "DEFAULT_MAX_BUNDLE_BYTES",
    "DEFAULT_MAX_FILE_BYTES",
    "EVAL_SPLITS",
    "MANIFEST",
    "SITE_SWEEP_PARAMETERS",
    "BundleBudgetError",
    "BundleChecksumError",
    "BundleError",
    "BundleFile",
    "BundleValueError",
    "ExportReport",
    "SizeBudget",
    "SkippedRun",
    "SweepRun",
    "export_site",
    "read_bundle",
    "read_slice",
]

BUNDLE_FORMAT: Final[str] = "parametric-insurance-design/site-bundle"
"""``format`` of every bundle manifest."""

BUNDLE_FORMAT_VERSION: Final[int] = 1
"""``format_version`` of the bundles this module writes and reads."""

MANIFEST: Final[str] = "manifest.json"
"""File name of the bundle manifest."""

SITE_SWEEP_PARAMETERS: Final[tuple[str, ...]] = (
    "alpha",
    "beta",
    "budget_loading",
    "n_bins",
)
"""Sweep parameters the explorers show: alpha, beta, budget loading, bins."""

EVAL_SPLITS: Final[tuple[str, ...]] = tuple(s.value for s in Split)
"""Evaluation splits the split filter accepts: ``full``, ``train``, ``test``."""

DEFAULT_MAX_FILE_BYTES: Final[int] = 2_000_000
"""Default budget per file: 2 MB (decimal)."""

DEFAULT_MAX_BUNDLE_BYTES: Final[int] = 10_000_000
"""Default budget of a bundle's data files together: 10 MB (decimal)."""

_JSON: Final[str] = "json"
_ARROW: Final[str] = "arrow"
_BASELINE: Final[str] = "baseline"
_SWEEP: Final[str] = "sweep"

_INFINITY_RULE: Final[str] = (
    "Strict JSON has no infinities: an infinite value is written as null, in "
    "JSON and in Arrow alike, only in the columns whose manifest entry has "
    "null_means '-inf' (payouts.lower: the zero row of a below_attachment "
    "'zero' run, param_index -1, covers the index range below the attachment). "
    "Any other infinite value is refused at export."
)
_NAN_RULE: Final[str] = (
    "NaN is never written. In a column whose store schema allows undefined "
    "values it is written as null, and the column's manifest entry gives its "
    "null count and what null means there; in any other column it is refused "
    "at export. A column has at most one meaning of null."
)
_INTEGER_RULE: Final[str] = (
    "Integers are 32-bit (Arrow JS reads 64-bit integers as BigInt); strings "
    "are dictionary-encoded UTF-8 with the narrowest signed index (int8, "
    "int16 or int32); floats are 64-bit."
)
_ARROW_RULE: Final[str] = (
    "Tables are Arrow IPC files (.arrow), uncompressed, one record batch: "
    "Quarto OJS reads them with FileAttachment(path).arrow()."
)
_BUDGET_RULE: Final[str] = (
    "Every file, the manifest included, fits max_file_bytes, and the data "
    "files together fit max_bundle_bytes (both in bytes). Over budget is an "
    "error at export, never a truncation."
)
_CHECKSUM_RULE: Final[str] = (
    "Every data file is listed under files with its size in bytes and the "
    "SHA-256 of its bytes; the manifest itself is not."
)

_RULES: Final[Mapping[str, str]] = {
    "infinity": _INFINITY_RULE,
    "nan": _NAN_RULE,
    "types": _INTEGER_RULE,
    "arrow": _ARROW_RULE,
    "budget": _BUDGET_RULE,
    "checksums": _CHECKSUM_RULE,
}
"""The rules every manifest states (``rules``)."""

_EVENTS_NOTE: Final[str] = (
    "the event data under each entity (baseline.events.arrow): left out by "
    "default (about 6 MB per grid on the thesis set), included with "
    "export-site --events"
)

_UNDEFINED: Final[str] = (
    "undefined (the store's null: e.g. a zero-variance correlation)"
)
_NO_CI: Final[str] = "no confidence bounds (the config has no bootstrap section)"
_NO_BETA: Final[str] = "not a VaR/CVaR KPI"
_NOT_PER_LOCATION: Final[str] = (
    "not available per location: the run is a joint design (cluster or "
    "portfolio scope) without per-location rows under an allocation rule, "
    "and the solver's split of its payout across locations is not shown "
    "(see the manifest's map section)"
)

_ALLOCATION_OF: Final[Mapping[str, str]] = {
    level.value: rule.value for rule, level in ALLOCATION_LEVELS.items()
}
"""Allocation rule per per-location KPI level (``location_by_value``: ``value``)."""

_MAP_RULE: Final[str] = (
    "Per run, evaluation and location: the location's expected loss, payout "
    "and uncovered loss. They come from the run's per-location KPI rows under "
    "an allocation rule, which splits each design problem's payout across its "
    "locations (kpi_level 'location_by_value', allocation 'value': pro rata "
    "to insured value; kpi_level 'location_by_loss', allocation 'loss': pro "
    "rata to loss; evaluate, MAR-100). Without them, a run of the individual "
    "scope takes each location's entity rows (kpi_level 'entity', allocation "
    "'none': one location per design problem, so the payout is the "
    "location's own). A joint design (cluster or portfolio scope) without "
    "them has no per-location numbers (null): its entity rows are one of "
    "several optimal splits of the design problem's payout, the one the "
    "solver returned, and are never shown as per-location cover. runs gives "
    "the source of each run's numbers, allocations the rules in the bundle."
)
_NO_NAME: Final[str] = "the EventSet gives the location no name"
_NO_POOLED_CI: Final[str] = (
    "no confidence bounds: the config has no bootstrap section (ci_level is "
    "null too), or the KPI is undefined in some bootstrap replicate (ci_level "
    "is set)"
)

_POOLED_RULE: Final[str] = (
    "The k test blocks partition the years, so every year is evaluated by "
    "exactly one design, the one calibrated on the other k - 1 blocks. The "
    "pooled KPIs are the portfolio KPIs of that one out-of-sample sample over "
    "all years (experiment.kfold.pooled_kpis, MAR-151), not the mean of the "
    "per-fold KPIs. Only the portfolio level is pooled."
)
_KFOLD_NOT_EXPORTED: Final[Mapping[str, str]] = {
    "kpis": (
        "the per-fold KPI rows: each is over 1/k of the years; the bundle has "
        "the pooled portfolio KPIs (baseline.pooled_kpis.arrow)"
    ),
    "exceedance": (
        "the per-fold exceedance curves: each is over 1/k of the years, and "
        "the pooled rule covers the portfolio KPIs only"
    ),
    "map": (
        "the per-location numbers: entities are not pooled across folds (the "
        "cluster partition differs per fold)"
    ),
    "sweeps": (
        "the sweeps: the pooled rule covers the single runs; export a holdout "
        "config for swept explorers"
    ),
}
"""Slices a k-fold bundle leaves out, with the reason (``kfold.not_exported``)."""

_SPLIT_SLICES: Final[tuple[str, ...]] = ("kpis", "exceedance", "map")
"""Slices with an ``eval_split`` column, which the split filter applies to."""
_SPLIT_KEPT: Final[str] = (
    "Only the rows with eval_split {split!r} of the kpis, exceedance and map "
    "slices (baseline and every sweep) are exported (export-site --split "
    "{split}); the rows of the other evaluation splits were removed "
    "(rows_removed, per file). The payout tables are unaffected: a design has "
    "no split."
)
_SPLIT_NONE: Final[str] = (
    "No split filter: the kpis, exceedance and map slices hold the rows of "
    "every evaluation split the runs stored (their eval_split column)."
)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class BundleError(VizError):
    """A site bundle cannot be written or read as asked."""


class BundleValueError(BundleError):
    """A value breaks a bundle rule: NaN or infinite where none is allowed."""


class BundleBudgetError(BundleError):
    """A bundle file, or the bundle, is over its size budget."""


class BundleChecksumError(BundleError):
    """A bundle file is missing, or its size or SHA-256 differs from the manifest."""


# --------------------------------------------------------------------------
# Public types
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SizeBudget:
    """Size budget of a bundle, in bytes.

    Parameters
    ----------
    max_file_bytes : int, default :data:`DEFAULT_MAX_FILE_BYTES`
        Largest allowed file, the manifest included.
    max_bundle_bytes : int, default :data:`DEFAULT_MAX_BUNDLE_BYTES`
        Largest allowed total of the data files (the manifest excluded).

    Raises
    ------
    BundleError
        If a limit is not a positive integer.
    """

    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES
    max_bundle_bytes: int = DEFAULT_MAX_BUNDLE_BYTES

    def __post_init__(self) -> None:
        """Check that both limits are positive integers."""
        for name in ("max_file_bytes", "max_bundle_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise BundleError(f"{name} must be a positive integer, got {value!r}")


@dataclass(frozen=True)
class BundleFile:
    """One data file of a bundle, as the manifest lists it.

    Parameters
    ----------
    path : str
        File name inside the bundle directory.
    format : {"json", "arrow"}
        Encoding.
    slice : str
        What it holds: ``runs``, ``locations``, ``payouts``, ``kpis``,
        ``exceedance``, ``map`` or ``events``.
    group : {"baseline", "sweep"} or None
        The runs it holds: the single runs or one sweep's points; None for
        the indexes.
    parameter : str or None
        The swept parameter of a ``sweep`` file.
    bytes : int
        Size of the file.
    sha256 : str
        ``"sha256:"`` and the hex digest of its bytes.
    rows : int or None
        Rows of an Arrow table; None for JSON.
    columns : tuple of mapping
        Arrow tables: per column its ``name``, ``type``, ``nulls`` (count)
        and ``null_means`` (None if the column has no nulls by rule).
    """

    path: str
    format: str
    slice: str
    group: str | None
    parameter: str | None
    bytes: int
    sha256: str
    rows: int | None = None
    columns: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Return the file's manifest entry."""
        entry: dict[str, Any] = {
            "path": self.path,
            "format": self.format,
            "slice": self.slice,
            "group": self.group,
            "parameter": self.parameter,
            "bytes": self.bytes,
            "sha256": self.sha256,
        }
        if self.format == _ARROW:
            entry["rows"] = self.rows
            entry["columns"] = [dict(c) for c in self.columns]
        return entry


@dataclass(frozen=True)
class SkippedRun:
    """A run left out of the bundle, with the reason.

    Parameters
    ----------
    run_id : str
        The run.
    reason : str
        Why its rows are not exported.
    """

    run_id: str
    reason: str


@dataclass(frozen=True)
class ExportReport:
    """What :func:`export_site` wrote.

    Parameters
    ----------
    out_dir : pathlib.Path
        The bundle directory.
    manifest : mapping
        The manifest, as written to ``manifest.json``.
    files : tuple of BundleFile
        The data files, in manifest order.
    skipped : tuple of SkippedRun
        Runs whose rows were not exported (a failed design problem).
    removed : tuple of str
        Files of a previous bundle in ``out_dir`` that the new one does not
        write, removed.
    """

    out_dir: Path
    manifest: Mapping[str, Any]
    files: tuple[BundleFile, ...]
    skipped: tuple[SkippedRun, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """True if no run was skipped."""
        return not self.skipped

    @property
    def bundle_bytes(self) -> int:
        """Total size of the data files."""
        return sum(f.bytes for f in self.files)


# --------------------------------------------------------------------------
# Columns and encoding
# --------------------------------------------------------------------------

_Kind = Literal["str", "int", "float"]


@dataclass(frozen=True)
class _Col:
    """One column of an exported table.

    ``null`` is what a null means in it (None: no nulls allowed). ``infinite``
    is the one infinite value it may hold, written as null; then ``null``
    must say so.
    """

    name: str
    kind: _Kind
    null: str | None = None
    infinite: Literal["-inf", "+inf"] | None = None

    def __post_init__(self) -> None:
        if self.infinite is not None and self.null != self.infinite:
            raise ValueError(f"column {self.name}: an infinite value needs null_means")


_INT32: Final[tuple[int, int]] = (-(2**31), 2**31 - 1)


def _encode(frame: pd.DataFrame, columns: Sequence[_Col], where: str) -> pa.Table:
    """Encode a frame as an Arrow table by the bundle rules.

    Raises
    ------
    BundleValueError
        If a column holds NaN, null or an infinite value that its spec does
        not allow, or an integer out of the 32-bit range.
    """
    arrays: list[pa.Array] = []
    names: list[str] = []
    for col in columns:
        if col.name not in frame:
            raise BundleValueError(f"{where}: no column {col.name!r}")
        series = cast(pd.Series, frame[col.name]).reset_index(drop=True)
        arrays.append(_encode_column(series, col, where))
        names.append(col.name)
    return pa.Table.from_arrays(arrays, names=names)


def _refuse(where: str, col: _Col, count: int, what: str) -> BundleValueError:
    allowed = f"its nulls mean {col.null!r}" if col.null else "it allows no nulls"
    return BundleValueError(
        f"{where}: column {col.name!r} holds {count} {what} value(s), which the "
        f"bundle rules refuse there ({allowed}); see the manifest rules"
    )


def _encode_column(series: pd.Series, col: _Col, where: str) -> pa.Array:
    if col.kind == "str":
        missing = series.isna().to_numpy()
        if missing.any() and col.null is None:
            raise _refuse(where, col, int(missing.sum()), "null")
        values = [None if m else str(v) for v, m in zip(series, missing, strict=True)]
        return _dictionary(pa.array(values, type=pa.string()))
    numeric = cast(pd.Series, pd.to_numeric(series, errors="raise")).astype("Float64")
    missing = numeric.isna().to_numpy()
    data = numeric.to_numpy(dtype=np.float64, na_value=np.nan)
    with np.errstate(invalid="ignore"):
        neg = np.isneginf(data)
        pos = np.isposinf(data)
    allowed_inf = (
        neg if col.infinite == "-inf" else pos if col.infinite == "+inf" else None
    )
    bad_inf = (neg | pos) if allowed_inf is None else ((neg | pos) & ~allowed_inf)
    if bad_inf.any():
        raise _refuse(where, col, int(bad_inf.sum()), "infinite")
    if missing.any():
        if col.null is None or col.infinite is not None:
            raise _refuse(where, col, int(missing.sum()), "NaN or null")
    null = missing if allowed_inf is None else (missing | allowed_inf)
    if col.kind == "int":
        present = data[~null]
        if present.size and (
            not np.all(present == np.round(present))
            or present.min() < _INT32[0]
            or present.max() > _INT32[1]
        ):
            raise BundleValueError(
                f"{where}: column {col.name!r} holds a value that is not a "
                "32-bit integer"
            )
        ints = np.where(null, 0, data).astype(np.int32)
        return pa.array(ints, type=pa.int32(), mask=null)
    return pa.array(np.where(null, 0.0, data), type=pa.float64(), mask=null)


def _dictionary(strings: pa.Array) -> pa.Array:
    """Dictionary-encode strings with the narrowest signed index type."""
    encoded = strings.dictionary_encode()
    size = len(encoded.dictionary)
    index = pa.int8() if size <= 127 else pa.int16() if size <= 32767 else pa.int32()
    return encoded.cast(pa.dictionary(index, pa.string()))


def _column_info(
    table: pa.Table, columns: Sequence[_Col]
) -> tuple[dict[str, Any], ...]:
    info: list[dict[str, Any]] = []
    for col, array in zip(columns, table.columns, strict=True):
        array_type = array.type
        if pa.types.is_dictionary(array_type):
            type_name = f"dictionary<{array_type.index_type}, utf8>"
        else:
            type_name = str(array_type)
        nulls = int(array.null_count)
        info.append(
            {
                "name": col.name,
                "type": type_name,
                "nulls": nulls,
                "null_means": col.null,
            }
        )
    return tuple(info)


def _arrow_bytes(table: pa.Table) -> bytes:
    """Uncompressed Arrow IPC file bytes of one record batch."""
    sink = io.BytesIO()
    options = pa.ipc.IpcWriteOptions(compression=None)
    batch = table.combine_chunks()
    with pa.ipc.new_file(sink, batch.schema, options=options) as writer:
        writer.write_table(batch, max_chunksize=max(batch.num_rows, 1))
    return sink.getvalue()


def _json_ready(value: object, where: str, path: str = "") -> object:
    """Check a JSON tree: finite numbers only (the bundle rules)."""
    if isinstance(value, Mapping):
        return {
            str(k): _json_ready(v, where, f"{path}.{k}" if path else str(k))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_json_ready(v, where, f"{path}[{i}]") for i, v in enumerate(value)]
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return value
    if isinstance(value, np.generic):
        return _json_ready(value.item(), where, path)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise BundleValueError(
                f"{where}: {path or 'value'} is {value!r}; the bundle rules "
                "write no NaN or infinite value to JSON"
            )
        return value
    raise BundleValueError(f"{where}: {path or 'value'} is not JSON: {value!r}")


def _json_bytes(value: object, where: str, *, indent: int | None = None) -> bytes:
    ready = _json_ready(value, where)
    separators = (",", ": ") if indent is not None else (",", ":")
    text = json.dumps(
        ready, allow_nan=False, ensure_ascii=False, indent=indent, separators=separators
    )
    return (text + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def _optional(value: object) -> float | None:
    """Return a nullable store float as JSON: None for null or NaN."""
    if value is None or value is pd.NA:
        return None
    number = float(value)  # pyright: ignore[reportArgumentType]
    return None if math.isnan(number) else number


# --------------------------------------------------------------------------
# Table specs
# --------------------------------------------------------------------------

_RUN_COLUMNS: Final[tuple[_Col, ...]] = (
    _Col("run_id", "str"),
    _Col("scope", "str"),
    _Col("scope_key", "str"),
    _Col("objective", "str"),
)
_SWEEP_VALUE: Final[_Col] = _Col("sweep_value", "float")
_FOLD: Final[_Col] = _Col("fold", "int")
_POOLED_KPI_COLUMNS: Final[tuple[_Col, ...]] = (
    _Col("scope_position", "int"),
    _Col("scope", "str"),
    _Col("scope_key", "str"),
    _Col("objective", "str"),
    _Col("run_ids", "str"),
    _Col("k", "int"),
    _Col("n_years", "int"),
    _Col("eval_split", "str"),
    _Col("basis", "str"),
    _Col("problem_id", "str"),
    _Col("level", "str"),
    _Col("subject_id", "str"),
    _Col("kpi", "str"),
    _Col("beta", "float", null=_NO_BETA),
    _Col("value", "float", null=_UNDEFINED),
    _Col("ci_low", "float", null=_NO_POOLED_CI),
    _Col("ci_high", "float", null=_NO_POOLED_CI),
    _Col("ci_level", "float", null=_NO_CI),
    _Col("n_bootstrap", "int", null=_NO_CI),
)
"""Columns of ``baseline.pooled_kpis.arrow``: ``POOLED_COLUMNS`` plus ``scope_key``."""

_PAYOUT_COLUMNS: Final[tuple[_Col, ...]] = (
    _Col("problem_id", "str"),
    _Col("entity_id", "str"),
    _Col("location_ids", "str"),
    _Col("below_attachment", "str"),
    _Col("param_index", "int"),
    _Col("lower", "float", null="-inf", infinite="-inf"),
    _Col("upper", "float"),
    _Col("value", "float"),
)
_EVAL_COLUMNS: Final[tuple[_Col, ...]] = (
    _Col("problem_id", "str"),
    _Col("eval_split", "str"),
    _Col("fold", "int"),
    _Col("basis", "str"),
    _Col("level", "str"),
    _Col("subject_id", "str"),
)
_KPI_COLUMNS: Final[tuple[_Col, ...]] = (
    *_EVAL_COLUMNS,
    _Col("kpi", "str"),
    _Col("beta", "float", null=_NO_BETA),
    _Col("value", "float", null=_UNDEFINED),
    _Col("ci_low", "float", null=_NO_CI),
    _Col("ci_high", "float", null=_NO_CI),
    _Col("ci_level", "float", null=_NO_CI),
    _Col("n_bootstrap", "int", null=_NO_CI),
)
_EXCEEDANCE_COLUMNS: Final[tuple[_Col, ...]] = (
    *_EVAL_COLUMNS,
    _Col("quantity", "str"),
    _Col("curve", "str"),
    _Col("return_period", "float"),
    _Col("value", "float"),
)
_MAP_KPIS: Final[tuple[str, ...]] = (
    "expected_loss",
    "expected_payout",
    "expected_uncovered",
)
_MAP_COLUMNS: Final[tuple[_Col, ...]] = (
    _Col("eval_split", "str"),
    _Col("fold", "int"),
    _Col("basis", "str"),
    _Col("location_id", "str"),
    _Col("problem_id", "str"),
    _Col("entity_id", "str"),
    _Col("kpi_level", "str", null=_NOT_PER_LOCATION),
    _Col("allocation", "str", null=_NOT_PER_LOCATION),
    *(_Col(k, "float", null=_NOT_PER_LOCATION) for k in _MAP_KPIS),
)
_EVENT_COLUMNS: Final[tuple[_Col, ...]] = (
    _Col("scope", "str"),
    _Col("scope_key", "str"),
    _Col("problem_id", "str"),
    _Col("entity_id", "str"),
    _Col("row", "int"),
    _Col("index", "float"),
    _Col("loss", "float"),
    _Col("rate", "float"),
)


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class _Exported:
    """A run of the bundle with its labels."""

    run: RunResult
    scope_key: str
    sweep_value: float | None = None
    fold: int | None = None

    def labels(self) -> dict[str, Any]:
        labels: dict[str, Any] = {
            "run_id": self.run.run_id,
            "scope": self.run.scope,
            "scope_key": self.scope_key,
            "objective": self.run.objective,
        }
        if self.sweep_value is not None:
            labels["sweep_value"] = self.sweep_value
        if self.fold is not None:
            labels["fold"] = self.fold
        return labels


@dataclass
class _Builder:
    """Encoded files of a bundle, in order, before anything is written."""

    budget: SizeBudget
    data: dict[str, bytes] = field(default_factory=dict)
    files: list[BundleFile] = field(default_factory=list)

    def add_json(self, path: str, slice_name: str, value: object) -> None:
        self._add(path, _JSON, slice_name, None, None, _json_bytes(value, path))

    def add_table(
        self,
        path: str,
        slice_name: str,
        frame: pd.DataFrame,
        columns: Sequence[_Col],
        *,
        group: str,
        parameter: str | None = None,
    ) -> None:
        table = _encode(frame, columns, path)
        self._add(
            path,
            _ARROW,
            slice_name,
            group,
            parameter,
            _arrow_bytes(table),
            rows=table.num_rows,
            columns=_column_info(table, columns),
        )

    def _add(
        self,
        path: str,
        fmt: str,
        slice_name: str,
        group: str | None,
        parameter: str | None,
        data: bytes,
        *,
        rows: int | None = None,
        columns: tuple[dict[str, Any], ...] = (),
    ) -> None:
        if path in self.data:  # pragma: no cover - names are built uniquely
            raise BundleError(f"bundle file {path!r} written twice")
        self.data[path] = data
        self.files.append(
            BundleFile(
                path=path,
                format=fmt,
                slice=slice_name,
                group=group,
                parameter=parameter,
                bytes=len(data),
                sha256=_sha256(data),
                rows=rows,
                columns=columns,
            )
        )

    def check_budget(self, manifest_bytes: int) -> None:
        """Raise :class:`BundleBudgetError` if a file or the bundle is too big."""
        limit = self.budget.max_file_bytes
        over = [(f.path, f.bytes) for f in self.files if f.bytes > limit]
        if manifest_bytes > limit:
            over.append((MANIFEST, manifest_bytes))
        total = sum(f.bytes for f in self.files)
        problems: list[str] = []
        if over:
            listed = ", ".join(f"{p} ({n:,} bytes)" for p, n in over)
            problems.append(f"over the {limit:,}-byte file budget: {listed}")
        if total > self.budget.max_bundle_bytes:
            problems.append(
                f"the data files total {total:,} bytes, over the "
                f"{self.budget.max_bundle_bytes:,}-byte bundle budget"
            )
        if problems:
            raise BundleBudgetError(
                "the bundle is over its size budget, nothing was written: "
                + "; ".join(problems)
                + ". Export fewer sweeps (--parameter), leave the events out, "
                "or raise the budget (--max-file-bytes, --max-bundle-bytes)"
            )


@dataclass
class _SplitFilter:
    """The split filter of a bundle and the rows it removed, per file."""

    eval_split: str | None
    removed: dict[str, int] = field(default_factory=dict)

    def check(self, runs: Iterable[_Exported]) -> None:
        """Raise :class:`BundleError` if a run has no KPI row of the split kept."""
        if self.eval_split is None:
            return
        for item in runs:
            stored = sorted({str(s) for s in item.run.kpis["eval_split"]})
            if self.eval_split not in stored:
                raise BundleError(
                    f"run {item.run.run_id} ({item.scope_key} x "
                    f"{item.run.objective}) has no KPI rows of eval_split "
                    f"{self.eval_split!r}, only of {stored}: the split filter "
                    "would leave its numbers out. Export a split its sample "
                    "evaluates (a holdout sample: 'test' out of sample)"
                )

    def apply(self, path: str, frame: pd.DataFrame) -> pd.DataFrame:
        """Keep the rows of the split kept; record how many were removed."""
        if self.eval_split is None:
            return frame
        keep = (frame["eval_split"].astype(str) == self.eval_split).to_numpy()
        self.removed[path] = int((~keep).sum())
        return _rows(frame, keep).reset_index(drop=True)

    def section(self) -> dict[str, Any]:
        """Return the manifest's ``split_filter`` section."""
        if self.eval_split is None:
            return {
                "eval_split": None,
                "slices": [],
                "rows_removed": {},
                "rule": _SPLIT_NONE,
            }
        return {
            "eval_split": self.eval_split,
            "slices": list(_SPLIT_SLICES),
            "rows_removed": dict(self.removed),
            "rule": _SPLIT_KEPT.format(split=self.eval_split),
        }


def _check_split(
    config: ExperimentConfig, eval_split: str | None, k: int | None
) -> None:
    """Raise :class:`BundleError` for an unknown split or one asked of k-fold."""
    if eval_split is None:
        return
    if eval_split not in EVAL_SPLITS:
        raise BundleError(
            f"eval_split must be one of {list(EVAL_SPLITS)}, got {eval_split!r}"
        )
    if k is not None:
        raise BundleError(
            f"config {config.name!r} is k-fold: its bundle holds the pooled "
            f"out-of-sample KPIs only (eval_split {POOLED_SPLIT!r}), so the "
            f"split filter (eval_split {eval_split!r}) does not apply"
        )


def _scope_keys(config: ExperimentConfig) -> list[str]:
    """Name per configured scope: its kind, numbered on repeats (as figures)."""
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


def _frame(parts: Iterable[pd.DataFrame], columns: Sequence[_Col]) -> pd.DataFrame:
    frames = [p for p in parts if len(p)]
    if not frames:
        return pd.DataFrame({c.name: pd.Series([], dtype=object) for c in columns})
    return pd.concat(frames, ignore_index=True)


def _labelled(frame: pd.DataFrame, run: _Exported) -> pd.DataFrame:
    return frame.assign(**run.labels())


def _payouts(runs: Sequence[_Exported]) -> pd.DataFrame:
    """Payout grids, with the zero row of each ``"zero"`` entity (MAR-178)."""
    parts: list[pd.DataFrame] = []
    for item in runs:
        steps = payout_steps([item.run])
        mode = below_attachment_mode(item.run)
        steps = steps.assign(below_attachment=mode)
        if mode == "zero":
            pieces: list[pd.DataFrame] = []
            for _, bins in steps.groupby(["problem_id", "entity_id"], sort=False):
                pieces.append(
                    bins.iloc[[0]].assign(
                        param_index=NO_BIN,
                        lower=-np.inf,
                        upper=float(bins["lower"].iloc[0]),
                        value=0.0,
                    )
                )
                pieces.append(bins)
            steps = pd.concat(pieces, ignore_index=True)
        parts.append(_labelled(steps.drop(columns=["scope", "objective"]), item))
    return _frame(parts, _PAYOUT_COLUMNS)


def _table(
    runs: Sequence[_Exported], name: str, columns: Sequence[_Col]
) -> pd.DataFrame:
    return _frame((_labelled(getattr(r.run, name), r) for r in runs), columns)


def _rows(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    """Return the rows of ``frame`` where ``mask`` is true."""
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


def _pivot(kpis: pd.DataFrame, index: list[str], suffix: str) -> pd.DataFrame:
    """One column per map KPI (``<kpi>@<suffix>``), one row per ``index``."""
    if kpis.empty:
        return pd.DataFrame({c: [] for c in index})
    wide = kpis.pivot_table(
        index=index, columns="kpi", values="value", aggfunc="first", dropna=False
    )
    wide.columns = [f"{c}@{suffix}" for c in wide.columns]
    return wide.reset_index()


def _map(runs: Sequence[_Exported]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Per (run, evaluation, location): its entity and its KPIs, where defined.

    A location's numbers come from the run's per-location rows under an
    allocation rule (``location_by_value`` or ``location_by_loss``, MAR-100)
    if the run has them; else, in the individual scope only, from its
    entity's rows (one location per design problem); else they are null
    (``kpi_level`` and ``allocation`` null too). The entity rows of a joint
    design (cluster or portfolio scope) are the solver's split of its design
    problem's payout and are never used (review finding F8). See
    :data:`_MAP_RULE`.

    Returns
    -------
    pandas.DataFrame
        The map rows, labelled with their run.
    list of dict
        Per run: ``run_id``, ``scope_key``, ``objective`` and the source of
        its numbers, ``kpi_level`` and ``allocation`` (both null when the map
        has no per-location numbers for the run): the manifest's
        ``map.runs``.

    Raises
    ------
    BundleError
        If a run holds rows at the reserved plain ``location`` level or rows
        of several allocation rules, if its allocation rows miss a location
        in an evaluation, or if an individual-scope entity covers several
        locations.
    BundleValueError
        If a location has a source of numbers but one of them is undefined:
        the map's nulls mean only "not available per location".
    """
    parts: list[pd.DataFrame] = []
    sources: list[dict[str, Any]] = []
    evaluation = ["eval_split", "fold", "basis"]
    for item in runs:
        run = item.run
        members = run.entities.loc[:, ["problem_id", "entity_id", "location_id"]]
        kpis = _rows(run.kpis, run.kpis["kpi"].isin(_MAP_KPIS))
        level, allocation = _map_source(item, kpis)
        grid = kpis.loc[:, evaluation].drop_duplicates().merge(members, how="cross")
        if level is None:
            rows = grid
        elif level == KpiLevel.ENTITY.value:
            if members.duplicated(["problem_id", "entity_id"]).any():
                raise BundleError(  # pragma: no cover - one location per entity
                    f"baseline.map.arrow: run {run.run_id} is in the individual "
                    "scope but an entity covers several locations"
                )
            subject, keys = "entity_id", [*evaluation, "problem_id", "entity_id"]
        else:
            subject, keys = "location_id", [*evaluation, "location_id"]
        if level is not None:
            source = _rows(kpis, kpis["level"] == level).rename(
                columns={"subject_id": subject}
            )
            present = source.loc[:, keys].drop_duplicates().assign(_present=True)
            rows = grid.merge(_pivot(source, keys, "src"), on=keys, how="left")
            rows = rows.merge(present, on=keys, how="left")
            missing = int(rows["_present"].isna().sum())
            if missing:
                raise BundleError(
                    f"baseline.map.arrow: run {run.run_id} ({item.scope_key} x "
                    f"{run.objective}) has {level!r} rows for "
                    f"{len(rows) - missing} of its {len(rows)} (evaluation, "
                    "location) pairs; the map needs every location in every "
                    "evaluation"
                )
        out = rows.loc[:, [*evaluation, "location_id", "problem_id", "entity_id"]]
        out["kpi_level"] = level
        out["allocation"] = allocation
        for kpi in _MAP_KPIS:
            name = f"{kpi}@src"
            out[kpi] = (
                cast(pd.Series, rows[name]).astype(np.float64)
                if name in rows
                else pd.Series(np.nan, index=rows.index, dtype=np.float64)
            )
        undefined = out.loc[:, list(_MAP_KPIS)].isna().to_numpy().any(axis=1)
        if level is not None and undefined.any():
            raise BundleValueError(
                f"baseline.map.arrow: run {run.run_id} has {int(undefined.sum())} "
                "location rows with an undefined expected loss, payout or "
                "uncovered loss; the map's nulls mean only "
                f"{_NOT_PER_LOCATION!r}"
            )
        parts.append(_labelled(out, item))
        sources.append(
            {
                "run_id": run.run_id,
                "scope_key": item.scope_key,
                "objective": run.objective,
                "kpi_level": level,
                "allocation": allocation,
            }
        )
    return _frame(parts, _MAP_COLUMNS), sources


def _map_source(item: _Exported, kpis: pd.DataFrame) -> tuple[str | None, str | None]:
    """Return the ``(kpi_level, allocation)`` the map takes a run's numbers from.

    ``(None, None)`` for a joint design without allocation rows (see
    :func:`_map`).

    Raises
    ------
    BundleError
        If the run holds plain ``location`` rows or rows of several rules.
    """
    run = item.run
    levels = {str(v) for v in kpis["level"].unique()}
    if KpiLevel.LOCATION.value in levels:
        raise BundleError(
            f"baseline.map.arrow: run {run.run_id} ({item.scope_key} x "
            f"{run.objective}) has KPI rows at level 'location', which is "
            "reserved: the payout a location receives from a joint design is "
            "not identified (MAR-100). Re-run it: evaluate writes per-location "
            "rows only under an allocation rule ('location_by_value' or "
            "'location_by_loss')"
        )
    allocated = sorted(levels & set(_ALLOCATION_OF))
    if len(allocated) > 1:
        raise BundleError(
            f"baseline.map.arrow: run {run.run_id} ({item.scope_key} x "
            f"{run.objective}) has per-location rows under several allocation "
            f"rules ({allocated}); the map shows one rule per run"
        )
    if allocated:
        return allocated[0], _ALLOCATION_OF[allocated[0]]
    if run.scope == Individual.name:
        return KpiLevel.ENTITY.value, Allocation.NONE.value
    return None, None


def _events(
    eventset: EventSet,
    config: ExperimentConfig,
    scopes: Sequence[tuple[int, _Exported]],
) -> pd.DataFrame:
    """Return the event data under each entity of some scopes (``events``).

    ``scopes`` holds, per scope to export, its position in ``config.scopes``
    and its first run.
    """
    parts: list[pd.DataFrame] = []
    for i, first in scopes:
        events = entity_events(
            eventset, config.scopes[i].build(), first.run.problem_specs()
        )
        parts.append(events.assign(scope=first.run.scope, scope_key=first.scope_key))
    return _frame(parts, _EVENT_COLUMNS)


def _run_entry(run: RunResult, scope_key: str) -> dict[str, Any]:
    rows = run.runs
    problems = [
        {
            "problem_id": str(row["problem_id"]),
            "status": str(row["status"]),
            "solver": None if row["solver"] is None else str(row["solver"]),
            "objective_value": _optional(row["objective_value"]),
            "premium": _optional(row["premium"]),
            "error_type": None if row["error_type"] is None else str(row["error_type"]),
            "error_message": (
                None if row["error_message"] is None else str(row["error_message"])
            ),
        }
        for row in rows.to_dict("records")
    ]
    first = rows.iloc[0]
    return {
        "run_id": run.run_id,
        "scope": run.scope,
        "scope_key": scope_key,
        "objective": run.objective,
        "source": str(first["source"]),
        "pricing": str(first["pricing"]),
        "payout": str(first["payout"]),
        "basis": str(first["basis"]),
        "calibration_split": str(first["calibration_split"]),
        "fold": int(first["fold"]),
        "parameters": run.parameters,
        "complete": run.complete,
        "problems": problems,
    }


# --------------------------------------------------------------------------
# Setup (the publication rule: the setup of every number)
# --------------------------------------------------------------------------


def _setup(config: ExperimentConfig) -> dict[str, Any]:
    """Portfolio, basis, basis-risk model, pricing and split of a config."""
    data = to_dict(config)
    sample = data.get("sample", {"kind": "full"})
    return {
        "portfolio": data.get("portfolio", {}),
        "basis": data["basis"],
        "basis_risk": {
            "noise": data.get("noise"),
            "threshold": data.get("threshold"),
        },
        "pricing": data.get("pricing", {"kind": "pure"}),
        "constraints": data.get("constraints", []),
        "split": {
            **sample,
            "out_of_sample": sample.get("kind") != "full",
        },
        "payout": data["payout"],
        "evaluation": data["evaluation"],
        "bootstrap": data.get("bootstrap"),
    }


def _eventset_entry(eventset: EventSet, results: Sequence[RunResult]) -> dict[str, Any]:
    metadata = eventset.metadata
    checksums = sorted(
        {
            str(c)
            for r in results
            for c in r.runs["eventset_checksum"].dropna().unique().tolist()
        }
    )
    return {
        "input_checksums": checksums,
        "prepared_content_hash": eventset.content_hash(),
        "hazard": {"name": metadata.hazard.name, "release": metadata.hazard.release},
        "scenario": metadata.scenario,
        "n_years": metadata.n_years,
        "licence": metadata.licence,
        "index": {
            "definition": metadata.index.definition,
            "unit": metadata.index.unit,
        },
        "loss": {"unit": metadata.loss.unit, "currency": metadata.loss.currency},
        "n_rows": eventset.n_rows,
        "n_locations": eventset.n_locations,
    }


def _locations(eventset: EventSet) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    frame = eventset.locations
    for row in frame.to_dict("records"):
        name = row.get("name")
        out.append(
            {
                "location_id": str(row["location_id"]),
                "name": None if name is None or pd.isna(name) else str(name),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "value": float(row["value"]),
            }
        )
    return out


# --------------------------------------------------------------------------
# Export
# --------------------------------------------------------------------------


def _check_parameters(
    config: ExperimentConfig, parameters: Sequence[str] | None
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Return the sweeps to export and the configured ones that are not.

    Raises
    ------
    BundleError
        If a requested parameter is not exportable or not a configured sweep.
    """
    configured = [s.parameter for s in config.sweeps]
    exportable = [p for p in configured if p in SITE_SWEEP_PARAMETERS]
    if parameters is None:
        chosen = tuple(exportable)
    else:
        chosen = tuple(dict.fromkeys(parameters))
        bad = [p for p in chosen if p not in SITE_SWEEP_PARAMETERS]
        if bad:
            raise BundleError(
                f"sweeps {bad} are not exported to the site; the site shows "
                f"the sweeps of {list(SITE_SWEEP_PARAMETERS)}"
            )
        absent = [p for p in chosen if p not in configured]
        if absent:
            raise BundleError(
                f"config {config.name!r} has no sweep of {absent}; its sweeps "
                f"are {configured}"
            )
    not_exported = tuple(p for p in configured if p not in chosen)
    return chosen, not_exported


def _versions() -> dict[str, str]:
    return {
        "parametric-insurance-design": version("parametric-insurance-design"),
        "parametric-insurance-design-viz": version("parametric-insurance-design-viz"),
        "pyarrow": pa.__version__,
    }


def export_site(
    config: ExperimentConfig,
    run_ids: Sequence[str],
    *,
    store: ResultStore,
    out_dir: str | Path,
    eventset: EventSet,
    sweeps: Sequence[SweepRun] = (),
    parameters: Sequence[str] | None = None,
    include_events: bool = False,
    budget: SizeBudget | None = None,
    label: str | None = None,
    pooled_kpis: pd.DataFrame | None = None,
    eval_split: str | None = None,
) -> ExportReport:
    """Export a config's site bundle from its result store.

    Parameters
    ----------
    config : ExperimentConfig
        The experiment config.
    run_ids : sequence of str
        The ``run_id`` of each of ``config.single_runs()``, in that order
        (for k-fold: every fold of every scope x objective).
    store : ResultStore
        The result store holding the runs.
    out_dir : str or pathlib.Path
        The bundle directory: created if missing; a previous bundle there is
        replaced; any other content is refused.
    eventset : EventSet
        The runs' prepared EventSet: the locations of the map and, with
        ``include_events``, the event data. Checked against every run.
    sweeps : sequence of SweepRun, default ()
        Every point of the config's sweeps, as the ``figures`` command
        computes them. Only the points of the exported parameters are read.
    parameters : sequence of str, optional
        The sweeps to export. Default: every configured sweep of
        :data:`SITE_SWEEP_PARAMETERS`.
    include_events : bool, default False
        Also write ``baseline.events.arrow``, the event data under each
        entity (large: about 6 MB per grid on the thesis set).
    budget : SizeBudget, optional
        Size budget. Default: :class:`SizeBudget` (2 MB per file, 10 MB of
        data files).
    label : str, optional
        What the data are, for the site to show, e.g. "thesis-fixture
        data". Default: the config's description, or its name.
    pooled_kpis : pandas.DataFrame, optional
        k-fold configs only, and required for them: the table of the core's
        ``experiment.kfold.pooled_kpis(config, store, eventset,
        run_ids).table`` (columns ``POOLED_COLUMNS``), as the
        ``export-site`` command computes it. Written to
        ``baseline.pooled_kpis.arrow``.
    eval_split : {"full", "train", "test"}, optional
        The split filter (MAR-213): keep only the rows of this evaluation
        split in the ``kpis``, ``exceedance`` and ``map`` slices, e.g.
        ``"test"`` for a published bundle (out of sample only). Default: no
        filter, every split the runs stored. Recorded in the manifest
        (``split_filter``). Not for k-fold configs.

    Returns
    -------
    ExportReport
        The manifest and files written, and the runs skipped.

    Raises
    ------
    KFoldRunsError
        If the config has a k-fold sample that fixes ``sample.fold``, or no
        ``pooled_kpis`` are given for it.
    InconsistentRunsError
        If ``run_ids`` does not match the config's single runs, a sweep point
        names no single run, an exported sweep has no points, or a run's
        setup differs from the config's; for k-fold, if ``pooled_kpis`` does
        not match the fold runs, or is given for another sample.
    MissingRunError
        If a run, or a point of an exported sweep, is not in the store.
    EventSetMismatchError
        If ``eventset`` is not the runs' prepared EventSet.
    BundleError
        If a sweep parameter is not exportable or not configured, or
        ``out_dir`` holds files that are not part of a bundle; for k-fold,
        if sweeps or events are asked for; if ``eval_split`` is not a split,
        is given for a k-fold config, or an exported run has no KPI rows of
        it; if a run's per-location rows are at the reserved plain
        ``location`` level, under several allocation rules, or miss a
        location in an evaluation (module docstring, "Map").
    BundleValueError
        If a value breaks the infinity, NaN or integer rule.
    BundleBudgetError
        If a file or the bundle is over the budget. Nothing is written.

    Notes
    -----
    ``manifest.json`` holds ``format`` (:data:`BUNDLE_FORMAT`),
    ``format_version`` (:data:`BUNDLE_FORMAT_VERSION`), ``label``, the
    config's ``name``, ``description`` and ``hash``, the package
    ``versions``, the ``eventset`` (checksums, hazard, scenario, years,
    licence, units), the ``setup`` of every number (portfolio, basis,
    basis-risk model, pricing, constraints, split, payout, evaluation,
    bootstrap; checked against every run's own config), the ``runs``
    (the baseline ``run_id`` per single run, the ``run_id`` per point of
    each exported sweep, the skipped runs), ``sweeps_not_exported``, the
    ``events`` switch, the ``budget`` with the bundle's total, the
    ``files`` (:meth:`BundleFile.to_dict`), the ``split_filter`` (the
    split kept or null, the slices filtered, the rows removed per file) and
    the ``rules``; a non-k-fold bundle also its ``map`` section (the source
    of each run's per-location numbers: allocation rule, entity rows of the
    individual scope, or none), a k-fold bundle its ``kfold`` section
    (module docstring).
    """
    k = _check_kfold(config, parameters, include_events, pooled_kpis)
    _check_split(config, eval_split, k)
    split = _SplitFilter(eval_split)
    if k is not None:
        parameters, sweeps = [], ()
    budget = SizeBudget() if budget is None else budget
    ids, chosen, not_exported, points = _plan(config, run_ids, sweeps, parameters)
    keys = _scope_keys(config)
    per_scope = len(config.objectives) * (1 if k is None else k)
    scope_key = {r: keys[i // per_scope] for i, r in enumerate(ids)}
    for point in points:
        scope_key.setdefault(point.run_id, keys[point.single // per_scope])

    all_ids = tuple(scope_key)
    _require(store, ids, points)
    results = {r.run_id: r for r in ResultReader(store).runs(all_ids)}
    singles = dict(zip(ids, config.single_runs(), strict=True))
    _check_runs(config, results.values(), eventset, singles)
    skipped = {
        r.run_id: SkippedRun(
            r.run_id, f"design problems failed: {', '.join(r.failed_problems)}"
        )
        for r in results.values()
        if not r.complete
    }

    builder = _Builder(budget)
    builder.add_json(
        "runs.json",
        "runs",
        {"runs": [_run_entry(results[r], scope_key[r]) for r in all_ids]},
    )
    builder.add_json("locations.json", "locations", {"locations": _locations(eventset)})
    kfold_section: dict[str, Any] | None = None
    map_section: dict[str, Any] | None = None
    if k is not None:
        if pooled_kpis is None:  # pragma: no cover - _check_kfold invariant
            raise KFoldRunsError("a k-fold bundle needs pooled_kpis")
        kfold_section = _add_kfold(
            builder,
            config,
            ids,
            {r: results[r] for r in ids},
            scope_key,
            set(skipped),
            pooled_kpis,
            k,
        )
    else:
        baseline = [
            _Exported(results[r], scope_key[r]) for r in ids if r not in skipped
        ]
        split.check(baseline)
        _add_group(builder, baseline, split, group=_BASELINE)
        map_rows, map_sources = _map(baseline)
        builder.add_table(
            "baseline.map.arrow",
            "map",
            split.apply("baseline.map.arrow", map_rows),
            (*_RUN_COLUMNS, *_MAP_COLUMNS),
            group=_BASELINE,
        )
        map_section = {
            "rule": _MAP_RULE,
            "allocations": sorted(
                {
                    str(s["allocation"])
                    for s in map_sources
                    if s["allocation"] not in (None, Allocation.NONE.value)
                }
            ),
            "runs": map_sources,
        }
    event_scopes: list[str] = []
    if include_events:
        scopes: list[tuple[int, _Exported]] = []
        for i, key in enumerate(keys):
            scope_ids = ids[i * per_scope : (i + 1) * per_scope]
            if any(r in skipped for r in scope_ids):
                continue  # its failed run is listed under runs.skipped
            scopes.append((i, _Exported(results[scope_ids[0]], key)))
            event_scopes.append(key)
        builder.add_table(
            "baseline.events.arrow",
            "events",
            _events(eventset, config, scopes),
            _EVENT_COLUMNS,
            group=_BASELINE,
        )
    for parameter in chosen:
        runs = [
            _Exported(results[p.run_id], scope_key[p.run_id], float(p.value))
            for p in points
            if p.parameter == parameter and p.run_id not in skipped
        ]
        split.check(runs)
        _add_group(builder, runs, split, group=_SWEEP, parameter=parameter)

    manifest: dict[str, Any] = {
        "format": BUNDLE_FORMAT,
        "format_version": BUNDLE_FORMAT_VERSION,
        "label": label if label is not None else (config.description or config.name),
        "config": {
            "name": config.name,
            "description": config.description,
            "hash": config_hash(config),
        },
        "versions": _versions(),
        "eventset": _eventset_entry(eventset, list(results.values())),
        "setup": _setup(config),
        "runs": {
            "baseline": list(ids),
            "sweeps": {
                parameter: [
                    {"value": p.value, "run_id": p.run_id, "single": p.single}
                    for p in points
                    if p.parameter == parameter
                ]
                for parameter in chosen
            },
            "skipped": [
                {"run_id": s.run_id, "reason": s.reason} for s in skipped.values()
            ],
        },
        "sweeps_not_exported": list(not_exported),
        "events": {
            "included": include_events,
            "scopes": event_scopes,
            "note": _EVENTS_NOTE,
        },
        "budget": {
            "max_file_bytes": budget.max_file_bytes,
            "max_bundle_bytes": budget.max_bundle_bytes,
            "bundle_bytes": sum(f.bytes for f in builder.files),
        },
        "files": [f.to_dict() for f in builder.files],
        "split_filter": split.section(),
        "rules": dict(_RULES),
    }
    if map_section is not None:
        manifest["map"] = map_section
    if kfold_section is not None:
        manifest["kfold"] = kfold_section
    manifest_bytes = _json_bytes(manifest, MANIFEST, indent=2)
    builder.check_budget(len(manifest_bytes))
    directory = Path(out_dir)
    removed = _write(directory, builder.data, manifest_bytes)
    return ExportReport(
        out_dir=directory,
        manifest=manifest,
        files=tuple(builder.files),
        skipped=tuple(skipped.values()),
        removed=removed,
    )


def _plan(
    config: ExperimentConfig,
    run_ids: Sequence[str],
    sweeps: Sequence[SweepRun],
    parameters: Sequence[str] | None,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[SweepRun, ...]]:
    """Check the runs asked for: ``(ids, sweeps exported, not, their points)``.

    Raises
    ------
    InconsistentRunsError
        If ``run_ids`` does not match the single runs, a point names no
        single run, or an exported sweep has no points.
    BundleError
        From :func:`_check_parameters`.
    """
    n_singles = len(config.single_runs())
    ids = tuple(run_ids)
    if len(ids) != n_singles:
        raise InconsistentRunsError(
            f"config {config.name!r} has {n_singles} single runs, got "
            f"{len(ids)} run ids"
        )
    chosen, not_exported = _check_parameters(config, parameters)
    points = tuple(p for p in sweeps if p.parameter in chosen)
    bad = sorted({p.single for p in points if not 0 <= p.single < n_singles})
    if bad:
        raise InconsistentRunsError(
            f"config {config.name!r} has {n_singles} single runs; sweep points "
            f"name single runs {bad}"
        )
    given = {p.parameter for p in points}
    empty = [p for p in chosen if p not in given]
    if empty:
        raise InconsistentRunsError(
            f"no sweep points were given for the sweeps {empty}"
        )
    return ids, chosen, not_exported, points


def _require(
    store: ResultStore, ids: Sequence[str], points: Sequence[SweepRun]
) -> None:
    """Raise :class:`MissingRunError` if a run or a sweep point is not stored."""
    missing = [r for r in dict.fromkeys(ids) if not store.has_run(r)]
    if missing:
        raise MissingRunError(
            f"{len(missing)} of {len(ids)} single runs are not in the result "
            f"store {store.root}: {missing}; export-site reads the store and "
            "never solves, so run the config first (parametric-insurance-design "
            "run CONFIG)"
        )
    gone = [p for p in points if not store.has_run(p.run_id)]
    if gone:
        per_sweep = Counter(p.parameter for p in gone)
        totals = Counter(p.parameter for p in points)
        counts = ", ".join(f"{k} {n}/{totals[k]}" for k, n in per_sweep.items())
        raise MissingRunError(
            f"{len(gone)} of {len(points)} sweep points are not in the result "
            f"store {store.root} ({counts}), e.g. {gone[0].parameter}="
            f"{gone[0].value!r} {gone[0].run_id}; export-site never solves, so "
            "run the sweeps first (parametric-insurance-design sweep CONFIG), or "
            "export fewer (--parameter P, --no-sweeps)"
        )


_SETUP_FIELDS: Final[tuple[str, ...]] = (
    "portfolio",
    "basis",
    "noise",
    "threshold",
    "pricing",
    "sample",
)
"""Config fields that every run of a bundle shares (the publication rule)."""


def _setup_fields(config: Mapping[str, Any]) -> object:
    """Return the setup fields of a config dict, JSON-normalised."""
    fields = {key: config.get(key) for key in _SETUP_FIELDS}
    return json.loads(json.dumps(fields, sort_keys=True, default=str))


def _check_runs(
    config: ExperimentConfig,
    results: Iterable[RunResult],
    eventset: EventSet,
    singles: Mapping[str, ExperimentConfig],
) -> None:
    """Check every run against the EventSet and the config's setup.

    ``singles`` maps each single run's ``run_id`` to its config, whose setup
    the run must have (for k-fold, with its fold); a sweep point must have
    the setup of ``config``.

    Raises
    ------
    EventSetMismatchError
        If a run was not solved on ``eventset``.
    InconsistentRunsError
        If a run's own config has another portfolio, basis, basis-risk
        model, pricing or split.
    """
    eventset_hash = eventset.content_hash()
    base = _setup_fields(to_dict(config))
    expected = {r: _setup_fields(to_dict(c)) for r, c in singles.items()}
    for result in results:
        check_eventset(result, eventset_hash)
        recorded = result.manifest.get("config")
        if not isinstance(recorded, Mapping):
            continue  # a run manifest without its config: nothing to compare
        if _setup_fields(recorded) != expected.get(result.run_id, base):
            raise InconsistentRunsError(
                f"run {result.run_id} was computed with another setup than "
                f"config {config.name!r} (its {', '.join(_SETUP_FIELDS)} "
                "differ): every number of a bundle shares one setup"
            )


def _check_kfold(
    config: ExperimentConfig,
    parameters: Sequence[str] | None,
    include_events: bool,
    pooled_kpis: pd.DataFrame | None,
) -> int | None:
    """Return ``k`` of a k-fold config it can export, None for other samples.

    Raises
    ------
    KFoldRunsError
        If the k-fold config fixes ``sample.fold``, or ``pooled_kpis`` is
        None.
    InconsistentRunsError
        If ``pooled_kpis`` is given for a config that is not k-fold.
    BundleError
        If sweeps (``parameters``) or events are asked of a k-fold config.
    """
    sample = config.sample
    if sample.kind != "kfold":  # KFOLD_SAMPLE, as a literal for narrowing
        if pooled_kpis is not None:
            raise InconsistentRunsError(
                f"config {config.name!r} has a {sample.kind!r} sample; pooled "
                "k-fold KPIs belong to a k-fold config only"
            )
        return None
    k, fold = sample.k, sample.fold
    if fold is not None:
        raise KFoldRunsError(
            f"config {config.name!r} fixes k-fold fold {fold}: a site bundle "
            "pools every fold (sample.fold must be unset)"
        )
    if parameters:
        raise BundleError(
            f"config {config.name!r} is k-fold: its sweeps are not exported "
            f"(asked for {list(parameters)}); " + _KFOLD_NOT_EXPORTED["sweeps"]
        )
    if include_events:
        raise BundleError(
            f"config {config.name!r} is k-fold: its events are not exported, "
            "because the entities differ per fold"
        )
    if pooled_kpis is None:
        raise KFoldRunsError(
            f"config {config.name!r} has a k-fold sample (k={k}): its runs "
            "are per fold, and its site bundle shows the pooled out-of-sample "
            "KPIs (MAR-151), of which none were given. Compute them with "
            "experiment.kfold.pooled_kpis and pass pooled_kpis=...table (the "
            "export-site command does this)"
        )
    return k


def _add_kfold(
    builder: _Builder,
    config: ExperimentConfig,
    ids: Sequence[str],
    results: Mapping[str, RunResult],
    scope_key: Mapping[str, str],
    skipped: set[str],
    pooled: pd.DataFrame,
    k: int,
) -> dict[str, Any]:
    """Add a k-fold bundle's payouts and pooled KPIs; return its ``kfold``.

    Raises
    ------
    InconsistentRunsError
        If the pooled table does not match the fold runs.
    """
    folds = [_Exported(results[r], scope_key[r], fold=i % k) for i, r in enumerate(ids)]
    builder.add_table(
        "baseline.payouts.arrow",
        "payouts",
        _payouts([f for f in folds if f.run.run_id not in skipped]),
        (*_RUN_COLUMNS, _FOLD, *_PAYOUT_COLUMNS),
        group=_BASELINE,
    )
    keys = _scope_keys(config)
    designs: list[dict[str, Any]] = []
    for d in range(len(ids) // k):
        run_ids = list(ids[d * k : (d + 1) * k])
        designs.append(
            {
                "scope_key": keys[d // len(config.objectives)],
                "objective": results[run_ids[0]].objective,
                "run_ids": run_ids,
                "failed": [r for r in run_ids if r in skipped],
            }
        )
    frame = _pooled_frame(config, pooled, designs, keys, k)
    builder.add_table(
        "baseline.pooled_kpis.arrow",
        "pooled_kpis",
        frame,
        _POOLED_KPI_COLUMNS,
        group=_BASELINE,
    )
    pooled_designs = [d for d in designs if not d["failed"]]
    return {
        "k": k,
        "eval_split": POOLED_SPLIT,
        "rule": _POOLED_RULE,
        "pooled": [
            {key: d[key] for key in ("scope_key", "objective", "run_ids")}
            for d in pooled_designs
        ],
        "not_pooled": [
            {
                "scope_key": d["scope_key"],
                "objective": d["objective"],
                "run_ids": d["run_ids"],
                "reason": "folds failed: " + ", ".join(d["failed"]),
            }
            for d in designs
            if d["failed"]
        ],
        "not_exported": dict(_KFOLD_NOT_EXPORTED),
    }


def _pooled_frame(
    config: ExperimentConfig,
    pooled: pd.DataFrame,
    designs: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    k: int,
) -> pd.DataFrame:
    """Check the pooled table against the fold runs; add ``scope_key``.

    Every design without a failed fold must have exactly one row per KPI it
    has, and a design with a failed fold none.

    Raises
    ------
    InconsistentRunsError
        If a column is missing, a row is not a pooled portfolio row of ``k``
        folds, names fold runs that are not one design's, or a design is
        missing, pooled over a failed fold, or has a KPI twice.
    """
    missing = [c for c in POOLED_COLUMNS if c not in pooled.columns]
    if missing:
        raise InconsistentRunsError(
            f"the pooled KPI table lacks the columns {missing}; pass "
            "experiment.kfold.pooled_kpis(...).table"
        )
    splits = sorted({str(s) for s in pooled["eval_split"]})
    levels = sorted({str(s) for s in pooled["level"]})
    if pooled.empty or splits != [POOLED_SPLIT] or levels != [KpiLevel.PORTFOLIO.value]:
        raise InconsistentRunsError(
            f"pooled KPI rows must be {POOLED_SPLIT!r} portfolio rows, at least "
            f"one; got {len(pooled)} rows, eval_split {splits}, level {levels}"
        )
    ks = sorted({int(v) for v in pooled["k"]})
    if ks != [k]:
        raise InconsistentRunsError(
            f"the pooled KPIs are over k = {ks} folds; config {config.name!r} "
            f"has k = {k}"
        )
    by_runs = {";".join(d["run_ids"]): (i, d) for i, d in enumerate(designs)}
    named = [str(r) for r in pooled["run_ids"]]
    unknown = sorted(set(named) - set(by_runs))
    if unknown:
        raise InconsistentRunsError(
            f"pooled KPI rows name fold runs {unknown[:3]} that are not the fold "
            "runs of one scope x objective of the config"
        )
    present = set(named)
    for runs, (i, design) in by_runs.items():
        label = f"{design['scope_key']} x {design['objective']}"
        if design["failed"] and runs in present:
            raise InconsistentRunsError(
                f"the pooled KPIs hold {label}, whose folds failed "
                f"({', '.join(design['failed'])}); pooled_kpis pools only "
                "complete designs"
            )
        if not design["failed"] and runs not in present:
            raise InconsistentRunsError(
                f"the pooled KPIs lack {label}, whose folds are all complete"
            )
        rows = _rows(pooled, pooled["run_ids"] == runs)
        position = i // len(config.objectives)
        if len(rows) and (
            {int(p) for p in rows["scope_position"]} != {position}
            or {str(o) for o in rows["objective"]} != {design["objective"]}
        ):
            raise InconsistentRunsError(
                f"the pooled rows of {label} name another scope position or "
                "objective than their fold runs"
            )
    duplicated = pooled.duplicated(subset=["run_ids", "kpi"])
    if duplicated.any():
        first = pooled.loc[duplicated].iloc[0]
        raise InconsistentRunsError(
            f"the pooled KPIs hold KPI {first['kpi']!r} of fold runs "
            f"{first['run_ids']!r} more than once"
        )
    frame = pooled.reset_index(drop=True)
    return frame.assign(scope_key=[keys[int(p)] for p in frame["scope_position"]])


def _add_group(
    builder: _Builder,
    runs: Sequence[_Exported],
    split: _SplitFilter,
    *,
    group: str,
    parameter: str | None = None,
) -> None:
    """Add the payouts, KPIs and exceedance curves of one group of runs.

    The KPIs and exceedance curves pass through the split filter; the payouts
    do not (a design has no split).
    """
    stem = _BASELINE if parameter is None else f"{_SWEEP}.{parameter}"
    labels = _RUN_COLUMNS if parameter is None else (*_RUN_COLUMNS, _SWEEP_VALUE)
    slices: tuple[tuple[str, pd.DataFrame, tuple[_Col, ...]], ...] = (
        ("payouts", _payouts(runs), _PAYOUT_COLUMNS),
        ("kpis", _table(runs, "kpis", _KPI_COLUMNS), _KPI_COLUMNS),
        (
            "exceedance",
            _table(runs, "exceedance", _EXCEEDANCE_COLUMNS),
            _EXCEEDANCE_COLUMNS,
        ),
    )
    for name, frame, columns in slices:
        path = f"{stem}.{name}.arrow"
        if name in _SPLIT_SLICES:
            frame = split.apply(path, frame)
        builder.add_table(
            path,
            name,
            frame,
            (*labels, *columns),
            group=group,
            parameter=parameter,
        )


# --------------------------------------------------------------------------
# Writing and reading
# --------------------------------------------------------------------------


def _previous(directory: Path) -> tuple[str, ...]:
    """Files of a previous bundle in ``directory``; refuse anything else.

    Raises
    ------
    BundleError
        If the directory holds files that no bundle manifest there lists.
    """
    if not directory.exists():
        return ()
    if not directory.is_dir():
        raise BundleError(f"{directory} is not a directory")
    present = sorted(p.name for p in directory.iterdir())
    if not present:
        return ()
    listed: set[str] = set()
    manifest_path = directory / MANIFEST
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            manifest = None
        if isinstance(manifest, dict) and manifest.get("format") == BUNDLE_FORMAT:
            listed = {MANIFEST} | {
                str(f["path"])
                for f in manifest.get("files", [])
                if isinstance(f, dict) and "path" in f
            }
    unknown = [name for name in present if name not in listed]
    if unknown:
        raise BundleError(
            f"{directory} holds files that are not part of a site bundle: "
            f"{unknown[:10]}; export into an empty directory or a previous bundle"
        )
    return tuple(name for name in present if name != MANIFEST)


def _replace_into(path: Path, data: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _write(
    directory: Path, data: Mapping[str, bytes], manifest: bytes
) -> tuple[str, ...]:
    """Write the files, then the manifest; remove a previous bundle's leftovers."""
    previous = _previous(directory)
    directory.mkdir(parents=True, exist_ok=True)
    stale = tuple(name for name in previous if name not in data)
    # The manifest goes last and is replaced first: a bundle interrupted
    # mid-write has no manifest listing files it does not hold.
    (directory / MANIFEST).unlink(missing_ok=True)
    for name in stale:
        (directory / name).unlink()
    for name, content in data.items():
        _replace_into(directory / name, content)
    _replace_into(directory / MANIFEST, manifest)
    return stale


def read_bundle(directory: str | Path) -> dict[str, Any]:
    """Read a bundle's manifest and verify every file against it.

    Parameters
    ----------
    directory : str or pathlib.Path
        The bundle directory.

    Returns
    -------
    dict
        The manifest.

    Raises
    ------
    BundleError
        If there is no manifest, or it is not a bundle manifest of
        :data:`BUNDLE_FORMAT_VERSION`.
    BundleChecksumError
        If a listed file is missing, or its size or SHA-256 differs.
    """
    root = Path(directory)
    path = root / MANIFEST
    if not path.is_file():
        raise BundleError(f"{root} has no {MANIFEST}")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("format") != BUNDLE_FORMAT:
        raise BundleError(f"{path} is not a {BUNDLE_FORMAT} manifest")
    if manifest.get("format_version") != BUNDLE_FORMAT_VERSION:
        raise BundleError(
            f"{path} has format_version {manifest.get('format_version')!r}; "
            f"this package reads {BUNDLE_FORMAT_VERSION}"
        )
    for entry in manifest["files"]:
        file = root / entry["path"]
        if not file.is_file():
            raise BundleChecksumError(f"bundle file {entry['path']} is missing")
        data = file.read_bytes()
        if len(data) != entry["bytes"] or _sha256(data) != entry["sha256"]:
            raise BundleChecksumError(
                f"bundle file {entry['path']} does not match the manifest "
                f"({len(data)} bytes, {_sha256(data)}; manifest: "
                f"{entry['bytes']} bytes, {entry['sha256']})"
            )
    return manifest


def read_slice(directory: str | Path, path: str) -> object:
    """Read one bundle file: an Arrow table, or the parsed JSON.

    Parameters
    ----------
    directory : str or pathlib.Path
        The bundle directory.
    path : str
        The file's name, as the manifest lists it.

    Returns
    -------
    pyarrow.Table or JSON value
        The table of an ``.arrow`` file, the parsed content of a JSON file.

    Raises
    ------
    BundleError
        If the file is not listed in the manifest.
    BundleChecksumError
        If it does not match the manifest.
    """
    root = Path(directory)
    manifest = json.loads((root / MANIFEST).read_text(encoding="utf-8"))
    entries = {e["path"]: e for e in manifest.get("files", [])}
    if path not in entries:
        raise BundleError(f"{path!r} is not a file of the bundle in {root}")
    data = (root / path).read_bytes()
    entry = entries[path]
    if len(data) != entry["bytes"] or _sha256(data) != entry["sha256"]:
        raise BundleChecksumError(f"bundle file {path} does not match the manifest")
    if entry["format"] == _ARROW:
        return pa.ipc.open_file(pa.BufferReader(data)).read_all()
    return json.loads(data.decode("utf-8"))
