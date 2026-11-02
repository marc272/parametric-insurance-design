"""MAR-206: committed tables of the C1 RQ2 sensitivities.

Reads the full tables of ``c1_rq2_sensitivities.py`` (``--full``, default
``results/c1-rq2-sensitivities/``, not committed) and, for family (e),
MAR-198's full results (``--mar198``). Writes the committed CSVs (each well
under 500 kB) and ``tables.md`` to ``research/data/c1-rq2-sensitivities/``.
A family whose full tables are missing is skipped. Run from the repository
root::

    uv run python research/scripts/c1_rq2_sensitivities_tables.py

Observations only.
"""

# ruff: noqa: RUF001, E501
# (tables use typographic minus and en dash; long Markdown cells)

from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
FULL_DIR: Final[Path] = REPO_ROOT / "results" / "c1-rq2-sensitivities"
OUT_DIR: Final[Path] = REPO_ROOT / "research" / "data" / "c1-rq2-sensitivities"
C1_RQ2: Final[Path] = REPO_ROOT / "research" / "data" / "c1-rq2"
MAR198_DIR: Final[Path] = Path(
    os.environ.get("MAR198_FULL", str(REPO_ROOT / "results" / "mar198"))
)
DESIGN_NAMES: Final[dict[str, str]] = {
    "mse": "MSE",
    "eu": "E[U]",
    "wcvar@0.95": "wCVaR β 0.95",
    "wcvar@0.97": "wCVaR β 0.97",
    "wcvar@0.98": "wCVaR β 0.98",
    "wcvar@0.99": "wCVaR β 0.99",
    "wcvar@0.995": "wCVaR β 0.995",
}
PRICING_NAMES: Final[dict[str, str]] = {
    "pure": "pure",
    "coc_r0.06": "CoC r 0.06",
    "coc_r0.10": "CoC r 0.10",
}
KPI_NAMES: Final[dict[str, str]] = {
    "eu": "E[U]",
    "cvar@0.95": "CVaR₀.₉₅",
    "cvar@0.99": "CVaR₀.₉₉",
    "cvar@0.995": "CVaR₀.₉₉₅",
}


def h12(value: str) -> str:
    """Return the first 12 hex digits of a ``sha256:`` config hash."""
    return str(value).split(":", 1)[-1][:12]


def money(x: float) -> str:
    """Format a money amount."""
    return "n/a" if not np.isfinite(x) else f"{x:,.0f}"


def pct(x: float, digits: int = 1) -> str:
    """Format a relative difference with a typographic minus."""
    if not np.isfinite(x):
        return "n/a"
    s = f"{100 * x:+.{digits}f} %"
    return s.replace("-", "−")


def num(x: float, digits: int = 2) -> str:
    """Format a ratio."""
    return "n/a" if not np.isfinite(x) else f"{x:.{digits}f}"


def excludes_zero(lo: float, hi: float) -> bool:
    """Whether an interval excludes zero."""
    return bool(np.isfinite(lo) and np.isfinite(hi) and (lo > 0 or hi < 0))


def rel_cell(diff: float, base: float, lo: float, hi: float) -> str:
    """``-12.3 % [-20.1, -1.2]*`` (relative to ``base``)."""
    if not np.isfinite(diff):
        return "n/a"
    star = "*" if excludes_zero(lo, hi) else ""
    return f"{pct(diff / base)}{star} [{pct(lo / base)[:-2]}, {pct(hi / base)[:-2]}]"


def md_table(header: list[str], rows: list[list[str]]) -> str:
    """Return a Markdown table."""
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


def kpi_label(kpi: str, beta: float) -> str:
    """Return the KPI label of a KPI table row."""
    return "eu" if kpi == "expected_uncovered" else f"cvar@{beta:g}"


# --------------------------------------------------------------------------
# (a) the optimal_inaccurate range programs
# --------------------------------------------------------------------------


