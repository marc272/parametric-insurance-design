"""Parity of ``evaluate.kpis`` with the thesis KPI table (MAR-16).

Acceptance: on the fixture with the thesis payouts, the KPIs match
``parity/golden/benchmarking_kpis.csv.gz``.

What the thesis evaluated
    ``calculate_benchmarking_kpis`` (``src/utils/benchmarking.py``) ran in
    the notebook on ``transformed_simulation_df``: the event-loss table with
    the heteroscedastic noise layer (eta 0.3, 13 draws, seed 42) and the 20
    m/s filter on the portfolio maximum wind, with probabilities rescaled to
    sum to one. That is the ``event_conditional`` basis.
    :func:`thesis_data` rebuilds it from the MAR-9 fixture with
    ``noise.add_noise`` and ``EventSet.filter_threshold``; MAR-12's
    ``test_clustering_parity.py`` checks the rebuild is bit-identical to the
    thesis frame. The payouts were the in-memory optimisation results
    ``full_optimization_results``; ``beta`` was ``BENCHMARK_BETA = 0.95``.

Precision of the golden payouts
    The golden results table stores the payout levels as numpy prints them:
    8 decimals, in fixed notation (absolute rounding <= 5e-9) or in
    scientific notation (relative rounding <= 5e-9). The thesis computed its
    KPIs from the unrounded levels, which no longer exist. A KPI that
    cancels (a small uncovered loss, a tiny payout-to-loss ratio) can move
    by much more than 1e-9 relative under that rounding: the thesis' own
    function on the golden payouts differs from the golden KPIs by up to
    1.7e-4 relative (``CVaR_Uncovered`` of A5, portfolio scope, pure basis
    risk, 20 bins: 0.00563 USD). So the comparison is in two parts:

    * Against the golden KPI table (committed files only, CI-runnable; the
      core test suite runs :func:`check_golden` too while ``parity/tests``
      is not in CI, MAR-86): every golden row has our row, and each KPI
      agrees within ``1e-9`` relative plus the rounding bound propagated
      from the printed payouts (:func:`rounding_bounds`). The bound is
      rigorous: every KPI is Lipschitz in the payout vector.
    * Against the thesis function itself (``PARITY_THESIS_REPO``, local): on
      identical inputs (rebuilt data, golden payouts) every KPI agrees
      within 1e-9 relative. This is the "same formulas" check.
"""

from __future__ import annotations

import ast
import math
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design import evaluate
from parametric_insurance_design.basis import Basis
from parametric_insurance_design.clustering import ThesisWardClustering
from parametric_insurance_design.errors import EntityMismatchError
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Entity,
    ProblemSpec,
    Sample,
    Scope,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.records import KpiLevel, KpiName
from parametric_insurance_design.scopes import (
    PORTFOLIO_PROBLEM_ID,
    Cluster,
    Individual,
    Portfolio,
)

PARITY_DIR = Path(__file__).resolve().parents[1]
EVENTSET_DIR = PARITY_DIR / "tests" / "data" / "thesis_eventset"
GOLDEN_RESULTS = PARITY_DIR / "golden" / "full_optimization_results.csv.gz"
GOLDEN_KPIS = PARITY_DIR / "golden" / "benchmarking_kpis.csv.gz"

THESIS_REPO_ENV = "PARITY_THESIS_REPO"
THESIS_BENCHMARKING = "src/utils/benchmarking.py"
THESIS_FORMATTING = "src/utils/formatting.py"

THESIS_ASSETS = [f"A{k}" for k in range(1, 10)]
ATTACHMENT, LIMIT = 20.0, 70.0  # thesis ATTACHEMENT, LIMIT
BENCHMARK_BETA = 0.95
NOISE = {"level": 0.3, "kind": "heteroscedastic", "n_copies": 13, "seed": 42}
THRESHOLD = 20.0
N_THESIS_ROWS = 13_897  # rows after noise and filter (MAR-12 golden)
N_GOLDEN_KPI_ROWS = 1776
PRINT_PRECISION = 8  # numpy's default print precision
RTOL = 1e-9

