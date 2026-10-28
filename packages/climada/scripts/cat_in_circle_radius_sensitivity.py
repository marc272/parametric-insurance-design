r"""Cat-in-a-circle radius sensitivity for the Florida counties (MAR-133, P-05).

Compares Florida-counties EventSets whose index is the cat-in-a-circle
category (MAR-26, SPEC §6.3 index (b)) at several radii, on the same loss
matrix. For each EventSet it reports:

* the **category distribution**: per Saffir-Simpson category 0-5, the share
  of the (row, county) pairs and the share of the total loss on them
  (rate-weighted), so the category-0 loss share is the loss whose circle sees
  no hurricane;
* the **basis risk** of a simple step payout, the same measure at every
  radius (``unexplained_share``): per county, the step payout that pays the
  rate-weighted mean loss of each category, ``P_j(c) = E[L_j | I_j = c]``
  (the least-squares step payout with integer category breakpoints and
  attachment 0, fitted in-sample on all rows), and its share of the loss
  variance left unexplained,
  ``sum_k w_k (L_kj - P_j(I_kj))^2 / sum_k w_k (L_kj - mean_w L_j)^2``
  (``1 - eta^2``, the correlation ratio; 0 is a perfect fit, 1 a payout that
  explains nothing). For the portfolio the payouts are summed over the
  counties and compared with the portfolio loss in the same way, per row
  ("event") and per (year, draw_id) outcome ("annual": sums over the rows of
  a year, years without a row are zero, every outcome equally likely). As a
  check on the in-sample fit, the same measure with each half of the years
  (``[0, n_years // 2)`` and the rest) paid by the levels fitted on the other
  half (``two_fold_payout``; "2fold");
* the **trigger frequency** per county: the expected number of rows a year
  with category >= 1 (``sum_k rate_k [I_kj >= 1]``).

Outputs in ``--out-dir``: ``summary.csv`` (one row per EventSet, with the
content hash, the index-table hash and the loss-matrix hash),
``counties.csv`` (one row per EventSet and county), ``checksums.json`` and
the figure ``radius_sensitivity.png`` (EventSets passed with
``--provisional`` are in the CSVs, flagged, but not in the figure).

From ``packages/climada``::

    pixi run --locked python scripts/cat_in_circle_radius_sensitivity.py \\
        --eventset ../../data/eventsets/florida-counties-iris-cat-in-circle-50km \\
        --config configs/florida_counties_cat_in_circle_50km_no_draws.yaml \\
        ... (one --eventset/--config pair per radius) \\
        --out-dir ../../research/data/cat-in-circle-radius-sensitivity

Attribution (printed on the figure): LitPop CC BY 4.0 (Eberenz et al. 2020),
U.S. Census Bureau 2025 TIGER/Line Shapefiles, IRIS (Sparks and Toumi 2024).
"""

from __future__ import annotations

import argparse
import hashlib
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
from matplotlib.ticker import FormatStrFormatter, NullFormatter
from numpy.typing import NDArray

from parametric_insurance_design.eventset import EventSet

INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#a3a29d"
GRID = "#e4e3df"
SURFACE = "#fcfcfb"
BLUE = "#2a78d6"
ORANGE = "#eb6834"
#: Category 0 in neutral grey, categories 1-5 on the ordinal blue ramp
#: (steps 250-650 of the reference sequential hue).
CATEGORY_COLOURS = ("#d6d5d0", "#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#104281")
DESCRIPTION = "Cat-in-a-circle radius sensitivity for the Florida counties."
ATTRIBUTION = (
    "Asset values: LitPop_150arcsec_USA v3 (CLIMADA data API), CC BY 4.0, "
    "Eberenz et al. (2020), doi:10.5194/essd-12-817-2020. County boundaries: "
    "U.S. Census Bureau, 2025 TIGER/Line Shapefiles. Hazard: IRIS (Sparks and "
    "Toumi 2024), doi:10.1038/s41597-024-03250-y."
)


def matrix_hash(matrix: NDArray[np.float64]) -> str:
    r"""Return ``sha256:`` of a matrix's shape and little-endian float64 bytes.

    Parameters
    ----------
    matrix : numpy.ndarray
        A 2-D matrix (the EventSet's ``index`` or ``loss``), row-major.

    Returns
    -------
    str
        ``"sha256:"`` and 64 hex digits over ``"<rows>x<cols>\n"`` followed
        by the C-order ``<f8`` bytes.
    """
    values = np.ascontiguousarray(matrix, dtype="<f8")
    if values.ndim != 2:
        raise ValueError(f"expected a 2-D matrix, got {values.ndim} dimensions")
    digest = hashlib.sha256(f"{values.shape[0]}x{values.shape[1]}\n".encode())
    digest.update(values.tobytes())
    return f"sha256:{digest.hexdigest()}"


