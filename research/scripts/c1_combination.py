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

**Pairing across scopes** (MAR-179, MAR-212; C1.md section 6b.1): every
design's bootstrap is cut to its portfolio-level rows
(``KpiBootstrap.portfolio_rows``), and every contrast is
``paired_difference(..., across_scopes=True)``. It pairs on
``PORTFOLIO_PAIR_KEY``, ``PAIR_KEY`` without ``problem_id`` (``"*"`` for a
run with several design problems, here the individual scope; the problem's
id for a run with one, here ``"portfolio"`` for the C1 cluster and portfolio
scopes), with the same resample check. MAR-182 relabelled ``problem_id`` to a
common value instead (a ``c1_rq2.portfolio_rows`` helper, removed in
MAR-228); the two give the same contrasts bit for bit (MAR-212). The
interaction is ``paired_difference`` of two difference bootstraps
(:func:`difference_bootstrap`: point values and replicates of two designs of
one scope subtracted row by row, after the same check). The k-fold contrasts
use ``kpi_replicates`` of ``kfold.pooled_designs`` on the one shared
resample, and are checked against ``kfold.pooled_difference`` wherever both
designs are in one k-fold config.

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

**Addendum (MAR-194).** Three more phases, on the same thesis portfolio:

``kfold_addendum`` (item 1)
    Solves the pooled 5-fold runs at kappa 0.5 (pure and r 0.06) and at
    r 0.10 (kappa 1): MAR-158's k-fold configs with another pricing or budget
    loading, written to ``research/configs/c1-combination/`` by
    ``--write-configs`` and checked to hash as derived. 180 runs into
    ``results/c1-combination/kfold-store`` (not committed), with the
    installed core version; then the pooled contrasts as phase ``kfold``.

``sites`` (item 2)
    Per-site KPIs of the **individual** designs: each site's own annual
    uncovered loss (its loss minus its own design's payout), train and
    holdout test for every main-line variant, pooled 5-fold for every k-fold
    variant; and per site weighted CVaR minus MSE / E[U], with paired
    intervals. Each site is its own design problem, so these KPIs are
    defined (unlike a joint design's per-asset split, MAR-100). Reads phase
    ``holdout``'s grid (the sites' expected values must add up to it).

``alt`` (item 3)
    The kappa-1 contrasts (pure and r 0.06) with the joint designs replaced
    by their second optimum ``alt`` (``c1_rq2.ALT_POLICY``): the thetas that
    MAR-206 family (e) stored (``result_joint_*.json``); nothing is
    re-solved. Every combination of C1 / ``alt`` for the joint tail and
    baseline designs. Checked against family (e)'s, family (b)'s and C1
    observation 32's test KPIs of the same designs.

The C1 and MAR-158 runs were solved with core ``0.1.0.dev0``, and the core
version is part of a run id (MAR-188): ``--c1-package-version`` (default
``0.1.0.dev0``) finds them under a later core. Run after the phases above::

    uv run python research/scripts/c1_combination.py \
        --phases kfold_addendum sites alt --jobs 2
    uv run python research/scripts/c1_combination_tables.py --parts addendum

Observations only. The interpretation is the owner's.
"""

from __future__ import annotations

import argparse
import dataclasses
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
    dump_config,
    load_config,
    parse_config,
)
from parametric_insurance_design.experiment.runner import package_versions, run_key
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import EventSet, Sample
from parametric_insurance_design.records import KpiName
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
C1_PACKAGE_VERSION: Final[str] = "0.1.0.dev0"
"""Core version of the C1 and MAR-158 runs; part of their run ids (MAR-188)."""
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
        Two designs' bootstraps with the same subjects and resample: two
        designs of one scope, as in every interaction (``(J, W) - (J, O)``,
        ``(I, W) - (I, O)``). ``PAIR_KEY`` includes ``problem_id``, so an
        individual design (``"*"``) and a joint one (``"portfolio"``) don't
        pair and raise ``BootstrapError``.

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
        Each design's portfolio-level bootstrap at ``beta``
        (``KpiBootstrap.portfolio_rows``), all on one resample.
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
            diff = paired_difference(boots[c.a], boots[c.b], across_scopes=True)
        else:
            diff = paired_difference(
                difference_bootstrap(boots[c.a], boots[c.b]),
                difference_bootstrap(boots[c.c], boots[c.d]),
                across_scopes=True,
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
            pb = boot.portfolio_rows()
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
    package_version: str = C1_PACKAGE_VERSION,
) -> dict[tuple[str, str, str, float], dict[Design, tuple[ExperimentConfig, str]]]:
    """Return the C1 runs of a family, grouped by variant.

    Parameters
    ----------
    family : str
        ``"main"`` or ``"f12"``.
    package_version : str, optional
        The core package version the C1 runs were solved with; it is part of
        their run ids (``runner.run_key``). Default: C1's, ``0.1.0.dev0``.

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
        rid = run_key(
            config_hash(s.config),
            sums[v.eventset],
            package_version=package_version,
            policy=DEFAULT_POLICY,
        )
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
    groups = holdout_groups(family, args.c1_package_version)
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
    problem_id: str,
) -> KpiBootstrap:
    """Wrap a pooled design's replicates as a portfolio-level KpiBootstrap.

    ``problem_id`` is the folds' own (``PooledDesign.problem_id``: ``"*"``
    for the individual scope, ``"portfolio"`` for the joint scopes), as in a
    holdout run's rows (MAR-228).
    """
    names = list(reps)
    table = pd.DataFrame(
        {
            "problem_id": problem_id,
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


@dataclass
class PooledVariant:
    """The pooled 5-fold designs of one (pricing, kappa) variant.

    Attributes
    ----------
    boots : dict
        KPI beta to {(scope, design): portfolio-level pooled bootstrap}, all
        on one resample of the 10,000 years.
    hashes : dict
        (scope, design) to the k-fold experiment config hash.
    native : list
        ``(PooledKpis, positions)`` per k-fold config, for
        ``kfold.pooled_difference``.
    grid : list of dict
        Pooled portfolio KPI rows.
    runs : list of dict
        One row per fold run.
    sites : dict
        (design, site) to (site loss, pooled site payout) per row of the
        prepared EventSet: the individual scope's designs per site. Empty
        unless requested.
    resample : YearResample
        The shared resample.
    """

    boots: dict[float, dict[Design, KpiBootstrap]]
    hashes: dict[Design, str]
    native: list[tuple[kfold.PooledKpis, dict[Design, tuple[int, str]]]]
    grid: list[dict[str, Any]]
    runs: list[dict[str, Any]]
    sites: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]]
    resample: YearResample


