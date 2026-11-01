"""MAR-198: committed tables of the individual-scope ranges.

Reads the full tables of ``individual_nonuniqueness.py`` for its two methods
(not committed): ``--free`` (``--method free_bins``: the exact optimal set's
free bins, tolerance 0) and ``--near`` (``--method near_optimal_set``: C1
T11's tolerance; the pure MSE group may come from a separate directory,
``--near-extra``). Writes the committed CSVs, ``summary_<method>.json`` and
``tables.md`` to ``research/data/individual-nonuniqueness/``. Run from the
repository root::

    uv run python research/scripts/individual_nonuniqueness_tables.py \
        --free results/mar198/free --near results/mar198/near

Observations only.
"""

# ruff: noqa: RUF001
# (tables use typographic minus and en dash)

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any, Final

import pandas as pd

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
FREE_DIR: Final[Path] = REPO_ROOT / "results" / "mar198" / "free"
NEAR_DIR: Final[Path] = REPO_ROOT / "results" / "mar198" / "near"
METHOD_NAMES: Final[dict[str, str]] = {
    "free_bins": "free bins (exact optimal designs, tolerance 0)",
    "near_optimal": "near-optimal set (C1 T11's tolerance 1e-5)",
}
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "individual-nonuniqueness"
DESIGN_NAMES: Final[dict[str, str]] = {
    "mse": "MSE",
    "eu": "E[U]",
    "wcvar@0.99": "wCVaR β 0.99",
    "wcvar@0.995": "wCVaR β 0.995",
}
PRICING_NAMES: Final[dict[str, str]] = {"pure": "pure", "coc_r0.06": "CoC r 0.06"}
KPI_NAMES: Final[dict[str, str]] = {
    "eu": "E[U]",
    "cvar@0.95": "CVaR₀.₉₅",
    "cvar@0.99": "CVaR₀.₉₉",
    "cvar@0.995": "CVaR₀.₉₉₅",
}
MATCHED: Final[dict[str, str]] = {
    "wcvar@0.99": "cvar@0.99",
    "wcvar@0.995": "cvar@0.995",
}
"""The KPI that matches a tail design's beta (MAR-182 section 4)."""


def h12(value: str) -> str:
    """First 12 hex digits of a ``sha256:`` config hash."""
    return str(value).removeprefix("sha256:")[:12]


def money(x: float) -> str:
    """Format USD with thousands separators."""
    return "n/a" if pd.isna(x) else f"{x:,.0f}"


def pct(x: float, digits: int = 1) -> str:
    """Format a ratio as a signed percentage."""
    return "n/a" if pd.isna(x) else f"{100 * x:+.{digits}f} %"


def excludes_zero(lo: float, hi: float) -> bool:
    """Whether a finite interval excludes zero."""
    return bool(not (pd.isna(lo) or pd.isna(hi)) and (lo > 0 or hi < 0))


def verdict(lo: float, hi: float) -> str:
    """``<0``, ``>0`` or ``0 in`` for an interval (``-`` if none)."""
    if pd.isna(lo) or pd.isna(hi):
        return "-"
    if hi < 0:
        return "<0"
    if lo > 0:
        return ">0"
    return "0 in"


def md_table(header: list[str], rows: list[list[str]]) -> str:
    """Return a Markdown table."""
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


def t1_ranges(ranges: pd.DataFrame) -> str:
    """T1: the range per design, KPI and split (C1 main line)."""
    c1 = ranges.loc[ranges["setup"] == "c1"]
    rows: list[list[str]] = []
    for r in c1.itertuples():
        stored = float(r.stored)  # type: ignore[arg-type]
        lo, hi = float(r.min), float(r.max_found)  # type: ignore[arg-type]
        rows.append(
            [
                PRICING_NAMES[str(r.pricing)],
                DESIGN_NAMES[str(r.design)],
                str(r.split),
                KPI_NAMES[str(r.kpi)],
                money(stored),
                f"{money(lo)} – {money(hi)}",
                f"{pct(lo / stored - 1, 2)} / {pct(hi / stored - 1, 2)}",
                pct((hi - lo) / stored, 2),
                money(float(r.outer_bound_max)),  # type: ignore[arg-type]
                pct(float(r.alt_solver) / stored - 1, 2),  # type: ignore[arg-type]
                f"`{h12(str(r.config_hash))}`",
            ]
        )
    header = [
        "Pricing",
        "Design",
        "Split",
        "KPI",
        "C1 (stored)",
        "Range [min – max found]",
        "Ends vs stored",
        "Width / stored",
        "Outer bound on max",
        "Alt. solver vs stored",
        "Hash",
    ]
    return md_table(header, rows)


