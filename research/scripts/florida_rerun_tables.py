r"""Committed tables and Markdown tables of the Florida rerun (MAR-202).

Reads the full tables that ``florida_rerun.py`` writes to
``results/florida/full/`` (not committed) and writes, each file under the
500 kB pre-commit limit, to ``research/data/florida-rerun/``:

* ``runs.csv``: every design used (holdout, k-fold fold runs, the derived
  ``cluster_separate`` designs and the ``portfolio_matched`` runs) with its
  full config hash (or ``derived:`` id), run id, statuses, solvers and
  budget use; the other tables carry the 12-hex prefix of the hash;
* ``grid.csv``: portfolio KPIs per split (train, test, pooled), index,
  pricing, kappa, scope and design, with 90 % intervals (test, pooled);
* ``contrasts.csv`` (test and pooled, paired 90 % intervals) and
  ``contrasts_train.csv`` (in sample, point values): every contrast of
  ``c1_combination`` (RQ1 within a scope, RQ2 within a design, the
  combination and the interaction), absolute and relative;
* ``cluster_parts.csv``: cluster - individual split into the index part
  (``cluster_separate`` - individual) and the joint part (cluster -
  ``cluster_separate``);
* ``entity_payouts.csv``: expected payout and expected loss per payout
  entity (county or cluster), train and test, and ``clusters.csv``, the
  counties of each cluster;
* ``premiums.csv`` and ``premium_split.csv``: the individual designs'
  aggregate premium against their stand-alone premiums, and the split of
  portfolio - individual into cross-coverage and pricing diversification;
* ``kfold_folds.csv``: per-fold train and test CVaR and E[U];
* ``guard.csv``: the zero-loss share of every calibration sample against
  the clustering's ``beta_tail`` (MAR-172);
* ``tables.md``: every table of ``research/notes/florida-rerun.md``,
  generated;
* ``summary.json``: inputs, checks, timings.

Run from the repository root, after ``florida_rerun.py``::

    uv run python research/scripts/florida_rerun_tables.py

Observations only. The interpretation is the owner's.
"""

# The Markdown labels use the typographic minus sign (U+2212).
# ruff: noqa: RUF001, RUF002

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
FULL: Final[Path] = REPO_ROOT / "results" / "florida" / "full"
OUT: Final[Path] = REPO_ROOT / "research" / "data" / "florida-rerun"
LOCATIONS: Final[Path] = (
    REPO_ROOT
    / "results"
    / "florida"
    / "eventsets"
    / "florida-counties-iris-vulnerability"
    / "locations.parquet"
)

INDICES: Final[tuple[str, ...]] = ("a", "cic75")
INDEX_LABEL: Final[dict[str, str]] = {
    "a": "index (a), wind at the centroid",
    "cic75": "index (b), cat-in-a-circle 75 km",
}
PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06")
PRICING_LABEL: Final[dict[str, str]] = {"pure": "pure", "coc_r0.06": "CoC r 0.06"}
KAPPAS: Final[tuple[float, ...]] = (0.5, 1.0, 1.5)
DESIGNS: Final[tuple[str, ...]] = ("mse", "eu", "wcvar@0.99", "wcvar@0.995")
TAIL_DESIGNS: Final[tuple[str, ...]] = ("wcvar@0.99", "wcvar@0.995")
DESIGN_LABEL: Final[dict[str, str]] = {
    "mse": "MSE",
    "eu": "E[U]",
    "wcvar@0.99": "wCVaR β 0.99",
    "wcvar@0.995": "wCVaR β 0.995",
    "": "",
}
MATCHED_BETA: Final[dict[str, float]] = {"wcvar@0.99": 0.99, "wcvar@0.995": 0.995}
SCOPES: Final[tuple[str, ...]] = ("individual", "cluster", "portfolio")
BETAS: Final[tuple[float, ...]] = (0.95, 0.99, 0.995)
CONFIG_BETA: Final[float] = 0.99
TAIL: Final[frozenset[str]] = frozenset({"var_uncovered", "cvar_uncovered"})
MONEY: Final[float] = 1e6
"""Markdown money unit: USD million (LitPop reference year 2018)."""
NOT_UNIQUE: Final[str] = (
    "Individual-scope near-optimal ranges are not measured yet for Florida "
    "(MAR-203): the individual design here is the one member of its optimal "
    "set the default solver policy returned, and individual designs are not "
    "unique either (MAR-198)."
)
"""One line next to every Florida RQ2 or combination difference."""
CONFOUNDED: Final[str] = (
    "The cluster scope confounds the cluster index with the joint "
    "calibration: MAR-180 (a separate cluster index) has not merged."
)
"""One line next to every cluster-scope difference."""


def _read(path: Path) -> pd.DataFrame:
    """Read a full table; an empty frame if that phase has not run."""
    return pd.read_csv(path) if path.is_file() else pd.DataFrame()


def _short(h: object) -> str:
    """First 12 hex digits of a config hash (``derived:`` ids keep a prefix)."""
    if h is None or (isinstance(h, float) and math.isnan(h)) or h == "":
        return ""
    s = str(h)
    if s.startswith("derived:"):
        return "d:" + s.split(":", 1)[1][:10]
    return s.split(":", 1)[1][:12] if ":" in s else s[:12]


