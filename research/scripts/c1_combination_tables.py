r"""Committed tables and Markdown tables of the C1 combination view (MAR-182).

Reads the full tables that ``c1_combination.py`` writes to
``results/c1-combination/full/`` (not committed) and writes to
``research/data/c1-combination/``:

* ``runs.csv``: every design used, holdout and k-fold, with its config hash,
  run id, statuses, solvers and budget use (the other tables carry the
  12-hex prefix of the config hash);
* ``grid.csv``, ``grid_f12.csv``: portfolio KPIs per split (train, test,
  pooled), scope and design, with 90 % intervals (test, pooled);
* ``contrasts.csv`` (test and pooled), ``contrasts_train.csv`` (in sample,
  point values), ``contrasts_f12.csv``: the contrasts of the module
  docstring of ``c1_combination.py``, absolute and relative to the
  reference design, with paired 90 % intervals;
* ``tables.md``: every table of ``research/notes/c1-combination.md``,
  generated, so each number can be traced to a CSV row and its hash;
* ``summary.json``: inputs, checks, timings.

Addendum (MAR-194; ``--parts addendum``): ``kfold_addendum_*.csv`` (item 1,
pooled 5-fold at kappa 0.5 and r 0.10), ``sites_*.csv`` (item 2, per-site
KPIs of the individual designs), ``alt_*.csv`` (item 3, the contrasts with
the joint designs' second optima), ``tables_addendum.md`` (T11-T20) and
``summary_addendum.json``. ``--parts main`` rewrites MAR-182's files
byte-identically.

Run from the repository root, after ``c1_combination.py``::

    uv run python research/scripts/c1_combination_tables.py

Observations only. The interpretation is the owner's.
"""

# The Markdown labels use the typographic minus sign (U+2212).
# ruff: noqa: RUF001

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Callable
from pathlib import Path
from typing import Final

import numpy as np
import pandas as pd

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
FULL: Final[Path] = REPO_ROOT / "results" / "c1-combination" / "full"
OUT: Final[Path] = REPO_ROOT / "research" / "data" / "c1-combination"

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
    "": "",
}
SCOPES: Final[tuple[str, ...]] = ("individual", "cluster", "portfolio")
SCOPE_LABEL: Final[dict[str, str]] = {
    "individual": "individual",
    "cluster": "cluster (different index)",
    "portfolio": "portfolio",
    "": "",
}
KAPPAS: Final[tuple[float, ...]] = (0.5, 1.0, 1.5)
BETAS: Final[tuple[float, ...]] = (0.95, 0.99, 0.995)
CONFIG_BETA: Final[float] = 0.99
"""Beta-free KPIs are kept at the configs' ``evaluation.beta``."""
F12_ORDER: Final[tuple[str, ...]] = ("cic50", "vuln", "cic50_vuln", "vuln_basins_null")
TAIL: Final[frozenset[str]] = frozenset({"var_uncovered", "cvar_uncovered"})
COMPARISON_LABEL: Final[dict[str, str]] = {
    "both": "vs individual {o} (both ideas against neither)",
    "adds_rq2": "vs individual {w} (adds RQ2)",
    "adds_rq1": "vs {j} {o} (adds RQ1)",
}
KPI_LABEL: Final[dict[str, str]] = {
    "cvar_uncovered": "CVaR",
    "expected_uncovered": "E[U]",
    "expected_payout": "E[π]",
}
SLIM_CONTRAST_COLUMNS: Final[tuple[str, ...]] = (
    "split",
    "pricing",
    "kappa",
    "contrast",
    "joint_scope",
    "tail_design",
    "base_design",
    "kpi",
    "eval_beta",
    "value",
    "ci_low",
    "ci_high",
    "value_ref",
    "rel",
    "rel_ci_low",
    "rel_ci_high",
    "hash_a",
    "hash_b",
    "hash_c",
    "hash_d",
)


def _short(h: object) -> str:
    """First 12 hex digits of a config hash."""
    if h is None or (isinstance(h, float) and math.isnan(h)) or h == "":
        return ""
    s = str(h)
    return s.split(":", 1)[1][:12] if ":" in s else s[:12]


def _int(x: float) -> str:
    if x is None or math.isnan(x):
        return "n/a"
    # no "-0" for a tiny negative value
    return f"{round(x) + 0:,.0f}".replace("-", "−")


def _pct(x: float) -> str:
    return "n/a" if math.isnan(x) else f"{100 * x:+.1f} %".replace("-", "−")


def _num(x: float) -> str:
    return f"{x:+.1f}".replace("-", "−")


# --------------------------------------------------------------------------
# Committed tables
# --------------------------------------------------------------------------


def _relative(frame: pd.DataFrame) -> pd.DataFrame:
    """Add rel, rel_ci_low, rel_ci_high (null where the reference is ~0)."""
    out = frame.copy()
    ref = out["value_ref"].where(out["value_ref"].abs() >= 1.0)
    out["rel"] = out["value"] / ref
    out["rel_ci_low"] = out["ci_low"] / ref
    out["rel_ci_high"] = out["ci_high"] / ref
    return out


def load(full: Path) -> dict[str, pd.DataFrame]:
    """Read the full tables and add the relative columns.

    Parameters
    ----------
    full : pathlib.Path
        ``results/c1-combination/full``.

    Returns
    -------
    dict of pandas.DataFrame
        ``grid``, ``contrasts`` (main and F-12, holdout and pooled), ``runs``.
    """
    grid = pd.concat(
        [
            pd.read_csv(full / "holdout_main_grid.csv"),
            pd.read_csv(full / "kfold_grid.csv"),
            pd.read_csv(full / "holdout_f12_grid.csv"),
        ],
        ignore_index=True,
    )
    con = pd.concat(
        [
            pd.read_csv(full / "holdout_main_contrasts.csv"),
            pd.read_csv(full / "kfold_contrasts.csv"),
            pd.read_csv(full / "holdout_f12_contrasts.csv"),
        ],
        ignore_index=True,
    )
    for column in ("joint_scope", "tail_design", "base_design"):
        con[column] = con[column].fillna("")
    # beta-free KPIs were contrasted at every KPI beta: keep them once
    tail = con["kpi"].isin(TAIL)
    con = con.loc[tail | (con["eval_beta"] == CONFIG_BETA)].copy()
    con.loc[~con["kpi"].isin(TAIL), "eval_beta"] = math.nan
    for column in ("hash_a", "hash_b", "hash_c", "hash_d"):
        con[column] = con[column].map(_short)
    grid["hash"] = grid["config_hash"].map(_short)
    runs = pd.concat(
        [
            pd.read_csv(full / "holdout_main_runs.csv"),
            pd.read_csv(full / "holdout_f12_runs.csv"),
            pd.read_csv(full / "kfold_runs.csv"),
        ],
        ignore_index=True,
    )
    # the compute phase concatenates groups in completion order: sort, so that
    # a rerun writes byte-identical tables
    variant = ["family", "eventset", "pricing", "kappa"]
    grid = grid.sort_values(
        [*variant, "split", "scope", "design", "kpi", "eval_beta"], kind="stable"
    )
    con = con.sort_values(
        [
            *variant,
            "split",
            "contrast",
            "joint_scope",
            "tail_design",
            "base_design",
            "kpi",
            "eval_beta",
        ],
        kind="stable",
    )
    runs = runs.sort_values(
        ["kind", *variant, "scope", "design", "fold"], kind="stable"
    )
    return {
        "grid": grid.reset_index(drop=True),
        "contrasts": _relative(con.reset_index(drop=True)),
        "runs": runs.reset_index(drop=True),
    }


