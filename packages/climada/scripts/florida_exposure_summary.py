r"""Exposure summary of the Florida-counties EventSet (MAR-114, D2).

One figure with four panels and their figure data:

(a) map of Florida's LitPop cells (``cells.parquet``, MAR-113) coloured by
    value, the TIGER/Line county outlines and the value-weighted centroids
    (the index location), sized by county value;
(b) Monroe County (the Keys): its cells, positive and zero-valued, against
    the county polygon. The cells present in the LitPop file are LitPop's
    land mask at 150 arcsec; a cell absent from the file is water to LitPop;
(c) the value distribution: county values sorted, on a log scale, with the
    cumulative share of the portfolio value;
(d) the tail dependence of the county losses: for counties ``i`` and ``j``,
    ``lambda_ij = P(A_i > q_i and A_j > q_j) / (1 - q)``, where ``A_i`` is the
    annual loss of county ``i`` per (year, draw_id) outcome (SPEC §5: each
    draw is one simulated version of the year; years without a row count as
    zero) and ``q_i`` its ``q``-quantile (default ``q = 0.99``). The diagonal
    is ``P(A_i > q_i) / (1 - q)``, 1 unless ties at the quantile (e.g. a
    county with a loss in under 1 % of the outcomes, so ``q_i = 0``) make it
    smaller. Counties are ordered by value.

Figure data (CSV, next to the figure): ``counties.csv`` (one row per county:
value, share, cells, expected annual loss, ``q_i``, ``P(A_i > q_i)``),
``monroe_cells.csv`` and ``tail_dependence.csv`` (long format).

From ``packages/climada``::

    pixi run --locked python scripts/florida_exposure_summary.py \\
        --eventset ../../data/eventsets/florida-counties-iris-vulnerability \\
        --cells ../../data/litpop-florida/locations/cells.parquet \\
        --boundaries ../../data/litpop-florida/raw/tl_2025_us_county.zip \\
        --out-dir ../../research/data/d2-florida-eventset/exposure-summary

Attribution (printed on the figure): LitPop CC BY 4.0 (Eberenz et al. 2020),
U.S. Census Bureau 2025 TIGER/Line Shapefiles, IRIS (Sparks and Toumi 2024).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import LogNorm
from numpy.typing import NDArray

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design_climada.portfolio_litpop import (
    load_manifest,
    read_county_boundaries,
)

MONROE = "12087"
STATE_FIPS = "12"
DEFAULT_Q = 0.99
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#a3a29d"
GRID = "#e4e3df"
BLUE = "#2a78d6"
ATTRIBUTION = (
    "Asset values: LitPop_150arcsec_USA v3 (CLIMADA data API), CC BY 4.0, "
    "Eberenz et al. (2020), doi:10.5194/essd-12-817-2020. County boundaries: "
    "U.S. Census Bureau, 2025 TIGER/Line Shapefiles. Hazard: IRIS (Sparks and "
    "Toumi 2024), doi:10.1038/s41597-024-03250-y."
)


def annual_losses(es: EventSet) -> tuple[NDArray[np.float64], int]:
    """Return the ``(n_years * n_draws, n_locations)`` annual losses.

    Outcomes are (year, draw_id) pairs: each draw is one simulated version of
    the year (SPEC §5). Years without a row are zero.

    Parameters
    ----------
    es : EventSet
        The EventSet; ``draw_id`` must run over ``0 .. n_draws - 1``.

    Returns
    -------
    tuple of numpy.ndarray and int
        The annual losses (row ``year * n_draws + draw_id``) and ``n_draws``.
    """
    draw = es.events["draw_id"].to_numpy(dtype=np.int64)
    year = es.events["year"].to_numpy(dtype=np.int64)
    n_draws = int(draw.max()) + 1
    if sorted(set(draw.tolist())) != list(range(n_draws)):
        raise ValueError("draw_id must run over 0 .. n_draws - 1")
    out = np.zeros((es.metadata.n_years * n_draws, es.n_locations))
    np.add.at(out, year * n_draws + draw, es.loss)
    return out, n_draws


def tail_dependence(
    annual: NDArray[np.float64], q: float = DEFAULT_Q
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Return the empirical upper-tail dependence matrix of the columns.

    ``lambda_ij = P(A_i > q_i and A_j > q_j) / (1 - q)`` with ``q_i`` the
    ``q``-quantile of column ``i`` (linear interpolation) and strict
    exceedance.

    Parameters
    ----------
    annual : numpy.ndarray
        ``(n_outcomes, n)`` annual losses, equally likely outcomes.
    q : float, optional
        Quantile level in (0, 1); default 0.99.

    Returns
    -------
    tuple of numpy.ndarray
        ``(lambda, quantiles, exceedance probabilities)``.
    """
    if not 0 < q < 1:
        raise ValueError(f"q must be in (0, 1), got {q}")
    quantiles = np.quantile(annual, q, axis=0)
    exceed = (annual > quantiles).astype(np.float64)
    joint = exceed.T @ exceed / len(annual)
    return joint / (1 - q), quantiles, exceed.mean(axis=0)


