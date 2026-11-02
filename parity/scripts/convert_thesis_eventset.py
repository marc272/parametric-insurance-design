r"""Convert the thesis event-loss table into the EventSet parity fixture.

The thesis repository (``parametric-insurance-framework``, the parity source)
holds the CLIMADA output ``data/output/climada_transformed_loss_data.csv``: a
wide table with one row per IRIS storm whose track passes within 500 km of any
of the 9 Miami assets, and the columns ``Event_ID``, ``Year``,
``Portfolio_Total_Loss``, ``Portfolio_Max_Wind`` and ``A<k>_Wind``,
``A<k>_Loss`` for every asset. This script turns it into an EventSet (schema
v1, ``docs/SPEC.md`` §5) and copies the thesis result tables that the parity
gate compares against.

Outputs, relative to the repository root:

``parity/tests/data/thesis_eventset/``
    The EventSet directory (``events``, ``locations`` and ``values`` Parquet
    tables plus ``metadata.json``).
``parity/golden/*.csv.gz``
    The thesis result tables ``full_optimization_results.csv`` and
    ``benchmarking_kpis.csv``, byte-identical after decompression. They are
    gzipped because ``full_optimization_results.csv`` (803 kB) exceeds the
    repository's 500 kB file limit.
``parity/manifest.json``
    SHA256 checksums and row/column counts of every source file, fixture file
    and golden table. The parity tests check the committed files against it.

Run from the repository root::

    uv run python parity/scripts/convert_thesis_eventset.py \
        --thesis-repo ../parametric-insurance-framework --overwrite

The thesis repository may also be given with the ``PARITY_THESIS_REPO``
environment variable. It is only read, never modified.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import parametric_insurance_design as pid
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)

#: Environment variable naming the thesis repository checkout.
THESIS_REPO_ENV = "PARITY_THESIS_REPO"

#: Public URL of the thesis repository (the parity source).
THESIS_REPO_URL = "https://github.com/marc272/parametric-insurance-framework"

#: Thesis files read by this script, relative to the thesis repository root.
EVENT_LOSS_CSV = "data/output/climada_transformed_loss_data.csv"
EXPERIMENT_CONFIG = "configs/experiment_config.yaml"
GLOBAL_SETTINGS = "configs/global_settings.yaml"

#: Thesis result tables copied to ``parity/golden/`` (gzipped).
GOLDEN_SOURCES: dict[str, str] = {
    "full_optimization_results.csv": (
        "src/outputs/optimization_results/full_optimization_results.csv"
    ),
    "benchmarking_kpis.csv": "src/outputs/benchmarking_results/benchmarking_kpis.csv",
}

#: Prefix of the ``source_checksums`` keys in the EventSet metadata.
SOURCE_KEY_PREFIX = "parametric-insurance-framework/"

REPO_ROOT = Path(__file__).resolve().parents[2]
PARITY_DIR = REPO_ROOT / "parity"
DEFAULT_EVENTSET_DIR = PARITY_DIR / "tests" / "data" / "thesis_eventset"
DEFAULT_GOLDEN_DIR = PARITY_DIR / "golden"
DEFAULT_MANIFEST = PARITY_DIR / "manifest.json"

#: Leading columns of the thesis CSV, before the per-asset columns.
LEADING_COLUMNS = ("Event_ID", "Year", "Portfolio_Total_Loss", "Portfolio_Max_Wind")

SCENARIO_ID = "iris-present-climate"
LICENCE = "CC-BY-4.0"
HAZARD = HazardSource(
    name="IRIS",
    release=(
        "Sparks & Toumi (2024) 10,000-year event set, figshare collection "
        "10.6084/m9.figshare.c.6724251.v1 (Main dataset "
        "10.6084/m9.figshare.24894186.v1), North Atlantic basin"
    ),
)
INDEX = IndexDefinition(
    definition=(
        "Maximum 1-minute sustained wind speed at 10 m above ground at the asset "
        "over the storm's lifetime: CLIMADA 6.0.1 TropCyclone.from_tracks "
        "intensity with CLIMADA's default wind model; winds below CLIMADA's "
        "17.5 m/s intensity threshold are stored as 0"
    ),
    unit="m/s",
)
LOSS = LossDefinition(unit="USD", currency="USD")
PROXIMITY_KM = 500


def _display(path: Path) -> str:
    """Return ``path`` relative to ``parity/`` when inside it, else absolute."""
    path = path.resolve()
    try:
        return path.relative_to(PARITY_DIR).as_posix()
    except ValueError:
        return path.as_posix()


class ConversionError(RuntimeError):
    """The thesis inputs do not have the layout this script expects."""


@dataclass(frozen=True)
class Conversion:
    """Result of :func:`convert`.

    Parameters
    ----------
    eventset : EventSet
        The converted EventSet.
    source_checksums : dict of str to str
        ``"sha256:<hex>"`` of every thesis file read, keyed by its path
        relative to the thesis repository root.
    source_counts : dict of str to tuple of int
        ``(rows, columns)`` of the thesis event-loss CSV, keyed like
        ``source_checksums``.
    checks : dict
        Consistency checks on the dropped aggregate columns. Recorded in the
        manifest, never silently discarded.
    """

    eventset: EventSet
    source_checksums: dict[str, str]
    source_counts: dict[str, tuple[int, int]]
    checks: dict[str, Any]


def sha256_file(path: str | Path) -> str:
    """Return the SHA256 hex digest of a file.

    Parameters
    ----------
    path : str or pathlib.Path
        File to hash.

    Returns
    -------
    str
        Lower-case hex digest, without a ``sha256:`` prefix.
    """
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_gzip_content(path: str | Path) -> str:
    """Return the SHA256 hex digest of a gzip file's decompressed content.

    Parameters
    ----------
    path : str or pathlib.Path
        Gzip file.

    Returns
    -------
    str
        Lower-case hex digest of the decompressed bytes.
    """
    digest = hashlib.sha256()
    with gzip.open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_thesis_repo(path: str | Path | None) -> Path:
    """Find the thesis repository from an argument or the environment.

    Parameters
    ----------
    path : str, pathlib.Path or None
        Explicit path. If None, :data:`THESIS_REPO_ENV` is read.

    Returns
    -------
    pathlib.Path
        The resolved directory.

    Raises
    ------
    ConversionError
        If no path is given, or the directory lacks the event-loss CSV.
    """
    if path is None:
        env = os.environ.get(THESIS_REPO_ENV)
        if not env:
            raise ConversionError(
                f"no thesis repository given: pass --thesis-repo or set "
                f"{THESIS_REPO_ENV}"
            )
        path = env
    repo = Path(path).expanduser().resolve()
    if not (repo / EVENT_LOSS_CSV).is_file():
        raise ConversionError(f"{repo} does not hold {EVENT_LOSS_CSV}")
    return repo


def thesis_commit(repo: Path) -> str | None:
    """Return the thesis repository's HEAD commit, or None if unavailable.

    Parameters
    ----------
    repo : pathlib.Path
        Thesis repository root.

    Returns
    -------
    str or None
        Full commit hash, or None if ``repo`` is not a git checkout or git is
        not installed. The checksums, not the commit, identify the inputs.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        import yaml  # pyyaml; available in the uv dev environment
    except ImportError as exc:  # pragma: no cover - environment problem
        raise ConversionError(
            "reading the thesis configs needs pyyaml; run with `uv run`"
        ) from exc
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConversionError(f"{path} does not hold a YAML mapping")
    return data


