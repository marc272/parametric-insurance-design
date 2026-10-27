r"""Build the basin lookup of the Eberenz et al. (2021) calibration events (MAR-132).

CLIMADA's ``tc_impf_cal_v01_EDR.csv`` lists each calibrated event by its
IBTrACS storm ID (``ibtracsID``) but not by its basin, and the ID encodes the
genesis date and position, not the basin. This script reads the basin from
IBTrACS itself and writes the pinned lookup
``src/parametric_insurance_design_climada/eberenz2021_edr_basins.csv`` that
:meth:`EberenzEdrPrior.from_climada
<parametric_insurance_design_climada.vulnerability.EberenzEdrPrior.from_climada>`
reads for its ``basins`` filter.

Rule, per unique ``ibtracsID``:

* ``basin`` is IBTrACS's ``basin`` variable ("current basin") at the storm's
  first observation, its genesis basin; ``basins_visited`` lists every basin
  along the track, in order.
* An ID that is in the IBTrACS file is used as is (``match = exact``).
* IBTrACS re-issues an ID when a storm's first position changes between
  versions, so some calibration IDs (from an older IBTrACS) are not in a
  newer file. Such an ID is matched to the storm of the same year whose
  genesis day-of-year is within ``MAX_DAY_GAP`` days of the ID's and whose
  track passes nearest to the ID's genesis point; the match must be within
  ``MAX_MATCH_DEG`` degrees (``match = genesis``, with the matched ``sid``,
  ``name`` and distance recorded). An ID without such a match, or a storm
  without a basin, raises: no event is dropped silently.

The IBTrACS file is the one CLIMADA downloads to ``~/climada/data/``
(``TCTracks.from_ibtracs_netcdf``), from NOAA NCEI
(https://www.ncei.noaa.gov/products/international-best-track-archive). Its
SHA256 and ``date_created`` go into the lookup's header. NCEI replaces the
file in place, so a later download has another checksum; a genesis basin
does not change between releases.

From ``packages/climada``::

    pixi run --locked python scripts/build_eberenz_basins.py \
        --ibtracs ~/climada/data/IBTrACS.ALL.v04r01.nc

Then update ``EBERENZ_BASINS_SHA256`` in ``vulnerability.py`` if the file
changed.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd
import xarray as xr

from parametric_insurance_design_climada.vulnerability import (
    EBERENZ_BASINS_FILE,
    EBERENZ_EDR_FILE,
    IBTRACS_BASINS,
    load_eberenz_edr,
)

#: Largest gap (days) between an unmatched ID's genesis day and a candidate's.
MAX_DAY_GAP: Final[int] = 3
#: Largest distance (degrees, longitude scaled by cos(lat)) between an
#: unmatched ID's genesis point and the matched storm's track.
MAX_MATCH_DEG: Final[float] = 5.0

_OUT: Final[Path] = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "parametric_insurance_design_climada"
    / EBERENZ_BASINS_FILE
)


class BasinLookupError(RuntimeError):
    """An event's basin cannot be determined."""


def parse_sid(sid: str) -> tuple[int, int, float, float]:
    """Return year, day of year, latitude and longitude (0-360) of an IBTrACS ID.

    Parameters
    ----------
    sid : str
        A 13-character ID like ``1982324N10193``: year, day of year,
        hemisphere, integer latitude and integer longitude east.

    Returns
    -------
    tuple of int, int, float, float
        Year, day of year, signed latitude and longitude east in degrees.

    Raises
    ------
    BasinLookupError
        If ``sid`` is not of that form.
    """
    if len(sid) != 13 or sid[7] not in "NS" or not (sid[:7] + sid[8:]).isdigit():
        raise BasinLookupError(f"not an IBTrACS storm ID: {sid!r}")
    lat = float(sid[8:10]) * (1 if sid[7] == "N" else -1)
    return int(sid[:4]), int(sid[4:7]), lat, float(sid[10:13])


def _track_basins(row: np.ndarray) -> list[str]:
    """Return the non-empty basin codes of one storm, in track order."""
    return [b.decode() if isinstance(b, bytes) else str(b) for b in row if b]