def family_a(full: Path, out: Path) -> str | None:
    """Tables of phase (a)."""
    path = full / "inaccurate.csv"
    if not path.exists():
        return None
    t = pd.read_csv(path)
    t.to_csv(out / "a_inaccurate.csv", index=False, float_format="%.10g")
    c1r = pd.read_csv(C1_RQ2 / "payout_ranges.csv")
    rows = []
    best_rows = []
    for (pricing, design, scope, ent), sub in t.groupby(
        ["pricing", "design", "scope", "entity_id"], sort=False
    ):
        c1row = c1r.loc[
            (c1r["pricing"] == pricing)
            & (c1r["design"] == design)
            & (c1r["scope"] == scope)
            & (c1r["entity_id"] == ent)
        ].iloc[0]
        ends: dict[str, str] = {}
        for sense in ("min", "max"):
            s = sub.loc[sub["sense"] == sense]
            ok = s.loc[s["in_set"].astype(bool)]
            for r in s.itertuples():
                rows.append(
                    [
                        PRICING_NAMES[pricing],
                        DESIGN_NAMES[design],
                        scope,
                        ent,
                        sense,
                        f"{r.solver} / {r.form}",
                        str(r.status),
                        num(r.ratio, 3),
                        "yes" if r.in_set else "no",
                        f"{r.objective_excess:.2e}"
                        if np.isfinite(r.objective_excess)
                        else "n/a",
                        f"{r.seconds:.0f}",
                    ]
                )
            if len(ok):
                pick = ok["ratio"].idxmin() if sense == "min" else ok["ratio"].idxmax()
                v = ok.loc[pick]
                ends[sense] = f"{v['ratio']:.2f} ({v['solver']} / {v['form']})"
            else:
                ends[sense] = "none in the set"
        best_rows.append(
            [
                PRICING_NAMES[pricing],
                DESIGN_NAMES[design],
                scope,
                ent,
                num(c1row["stored_payout_to_loss"]),
                f"[{num(c1row['min_payout_to_loss'])}, "
                f"{num(c1row['max_payout_to_loss'])}]",
                ends["min"],
                ends["max"],
                f"`{h12(sub['config_hash'].iloc[0])}`",
            ]
        )
    md = [
        "## A1. The C1 T11 range programs that ended `optimal_inaccurate`, re-solved",
        "",
        "Train E[π_j]/E[L_j] of entity j over the joint design's near-optimal set "
        "(objective within 1e-5 of the optimum, κ 1). C1 T11: the stored value and "
        "its range, `n/a` where CLARABEL ended `optimal_inaccurate`. Re-solved: the "
        "smallest (largest) value among the solutions that pass the numpy check "
        "(objective within 1e-5 + 1e-6, budget, payout structure), and the solver "
        "and form that found it. `compact`: the MSE constraint in its exact "
        "135-parameter form, scaled to a right-hand side of 1.",
        "",
        md_table(
            [
                "Pricing",
                "Design",
                "Scope",
                "Entity",
                "Stored",
                "C1 T11 range",
                "Smallest found",
                "Largest found",
                "Hash",
            ],
            best_rows,
        ),
        "",
        "## A2. Every program",
        "",
        md_table(
            [
                "Pricing",
                "Design",
                "Scope",
                "Entity",
                "End",
                "Solver / form",
                "Status",
                "E[π_j]/E[L_j]",
                "In the set",
                "Objective excess",
                "Seconds",
            ],
            rows,
        ),
    ]
    return "\n".join(md)


# --------------------------------------------------------------------------
# (b) non-unique joint designs in the within-scope comparisons
# --------------------------------------------------------------------------

COMBO_NAMES: Final[dict[tuple[str, str], str]] = {
    ("stored", "stored"): "C1",
    ("alt", "stored"): "alt / C1",
    ("stored", "alt"): "C1 / alt",
    ("alt", "alt"): "alt / alt",
    ("free_hi", "free_lo"): "free low end",
    ("free_lo", "free_hi"): "free high end",
}