def read_locations(experiment_config: Path) -> pd.DataFrame:
    """Build the ``locations`` table from the thesis ``experiment_config.yaml``.

    Parameters
    ----------
    experiment_config : pathlib.Path
        The thesis experiment config, with an ``ASSETS`` mapping of asset ID
        to ``name``, ``lat``, ``lon``, ``value`` and ``impf_TC``.

    Returns
    -------
    pandas.DataFrame
        Columns ``location_id``, ``lat``, ``lon``, ``value`` (USD), ``name``
        and the free column ``impf_TC`` (CLIMADA impact function ID), in the
        config's asset order.

    Raises
    ------
    ConversionError
        If ``ASSETS`` is missing or an asset lacks a field.
    """
    assets = _load_yaml(experiment_config).get("ASSETS")
    if not isinstance(assets, dict) or not assets:
        raise ConversionError(f"{experiment_config} has no ASSETS mapping")
    rows = []
    for asset_id, spec in assets.items():
        missing = [
            k for k in ("name", "lat", "lon", "value", "impf_TC") if k not in spec
        ]
        if missing:
            raise ConversionError(f"asset {asset_id} lacks {', '.join(missing)}")
        rows.append(
            {
                "location_id": str(asset_id),
                "lat": float(spec["lat"]),
                "lon": float(spec["lon"]),
                "value": float(spec["value"]),
                "name": str(spec["name"]),
                "impf_TC": int(spec["impf_TC"]),
            }
        )
    return pd.DataFrame(rows)