GROUP = ["Approach", "Method", "Source", "Alpha", "Beta", "Budget_Loading"]
GROUP += ["N_Bins", "N_Clusters"]
UNSET = ("Alpha", "Beta", "N_Clusters")  # NaN where a method doesn't use them
KPI_COLUMNS: dict[str, KpiName] = {
    "CVaR_Uncovered": KpiName.CVAR_UNCOVERED,
    "VaR_Uncovered": KpiName.VAR_UNCOVERED,
    "E_Uncovered": KpiName.EXPECTED_UNCOVERED,
    "E_Residual": KpiName.RMSE_RESIDUAL,
    "E_Payout_to_E_Loss_Ratio": KpiName.PAYOUT_TO_LOSS_RATIO,
    "Correlation": KpiName.CORRELATION,
}


def thesis_data() -> EventSet:
    """The thesis' ``transformed_simulation_df`` as an EventSet."""
    eventset = EventSet.from_parquet(EVENTSET_DIR)
    noisy = add_noise(
        eventset,
        level=NOISE["level"],
        kind="heteroscedastic",
        n_copies=NOISE["n_copies"],
        rng=np.random.default_rng(seed=NOISE["seed"]),
        location_ids=THESIS_ASSETS,  # the thesis draws asset by asset
    )
    data = noisy.filter_threshold(THRESHOLD)
    assert data.n_rows == N_THESIS_ROWS
    assert list(data.location_ids) == THESIS_ASSETS
    return data


def parse_levels(text: str) -> tuple[np.ndarray, np.ndarray]:
    """Payout levels printed by numpy, and the rounding bound of each.

    numpy prints 8 decimals: of the value in fixed notation, of the mantissa
    in scientific notation (trailing zeros may be stripped). The bound is
    half a unit in the 8th decimal.
    """
    tokens = text.strip().strip("[]").split()
    levels = np.array(tokens, dtype=np.float64)
    bounds = np.empty_like(levels)
    for k, token in enumerate(tokens):
        mantissa, _, exponent = token.lower().partition("e")
        decimals = len(mantissa.partition(".")[2])
        assert decimals <= PRINT_PRECISION, token
        bounds[k] = 0.5 * 10.0 ** (int(exponent or 0) - PRINT_PRECISION)
    return levels, bounds


@dataclass(frozen=True)
class GoldenRun:
    """One thesis KPI group as a core run built from the golden payouts."""

    key: tuple[Any, ...]
    scope: Scope
    results: tuple[SolveResult, ...]
    bounds: tuple[SolveResult, ...]  # same specs, theta = rounding bounds
    golden: pd.DataFrame  # the group's rows of the golden KPI table
    payouts: pd.DataFrame  # the group's rows of the golden results table


def _result(spec: ProblemSpec, n_bins: int, theta: np.ndarray) -> SolveResult:
    """A SolveResult carrying given payout levels (no solve involved)."""
    return SolveResult(
        spec=spec,
        payout_structure=StepPayout(ATTACHMENT, LIMIT, n_bins),
        theta=theta,
        status=SolveStatus.OPTIMAL,
        objective_value=math.nan,
        premium=math.nan,
        scale=1.0,
        solver="thesis-golden",
        attempts=(),
        build_seconds=0.0,
        solve_seconds=0.0,
    )


def golden_runs() -> Iterator[GoldenRun]:
    """Every thesis KPI group, with its scope and results."""
    # NaN (unused parameters) never equals itself, so it can't be a key.
    payouts = pd.read_csv(GOLDEN_RESULTS).fillna({c: -1.0 for c in UNSET})
    kpis = pd.read_csv(GOLDEN_KPIS).fillna({c: -1.0 for c in UNSET})
    assert len(kpis) == N_GOLDEN_KPI_ROWS
    strategy = ThesisWardClustering(beta_tail=0.9, linkage="ward")
    groups = dict(list(payouts.groupby(GROUP, dropna=False, sort=False)))
    for group_key, golden in kpis.groupby(GROUP, dropna=False, sort=False):
        key = cast("tuple[Any, ...]", group_key)
        rows = groups[key]
        approach, n_bins = str(key[0]), int(key[6])
        levels = [parse_levels(s) for s in rows["Payouts"]]
        ids = [str(a).strip() for a in rows["Asset_ID"]]
        if approach == "individual_optimization":
            scope: Scope = Individual()
            specs = [ProblemSpec(a, (Entity(a, (a,)),)) for a in ids]
            results = tuple(
                _result(s, n_bins, lv[None, :])
                for s, (lv, _) in zip(specs, levels, strict=True)
            )
            bounds = tuple(
                _result(s, n_bins, b[None, :])
                for s, (_, b) in zip(specs, levels, strict=True)
            )
        else:
            if approach == "integrated_portfolio_optimization":
                scope = Portfolio()
                entities = tuple(Entity(a, (a,)) for a in ids)
            else:
                assert approach == "cluster_optimization", approach
                scope = Cluster(strategy=strategy, n_clusters=int(key[7]))
                entities = tuple(
                    Entity(c, tuple(ast.literal_eval(inc)))
                    for c, inc in zip(ids, rows["Included_Assets"], strict=True)
                )
            spec = ProblemSpec(PORTFOLIO_PROBLEM_ID, entities)
            results = (_result(spec, n_bins, np.vstack([lv for lv, _ in levels])),)
            bounds = (_result(spec, n_bins, np.vstack([b for _, b in levels])),)
        yield GoldenRun(key, scope, results, bounds, golden, rows)


