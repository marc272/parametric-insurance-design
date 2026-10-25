"""EventSet: the data contract between all streams (schema v1, SPEC §5).

An EventSet holds a simulated event catalogue for a set of locations: for every
event row (an event, or one noise/vulnerability draw of an event) and every
location, the parametric index value and the ground-truth loss.

In memory
    Dense ``(n_rows, n_locations)`` float64 matrices :attr:`EventSet.index` and
    :attr:`EventSet.loss`, an aligned ``events`` table (one row per matrix row),
    a ``locations`` table (one row per matrix column) and
    :class:`EventSetMetadata`.

On disk
    One directory holding ``events.parquet``, ``locations.parquet``,
    ``values.parquet`` (long format) and ``metadata.json``. See
    :meth:`EventSet.to_parquet` and :meth:`EventSet.from_parquet`.

Tables
    ``events``
        ``event_id`` (str), ``year`` (int, 0-based simulation year in
        ``[0, n_years)``), ``rate`` (float, annual frequency, > 0),
        ``draw_id`` (int, >= 0; 0 if no draws), ``scenario_id`` (str). The key
        is ``(event_id, draw_id)``.
    ``locations``
        ``location_id`` (str, key), ``lat`` (float, degrees in [-90, 90]),
        ``lon`` (float, degrees in [-180, 180]), ``value`` (float, >= 0),
        ``name`` (str), plus free metadata columns.
    ``values``
        ``event_id``, ``draw_id``, ``location_id``, ``index`` (float),
        ``loss`` (float, >= 0). The key is ``(event_id, draw_id,
        location_id)`` and the table must cover every event row and location
        exactly once.

Rates are never rescaled. :meth:`EventSet.filter_threshold` drops rows only to
make solving faster: the dropped rows count as zero-loss mass, and every
filter is recorded in :attr:`EventSetMetadata.filters`. Other transformations
that change rows, locations or values, such as a location subset
(:meth:`EventSet.select_locations`), the noise layer or vulnerability draws,
are recorded in :attr:`EventSetMetadata.transforms` (:class:`TransformRecord`).

Content hash
    :meth:`EventSet.content_hash` returns a ``"sha256:<hex>"`` checksum of the
    data, for result provenance (SPEC §4.3, ``runs.eventset_checksum``). It
    hashes a canonical byte serialisation, not the Parquet files, so it does
    not depend on the pandas, pyarrow or Parquet version.

Every validation failure raises a subclass of :class:`EventSetError`, which is
both a :class:`~parametric_insurance_design.errors.ParametricInsuranceDesignError`
and a :class:`ValueError`.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import os
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Final, Literal, cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from numpy.typing import NDArray

from parametric_insurance_design.errors import ParametricInsuranceDesignError

__all__ = [
    "EVENTS_FILE",
    "LOCATIONS_FILE",
    "METADATA_FILE",
    "SCHEMA_VERSION",
    "SELECT_LOCATIONS_TRANSFORM",
    "VALUES_FILE",
    "DuplicateKeyError",
    "EventSet",
    "EventSetError",
    "EventSetMetadata",
    "HazardSource",
    "InconsistentKeysError",
    "IndexDefinition",
    "LossDefinition",
    "MissingColumnsError",
    "NegativeLossError",
    "NonFiniteValueError",
    "NonPositiveRateError",
    "OutOfRangeError",
    "Provenance",
    "SchemaError",
    "ThresholdFilterRecord",
    "TransformRecord",
]

SCHEMA_VERSION: Final[int] = 1
"""Version of the EventSet schema written by this module."""

EVENTS_FILE: Final[str] = "events.parquet"
LOCATIONS_FILE: Final[str] = "locations.parquet"
VALUES_FILE: Final[str] = "values.parquet"
METADATA_FILE: Final[str] = "metadata.json"

_EVENT_KEY: Final[tuple[str, str]] = ("event_id", "draw_id")
_EVENT_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "year",
    "rate",
    "draw_id",
    "scenario_id",
)
_LOCATION_COLUMNS: Final[tuple[str, ...]] = (
    "location_id",
    "lat",
    "lon",
    "value",
    "name",
)
_VALUE_COLUMNS: Final[tuple[str, ...]] = (
    "event_id",
    "draw_id",
    "location_id",
    "index",
    "loss",
)

_ColumnKind = Literal["str", "int", "float"]
_EVENT_KINDS: Final[dict[str, _ColumnKind]] = {
    "event_id": "str",
    "year": "int",
    "rate": "float",
    "draw_id": "int",
    "scenario_id": "str",
}
_LOCATION_KINDS: Final[dict[str, _ColumnKind]] = {
    "location_id": "str",
    "lat": "float",
    "lon": "float",
    "value": "float",
    "name": "str",
}
_VALUE_KINDS: Final[dict[str, _ColumnKind]] = {
    "event_id": "str",
    "draw_id": "int",
    "location_id": "str",
    "index": "float",
    "loss": "float",
}
_ARROW_TYPES: Final[dict[_ColumnKind, pa.DataType]] = {
    "str": pa.string(),
    "int": pa.int64(),
    "float": pa.float64(),
}

_MAX_EXAMPLES: Final[int] = 5

_VERSION: Final[str] = version("parametric-insurance-design")
"""Version recorded in the :class:`TransformRecord` of this module's methods."""

SELECT_LOCATIONS_TRANSFORM: Final[str] = "select_locations"
"""``TransformRecord.name`` of the records written by
:meth:`EventSet.select_locations`."""


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------


class EventSetError(ParametricInsuranceDesignError, ValueError):
    """Base class for every EventSet validation error.

    It derives from the library base
    :class:`~parametric_insurance_design.errors.ParametricInsuranceDesignError`
    (ADR 0002 §6, §9 row 8) and from :class:`ValueError`.

    Parameters
    ----------
    message : str
        Human-readable description of the problem.
    table : str or None, optional
        The table or file the problem was found in (``"events"``,
        ``"locations"``, ``"values"``, ``"metadata"`` or ``"matrices"``).

    Attributes
    ----------
    table : str or None
        The table or file the problem was found in.
    """

    def __init__(self, message: str, *, table: str | None = None) -> None:
        super().__init__(message if table is None else f"[{table}] {message}")
        self.table = table


class SchemaError(EventSetError):
    """The structure does not match schema v1.

    Raised for an unsupported schema version, malformed or incomplete
    metadata, unexpected columns, wrong column types, wrong matrix shapes and
    missing files.
    """


class MissingColumnsError(EventSetError):
    """A table lacks one or more required columns.

    Parameters
    ----------
    table : str
        The table that lacks the columns.
    missing : sequence of str
        The missing column names.

    Attributes
    ----------
    missing : tuple of str
        The missing column names.
    """

    def __init__(self, table: str, missing: Sequence[str]) -> None:
        self.missing = tuple(missing)
        super().__init__(
            f"missing required columns: {', '.join(self.missing)}", table=table
        )


class DuplicateKeyError(EventSetError):
    """A table holds the same key more than once."""


class NonFiniteValueError(EventSetError):
    """A required value is null, NaN or infinite."""


class InconsistentKeysError(EventSetError):
    """Tables or matrices do not line up.

    Raised when ``values`` refers to an unknown event row or location, when
    ``values`` does not cover every (event row, location) pair, or when the
    matrices do not match the ``events`` and ``locations`` tables.
    """


class OutOfRangeError(EventSetError):
    """A value lies outside its allowed range."""


class NegativeLossError(OutOfRangeError):
    """A loss is negative."""


class NonPositiveRateError(OutOfRangeError):
    """An event rate is zero or negative."""


# --------------------------------------------------------------------------
# Metadata
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HazardSource:
    """Hazard model or catalogue the EventSet was produced from.

    Parameters
    ----------
    name : str
        Source name, e.g. ``"IRIS"`` or ``"CRC"``.
    release : str
        Release or version of the source, e.g. ``"v1.0"``.
    """

    name: str
    release: str

    def __post_init__(self) -> None:
        """Validate the fields."""
        _require_text(self.name, "hazard.name")
        _require_text(self.release, "hazard.release")