def _m(x: float) -> str:
    """Money in USD million, no decimals."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return f"{round(x / MONEY) + 0:,.0f}".replace("-", "−")


def _pct(x: float, signed: bool = True) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "n/a"
    return (f"{100 * x:+.1f} %" if signed else f"{100 * x:.1f} %").replace("-", "−")


def _rel_ci(rel: float, lo: float, hi: float) -> str:
    """``−12.3 % [−20.1, −4.0]*`` (``*``: the interval excludes zero)."""
    if any(isinstance(v, float) and math.isnan(v) for v in (lo, hi)):
        return _pct(rel)
    star = "*" if (lo > 0) or (hi < 0) else ""
    body = f"{100 * rel:+.1f} %{star} [{100 * lo:+.1f}, {100 * hi:+.1f}]"
    return body.replace("-", "−")


def _money_ci(v: float, lo: float, hi: float) -> str:
    if any(isinstance(x, float) and math.isnan(x) for x in (lo, hi)):
        return _m(v)
    return f"{_m(v)} [{_m(lo)}, {_m(hi)}]"


def _ratio(x: float) -> str:
    """Format a payout ratio with two decimals (a tiny negative shows as 0.00)."""
    return f"{round(float(x), 2) + 0.0:.2f}"


def _table(header: list[str], rows: Iterable[list[str]]) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(out)


# --------------------------------------------------------------------------
# Committed tables
# --------------------------------------------------------------------------


def _beta_free_once(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep beta-free KPIs once (at CONFIG_BETA), with a null eval_beta."""
    tail = frame["kpi"].isin(TAIL)
    keep = tail | (frame["eval_beta"].isna()) | (frame["eval_beta"] == CONFIG_BETA)
    out = frame.loc[keep].copy()
    out.loc[~out["kpi"].isin(TAIL), "eval_beta"] = np.nan
    return out


