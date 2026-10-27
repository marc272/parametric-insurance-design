"""Estimate the dense events x locations grid of an IRIS EventSet (MAR-113).

The pipeline (``pipeline.build_eventset``) keeps one row per storm whose
track passes within ``proximity_km`` of any location, times ``n_draws``
vulnerability draws, and stores a dense ``(n_rows, n_locations)`` index and
loss matrix (SPEC §5). This script counts those storms for a set of
locations, without running CLIMADA, so that the size can be planned:

* storms within ``proximity_km`` (500 km, the thesis value) of any location:
  the rows the pipeline would write (minus storms with a single track point,
  which it skips and lists);
* storms within ``max_dist_eye_km`` (300 km, the wind config) of any
  location: an upper bound on the rows that can have non-zero wind;
* optionally the same counts over every LitPop cell (``cells.parquet``), the
  hazard grid if the loss were computed per cell.

From ``packages/climada``::

    pixi run python scripts/estimate_florida_grid.py \
        --catalogue ../../data/iris/transformed/IRIS_NA_10000Y_merged.txt \
        --locations ../../data/litpop-florida/locations/locations.yaml \
        --cells ../../data/litpop-florida/locations/cells.parquet \
        --compare-eventset ../../parity/tests/data/thesis_eventset
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

from parametric_insurance_design_climada import tracks
from parametric_insurance_design_climada.config import LocationsConfig
from parametric_insurance_design_climada.pipeline import read_locations

EARTH_RADIUS_KM = 6371.0


def _counts(
    catalogue: pd.DataFrame, lats: Sequence[float], lons: Sequence[float], radius: float
) -> dict[str, int]:
    near = tracks.storms_near_locations(catalogue, lats, lons, radius)
    points = catalogue[catalogue["event_id"].isin(near)].groupby("event_id").size()
    return {"storms": len(near), "single_point_storms": int((points < 2).sum())}


def _storms_near_points(
    catalogue: pd.DataFrame, lats: np.ndarray, lons: np.ndarray, radius: float
) -> int:
    """Storms with a track point within ``radius`` km of any point (BallTree)."""
    tree = BallTree(np.radians(np.column_stack([lats, lons])), metric="haversine")
    track = np.radians(catalogue[["lat", "lon"]].to_numpy(dtype=np.float64))
    dist, _ = tree.query(track, k=1)
    close = dist[:, 0] * EARTH_RADIUS_KM <= radius
    return int(catalogue.loc[close, "event_id"].nunique())


def main(argv: Sequence[str] | None = None) -> int:
    """Print the counts as JSON.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(
        description="Estimate the dense events x locations grid of an IRIS EventSet."
    )
    parser.add_argument("--catalogue", type=Path, required=True)
    parser.add_argument("--locations", type=Path, required=True, help="YAML")
    parser.add_argument("--cells", type=Path, default=None, help="cells.parquet")
    parser.add_argument("--compare-eventset", type=Path, default=None)
    parser.add_argument("--proximity-km", type=float, default=500.0)
    parser.add_argument("--max-dist-eye-km", type=float, default=300.0)
    parser.add_argument("--n-draws", type=int, nargs="+", default=[1, 10])
    args = parser.parse_args(argv)

    catalogue = tracks.read_iris_catalogue(args.catalogue)
    sources = {"florida": LocationsConfig(yaml=args.locations)}
    if args.compare_eventset is not None:
        sources["compare"] = LocationsConfig(eventset=args.compare_eventset)
    out: dict[str, object] = {
        "catalogue_storms": int(catalogue["event_id"].nunique()),
        "catalogue_track_points": len(catalogue),
    }
    for key, source in sources.items():
        locations = read_locations(source)
        lats, lons = locations["lat"].tolist(), locations["lon"].tolist()
        n_loc = len(locations)
        prox = _counts(catalogue, lats, lons, args.proximity_km)
        eye = _counts(catalogue, lats, lons, args.max_dist_eye_km)
        rows = prox["storms"] - prox["single_point_storms"]
        out[key] = {
            "n_locations": n_loc,
            f"storms_within_{args.proximity_km:g}km": prox,
            f"storms_within_{args.max_dist_eye_km:g}km": eye,
            "grid": {
                str(n): {
                    "rows": rows * n,
                    "cells": rows * n * n_loc,
                    "dense_index_plus_loss_MiB": round(
                        2 * rows * n * n_loc * 8 / 2**20, 1
                    ),
                }
                for n in args.n_draws
            },
        }
    if args.cells is not None:
        cells = pd.read_parquet(args.cells)
        in_target = cells["location_id"].notna().to_numpy()
        lats = np.asarray(cells["lat"], dtype=np.float64)[in_target]
        lons = np.asarray(cells["lon"], dtype=np.float64)[in_target]
        out["florida_cells"] = {
            "n_cells": int(in_target.sum()),
            f"storms_within_{args.proximity_km:g}km": _storms_near_points(
                catalogue, lats, lons, args.proximity_km
            ),
            f"storms_within_{args.max_dist_eye_km:g}km": _storms_near_points(
                catalogue, lats, lons, args.max_dist_eye_km
            ),
        }
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
