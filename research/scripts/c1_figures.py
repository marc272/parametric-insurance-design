r"""Figures and Markdown tables of checkpoint C1 (MAR-29).

Reads ``research/data/c1/{kpis,paired,runs}.csv`` (written by
``c1_checkpoint.py``) and writes

* ``research/checkpoints/figures/c1_*.png``: the figures of ``C1.md``;
* ``research/data/c1/tables.md``: every table of ``C1.md``, generated, so
  each number in the note can be traced to a CSV row and its config hash.

Run from the repository root::

    uv run python research/scripts/c1_figures.py

Observations only. The interpretation is the owner's (MAR-29).
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Final

import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DATA: Final[Path] = REPO_ROOT / "research" / "data" / "c1"
FIGURES: Final[Path] = REPO_ROOT / "research" / "checkpoints" / "figures"

SCOPES: Final[tuple[str, ...]] = ("individual", "cluster", "portfolio")
PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06", "coc_r0.10")
PRICING_LABEL: Final[dict[str, str]] = {
    "pure": "pure",
    "coc_r0.06": "CoC r=0.06, q=0.99",
    "coc_r0.10": "CoC r=0.10, q=0.99",
}
DESIGN_LABEL: Final[dict[str, str]] = {"mse": "MSE", "eu": "E[U]"}
F12_ORDER: Final[tuple[str, ...]] = (
    "thesis",
    "cic50",
    "vuln",
    "cic50_vuln",
    "vuln_basins_null",
)
F12_LABEL: Final[dict[str, str]] = {
    "thesis": "thesis noise layer (main line)",
    "cic50": "cat-in-circle 50 km, no draws",
    "vuln": "wind + draws (default prior)",
    "cic50_vuln": "cat-in-circle 50 km + draws",
    "vuln_basins_null": "wind + draws (basins: null)",
}
# Reference palette (dataviz skill), slots 1-3, validated for the light
# surface; markers differ too, so identity is never colour alone.
COLORS: Final[tuple[str, ...]] = ("#2a78d6", "#eb6834", "#1baf7a")
MARKERS: Final[tuple[str, ...]] = ("o", "s", "D")
INK: Final[str] = "#3b3b38"
GRID: Final[str] = "#e4e3df"

HEADLINE_DESIGN: Final[str] = "wcvar@0.99"
HEADLINE_BETA: Final[float] = 0.99


def _style(ax: plt.Axes) -> None:
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK)
    ax.tick_params(colors=INK, labelsize=8)
    ax.axvline(0, color=INK, linewidth=0.8)


def _pct(x: float) -> str:
    return f"{100 * x:+.1f} %"


def _money(x: float) -> str:
    return f"{x:,.0f}"


def _hash(h: str) -> str:
    return f"`{h.removeprefix('sha256:')[:12]}`"


def select(
    paired: pd.DataFrame,
    *,
    family: str,
    kpi: str,
    eval_beta: float,
    eventset: str = "thesis",
    kappa: float = 1.0,
) -> pd.DataFrame:
    """Paired rows of one family / KPI / evaluation beta."""
    q = paired.loc[
        (paired["family"] == family)
        & (paired["eventset"] == eventset)
        & (paired["kpi"] == kpi)
        & (paired["eval_beta"] == eval_beta)
        & (paired["kappa"] == kappa)
    ]
    return pd.DataFrame(q)


def fig_headline(paired: pd.DataFrame, out: Path) -> None:
    """Forest plot: wCVaR(0.99) - MSE / - E[U], test CVaR_0.99, per pricing."""
    q = select(paired, family="main", kpi="cvar_uncovered", eval_beta=HEADLINE_BETA)
    q = q.loc[q["design_a"] == HEADLINE_DESIGN]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.0), sharex=True, sharey=True)
    for ax, scope in zip(axes, SCOPES, strict=True):
        _style(ax)
        for j, b in enumerate(("mse", "eu")):
            for i, pricing in enumerate(PRICINGS):
                r = q.loc[(q["scope"] == scope) & (q["design_b"] == b)]
                r = r.loc[r["pricing"] == pricing].iloc[0]
                y = i + (j - 0.5) * 0.25
                ax.errorbar(
                    100 * r["relative"],
                    y,
                    xerr=[
                        [100 * (r["relative"] - r["ci_low_relative"])],
                        [100 * (r["ci_high_relative"] - r["relative"])],
                    ],
                    fmt=MARKERS[j],
                    color=COLORS[j],
                    markersize=5,
                    elinewidth=1.5,
                    capsize=0,
                    label=f"vs {DESIGN_LABEL[b]}" if i == 0 else None,
                )
        ax.set_title(scope, fontsize=9, color=INK)
        ax.set_yticks(range(len(PRICINGS)), [PRICING_LABEL[p] for p in PRICINGS])
        ax.invert_yaxis()
        ax.set_xlabel("paired difference in test CVaR$_{0.99}$(U), %", fontsize=8)
    axes[0].legend(fontsize=8, frameon=False, loc="lower left")
    fig.suptitle(
        "Weighted CVaR (alpha 0.9, beta 0.99) minus MSE / E[U]: annual basis, "
        "test years 7,000-9,999, κ = 1, 90 % paired CI",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_lines(
    paired: pd.DataFrame, out: Path, *, x: str, title: str, xlabel: str
) -> None:
    """Relative paired difference vs MSE (rows: CVaR_0.99, E[U]) along x."""
    fig, axes = plt.subplots(2, 3, figsize=(10, 5.2), sharex=True)
    for row, kpi in enumerate(("cvar_uncovered", "expected_uncovered")):
        for col, scope in enumerate(SCOPES):
            ax = axes[row, col]
            ax.grid(axis="y", color=GRID, linewidth=0.8)
            ax.set_axisbelow(True)
            for side in ("top", "right"):
                ax.spines[side].set_visible(False)
            ax.tick_params(colors=INK, labelsize=8)
            ax.axhline(0, color=INK, linewidth=0.8)
            for i, pricing in enumerate(PRICINGS):
                q = paired.loc[
                    (paired["family"] == "main")
                    & (paired["kpi"] == kpi)
                    & (paired["eval_beta"] == HEADLINE_BETA)
                    & (paired["design_b"] == "mse")
                    & (paired["scope"] == scope)
                    & (paired["pricing"] == pricing)
                ]
                if x == "beta":
                    q = q.loc[q["kappa"] == 1.0].copy()
                    q["x"] = q["design_a"].str.removeprefix("wcvar@").astype(float)
                else:
                    q = q.loc[q["design_a"] == HEADLINE_DESIGN].copy()
                    q["x"] = q["kappa"]
                q = q.sort_values("x")
                ax.fill_between(
                    q["x"],
                    100 * q["ci_low_relative"],
                    100 * q["ci_high_relative"],
                    color=COLORS[i],
                    alpha=0.15,
                    linewidth=0,
                )
                ax.plot(
                    q["x"],
                    100 * q["relative"],
                    marker=MARKERS[i],
                    color=COLORS[i],
                    linewidth=2,
                    markersize=5,
                    label=PRICING_LABEL[pricing],
                )
            if row == 0:
                ax.set_title(scope, fontsize=9, color=INK)
            if col == 0:
                ax.set_ylabel(
                    {
                        "cvar_uncovered": "Δ test CVaR$_{0.99}$(U) vs MSE, %",
                        "expected_uncovered": "Δ test E[U] vs MSE, %",
                    }[kpi],
                    fontsize=8,
                )
            if row == 1:
                ax.set_xlabel(xlabel, fontsize=8)
    axes[0, 0].legend(fontsize=7, frameon=False)
    fig.suptitle(title, fontsize=9, color=INK)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_f12(paired: pd.DataFrame, out: Path) -> None:
    """Forest plot of the provisional F-12 sensitivities (pure and r 0.06)."""
    q = paired.loc[
        (paired["kpi"] == "cvar_uncovered")
        & (paired["eval_beta"] == HEADLINE_BETA)
        & (paired["design_a"] == HEADLINE_DESIGN)
        & (paired["kappa"] == 1.0)
        & (paired["family"].isin(["main", "f12"]))
        & (paired["pricing"].isin(["pure", "coc_r0.06"]))
    ]
    rows = [(e, p) for e in F12_ORDER for p in ("pure", "coc_r0.06")]
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.2), sharey=True)
    for ax, scope in zip(axes, SCOPES, strict=True):
        _style(ax)
        for j, b in enumerate(("mse", "eu")):
            for i, (e, p) in enumerate(rows):
                r = q.loc[
                    (q["scope"] == scope)
                    & (q["design_b"] == b)
                    & (q["eventset"] == e)
                    & (q["pricing"] == p)
                ]
                if r.empty:
                    continue
                r = r.iloc[0]
                ax.errorbar(
                    100 * r["relative"],
                    i + (j - 0.5) * 0.3,
                    xerr=[
                        [100 * (r["relative"] - r["ci_low_relative"])],
                        [100 * (r["ci_high_relative"] - r["relative"])],
                    ],
                    fmt=MARKERS[j],
                    color=COLORS[j],
                    markersize=4,
                    elinewidth=1.3,
                    capsize=0,
                    label=f"vs {DESIGN_LABEL[b]}" if i == 0 else None,
                )
        ax.set_yticks(
            range(len(rows)),
            [f"{F12_LABEL[e]} | {PRICING_LABEL[p]}" for e, p in rows],
        )
        ax.invert_yaxis()
        ax.set_title(scope, fontsize=9, color=INK)
        ax.set_xlabel("paired Δ test CVaR$_{0.99}$(U), %", fontsize=8)
    axes[0].legend(fontsize=8, frameon=False, loc="lower left")
    fig.suptitle(
        "PROVISIONAL (prior: MAR-118 Q5, radius: Q6 open). Weighted CVaR (β 0.99) "
        "minus MSE / E[U], annual basis, test years, κ = 1, 90 % paired CI",
        fontsize=9,
        color=INK,
    )
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# --------------------------------------------------------------------------
# Markdown tables
# --------------------------------------------------------------------------


def _kpi(
    kpis: pd.DataFrame,
    *,
    family: str,
    eventset: str,
    pricing: str,
    kappa: float,
    scope: str,
    design: str,
    kpi: str,
    eval_beta: float,
    split: str = "test",
    source: str = "c1_bootstrap",
) -> pd.Series:
    q = kpis.loc[
        (kpis["family"] == family)
        & (kpis["eventset"] == eventset)
        & (kpis["pricing"] == pricing)
        & (kpis["kappa"] == kappa)
        & (kpis["scope"] == scope)
        & (kpis["design"] == design)
        & (kpis["kpi"] == kpi)
        & (kpis["eval_beta"] == eval_beta)
        & (kpis["eval_split"] == split)
        & (kpis["source"] == source)
    ]
    if len(q) != 1:
        raise RuntimeError(f"{len(q)} rows for {family} {pricing} {scope} {design}")
    return q.iloc[0]


def _ci(r: pd.Series) -> str:
    return f"{_money(r['value'])} [{_money(r['ci_low'])}, {_money(r['ci_high'])}]"


def _diff(r: pd.Series) -> str:
    return (
        f"{_money(r['difference'])} [{_money(r['ci_low'])}, {_money(r['ci_high'])}]"
        f" ({_pct(r['relative'])})"
    )


def _excl(r: pd.Series) -> str:
    if r["ci_high"] < 0:
        return "< 0"
    if r["ci_low"] > 0:
        return "> 0"
    return "contains 0"


def headline_tables(kpis: pd.DataFrame, paired: pd.DataFrame) -> list[str]:
    """Per pricing: test KPIs with CIs and the paired differences, per scope."""
    out: list[str] = []
    designs = ("mse", "eu", HEADLINE_DESIGN)
    for pricing in PRICINGS:
        out.append(f"\n#### {PRICING_LABEL[pricing]}, κ = 1\n")
        out.append(
            "| Scope | Design | Test CVaR₀.₉₉(U) [90 % CI] | Test E[U] [90 % CI] "
            "| Train CVaR₀.₉₉(U) | Budget use | Config hash |"
        )
        out.append("|---|---|---|---|---|---|---|")
        for scope in SCOPES:
            for d in designs:
                kw = {
                    "family": "main",
                    "eventset": "thesis",
                    "pricing": pricing,
                    "kappa": 1.0,
                    "scope": scope,
                    "design": d,
                }
                c = _kpi(kpis, **kw, kpi="cvar_uncovered", eval_beta=0.99)
                e = _kpi(kpis, **kw, kpi="expected_uncovered", eval_beta=0.99)
                t = _kpi(
                    kpis,
                    **kw,
                    kpi="cvar_uncovered",
                    eval_beta=0.99,
                    split="train",
                    source="runner",
                )
                out.append(
                    f"| {scope} | {d} | {_ci(c)} | {_ci(e)} | {_money(t['value'])} "
                    f"| {{budget:{c['run_id']}}} | {_hash(c['config_hash'])} |"
                )
        out.append("")
        out.append(
            "| Scope | Δ CVaR₀.₉₉ vs MSE [90 % CI] | vs E[U] "
            "| Δ E[U] vs MSE | vs E[U] |"
        )
        out.append("|---|---|---|---|---|")
        q = select(paired, family="main", kpi="cvar_uncovered", eval_beta=0.99)
        qe = select(paired, family="main", kpi="expected_uncovered", eval_beta=0.99)
        for scope in SCOPES:
            cells = []
            for frame in (q, qe):
                for b in ("mse", "eu"):
                    r = frame.loc[
                        (frame["scope"] == scope)
                        & (frame["pricing"] == pricing)
                        & (frame["design_a"] == HEADLINE_DESIGN)
                        & (frame["design_b"] == b)
                    ].iloc[0]
                    cells.append(_diff(r))
            out.append(f"| {scope} | " + " | ".join(cells) + " |")
    return out


def beta_table(paired: pd.DataFrame) -> list[str]:
    """Relative paired differences along the design beta (kappa 1)."""
    out = [
        "| Pricing | Scope | KPI β | vs | "
        + " | ".join(f"β {b:g}" for b in (0.95, 0.97, 0.98, 0.99, 0.995))
        + " |",
        "|---|---|---|---|" + "---|" * 5,
    ]
    for pricing in PRICINGS:
        for scope in SCOPES:
            for eb in (0.95, 0.99, 0.995):
                for b in ("mse", "eu"):
                    q = select(
                        paired, family="main", kpi="cvar_uncovered", eval_beta=eb
                    )
                    q = q.loc[
                        (q["pricing"] == pricing)
                        & (q["scope"] == scope)
                        & (q["design_b"] == b)
                    ]
                    cells = []
                    for beta in (0.95, 0.97, 0.98, 0.99, 0.995):
                        r = q.loc[q["design_a"] == f"wcvar@{beta:g}"].iloc[0]
                        mark = "" if _excl(r) == "contains 0" else "*"
                        cells.append(f"{_pct(r['relative'])}{mark}")
                    out.append(
                        f"| {PRICING_LABEL[pricing]} | {scope} | {eb:g} | "
                        f"{DESIGN_LABEL[b]} | " + " | ".join(cells) + " |"
                    )
    return out


def kappa_table(paired: pd.DataFrame) -> list[str]:
    """Paired differences of wCVaR(0.99) along kappa."""
    out = [
        "| Pricing | Scope | vs | κ 0.5 | κ 1 | κ 1.5 |",
        "|---|---|---|---|---|---|",
    ]
    q = paired.loc[
        (paired["family"] == "main")
        & (paired["kpi"] == "cvar_uncovered")
        & (paired["eval_beta"] == 0.99)
        & (paired["design_a"] == HEADLINE_DESIGN)
    ]
    for pricing in PRICINGS:
        for scope in SCOPES:
            for b in ("mse", "eu"):
                cells = []
                for k in (0.5, 1.0, 1.5):
                    r = q.loc[
                        (q["pricing"] == pricing)
                        & (q["scope"] == scope)
                        & (q["design_b"] == b)
                        & (q["kappa"] == k)
                    ].iloc[0]
                    cells.append(
                        f"{_pct(r['relative'])} [{_pct(r['ci_low_relative'])}, "
                        f"{_pct(r['ci_high_relative'])}]"
                    )
                out.append(
                    f"| {PRICING_LABEL[pricing]} | {scope} | {DESIGN_LABEL[b]} | "
                    + " | ".join(cells)
                    + " |"
                )
    return out


def reference_table(paired: pd.DataFrame) -> list[str]:
    """event_conditional reference column: wCVaR(0.95) - MSE / - E[U]."""
    out = [
        "| Pricing | Scope | KPI | Δ vs MSE [90 % CI] | Δ vs E[U] [90 % CI] | "
        "Hash wCVaR / MSE / E[U] |",
        "|---|---|---|---|---|---|",
    ]
    for pricing in PRICINGS:
        for scope in SCOPES:
            for eb in (0.95, 0.99):
                q = paired.loc[
                    (paired["family"] == "reference")
                    & (paired["kpi"] == "cvar_uncovered")
                    & (paired["eval_beta"] == eb)
                    & (paired["pricing"] == pricing)
                    & (paired["scope"] == scope)
                ]
                rm = q.loc[q["design_b"] == "mse"].iloc[0]
                re = q.loc[q["design_b"] == "eu"].iloc[0]
                out.append(
                    f"| {PRICING_LABEL[pricing]} | {scope} | CVaR_{eb:g} (per event) | "
                    f"{_diff(rm)} | {_diff(re)} | {_hash(rm['config_hash_a'])} / "
                    f"{_hash(rm['config_hash_b'])} / {_hash(re['config_hash_b'])} |"
                )
    return out


def f12_table(paired: pd.DataFrame, summary_hashes: dict[str, str]) -> list[str]:
    """Provisional F-12 sensitivities, wCVaR(0.99) on test CVaR_0.99."""
    out = [
        "| EventSet | Pricing | Scope | Δ CVaR₀.₉₉ vs MSE [90 % CI] | vs E[U] | "
        "Δ E[U] vs MSE | Hash wCVaR / MSE / E[U] |",
        "|---|---|---|---|---|---|---|",
    ]
    for e in F12_ORDER:
        for pricing in ("pure", "coc_r0.06"):
            for scope in SCOPES:
                fam = "main" if e == "thesis" else "f12"
                q = paired.loc[
                    (paired["family"] == fam)
                    & (paired["eventset"] == e)
                    & (paired["kappa"] == 1.0)
                    & (paired["eval_beta"] == 0.99)
                    & (paired["pricing"] == pricing)
                    & (paired["scope"] == scope)
                    & (paired["design_a"] == HEADLINE_DESIGN)
                ]
                if q.empty:
                    continue
                c = q.loc[q["kpi"] == "cvar_uncovered"]
                u = q.loc[q["kpi"] == "expected_uncovered"]
                rm = c.loc[c["design_b"] == "mse"].iloc[0]
                re = c.loc[c["design_b"] == "eu"].iloc[0]
                um = u.loc[u["design_b"] == "mse"].iloc[0]
                out.append(
                    f"| {F12_LABEL[e]} | {PRICING_LABEL[pricing]} | {scope} | "
                    f"{_diff(rm)} | {_diff(re)} | {_pct(um['relative'])} "
                    f"[{_pct(um['ci_low_relative'])}, {_pct(um['ci_high_relative'])}]"
                    f" | {_hash(rm['config_hash_a'])} / {_hash(rm['config_hash_b'])}"
                    f" / {_hash(re['config_hash_b'])} |"
                )
    del summary_hashes
    return out


def _every_beta(frame: pd.DataFrame, key: list[str]) -> pd.DataFrame:
    """Repeat the beta-free KPI rows (stored once) at every evaluation beta."""
    tail = frame["kpi"].isin(("var_uncovered", "cvar_uncovered"))
    betas = frame.loc[tail, [*key, "eval_beta"]].drop_duplicates()
    free = frame.loc[~tail].drop(columns="eval_beta").merge(betas, on=key)
    return pd.concat([frame.loc[tail], free], ignore_index=True)


def load(data: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the committed tables; join config hashes and run ids from runs.csv."""
    runs = pd.read_csv(data / "runs.csv")
    kpis = pd.concat(
        [pd.read_csv(p) for p in sorted(data.glob("kpis_*.csv"))], ignore_index=True
    )
    paired = pd.concat(
        [pd.read_csv(p) for p in sorted(data.glob("paired_*.csv"))], ignore_index=True
    )
    key = ["family", "eventset", "basis", "pricing", "kappa", "scope"]
    kpis = _every_beta(kpis, [*key, "source", "eval_split"])
    paired = _every_beta(paired, [*key, "eval_split"])
    ids = runs[[*key, "design", "config_hash", "run_id"]]
    kpis = kpis.merge(ids, on=[*key, "design"], how="left", validate="many_to_one")
    for side in ("a", "b"):
        renamed = ids.rename(
            columns={
                "design": f"design_{side}",
                "config_hash": f"config_hash_{side}",
                "run_id": f"run_id_{side}",
            }
        )
        paired = paired.merge(
            renamed, on=[*key, f"design_{side}"], how="left", validate="many_to_one"
        )
    if kpis["config_hash"].isna().any() or paired["config_hash_a"].isna().any():
        raise RuntimeError("a KPI row has no run in runs.csv")
    paired["relative"] = paired["difference"] / paired["value_b"]
    paired["ci_low_relative"] = paired["ci_low"] / paired["value_b"]
    paired["ci_high_relative"] = paired["ci_high"] / paired["value_b"]
    return kpis, paired, runs