def family_b(full: Path, out: Path) -> str | None:
    """Tables of phase (b)."""
    if not (full / "nonunique_paired.csv").exists():
        return None
    paired = pd.read_csv(full / "nonunique_paired.csv")
    designs = pd.read_csv(full / "nonunique_designs.csv")
    entities = pd.read_csv(full / "nonunique_entities.csv")
    alloc = pd.read_csv(full / "nonunique_allocation.csv")
    tail = paired.loc[
        paired["kpi"].isin(["cvar_uncovered", "expected_uncovered"])
    ].copy()
    tail["label"] = [
        kpi_label(k, b) for k, b in zip(tail["kpi"], tail["eval_beta"], strict=True)
    ]
    tail = tail.loc[
        ~((tail["kpi"] == "expected_uncovered") & (tail["eval_beta"] != 0.99))
    ]
    tail["excludes_zero"] = [
        excludes_zero(lo, hi)
        for lo, hi in zip(tail["ci_low"], tail["ci_high"], strict=True)
    ]
    keep = [
        "family",
        "pricing",
        "kappa",
        "scope",
        "design_a",
        "design_b",
        "label",
        "variant_a",
        "variant_b",
        "value_a",
        "value_b",
        "difference",
        "ci_low",
        "ci_high",
        "excludes_zero",
        "config_hash_a",
        "config_hash_b",
    ]
    tail[keep].to_csv(out / "b_within_scope.csv", index=False, float_format="%.10g")
    designs.to_csv(out / "b_designs.csv", index=False, float_format="%.6g")
    entities.to_csv(out / "b_free_bins.csv", index=False, float_format="%.6g")
    # verdict changes against the C1 designs
    key = ["family", "pricing", "kappa", "scope", "design_a", "design_b", "label"]
    base = tail.loc[(tail["variant_a"] == "stored") & (tail["variant_b"] == "stored")]
    base = base.set_index(key)[["difference", "ci_low", "ci_high", "excludes_zero"]]
    other = tail.loc[
        ~((tail["variant_a"] == "stored") & (tail["variant_b"] == "stored"))
    ]
    m = other.join(base, on=key, rsuffix="_c1")
    m["changed"] = m["excludes_zero"] != m["excludes_zero_c1"]
    m["sign_changed"] = np.sign(m["difference"]) != np.sign(m["difference_c1"])
    changes = m.loc[m["changed"]]
    changes[
        [
            *key,
            "variant_a",
            "variant_b",
            "difference",
            "ci_low",
            "ci_high",
            "difference_c1",
            "ci_low_c1",
            "ci_high_c1",
            "value_b",
            "config_hash_a",
            "config_hash_b",
        ]
    ].to_csv(out / "b_changes.csv", index=False, float_format="%.10g")
    md: list[str] = []
    # B1: counts
    rows = []
    for combo, name in COMBO_NAMES.items():
        if combo == ("stored", "stored"):
            continue
        s = m.loc[(m["variant_a"] == combo[0]) & (m["variant_b"] == combo[1])]
        for fam in ("main", "reference"):
            f = s.loc[s["family"] == fam]
            if not len(f):
                continue
            rows.append(
                [
                    name,
                    fam,
                    str(len(f)),
                    str(int((f["excludes_zero_c1"] & ~f["excludes_zero"]).sum())),
                    str(int((~f["excludes_zero_c1"] & f["excludes_zero"]).sum())),
                    str(int(f["sign_changed"].sum())),
                ]
            )
    md += [
        "## B1. Within-scope comparisons whose interval verdict changes",
        "",
        "Weighted CVaR (every design β) minus MSE and minus E[U], cluster and "
        "portfolio scopes, test years, paired 90 % intervals on the C1 resample; "
        "KPIs CVaR at every KPI β of the family and E[U]. Each joint design is "
        "replaced by its second optimum (`alt`: `c1_rq2.ALT_POLICY`) or by an end of "
        "its free-bin family (low end: the weighted-CVaR design with every free "
        "parameter at its highest and the other design at its lowest, which gives "
        "the smallest difference over the two families; high end: the reverse). "
        "Cells: comparisons; of them, how many lose or gain an interval excluding "
        "zero against the C1 designs, and how many change sign.",
        "",
        md_table(
            [
                "Variant (wCVaR / other)",
                "Family",
                "Cells",
                "Lose exclusion",
                "Gain exclusion",
                "Sign changes",
            ],
            rows,
        ),
        "",
    ]
    # B2: the headline cells (kappa 1, wCVaR 0.99 at its own KPI and E[U])
    rows = []
    for fam, label in (
        ("main", "cvar@0.99"),
        ("main", "eu"),
        ("reference", "cvar@0.95"),
    ):
        design = "wcvar@0.99" if fam == "main" else "wcvar@0.95"
        for pricing in PRICING_NAMES:
            for scope in ("cluster", "portfolio"):
                for b in ("mse", "eu"):
                    s = tail.loc[
                        (tail["family"] == fam)
                        & (tail["pricing"] == pricing)
                        & (tail["kappa"] == 1.0)
                        & (tail["scope"] == scope)
                        & (tail["design_a"] == design)
                        & (tail["design_b"] == b)
                        & (tail["label"] == label)
                    ]
                    if not len(s):
                        continue
                    cells = []
                    for combo in COMBO_NAMES:
                        r = s.loc[
                            (s["variant_a"] == combo[0]) & (s["variant_b"] == combo[1])
                        ].iloc[0]
                        base_b = s.loc[
                            (s["variant_a"] == "stored") & (s["variant_b"] == "stored"),
                            "value_b",
                        ].iloc[0]
                        cells.append(
                            rel_cell(r["difference"], base_b, r["ci_low"], r["ci_high"])
                        )
                    rows.append(
                        [
                            fam,
                            PRICING_NAMES[pricing],
                            scope,
                            f"{DESIGN_NAMES[design]} − {DESIGN_NAMES[b]}",
                            KPI_NAMES[label],
                            *cells,
                            f"`{h12(s['config_hash_a'].iloc[0])}` / `{h12(s['config_hash_b'].iloc[0])}`",
                        ]
                    )
    md += [
        "## B2. The C1 section 3 and 4 cells, κ 1",
        "",
        "Relative to the C1 value of the other design (MSE or E[U]); `*`: the "
        "interval excludes zero. Main line: the headline design (β 0.99) at "
        "CVaR₀.₉₉ and E[U] (C1 sections 3.1–3.2). Reference: the event-conditional "
        "column at the thesis β 0.95 and KPI 0.95 (C1 section 4).",
        "",
        md_table(
            [
                "Family",
                "Pricing",
                "Scope",
                "Comparison",
                "KPI",
                *COMBO_NAMES.values(),
                "Hash wCVaR / other",
            ],
            rows,
        ),
        "",
    ]
    # B3: every change
    rows = []
    for r in changes.sort_values(key).itertuples():
        rows.append(
            [
                r.family,
                PRICING_NAMES[r.pricing],
                f"{r.kappa:g}",
                r.scope,
                f"{DESIGN_NAMES[r.design_a]} − {DESIGN_NAMES[r.design_b]}",
                KPI_NAMES[r.label],
                COMBO_NAMES[(r.variant_a, r.variant_b)],
                rel_cell(
                    r.difference_c1,
                    r.value_b,
                    r.ci_low_c1,
                    r.ci_high_c1,
                ),
                rel_cell(r.difference, r.value_b, r.ci_low, r.ci_high),
            ]
        )
    md += [
        "## B3. Every within-scope cell whose verdict changes",
        "",
        "Relative to the other design's value in that variant. `b_changes.csv` has "
        "the absolute values and both hashes.",
        "",
        md_table(
            [
                "Family",
                "Pricing",
                "κ",
                "Scope",
                "Comparison",
                "KPI",
                "Variant",
                "C1 designs",
                "Variant designs",
            ],
            rows,
        ),
        "",
    ]
    # B4: the second optima and free bins
    alt = designs.loc[designs["variant"] == "alt"]
    rows = []
    for (fam, pricing, scope), s in alt.groupby(
        ["family", "pricing", "scope"], sort=False
    ):
        rows.append(
            [
                fam,
                PRICING_NAMES[pricing],
                scope,
                str(len(s)),
                f"{s['objective_rel_diff'].min():.1e} to {s['objective_rel_diff'].max():.1e}",
                ", ".join(sorted(set(s["solver"]))),
                ", ".join(sorted(set(s["status"]))),
            ]
        )
    md += [
        "## B4. The second optima (`alt`)",
        "",
        "Train objective of the `alt` design relative to the C1 design's "
        "(numpy recomputation), every κ and design.",
        "",
        md_table(
            [
                "Family",
                "Pricing",
                "Scope",
                "Designs",
                "Objective rel. diff.",
                "Solvers",
                "Status",
            ],
            rows,
        ),
        "",
    ]
    ent = entities.copy()
    ent["n_free"] = ent["free_bins"].fillna("").astype(str).str.split().str.len()
    rows = []
    for (fam, pricing, scope), s in ent.groupby(
        ["family", "pricing", "scope"], sort=False
    ):
        per = s.groupby("entity_id")["n_free"].max()
        width = s.groupby("entity_id")["free_param_width_to_cap"].max()
        rows.append(
            [
                fam,
                PRICING_NAMES[pricing],
                scope,
                " ".join(f"{e}:{int(n)}" for e, n in per.items() if n > 0) or "none",
                f"{width.max():.3f}",
            ]
        )
    md += [
        "## B5. Free bins of the joint designs",
        "",
        "Entities with bins that hold no train row of their index (entity: number "
        "of free bins), and the largest free-parameter width relative to the "
        "entity's cap over every design and κ.",
        "",
        md_table(
            [
                "Family",
                "Pricing",
                "Scope",
                "Entities with free bins",
                "Largest width / cap",
            ],
            rows,
        ),
        "",
    ]
    md.append(t6_allocation(alloc, out))
    return "\n".join(md)