def ours_as_thesis(table: pd.DataFrame) -> pd.DataFrame:
    """Our KPI rows in the thesis layout: one row per subject (``Asset``)."""
    rows = table[table["level"].isin([KpiLevel.ENTITY, KpiLevel.PORTFOLIO])]
    wide = rows.pivot(index=["level", "subject_id"], columns="kpi", values="value")
    wide.index = [
        "Portfolio" if level == KpiLevel.PORTFOLIO else subject
        for level, subject in wide.index
    ]
    return wide.rename(columns={v.value: k for k, v in KPI_COLUMNS.items()})


def rounding_bounds(data: EventSet, run: GoldenRun, ours: pd.DataFrame) -> pd.DataFrame:
    """How far each KPI can move under the print rounding of the payouts.

    With ``D_e >= |pi_e - pi'_e|`` per row (the bound of the level the row
    pays, summed over the subject's entities), ``p`` the probabilities and
    ``sigma`` our payout's weighted standard deviation:

    * ``E[U]``: ``E[D]``, as ``(L - pi)^+`` is 1-Lipschitz in ``pi``;
    * VaR and CVaR: ``max D``, both are monotone and translation-equivariant;
    * RMSE: ``sqrt(E[D^2])`` (triangle inequality in L2(p));
    * ``E[pi] / E[L]``: ``E[D] / E[L]``;
    * correlation: ``2 sqrt(E[D^2]) / sigma``, since the normalised centred
      payout is ``2 / sigma``-Lipschitz in L2(p).
    """
    p = data.rates / data.rates.sum()
    per_subject: dict[str, np.ndarray] = {}
    losses: dict[str, np.ndarray] = {}
    payouts: dict[str, np.ndarray] = {}
    for result, bound in zip(run.results, run.bounds, strict=True):
        problem = run.scope.materialise(data, result.spec)
        d = bound.payouts(problem)
        pi = result.payouts(problem)
        for j, entity_id in enumerate(result.entity_ids):
            per_subject[entity_id] = d[:, j]
            losses[entity_id] = problem.entity_loss[:, j]
            payouts[entity_id] = pi[:, j]
    per_subject["Portfolio"] = np.sum(list(per_subject.values()), axis=0)
    losses["Portfolio"] = data.loss.sum(axis=1)
    payouts["Portfolio"] = np.sum(
        [v for k, v in payouts.items() if k != "Portfolio"], axis=0
    )
    out = {}
    for subject, d in per_subject.items():
        mean_d = float(p @ d)
        rms_d = math.sqrt(float(p @ d**2))
        pi = payouts[subject]
        sigma = math.sqrt(float(p @ (pi - p @ pi) ** 2))
        out[subject] = {
            "E_Uncovered": mean_d,
            "VaR_Uncovered": float(d.max()),
            "CVaR_Uncovered": float(d.max()),
            "E_Residual": rms_d,
            "E_Payout_to_E_Loss_Ratio": mean_d / float(p @ losses[subject]),
            "Correlation": 2 * rms_d / sigma if sigma > 0 else math.inf,
        }
    return pd.DataFrame(out).T.loc[ours.index]