def _site_pooled(
    cfg: ExperimentConfig,
    single: list[tuple[ExperimentConfig, str]],
    store: ResultStore,
    prepared: EventSet,
    portfolio_payout: np.ndarray,
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Per-site pooled loss and payout of one individual-scope k-fold design.

    Every row is paid by the fold design that did not see its year block,
    site by site, as ``kfold.pooled_designs`` does for the portfolio. The
    sites' payouts must add up to the pooled portfolio payout (checked).

    Parameters
    ----------
    cfg : ExperimentConfig
        The k-fold experiment config.
    single : list
        The design's fold runs, (single-run config, run id), fold 0 .. k-1.
    store : ResultStore
        The store holding them.
    prepared : EventSet
        The prepared EventSet.
    portfolio_payout : numpy.ndarray
        ``PooledDesign.payout`` of the same design.

    Returns
    -------
    dict
        Site id to (loss, pooled payout) per row of ``prepared``.

    Raises
    ------
    RuntimeError
        If a run is not the expected fold, a row has no fold design, or the
        sites' payouts do not add up to the portfolio's.
    """
    comps = cfg.to_components()
    samples = splits.year_block_kfold(prepared, k=len(single))
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for f, (s, rid) in enumerate(single):
        if getattr(s.sample, "fold", None) != f:
            raise RuntimeError(f"run {rid}: sample {s.sample!r}, expected fold {f}")
        test = samples[f][1]
        data = test.select(prepared)
        results = c1.rebuild(
            s,
            store.read("runs", run_ids=[rid]),
            store.read("payouts", run_ids=[rid]),
            store.read("entities", run_ids=[rid]),
        )
        scope = s.to_components().scopes[0]
        for r in results:
            (site,) = r.spec.location_ids
            problem = scope.materialise(data, r.spec)
            pay = comps.payout.evaluate(problem.index, r.theta)[:, 0]
            if site not in out:
                out[site] = (
                    np.full(prepared.n_rows, np.nan),
                    np.full(prepared.n_rows, np.nan),
                )
            out[site][0][test.rows] = problem.loss
            out[site][1][test.rows] = pay
    for site, (loss, pay) in out.items():
        if np.isnan(loss).any() or np.isnan(pay).any():
            raise RuntimeError(f"site {site}: rows without a fold design")
    total = np.vstack([p for _, p in out.values()]).sum(axis=0)
    if not np.allclose(total, portfolio_payout, rtol=1e-12, atol=1e-6):
        raise RuntimeError("the sites' pooled payouts do not add up")
    return out


def pooled_variant(
    pricing: str,
    kappa: float,
    configs: dict[str, ExperimentConfig],
    store: ResultStore,
    package_version: str | None,
    prepared: EventSet,
    *,
    sites: bool = False,
) -> PooledVariant:
    """Pooled 5-fold bootstraps of one variant's 12 designs (3 scopes x 4).

    Parameters
    ----------
    pricing : str
        C1 pricing label.
    kappa : float
        Budget loading.
    configs : dict
        Objective set (``"a"``: MSE, E[U], wCVaR beta 0.99; ``"b"``: wCVaR
        beta 0.995) to its k-fold experiment config.
    store : ResultStore
        The store holding the fold runs.
    package_version : str or None
        Core version of the runs (part of their run ids); None: installed.
    prepared : EventSet
        The prepared thesis EventSet.
    sites : bool, optional
        Also return the individual designs' per-site pooled payouts.

    Returns
    -------
    PooledVariant
        Bootstraps, hashes, grid rows and run rows.

    Raises
    ------
    RuntimeError
        If a run is missing, a design is not pooled, or the configs drew
        different resamples.
    """
    checksum = str(load_config(c1.BASE_CONFIG).eventset.checksum)
    measure = outcome_measure(prepared, Basis.ANNUAL, years=Sample.full(prepared).years)
    row_years = prepared.events["year"].to_numpy(dtype=np.int64)
    resample_ref: YearResample | None = None
    boots: dict[float, dict[Design, KpiBootstrap]] = {b: {} for b in EVAL_BETAS}
    hashes: dict[Design, str] = {}
    native: list[tuple[kfold.PooledKpis, dict[Design, tuple[int, str]]]] = []
    run_rows: list[dict[str, Any]] = []
    site_rows: dict[tuple[str, str], tuple[np.ndarray, np.ndarray]] = {}
    for cfg in configs.values():
        exp_hash = config_hash(cfg)
        single: list[tuple[ExperimentConfig, str]] = []
        for s in cfg.single_runs():
            rid = run_key(
                config_hash(s),
                checksum,
                package_version=package_version,
                policy=DEFAULT_POLICY,
            )
            if not store.has_run(rid):
                raise RuntimeError(f"k-fold run {rid} missing from {store.root}")
            single.append((s, rid))
            obj = s.objectives[0].model_dump(mode="json")
            design = rq2.OBJECTIVE_DESIGN[(obj["kind"], obj.get("beta"))]
            runs = store.read("runs", run_ids=[rid])
            run_rows.append(
                {
                    "kind": "kfold",
                    "family": "main",
                    "eventset": "thesis",
                    "pricing": pricing,
                    "kappa": kappa,
                    "scope": s.scopes[0].kind,
                    "design": design,
                    "fold": getattr(s.sample, "fold", None),
                    "n_problems": len(runs),
                    "statuses": ",".join(sorted(set(runs["status"].astype(str)))),
                    "solvers": ",".join(sorted(set(runs["solver"].astype(str)))),
                    "budget_use": _budget_use(store, rid, kappa),
                    "config_hash": config_hash(s),
                    "run_id": rid,
                    "experiment_config_hash": exp_hash,
                    "package_version": str(runs["package_version"].iloc[0]),
                }
            )
        run_ids = [rid for _, rid in single]
        pooled = kfold.pooled_kpis(cfg, store, prepared, run_ids)
        if pooled.failed or pooled.resample is None or pooled.level is None:
            raise RuntimeError(f"k-fold {pricing} k{kappa}: not pooled {pooled.failed}")
        if resample_ref is None:
            resample_ref = pooled.resample
        elif not resample_ref.same_as(pooled.resample):
            raise RuntimeError("the k-fold configs drew different resamples")
        designs, _ = kfold.pooled_designs(cfg, store, prepared, run_ids)
        ones = rq2._identity(pooled.resample)
        positions: dict[Design, tuple[int, str]] = {}
        n_obj = len(cfg.objectives)
        k = len(single) // (len(cfg.scopes) * n_obj)
        names = [o.name for o in cfg.to_components().objectives]
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
                    reps,
                    point,
                    beta,
                    pooled.resample,
                    pooled.level,
                    exp_hash,
                    d.problem_id,
                )
            if sites and d.scope == INDIVIDUAL:
                start = (d.scope_position * n_obj + names.index(d.objective)) * k
                per_site = _site_pooled(
                    cfg, single[start : start + k], store, prepared, d.payout
                )
                for site, arrays in per_site.items():
                    site_rows[(key[1], site)] = arrays
        native.append((pooled, positions))
    if resample_ref is None:
        raise RuntimeError(f"k-fold {pricing} k{kappa}: no configs")
    grid: list[dict[str, Any]] = []
    for beta, by_design in boots.items():
        for (scope, design), b in by_design.items():
            for r in _grid_rows(b.table, beta).itertuples():
                grid.append(
                    {
                        "family": "main",
                        "eventset": "thesis",
                        "pricing": pricing,
                        "kappa": kappa,
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
    return PooledVariant(
        boots=boots,
        hashes=hashes,
        native=native,
        grid=grid,
        runs=run_rows,
        sites=site_rows,
        resample=resample_ref,
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
    store = ResultStore(args.kfold_store)
    prepared = c1._prepared(next(iter(configs.values())))
    resample_ref: YearResample | None = None
    grid: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    n_checked = 0
    for pricing in rq2.KFOLD_PRICINGS:
        variant = pooled_variant(
            pricing,
            1.0,
            {o: c for (p, o), c in configs.items() if p == pricing},
            store,
            args.c1_package_version,
            prepared,
        )
        if resample_ref is None:
            resample_ref = variant.resample
        elif not resample_ref.same_as(variant.resample):
            raise RuntimeError("the k-fold configs drew different resamples")
        grid += variant.grid
        run_rows += [
            {k: v for k, v in r.items() if k != "package_version"} for r in variant.runs
        ]
        for beta in EVAL_BETAS:
            new = contrast_rows(
                variant.boots[beta],
                variant.hashes,
                contrasts("main"),
                split="pooled",
                beta=beta,
            )
            for r in new:
                r.update(family="main", eventset="thesis", pricing=pricing, kappa=1.0)
            rows += new
        n_checked += _check_native(rows, variant.native, pricing)
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
# Addendum (MAR-194): k-fold at kappa 0.5 and r 0.10, per-site KPIs of the
# individual designs, and the second optima of the joint designs
# --------------------------------------------------------------------------

KFOLD_ADDENDUM: Final[tuple[tuple[str, float], ...]] = (
    ("pure", 0.5),
    ("coc_r0.06", 0.5),
    ("coc_r0.10", 1.0),
)
"""The (pricing, kappa) variants of the new pooled 5-fold runs (MAR-194 item 1)."""
CONFIG_DIR: Final[Path] = REPO_ROOT / "research" / "configs" / "c1-combination"
ADDENDUM_STORE: Final[Path] = REPO_ROOT / "results" / "c1-combination" / "kfold-store"
FAMILY_E_DIR: Final[Path] = (
    REPO_ROOT / "results" / "c1-rq2-sensitivities" / "full" / "joint"
)
"""MAR-206 family (e)'s per-design results (``result_joint_*.json``: the C1
and ``alt`` thetas of the 16 joint designs at kappa 1, pure and r 0.06)."""
NONUNIQUE_KPIS: Final[Path] = (
    REPO_ROOT / "results" / "c1-rq2-sensitivities" / "full" / "nonunique_kpis.csv"
)
"""MAR-206 family (b)'s test KPIs of every C1 joint design and its ``alt``."""
ALT_PRICINGS: Final[tuple[str, ...]] = ("pure", "coc_r0.06")
"""Pricings whose ``alt`` thetas are stored (MAR-206 family (e), kappa 1)."""
VERSIONS: Final[tuple[tuple[str, str], ...]] = (
    ("c1", "c1"),
    ("alt", "alt"),
    ("c1", "alt"),
    ("alt", "c1"),
)
"""(tail-design version, base-design version) of the joint designs."""
SITE_KPIS: Final[tuple[str, ...]] = (
    "expected_loss",
    "expected_payout",
    "expected_uncovered",
    "cvar_uncovered",
)
SITE_CONTRAST_KPIS: Final[tuple[str, ...]] = (
    "expected_payout",
    "expected_uncovered",
    "cvar_uncovered",
)
_RELATIVE_PATHS: Final[dict[str, str]] = {
    "eventset": "../../../parity/tests/data/thesis_eventset",
    "output": "../../../results/c1-combination/kfold-store",
}


