r"""C1 combination view (MAR-182): a tail objective calibrated jointly (RQ1 x RQ2).

Question (MAR-182): C1 answers RQ1 (the objective, within each scope) and
RQ2 (the scope, within each objective) separately. The combination changes
both at once: a weighted-CVaR objective calibrated jointly across one owner's
sites, against the alternatives the owner would otherwise use. And do the two
ideas interact: does the tail gain depend on the scope, and does the joint
gain depend on the objective?

This script reuses the C1 designs and solves nothing. It reads them from the
C1 result store (``results/c1/store``, not committed; built by
``c1_checkpoint.py``) and the k-fold runs of MAR-158 from
``results/c1-rq2/store`` (not committed; built by ``c1_rq2.py``). Phases:

``holdout``
    For every main-line variant (pricing pure, cost of capital r 0.06 and
    0.10 with q 0.99; kappa 0.5, 1, 1.5) and the provisional F-12 variants
    (four EventSets, pure and r 0.06, kappa 1), rebuilds the 3 scopes x 4
    designs (MSE, E[U], weighted CVaR beta 0.99 and 0.995; F-12: no beta
    0.995) and bootstraps their **test** KPIs at KPI beta 0.95, 0.99 and
    0.995 on **one** year resample (B = 1000, seed 0: the C1 resample), so
    every design of a variant is paired with every other, across scopes and
    objectives. Train KPIs are point values (in sample).

``kfold``
    The pooled 5-fold KPIs (MAR-151) of the MAR-158 k-fold runs (kappa 1,
    pure and r 0.06, the four designs and three scopes): every year
    evaluated by the design that did not see it, on one resample of all
    10,000 years shared by every design.

**Contrasts.** For a joint scope J (portfolio, or cluster: a different
index), a tail design W (weighted CVaR beta 0.99 or 0.995) and a base
objective O (MSE or E[U]), with I the individual scope:

* ``both``: (J, W) - (I, O), both ideas against neither;
* ``adds_rq2``: (J, W) - (I, W), joint calibration added to the tail design;
* ``adds_rq1``: (J, W) - (J, O), the tail objective added to joint
  calibration;
* ``rq1_alone``: (I, W) - (I, O); ``rq2_alone``: (J, O) - (I, O);
* ``interaction``: ((J, W) - (J, O)) - ((I, W) - (I, O)), the difference of
  differences. It equals ((J, W) - (I, W)) - ((J, O) - (I, O)): "does the
  tail gain depend on the scope" and "does the joint gain depend on the
  objective" are the same number. And ``both`` = ``rq1_alone`` +
  ``rq2_alone`` + ``interaction`` exactly (checked on every row).

**Pairing across scopes** (MAR-158's method; C1.md section 6b.1):
``bootstrap.paired_difference`` pairs KPI rows on ``PAIR_KEY``, which
includes ``problem_id`` (``"*"`` for the individual scope, ``"portfolio"``
for a joint one). ``c1_rq2.portfolio_rows`` keeps each design's
portfolio-level rows with a common ``problem_id`` on a copy, and
``paired_difference`` is called unchanged, with its same-resample check. The
interaction is ``paired_difference`` of two difference bootstraps
(:func:`difference_bootstrap`: point values and replicates subtracted row by
row, after the same check). The k-fold contrasts use ``kpi_replicates`` of
``kfold.pooled_designs`` on the one shared resample, and are checked against
``kfold.pooled_difference`` wherever both designs are in one k-fold config.

**Checks** (raise on failure): the recomputed test KPIs equal C1's
(``research/data/c1/kpis_<family>.csv``); the two-term contrasts that C1 or
MAR-158 already reported equal theirs (``research/data/c1/paired_*.csv``,
``research/data/c1-rq2/scope_paired*.csv``); the budget use equals C1's
``runs.csv``; the decomposition identity holds.

Outputs: the full tables go to ``results/c1-combination/full/`` (not
committed). ``c1_combination_tables.py`` writes the committed ones, each
under the 500 kB pre-commit limit, ``tables.md`` and ``summary.json`` to
``research/data/c1-combination/``. Portfolio-level KPIs only: no per-asset
KPIs of joint designs (MAR-98, MAR-100).

Run from the repository root, after ``c1_checkpoint.py`` and ``c1_rq2.py``
(their stores)::

    uv run python research/scripts/c1_combination.py --jobs 3
    uv run python research/scripts/c1_combination_tables.py

Observations only. The interpretation is the owner's.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Any, Final

import c1_checkpoint as c1
import c1_rq2 as rq2
import numpy as np
import pandas as pd

from parametric_insurance_design import splits
from parametric_insurance_design.basis import Basis, outcome_measure
from parametric_insurance_design.bootstrap import (
    PAIR_KEY,
    BootstrapError,
    KpiBootstrap,
    YearResample,
    bootstrap_kpis,
    kpi_replicates,
    paired_difference,
    percentile_interval,
    resample_years,
)
from parametric_insurance_design.evaluate import kpis
from parametric_insurance_design.experiment import kfold
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.runner import package_versions, run_key
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.records import ALL_PROBLEMS, KpiName
from parametric_insurance_design.solve import DEFAULT_POLICY

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
FULL_DIR: Final[Path] = REPO_ROOT / "results" / "c1-combination" / "full"
C1_DATA: Final[Path] = REPO_ROOT / "research" / "data" / "c1"
RQ2_DATA: Final[Path] = REPO_ROOT / "research" / "data" / "c1-rq2"

INDIVIDUAL: Final[str] = "individual"
SCOPES: Final[tuple[str, ...]] = c1.SCOPES
JOINT_SCOPES: Final[tuple[str, ...]] = ("portfolio", "cluster")
DESIGNS: Final[dict[str, tuple[str, ...]]] = {
    "main": ("mse", "eu", "wcvar@0.99", "wcvar@0.995"),
    "f12": ("mse", "eu", "wcvar@0.99"),
}
TAIL_DESIGNS: Final[dict[str, tuple[str, ...]]] = {
    "main": ("wcvar@0.99", "wcvar@0.995"),
    "f12": ("wcvar@0.99",),
}
BASE_DESIGNS: Final[tuple[str, ...]] = ("mse", "eu")
EVAL_BETAS: Final[tuple[float, ...]] = c1.ANNUAL_EVAL_BETAS
CONFIG_BETA: Final[float] = 0.99
"""The configs' ``evaluation.beta``; beta-free KPIs are kept at this beta."""
GRID_KPIS: Final[tuple[str, ...]] = (
    "expected_loss",
    "expected_payout",
    "expected_uncovered",
    "cvar_uncovered",
    "premium",
)
CONTRAST_KPIS: Final[tuple[str, ...]] = (
    "expected_payout",
    "expected_uncovered",
    "cvar_uncovered",
)
TAIL_KPIS: Final[frozenset[str]] = frozenset({"var_uncovered", "cvar_uncovered"})
POOLED_FOLD: Final[int] = -1
"""``fold`` label of the pooled k-fold KPI rows (one sample of all years)."""


