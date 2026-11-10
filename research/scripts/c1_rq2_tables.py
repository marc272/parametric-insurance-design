r"""Committed tables, Markdown tables and the figure of the C1 RQ2 addendum (MAR-158).

Reads the full tables that ``c1_rq2.py`` writes to ``results/c1-rq2/full/``
(not committed) and writes

* ``research/data/c1-rq2/*.csv``: the committed tables, each under the
  500 kB pre-commit limit (``runs.csv`` maps every design to its config hash
  or derived id; the other tables carry the design labels);
* ``research/data/c1-rq2/tables.md``: every table of the RQ2 section of
  ``research/checkpoints/C1.md``, generated, so each number can be traced to
  a CSV row and its hash;
* ``research/checkpoints/figures/c1_rq2_scopes.png``.

Portfolio-level KPIs, and the payout per entity only: no per-asset
uncovered-loss or premium KPIs of joint designs (MAR-98, MAR-100).

Run from the repository root::

    uv run python research/scripts/c1_rq2_tables.py

Observations only. The interpretation is the owner's (MAR-29 section 8).
"""

# The Markdown and figure labels use the typographic minus sign (U+2212).
# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Final

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
FULL: Final[Path] = REPO_ROOT / "results" / "c1-rq2" / "full"
OUT: Final[Path] = REPO_ROOT / "research" / "data" / "c1-rq2"
FIGURES: Final[Path] = REPO_ROOT / "research" / "checkpoints" / "figures"

PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06", "coc_r0.10")
PRICING_LABEL: Final[dict[str, str]] = {
    "pure": "pure",
    "coc_r0.06": "CoC r 0.06",
    "coc_r0.10": "CoC r 0.10",
}
DESIGNS: Final[tuple[str, ...]] = ("mse", "eu", "wcvar@0.99", "wcvar@0.995")
DESIGN_LABEL: Final[dict[str, str]] = {
    "mse": "MSE",
    "eu": "E[U]",
    "wcvar@0.99": "wCVaR β 0.99",
    "wcvar@0.995": "wCVaR β 0.995",
}
F12_ORDER: Final[tuple[str, ...]] = ("cic50", "vuln", "cic50_vuln", "vuln_basins_null")
F12_DESIGNS: Final[tuple[str, ...]] = ("mse", "eu", "wcvar@0.99")
KAPPAS: Final[tuple[float, ...]] = (0.5, 1.0, 1.5)
BETAS: Final[tuple[float, ...]] = (0.95, 0.99, 0.995)
SCOPE_ORDER: Final[tuple[str, ...]] = (
    "individual",
    "cluster_separate",
    "cluster",
    "portfolio",
    "cluster_alt",
    "portfolio_alt",
)
SLIM_KPIS: Final[tuple[str, ...]] = (
    "expected_loss",
    "expected_payout",
    "expected_uncovered",
    "var_uncovered",
    "cvar_uncovered",
    "premium",
)
SLIM_PAIRED_KPIS: Final[tuple[str, ...]] = (
    "expected_payout",
    "expected_uncovered",
    "cvar_uncovered",
    "premium",
)
TAIL: Final[frozenset[str]] = frozenset({"var_uncovered", "cvar_uncovered"})
COLORS: Final[tuple[str, ...]] = ("#2a78d6", "#eb6834", "#1baf7a")
MARKERS: Final[tuple[str, ...]] = ("o", "s", "D")
INK: Final[str] = "#3b3b38"
GRID: Final[str] = "#e4e3df"


def _short(h: object) -> str:
    """First 12 hex digits of a config hash or derived id."""
    s = str(h)
    return s.split(":", 1)[1][:12] if ":" in s else s[:12]


def _set_label(design: str) -> str:
    """Objectives of a k-fold experiment config, from one of its designs."""
    return "wCVaR β 0.995" if design.endswith("0.995") else "MSE, E[U], wCVaR β 0.99"


def _end(x: float) -> str:
    """One end of a payout range; n/a if its range problem was not optimal."""
    if math.isnan(x):
        return "n/a"
    # solver round-off can put a smallest payout at -1e-9: show 0
    return f"{max(x, 0.0):.2f}"


def _int(x: float) -> str:
    return "n/a" if x is None or math.isnan(x) else f"{x:,.0f}"


def _pct(x: float) -> str:
    return "n/a" if x is None or math.isnan(x) else f"{100 * x:+.1f} %"