def kfold_addendum_configs(pricing: str, kappa: float) -> dict[str, ExperimentConfig]:
    """Return one variant's k-fold experiment configs, keyed by objective set.

    The MAR-158 k-fold configs (``c1_rq2.kfold_configs``) with another
    pricing and budget loading: the C1 main line on a year-block 5-fold
    split, three scopes, objective set ``"a"`` (MSE, E[U], weighted CVaR
    beta 0.99) and ``"b"`` (weighted CVaR beta 0.995). At (pure, 1) they
    hash as MAR-158's (checked by :func:`load_kfold_addendum`).

    Parameters
    ----------
    pricing : str
        C1 pricing label (``c1_checkpoint.PRICINGS``).
    kappa : float
        Budget loading.

    Returns
    -------
    dict
        ``"a"`` and ``"b"`` to their configs.
    """
    base = load_config(c1.BASE_CONFIG).model_dump(mode="json")
    base["output"] = {"directory": str(ADDENDUM_STORE)}
    out: dict[str, ExperimentConfig] = {}
    for name, objectives in rq2.KFOLD_OBJECTIVE_SETS.items():
        data = json.loads(json.dumps(base))
        data["name"] = f"c1-combination-kfold-{pricing}-k{kappa:g}-{name}"
        data["description"] = (
            "MAR-194 (C1 combination view follow-ups): the C1 main line on a "
            "year-block 5-fold split, for pooled out-of-sample KPIs (MAR-151); "
            "MAR-158's k-fold configs at another pricing or budget loading."
        )
        data["sample"] = {"kind": "kfold", "k": rq2.KFOLD_K}
        data["pricing"] = c1.PRICINGS[pricing]
        data["constraints"] = [{"kind": "budget", "loading": kappa}]
        data["objectives"] = objectives
        out[name] = parse_config(data)
    return out


def _config_path(pricing: str, kappa: float, name: str) -> Path:
    return CONFIG_DIR / f"kfold_{pricing}_k{kappa:g}_{name}.yaml"