# --------------------------------------------------------------------------
# Contrasts
# --------------------------------------------------------------------------


Design = tuple[str, str]
"""(scope, design label), e.g. ``("portfolio", "wcvar@0.99")``."""


@dataclass(frozen=True)
class Contrast:
    """One contrast of designs: ``a - b``, or ``(a - b) - (c - d)``.

    Parameters
    ----------
    name : str
        ``both``, ``adds_rq2``, ``adds_rq1``, ``rq1_alone``, ``rq2_alone``
        or ``interaction`` (module docstring).
    joint_scope, tail_design, base_design : str
        J, W and O of the module docstring; ``""`` where the contrast does
        not involve one (``adds_rq2`` has no O, ``rq1_alone`` no J,
        ``rq2_alone`` no W).
    a, b : Design
        The two terms of a difference.
    c, d : Design or None
        The second difference of an interaction.
    """

    name: str
    joint_scope: str
    tail_design: str
    base_design: str
    a: Design
    b: Design
    c: Design | None = None
    d: Design | None = None

    @property
    def reference(self) -> Design:
        """The design a relative difference is taken against.

        Returns
        -------
        Design
            ``b`` for a difference; ``d`` (the individual base design, the
            "neither" design) for an interaction.
        """
        return self.b if self.d is None else self.d

    @property
    def terms(self) -> tuple[Design, ...]:
        """Every design in the contrast, in the order a, b, c, d.

        Returns
        -------
        tuple of Design
            Two or four designs.
        """
        if self.c is None or self.d is None:
            return (self.a, self.b)
        return (self.a, self.b, self.c, self.d)


def contrasts(family: str) -> list[Contrast]:
    """Return the contrasts of a C1 family, without duplicates.

    Parameters
    ----------
    family : str
        ``"main"`` or ``"f12"``.

    Returns
    -------
    list of Contrast
        For every joint scope, tail design and base objective: ``both``,
        ``adds_rq1`` and ``interaction``; ``adds_rq2`` per joint scope and
        tail design; ``rq1_alone`` per tail design and base objective;
        ``rq2_alone`` per joint scope and base objective.
    """
    out: dict[tuple[str, str, str, str], Contrast] = {}

    def add(c: Contrast) -> None:
        out.setdefault((c.name, c.joint_scope, c.tail_design, c.base_design), c)

    for j in JOINT_SCOPES:
        for w in TAIL_DESIGNS[family]:
            add(Contrast("adds_rq2", j, w, "", (j, w), (INDIVIDUAL, w)))
            for o in BASE_DESIGNS:
                add(Contrast("both", j, w, o, (j, w), (INDIVIDUAL, o)))
                add(Contrast("adds_rq1", j, w, o, (j, w), (j, o)))
                add(Contrast("rq1_alone", "", w, o, (INDIVIDUAL, w), (INDIVIDUAL, o)))
                add(Contrast("rq2_alone", j, "", o, (j, o), (INDIVIDUAL, o)))
                add(
                    Contrast(
                        "interaction",
                        j,
                        w,
                        o,
                        (j, w),
                        (j, o),
                        (INDIVIDUAL, w),
                        (INDIVIDUAL, o),
                    )
                )
    return list(out.values())