def _weights(rates: NDArray[np.float64]) -> NDArray[np.float64]:
    rates = np.asarray(rates, dtype=np.float64)
    if rates.ndim != 1 or not (rates > 0).all():
        raise ValueError("rates must be a 1-D array of positive values")
    return rates


def category_shares(
    index: NDArray[np.float64],
    loss: NDArray[np.float64],
    rates: NDArray[np.float64],
    n_categories: int,
) -> pd.DataFrame:
    """Return the pair count, pair share and loss share of each category.

    Parameters
    ----------
    index, loss : numpy.ndarray
        ``(n_rows, n_locations)`` category index (integers 0 to
        ``n_categories - 1``) and loss.
    rates : numpy.ndarray
        Annual rate of each row.
    n_categories : int
        Number of categories, including 0.

    Returns
    -------
    pandas.DataFrame
        One row per category: ``category``, ``n_pairs``, ``pair_share``
        (unweighted share of the (row, location) pairs) and ``loss_share``
        (rate-weighted share of the total loss).

    Raises
    ------
    ValueError
        If an index value is not an integer in ``[0, n_categories)`` or the
        total loss is zero.
    """
    w = _weights(rates)
    cat = _categories(index, n_categories)
    weighted = np.asarray(loss, dtype=np.float64) * w[:, None]
    total = float(weighted.sum())
    if total <= 0:
        raise ValueError("the total loss is zero")
    rows = []
    for c in range(n_categories):
        mask = cat == c
        rows.append(
            {
                "category": c,
                "n_pairs": int(mask.sum()),
                "pair_share": float(mask.mean()),
                "loss_share": float(weighted[mask].sum() / total),
            }
        )
    return pd.DataFrame(rows)


def _categories(index: NDArray[np.float64], n_categories: int) -> NDArray[np.int64]:
    values = np.asarray(index, dtype=np.float64)
    cat = np.rint(values).astype(np.int64)
    if not np.array_equal(cat, values) or cat.min() < 0 or cat.max() >= n_categories:
        raise ValueError(
            f"index values must be integers in [0, {n_categories}), got "
            f"[{values.min()}, {values.max()}]"
        )
    return cat