def t2_mar165(ranges: pd.DataFrame) -> str:
    """T2: the MAR-165 check."""
    v = ranges.loc[ranges["setup"].str.startswith("mar165")]
    rows = [
        [
            str(r.setup).removeprefix("mar165_").replace("_", " "),
            str(r.split),
            KPI_NAMES[str(r.kpi)],
            money(float(r.stored)),  # type: ignore[arg-type]
            f"{money(float(r.min))} – {money(float(r.max_found))}",  # type: ignore[arg-type]
            money(float(r.outer_bound_max)),  # type: ignore[arg-type]
            money(float(r.alt_solver)),  # type: ignore[arg-type]
            f"`{h12(str(r.config_hash))}`",
        ]
        for r in v.itertuples()
    ]
    header = [
        "Threshold filter",
        "Split",
        "KPI",
        "Default policy",
        "Range [min – max found]",
        "Outer bound",
        "Alt. solver",
        "Hash",
    ]
    return md_table(header, rows)


def t3_assets(assets: pd.DataFrame) -> str:
    """T3: per-asset train E[pi_i]/E[L_i] ranges, individual scope."""
    c1 = assets.loc[assets["setup"] == "c1"]
    groups = list(dict.fromkeys(zip(c1["pricing"], c1["design"], strict=True)))
    header = ["Asset"] + [f"{PRICING_NAMES[p]} {DESIGN_NAMES[d]}" for p, d in groups]
    rows: list[list[str]] = []
    for asset in sorted(c1["entity_id"].unique()):
        row = [asset]
        for p, d in groups:
            r = c1.loc[
                (c1["entity_id"] == asset) & (c1["pricing"] == p) & (c1["design"] == d)
            ].iloc[0]
            row.append(
                f"{r['stored_payout_to_loss']:.2f} "
                f"[{r['min_payout_to_loss']:.2f}, {r['max_payout_to_loss']:.2f}]"
            )
        rows.append(row)
    move = ["largest θ change / cap"]
    for p, d in groups:
        g = c1.loc[(c1["pricing"] == p) & (c1["design"] == d)]
        move.append(f"{g['max_param_change_to_cap'].max():.3f}")
    rows.append(move)
    return md_table(header, rows)


def _end_cells(sub: pd.DataFrame, value: str, base: str | None) -> dict[str, str]:
    """Cells for stored / min / max rows of one comparison."""
    out: dict[str, str] = {}
    for end in sub["individual_at"]:
        r = sub.loc[sub["individual_at"] == end].iloc[0]
        ref = r[base] if base else math.nan
        rel = r[value] / ref if base else math.nan
        txt = pct(rel) if base else money(r[value])
        if not pd.isna(r["ci_low"]):
            lo = r["ci_low"] / ref if base else r["ci_low"]
            hi = r["ci_high"] / ref if base else r["ci_high"]
            star = "*" if excludes_zero(r["ci_low"], r["ci_high"]) else ""
            if base:
                txt += f"{star} [{100 * lo:+.1f}, {100 * hi:+.1f}]"
            else:
                txt += f"{star} [{money(lo)}, {money(hi)}]"
        out[str(end)] = txt
    return out