def difference_bootstrap(a: KpiBootstrap, b: KpiBootstrap) -> KpiBootstrap:
    """``KPI(a) - KPI(b)`` as a bootstrap: values and replicates subtracted.

    Rows are paired on ``PAIR_KEY`` as in ``paired_difference``, after the
    same check that both were bootstrapped with the same resample. The result
    can be passed to ``paired_difference`` again, which gives the paired
    interval of a difference of differences.

    Parameters
    ----------
    a, b : KpiBootstrap
        Two designs' bootstraps with the same subjects and resample (for
        designs of different scopes: their :func:`c1_rq2.portfolio_rows`).

    Returns
    -------
    KpiBootstrap
        ``value`` and replicates ``a - b`` per KPI row; ``ci_low`` and
        ``ci_high`` the percentile interval of the replicate differences.

    Raises
    ------
    BootstrapError
        If the resamples differ or a KPI row has no partner.
    """
    if not a.resample.same_as(b.resample):
        raise BootstrapError("difference of designs bootstrapped on other resamples")
    key = list(PAIR_KEY)
    left = a.table[[*key, "run_id", "value"]].copy()
    left["_ia"] = np.arange(len(left))
    right = b.table[[*key, "run_id", "value"]].copy()
    right["_ib"] = np.arange(len(right))
    merged = left.merge(
        right,
        on=key,
        how="outer",
        suffixes=("_a", "_b"),
        indicator=True,
        validate="one_to_one",
    )
    if (merged["_merge"] != "both").any():
        raise BootstrapError("difference of designs with different KPI rows")
    ia = merged["_ia"].to_numpy(dtype=np.int64)
    ib = merged["_ib"].to_numpy(dtype=np.int64)
    reps = a.replicates[ia] - b.replicates[ib]
    table = pd.DataFrame(merged.loc[:, key]).reset_index(drop=True)
    table["run_id"] = (
        merged["run_id_a"].astype(str) + " - " + merged["run_id_b"].astype(str)
    ).to_numpy()
    table["value"] = merged["value_a"].to_numpy(dtype=np.float64) - merged[
        "value_b"
    ].to_numpy(dtype=np.float64)
    bounds = np.array([percentile_interval(r, a.level) for r in reps]).reshape(-1, 2)
    table["ci_low"] = bounds[:, 0]
    table["ci_high"] = bounds[:, 1]
    return KpiBootstrap(
        table=table, replicates=reps, resample=a.resample, level=a.level
    )


def contrast_rows(
    boots: dict[Design, KpiBootstrap],
    hashes: dict[Design, str],
    items: Iterable[Contrast],
    *,
    split: str,
    beta: float,
) -> list[dict[str, Any]]:
    """Paired contrasts on one resample, one row per contrast and KPI.

    Parameters
    ----------
    boots : dict
        Each design's portfolio-level bootstrap at ``beta``, all on one
        resample, with a common ``problem_id``.
    hashes : dict
        Each design's config hash.
    items : iterable of Contrast
        The contrasts.
    split : str
        ``"test"`` or ``"pooled"``, for the output rows.
    beta : float
        KPI beta of ``boots``.

    Returns
    -------
    list of dict
        ``value`` (the contrast), ``ci_low``, ``ci_high``, the terms' values
        ``value_a`` ... ``value_d``, ``value_ref`` and the hashes.
    """
    rows: list[dict[str, Any]] = []
    for c in items:
        if c.c is None or c.d is None:
            diff = paired_difference(boots[c.a], boots[c.b])
        else:
            diff = paired_difference(
                difference_bootstrap(boots[c.a], boots[c.b]),
                difference_bootstrap(boots[c.c], boots[c.d]),
            )
        values = {t: boots[t].table.set_index("kpi")["value"] for t in c.terms}
        for row in diff.itertuples():
            kpi = str(row.kpi)
            if kpi not in CONTRAST_KPIS:
                continue
            rows.append(
                _row(c, kpi, beta, split, float(row.difference), values, hashes)
                | {"ci_low": float(row.ci_low), "ci_high": float(row.ci_high)}
            )
    return rows


def _row(
    c: Contrast,
    kpi: str,
    beta: float,
    split: str,
    value: float,
    values: dict[Design, pd.Series],
    hashes: dict[Design, str],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "split": split,
        "contrast": c.name,
        "joint_scope": c.joint_scope,
        "tail_design": c.tail_design,
        "base_design": c.base_design,
        "kpi": kpi,
        "eval_beta": beta,
        "value": value,
        "ci_low": math.nan,
        "ci_high": math.nan,
        "value_ref": float(values[c.reference][kpi]),
    }
    for name, t in zip("abcd", (c.a, c.b, c.c, c.d), strict=True):
        out[f"term_{name}"] = "" if t is None else f"{t[0]}/{t[1]}"
        out[f"value_{name}"] = math.nan if t is None else float(values[t][kpi])
        out[f"hash_{name}"] = "" if t is None else hashes[t]
    return out


def train_contrast_rows(
    values: dict[Design, pd.Series],
    hashes: dict[Design, str],
    items: Iterable[Contrast],
    *,
    beta: float,
) -> list[dict[str, Any]]:
    """In-sample contrasts: point values, no intervals.

    Parameters
    ----------
    values : dict
        Each design's train KPI values (index: KPI name) at ``beta``.
    hashes : dict
        Each design's config hash.
    items : iterable of Contrast
        The contrasts.
    beta : float
        KPI beta.

    Returns
    -------
    list of dict
        As :func:`contrast_rows`, with null intervals.
    """
    rows: list[dict[str, Any]] = []
    for c in items:
        for kpi in CONTRAST_KPIS:
            v = {t: float(values[t][kpi]) for t in c.terms}
            value = v[c.a] - v[c.b]
            if c.c is not None and c.d is not None:
                value -= v[c.c] - v[c.d]
            rows.append(_row(c, kpi, beta, "train", value, values, hashes))
    return rows


