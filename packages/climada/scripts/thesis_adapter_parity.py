r"""Check that the CLIMADA adapter regenerates the thesis event-loss table (MAR-20).

The parity fixture ``parity/tests/data/thesis_eventset`` is the thesis input,
the event-loss table that the thesis ``src/CLIMADA/engine.py`` wrote
(``data/output/climada_transformed_loss_data.csv``, SHA256
``8513f5fe…ff68``; converted by MAR-9). This script builds the same portfolio
with the adapter (``configs/thesis.yaml``: the 9 Miami assets on the IRIS
North Atlantic 10,000-year catalogue), compares the two EventSets field by
field and writes the adapter section of the parity report,
``parity/analysis/adapter.md``. ``parity/scripts/run_default_parity.py``
appends that file to ``parity/REPORT.md`` under its own heading.

The comparison is bit for bit: event IDs and their order, years, rates,
draw IDs, the location table, and the ``index`` (wind, m/s) and ``loss``
(USD) matrices as IEEE 754 binary64 bytes. Where a matrix is not
bit-identical, the section gives the largest relative deviation against the
issue's tolerance (:data:`RTOL`, 1e-6). It also checks both EventSets'
matrices against the pinned digest file
(``tests/data/thesis_eventset_digest.json``, :func:`digests`), which the CI
test ``tests/test_thesis_parity.py`` checks against the fixture without IRIS.

Run from ``packages/climada`` in the pixi env, with the merged IRIS
catalogue (``pixi run iris``)::

    pixi run python scripts/thesis_adapter_parity.py
    pixi run python scripts/thesis_adapter_parity.py \
        --catalogue /path/to/IRIS_NA_10000Y_merged.txt

It exits with status 1 when a field differs beyond the tolerance. To rewrite
the digest file from the fixture (only when the fixture itself changes)::

    pixi run python scripts/thesis_adapter_parity.py --write-digest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, Final

import numpy as np
from numpy.typing import NDArray

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design_climada.config import PipelineConfig, load_config
from parametric_insurance_design_climada.pipeline import (
    BUILD_RECORD_NAME,
    PipelineResult,
    build_eventset,
)

PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parents[1]
REPO: Final[Path] = PACKAGE_DIR.parents[1]
CONFIG: Final[Path] = PACKAGE_DIR / "configs" / "thesis.yaml"
FIXTURE: Final[Path] = REPO / "parity" / "tests" / "data" / "thesis_eventset"
DIGEST: Final[Path] = PACKAGE_DIR / "tests" / "data" / "thesis_eventset_digest.json"
OUT: Final[Path] = REPO / "parity" / "analysis" / "adapter.md"

RTOL: Final[float] = 1e-6
"""Relative tolerance of the issue (MAR-20) for wind and loss."""
_RTOL_TEXT: Final[str] = "1e-6"

THESIS_CLIMADA: Final[str] = "6.0.1"
"""CLIMADA version of the thesis run: ``climada=6.0.1`` in the thesis
``climada_env.yml`` (and the fixture's index definition)."""

SOURCE_CSV_SHA256: Final[str] = (
    "8513f5fefdcf6686207df575e6a89d576e5ed935f71b652b4045229caf23ff68"
)
"""SHA256 of the thesis event-loss CSV the fixture was converted from."""

CREATED_AT: Final[datetime] = datetime(2026, 10, 25, tzinfo=UTC)
"""Fixed provenance timestamp of the build (excluded from the content hash)."""

DIGEST_ENCODING: Final[str] = (
    "SHA256 of: event_id, the UTF-8 strings joined by newlines; year and "
    "draw_id, int64 little-endian; rate, index and loss, IEEE 754 binary64 "
    "little-endian, row-major (C order), bytes as stored (no -0.0 "
    "normalisation)"
)


# --------------------------------------------------------------------------
# Digests
# --------------------------------------------------------------------------


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def float_bytes(values: object) -> bytes:
    """Return the binary64 little-endian, C-order bytes of ``values``."""
    return np.ascontiguousarray(np.asarray(values, dtype="<f8")).tobytes()


def int_bytes(values: object) -> bytes:
    """Return the int64 little-endian bytes of ``values``."""
    return np.ascontiguousarray(np.asarray(values, dtype="<i8")).tobytes()


def digests(eventset: EventSet) -> dict[str, Any]:
    """Return the shape, location IDs and field digests of an EventSet.

    Parameters
    ----------
    eventset : EventSet
        The EventSet.

    Returns
    -------
    dict
        ``shape``, ``location_ids`` and ``sha256`` (one hex digest per field:
        ``event_id``, ``year``, ``rate``, ``draw_id``, ``index``, ``loss``),
        encoded as :data:`DIGEST_ENCODING` states.
    """
    events = eventset.events
    event_ids = "\n".join(str(e) for e in events["event_id"]).encode("utf-8")
    return {
        "shape": [eventset.n_rows, eventset.n_locations],
        "location_ids": eventset.location_ids,
        "sha256": {
            "event_id": _sha256(event_ids),
            "year": _sha256(int_bytes(events["year"])),
            "rate": _sha256(float_bytes(events["rate"])),
            "draw_id": _sha256(int_bytes(events["draw_id"])),
            "index": _sha256(float_bytes(eventset.index)),
            "loss": _sha256(float_bytes(eventset.loss)),
        },
    }


def digest_record(fixture: EventSet) -> dict[str, Any]:
    """Return the digest file's content for the parity fixture."""
    return {
        "description": (
            "Pinned digests of the thesis parity fixture "
            "(parity/tests/data/thesis_eventset), the thesis event-loss table "
            "that the CLIMADA adapter must regenerate bit for bit (MAR-20). "
            "Written by packages/climada/scripts/thesis_adapter_parity.py "
            "--write-digest."
        ),
        "fixture": "parity/tests/data/thesis_eventset",
        "source_csv_sha256": SOURCE_CSV_SHA256,
        "encoding": DIGEST_ENCODING,
        **digests(fixture),
    }


def load_digest(path: Path = DIGEST) -> dict[str, Any]:
    """Read the pinned digest file."""
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldCheck:
    """One field of the adapter's EventSet against the fixture.

    Attributes
    ----------
    name : str
        Field.
    identical : bool
        Bit-identical, including order.
    within_tolerance : bool
        Identical, or (matrices only) within :data:`RTOL` relative.
    detail : str
        What was compared and, if not identical, how it differs.
    """

    name: str
    identical: bool
    within_tolerance: bool
    detail: str


def _list_check(
    name: str, ours: Sequence[object], theirs: Sequence[object]
) -> FieldCheck:
    ours, theirs = list(ours), list(theirs)
    if ours == theirs:
        return FieldCheck(name, True, True, f"{len(ours):,} values, same order")
    if sorted(map(str, ours)) == sorted(map(str, theirs)):
        detail = "same values, different order"
    else:
        only_ours = len(set(map(str, ours)) - set(map(str, theirs)))
        only_theirs = len(set(map(str, theirs)) - set(map(str, ours)))
        detail = (
            f"{len(ours):,} vs {len(theirs):,} values; {only_ours:,} only in the "
            f"adapter's, {only_theirs:,} only in the fixture's"
        )
    return FieldCheck(name, False, False, detail)


def _bytes_check(name: str, ours: bytes, theirs: bytes, n: int) -> FieldCheck:
    if ours == theirs:
        return FieldCheck(name, True, True, f"{n:,} values, bit-identical")
    return FieldCheck(name, False, False, f"{n:,} values, not bit-identical")


def matrix_check(
    name: str,
    ours: NDArray[np.float64],
    theirs: NDArray[np.float64],
    rtol: float = RTOL,
) -> FieldCheck:
    """Compare two matrices bit for bit, then within ``rtol`` relative.

    Parameters
    ----------
    name : str
        Field name.
    ours, theirs : numpy.ndarray
        Adapter and fixture matrices.
    rtol : float, default RTOL
        Relative tolerance, against the fixture's value. A cell that is zero
        in one matrix and not in the other is outside any tolerance.

    Returns
    -------
    FieldCheck
        The result.
    """
    if ours.shape != theirs.shape:
        return FieldCheck(
            name, False, False, f"shape {ours.shape} vs fixture {theirs.shape}"
        )
    n = int(theirs.size)
    if float_bytes(ours) == float_bytes(theirs):
        return FieldCheck(name, True, True, f"{n:,} cells, bit-identical")
    diff = ours != theirs
    zero_mismatch = int(((ours == 0) != (theirs == 0)).sum())
    both = (theirs != 0) & (ours != 0)
    rel = np.abs(ours[both] - theirs[both]) / np.abs(theirs[both])
    max_rel = float(rel.max()) if rel.size else 0.0
    within = zero_mismatch == 0 and max_rel <= rtol
    return FieldCheck(
        name,
        False,
        within,
        f"{n:,} cells, {int(diff.sum()):,} differ; largest relative deviation "
        f"{max_rel:.2e}; {zero_mismatch:,} cells zero in only one of the two",
    )


def compare(ours: EventSet, fixture: EventSet) -> list[FieldCheck]:
    """Compare the adapter's EventSet with the fixture, field by field.

    Parameters
    ----------
    ours : EventSet
        Built by the adapter.
    fixture : EventSet
        The parity fixture.

    Returns
    -------
    list of FieldCheck
        Event IDs (with order), years, rates, draw IDs, scenario IDs, the
        location table, ``index`` and ``loss``.
    """
    ev, fx = ours.events, fixture.events
    checks = [
        _list_check(
            "Event IDs and order", ev["event_id"].tolist(), fx["event_id"].tolist()
        ),
        _bytes_check("Years", int_bytes(ev["year"]), int_bytes(fx["year"]), len(fx)),
        _bytes_check(
            "Rates", float_bytes(ev["rate"]), float_bytes(fx["rate"]), len(fx)
        ),
        _bytes_check(
            "Draw IDs", int_bytes(ev["draw_id"]), int_bytes(fx["draw_id"]), len(fx)
        ),
        _list_check(
            "Scenario IDs", ev["scenario_id"].tolist(), fx["scenario_id"].tolist()
        ),
    ]
    loc_ours, loc_fx = ours.locations, fixture.locations
    same_locations = loc_ours.equals(loc_fx) and list(loc_ours.columns) == list(
        loc_fx.columns
    )
    columns = ", ".join(f"`{c}`" for c in loc_fx.columns)
    checks.append(
        FieldCheck(
            "Locations",
            same_locations,
            same_locations,
            f"{len(loc_fx)} rows, columns {columns}: "
            + ("identical" if same_locations else "differ"),
        )
    )
    checks.append(matrix_check("Index (wind, m/s)", ours.index, fixture.index))
    checks.append(matrix_check("Loss (USD)", ours.loss, fixture.loss))
    return checks


def metadata_differences(ours: EventSet, fixture: EventSet) -> list[str]:
    """Return the top-level metadata fields that differ (dotted for nested)."""
    a, b = ours.metadata.to_dict(), fixture.metadata.to_dict()
    out: list[str] = []
    for key in sorted(set(a) | set(b)):
        if a.get(key) == b.get(key):
            continue
        sub_a, sub_b = a.get(key), b.get(key)
        if isinstance(sub_a, dict) and isinstance(sub_b, dict):
            out += [
                f"{key}.{k}"
                for k in sorted(set(sub_a) | set(sub_b))
                if sub_a.get(k) != sub_b.get(k)
            ]
        else:
            out.append(key)
    return out


# --------------------------------------------------------------------------
# Build and render
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class AdapterParity:
    """Everything the adapter section reports."""

    config: PipelineConfig
    result: PipelineResult
    fixture: EventSet
    checks: list[FieldCheck]
    digest_file: dict[str, Any]

    @property
    def ours(self) -> EventSet:
        """The adapter's EventSet."""
        return self.result.eventset

    @property
    def bit_identical(self) -> bool:
        """Every field bit-identical."""
        return all(c.identical for c in self.checks)

    @property
    def within_tolerance(self) -> bool:
        """Every field identical or within :data:`RTOL`."""
        return all(c.within_tolerance for c in self.checks)

    @property
    def build_record(self) -> dict[str, Any]:
        """Parameters of the adapter's build record."""
        for record in self.ours.metadata.transforms:
            if record.name == BUILD_RECORD_NAME:
                return dict(record.parameters)
        raise KeyError(BUILD_RECORD_NAME)


def run(config_path: Path = CONFIG, catalogue: Path | None = None) -> AdapterParity:
    """Build the thesis EventSet with the adapter and compare it.

    Parameters
    ----------
    config_path : pathlib.Path, default CONFIG
        Pipeline config (``configs/thesis.yaml``).
    catalogue : pathlib.Path, optional
        Merged IRIS catalogue; overrides the config's.

    Returns
    -------
    AdapterParity
        The build and the comparison.
    """
    config = load_config(config_path)
    if catalogue is not None:
        config = config.model_copy(update={"catalogue": catalogue.resolve()})
    result = build_eventset(config, created_at=CREATED_AT)
    fixture = EventSet.from_parquet(FIXTURE)
    return AdapterParity(
        config=config,
        result=result,
        fixture=fixture,
        checks=compare(result.eventset, fixture),
        digest_file=load_digest(),
    )


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|")


def _row(*cells: object) -> str:
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def _verdict(check: FieldCheck) -> str:
    if check.identical:
        return "identical"
    return f"within {_RTOL_TEXT}" if check.within_tolerance else "**differs**"


def render(parity: AdapterParity) -> str:
    """Render the adapter section of the parity report.

    Parameters
    ----------
    parity : AdapterParity
        From :func:`run`.

    Returns
    -------
    str
        Markdown, starting with a level-2 heading.
    """
    ours, fixture = parity.ours, parity.fixture
    record = parity.build_record
    catalogue = record["catalogue"]
    pinned = parity.digest_file["sha256"]
    ours_digests = digests(ours)["sha256"]
    fixture_digests = digests(fixture)["sha256"]
    wind = parity.config.wind
    n_zero = int(((ours.index == 0) & (ours.loss == 0)).all(axis=1).sum())
    if parity.bit_identical:
        headline = (
            "**Result: bit-identical.** The adapter regenerates the thesis input: "
            "the same event IDs in the same order, the same years, rates and "
            "locations, and `index` and `loss` bit-identical in all "
            f"{ours.index.size + ours.loss.size:,} cells. Only the metadata "
            "differs (below)."
        )
    elif parity.within_tolerance:
        headline = (
            f"**Result: within {_RTOL_TEXT} relative, not bit-identical.** See the "
            "table for the fields that differ."
        )
    else:
        headline = (
            f"**Result: differs beyond {_RTOL_TEXT} relative.** See the table for "
            "the fields that differ."
        )
    lines = [
        "## Adapter: the CLIMADA pipeline regenerates the thesis event-loss table",
        "",
        "Generated by `packages/climada/scripts/thesis_adapter_parity.py` (MAR-20) "
        "in the CLIMADA pixi env. The adapter "
        "(`parametric_insurance_design_climada.pipeline.build_eventset`, the port "
        "of the thesis `src/CLIMADA/engine.py`, MAR-73) builds the thesis "
        "portfolio from `packages/climada/configs/thesis.yaml`: the 9 Miami "
        "assets on the IRIS North Atlantic 10,000-year catalogue. Its EventSet is "
        "compared with the parity fixture `parity/tests/data/thesis_eventset`, "
        "the thesis event-loss table (`data/output/climada_transformed_loss_data"
        f".csv`, SHA256 `{SOURCE_CSV_SHA256}`, MAR-9), not with the thesis "
        "`engine.py` outputs, which go to other paths (known issue C4). Matrices "
        "are compared as IEEE 754 binary64 bytes; the issue's tolerance is "
        f"{_RTOL_TEXT} relative.",
        "",
        headline,
        "",
        _row("Field", "Compared", "Result"),
        "|---|---|---|",
    ]
    lines += [_row(c.name, c.detail, _verdict(c)) for c in parity.checks]
    lines += [
        "",
        "### Inputs and build",
        "",
        f"- Catalogue: `{catalogue['file']}`, SHA256 `{catalogue['sha256']}`, "
        f"{catalogue['n_storms']:,} storms, {catalogue['n_track_points']:,} track "
        "points.",
        f"- Storms within {record['proximity_km']:g} km of an asset: "
        f"{record['n_storms_within_radius']:,}; skipped (fewer than two track "
        f"points): {len(record['skipped_storms'])}; rows: {ours.n_rows:,}, of "
        f"which {n_zero:,} are zero at every asset (kept, as in the fixture).",
        f"- Wind: model {wind.model}, intensity threshold {wind.intensity_thres:g} "
        "m/s (winds below it are stored as 0, as in the fixture), "
        f"`max_dist_eye_km` {wind.max_dist_eye_km:g}, `max_latitude` "
        f"{wind.max_latitude:g}, `max_dist_inland_km` "
        f"{'off' if wind.max_dist_inland_km is None else wind.max_dist_inland_km}. "
        "Impact function: Emanuel (2011) USA "
        f"(`v_thresh` {parity.config.impact_function.v_thresh:g}, `v_half` "
        f"{parity.config.impact_function.v_half:g} m/s).",
        f"- Runtime: {parity.result.seconds:.0f} s on {platform.system()} "
        f"{platform.machine()} (Python {platform.python_version()}, numpy "
        f"{np.__version__}).",
        "",
        "### Differences in setup, with the same result",
        "",
        f"- **CLIMADA version.** The thesis ran CLIMADA {THESIS_CLIMADA} "
        "(`climada_env.yml` of the thesis repository); the adapter runs "
        f"CLIMADA {record['climada_version']} (`packages/climada/pixi.toml`). "
        "The comparison above holds across the two versions.",
        "- **Distance to the coast.** The thesis used CLIMADA's default inland "
        "cut-off (`max_dist_inland_km` 1000 km). The adapter switches it off by "
        "default (`wind.max_dist_inland_km: null` in `configs/thesis.yaml`), "
        "because CLIMADA's default would download a 300 MB distance-to-coast "
        "raster outside the checksummed downloads. The nine Miami assets lie "
        "within a few tens of kilometres of the coast, far inside 1000 km, so "
        "the cut-off removes no wind there; the comparison above confirms it "
        "for this portfolio.",
        "",
        "### Metadata",
        "",
        "Only descriptive text and provenance differ: the fixture describes "
        "and records the thesis CSV it was converted from, the adapter its own "
        "build (CLIMADA version, catalogue checksum, parameters). Metadata "
        "fields that differ: "
        + ", ".join(f"`{k}`" for k in metadata_differences(ours, fixture))
        + ". The content hashes (`EventSet.content_hash`, which covers the "
        "metadata) therefore differ:",
        "",
        f"- fixture: `{fixture.content_hash()}`",
        f"- adapter: `{ours.content_hash()}`",
        "",
        "### Digests",
        "",
        "SHA256 of each field (encoding in "
        "`packages/climada/tests/data/thesis_eventset_digest.json`). The digest "
        "file pins the fixture's values; CI checks the committed fixture against "
        "it without IRIS (`packages/climada/tests/test_thesis_parity.py`), and "
        "the same test rebuilds the EventSet and compares it bit for bit "
        "wherever the IRIS catalogue is present.",
        "",
        _row("Field", "Pinned (digest file)", "Fixture", "Adapter"),
        "|---|---|---|---|",
    ]
    for key, value in pinned.items():
        lines.append(
            _row(
                f"`{key}`",
                f"`{value[:16]}…`",
                "same" if fixture_digests[key] == value else "**differs**",
                "same" if ours_digests[key] == value else "**differs**",
            )
        )
    lines += [
        "",
        "To reproduce, from `packages/climada`: `pixi run iris`, then "
        "`pixi run python scripts/thesis_adapter_parity.py`; then regenerate "
        "this report with `uv run python parity/scripts/run_default_parity.py "
        "--check` from the repository root.",
    ]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Build, compare and write the adapter section.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments (default: ``sys.argv[1:]``).

    Returns
    -------
    int
        0 if every field is within the tolerance (and the matrices match the
        pinned digests), 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Build the thesis EventSet with the CLIMADA adapter, compare it with "
            "the parity fixture and write the adapter section of the report."
        )
    )
    parser.add_argument("--config", type=Path, default=CONFIG)
    parser.add_argument(
        "--catalogue", type=Path, help="merged IRIS catalogue (overrides the config)"
    )
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--write-digest",
        action="store_true",
        help=f"rewrite {DIGEST.name} from the fixture and exit (no build)",
    )
    args = parser.parse_args(argv)

    if args.write_digest:
        record = digest_record(EventSet.from_parquet(FIXTURE))
        DIGEST.parent.mkdir(parents=True, exist_ok=True)
        DIGEST.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {DIGEST}")
        return 0

    parity = run(args.config, args.catalogue)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(parity), encoding="utf-8")
    fixture_pinned = digests(parity.fixture)["sha256"] == parity.digest_file["sha256"]
    for check in parity.checks:
        print(f"{check.name}: {_verdict(check)} ({check.detail})")
    if not fixture_pinned:
        print(f"the fixture does not match {DIGEST.name}", file=sys.stderr)
    print(f"climada {version('climada')}; wrote {args.out}")
    return 0 if parity.within_tolerance and fixture_pinned else 1


if __name__ == "__main__":
    sys.exit(main())