def evaluate_run(data: EventSet, run: GoldenRun) -> pd.DataFrame:
    """``evaluate.kpis`` of a golden run, in the thesis layout."""
    table = evaluate.kpis(
        data,
        run.scope,
        run.results,
        basis=Basis.EVENT_CONDITIONAL,
        beta=BENCHMARK_BETA,
        run_id="thesis-golden",
        sample=Sample.full(data),
    )
    return ours_as_thesis(table)


def check_golden(data: EventSet) -> dict[str, dict[str, float]]:
    """Compare every golden KPI with ours; return error statistics per KPI.

    Raises ``AssertionError`` if a golden row has no counterpart or a KPI
    differs by more than ``RTOL`` relative plus its rounding bound.
    """
    stats = {k: {"max_rel": 0.0, "n_within_rtol": 0, "n": 0} for k in KPI_COLUMNS}
    stats_rel: dict[str, list[float]] = {k: [] for k in KPI_COLUMNS}
    n_rows = 0
    for run in golden_runs():
        ours = evaluate_run(data, run)
        golden = run.golden.set_index(run.golden["Asset"].astype(str))
        assert sorted(golden.index) == sorted(ours.index), run.key
        bounds = rounding_bounds(data, run, ours)
        for column in KPI_COLUMNS:
            want = golden.loc[ours.index, column].to_numpy(dtype=float)
            got = ours[column].to_numpy(dtype=float)
            err = np.abs(got - want)
            tol = RTOL * np.abs(want) + bounds[column].to_numpy() * (1 + 1e-6)
            assert np.array_equal(np.isnan(got), np.isnan(want)), (run.key, column)
            ok = np.isnan(want) | (err <= tol)
            assert ok.all(), (run.key, column, list(ours.index[~ok]), err[~ok])
            finite = ~np.isnan(want)
            rel = err[finite] / np.maximum(np.abs(want[finite]), np.finfo(float).tiny)
            stats_rel[column].extend(rel.tolist())
        n_rows += len(ours)
    assert n_rows == N_GOLDEN_KPI_ROWS
    for column, rel in stats_rel.items():
        arr = np.asarray(rel)
        stats[column] = {
            "max_rel": float(arr.max()),
            "n_within_rtol": int((arr <= RTOL).sum()),
            "n": int(arr.size),
        }
    return stats


# --------------------------------------------------------------------------
# Committed files only
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def data() -> EventSet:
    return thesis_data()


def test_every_golden_group_has_its_payouts() -> None:
    # Each KPI group of the thesis has one results row per entity.
    runs = list(golden_runs())
    assert sum(len(r.golden) for r in runs) == N_GOLDEN_KPI_ROWS
    for run in runs:
        entities = {i for r in run.results for i in r.entity_ids}
        assert entities == set(run.golden["Asset"]) - {"Portfolio"}, run.key


def test_kpis_match_golden_within_print_rounding(data: EventSet) -> None:
    stats = check_golden(data)
    for column, s in stats.items():
        print(f"{column}: {s}")
    assert all(s["n"] > 0 for s in stats.values())


def test_groups_the_thesis_dropped_raise(data: EventSet) -> None:
    # Thesis C3: three individual-scope groups (MSE, budget loading 0.5, 0.6,
    # 0.7) have a result for A1 only, the other solves failed. The thesis
    # skipped them without a KPI row; evaluate.kpis raises instead.
    payouts = pd.read_csv(GOLDEN_RESULTS).fillna({c: -1.0 for c in UNSET})
    kpi_groups = set(
        pd.read_csv(GOLDEN_KPIS)
        .fillna({c: -1.0 for c in UNSET})
        .groupby(GROUP)
        .size()
        .index
    )
    dropped = [
        (cast("tuple[Any, ...]", key), rows)
        for key, rows in payouts.groupby(GROUP)
        if key not in kpi_groups
    ]
    assert [(k[0], k[1], k[5], len(r)) for k, r in dropped] == [
        ("individual_optimization", "pure_basis_risk_minimization", b, 1)
        for b in (0.5, 0.6, 0.7)
    ]
    for key, rows in dropped:
        (asset,) = rows["Asset_ID"]
        levels, _ = parse_levels(rows["Payouts"].iloc[0])
        spec = ProblemSpec(asset, (Entity(asset, (asset,)),))
        result = _result(spec, int(key[6]), levels[None, :])
        with pytest.raises(EntityMismatchError, match="no result covers"):
            evaluate.kpis(
                data,
                Individual(),
                (result,),
                basis=Basis.EVENT_CONDITIONAL,
                beta=BENCHMARK_BETA,
                run_id="thesis-golden",
            )


