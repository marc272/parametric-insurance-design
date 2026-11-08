"""K-12 (MAR-311), question 7: the zero-basis-risk trap.

With one exposure point, a centroid index and one impact function, the loss is
a deterministic function of the index. This script measures how far the
uncovered loss falls as the payout gets more steps, on synthetic ``TCTracks``,
``TropCyclone``, ``Exposures`` and ``Impact`` objects (nothing is downloaded),
and what happens with the set-ups that break the determinism:

``centroid``
    one point, the wind at its centroid, one Emanuel impact function
    (``v_half = 74.7``, ``v_thresh = 25.7``);
``cat_circle_category`` and ``cat_circle_wind``
    the same loss; the index is the Saffir-Simpson category, or the highest
    track wind, within 50 km of the point;
``unit_point_index`` and ``unit_mean_index``
    a unit of 25 points on a 0.1 degree grid; the index is the wind at the
    central point, or the mean wind of the 25 points, and the loss is the sum;
``unit_wide_point_index`` and ``unit_wide_mean_index``
    the same on a 0.5 degree grid;
``impf_draws``
    one point and the centroid wind, but every event's loss uses a ``v_half``
    drawn uniformly on 60 to 95 m/s (independently over events).

Setup of every number (the publication rule): one unit in the "individual"
scope; annual basis (one simulation year = one outcome); 6,000 synthetic
storms over 3,000 simulation years, frequency ``1/3000`` each; the first 2,100
years calibrate and the last 900 years are the out-of-sample test; pure premium
with budget 1.0; the objective is the expected uncovered loss. The step payout
is uniform on ``[25, 85)`` m/s for wind indices, and on categories 1 to 5 for
the category index. The storm set and all the draws are fixed by a seed.

The script gives observations only: which set-ups avoid the trap. Run it in
CLIMADA's environment::

    python packages/climada/scripts/k12_zero_basis.py --out zero_basis.json
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import numpy as np
import scipy.sparse as sp
import xarray as xr
from climada.engine import Impact, ImpactCalc
from climada.entity import Exposures, ImpactFuncSet, ImpfTropCyclone
from climada.hazard import Centroids, TCTracks, TropCyclone
from numpy.typing import NDArray
from scipy.stats import spearmanr

import petals_parametric as pm

SEED: Final[int] = 311
N_STORMS: Final[int] = 6_000
N_YEARS: Final[int] = 3_000
N_TRAIN: Final[int] = 2_100
SITE: Final[tuple[float, float]] = (25.76, -80.19)
VALUE: Final[float] = 1.0e9
STEPS: Final[tuple[int, ...]] = (5, 10, 20, 40, 80)
V_HALF: Final[float] = 74.7
V_THRESH: Final[float] = 25.7
V_HALF_DRAWS: Final[tuple[float, float]] = (60.0, 95.0)
BETA: Final[float] = 0.95


def straight_track(
    sid: str, lat: float, wind_kn: float, *, n_points: int = 13
) -> xr.Dataset:
    """Return a straight west-moving storm along one latitude, 3 h between points."""
    time = np.datetime64("2000-09-01T00:00") + np.arange(n_points) * np.timedelta64(
        3, "h"
    )
    return xr.Dataset(
        data_vars={
            "time_step": ("time", np.full(n_points, 3.0)),
            "radius_max_wind": ("time", np.full(n_points, 25.0)),
            "radius_oci": ("time", np.full(n_points, 200.0)),
            "max_sustained_wind": ("time", np.full(n_points, float(wind_kn))),
            "central_pressure": ("time", np.full(n_points, 950.0)),
            "environmental_pressure": ("time", np.full(n_points, 1013.0)),
            "basin": ("time", np.full(n_points, "NA")),
        },
        coords={
            "time": ("time", time),
            "lat": ("time", np.full(n_points, float(lat))),
            "lon": ("time", np.linspace(-77.0, -83.0, n_points)),
        },
        attrs={
            "max_sustained_wind_unit": "kn",
            "central_pressure_unit": "hPa",
            "name": sid,
            "sid": sid,
            "orig_event_flag": True,
            "data_provider": "synthetic",
            "id_no": 0,
            "category": 0,
        },
    )


def make_tracks(
    rng: np.random.Generator,
) -> tuple[TCTracks, NDArray[np.int64]]:
    """Return the storms and each storm's simulation year."""
    years = np.sort(rng.integers(0, N_YEARS, size=N_STORMS))
    lats = SITE[0] + rng.uniform(-1.5, 1.5, size=N_STORMS)
    winds = rng.uniform(40.0, 140.0, size=N_STORMS)
    return (
        TCTracks(
            [
                straight_track(f"S_{i}", float(lat), float(wind))
                for i, (lat, wind) in enumerate(zip(lats, winds, strict=True))
            ]
        ),
        years,
    )