def _style() -> None:
    mpl.rcParams.update(
        {
            "font.size": 8,
            "axes.edgecolor": MUTED,
            "axes.labelcolor": INK_2,
            "axes.titlesize": 9,
            "axes.titlecolor": INK,
            "axes.titlelocation": "left",
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "axes.spines.top": False,
            "axes.spines.right": False,
        }
    )


def summarise(
    es: EventSet,
    cells: pd.DataFrame,
    counties: Any,  # noqa: ANN401  (geopandas.GeoDataFrame)
    out_dir: Path,
    *,
    q: float = DEFAULT_Q,
) -> dict[str, Any]:
    """Write the figure and its figure data; return the summary numbers."""
    out_dir.mkdir(parents=True, exist_ok=True)
    loc = es.locations.reset_index(drop=True)
    ids = loc["location_id"].astype(str).tolist()
    florida_cells = cells[cells["location_id"].notna()].copy()
    annual, n_draws = annual_losses(es)
    lam, quantiles, p_exceed = tail_dependence(annual, q)
    eal = es.rates @ es.loss

    table = pd.DataFrame(
        {
            "location_id": ids,
            "name": loc["name"].astype(str),
            "lat": loc["lat"],
            "lon": loc["lon"],
            "value": loc["value"],
            "share": loc["value"] / loc["value"].sum(),
            "n_cells": loc["n_cells"] if "n_cells" in loc else np.nan,
            "n_cells_positive": loc.get("n_cells_positive", np.nan),
            "expected_annual_loss": eal,
            f"annual_loss_q{q:g}": quantiles,
            "p_annual_loss_above_q": p_exceed,
        }
    ).sort_values("value", ascending=False, kind="stable")
    table.insert(0, "value_rank", np.arange(1, len(table) + 1))
    table.to_csv(out_dir / "counties.csv", index=False, float_format="%.6g")
    order = [ids.index(i) for i in table["location_id"]]

    monroe = pd.DataFrame(florida_cells[florida_cells["location_id"] == MONROE])
    pd.DataFrame(monroe[["lat", "lon", "value"]]).to_csv(
        out_dir / "monroe_cells.csv", index=False, float_format="%.8g"
    )
    long = pd.DataFrame(
        [
            {
                "location_id_i": ids[i],
                "location_id_j": ids[j],
                "tail_dependence": lam[i, j],
            }
            for i in order
            for j in order
        ]
    )
    long.to_csv(out_dir / "tail_dependence.csv", index=False, float_format="%.6g")

    _style()
    fig = plt.figure(figsize=(11, 9.2), layout="constrained")
    grid = fig.add_gridspec(2, 2, width_ratios=[1.15, 1])
    florida = counties[counties["state_fips"] == STATE_FIPS]

    # (a) map
    ax = fig.add_subplot(grid[0, 0])
    positive = florida_cells[florida_cells["value"] > 0]
    sc = ax.scatter(
        positive["lon"],
        positive["lat"],
        c=positive["value"],
        s=2.2,
        marker="s",
        cmap="Blues",
        norm=LogNorm(
            vmin=max(float(positive["value"].min()), 1e5),
            vmax=float(positive["value"].max()),
        ),
        linewidths=0,
        rasterized=True,
    )
    zero = florida_cells[florida_cells["value"] == 0]
    ax.scatter(zero["lon"], zero["lat"], s=2.2, marker="s", color=GRID, linewidths=0)
    florida.boundary.plot(ax=ax, color=MUTED, linewidth=0.3)
    ax.scatter(
        loc["lon"],
        loc["lat"],
        s=8 + 300 * loc["value"] / loc["value"].max(),
        facecolors="none",
        edgecolors=INK,
        linewidths=0.6,
    )
    ax.set_aspect(1 / np.cos(np.radians(27.5)))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(
        "(a) LitPop cells (value, USD) and county centroids (circle area ~ value)"
    )
    fig.colorbar(sc, ax=ax, shrink=0.7, label="cell value, USD (LitPop 2018)")

    # (b) Monroe
    ax = fig.add_subplot(grid[0, 1])
    florida[florida["unit_id"] == MONROE].plot(
        ax=ax, facecolor="#f4f3ef", edgecolor=MUTED, linewidth=0.5
    )
    mpos = monroe[monroe["value"] > 0]
    mzero = monroe[monroe["value"] == 0]
    ax.scatter(
        mpos["lon"],
        mpos["lat"],
        s=18,
        marker="s",
        color=BLUE,
        label=f"value > 0 ({len(mpos)})",
    )
    ax.scatter(
        mzero["lon"],
        mzero["lat"],
        s=18,
        marker="s",
        facecolors="none",
        edgecolors=INK_2,
        linewidths=0.6,
        label=f"value 0 ({len(mzero)})",
    )
    centroid = loc[loc["location_id"] == MONROE].iloc[0]
    ax.scatter(
        [centroid["lon"]],
        [centroid["lat"]],
        s=40,
        marker="x",
        color=INK,
        label="centroid",
    )
    ax.annotate(
        "Key West (24.56 N, 81.78 W):\nno LitPop cell",
        xy=(-81.78, 24.555),
        xytext=(-82.6, 24.95),
        fontsize=7,
        color=INK_2,
        arrowprops={"arrowstyle": "-", "color": INK_2, "linewidth": 0.6},
    )
    ax.set_xlim(-83.2, -80.1)
    ax.set_ylim(24.35, 25.95)
    ax.set_aspect(1 / np.cos(np.radians(25)))
    ax.legend(loc="upper left", frameon=False, title="Monroe County LitPop cells")
    ax.set_title(
        f"(b) Monroe County: {len(monroe)} cells, "
        f"{centroid['value'] / 1e9:.2f} x 10^9 USD (cells = LitPop land mask)"
    )
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")

    # (c) value distribution
    ax = fig.add_subplot(grid[1, 0])
    ranks = table["value_rank"].to_numpy()
    ax.bar(ranks, table["value"] / 1e9, color=BLUE, width=0.8)
    ax.set_yscale("log")
    ax.set_xlabel("county, by value rank")
    ax.set_ylabel("value, 10^9 USD (log scale)")
    monroe_rank = int(table.loc[table["location_id"] == MONROE, "value_rank"].iloc[0])
    ax.annotate(
        "Monroe",
        xy=(monroe_rank, float(centroid["value"]) / 1e9),
        xytext=(monroe_rank - 8, float(centroid["value"]) / 1e9 * 8),
        fontsize=7,
        color=INK_2,
        arrowprops={"arrowstyle": "-", "color": INK_2, "linewidth": 0.6},
    )
    share = ax.twinx()
    share.plot(ranks, 100 * table["share"].cumsum(), color=INK, linewidth=1.2)
    share.set_ylim(0, 100)
    share.set_ylabel("cumulative share of value, % (line)")
    share.spines["right"].set_visible(True)
    ax.set_title(
        f"(c) County values: total {loc['value'].sum() / 1e12:.3f} x 10^12 USD"
    )

    # (d) tail dependence
    ax = fig.add_subplot(grid[1, 1])
    image = ax.imshow(lam[np.ix_(order, order)], cmap="Blues", vmin=0, vmax=1)
    names = table["name"].tolist()
    ticks = list(range(0, len(names), 6))
    ax.set_xticks(ticks, [names[t] for t in ticks], rotation=90, fontsize=6)
    ax.set_yticks(ticks, [names[t] for t in ticks], fontsize=6)
    ax.set_title(
        f"(d) Tail dependence of annual county losses, q = {q:g}\n"
        f"({es.metadata.n_years:,} years x {n_draws} draws; counties by value)"
    )
    fig.colorbar(
        image, ax=ax, shrink=0.8, label="P(both above own q-quantile) / (1 - q)"
    )

    fig.text(0.01, -0.01, ATTRIBUTION, fontsize=6, color=INK_2, wrap=True)
    fig.savefig(out_dir / "exposure_summary.png", dpi=150, bbox_inches="tight")
    plt.close(fig)

    off = lam[~np.eye(len(ids), dtype=bool)]
    summary: dict[str, Any] = {
        "eventset_content_hash": es.content_hash(),
        "q": q,
        "n_outcomes": len(annual),
        "n_draws": n_draws,
        "tail_dependence_offdiagonal": {
            "min": float(off.min()),
            "median": float(np.median(off)),
            "max": float(off.max()),
        },
        "counties_with_zero_quantile": [ids[i] for i in np.flatnonzero(quantiles == 0)],
        "portfolio_expected_annual_loss": float(eal.sum()),
        "monroe": {
            "value": float(centroid["value"]),
            "value_rank": monroe_rank,
            "n_cells": len(monroe),
            "n_cells_positive": len(mpos),
            "cells_lon_range": [float(monroe["lon"].min()), float(monroe["lon"].max())],
            "cells_lat_range": [float(monroe["lat"].min()), float(monroe["lat"].max())],
            "expected_annual_loss": float(eal[ids.index(MONROE)]),
        },
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    """Run the script; see the module docstring."""
    parser = argparse.ArgumentParser(
        description="Exposure summary of the Florida-counties EventSet (MAR-114)."
    )
    parser.add_argument("--eventset", type=Path, required=True)
    parser.add_argument("--cells", type=Path, required=True)
    parser.add_argument("--boundaries", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--q", type=float, default=DEFAULT_Q)
    args = parser.parse_args(argv)
    es = EventSet.from_parquet(args.eventset)
    cells = pd.read_parquet(args.cells)
    member = load_manifest().boundaries_info["member"]
    counties = read_county_boundaries(args.boundaries, member)
    summary = summarise(es, cells, counties, args.out_dir, q=args.q)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