def write_slim(t: dict[str, pd.DataFrame], out: Path) -> dict[str, int]:
    """Write the committed CSVs.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        :func:`load` output.
    out : pathlib.Path
        ``research/data/c1-combination``.

    Returns
    -------
    dict
        File name to row count.
    """
    out.mkdir(parents=True, exist_ok=True)
    grid, con, runs = t["grid"], t["contrasts"], t["runs"]
    columns = [
        "split",
        "pricing",
        "kappa",
        "scope",
        "design",
        "kpi",
        "eval_beta",
        "value",
        "ci_low",
        "ci_high",
        "hash",
    ]
    main = grid["family"] == "main"
    cmain = con["family"] == "main"
    files = {
        "grid.csv": grid.loc[main, columns],
        "grid_f12.csv": grid.loc[~main, ["eventset", *columns]],
        "contrasts.csv": con.loc[cmain & (con["split"] != "train")],
        "contrasts_train.csv": con.loc[cmain & (con["split"] == "train")],
        "contrasts_f12.csv": con.loc[~cmain],
    }
    counts: dict[str, int] = {}
    for name, frame in files.items():
        if name.startswith("contrasts"):
            cols = list(SLIM_CONTRAST_COLUMNS)
            if "f12" in name:
                cols = ["eventset", *cols]
            if "train" in name:
                cols = [c for c in cols if not c.startswith(("ci_", "rel_ci_"))]
            frame = frame[cols]
        frame.to_csv(out / name, index=False, float_format="%.7g")
        counts[name] = len(frame)
    run_cols = [
        "kind",
        "family",
        "eventset",
        "pricing",
        "kappa",
        "scope",
        "design",
        "fold",
        "n_problems",
        "statuses",
        "solvers",
        "budget_use",
        "config_hash",
        "run_id",
        "experiment_config_hash",
    ]
    runs = runs.reindex(columns=run_cols)
    runs["fold"] = runs["fold"].astype("Int64")
    runs.to_csv(out / "runs.csv", index=False, float_format="%.10g")
    counts["runs.csv"] = len(runs)
    return counts


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


def _one(frame: pd.DataFrame, **where: object) -> pd.Series | None:
    """Return the single row matching ``where`` (None matches a null)."""
    mask = pd.Series(True, index=frame.index)
    for column, value in where.items():
        if value is None:
            mask &= frame[column].isna()
        else:
            mask &= frame[column] == value
    rows = frame.loc[mask]
    if rows.empty:
        return None
    if len(rows) > 1:
        raise RuntimeError(f"several rows for {where}")
    return rows.iloc[0]


def _rel(row: pd.Series | None, ci: bool = True) -> str:
    """Relative contrast with its paired interval; ``*`` if it excludes 0."""
    if row is None:
        return "not run"
    if math.isnan(float(row["rel"])):
        return f"{_int(float(row['value']))} USD (ref ≈ 0)"
    if not ci or math.isnan(float(row["ci_low"])):
        return _pct(float(row["rel"]))
    lo, hi = float(row["rel_ci_low"]), float(row["rel_ci_high"])
    star = "*" if lo > 0 or hi < 0 else ""
    return f"{_pct(float(row['rel']))}{star} [{_num(100 * lo)}, {_num(100 * hi)}]"


def _abs(row: pd.Series | None, ci: bool = True) -> str:
    """Absolute contrast in USD with its paired interval."""
    if row is None:
        return "not run"
    v = _int(float(row["value"]))
    if not ci or math.isnan(float(row["ci_low"])):
        return v
    lo, hi = float(row["ci_low"]), float(row["ci_high"])
    star = "*" if lo > 0 or hi < 0 else ""
    return f"{v}{star} [{_int(lo)}, {_int(hi)}]"


def _kpi_where(kpi: str, beta: float | None) -> dict[str, object]:
    return {"kpi": kpi, "eval_beta": beta if kpi in TAIL else None}


def _grid_cell(row: pd.Series | None, ci: bool = True) -> str:
    if row is None:
        return "not run"
    v = _int(float(row["value"]))
    if not ci or math.isnan(float(row["ci_low"])):
        return v
    return f"{v} [{_int(float(row['ci_low']))}, {_int(float(row['ci_high']))}]"


def _hashes(row: pd.Series | None, n: int = 2) -> str:
    if row is None:
        return ""
    return " / ".join(f"`{row[f'hash_{x}']}`" for x in "abcd"[:n])


def _contrast(
    con: pd.DataFrame,
    split: str,
    pricing: str,
    kappa: float,
    name: str,
    j: str,
    w: str,
    o: str,
    kpi: str,
    beta: float | None,
    eventset: str = "thesis",
) -> pd.Series | None:
    return _one(
        con,
        eventset=eventset,
        split=split,
        pricing=pricing,
        kappa=kappa,
        contrast=name,
        joint_scope=j if name != "rq1_alone" else "",
        tail_design=w if name != "rq2_alone" else "",
        base_design=o if name != "adds_rq2" else "",
        **_kpi_where(kpi, beta),
    )


def _grid_getter(
    grid: pd.DataFrame, pricing: str, kappa: float, scope: str, design: str
) -> Callable[[str, str, float | None], pd.Series | None]:
    """Look up one main-line design's grid rows by split, KPI and beta."""

    def g(split: str, kpi: str, beta: float | None) -> pd.Series | None:
        return _one(
            grid,
            family="main",
            split=split,
            pricing=pricing,
            kappa=kappa,
            scope=scope,
            design=design,
            **_kpi_where(kpi, beta),
        )

    return g


