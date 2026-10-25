"""Fixtures for the parity harness tests (MAR-67): a hand-made mini golden.

The mini golden, ``data/mini_golden/``, mimics the thesis tables: the same
columns, empty cells for unused parameters, numpy-printed arrays (one wrapped
over two lines) and Python list literals for ``Included_Assets``. Two assets,
two bins with the edges 20, 45, 70, and four records:

1. ``individual_optimization`` / ``pure_uncovered_loss_minimization`` /
   ``single_run``, budget loading 1: payouts and KPIs of A1, A2 and the
   portfolio (A2's correlation is undefined), plus the objective values of
   the problems A1 and A2 (``objectives.csv``; the thesis has no such table);
2. ``cluster_optimization`` / ``weighted_cvar_minimization`` /
   ``single_run``, alpha 0.5, beta 0.9, one cluster C1 = {A1, A2};
3. the same as 2 under ``alpha_sweep`` (the thesis repeats default points
   under every sweep);
4. ``individual_optimization`` / ``pure_basis_risk_minimization`` /
   ``budget_loading_sweep``, budget loading 0.5: a payout for A1 only and no
   KPI rows, like the groups the thesis dropped after failed solves.

:func:`mini_runs` describes the result store that reproduces it, and
``make_store`` writes it: the values agree with the golden ones unless a
test passes offsets to inject a mismatch. :data:`GOLDEN_KPIS` repeats the
KPI file's values for that purpose.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from parametric_insurance_design.experiment.store import ResultStore, RunTables
from parametric_insurance_design.records import (
    ALL_PROBLEMS,
    ENTITIES,
    EXCEEDANCE,
    KPIS,
    PAYOUTS,
    RUNS,
)

MINI_GOLDEN_DIR = Path(__file__).resolve().parent / "data" / "mini_golden"

GOLDEN_KPIS: dict[tuple[str, str], tuple[float, ...]] = {
    # (record, subject): CVaR, VaR, E[U], RMSE, E[pi]/E[L], correlation
    ("ind", "Portfolio"): (900.0, 400.0, 30.0, 150.0, 0.95, 0.9),
    ("ind", "A1"): (500.0, 250.0, 20.0, 100.0, 0.9, 0.8),
    ("ind", "A2"): (400.0, 150.0, 10.0, 50.0, 1.1, math.nan),
    ("clu", "Portfolio"): (800.0, 350.0, 25.0, 140.0, 1.0, 0.92),
    ("clu", "C1"): (800.0, 350.0, 25.0, 140.0, 1.0, 0.92),
}
"""The values of ``data/mini_golden/benchmarking_kpis.csv``."""

KPI_ORDER = (
    "cvar_uncovered",
    "var_uncovered",
    "expected_uncovered",
    "rmse_residual",
    "payout_to_loss_ratio",
    "correlation",
)
EDGES = (20.0, 45.0, 70.0)


@dataclass(frozen=True)
class GoldenPaths:
    """Paths of the mini golden tables."""

    results: Path
    kpis: Path
    objectives: Path


@pytest.fixture
def mini_golden() -> GoldenPaths:
    """The hand-made mini golden tables (``data/mini_golden/``)."""
    return GoldenPaths(
        MINI_GOLDEN_DIR / "full_optimization_results.csv",
        MINI_GOLDEN_DIR / "benchmarking_kpis.csv",
        MINI_GOLDEN_DIR / "objectives.csv",
    )


@dataclass
class RunSpec:
    """One store run, compactly.

    ``problems`` maps problem id to (status, objective value). ``entities``
    maps entity id to (problem id, members). ``payouts`` maps entity id to its
    levels (edges :data:`EDGES` unless ``edges`` is given). ``kpis`` maps
    (level, subject) to the six values in :data:`KPI_ORDER`.
    """

    name: str
    scope: str
    objective: str
    parameters: dict[str, Any]
    problems: dict[str, tuple[str, float | None]]
    entities: dict[str, tuple[str, tuple[str, ...]]]
    payouts: dict[str, tuple[float, ...]]
    kpis: dict[tuple[str, str], tuple[float, ...]] = field(default_factory=dict)
    source: str = "single_run"
    edges: tuple[float, ...] = EDGES
    beta: float = 0.95

    @property
    def run_id(self) -> str:
        return "sha256:" + hashlib.sha256(self.name.encode()).hexdigest()


def _tables(spec: RunSpec) -> RunTables:
    run_id = spec.run_id
    now = datetime(2026, 10, 25, tzinfo=UTC)
    runs = []
    for problem_id, (status, objective) in spec.problems.items():
        ok = status in ("optimal", "optimal_inaccurate")
        runs.append(
            {
                "run_id": run_id,
                "problem_id": problem_id,
                "config_hash": "sha256:" + "0" * 64,
                "source": spec.source,
                "scope": spec.scope,
                "objective": spec.objective,
                "pricing": "pure",
                "payout": "step",
                "basis": "event_conditional",
                "calibration_split": "full",
                "fold": 0,
                "parameters": json.dumps(spec.parameters, sort_keys=True),
                "status": status,
                "solver": "CLARABEL" if ok else None,
                "objective_value": objective,
                "premium": 1.0 if ok else None,
                "build_seconds": 0.0,
                "solve_seconds": 0.0,
                "error_type": None if ok else "InfeasibleError",
                "error_message": None if ok else "no solver solved it",
                "eventset_checksum": None,
                "package_version": "0.0.0",
                "created_at": pd.Timestamp(now),
            }
        )
    entities = [
        {
            "run_id": run_id,
            "problem_id": problem_id,
            "entity_id": entity_id,
            "location_id": location_id,
        }
        for entity_id, (problem_id, members) in spec.entities.items()
        for location_id in members
    ]
    payouts = [
        {
            "run_id": run_id,
            "problem_id": spec.entities[entity_id][0],
            "entity_id": entity_id,
            "param_index": k,
            "lower": spec.edges[k],
            "upper": spec.edges[k + 1],
            "value": value,
        }
        for entity_id, levels in spec.payouts.items()
        for k, value in enumerate(levels)
    ]
    kpis = []
    for (level, subject), values in spec.kpis.items():
        problem_id = (
            ALL_PROBLEMS
            if level == "portfolio" and spec.scope == "individual"
            else "portfolio"
            if level == "portfolio"
            else spec.entities[subject][0]
        )
        for kpi, value in zip(KPI_ORDER, values, strict=True):
            kpis.append(
                {
                    "run_id": run_id,
                    "problem_id": problem_id,
                    "eval_split": "full",
                    "fold": 0,
                    "basis": "event_conditional",
                    "level": level,
                    "subject_id": "portfolio" if level == "portfolio" else subject,
                    "kpi": kpi,
                    "beta": spec.beta if kpi in KPI_ORDER[:2] else None,
                    "value": None if math.isnan(value) else value,
                    "ci_low": None,
                    "ci_high": None,
                    "ci_level": None,
                    "n_bootstrap": None,
                }
            )
    return RunTables(
        runs=RUNS.from_rows(runs),
        entities=ENTITIES.from_rows(entities),
        payouts=PAYOUTS.from_rows(payouts),
        kpis=KPIS.from_rows(kpis),
        exceedance=EXCEEDANCE.empty(),
    )


def write_runs(root: Path, specs: Sequence[RunSpec]) -> ResultStore:
    """Write runs into a result store at ``root``."""
    store = ResultStore(root)
    for spec in specs:
        store.write_run(_tables(spec), {"run_id": spec.run_id}, overwrite=True)
    return store


def _ind_params(budget_loading: float) -> dict[str, Any]:
    return {
        "attachment": 20.0,
        "limit": 70.0,
        "n_bins": 2,
        "n_assets": 2,
        "budget_loading": budget_loading,
        "noise_level": 0.3,
    }


def mini_runs(
    *,
    kpi_offsets: Mapping[tuple[str, str, int], float] | None = None,
    payout_offsets: Mapping[str, float] | None = None,
    objective_offsets: Mapping[str, float] | None = None,
) -> list[RunSpec]:
    """The store runs that reproduce the mini golden.

    ``kpi_offsets`` maps (record, subject, KPI position) to a relative change
    of our value, ``payout_offsets`` an entity of record 1 to an absolute
    change of its top level, ``objective_offsets`` a problem of record 1 to a
    relative change of its objective value.
    """
    kpi_offsets = kpi_offsets or {}
    payout_offsets = payout_offsets or {}
    objective_offsets = objective_offsets or {}

    def kpis(record: str, subject: str) -> tuple[float, ...]:
        return tuple(
            v * (1 + kpi_offsets.get((record, subject, i), 0.0))
            for i, v in enumerate(GOLDEN_KPIS[(record, subject)])
        )

    individual = RunSpec(
        name="individual-expected-uncovered",
        scope="individual",
        objective="expected_uncovered",
        parameters=_ind_params(1.0),
        problems={
            "A1": ("optimal", 20.0 * (1 + objective_offsets.get("A1", 0.0))),
            "A2": ("optimal", 10.0 * (1 + objective_offsets.get("A2", 0.0))),
        },
        entities={"A1": ("A1", ("A1",)), "A2": ("A2", ("A2",))},
        payouts={
            "A1": (0.0, 100.0 + payout_offsets.get("A1", 0.0)),
            "A2": (10.0, 200.0 + payout_offsets.get("A2", 0.0)),
        },
        kpis={
            ("portfolio", "Portfolio"): kpis("ind", "Portfolio"),
            ("entity", "A1"): kpis("ind", "A1"),
            ("entity", "A2"): kpis("ind", "A2"),
        },
    )
    cluster = RunSpec(
        name="cluster-weighted-cvar",
        scope="cluster",
        objective="weighted_cvar",
        parameters={
            **_ind_params(1.0),
            "alpha": 0.5,
            "beta": 0.9,
            "n_clusters": 1,
            "beta_tail": 0.9,
            "linkage": "ward",
        },
        problems={"portfolio": ("optimal", 123.0)},
        entities={"C1": ("portfolio", ("A1", "A2"))},
        payouts={"C1": (5.0, 300.0)},
        kpis={
            ("portfolio", "Portfolio"): kpis("clu", "Portfolio"),
            ("entity", "C1"): kpis("clu", "C1"),
        },
    )
    dropped = RunSpec(
        name="individual-mse-budget-0.5",
        scope="individual",
        objective="mse",
        parameters=_ind_params(0.5),
        problems={"A1": ("optimal", 7.0), "A2": ("infeasible", None)},
        entities={"A1": ("A1", ("A1",)), "A2": ("A2", ("A2",))},
        payouts={"A1": (0.0, 50.0)},
        source="budget_loading_sweep",
    )
    return [individual, cluster, dropped]


@pytest.fixture
def mini_specs() -> Callable[..., list[RunSpec]]:
    """:func:`mini_runs`, for tests that edit a run before writing it."""
    return mini_runs


@pytest.fixture
def make_store(tmp_path: Path) -> Callable[..., ResultStore]:
    """Factory: ``make_store(specs=None, **offsets)`` writes a store."""

    def factory(
        specs: Sequence[RunSpec] | None = None,
        **offsets: Mapping[Any, float],
    ) -> ResultStore:
        root = tmp_path / f"store-{len(list(tmp_path.glob('store-*')))}"
        return write_runs(root, mini_runs(**offsets) if specs is None else specs)

    return factory