def test_rounding_bound_of_printed_levels() -> None:
    # Half a unit in the 8th decimal: absolute in fixed, relative in scientific.
    levels, bounds = parse_levels("[0. 1.5 2.25e+03 3.12345678e-04]")
    np.testing.assert_array_equal(levels, [0.0, 1.5, 2250.0, 3.12345678e-04])
    np.testing.assert_allclose(bounds, [5e-9, 5e-9, 5e-6, 5e-13], rtol=1e-12)


# --------------------------------------------------------------------------
# Against the thesis code
# --------------------------------------------------------------------------


@pytest.fixture(scope="module")
def thesis_kpis() -> Any:  # noqa: ANN401
    """The thesis ``calculate_benchmarking_kpis``, loaded on its own."""
    value = os.environ.get(THESIS_REPO_ENV)
    if not value:
        pytest.skip(
            f"{THESIS_REPO_ENV} is not set: set it to a checkout of "
            "parametric-insurance-framework to compare with the thesis "
            "calculate_benchmarking_kpis"
        )
    repo = Path(value).expanduser()
    for rel in (THESIS_BENCHMARKING, THESIS_FORMATTING):
        if not (repo / rel).is_file():
            pytest.fail(f"{THESIS_REPO_ENV}={value} does not hold {rel}")
    namespace: dict[str, Any] = {}
    formatting = (repo / THESIS_FORMATTING).read_text(encoding="utf-8")
    exec(compile(formatting, str(repo / THESIS_FORMATTING), "exec"), namespace)
    # benchmarking.py imports coerce_object_list from src.utils.formatting;
    # drop that import and supply the function loaded above.
    tree = ast.parse((repo / THESIS_BENCHMARKING).read_text(encoding="utf-8"))
    tree.body = [
        node
        for node in tree.body
        if not (
            isinstance(node, ast.ImportFrom) and node.module == "src.utils.formatting"
        )
    ]
    exec(compile(tree, str(repo / THESIS_BENCHMARKING), "exec"), namespace)
    return namespace["calculate_benchmarking_kpis"]


def _simulation_df(data: EventSet) -> pd.DataFrame:
    frame = pd.DataFrame({"probability": data.rates})
    for i, asset in enumerate(data.location_ids):
        frame[f"{asset}_Wind"] = data.index[:, i]
        frame[f"{asset}_Loss"] = data.loss[:, i]
    return frame


def test_against_thesis_function(
    data: EventSet,
    thesis_kpis: Any,  # noqa: ANN401
) -> None:
    sim = _simulation_df(data)
    values = dict(
        zip(data.locations["location_id"], data.locations["value"], strict=True)
    )
    config = {a: {"value": float(v)} for a, v in values.items()}
    worst = dict.fromkeys(KPI_COLUMNS, 0.0)
    for run in golden_runs():
        rows = run.payouts.copy()
        rows["Payouts"] = [parse_levels(s)[0].tolist() for s in rows["Payouts"]]
        rows["Breakpoints"] = [
            StepPayout(ATTACHMENT, LIMIT, int(n)).edges.tolist() for n in rows["N_Bins"]
        ]
        rows["Included_Assets"] = [
            ast.literal_eval(s) if isinstance(s, str) else None
            for s in rows["Included_Assets"]
        ]
        theirs = thesis_kpis(
            sim,
            rows,
            assets_config=config,
            benchmark_beta=BENCHMARK_BETA,
            asset_list=THESIS_ASSETS,
        ).set_index("Asset")
        ours = evaluate_run(data, run)
        assert sorted(theirs.index) == sorted(ours.index), run.key
        for column in KPI_COLUMNS:
            want = theirs.loc[ours.index, column].to_numpy(dtype=float)
            got = ours[column].to_numpy(dtype=float)
            np.testing.assert_allclose(
                got, want, rtol=RTOL, atol=0.0, err_msg=f"{run.key} {column}"
            )
            finite = ~np.isnan(want) & (want != 0)
            if finite.any():
                rel = np.abs(got[finite] - want[finite]) / np.abs(want[finite])
                worst[column] = max(worst[column], float(rel.max()))
    print(f"max relative error vs thesis function: {worst}")