def main(argv: list[str] | None = None) -> int:
    """Write the figures and ``tables.md``."""
    parser = argparse.ArgumentParser(description="C1 figures and tables (MAR-29).")
    parser.add_argument("--data", type=Path, default=DATA)
    parser.add_argument("--figures", type=Path, default=FIGURES)
    args = parser.parse_args(argv)
    kpis, paired, runs = load(args.data)
    args.figures.mkdir(parents=True, exist_ok=True)

    fig_headline(paired, args.figures / "c1_headline.png")
    fig_lines(
        paired,
        args.figures / "c1_beta.png",
        x="beta",
        xlabel="design β of the weighted-CVaR objective",
        title="Weighted CVaR (alpha 0.9) minus MSE along the design β: annual basis, "
        "test years, κ = 1, KPI at 0.99, 90 % paired CI",
    )
    fig_lines(
        paired,
        args.figures / "c1_kappa.png",
        x="kappa",
        xlabel="budget loading κ (premium ≤ κ·E[L])",
        title="Weighted CVaR (β 0.99) minus MSE along the budget loading κ: annual "
        "basis, test years, KPI at 0.99, 90 % paired CI",
    )
    if (paired["family"] == "f12").any():
        fig_f12(paired, args.figures / "c1_f12_provisional.png")

    budget = dict(zip(runs["run_id"], runs["budget_use"], strict=True))
    lines = ["# C1 tables (generated by research/scripts/c1_figures.py)", ""]
    lines += ["## Headline (main line)", *headline_tables(kpis, paired), ""]
    lines += ["## Design β grid (relative Δ CVaR, * = 90 % CI excludes 0)"]
    lines += [*beta_table(paired), ""]
    lines += ["## κ sweep", *kappa_table(paired), ""]
    lines += ["## event_conditional reference", *reference_table(paired), ""]
    if (paired["family"] == "f12").any():
        lines += ["## F-12 provisional", *f12_table(paired, {}), ""]
    text = "\n".join(lines).rstrip("\n") + "\n"
    for rid, use in budget.items():
        text = text.replace(f"{{budget:{rid}}}", f"{use:.4f}")
    (args.data / "tables.md").write_text(text)
    print(f"wrote {args.figures} and {args.data / 'tables.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