def t4_rq2(rq2: pd.DataFrame, kpis: tuple[str, ...]) -> str:
    """T4: C1 6b's joint - individual differences at the range ends."""
    rows: list[list[str]] = []
    for (pricing, design, scope, kpi, split), sub in rq2.groupby(
        ["pricing", "design", "scope_a", "kpi", "split"], sort=False
    ):
        if kpi not in kpis:
            continue
        cells = _end_cells(sub, "difference", "value_b")
        rows.append(
            [
                PRICING_NAMES[str(pricing)],
                DESIGN_NAMES[str(design)],
                str(scope),
                KPI_NAMES[str(kpi)],
                str(split),
                cells.get("stored", "-"),
                cells.get("min", "-"),
                cells.get("max", "-"),
                f"`{h12(sub['hash_b'].iloc[0])}` / `{h12(sub['hash_a'].iloc[0])}`",
            ]
        )
    header = [
        "Pricing",
        "Design",
        "Joint scope",
        "KPI",
        "Split",
        "Individual = C1 design",
        "Individual at its min",
        "Individual at its max found",
        "Hash individual / joint",
    ]
    return md_table(header, rows)


def t5_contrasts(con: pd.DataFrame, pricing: str, joint: str) -> str:
    """T5: MAR-182's contrasts at the ends (matched KPI and E[U])."""
    rows: list[list[str]] = []
    con = con.copy()
    roles = ["joint_scope", "tail_design", "base_design"]
    con[roles] = con[roles].fillna("")
    sel = con.loc[(con["pricing"] == pricing) & con["joint_scope"].isin([joint, ""])]
    for (contrast, tail, base, kpi, split), sub in sel.groupby(
        ["contrast", "tail_design", "base_design", "kpi", "split"], sort=False
    ):
        matched = MATCHED.get(str(tail), "cvar@0.99")
        if kpi not in (matched, "eu"):
            continue
        cells: dict[str, str] = {}
        for end in ("stored", "low", "high"):
            r = sub.loc[sub["individual_at"] == end]
            if r.empty:
                cells[end] = "-"
                continue
            r0 = r.iloc[0]
            txt = pct(r0["rel_value"])
            if not pd.isna(r0["ci_low"]):
                star = "*" if excludes_zero(r0["ci_low"], r0["ci_high"]) else ""
                txt += (
                    f"{star} [{100 * r0['rel_ci_low']:+.1f}, "
                    f"{100 * r0['rel_ci_high']:+.1f}]"
                )
            cells[end] = txt
        rows.append(
            [
                str(contrast),
                DESIGN_NAMES.get(str(tail), "–"),
                DESIGN_NAMES.get(str(base), "–"),
                KPI_NAMES[str(kpi)],
                str(split),
                cells["stored"],
                cells["low"],
                cells["high"],
            ]
        )
    header = [
        "Contrast",
        "Tail design W",
        "Base design O",
        "KPI",
        "Split",
        "Individual = C1 designs",
        "Individual terms at the low end",
        "… at the high end",
    ]
    return md_table(header, rows)


def changes(frame: pd.DataFrame, key: list[str], ends: tuple[str, str]) -> pd.DataFrame:
    """Rows whose interval verdict or point sign differs at an end."""
    test = frame.loc[frame["split"] == "test"].copy()
    test[key] = test[key].fillna("")
    test["verdict"] = [
        verdict(lo, hi) for lo, hi in zip(test["ci_low"], test["ci_high"], strict=True)
    ]
    val = "difference" if "difference" in test.columns else "value"
    test["sign"] = test[val].map(lambda x: "+" if x > 0 else "-" if x < 0 else "0")
    wide = test.pivot_table(
        index=key, columns="individual_at", values=["verdict", "sign"], aggfunc="first"
    )
    out = []
    for idx, r in wide.iterrows():
        v0 = r[("verdict", "stored")]
        s0 = r[("sign", "stored")]
        vs = {e: r[("verdict", e)] for e in ends}
        ss = {e: r[("sign", e)] for e in ends}
        if any(v != v0 for v in vs.values()) or any(s != s0 for s in ss.values()):
            out.append(
                dict(
                    zip(key, idx if isinstance(idx, tuple) else (idx,), strict=True),
                    verdict_stored=v0,
                    **{f"verdict_{e}": vs[e] for e in ends},
                    sign_stored=s0,
                    **{f"sign_{e}": ss[e] for e in ends},
                )
            )
    return pd.DataFrame(out)


