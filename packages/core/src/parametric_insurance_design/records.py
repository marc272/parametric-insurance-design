"""Record schemas of the result store (ADR 0002, SPEC §3.1 C5).

The result store is a set of tidy tables. ``evaluate.py`` produces KPI and
exceedance rows, the runner (``experiment/runner.py``) produces run, entity
and payout rows, ``experiment/store.py`` persists them as Parquet, and the
viz package reads them. All of them agree on the schemas defined here.

Tables (key columns first)
    ``runs``
        One row per (run, design problem), including failed solves.
    ``entities``
        Which locations each payout entity covers (e.g. cluster members).
    ``payouts``
        One row per payout parameter: the fitted step levels and their bin
        edges. No arrays stored as strings.
    ``kpis``
        Long format: one row per KPI value, with optional confidence bounds.
    ``exceedance``
        Exceedance curves: value per return period.

Conventions
    * ``run_id`` is the run's content hash (cache key); ``problem_id`` is the
      design problem (asset id, or ``"portfolio"``).
    * Rows that aggregate every design problem of a run (the portfolio KPIs
      of the individual scope) use ``problem_id = "*"``
      (:data:`ALL_PROBLEMS`).
    * Undefined values (e.g. a correlation with zero variance) are null:
      NaN in a pandas float column, null in Parquet. Infinite values are
      rejected.

Changing a schema needs an ADR 0002 amendment.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Final, Literal, cast

import numpy as np
import pandas as pd
import pyarrow as pa

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.errors import RecordSchemaError
from parametric_insurance_design.interfaces import SolveStatus

__all__ = [
    "ALL_PROBLEMS",
    "ENTITIES",
    "EXCEEDANCE",
    "KPIS",
    "PAYOUTS",
    "RUNS",
    "TABLES",
    "Column",
    "CurveKind",
    "CurveQuantity",
    "KpiLevel",
    "KpiName",
    "Split",
    "TableSchema",
]

ALL_PROBLEMS: Final[str] = "*"
"""``problem_id`` of rows that aggregate every design problem of a run."""

ColumnKind = Literal["str", "int", "float", "bool", "timestamp"]

_ARROW: Final[dict[str, pa.DataType]] = {
    "str": pa.string(),
    "int": pa.int64(),
    "float": pa.float64(),
    "bool": pa.bool_(),
    "timestamp": pa.timestamp("us", tz="UTC"),
}


class Split(StrEnum):
    """Which rows a run was calibrated on, or a KPI evaluated on."""

    FULL = "full"
    TRAIN = "train"
    TEST = "test"


class KpiLevel(StrEnum):
    """What a KPI row describes.

    Attributes
    ----------
    LOCATION : str
        One location (asset): its loss against the payout it receives.
        Reserved: ``evaluate.kpis`` doesn't write it, because the payout a
        location receives from a joint design isn't identified (MAR-100).
        Per-location rows carry the allocation rule in their level, below.
    LOCATION_BY_VALUE : str
        One location: its loss against its share of its design problem's
        payout, pro rata to insured value (``evaluate`` allocation
        ``"value"``, MAR-100).
    LOCATION_BY_LOSS : str
        One location: its loss against its share of its design problem's
        payout, pro rata to its loss in each row (``evaluate`` allocation
        ``"loss"``, MAR-100).
    ENTITY : str
        One payout entity (an asset or a cluster). For a joint scope, one
        member of the set of optimal designs (MAR-100).
    PROBLEM : str
        The objective level of one design problem.
    PORTFOLIO : str
        All locations of the run together (``problem_id = "*"`` when the
        scope has several design problems).
    """

    LOCATION = "location"
    LOCATION_BY_VALUE = "location_by_value"
    LOCATION_BY_LOSS = "location_by_loss"
    ENTITY = "entity"
    PROBLEM = "problem"
    PORTFOLIO = "portfolio"


class KpiName(StrEnum):
    """KPI names. The thesis column each one replaces is given in brackets."""

    EXPECTED_LOSS = "expected_loss"
    EXPECTED_PAYOUT = "expected_payout"
    EXPECTED_UNCOVERED = "expected_uncovered"  # [E_Uncovered]
    VAR_UNCOVERED = "var_uncovered"  # [VaR_Uncovered]
    CVAR_UNCOVERED = "cvar_uncovered"  # [CVaR_Uncovered]
    RMSE_RESIDUAL = "rmse_residual"  # [E_Residual]
    PAYOUT_TO_LOSS_RATIO = "payout_to_loss_ratio"  # [E_Payout_to_E_Loss_Ratio]
    CORRELATION = "correlation"  # [Correlation]
    PREMIUM = "premium"


class CurveQuantity(StrEnum):
    """Quantity an exceedance curve describes."""

    LOSS = "loss"
    PAYOUT = "payout"
    UNCOVERED = "uncovered"


class CurveKind(StrEnum):
    """Kind of exceedance curve.

    Attributes
    ----------
    EVENT : str
        Per event row (event and event-conditional bases).
    OEP : str
        Occurrence exceedance: the largest event of each year.
    AEP : str
        Aggregate exceedance: the sum over each year.
    """

    EVENT = "event"
    OEP = "oep"
    AEP = "aep"


def _values(enum: type[StrEnum]) -> frozenset[str]:
    return frozenset(member.value for member in enum)


# -- value-type checks (MAR-130) ----------------------------------------------
#
# ``_is_kind`` is the reference definition of which Python values a column
# kind holds. ``_holds_only`` gives the same answer for a whole column, but
# decides it from the dtype, or from one C-level ``infer_dtype`` pass over an
# object column, when that already proves every value is of the right type.
# It only ever *accepts* that way: whenever the shortcut can't prove it, it
# falls back to ``_is_kind`` on every value, so every rejection is the
# reference's. The shortcuts are sound because each dtype below only holds
# values that ``_is_kind`` accepts, and ``infer_dtype`` returns each listed
# label only if every value passes the ``isinstance`` check of that label.

_MASKED_NUMERIC: Final[tuple[type, ...]] = (
    pd.Int8Dtype,
    pd.Int16Dtype,
    pd.Int32Dtype,
    pd.Int64Dtype,
    pd.UInt8Dtype,
    pd.UInt16Dtype,
    pd.UInt32Dtype,
    pd.UInt64Dtype,
    pd.Float32Dtype,
    pd.Float64Dtype,
)
"""Nullable numeric dtypes: their values are Python ints or floats."""

_INFERRED: Final[dict[str, frozenset[str]]] = {
    # every value isinstance str
    "str": frozenset({"string"}),
    # every value isinstance bool | np.bool_
    "bool": frozenset({"boolean"}),
    # every value isinstance int | np.integer (bools excluded), float |
    # np.floating, or one of the two
    "int": frozenset({"integer", "floating", "mixed-integer-float"}),
    "float": frozenset({"integer", "floating", "mixed-integer-float"}),
}
"""``infer_dtype`` labels of object columns whose values all pass ``_is_kind``."""


def _is_kind(value: object, kind: ColumnKind) -> bool:
    """Whether one non-null value may be stored in a column of ``kind``.

    The reference definition; timestamps are checked by dtype only.
    """
    if kind == "str":
        return isinstance(value, str)
    if kind == "bool":
        return isinstance(value, bool | np.bool_)
    if isinstance(value, bool | np.bool_):
        return False
    return isinstance(value, int | float | np.integer | np.floating)


def _dtype_holds_only(dtype: object, kind: ColumnKind) -> bool:
    """Whether every non-null value of a column of ``dtype`` passes ``_is_kind``."""
    if kind == "str":
        return isinstance(dtype, pd.StringDtype) or (
            isinstance(dtype, pd.ArrowDtype)
            and (
                pa.types.is_string(dtype.pyarrow_dtype)
                or pa.types.is_large_string(dtype.pyarrow_dtype)
            )
        )
    if kind == "bool":
        return (isinstance(dtype, np.dtype) and dtype.kind == "b") or isinstance(
            dtype, pd.BooleanDtype
        )
    return (isinstance(dtype, np.dtype) and dtype.kind in "iuf") or isinstance(
        dtype, _MASKED_NUMERIC
    )


def _holds_only(present: pd.Series, kind: ColumnKind) -> bool:
    """Whether every value of ``present`` (no nulls) fits a column of ``kind``.

    Equal to ``all(_is_kind(v, kind) for v in present)``, and for timestamps
    to "the dtype is timezone-aware, or there are no values".
    """
    if present.empty:
        return True
    dtype = present.dtype
    if kind == "timestamp":
        return isinstance(dtype, pd.DatetimeTZDtype)
    if _dtype_holds_only(dtype, kind):
        return True
    if isinstance(dtype, np.dtype) and dtype.kind == "O":
        label = pd.api.types.infer_dtype(present.to_numpy(), skipna=False)
        if label in _INFERRED[kind]:
            return True
    # Not proven by the shortcuts: check value by value.
    return all(_is_kind(v, kind) for v in present)


@dataclass(frozen=True)
class Column:
    """One column of a record table.

    Parameters
    ----------
    name : str
        Column name.
    kind : {"str", "int", "float", "bool", "timestamp"}
        Logical type. Timestamps are timezone-aware UTC.
    description : str
        What the column holds.
    nullable : bool, default False
        Whether nulls are allowed.
    allowed : frozenset of str or None, optional
        For ``str`` columns, the allowed values.
    """

    name: str
    kind: ColumnKind
    description: str
    nullable: bool = False
    allowed: frozenset[str] | None = None


@dataclass(frozen=True)
class TableSchema:
    """Schema of one result-store table.

    Parameters
    ----------
    name : str
        Table name, also the Parquet file stem.
    columns : tuple of Column
        Columns in canonical order.
    key : tuple of str
        Columns that identify a row. Must be unique together.
    """

    name: str
    columns: tuple[Column, ...]
    key: tuple[str, ...]
    _by_name: dict[str, Column] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        """Check that column names are unique and key columns exist."""
        by_name = {c.name: c for c in self.columns}
        if len(by_name) != len(self.columns):
            raise ValueError(f"table {self.name!r} repeats a column name")
        missing = [k for k in self.key if k not in by_name]
        if missing:
            raise ValueError(f"table {self.name!r} key columns missing: {missing}")
        object.__setattr__(self, "_by_name", by_name)

    @property
    def column_names(self) -> tuple[str, ...]:
        """Column names in canonical order."""
        return tuple(c.name for c in self.columns)

    def column(self, name: str) -> Column:
        """Return a column by name.

        Parameters
        ----------
        name : str
            Column name.

        Returns
        -------
        Column
            The column.

        Raises
        ------
        KeyError
            If the table has no such column.
        """
        return self._by_name[name]

    def arrow_schema(self) -> pa.Schema:
        """Return the Arrow schema used for Parquet files.

        Returns
        -------
        pyarrow.Schema
            One field per column, in canonical order.
        """
        return pa.schema(
            [
                pa.field(c.name, _ARROW[c.kind], nullable=c.nullable)
                for c in self.columns
            ]
        )

    def empty(self) -> pd.DataFrame:
        """Return an empty table with canonical dtypes.

        Returns
        -------
        pandas.DataFrame
            No rows, every column.
        """
        return self.validate(pd.DataFrame({c.name: [] for c in self.columns}))

    def from_rows(self, rows: Iterable[Mapping[str, Any]]) -> pd.DataFrame:
        """Build a validated table from row mappings.

        Parameters
        ----------
        rows : iterable of mapping
            Each row maps every column name to a value (None for null).

        Returns
        -------
        pandas.DataFrame
            Validated table, see :meth:`validate`.

        Raises
        ------
        RecordSchemaError
            If a row has missing or unknown keys, or the table is invalid.
        """
        records = [dict(r) for r in rows]
        expected = set(self.column_names)
        for i, rec in enumerate(records):
            if set(rec) != expected:
                missing = sorted(expected - set(rec))
                unknown = sorted(set(rec) - expected)
                raise RecordSchemaError(
                    f"row {i}: missing keys {missing}, unknown keys {unknown}",
                    table=self.name,
                )
        if not records:
            return self.empty()
        return self.validate(pd.DataFrame.from_records(records))

    def validate(self, frame: pd.DataFrame) -> pd.DataFrame:
        """Validate a table and return it in canonical form.

        Parameters
        ----------
        frame : pandas.DataFrame
            Exactly the schema's columns, in any order.

        Returns
        -------
        pandas.DataFrame
            Columns in canonical order, a fresh ``RangeIndex`` and canonical
            dtypes: ``object`` for strings, ``int64``/``Int64``, ``float64``,
            ``bool``/``boolean`` and ``datetime64[us, UTC]``.

        Raises
        ------
        RecordSchemaError
            If columns are missing or unknown, a value has the wrong type, is
            null in a non-nullable column, is infinite or NaN, is not an
            allowed value, or the key repeats.
        """
        if not isinstance(frame, pd.DataFrame):
            raise RecordSchemaError("must be a pandas DataFrame", table=self.name)
        if not frame.columns.is_unique:
            raise RecordSchemaError("column names repeat", table=self.name)
        names = set(frame.columns)
        missing = [c for c in self.column_names if c not in names]
        unknown = sorted(str(c) for c in names - set(self.column_names))
        if missing or unknown:
            raise RecordSchemaError(
                f"missing columns {missing}, unknown columns {unknown}",
                table=self.name,
            )
        out = pd.DataFrame(
            {
                c.name: self._normalise(cast(pd.Series, frame[c.name]), c)
                for c in self.columns
            }
        )
        dup = out.duplicated(subset=list(self.key))
        if dup.any():
            raise RecordSchemaError(
                f"{int(dup.sum())} rows repeat the key {self.key}", table=self.name
            )
        return out

    def _normalise(self, series: pd.Series, col: Column) -> pd.Series:
        values = series.reset_index(drop=True)
        null_mask = values.isna()
        null = null_mask.to_numpy()
        if null.any() and not col.nullable:
            raise RecordSchemaError(
                f"column {col.name!r} has {int(null.sum())} nulls", table=self.name
            )
        fail = RecordSchemaError(
            f"column {col.name!r} must hold {col.kind} values", table=self.name
        )
        present = values.loc[~null_mask]
        if not _holds_only(present, col.kind):
            raise fail
        if col.kind == "str":
            if col.allowed is not None:
                # The distinct values, not every row: the same set of values.
                bad = sorted({v for v in present.unique() if v not in col.allowed})
                if bad:
                    raise RecordSchemaError(
                        f"column {col.name!r} has values {bad} not in "
                        f"{sorted(col.allowed)}",
                        table=self.name,
                    )
            return values.astype(object).where(~null, None)
        if col.kind == "timestamp":
            return pd.Series(
                pd.to_datetime(values, utc=True), dtype="datetime64[us, UTC]"
            )
        if col.kind == "bool":
            return values.astype("boolean" if col.nullable else bool)
        # int and float
        numeric = present.to_numpy(dtype=np.float64)
        if not np.all(np.isfinite(numeric)):
            raise RecordSchemaError(
                f"column {col.name!r} has infinite values", table=self.name
            )
        if col.kind == "int":
            if not np.all(numeric == np.round(numeric)):
                raise fail
            return values.astype("Int64" if col.nullable else np.int64)
        return values.astype(np.float64)


def _str(
    name: str,
    description: str,
    *,
    nullable: bool = False,
    allowed: frozenset[str] | None = None,
) -> Column:
    return Column(name, "str", description, nullable=nullable, allowed=allowed)


def _float(name: str, description: str, *, nullable: bool = False) -> Column:
    return Column(name, "float", description, nullable=nullable)


def _int(name: str, description: str, *, nullable: bool = False) -> Column:
    return Column(name, "int", description, nullable=nullable)


_RUN_ID = _str("run_id", "Content hash of the run configuration (cache key)")
_PROBLEM_ID = _str("problem_id", "Design problem: asset id, 'portfolio' or '*'")
_ENTITY_ID = _str("entity_id", "Payout entity id, e.g. 'A1' or 'C1'")
_SPLIT_VALUES = _values(Split)
_BASIS = _str("basis", "Evaluation basis", allowed=_values(Basis))

RUNS: Final[TableSchema] = TableSchema(
    name="runs",
    key=("run_id", "problem_id"),
    columns=(
        _RUN_ID,
        _PROBLEM_ID,
        _str("config_hash", "Hash of the canonical run configuration"),
        _str("source", "Origin tag, e.g. 'single_run' or 'alpha_sweep'"),
        _str("scope", "Scope name, e.g. 'individual'"),
        _str("objective", "Objective name, e.g. 'weighted_cvar'"),
        _str("pricing", "Pricing name, e.g. 'pure'"),
        _str("payout", "Payout structure name, e.g. 'step'"),
        _BASIS,
        _str("calibration_split", "Rows calibrated on", allowed=_SPLIT_VALUES),
        _int("fold", "Fold number for k-fold splits; 0 otherwise"),
        _str("parameters", "Canonical JSON object of scalar run parameters"),
        _str("status", "Solve status", allowed=_values(SolveStatus)),
        _str("solver", "Solver of the accepted result", nullable=True),
        _float("objective_value", "Objective value, loss units", nullable=True),
        _float("premium", "Premium of the solution, loss units", nullable=True),
        _float("build_seconds", "Wall time to build the problem", nullable=True),
        _float("solve_seconds", "Wall time of all solver calls", nullable=True),
        _str("error_type", "Exception class name of a failure", nullable=True),
        _str("error_message", "Exception message of a failure", nullable=True),
        _str("eventset_checksum", "Content hash of the input EventSet", nullable=True),
        _str("package_version", "parametric-insurance-design version"),
        Column("created_at", "timestamp", "When the row was written (UTC)"),
    ),
)
"""One row per (run, design problem), failed solves included."""

ENTITIES: Final[TableSchema] = TableSchema(
    name="entities",
    key=("run_id", "problem_id", "entity_id", "location_id"),
    columns=(
        _RUN_ID,
        _PROBLEM_ID,
        _ENTITY_ID,
        _str("location_id", "A location the entity covers"),
    ),
)
"""Entity membership: one row per (entity, covered location)."""

PAYOUTS: Final[TableSchema] = TableSchema(
    name="payouts",
    key=("run_id", "problem_id", "entity_id", "param_index"),
    columns=(
        _RUN_ID,
        _PROBLEM_ID,
        _ENTITY_ID,
        _int("param_index", "Parameter (bin) number, from 0"),
        _float("lower", "Lower index bound of the parameter (bin edge)"),
        _float("upper", "Upper index bound of the parameter (bin edge)"),
        _float("value", "Fitted parameter (payout level), loss units"),
    ),
)
"""One row per fitted payout parameter."""

_EVAL_KEY: Final[tuple[Column, ...]] = (
    _RUN_ID,
    _PROBLEM_ID,
    _str("eval_split", "Rows evaluated on", allowed=_SPLIT_VALUES),
    _int("fold", "Fold number for k-fold splits; 0 otherwise"),
    _BASIS,
    _str("level", "What the row describes", allowed=_values(KpiLevel)),
    _str("subject_id", "Location, entity or problem id the row describes"),
)

KPIS: Final[TableSchema] = TableSchema(
    name="kpis",
    key=(
        "run_id",
        "problem_id",
        "eval_split",
        "fold",
        "basis",
        "level",
        "subject_id",
        "kpi",
        "beta",
    ),
    columns=(
        *_EVAL_KEY,
        _str("kpi", "KPI name", allowed=_values(KpiName)),
        _float("beta", "Confidence level of VaR/CVaR KPIs", nullable=True),
        _float("value", "Point estimate; null if undefined", nullable=True),
        _float("ci_low", "Lower confidence bound", nullable=True),
        _float("ci_high", "Upper confidence bound", nullable=True),
        _float("ci_level", "Confidence level of the bounds, e.g. 0.9", nullable=True),
        _int("n_bootstrap", "Bootstrap resamples behind the bounds", nullable=True),
    ),
)
"""One row per KPI value."""

EXCEEDANCE: Final[TableSchema] = TableSchema(
    name="exceedance",
    key=(
        "run_id",
        "problem_id",
        "eval_split",
        "fold",
        "basis",
        "level",
        "subject_id",
        "quantity",
        "curve",
        "return_period",
    ),
    columns=(
        *_EVAL_KEY,
        _str("quantity", "Quantity described", allowed=_values(CurveQuantity)),
        _str("curve", "Curve kind", allowed=_values(CurveKind)),
        _float("return_period", "Return period in years"),
        _float("value", "Quantity exceeded at that return period, loss units"),
    ),
)
"""One row per exceedance-curve point."""

TABLES: Final[Mapping[str, TableSchema]] = {
    t.name: t for t in (RUNS, ENTITIES, PAYOUTS, KPIS, EXCEEDANCE)
}
"""Every result-store table, by name."""