def _check_decomposition(frame: pd.DataFrame) -> int:
    """Raise unless both = rq1_alone + rq2_alone + interaction on every row."""
    key = [
        c
        for c in (
            "family",
            "eventset",
            "pricing",
            "kappa",
            "split",
            "kpi",
            "eval_beta",
        )
        if c in frame.columns
    ]
    n = 0
    f = frame.fillna({"eval_beta": -1.0})
    for idx, g in f.groupby(key, dropna=False):
        del idx
        val = g.set_index(["contrast", "joint_scope", "tail_design", "base_design"])[
            "value"
        ]
        for (name, j, w, o), total in val.items():
            if name != "both":
                continue
            parts = (
                val[("rq1_alone", "", w, o)]
                + val[("rq2_alone", j, "", o)]
                + val[("interaction", j, w, o)]
            )
            if not math.isclose(total, parts, rel_tol=1e-9, abs_tol=1e-4):
                raise RuntimeError(f"decomposition fails: {name} {j} {w} {o}")
            n += 1
    return n


# --------------------------------------------------------------------------
# Phase holdout
# --------------------------------------------------------------------------


def _budget_use(store: ResultStore, run_id: str, kappa: float) -> float:
    """Sum of the design problems' premiums / (kappa * train E[L])."""
    runs = store.read("runs", run_ids=[run_id])
    k = store.read("kpis", run_ids=[run_id])
    el = k.loc[
        (k["level"] == "portfolio")
        & (k["eval_split"] == "train")
        & (k["kpi"] == "expected_loss"),
        "value",
    ].unique()
    if len(el) != 1:
        raise RuntimeError(f"run {run_id}: {len(el)} train expected losses")
    return float(runs["premium"].sum()) / (kappa * float(el[0]))


def _grid_rows(table: pd.DataFrame, beta: float) -> pd.DataFrame:
    """Portfolio rows of the grid KPIs; beta-free KPIs once (at CONFIG_BETA)."""
    t = table.loc[
        (table["level"] == "portfolio") & table["kpi"].isin(GRID_KPIS),
        ["kpi", "value", "ci_low", "ci_high"],
    ].copy()
    tail = t["kpi"].isin(TAIL_KPIS)
    if beta != CONFIG_BETA:
        t = t.loc[tail]
        tail = t["kpi"].isin(TAIL_KPIS)
    t["eval_beta"] = np.where(tail, beta, np.nan)
    return t


def holdout_worker(
    family: str,
    eventset: str,
    pricing: str,
    kappa: float,
    members: dict[Design, tuple[ExperimentConfig, str]],
    store_root: str,
) -> tuple[dict[str, pd.DataFrame], float]:
    """Bootstrap one variant's 3 scopes x designs on one resample; contrast them.

    Parameters
    ----------
    family, eventset, pricing : str
        C1 variant labels, e.g. ``"main"``, ``"thesis"``, ``"coc_r0.06"``.
    kappa : float
        Budget loading.
    members : dict
        (scope, design) to (single-run config, run id) of the C1 runs.
    store_root : str
        The C1 result store.

    Returns
    -------
    frames : dict of pandas.DataFrame
        ``grid`` (train and test KPIs, budget use), ``contrasts`` (train and
        test) and ``runs``.
    seconds : float
        Wall time.
    """
    start = time.perf_counter()
    store = ResultStore(Path(store_root))
    cfg0 = members[(INDIVIDUAL, "mse")][0]
    prepared = c1._prepared(cfg0)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    assert cfg0.bootstrap is not None
    resample = resample_years(
        test.years, cfg0.bootstrap.n_bootstrap, cfg0.bootstrap.rng()
    )
    level = cfg0.bootstrap.level
    comps = cfg0.to_components()
    basis, price = comps.basis, comps.pricing

    boots: dict[float, dict[Design, KpiBootstrap]] = {b: {} for b in EVAL_BETAS}
    train_values: dict[float, dict[Design, pd.Series]] = {b: {} for b in EVAL_BETAS}
    hashes: dict[Design, str] = {}
    grid: list[pd.DataFrame] = []
    run_rows: list[dict[str, Any]] = []
    for (scope, design), (cfg, rid) in members.items():
        d = rq2._stored(cfg, rid, store)
        hashes[(scope, design)] = d.config_hash
        for beta in EVAL_BETAS:
            boot = bootstrap_kpis(
                prepared,
                d.scope,
                d.results,
                basis=basis,
                beta=beta,
                run_id=rid,
                resample=resample,
                sample=test,
                pricing=price,
                level=level,
            )
            pb = rq2.portfolio_rows(boot)
            boots[beta][(scope, design)] = pb
            tr = kpis(
                prepared,
                d.scope,
                d.results,
                basis=basis,
                beta=beta,
                run_id=rid,
                sample=train,
                pricing=price,
            )
            tr = tr.loc[tr["level"] == "portfolio"]
            train_values[beta][(scope, design)] = tr.set_index("kpi")["value"]
            for split, table in (("test", pb.table), ("train", tr)):
                g = _grid_rows(table, beta)
                g["split"] = split
                g["scope"], g["design"] = scope, design
                g["config_hash"] = d.config_hash
                grid.append(g)
        use = _budget_use(store, rid, kappa)
        grid.append(
            pd.DataFrame(
                [
                    {
                        "kpi": "budget_use",
                        "value": use,
                        "ci_low": math.nan,
                        "ci_high": math.nan,
                        "eval_beta": math.nan,
                        "split": "train",
                        "scope": scope,
                        "design": design,
                        "config_hash": d.config_hash,
                    }
                ]
            )
        )
        run_rows.append(
            {
                "kind": "holdout",
                "scope": scope,
                "design": design,
                "fold": math.nan,
                "n_problems": len(d.results),
                "statuses": d.statuses,
                "solvers": d.solvers,
                "budget_use": use,
                "config_hash": d.config_hash,
                "run_id": rid,
            }
        )

    items = contrasts(family)
    rows: list[dict[str, Any]] = []
    for beta in EVAL_BETAS:
        rows += contrast_rows(boots[beta], hashes, items, split="test", beta=beta)
        rows += train_contrast_rows(train_values[beta], hashes, items, beta=beta)
    frames = {
        "grid": pd.concat(grid, ignore_index=True),
        "contrasts": pd.DataFrame(rows),
        "runs": pd.DataFrame(run_rows),
    }
    for frame in frames.values():
        frame.insert(0, "kappa", kappa)
        frame.insert(0, "pricing", pricing)
        frame.insert(0, "eventset", eventset)
        frame.insert(0, "family", family)
    return frames, time.perf_counter() - start