def read_n_years(global_settings: Path) -> int:
    """Read the number of simulated years from the thesis global settings.

    Parameters
    ----------
    global_settings : pathlib.Path
        The thesis ``global_settings.yaml``.

    Returns
    -------
    int
        ``N_YEARS``.

    Raises
    ------
    ConversionError
        If ``N_YEARS`` is missing or not a positive int.
    """
    n_years = _load_yaml(global_settings).get("N_YEARS")
    if not isinstance(n_years, int) or isinstance(n_years, bool) or n_years <= 0:
        raise ConversionError(f"{global_settings}: N_YEARS must be a positive int")
    return n_years


def read_event_loss_table(path: Path, asset_ids: Sequence[str]) -> pd.DataFrame:
    """Read the thesis wide event-loss CSV and check its layout.

    The CSV is parsed with pandas defaults, exactly as the thesis notebook does
    (``utils.data_processing.load_event_data``), so the floats are identical.

    Parameters
    ----------
    path : pathlib.Path
        ``climada_transformed_loss_data.csv``.
    asset_ids : sequence of str
        Asset IDs in config order.

    Returns
    -------
    pandas.DataFrame
        The table as read.

    Raises
    ------
    ConversionError
        If the columns are not exactly the expected layout, ``Event_ID`` is
        not a unique string column, or ``Year`` does not match the year
        encoded in ``Event_ID`` (``NA_<year>_<tc>``).
    """
    frame = pd.read_csv(path)
    expected = list(LEADING_COLUMNS) + [
        f"{a}_{kind}" for a in asset_ids for kind in ("Wind", "Loss")
    ]
    if list(frame.columns) != expected:
        raise ConversionError(
            f"{path.name}: columns {list(frame.columns)} differ from the expected "
            f"layout {expected}"
        )
    event_id = frame["Event_ID"]
    if not all(isinstance(v, str) for v in event_id):
        raise ConversionError(f"{path.name}: Event_ID must be non-null strings")
    if not event_id.is_unique:
        raise ConversionError(f"{path.name}: Event_ID values repeat")
    encoded_year = event_id.str.split("_").str[1]
    if not (encoded_year == frame["Year"].astype(str)).all():
        raise ConversionError(f"{path.name}: Year differs from the Event_ID year")
    return frame


def aggregate_checks(frame: pd.DataFrame, asset_ids: Sequence[str]) -> dict[str, Any]:
    """Check the aggregate columns that the EventSet does not keep.

    ``Portfolio_Max_Wind`` and ``Portfolio_Total_Loss`` are derived from the
    per-asset columns, so the EventSet drops them; the thesis notebook
    recomputes both from the per-asset columns. This records how well they
    agree, so that nothing is dropped unchecked.

    Parameters
    ----------
    frame : pandas.DataFrame
        The thesis event-loss table.
    asset_ids : sequence of str
        Asset IDs.

    Returns
    -------
    dict
        For each aggregate column, the number of rows where it differs from
        the per-asset recomputation (relative tolerance 1e-9 for the loss sum,
        exact for the max wind) and, for the loss, the distinct ratios
        ``sum / Portfolio_Total_Loss`` among those rows.
    """
    wind = frame[[f"{a}_Wind" for a in asset_ids]].to_numpy(dtype=np.float64)
    loss = frame[[f"{a}_Loss" for a in asset_ids]].to_numpy(dtype=np.float64)
    max_wind = frame["Portfolio_Max_Wind"].to_numpy(dtype=np.float64)
    total = frame["Portfolio_Total_Loss"].to_numpy(dtype=np.float64)
    loss_sum = loss.sum(axis=1)
    wind_bad = wind.max(axis=1) != max_wind
    loss_bad = ~np.isclose(loss_sum, total, rtol=1e-9, atol=0.0)
    ratios = np.unique(np.round(loss_sum[loss_bad] / total[loss_bad], 9))
    return {
        "Portfolio_Max_Wind": {
            "rule": "equals the row max of the A<k>_Wind columns (exact)",
            "rows_differing": int(wind_bad.sum()),
        },
        "Portfolio_Total_Loss": {
            "rule": "equals the row sum of the A<k>_Loss columns (rtol 1e-9)",
            "rows_differing": int(loss_bad.sum()),
            "ratios_sum_to_column_in_differing_rows": [float(r) for r in ratios],
        },
    }