def t3_free(assets: pd.DataFrame) -> str:
    """T3a: the free bins per asset (identical bins for every design)."""
    c1 = assets.loc[assets["setup"] == "c1"]
    groups = list(dict.fromkeys(zip(c1["pricing"], c1["design"], strict=True)))
    header = ["Asset", "Bins without a train row", "Their test rows", "MSE Hessian"]
    header += [f"{PRICING_NAMES[p]} {DESIGN_NAMES[d]}" for p, d in groups]
    rows: list[list[str]] = []
    for asset in sorted(c1["entity_id"].unique()):
        a = c1.loc[c1["entity_id"] == asset]
        first = a.iloc[0]
        free = first["free_bins"]
        row = [
            asset,
            "none" if pd.isna(free) else str(free),
            str(int(first["free_bins_test_rows"])),
            f"{first['mse_hessian_min_eig_rel_used_bins']:.4f}",
        ]
        for p, d in groups:
            r = a.loc[(a["pricing"] == p) & (a["design"] == d)].iloc[0]
            row.append(f"{r['free_param_width_to_cap']:.3f}")
        rows.append(row)
    return md_table(header, rows)


def method_parts(
    method: str, ranges: pd.DataFrame, rq2: pd.DataFrame, con: pd.DataFrame, out: Path
) -> list[str]:
    """Tables T1, T4, T5 and T6 of one method; write its change lists."""
    tag = {"free_bins": "a", "near_optimal": "b"}[method]
    rq2_key = ["pricing", "design", "scope_a", "kpi"]
    con_key = [
        "pricing",
        "contrast",
        "joint_scope",
        "tail_design",
        "base_design",
        "kpi",
    ]
    ch_rq2 = changes(rq2, rq2_key, ("min", "max"))
    ch_con = changes(con, con_key, ("low", "high"))
    ch_rq2.to_csv(out / f"rq2_changes_{method}.csv", index=False)
    ch_con.to_csv(out / f"contrasts_changes_{method}.csv", index=False)
    n_rq2 = len(rq2.loc[(rq2["split"] == "test") & (rq2["individual_at"] == "stored")])
    n_con = len(con.loc[(con["split"] == "test") & (con["individual_at"] == "stored")])
    name = METHOD_NAMES[method]
    parts = [
        f"## T1{tag}. Range of the individual scope's portfolio KPIs: {name}",
        "",
        t1_ranges(ranges),
        "",
        f"## T4{tag}. C1 section 6b, joint − individual at the range ends: {name}",
        "",
        "Relative to the individual design's value used in that column. Test: "
        "paired 90 % interval on the C1 resample of the test years. `min`: the "
        "individual design with the smallest value of the row's KPI (so the "
        "largest joint − individual difference); `max`: the largest found. "
        "CVaR₀.₉₅ rows are in the CSV.",
        "",
        t4_rq2(rq2, ("cvar@0.99", "cvar@0.995", "eu")),
        "",
    ]
    for pricing in ("pure", "coc_r0.06"):
        parts += [
            f"## T5{tag} ({PRICING_NAMES[pricing]}). MAR-182 contrasts, portfolio "
            f"scope, at the range ends: {name}",
            "",
            "Relative to MAR-182's reference (the individual baseline design's "
            "C1 value). `low`: every individual term at the end that lowers the "
            "contrast; `high`: the reverse. Matched KPI β and E[U]; every KPI and "
            "the cluster scope are in the CSV.",
            "",
            t5_contrasts(con, pricing, "portfolio"),
            "",
        ]
    parts += [
        f"## T6{tag}. Test intervals whose verdict or sign changes at a range end: "
        f"{name}",
        "",
        f"C1 section 6b (portfolio and cluster − individual): {len(ch_rq2)} of "
        f"{n_rq2} test rows (`rq2_changes_{method}.csv`). MAR-182 contrasts: "
        f"{len(ch_con)} of {n_con} test rows (`contrasts_changes_{method}.csv`). "
        "Verdict: `<0` / `>0` (interval excludes zero) or `0 in`.",
        "",
    ]
    for ch in (ch_rq2, ch_con):
        if len(ch):
            parts += [
                md_table(
                    list(ch.columns), [[str(x) for x in r] for r in ch.to_numpy()]
                ),
                "",
            ]
    return parts