def build_lookup(calibration: pd.DataFrame, ibtracs: xr.Dataset) -> pd.DataFrame:
    """Return the basin of every unique ``ibtracsID`` of the calibration.

    Parameters
    ----------
    calibration : pandas.DataFrame
        The calibration table, with column ``ibtracsID``.
    ibtracs : xarray.Dataset
        An IBTrACS v04 file, with ``sid``, ``name``, ``basin``, ``lat`` and
        ``lon`` per storm.

    Returns
    -------
    pandas.DataFrame
        Columns ``ibtracsID``, ``basin``, ``basins_visited``, ``match``,
        ``ibtracs_sid``, ``ibtracs_name`` and ``match_distance_deg``, sorted by
        ``ibtracsID``.

    Raises
    ------
    BasinLookupError
        If an ID has no match or a storm has an unknown or missing basin.
    """
    sids = np.char.decode(ibtracs["sid"].values.astype("S13")).astype(str)
    names = ibtracs["name"].values.astype(str)
    basins = ibtracs["basin"].values
    lats = ibtracs["lat"].values
    lons = ibtracs["lon"].values % 360
    position = {sid: i for i, sid in enumerate(sids)}
    rows = []
    for event in sorted(calibration["ibtracsID"].astype(str).unique()):
        if event in position:
            index, match, distance = position[event], "exact", 0.0
        else:
            year, day, lat, lon = parse_sid(event)
            best: tuple[float, int] | None = None
            for i, sid in enumerate(sids):
                if int(sid[:4]) != year or abs(int(sid[4:7]) - day) > MAX_DAY_GAP:
                    continue
                ok = ~np.isnan(lats[i])
                d_lon = (lons[i][ok] - lon + 180) % 360 - 180
                dist = float(
                    np.hypot(lats[i][ok] - lat, d_lon * np.cos(np.radians(lat))).min()
                )
                if best is None or dist < best[0]:
                    best = (dist, i)
            if best is None or best[0] > MAX_MATCH_DEG:
                raise BasinLookupError(
                    f"{event}: no IBTrACS storm within {MAX_DAY_GAP} days and "
                    f"{MAX_MATCH_DEG:g} degrees of its genesis"
                )
            distance, index = best
            match = "genesis"
        track = _track_basins(basins[index])
        if not track or not set(track) <= set(IBTRACS_BASINS):
            raise BasinLookupError(
                f"{event} (IBTrACS {sids[index]}): basins {track} are not all in "
                f"{list(IBTRACS_BASINS)}"
            )
        rows.append(
            {
                "ibtracsID": event,
                "basin": track[0],
                "basins_visited": ";".join(dict.fromkeys(track)),
                "match": match,
                "ibtracs_sid": sids[index],
                "ibtracs_name": names[index],
                "match_distance_deg": round(distance, 2),
            }
        )
    return pd.DataFrame(rows)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the lookup; return the exit code."""
    parser = argparse.ArgumentParser(
        description="Build the basin lookup of the Eberenz et al. (2021) events."
    )
    parser.add_argument("--ibtracs", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=_OUT)
    args = parser.parse_args(argv)
    raw = args.ibtracs.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    calibration, calibration_sha = load_eberenz_edr()
    with xr.open_dataset(args.ibtracs) as ibtracs:
        lookup = build_lookup(calibration, ibtracs)
        created = str(ibtracs.attrs.get("date_created", "unknown"))
        product = str(ibtracs.attrs.get("product_version", "unknown"))
    header = [
        "# Basin of each event in CLIMADA's tc_impf_cal_v01_EDR.csv "
        "(Eberenz et al. 2021), MAR-132.",
        f"# Calibration file: climada/data/system/{EBERENZ_EDR_FILE}, "
        f"SHA256 {calibration_sha}.",
        f"# Source: IBTrACS {product} (NOAA NCEI; Knapp et al. 2010, "
        "doi:10.1175/2009BAMS2755.1; data doi:10.25921/82ty-9e16), "
        f"file {args.ibtracs.name}, date_created {created}, SHA256 {digest}.",
        "# basin: IBTrACS 'basin' (current basin) at the storm's first "
        "observation (genesis basin); basins_visited: all basins along the "
        "track, in order.",
        "# match: exact = the ID is in the file; genesis = the ID is not, and "
        f"is matched to the storm of the same year with genesis within "
        f"{MAX_DAY_GAP} days whose track passes nearest to the ID's genesis "
        f"point (at most {MAX_MATCH_DEG:g} degrees; distance recorded).",
        "# Generated by packages/climada/scripts/build_eberenz_basins.py.",
    ]
    with args.out.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\n".join(header) + "\n")
        lookup.to_csv(handle, index=False, lineterminator="\n")
    print(
        f"wrote {args.out}: {len(lookup)} events, "
        f"{(lookup['match'] == 'genesis').sum()} matched by genesis; "
        f"SHA256 {hashlib.sha256(args.out.read_bytes()).hexdigest()}"
    )
    print(lookup["basin"].value_counts().to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