def holdout_groups(
    family: str,
) -> dict[tuple[str, str, str, float], dict[Design, tuple[ExperimentConfig, str]]]:
    """Return the C1 runs of a family, grouped by variant.

    Parameters
    ----------
    family : str
        ``"main"`` or ``"f12"``.

    Returns
    -------
    dict
        (family, eventset, pricing, kappa) to {(scope, design): (config,
        run id)}.
    """
    specs, checksums = c1.plan([family])
    sums = {"thesis": str(load_config(c1.BASE_CONFIG).eventset.checksum), **checksums}
    groups: dict[
        tuple[str, str, str, float], dict[Design, tuple[ExperimentConfig, str]]
    ] = {}
    for s in specs:
        v = s.variant
        if s.design not in DESIGNS[family]:
            continue
        rid = run_key(config_hash(s.config), sums[v.eventset], policy=DEFAULT_POLICY)
        key = (v.family, v.eventset, v.pricing, v.kappa)
        groups.setdefault(key, {})[(s.scope, s.design)] = (s.config, rid)
    return groups


def run_holdout(args: argparse.Namespace, family: str) -> dict[str, Any]:
    """Phase holdout of one family; writes ``holdout_<family>_*.csv``.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.
    family : str
        ``"main"`` or ``"f12"``.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    groups = holdout_groups(family)
    store = ResultStore(args.c1_store)
    for members in groups.values():
        for _, rid in members.values():
            if not store.has_run(rid):
                raise RuntimeError(
                    f"C1 run {rid} is not in {args.c1_store}: run c1_checkpoint.py"
                )
    frames: dict[str, list[pd.DataFrame]] = {}
    seconds: dict[str, float] = {}
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {
            pool.submit(holdout_worker, *key, m, str(args.c1_store)): key
            for key, m in groups.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            out, sec = fut.result()
            for name, frame in out.items():
                frames.setdefault(name, []).append(frame)
            label = "|".join(f"{x:g}" if isinstance(x, float) else x for x in futs[fut])
            seconds[label] = round(sec, 1)
            print(f"[holdout {i}/{len(futs)}] {label} {sec:.0f}s", flush=True)
    tables = {n: pd.concat(f, ignore_index=True) for n, f in frames.items()}
    n_kpis = _check_kpis_against_c1(tables["grid"], family)
    n_pairs = _check_contrasts_against_c1(tables["contrasts"], family)
    n_use = _check_budget_use(tables["runs"])
    n_dec = _check_decomposition(tables["contrasts"])
    print(
        f"{family}: checked {n_kpis} KPI rows, {n_pairs} contrast rows, "
        f"{n_use} budget uses against C1/MAR-158; {n_dec} decompositions",
        flush=True,
    )
    args.full.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(
            args.full / f"holdout_{family}_{name}.csv",
            index=False,
            float_format="%.10g",
        )
    return {
        "holdout_groups": len(groups),
        "holdout_designs": int(sum(len(m) for m in groups.values())),
        "checked_kpi_rows_against_c1": n_kpis,
        "checked_contrast_rows_against_c1_and_mar158": n_pairs,
        "checked_budget_uses_against_c1": n_use,
        "checked_decompositions": n_dec,
        "holdout_seconds": round(time.perf_counter() - t0, 1),
        "holdout_seconds_per_group": seconds,
    }


def _close(a: pd.Series, b: pd.Series, where: str) -> None:
    """Raise unless two columns agree to the 7 significant digits of the CSVs."""
    x = a.to_numpy(dtype=np.float64)
    y = b.to_numpy(dtype=np.float64)
    tol = 1e-6 * np.maximum(np.abs(x), np.abs(y)) + 1e-3
    bad = ~((np.abs(x - y) <= tol) | (np.isnan(x) & np.isnan(y)))
    if bad.any():
        i = int(np.flatnonzero(bad)[0])
        raise RuntimeError(f"{where}: {x[i]!r} vs C1 {y[i]!r} (row {i})")


def _check_kpis_against_c1(grid: pd.DataFrame, family: str) -> int:
    """Raise unless the test KPIs and intervals equal C1's committed ones."""
    c1k = pd.read_csv(C1_DATA / f"kpis_{family}.csv")
    c1k = c1k.loc[(c1k["source"] == "c1_bootstrap") & (c1k["eval_split"] == "test")]
    mine = grid.loc[(grid["split"] == "test") & (grid["kpi"] != "budget_use")].copy()
    key = ["eventset", "pricing", "kappa", "scope", "design", "kpi"]
    tail = mine["kpi"].isin(TAIL_KPIS)
    out = 0
    for part, theirs, k in (
        (mine.loc[tail], c1k.loc[c1k["kpi"].isin(TAIL_KPIS)], [*key, "eval_beta"]),
        (
            mine.loc[~tail],
            c1k.loc[~c1k["kpi"].isin(TAIL_KPIS)].drop_duplicates(key),
            key,
        ),
    ):
        merged = part.merge(
            theirs[[*k, "value", "ci_low", "ci_high"]],
            on=k,
            suffixes=("", "_c1"),
            validate="one_to_one",
        )
        if len(merged) != len(part):
            raise RuntimeError(f"{len(part) - len(merged)} KPI rows not in C1")
        for column in ("value", "ci_low", "ci_high"):
            _close(merged[column], merged[f"{column}_c1"], f"{family} {column}")
        out += len(merged)
    return out