def t6_allocation(alloc: pd.DataFrame, out: Path) -> str:
    """C1 T6 re-derived with the named allocation rules."""
    a = alloc.loc[alloc["kpi"].isin(["expected_payout", "expected_loss"])].copy()
    a.to_csv(out / "b_t6_allocation.csv", index=False, float_format="%.10g")
    md = []
    for pricing in ("pure", "coc_r0.06"):
        for scope in ("portfolio", "cluster"):
            s = a.loc[
                (a["pricing"] == pricing)
                & (a["scope"] == scope)
                & (a["split"] == "train")
                & (a["kappa"] == 1.0)
            ]
            if not len(s):
                continue
            pv = s.pivot_table(
                index=["design", "variant", "allocation", "level", "subject_id"],
                columns="kpi",
                values="value",
            )
            pv["ratio"] = pv["expected_payout"] / pv["expected_loss"]
            assets = [f"A{i}" for i in range(1, 10)]
            rows = []
            for design in ("mse", "eu", "wcvar@0.99", "wcvar@0.995"):
                for var in ("stored", "alt"):
                    if scope == "portfolio":
                        r = pv.loc[(design, var, "value", "entity")]
                        rows.append(
                            [
                                DESIGN_NAMES[design],
                                var,
                                "solver split",
                                *(num(r.loc[x, "ratio"]) for x in assets),
                            ]
                        )
                    for rule in ("value", "loss"):
                        r = pv.loc[(design, var, rule, f"location_by_{rule}")]
                        rows.append(
                            [
                                DESIGN_NAMES[design],
                                var,
                                f"rule `{rule}`",
                                *(num(r.loc[x, "ratio"]) for x in assets),
                            ]
                        )
            md += [
                f"## T6′ ({PRICING_NAMES[pricing]}, {scope} scope). Train E[π_i]/E[L_i] per asset under a named allocation rule (κ 1)",
                "",
                "`rule value`: each design problem's payout split pro rata to insured "
                'value (`evaluate` `allocation="value"`); `rule loss`: pro rata to '
                'each asset\'s loss in every row (`allocation="loss"`). '
                + (
                    "`solver split`: the joint design's own per-asset payout (C1 T6). "
                    if scope == "portfolio"
                    else ""
                )
                + "`alt`: the second optimum (`c1_rq2.ALT_POLICY`).",
                "",
                md_table(["Design", "Optimum", "Split", *assets], rows),
                "",
            ]
    return "\n".join(md)


# --------------------------------------------------------------------------
# (c) the noise layer and (d) the cluster count
# --------------------------------------------------------------------------

NOISE_NAMES: Final[dict[str, str]] = {
    "per_asset": "per asset (C1)",
    "common": "common to all assets",
    "none": "none",
}
PAIR_NAMES: Final[dict[tuple[str, str], str]] = {
    ("portfolio", "individual"): "portfolio − individual",
    ("cluster", "individual"): "cluster − individual",
    ("cluster_sep", "individual"): "index part: cluster (joint: false) − individual",
    ("cluster", "cluster_sep"): "joint part: cluster − cluster (joint: false)",
    ("cluster", "portfolio"): "cluster − portfolio",
}
C1_SCOPE: Final[dict[str, str]] = {"cluster_separate": "cluster_sep"}


def _c1_noise_rows() -> pd.DataFrame:
    """C1's own rows (per-asset noise layer), kappa 1, in this family's shape."""
    p = pd.read_csv(C1_RQ2 / "scope_paired.csv")
    p = p.loc[(p["kappa"] == 1.0) & (p["split"].isin(["train", "test"]))].copy()
    p["scope_a"] = p["scope_a"].replace(C1_SCOPE)
    p["scope_b"] = p["scope_b"].replace(C1_SCOPE)
    p["variant"] = "per_asset"
    return p