def write_kfold_addendum_configs() -> list[Path]:
    """Write the item-1 k-fold configs to ``research/configs/c1-combination/``.

    Paths in the files are relative to them, as in the other research
    configs.

    Returns
    -------
    list of Path
        The files written.
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for pricing, kappa in KFOLD_ADDENDUM:
        for name, cfg in kfold_addendum_configs(pricing, kappa).items():
            text = dump_config(cfg)
            text = text.replace(str(cfg.eventset.path), _RELATIVE_PATHS["eventset"])
            text = text.replace(str(ADDENDUM_STORE), _RELATIVE_PATHS["output"])
            header = (
                f"# MAR-194 item 1: pooled 5-fold runs of the C1 main line at "
                f"{pricing}, kappa {kappa:g}, objective set {name!r}.\n"
                "# Written by research/scripts/c1_combination.py "
                "--write-configs; the script\n"
                "# checks that this file hashes as the configs it derives "
                "from MAR-158's\n"
                "# (c1_rq2.kfold_configs) with this pricing and budget "
                "loading.\n"
                "#\n# Paths are relative to this file.\n"
            )
            path = _config_path(pricing, kappa, name)
            path.write_text(header + text)
            written.append(path)
    return written


def load_kfold_addendum() -> dict[tuple[str, float], dict[str, ExperimentConfig]]:
    """Read the item-1 k-fold configs and check their hashes.

    Returns
    -------
    dict
        (pricing, kappa) to {objective set: config}.

    Raises
    ------
    RuntimeError
        If a file does not hash as the config it was derived as, or the
        derivation does not reproduce MAR-158's configs at (pure, 1) and
        (r 0.06, 1).
    """
    reference = rq2.kfold_configs()
    for pricing in rq2.KFOLD_PRICINGS:
        mine = kfold_addendum_configs(pricing, 1.0)
        for name, cfg in mine.items():
            if config_hash(cfg) != config_hash(reference[(pricing, name)]):
                raise RuntimeError(f"derivation differs from MAR-158: {pricing} {name}")
    out: dict[tuple[str, float], dict[str, ExperimentConfig]] = {}
    for pricing, kappa in KFOLD_ADDENDUM:
        derived = kfold_addendum_configs(pricing, kappa)
        out[(pricing, kappa)] = {}
        for name, cfg in derived.items():
            loaded = load_config(_config_path(pricing, kappa, name))
            if config_hash(loaded) != config_hash(cfg):
                raise RuntimeError(
                    f"{_config_path(pricing, kappa, name)}: hash differs"
                )
            out[(pricing, kappa)][name] = loaded
    return out


def _variant_contrasts(
    variant: PooledVariant, pricing: str, kappa: float
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    for beta in EVAL_BETAS:
        new = contrast_rows(
            variant.boots[beta],
            variant.hashes,
            contrasts("main"),
            split="pooled",
            beta=beta,
        )
        for r in new:
            r.update(family="main", eventset="thesis", pricing=pricing, kappa=kappa)
        rows += new
    return rows, _check_native(rows, variant.native, pricing)


def run_kfold_addendum(args: argparse.Namespace) -> dict[str, Any]:
    """Phase kfold_addendum: solve and pool the item-1 k-fold runs.

    Solves the missing runs of the configs in ``research/configs/
    c1-combination/`` into ``--addendum-store`` with the installed core
    version, then pools them as phase ``kfold`` does the MAR-158 runs.

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
    variants = load_kfold_addendum()
    checksum = str(load_config(c1.BASE_CONFIG).eventset.checksum)
    store = ResultStore(args.addendum_store)
    todo: dict[str, ExperimentConfig] = {}
    n_runs = 0
    for configs in variants.values():
        for cfg in configs.values():
            for s in cfg.single_runs():
                n_runs += 1
                rid = run_key(config_hash(s), checksum, policy=DEFAULT_POLICY)
                if not store.has_run(rid):
                    todo[rid] = s
    print(f"kfold_addendum: {n_runs} runs, {len(todo)} to solve", flush=True)
    solve_seconds: dict[str, float] = {}
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {pool.submit(c1.solve_worker, cfg): rid for rid, cfg in todo.items()}
        for i, fut in enumerate(as_completed(futs), 1):
            tables, manifest, sec = fut.result()
            rid = futs[fut]
            if manifest["run_id"] != rid:
                raise RuntimeError(f"run id mismatch: {manifest['run_id']} != {rid}")
            store.write_run(tables, manifest)
            solve_seconds[rid[7:19]] = round(sec, 1)
            print(
                f"[kfold_addendum {i}/{len(todo)}] {rid[7:19]} {sec:.0f}s", flush=True
            )
    t_solve = time.perf_counter() - t0
    prepared = c1._prepared(next(iter(next(iter(variants.values())).values())))
    grid: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    run_rows: list[dict[str, Any]] = []
    n_checked = 0
    resample_ref: YearResample | None = None
    for (pricing, kappa), configs in variants.items():
        variant = pooled_variant(pricing, kappa, configs, store, None, prepared)
        if resample_ref is None:
            resample_ref = variant.resample
        elif not resample_ref.same_as(variant.resample):
            raise RuntimeError("the k-fold configs drew different resamples")
        grid += variant.grid
        run_rows += variant.runs
        new, n = _variant_contrasts(variant, pricing, kappa)
        rows += new
        n_checked += n
    con = pd.DataFrame(rows)
    n_dec = _check_decomposition(con)
    args.full.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(grid).to_csv(
        args.full / "kfold_addendum_grid.csv", index=False, float_format="%.10g"
    )
    con.to_csv(
        args.full / "kfold_addendum_contrasts.csv", index=False, float_format="%.10g"
    )
    pd.DataFrame(run_rows).to_csv(args.full / "kfold_addendum_runs.csv", index=False)
    print(
        f"kfold_addendum: checked {n_checked} rows against pooled_difference; "
        f"{n_dec} decompositions",
        flush=True,
    )
    return {
        "kfold_addendum_experiment_config_hashes": {
            f"{p}|k{k:g}|{o}": config_hash(c)
            for (p, k), cs in variants.items()
            for o, c in cs.items()
        },
        "kfold_addendum_runs": len(run_rows),
        "kfold_addendum_solved": len(todo),
        "kfold_addendum_solve_seconds_wall": round(t_solve, 1),
        "kfold_addendum_solve_seconds_per_run": solve_seconds,
        "checked_against_pooled_difference": n_checked,
        "checked_decompositions": n_dec,
        "kfold_addendum_seconds": round(time.perf_counter() - t0, 1),
        "jobs": args.jobs,
    }


# --- item 2: per-site KPIs of the individual designs -----------------------


def _site_premiums(store: ResultStore, run_id: str) -> pd.Series:
    """Each site's design premium (problem id = site in the individual scope)."""
    runs = store.read("runs", run_ids=[run_id])
    return runs.set_index("problem_id")["premium"].astype(float)