def convert(thesis_repo: Path, *, created_at: datetime | None = None) -> Conversion:
    """Convert the thesis event-loss table into an EventSet.

    Every CSV row becomes one event row, in CSV order (the thesis noise layer
    draws its random numbers in that order, so it matters for parity), with
    ``draw_id`` 0 and the annual rate ``1 / N_YEARS``. No row is dropped:
    rows with zero wind and loss at every asset are kept, and years without
    any row are implicit zero-loss years.

    Parameters
    ----------
    thesis_repo : pathlib.Path
        Thesis repository root.
    created_at : datetime.datetime or None, optional
        Provenance timestamp. Defaults to now (UTC).

    Returns
    -------
    Conversion
        The EventSet with its source checksums, counts and aggregate checks.

    Raises
    ------
    ConversionError
        If an input has an unexpected layout.
    EventSetError
        If the converted data fails EventSet validation.
    """
    csv_path = thesis_repo / EVENT_LOSS_CSV
    config_path = thesis_repo / EXPERIMENT_CONFIG
    settings_path = thesis_repo / GLOBAL_SETTINGS

    locations = read_locations(config_path)
    asset_ids = locations["location_id"].tolist()
    n_years = read_n_years(settings_path)
    frame = read_event_loss_table(csv_path, asset_ids)
    checks = aggregate_checks(frame, asset_ids)

    events = pd.DataFrame(
        {
            "event_id": frame["Event_ID"].astype(object),
            "year": frame["Year"].astype(np.int64),
            "rate": np.full(len(frame), 1.0 / n_years),
            "draw_id": np.zeros(len(frame), dtype=np.int64),
            "scenario_id": SCENARIO_ID,
        }
    )
    index = frame[[f"{a}_Wind" for a in asset_ids]].to_numpy(dtype=np.float64)
    loss = frame[[f"{a}_Loss" for a in asset_ids]].to_numpy(dtype=np.float64)
    n_zero = int(((index == 0) & (loss == 0)).all(axis=1).sum())

    source_checksums = {
        rel: f"sha256:{sha256_file(thesis_repo / rel)}"
        for rel in (EVENT_LOSS_CSV, EXPERIMENT_CONFIG, GLOBAL_SETTINGS)
    }
    scenario = (
        f"Thesis parity event set: IRIS North Atlantic {n_years:,}-year synthetic "
        "catalogue (present climate, from 1980-2021 tracks) for the 9 Miami "
        f"assets of the thesis. One row per storm whose track passes within "
        f"{PROXIMITY_KM} km of any asset ({len(frame):,} rows, {n_zero:,} of them "
        "with zero wind and loss at every asset); years without such a storm "
        "are implicit zero-loss years. Losses from CLIMADA's Emanuel (2011) USA "
        "tropical-cyclone impact function. No noise or vulnerability draws "
        "(draw_id 0): the thesis noise layer is applied downstream."
    )
    metadata = EventSetMetadata(
        hazard=HAZARD,
        index=INDEX,
        loss=LOSS,
        n_years=n_years,
        scenario=scenario,
        provenance=Provenance(
            producer=(
                "parametric-insurance-design parity/scripts/convert_thesis_eventset.py"
            ),
            producer_version=pid.__version__,
            created_at=created_at or datetime.now(UTC),
            source_checksums={
                SOURCE_KEY_PREFIX + rel: value
                for rel, value in source_checksums.items()
            },
        ),
        licence=LICENCE,
    )
    eventset = EventSet(
        events=events, locations=locations, index=index, loss=loss, metadata=metadata
    )
    return Conversion(
        eventset=eventset,
        source_checksums=source_checksums,
        source_counts={EVENT_LOSS_CSV: (len(frame), len(frame.columns))},
        checks=checks,
    )