def family_c(full: Path, out: Path) -> str | None:
    """Tables of phase (c)."""
    if not (full / "noise_paired.csv").exists():
        return None
    paired = pd.read_csv(full / "noise_paired.csv")
    kp = pd.read_csv(full / "noise_kpis.csv")
    runs = pd.read_csv(full / "noise_runs.csv")
    ents = pd.read_csv(full / "noise_entities.csv")
    keep = paired.loc[
        paired["kpi"].isin(
            ["cvar_uncovered", "expected_uncovered", "expected_payout", "premium"]
        )
    ]
    keep.drop(
        columns=[
            c
            for c in (
                "problem_id_a",
                "problem_id_b",
                "run_id_a",
                "run_id_b",
                "eval_split",
                "fold",
                "basis",
                "level",
                "subject_id",
                "beta",
                "ci_level",
                "n_bootstrap",
                "problem_id",
            )
            if c in keep.columns
        ]
    ).to_csv(out / "c_noise_paired.csv", index=False, float_format="%.10g")
    kp.loc[
        kp["kpi"].isin(
            [
                "cvar_uncovered",
                "expected_uncovered",
                "expected_payout",
                "expected_loss",
                "premium",
            ]
        ),
        [
            "family",
            "variant",
            "pricing",
            "design",
            "scope",
            "split",
            "eval_beta",
            "kpi",
            "value",
            "ci_low",
            "ci_high",
            "config_hash",
        ],
    ].to_csv(out / "c_noise_kpis.csv", index=False, float_format="%.10g")
    runs.to_csv(out / "c_noise_runs.csv", index=False, float_format="%.10g")
    ents.to_csv(out / "c_noise_entities.csv", index=False, float_format="%.10g")
    c1p = _c1_noise_rows()
    allp = pd.concat([paired.assign(kappa=1.0), c1p], ignore_index=True)
    md: list[str] = []
    for pricing in ("pure", "coc_r0.06"):
        rows = []
        for (a, b), pname in PAIR_NAMES.items():
            for design in ("mse", "eu", "wcvar@0.99", "wcvar@0.995"):
                cells = []
                for variant in NOISE_NAMES:
                    s = allp.loc[
                        (allp["variant"] == variant)
                        & (allp["pricing"] == pricing)
                        & (allp["design"] == design)
                        & (allp["scope_a"] == a)
                        & (allp["scope_b"] == b)
                        & (allp["kpi"] == "cvar_uncovered")
                        & (allp["eval_beta"] == 0.99)
                    ]
                    tr = s.loc[s["split"] == "train"]
                    te = s.loc[s["split"] == "test"]
                    if not len(tr) or not len(te):
                        cells += ["n/a", "n/a"]
                        continue
                    tr, te = tr.iloc[0], te.iloc[0]
                    cells.append(pct(tr["difference"] / tr["value_b"]))
                    cells.append(
                        rel_cell(
                            te["difference"], te["value_b"], te["ci_low"], te["ci_high"]
                        )
                    )
                rows.append([pname, DESIGN_NAMES[design], *cells])
        md += [
            f"## C1 ({PRICING_NAMES[pricing]}). Joint against individual calibration by noise layer, CVaR₀.₉₉(U), κ 1",
            "",
            "Relative to scope b. Train: in sample, point value; test: holdout test years, "
            "paired 90 % interval on the C1 resample. Per-asset noise: C1's runs "
            "(`research/data/c1-rq2/scope_paired.csv`; there the separately calibrated "
            "cluster designs are `cluster_separate`, a derived design with the same "
            "problems as `joint: false`).",
            "",
            md_table(
                [
                    "Comparison",
                    "Design",
                    *[
                        f"{NOISE_NAMES[v]}: {s}"
                        for v in NOISE_NAMES
                        for s in ("train", "test")
                    ],
                ],
                rows,
            ),
            "",
        ]
    # absolute values and train -> test changes, pure
    rows = []
    sub = kp.loc[(kp["kpi"] == "cvar_uncovered") & (kp["eval_beta"] == 0.99)]
    for variant in ("none", "common"):
        for pricing in ("pure", "coc_r0.06"):
            for design in ("mse", "eu", "wcvar@0.99", "wcvar@0.995"):
                for scope in ("individual", "cluster_sep", "cluster", "portfolio"):
                    s = sub.loc[
                        (sub["variant"] == variant)
                        & (sub["pricing"] == pricing)
                        & (sub["design"] == design)
                        & (sub["scope"] == scope)
                    ]
                    tr = s.loc[s["split"] == "train"].iloc[0]
                    te = s.loc[s["split"] == "test"].iloc[0]
                    rows.append(
                        [
                            NOISE_NAMES[variant],
                            PRICING_NAMES[pricing],
                            DESIGN_NAMES[design],
                            scope,
                            money(tr["value"]),
                            f"{money(te['value'])} [{money(te['ci_low'])}, {money(te['ci_high'])}]",
                            pct(te["value"] / tr["value"] - 1.0),
                            f"`{h12(tr['config_hash'])}`",
                        ]
                    )
    md += [
        "## C2. Values per scope, CVaR₀.₉₉(U), κ 1",
        "",
        md_table(
            [
                "Noise",
                "Pricing",
                "Design",
                "Scope",
                "Train",
                "Test [90 % CI]",
                "Test / train − 1",
                "Config hash",
            ],
            rows,
        ),
        "",
    ]
    el = kp.loc[
        (kp["kpi"] == "expected_loss")
        & (kp["eval_beta"] == 0.99)
        & (kp["scope"] == "individual")
        & (kp["design"] == "mse")
        & (kp["pricing"] == "pure")
    ]
    rows = [[NOISE_NAMES[r.variant], r.split, money(r.value)] for r in el.itertuples()]
    md += [
        "## C3. Expected annual loss (the portfolio's, USD)",
        "",
        md_table(["Noise", "Split", "E[L]"], rows),
        "",
    ]
    cl = ents.loc[
        (ents["scope"] == "cluster")
        & (ents["pricing"] == "pure")
        & (ents["design"] == "mse")
        & (ents["kpi"] == "expected_loss")
    ]
    rows = [
        [
            NOISE_NAMES[v],
            "; ".join(f"{r.subject_id} = {r.entity_locations}" for r in s.itertuples()),
        ]
        for v, s in cl.groupby("variant")
    ]
    md += [
        "## C4. The clusters (thesis Ward on the train years)",
        "",
        "C1 (per-asset noise): C1 = A1 A2, C2 = A3 A4 A5 A6, C3 = A7 A8 A9.",
        "",
        md_table(["Noise", "Clusters"], rows),
        "",
    ]
    st = (
        runs.groupby(["variant", "scope"])
        .agg(
            statuses=(
                "statuses",
                lambda x: ",".join(sorted(set(",".join(x).split(",")))),
            ),
            solvers=(
                "solvers",
                lambda x: ",".join(sorted(set(",".join(x).split(",")))),
            ),
            runs=("run_id", "count"),
        )
        .reset_index()
    )
    md += [
        "## C5. Runs",
        "",
        md_table(
            ["Noise", "Scope", "Runs", "Statuses", "Solvers"],
            [
                [NOISE_NAMES[r.variant], r.scope, str(r.runs), r.statuses, r.solvers]
                for r in st.itertuples()
            ],
        ),
        "",
    ]
    return "\n".join(md)