def _one_beta(frame: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Keep beta-free KPIs once (lowest evaluation beta of the group)."""
    first = frame.groupby(keys)["eval_beta"].transform("min")
    keep = frame["kpi"].isin(TAIL) | (frame["eval_beta"] == first)
    out = pd.DataFrame(frame.loc[keep]).copy()
    out.loc[~out["kpi"].isin(TAIL), "eval_beta"] = math.nan
    return out


# --------------------------------------------------------------------------
# Committed tables
# --------------------------------------------------------------------------


def write_slim(full: Path, out: Path) -> dict[str, pd.DataFrame]:
    """Write the committed CSVs and return them.

    Parameters
    ----------
    full : pathlib.Path
        ``results/c1-rq2/full``.
    out : pathlib.Path
        ``research/data/c1-rq2``.

    Returns
    -------
    dict of pandas.DataFrame
        The committed tables by file stem.
    """
    out.mkdir(parents=True, exist_ok=True)

    def both(name: str) -> pd.DataFrame:
        return pd.concat(
            [pd.read_csv(full / f"holdout_{f}_{name}.csv") for f in ("main", "f12")],
            ignore_index=True,
        )

    hk, hp, hr = both("kpis"), both("paired"), both("runs")
    kp = pd.read_csv(full / "kfold_pooled.csv")
    kpa = pd.read_csv(full / "kfold_paired.csv")
    kf = pd.read_csv(full / "kfold_folds.csv")
    kr = pd.read_csv(full / "kfold_runs.csv")
    ranges = pd.read_csv(full / "ranges.csv")
    kr["family"], kr["eventset"] = "main", "thesis"
    f12k = hk.loc[hk["family"] == "f12"]
    f12p = hp.loc[hp["family"] == "f12"]
    hk = hk.loc[hk["family"] == "main"]
    hp = hp.loc[hp["family"] == "main"]

    # portfolio KPIs: holdout train/test and pooled k-fold
    port = hk.loc[(hk["level"] == "portfolio") & hk["kpi"].isin(SLIM_KPIS)]
    port = port[
        [
            "split",
            "pricing",
            "kappa",
            "design",
            "scope",
            "kpi",
            "eval_beta",
            "value",
            "ci_low",
            "ci_high",
        ]
    ]
    port = _one_beta(port, ["split", "pricing", "kappa", "design", "scope"])
    pooled = kp.loc[kp["kpi"].isin(SLIM_KPIS)].copy()
    pooled["split"] = "pooled"
    pooled = pooled.drop_duplicates(
        ["pricing", "design", "scope", "kpi", "eval_beta"], keep="first"
    )
    pooled.loc[~pooled["kpi"].isin(TAIL), "eval_beta"] = math.nan
    scope_kpis = pd.concat(
        [port, pooled[port.columns.tolist()]], ignore_index=True
    ).sort_values(["split", "pricing", "kappa", "design", "scope", "kpi"])

    # paired scope differences
    cols = [
        "split",
        "pricing",
        "kappa",
        "design",
        "scope_a",
        "scope_b",
        "kpi",
        "eval_beta",
        "value_a",
        "value_b",
        "difference",
        "ci_low",
        "ci_high",
    ]
    hpp = hp.loc[hp["kpi"].isin(SLIM_PAIRED_KPIS), cols]
    hpp = _one_beta(hpp, ["split", "pricing", "kappa", "design", "scope_a", "scope_b"])
    kpp = kpa.loc[kpa["kpi"].isin(SLIM_PAIRED_KPIS)].copy()
    kpp = kpp.drop_duplicates(
        ["pricing", "design", "scope_a", "scope_b", "kpi", "eval_beta"], keep="first"
    )
    kpp.loc[~kpp["kpi"].isin(TAIL), "eval_beta"] = math.nan
    scope_paired = pd.concat([hpp, kpp[cols]], ignore_index=True)

    # the provisional F-12 sensitivities (C1 section 6): test and train
    fk = f12k.loc[(f12k["level"] == "portfolio") & f12k["kpi"].isin(SLIM_KPIS)]
    fk = _one_beta(
        fk[["eventset", *port.columns.tolist()]],
        ["eventset", "split", "pricing", "kappa", "design", "scope"],
    )
    fp = _one_beta(
        f12p.loc[f12p["kpi"].isin(SLIM_PAIRED_KPIS), ["eventset", *cols]],
        ["eventset", "split", "pricing", "kappa", "design", "scope_a", "scope_b"],
    )

    # payout per entity (and the entity's loss, which is data)
    ent = hk.loc[
        (hk["level"] == "entity")
        & hk["kpi"].isin(["expected_payout", "expected_loss"])
        & (hk["eval_beta"] == 0.99)
    ]
    ent = ent.pivot_table(
        index=[
            "split",
            "pricing",
            "kappa",
            "design",
            "scope",
            "subject_id",
            "entity_locations",
        ],
        columns="kpi",
        values="value",
    ).reset_index()
    grp = ent.groupby(["split", "pricing", "kappa", "design", "scope"])
    ent["payout_share"] = ent["expected_payout"] / grp["expected_payout"].transform(
        "sum"
    )
    ent["loss_share"] = ent["expected_loss"] / grp["expected_loss"].transform("sum")
    ent["payout_to_loss"] = ent["expected_payout"] / ent["expected_loss"]
    ent = ent.rename(columns={"subject_id": "entity_id"})

    # premiums: aggregate premium vs the sum of the problems' premiums
    pr = hk.loc[
        hk["kpi"].isin(["premium", "expected_payout"]) & (hk["eval_beta"] == 0.99)
    ]
    rows = []
    for key, g in pr.groupby(["split", "pricing", "kappa", "design", "scope"]):
        agg = g.loc[(g["level"] == "portfolio") & (g["kpi"] == "premium"), "value"]
        probs = g.loc[(g["level"] == "problem") & (g["kpi"] == "premium"), "value"]
        epi = g.loc[
            (g["level"] == "portfolio") & (g["kpi"] == "expected_payout"), "value"
        ]
        el = hk.loc[
            (hk["split"] == key[0])
            & (hk["pricing"] == key[1])
            & (hk["kappa"] == key[2])
            & (hk["design"] == key[3])
            & (hk["scope"] == key[4])
            & (hk["level"] == "portfolio")
            & (hk["kpi"] == "expected_loss")
            & (hk["eval_beta"] == 0.99),
            "value",
        ]
        rows.append(
            {
                "split": key[0],
                "pricing": key[1],
                "kappa": key[2],
                "design": key[3],
                "scope": key[4],
                "n_problems": len(probs),
                "aggregate_premium": float(agg.iloc[0]),
                "sum_problem_premiums": float(probs.sum()),
                "expected_payout": float(epi.iloc[0]),
                "expected_loss": float(el.iloc[0]),
            }
        )
    premiums = pd.DataFrame(rows)
    premiums["aggregate_to_sum"] = (
        premiums["aggregate_premium"] / premiums["sum_problem_premiums"]
    )
    premiums["budget_train"] = premiums["kappa"] * premiums.groupby(
        ["pricing", "kappa", "design"]
    )["expected_loss"].transform(lambda s: s.iloc[0])
    premiums.loc[premiums["split"] != "train", "budget_train"] = math.nan

    folds = kf.loc[
        kf["kpi"].isin(["expected_uncovered", "cvar_uncovered", "expected_payout"])
        & (kf["level"] == "portfolio"),
        [
            "pricing",
            "kappa",
            "design",
            "scope",
            "fold",
            "eval_split",
            "kpi",
            "beta",
            "value",
        ],
    ]

    runs = pd.concat(
        [
            hr.assign(kind="holdout", fold=pd.NA),
            kr.drop(columns=["kind"]).assign(kind="kfold"),
        ],
        ignore_index=True,
    )
    runs = runs[
        [
            "kind",
            "family",
            "eventset",
            "pricing",
            "kappa",
            "design",
            "scope",
            "fold",
            "n_problems",
            "statuses",
            "solvers",
            "config_hash",
            "base_config_hash",
            "experiment_config_hash",
            "run_id",
        ]
    ]
    tables = {
        "scope_kpis": scope_kpis,
        "scope_paired": scope_paired,
        "scope_kpis_f12": fk,
        "scope_paired_f12": fp,
        "entity_payouts": ent,
        "premiums": premiums,
        "kfold_folds": folds,
        "payout_ranges": ranges,
        "runs": runs,
    }
    for name, frame in tables.items():
        frame.to_csv(out / f"{name}.csv", index=False, float_format="%.7g")
    summary = {
        path.stem.removeprefix("summary_"): json.loads(path.read_text())
        for path in sorted(full.glob("summary_*.json"))
    }
    summary["committed_tables"] = {
        "runs.csv": "every design: config hash (or derived id), run id, statuses",
        "scope_kpis.csv": "portfolio KPIs: train, test (holdout), pooled (k-fold)",
        "scope_paired.csv": "scope differences: test and pooled with paired CIs",
        "scope_kpis_f12.csv": "the same on the provisional F-12 EventSets (C1 s. 6)",
        "scope_paired_f12.csv": "scope differences on the F-12 EventSets",
        "entity_payouts.csv": "expected payout and loss per payout entity",
        "premiums.csv": "aggregate premium vs the sum of the problem premiums",
        "kfold_folds.csv": "per-fold portfolio KPIs of the k-fold runs",
        "payout_ranges.csv": "per-entity payout range over the optimal set (F8)",
        "full tables": "results/c1-rq2/full/ (not committed), by c1_rq2.py",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return tables


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def _pair(
    paired: pd.DataFrame,
    split: str,
    pricing: str,
    kappa: float,
    design: str,
    a: str,
    b: str,
    kpi: str,
    beta: float | None,
) -> pd.Series | None:
    m = (
        (paired["split"] == split)
        & (paired["pricing"] == pricing)
        & (paired["kappa"] == kappa)
        & (paired["design"] == design)
        & (paired["scope_a"] == a)
        & (paired["scope_b"] == b)
        & (paired["kpi"] == kpi)
    )
    m &= paired["eval_beta"].isna() if beta is None else paired["eval_beta"] == beta
    rows = paired.loc[m]
    if rows.empty:
        return None
    if len(rows) > 1:
        raise RuntimeError(f"several rows for {split} {pricing} {design} {a}-{b}")
    return rows.iloc[0]


def _rel(row: pd.Series | None, ci: bool = True) -> str:
    """Relative difference with its paired interval; ``*`` if it excludes 0."""
    if row is None:
        return "n/a"
    base = float(row["value_b"])
    if abs(base) < 1.0:
        # b has (almost) no uncovered loss: a relative difference is undefined
        return f"{_int(float(row['difference']))} USD (b ≈ 0)"
    rel = float(row["difference"]) / base
    if not ci or math.isnan(float(row["ci_low"])):
        return _pct(rel)
    lo, hi = float(row["ci_low"]) / base, float(row["ci_high"]) / base
    star = "*" if lo > 0 or hi < 0 else ""
    return f"{_pct(rel)}{star} [{100 * lo:+.1f}, {100 * hi:+.1f}]"


def _abs(row: pd.Series | None) -> str:
    if row is None:
        return "n/a"
    return (
        f"{_int(float(row['difference']))} "
        f"[{_int(float(row['ci_low']))}, {_int(float(row['ci_high']))}]"
    )


def _hash_of(
    runs: pd.DataFrame,
    kind: str,
    pricing: str,
    kappa: float,
    design: str,
    scope: str,
    eventset: str = "thesis",
) -> str:
    r = runs.loc[
        (runs["kind"] == kind)
        & (runs["eventset"] == eventset)
        & (runs["pricing"] == pricing)
        & (runs["kappa"] == kappa)
        & (runs["design"] == design)
        & (runs["scope"] == scope)
    ]
    if kind == "kfold":
        return _short(r["experiment_config_hash"].iloc[0])
    return _short(r["config_hash"].iloc[0])


def markdown(t: dict[str, pd.DataFrame]) -> str:
    """Return every RQ2 table as Markdown.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        The committed tables (:func:`write_slim`).

    Returns
    -------
    str
        The Markdown document.
    """
    p, runs, k = t["scope_paired"], t["runs"], t["scope_kpis"]
    lines: list[str] = [
        "# C1 RQ2 addendum: generated tables (MAR-158)",
        "",
        "Generated by `research/scripts/c1_rq2_tables.py` from "
        "`research/data/c1-rq2/*.csv`. Relative differences are "
        "(a − b) / b; `*` marks a paired 90 % interval that excludes zero. "
        "Train values are in sample (point values, no interval). Hashes: "
        "first 12 hex digits of the config hash (`runs.csv`), or of the "
        "`derived:` id for designs solved by `c1_rq2.py`.",
        "",
    ]

    # T1 headline: joint minus individual, CVaR 0.99, kappa 1
    lines += [
        "## T1. Joint minus individual, CVaR₀.₉₉(U), κ = 1",
        "",
        "| Pricing | Design | Portfolio − individual, train | test [90 % CI] "
        "| pooled k-fold [90 % CI] | Cluster (different index) − individual, train "
        "| test [90 % CI] "
        "| pooled k-fold [90 % CI] | Hash individual / cluster / portfolio |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pricing in PRICINGS:
        for design in DESIGNS:
            cells = []
            for a in ("portfolio", "cluster"):
                for split in ("train", "test", "pooled"):
                    row = _pair(
                        p,
                        split,
                        pricing,
                        1.0,
                        design,
                        a,
                        "individual",
                        "cvar_uncovered",
                        0.99,
                    )
                    cells.append(
                        "not run"
                        if row is None and split == "pooled"
                        else _rel(row, ci=split != "train")
                    )
            hashes = " / ".join(
                f"`{_hash_of(runs, 'holdout', pricing, 1.0, design, s)}`"
                for s in ("individual", "cluster", "portfolio")
            )
            lines.append(
                f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[design]} | "
                + " | ".join(cells)
                + f" | {hashes} |"
            )
    lines.append("")
    kh = runs.loc[runs["kind"] == "kfold"].drop_duplicates(
        ["pricing", "experiment_config_hash"]
    )
    lines.append(
        "k-fold experiment hashes: "
        + "; ".join(
            f"{PRICING_LABEL[r.pricing]} {_set_label(str(r.design))}: "
            f"`{_short(r.experiment_config_hash)}`"
            for r in kh.itertuples()
        )
    )
    lines.append("")

    # T2 grid: test, every kappa and KPI beta
    for a, label in (
        ("portfolio", "Portfolio"),
        ("cluster", "Cluster (different index)"),
    ):
        lines += [
            f"## T2{a[0]}. {label} − individual, test CVaR_β(U), every κ and KPI β",
            "",
            "| Pricing | κ | Design | KPI β 0.95 | KPI β 0.99 | KPI β 0.995 "
            "| Δ E[U] | Δ E[π] |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for pricing in PRICINGS:
            for kappa in KAPPAS:
                for design in DESIGNS:
                    cells = [
                        _rel(
                            _pair(
                                p,
                                "test",
                                pricing,
                                kappa,
                                design,
                                a,
                                "individual",
                                "cvar_uncovered",
                                b,
                            )
                        )
                        for b in BETAS
                    ]
                    for kpi in ("expected_uncovered", "expected_payout"):
                        cells.append(
                            _rel(
                                _pair(
                                    p,
                                    "test",
                                    pricing,
                                    kappa,
                                    design,
                                    a,
                                    "individual",
                                    kpi,
                                    None,
                                )
                            )
                        )
                    lines.append(
                        f"| {PRICING_LABEL[pricing]} | {kappa:g} | "
                        f"{DESIGN_LABEL[design]} | " + " | ".join(cells) + " |"
                    )
        lines.append("")

    # T3 train counterpart of T2 at KPI beta 0.99/0.995
    lines += [
        "## T3. Joint − individual, train (in sample), every κ",
        "",
        "| Pricing | κ | Design | Portfolio CVaR₀.₉₉ | Portfolio CVaR₀.₉₉₅ "
        "| Portfolio E[U] | Cluster CVaR₀.₉₉ | Cluster CVaR₀.₉₉₅ | Cluster E[U] |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pricing in PRICINGS:
        for kappa in KAPPAS:
            for design in DESIGNS:
                cells = []
                for a in ("portfolio", "cluster"):
                    for kpi, b in (
                        ("cvar_uncovered", 0.99),
                        ("cvar_uncovered", 0.995),
                        ("expected_uncovered", None),
                    ):
                        cells.append(
                            _rel(
                                _pair(
                                    p,
                                    "train",
                                    pricing,
                                    kappa,
                                    design,
                                    a,
                                    "individual",
                                    kpi,
                                    b,
                                ),
                                ci=False,
                            )
                        )
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {kappa:g} | "
                    f"{DESIGN_LABEL[design]} | " + " | ".join(cells) + " |"
                )
    lines.append("")

    # T4 absolute values, kappa 1, KPI beta 0.99
    lines += [
        "## T4. Test values per scope, κ = 1, KPI β 0.99",
        "",
        "| Pricing | Design | Scope | Test CVaR₀.₉₉(U) [90 % CI] | Train "
        "CVaR₀.₉₉(U) | Test E[U] | Train E[π] | Test E[π] | Hash |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    def val(
        split: str, pricing: str, design: str, scope: str, kpi: str, beta: float | None
    ) -> pd.Series | None:
        m = (
            (k["split"] == split)
            & (k["pricing"] == pricing)
            & (k["kappa"] == 1.0)
            & (k["design"] == design)
            & (k["scope"] == scope)
            & (k["kpi"] == kpi)
        )
        m &= k["eval_beta"].isna() if beta is None else k["eval_beta"] == beta
        rows = k.loc[m]
        return None if rows.empty else rows.iloc[0]

    for pricing in PRICINGS:
        for design in DESIGNS:
            for scope in SCOPE_ORDER[:4]:
                c = val("test", pricing, design, scope, "cvar_uncovered", 0.99)
                ctr = val("train", pricing, design, scope, "cvar_uncovered", 0.99)
                eu = val("test", pricing, design, scope, "expected_uncovered", None)
                ept = val("train", pricing, design, scope, "expected_payout", None)
                epe = val("test", pricing, design, scope, "expected_payout", None)
                assert c is not None
                assert ctr is not None
                assert eu is not None
                assert ept is not None
                assert epe is not None
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[design]} | {scope} | "
                    f"{_int(c['value'])} [{_int(c['ci_low'])}, {_int(c['ci_high'])}] | "
                    f"{_int(ctr['value'])} | {_int(eu['value'])} | "
                    f"{_int(ept['value'])} | {_int(epe['value'])} | "
                    f"`{_hash_of(runs, 'holdout', pricing, 1.0, design, scope)}` |"
                )
    lines.append("")

    # T5 cluster decomposition, kappa 1, test, CVaR 0.99 and 0.995
    lines += [
        "## T5. The cluster scope, decomposed (κ = 1, test, paired 90 % CI)",
        "",
        "`cluster_separate`: the same three clusters and value-weighted index, "
        "each cluster calibrated on its own with budget κ·E[L_cluster].",
        "",
        "| Pricing | Design | KPI β | Cluster − individual | of which index "
        "(separate − individual) | of which joint (cluster − separate) | "
        "Train: index / joint | Hash separate |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for pricing in PRICINGS:
        for design in DESIGNS:
            for b in (0.99, 0.995):
                tot = _pair(
                    p,
                    "test",
                    pricing,
                    1.0,
                    design,
                    "cluster",
                    "individual",
                    "cvar_uncovered",
                    b,
                )
                idx = _pair(
                    p,
                    "test",
                    pricing,
                    1.0,
                    design,
                    "cluster_separate",
                    "individual",
                    "cvar_uncovered",
                    b,
                )
                jnt = _pair(
                    p,
                    "test",
                    pricing,
                    1.0,
                    design,
                    "cluster",
                    "cluster_separate",
                    "cvar_uncovered",
                    b,
                )
                tidx = _pair(
                    p,
                    "train",
                    pricing,
                    1.0,
                    design,
                    "cluster_separate",
                    "individual",
                    "cvar_uncovered",
                    b,
                )
                tjnt = _pair(
                    p,
                    "train",
                    pricing,
                    1.0,
                    design,
                    "cluster",
                    "cluster_separate",
                    "cvar_uncovered",
                    b,
                )
                sep = _hash_of(
                    runs, "holdout", pricing, 1.0, design, "cluster_separate"
                )
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[design]} | {b:g} | "
                    f"{_rel(tot)} | {_rel(idx)} | {_rel(jnt)} | "
                    f"{_rel(tidx, ci=False)} / {_rel(tjnt, ci=False)} | `{sep}` |"
                )
    lines.append("")

    # T6 payout shares, kappa 1
    e = t["entity_payouts"]
    for pricing in ("pure", "coc_r0.06"):
        lines += [
            f"## T6 ({PRICING_LABEL[pricing]}). Payout per asset, train, κ = 1: "
            "E[π_i] / E[L_i]",
            "",
            "Loss share = E[L_i] / Σ E[L] on the train years. Joint designs: one "
            "optimal split of a possibly non-unique optimum (MAR-100; T8).",
            "",
            "| Asset | Loss share | "
            + " | ".join(
                f"{DESIGN_LABEL[d]} {s}" for d in DESIGNS for s in ("ind.", "port.")
            )
            + " |",
            "|---|---|" + "---|" * (2 * len(DESIGNS)),
        ]
        sub = e.loc[
            (e["split"] == "train") & (e["pricing"] == pricing) & (e["kappa"] == 1.0)
        ]
        assets = sorted(sub.loc[sub["scope"] == "portfolio", "entity_id"].unique())
        for asset in assets:
            row = sub.loc[(sub["scope"] == "individual") & (sub["entity_id"] == asset)]
            cells = [f"{100 * float(row['loss_share'].iloc[0]):.1f} %"]
            for d in DESIGNS:
                for s in ("individual", "portfolio"):
                    r = sub.loc[
                        (sub["scope"] == s)
                        & (sub["design"] == d)
                        & (sub["entity_id"] == asset)
                    ]
                    cells.append(f"{float(r['payout_to_loss'].iloc[0]):.2f}")
            lines.append(f"| {asset} | " + " | ".join(cells) + " |")
        lines.append("")
        lines += [
            f"Clusters ({PRICING_LABEL[pricing]}, train, κ = 1): E[π_c] / E[L_c]",
            "",
            "| Cluster | Assets | Loss share | "
            + " | ".join(
                f"{DESIGN_LABEL[d]} {s}" for d in DESIGNS for s in ("sep.", "joint")
            )
            + " |",
            "|---|---|---|" + "---|" * (2 * len(DESIGNS)),
        ]
        cl = sub.loc[sub["scope"] == "cluster"]
        for c in sorted(cl["entity_id"].unique()):
            r0 = cl.loc[cl["entity_id"] == c].iloc[0]
            cells = [
                str(r0["entity_locations"]),
                f"{100 * float(r0['loss_share']):.1f} %",
            ]
            for d in DESIGNS:
                for s in ("cluster_separate", "cluster"):
                    r = sub.loc[
                        (sub["scope"] == s)
                        & (sub["design"] == d)
                        & (sub["entity_id"] == c)
                    ]
                    cells.append(f"{float(r['payout_to_loss'].iloc[0]):.2f}")
            lines.append(f"| {c} | " + " | ".join(cells) + " |")
        lines.append("")

    # T7 premiums
    pr = t["premiums"]
    lines += [
        "## T7. Aggregate premium against the sum of the problem premiums (train)",
        "",
        "Individual scope: 9 problems, each with its own budget; the aggregate "
        "premium prices the summed payout. Joint scopes: one problem, so the two "
        "are equal and the budget binds the aggregate premium.",
        "",
        "| Pricing | κ | Design | Individual: aggregate / Σ problems | Train E[π]: "
        "individual | cluster | portfolio | Test aggregate premium: individual | "
        "portfolio |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pricing in PRICINGS:
        for kappa in KAPPAS:
            for design in DESIGNS:
                q = pr.loc[
                    (pr["pricing"] == pricing)
                    & (pr["kappa"] == kappa)
                    & (pr["design"] == design)
                ]

                def g(split: str, scope: str, col: str, q: pd.DataFrame = q) -> float:
                    return float(
                        q.loc[(q["split"] == split) & (q["scope"] == scope), col].iloc[
                            0
                        ]
                    )

                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {kappa:g} | "
                    f"{DESIGN_LABEL[design]} | "
                    f"{g('train', 'individual', 'aggregate_to_sum'):.4f} | "
                    f"{_int(g('train', 'individual', 'expected_payout'))} | "
                    f"{_int(g('train', 'cluster', 'expected_payout'))} | "
                    f"{_int(g('train', 'portfolio', 'expected_payout'))} | "
                    f"{_int(g('test', 'individual', 'aggregate_premium'))} | "
                    f"{_int(g('test', 'portfolio', 'aggregate_premium'))} |"
                )
    lines.append("")

    # T8 second optimum
    lines += [
        "## T8. A second optimum of the joint designs (κ = 1)",
        "",
        "`_alt`: the same design problem solved with HiGHS first (LP) or "
        "CLARABEL first (QP). Train objective and train CVaR equal within "
        "solver tolerance; the per-asset split and the test KPIs can differ.",
        "",
        "| Pricing | Design | Scope | Train CVaR₀.₉₉ alt − C1 | Test CVaR₀.₉₉ alt − "
        "C1 [90 % CI] | Max |Δ payout share|, train (pp) | Hash alt |",
        "|---|---|---|---|---|---|---|",
    ]
    for pricing in PRICINGS:
        for design in DESIGNS:
            for scope in ("portfolio", "cluster"):
                tr = _pair(
                    p,
                    "train",
                    pricing,
                    1.0,
                    design,
                    scope + "_alt",
                    scope,
                    "cvar_uncovered",
                    0.99,
                )
                te = _pair(
                    p,
                    "test",
                    pricing,
                    1.0,
                    design,
                    scope + "_alt",
                    scope,
                    "cvar_uncovered",
                    0.99,
                )
                sub = e.loc[
                    (e["split"] == "train")
                    & (e["pricing"] == pricing)
                    & (e["kappa"] == 1.0)
                    & (e["design"] == design)
                ]
                base = sub.loc[sub["scope"] == scope].set_index("entity_id")
                alt = sub.loc[sub["scope"] == scope + "_alt"].set_index("entity_id")
                rel = (alt["payout_share"] - base["payout_share"]).abs().max()
                ah = _hash_of(runs, "holdout", pricing, 1.0, design, scope + "_alt")
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[design]} | {scope} | "
                    f"{_rel(tr, ci=False)} | {_rel(te)} | {100 * rel:.1f} | `{ah}` |"
                )
    lines.append("")

    # T9 k-fold per fold
    f = t["kfold_folds"]
    lines += [
        "## T9. k-fold: portfolio − individual per fold, CVaR₀.₉₉(U) (κ = 1)",
        "",
        "Train = the fold's 8,000 calibration years (in sample); test = its "
        "2,000 held-out years.",
        "",
        "| Pricing | Design | Split | Fold 0 | Fold 1 | Fold 2 | Fold 3 | Fold 4 | "
        "Pooled (all 10,000 years) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pricing in ("pure", "coc_r0.06"):
        for design in DESIGNS:
            for split in ("train", "test"):
                cells = []
                for fold in range(5):
                    vals = {}
                    for scope in ("portfolio", "individual"):
                        r = f.loc[
                            (f["pricing"] == pricing)
                            & (f["design"] == design)
                            & (f["scope"] == scope)
                            & (f["fold"] == fold)
                            & (f["eval_split"] == split)
                            & (f["kpi"] == "cvar_uncovered")
                        ]
                        vals[scope] = float(r["value"].iloc[0])
                    cells.append(_pct(vals["portfolio"] / vals["individual"] - 1))
                pooled = _pair(
                    p,
                    "pooled",
                    pricing,
                    1.0,
                    design,
                    "portfolio",
                    "individual",
                    "cvar_uncovered",
                    0.99,
                )
                cells.append(_rel(pooled) if split == "test" else "")
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[design]} | {split} | "
                    + " | ".join(cells)
                    + " |"
                )
    lines.append("")

    # T10 F-12, provisional
    fp = t["scope_paired_f12"]
    lines += [
        "## T10. Provisional F-12 EventSets (C1 section 6): joint − individual, "
        "CVaR₀.₉₉(U), κ = 1",
        "",
        "| EventSet | Pricing | Design | Portfolio − ind., train | test [90 % CI] "
        "| Cluster (different index) − ind., train | test [90 % CI] "
        "| Hash individual / cluster / "
        "portfolio |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for es in F12_ORDER:
        for pricing in ("pure", "coc_r0.06"):
            for design in F12_DESIGNS:
                sub = fp.loc[fp["eventset"] == es]
                cells = []
                for a in ("portfolio", "cluster"):
                    for split in ("train", "test"):
                        row = _pair(
                            sub,
                            split,
                            pricing,
                            1.0,
                            design,
                            a,
                            "individual",
                            "cvar_uncovered",
                            0.99,
                        )
                        cells.append(_rel(row, ci=split != "train"))
                hashes = " / ".join(
                    f"`{_hash_of(runs, 'holdout', pricing, 1.0, design, sc, es)}`"
                    for sc in ("individual", "cluster", "portfolio")
                )
                lines.append(
                    f"| `{es}` | {PRICING_LABEL[pricing]} | {DESIGN_LABEL[design]} | "
                    + " | ".join(cells)
                    + f" | {hashes} |"
                )

    # T11 payout ranges over the optimal set
    rg = t["payout_ranges"]
    n_inaccurate = int(
        ((rg["status_min"] != "optimal") | (rg["status_max"] != "optimal")).sum()
    )
    lines += [
        "## T11. How unique is a joint design's split? Train E[π_j] / E[L_j] "
        "over the near-optimal set (κ = 1)",
        "",
        "For each entity: the stored design's value, and the smallest and largest "
        "value over all designs whose objective is within "
        f"{rg['rel_tol'].iloc[0]:g} (relative) of the optimum, under the design "
        "problem's constraints (CLARABEL; `c1_rq2.py` phase `ranges`). n/a: "
        "that range problem ended `optimal_inaccurate` (`payout_ranges.csv`, "
        f"{n_inaccurate} of the entities).",
        "",
        "| Pricing | Design | Scope | "
        + " | ".join(
            f"{e}"
            for e in sorted(rg.loc[rg["scope"] == "portfolio", "entity_id"].unique())
        )
        + " |",
        "|---|---|---|" + "---|" * 9,
    ]
    for pricing in ("pure", "coc_r0.06"):
        for design in DESIGNS:
            for scope in ("portfolio", "cluster"):
                sub = rg.loc[
                    (rg["pricing"] == pricing)
                    & (rg["design"] == design)
                    & (rg["scope"] == scope)
                ].sort_values("entity_id")
                cells = [
                    f"{r.stored_payout_to_loss:.2f} "
                    f"[{_end(r.min_payout_to_loss)}, {_end(r.max_payout_to_loss)}]"
                    for r in sub.itertuples()
                ]
                cells += [""] * (9 - len(cells))
                label = (
                    "cluster: "
                    + ", ".join(sub["entity_id"] + " = " + sub["entity_locations"])
                    if scope == "cluster"
                    else scope
                )
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[design]} | {label} | "
                    + " | ".join(cells)
                    + " |"
                )
    lines.append("")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Figure
# --------------------------------------------------------------------------


def figure(t: dict[str, pd.DataFrame], path: Path) -> None:
    """Joint minus individual along train, test and pooled k-fold.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        The committed tables.
    path : pathlib.Path
        Output PNG.
    """
    p = t["scope_paired"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 5.2), sharex=True, sharey=True)
    splits = (
        ("train", "train (in sample)"),
        ("test", "holdout test"),
        ("pooled", "pooled 5-fold"),
    )
    for ax, pricing in zip(axes, ("pure", "coc_r0.06"), strict=True):
        labels: list[str] = []
        y = 0.0
        for a in ("portfolio", "cluster"):
            for design in DESIGNS:
                for i, (split, name) in enumerate(splits):
                    row = _pair(
                        p,
                        split,
                        pricing,
                        1.0,
                        design,
                        a,
                        "individual",
                        "cvar_uncovered",
                        0.99,
                    )
                    if row is None:
                        continue
                    base = float(row["value_b"])
                    x = 100 * float(row["difference"]) / base
                    yy = y + (i - 1) * 0.25
                    if split != "train":
                        lo = 100 * float(row["ci_low"]) / base
                        hi = 100 * float(row["ci_high"]) / base
                        ax.plot([lo, hi], [yy, yy], color=COLORS[i], linewidth=1.6)
                    ax.plot(
                        x,
                        yy,
                        marker=MARKERS[i],
                        color=COLORS[i],
                        linestyle="none",
                        markersize=5,
                        label=name if y == 0.0 else None,
                    )
                name = "cluster (diff. index)" if a == "cluster" else a
                labels.append(f"{name} − ind., {DESIGN_LABEL[design]}")
                y += 1.0
        ax.set_yticks(range(len(labels)), labels, fontsize=8)
        ax.axvline(0, color=INK, linewidth=0.8)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(colors=INK, labelsize=8)
        ax.set_title(f"{PRICING_LABEL[pricing]}, κ = 1", fontsize=10, color=INK)
        ax.set_xlabel(
            "Δ CVaR₀.₉₉ of annual uncovered loss, % of individual",
            fontsize=8,
            color=INK,
        )
    axes[0].invert_yaxis()  # shared y axis: invert once
    handles, names = axes[0].get_legend_handles_labels()
    # the right panel's differences sit near zero: room for the legend
    axes[1].legend(handles, names, loc="lower right", fontsize=8, frameon=False)
    fig.suptitle(
        "Joint minus individual calibration, thesis portfolio (9 Miami assets), "
        "annual basis; bars: paired 90 % CI",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    """Write the committed tables, the Markdown tables and the figure.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description="C1 RQ2 tables (MAR-158).")
    parser.add_argument("--full", type=Path, default=FULL)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--figures", type=Path, default=FIGURES)
    args = parser.parse_args(argv)
    tables = write_slim(args.full, args.out)
    (args.out / "tables.md").write_text(markdown(tables).rstrip("\n") + "\n")
    figure(tables, args.figures / "c1_rq2_scopes.png")
    print(f"wrote {args.out} and {args.figures / 'c1_rq2_scopes.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