def sites_worker(
    pricing: str,
    kappa: float,
    members: dict[str, tuple[ExperimentConfig, str]],
    store_root: str,
) -> tuple[dict[str, pd.DataFrame], float]:
    """Per-site train and test KPIs of one variant's four individual designs.

    Parameters
    ----------
    pricing : str
        C1 pricing label.
    kappa : float
        Budget loading.
    members : dict
        Design label to (single-run config, run id) of the C1 individual runs.
    store_root : str
        The C1 result store.

    Returns
    -------
    frames : dict of pandas.DataFrame
        ``grid`` (per-site KPIs, train and test, and budget use) and
        ``contrasts`` (per-site weighted CVaR minus MSE / E[U], train and
        test, paired 90 % intervals on the test years).
    seconds : float
        Wall time.
    """
    start = time.perf_counter()
    store = ResultStore(Path(store_root))
    cfg0 = members["mse"][0]
    prepared = c1._prepared(cfg0)
    train, test = splits.holdout(prepared, train_fraction=0.7)
    assert cfg0.bootstrap is not None
    resample = resample_years(
        test.years, cfg0.bootstrap.n_bootstrap, cfg0.bootstrap.rng()
    )
    level = cfg0.bootstrap.level
    comps = cfg0.to_components()
    basis, price = comps.basis, comps.pricing
    boots: dict[tuple[str, float], KpiBootstrap] = {}
    trains: dict[tuple[str, float], pd.DataFrame] = {}
    hashes: dict[str, str] = {}
    grid: list[dict[str, Any]] = []
    for design, (cfg, rid) in members.items():
        d = rq2._stored(cfg, rid, store)
        hashes[design] = d.config_hash
        premiums = _site_premiums(store, rid)
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
            ent = boot.table["level"] == "entity"
            boots[(design, beta)] = KpiBootstrap(
                table=boot.table.loc[ent].reset_index(drop=True),
                replicates=boot.replicates[ent.to_numpy()],
                resample=boot.resample,
                level=boot.level,
            )
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
            trains[(design, beta)] = tr.loc[tr["level"] == "entity"]
            for split, table in (
                ("test", boots[(design, beta)].table),
                ("train", trains[(design, beta)]),
            ):
                t = table.loc[table["kpi"].isin(SITE_KPIS)]
                if beta != CONFIG_BETA:
                    t = t.loc[t["kpi"].isin(TAIL_KPIS)]
                for r in t.itertuples():
                    grid.append(
                        {
                            "split": split,
                            "site": str(r.subject_id),
                            "design": design,
                            "kpi": str(r.kpi),
                            "eval_beta": beta if r.kpi in TAIL_KPIS else math.nan,
                            "value": float(r.value),
                            "ci_low": float(r.ci_low) if split == "test" else math.nan,
                            "ci_high": float(r.ci_high)
                            if split == "test"
                            else math.nan,
                            "config_hash": d.config_hash,
                        }
                    )
        el = trains[(design, CONFIG_BETA)]
        el = el.loc[el["kpi"] == "expected_loss"].set_index("subject_id")["value"]
        for site, prem in premiums.items():
            for name, value in (
                ("premium", prem),
                ("budget_use", prem / (kappa * float(el[site]))),
            ):
                grid.append(
                    {
                        "split": "train",
                        "site": str(site),
                        "design": design,
                        "kpi": name,
                        "eval_beta": math.nan,
                        "value": float(value),
                        "ci_low": math.nan,
                        "ci_high": math.nan,
                        "config_hash": d.config_hash,
                    }
                )
    rows: list[dict[str, Any]] = []
    for w in TAIL_DESIGNS["main"]:
        for o in BASE_DESIGNS:
            for beta in EVAL_BETAS:
                diff = paired_difference(boots[(w, beta)], boots[(o, beta)])
                tw = trains[(w, beta)].set_index(["subject_id", "kpi"])["value"]
                to = trains[(o, beta)].set_index(["subject_id", "kpi"])["value"]
                for r in diff.itertuples():
                    kpi = str(r.kpi)
                    if kpi not in SITE_CONTRAST_KPIS:
                        continue
                    if beta != CONFIG_BETA and kpi not in TAIL_KPIS:
                        continue
                    site = str(r.subject_id)
                    common = {
                        "site": site,
                        "tail_design": w,
                        "base_design": o,
                        "kpi": kpi,
                        "eval_beta": beta if kpi in TAIL_KPIS else math.nan,
                        "hash_a": hashes[w],
                        "hash_b": hashes[o],
                    }
                    rows.append(
                        {
                            "split": "test",
                            **common,
                            "value": float(r.difference),
                            "ci_low": float(r.ci_low),
                            "ci_high": float(r.ci_high),
                            "value_ref": float(r.value_b),
                        }
                    )
                    rows.append(
                        {
                            "split": "train",
                            **common,
                            "value": float(tw[(site, kpi)] - to[(site, kpi)]),
                            "ci_low": math.nan,
                            "ci_high": math.nan,
                            "value_ref": float(to[(site, kpi)]),
                        }
                    )
    frames = {"grid": pd.DataFrame(grid), "contrasts": pd.DataFrame(rows)}
    for frame in frames.values():
        frame.insert(0, "kappa", kappa)
        frame.insert(0, "pricing", pricing)
    return frames, time.perf_counter() - start


def _pooled_site_frames(
    variant: PooledVariant, pricing: str, kappa: float, prepared: EventSet
) -> dict[str, pd.DataFrame]:
    """Per-site pooled KPIs and contrasts of one k-fold variant."""
    measure = outcome_measure(prepared, Basis.ANNUAL, years=Sample.full(prepared).years)
    row_years = prepared.events["year"].to_numpy(dtype=np.int64)
    ones = rq2._identity(variant.resample)
    level = next(iter(variant.boots[CONFIG_BETA].values())).level
    reps: dict[tuple[str, str, float], dict[KpiName, np.ndarray]] = {}
    point: dict[tuple[str, str, float], dict[KpiName, np.ndarray]] = {}
    grid: list[dict[str, Any]] = []
    for (design, site), (loss, pay) in variant.sites.items():
        for beta in EVAL_BETAS:
            key = (design, site, beta)
            reps[key] = kpi_replicates(
                loss, pay, measure, row_years, variant.resample, beta=beta
            )
            point[key] = kpi_replicates(loss, pay, measure, row_years, ones, beta=beta)
            for k, r in reps[key].items():
                if k.value not in SITE_KPIS:
                    continue
                if beta != CONFIG_BETA and k.value not in TAIL_KPIS:
                    continue
                lo, hi = percentile_interval(r, level)
                grid.append(
                    {
                        "split": "pooled",
                        "site": site,
                        "design": design,
                        "kpi": k.value,
                        "eval_beta": beta if k.value in TAIL_KPIS else math.nan,
                        "value": float(point[key][k][0]),
                        "ci_low": lo,
                        "ci_high": hi,
                        "config_hash": variant.hashes[(INDIVIDUAL, design)],
                    }
                )
    rows: list[dict[str, Any]] = []
    sites = sorted({s for _, s in variant.sites})
    for w in TAIL_DESIGNS["main"]:
        for o in BASE_DESIGNS:
            for site in sites:
                for beta in EVAL_BETAS:
                    for k in reps[(w, site, beta)]:
                        if k.value not in SITE_CONTRAST_KPIS:
                            continue
                        if beta != CONFIG_BETA and k.value not in TAIL_KPIS:
                            continue
                        diff = reps[(w, site, beta)][k] - reps[(o, site, beta)][k]
                        lo, hi = percentile_interval(diff, level)
                        ref = float(point[(o, site, beta)][k][0])
                        rows.append(
                            {
                                "split": "pooled",
                                "site": site,
                                "tail_design": w,
                                "base_design": o,
                                "kpi": k.value,
                                "eval_beta": beta if k.value in TAIL_KPIS else math.nan,
                                "hash_a": variant.hashes[(INDIVIDUAL, w)],
                                "hash_b": variant.hashes[(INDIVIDUAL, o)],
                                "value": float(point[(w, site, beta)][k][0]) - ref,
                                "ci_low": lo,
                                "ci_high": hi,
                                "value_ref": ref,
                            }
                        )
    frames = {"grid": pd.DataFrame(grid), "contrasts": pd.DataFrame(rows)}
    for frame in frames.values():
        frame.insert(0, "kappa", kappa)
        frame.insert(0, "pricing", pricing)
    return frames


