"""K-12 (MAR-311), question 8: ``climada_petals.engine.cat_bonds`` next to our units.

On small synthetic ``Hazard`` and ``Exposures`` objects (nothing is downloaded)
it checks (a) whether ``Subareas`` can serve as a source of units, and (b)
whether ``calc_payout`` equals a linear payout with the same parameters. Needs
``climada_petals`` 6.2.0 or newer::

    python packages/climada/scripts/k12_cat_bonds.py --out cat_bonds.json
"""

from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
from typing import Any, Final

import geopandas as gpd
import numpy as np
import pandas as pd
import scipy.sparse as sp
from climada.entity import Exposures
from climada.hazard import Centroids, Hazard
from numpy.typing import NDArray
from shapely.geometry import box

SEED: Final[int] = 311


def grid_exposures(n: int = 12) -> Exposures:
    """Return ``n * n`` exposure points on a 0.1 degree grid, value 1 each."""
    lats, lons = np.meshgrid(
        18.0 + np.arange(n) * 0.1, -77.0 + np.arange(n) * 0.1, indexing="ij"
    )
    exp = Exposures(lat=lats.ravel(), lon=lons.ravel(), value=np.ones(n * n))
    exp.gdf["impf_TC"] = 1
    return exp


def small_hazard(exp: Exposures, n_events: int = 20) -> Hazard:
    """Return a hazard with its centroids on the exposure points."""
    rng = np.random.default_rng(SEED)
    n_centroids = exp.gdf.shape[0]
    return Hazard(
        haz_type="TC",
        intensity=sp.csr_matrix(rng.uniform(0.0, 60.0, (n_events, n_centroids))),
        fraction=sp.csr_matrix(np.ones((n_events, n_centroids))),
        centroids=Centroids(
            lat=np.asarray(exp.latitude, dtype=float),
            lon=np.asarray(exp.longitude, dtype=float),
        ),
        event_id=np.arange(1, n_events + 1),
        event_name=[f"e{i}" for i in range(n_events)],
        date=np.full(n_events, 730000),
        frequency=np.full(n_events, 1.0 / 100.0),
        frequency_unit="1/year",
        units="m/s",
    )


def expect_error(call: Any) -> dict[str, Any]:  # noqa: ANN401
    """Call and report the outcome."""
    try:
        value = call()
    except Exception as error:  # each type is reported, nothing hidden
        return {"raised": type(error).__name__, "message": str(error)[:300]}
    return {"raised": None, "value": value}


def subareas_checks(subareas_module: Any) -> dict[str, Any]:  # noqa: ANN401
    """Check what ``Subareas`` gives as a source of units."""
    subareas = subareas_module.Subareas
    exp = grid_exposures()
    hazard = small_hazard(exp)
    out: dict[str, Any] = {}

    grid = subareas.from_resolution(hazard, None, exp, resolution=0.3)
    gdf = grid.subareas_gdf
    out["from_resolution"] = {
        "n_subareas": int(grid.count_subareas()),
        "columns": sorted(gdf.columns.tolist()),
        "letters_first": gdf["subarea_letter"].tolist()[:3],
    }
    points = exp.gdf[["geometry"]].sjoin(
        gdf[["geometry", "subarea_letter"]], how="left", predicate="intersects"
    )
    per_point = points.groupby(points.index).size()
    points_per_area = points.groupby("subarea_letter").size()
    out["from_resolution"]["points_in_more_than_one_subarea"] = int(
        (per_point > 1).sum()
    )
    out["from_resolution"]["points_in_none"] = int(
        points["subarea_letter"].isna().sum()
    )
    out["from_resolution"]["points_per_subarea_min_max"] = [
        int(points_per_area.min()),
        int(points_per_area.max()),
    ]

    many = grid_exposures(n=30)
    many_hazard = small_hazard(many)
    grid_many = subareas.from_resolution(many_hazard, None, many, resolution=0.1)
    letters = grid_many.subareas_gdf["subarea_letter"].tolist()
    out["from_resolution_many_cells"] = {
        "n_subareas": len(letters),
        "unique_letters": len(set(letters)),
        "letter_27_and_last": [letters[26], letters[-1]] if len(letters) > 26 else None,
    }

    outside = gpd.GeoDataFrame(geometry=[box(0.0, 0.0, 0.1, 0.1)], crs="EPSG:4326")
    out["from_geodataframe_outside_the_exposure"] = expect_error(
        lambda: subareas.from_geodataframe(hazard, None, exp, outside).count_subareas()
    )
    partial = gpd.GeoDataFrame(
        geometry=[box(-77.05, 17.95, -76.5, 18.5)], crs="EPSG:4326"
    )
    out["from_geodataframe_part_of_the_exposure"] = expect_error(
        lambda: subareas.from_geodataframe(hazard, None, exp, partial).count_subareas()
    )
    out["from_geodataframe_multipolygon"] = expect_error(
        lambda: subareas.from_geodataframe(
            hazard,
            None,
            exp,
            gpd.GeoDataFrame(
                geometry=[
                    box(-77.05, 17.95, -76.5, 18.5).union(box(-76.0, 19.0, -75.5, 19.5))
                ],
                crs="EPSG:4326",
            ),
        ).count_subareas()
    )

    one = Exposures(lat=[18.0], lon=[-77.0], value=[1.0])
    out["from_resolution_one_point"] = expect_error(
        lambda: subareas.from_resolution(
            small_hazard(one), None, one, resolution=0.3
        ).count_subareas()
    )
    three = Exposures(
        lat=[18.0, 18.5, 19.0], lon=[-77.0, -76.5, -76.0], value=[1.0, 1.0, 1.0]
    )
    out["from_resolution_three_scattered_points"] = expect_error(
        lambda: subareas.from_resolution(
            small_hazard(three), None, three, resolution=0.3
        ).count_subareas()
    )
    return out