def table_grid_k1(grid: pd.DataFrame) -> list[str]:
    """T1: the grid at kappa 1, per pricing."""
    lines = [
        "## T1. The grid at κ = 1: every scope × objective, train, holdout test "
        "and pooled 5-fold",
        "",
        "Portfolio-level KPIs (USD per year), annual basis, thesis portfolio. "
        "Test and pooled: 90 % year-block bootstrap intervals (B 1000, seed 0). "
        "Train: in sample, point values. Budget use: the design problems' "
        "premiums on the train years over κ·E[L] (holdout calibration). Hash: "
        "the holdout run's config hash (pooled: the k-fold experiment hashes in "
        "the note). `not run`: no k-fold runs at r 0.10 (MAR-158 scope).",
        "",
    ]
    for pricing in PRICINGS:
        lines += [
            f"### {PRICING_LABEL[pricing]}",
            "",
            "| Scope | Objective | Train CVaR₀.₉₉(U) | Test CVaR₀.₉₉(U) [90 % CI] | "
            "Pooled CVaR₀.₉₉(U) [90 % CI] | Test CVaR₀.₉₉₅(U) | "
            "Test E[U] [90 % CI] | Pooled E[U] | Budget use | Hash |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for scope in SCOPES:
            for design in DESIGNS:
                g = _grid_getter(grid, pricing, 1.0, scope, design)
                use = g("train", "budget_use", None)
                tr = g("train", "cvar_uncovered", 0.99)
                assert tr is not None
                assert use is not None
                lines.append(
                    f"| {SCOPE_LABEL[scope]} | {DESIGN_LABEL[design]} | "
                    f"{_grid_cell(tr, ci=False)} | "
                    f"{_grid_cell(g('test', 'cvar_uncovered', 0.99))} | "
                    f"{_grid_cell(g('pooled', 'cvar_uncovered', 0.99))} | "
                    f"{_grid_cell(g('test', 'cvar_uncovered', 0.995), ci=False)} | "
                    f"{_grid_cell(g('test', 'expected_uncovered', None))} | "
                    f"{_grid_cell(g('pooled', 'expected_uncovered', None), ci=False)}"
                    f" | {float(use['value']):.3f} | `{tr['hash']}` |"
                )
        lines.append("")
    return lines


def table_grid_all(grid: pd.DataFrame) -> list[str]:
    """T2: the holdout grid at every kappa and KPI beta (test)."""
    lines = [
        "## T2. The holdout grid at every κ: test CVaR at KPI β 0.95, 0.99, "
        "0.995, E[U] and budget use",
        "",
        "Test values with 90 % intervals for CVaR₀.₉₉ and E[U]; the other "
        "CVaR columns are point values (intervals in `grid.csv`).",
        "",
        "| Pricing | κ | Scope | Objective | CVaR₀.₉₅ | CVaR₀.₉₉ [90 % CI] | "
        "CVaR₀.₉₉₅ | E[U] [90 % CI] | Budget use | Hash |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for pricing in PRICINGS:
        for kappa in KAPPAS:
            for scope in SCOPES:
                for design in DESIGNS:
                    g = _grid_getter(grid, pricing, kappa, scope, design)
                    use = g("train", "budget_use", None)
                    c99 = g("test", "cvar_uncovered", 0.99)
                    assert use is not None
                    assert c99 is not None
                    lines.append(
                        f"| {PRICING_LABEL[pricing]} | {kappa:g} | "
                        f"{SCOPE_LABEL[scope]} | {DESIGN_LABEL[design]} | "
                        f"{_grid_cell(g('test', 'cvar_uncovered', 0.95), False)} | "
                        f"{_grid_cell(c99)} | "
                        f"{_grid_cell(g('test', 'cvar_uncovered', 0.995), False)} | "
                        f"{_grid_cell(g('test', 'expected_uncovered', None))} | "
                        f"{float(use['value']):.3f} | `{c99['hash']}` |"
                    )
    lines.append("")
    return lines


def table_comparisons(con: pd.DataFrame, j: str, o: str, title: str) -> list[str]:
    """T3/T7/T8: the combination against each baseline at kappa 1."""
    lines = [
        title,
        "",
        f"Joint scope {SCOPE_LABEL[j]}, tail objective a weighted CVaR, "
        f"baseline objective {DESIGN_LABEL[o]}; κ 1. Relative to the baseline "
        "design's value (train: in sample; test: holdout; pooled: 5-fold). "
        "`*`: the paired 90 % interval excludes zero. Hashes: combination / "
        "baseline (holdout runs).",
        "",
        "| Pricing | Tail design | Comparison | KPI | Train | Test [90 % CI] | "
        "Pooled [90 % CI] | Hashes |",
        "|---|---|---|---|---|---|---|---|",
    ]
    kpis: list[tuple[str, float | None]] = [
        ("cvar_uncovered", 0.99),
        ("cvar_uncovered", 0.995),
        ("cvar_uncovered", 0.95),
        ("expected_uncovered", None),
    ]
    for pricing in PRICINGS:
        for w in ("wcvar@0.99", "wcvar@0.995"):
            for name in ("both", "adds_rq2", "adds_rq1"):
                label = COMPARISON_LABEL[name].format(
                    j=j, o=DESIGN_LABEL[o], w=DESIGN_LABEL[w]
                )
                for kpi, beta in kpis:
                    args = (pricing, 1.0, name, j, w, o, kpi, beta)
                    tr = _contrast(con, "train", *args)
                    te = _contrast(con, "test", *args)
                    po = _contrast(con, "pooled", *args)
                    kl = KPI_LABEL[kpi] + (f" {beta:g}" if beta else "")
                    lines.append(
                        f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[w]} | {label} "
                        f"| {kl} | {_rel(tr, ci=False)} | {_rel(te)} | {_rel(po)} | "
                        f"{_hashes(te)} |"
                    )
    lines.append("")
    return lines


def table_decomposition(con: pd.DataFrame, j: str, o: str, title: str) -> list[str]:
    """T4: both = RQ1 alone + RQ2 alone + interaction, kappa 1."""
    lines = [
        title,
        "",
        f"(J, W) − (I, O) = [(I, W) − (I, O)] + [(J, O) − (I, O)] + "
        f"[(J, W) − (J, O) − (I, W) + (I, O)], with J = {j}, I = individual, "
        f"O = {DESIGN_LABEL[o]}, W the tail design; κ 1. Each term in USD with "
        "its paired 90 % interval (same resample), and relative to the "
        "individual O design. The interaction is also (J, W) − (I, W) − "
        "[(J, O) − (I, O)]: how much the joint gain depends on the objective. "
        "Hashes of the four designs: (J, W) / (J, O) / (I, W) / (I, O).",
        "",
        "| Pricing | Tail design | KPI | Split | Both (J, W) − (I, O) | "
        "RQ1 alone | RQ2 alone | Interaction | Interaction, relative | Hashes |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    kpis: list[tuple[str, float | None]] = [
        ("cvar_uncovered", 0.99),
        ("cvar_uncovered", 0.995),
        ("cvar_uncovered", 0.95),
        ("expected_uncovered", None),
    ]
    for pricing in PRICINGS:
        for w in ("wcvar@0.99", "wcvar@0.995"):
            for kpi, beta in kpis:
                for split in ("train", "test", "pooled"):
                    ci = split != "train"
                    args = (split, pricing, 1.0)
                    both = _contrast(con, *args, "both", j, w, o, kpi, beta)
                    r1 = _contrast(con, *args, "rq1_alone", j, w, o, kpi, beta)
                    r2 = _contrast(con, *args, "rq2_alone", j, w, o, kpi, beta)
                    ix = _contrast(con, *args, "interaction", j, w, o, kpi, beta)
                    if both is None:
                        if split == "pooled":
                            lines.append(
                                f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[w]} | "
                                f"{KPI_LABEL[kpi]}{f' {beta:g}' if beta else ''} | "
                                "pooled | not run | | | | | |"
                            )
                        continue
                    kl = KPI_LABEL[kpi] + (f" {beta:g}" if beta else "")
                    lines.append(
                        f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[w]} | {kl} | "
                        f"{split} | {_abs(both, ci)} | {_abs(r1, ci)} | "
                        f"{_abs(r2, ci)} | {_abs(ix, ci)} | {_rel(ix, ci)} | "
                        f"{_hashes(ix, 4)} |"
                    )
    lines.append("")
    return lines