def unit_points(step: float) -> list[tuple[float, float]]:
    """Return 25 points on a grid with the given spacing, centred on the site."""
    offsets = np.arange(-2, 3) * step
    return [
        (SITE[0] + float(dlat), SITE[1] + float(dlon))
        for dlat in offsets
        for dlon in offsets
    ]


def one_point_exposures() -> Exposures:
    """Return the single insured point."""
    exp = Exposures(lat=[SITE[0]], lon=[SITE[1]], value=[VALUE])
    exp.gdf["impf_TC"] = 1
    return exp


def array_index(
    values: NDArray[np.float64],
    loss: NDArray[np.float64],
    years: NDArray[np.int64],
) -> tuple[pm.ParametricIndex, Impact]:
    """Return an index and an ``Impact`` built from arrays (one unit)."""
    n_events = values.shape[0]
    frequency = np.full(n_events, 1.0 / N_YEARS)
    event_id = np.arange(1, n_events + 1)
    names = [f"S_{i}" for i in range(n_events)]
    coords = np.array([[SITE[0], SITE[1]]])
    index = pm.ParametricIndex(
        values=values,
        event_id=event_id,
        event_name=names,
        frequency=frequency,
        event_year=years,
        years=np.arange(N_YEARS),
        unit_id=("unit",),
        coords=coords,
        unit="m/s",
        definition="k12 synthetic",
    )
    impact = Impact(
        event_id=event_id,
        event_name=names,
        date=np.ones(n_events, dtype=int),
        frequency=frequency,
        coord_exp=coords,
        eai_exp=frequency @ loss,
        at_event=loss.sum(axis=1),
        aai_agg=float((frequency @ loss).sum()),
        imp_mat=sp.csr_matrix(loss),
        unit="USD",
    )
    return index, impact


def evaluate(
    index: pm.ParametricIndex,
    impact: Impact,
    payout: pm.StepPayout,
) -> dict[str, float]:
    """Calibrate on the training years and return the test metrics."""
    train, test = index.years[:N_TRAIN], index.years[N_TRAIN:]
    cover = pm.calibrate(
        index,
        impact,
        payout=payout,
        objective=pm.ExpectedUncovered(),
        basis="annual",
        scope="individual",
        budget=1.0,
        years=train,
    )
    metrics = pm.basis_risk(index, impact, cover, beta=BETA, years=test)
    row = metrics[metrics["level"] == "portfolio"].iloc[0]
    event_loss = np.asarray(impact.imp_mat.todense(), dtype=float).sum(axis=1)
    test_mask = np.isin(index.event_year, test)
    annual = np.zeros(test.size)
    np.add.at(annual, index.event_year[test_mask] - int(test[0]), event_loss[test_mask])
    var = float(np.quantile(annual, BETA))
    cvar_loss = float(annual[annual >= var].mean())
    cap = float(event_loss[np.isin(index.event_year, train)].max())
    problem = cover.problems[0]
    return {
        "e_uncovered_over_e_loss": float(
            row["expected_uncovered"] / row["expected_loss"]
        ),
        "cvar95_uncovered_over_cvar95_loss": float(row["cvar_uncovered"] / cvar_loss),
        "expected_loss_usd": float(row["expected_loss"]),
        "correlation": float(row["correlation"]),
        "payout_to_loss": float(row["payout_to_loss_ratio"]),
        "train_premium_over_expected_loss": float(
            problem.premium / problem.expected_loss
        ),
        "share_of_levels_at_the_cap": float(np.mean(cover.levels >= cap * (1 - 1e-9))),
    }


def wind_payouts(steps: Sequence[int]) -> list[pm.StepPayout]:
    """Return the step payouts on the wind index."""
    return [pm.StepPayout(attachment=25.0, limit=85.0, n_steps=n) for n in steps]


def rank_correlation(
    index: NDArray[np.float64], loss: NDArray[np.float64]
) -> dict[str, float]:
    """Return the Spearman correlation of index and loss over events with loss."""
    mask = loss.ravel() > 0
    result = spearmanr(index.ravel()[mask], loss.ravel()[mask])
    return {
        "spearman": float(result.statistic),
        "n_events_with_loss": int(mask.sum()),
    }


def mdr(wind: NDArray[np.float64], v_half: NDArray[np.float64] | float) -> NDArray:
    """Return Emanuel's mean damage ratio for the given wind and ``v_half``."""
    v = np.maximum(wind - V_THRESH, 0.0) / (np.asarray(v_half) - V_THRESH)
    return v**3 / (1.0 + v**3)


