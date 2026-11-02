"""MAR-203: committed tables of the Florida near-optimal ranges.

Reads the full results of ``florida_ranges.py`` (``results/florida-ranges/``)
and writes to ``research/data/florida-rerun/`` (each CSV under 500 kB):

* ``ranges_kpis.csv``: per design (index, pricing, kappa, scope, design),
  split and portfolio KPI: the stored design's value and, relative to it,
  the second optimum (``alt``, joint designs), the free-bin ends and, where
  measured, the smallest and largest value found over the near-optimal set,
  with the member that attains it; the config hash;
* ``ranges_designs.csv``: per joint design: the ``alt`` solve (solver,
  status, objective relative to the stored one, inside the set or not) and
  the near-optimal search's statuses;
* ``ranges_counties.csv``: per individual design and county: the bins
  without a train row (free bins), their test rows and the free parameters'
  width relative to the cap; for MSE the Hessian eigenvalue ratio;
* ``ranges_entities.csv``: per joint design and payout entity (county or
  cluster): train ``E[pi_j] / E[L_j]`` of the stored, ``alt`` and free-bin
  designs and, where measured, its smallest and largest value over the
  near-optimal set (C1 T11's ranges);
* ``ranges_contrasts.csv``: every MAR-202 holdout test contrast (E[U] and
  CVaR at 0.95, 0.99, 0.995) at the stored designs and at each end, relative
  to the stored reference design's value, with the verdict;
* ``ranges_flips.csv``: every (contrast, variant) whose sign or interval
  verdict differs from the stored designs';
* ``ranges_tables.md``: the tables R1-R7 of the note.

Observations only.
"""

# ruff: noqa: RUF001

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Final

import florida_ranges as frg
import numpy as np
import pandas as pd

LABEL_NAME: Final[dict[str, str]] = {
    "eu": "E[U]",
    "cvar@0.95": "CVaR 0.95",
    "cvar@0.99": "CVaR 0.99",
    "cvar@0.995": "CVaR 0.995",
}
DESIGN_NAME: Final[dict[str, str]] = {
    "mse": "MSE",
    "eu": "E[U]",
    "wcvar@0.99": "wCVaR β 0.99",
    "wcvar@0.995": "wCVaR β 0.995",
}
PRICING_NAME: Final[dict[str, str]] = {"pure": "pure", "coc_r0.06": "CoC r 0.06"}
CONTRAST_NAME: Final[dict[str, str]] = {
    "rq1_alone": "RQ1 alone (I,W) − (I,O)",
    "rq2_alone": "RQ2 alone (J,O) − (I,O)",
    "adds_rq2": "adds RQ2 (J,W) − (I,W)",
    "adds_rq1": "adds RQ1 (J,W) − (J,O)",
    "both": "both (J,W) − (I,O)",
    "interaction": "interaction",
}
CROSS: Final[frozenset[str]] = frozenset(
    {"rq2_alone", "adds_rq2", "both", "interaction"}
)
"""Contrasts with a joint and an individual term (cross-scope)."""
FAMILIES: Final[dict[str, tuple[str, ...]]] = {
    "alt": ("alt", "alt:a", "alt:b"),
    "free bins": ("free_low", "free_high"),
    "free bins, joint terms only": ("free_low_joint", "free_high_joint"),
    "free bins, individual terms only": (
        "free_low_individual",
        "free_high_individual",
    ),
    "near-optimal (joint) + free bins (individual)": ("near_low", "near_high"),
    "near-optimal, joint terms only": ("near_low_joint", "near_high_joint"),
}
INDICES: Final[tuple[str, ...]] = ("a", "cic75")
VERDICT_CODE: Final[dict[str, str]] = {
    "below zero": "<0",
    "contains zero": "0",
    "above zero": ">0",
}
"""Interval verdicts in ``ranges_contrasts*.csv``: below, containing, above zero."""


def _short(h: str) -> str:
    return str(h).split(":", 1)[-1][:12]


def _pct(x: float) -> str:
    if not math.isfinite(x):
        return "n/a"
    s = f"{100 * x:+.1f} %"
    return s.replace("-", "−")


def _pct2(x: float) -> str:
    if not math.isfinite(x):
        return "n/a"
    s = f"{100 * x:+.2f} %"
    return s.replace("-", "−")


