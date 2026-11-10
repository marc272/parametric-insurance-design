"""The premium of a solution is ``premium_value`` of its realised payout (MAR-143).

``solve.solve(built)`` records ``SolveResult.premium`` as
``pricing.premium_value`` of the realised payout in numpy, exact and without
a solver call, with the pricing the problem was built with
(``BuiltProblem.pricing``, MAR-171); the runner passes no pricing. Checked
for both pricings, with the budget binding and slack, on two bases, against
``premium_value`` and the in-sample ``premium`` KPI, bit for bit. The
``pricing`` keyword stays (MAR-143): an equal pricing gives the same premium,
a different one raises ``ComponentConfigError`` before any solver runs.
"""

from __future__ import annotations

import copy
import dataclasses
import pickle
from collections.abc import Callable
from pathlib import Path

import cvxpy as cp
import numpy as np
import pytest
from numpy.typing import NDArray

from parametric_insurance_design.basis import Basis
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import ComponentConfigError
from parametric_insurance_design.evaluate import kpis
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import parse_config
from parametric_insurance_design.experiment.runner import load_input, run_single
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import Constraint, Objective, Pricing
from parametric_insurance_design.objectives import MSE, WeightedCVaR
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import CostOfCapitalLoad, PurePremium
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.scopes import Individual, Portfolio
from parametric_insurance_design.solve import solve

from .test_bootstrap import random_rows

PAYOUT = StepPayout(attachment=1.0, limit=15.0, n_bins=3)
PRICINGS: dict[str, Pricing] = {
    "pure": PurePremium(),
    "loaded": CostOfCapitalLoad(rate=0.1, q=0.9),
    "cvar": CostOfCapitalLoad(rate=1.0, q=0.8),
}
OBJECTIVES: dict[str, Objective] = {
    "wcvar": WeightedCVaR(alpha=0.9, beta=0.8),
    "mse": MSE(),
}
TIGHT = Budget(0.3)
"""A budget that binds: every objective here wants more cover than this."""
SLACK = Budget(50.0)
"""A budget that does not bind."""


@pytest.fixture
def data(toy_eventset: EventSet) -> EventSet:
    """Twelve years, two draws, several events per year, two locations."""
    return random_rows(toy_eventset, n_years=12, n_draws=2, seed=143)


def realised_premium(
    built: BuiltProblem, theta: NDArray[np.float64], p: Pricing
) -> float:
    """``premium_value`` of the objective-level payout of ``theta`` (loss units)."""
    ctx = built.context
    entity = ctx.payout_structure.evaluate(ctx.problem.index, theta)
    return p.premium_value(np.vstack(list(entity.T)).sum(axis=0), ctx.measure)


def build(
    data: EventSet,
    pricing: Pricing,
    objective: Objective,
    constraints: tuple[Constraint, ...],
    basis: Basis,
) -> tuple[BuiltProblem, ...]:
    return build_problems(
        data, Portfolio(), PAYOUT, objective, pricing, constraints, basis=basis
    )


@pytest.mark.parametrize("basis", [Basis.EVENT_CONDITIONAL, Basis.ANNUAL])
@pytest.mark.parametrize("budget", ["tight", "slack", "none"])
@pytest.mark.parametrize("objective", sorted(OBJECTIVES))
@pytest.mark.parametrize("pricing", sorted(PRICINGS))
def test_recorded_premium_is_premium_value_of_the_realised_payout(
    data: EventSet, pricing: str, objective: str, budget: str, basis: Basis
) -> None:
    p = PRICINGS[pricing]
    constraints = {"tight": (TIGHT,), "slack": (SLACK,), "none": ()}[budget]
    (built,) = build(data, p, OBJECTIVES[objective], constraints, basis)
    assert built.pricing is p
    result = solve(built)  # no pricing argument (MAR-171)
    # Exactly premium_value of the realised payout: no rounding allowance.
    assert result.premium == realised_premium(built, result.theta, p)
    # ... which is the in-sample premium KPI of the design problem, bit for bit.
    table = kpis(
        data, Portfolio(), [result], basis=basis, beta=0.9, run_id="r", pricing=p
    )
    row = (table["level"] == "problem") & (table["kpi"] == "premium")
    assert table.loc[row, "value"].tolist() == [result.premium]
    # The budget binds or is slack, as intended (loss units).
    expected_loss = built.context.measure.expectation(built.context.problem.loss)
    tol = 1e-6 * result.scale
    if budget == "tight":
        assert result.premium == pytest.approx(TIGHT.loading * expected_loss, abs=tol)
    elif budget == "slack":
        assert result.premium < SLACK.loading * expected_loss - 1.0


