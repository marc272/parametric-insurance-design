"""Parity of the petals prototype (``petals_parametric``) with the core (MAR-168).

The prototype never imports the core (``test_petals_parametric_isolation.py``);
here the core is the oracle. For the same index, losses, years, payout,
budget, pricing and objective, the optimal objective value of every design
problem must match the core's within :data:`RTOL` (relative):

* on a small synthetic set: both scopes, the three objectives, pure and
  loaded pricing, the annual and the event basis, both attachment modes, the
  full sample and a training block of years;
* on the committed thesis fixture (``parity/tests/data/thesis_eventset``,
  9 assets, 10,000 years, no noise): both scopes, the three objectives,
  pure pricing, ``Budget(1.0)``, the thesis payout (15 steps on [20, 70]
  m/s) and weighted-CVaR parameters (``alpha = 0.9``, ``beta = 0.95``),
  annual basis, both attachment modes;
* on CLIMADA objects from the adapter's pipeline: the prototype's two index
  builders reproduce the adapter's ``CentroidWindIndex`` and
  ``CatInCircleIndex``, and a design from the hazard, exposures and impact
  matches the core's design on the EventSet the pipeline wrote.

Objective values are compared, not levels: individual designs with empty
steps, and the per-unit split of joint designs, are not unique (an optimal
value is).

Core solver policies:

* linear objectives: the core's default policy (Clarabel first), and on the
  thesis fixture also HiGHS (:data:`HIGHS_POLICY`), the prototype's solver,
  which must give the same optimum within :data:`RTOL_SAME_LP`: the two
  build the same LP;
* mean squared error: the core's default policy with OSQP at ``1e-10``
  instead of ``1e-8`` (:data:`QP_POLICY`). At ``1e-8`` OSQP's solution of
  the thesis fixture's first-bin problem A3 violates the budget by about
  ``2e-8`` (scaled), which lowers its objective by ``1.1e-6`` relative
  below the feasible optimum that the prototype's Clarabel returns.

Every policy keeps the core's guard against OSQP's all-zero "optimal" points.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
import scipy.sparse as sp
from climada.engine import Impact, ImpactCalc
from numpy.typing import NDArray

import parametric_insurance_design as pid
import petals_parametric as pm
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.solve import DEFAULT_POLICY, SolverPolicy
from parametric_insurance_design_climada.cat_in_circle import CatInCircleIndex
from parametric_insurance_design_climada.hooks import CentroidWindIndex, HazardBatch
from parametric_insurance_design_climada.pipeline import build_eventset
from petals_parametric.payout import BelowAttachment

from .conftest import N_YEARS

RTOL = 1e-6
"""Largest relative difference of an optimal objective value."""

RTOL_SAME_LP = 1e-9
"""Largest relative difference when the core also solves the LP with HiGHS."""

HIGHS_POLICY = SolverPolicy(lp_solvers=("HIGHS",), qp_solvers=("CLARABEL",))
"""The core with HiGHS for the linear objectives, as the prototype."""

QP_POLICY = SolverPolicy(
    solver_options={
        "OSQP": {"eps_abs": 1e-10, "eps_rel": 1e-10, "max_iter": 1_000_000},
        "SCS": {"max_iters": 20000},
    }
)
"""The core's default policy with OSQP at ``1e-10`` (module docstring)."""

REPO = Path(__file__).resolve().parents[3]
THESIS_EVENTSET = REPO / "parity" / "tests" / "data" / "thesis_eventset"

# --- building the same inputs for both ---------------------------------------