@dataclass(frozen=True)
class IndexDefinition:
    """What the ``index`` values measure.

    Parameters
    ----------
    definition : str
        How the index is computed, e.g. ``"max 1-min sustained wind at the
        asset"``.
    unit : str
        Unit of the index values, e.g. ``"m/s"``.
    """

    definition: str
    unit: str

    def __post_init__(self) -> None:
        """Validate the fields."""
        _require_text(self.definition, "index.definition")
        _require_text(self.unit, "index.unit")


@dataclass(frozen=True)
class LossDefinition:
    """Unit of the ``loss`` values.

    Parameters
    ----------
    unit : str
        Unit of the loss values, e.g. ``"USD"`` or ``"fraction of value"``.
    currency : str or None, optional
        ISO 4217 currency code when losses are monetary, e.g. ``"USD"``.
    """

    unit: str
    currency: str | None = None

    def __post_init__(self) -> None:
        """Validate the fields."""
        _require_text(self.unit, "loss.unit")
        if self.currency is not None:
            _require_text(self.currency, "loss.currency")


@dataclass(frozen=True)
class Provenance:
    """Where an EventSet came from.

    Parameters
    ----------
    producer : str
        Distribution or tool that wrote the EventSet, e.g.
        ``"parametric-insurance-design-climada"``.
    producer_version : str
        Version of the producer.
    created_at : datetime.datetime
        Creation time. Must be timezone-aware.
    source_checksums : dict of str to str, optional
        Checksums of the input files, keyed by file name or URL, e.g.
        ``{"tracks.nc": "sha256:..."}``.
    """

    producer: str
    producer_version: str
    created_at: datetime
    source_checksums: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the fields."""
        _require_text(self.producer, "provenance.producer")
        _require_text(self.producer_version, "provenance.producer_version")
        if not isinstance(self.created_at, datetime):
            raise SchemaError(
                "provenance.created_at must be a datetime", table="metadata"
            )
        if self.created_at.utcoffset() is None:
            raise SchemaError(
                "provenance.created_at must be timezone-aware", table="metadata"
            )
        if not isinstance(self.source_checksums, Mapping):
            raise SchemaError(
                "provenance.source_checksums must be a mapping", table="metadata"
            )
        for key, value in self.source_checksums.items():
            _require_text(key, "provenance.source_checksums key")
            _require_text(value, f"provenance.source_checksums[{key!r}]")
        object.__setattr__(self, "source_checksums", dict(self.source_checksums))


@dataclass(frozen=True)
class ThresholdFilterRecord:
    """Record of one :meth:`EventSet.filter_threshold` call.

    Dropped rows count as zero-loss mass. The fields below say how much
    probability and loss mass that assumption removed, so that no filter is
    ever silent.

    Parameters
    ----------
    column : {"index", "loss"}
        Matrix the threshold was applied to.
    threshold : float
        A row was kept if its value in ``column`` was ``>= threshold`` at one
        or more locations.
    n_rows_before : int
        Number of rows before the filter.
    n_rows_kept : int
        Number of rows after the filter.
    rate_dropped : float
        Sum of the annual rates of the dropped rows.
    expected_loss_dropped : float
        Annual expected loss of the dropped rows, summed over locations:
        ``sum(rate * loss.sum(axis=1))`` over the dropped rows.
    max_index_dropped : float or None
        Largest index value among the dropped rows, or None if no row was
        dropped.
    max_loss_dropped : float or None
        Largest loss among the dropped rows, or None if no row was dropped.
    """

    column: Literal["index", "loss"]
    threshold: float
    n_rows_before: int
    n_rows_kept: int
    rate_dropped: float
    expected_loss_dropped: float
    max_index_dropped: float | None
    max_loss_dropped: float | None

    def __post_init__(self) -> None:
        """Validate the fields."""
        if self.column not in ("index", "loss"):
            raise SchemaError(
                f"filter column must be 'index' or 'loss', got {self.column!r}",
                table="metadata",
            )
        for name in ("n_rows_before", "n_rows_kept"):
            value = getattr(self, name)
            if not _is_int(value) or value < 0:
                raise SchemaError(
                    f"filter {name} must be a non-negative int", table="metadata"
                )
        if self.n_rows_kept > self.n_rows_before:
            raise SchemaError(
                "filter n_rows_kept exceeds n_rows_before", table="metadata"
            )
        for name in ("threshold", "rate_dropped", "expected_loss_dropped"):
            object.__setattr__(self, name, _finite_float(getattr(self, name), name))
        for name in ("max_index_dropped", "max_loss_dropped"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _finite_float(value, name))

    @property
    def n_rows_dropped(self) -> int:
        """Number of rows the filter dropped."""
        return self.n_rows_before - self.n_rows_kept


@dataclass(frozen=True)
class TransformRecord:
    """Record of one transformation applied to an EventSet.

    A transformation changes the rows, locations or values of an EventSet
    beyond a threshold filter, e.g. a location subset
    (:meth:`EventSet.select_locations`), the thesis noise layer
    (:func:`parametric_insurance_design.noise.add_noise`) or vulnerability
    draws in an adapter. The producer appends one record to
    :attr:`EventSetMetadata.transforms` per call, so that the provenance of
    the data is structured rather than free text in ``scenario``.

    Random seeds are not recorded here: the caller owns the
    :class:`numpy.random.Generator` and records its seed in the run
    configuration.

    Parameters
    ----------
    name : str
        Short name of the transformation, e.g. ``"noise"`` or
        ``"vulnerability_draws"``.
    function : str
        Fully qualified name of the producing function, e.g.
        ``"parametric_insurance_design.noise.add_noise"``.
    version : str
        Version of the distribution that provides ``function``, e.g. the
        ``parametric-insurance-design`` version.
    n_filters_before : int
        Number of entries in :attr:`EventSetMetadata.filters` when the
        transformation was applied. It places the record among the threshold
        filters, so that their relative order can be recovered (the noise
        layer's random stream depends on the number of input rows).
    parameters : mapping of str to JSON value, optional
        The transformation's parameters, e.g. ``{"kind": "heteroscedastic",
        "level": 0.3}``, or an impact-function prior with its literature
        source. Values may be None, bool, int, finite float, str, lists and
        mappings with str keys, nested to any depth. Tuples become lists and
        numpy scalars become Python scalars, so that the record equals itself
        after a ``metadata.json`` round trip.

    Raises
    ------
    SchemaError
        If a text field is empty, ``n_filters_before`` is not a non-negative
        int, or ``parameters`` holds a value that is not JSON (or a
        non-finite float).
    """

    name: str
    function: str
    version: str
    n_filters_before: int
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the fields and normalise ``parameters``."""
        _require_text(self.name, "transforms[].name")
        _require_text(self.function, "transforms[].function")
        _require_text(self.version, "transforms[].version")
        if not _is_int(self.n_filters_before) or self.n_filters_before < 0:
            raise SchemaError(
                "transforms[].n_filters_before must be a non-negative int",
                table="metadata",
            )
        object.__setattr__(self, "n_filters_before", int(self.n_filters_before))
        if not isinstance(self.parameters, Mapping):
            raise SchemaError(
                "transforms[].parameters must be a mapping", table="metadata"
            )
        object.__setattr__(
            self,
            "parameters",
            _json_value(self.parameters, "transforms[].parameters"),
        )