def family_d(full: Path, out: Path) -> str | None:
    """Tables of phase (d)."""
    if not (full / "nclusters_paired.csv").exists():
        return None
    paired = pd.read_csv(full / "nclusters_paired.csv")
    kp = pd.read_csv(full / "nclusters_kpis.csv")
    runs = pd.read_csv(full / "nclusters_runs.csv")
    ents = pd.read_csv(full / "nclusters_entities.csv")
    keep = paired.loc[
        paired["kpi"].isin(["cvar_uncovered", "expected_uncovered", "expected_payout"])
    ]
    keep.drop(
        columns=[
            c
            for c in (
                "problem_id_a",
                "problem_id_b",
                "run_id_a",
                "run_id_b",
                "eval_split",
                "fold",
                "basis",
                "level",
                "subject_id",
                "beta",
                "ci_level",
                "n_bootstrap",
                "problem_id",
            )
            if c in keep.columns
        ]
    ).to_csv(out / "d_nclusters_paired.csv", index=False, float_format="%.10g")
    kp.loc[
        kp["kpi"].isin(["cvar_uncovered", "expected_uncovered", "expected_payout"]),
        [
            "family",
            "pricing",
            "design",
            "scope",
            "split",
            "eval_beta",
            "kpi",
            "value",
            "ci_low",
            "ci_high",
            "config_hash",
        ],
    ].to_csv(out / "d_nclusters_kpis.csv", index=False, float_format="%.10g")
    runs.to_csv(out / "d_nclusters_runs.csv", index=False, float_format="%.10g")
    ents.loc[
        (ents["kpi"] == "expected_loss")
        & (ents["design"] == "mse")
        & (ents["pricing"] == "pure")
    ].to_csv(out / "d_nclusters_clusters.csv", index=False, float_format="%.10g")
    md: list[str] = []
    sub = paired.loc[
        (paired["kpi"] == "cvar_uncovered") & (paired["eval_beta"] == 0.99)
    ]
    for pricing in ("pure", "coc_r0.06"):
        for design in ("mse", "eu", "wcvar@0.99", "wcvar@0.995"):
            rows = []
            for n in range(1, 10):
                cells = []
                for a, b in (
                    ("cluster", "individual"),
                    ("cluster_sep", "individual"),
                    ("cluster", "cluster_sep"),
                    ("cluster", "portfolio"),
                ):
                    sa = f"{a}|n{n}"
                    sb = f"{b}|n{n}" if b == "cluster_sep" else b
                    s = sub.loc[
                        (sub["pricing"] == pricing)
                        & (sub["design"] == design)
                        & (sub["scope_a"] == sa)
                        & (sub["scope_b"] == sb)
                    ]
                    tr = s.loc[s["split"] == "train"]
                    te = s.loc[s["split"] == "test"]
                    if not len(tr):
                        cells += ["n/a", "n/a"]
                        continue
                    tr, te = tr.iloc[0], te.iloc[0]
                    cells += [
                        pct(tr["difference"] / tr["value_b"]),
                        rel_cell(
                            te["difference"], te["value_b"], te["ci_low"], te["ci_high"]
                        ),
                    ]
                rows.append([str(n), *cells])
            md += [
                f"## D ({PRICING_NAMES[pricing]}, {DESIGN_NAMES[design]}). Cluster count sweep, CVaR₀.₉₉(U), κ 1",
                "",
                "`joint`: the cluster scope calibrated jointly (one design problem); `sep`: "
                "`joint: false` (one problem per cluster, same clusters and index). Individual "
                "and portfolio: C1's runs. Relative to the second scope; train in sample, "
                "test with the paired 90 % interval.",
                "",
                md_table(
                    [
                        "n",
                        "joint − individual: train",
                        "test",
                        "sep − individual (index): train",
                        "test",
                        "joint − sep (joint part): train",
                        "test",
                        "joint − portfolio: train",
                        "test",
                    ],
                    rows,
                ),
                "",
            ]
    cl = ents.loc[
        (ents["kpi"] == "expected_loss")
        & (ents["design"] == "mse")
        & (ents["pricing"] == "pure")
        & ents["scope"].str.startswith("cluster|")
    ]
    rows = []
    for scope, s in cl.groupby("scope", sort=False):
        rows.append(
            [
                scope.split("|")[1],
                "; ".join(
                    f"{r.subject_id} = {r.entity_locations}" for r in s.itertuples()
                ),
            ]
        )
    md += [
        "## D2. The clusters per n (thesis Ward, train years)",
        "",
        md_table(["n", "Clusters"], rows),
        "",
    ]
    rows = []
    for r in runs.loc[runs["scope"].str.contains(r"\|")].itertuples():
        rows.append(
            [
                r.pricing,
                DESIGN_NAMES[r.design],
                r.scope,
                str(r.n_problems),
                r.statuses,
                r.solvers,
                f"{r.objective_value:.6g}",
                f"`{h12(r.config_hash)}`",
            ]
        )
    md += [
        "## D3. Runs",
        "",
        md_table(
            [
                "Pricing",
                "Design",
                "Scope",
                "Problems",
                "Status",
                "Solvers",
                "Objective",
                "Config hash",
            ],
            rows,
        ),
        "",
    ]
    return "\n".join(md)