def _relative(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    ref = out["value_ref"].where(out["value_ref"].abs() >= 1.0)
    out["rel"] = out["value"] / ref
    out["rel_ci_low"] = out["ci_low"] / ref
    out["rel_ci_high"] = out["ci_high"] / ref
    return out


CONTRAST_COLUMNS: Final[list[str]] = [
    "eventset",
    "pricing",
    "kappa",
    "split",
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
]


PAIR_COLUMNS = [
    "eventset",
    "pricing",
    "kappa",
    "design",
    "split",
    "scope_a",
    "scope_b",
    "kpi",
    "eval_beta",
    "value_a",
    "value_b",
    "difference",
    "ci_low",
    "ci_high",
    "rel",
    "rel_ci_low",
    "rel_ci_high",
    "hash_a",
    "hash_b",
]


def _pairs(
    frame: pd.DataFrame, pairs: set[tuple[str, str]], kpis: list[str]
) -> pd.DataFrame:
    keep = [
        (a, b) in pairs for a, b in zip(frame["scope_a"], frame["scope_b"], strict=True)
    ]
    out = frame.loc[keep]
    out = _beta_free_once(out.loc[out["kpi"].isin(kpis)]).copy()
    out["rel"] = out["difference"] / out["value_b"]
    out["rel_ci_low"] = out["ci_low"] / out["value_b"]
    out["rel_ci_high"] = out["ci_high"] / out["value_b"]
    out["hash_a"] = out["config_hash_a"].map(_short)
    out["hash_b"] = out["config_hash_b"].map(_short)
    return out.reindex(columns=PAIR_COLUMNS)


def _premium_split(parts: pd.DataFrame, con: pd.DataFrame) -> pd.DataFrame:
    """Add the total and take every part relative to the individual design.

    The total is portfolio - individual; relative to the individual design's
    value the parts add up in percent. The total is the ``adds_rq2`` or
    ``rq2_alone`` contrast of the portfolio scope (the same resample and
    pairing); its interval is that contrast's.
    """
    pricings = set(parts["pricing"])
    tot = con.loc[
        con["contrast"].isin(["adds_rq2", "rq2_alone"])
        & (con["joint_scope"] == "portfolio")
        & con["pricing"].isin(pricings)
        & (con["split"] != "pooled")
    ].copy()
    tot["design"] = tot["tail_design"].where(
        tot["contrast"] == "adds_rq2", tot["base_design"]
    )
    tot = pd.DataFrame(
        {
            "eventset": tot["eventset"],
            "pricing": tot["pricing"],
            "kappa": tot["kappa"],
            "design": tot["design"],
            "split": tot["split"],
            "scope_a": "portfolio",
            "scope_b": "individual",
            "kpi": tot["kpi"],
            "eval_beta": tot["eval_beta"],
            "value_a": np.nan,
            "value_b": tot["value_ref"],
            "difference": tot["value"],
            "ci_low": tot["ci_low"],
            "ci_high": tot["ci_high"],
            "hash_a": tot["hash_a"],
            "hash_b": tot["hash_b"],
        }
    )
    out = pd.concat([parts, tot], ignore_index=True)
    key = ["eventset", "pricing", "kappa", "design", "split", "kpi", "eval_beta"]
    ref = (
        out.loc[out["scope_b"] == "individual"]
        .fillna({"eval_beta": -1.0})
        .groupby(key)["value_b"]
        .first()
    )
    idx = pd.MultiIndex.from_frame(out[key].fillna({"eval_beta": -1.0}))
    out["value_individual"] = ref.reindex(idx).to_numpy()
    for col, src in (
        ("rel", "difference"),
        ("rel_ci_low", "ci_low"),
        ("rel_ci_high", "ci_high"),
    ):
        out[col] = out[src] / out["value_individual"]
    return out


def build(full: Path) -> dict[str, pd.DataFrame]:
    """Return the committed tables, from the full ones.

    Parameters
    ----------
    full : pathlib.Path
        ``results/florida/full``.

    Returns
    -------
    dict of pandas.DataFrame
        Name (file stem) to table.
    """
    out: dict[str, pd.DataFrame] = {}
    hold = pd.read_csv(full / "holdout_runs.csv")
    kf = _read(full / "kfold_runs.csv")
    prem = pd.read_csv(full / "premiums.csv")
    cols = [
        "kind",
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
        "loading",
        "config_hash",
        "run_id",
        "experiment_config_hash",
        "base_config_hash",
    ]
    out["runs"] = pd.concat([hold, kf], ignore_index=True).reindex(columns=cols)
    grid = pd.concat(
        [pd.read_csv(full / "holdout_grid.csv"), _read(full / "kfold_grid.csv")],
        ignore_index=True,
    )
    grid["hash"] = grid["config_hash"].map(_short)
    out["grid"] = grid[
        [
            "eventset",
            "pricing",
            "kappa",
            "split",
            "scope",
            "design",
            "kpi",
            "eval_beta",
            "value",
            "ci_low",
            "ci_high",
            "hash",
        ]
    ]
    con = pd.concat(
        [
            pd.read_csv(full / "holdout_contrasts.csv"),
            _read(full / "kfold_contrasts.csv"),
        ],
        ignore_index=True,
    )
    con = _relative(_beta_free_once(con))
    for c in ("hash_a", "hash_b", "hash_c", "hash_d"):
        con[c] = con[c].map(_short)
    con = con[CONTRAST_COLUMNS]
    out["contrasts"] = con.loc[con["split"] == "test"]
    out["contrasts_pooled"] = con.loc[con["split"] == "pooled"]
    out["contrasts_train"] = con.loc[con["split"] == "train"].drop(
        columns=["ci_low", "ci_high", "rel_ci_low", "rel_ci_high"]
    )
    pairs = pd.read_csv(full / "holdout_pairs.csv")
    kpis = ["cvar_uncovered", "expected_uncovered", "expected_payout", "premium"]
    out["cluster_parts"] = _pairs(
        pairs,
        {("cluster_separate", "individual"), ("cluster", "cluster_separate")},
        kpis,
    )
    out["premium_split"] = _premium_split(
        _pairs(
            pairs,
            {("portfolio_matched", "individual"), ("portfolio", "portfolio_matched")},
            kpis,
        ),
        con,
    )
    e = pd.read_csv(full / "holdout_entities.csv")
    ent = e.pivot_table(
        index=[
            "eventset",
            "pricing",
            "kappa",
            "design",
            "scope",
            "split",
            "subject_id",
        ],
        columns="kpi",
        values="value",
        aggfunc="first",
    ).reset_index()
    ent = ent.rename(columns={"subject_id": "entity_id"})
    ent["payout_to_loss"] = ent["expected_payout"] / ent["expected_loss"]
    # kappa 1 and the plan's scopes and cluster_separate only, to stay under
    # 500 kB; every kappa and portfolio_matched are in the full table
    ent = ent.loc[(ent["kappa"] == 1.0) & (ent["scope"] != "portfolio_matched")]
    out["entity_payouts"] = ent.drop(columns=["kappa"])
    clusters = e.loc[e["scope"].isin(["cluster", "cluster_separate"])][
        ["eventset", "subject_id", "entity_locations"]
    ].drop_duplicates()
    groups = clusters.groupby(["eventset", "subject_id"])["entity_locations"].nunique()
    if (groups != 1).any():
        raise RuntimeError("a cluster has different counties across variants")
    clusters = clusters.drop_duplicates(["eventset", "subject_id"])
    out["clusters"] = pd.DataFrame(
        [
            {"eventset": r.eventset, "cluster_id": r.subject_id, "location_id": loc}
            for r in clusters.itertuples()
            for loc in str(r.entity_locations).split()
        ]
    )
    out["premiums"] = prem.drop(columns=["matched_run_id"]).assign(
        matched_config_hash=prem["matched_config_hash"].map(_short),
        individual_config_hash=prem["individual_config_hash"].map(_short),
        portfolio_config_hash=prem["portfolio_config_hash"].map(_short),
    )
    f = _read(full / "kfold_folds.csv")
    fold_cols = [
        "eventset",
        "pricing",
        "kappa",
        "scope",
        "design",
        "fold",
        "eval_split",
        "kpi",
        "beta",
        "value",
        "hash",
    ]
    if f.empty:
        out["kfold_folds"] = pd.DataFrame(columns=fold_cols)
    else:
        f = f.loc[
            (f["kpi"].isin(["cvar_uncovered", "expected_uncovered"]))
            & (f["level"] == "portfolio")
        ].copy()
        f["hash"] = f["config_hash"].map(_short)
        out["kfold_folds"] = f[fold_cols]
    g = pd.read_csv(full / "guard_samples.csv")
    out["guard"] = g.drop(columns=["filters"])
    t = _read(full / "guard_tails.csv")
    if not t.empty:
        out["guard_tails"] = (
            t.groupby(
                ["eventset", "split", "fold", "scope", "design", "beta"], dropna=False
            )
            .agg(
                problems=("problem_id", "size"),
                p_zero_loss_min=("p_zero_loss", "min"),
                p_zero_loss_median=("p_zero_loss", "median"),
                p_zero_loss_max=("p_zero_loss", "max"),
                tail_outcomes=("tail_outcomes", "min"),
                flagged_expected_uncovered=(
                    "degenerate_tail",
                    lambda s: int((s == "expected_uncovered").sum()),
                ),
                flagged_single_outcome=(
                    "degenerate_tail",
                    lambda s: int((s == "single_outcome").sum()),
                ),
            )
            .reset_index()
        )
        out["guard_tail_counties"] = t.loc[t["scope"] == "individual"][
            [
                "eventset",
                "split",
                "fold",
                "design",
                "beta",
                "problem_id",
                "p_zero_loss",
                "degenerate_tail",
            ]
        ]
    return out


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------


class Look:
    """Lookups into the committed tables."""

    def __init__(self, t: dict[str, pd.DataFrame]) -> None:
        self.t = t
        c = pd.concat(
            [t["contrasts"], t["contrasts_pooled"], t["contrasts_train"]],
            ignore_index=True,
        )
        c = c.fillna({"joint_scope": "", "tail_design": "", "base_design": ""})
        self.c = c
        self.g = t["grid"]

    def con(
        self,
        idx: str,
        pricing: str,
        kappa: float,
        split: str,
        name: str,
        j: str,
        w: str,
        o: str,
        kpi: str,
        beta: float | None,
    ) -> pd.Series | None:
        """Return one contrast row (None if that contrast was not run)."""
        c = self.c
        m = (
            (c["eventset"] == idx)
            & (c["pricing"] == pricing)
            & (c["kappa"] == kappa)
            & (c["split"] == split)
            & (c["contrast"] == name)
            & (c["joint_scope"] == j)
            & (c["tail_design"] == w)
            & (c["base_design"] == o)
            & (c["kpi"] == kpi)
        )
        m &= c["eval_beta"].isna() if beta is None else (c["eval_beta"] == beta)
        r = c.loc[m]
        if len(r) > 1:
            raise RuntimeError(
                f"{len(r)} rows for {idx} {pricing} {kappa} {split} {name}"
            )
        return None if r.empty else r.iloc[0]

    def rel(self, *args: Any) -> str:  # noqa: ANN401
        """Return a contrast's relative value, with its interval (not train)."""
        r = self.con(*args)
        if r is None:
            return "not run"
        if r["split"] == "train":
            return _pct(float(r["rel"]))
        return _rel_ci(float(r["rel"]), float(r["rel_ci_low"]), float(r["rel_ci_high"]))

    def grid(
        self,
        idx: str,
        pricing: str,
        kappa: float,
        split: str,
        scope: str,
        design: str,
        kpi: str,
        beta: float | None,
    ) -> pd.Series | None:
        """Return one grid row (None if that design was not run)."""
        g = self.g
        m = (
            (g["eventset"] == idx)
            & (g["pricing"] == pricing)
            & (g["kappa"] == kappa)
            & (g["split"] == split)
            & (g["scope"] == scope)
            & (g["design"] == design)
            & (g["kpi"] == kpi)
        )
        m &= g["eval_beta"].isna() if beta is None else (g["eval_beta"] == beta)
        r = g.loc[m]
        if len(r) > 1:
            raise RuntimeError("duplicate grid rows")
        return None if r.empty else r.iloc[0]

    def money(self, *args: Any) -> str:  # noqa: ANN401
        """Return a grid value in USD million, with its interval if any."""
        r = self.grid(*args)
        if r is None:
            return "not run"
        return _money_ci(float(r["value"]), float(r["ci_low"]), float(r["ci_high"]))


def _rq1_contrast(scope: str, w: str, o: str) -> tuple[str, str, str, str]:
    """Return the contrast name and terms for W - O within a scope."""
    if scope == "individual":
        return ("rq1_alone", "", w, o)
    return ("adds_rq1", scope, w, o)


def _rq2_contrast(scope: str, design: str) -> tuple[str, str, str, str]:
    """Return the contrast name and terms for J - I within a design."""
    if design in TAIL_DESIGNS:
        return ("adds_rq2", scope, design, "")
    return ("rq2_alone", scope, "", design)


def markdown(t: dict[str, pd.DataFrame]) -> str:
    """Every table of the note, generated.

    Parameters
    ----------
    t : dict of pandas.DataFrame
        The committed tables.

    Returns
    -------
    str
        ``tables.md``.
    """
    lk = Look(t)
    parts: list[str] = [
        "# Florida rerun (MAR-202): tables",
        "",
        "Generated by `research/scripts/florida_rerun_tables.py` from the CSVs "
        "in this directory. Observations only. Setup: `research/notes/"
        "florida-rerun.md` section 2. Money in USD million (LitPop reference "
        "year 2018), per year. Relative differences are against the "
        "subtracted design (the interaction: against individual MSE or E[U]). "
        "`*`: the paired 90 % interval excludes zero. Train is in sample "
        "(holdout calibration years); test the holdout test years; pooled the "
        "5-fold pooled out-of-sample result (κ 1 only). Hashes: first 12 hex "
        "digits of the config hash (`runs.csv` has them in full; `d:` is a "
        "derived design).",
        "",
    ]

    # T1 grid
    parts += ["## T1. The grid at κ 1 (CVaR₀.₉₉(U) and E[U])", ""]
    for idx in INDICES:
        for pricing in PRICINGS:
            parts += [f"**{INDEX_LABEL[idx]}, {PRICING_LABEL[pricing]}, κ 1**", ""]
            rows = []
            for scope in SCOPES:
                for d in DESIGNS:
                    r = lk.grid(
                        idx, pricing, 1.0, "test", scope, d, "cvar_uncovered", 0.99
                    )
                    bu = lk.grid(
                        idx, pricing, 1.0, "train", scope, d, "budget_use", None
                    )
                    rows.append(
                        [
                            scope,
                            DESIGN_LABEL[d],
                            lk.money(
                                idx,
                                pricing,
                                1.0,
                                "train",
                                scope,
                                d,
                                "cvar_uncovered",
                                0.99,
                            ),
                            lk.money(
                                idx,
                                pricing,
                                1.0,
                                "test",
                                scope,
                                d,
                                "cvar_uncovered",
                                0.99,
                            ),
                            lk.money(
                                idx,
                                pricing,
                                1.0,
                                "pooled",
                                scope,
                                d,
                                "cvar_uncovered",
                                0.99,
                            ),
                            lk.money(
                                idx,
                                pricing,
                                1.0,
                                "test",
                                scope,
                                d,
                                "expected_uncovered",
                                None,
                            ),
                            lk.money(
                                idx,
                                pricing,
                                1.0,
                                "pooled",
                                scope,
                                d,
                                "expected_uncovered",
                                None,
                            ),
                            "n/a" if bu is None else f"{float(bu['value']):.3f}",
                            "" if r is None else f"`{r['hash']}`",
                        ]
                    )
            parts += [
                _table(
                    [
                        "Scope",
                        "Design",
                        "Train CVaR₀.₉₉",
                        "Test CVaR₀.₉₉ [90 % CI]",
                        "Pooled CVaR₀.₉₉ [90 % CI]",
                        "Test E[U] [90 % CI]",
                        "Pooled E[U] [90 % CI]",
                        "Budget use",
                        "Hash",
                    ],
                    rows,
                ),
                "",
            ]
        exp = [
            (
                s,
                lk.grid(
                    idx, "pure", 1.0, s, "individual", "mse", "expected_loss", None
                ),
            )
            for s in ("train", "test", "pooled")
        ]
        parts += [
            "Expected annual loss, "
            + INDEX_LABEL[idx]
            + ": "
            + ", ".join(f"{s} {_m(float(r['value']))}" for s, r in exp if r is not None)
            + ".",
            "",
        ]

    # T2 RQ1 at kappa 1
    parts += [
        "## T2. RQ1: weighted CVaR minus MSE and E[U] within each scope, κ 1",
        "",
        "Read at the KPI β that matches the design β; ΔE[U] relative to the "
        "baseline design's E[U].",
        "",
    ]
    rows = []
    for idx in INDICES:
        for pricing in PRICINGS:
            for scope in SCOPES:
                for w in TAIL_DESIGNS:
                    b = MATCHED_BETA[w]
                    for o in ("mse", "eu"):
                        name, j, ww, oo = _rq1_contrast(scope, w, o)
                        a = (idx, pricing, 1.0)
                        rows.append(
                            [
                                idx,
                                PRICING_LABEL[pricing],
                                scope,
                                f"{DESIGN_LABEL[w]} − {DESIGN_LABEL[o]}",
                                f"{b:g}",
                                lk.rel(
                                    *a, "train", name, j, ww, oo, "cvar_uncovered", b
                                ),
                                lk.rel(
                                    *a, "test", name, j, ww, oo, "cvar_uncovered", b
                                ),
                                lk.rel(
                                    *a, "pooled", name, j, ww, oo, "cvar_uncovered", b
                                ),
                                lk.rel(
                                    *a,
                                    "test",
                                    name,
                                    j,
                                    ww,
                                    oo,
                                    "expected_uncovered",
                                    None,
                                ),
                                lk.rel(
                                    *a,
                                    "pooled",
                                    name,
                                    j,
                                    ww,
                                    oo,
                                    "expected_uncovered",
                                    None,
                                ),
                            ]
                        )
    parts += [
        _table(
            [
                "Index",
                "Pricing",
                "Scope",
                "Contrast",
                "KPI β",
                "Train ΔCVaR",
                "Test ΔCVaR [90 % CI]",
                "Pooled ΔCVaR [90 % CI]",
                "Test ΔE[U]",
                "Pooled ΔE[U]",
            ],
            rows,
        ),
        "",
    ]

    # T3 RQ1 across kappa and KPI beta (holdout test)
    parts += [
        "## T3. RQ1 across κ and KPI β (holdout test)",
        "",
        "Weighted CVaR minus MSE / minus E[U], test CVaR at KPI β 0.95, 0.99, 0.995.",
        "",
    ]
    rows = []
    for idx in INDICES:
        for pricing in PRICINGS:
            for kappa in KAPPAS:
                for scope in SCOPES:
                    for w in TAIL_DESIGNS:
                        for o in ("mse", "eu"):
                            name, j, ww, oo = _rq1_contrast(scope, w, o)
                            rows.append(
                                [
                                    idx,
                                    PRICING_LABEL[pricing],
                                    f"{kappa:g}",
                                    scope,
                                    f"{DESIGN_LABEL[w]} − {DESIGN_LABEL[o]}",
                                    *[
                                        lk.rel(
                                            idx,
                                            pricing,
                                            kappa,
                                            "test",
                                            name,
                                            j,
                                            ww,
                                            oo,
                                            "cvar_uncovered",
                                            b,
                                        )
                                        for b in BETAS
                                    ],
                                ]
                            )
    parts += [
        _table(
            [
                "Index",
                "Pricing",
                "κ",
                "Scope",
                "Contrast",
                "KPI 0.95",
                "KPI 0.99",
                "KPI 0.995",
            ],
            rows,
        ),
        "",
    ]

    # T4 RQ2 kappa 1
    parts += [
        "## T4. RQ2: joint minus individual calibration within each design, κ 1",
        "",
        "Cluster: a different index (value-weighted mean wind or category of "
        "3 clusters). " + CONFOUNDED + " T6 splits the difference as C1 "
        "section 6b.6 does.",
        "",
        NOT_UNIQUE,
        "",
    ]
    rows = []
    for idx in INDICES:
        for pricing in PRICINGS:
            for scope in ("portfolio", "cluster"):
                for d in DESIGNS:
                    name, j, w, o = _rq2_contrast(scope, d)
                    a = (idx, pricing, 1.0)
                    cells = []
                    for b in (0.99, 0.995):
                        cells += [
                            lk.rel(*a, s, name, j, w, o, "cvar_uncovered", b)
                            for s in ("train", "test", "pooled")
                        ]
                    rows.append(
                        [
                            idx,
                            PRICING_LABEL[pricing],
                            f"{scope} − individual",
                            DESIGN_LABEL[d],
                            *cells,
                            lk.rel(
                                *a, "test", name, j, w, o, "expected_uncovered", None
                            ),
                            lk.rel(
                                *a, "pooled", name, j, w, o, "expected_uncovered", None
                            ),
                        ]
                    )
    parts += [
        _table(
            [
                "Index",
                "Pricing",
                "Comparison",
                "Design",
                "Train CVaR₀.₉₉",
                "Test CVaR₀.₉₉",
                "Pooled CVaR₀.₉₉",
                "Train CVaR₀.₉₉₅",
                "Test CVaR₀.₉₉₅",
                "Pooled CVaR₀.₉₉₅",
                "Test ΔE[U]",
                "Pooled ΔE[U]",
            ],
            rows,
        ),
        "",
    ]

    # T5 RQ2 across kappa
    parts += [
        "## T5. RQ2 across κ (holdout; CVaR₀.₉₉, train and test)",
        "",
        CONFOUNDED,
        "",
        NOT_UNIQUE,
        "",
    ]
    rows = []
    for idx in INDICES:
        for pricing in PRICINGS:
            for kappa in KAPPAS:
                for d in DESIGNS:
                    cells = []
                    for scope in ("portfolio", "cluster"):
                        name, j, w, o = _rq2_contrast(scope, d)
                        cells += [
                            lk.rel(
                                idx,
                                pricing,
                                kappa,
                                s,
                                name,
                                j,
                                w,
                                o,
                                "cvar_uncovered",
                                0.99,
                            )
                            for s in ("train", "test")
                        ]
                    rows.append(
                        [
                            idx,
                            PRICING_LABEL[pricing],
                            f"{kappa:g}",
                            DESIGN_LABEL[d],
                            *cells,
                        ]
                    )
    parts += [
        _table(
            [
                "Index",
                "Pricing",
                "κ",
                "Design",
                "Portfolio − ind., train",
                "Portfolio − ind., test",
                "Cluster − ind., train",
                "Cluster − ind., test",
            ],
            rows,
        ),
        "",
    ]

    # T6 cluster parts
    parts += [
        "## T6. Cluster minus individual: index part and joint part (κ 1, CVaR₀.₉₉)",
        "",
        "Index part: `cluster_separate` (the clusters and their index, each "
        "cluster calibrated on its own) − individual. Joint part: cluster − "
        "`cluster_separate`. Cluster − individual is in T4. " + CONFOUNDED,
        "",
        NOT_UNIQUE,
        "",
    ]
    cp = t["cluster_parts"]
    rows = []
    for idx in INDICES:
        for pricing in PRICINGS:
            for d in DESIGNS:
                cells = []
                h = ""
                for a_, b_ in (
                    ("cluster_separate", "individual"),
                    ("cluster", "cluster_separate"),
                ):
                    for s in ("train", "test"):
                        r = cp.loc[
                            (cp["eventset"] == idx)
                            & (cp["pricing"] == pricing)
                            & (cp["kappa"] == 1.0)
                            & (cp["design"] == d)
                            & (cp["split"] == s)
                            & (cp["scope_a"] == a_)
                            & (cp["scope_b"] == b_)
                            & (cp["kpi"] == "cvar_uncovered")
                            & (cp["eval_beta"] == 0.99)
                        ]
                        if r.empty:
                            cells.append("n/a")
                            continue
                        x = r.iloc[0]
                        if a_ == "cluster_separate":
                            h = str(x["hash_a"])
                        cells.append(
                            _pct(float(x["rel"]))
                            if s == "train"
                            else _rel_ci(
                                float(x["rel"]),
                                float(x["rel_ci_low"]),
                                float(x["rel_ci_high"]),
                            )
                        )
                rows.append(
                    [idx, PRICING_LABEL[pricing], DESIGN_LABEL[d], *cells, f"`{h}`"]
                )
    parts += [
        _table(
            [
                "Index",
                "Pricing",
                "Design",
                "Index part, train",
                "Index part, test",
                "Joint part, train",
                "Joint part, test",
                "Id separate",
            ],
            rows,
        ),
        "",
    ]

    # T7 payout per county
    parts += _payout_tables(t)

    # T8 premium split
    parts += _premium_tables(t)

    # T9 combination
    parts += [
        "## T9. The combination: portfolio weighted CVaR against the three "
        "alternatives, κ 1",
        "",
        "Read at the KPI β that matches the design β.",
        "",
        NOT_UNIQUE,
        "",
    ]
    rows = []
    for idx in INDICES:
        for pricing in PRICINGS:
            for w in TAIL_DESIGNS:
                b = MATCHED_BETA[w]
                for label, (name, j, ww, oo) in (
                    ("vs individual MSE (both)", ("both", "portfolio", w, "mse")),
                    (
                        f"vs individual {DESIGN_LABEL[w]} (adds RQ2)",
                        ("adds_rq2", "portfolio", w, ""),
                    ),
                    (
                        "vs portfolio MSE (adds RQ1)",
                        ("adds_rq1", "portfolio", w, "mse"),
                    ),
                ):
                    a = (idx, pricing, 1.0)
                    rows.append(
                        [
                            idx,
                            PRICING_LABEL[pricing],
                            DESIGN_LABEL[w],
                            label,
                            *[
                                lk.rel(*a, s, name, j, ww, oo, "cvar_uncovered", b)
                                for s in ("train", "test", "pooled")
                            ],
                            lk.rel(
                                *a, "test", name, j, ww, oo, "expected_uncovered", None
                            ),
                            lk.rel(
                                *a,
                                "pooled",
                                name,
                                j,
                                ww,
                                oo,
                                "expected_uncovered",
                                None,
                            ),
                        ]
                    )
    parts += [
        _table(
            [
                "Index",
                "Pricing",
                "Design",
                "Comparison",
                "Train ΔCVaR",
                "Test ΔCVaR",
                "Pooled ΔCVaR",
                "Test ΔE[U]",
                "Pooled ΔE[U]",
            ],
            rows,
        ),
        "",
    ]

    # T10 decomposition
    parts += [
        "## T10. Both = RQ1 alone + RQ2 alone + interaction (portfolio, base MSE, κ 1)",
        "",
        "Relative to the individual MSE design's value.",
        "",
        NOT_UNIQUE,
        "",
    ]
    rows = []
    for idx in INDICES:
        for pricing in PRICINGS:
            for w in TAIL_DESIGNS:
                for kpi, b in (
                    ("cvar_uncovered", MATCHED_BETA[w]),
                    ("expected_uncovered", None),
                ):
                    for s in ("train", "test", "pooled"):
                        a = (idx, pricing, 1.0, s)
                        rows.append(
                            [
                                idx,
                                PRICING_LABEL[pricing],
                                DESIGN_LABEL[w],
                                "E[U]" if b is None else f"CVaR {b:g}",
                                s,
                                lk.rel(*a, "both", "portfolio", w, "mse", kpi, b),
                                lk.rel(*a, "rq1_alone", "", w, "mse", kpi, b),
                                lk.rel(*a, "rq2_alone", "portfolio", "", "mse", kpi, b),
                                lk.rel(
                                    *a, "interaction", "portfolio", w, "mse", kpi, b
                                ),
                            ]
                        )
    parts += [
        _table(
            [
                "Index",
                "Pricing",
                "Design",
                "KPI",
                "Split",
                "Both",
                "RQ1 alone",
                "RQ2 alone",
                "Interaction",
            ],
            rows,
        ),
        "",
    ]

    # T11 counts
    parts += _count_table(t)

    # T12 folds
    parts += _fold_table(t)

    # T13 guard
    g = t["guard"]
    parts += [
        "## T13. Degenerate-tail guard (MAR-172): zero-loss share of each "
        "calibration sample",
        "",
        "Rate-weighted share of the prepared rows with zero portfolio loss; "
        "the guard fires at `beta_tail` (0.9) or above.",
        "",
        _table(
            [
                "Index",
                "Split",
                "Fold",
                "Sample",
                "Rows",
                "Zero-loss share",
                "beta_tail",
                "Fires",
            ],
            [
                [
                    str(r.eventset),
                    str(r.split),
                    "" if r.fold < 0 else str(r.fold),
                    str(r.sample),
                    f"{r.rows:,}",
                    f"{100 * r.zero_loss_share:.2f} %",
                    f"{r.beta_tail:g}",
                    "yes" if r.guard_fires else "no",
                ]
                for r in g.itertuples()
            ],
        ),
        "",
    ]
    return "\n".join(parts)


def _payout_tables(t: dict[str, pd.DataFrame]) -> list[str]:
    ent = t["entity_payouts"]
    names = _names()
    parts = [
        "## T7. Payout per county: E[π_i] / E[L_i] on the train years, κ 1",
        "",
        "Every individual design's ratio and every portfolio design's ratio, "
        "summarised over the 67 counties; then the 10 counties with the "
        "largest train loss. A joint design's split is one member of its "
        "optimal set (MAR-100, MAR-161 F8); no near-optimal ranges here "
        "(MAR-198).",
        "",
    ]
    rows = []
    for idx in INDICES:
        for pricing in PRICINGS:
            for scope in ("individual", "portfolio"):
                for d in DESIGNS:
                    e = ent.loc[
                        (ent["eventset"] == idx)
                        & (ent["pricing"] == pricing)
                        & (ent["design"] == d)
                        & (ent["scope"] == scope)
                        & (ent["split"] == "train")
                    ]
                    if e.empty:
                        continue
                    r = e["payout_to_loss"]
                    share = e["expected_loss"] / e["expected_loss"].sum()
                    pay_share = e["expected_payout"] / e["expected_payout"].sum()
                    top = share.sort_values(ascending=False).index[:5]
                    rows.append(
                        [
                            idx,
                            PRICING_LABEL[pricing],
                            scope,
                            DESIGN_LABEL[d],
                            _ratio(r.min()),
                            _ratio(r.quantile(0.25)),
                            _ratio(r.median()),
                            _ratio(r.quantile(0.75)),
                            _ratio(r.max()),
                            str(int((r < 0.01).sum())),
                            str(int((r < 0.5).sum())),
                            str(int((r > 2.0).sum())),
                            _pct(float(share[top].sum()), signed=False),
                            _pct(float(pay_share[top].sum()), signed=False),
                        ]
                    )
    parts += [
        _table(
            [
                "Index",
                "Pricing",
                "Scope",
                "Design",
                "min",
                "25 %",
                "median",
                "75 %",
                "max",
                "< 0.01",
                "< 0.5",
                "> 2",
                "Loss share, top 5",
                "Payout share, top 5",
            ],
            rows,
        ),
        "",
    ]
    for idx in INDICES:
        e = ent.loc[
            (ent["eventset"] == idx)
            & (ent["pricing"] == "pure")
            & (ent["scope"] == "portfolio")
            & (ent["split"] == "train")
        ]
        if e.empty:
            continue
        base = e.loc[e["design"] == "mse"].set_index("entity_id")
        total = base["expected_loss"].sum()
        top = base["expected_loss"].sort_values(ascending=False).index[:10]
        rows = []
        for loc in top:
            row = [
                names.get(str(loc), str(loc)),
                _pct(float(base.loc[loc, "expected_loss"] / total), signed=False),
            ]
            for d in DESIGNS:
                x = e.loc[
                    (e["design"] == d) & (e["entity_id"].astype(str) == str(loc)),
                    "payout_to_loss",
                ]
                row.append("n/a" if x.empty else _ratio(float(x.iloc[0])))
            rows.append(row)
        parts += [
            f"**{INDEX_LABEL[idx]}, pure, κ 1, portfolio designs**",
            "",
            _table(
                ["County", "Loss share (train)", *[DESIGN_LABEL[d] for d in DESIGNS]],
                rows,
            ),
            "",
        ]
    # clusters
    cl = t["clusters"]
    rows = []
    for idx in INDICES:
        c = cl.loc[cl["eventset"] == idx]
        for cid, g in c.groupby("cluster_id"):
            e = ent.loc[
                (ent["eventset"] == idx)
                & (ent["pricing"] == "pure")
                & (ent["scope"] == "cluster")
                & (ent["split"] == "train")
                & (ent["entity_id"].astype(str) == str(cid))
            ]
            el_all = ent.loc[
                (ent["eventset"] == idx)
                & (ent["pricing"] == "pure")
                & (ent["scope"] == "cluster")
                & (ent["split"] == "train")
                & (ent["design"] == "mse")
            ]["expected_loss"].sum()
            ratios = {d: e.loc[e["design"] == d, "payout_to_loss"] for d in DESIGNS}
            el = e.loc[e["design"] == "mse", "expected_loss"]
            members = [names.get(str(x), str(x)) for x in g["location_id"]]
            rows.append(
                [
                    idx,
                    str(cid),
                    str(len(g)),
                    ", ".join(members[:6]) + (" …" if len(members) > 6 else ""),
                    "n/a"
                    if el.empty
                    else _pct(float(el.iloc[0] / el_all), signed=False),
                    *[
                        "n/a" if r.empty else _ratio(float(r.iloc[0]))
                        for r in ratios.values()
                    ],
                ]
            )
    parts += [
        "**Clusters (thesis Ward, 3 clusters, train years) and the cluster "
        "designs' E[π]/E[L], pure, κ 1**",
        "",
        _table(
            [
                "Index",
                "Cluster",
                "Counties",
                "Members (first 6)",
                "Loss share",
                *[DESIGN_LABEL[d] for d in DESIGNS],
            ],
            rows,
        ),
        "",
    ]
    return parts


def _premium_tables(t: dict[str, pd.DataFrame]) -> list[str]:
    p = t["premiums"]
    ps = t["premium_split"]
    parts = [
        "## T8. Under the load: the pricing-diversification credit and the "
        "premium split (CoC r 0.06)",
        "",
        "A = the premium of the individual designs' summed payout (train), "
        "S = the sum of their 67 stand-alone premiums; credit = 1 − A / S. "
        "`portfolio_matched` = the portfolio design problem budgeted at A. "
        "Portfolio − individual = cross-coverage (matched − individual) + "
        "pricing diversification (portfolio − matched); CVaR₀.₉₉(U), every "
        "part relative to the individual design's value, so the parts add up.",
        "",
        NOT_UNIQUE,
        "",
    ]
    rows = []
    for r in p.sort_values(["eventset", "kappa", "design"]).itertuples():
        cells = []
        for a_, b_ in (
            ("portfolio_matched", "individual"),
            ("portfolio", "portfolio_matched"),
            ("portfolio", "individual"),
        ):
            for s in ("train", "test"):
                x = ps.loc[
                    (ps["eventset"] == r.eventset)
                    & (ps["pricing"] == r.pricing)
                    & (ps["kappa"] == r.kappa)
                    & (ps["design"] == r.design)
                    & (ps["split"] == s)
                    & (ps["scope_a"] == a_)
                    & (ps["scope_b"] == b_)
                    & (ps["kpi"] == "cvar_uncovered")
                    & (ps["eval_beta"] == 0.99)
                ]
                if x.empty:
                    cells.append("n/a")
                    continue
                y = x.iloc[0]
                cells.append(
                    _pct(float(y["rel"]))
                    if s == "train"
                    else _rel_ci(
                        float(y["rel"]), float(y["rel_ci_low"]), float(y["rel_ci_high"])
                    )
                )
        rows.append(
            [
                str(r.eventset),
                f"{r.kappa:g}",
                DESIGN_LABEL[str(r.design)],
                _pct(float(r.pricing_credit), signed=False),
                f"{r.matched_loading:.4f}",
                f"{r.matched_budget_use:.3f}",
                *cells,
                f"`{r.matched_config_hash}`",
            ]
        )
    parts += [
        _table(
            [
                "Index",
                "κ",
                "Design",
                "Credit 1 − A/S",
                "Matched loading A/E[L]",
                "Matched budget use",
                "Cross-cov., train",
                "Cross-cov., test",
                "Pricing div., train",
                "Pricing div., test",
                "Total, train",
                "Total, test",
                "Hash matched",
            ],
            rows,
        ),
        "",
    ]
    return parts


def _count_table(t: dict[str, pd.DataFrame]) -> list[str]:
    c = t["contrasts"]
    c = c.loc[(c["split"] == "test") & (c["kpi"] == "cvar_uncovered")].fillna(
        {"joint_scope": ""}
    )
    rows = []
    for idx in INDICES:
        for name in (
            "rq1_alone",
            "adds_rq1",
            "rq2_alone",
            "adds_rq2",
            "both",
            "interaction",
        ):
            for j in ("", "portfolio", "cluster"):
                x = c.loc[
                    (c["eventset"] == idx)
                    & (c["contrast"] == name)
                    & (c["joint_scope"] == j)
                ]
                x = x.drop_duplicates(
                    ["pricing", "kappa", "tail_design", "base_design", "eval_beta"]
                )
                if x.empty:
                    continue
                rows.append(
                    [
                        idx,
                        name,
                        j or "individual",
                        str(len(x)),
                        str(int((x["ci_high"] < 0).sum())),
                        str(int((x["ci_low"] > 0).sum())),
                    ]
                )
    return [
        "## T11. Holdout grid: test CVaR intervals below and above zero",
        "",
        "Every pricing, κ, tail design, base design and KPI β (0.95, 0.99, 0.995).",
        "",
        _table(
            ["Index", "Contrast", "Scope", "Cells", "Below zero", "Above zero"], rows
        ),
        "",
    ]


def _fold_table(t: dict[str, pd.DataFrame]) -> list[str]:
    f = t["kfold_folds"]
    f = f.loc[(f["kpi"] == "cvar_uncovered") & (f["beta"] == 0.99)]
    rows = []
    for idx in INDICES:
        for pricing in PRICINGS:
            for d in DESIGNS:
                x = f.loc[
                    (f["eventset"] == idx)
                    & (f["pricing"] == pricing)
                    & (f["design"] == d)
                ]
                if x.empty:
                    continue
                piv = x.pivot_table(
                    index=["fold", "eval_split"],
                    columns="scope",
                    values="value",
                    aggfunc="first",
                )
                cells = []
                for split in ("train", "test"):
                    s = piv.xs(split, level="eval_split")
                    rel = s["portfolio"] / s["individual"] - 1.0
                    cells.append(
                        f"{_pct(float(rel.min()))} to {_pct(float(rel.max()))}"
                    )
                rows.append([idx, PRICING_LABEL[pricing], DESIGN_LABEL[d], *cells])
    return [
        "## T12. Per fold: portfolio − individual, CVaR₀.₉₉(U), κ 1",
        "",
        "Range over the 5 folds; train = the fold's 8,000 calibration years, "
        "test = its held-out block.",
        "",
        NOT_UNIQUE,
        "",
        _table(
            ["Index", "Pricing", "Design", "Train (5 folds)", "Test (5 folds)"], rows
        ),
        "",
    ]


def _names() -> dict[str, str]:
    if not LOCATIONS.is_file():
        return {}
    loc = pd.read_parquet(LOCATIONS)
    return dict(
        zip(loc["location_id"].astype(str), loc["name"].astype(str), strict=True)
    )


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
    parser = argparse.ArgumentParser(description="Florida rerun tables (MAR-202).")
    parser.add_argument("--full", type=Path, default=FULL)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    tables = build(args.full)
    args.out.mkdir(parents=True, exist_ok=True)
    for name, frame in tables.items():
        path = args.out / f"{name}.csv"
        frame.to_csv(path, index=False, float_format="%.7g")
        size = path.stat().st_size
        if size > 500_000:
            raise RuntimeError(f"{path} is {size} bytes, over the 500 kB limit")
    (args.out / "tables.md").write_text(markdown(tables).rstrip("\n") + "\n")
    summary: dict[str, Any] = {"issue": "MAR-202", "phases": {}}
    for p in sorted(args.full.glob("summary_*.json")):
        s = json.loads(p.read_text())
        s.pop("solve_seconds_per_run", None)
        summary["phases"][p.stem.removeprefix("summary_")] = s
    g = tables["guard"]
    summary["guard_fires"] = int(g["guard_fires"].sum())
    summary["committed_tables"] = sorted(f"{n}.csv" for n in tables)
    (args.out / "summary.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