@pytest.mark.parametrize("pricing", sorted(PRICINGS))
def test_individual_scope_records_each_problem_premium(
    data: EventSet, pricing: str
) -> None:
    p = PRICINGS[pricing]
    built = build_problems(
        data,
        Individual(),
        PAYOUT,
        OBJECTIVES["wcvar"],
        p,
        (TIGHT,),
        basis=Basis.ANNUAL,
    )
    results = [solve(b) for b in built]
    assert len(results) == 2
    for b, r in zip(built, results, strict=True):
        assert r.premium == realised_premium(b, r.theta, p)
    table = kpis(
        data, Individual(), results, basis=Basis.ANNUAL, beta=0.9, run_id="r", pricing=p
    )
    rows = table[(table["level"] == "problem") & (table["kpi"] == "premium")]
    assert dict(zip(rows["problem_id"], rows["value"], strict=True)) == {
        r.problem_id: r.premium for r in results
    }


def counting_solves(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count every ``cvxpy.Problem.solve`` call, inner ones included."""
    calls: list[int] = []
    real: Callable[..., object] = cp.Problem.solve

    def counted(self: cp.Problem, *args: object, **kwargs: object) -> object:
        calls.append(1)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(cp.Problem, "solve", counted)
    return calls


@pytest.mark.parametrize("budget", ["tight", "slack"])
def test_no_solver_call_when_reading_a_loaded_premium(
    data: EventSet, budget: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    p = PRICINGS["loaded"]
    constraints = (TIGHT,) if budget == "tight" else (SLACK,)
    (built,) = build(data, p, OBJECTIVES["wcvar"], constraints, Basis.ANNUAL)
    calls = counting_solves(monkeypatch)
    result = solve(built)
    # One solver call: the accepted attempt. No inner solve for the premium,
    # the budget's constraint violation or anything else.
    assert len(result.attempts) == 1
    assert len(calls) == 1
    # Reading the premium term's value solves nothing either: it is the plain
    # Rockafellar-Uryasev function at the solver's zeta.
    bound = built.premium.expression.value
    assert bound is not None
    assert len(calls) == 1
    # That value is an upper bound on the loaded premium (scaled units).
    assert float(bound) * result.scale >= result.premium - 1e-6 * result.scale


def equal_copies(p: Pricing) -> dict[str, Pricing]:
    """Pricings equal to ``p``: itself, copies and a fresh instance."""
    fresh = (
        CostOfCapitalLoad(rate=int(p.rate) if p.rate == 1.0 else p.rate, q=p.q)
        if isinstance(p, CostOfCapitalLoad)
        else PurePremium()
    )
    return {
        "same": p,
        "deepcopy": copy.deepcopy(p),
        "pickled": pickle.loads(pickle.dumps(p)),
        "fresh": fresh,
    }


@pytest.mark.parametrize("variant", ["same", "deepcopy", "pickled", "fresh"])
@pytest.mark.parametrize("pricing", sorted(PRICINGS))
def test_an_equal_pricing_keyword_records_the_same_premium(
    data: EventSet, pricing: str, variant: str
) -> None:
    p = PRICINGS[pricing]
    given = equal_copies(p)[variant]
    # Frozen dataclasses compare by class and fields (``rate=1`` is stored
    # as ``1.0``), so every variant equals the built pricing.
    assert given == p
    (built,) = build(data, p, OBJECTIVES["wcvar"], (TIGHT,), Basis.ANNUAL)
    result = solve(built, pricing=given)
    assert result.premium == realised_premium(built, result.theta, p)


MISMATCHES: dict[str, tuple[Pricing, Pricing]] = {
    "pure-vs-loaded": (PurePremium(), CostOfCapitalLoad(rate=0.1, q=0.9)),
    "loaded-vs-pure": (CostOfCapitalLoad(rate=0.1, q=0.9), PurePremium()),
    "other-rate": (
        CostOfCapitalLoad(rate=0.1, q=0.9),
        CostOfCapitalLoad(rate=0.2, q=0.9),
    ),
    "other-q": (
        CostOfCapitalLoad(rate=0.1, q=0.9),
        CostOfCapitalLoad(rate=0.1, q=0.95),
    ),
    # Same premium as PurePremium, but another pricing: refused all the same.
    "zero-rate-vs-pure": (PurePremium(), CostOfCapitalLoad(rate=0.0, q=0.9)),
}


@pytest.mark.parametrize("case", sorted(MISMATCHES))
def test_a_mismatched_pricing_is_refused_before_any_solve(
    data: EventSet, case: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    built_with, given = MISMATCHES[case]
    assert given != built_with
    (built,) = build(data, built_with, OBJECTIVES["wcvar"], (TIGHT,), Basis.ANNUAL)
    calls = counting_solves(monkeypatch)
    with pytest.raises(ComponentConfigError, match="was built with pricing") as info:
        solve(built, pricing=given)
    assert repr(built_with) in str(info.value)
    assert repr(given) in str(info.value)
    assert calls == []  # refused before any solver ran
    assert built.problem.status is None


@pytest.mark.parametrize("pricing", sorted(PRICINGS))
def test_a_problem_without_a_pricing_records_the_term_value(
    data: EventSet, pricing: str
) -> None:
    p = PRICINGS[pricing]
    (built,) = build(data, p, OBJECTIVES["wcvar"], (TIGHT,), Basis.EVENT_CONDITIONAL)
    # A problem assembled by hand, without its pricing (the old behaviour).
    bare = dataclasses.replace(built, pricing=None)
    result = solve(bare)
    term = float(built.premium.expression.value) * result.scale  # type: ignore[arg-type]
    assert result.premium == term
    exact = realised_premium(built, result.theta, p)
    tol = 1e-6 * result.scale
    if isinstance(p, PurePremium):
        assert result.premium == pytest.approx(exact, abs=tol)
    else:
        # The Rockafellar-Uryasev bound: at least the loaded premium.
        assert result.premium >= exact - tol
    # Given a pricing, such a problem records premium_value under it; there
    # is no built pricing to check it against.
    priced = solve(bare, pricing=p)
    assert priced.premium == realised_premium(built, priced.theta, p)


def test_solve_rejects_a_pricing_that_is_not_one(data: EventSet) -> None:
    (built,) = build(
        data, PurePremium(), OBJECTIVES["wcvar"], (TIGHT,), Basis.EVENT_CONDITIONAL
    )
    with pytest.raises(ComponentConfigError, match="pricing must be a Pricing"):
        solve(built, pricing="pure")  # type: ignore[arg-type]
    bare = dataclasses.replace(built, pricing=None)
    with pytest.raises(ComponentConfigError, match="pricing must be a Pricing"):
        solve(bare, pricing="pure")  # type: ignore[arg-type]


def test_runner_records_the_premium_value(data: EventSet, tmp_path: Path) -> None:
    path = tmp_path / "eventset"
    data.to_parquet(path)
    config = parse_config(
        {
            "schema_version": 1,
            "name": "premium",
            "eventset": {"path": str(path)},
            "basis": "annual",
            "payout": {"attachment": 1.0, "limit": 15.0, "n_bins": 3},
            "scopes": [{"kind": "individual"}],
            "objectives": [{"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.8}],
            "pricing": {"kind": "cost_of_capital", "rate": 0.1, "q": 0.9},
            "constraints": [{"kind": "budget", "loading": 50.0}],
            "evaluation": {"beta": 0.9},
            "output": {"directory": str(tmp_path / "results")},
        }
    )
    (run,) = config.single_runs()
    store = ResultStore(tmp_path / "results")
    outcome = run_single(run, load_input(run), store)
    assert outcome.ok
    runs = store.read("runs", run_ids=[outcome.run_id])
    table = store.read("kpis", run_ids=[outcome.run_id])
    rows = table[(table["level"] == "problem") & (table["kpi"] == "premium")]
    premium_kpi = dict(zip(rows["problem_id"], rows["value"], strict=True))
    assert len(premium_kpi) == 2
    # Calibration and evaluation sample are the full EventSet: the recorded
    # premium is the in-sample premium KPI, bit for bit, budget slack.
    assert dict(zip(runs["problem_id"], runs["premium"], strict=True)) == premium_kpi
    manifest = store.manifest(outcome.run_id)
    assert {e["problem_id"]: e["premium"] for e in manifest["problems"]} == premium_kpi