def _ci(rel: float, lo: float, hi: float) -> str:
    star = "*" if (lo > 0 or hi < 0) else ""
    a = f"{100 * lo:+.1f}".replace("-", "−")
    b = f"{100 * hi:+.1f}".replace("-", "−")
    return f"{_pct(rel)}{star} [{a}, {b}]"


def _in_set(inside: bool, structure: float, budget: float) -> str:
    """Return 'yes', or why a design fails the set's numpy check."""
    if inside:
        return "yes"
    parts = []
    if structure > 1e-6:
        parts.append(f"structure {structure:.1e}")
    if math.isfinite(budget) and budget > 1e-6:
        parts.append(f"budget {budget:+.1e}")
    return "no" + (f" ({', '.join(parts)})" if parts else " (objective)")


def _table(header: list[str], rows: list[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


# --------------------------------------------------------------------------
# Frames
# --------------------------------------------------------------------------


def kpi_rows(results: dict[Any, dict[str, Any]]) -> pd.DataFrame:
    """Per design, split and KPI: the stored value and the candidates' range."""
    rows = []
    for (key, design), r in sorted(results.items()):
        joint = design[0] in frg.JOINT_SCOPES
        near = bool(r["meta"].get("near"))
        names = frg.members(r) if joint else ["stored", "free_lo", "free_hi"]
        for split in ("train", "test"):
            for lab in frg.LABELS:
                ref = r["point"]["stored"][split][lab]

                def rel(
                    name: str,
                    split: str = split,
                    lab: str = lab,
                    r: dict[str, Any] = r,
                    ref: float = ref,
                ) -> float:
                    if name not in r["point"]:
                        return math.nan
                    return r["point"][name][split][lab] / ref - 1.0 if ref else math.nan

                row: dict[str, Any] = {
                    "eventset": key[0],
                    "pricing": key[1],
                    "kappa": key[2],
                    "scope": design[0],
                    "design": design[1],
                    "split": split,
                    "kpi": lab,
                    "stored": ref,
                    "alt": rel("alt"),
                    "free_lo": rel("free_lo"),
                    "free_hi": rel("free_hi"),
                    "min_found": math.nan,
                    "max_found": math.nan,
                    "min_from": "",
                    "max_from": "",
                }
                if joint and near:
                    vals = {n: r["point"][n][split][lab] for n in names}
                    lo = min(vals, key=lambda n: vals[n])
                    hi = max(vals, key=lambda n: vals[n])
                    row.update(
                        min_found=rel(lo),
                        max_found=rel(hi),
                        min_from=lo,
                        max_from=hi,
                    )
                row["hash"] = _short(r["meta"]["config_hash"])
                rows.append(row)
    return pd.DataFrame(rows)


def design_rows(results: dict[Any, dict[str, Any]]) -> pd.DataFrame:
    """Per joint design: the alt solve and the near-optimal search."""
    rows = []
    for (key, design), r in sorted(results.items()):
        if design[0] not in frg.JOINT_SCOPES:
            continue
        m = r["meta"]
        rows.append(
            {
                "eventset": key[0],
                "pricing": key[1],
                "kappa": key[2],
                "scope": design[0],
                "design": design[1],
                "stored_solvers": m["solvers"],
                "stored_statuses": m["statuses"],
                "alt_solver": m["alt_solver"],
                "alt_status": m["alt_status"],
                "alt_objective_rel": m["objective_alt"] / m["objective_stored"] - 1.0
                if m["objective_stored"]
                else math.nan,
                "alt_in_set": "alt" in frg.members(r),
                "alt_objective_excess": r["checks"]["alt"]["objective_excess"],
                "alt_budget_excess": r["checks"]["alt"]["budget_excess"],
                "alt_structure_violation": r["checks"]["alt"]["structure_violation"],
                "stored_in_set": "stored" in frg.members(r),
                "stored_structure_violation": r["checks"]["stored"][
                    "structure_violation"
                ],
                "optimum_from": m["optimum_from"],
                "near": m["near"],
                "payouts": m["payouts"],
                "n_members": len(frg.members(r)),
                "n_candidates_outside_set": len(r["checks"]) - len(frg.members(r)),
                "statuses": json.dumps(r["statuses"], sort_keys=True),
                "seconds": m["seconds"],
                "rel_tol": m["rel_tol"],
                "hash": _short(m["config_hash"]),
            }
        )
    return pd.DataFrame(rows)


def county_rows(results: dict[Any, dict[str, Any]]) -> pd.DataFrame:
    """Per individual design and county: free bins."""
    rows = []
    for (key, design), r in sorted(results.items()):
        if design[0] != "individual":
            continue
        for c in r["counties"]:
            rows.append(
                {
                    "eventset": key[0],
                    "pricing": key[1],
                    "kappa": key[2],
                    "design": design[1],
                    "county": c["county"],
                    "free_bins": c["free_bins"],
                    "free_bins_test_rows": c["free_bins_test_rows"],
                    "width_to_cap": round(c["free_param_width_to_cap"], 5),
                    "mse_eig_ratio": c["mse_hessian_min_eig_rel_used_bins"],
                    "hash": _short(r["meta"]["config_hash"]),
                }
            )
    return pd.DataFrame(rows)


def entity_rows(results: dict[Any, dict[str, Any]]) -> pd.DataFrame:
    """Per joint design and payout entity: train E[pi_j]/E[L_j] and ranges."""
    rows = []
    for (key, design), r in sorted(results.items()):
        if design[0] not in frg.JOINT_SCOPES:
            continue
        for e in r["entities"]:
            rows.append(
                {
                    "eventset": key[0],
                    "pricing": key[1],
                    "kappa": key[2],
                    "scope": design[0],
                    "design": design[1],
                    "entity": e["entity_id"],
                    "free_bins": e["free_bins"],
                    "train_expected_loss": e["train_expected_loss"],
                    "ratio_stored": e["ratio_stored"],
                    "ratio_alt": e["ratio_alt"],
                    "ratio_min": e.get("ratio_min", math.nan),
                    "ratio_max": e.get("ratio_max", math.nan),
                    "status_min": e.get("status_min", ""),
                    "status_max": e.get("status_max", ""),
                    "hash": _short(r["meta"]["config_hash"]),
                }
            )
    return pd.DataFrame(rows)


KEYS: Final[list[str]] = [
    "eventset",
    "pricing",
    "kappa",
    "contrast",
    "joint_scope",
    "tail_design",
    "base_design",
    "kpi",
    "eval_beta",
]


def contrast_frames(con: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return the wide table of contrast ends, the flips and the long table."""
    if (con["missing"].fillna("") != "").any():
        bad = con.loc[con["missing"].fillna("") != ""].iloc[0]
        raise RuntimeError(f"a contrast variant has a missing term: {bad.to_dict()}")
    c = con.copy()
    for k in ("joint_scope", "tail_design", "base_design"):
        c[k] = c[k].fillna("")
    c["eval_beta"] = c["eval_beta"].fillna(-1.0)
    ref = c["value_ref"].where(c["value_ref"].abs() >= 1.0)
    c["rel"] = c["value"] / ref
    c["rel_lo"] = c["ci_low"] / ref
    c["rel_hi"] = c["ci_high"] / ref
    stored = c.loc[c["variant"] == "stored", [*KEYS, "value", "verdict"]].rename(
        columns={"value": "stored_value", "verdict": "stored_verdict"}
    )
    c = c.merge(stored, on=KEYS, validate="many_to_one")
    c["sign_flip"] = np.sign(c["value"]) * np.sign(c["stored_value"]) < 0
    c["verdict_flip"] = c["verdict"] != c["stored_verdict"]
    wide_parts = []
    for v in ("stored", "alt", "free_low", "free_high", "near_low", "near_high"):
        part = c.loc[c["variant"] == v, [*KEYS, "rel", "rel_lo", "rel_hi", "verdict"]]
        part = part.rename(
            columns={
                "rel": f"{v}_rel",
                "rel_lo": f"{v}_lo",
                "rel_hi": f"{v}_hi",
                "verdict": f"{v}_verdict",
            }
        )
        wide_parts.append(part.set_index(KEYS))
    wide = pd.concat(wide_parts, axis=1).reset_index()
    for col in [x for x in wide.columns if str(x).endswith("_verdict")]:
        wide[col] = wide[col].map(VERDICT_CODE)  # short codes keep the CSV small
    hcols = [h for h in ("hash_a", "hash_b", "hash_c", "hash_d") if h in c.columns]
    if hcols:  # holdout: per term; pooled: the k-fold experiment configs (T15)
        hashes = c.loc[c["variant"] == "stored", [*KEYS, *hcols]]
        wide = wide.merge(hashes, on=KEYS, validate="one_to_one")
    flips = c.loc[
        (c["variant"] != "stored") & (c["sign_flip"] | c["verdict_flip"]),
        [
            *KEYS,
            "variant",
            "candidates",
            "rel",
            "rel_lo",
            "rel_hi",
            "verdict",
            "stored_verdict",
            "sign_flip",
            "verdict_flip",
        ],
    ]
    return wide, flips, c  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def _kpi_table(k: pd.DataFrame, pricing: str, kappa: float) -> list[str]:
    x = k.loc[(k["pricing"] == pricing) & (k["kappa"] == kappa)]
    rows = []
    for idx in INDICES:
        for scope in ("individual", "cluster", "portfolio"):
            for d in DESIGN_NAME:
                for split in ("test", "train"):
                    for lab in frg.LABELS:
                        r = x.loc[
                            (x["eventset"] == idx)
                            & (x["scope"] == scope)
                            & (x["design"] == d)
                            & (x["split"] == split)
                            & (x["kpi"] == lab)
                        ]
                        if r.empty:
                            continue
                        r = r.iloc[0]
                        if split == "train" and lab != "cvar@0.99" and lab != "eu":
                            continue
                        rows.append(
                            [
                                idx,
                                scope,
                                DESIGN_NAME[d],
                                split,
                                LABEL_NAME[lab],
                                f"{r['stored'] / 1e6:,.0f}",
                                "" if scope == "individual" else _pct2(r["alt"]),
                                f"{_pct2(r['free_hi'])} / {_pct2(r['free_lo'])}",
                                (
                                    f"{_pct2(r['min_found'])} / {_pct2(r['max_found'])}"
                                    if math.isfinite(r["min_found"])
                                    else ""
                                ),
                                f"`{r['hash']}`",
                            ]
                        )
    return [
        _table(
            [
                "Index",
                "Scope",
                "Design",
                "Split",
                "KPI",
                "Stored (USD m)",
                "alt",
                "Free bins: low / high",
                "Near-optimal: low / high found",
                "Hash",
            ],
            rows,
        )
    ]


def _count_rows(c: pd.DataFrame, groups: pd.Series) -> list[list[str]]:
    rows = []
    for fam, vs in FAMILIES.items():
        x = c.loc[c["variant"].isin(vs) & groups]
        if x.empty:
            continue
        per = x.groupby(KEYS).agg(
            sign=("sign_flip", "any"), verdict=("verdict_flip", "any")
        )
        n = len(per)
        rows.append(
            [
                fam,
                str(n),
                str(int(per["sign"].sum())),
                str(int(per["verdict"].sum())),
            ]
        )
    return rows


def markdown(
    k: pd.DataFrame,
    d: pd.DataFrame,
    counties: pd.DataFrame,
    ents: pd.DataFrame,
    wide: pd.DataFrame,
    c: pd.DataFrame,
    summary: dict[str, Any],
) -> str:
    """Return the tables of the note (R1-R7) as Markdown."""
    out = [
        "# Florida near-optimal ranges (MAR-203): tables",
        "",
        "Generated by `research/scripts/florida_ranges_tables.py` from "
        "`florida_ranges.py`'s full results. Setup of every number: "
        "`research/notes/florida-rerun.md` section 2 (D2 portfolio, 67 Florida "
        "counties, the State as owner; annual basis; basis risk from the index "
        "against the cell-level loss with vulnerability draws, no noise layer; "
        "`below_attachment: zero`; holdout, train years 0–6,999, test "
        "7,000–9,999), with the pricing, κ, index, scope and design stated per "
        "row. Near-optimal set: C1 T11's, objective ≤ optimum · (1 + 10⁻⁵). "
        "Relative values are against the stored (MAR-202) design's value. "
        "`*`: the 90 % interval excludes zero. Observations only.",
        "",
        f"Core package version: `{summary['core_version']}`.",
        "",
    ]
    out += [
        "## R1. Portfolio KPIs over each design's optimal set: pure, κ 1",
        "",
        "Stored: MAR-202's design. alt: the second optimum (`ALT_POLICY`). "
        "Free bins: the exact free-bin family's ends (every free parameter at "
        "its highest / lowest: smallest / largest KPI). Near-optimal: the "
        "smallest and largest values found over the checked members of the "
        "near-optimal set (inner bounds; joint designs only). Train rows are "
        "E[U] and CVaR 0.99.",
        "",
        *_kpi_table(k, "pure", 1.0),
        "",
    ]
    # R2 widths over all groups
    rows = []
    for idx in INDICES:
        for pricing in PRICING_NAME:
            for kappa in (0.5, 1.0, 1.5):
                for scope in ("individual", "cluster", "portfolio"):
                    x = k.loc[
                        (k["eventset"] == idx)
                        & (k["pricing"] == pricing)
                        & (k["kappa"] == kappa)
                        & (k["scope"] == scope)
                        & (k["split"] == "test")
                        & (k["kpi"] == "cvar@0.99")
                    ]
                    if x.empty:
                        continue
                    lo = x[["free_hi", "alt", "min_found"]].min(axis=1)
                    hi = x[["free_lo", "alt", "max_found"]].max(axis=1)
                    rows.append(
                        [
                            idx,
                            PRICING_NAME[pricing],
                            f"{kappa:g}",
                            scope,
                            f"{_pct2(float(lo.min()))} to {_pct2(float(hi.max()))}",
                            f"{100 * float((hi - lo).max()):.2f} pts",
                        ]
                    )
    out += [
        "## R2. Test CVaR 0.99 across optimal designs, every group",
        "",
        "Over the four designs of each scope: the lowest and highest test "
        "CVaR 0.99 among the stored design, `alt`, the free-bin ends and (pure, "
        "κ 1) the near-optimal members found, relative to the stored design; "
        "and the widest single design's range.",
        "",
        _table(
            ["Index", "Pricing", "κ", "Scope", "Range (all designs)", "Widest"], rows
        ),
        "",
    ]
    # R3 second optima
    rows = []
    for r in d.itertuples():
        rows.append(
            [
                str(r.eventset),
                PRICING_NAME[str(r.pricing)],
                f"{r.kappa:g}",
                str(r.scope),
                DESIGN_NAME[str(r.design)],
                f"{r.stored_solvers}",
                f"{r.alt_solver} ({r.alt_status})",
                f"{r.alt_objective_rel:+.1e}",
                _in_set(r.alt_in_set, r.alt_structure_violation, r.alt_budget_excess),
                _in_set(r.stored_in_set, r.stored_structure_violation, math.nan),
                f"`{r.hash}`",
            ]
        )
    out += [
        "## R3. The second optima (joint designs)",
        "",
        "Every holdout cluster and portfolio design solved again with "
        "`c1_rq2.ALT_POLICY`; its train objective relative to the stored "
        "design's (numpy), and whether it and the stored design pass the "
        "near-optimal set's numpy check (objective within 10⁻⁵ + 10⁻⁶ of the "
        "smaller of the two objectives, budget within 10⁻⁶, payout structure "
        "within 10⁻⁶ of the cap); if not, the largest structure violation "
        "relative to the cap (a solver tolerance).",
        "",
        _table(
            [
                "Index",
                "Pricing",
                "κ",
                "Scope",
                "Design",
                "Stored solvers",
                "alt solver",
                "alt objective − stored",
                "alt in set",
                "Stored in set",
                "Hash",
            ],
            rows,
        ),
        "",
    ]
    # R4 free bins per county
    rows = []
    for idx in INDICES:
        x = counties.loc[counties["eventset"] == idx]
        n_free = x["free_bins"].fillna("").map(lambda s: len(str(s).split()))
        for design in DESIGN_NAME:
            y = x.loc[x["design"] == design]
            nf = n_free.loc[y.index]
            rows.append(
                [
                    idx,
                    DESIGN_NAME[design],
                    f"{int((nf > 0).sum() / max(len(y) / 67, 1))} of 67",
                    f"{int(nf.max())}",
                    f"{y['width_to_cap'].max():.3f}",
                    f"{int(y['free_bins_test_rows'].sum())}",
                ]
            )
    out += [
        "## R4. Free bins of the individual designs (per county)",
        "",
        "Counties with at least one bin without a train row of their index "
        "(per design, averaged over the 6 pricing × κ variants, which share the "
        "train rows), the most free bins of a county, the widest free "
        "parameter relative to the county's cap, and the test rows that fall "
        "in free bins (summed over counties and variants). Per county: "
        "`ranges_counties.csv`.",
        "",
        _table(
            [
                "Index",
                "Design",
                "Counties with free bins",
                "Most free bins",
                "Widest (of cap)",
                "Test rows in free bins",
            ],
            rows,
        ),
        "",
    ]
    # R5 entity payout ranges
    e = ents.loc[ents["ratio_min"].notna()]
    rows = []
    for (idx, pricing, kappa, scope, design), g in e.groupby(
        ["eventset", "pricing", "kappa", "scope", "design"], sort=True
    ):
        width = g["ratio_max"] - g["ratio_min"]
        rows.append(
            [
                str(idx),
                PRICING_NAME[str(pricing)],
                f"{kappa:g}",
                str(scope),
                DESIGN_NAME[str(design)],
                f"{len(g)}",
                f"{g['ratio_min'].min():.2f}–{g['ratio_max'].max():.2f}",
                f"{float(width.median()):.2f}",
                f"{float(width.max()):.2f}",
                f"{int((g['ratio_min'] < 0.01).sum())}",
                f"{int((g['ratio_stored'] < 0.01).sum())}",
            ]
        )
    out += [
        "## R5. Per-entity train payout ratio E[π_j]/E[L_j] over the near-optimal set",
        "",
        "C1 T11's ranges for the joint designs where measured: the smallest "
        "and largest ratio of each entity (county or cluster) over the checked "
        "members; per entity in `ranges_entities.csv`.",
        "",
        _table(
            [
                "Index",
                "Pricing",
                "κ",
                "Scope",
                "Design",
                "Entities",
                "Ratios over the set",
                "Median width",
                "Widest",
                "Entities that can get < 0.01",
                "Stored < 0.01",
            ],
            rows,
        ),
        "",
    ]
    # R6 flip counts
    out += ["## R6. MAR-202 test contrasts whose sign or verdict changes at an end", ""]
    out += [
        "Counted per (group, contrast, KPI): a contrast counts once per family "
        "if any variant of the family changes its sign or its interval verdict "
        "(below zero, contains zero, above zero) against the stored designs'. "
        "KPIs: E[U], CVaR 0.95, 0.99, 0.995. Cross-scope: RQ2 alone, adds RQ2, "
        "both, interaction; within a joint scope: adds RQ1; individual only: "
        "RQ1 alone.",
        "",
    ]
    kinds = {
        "cross-scope": c["contrast"].isin(CROSS),
        "within a joint scope (adds RQ1)": c["contrast"] == "adds_rq1",
        "individual only (RQ1 alone)": c["contrast"] == "rq1_alone",
    }
    for idx_label, sel in (
        ("every group", pd.Series(True, index=c.index)),
        ("pure, κ 1", (c["pricing"] == "pure") & (c["kappa"] == 1.0)),
    ):
        rows = []
        for kind, ks in kinds.items():
            for r in _count_rows(c, ks & sel):
                rows.append([kind, *r])
        out += [
            f"**{idx_label}**",
            "",
            _table(
                [
                    "Contrasts",
                    "Family",
                    "Contrasts × KPIs",
                    "Sign changes",
                    "Verdict changes",
                ],
                rows,
            ),
            "",
        ]
    # R7 headline cells
    out += [
        "## R7. MAR-202's κ 1 RQ2 and combination cells at the ends (CVaR 0.99)",
        "",
        "Relative to the stored reference design. alt: every joint term at its "
        "second optimum. Free bins: every term at the free-bin end that lowers "
        "/ raises the contrast. Near-optimal: joint terms at the member found "
        "with the lowest / highest KPI, individual terms at their free-bin end "
        "(pure, κ 1 only).",
        "",
    ]
    rows = []
    sel = wide.loc[
        (wide["kappa"] == 1.0)
        & (wide["kpi"] == "cvar_uncovered")
        & (wide["eval_beta"] == 0.99)
        & wide["contrast"].isin(["rq2_alone", "adds_rq2", "both", "interaction"])
    ]
    for r in sel.sort_values(
        ["eventset", "pricing", "contrast", "joint_scope"]
    ).itertuples():
        if r.contrast in ("both", "interaction") and r.base_design != "mse":
            continue
        design = r.tail_design or r.base_design
        rows.append(
            [
                str(r.eventset),
                PRICING_NAME[str(r.pricing)],
                CONTRAST_NAME[str(r.contrast)],
                str(r.joint_scope),
                DESIGN_NAME[str(design)],
                _ci(r.stored_rel, r.stored_lo, r.stored_hi),
                _ci(r.alt_rel, r.alt_lo, r.alt_hi),
                _ci(r.free_low_rel, r.free_low_lo, r.free_low_hi)
                + " / "
                + _ci(r.free_high_rel, r.free_high_lo, r.free_high_hi),
                (
                    _ci(r.near_low_rel, r.near_low_lo, r.near_low_hi)
                    + " / "
                    + _ci(r.near_high_rel, r.near_high_lo, r.near_high_hi)
                    if isinstance(r.near_low_verdict, str)
                    else ""
                ),
                f"`{r.hash_a}` / `{r.hash_b}`",
            ]
        )
    out += [
        _table(
            [
                "Index",
                "Pricing",
                "Contrast",
                "J",
                "W or O",
                "Stored (MAR-202)",
                "alt",
                "Free bins: low / high",
                "Near-optimal: low / high",
                "Hash a / b",
            ],
            rows,
        ),
        "",
    ]
    return "\n".join(out)


def kfold_design_rows(full: Path) -> pd.DataFrame:
    """Per k-fold fold design: the alt solve and its free bins."""
    import pickle

    rows = []
    for path in sorted((full / "kfold").glob("*.pkl")):
        r = pickle.loads(path.read_bytes())
        m = r["meta"]
        stem = path.stem
        index, rest = stem.split("_", 1)
        pricing = "pure"
        scope = (
            "portfolio"
            if "_portfolio_" in rest
            else ("cluster" if "_cluster_" in rest else "individual")
        )
        design = rest.split(f"_{scope}_", 1)[1].rsplit("_f", 1)[0]
        row: dict[str, Any] = {
            "eventset": index,
            "pricing": pricing,
            "kappa": 1.0,
            "scope": scope,
            "design": design,
            "fold": m["fold"],
            "stored_solvers": m["solvers"],
            "free_bins": m.get("free_bins", 0),
            "alt_solver": m.get("alt_solver", ""),
            "alt_status": m.get("alt_status", ""),
            "alt_objective_rel": (
                m["objective_alt"] / m["objective_stored"] - 1.0
                if m.get("objective_stored")
                else math.nan
            ),
            "hash": _short(m["config_hash"]),
        }
        rows.append(row)
    return pd.DataFrame(rows)


def pooled_markdown(wide: pd.DataFrame, c: pd.DataFrame, kd: pd.DataFrame) -> str:
    """Return the pooled 5-fold tables (R8-R10) as Markdown."""
    out = [
        "## R8. Pooled 5-fold contrasts (pure, κ 1) whose sign or verdict changes",
        "",
        "As R6, on MAR-202's pooled 5-fold contrasts: each fold design replaced "
        "by its second optimum (`alt`) or its free-bin ends, then pooled (every "
        "year evaluated by the fold design that did not see it). No "
        "near-optimal programs for the folds. The two T14 folds are their "
        "CLARABEL re-solves. Experiment config hashes: MAR-202 T15 "
        "(index (a) `2ace43bd99c8`, `e030e975389d`; index (b) `a2e2c3b6875f`, "
        "`0e7dc2834399`); per fold design: `ranges_kfold_designs.csv`.",
        "",
    ]
    kinds = {
        "cross-scope": c["contrast"].isin(CROSS),
        "within a joint scope (adds RQ1)": c["contrast"] == "adds_rq1",
        "individual only (RQ1 alone)": c["contrast"] == "rq1_alone",
    }
    rows = []
    for kind, ks in kinds.items():
        for idx in INDICES:
            for r in _count_rows(c, ks & (c["eventset"] == idx)):
                rows.append([kind, idx, *r])
    out += [
        _table(
            [
                "Contrasts",
                "Index",
                "Family",
                "Contrasts × KPIs",
                "Sign changes",
                "Verdict changes",
            ],
            rows,
        ),
        "",
        "## R9. Pooled RQ2 and combination cells at the ends (CVaR 0.99)",
        "",
    ]
    rows = []
    sel = wide.loc[
        (wide["kpi"] == "cvar_uncovered")
        & (wide["eval_beta"] == 0.99)
        & wide["contrast"].isin(["rq2_alone", "adds_rq2", "both", "interaction"])
    ]
    for r in sel.sort_values(["eventset", "contrast", "joint_scope"]).itertuples():
        if r.contrast in ("both", "interaction") and r.base_design != "mse":
            continue
        design = r.tail_design or r.base_design
        rows.append(
            [
                str(r.eventset),
                CONTRAST_NAME[str(r.contrast)],
                str(r.joint_scope),
                DESIGN_NAME[str(design)],
                _ci(r.stored_rel, r.stored_lo, r.stored_hi),
                _ci(r.alt_rel, r.alt_lo, r.alt_hi),
                _ci(r.free_low_rel, r.free_low_lo, r.free_low_hi),
                _ci(r.free_high_rel, r.free_high_lo, r.free_high_hi),
            ]
        )
    out += [
        _table(
            [
                "Index",
                "Contrast",
                "J",
                "W or O",
                "Stored (MAR-202, T14 re-solved)",
                "alt",
                "Free bins: low",
                "Free bins: high",
            ],
            rows,
        ),
        "",
    ]
    j = kd.loc[kd["scope"] != "individual"]
    rows = []
    for (idx, scope), g in j.groupby(["eventset", "scope"]):
        rows.append(
            [
                str(idx),
                str(scope),
                str(len(g)),
                f"{g['alt_objective_rel'].min():+.1e} to "
                f"{g['alt_objective_rel'].max():+.1e}",
                ", ".join(sorted(set(g["alt_solver"]))),
                str(int(g["free_bins"].sum())),
            ]
        )
    out += [
        "## R10. The k-fold fold designs' second optima",
        "",
        _table(
            [
                "Index",
                "Scope",
                "Fold designs",
                "alt objective − stored (relative)",
                "alt solvers",
                "Free bins (all fold designs)",
            ],
            rows,
        ),
        "",
    ]
    return "\n".join(out)


def _computed_version(full: Path) -> str:
    """Return the core version the ranges were computed with (phase summaries).

    Raises
    ------
    RuntimeError
        If the phases recorded different versions.
    """
    versions = {
        json.loads(p.read_text())["package_versions"]["parametric-insurance-design"]
        for name in ("joint", "contrasts", "kfold_pooled")
        if (p := full / f"summary_{name}.json").is_file()
    }
    if len(versions) != 1:
        raise RuntimeError(f"the phases ran on core versions {sorted(versions)}")
    return versions.pop()


def write(full: Path, out: Path) -> dict[str, Any]:
    """Write the committed tables; return summary entries."""
    results = frg.load_results(full)
    k = kpi_rows(results)
    d = design_rows(results)
    counties = county_rows(results)
    ents = entity_rows(results)
    con = pd.read_csv(full / "contrasts.csv")
    wide, flips, c = contrast_frames(con)
    pcon = pd.read_csv(full / "kfold_contrasts.csv")
    pwide, pflips, pc = contrast_frames(pcon)
    kd = kfold_design_rows(full)
    summary = {
        "core_version": _computed_version(full),
        "designs": len(results),
        "contrast_rows": len(con),
        "flips": len(flips),
        "pooled_contrast_rows": len(pcon),
        "pooled_flips": len(pflips),
        "kfold_fold_designs": len(kd),
    }
    out.mkdir(parents=True, exist_ok=True)
    frames = {
        "ranges_kpis": k,
        "ranges_designs": d,
        "ranges_counties": counties,
        "ranges_entities": ents,
        "ranges_contrasts": wide,
        "ranges_flips": flips,
        "ranges_contrasts_pooled": pwide,
        "ranges_flips_pooled": pflips,
        "ranges_kfold_designs": kd,
    }
    for name, f in frames.items():
        path = out / f"{name}.csv"
        fmt = "%.4g" if "contrasts" in name or "flips" in name else "%.6g"
        f.to_csv(path, index=False, float_format=fmt)
        size = path.stat().st_size
        if size > 500_000:
            raise RuntimeError(f"{path} is {size} bytes (over 500 kB)")
        summary[f"{name}_bytes"] = size
    (out / "ranges_tables.md").write_text(
        (
            markdown(k, d, counties, ents, wide, c, summary)
            + "\n"
            + pooled_markdown(pwide, pc, kd)
        ).rstrip("\n")
        + "\n"
    )
    (out / "ranges_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


if __name__ == "__main__":
    print(write(frg.FULL_DIR, frg.OUT_DIR))