def _check_contrasts_against_c1(con: pd.DataFrame, family: str) -> int:
    """Raise unless the two-term contrasts C1 or MAR-158 reported equal theirs."""
    test = con.loc[(con["split"] == "test") & con["term_c"].eq("")].copy()
    test[["scope_a", "design_a"]] = test["term_a"].str.split("/", expand=True)
    test[["scope_b", "design_b"]] = test["term_b"].str.split("/", expand=True)
    test = test.drop_duplicates(
        ["eventset", "pricing", "kappa", "term_a", "term_b", "kpi", "eval_beta"]
    )
    tail = test["kpi"].isin(TAIL_KPIS)
    out = 0
    # within a scope, across designs: C1's paired_<family>.csv
    c1p = pd.read_csv(C1_DATA / f"paired_{family}.csv")
    c1p = c1p.loc[c1p["eval_split"] == "test"]
    same = test.loc[test["scope_a"] == test["scope_b"]].copy()
    same["scope"] = same["scope_a"]
    key = ["eventset", "pricing", "kappa", "scope", "design_a", "design_b", "kpi"]
    out += _merge_check(same, c1p, key, tail.loc[same.index], f"{family} C1 paired")
    # within a design, across scopes: MAR-158's scope_paired*.csv
    name = "scope_paired.csv" if family == "main" else "scope_paired_f12.csv"
    sp = pd.read_csv(RQ2_DATA / name)
    sp = sp.loc[sp["split"] == "test"]
    if "eventset" not in sp.columns:
        sp["eventset"] = "thesis"
    cross = test.loc[test["design_a"] == test["design_b"]].copy()
    cross["design"] = cross["design_a"]
    key = ["eventset", "pricing", "kappa", "design", "scope_a", "scope_b", "kpi"]
    out += _merge_check(cross, sp, key, tail.loc[cross.index], f"{family} MAR-158")
    return out


def _merge_check(
    mine: pd.DataFrame,
    theirs: pd.DataFrame,
    key: list[str],
    tail: pd.Series,
    where: str,
) -> int:
    n = 0
    for is_tail in (True, False):
        part = mine.loc[tail == is_tail]
        if part.empty:
            continue
        th = theirs.loc[theirs["kpi"].isin(TAIL_KPIS) == is_tail]
        k = [*key, "eval_beta"] if is_tail else key
        if not is_tail:
            th = th.drop_duplicates(key)
            part = part.drop_duplicates(key)
        merged = part.merge(
            th[[*k, "difference", "ci_low", "ci_high"]],
            on=k,
            suffixes=("", "_c1"),
            validate="one_to_one",
        )
        if len(merged) != len(part):
            raise RuntimeError(f"{where}: {len(part) - len(merged)} rows unmatched")
        _close(merged["value"], merged["difference"], f"{where} difference")
        for column in ("ci_low", "ci_high"):
            _close(merged[column], merged[f"{column}_c1"], f"{where} {column}")
        n += len(merged)
    return n


def _check_budget_use(runs: pd.DataFrame) -> int:
    c1r = pd.read_csv(C1_DATA / "runs.csv")
    merged = runs.merge(
        c1r[["config_hash", "budget_use"]],
        on="config_hash",
        suffixes=("", "_c1"),
        validate="one_to_one",
    )
    if len(merged) != len(runs):
        raise RuntimeError("runs without a C1 budget use")
    _close(merged["budget_use"], merged["budget_use_c1"], "budget use")
    return len(merged)


# --------------------------------------------------------------------------
# Phase kfold
# --------------------------------------------------------------------------