def _check_sites_against_rq2(grid: pd.DataFrame) -> int:
    """Raise unless the per-site test KPIs equal MAR-158's full entity rows."""
    path = args_rq2_full() / "holdout_main_kpis.csv"
    theirs = pd.read_csv(path)
    theirs = theirs.loc[
        (theirs["level"] == "entity")
        & (theirs["scope"] == INDIVIDUAL)
        & (theirs["split"] == "test")
        & theirs["kpi"].isin(SITE_KPIS)
    ].copy()
    theirs["site"] = theirs["subject_id"]
    tail = theirs["kpi"].isin(TAIL_KPIS)
    theirs.loc[~tail, "eval_beta"] = math.nan
    theirs = theirs.drop_duplicates(
        ["pricing", "kappa", "design", "site", "kpi", "eval_beta"]
    )
    mine = grid.loc[grid["split"] == "test"]
    key = ["pricing", "kappa", "design", "site", "kpi", "eval_beta"]
    merged = mine.merge(
        theirs[[*key, "value", "ci_low", "ci_high"]],
        on=key,
        suffixes=("", "_rq2"),
        validate="one_to_one",
    )
    if len(merged) != len(mine):
        raise RuntimeError(f"{len(mine) - len(merged)} per-site rows not in MAR-158")
    for column in ("value", "ci_low", "ci_high"):
        _close(merged[column], merged[f"{column}_rq2"], f"per-site {column}")
    return len(merged)


def args_rq2_full() -> Path:
    """MAR-158's full results (``c1_rq2.FULL_DIR``)."""
    return rq2.FULL_DIR