@dataclass(frozen=True)
class EventSetMetadata:
    """Contents of ``metadata.json``.

    Parameters
    ----------
    hazard : HazardSource
        Hazard source and release.
    index : IndexDefinition
        Index definition and unit.
    loss : LossDefinition
        Loss unit and currency.
    n_years : int
        Number of simulated years Y the event rates refer to. Must be > 0.
    scenario : str
        Description of the scenario(s), e.g. ``"historical climate"``.
    provenance : Provenance
        Source checksums, producer and version, creation time.
    licence : str
        Licence of the data, preferably an SPDX identifier such as
        ``"CC-BY-4.0"``.
    filters : tuple of ThresholdFilterRecord, optional
        Threshold filters applied so far, oldest first.
    transforms : tuple of TransformRecord, optional
        Other transformations applied so far (location subsets, noise,
        vulnerability draws), oldest first. Append-only, like ``filters``. Each record's
        ``n_filters_before`` must not exceed ``len(filters)`` and must not
        decrease along the tuple. A ``metadata.json`` without the
        ``transforms`` key reads as no transforms.
    schema_version : int, optional
        Schema version. Only :data:`SCHEMA_VERSION` is supported.
    """

    hazard: HazardSource
    index: IndexDefinition
    loss: LossDefinition
    n_years: int
    scenario: str
    provenance: Provenance
    licence: str
    filters: tuple[ThresholdFilterRecord, ...] = ()
    transforms: tuple[TransformRecord, ...] = ()
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self) -> None:
        """Validate the fields."""
        if not _is_int(self.schema_version):
            raise SchemaError("schema_version must be an int", table="metadata")
        if self.schema_version != SCHEMA_VERSION:
            raise SchemaError(
                f"unsupported schema_version {self.schema_version}; "
                f"this version reads schema {SCHEMA_VERSION}",
                table="metadata",
            )
        for name, cls in (
            ("hazard", HazardSource),
            ("index", IndexDefinition),
            ("loss", LossDefinition),
            ("provenance", Provenance),
        ):
            if not isinstance(getattr(self, name), cls):
                raise SchemaError(f"{name} must be a {cls.__name__}", table="metadata")
        if not _is_int(self.n_years):
            raise SchemaError("n_years must be an int", table="metadata")
        if self.n_years <= 0:
            raise OutOfRangeError(
                f"n_years must be > 0, got {self.n_years}", table="metadata"
            )
        _require_text(self.scenario, "scenario")
        _require_text(self.licence, "licence")
        filters = tuple(self.filters)
        if not all(isinstance(f, ThresholdFilterRecord) for f in filters):
            raise SchemaError(
                "filters must hold ThresholdFilterRecord objects", table="metadata"
            )
        object.__setattr__(self, "filters", filters)
        transforms = tuple(self.transforms)
        if not all(isinstance(t, TransformRecord) for t in transforms):
            raise SchemaError(
                "transforms must hold TransformRecord objects", table="metadata"
            )
        previous = 0
        for i, record in enumerate(transforms):
            if record.n_filters_before > len(filters):
                raise SchemaError(
                    f"transforms[{i}].n_filters_before is "
                    f"{record.n_filters_before}, but only {len(filters)} "
                    "filters are recorded",
                    table="metadata",
                )
            if record.n_filters_before < previous:
                raise SchemaError(
                    f"transforms[{i}].n_filters_before decreases "
                    f"({previous} -> {record.n_filters_before}); records are "
                    "append-only, oldest first",
                    table="metadata",
                )
            previous = record.n_filters_before
        object.__setattr__(self, "transforms", transforms)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serialisable form written to ``metadata.json``.

        Returns
        -------
        dict
            Nested dictionary with the keys of schema v1.
        """
        return {
            "schema_version": self.schema_version,
            "hazard": dataclasses.asdict(self.hazard),
            "index": dataclasses.asdict(self.index),
            "loss": dataclasses.asdict(self.loss),
            "n_years": self.n_years,
            "scenario": self.scenario,
            "provenance": {
                "producer": self.provenance.producer,
                "producer_version": self.provenance.producer_version,
                "created_at": self.provenance.created_at.isoformat(),
                "source_checksums": dict(self.provenance.source_checksums),
            },
            "licence": self.licence,
            "filters": [dataclasses.asdict(f) for f in self.filters],
            "transforms": [dataclasses.asdict(t) for t in self.transforms],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EventSetMetadata:
        """Build metadata from its ``metadata.json`` form.

        Parameters
        ----------
        data : mapping
            Parsed ``metadata.json``. Unknown and missing keys are errors,
            except that the optional keys ``filters``, ``transforms``,
            ``loss.currency`` and ``provenance.source_checksums`` may be
            missing.

        Returns
        -------
        EventSetMetadata
            The validated metadata.

        Raises
        ------
        SchemaError
            If the version is unsupported, a key is missing or unknown, or a
            value has the wrong type.
        OutOfRangeError
            If ``n_years`` is not positive.
        """
        top = _strict_keys(
            data,
            "metadata",
            required=(
                "schema_version",
                "hazard",
                "index",
                "loss",
                "n_years",
                "scenario",
                "provenance",
                "licence",
            ),
            optional=("filters", "transforms"),
        )
        # Check the version first, so that a future schema fails with a clear
        # message rather than on its first unknown key.
        version = top["schema_version"]
        if not _is_int(version) or version != SCHEMA_VERSION:
            raise SchemaError(
                f"unsupported schema_version {version!r}; "
                f"this version reads schema {SCHEMA_VERSION}",
                table="metadata",
            )
        hazard = _strict_keys(top["hazard"], "hazard", required=("name", "release"))
        index = _strict_keys(top["index"], "index", required=("definition", "unit"))
        loss = _strict_keys(
            top["loss"], "loss", required=("unit",), optional=("currency",)
        )
        prov = _strict_keys(
            top["provenance"],
            "provenance",
            required=("producer", "producer_version", "created_at"),
            optional=("source_checksums",),
        )
        created_at = prov["created_at"]
        if not isinstance(created_at, str):
            raise SchemaError(
                "provenance.created_at must be an ISO 8601 string", table="metadata"
            )
        try:
            created = datetime.fromisoformat(created_at)
        except ValueError as exc:
            raise SchemaError(
                f"provenance.created_at is not ISO 8601: {created_at!r}",
                table="metadata",
            ) from exc
        raw_filters = top.get("filters", [])
        if not isinstance(raw_filters, list):
            raise SchemaError("filters must be a list", table="metadata")
        filter_fields = tuple(f.name for f in dataclasses.fields(ThresholdFilterRecord))
        filters = tuple(
            ThresholdFilterRecord(
                **_strict_keys(raw, "filters[]", required=filter_fields)
            )
            for raw in raw_filters
        )
        raw_transforms = top.get("transforms", [])
        if not isinstance(raw_transforms, list):
            raise SchemaError("transforms must be a list", table="metadata")
        transform_fields = tuple(f.name for f in dataclasses.fields(TransformRecord))
        transforms = tuple(
            TransformRecord(
                **_strict_keys(raw, "transforms[]", required=transform_fields)
            )
            for raw in raw_transforms
        )
        return cls(
            hazard=HazardSource(**hazard),
            index=IndexDefinition(**index),
            loss=LossDefinition(**loss),
            n_years=top["n_years"],
            scenario=top["scenario"],
            provenance=Provenance(
                producer=prov["producer"],
                producer_version=prov["producer_version"],
                created_at=created,
                source_checksums=prov.get("source_checksums", {}),
            ),
            licence=top["licence"],
            filters=filters,
            transforms=transforms,
            schema_version=version,
        )


# --------------------------------------------------------------------------
# EventSet
# --------------------------------------------------------------------------


@dataclass(frozen=True, eq=False, repr=False)
class EventSet:
    """Dense event catalogue: index and loss per event row and location.

    The constructor validates every argument and stores normalised copies:
    tables get a fresh ``RangeIndex`` and canonical dtypes (``object`` for
    strings, ``int64`` and ``float64`` for numbers), and the matrices become
    read-only ``float64`` arrays. Use :meth:`from_long` to build an EventSet
    from a long ``values`` table.

    Parameters
    ----------
    events : pandas.DataFrame
        One row per matrix row, with exactly the columns ``event_id``,
        ``year``, ``rate``, ``draw_id`` and ``scenario_id``.
    locations : pandas.DataFrame
        One row per matrix column, with the columns ``location_id``, ``lat``,
        ``lon``, ``value`` and ``name``, plus any free metadata columns.
    index : array_like
        Index values, shape ``(n_rows, n_locations)``. Must be finite.
    loss : array_like
        Losses, shape ``(n_rows, n_locations)``. Must be finite and >= 0.
    metadata : EventSetMetadata
        Dataset metadata.

    Raises
    ------
    MissingColumnsError
        If a table lacks a required column.
    SchemaError
        If a column has the wrong type, ``events`` has an unexpected column,
        there are no locations, or a matrix is not two-dimensional.
    NonFiniteValueError
        If a required value is null, NaN or infinite.
    NonPositiveRateError
        If a rate is <= 0.
    NegativeLossError
        If a loss is < 0.
    OutOfRangeError
        If ``year`` lies outside ``[0, metadata.n_years)``, or ``draw_id``,
        ``lat``, ``lon`` or ``value`` is out of range.
    DuplicateKeyError
        If ``(event_id, draw_id)`` or ``location_id`` repeats.
    InconsistentKeysError
        If the matrix shapes do not match the tables.

    Notes
    -----
    Years are 0-based: ``year`` is in ``[0, n_years)``, as in IRIS, the thesis
    and the parity fixture (ADR 0002 §5). SPEC §6 writes ``y = 1..Y`` as
    notation only.

    Examples
    --------
    >>> es = EventSet.from_parquet("data/eventsets/iris-florida")  # doctest: +SKIP
    >>> es.index.shape == (es.n_rows, es.n_locations)  # doctest: +SKIP
    True
    """

    events: pd.DataFrame
    locations: pd.DataFrame
    index: NDArray[np.float64]
    loss: NDArray[np.float64]
    metadata: EventSetMetadata

    def __post_init__(self) -> None:
        """Validate the fields."""
        if not isinstance(self.metadata, EventSetMetadata):
            raise SchemaError("metadata must be an EventSetMetadata")
        events = _normalise_events(self.events)
        _check_years(events, self.metadata.n_years)
        locations = _normalise_locations(self.locations)
        shape = (len(events), len(locations))
        index = _normalise_matrix(self.index, "index", shape)
        loss = _normalise_matrix(self.loss, "loss", shape)
        _check_non_negative_loss(loss, "matrices")
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "locations", locations)
        object.__setattr__(self, "index", index)
        object.__setattr__(self, "loss", loss)

    # -- shape and convenience accessors -----------------------------------

    @property
    def n_rows(self) -> int:
        """Number of event rows (events times draws)."""
        return len(self.events)

    @property
    def n_locations(self) -> int:
        """Number of locations."""
        return len(self.locations)

    @property
    def rates(self) -> NDArray[np.float64]:
        """Annual rate of each row, aligned with the matrix rows."""
        return self.events["rate"].to_numpy(dtype=np.float64)

    @property
    def location_ids(self) -> list[str]:
        """Location IDs, aligned with the matrix columns."""
        return self.locations["location_id"].tolist()

    def __repr__(self) -> str:
        """Return a short summary."""
        return (
            f"EventSet(n_rows={self.n_rows}, n_locations={self.n_locations}, "
            f"n_years={self.metadata.n_years}, "
            f"hazard={self.metadata.hazard.name!r} "
            f"{self.metadata.hazard.release!r}, "
            f"filters={len(self.metadata.filters)}, "
            f"transforms={len(self.metadata.transforms)})"
        )

    def equals(self, other: object) -> bool:
        """Test whether two EventSets hold the same data.

        Parameters
        ----------
        other : object
            Object to compare with.

        Returns
        -------
        bool
            True if ``other`` is an EventSet with equal metadata, equal tables
            (values, column order and dtypes) and bitwise-equal matrices.
        """
        if not isinstance(other, EventSet):
            return False
        return (
            self.metadata == other.metadata
            and self.events.equals(other.events)
            and self.locations.equals(other.locations)
            and np.array_equal(self.index, other.index)
            and np.array_equal(self.loss, other.loss)
        )

    # -- content hash ------------------------------------------------------

    def content_hash(self) -> str:
        """Return a SHA-256 checksum of the EventSet's content.

        The checksum identifies the data for result provenance (SPEC §4.3):
        it is the value of ``runs.eventset_checksum`` in the result store
        (ADR 0002 §7). It is computed from a canonical byte serialisation of
        the tables, the matrices and the metadata, never from Parquet bytes,
        so it is the same before and after a Parquet round trip and across
        pandas, pyarrow and numpy versions.

        Returns
        -------
        str
            ``"sha256:"`` followed by 64 lowercase hex digits, the format of
            :attr:`Provenance.source_checksums`.

        Raises
        ------
        SchemaError
            If a free metadata column of ``locations`` holds values other
            than booleans, integers, floats or strings (with or without
            nulls), e.g. datetimes or categoricals.

        Notes
        -----
        **Included**, in this order: the shape; every ``events`` column; every
        ``locations`` schema column; the free ``locations`` columns, sorted by
        name; the ``index`` and ``loss`` matrices; and the metadata. Row order
        and location order are content: they set the matrix layout, and
        samples refer to rows by position.

        **Excluded**:

        * ``metadata.provenance.created_at``. It records when a producer wrote
          the data, not what the data is: writing the same EventSet twice
          would otherwise give two checksums, and caches keyed on the
          checksum would miss.
        * The order of the free ``locations`` columns. It carries no
          information, and a reader may reorder them.
        * Storage details: pandas dtypes beyond the kinds below, the
          DataFrame index, matrix memory layout, Parquet encoding and file
          layout.

        **Canonical serialisation (version 1).** The hash input starts with
        the domain tag ``parametric-insurance-design/eventset-content-hash/v1``
        followed by a NUL byte. Every field after it is framed as
        ``len(tag) || tag || len(payload) || payload``, where lengths are
        unsigned 64-bit little-endian integers and tags are UTF-8 strings
        such as ``"events/rate:float"``. Payloads encode values by kind:

        * ``int``: signed 64-bit little-endian; ``uint``: unsigned 64-bit
          little-endian; ``bool``: one byte, 0 or 1.
        * ``float``: IEEE 754 binary64 little-endian, with ``-0.0`` written
          as ``0.0`` (as :meth:`equals` treats them).
        * ``str``: the count, then each string's UTF-8 byte length, then the
          concatenated UTF-8 bytes.
        * Free ``locations`` columns add a ``:null`` field (one byte per row,
          1 for a null value) and encode only the non-null values. A column
          whose values are all null has kind ``null``.
        * The metadata is :meth:`EventSetMetadata.to_dict` without
          ``provenance.created_at``, and without ``transforms`` when it is
          empty, as JSON with sorted keys, ``(",", ":")`` separators and
          ASCII escapes. Omitting an empty ``transforms`` keeps the hash of
          every EventSet without transforms what it was before
          :attr:`EventSetMetadata.transforms` existed (MAR-88).

        Any change to this format must change the version in the domain tag.

        Computing the hash reads every value once (``O(n_rows * n_locations)``).
        It is not cached, because the tables are mutable DataFrames; compute
        it once per run.

        Examples
        --------
        >>> es = EventSet.from_parquet("data/eventsets/iris-florida")  # doctest: +SKIP
        >>> es.content_hash()  # doctest: +SKIP
        'sha256:3f5a...'
        """
        hasher = _CanonicalHasher()
        hasher.field("shape:int", _int_bytes(np.array([self.n_rows, self.n_locations])))
        for column, kind in _EVENT_KINDS.items():
            hasher.column(f"events/{column}", _column(self.events, column), kind)
        for column, kind in _LOCATION_KINDS.items():
            hasher.column(f"locations/{column}", _column(self.locations, column), kind)
        free = sorted(c for c in self.locations.columns if c not in _LOCATION_KINDS)
        for column in free:
            hasher.free_column(f"locations/{column}", _column(self.locations, column))
        hasher.field("matrices/index:float", _float_bytes(self.index))
        hasher.field("matrices/loss:float", _float_bytes(self.loss))
        metadata = self.metadata.to_dict()
        del metadata["provenance"]["created_at"]
        if not metadata["transforms"]:
            del metadata["transforms"]
        hasher.field(
            "metadata:json",
            json.dumps(
                metadata,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii"),
        )
        return f"sha256:{hasher.hexdigest()}"

    # -- long format -------------------------------------------------------

    @classmethod
    def from_long(
        cls,
        events: pd.DataFrame,
        locations: pd.DataFrame,
        values: pd.DataFrame,
        metadata: EventSetMetadata,
    ) -> EventSet:
        """Build an EventSet from a long ``values`` table.

        Parameters
        ----------
        events : pandas.DataFrame
            The ``events`` table. Its row order sets the matrix row order.
        locations : pandas.DataFrame
            The ``locations`` table. Its row order sets the matrix column
            order.
        values : pandas.DataFrame
            Long table with exactly the columns ``event_id``, ``draw_id``,
            ``location_id``, ``index`` and ``loss``, holding every
            (event row, location) pair once. Row order does not matter.
        metadata : EventSetMetadata
            Dataset metadata.

        Returns
        -------
        EventSet
            The validated EventSet.

        Raises
        ------
        EventSetError
            Any subclass listed for :class:`EventSet`. In addition,
            :class:`DuplicateKeyError` if ``values`` repeats a key and
            :class:`InconsistentKeysError` if it refers to an unknown event
            row or location or misses a pair.
        """
        events = _normalise_events(events)
        locations = _normalise_locations(locations)
        values = _normalise_table(values, "values", _VALUE_KINDS, extra="forbid")
        _check_non_negative_loss(values["loss"].to_numpy(), "values")
        n_rows, n_locations = len(events), len(locations)

        dup = values.duplicated(subset=["event_id", "draw_id", "location_id"])
        if dup.any():
            raise DuplicateKeyError(
                f"{int(dup.sum())} duplicate (event_id, draw_id, location_id) "
                f"keys, e.g. {_examples(values.loc[dup, list(_VALUE_COLUMNS[:3])])}",
                table="values",
            )

        event_keys = pd.MultiIndex.from_arrays(
            [_column(events, "event_id"), _column(events, "draw_id")]
        )
        value_keys = pd.MultiIndex.from_arrays(
            [_column(values, "event_id"), _column(values, "draw_id")]
        )
        row_pos = np.asarray(event_keys.get_indexer(value_keys), dtype=np.int64)
        unknown_rows = row_pos < 0
        if unknown_rows.any():
            raise InconsistentKeysError(
                f"{int(unknown_rows.sum())} values rows refer to an "
                "(event_id, draw_id) not in events, e.g. "
                f"{_examples(values.loc[unknown_rows, list(_EVENT_KEY)])}",
                table="values",
            )
        col_pos = np.asarray(
            pd.Index(_column(locations, "location_id")).get_indexer(
                _column(values, "location_id").to_numpy()
            ),
            dtype=np.int64,
        )
        unknown_cols = col_pos < 0
        if unknown_cols.any():
            raise InconsistentKeysError(
                f"{int(unknown_cols.sum())} values rows refer to a location_id "
                "not in locations, e.g. "
                f"{_examples(values.loc[unknown_cols, ['location_id']])}",
                table="values",
            )

        n_cells = n_rows * n_locations
        if len(values) != n_cells:
            # Keys are unique and known, so fewer rows means missing pairs.
            covered = np.zeros(n_cells, dtype=bool)
            covered[row_pos * n_locations + col_pos] = True
            first = int(np.flatnonzero(~covered)[0])
            r, c = divmod(first, n_locations)
            raise InconsistentKeysError(
                f"values covers {len(values)} of {n_cells} (event row, location) "
                f"pairs; {n_cells - len(values)} are missing, e.g. "
                f"event_id={events['event_id'].iat[r]!r}, "
                f"draw_id={int(events['draw_id'].iat[r])}, "
                f"location_id={locations['location_id'].iat[c]!r}",
                table="values",
            )

        flat = row_pos * n_locations + col_pos
        index = np.empty(n_cells, dtype=np.float64)
        loss = np.empty(n_cells, dtype=np.float64)
        index[flat] = values["index"].to_numpy(dtype=np.float64)
        loss[flat] = values["loss"].to_numpy(dtype=np.float64)
        return cls(
            events=events,
            locations=locations,
            index=index.reshape(n_rows, n_locations),
            loss=loss.reshape(n_rows, n_locations),
            metadata=metadata,
        )

    def to_long(self) -> pd.DataFrame:
        """Return the long ``values`` table.

        Returns
        -------
        pandas.DataFrame
            Columns ``event_id``, ``draw_id``, ``location_id``, ``index`` and
            ``loss``; one row per (event row, location) pair, ordered by
            event row, then location.
        """
        n_locations = self.n_locations
        return pd.DataFrame(
            {
                "event_id": np.repeat(
                    self.events["event_id"].to_numpy(dtype=object), n_locations
                ),
                "draw_id": np.repeat(
                    self.events["draw_id"].to_numpy(dtype=np.int64), n_locations
                ),
                "location_id": np.tile(
                    self.locations["location_id"].to_numpy(dtype=object), self.n_rows
                ),
                "index": self.index.ravel(),
                "loss": self.loss.ravel(),
            }
        )

    # -- Parquet I/O -------------------------------------------------------

    def to_parquet(self, path: str | Path, *, overwrite: bool = False) -> Path:
        """Write the EventSet as a directory of Parquet tables and metadata.

        Parameters
        ----------
        path : str or pathlib.Path
            Target directory. It is created if needed.
        overwrite : bool, default False
            Replace the EventSet files if the directory already holds any of
            them. Other files in the directory are left alone.

        Returns
        -------
        pathlib.Path
            The directory written.

        Raises
        ------
        FileExistsError
            If ``overwrite`` is False and the directory already holds an
            EventSet file, or ``path`` is an existing file.

        Notes
        -----
        The write is atomic for readers: if it is interrupted at any point,
        ``path`` holds the old EventSet, or no EventSet that
        :meth:`from_parquet` accepts, never a mix or a partial file.

        All four files are first written and flushed to disk (``fsync``) in a
        staging directory on the same file system:

        * If ``path`` does not exist, the staging directory is a hidden
          sibling (``.<name>.*.tmp``) and is renamed to ``path`` in one step.
        * If ``path`` is an existing directory, the staging directory is a
          hidden subdirectory of it (``.eventset-*.tmp``), so that the other
          files in ``path`` stay where they are. ``metadata.json`` acts as
          the commit marker: an old one is removed first, the three Parquet
          files are moved in, and the new ``metadata.json`` is moved in last.
          Each move is an atomic rename, and :meth:`from_parquet` refuses a
          directory without ``metadata.json``.

        On an exception (including ``KeyboardInterrupt``), the staging
        directory is removed before the exception propagates. A process that
        is killed outright may leave the hidden staging directory behind; it
        never affects :meth:`from_parquet` and may be deleted.
        """
        directory = Path(path)
        if directory.exists() and not directory.is_dir():
            raise FileExistsError(f"{directory} exists and is not a directory")
        names = (EVENTS_FILE, LOCATIONS_FILE, VALUES_FILE, METADATA_FILE)
        existing = [n for n in names if (directory / n).exists()]
        if existing and not overwrite:
            raise FileExistsError(
                f"{directory} already holds {', '.join(existing)}; "
                "pass overwrite=True to replace them"
            )
        # Resolve symlinks so that the staging directory and the target share
        # a file system, which renames require.
        target = directory.resolve()
        fresh = not target.exists()
        if fresh:
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
                )
            )
        else:
            staging = Path(
                tempfile.mkdtemp(prefix=".eventset-", suffix=".tmp", dir=target)
            )
        try:
            self._write_files(staging)
            if fresh:
                os.rename(staging, target)
                _fsync_directory(target.parent)
            else:
                _commit_files(staging, target)
                os.rmdir(staging)
        except BaseException as exc:
            if staging.exists():
                try:
                    shutil.rmtree(staging)
                except OSError as cleanup:
                    exc.add_note(
                        f"could not remove the staging directory {staging}: {cleanup}"
                    )
            raise
        return directory

    def _write_files(self, directory: Path) -> None:
        """Write the four EventSet files into ``directory`` and fsync them."""
        pq.write_table(_to_arrow(self.events, _EVENT_KINDS), directory / EVENTS_FILE)
        pq.write_table(
            _to_arrow(self.locations, _LOCATION_KINDS), directory / LOCATIONS_FILE
        )
        pq.write_table(_to_arrow(self.to_long(), _VALUE_KINDS), directory / VALUES_FILE)
        (directory / METADATA_FILE).write_text(
            json.dumps(self.metadata.to_dict(), indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        for name in (EVENTS_FILE, LOCATIONS_FILE, VALUES_FILE, METADATA_FILE):
            with (directory / name).open("rb+") as handle:
                os.fsync(handle.fileno())
        _fsync_directory(directory)

    @classmethod
    def from_parquet(cls, path: str | Path) -> EventSet:
        """Read and validate an EventSet directory.

        Parameters
        ----------
        path : str or pathlib.Path
            Directory written by :meth:`to_parquet` or any producer of
            schema v1.

        Returns
        -------
        EventSet
            The validated EventSet.

        Raises
        ------
        SchemaError
            If a file is missing, ``metadata.json`` is not valid JSON, or the
            schema version is unsupported.
        EventSetError
            Any other validation error, as for :meth:`from_long`.
        """
        directory = Path(path)
        missing = [
            n
            for n in (EVENTS_FILE, LOCATIONS_FILE, VALUES_FILE, METADATA_FILE)
            if not (directory / n).is_file()
        ]
        if missing:
            raise SchemaError(
                f"{directory} is not an EventSet directory; "
                f"missing {', '.join(missing)}"
            )
        try:
            raw = json.loads((directory / METADATA_FILE).read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SchemaError(f"invalid JSON: {exc}", table="metadata") from exc
        if not isinstance(raw, dict):
            raise SchemaError("must hold a JSON object", table="metadata")
        metadata = EventSetMetadata.from_dict(raw)
        return cls.from_long(
            events=pq.read_table(directory / EVENTS_FILE).to_pandas(),
            locations=pq.read_table(directory / LOCATIONS_FILE).to_pandas(),
            values=pq.read_table(directory / VALUES_FILE).to_pandas(),
            metadata=metadata,
        )

    # -- filtering ---------------------------------------------------------

    def filter_threshold(
        self, threshold: float, *, column: Literal["index", "loss"] = "index"
    ) -> EventSet:
        """Drop rows below a threshold at every location, for speed only.

        A row is kept if its value in ``column`` is ``>= threshold`` at one or
        more locations. Rates are not rescaled: the dropped rows count as
        zero-loss mass. The returned EventSet carries a
        :class:`ThresholdFilterRecord` as the last entry of
        ``metadata.filters``, stating how many rows, how much rate and how much
        expected loss were dropped.

        Parameters
        ----------
        threshold : float
            Finite threshold.
        column : {"index", "loss"}, default "index"
            Matrix to compare with the threshold. The thesis filter is
            ``column="index"`` with the attachment point as threshold, which
            keeps every row that can trigger a payout.

        Returns
        -------
        EventSet
            A new EventSet with the kept rows, in their original order.

        Raises
        ------
        ValueError
            If ``threshold`` is not finite or ``column`` is unknown.
        """
        if column not in ("index", "loss"):
            raise ValueError(f"column must be 'index' or 'loss', got {column!r}")
        threshold = float(threshold)
        if not math.isfinite(threshold):
            raise ValueError(f"threshold must be finite, got {threshold}")
        matrix = self.index if column == "index" else self.loss
        keep = (matrix >= threshold).any(axis=1)
        drop = ~keep
        rates = self.rates
        n_dropped = int(drop.sum())
        record = ThresholdFilterRecord(
            column=column,
            threshold=threshold,
            n_rows_before=self.n_rows,
            n_rows_kept=self.n_rows - n_dropped,
            rate_dropped=float(rates[drop].sum()),
            expected_loss_dropped=float(rates[drop] @ self.loss[drop].sum(axis=1)),
            max_index_dropped=float(self.index[drop].max()) if n_dropped else None,
            max_loss_dropped=float(self.loss[drop].max()) if n_dropped else None,
        )
        metadata = dataclasses.replace(
            self.metadata, filters=(*self.metadata.filters, record)
        )
        return EventSet(
            events=self.events.loc[keep],
            locations=self.locations,
            index=self.index[keep],
            loss=self.loss[keep],
            metadata=metadata,
        )

    # -- location subset ---------------------------------------------------

    def select_locations(self, location_ids: Sequence[str]) -> EventSet:
        """Keep a subset of the locations, in a given order.

        The portfolio subset of an experiment (``portfolio.location_ids``) and
        each point of an ``n_assets`` sweep. The returned EventSet holds the
        matrix columns and ``locations`` rows of ``location_ids``, in that
        order, with every free metadata column. Every event row is kept, so
        rates, years and draws are unchanged.

        The metadata is kept, including every threshold filter and transform
        record, and one :class:`TransformRecord` is appended to
        ``metadata.transforms``:

        * ``name``: :data:`SELECT_LOCATIONS_TRANSFORM` (``"select_locations"``);
        * ``function``: the qualified name of this method,
          ``parametric_insurance_design.eventset.EventSet.select_locations``;
        * ``parameters``: ``{"location_ids": [...], "n_locations_before": n}``,
          the kept ids in their new order and the number of locations of the
          input.

        A record is appended on every call, also when the selection keeps all
        locations in their order, as :meth:`filter_threshold` records a
        filter that drops nothing. So :meth:`content_hash` always tells a
        subset from the EventSet it was cut from.

        Parameters
        ----------
        location_ids : sequence of str
            Locations to keep, in the order of the new matrix columns.
            Non-empty, unique, and each one a ``location_id`` of this
            EventSet.

        Returns
        -------
        EventSet
            A new EventSet with ``len(location_ids)`` locations.

        Raises
        ------
        SchemaError
            If ``location_ids`` is a single string, is empty (an EventSet
            holds at least one location), or holds a value that is not a
            string.
        DuplicateKeyError
            If an id appears more than once.
        InconsistentKeysError
            If an id is not a location of this EventSet.

        Notes
        -----
        Thesis: ``create_sub_portfolio`` drops the ``<id>_Wind`` and
        ``<id>_Loss`` columns of the other assets, and the solver reads the
        kept ones in ``asset_ids`` order, the order of
        ``itertools.combinations`` over the asset list in the ``n_assets``
        sweep. Selecting those ids in that order gives the same matrices.

        Examples
        --------
        >>> es = EventSet.from_parquet("data/eventsets/thesis")  # doctest: +SKIP
        >>> es.select_locations(["A3", "A1"]).location_ids  # doctest: +SKIP
        ['A3', 'A1']
        """
        if isinstance(location_ids, str):
            raise SchemaError(
                "location_ids must be a sequence of ids, not the string "
                f"{location_ids!r}",
                table="locations",
            )
        requested: list[object] = list(location_ids)
        if not requested:
            raise SchemaError(
                "location_ids is empty; an EventSet must hold at least one location",
                table="locations",
            )
        not_text = [v for v in requested if not isinstance(v, str)]
        if not_text:
            raise SchemaError(
                f"location_ids must be strings; {len(not_text)} are not, e.g. "
                f"{', '.join(repr(v) for v in not_text[:_MAX_EXAMPLES])}",
                table="locations",
            )
        # str() turns numpy strings into plain ones for the JSON record.
        ids = [str(v) for v in requested]
        seen: set[str] = set()
        repeated: list[str] = []
        for loc in ids:
            if loc in seen and loc not in repeated:
                repeated.append(loc)
            seen.add(loc)
        if repeated:
            raise DuplicateKeyError(
                f"location_ids repeat {len(repeated)} ids, e.g. "
                f"{', '.join(repr(v) for v in repeated[:_MAX_EXAMPLES])}",
                table="locations",
            )
        position = {loc: j for j, loc in enumerate(self.location_ids)}
        unknown = [loc for loc in ids if loc not in position]
        if unknown:
            raise InconsistentKeysError(
                f"{len(unknown)} location_ids are not locations of this "
                "EventSet, e.g. "
                f"{', '.join(repr(v) for v in unknown[:_MAX_EXAMPLES])}",
                table="locations",
            )
        columns = np.array([position[loc] for loc in ids], dtype=np.int64)
        record = TransformRecord(
            name=SELECT_LOCATIONS_TRANSFORM,
            function=(
                f"{EventSet.select_locations.__module__}."
                f"{EventSet.select_locations.__qualname__}"
            ),
            version=_VERSION,
            n_filters_before=len(self.metadata.filters),
            parameters={"location_ids": ids, "n_locations_before": self.n_locations},
        )
        metadata = dataclasses.replace(
            self.metadata, transforms=(*self.metadata.transforms, record)
        )
        return EventSet(
            events=self.events,
            locations=self.locations.iloc[columns],
            index=self.index[:, columns],
            loss=self.loss[:, columns],
            metadata=metadata,
        )


# --------------------------------------------------------------------------
# Validation helpers
# --------------------------------------------------------------------------


def _is_int(value: object) -> bool:
    return isinstance(value, int | np.integer) and not isinstance(value, bool)


def _finite_float(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float | np.number):
        raise SchemaError(f"{name} must be a number", table="metadata")
    result = float(value)
    if not math.isfinite(result):
        raise SchemaError(f"{name} must be finite", table="metadata")
    return result


def _require_text(value: object, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{name} must be a non-empty string", table="metadata")


def _json_value(value: object, path: str) -> object:
    """Return a plain-JSON copy of ``value`` or raise :class:`SchemaError`."""
    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, int | np.integer):
        return int(value)
    if isinstance(value, float | np.floating):
        result = float(value)
        if not math.isfinite(result):
            raise SchemaError(f"{path} must be finite, got {result}", table="metadata")
        return result
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        copy: dict[str, Any] = {}
        for key, item in mapping.items():
            if not isinstance(key, str):
                raise SchemaError(
                    f"{path} has a non-string key {key!r}", table="metadata"
                )
            copy[key] = _json_value(item, f"{path}.{key}")
        return copy
    if isinstance(value, list | tuple):
        items = cast(Sequence[object], value)
        return [_json_value(item, f"{path}[{i}]") for i, item in enumerate(items)]
    raise SchemaError(
        f"{path} holds a {type(value).__name__}, which is not a JSON value",
        table="metadata",
    )


def _strict_keys(
    data: object,
    name: str,
    *,
    required: Sequence[str],
    optional: Sequence[str] = (),
) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise SchemaError(f"{name} must be a JSON object", table="metadata")
    keys = set(data)
    missing = [k for k in required if k not in keys]
    unknown = sorted(str(k) for k in keys - set(required) - set(optional))
    if missing:
        raise SchemaError(f"{name} lacks keys: {', '.join(missing)}", table="metadata")
    if unknown:
        raise SchemaError(
            f"{name} has unknown keys: {', '.join(unknown)}", table="metadata"
        )
    return dict(data)


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    return cast(pd.Series, frame[name])


def _examples(frame: pd.DataFrame) -> str:
    rows: list[tuple[Any, ...]] = list(
        frame.head(_MAX_EXAMPLES).itertuples(index=False, name=None)
    )
    return ", ".join(repr(r[0]) if len(r) == 1 else repr(r) for r in rows)


def _normalise_column(
    series: pd.Series, table: str, column: str, kind: _ColumnKind
) -> pd.Series:
    null = series.isna().to_numpy()
    if null.any():
        raise NonFiniteValueError(
            f"column {column!r} has {int(null.sum())} null/NaN values", table=table
        )
    if len(series) == 0:
        # An empty column holds no values to check; only its dtype is set.
        return series.astype(
            {"str": object, "int": np.int64, "float": np.float64}[kind]
        )
    dtype = series.dtype
    if kind == "str":
        inferred = pd.api.types.infer_dtype(series, skipna=False)
        if inferred != "string":
            raise SchemaError(
                f"column {column!r} must hold strings, found {inferred}", table=table
            )
        return series.astype(object)
    if kind == "int":
        if not pd.api.types.is_integer_dtype(dtype):
            raise SchemaError(
                f"column {column!r} must have an integer dtype, found {dtype}",
                table=table,
            )
        return series.astype(np.int64)
    if pd.api.types.is_bool_dtype(dtype) or not pd.api.types.is_numeric_dtype(dtype):
        raise SchemaError(
            f"column {column!r} must have a numeric dtype, found {dtype}", table=table
        )
    result = series.astype(np.float64)
    infinite = ~np.isfinite(result.to_numpy())
    if infinite.any():
        raise NonFiniteValueError(
            f"column {column!r} has {int(infinite.sum())} infinite values",
            table=table,
        )
    return result


def _normalise_table(
    frame: object,
    table: str,
    kinds: Mapping[str, _ColumnKind],
    *,
    extra: Literal["forbid", "keep"],
) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise SchemaError("must be a pandas DataFrame", table=table)
    columns = list(frame.columns)
    if any(not isinstance(c, str) for c in columns):
        raise SchemaError("column names must be strings", table=table)
    if len(set(columns)) != len(columns):
        raise SchemaError("column names must be unique", table=table)
    missing = [c for c in kinds if c not in columns]
    if missing:
        raise MissingColumnsError(table, missing)
    others = [c for c in columns if c not in kinds]
    if others and extra == "forbid":
        raise SchemaError(f"unexpected columns: {', '.join(others)}", table=table)
    data: dict[str, pd.Series] = {
        c: _normalise_column(_column(frame, c).reset_index(drop=True), table, c, kind)
        for c, kind in kinds.items()
    }
    for c in others:
        col = _column(frame, c).reset_index(drop=True)
        # Parquet readers on pandas >= 3 return the "str" dtype; keep object so
        # that a round trip yields identical dtypes on every pandas version.
        if isinstance(col.dtype, pd.StringDtype):
            col = col.astype(object)
        data[c] = col
    return pd.DataFrame(data, index=pd.RangeIndex(len(frame)))


def _normalise_events(frame: object) -> pd.DataFrame:
    events = _normalise_table(frame, "events", _EVENT_KINDS, extra="forbid")
    rate = events["rate"].to_numpy()
    bad = rate <= 0
    if bad.any():
        raise NonPositiveRateError(
            f"{int(bad.sum())} rates are <= 0 (min {rate.min()!r})", table="events"
        )
    if (events["draw_id"].to_numpy() < 0).any():
        raise OutOfRangeError("draw_id must be >= 0", table="events")
    dup = events.duplicated(subset=list(_EVENT_KEY))
    if dup.any():
        raise DuplicateKeyError(
            f"{int(dup.sum())} duplicate (event_id, draw_id) keys, e.g. "
            f"{_examples(events.loc[dup, list(_EVENT_KEY)])}",
            table="events",
        )
    return events


def _check_years(events: pd.DataFrame, n_years: int) -> None:
    # ADR 0002 §5: years are 0-based, year in [0, n_years).
    years = events["year"].to_numpy()
    bad = (years < 0) | (years >= n_years)
    if bad.any():
        raise OutOfRangeError(
            f"year must lie in [0, {n_years}) (0-based, ADR 0002 §5; n_years from "
            f"metadata); {int(bad.sum())} rows are outside, e.g. "
            f"{_examples(events.loc[bad, ['event_id', 'draw_id', 'year']])}",
            table="events",
        )


def _normalise_locations(frame: object) -> pd.DataFrame:
    locations = _normalise_table(frame, "locations", _LOCATION_KINDS, extra="keep")
    if len(locations) == 0:
        raise SchemaError("must hold at least one location", table="locations")
    for column, low, high in (("lat", -90.0, 90.0), ("lon", -180.0, 180.0)):
        values = locations[column].to_numpy()
        if ((values < low) | (values > high)).any():
            raise OutOfRangeError(
                f"{column} must lie in [{low}, {high}]", table="locations"
            )
    if (locations["value"].to_numpy() < 0).any():
        raise OutOfRangeError("value must be >= 0", table="locations")
    dup = locations.duplicated(subset=["location_id"])
    if dup.any():
        raise DuplicateKeyError(
            f"{int(dup.sum())} duplicate location_id keys, e.g. "
            f"{_examples(locations.loc[dup, ['location_id']])}",
            table="locations",
        )
    return locations


def _normalise_matrix(
    matrix: object, name: str, shape: tuple[int, int]
) -> NDArray[np.float64]:
    array = np.asarray(matrix)
    if array.dtype == np.bool_ or not np.issubdtype(array.dtype, np.number):
        raise SchemaError(
            f"{name} must be numeric, found {array.dtype}", table="matrices"
        )
    if array.ndim != 2:
        raise SchemaError(
            f"{name} must be two-dimensional, found {array.ndim} dimensions",
            table="matrices",
        )
    if array.shape != shape:
        raise InconsistentKeysError(
            f"{name} has shape {array.shape}, but events and locations imply {shape}",
            table="matrices",
        )
    result = np.array(array, dtype=np.float64, copy=True)
    bad = ~np.isfinite(result)
    if bad.any():
        raise NonFiniteValueError(
            f"{name} has {int(bad.sum())} NaN or infinite values", table="matrices"
        )
    result.setflags(write=False)
    return result


def _check_non_negative_loss(loss: NDArray[Any], table: str) -> None:
    negative = loss < 0
    if negative.any():
        raise NegativeLossError(
            f"{int(negative.sum())} losses are negative (min {loss.min()!r})",
            table=table,
        )


def _to_arrow(frame: pd.DataFrame, kinds: Mapping[str, _ColumnKind]) -> pa.Table:
    # Explicit Arrow types for the schema columns, so that empty tables and
    # every pandas version write the same schema.
    arrays: dict[str, pa.Array] = {}
    for column in frame.columns:
        values = frame[column]
        if column in kinds:
            arrays[column] = pa.array(
                values.to_numpy(), type=_ARROW_TYPES[kinds[column]]
            )
        else:
            arrays[column] = pa.Array.from_pandas(values)
    return pa.table(arrays)


# --------------------------------------------------------------------------
# Atomic write helpers (see EventSet.to_parquet)
# --------------------------------------------------------------------------


def _fsync_directory(directory: Path) -> None:
    """Flush a directory's entries (renames, removals) to disk.

    POSIX only: Windows cannot open a directory for ``fsync``, and NTFS
    journals renames itself.
    """
    if os.name != "posix":  # pragma: no cover - CI runs on Linux
        return
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _commit_files(staging: Path, target: Path) -> None:
    """Move the staged EventSet files into an existing directory.

    ``metadata.json`` is the commit marker: it is removed first and moved in
    last, so that every intermediate state lacks it and
    :meth:`EventSet.from_parquet` refuses it.
    """
    old_metadata = target / METADATA_FILE
    if old_metadata.exists():
        os.unlink(old_metadata)
        _fsync_directory(target)
    for name in (EVENTS_FILE, LOCATIONS_FILE, VALUES_FILE):
        os.replace(staging / name, target / name)
    _fsync_directory(target)
    os.replace(staging / METADATA_FILE, old_metadata)
    _fsync_directory(target)


# --------------------------------------------------------------------------
# Content hash (canonical serialisation v1, see EventSet.content_hash)
# --------------------------------------------------------------------------

_HASH_DOMAIN: Final[bytes] = b"parametric-insurance-design/eventset-content-hash/v1\x00"

_FreeKind = Literal["null", "bool", "int", "uint", "float", "str"]
_OBJECT_KINDS: Final[dict[str, _FreeKind]] = {
    "empty": "null",
    "string": "str",
    "boolean": "bool",
    "integer": "int",
    "floating": "float",
}
_INT64: Final = np.iinfo(np.int64)


def _u64(value: int) -> bytes:
    return int(value).to_bytes(8, "little", signed=False)


def _int_bytes(values: object) -> NDArray[Any]:
    return np.ascontiguousarray(values, dtype="<i8")


def _uint_bytes(values: object) -> NDArray[Any]:
    return np.ascontiguousarray(values, dtype="<u8")


def _float_bytes(values: object) -> NDArray[Any]:
    # Adding 0.0 turns -0.0 into 0.0 and leaves every other value unchanged.
    return np.ascontiguousarray(np.asarray(values, dtype="<f8") + 0.0)


def _bool_bytes(values: object) -> NDArray[Any]:
    return np.ascontiguousarray(np.asarray(values, dtype=np.bool_), dtype=np.uint8)


def _str_chunks(values: Sequence[str]) -> tuple[bytes, NDArray[Any], bytes]:
    encoded = [v.encode("utf-8") for v in values]
    lengths = np.fromiter((len(b) for b in encoded), dtype="<u8", count=len(encoded))
    return _u64(len(encoded)), lengths, b"".join(encoded)


class _CanonicalHasher:
    """Feed framed fields into SHA-256 (format in EventSet.content_hash)."""

    def __init__(self) -> None:
        self._sha = hashlib.sha256(_HASH_DOMAIN)

    def hexdigest(self) -> str:
        return self._sha.hexdigest()

    def field(self, tag: str, *chunks: bytes | NDArray[Any]) -> None:
        tag_bytes = tag.encode("utf-8")
        views = [memoryview(c).cast("B") for c in chunks]
        self._sha.update(_u64(len(tag_bytes)))
        self._sha.update(tag_bytes)
        self._sha.update(_u64(sum(v.nbytes for v in views)))
        for view in views:
            self._sha.update(view)

    def column(self, tag: str, series: pd.Series, kind: _ColumnKind) -> None:
        # Schema columns are validated and normalised: no nulls, fixed kind.
        if kind == "str":
            self.field(f"{tag}:str", *_str_chunks(series.tolist()))
        elif kind == "int":
            self.field(f"{tag}:int", _int_bytes(series.to_numpy(dtype=np.int64)))
        else:
            self.field(f"{tag}:float", _float_bytes(series.to_numpy(dtype=np.float64)))

    def free_column(self, tag: str, series: pd.Series) -> None:
        null = series.isna().to_numpy(dtype=np.bool_)
        present = cast(pd.Series, series[~null])
        kind = _free_kind(present, tag)
        self.field(f"{tag}:null", _bool_bytes(null))
        if kind == "null":
            self.field(f"{tag}:null-kind")
        elif kind == "bool":
            self.field(f"{tag}:bool", _bool_bytes(present.to_numpy(dtype=np.bool_)))
        elif kind == "int":
            self.field(f"{tag}:int", _int_bytes(present.to_numpy(dtype=np.int64)))
        elif kind == "uint":
            self.field(f"{tag}:uint", _uint_bytes(present.to_numpy(dtype=np.uint64)))
        elif kind == "float":
            self.field(f"{tag}:float", _float_bytes(present.to_numpy(dtype=np.float64)))
        else:
            self.field(f"{tag}:str", *_str_chunks(present.tolist()))


def _free_kind(present: pd.Series, tag: str) -> _FreeKind:
    """Classify the non-null values of a free ``locations`` column."""
    column = tag.split("/", 1)[1]
    dtype = present.dtype
    if len(present) == 0:
        return "null"
    if pd.api.types.is_bool_dtype(dtype):
        return "bool"
    if pd.api.types.is_unsigned_integer_dtype(dtype):
        return "uint"
    if pd.api.types.is_integer_dtype(dtype):
        return "int"
    if pd.api.types.is_float_dtype(dtype):
        return "float"
    found: object = dtype
    if pd.api.types.is_object_dtype(dtype) or isinstance(dtype, pd.StringDtype):
        found = pd.api.types.infer_dtype(present, skipna=False)
        kind = _OBJECT_KINDS.get(str(found))
        if kind == "int":
            values = present.tolist()
            if min(values) < _INT64.min or max(values) > _INT64.max:
                raise SchemaError(
                    f"free column {column!r} holds integers outside the int64 "
                    "range, which content_hash cannot encode",
                    table="locations",
                )
        if kind is not None:
            return kind
    raise SchemaError(
        f"free column {column!r} has values of type {found}; content_hash "
        "supports booleans, integers, floats and strings (with or without nulls)",
        table="locations",
    )