def _pooled_bootstrap(
    reps: dict[KpiName, np.ndarray],
    point: dict[KpiName, np.ndarray],
    beta: float,
    resample: YearResample,
    level: float,
    run_id: str,
) -> KpiBootstrap:
    """Wrap a pooled design's replicates as a portfolio-level KpiBootstrap."""
    names = list(reps)
    table = pd.DataFrame(
        {
            "problem_id": ALL_PROBLEMS,
            "eval_split": "pooled",
            "fold": POOLED_FOLD,
            "basis": Basis.ANNUAL.value,
            "level": "portfolio",
            "subject_id": "portfolio",
            "kpi": [k.value for k in names],
            "beta": [beta if k.value in TAIL_KPIS else math.nan for k in names],
            "run_id": run_id,
            "value": [float(point[k][0]) for k in names],
        }
    )
    replicates = np.vstack([reps[k] for k in names])
    bounds = np.array([percentile_interval(r, level) for r in replicates])
    table["ci_low"] = bounds[:, 0]
    table["ci_high"] = bounds[:, 1]
    return KpiBootstrap(
        table=table, replicates=replicates, resample=resample, level=level
    )


def run_kfold(args: argparse.Namespace) -> dict[str, Any]:
    """Phase kfold: pooled 5-fold KPIs and contrasts of the MAR-158 runs.

    Parameters
    ----------
    args : argparse.Namespace
        Command-line arguments.

    Returns
    -------
    dict
        Summary entries.
    """
    t0 = time.perf_counter()
    configs = rq2.kfold_configs()
    checksum = str(load_config(c1.BASE_CONFIG).eventset.checksum)
    store = ResultStore(args.kfold_store)
    first = next(iter(configs.values()))
    prepared = c1._prepared(first)
    measure = outcome_measure(prepared, Basis.ANNUAL, years=Sample.full(prepared).years)
    row_years = prepared.events["year"].to_numpy(dtype=np.int64)
    resample_ref: YearResample | None = None
    grid: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    n_checked = 0
    for pricing in rq2.KFOLD_PRICINGS:
        boots: dict[float, dict[Design, KpiBootstrap]] = {b: {} for b in EVAL_BETAS}
        hashes: dict[Design, str] = {}
        native: list[tuple[kfold.PooledKpis, dict[Design, tuple[int, str]]]] = []
        for (p, _), cfg in configs.items():
            if p != pricing:
                continue
            exp_hash = config_hash(cfg)
            run_ids = []
            for s in cfg.single_runs():
                rid = run_key(config_hash(s), checksum, policy=DEFAULT_POLICY)
                if not store.has_run(rid):
                    raise RuntimeError(f"k-fold run {rid} missing: run c1_rq2.py")
                run_ids.append(rid)
                obj = s.objectives[0].model_dump(mode="json")
                design = rq2.OBJECTIVE_DESIGN[(obj["kind"], obj.get("beta"))]
                scope = s.scopes[0].kind
                runs = store.read("runs", run_ids=[rid])
                run_rows.append(
                    {
                        "kind": "kfold",
                        "family": "main",
                        "eventset": "thesis",
                        "pricing": pricing,
                        "kappa": 1.0,
                        "scope": scope,
                        "design": design,
                        "fold": getattr(s.sample, "fold", None),
                        "n_problems": len(runs),
                        "statuses": ",".join(sorted(set(runs["status"].astype(str)))),
                        "solvers": ",".join(sorted(set(runs["solver"].astype(str)))),
                        "budget_use": _budget_use(store, rid, 1.0),
                        "config_hash": config_hash(s),
                        "run_id": rid,
                        "experiment_config_hash": exp_hash,
                    }
                )
            pooled = kfold.pooled_kpis(cfg, store, prepared, run_ids)
            if pooled.failed or pooled.resample is None or pooled.level is None:
                raise RuntimeError(f"k-fold {pricing}: not pooled {pooled.failed}")
            if resample_ref is None:
                resample_ref = pooled.resample
            elif not resample_ref.same_as(pooled.resample):
                raise RuntimeError("the k-fold configs drew different resamples")
            designs, _ = kfold.pooled_designs(cfg, store, prepared, run_ids)
            ones = rq2._identity(pooled.resample)
            positions: dict[Design, tuple[int, str]] = {}
            for d in designs:
                key = (d.scope, rq2._design_of(d.objective, cfg))
                positions[key] = (d.scope_position, d.objective)
                hashes[key] = exp_hash
                for beta in EVAL_BETAS:
                    reps = kpi_replicates(
                        d.loss, d.payout, measure, row_years, pooled.resample, beta=beta
                    )
                    point = kpi_replicates(
                        d.loss, d.payout, measure, row_years, ones, beta=beta
                    )
                    boots[beta][key] = _pooled_bootstrap(
                        reps, point, beta, pooled.resample, pooled.level, exp_hash
                    )
            native.append((pooled, positions))
        # grid rows: pooled KPIs (and the pooled_kpis cross-check at 0.99)
        for beta, by_design in boots.items():
            for (scope, design), b in by_design.items():
                for r in _grid_rows(b.table, beta).itertuples():
                    grid.append(
                        {
                            "family": "main",
                            "eventset": "thesis",
                            "pricing": pricing,
                            "kappa": 1.0,
                            "kpi": r.kpi,
                            "value": r.value,
                            "ci_low": r.ci_low,
                            "ci_high": r.ci_high,
                            "eval_beta": r.eval_beta,
                            "split": "pooled",
                            "scope": scope,
                            "design": design,
                            "config_hash": hashes[(scope, design)],
                        }
                    )
        for beta in EVAL_BETAS:
            new = contrast_rows(
                boots[beta], hashes, contrasts("main"), split="pooled", beta=beta
            )
            for r in new:
                r.update(family="main", eventset="thesis", pricing=pricing, kappa=1.0)
            rows += new
        n_checked += _check_native(rows, native, pricing)
    con = pd.DataFrame(rows)
    n_dec = _check_decomposition(con)
    n_rq2 = _check_pooled_against_rq2(con)
    args.full.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(grid).to_csv(
        args.full / "kfold_grid.csv", index=False, float_format="%.10g"
    )
    con.to_csv(args.full / "kfold_contrasts.csv", index=False, float_format="%.10g")
    pd.DataFrame(run_rows).to_csv(args.full / "kfold_runs.csv", index=False)
    print(
        f"kfold: checked {n_checked} rows against pooled_difference, {n_rq2} "
        f"against MAR-158; {n_dec} decompositions",
        flush=True,
    )
    return {
        "kfold_experiment_config_hashes": {
            f"{p}|{o}": config_hash(c) for (p, o), c in configs.items()
        },
        "kfold_runs": len(run_rows),
        "checked_against_pooled_difference": n_checked,
        "checked_pooled_against_mar158": n_rq2,
        "checked_decompositions": n_dec,
        "kfold_seconds": round(time.perf_counter() - t0, 1),
    }