def step_payout(
    index: NDArray[np.float64],
    loss: NDArray[np.float64],
    rates: NDArray[np.float64],
    n_categories: int,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """Fit the least-squares step payout of each location on its category.

    The payout of category ``c`` at location ``j`` is the rate-weighted mean
    loss of the rows where location ``j`` has category ``c``; a category
    that never occurs at ``j`` pays nothing (it is never evaluated).

    Parameters
    ----------
    index, loss : numpy.ndarray
        ``(n_rows, n_locations)`` category index and loss.
    rates : numpy.ndarray
        Annual rate of each row.
    n_categories : int
        Number of categories, including 0.

    Returns
    -------
    tuple of numpy.ndarray
        The fitted payout per row, ``(n_rows, n_locations)``, and the payout
        levels, ``(n_categories, n_locations)``.
    """
    w = _weights(rates)
    cat = _categories(index, n_categories)
    loss = np.asarray(loss, dtype=np.float64)
    levels = np.zeros((n_categories, loss.shape[1]))
    for c in range(n_categories):
        mask = cat == c
        weight = (mask * w[:, None]).sum(axis=0)
        total = (np.where(mask, loss, 0.0) * w[:, None]).sum(axis=0)
        levels[c] = np.divide(total, weight, out=np.zeros_like(total), where=weight > 0)
    fitted = np.take_along_axis(levels, cat, axis=0)
    return fitted, levels


def two_fold_payout(
    index: NDArray[np.float64],
    loss: NDArray[np.float64],
    rates: NDArray[np.float64],
    year: NDArray[np.int64],
    n_years: int,
    n_categories: int,
) -> tuple[NDArray[np.float64], int]:
    """Return the step payout of each row fitted on the other half of the years.

    The years are split into two blocks, ``[0, n_years // 2)`` and the rest.
    The rows of each block get the :func:`step_payout` levels fitted on the
    other block. A category that does not occur at a location in the fitting
    block pays nothing; such (row, location) pairs are counted.

    Parameters
    ----------
    index, loss : numpy.ndarray
        ``(n_rows, n_locations)`` category index and loss.
    rates : numpy.ndarray
        Annual rate of each row.
    year : numpy.ndarray
        Simulation year of each row.
    n_years : int
        Number of simulated years.
    n_categories : int
        Number of categories, including 0.

    Returns
    -------
    tuple of numpy.ndarray and int
        The out-of-block payout per row, ``(n_rows, n_locations)``, and the
        number of (row, location) pairs whose category was not seen in the
        fitting block.

    Raises
    ------
    ValueError
        If a block has no rows.
    """
    cat = _categories(index, n_categories)
    rates = _weights(rates)
    first = np.asarray(year, dtype=np.int64) < n_years // 2
    if first.all() or not first.any():
        raise ValueError("both year blocks need rows")
    out = np.zeros(cat.shape)
    n_unseen = 0
    for fit, apply in ((first, ~first), (~first, first)):
        _, levels = step_payout(index[fit], loss[fit], rates[fit], n_categories)
        seen = np.zeros((n_categories, cat.shape[1]), dtype=bool)
        for c in range(n_categories):
            seen[c] = (cat[fit] == c).any(axis=0)
        out[apply] = np.take_along_axis(levels, cat[apply], axis=0)
        n_unseen += int((~np.take_along_axis(seen, cat[apply], axis=0)).sum())
    return out, n_unseen


def unexplained_share(
    target: NDArray[np.float64],
    fitted: NDArray[np.float64],
    weights: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Return ``sum w (t - f)^2 / sum w (t - mean_w t)^2`` per column.

    Parameters
    ----------
    target, fitted : numpy.ndarray
        ``(n,)`` or ``(n, m)`` values.
    weights : numpy.ndarray
        ``(n,)`` positive weights.

    Returns
    -------
    numpy.ndarray
        One value per column (a 0-d array for 1-D input); NaN where the
        target is constant.
    """
    w = _weights(weights)
    t = np.asarray(target, dtype=np.float64)
    f = np.asarray(fitted, dtype=np.float64)
    if t.shape != f.shape or t.shape[0] != len(w):
        raise ValueError("target, fitted and weights do not match")
    ww = w.reshape((-1,) + (1,) * (t.ndim - 1))
    mean = (ww * t).sum(axis=0) / w.sum()
    total = (ww * (t - mean) ** 2).sum(axis=0)
    residual = (ww * (t - f) ** 2).sum(axis=0)
    return np.divide(
        residual,
        total,
        out=np.full(np.shape(total), np.nan),
        where=total > 0,
    )


def annual_sums(
    values: NDArray[np.float64],
    year: NDArray[np.int64],
    draw_id: NDArray[np.int64],
    n_years: int,
) -> NDArray[np.float64]:
    """Return the sums per (year, draw_id) outcome; years without a row are 0.

    Parameters
    ----------
    values : numpy.ndarray
        ``(n_rows,)`` or ``(n_rows, m)`` values.
    year, draw_id : numpy.ndarray
        Each row's simulation year and draw; ``draw_id`` must run over
        ``0 .. n_draws - 1``.
    n_years : int
        Number of simulated years.

    Returns
    -------
    numpy.ndarray
        ``(n_years * n_draws, ...)``; row ``year * n_draws + draw_id``.
    """
    draw = np.asarray(draw_id, dtype=np.int64)
    n_draws = int(draw.max()) + 1
    if sorted(set(draw.tolist())) != list(range(n_draws)):
        raise ValueError("draw_id must run over 0 .. n_draws - 1")
    values = np.asarray(values, dtype=np.float64)
    out = np.zeros((n_years * n_draws, *values.shape[1:]))
    np.add.at(out, np.asarray(year, dtype=np.int64) * n_draws + draw, values)
    return out


def build_parameters(es: EventSet) -> dict[str, Any]:
    """Return the build record's parameters (the first transform).

    Raises
    ------
    ValueError
        If the EventSet's index is not a cat-in-a-circle category.
    """
    if not es.metadata.transforms:
        raise ValueError("the EventSet has no build record")
    parameters = dict(es.metadata.transforms[0].parameters)
    index = parameters.get("index", {})
    if index.get("kind") != "cat_in_circle" or index.get("metric") != "category":
        raise ValueError(f"not a cat-in-a-circle category index: {index}")
    return parameters


def analyse(
    es: EventSet, *, label: str, provisional: bool, config_sha256: str | None
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Return the summary row and the per-county table of one EventSet.

    Parameters
    ----------
    es : EventSet
        A cat-in-a-circle EventSet (metric ``category``).
    label : str
        Its label in the outputs.
    provisional : bool
        Flag recorded in both outputs.
    config_sha256 : str or None
        SHA256 of the config file that built it, if known.

    Returns
    -------
    tuple of dict and pandas.DataFrame
        The summary row and the per-county rows.
    """
    parameters = build_parameters(es)
    n_categories = len(parameters["index"]["breakpoints_kn"]) + 1
    radius = float(parameters["index"]["radius_km"])
    n_draws = int(parameters["n_draws"])
    rates = es.rates
    index, loss = es.index, es.loss
    events = es.events
    year = events["year"].to_numpy(dtype=np.int64)
    draw = events["draw_id"].to_numpy(dtype=np.int64)

    shares = category_shares(index, loss, rates, n_categories)
    fitted, _levels = step_payout(index, loss, rates, n_categories)
    county_br = unexplained_share(loss, fitted, rates)
    portfolio_br = float(unexplained_share(loss.sum(axis=1), fitted.sum(axis=1), rates))
    annual_loss = annual_sums(loss.sum(axis=1), year, draw, es.metadata.n_years)
    annual_payout = annual_sums(fitted.sum(axis=1), year, draw, es.metadata.n_years)
    annual_br = float(
        unexplained_share(annual_loss, annual_payout, np.ones(len(annual_loss)))
    )
    oos, n_unseen = two_fold_payout(
        index, loss, rates, year, es.metadata.n_years, n_categories
    )
    county_br_oos = unexplained_share(loss, oos, rates)
    portfolio_br_oos = float(
        unexplained_share(loss.sum(axis=1), oos.sum(axis=1), rates)
    )
    cat = _categories(index, n_categories)
    trigger = ((cat >= 1) * rates[:, None]).sum(axis=0)
    eal = (loss * rates[:, None]).sum(axis=0)
    cat0_loss = (np.where(cat == 0, loss, 0.0) * rates[:, None]).sum(axis=0)
    storm_any = pd.Series((cat >= 1).any(axis=1)).groupby(events["event_id"]).any()

    row: dict[str, Any] = {
        "label": label,
        "radius_km": radius,
        "n_draws": n_draws,
        "provisional": provisional,
        "eventset_content_hash": es.content_hash(),
        "index_table_hash": matrix_hash(index),
        "loss_matrix_hash": matrix_hash(loss),
        "config_sha256": config_sha256 or "",
        "n_rows": es.n_rows,
        "n_storms": int(events["event_id"].nunique()),
        "n_locations": es.n_locations,
        "eal_usd": float(eal.sum()),
        "n_storms_cat_ge1_any_county": int(storm_any.sum()),
    }
    loss_share = shares["loss_share"].to_numpy(dtype=np.float64)
    pair_share = shares["pair_share"].to_numpy(dtype=np.float64)
    for c in range(n_categories):
        row[f"loss_share_cat{c}"] = float(loss_share[c])
    for c in range(n_categories):
        row[f"pair_share_cat{c}"] = float(pair_share[c])
    row.update(
        {
            "basis_risk_portfolio_event": portfolio_br,
            "basis_risk_portfolio_annual": annual_br,
            "basis_risk_county_min": float(np.nanmin(county_br)),
            "basis_risk_county_median": float(np.nanmedian(county_br)),
            "basis_risk_county_max": float(np.nanmax(county_br)),
            "basis_risk_county_eal_weighted": float(
                np.nansum(county_br * eal) / eal[np.isfinite(county_br)].sum()
            ),
            "basis_risk_portfolio_event_2fold": portfolio_br_oos,
            "basis_risk_county_median_2fold": float(np.nanmedian(county_br_oos)),
            "n_pairs_unseen_category_2fold": n_unseen,
            "trigger_per_year_county_min": float(trigger.min()),
            "trigger_per_year_county_median": float(np.median(trigger)),
            "trigger_per_year_county_max": float(trigger.max()),
            "n_counties_never_cat_ge1": int((trigger == 0).sum()),
        }
    )

    names = (
        es.locations["name"].astype(str).tolist()
        if "name" in es.locations.columns
        else [""] * es.n_locations
    )
    county = pd.DataFrame(
        {
            "label": label,
            "radius_km": radius,
            "provisional": provisional,
            "location_id": es.location_ids,
            "name": names,
            "eal_usd": eal,
            "loss_share_cat0": np.divide(
                cat0_loss, eal, out=np.full_like(eal, np.nan), where=eal > 0
            ),
            "basis_risk": county_br,
            "basis_risk_2fold": county_br_oos,
            "trigger_per_year": trigger,
        }
    )
    for c in range(n_categories):
        county[f"per_year_cat{c}"] = ((cat == c) * rates[:, None]).sum(axis=0)
    return row, county


def plot(
    summary: pd.DataFrame, counties: pd.DataFrame, path: Path, n_years: int
) -> None:
    """Draw the three-panel radius sensitivity figure (non-provisional rows)."""
    keep = ~summary["provisional"].to_numpy(dtype=bool)
    summary = pd.DataFrame(summary.loc[keep]).sort_values(by="radius_km")
    counties = pd.DataFrame(counties.loc[~counties["provisional"].to_numpy(dtype=bool)])
    radii = summary["radius_km"].tolist()
    labels = [f"{r:g} km" for r in radii]
    x = np.arange(len(radii))
    n_categories = sum(c.startswith("loss_share_cat") for c in summary.columns)

    plt.rcParams.update(
        {
            "font.size": 9,
            "axes.edgecolor": MUTED,
            "axes.labelcolor": INK_2,
            "xtick.color": INK_2,
            "ytick.color": INK_2,
            "axes.titlesize": 10,
            "axes.titleweight": "bold",
            "axes.titlecolor": INK,
            "axes.titlelocation": "left",
        }
    )
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.6), facecolor=SURFACE)
    for ax in axes:
        ax.set_facecolor(SURFACE)
        ax.spines[["top", "right"]].set_visible(False)

    # (a) loss share by category, stacked horizontal bars.
    ax = axes[0]
    left = np.zeros(len(radii))
    for c in range(n_categories):
        share = summary[f"loss_share_cat{c}"].to_numpy() * 100
        ax.barh(
            x,
            share,
            left=left,
            height=0.62,
            color=CATEGORY_COLOURS[c],
            edgecolor=SURFACE,
            linewidth=1.5,
            label=f"cat {c}",
        )
        left += share
    cat0 = summary["loss_share_cat0"].to_numpy() * 100
    ax.set_yticks(
        x,
        [f"{lab}\ncat 0: {s:.1f} %" for lab, s in zip(labels, cat0, strict=True)],
    )
    ax.invert_yaxis()
    ax.set_xlim(0, 100)
    ax.set_xlabel("share of total loss (%), by the pair's index category")
    ax.set_title("(a) Loss by cat-in-a-circle category")
    ax.legend(
        ncol=n_categories,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.17),
        frameon=False,
        handlelength=1.0,
        columnspacing=0.8,
        fontsize=8,
    )
    ax.grid(axis="x", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)

    rng = np.random.default_rng(0)  # jitter of the county dots only

    # (b) basis risk: counties (dots), portfolio per event and per year.
    ax = axes[1]
    for xi, r in zip(x, radii, strict=True):
        values = counties.loc[counties["radius_km"] == r, "basis_risk"].to_numpy()
        ax.scatter(
            xi + rng.uniform(-0.18, 0.18, len(values)),
            values,
            s=10,
            color=MUTED,
            linewidths=0,
            label="county" if xi == 0 else None,
        )
    ax.plot(
        x,
        summary["basis_risk_portfolio_event"],
        marker="D",
        markersize=7,
        color=BLUE,
        linewidth=2,
        label="portfolio, per event",
    )
    ax.plot(
        x,
        summary["basis_risk_portfolio_annual"],
        marker="s",
        markersize=7,
        color=ORANGE,
        linewidth=2,
        label="portfolio, per year",
    )
    ax.set_xticks(x, labels)
    ax.set_ylim(0, 1.02)
    ax.set_ylabel("unexplained loss variance, 1 - η²")
    ax.set_title("(b) Basis risk of the in-sample step payout")
    ax.legend(frameon=False, loc="lower left", fontsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)

    # (c) trigger frequency per county.
    ax = axes[2]
    floor = 0.5 / n_years
    for xi, r in zip(x, radii, strict=True):
        values = counties.loc[counties["radius_km"] == r, "trigger_per_year"]
        values = np.maximum(values.to_numpy(), floor)
        ax.scatter(
            xi + rng.uniform(-0.18, 0.18, len(values)),
            values,
            s=10,
            color=MUTED,
            linewidths=0,
            label="county" if xi == 0 else None,
        )
    ax.plot(
        x,
        summary["trigger_per_year_county_median"],
        marker="D",
        markersize=7,
        color=BLUE,
        linewidth=2,
        label="county median",
    )
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FormatStrFormatter("%g"))
    ax.yaxis.set_minor_formatter(NullFormatter())
    ax.set_yticks([0.02, 0.03, 0.05, 0.1, 0.2])
    ax.set_xticks(x, labels)
    ax.set_ylabel("events a year with category ≥ 1 in the circle")
    ax.set_title("(c) Trigger frequency per county")
    ax.legend(frameon=False, loc="upper left", fontsize=8)
    ax.grid(axis="y", color=GRID, linewidth=0.6, which="major")
    ax.set_axisbelow(True)

    fig.suptitle(
        "Cat-in-a-circle radius sensitivity, Florida's 67 counties "
        "(IRIS 10,000 years, base Emanuel function, no vulnerability draws)",
        x=0.01,
        ha="left",
        color=INK,
        fontsize=11,
        fontweight="bold",
    )
    fig.text(
        0.01,
        0.01,
        "Index: max Saffir-Simpson category of the track within r of the "
        "county's value-weighted centroid. Loss: sum over the county's LitPop "
        "cells. Basis risk: per county, step payout = mean loss per category, "
        "fitted in-sample; portfolio = sum of county payouts.\n" + ATTRIBUTION,
        fontsize=7,
        color=INK_2,
        va="bottom",
    )
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: Sequence[str] | None = None) -> int:
    """Run the analysis; see the module docstring."""
    parser = argparse.ArgumentParser(description=DESCRIPTION)
    parser.add_argument("--eventset", type=Path, action="append", required=True)
    parser.add_argument(
        "--config",
        type=Path,
        action="append",
        default=[],
        help="config of each --eventset, same order (recorded as SHA256)",
    )
    parser.add_argument(
        "--provisional",
        type=Path,
        action="append",
        default=[],
        help="an EventSet reported in the CSVs, flagged, but not in the figure",
    )
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.config and len(args.config) != len(args.eventset):
        parser.error("give one --config per --eventset, or none")

    configs: list[Path | None] = list(args.config) or [None] * len(args.eventset)
    jobs = [(p, c, False) for p, c in zip(args.eventset, configs, strict=True)]
    jobs += [(p, None, True) for p in args.provisional]
    rows: list[dict[str, Any]] = []
    tables: list[pd.DataFrame] = []
    n_years: int | None = None
    for path, config, provisional in jobs:
        es = EventSet.from_parquet(path)
        if n_years is not None and es.metadata.n_years != n_years:
            raise ValueError("the EventSets differ in n_years")
        n_years = es.metadata.n_years
        row, county = analyse(
            es,
            label=f"{path.name} (provisional)" if provisional else path.name,
            provisional=provisional,
            config_sha256=_sha256(config) if config is not None else None,
        )
        rows.append(row)
        tables.append(county)
        print(
            f"{path.name}: r={row['radius_km']:g} km, cat-0 loss share "
            f"{row['loss_share_cat0']:.4f}, portfolio basis risk "
            f"{row['basis_risk_portfolio_event']:.4f} (event), "
            f"{row['basis_risk_portfolio_annual']:.4f} (annual)"
        )
    assert n_years is not None
    summary = pd.DataFrame(rows)
    counties = pd.concat(tables, ignore_index=True)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(args.out_dir / "summary.csv", index=False, float_format="%.10g")
    counties.to_csv(args.out_dir / "counties.csv", index=False, float_format="%.10g")
    plot(summary, counties, args.out_dir / "radius_sensitivity.png", n_years)
    checksums = {
        "eventsets": {
            r["label"]: {
                key: r[key]
                for key in (
                    "radius_km",
                    "n_draws",
                    "provisional",
                    "eventset_content_hash",
                    "index_table_hash",
                    "loss_matrix_hash",
                    "config_sha256",
                )
            }
            for r in rows
        },
        "index_table_hash": (
            "sha256 over '<rows>x<cols>\\n' and the index matrix as C-order "
            "little-endian float64 bytes (matrix_hash); same for the loss matrix"
        ),
        "outputs": {
            name: _sha256(args.out_dir / name)
            for name in ("summary.csv", "counties.csv", "radius_sensitivity.png")
        },
    }
    (args.out_dir / "checksums.json").write_text(
        json.dumps(checksums, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