def _eventset(
    index: NDArray[np.float64],
    loss: NDArray[np.float64],
    years: NDArray[np.int64],
    n_years: int,
) -> EventSet:
    """A core EventSet with one row per event and rate ``1 / n_years``."""
    n_events, n_locations = index.shape
    events = pd.DataFrame(
        {
            "event_id": [f"e{i}" for i in range(n_events)],
            "year": years,
            "rate": np.full(n_events, 1.0 / n_years),
            "draw_id": np.zeros(n_events, dtype=np.int64),
            "scenario_id": ["parity"] * n_events,
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": [f"U{j}" for j in range(n_locations)],
            "lat": np.full(n_locations, 25.0),
            "lon": np.linspace(-81.0, -80.0, n_locations),
            "value": np.full(n_locations, 100.0),
            "name": [f"Unit {j}" for j in range(n_locations)],
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name="synthetic", release="1"),
        index=IndexDefinition(definition="synthetic", unit="m/s"),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=n_years,
        scenario="petals prototype parity",
        provenance=Provenance(
            producer="tests",
            producer_version="0",
            created_at=datetime(2026, 11, 6, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events, locations=locations, index=index, loss=loss, metadata=metadata
    )


def _climada_inputs(es: EventSet) -> tuple[pm.ParametricIndex, Impact]:
    """The prototype's index and a CLIMADA ``Impact`` with the EventSet's data."""
    n = es.n_rows
    coords = es.locations[["lat", "lon"]].to_numpy(dtype=np.float64)
    names = es.events["event_id"].astype(str).tolist()
    event_id = np.arange(1, n + 1)
    index = pm.ParametricIndex(
        values=es.index,
        event_id=event_id,
        event_name=names,
        frequency=es.rates,
        event_year=es.events["year"].to_numpy(dtype=np.int64),
        years=np.arange(es.metadata.n_years),
        unit_id=tuple(es.location_ids),
        coords=coords,
        unit=es.metadata.index.unit,
        definition=es.metadata.index.definition,
    )
    impact = Impact(
        event_id=event_id,
        event_name=names,
        date=np.ones(n, dtype=np.int64),
        frequency=es.rates,
        coord_exp=coords,
        eai_exp=es.rates @ es.loss,
        at_event=es.loss.sum(axis=1),
        aai_agg=float((es.rates @ es.loss).sum()),
        imp_mat=sp.csr_matrix(es.loss),
        unit="USD",
    )
    return index, impact


@dataclass(frozen=True)
class Setup:
    """One design setup, in the core's and in the prototype's terms."""

    scope: str
    objective: str
    pricing: str
    basis: str
    mode: BelowAttachment
    budget: float = 0.6
    n_steps: int = 4
    alpha: float = 0.9
    beta: float = 0.9

    def core_args(self) -> dict[str, Any]:
        """Arguments of ``pid.design`` (without the EventSet and sample)."""
        objective = {
            "mse": pid.MSE(),
            "expected_uncovered": pid.ExpectedUncovered(),
            "weighted_cvar": pid.WeightedCVaR(self.alpha, self.beta),
        }[self.objective]
        pricing = (
            pid.PurePremium()
            if self.pricing == "pure"
            else pid.CostOfCapitalLoad(rate=0.1, q=0.9)
        )
        return {
            "scope": pid.Portfolio() if self.scope == "portfolio" else pid.Individual(),
            "payout": pid.StepPayout(
                20.0, 70.0, self.n_steps, below_attachment=self.mode
            ),
            "objective": objective,
            "basis": pid.Basis(self.basis),
            "pricing": pricing,
            "constraints": (pid.Budget(self.budget),),
        }

    def prototype_args(self) -> dict[str, Any]:
        """Keyword arguments of ``pm.calibrate`` (without index, impact, years)."""
        objective = {
            "mse": pm.MeanSquaredError(),
            "expected_uncovered": pm.ExpectedUncovered(),
            "weighted_cvar": pm.WeightedCVaR(alpha=self.alpha, beta=self.beta),
        }[self.objective]
        pricing = (
            pm.PurePremium()
            if self.pricing == "pure"
            else pm.CostOfCapitalLoad(rate=0.1, q=0.9)
        )
        return {
            "scope": self.scope,
            "payout": pm.StepPayout(
                20.0, 70.0, self.n_steps, below_attachment=self.mode
            ),
            "objective": objective,
            "basis": self.basis,
            "pricing": pricing,
            "budget": self.budget,
        }

    def policy(self) -> SolverPolicy:
        """The core's solver policy for this setup (module docstring)."""
        return QP_POLICY if self.objective == "mse" else DEFAULT_POLICY


def compare(
    es: EventSet,
    setup: Setup,
    years: NDArray[np.int64] | None = None,
    policy: SolverPolicy | None = None,
) -> list[tuple[str, float, float]]:
    """Solve a setup with both; return ``(problem_id, core, prototype)`` values."""
    sample = None
    if years is not None:
        rows = np.isin(es.events["year"].to_numpy(), years)
        sample = Sample(name="train", rows=rows, years=years)
    core = pid.design(
        es,
        **setup.core_args(),
        sample=sample,
        policy=setup.policy() if policy is None else policy,
    )
    index, impact = _climada_inputs(es)
    cover = pm.calibrate(index, impact, **setup.prototype_args(), years=years)
    assert [r.problem_id for r in core] == [p.problem_id for p in cover.problems]
    return [
        (r.problem_id, r.objective_value, p.objective_value)
        for r, p in zip(core, cover.problems, strict=True)
    ]


def _assert_parity(rows: list[tuple[str, float, float]], rtol: float = RTOL) -> None:
    for problem_id, core, prototype in rows:
        assert prototype == pytest.approx(core, rel=rtol, abs=1e-12), problem_id


# --- small synthetic set -------------------------------------------------------


def _synthetic(seed: int) -> EventSet:
    """Three units, 40 events in 60 years (some years hold several)."""
    rng = np.random.default_rng(seed)
    index = rng.uniform(0.0, 80.0, size=(40, 3))
    noise = rng.lognormal(0.0, 0.5, size=(40, 3))
    loss = np.where(index > 25.0, (index - 25.0) ** 2 * noise, 0.0)
    loss[rng.random((40, 3)) < 0.15] = 0.0
    years = np.sort(rng.integers(0, 60, size=40))
    return _eventset(index, loss, years, 60)


SYNTHETIC_SETUPS = [
    Setup(scope, objective, pricing, basis, mode)
    for scope in ("individual", "portfolio")
    for objective in ("expected_uncovered", "weighted_cvar", "mse")
    for pricing in ("pure", "cost_of_capital")
    for basis in ("annual", "event")
    for mode in ("zero", "first_bin")
]


@pytest.mark.parametrize("seed", [0, 1])
@pytest.mark.parametrize(
    "setup",
    SYNTHETIC_SETUPS,
    ids=lambda s: f"{s.scope}-{s.objective}-{s.pricing}-{s.basis}-{s.mode}",
)
def test_synthetic_objective_values_match_the_core(seed: int, setup: Setup) -> None:
    _assert_parity(compare(_synthetic(seed), setup))


@pytest.mark.parametrize("objective", ["expected_uncovered", "weighted_cvar", "mse"])
@pytest.mark.parametrize("scope", ["individual", "portfolio"])
def test_synthetic_training_years_match_the_core(scope: str, objective: str) -> None:
    setup = Setup(scope, objective, "pure", "annual", "zero")
    _assert_parity(compare(_synthetic(2), setup, years=np.arange(42)))


# --- the thesis fixture ---------------------------------------------------------


@pytest.fixture(scope="module")
def thesis() -> EventSet:
    return EventSet.from_parquet(THESIS_EVENTSET)


THESIS_SETUPS = [
    Setup(
        scope,
        objective,
        "pure",
        "annual",
        mode,
        budget=1.0,
        n_steps=15,
        alpha=0.9,
        beta=0.95,
    )
    for scope in ("individual", "portfolio")
    for objective in ("expected_uncovered", "weighted_cvar", "mse")
    for mode in ("zero", "first_bin")
]


@pytest.mark.parametrize(
    "setup", THESIS_SETUPS, ids=lambda s: f"{s.scope}-{s.objective}-{s.mode}"
)
def test_thesis_fixture_objective_values_match_the_core(
    thesis: EventSet, setup: Setup
) -> None:
    rows = compare(thesis, setup)
    assert len(rows) == (9 if setup.scope == "individual" else 1)
    _assert_parity(rows)


@pytest.mark.parametrize(
    "setup",
    [s for s in THESIS_SETUPS if s.objective != "mse"],
    ids=lambda s: f"{s.scope}-{s.objective}-{s.mode}",
)
def test_thesis_fixture_lps_are_the_cores_lps(thesis: EventSet, setup: Setup) -> None:
    _assert_parity(compare(thesis, setup, policy=HIGHS_POLICY), rtol=RTOL_SAME_LP)


# --- CLIMADA objects from the adapter's pipeline --------------------------------


@dataclass(frozen=True)
class _Capture:
    """An index builder that records the pipeline's batch and writes the wind."""

    batches: list[HazardBatch]

    def describe(self, wind_field: str) -> Any:  # noqa: ANN401
        return CentroidWindIndex().describe(wind_field)

    def parameters(self) -> dict[str, Any]:
        return {"kind": "capture"}

    def build(self, batch: HazardBatch) -> NDArray[np.float64]:
        self.batches.append(batch)
        return batch.wind


@pytest.fixture
def pipeline(make_config: Callable[..., Any]) -> tuple[EventSet, HazardBatch]:
    """The adapter's EventSet of the synthetic catalogue, and its one batch."""
    capture = _Capture([])
    result = build_eventset(make_config(batch_size=3), index_builder=capture)
    (batch,) = capture.batches
    return result.eventset, batch


def test_index_builders_match_the_adapter(
    pipeline: tuple[EventSet, HazardBatch],
) -> None:
    es, batch = pipeline
    years = np.arange(N_YEARS)
    event_year = es.events["year"].to_numpy()
    point = pm.ParametricIndex.from_hazard(
        batch.hazard, batch.exposures, event_year=event_year, years=years
    )
    np.testing.assert_array_equal(point.values, CentroidWindIndex().build(batch))
    np.testing.assert_array_equal(point.values, es.index)
    for radius in (10.0, 30.0, 110.0, 150.0):
        for metric in ("category", "max_wind"):
            for step in (None, 0.5):
                circle = pm.ParametricIndex.from_cat_in_circle(
                    batch.tracks,
                    batch.exposures,
                    hazard=batch.hazard,
                    radius_km=radius,
                    metric=metric,  # type: ignore[arg-type]
                    track_step_hours=step,
                    event_year=event_year,
                    years=years,
                )
                adapter = CatInCircleIndex(
                    radius_km=radius,
                    metric=metric,
                    track_step_hours=step,  # type: ignore[arg-type]
                ).build(batch)
                np.testing.assert_array_equal(circle.values, adapter)


def test_a_design_on_climada_objects_matches_the_core_on_the_eventset(
    pipeline: tuple[EventSet, HazardBatch],
) -> None:
    es, batch = pipeline
    hazard = batch.hazard
    # IRIS tracks all start on one date, so the simulation years and the
    # frequency 1 / N come from the catalogue, not from the dates.
    hazard.frequency = np.full(hazard.size, 1.0 / N_YEARS)
    impact = ImpactCalc(batch.exposures, batch.impact_functions, hazard).impact(
        save_mat=True
    )
    np.testing.assert_allclose(impact.imp_mat.toarray(), es.loss, rtol=1e-12, atol=0)
    index = pm.ParametricIndex.from_hazard(
        hazard,
        batch.exposures,
        event_year=es.events["year"].to_numpy(),
        years=np.arange(N_YEARS),
    )
    designs = [("individual", "expected_uncovered"), ("portfolio", "weighted_cvar")]
    for scope, objective in designs:
        setup = Setup(scope, objective, "pure", "annual", "zero", budget=0.8, beta=0.8)
        core = pid.design(es, **setup.core_args(), policy=setup.policy())
        cover = pm.calibrate(index, impact, **setup.prototype_args())
        for result, problem in zip(core, cover.problems, strict=True):
            assert problem.objective_value == pytest.approx(
                result.objective_value, rel=RTOL, abs=1e-9
            )