def run() -> dict[str, Any]:
    """Build the catalogue, run every set-up and return the observations."""
    rng = np.random.default_rng(SEED)
    tracks, years = make_tracks(rng)
    tracks.equal_timestep(time_step_h=1)
    narrow = unit_points(0.1)
    centre = 12  # position of the single site, the central point of the grid
    wide = [point for point in unit_points(0.5) if point != narrow[centre]]
    points = [*narrow, *wide]
    wide_columns = [centre, *range(len(narrow), len(points))]
    centroids = Centroids(
        lat=np.array([p[0] for p in points]), lon=np.array([p[1] for p in points])
    )
    hazard = TropCyclone.from_tracks(
        tracks, centroids=centroids, ignore_distance_to_coast=True
    )
    hazard.frequency = np.full(hazard.size, 1.0 / N_YEARS)
    wind = np.asarray(hazard.intensity.todense(), dtype=float)

    impf = ImpfTropCyclone.from_emanuel_usa(v_half=V_HALF, v_thresh=V_THRESH)
    impfset = ImpactFuncSet([impf])
    single = one_point_exposures()
    impact_single = ImpactCalc(single.copy(), impfset, hazard).impact(save_mat=True)
    loss_single = np.asarray(impact_single.imp_mat.todense(), dtype=float)
    wind_single = wind[:, [centre]]

    setups: dict[str, Any] = {}
    records: dict[str, Any] = {}

    def record(
        name: str, values: NDArray[np.float64], loss: NDArray[np.float64]
    ) -> None:
        index, impact = array_index(values, loss, years)
        setups[name] = {
            "rank_correlation": rank_correlation(values, loss),
            "by_steps": {
                str(payout.n_steps): evaluate(index, impact, payout)
                for payout in wind_payouts(STEPS)
            },
        }

    record("centroid", wind_single, loss_single)

    cat_exposures = one_point_exposures()
    for name, metric in (
        ("cat_circle_category", "category"),
        ("cat_circle_wind", "max_wind"),
    ):
        index_cat = pm.ParametricIndex.from_cat_in_circle(
            tracks,
            cat_exposures,
            hazard=hazard,
            radius_km=50.0,
            metric=metric,
            event_year=years,
            n_years=N_YEARS,
            first_year=0,
        )
        values = np.asarray(index_cat.values, dtype=float)
        impact_cat = array_index(wind_single, loss_single, years)[1]
        records[name] = rank_correlation(values, loss_single)
        if metric == "category":
            setups[name] = {
                "rank_correlation": records[name],
                "by_steps": {
                    "5 (categories 1 to 5)": evaluate(
                        index_cat, impact_cat, pm.StepPayout(1, 6, 5)
                    )
                },
            }
        else:
            setups[name] = {
                "rank_correlation": records[name],
                "by_steps": {
                    str(payout.n_steps): evaluate(index_cat, impact_cat, payout)
                    for payout in wind_payouts(STEPS)
                },
            }

    def unit_loss(grid_points: list[tuple[float, float]]) -> NDArray[np.float64]:
        grid = np.array(grid_points, dtype=float)
        unit = Exposures(
            lat=grid[:, 0],
            lon=grid[:, 1],
            value=np.full(grid.shape[0], VALUE / grid.shape[0]),
        )
        unit.gdf["impf_TC"] = 1
        calc = ImpactCalc(unit.copy(), impfset, hazard).impact(save_mat=True)
        return np.asarray(calc.imp_mat.todense(), dtype=float).sum(axis=1)[:, None]

    narrow_loss = unit_loss(narrow)
    record("unit_point_index", wind[:, [centre]], narrow_loss)
    record("unit_mean_index", wind[:, :25].mean(axis=1, keepdims=True), narrow_loss)
    wide_loss = unit_loss([points[j] for j in wide_columns])
    record("unit_wide_point_index", wind[:, [centre]], wide_loss)
    record(
        "unit_wide_mean_index",
        wind[:, wide_columns].mean(axis=1, keepdims=True),
        wide_loss,
    )

    v_low, v_high = V_HALF_DRAWS
    draws = rng.uniform(v_low, v_high, size=hazard.size)
    loss_draws = VALUE * mdr(wind[:, centre], draws)[:, None]
    record("impf_draws", wind_single, loss_draws)

    return {
        "setup": {
            "n_storms": N_STORMS,
            "n_years": N_YEARS,
            "n_train_years": N_TRAIN,
            "n_test_years": N_YEARS - N_TRAIN,
            "index_above_attachment_share": float(np.mean(wind_single[:, 0] >= 25.0)),
            "objective": "expected uncovered loss",
            "basis": "annual",
            "scope": "individual",
            "pricing": "pure premium",
            "budget": 1.0,
            "beta": BETA,
            "seed": SEED,
        },
        "setups": setups,
    }


def main() -> None:
    """Run the experiment and write the observations as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(run(), indent=1) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
