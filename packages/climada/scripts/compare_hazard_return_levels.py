r"""Return-level comparison of two hazard catalogues per location (MAR-32).

Diagnostic of the hazard-model scenario (SPEC §6.5 (i), D7): the same
portfolio built on a reference catalogue (S_0, IRIS) and on a second one
(S_1, STORM), compared location by location. Two annual quantities per
(year, draw_id) outcome (SPEC §5: each draw is one simulated version of the
year; years without a row count as zero):

* ``annual_loss``: the sum of the location's losses over the year's rows;
* ``annual_max_index``: the largest index value of the year (m/s for wind at
  the centroid, the category for cat-in-a-circle).

The return level at return period ``T`` years is the empirical quantile of
the annual quantity at ``1 - 1/T`` (numpy ``method="higher"``): with 10,000
equally likely years, the 1,000th, 200th, 100th and 40th largest value for
``T`` = 10, 50, 100 and 250. Every row's rate must be ``1 / (n_years *
n_draws)``, so the outcomes are equally likely; the script raises otherwise.
A ``portfolio`` row (the sum of the losses of all locations) is added for
``annual_loss``.

Outputs, in ``--out-dir``:

* ``return_levels.csv`` (figure data, long format): metric, location_id,
  name, return_period, reference, scenario, ratio (scenario / reference;
  empty when the reference is 0);
* ``summary.json``: both EventSets (content hash, hazard, scenario_id,
  ``n_years``, rows, draws), the rule, and per metric and return period the
  number of locations where the scenario level is above, equal to or below
  the reference and the median ratio. These are observations, not
  conclusions;
* ``return_levels.png``: (a) county annual-loss return levels, scenario
  against reference, log-log with the 1:1 line; (b) the same for the annual
  maximum index; (c) the portfolio annual-loss exceedance curves of both.

From ``packages/climada``::

    pixi run --locked python scripts/compare_hazard_return_levels.py \\
        --reference ../../data/eventsets/florida-counties-iris \\
        --scenario ../../data/eventsets/florida-counties-storm \\
        --out-dir ../../research/data/p06-storm-eventset/return-levels

The two EventSets must have the same locations (IDs, in any order) and the
same loss unit.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final, cast

import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.layout_engine import ConstrainedLayoutEngine
from numpy.typing import NDArray

from parametric_insurance_design.eventset import EventSet

DEFAULT_RETURN_PERIODS: Final[tuple[int, ...]] = (10, 50, 100, 250)
METRICS: Final[tuple[str, ...]] = ("annual_loss", "annual_max_index")
PORTFOLIO: Final[str] = "portfolio"
RATE_RTOL: Final[float] = 1e-9
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
#: Categorical slots 1 and 2 (reference, scenario); validated pair.
SERIES = ("#2a78d6", "#eb6834")
#: Ordinal blue ramp (steps 250, 400, 550, 700) for the return periods, with
#: one marker shape each as secondary encoding.
ORDINAL = ("#86b6ef", "#3987e5", "#1c5cab", "#0d366b")
MARKERS = ("o", "s", "^", "D")


class ComparisonError(ValueError):
    """The two EventSets cannot be compared."""


def annual_outcomes(
    es: EventSet, values: NDArray[np.float64], how: str
) -> NDArray[np.float64]:
    """Aggregate per-row values into (year, draw_id) outcomes.

    Parameters
    ----------
    es : EventSet
        The EventSet; ``draw_id`` must run over ``0 .. n_draws - 1`` and every
        rate must be ``1 / (n_years * n_draws)``.
    values : numpy.ndarray
        ``(n_rows, n_locations)`` per-row values (loss or index).
    how : {"sum", "max"}
        Sum the rows of an outcome, or take their maximum. Outcomes without
        rows are 0 either way (no storm: no loss, index 0).

    Returns
    -------
    numpy.ndarray
        ``(n_years * n_draws, n_locations)``; row ``year * n_draws + draw``.

    Raises
    ------
    ComparisonError
        If the draws are not ``0 .. n - 1``, the rates differ from
        ``1 / (n_years * n_draws)``, a value is negative, or ``how`` is
        unknown.
    """
    draw = es.events["draw_id"].to_numpy(dtype=np.int64)
    year = es.events["year"].to_numpy(dtype=np.int64)
    n_draws = int(draw.max()) + 1
    if sorted(set(draw.tolist())) != list(range(n_draws)):
        raise ComparisonError("draw_id must run over 0 .. n_draws - 1")
    n_years = es.metadata.n_years
    expected = 1.0 / (n_years * n_draws)
    if not np.allclose(es.rates, expected, rtol=RATE_RTOL, atol=0.0):
        raise ComparisonError(
            f"rates must all be 1 / (n_years * n_draws) = {expected:.6g} so "
            "that the (year, draw) outcomes are equally likely"
        )
    if (values < 0).any():
        raise ComparisonError("values must be non-negative")
    out = np.zeros((n_years * n_draws, values.shape[1]))
    rows = year * n_draws + draw
    if how == "sum":
        np.add.at(out, rows, values)
    elif how == "max":
        np.maximum.at(out, rows, values)
    else:
        raise ComparisonError(f"unknown aggregation {how!r}")
    return out


def return_levels(
    outcomes: NDArray[np.float64], return_periods: Sequence[float]
) -> NDArray[np.float64]:
    """Return the empirical return levels of equally likely outcomes.

    Parameters
    ----------
    outcomes : numpy.ndarray
        ``(n_outcomes, n)`` annual values.
    return_periods : sequence of float
        Return periods ``T`` in years, each in ``[1, n_outcomes]``.

    Returns
    -------
    numpy.ndarray
        ``(len(return_periods), n)``: the quantile at ``1 - 1/T`` with
        ``method="higher"``.

    Raises
    ------
    ComparisonError
        If a return period lies outside ``[1, n_outcomes]``.
    """
    n = outcomes.shape[0]
    periods = np.asarray(return_periods, dtype=np.float64)
    if (periods < 1).any() or (periods > n).any():
        raise ComparisonError(f"return periods must lie in [1, {n}] years")
    return np.quantile(outcomes, 1.0 - 1.0 / periods, axis=0, method="higher")


def _describe(es: EventSet, path: Path) -> dict[str, Any]:
    meta = es.metadata
    return {
        "eventset": path.name,
        "content_hash": es.content_hash(),
        "hazard": meta.hazard.name,
        "hazard_release": meta.hazard.release,
        "scenario_id": sorted(es.events["scenario_id"].unique().tolist()),
        "n_years": meta.n_years,
        "n_rows": es.n_rows,
        "n_draws": int(es.events["draw_id"].max()) + 1,
        "index": {"unit": meta.index.unit, "definition": meta.index.definition},
        "loss_unit": meta.loss.unit,
        "licence": meta.licence,
    }


def compare(
    reference: EventSet,
    scenario: EventSet,
    return_periods: Sequence[int] = DEFAULT_RETURN_PERIODS,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """Compute the return levels of both EventSets.

    Parameters
    ----------
    reference, scenario : EventSet
        The two EventSets, with the same location IDs and loss unit.
    return_periods : sequence of int
        Return periods in years.

    Returns
    -------
    tuple
        The long table (:data:`METRICS` per location and return period,
        plus the portfolio annual loss) and the portfolio annual-loss
        exceedance curves (``{"reference": ..., "scenario": ...}``, columns
        ``return_period`` and ``annual_loss``).

    Raises
    ------
    ComparisonError
        If the locations or the loss units differ, or see
        :func:`annual_outcomes` and :func:`return_levels`.
    """
    ids = reference.location_ids
    if sorted(ids) != sorted(scenario.location_ids):
        raise ComparisonError("the two EventSets have different locations")
    if reference.metadata.loss.unit != scenario.metadata.loss.unit:
        raise ComparisonError(
            f"loss units differ: {reference.metadata.loss.unit!r} and "
            f"{scenario.metadata.loss.unit!r}"
        )
    if reference.metadata.index.unit != scenario.metadata.index.unit:
        raise ComparisonError(
            f"index units differ: {reference.metadata.index.unit!r} and "
            f"{scenario.metadata.index.unit!r}"
        )
    scenario = scenario.select_locations(ids)
    names = reference.locations.set_index("location_id")["name"].astype(str)
    parts: list[pd.DataFrame] = []
    curves: dict[str, pd.DataFrame] = {}
    for metric in METRICS:
        levels = {}
        for key, es in (("reference", reference), ("scenario", scenario)):
            if metric == "annual_loss":
                annual = annual_outcomes(es, es.loss, "sum")
                total = annual.sum(axis=1, keepdims=True)
                annual = np.hstack([annual, total])
                ranked = np.sort(total[:, 0])[::-1]
                curves[key] = pd.DataFrame(
                    {
                        "return_period": len(ranked) / np.arange(1, len(ranked) + 1),
                        "annual_loss": ranked,
                    }
                )
            else:
                annual = annual_outcomes(es, es.index, "max")
            levels[key] = return_levels(annual, return_periods)
        columns = [*ids, PORTFOLIO] if metric == "annual_loss" else list(ids)
        for r, period in enumerate(return_periods):
            ref = levels["reference"][r]
            sce = levels["scenario"][r]
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(ref > 0, sce / np.where(ref > 0, ref, 1.0), np.nan)
            parts.append(
                pd.DataFrame(
                    {
                        "metric": metric,
                        "location_id": columns,
                        "name": [
                            PORTFOLIO if c == PORTFOLIO else names[c] for c in columns
                        ],
                        "return_period": int(period),
                        "reference": ref,
                        "scenario": sce,
                        "ratio": ratio,
                    }
                )
            )
    return pd.concat(parts, ignore_index=True), curves


def summarise(table: pd.DataFrame) -> list[dict[str, Any]]:
    """Count, per metric and return period, where the scenario is above.

    Parameters
    ----------
    table : pandas.DataFrame
        Output of :func:`compare`; the portfolio row is left out.

    Returns
    -------
    list of dict
        One entry per (metric, return period): locations with the scenario
        level above, equal to and below the reference, and the median ratio
        over the locations with a positive reference.
    """
    out = []
    rows = table.loc[table["location_id"] != PORTFOLIO]
    keys = rows[["metric", "return_period"]].drop_duplicates()
    for metric, period in zip(
        keys["metric"].tolist(), keys["return_period"].tolist(), strict=True
    ):
        mask = (rows["metric"] == metric) & (rows["return_period"] == period)
        ref = rows.loc[mask, "reference"].to_numpy(dtype=np.float64)
        sce = rows.loc[mask, "scenario"].to_numpy(dtype=np.float64)
        ratio = rows.loc[mask, "ratio"].to_numpy(dtype=np.float64)
        ratio = ratio[np.isfinite(ratio)]
        out.append(
            {
                "metric": str(metric),
                "return_period": int(period),
                "n_locations": int(mask.sum()),
                "scenario_above": int((sce > ref).sum()),
                "equal": int((sce == ref).sum()),
                "scenario_below": int((sce < ref).sum()),
                "median_ratio": float(np.median(ratio)) if ratio.size else None,
                "n_reference_zero": int((ref == 0).sum()),
            }
        )
    return out


def plot(
    table: pd.DataFrame,
    curves: dict[str, pd.DataFrame],
    labels: tuple[str, str],
    units: tuple[str, str],
    out: Path,
    attribution: str = "",
) -> None:
    """Draw the three-panel comparison figure.

    Parameters
    ----------
    table : pandas.DataFrame
        Output of :func:`compare`.
    curves : dict
        Portfolio exceedance curves from :func:`compare`.
    labels : tuple of str
        Reference and scenario labels (e.g. ``("IRIS", "STORM")``).
    units : tuple of str
        Loss unit and index unit.
    out : pathlib.Path
        PNG file to write.
    attribution : str, optional
        Data attribution printed under the panels.
    """
    ref_label, sce_label = labels
    loss_unit, index_unit = units
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.6), layout="constrained")
    engine = fig.get_layout_engine()
    if attribution and isinstance(engine, ConstrainedLayoutEngine):
        engine.set(rect=(0, 0.07, 1, 0.93))
        fig.text(0.005, 0.005, attribution, fontsize=7, color=INK_2, wrap=True)
    periods = sorted(table["return_period"].unique().tolist())
    counties = table[table["location_id"] != PORTFOLIO]
    for ax, metric, title, unit, log in (
        (axes[0], "annual_loss", "(a) County annual loss", loss_unit, True),
        (
            axes[1],
            "annual_max_index",
            "(b) County annual maximum index",
            index_unit,
            False,
        ),
    ):
        rows = cast(pd.DataFrame, counties.loc[counties["metric"] == metric])
        if log:
            positive = (rows["reference"] > 0) & (rows["scenario"] > 0)
            hidden = int((~positive).sum())
            if hidden:
                ax.text(
                    0.98,
                    0.02,
                    f"{hidden} (county, period) pair(s) with a zero level not shown",
                    transform=ax.transAxes,
                    ha="right",
                    fontsize=7,
                    color=INK_2,
                )
            rows = cast(pd.DataFrame, rows.loc[positive])
        for k, period in enumerate(periods):
            sel = rows[rows["return_period"] == period]
            ax.scatter(
                sel["reference"],
                sel["scenario"],
                s=28,
                color=ORDINAL[k % len(ORDINAL)],
                marker=MARKERS[k % len(MARKERS)],
                edgecolors="white",
                linewidths=0.6,
                label=f"{period}-year",
                zorder=3,
            )
        values = np.concatenate(
            [
                rows["reference"].to_numpy(dtype=np.float64),
                rows["scenario"].to_numpy(dtype=np.float64),
            ]
        )
        if values.size:
            low, high = float(values.min()), float(values.max())
            if log:
                ax.set_xscale("log")
                ax.set_yscale("log")
                low /= 1.5
                high *= 1.5
            else:
                pad = 0.05 * (high - low or 1.0)
                low, high = low - pad, high + pad
            ax.plot([low, high], [low, high], color=INK_2, lw=1, ls="--", zorder=2)
            ax.set_xlim(low, high)
            ax.set_ylim(low, high)
        ax.set_xlabel(f"{ref_label} return level ({unit})", color=INK)
        ax.set_ylabel(f"{sce_label} return level ({unit})", color=INK)
        ax.set_title(title, loc="left", color=INK)
        ax.grid(color=GRID, lw=0.6)
        ax.legend(title="Return period", frameon=False, fontsize=8)
    ax = axes[2]
    for (key, label), color in zip(
        (("reference", ref_label), ("scenario", sce_label)), SERIES, strict=True
    ):
        curve = curves[key]
        curve = curve[curve["annual_loss"] > 0]
        ax.plot(
            curve["return_period"], curve["annual_loss"], color=color, lw=2, label=label
        )
    ax.set_xscale("log")
    ax.set_yscale("log")
    for period in periods:
        ax.axvline(period, color=GRID, lw=0.8, zorder=0)
    ax.set_xlabel("Return period (years)", color=INK)
    ax.set_ylabel(f"Portfolio annual loss ({loss_unit})", color=INK)
    ax.set_title("(c) Portfolio annual-loss exceedance", loc="left", color=INK)
    ax.grid(color=GRID, lw=0.6, which="major")
    ax.legend(frameon=False)
    fig.savefig(out, dpi=150)
    plt.close(fig)


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point; see the module docstring.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        0 on success, 1 if the EventSets cannot be read or compared.
    """
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--return-periods",
        type=int,
        nargs="+",
        default=list(DEFAULT_RETURN_PERIODS),
    )
    parser.add_argument(
        "--attribution", default="", help="data attribution printed on the figure"
    )
    args = parser.parse_args(argv)
    try:
        reference = EventSet.from_parquet(args.reference)
        scenario = EventSet.from_parquet(args.scenario)
        table, curves = compare(reference, scenario, args.return_periods)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    table.to_csv(out_dir / "return_levels.csv", index=False, float_format="%.10g")
    ref_meta, sce_meta = reference.metadata, scenario.metadata
    summary = {
        "issue": "MAR-32",
        "rule": (
            "return level at T years = empirical quantile of the annual value at "
            "1 - 1/T (numpy method 'higher') over equally likely (year, draw_id) "
            "outcomes; years without a row are 0"
        ),
        "metrics": {
            "annual_loss": "sum of the location's losses over the year's rows",
            "annual_max_index": "largest index value of the year",
        },
        "return_periods": [int(t) for t in args.return_periods],
        "reference": _describe(reference, args.reference),
        "scenario": _describe(scenario, args.scenario),
        "portfolio_eal": {
            "reference": float(reference.rates @ reference.loss.sum(axis=1)),
            "scenario": float(scenario.rates @ scenario.loss.sum(axis=1)),
        },
        "counts": summarise(table),
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    plot(
        table,
        curves,
        (ref_meta.hazard.name, sce_meta.hazard.name),
        (ref_meta.loss.unit, ref_meta.index.unit),
        out_dir / "return_levels.png",
        args.attribution,
    )
    print(f"wrote {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