def _read(dirs: list[Path], name: str) -> pd.DataFrame:
    """Concatenate one full table over directories (later ones replace groups)."""
    frames = [pd.read_csv(d / name) for d in dirs if (d / name).exists()]
    return pd.concat(frames, ignore_index=True)


def main(argv: list[str] | None = None) -> int:
    """Write the committed tables.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description="MAR-198 tables.")
    parser.add_argument("--free", type=Path, default=FREE_DIR)
    parser.add_argument("--near", type=Path, default=NEAR_DIR)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    tables: dict[str, dict[str, pd.DataFrame]] = {}
    for method, full in (("free_bins", args.free), ("near_optimal", args.near)):
        t = {
            n: pd.read_csv(full / f"{n}.csv")
            for n in ("ranges", "asset_ranges", "rq2_ends", "contrasts_ends")
        }
        tables[method] = t
        for n, frame in t.items():
            frame.to_csv(
                args.out / f"{n}_{method}.csv", index=False, float_format="%.8g"
            )
        summary: dict[str, Any] = json.loads((full / "summary.json").read_text())
        (args.out / f"summary_{method}.json").write_text(
            json.dumps(summary, indent=2) + "\n"
        )
    free, near = tables["free_bins"], tables["near_optimal"]
    parts = [
        "# MAR-198 tables: the individual scope's portfolio-level KPIs over its "
        "optimal set",
        "",
        "Generated by `research/scripts/individual_nonuniqueness_tables.py` from "
        "`individual_nonuniqueness.py`'s full tables. Thesis portfolio, annual "
        "basis, thesis noise layer, holdout (train years 0–6,999, test "
        "7,000–9,999), κ 1, step payout 15 bins (`first_bin`), C1 designs from "
        "the default solver policy. Two families of alternative individual "
        "designs: (a) **free bins**, every design that differs from the C1 one "
        "only in the parameters of bins without a train row (exactly optimal; "
        "for MSE the whole optimal set); (b) the **near-optimal set**, each "
        "asset's objective within 1e-5 (relative) of its optimum (C1 T11). "
        "Money in USD per year. Hashes: first 12 hex digits of the config hash. "
        "`*`: the paired 90 % interval excludes zero. Notes: "
        "`research/notes/individual-nonuniqueness.md`.",
        "",
        "## T2. The MAR-165 check (example config, no noise layer, `zero` below "
        "the attachment, E[U], pure, κ 1): near-optimal set",
        "",
        t2_mar165(near["ranges"]),
        "",
        "## T3a. Bins without a train row, per asset",
        "",
        "Bin numbers 0–14 (bin 12 is [60, 63.3) m/s, bin 13 [63.3, 66.7)). Their "
        "test rows (13 rows = one event in 13 noise copies). MSE Hessian: smallest "
        "over largest eigenvalue of the MSE Hessian on the used bins (> 0: the "
        "MSE optimum is unique there). Design columns: the widest free "
        "parameter range relative to the asset's cap.",
        "",
        t3_free(free["asset_ranges"]),
        "",
        "## T3b. Per-asset train E[π_i] / E[L_i] over each asset's near-optimal set",
        "",
        "C1 design, and in brackets the smallest and largest value over the set "
        "(T11's measure, individual scope). Last row: the largest change of any "
        "asset's payout parameter, relative to its cap, between the C1 design "
        "and any design found.",
        "",
        t3_assets(near["asset_ranges"]),
        "",
    ]
    for method, t in tables.items():
        parts += method_parts(
            method, t["ranges"], t["rq2_ends"], t["contrasts_ends"], args.out
        )
    (args.out / "tables.md").write_text("\n".join(parts))
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