def table_across_kappa(con: pd.DataFrame) -> list[str]:
    """T5: the combination and the interaction at every kappa (holdout test)."""
    lines = [
        "## T5. Every κ (holdout test): the combination against individual MSE, "
        "and the interaction",
        "",
        "Portfolio scope, baseline MSE. Relative to the individual MSE design, "
        "with paired 90 % intervals; `*` excludes zero. Train values in "
        "`contrasts_train.csv`.",
        "",
        "| Pricing | κ | Tail design | KPI | Both vs individual MSE | "
        "Adds RQ2 (vs individual W) | Adds RQ1 (vs portfolio MSE) | "
        "Interaction | Hashes (J, W) / (I, O) |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pricing in PRICINGS:
        for kappa in KAPPAS:
            for w in ("wcvar@0.99", "wcvar@0.995"):
                for kpi, beta in (
                    ("cvar_uncovered", 0.99),
                    ("cvar_uncovered", 0.995),
                    ("expected_uncovered", None),
                ):
                    a = ("test", pricing, kappa)
                    j, o = "portfolio", "mse"
                    both = _contrast(con, *a, "both", j, w, o, kpi, beta)
                    r2 = _contrast(con, *a, "adds_rq2", j, w, o, kpi, beta)
                    r1 = _contrast(con, *a, "adds_rq1", j, w, o, kpi, beta)
                    ix = _contrast(con, *a, "interaction", j, w, o, kpi, beta)
                    kl = KPI_LABEL[kpi] + (f" {beta:g}" if beta else "")
                    lines.append(
                        f"| {PRICING_LABEL[pricing]} | {kappa:g} | {DESIGN_LABEL[w]} "
                        f"| {kl} | {_rel(both)} | {_rel(r2)} | {_rel(r1)} | "
                        f"{_rel(ix)} | {_hashes(both)} |"
                    )
    lines.append("")
    return lines


def table_f12(con: pd.DataFrame) -> list[str]:
    """T9: the F-12 EventSets (provisional)."""
    lines = [
        "## T9. Realistic basis risk (F-12, provisional): the combination on the "
        "C1 F-12 EventSets",
        "",
        "κ 1, weighted CVaR β 0.99, baseline MSE, portfolio scope; holdout "
        "test, relative to the baseline design with paired 90 % intervals "
        "(train in sample). Provisional: MAR-118 Q5 (prior) and Q6 (radius) "
        "are open (C1.md section 6). No β 0.995 design and no k-fold runs on "
        "these EventSets. Hashes (J, W) / (J, O) / (I, W) / (I, O).",
        "",
        "| EventSet | Pricing | KPI | Both, train | Both vs individual MSE | "
        "Adds RQ2 | Adds RQ1 | RQ1 alone | RQ2 alone | Interaction | Hashes |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for es in F12_ORDER:
        for pricing in ("pure", "coc_r0.06"):
            for kpi, beta in (
                ("cvar_uncovered", 0.99),
                ("cvar_uncovered", 0.995),
                ("expected_uncovered", None),
            ):
                j, w, o = "portfolio", "wcvar@0.99", "mse"
                a = ("test", pricing, 1.0)
                cells = [
                    _contrast(con, *a, n, j, w, o, kpi, beta, eventset=es)
                    for n in (
                        "both",
                        "adds_rq2",
                        "adds_rq1",
                        "rq1_alone",
                        "rq2_alone",
                        "interaction",
                    )
                ]
                tr = _contrast(
                    con, "train", pricing, 1.0, "both", j, w, o, kpi, beta, eventset=es
                )
                kl = KPI_LABEL[kpi] + (f" {beta:g}" if beta else "")
                lines.append(
                    f"| `{es}` | {PRICING_LABEL[pricing]} | {kl} | "
                    f"{_rel(tr, ci=False)} | "
                    + " | ".join(_rel(c) for c in cells)
                    + f" | {_hashes(cells[-1], 4)} |"
                )
    lines.append("")
    return lines


def table_counts(con: pd.DataFrame) -> list[str]:
    """T10: how many paired intervals exclude zero, per contrast type."""
    lines = [
        "## T10. Counts over the holdout grid: intervals excluding zero",
        "",
        "Main line, holdout test, every pricing and κ (9 variants), KPI CVaR at "
        "β 0.95, 0.99, 0.995 and E[U]; joint scope J and tail design W as "
        "listed, baseline O ∈ {MSE, E[U]} where the contrast has one. "
        "`below` / `above`: the paired 90 % interval lies below / above zero.",
        "",
        "| Contrast | J | Cells | Below zero | Above zero | Contains zero |",
        "|---|---|---|---|---|---|",
    ]
    t = con.loc[
        (con["family"] == "main")
        & (con["split"] == "test")
        & con["kpi"].isin(["cvar_uncovered", "expected_uncovered"])
    ]
    t = t.drop_duplicates(
        [
            "pricing",
            "kappa",
            "contrast",
            "joint_scope",
            "tail_design",
            "base_design",
            "kpi",
            "eval_beta",
        ]
    )
    for name in (
        "both",
        "adds_rq2",
        "adds_rq1",
        "rq1_alone",
        "rq2_alone",
        "interaction",
    ):
        for j in ("portfolio", "cluster"):
            part = t.loc[t["contrast"] == name]
            if name != "rq1_alone":
                part = part.loc[part["joint_scope"] == j]
            elif j == "cluster":
                continue
            below = int((part["ci_high"] < 0).sum())
            above = int((part["ci_low"] > 0).sum())
            jl = "" if name == "rq1_alone" else SCOPE_LABEL[j]
            lines.append(
                f"| {name} | {jl} | {len(part)} | {below} | {above} | "
                f"{len(part) - below - above} |"
            )
    lines.append("")
    return lines


def markdown(t: dict[str, pd.DataFrame]) -> str:
    """Every table of the note, as Markdown.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        :func:`load` output.

    Returns
    -------
    str
        ``tables.md``.
    """
    con, grid = t["contrasts"], t["grid"]
    lines = [
        "# C1 combination view (MAR-182): generated tables",
        "",
        "Generated by `research/scripts/c1_combination_tables.py` from the "
        "CSVs in this folder; do not edit. Setup: "
        "`research/notes/c1-combination.md` section 2 (C1.md section 2 and "
        "6b.1). Hashes are the first 12 hex digits of the `sha256:` config "
        "hash; `runs.csv` has the full hashes and run ids. Observations only.",
        "",
    ]
    lines += table_grid_k1(grid)
    lines += table_grid_all(grid)
    lines += table_comparisons(
        con,
        "portfolio",
        "mse",
        "## T3. The combination against each baseline (portfolio scope, MSE), κ = 1",
    )
    lines += table_decomposition(
        con,
        "portfolio",
        "mse",
        "## T4. Decomposition and interaction (portfolio scope, MSE), κ = 1",
    )
    lines += table_across_kappa(con)
    lines += table_comparisons(
        con,
        "cluster",
        "mse",
        "## T6. The combination with the cluster scope (a different index), κ = 1",
    )
    lines += table_decomposition(
        con,
        "cluster",
        "mse",
        "## T7. Decomposition and interaction, cluster scope (a different "
        "index), κ = 1",
    )
    lines += table_decomposition(
        con,
        "portfolio",
        "eu",
        "## T8. Decomposition and interaction against E[U] (portfolio scope), κ = 1",
    )
    lines += table_f12(con)
    lines += table_counts(con)
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------
# Addendum (MAR-194)
# --------------------------------------------------------------------------

MAR182_SUMMARIES: Final[tuple[str, ...]] = ("holdout_f12", "holdout_main", "kfold")
"""The phases whose summaries go into ``summary.json`` (MAR-182's)."""
ADDENDUM_SUMMARIES: Final[tuple[str, ...]] = ("kfold_addendum", "sites", "alt")
KFOLD_VARIANTS: Final[tuple[tuple[str, float], ...]] = (
    ("pure", 1.0),
    ("coc_r0.06", 1.0),
    ("pure", 0.5),
    ("coc_r0.06", 0.5),
    ("coc_r0.10", 1.0),
)
"""Every pooled 5-fold variant: MAR-158's (kappa 1) and MAR-194 item 1's."""
NEW_KFOLD: Final[tuple[tuple[str, float], ...]] = KFOLD_VARIANTS[2:]
SITES: Final[tuple[str, ...]] = tuple(f"A{i}" for i in range(1, 10))
VERSION_LABEL: Final[dict[tuple[str, str], str]] = {
    ("c1", "c1"): "C1 / C1",
    ("alt", "alt"): "alt / alt",
    ("c1", "alt"): "C1 / alt",
    ("alt", "c1"): "alt / C1",
}
"""(tail-design version, base-design version) of the joint designs."""
CONTRAST_LABEL: Final[dict[str, str]] = {
    "both": "both (J, W) − (I, O)",
    "adds_rq2": "adds RQ2 (J, W) − (I, W)",
    "adds_rq1": "adds RQ1 (J, W) − (J, O)",
    "rq1_alone": "RQ1 alone (I, W) − (I, O)",
    "rq2_alone": "RQ2 alone (J, O) − (I, O)",
    "interaction": "interaction",
}
MATCHED: Final[tuple[tuple[str, str, float | None], ...]] = (
    ("wcvar@0.99", "cvar_uncovered", 0.99),
    ("wcvar@0.99", "cvar_uncovered", 0.995),
    ("wcvar@0.99", "expected_uncovered", None),
    ("wcvar@0.995", "cvar_uncovered", 0.995),
    ("wcvar@0.995", "cvar_uncovered", 0.99),
    ("wcvar@0.995", "expected_uncovered", None),
)
"""(tail design, KPI, KPI beta) rows of the addendum tables."""
SITE_COLUMNS: Final[tuple[str, ...]] = (
    "split",
    "pricing",
    "kappa",
    "site",
    "tail_design",
    "base_design",
    "kpi",
    "eval_beta",
    "value",
    "ci_low",
    "ci_high",
    "value_ref",
    "rel",
    "hash_a",
    "hash_b",
)


def _dedupe_contrasts(con: pd.DataFrame) -> pd.DataFrame:
    """Keep beta-free KPIs once, shorten hashes, add the relative columns."""
    con = con.copy()
    for column in ("joint_scope", "tail_design", "base_design"):
        if column in con.columns:
            con[column] = con[column].fillna("")
    tail = con["kpi"].isin(TAIL)
    con = con.loc[tail | (con["eval_beta"] == CONFIG_BETA)].copy()
    con.loc[~con["kpi"].isin(TAIL), "eval_beta"] = math.nan
    for column in ("hash_a", "hash_b", "hash_c", "hash_d"):
        if column in con.columns:
            con[column] = con[column].map(_short)
    return _relative(con.reset_index(drop=True))


def load_addendum(full: Path) -> dict[str, pd.DataFrame]:
    """Read the MAR-194 full tables (phases kfold_addendum, sites, alt).

    Parameters
    ----------
    full : pathlib.Path
        ``results/c1-combination/full``.

    Returns
    -------
    dict of pandas.DataFrame
        ``kgrid``, ``kcon``, ``kruns`` (item 1), ``sgrid``, ``scon`` (item 2),
        ``agrid``, ``acon``, ``adesigns`` (item 3), each sorted so that a
        rerun writes byte-identical files.
    """
    variant = ["pricing", "kappa"]
    order = [
        "contrast",
        "joint_scope",
        "tail_design",
        "base_design",
        "kpi",
        "eval_beta",
    ]
    kgrid = pd.read_csv(full / "kfold_addendum_grid.csv")
    kgrid["hash"] = kgrid["config_hash"].map(_short)
    kgrid = kgrid.sort_values(
        [*variant, "scope", "design", "kpi", "eval_beta"], kind="stable"
    )
    kcon = _dedupe_contrasts(pd.read_csv(full / "kfold_addendum_contrasts.csv"))
    kcon = kcon.sort_values([*variant, "split", *order], kind="stable")
    kruns = pd.read_csv(full / "kfold_addendum_runs.csv").sort_values(
        [*variant, "scope", "design", "fold"], kind="stable"
    )
    sgrid = pd.read_csv(full / "sites_grid.csv")
    sgrid["hash"] = sgrid["config_hash"].map(_short)
    sgrid = sgrid.sort_values(
        [*variant, "split", "site", "design", "kpi", "eval_beta"], kind="stable"
    )
    scon = pd.read_csv(full / "sites_contrasts.csv")
    for column in ("hash_a", "hash_b"):
        scon[column] = scon[column].map(_short)
    scon = _relative(scon)
    scon = scon.sort_values(
        [*variant, "split", "site", "tail_design", "base_design", "kpi", "eval_beta"],
        kind="stable",
    )
    agrid = pd.read_csv(full / "alt_grid.csv")
    agrid["hash"] = agrid["config_hash"].map(_short)
    agrid = agrid.sort_values(
        [*variant, "split", "scope", "design", "kpi", "eval_beta"], kind="stable"
    )
    acon = _dedupe_contrasts(pd.read_csv(full / "alt_contrasts.csv"))
    acon = acon.sort_values(
        [*variant, "split", "tail_version", "base_version", *order], kind="stable"
    )
    adesigns = pd.read_csv(full / "alt_designs.csv").sort_values(
        [*variant, "scope", "design"], kind="stable"
    )
    return {
        "kgrid": kgrid.reset_index(drop=True),
        "kcon": kcon.reset_index(drop=True),
        "kruns": kruns.reset_index(drop=True),
        "sgrid": sgrid.reset_index(drop=True),
        "scon": scon.reset_index(drop=True),
        "agrid": agrid.reset_index(drop=True),
        "acon": acon.reset_index(drop=True),
        "adesigns": adesigns.reset_index(drop=True),
    }


def write_addendum(a: dict[str, pd.DataFrame], out: Path) -> dict[str, int]:
    """Write the MAR-194 committed CSVs (each under 500 kB).

    Parameters
    ----------
    a : dict of pandas.DataFrame
        :func:`load_addendum` output.
    out : pathlib.Path
        ``research/data/c1-combination``.

    Returns
    -------
    dict
        File name to row count.
    """
    grid_cols = [
        "split",
        "pricing",
        "kappa",
        "scope",
        "design",
        "kpi",
        "eval_beta",
        "value",
        "ci_low",
        "ci_high",
        "hash",
    ]
    con_cols = list(SLIM_CONTRAST_COLUMNS)
    train_cols = [c for c in con_cols if not c.startswith(("ci_", "rel_ci_"))]
    site_grid_cols = [
        "split",
        "pricing",
        "kappa",
        "site",
        "design",
        "kpi",
        "eval_beta",
        "value",
        "ci_low",
        "ci_high",
        "hash",
    ]
    sg, sc, ac = a["sgrid"], a["scon"], a["acon"]
    alt_cols = ["tail_version", "base_version", *con_cols]
    files: dict[str, pd.DataFrame] = {
        "kfold_addendum_grid.csv": a["kgrid"][grid_cols],
        "kfold_addendum_contrasts.csv": a["kcon"][con_cols],
        "sites_grid.csv": sg.loc[sg["split"] != "train", site_grid_cols],
        "sites_grid_train.csv": sg.loc[
            sg["split"] == "train", [c for c in site_grid_cols if "ci_" not in c]
        ],
        "sites_contrasts_test.csv": sc.loc[sc["split"] == "test", list(SITE_COLUMNS)],
        "sites_contrasts_pooled.csv": sc.loc[
            sc["split"] == "pooled", list(SITE_COLUMNS)
        ],
        "sites_contrasts_train.csv": sc.loc[
            sc["split"] == "train", [c for c in SITE_COLUMNS if "ci_" not in c]
        ],
        "alt_grid.csv": a["agrid"][grid_cols],
        "alt_contrasts.csv": ac.loc[ac["split"] == "test", alt_cols],
        "alt_contrasts_train.csv": ac.loc[
            ac["split"] == "train", ["tail_version", "base_version", *train_cols]
        ],
    }
    counts: dict[str, int] = {}
    for name, frame in files.items():
        frame.to_csv(out / name, index=False, float_format="%.7g")
        counts[name] = len(frame)
    runs = a["kruns"].copy()
    runs["fold"] = runs["fold"].astype("Int64")
    runs.to_csv(out / "kfold_addendum_runs.csv", index=False, float_format="%.10g")
    counts["kfold_addendum_runs.csv"] = len(runs)
    d = a["adesigns"].copy()
    d.to_csv(out / "alt_designs.csv", index=False, float_format="%.6g")
    counts["alt_designs.csv"] = len(d)
    for name in counts:
        size = (out / name).stat().st_size
        if size >= 500_000:
            raise RuntimeError(f"{name}: {size} bytes, over the 500 kB limit")
    return counts


def _kcon_all(t: dict[str, pd.DataFrame], a: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Every main-line contrast: MAR-182's (holdout, kappa-1 pooled) and item 1's."""
    con = t["contrasts"]
    con = con.loc[con["eventset"] == "thesis"]
    k = a["kcon"].assign(eventset="thesis", family="main")
    return pd.concat([con, k], ignore_index=True)


def table_kfold_grid(a: dict[str, pd.DataFrame]) -> list[str]:
    """T11: the pooled grid of the item-1 variants."""
    lines = [
        "## T11. Pooled 5-fold grid at κ 0.5 (pure, CoC r 0.06) and CoC r 0.10 "
        "(κ 1) (MAR-194 item 1)",
        "",
        "Portfolio KPIs (sum over the 9 assets), USD per year, pooled over the "
        "five folds: every year evaluated by the design that did not see it, "
        "one resample of all 10,000 years (B 1000, seed 0). Budget use: the "
        "folds' premiums over κ·E[L] on their calibration years (min–max over "
        "the 5 folds; `kfold_addendum_runs.csv`). Hash: the k-fold experiment "
        "config.",
        "",
        "| Pricing | κ | Scope | Objective | Pooled CVaR₀.₉₉ [90 % CI] | "
        "Pooled CVaR₀.₉₉₅ [90 % CI] | Pooled E[U] [90 % CI] | Budget use | Hash |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    g, runs = a["kgrid"], a["kruns"]
    for pricing, kappa in NEW_KFOLD:
        for scope in SCOPES:
            for design in DESIGNS:
                where = {
                    "pricing": pricing,
                    "kappa": kappa,
                    "scope": scope,
                    "design": design,
                }
                r = runs.loc[
                    (runs["pricing"] == pricing)
                    & (runs["kappa"] == kappa)
                    & (runs["scope"] == scope)
                    & (runs["design"] == design)
                ]
                use = f"{r['budget_use'].min():.4f}–{r['budget_use'].max():.4f}"
                c99 = _at(g, where, "cvar_uncovered", 0.99)
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {kappa:g} | {scope} | "
                    f"{DESIGN_LABEL[design]} | {_grid_cell(c99)} | "
                    f"{_grid_cell(_at(g, where, 'cvar_uncovered', 0.995))} | "
                    f"{_grid_cell(_at(g, where, 'expected_uncovered', None))} | "
                    f"{use} | "
                    f"`{'' if c99 is None else c99['hash']}` |"
                )
    lines.append("")
    return lines


def table_kfold_contrasts(con: pd.DataFrame, j: str, o: str, title: str) -> list[str]:
    """T12/T13: the combination contrasts, holdout test against pooled."""
    lines = [
        title,
        "",
        f"J = {SCOPE_LABEL[j]}, I = individual, O = {DESIGN_LABEL[o]}, W the "
        "tail design. Relative to the subtracted design (the interaction: to "
        "the individual O design); paired 90 % intervals; `*`: the interval "
        "excludes zero. Test: holdout (MAR-182, `contrasts.csv`); pooled: "
        "5-fold. The κ 1 pure and CoC r 0.06 pooled values are MAR-182's "
        "(T3, T4); the others are new (item 1).",
        "",
        "| Pricing | κ | Tail design | KPI | Contrast | Test [90 % CI] | "
        "Pooled [90 % CI] |",
        "|---|---|---|---|---|---|---|",
    ]
    for pricing, kappa in KFOLD_VARIANTS:
        for w, kpi, beta in MATCHED:
            kl = KPI_LABEL[kpi] + (f" {beta:g}" if beta else "")
            for name in (
                "both",
                "adds_rq2",
                "adds_rq1",
                "rq1_alone",
                "rq2_alone",
                "interaction",
            ):
                args = (pricing, kappa, name, j, w, o, kpi, beta)
                te = _contrast(con, "test", *args)
                po = _contrast(con, "pooled", *args)
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {kappa:g} | {DESIGN_LABEL[w]} | "
                    f"{kl} | {CONTRAST_LABEL[name]} | {_rel(te)} | {_rel(po)} |"
                )
    lines.append("")
    return lines


def table_kfold_counts(con: pd.DataFrame) -> list[str]:
    """T14: how many pooled intervals exclude zero, by variant and contrast."""
    lines = [
        "## T14. Pooled intervals that exclude zero, by variant (both joint "
        "scopes, both baselines, both tail designs, KPIs CVaR 0.95 / 0.99 / "
        "0.995 and E[U])",
        "",
        "Cells: below zero / above zero / containing zero, of 16 per contrast "
        "and joint scope (8 for adds RQ2). Holdout test counts in brackets, on "
        "the same cells.",
        "",
        "| Pricing | κ | Joint scope | Both | Adds RQ2 | Adds RQ1 | RQ2 alone | "
        "Interaction |",
        "|---|---|---|---|---|---|---|---|",
    ]
    kpi_ok = con["kpi"].isin(["cvar_uncovered", "expected_uncovered"])
    for pricing, kappa in KFOLD_VARIANTS:
        for j in ("portfolio", "cluster"):
            cells = []
            for name in ("both", "adds_rq2", "adds_rq1", "rq2_alone", "interaction"):
                out = []
                for split in ("pooled", "test"):
                    f = con.loc[
                        (con["split"] == split)
                        & (con["pricing"] == pricing)
                        & (con["kappa"] == kappa)
                        & (con["contrast"] == name)
                        & (con["joint_scope"] == j)
                        & kpi_ok
                    ]
                    lo = int((f["ci_high"] < 0).sum())
                    hi = int((f["ci_low"] > 0).sum())
                    out.append(f"{lo} / {hi} / {len(f) - lo - hi}")
                cells.append(f"{out[0]} [{out[1]}]")
            lines.append(
                f"| {PRICING_LABEL[pricing]} | {kappa:g} | {j} | "
                + " | ".join(cells)
                + " |"
            )
    lines.append("")
    return lines


def _at(
    frame: pd.DataFrame, where: dict[str, object], kpi: str, beta: float | None
) -> pd.Series | None:
    """Return the single row of ``frame`` at ``where``, KPI and KPI beta."""
    return _one(frame, **where, **_kpi_where(kpi, beta))


def _site(frame: pd.DataFrame, **where: object) -> pd.Series | None:
    return _one(frame, **where)


def table_sites(a: dict[str, pd.DataFrame], pricing: str, kappa: float) -> list[str]:
    """T15: per-site RQ1 alone (individual designs), one variant."""
    sc = a["scon"]
    sg = a["sgrid"]
    lines = [
        f"## T15{'a' if pricing == 'pure' else 'b'}. Per site: the individual "
        f"weighted-CVaR design against the individual MSE design, "
        f"{PRICING_LABEL[pricing]}, κ {kappa:g} (MAR-194 item 2)",
        "",
        "Each site's own annual uncovered loss U_i (its loss minus its own "
        "design's payout), CVaR and E[U] in USD per year for the MSE design, "
        "and the weighted-CVaR design's difference relative to it (train: in "
        "sample; test: holdout, paired 90 % interval; pooled: 5-fold). Each "
        "site's design is its own problem with its own budget, κ·E[L_i]. "
        "Hashes: weighted CVaR / MSE (holdout runs; the pooled rows' k-fold "
        "hashes are in the CSVs).",
        "",
        "| Site | Train E[L_i] | KPI | MSE: test [90 % CI] | MSE: pooled | "
        "wCVaR − MSE: train | test [90 % CI] | pooled [90 % CI] | Hashes |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    rows: list[tuple[str, str, float | None]] = [
        ("wcvar@0.99", "cvar_uncovered", 0.99),
        ("wcvar@0.995", "cvar_uncovered", 0.995),
        ("wcvar@0.99", "expected_uncovered", None),
    ]
    for site in SITES:
        el = _site(
            sg,
            split="train",
            pricing=pricing,
            kappa=kappa,
            site=site,
            design="mse",
            kpi="expected_loss",
            eval_beta=None,
        )
        for w, kpi, beta in rows:
            kl = f"{DESIGN_LABEL[w]}, {KPI_LABEL[kpi]}" + (f" {beta:g}" if beta else "")
            where = {
                "pricing": pricing,
                "kappa": kappa,
                "site": site,
                "tail_design": w,
                "base_design": "mse",
                **_kpi_where(kpi, beta),
            }
            tr = _site(sc, split="train", **where)
            te = _site(sc, split="test", **where)
            po = _site(sc, split="pooled", **where)
            g = {
                "pricing": pricing,
                "kappa": kappa,
                "site": site,
                "design": "mse",
                **_kpi_where(kpi, beta),
            }
            gte = _site(sg, split="test", **g)
            gpo = _site(sg, split="pooled", **g)
            hashes = "" if te is None else f"`{te['hash_a']}` / `{te['hash_b']}`"
            lines.append(
                f"| {site} | {_int(float(el['value'])) if el is not None else 'n/a'} | "
                f"{kl} | {_grid_cell(gte)} | {_grid_cell(gpo, ci=False)} | "
                f"{_rel(tr, ci=False)} | {_rel(te)} | {_rel(po)} | {hashes} |"
            )
    lines.append("")
    return lines


def table_site_counts(a: dict[str, pd.DataFrame]) -> list[str]:
    """T16: per-site intervals that exclude zero, every variant."""
    sc = a["scon"]
    lines = [
        "## T16. Per site: weighted CVaR − MSE / − E[U] intervals that exclude "
        "zero, every variant",
        "",
        "Counts over the 9 sites: below zero / above zero / containing zero. "
        "Holdout test for every main-line variant; pooled where k-fold runs "
        "exist. Matched reading: β 0.99 at CVaR₀.₉₉, β 0.995 at CVaR₀.₉₉₅; "
        "and E[U].",
        "",
        "| Pricing | κ | Split | Baseline | β 0.99 at CVaR₀.₉₉ | β 0.995 at "
        "CVaR₀.₉₉₅ | β 0.99: E[U] | β 0.995: E[U] |",
        "|---|---|---|---|---|---|---|---|",
    ]
    cells_spec: list[tuple[str, str, float | None]] = [
        ("wcvar@0.99", "cvar_uncovered", 0.99),
        ("wcvar@0.995", "cvar_uncovered", 0.995),
        ("wcvar@0.99", "expected_uncovered", None),
        ("wcvar@0.995", "expected_uncovered", None),
    ]
    for pricing in PRICINGS:
        for kappa in KAPPAS:
            for split in ("test", "pooled"):
                for o in ("mse", "eu"):
                    f = sc.loc[
                        (sc["pricing"] == pricing)
                        & (sc["kappa"] == kappa)
                        & (sc["split"] == split)
                        & (sc["base_design"] == o)
                    ]
                    if f.empty:
                        continue
                    cells = []
                    for w, kpi, beta in cells_spec:
                        g = f.loc[(f["tail_design"] == w) & (f["kpi"] == kpi)]
                        if beta is not None:
                            g = g.loc[g["eval_beta"] == beta]
                        lo = int((g["ci_high"] < 0).sum())
                        hi = int((g["ci_low"] > 0).sum())
                        cells.append(f"{lo} / {hi} / {len(g) - lo - hi}")
                    lines.append(
                        f"| {PRICING_LABEL[pricing]} | {kappa:g} | {split} | "
                        f"{DESIGN_LABEL[o]} | " + " | ".join(cells) + " |"
                    )
    lines.append("")
    return lines


def _alt(
    acon: pd.DataFrame,
    split: str,
    version: tuple[str, str],
    pricing: str,
    name: str,
    j: str,
    w: str,
    o: str,
    kpi: str,
    beta: float | None,
) -> pd.Series | None:
    return _one(
        acon,
        split=split,
        tail_version=version[0],
        base_version=version[1],
        pricing=pricing,
        kappa=1.0,
        contrast=name,
        joint_scope=j if name != "rq1_alone" else "",
        tail_design=w if name != "rq2_alone" else "",
        base_design=o if name != "adds_rq2" else "",
        **_kpi_where(kpi, beta),
    )


def table_alt(a: dict[str, pd.DataFrame], j: str, title: str) -> list[str]:
    """T17/T18: the combination contrasts with the joint designs' alt optima."""
    acon = a["acon"]
    lines = [
        title,
        "",
        f"J = {SCOPE_LABEL[j]}, κ 1, holdout test, relative (paired 90 % "
        "interval). Versions: the joint weighted-CVaR design (W) / the joint "
        "baseline design (O), each C1's or its `alt` optimum (MAR-206 family "
        "(e) thetas, the same designs as C1 observation 32's `_alt` and family "
        "(b)'s). Contrasts with one joint term change only with that term's "
        "version. In-sample (train) values: `alt_contrasts_train.csv`.",
        "",
        "| Pricing | Tail design | Baseline | KPI | Contrast | C1 / C1 | "
        "alt / alt | C1 / alt | alt / C1 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for pricing in ("pure", "coc_r0.06"):
        for o in ("mse", "eu"):
            for w, kpi, beta in MATCHED:
                kl = KPI_LABEL[kpi] + (f" {beta:g}" if beta else "")
                for name in (
                    "both",
                    "adds_rq2",
                    "adds_rq1",
                    "rq2_alone",
                    "interaction",
                ):
                    if name == "adds_rq2" and o != "mse":
                        continue
                    cells = [
                        _rel(_alt(acon, "test", v, pricing, name, j, w, o, kpi, beta))
                        for v in VERSION_LABEL
                    ]
                    lines.append(
                        f"| {PRICING_LABEL[pricing]} | {DESIGN_LABEL[w]} | "
                        f"{DESIGN_LABEL[o]} | {kl} | {CONTRAST_LABEL[name]} | "
                        + " | ".join(cells)
                        + " |"
                    )
    lines.append("")
    return lines


def table_alt_counts(a: dict[str, pd.DataFrame]) -> list[str]:
    """T19: verdict changes between the C1 designs and the alt optima."""
    acon = a["acon"]
    t = acon.loc[(acon["split"] == "test") & (acon["contrast"] != "rq1_alone")]
    key = [
        "pricing",
        "contrast",
        "joint_scope",
        "tail_design",
        "base_design",
        "kpi",
        "eval_beta",
    ]
    base = t.loc[(t["tail_version"] == "c1") & (t["base_version"] == "c1")]

    def verdict(f: pd.DataFrame) -> pd.Series:
        return pd.Series(
            (f["ci_low"] > 0).astype(int) - (f["ci_high"] < 0).astype(int),
            index=f.index,
        )

    lines = [
        "## T19. Interval verdicts that change with the joint designs' alt "
        "optima (κ 1, holdout test)",
        "",
        "Cells: test contrasts with a joint term (both joint scopes, both "
        "tail designs, both baselines, KPIs E[π], E[U], CVaR 0.95 / 0.99 / "
        "0.995), per pricing. A verdict is below zero / contains zero / above "
        'zero (paired 90 % interval). "Changed" counts the cells whose '
        "verdict differs from C1 / C1 (lost: an exclusion of zero became "
        "containment; gained: the reverse; flipped: one side to the other); "
        '"sign" counts the point values whose sign differs. Unique cells '
        "only (a contrast with one joint term is counted under the versions "
        "that change it).",
        "",
        "| Pricing | Version | Contrast | Cells | Changed (lost / gained / "
        "flipped) | Sign changed | Largest shift, points of the reference |",
        "|---|---|---|---|---|---|---|",
    ]
    for pricing in ("pure", "coc_r0.06"):
        for version in list(VERSION_LABEL)[1:]:
            for name in ("both", "adds_rq2", "adds_rq1", "rq2_alone", "interaction"):
                uses_w = name in ("both", "adds_rq2", "adds_rq1", "interaction")
                uses_o = name in ("adds_rq1", "rq2_alone", "interaction")
                changes = (uses_w and version[0] == "alt") or (
                    uses_o and version[1] == "alt"
                )
                if not changes:
                    continue
                if version != ("alt", "alt") and not (uses_w and uses_o):
                    continue
                v = t.loc[
                    (t["tail_version"] == version[0])
                    & (t["base_version"] == version[1])
                    & (t["pricing"] == pricing)
                    & (t["contrast"] == name)
                ]
                b = base.loc[(base["pricing"] == pricing) & (base["contrast"] == name)]
                m = v.merge(b, on=key, suffixes=("", "_c1"), validate="one_to_one")
                va = verdict(m)
                vb = pd.Series(
                    (m["ci_low_c1"] > 0).astype(int)
                    - (m["ci_high_c1"] < 0).astype(int),
                    index=m.index,
                )
                lost = int(((vb != 0) & (va == 0)).sum())
                gained = int(((vb == 0) & (va != 0)).sum())
                flipped = int(((vb != 0) & (va != 0) & (va != vb)).sum())
                sign = int((np.sign(m["value"]) != np.sign(m["value_c1"])).sum())
                shift = (m["rel"] - m["rel_c1"]).abs().max()
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {VERSION_LABEL[version]} | "
                    f"{CONTRAST_LABEL[name]} | {len(m)} | "
                    f"{lost + gained + flipped} ({lost} / {gained} / {flipped}) | "
                    f"{sign} | {100 * shift:.1f} |"
                )
    lines.append("")
    return lines


def table_alt_designs(a: dict[str, pd.DataFrame]) -> list[str]:
    """T20: the alt designs against the C1 designs (train and test KPIs)."""
    g = a["agrid"]
    lines = [
        "## T20. The alt optima's portfolio KPIs (κ 1)",
        "",
        "Train (in sample) and holdout test, USD per year; the C1 design's "
        "values are in `grid.csv`. Objective excess: the alt design's train "
        "objective over C1's, relative (MAR-206 family (e) check; `alt_designs."
        "csv`).",
        "",
        "| Pricing | Scope | Objective | Train CVaR₀.₉₉ | Test CVaR₀.₉₉ [90 % CI] "
        "| Test CVaR₀.₉₉₅ [90 % CI] | Test E[U] [90 % CI] | Objective excess | "
        "Hash |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    d = a["adesigns"]
    for pricing in ("pure", "coc_r0.06"):
        for scope in ("portfolio", "cluster"):
            for design in DESIGNS:
                where = {"pricing": pricing, "scope": scope, "design": design}
                dd = d.loc[
                    (d["pricing"] == pricing)
                    & (d["scope"] == scope)
                    & (d["design"] == design)
                ].iloc[0]
                tr = _at(g, {**where, "split": "train"}, "cvar_uncovered", 0.99)
                te = {**where, "split": "test"}
                lines.append(
                    f"| {PRICING_LABEL[pricing]} | {scope} | {DESIGN_LABEL[design]} | "
                    f"{_grid_cell(tr, ci=False)} | "
                    f"{_grid_cell(_at(g, te, 'cvar_uncovered', 0.99))} | "
                    f"{_grid_cell(_at(g, te, 'cvar_uncovered', 0.995))} | "
                    f"{_grid_cell(_at(g, te, 'expected_uncovered', None))} | "
                    f"{float(dd['alt_objective_excess']):.1e} | "
                    f"`{'' if tr is None else tr['hash']}` |"
                )
    lines.append("")
    return lines


def markdown_addendum(t: dict[str, pd.DataFrame], a: dict[str, pd.DataFrame]) -> str:
    """Every table of the note's addendum (section 12), as Markdown.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        :func:`load` output (MAR-182).
    a : dict of pandas.DataFrame
        :func:`load_addendum` output (MAR-194).

    Returns
    -------
    str
        ``tables_addendum.md``.
    """
    con = _kcon_all(t, a)
    lines = [
        "# C1 combination view, addendum (MAR-194): generated tables",
        "",
        "Generated by `research/scripts/c1_combination_tables.py` from the "
        "CSVs in this folder; do not edit. Setup: "
        "`research/notes/c1-combination.md` sections 2 and 12. Hashes are the "
        "first 12 hex digits of the `sha256:` config hash; `runs.csv` and "
        "`kfold_addendum_runs.csv` have the full hashes and run ids. "
        "Observations only.",
        "",
    ]
    lines += table_kfold_grid(a)
    lines += table_kfold_contrasts(
        con,
        "portfolio",
        "mse",
        "## T12. The combination contrasts, holdout test and pooled 5-fold, "
        "portfolio scope, MSE baseline, every k-fold variant",
    )
    lines += table_kfold_contrasts(
        con,
        "portfolio",
        "eu",
        "## T13. The same against E[U] as the baseline",
    )
    lines += table_kfold_counts(con)
    lines += table_sites(a, "pure", 1.0)
    lines += table_sites(a, "coc_r0.06", 1.0)
    lines += table_site_counts(a)
    lines += table_alt(
        a,
        "portfolio",
        "## T17. The combination contrasts with the joint designs' alt optima, "
        "portfolio scope (MAR-194 item 3)",
    )
    lines += table_alt(
        a,
        "cluster",
        "## T18. The same, cluster scope (a different index)",
    )
    lines += table_alt_counts(a)
    lines += table_alt_designs(a)
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the committed tables, the Markdown tables and the summaries.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full", type=Path, default=FULL)
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument(
        "--parts",
        nargs="+",
        default=["main", "addendum"],
        choices=["main", "addendum"],
        help="main: MAR-182's files; addendum: MAR-194's",
    )
    args = parser.parse_args(argv)
    t = load(args.full)
    if "main" in args.parts:
        counts = write_slim(t, args.out)
        (args.out / "tables.md").write_text(markdown(t))
        summary: dict[str, object] = {"committed_rows": counts}
        for name in MAR182_SUMMARIES:
            path = args.full / f"summary_{name}.json"
            summary[name] = json.loads(path.read_text())
        (args.out / "summary.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
    if "addendum" in args.parts:
        a = load_addendum(args.full)
        counts = write_addendum(a, args.out)
        (args.out / "tables_addendum.md").write_text(markdown_addendum(t, a))
        summary = {"committed_rows": counts}
        for name in ADDENDUM_SUMMARIES:
            path = args.full / f"summary_{name}.json"
            summary[name] = json.loads(path.read_text())
        (args.out / "summary_addendum.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
    print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