# --------------------------------------------------------------------------
# (e) joint - individual over both optimal sets
# --------------------------------------------------------------------------

TEST_LABELS: Final[tuple[str, ...]] = ("eu", "cvar@0.95", "cvar@0.99", "cvar@0.995")


def _load_joint(full: Path) -> dict[tuple[str, str, str], dict[str, Any]]:
    out = {}
    for p in sorted((full / "joint").glob("result_joint_*.json")):
        d = json.loads(p.read_text())
        reps = np.load(
            p.with_name(p.name.replace("result_", "reps_").replace(".json", ".npz"))
        )
        d["reps"] = {k: reps[k] for k in reps.files}
        out[tuple(d["group"])] = d
    return out


def _load_individual(
    mar198: Path, method: str, pricing: str, design: str
) -> dict[str, Any] | None:
    sub = "near" if method == "near" else "free"
    p = mar198 / sub / f"result_c1_{pricing}_{design}.json"
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    reps = np.load(mar198 / sub / f"reps_c1_{pricing}_{design}.npz")
    d["reps"] = {k: reps[k] for k in reps.files}
    return d


def family_e(full: Path, out: Path, mar198: Path) -> str | None:
    """Tables of phase (e)."""
    joint = _load_joint(full)
    if not joint:
        return None
    jrows = pd.DataFrame([r for d in joint.values() for r in d["rows"]])
    jrows.to_csv(out / "e_joint_ranges.csv", index=False, float_format="%.10g")
    level = 0.9
    q = [(1 - level) / 2, (1 + level) / 2]
    ends: list[dict[str, Any]] = []
    for (pricing, design, scope), jd in joint.items():
        jhash = jrows.loc[
            (jrows["pricing"] == pricing)
            & (jrows["design"] == design)
            & (jrows["scope"] == scope),
            "config_hash",
        ].iloc[0]
        for method in ("near", "free"):
            ind = _load_individual(mar198, method, pricing, design)
            if ind is None:
                continue
            for lab in TEST_LABELS:
                key = f"test|{lab}"
                # candidates: (joint candidate, individual candidate) per end
                if method == "near":
                    jmin, jmax = f"min|{key}", f"max|{key}"
                else:
                    jmin, jmax = "free_hi", "free_lo"
                imin, imax = f"min|{key}", f"max|{key}"
                pairs = {
                    "C1 designs": ("stored", "stored"),
                    "joint ranged, individual C1": None,
                    "low end (joint min − individual max)": (jmin, imax),
                    "high end (joint max − individual min)": (jmax, imin),
                    "joint min − individual C1": (jmin, "stored"),
                    "joint max − individual C1": (jmax, "stored"),
                }
                for end, pr in pairs.items():
                    if pr is None:
                        continue
                    jc, ic = pr
                    jr = jd["reps"].get(f"{jc}||{lab}")
                    ir = ind["reps"].get(f"{ic}||{lab}")
                    jv = jd["point"].get(jc, {}).get("test", {}).get(lab, math.nan)
                    iv = ind["point"].get(ic, {}).get(lab, math.nan)
                    if (
                        jr is None
                        or ir is None
                        or not np.isfinite(jv)
                        or not np.isfinite(iv)
                    ):
                        lo = hi = math.nan
                        if jr is None or ir is None:
                            jv = jv if jr is not None else math.nan
                            iv = iv if ir is not None else math.nan
                    else:
                        d = np.asarray(jr) - np.asarray(ir)
                        lo, hi = (
                            (math.nan, math.nan)
                            if np.isnan(d).any()
                            else tuple(np.quantile(d, q))
                        )
                    ends.append(
                        {
                            "pricing": pricing,
                            "design": design,
                            "scope": scope,
                            "method": method,
                            "kpi": lab,
                            "end": end,
                            "joint_candidate": jc,
                            "individual_candidate": ic,
                            "joint": jv,
                            "individual": iv,
                            "difference": jv - iv,
                            "ci_low": lo,
                            "ci_high": hi,
                            "joint_hash": jhash,
                            "individual_hash": ind["ranges"][0]["config_hash"],
                        }
                    )
    e = pd.DataFrame(ends)
    if e.empty:
        return None
    e.to_csv(out / "e_rq2_ends.csv", index=False, float_format="%.10g")
    md: list[str] = []
    # E1: joint ranges alone
    rows = []
    for r in jrows.itertuples():
        rows.append(
            [
                PRICING_NAMES[r.pricing],
                DESIGN_NAMES[r.design],
                r.scope,
                r.split,
                KPI_NAMES[r.kpi],
                money(r.stored),
                pct(r.alt / r.stored - 1),
                f"{pct(r.free_hi / r.stored - 1)} / {pct(r.free_lo / r.stored - 1)}",
                f"{pct(r.min / r.stored - 1)} / {pct(r.max_found / r.stored - 1)}",
                f"{r.status_min} / {r.status_max}",
                f"`{h12(r.config_hash)}`",
            ]
        )
    md += [
        "## E1. Range of each joint design's portfolio KPI over its optimal sets (κ 1)",
        "",
        "Relative to the C1 design. Alt: the second optimum (`c1_rq2.ALT_POLICY`). "
        "Free bins: the exact family (tolerance 0) at its two ends. Near-optimal set "
        "(C1 T11's, tolerance 1e-5): the smallest value (one convex program) and the "
        "largest value found by successive linearisation from the C1 and alt designs "
        "(an inner bound), every design checked in numpy against the set.",
        "",
        md_table(
            [
                "Pricing",
                "Design",
                "Scope",
                "Split",
                "KPI",
                "C1 design",
                "Alt",
                "Free bins: low / high",
                "Near-optimal: min / max found",
                "Status min / max",
                "Hash",
            ],
            rows,
        ),
        "",
    ]
    rows = []
    for (pricing, design, scope, method, kpi), s in e.groupby(
        ["pricing", "design", "scope", "method", "kpi"], sort=False
    ):
        if kpi not in ("cvar@0.99", "eu", "cvar@0.995"):
            continue
        base = s.loc[s["end"] == "C1 designs"].iloc[0]
        cells = [
            rel_cell(
                base["difference"], base["individual"], base["ci_low"], base["ci_high"]
            )
        ]
        for end in (
            "low end (joint min − individual max)",
            "high end (joint max − individual min)",
            "joint min − individual C1",
            "joint max − individual C1",
        ):
            x = s.loc[s["end"] == end]
            cells.append(
                "n/a"
                if not len(x)
                else rel_cell(
                    x["difference"].iloc[0],
                    base["individual"],
                    x["ci_low"].iloc[0],
                    x["ci_high"].iloc[0],
                )
            )
        rows.append(
            [
                PRICING_NAMES[pricing],
                DESIGN_NAMES[design],
                scope,
                method,
                KPI_NAMES[kpi],
                *cells,
            ]
        )
    md += [
        "## E2. Joint − individual (C1 section 6b) over both optimal sets, test, κ 1",
        "",
        "Relative to the individual C1 design's value. `near`: both designs over their "
        "near-optimal sets (joint: E1; individual: MAR-198 method (b)); `free`: both over "
        "their free-bin families (exact; joint: E1; individual: MAR-198 method (a)). Low "
        "end: the joint design with the smallest KPI against the individual design with "
        "the largest; high end: the reverse. The last two columns hold the individual "
        "design at its C1 value, to separate the joint designs' share. `n/a`: an end "
        "design was not found (MAR-198 MSE, near-optimal method).",
        "",
        md_table(
            [
                "Pricing",
                "Design",
                "Scope",
                "Method",
                "KPI",
                "C1 designs",
                "Low end",
                "High end",
                "Joint min − ind. C1",
                "Joint max − ind. C1",
            ],
            rows,
        ),
        "",
    ]
    return "\n".join(md)