def linear_payout(
    intensity: NDArray[np.float64], low: float, high: float, top: float
) -> NDArray[np.float64]:
    """Return a payout rising linearly from ``low`` to ``high``, capped at ``top``."""
    return top * np.clip((intensity - low) / (high - low), 0.0, 1.0)


def payout_checks(calculations_module: Any) -> dict[str, Any]:  # noqa: ANN401
    """Compare ``calc_payout`` with a linear payout with the same parameters."""
    calc_payout = calculations_module.calc_payout
    rng = np.random.default_rng(SEED)
    low, high, top = 30.0, 60.0, 1.0e6
    out: dict[str, Any] = {"low": low, "high": high, "max_pay": top}

    intensity = np.concatenate(
        [rng.uniform(0.0, 90.0, 100_000), np.array([0.0, low, high, 90.0])]
    )
    frame = pd.DataFrame({"intensity": intensity, "year": 2000})
    theirs = np.asarray(calc_payout(low, high, frame, top), dtype=float)
    ours = linear_payout(intensity, low, high, top)
    out["float_input"] = {
        "max_abs_difference": float(np.max(np.abs(theirs - ours))),
        "at_low_equals_zero": float(theirs[-3]) == 0.0,
        "at_high_equals_max_pay": float(theirs[-2]) == top,
    }

    integers = pd.DataFrame({"category": np.array([0, 1, 2, 3, 4, 5]), "year": 2000})
    payout_int = calc_payout(1.0, 4.0, integers, 1_000_000.5)
    out["integer_index"] = {
        "input_dtype": str(integers["category"].dtype),
        "payout_dtype": str(np.asarray(payout_int).dtype),
        "calc_payout": np.asarray(payout_int).tolist(),
        "linear_payout": linear_payout(
            np.array([0, 1, 2, 3, 4, 5], dtype=float), 1.0, 4.0, 1_000_000.5
        ).tolist(),
    }

    out["low_above_high"] = {
        "calc_payout": np.asarray(
            calc_payout(60.0, 30.0, frame.iloc[:5], top), dtype=float
        ).tolist(),
        "intensity": intensity[:5].tolist(),
    }
    return out


def main() -> None:
    """Run the checks and write the observations as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    subareas_module = importlib.import_module(
        "climada_petals.engine.cat_bonds.subareas"
    )
    calculations_module = importlib.import_module(
        "climada_petals.engine.cat_bonds.subarea_calculations"
    )
    facts = {
        "subareas": subareas_checks(subareas_module),
        "payout": payout_checks(calculations_module),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(facts, indent=1, default=str) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