def write_golden(thesis_repo: Path, golden_dir: Path, *, overwrite: bool) -> dict:
    """Copy the thesis result tables to ``golden_dir`` as deterministic gzip.

    Parameters
    ----------
    thesis_repo : pathlib.Path
        Thesis repository root.
    golden_dir : pathlib.Path
        Target directory.
    overwrite : bool
        Replace existing files.

    Returns
    -------
    dict
        Manifest entries keyed by the golden file name.

    Raises
    ------
    FileExistsError
        If a target exists and ``overwrite`` is False.
    """
    golden_dir.mkdir(parents=True, exist_ok=True)
    entries: dict[str, Any] = {}
    for name, rel in GOLDEN_SOURCES.items():
        source = thesis_repo / rel
        target = golden_dir / f"{name}.gz"
        if target.exists() and not overwrite:
            raise FileExistsError(f"{target} exists; pass --overwrite to replace it")
        data = source.read_bytes()
        # mtime=0 and no file name keep the gzip bytes reproducible.
        with (
            target.open("wb") as raw,
            gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0
            ) as handle,
        ):
            handle.write(data)
        table = pd.read_csv(source)
        entries[name] = {
            "thesis_path": rel,
            "stored_as": _display(target),
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "rows": len(table),
            "columns": len(table.columns),
        }
    return entries


def build_manifest(
    conversion: Conversion,
    eventset_dir: Path,
    golden: dict[str, Any],
    commit: str | None,
) -> dict[str, Any]:
    """Assemble ``parity/manifest.json``.

    Parameters
    ----------
    conversion : Conversion
        Output of :func:`convert`.
    eventset_dir : pathlib.Path
        Directory the EventSet was written to.
    golden : dict
        Output of :func:`write_golden`.
    commit : str or None
        Thesis repository commit.

    Returns
    -------
    dict
        The manifest.
    """
    es = conversion.eventset
    sources: dict[str, Any] = {}
    for rel, value in conversion.source_checksums.items():
        entry: dict[str, Any] = {"sha256": value.removeprefix("sha256:")}
        if rel in conversion.source_counts:
            rows, columns = conversion.source_counts[rel]
            entry.update(rows=rows, columns=columns)
        sources[rel] = entry
    files = {
        p.name: sha256_file(p) for p in sorted(eventset_dir.iterdir()) if p.is_file()
    }
    return {
        "description": (
            "Thesis parity fixture. Written by "
            "parity/scripts/convert_thesis_eventset.py; checked by parity/tests."
        ),
        "thesis_repo": THESIS_REPO_URL,
        "thesis_commit": commit,
        "sources": sources,
        "eventset": {
            "path": _display(eventset_dir),
            "n_rows": es.n_rows,
            "n_locations": es.n_locations,
            "n_years": es.metadata.n_years,
            "n_values_rows": es.n_rows * es.n_locations,
            "location_ids": es.location_ids,
            "files_sha256": files,
            "dropped_source_columns": conversion.checks,
        },
        "golden": golden,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run the conversion from the command line.

    Parameters
    ----------
    argv : sequence of str or None, optional
        Arguments; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(
        description="Convert the thesis event-loss table into the parity EventSet."
    )
    parser.add_argument(
        "--thesis-repo",
        default=None,
        help=f"thesis repository root (default: ${THESIS_REPO_ENV})",
    )
    parser.add_argument("--eventset-dir", type=Path, default=DEFAULT_EVENTSET_DIR)
    parser.add_argument("--golden-dir", type=Path, default=DEFAULT_GOLDEN_DIR)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--created-at",
        type=datetime.fromisoformat,
        default=None,
        help="provenance timestamp, ISO 8601 with a UTC offset (default: now)",
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)

    repo = resolve_thesis_repo(args.thesis_repo)
    conversion = convert(repo, created_at=args.created_at)
    conversion.eventset.to_parquet(args.eventset_dir, overwrite=args.overwrite)
    golden = write_golden(repo, args.golden_dir, overwrite=args.overwrite)
    manifest = build_manifest(
        conversion, args.eventset_dir.resolve(), golden, thesis_commit(repo)
    )
    if args.manifest.exists() and not args.overwrite:
        raise FileExistsError(f"{args.manifest} exists; pass --overwrite")
    args.manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(conversion.eventset)
    for rel, value in conversion.source_checksums.items():
        print(f"{value}  {rel}")
    for name, check in conversion.checks.items():
        print(f"{name}: {check['rows_differing']} rows differ ({check['rule']})")
    print(f"wrote {args.eventset_dir}, {args.golden_dir}, {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