FAMILIES: Final[list[tuple[str, Callable[[Path, Path], str | None]]]] = [
    ("a", family_a),
    ("b", family_b),
    ("c", family_c),
    ("d", family_d),
]


def main(argv: list[str] | None = None) -> int:
    """Write the committed tables and ``tables.md``.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description="MAR-206 tables.")
    parser.add_argument("--full", type=Path, default=FULL_DIR)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--mar198", type=Path, default=MAR198_DIR)
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    parts = [
        "# C1 RQ2 sensitivities: generated tables (MAR-206)",
        "",
        "Generated by `research/scripts/c1_rq2_sensitivities_tables.py` from the "
        "full tables of `research/scripts/c1_rq2_sensitivities.py`. Hashes: the "
        "first 12 hex digits of the config hash. `*`: a paired 90 % interval that "
        "excludes zero. Observations only.",
        "",
    ]
    summary: dict[str, Any] = {}
    families: list[tuple[str, Callable[[Path, Path], str | None]]] = [
        *FAMILIES,
        ("e", lambda f, o: family_e(f, o, args.mar198)),
    ]
    for name, fn in families:
        md = fn(args.full, args.out)
        if md is None:
            print(f"family {name}: no full tables, skipped")
            continue
        parts += [md, ""]
        for s in sorted(args.full.glob("summary_*.json")):
            summary[s.stem] = json.loads(s.read_text())
    (args.out / "tables.md").write_text("\n".join(parts).rstrip() + "\n")
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
