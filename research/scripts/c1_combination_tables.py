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


def main(argv: list[str] | None = None) -> int:
    """Write the committed tables, ``tables.md`` and ``summary.json``.

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
    args = parser.parse_args(argv)
    t = load(args.full)
    counts = write_slim(t, args.out)
    (args.out / "tables.md").write_text(markdown(t))
    summary: dict[str, object] = {"committed_rows": counts}
    for path in sorted(args.full.glob("summary_*.json")):
        summary[path.stem.removeprefix("summary_")] = json.loads(path.read_text())
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(f"wrote {args.out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