def _check_native(
    rows: list[dict[str, Any]],
    native: list[tuple[kfold.PooledKpis, dict[Design, tuple[int, str]]]],
    pricing: str,
) -> int:
    """Two-term pooled contrasts at 0.99 against ``kfold.pooled_difference``."""
    n = 0
    for r in rows:
        if r["pricing"] != pricing or r["term_c"] or r["eval_beta"] != CONFIG_BETA:
            continue
        a = tuple(r["term_a"].split("/"))
        b = tuple(r["term_b"].split("/"))
        for pooled, positions in native:
            if a not in positions or b not in positions:
                continue
            diff = kfold.pooled_difference(pooled, positions[a], positions[b])
            got = diff.set_index("kpi").loc[r["kpi"]]
            for mine, theirs in (
                (r["value"], got["difference"]),
                (r["ci_low"], got["ci_low"]),
                (r["ci_high"], got["ci_high"]),
            ):
                if not math.isclose(mine, float(theirs), rel_tol=1e-9, abs_tol=1e-6):
                    raise RuntimeError(
                        f"pooled contrast {a} - {b} {r['kpi']}: {mine} vs {theirs}"
                    )
            n += 1
    return n


def _check_pooled_against_rq2(con: pd.DataFrame) -> int:
    sp = pd.read_csv(RQ2_DATA / "scope_paired.csv")
    sp = sp.loc[sp["split"] == "pooled"]
    pooled = con.loc[con["term_c"].eq("")].copy()
    pooled[["scope_a", "design_a"]] = pooled["term_a"].str.split("/", expand=True)
    pooled[["scope_b", "design_b"]] = pooled["term_b"].str.split("/", expand=True)
    pooled = pooled.loc[pooled["design_a"] == pooled["design_b"]].copy()
    pooled["design"] = pooled["design_a"]
    pooled["eventset"] = "thesis"
    sp = sp.assign(eventset="thesis")
    pooled = pooled.drop_duplicates(
        ["pricing", "design", "scope_a", "scope_b", "kpi", "eval_beta"]
    )
    tail = pooled["kpi"].isin(TAIL_KPIS)
    key = ["eventset", "pricing", "kappa", "design", "scope_a", "scope_b", "kpi"]
    # MAR-158 reported the pooled CVaR at every beta, the rest at 0.99
    sp_tail = sp.loc[sp["kpi"].isin(TAIL_KPIS)]
    mine_tail = pooled.loc[tail]
    n = _merge_check(mine_tail, sp_tail, key, tail.loc[mine_tail.index], "pooled")
    return n


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Run the requested phases.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Exit status.
    """
    parser = argparse.ArgumentParser(description="C1 combination view (MAR-182).")
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument(
        "--phases",
        nargs="+",
        default=["holdout", "kfold"],
        choices=["holdout", "kfold"],
    )
    parser.add_argument(
        "--families", nargs="+", default=["main", "f12"], choices=["main", "f12"]
    )
    parser.add_argument("--c1-store", type=Path, default=c1.STORE)
    parser.add_argument("--kfold-store", type=Path, default=rq2.KFOLD_STORE)
    parser.add_argument("--full", type=Path, default=FULL_DIR)
    args = parser.parse_args(argv)
    common: dict[str, Any] = {
        "issue": "MAR-182",
        "base_config": str(c1.BASE_CONFIG.relative_to(REPO_ROOT)),
        "designs": {k: list(v) for k, v in DESIGNS.items()},
        "eval_betas": list(EVAL_BETAS),
        "package_versions": package_versions(),
    }
    args.full.mkdir(parents=True, exist_ok=True)
    parts: list[tuple[str, Any]] = []
    if "holdout" in args.phases:
        parts += [
            (f"holdout_{f}", lambda f=f: run_holdout(args, f)) for f in args.families
        ]
    if "kfold" in args.phases:
        parts.append(("kfold", lambda: run_kfold(args)))
    for name, run in parts:
        summary = {**common, **run()}
        (args.full / f"summary_{name}.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
    print(f"wrote {args.full}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