def run_sites(args: argparse.Namespace) -> dict[str, Any]:
    """Phase sites: per-site KPIs of the individual designs (item 2).

    Holdout train and test for every main-line variant (C1 runs), and pooled
    5-fold for every k-fold variant (MAR-158's and item 1's runs).

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
    groups = holdout_groups("main", args.c1_package_version)
    tasks: dict[tuple[str, float], dict[str, tuple[ExperimentConfig, str]]] = {}
    for (_, _, pricing, kappa), members in groups.items():
        tasks[(pricing, kappa)] = {
            design: m for (scope, design), m in members.items() if scope == INDIVIDUAL
        }
    frames: dict[str, list[pd.DataFrame]] = {}
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {
            pool.submit(sites_worker, p, k, m, str(args.c1_store)): (p, k)
            for (p, k), m in tasks.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            out, sec = fut.result()
            for name, frame in out.items():
                frames.setdefault(name, []).append(frame)
            print(f"[sites {i}/{len(futs)}] {futs[fut]} {sec:.0f}s", flush=True)
    holdout = {n: pd.concat(f, ignore_index=True) for n, f in frames.items()}
    n_rq2 = _check_sites_against_rq2(holdout["grid"])
    n_sum = _check_sites_sum(holdout["grid"], args)
    # pooled
    pooled: dict[str, list[pd.DataFrame]] = {}
    reference = rq2.kfold_configs()
    kstore = ResultStore(args.kfold_store)
    prepared = c1._prepared(next(iter(reference.values())))
    sources: list[tuple[str, float, dict[str, ExperimentConfig], ResultStore, Any]] = [
        (
            p,
            1.0,
            {o: c for (q, o), c in reference.items() if q == p},
            kstore,
            args.c1_package_version,
        )
        for p in rq2.KFOLD_PRICINGS
    ]
    astore = ResultStore(args.addendum_store)
    for (p, k), cs in load_kfold_addendum().items():
        sources.append((p, k, cs, astore, None))
    for p, k, cs, store, version in sources:
        variant = pooled_variant(p, k, cs, store, version, prepared, sites=True)
        for name, frame in _pooled_site_frames(variant, p, k, prepared).items():
            pooled.setdefault(name, []).append(frame)
        print(f"[sites pooled] {p} k{k:g}", flush=True)
    out = {n: pd.concat([holdout[n], *pooled[n]], ignore_index=True) for n in holdout}
    args.full.mkdir(parents=True, exist_ok=True)
    for name, table in out.items():
        table.to_csv(args.full / f"sites_{name}.csv", index=False, float_format="%.10g")
    print(f"sites: checked {n_rq2} rows against MAR-158, {n_sum} sums", flush=True)
    return {
        "sites_holdout_variants": len(tasks),
        "sites_pooled_variants": len(sources),
        "checked_site_rows_against_mar158": n_rq2,
        "checked_site_sums_against_grid": n_sum,
        "sites_seconds": round(time.perf_counter() - t0, 1),
    }


def _check_sites_sum(grid: pd.DataFrame, args: argparse.Namespace) -> int:
    """Raise unless the sites' E[L] and E[payout] add up to the portfolio's.

    E[U] does not add up: the portfolio's uncovered loss nets one site's
    excess payout against another's shortfall in the same event.
    """
    full = pd.read_csv(args.full / "holdout_main_grid.csv")
    port = full.loc[
        (full["scope"] == INDIVIDUAL)
        & full["kpi"].isin(["expected_loss", "expected_payout"])
    ]
    s = grid.loc[grid["kpi"].isin(["expected_loss", "expected_payout"])]
    s = s.groupby(["pricing", "kappa", "split", "design", "kpi"], as_index=False)[
        "value"
    ].sum()
    merged = s.merge(
        port[["pricing", "kappa", "split", "design", "kpi", "value"]],
        on=["pricing", "kappa", "split", "design", "kpi"],
        suffixes=("", "_portfolio"),
        validate="one_to_one",
    )
    if len(merged) != len(s):
        raise RuntimeError("per-site sums without a portfolio row")
    _close(merged["value"], merged["value_portfolio"], "per-site sum")
    return len(merged)


# --- item 3: the second optima of the joint designs ------------------------


def _family_e(pricing: str, design: str, scope: str, root: Path) -> dict[str, Any]:
    path = root / f"result_joint_{pricing}_{design}_{scope}.json"
    data: dict[str, Any] = json.loads(path.read_text())
    if data["group"] != [pricing, design, scope]:
        raise RuntimeError(f"{path}: group {data['group']}")
    return data


def alt_worker(
    pricing: str,
    members: dict[Design, tuple[ExperimentConfig, str]],
    store_root: str,
    family_e: str,
) -> tuple[dict[str, pd.DataFrame], float]:
    """Contrast one kappa-1 variant's designs with the joint ``alt`` optima in.

    Parameters
    ----------
    pricing : str
        ``"pure"`` or ``"coc_r0.06"``.
    members : dict
        (scope, design) to (single-run config, run id) of the C1 runs.
    store_root : str
        The C1 result store.
    family_e : str
        MAR-206 family (e)'s ``joint`` directory.

    Returns
    -------
    frames : dict of pandas.DataFrame
        ``grid`` (the ``alt`` designs' train and test portfolio KPIs),
        ``contrasts`` (train and test, every version of
        :data:`VERSIONS`) and ``designs`` (checks per ``alt`` design).
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
    boots: dict[tuple[str, float], dict[Design, KpiBootstrap]] = {}
    train_values: dict[tuple[str, float], dict[Design, pd.Series]] = {}
    hashes: dict[Design, str] = {}
    grid: list[pd.DataFrame] = []
    design_rows: list[dict[str, Any]] = []
    for (scope, design), (cfg, rid) in members.items():
        d = rq2._stored(cfg, rid, store)
        hashes[(scope, design)] = d.config_hash
        versions: dict[str, list[Any]] = {"c1": d.results}
        if scope != INDIVIDUAL:
            fe = _family_e(pricing, design, scope, Path(family_e))
            stored = np.asarray(fe["thetas"]["stored"], dtype=np.float64)
            mine = np.vstack([r.theta for r in d.results])
            if stored.shape != mine.shape or not np.allclose(
                stored, mine, rtol=1e-9, atol=1e-6
            ):
                raise RuntimeError(f"{pricing} {scope} {design}: stored theta differs")
            (r0,) = d.results
            alt = np.asarray(fe["thetas"]["alt"], dtype=np.float64)
            versions["alt"] = [
                dataclasses.replace(r0, theta=alt, solver="alt", attempts=())
            ]
            design_rows.append(
                {
                    "pricing": pricing,
                    "scope": scope,
                    "design": design,
                    "config_hash": d.config_hash,
                    "run_id": rid,
                    **{f"alt_{k}": v for k, v in fe["checks"]["alt"].items()},
                    "max_abs_theta_change": float(np.max(np.abs(alt - mine))),
                }
            )
        for version, results in versions.items():
            for beta in EVAL_BETAS:
                boot = bootstrap_kpis(
                    prepared,
                    d.scope,
                    results,
                    basis=basis,
                    beta=beta,
                    run_id=f"{rid}|{version}",
                    resample=resample,
                    sample=test,
                    pricing=price,
                    level=level,
                ).portfolio_rows()
                boots.setdefault((version, beta), {})[(scope, design)] = boot
                tr = kpis(
                    prepared,
                    d.scope,
                    results,
                    basis=basis,
                    beta=beta,
                    run_id=f"{rid}|{version}",
                    sample=train,
                    pricing=price,
                )
                tr = tr.loc[tr["level"] == "portfolio"]
                train_values.setdefault((version, beta), {})[(scope, design)] = (
                    tr.set_index("kpi")["value"]
                )
                if version != "alt":
                    continue
                for split, table in (("test", boot.table), ("train", tr)):
                    g = _grid_rows(table, beta)
                    g["split"] = split
                    g["scope"], g["design"] = scope, design
                    g["version"] = version
                    g["config_hash"] = d.config_hash
                    grid.append(g)
    rows: list[dict[str, Any]] = []
    items = contrasts("main")
    for wv, ov in VERSIONS:
        for beta in EVAL_BETAS:
            b: dict[Design, KpiBootstrap] = {}
            tv: dict[Design, pd.Series] = {}
            for key in boots[("c1", beta)]:
                scope, design = key
                v = "c1"
                if scope != INDIVIDUAL:
                    v = wv if design in TAIL_DESIGNS["main"] else ov
                b[key] = boots[(v, beta)][key]
                tv[key] = train_values[(v, beta)][key]
            new = contrast_rows(b, hashes, items, split="test", beta=beta)
            new += train_contrast_rows(tv, hashes, items, beta=beta)
            for r in new:
                r["tail_version"], r["base_version"] = wv, ov
            rows += new
    frames = {
        "grid": pd.concat(grid, ignore_index=True),
        "contrasts": pd.DataFrame(rows),
        "designs": pd.DataFrame(design_rows),
    }
    for frame in frames.values():
        if "kappa" not in frame.columns:
            frame.insert(0, "kappa", 1.0)
        if "pricing" not in frame.columns:
            frame.insert(0, "pricing", pricing)
    return frames, time.perf_counter() - start


def _check_alt(
    frames: dict[str, pd.DataFrame], args: argparse.Namespace
) -> dict[str, Any]:
    """Compare the ``alt`` designs with family (e), (b) and C1 observation 32."""
    grid = frames["grid"]
    test = grid.loc[(grid["split"] == "test") & (grid["kpi"] != "premium")]
    # family (e): point test KPIs of the same thetas
    n_e = 0
    key_e = {"expected_uncovered": "eu"}
    for r in test.itertuples():
        if r.kpi not in ("expected_uncovered", "cvar_uncovered"):
            continue
        name = key_e.get(r.kpi, f"cvar@{r.eval_beta:g}")
        fe = _family_e(r.pricing, r.design, r.scope, args.family_e)
        theirs = float(fe["point"]["alt"]["test"][name])
        if not math.isclose(r.value, theirs, rel_tol=1e-9, abs_tol=1e-6):
            raise RuntimeError(
                f"alt {r.pricing} {r.scope} {r.design} {name}: family (e)"
            )
        n_e += 1
    # family (b): test KPIs and intervals of its alt solves
    nb = pd.read_csv(args.nonunique_kpis)
    nb = nb.loc[
        (nb["variant"] == "alt")
        & (nb["family"] == "main")
        & (nb["kappa"] == 1.0)
        & nb["pricing"].isin(ALT_PRICINGS)
        & nb["kpi"].isin(["expected_uncovered", "cvar_uncovered"])
    ].copy()
    tail = nb["kpi"].isin(TAIL_KPIS)
    nb.loc[~tail, "eval_beta"] = math.nan
    nb = nb.drop_duplicates(["pricing", "scope", "design", "kpi", "eval_beta"])
    mine = test.loc[test["kpi"].isin(["expected_uncovered", "cvar_uncovered"])]
    key = ["pricing", "scope", "design", "kpi", "eval_beta"]
    merged = mine.merge(
        nb[[*key, "value", "ci_low", "ci_high"]], on=key, suffixes=("", "_b")
    )
    rel_b = (merged["value"] / merged["value_b"] - 1.0).abs()
    # C1 observation 32 (c1_rq2 `_alt` designs): test KPIs, kappa 1
    rq = pd.read_csv(args_rq2_full() / "holdout_main_kpis.csv")
    rq = rq.loc[
        rq["scope"].isin(["portfolio_alt", "cluster_alt"])
        & (rq["level"] == "portfolio")
        & (rq["split"] == "test")
        & rq["pricing"].isin(ALT_PRICINGS)
        & rq["kpi"].isin(["expected_uncovered", "cvar_uncovered"])
    ].copy()
    rq["scope"] = rq["scope"].str.replace("_alt", "", regex=False)
    tail = rq["kpi"].isin(TAIL_KPIS)
    rq.loc[~tail, "eval_beta"] = math.nan
    rq = rq.drop_duplicates(key)
    merged32 = mine.merge(rq[[*key, "value"]], on=key, suffixes=("", "_32"))
    rel_32 = (merged32["value"] / merged32["value_32"] - 1.0).abs()
    return {
        "checked_alt_rows_against_family_e": n_e,
        "alt_rows_compared_with_family_b": len(merged),
        "alt_max_rel_diff_family_b": float(rel_b.max()),
        "alt_rows_compared_with_c1_obs32": len(merged32),
        "alt_max_rel_diff_c1_obs32": float(rel_32.max()),
        "alt_max_rel_diff_c1_obs32_by_design": {
            f"{r.pricing}|{r.scope}|{r.design}": float(
                rel_32.loc[
                    (merged32["pricing"] == r.pricing)
                    & (merged32["scope"] == r.scope)
                    & (merged32["design"] == r.design)
                ].max()
            )
            for r in merged32.drop_duplicates(
                ["pricing", "scope", "design"]
            ).itertuples()
        },
    }


def _check_alt_c1_version(con: pd.DataFrame, full: Path) -> int:
    """Raise unless the (c1, c1) version reproduces the holdout phase's contrasts."""
    mine = con.loc[(con["tail_version"] == "c1") & (con["base_version"] == "c1")]
    theirs = pd.read_csv(full / "holdout_main_contrasts.csv")
    theirs = theirs.loc[theirs["kappa"] == 1.0]
    key = [
        "split",
        "pricing",
        "kappa",
        "contrast",
        "joint_scope",
        "tail_design",
        "base_design",
        "kpi",
        "eval_beta",
    ]
    text = ["joint_scope", "tail_design", "base_design"]
    mine = mine.assign(**{c: mine[c].fillna("") for c in text})
    theirs = theirs.assign(**{c: theirs[c].fillna("") for c in text})
    merged = mine.merge(
        theirs[[*key, "value", "ci_low", "ci_high"]],
        on=key,
        suffixes=("", "_holdout"),
        validate="one_to_one",
    )
    if len(merged) != len(mine):
        raise RuntimeError(f"{len(mine) - len(merged)} alt (c1, c1) rows unmatched")
    for column in ("value", "ci_low", "ci_high"):
        _close(merged[column], merged[f"{column}_holdout"], f"alt c1/c1 {column}")
    return len(merged)


def run_alt(args: argparse.Namespace) -> dict[str, Any]:
    """Phase alt: the contrasts with the joint designs' second optima (item 3).

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
    groups = holdout_groups("main", args.c1_package_version)
    tasks = {
        pricing: members
        for (_, _, pricing, kappa), members in groups.items()
        if kappa == 1.0 and pricing in ALT_PRICINGS
    }
    frames: dict[str, list[pd.DataFrame]] = {}
    ctx = get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.jobs, mp_context=ctx) as pool:
        futs = {
            pool.submit(alt_worker, p, m, str(args.c1_store), str(args.family_e)): p
            for p, m in tasks.items()
        }
        for i, fut in enumerate(as_completed(futs), 1):
            out, sec = fut.result()
            for name, frame in out.items():
                frames.setdefault(name, []).append(frame)
            print(f"[alt {i}/{len(futs)}] {futs[fut]} {sec:.0f}s", flush=True)
    tables = {n: pd.concat(f, ignore_index=True) for n, f in frames.items()}
    checks = _check_alt(tables, args)
    n_c1 = _check_alt_c1_version(tables["contrasts"], args.full)
    n_dec = 0
    for (wv, ov), g in tables["contrasts"].groupby(["tail_version", "base_version"]):
        del wv, ov
        n_dec += _check_decomposition(g)
    args.full.mkdir(parents=True, exist_ok=True)
    for name, table in tables.items():
        table.to_csv(args.full / f"alt_{name}.csv", index=False, float_format="%.10g")
    print(f"alt: {checks}; {n_c1} c1/c1 rows equal MAR-182; {n_dec} decompositions")
    return {
        **checks,
        "checked_c1_version_against_mar182": n_c1,
        "checked_decompositions": n_dec,
        "alt_seconds": round(time.perf_counter() - t0, 1),
    }


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
    parser = argparse.ArgumentParser(
        description="C1 combination view (MAR-182) and its follow-ups (MAR-194)."
    )
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument(
        "--phases",
        nargs="+",
        default=["holdout", "kfold"],
        choices=["holdout", "kfold", "kfold_addendum", "sites", "alt"],
        help=(
            "holdout, kfold: MAR-182; kfold_addendum, sites, alt: MAR-194 "
            "items 1, 2 and 3 (sites reads holdout's output and item 1's runs)"
        ),
    )
    parser.add_argument(
        "--families", nargs="+", default=["main", "f12"], choices=["main", "f12"]
    )
    parser.add_argument("--c1-store", type=Path, default=c1.STORE)
    parser.add_argument("--kfold-store", type=Path, default=rq2.KFOLD_STORE)
    parser.add_argument("--addendum-store", type=Path, default=ADDENDUM_STORE)
    parser.add_argument("--family-e", type=Path, default=FAMILY_E_DIR)
    parser.add_argument("--nonunique-kpis", type=Path, default=NONUNIQUE_KPIS)
    parser.add_argument("--full", type=Path, default=FULL_DIR)
    parser.add_argument(
        "--c1-package-version",
        default=C1_PACKAGE_VERSION,
        help="core version of the C1 and MAR-158 runs (part of their run ids)",
    )
    parser.add_argument(
        "--write-configs",
        action="store_true",
        help="write the item-1 k-fold configs to research/configs/c1-combination/",
    )
    args = parser.parse_args(argv)
    if args.write_configs:
        for path in write_kfold_addendum_configs():
            print(f"wrote {path.relative_to(REPO_ROOT)}")
        return 0
    common: dict[str, Any] = {
        "issue": "MAR-182",
        "base_config": str(c1.BASE_CONFIG.relative_to(REPO_ROOT)),
        "designs": {k: list(v) for k, v in DESIGNS.items()},
        "eval_betas": list(EVAL_BETAS),
        "package_versions": package_versions(),
        "c1_package_version": args.c1_package_version,
    }
    args.full.mkdir(parents=True, exist_ok=True)
    parts: list[tuple[str, Any]] = []
    if "holdout" in args.phases:
        parts += [
            (f"holdout_{f}", lambda f=f: run_holdout(args, f)) for f in args.families
        ]
    if "kfold" in args.phases:
        parts.append(("kfold", lambda: run_kfold(args)))
    addendum = {
        "kfold_addendum": lambda: run_kfold_addendum(args),
        "sites": lambda: run_sites(args),
        "alt": lambda: run_alt(args),
    }
    for name, run in addendum.items():
        if name in args.phases:
            parts.append((name, run))
    for name, run in parts:
        issue = "MAR-194" if name in addendum else "MAR-182"
        summary = {**common, "issue": issue, **run()}
        (args.full / f"summary_{name}.json").write_text(
            json.dumps(summary, indent=2, default=str) + "\n"
        )
    print(f"wrote {args.full}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
