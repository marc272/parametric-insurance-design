"""Tests for the solver policy (MAR-14, SPEC §3.1 C3).

Two groups:

- Policy and failure handling on the three-event toy EventSet
  (``conftest.py``), with real components. Failures that real solvers do not
  produce on demand (crashes, unknown statuses, a missing solver) are
  injected by patching the cvxpy problem of one ``BuiltProblem``.
- MAR-14 acceptance on the parity fixture (``parity/tests/data/
  thesis_eventset``, MAR-9): the nine scope x objective combinations of the
  thesis default configuration solve, and an injected infeasible problem
  raises ``SolveError``. Comparing the values with the thesis golden tables
  is MAR-68; ``parity/BENCHMARK.md`` records the observations and timings.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

import cvxpy as cp
import numpy as np
import pandas as pd
import pytest
from cvxpy.error import SolverError
from numpy.typing import NDArray

from parametric_insurance_design import solve as solve_module
from parametric_insurance_design.basis import Basis
from parametric_insurance_design.clustering import ThesisWardClustering
from parametric_insurance_design.constraints import Budget
from parametric_insurance_design.errors import (
    ConfigError,
    InfeasibleError,
    SolveError,
    UnboundedError,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Constraint,
    Objective,
    ProblemContext,
    Scope,
    Term,
)
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.objectives import MSE, ExpectedUncovered, WeightedCVaR
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.problem import BuiltProblem, build_problems
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio
from parametric_insurance_design.solve import (
    DEFAULT_POLICY,
    FAILURE_PRECEDENCE,
    NOT_INSTALLED,
    OSQP_OPTIONS,
    THESIS_POLICY,
    SolverPolicy,
    SolveStatus,
    is_qp,
    solve,
)

TOY_PAYOUT = StepPayout(attachment=20.0, limit=60.0, n_bins=2)
BASIS = Basis.EVENT_CONDITIONAL


@dataclass(frozen=True)
class MinimumPremium(Constraint):
    """Constraint double: premium >= loading * E[L] (infeasible with Budget)."""

    name: ClassVar[str] = "minimum_premium"
    loading: float

    def build(self, ctx: ProblemContext, premium: Term) -> tuple[cp.Constraint, ...]:
        return (premium.expression >= self.loading * ctx.expected_loss,)


def toy_built(
    eventset: EventSet,
    objective: Objective | None = None,
    constraints: tuple[Constraint, ...] = (Budget(1.0),),
) -> BuiltProblem:
    (built,) = build_problems(
        eventset,
        Portfolio(),
        TOY_PAYOUT,
        ExpectedUncovered() if objective is None else objective,
        PurePremium(),
        constraints,
        basis=BASIS,
    )
    return built


def with_fake_solve(
    monkeypatch: pytest.MonkeyPatch, built: BuiltProblem, outcomes: dict[str, Any]
) -> None:
    """Replace ``built.problem.solve``: per solver, raise or set a status.

    A solver whose outcome is ``"real"`` is solved for real.
    """
    problem = built.problem
    real_solve = problem.solve

    def fake(*, solver: str, **kwargs: object) -> None:
        outcome = outcomes[solver]
        if outcome == "real":
            real_solve(solver=solver, **kwargs)
        elif isinstance(outcome, Exception):
            raise outcome
        else:
            problem._status = outcome  # pyright: ignore[reportAttributeAccessIssue]

    monkeypatch.setattr(problem, "solve", fake)


# -- policy ------------------------------------------------------------------


def test_default_policy_follows_the_thesis() -> None:
    assert DEFAULT_POLICY.lp_solvers == ("CLARABEL", "HIGHS", "SCS")
    assert DEFAULT_POLICY.qp_solvers == ("OSQP", "CLARABEL")
    assert DEFAULT_POLICY.accept_inaccurate
    assert dict(DEFAULT_POLICY.solver_options["SCS"]) == {"max_iters": 20000}
    # The one deviation from the thesis: OSQP at interior-point accuracy.
    assert set(DEFAULT_POLICY.solver_options) == {"OSQP", "SCS"}
    assert DEFAULT_POLICY.accepted == {
        SolveStatus.OPTIMAL,
        SolveStatus.OPTIMAL_INACCURATE,
    }
    assert SolverPolicy(accept_inaccurate=False).accepted == {SolveStatus.OPTIMAL}


def test_default_osqp_options_are_tight() -> None:
    # MAR-98: cvxpy's OSQP defaults (eps 1e-5, max_iter 10000) leave
    # violations of ~1.5e-5 in scaled units when polishing fails.
    options = dict(DEFAULT_POLICY.solver_options["OSQP"])
    assert options == dict(OSQP_OPTIONS)
    assert options == {"eps_abs": 1e-8, "eps_rel": 1e-8, "max_iter": 100_000}
    with pytest.raises(TypeError):
        OSQP_OPTIONS["eps_abs"] = 1e-5  # type: ignore[index]


def test_thesis_policy_is_the_pre_mar98_default() -> None:
    # Main's DEFAULT_POLICY before MAR-98, field for field: OSQP at cvxpy's
    # defaults, everything else as the default.
    assert THESIS_POLICY.lp_solvers == DEFAULT_POLICY.lp_solvers
    assert THESIS_POLICY.qp_solvers == DEFAULT_POLICY.qp_solvers
    assert THESIS_POLICY.accept_inaccurate is DEFAULT_POLICY.accept_inaccurate
    assert {k: dict(v) for k, v in THESIS_POLICY.solver_options.items()} == {
        "SCS": {"max_iters": 20000}
    }


def test_explicit_options_replace_the_defaults() -> None:
    # A policy that names its options runs OSQP with cvxpy's defaults, e.g.
    # to reproduce the thesis MSE values.
    policy = SolverPolicy(solver_options={"SCS": {"max_iters": 20000}})
    assert "OSQP" not in policy.solver_options


def test_policy_options_are_read_only() -> None:
    options = {"SCS": {"eps": 1e-6}}
    policy = SolverPolicy(solver_options=options)
    options["SCS"]["eps"] = 1.0
    assert policy.solver_options["SCS"]["eps"] == 1e-6
    with pytest.raises(TypeError):
        policy.solver_options["SCS"]["eps"] = 2.0  # type: ignore[index]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"lp_solvers": ()}, "lp_solvers must name at least one solver"),
        ({"qp_solvers": ("OSQP", "OSQP")}, "repeats a solver"),
        ({"lp_solvers": ("CLARABLE",)}, r"knows no solver \['CLARABLE'\]"),
        ({"qp_solvers": (1,)}, "must hold solver names"),
        ({"accept_inaccurate": 1}, "accept_inaccurate must be a bool"),
        ({"solver_options": {"SCSS": {}}}, r"solver_options: .*\['SCSS'\]"),
    ],
)
def test_invalid_policies_are_refused(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ConfigError, match=message):
        SolverPolicy(**kwargs)


def test_lists_are_stored_as_tuples() -> None:
    policy = SolverPolicy(lp_solvers=["SCS"])  # type: ignore[arg-type]
    assert policy.lp_solvers == ("SCS",)


def test_problem_class_selects_the_solver_list(toy_eventset: EventSet) -> None:
    lp = toy_built(toy_eventset)
    qp = toy_built(toy_eventset, MSE())
    cvar = toy_built(toy_eventset, WeightedCVaR(alpha=0.5, beta=0.5))
    assert (is_qp(lp.problem), is_qp(qp.problem), is_qp(cvar.problem)) == (
        False,
        True,
        False,
    )
    assert DEFAULT_POLICY.solvers_for(qp.problem) == DEFAULT_POLICY.qp_solvers
    assert DEFAULT_POLICY.solvers_for(lp.problem) == DEFAULT_POLICY.lp_solvers


# -- results -----------------------------------------------------------------


def test_result_matches_the_hand_solution(toy_eventset: EventSet) -> None:
    # Walking-skeleton optimum with the real components: with 2s + t <= 23
    # the budget covers event 3 (t = 16) and leaves s = 3.5 for bin 0.
    result = solve(toy_built(toy_eventset))
    assert result.status is SolveStatus.OPTIMAL
    assert result.solver == "CLARABEL"
    assert [a.solver for a in result.attempts] == ["CLARABEL"]
    assert result.scale == 16.0
    assert result.objective_value == pytest.approx(2.5 / 3, rel=1e-6)
    assert result.premium == pytest.approx(23 / 3, rel=1e-6)
    np.testing.assert_allclose(result.theta.sum(axis=0), [3.5, 16.0], rtol=1e-6)
    assert result.diagnostics["expected_uncovered"] == pytest.approx(2.5 / 3, rel=1e-6)
    assert result.diagnostics["max_constraint_violation_scaled"] < 1e-8
    assert "solver_solve_time" in result.diagnostics
    assert result.solve_seconds == pytest.approx(result.attempts[0].seconds)
    assert result.build_seconds > 0


def test_mse_is_reported_in_squared_loss_units(toy_eventset: EventSet) -> None:
    # Slack budget, two bins: bin 0 pays the mean of (1, 6) and bin 1 pays
    # 16, so the MSE is ((1 - 3.5)^2 + (6 - 3.5)^2) / 3 in loss units squared.
    built = toy_built(toy_eventset, MSE(), (Budget(2.0),))
    result = solve(built)
    assert result.solver in DEFAULT_POLICY.qp_solvers
    assert result.objective_value == pytest.approx(12.5 / 3, rel=1e-6)
    assert result.diagnostics["mse"] == pytest.approx(result.objective_value)
    np.testing.assert_allclose(result.theta.sum(axis=0), [3.5, 16.0], rtol=1e-6)


INACCURATE_WARNING = "ignore:Solution may be inaccurate:UserWarning"


@pytest.mark.filterwarnings(INACCURATE_WARNING)
def test_inaccurate_result_is_accepted_by_default(toy_eventset: EventSet) -> None:
    policy = SolverPolicy(lp_solvers=("SCS",), solver_options={"SCS": {"max_iters": 1}})
    result = solve(toy_built(toy_eventset), policy)
    assert result.status is SolveStatus.OPTIMAL_INACCURATE
    assert result.solver == "SCS"


@pytest.mark.filterwarnings(INACCURATE_WARNING)
def test_inaccurate_result_falls_back_when_refused(toy_eventset: EventSet) -> None:
    policy = SolverPolicy(
        lp_solvers=("SCS", "CLARABEL"),
        accept_inaccurate=False,
        solver_options={"SCS": {"max_iters": 1}},
    )
    result = solve(toy_built(toy_eventset), policy)
    assert result.solver == "CLARABEL"
    assert [(a.solver, a.status) for a in result.attempts] == [
        ("SCS", SolveStatus.OPTIMAL_INACCURATE),
        ("CLARABEL", SolveStatus.OPTIMAL),
    ]
    total = sum(a.seconds for a in result.attempts)
    assert result.solve_seconds == pytest.approx(total)


@pytest.mark.filterwarnings(INACCURATE_WARNING)
def test_only_inaccurate_results_raise_when_refused(toy_eventset: EventSet) -> None:
    policy = SolverPolicy(
        lp_solvers=("SCS",),
        accept_inaccurate=False,
        solver_options={"SCS": {"max_iters": 1}},
    )
    with pytest.raises(SolveError) as info:
        solve(toy_built(toy_eventset), policy)
    assert type(info.value) is SolveError
    assert info.value.status is SolveStatus.OPTIMAL_INACCURATE


# -- failures ----------------------------------------------------------------


def test_infeasible_problem_raises_with_every_attempt(toy_eventset: EventSet) -> None:
    built = toy_built(toy_eventset, constraints=(Budget(1.0), MinimumPremium(2.0)))
    policy = SolverPolicy(lp_solvers=("CLARABEL", "SCS"))
    with pytest.raises(InfeasibleError, match=r"\[portfolio\] no solver") as info:
        solve(built, policy)
    error = info.value
    assert error.problem_id == "portfolio"
    assert error.status is SolveStatus.INFEASIBLE
    assert [a.solver for a in error.attempts] == ["CLARABEL", "SCS"]
    assert {a.status for a in error.attempts} <= {
        SolveStatus.INFEASIBLE,
        SolveStatus.INFEASIBLE_INACCURATE,
    }


def test_unbounded_problem_raises(toy_eventset: EventSet) -> None:
    built = toy_built(toy_eventset)
    theta = built.context.theta
    unbounded = replace(built, problem=cp.Problem(cp.Minimize(cp.sum(theta))))
    policy = SolverPolicy(lp_solvers=("CLARABEL",))
    with pytest.raises(UnboundedError) as info:
        solve(unbounded, policy)
    assert info.value.status is SolveStatus.UNBOUNDED


def test_solver_error_falls_back(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = toy_built(toy_eventset)
    with_fake_solve(
        monkeypatch, built, {"SCS": SolverError("boom"), "CLARABEL": "real"}
    )
    result = solve(built, SolverPolicy(lp_solvers=("SCS", "CLARABEL")))
    assert result.solver == "CLARABEL"
    first = result.attempts[0]
    assert (first.solver, first.status) == ("SCS", SolveStatus.SOLVER_ERROR)
    assert first.message == "SolverError: boom"


def test_other_exceptions_propagate(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = toy_built(toy_eventset)
    with_fake_solve(monkeypatch, built, {"CLARABEL": ValueError("bug")})
    with pytest.raises(ValueError, match="bug"):
        solve(built, SolverPolicy(lp_solvers=("CLARABEL",)))


def test_unrecognised_status_is_a_solver_error(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = toy_built(toy_eventset)
    with_fake_solve(monkeypatch, built, {"HIGHS": "infeasible_or_unbounded"})
    monkeypatch.setattr(cp, "installed_solvers", lambda: ["HIGHS"])
    with pytest.raises(SolveError) as info:
        solve(built, SolverPolicy(lp_solvers=("HIGHS",)))
    (attempt,) = info.value.attempts
    assert attempt.status is SolveStatus.SOLVER_ERROR
    assert attempt.message == "unrecognised cvxpy status 'infeasible_or_unbounded'"
    assert info.value.status is SolveStatus.SOLVER_ERROR


def test_accepted_status_without_solution_is_an_error(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = toy_built(toy_eventset)
    with_fake_solve(monkeypatch, built, {"CLARABEL": "optimal"})
    with pytest.raises(SolveError, match="without a finite solution") as info:
        solve(built, SolverPolicy(lp_solvers=("CLARABEL",)))
    assert info.value.status is SolveStatus.ERROR


def test_missing_solver_is_recorded_and_skipped(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The CLIMADA env (cvxpy < 1.8) has no HiGHS: the default LP chain then
    # records HIGHS as not installed if it gets that far, and goes on to SCS.
    built = toy_built(toy_eventset)
    monkeypatch.setattr(cp, "installed_solvers", lambda: ["CLARABEL", "SCS"])
    result = solve(built, SolverPolicy(lp_solvers=("HIGHS", "CLARABEL")))
    assert result.solver == "CLARABEL"
    skipped = result.attempts[0]
    assert (skipped.solver, skipped.status, skipped.seconds) == (
        "HIGHS",
        SolveStatus.ERROR,
        0.0,
    )
    assert skipped.message == NOT_INSTALLED


def test_no_installed_solver_raises(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = toy_built(toy_eventset, MSE())
    monkeypatch.setattr(cp, "installed_solvers", lambda: ["SCS"])
    with pytest.raises(SolveError, match="none of the policy's solvers") as info:
        solve(built)
    assert info.value.status is SolveStatus.ERROR
    assert info.value.attempts == ()


def test_certificate_beats_a_numerical_failure(
    toy_eventset: EventSet, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = toy_built(toy_eventset)
    with_fake_solve(
        monkeypatch, built, {"CLARABEL": "infeasible", "SCS": SolverError("x")}
    )
    with pytest.raises(InfeasibleError) as info:
        solve(built, SolverPolicy(lp_solvers=("CLARABEL", "SCS")))
    assert [a.status for a in info.value.attempts] == [
        SolveStatus.INFEASIBLE,
        SolveStatus.SOLVER_ERROR,
    ]


def test_failure_precedence_covers_every_failure_status() -> None:
    failures = set(SolveStatus) - {SolveStatus.OPTIMAL}
    assert set(FAILURE_PRECEDENCE) == failures
    assert len(FAILURE_PRECEDENCE) == len(failures)


def test_solve_module_reexports_the_result_types() -> None:
    from parametric_insurance_design import interfaces

    assert solve_module.SolveResult is interfaces.SolveResult
    assert solve_module.SolveError is SolveError


# -- MAR-14 acceptance on the parity fixture ---------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"

# Thesis default configuration (configs/experiment_config.yaml and
# configs/global_settings.yaml of parametric-insurance-framework).
THESIS_ASSETS = [f"A{k}" for k in range(1, 10)]
ATTACHMENT, LIMIT, N_BINS = 20.0, 70.0, 15
ALPHA, BETA, KAPPA = 0.9, 0.95, 1.0
N_CLUSTERS, BETA_TAIL = 3, 0.9
NOISE_LEVEL, N_DRAWS, SEED = 0.3, 13, 42

SCOPES: dict[str, Scope] = {
    "individual": Individual(),
    "portfolio": Portfolio(),
    "cluster": Cluster(ThesisWardClustering(beta_tail=BETA_TAIL), N_CLUSTERS),
}
OBJECTIVES: dict[str, Objective] = {
    "mse": MSE(),
    "expected_uncovered": ExpectedUncovered(),
    "weighted_cvar": WeightedCVaR(alpha=ALPHA, beta=BETA),
}
N_PROBLEMS = {"individual": 9, "portfolio": 1, "cluster": 1}

N_ENTITIES = {"individual": 1, "portfolio": 9, "cluster": N_CLUSTERS}

needs_fixture = pytest.mark.skipif(
    not PARITY_EVENTSET.is_dir(),
    reason="the parity fixture is only in a repository checkout",
)


@pytest.fixture(scope="module")
def thesis_data() -> EventSet:
    """The thesis data preparation on the fixture: noise layer, 20 m/s filter."""
    eventset = add_noise(
        EventSet.from_parquet(PARITY_EVENTSET),
        level=NOISE_LEVEL,
        kind="heteroscedastic",
        n_copies=N_DRAWS,
        rng=np.random.default_rng(SEED),
        location_ids=THESIS_ASSETS,  # the thesis draws asset by asset
    )
    return eventset.filter_threshold(ATTACHMENT)


def numpy_objective(
    name: str, loss: NDArray[np.float64], payout: NDArray[np.float64], p: NDArray
) -> float:
    """The thesis objectives recomputed with numpy, in loss units."""
    if name == "mse":
        return float(p @ (loss - payout) ** 2)
    uncovered = np.maximum(loss - payout, 0.0)
    expected = float(p @ uncovered)
    if name == "expected_uncovered":
        return expected
    order = np.argsort(uncovered, kind="stable")
    var = uncovered[order][np.searchsorted(np.cumsum(p[order]), BETA)]
    cvar = var + float(p @ np.maximum(uncovered - var, 0.0)) / (1 - BETA)
    return ALPHA * cvar + (1 - ALPHA) * expected


@needs_fixture
@pytest.mark.parametrize("objective", list(OBJECTIVES))
@pytest.mark.parametrize("scope", list(SCOPES))
def test_nine_combinations_solve_on_the_fixture(
    thesis_data: EventSet, scope: str, objective: str
) -> None:
    assert thesis_data.n_rows == 13897  # thesis row count after the filter
    payout = StepPayout(attachment=ATTACHMENT, limit=LIMIT, n_bins=N_BINS)
    built = build_problems(
        thesis_data,
        SCOPES[scope],
        payout,
        OBJECTIVES[objective],
        PurePremium(),
        (Budget(KAPPA),),
        basis=BASIS,
    )
    assert len(built) == N_PROBLEMS[scope]
    p = thesis_data.rates / thesis_data.rates.sum()
    for b in built:
        result = solve(b)
        problem = b.context.problem
        assert result.status in DEFAULT_POLICY.accepted
        assert result.theta.shape == (N_ENTITIES[scope], N_BINS)
        assert result.solver == ("OSQP" if objective == "mse" else "CLARABEL")
        # Payout family and budget hold in loss units, up to the solver
        # tolerance in scaled units (OSQP's eps is 1e-8, MAR-98; Clarabel's
        # ~1e-8). Measured: <= 4.4e-10 (OSQP), <= 5e-12 (Clarabel).
        violation = result.diagnostics["max_constraint_violation_scaled"]
        assert violation <= 1e-6
        theta, cap = result.theta, problem.entity_loss.max(axis=0)
        tol = 1e-6 * result.scale
        assert np.all(theta >= -tol)
        assert np.all(np.diff(theta, axis=1) >= -tol)
        assert np.all(theta <= cap[:, None] + tol)
        expected_loss = float(p @ problem.loss)
        assert result.premium <= KAPPA * expected_loss + tol
        # cvxpy and numpy paths agree on the reported objective value.
        paid = result.payouts(problem).sum(axis=1)
        value = numpy_objective(objective, problem.loss, paid, p)
        assert result.objective_value == pytest.approx(value, rel=1e-6)
        assert result.premium == pytest.approx(float(p @ paid), rel=1e-9)


@needs_fixture
@pytest.mark.parametrize("objective", ["expected_uncovered", "mse"])
def test_injected_infeasible_problem_raises_on_the_fixture(
    thesis_data: EventSet, objective: str
) -> None:
    (built,) = build_problems(
        thesis_data,
        Portfolio(),
        StepPayout(attachment=ATTACHMENT, limit=LIMIT, n_bins=N_BINS),
        OBJECTIVES[objective],
        PurePremium(),
        (Budget(KAPPA), MinimumPremium(2 * KAPPA)),
        basis=BASIS,
    )
    with pytest.raises(SolveError) as info:
        solve(built)
    error = info.value
    assert isinstance(error, InfeasibleError)
    assert error.problem_id == "portfolio"
    assert error.status is SolveStatus.INFEASIBLE
    tried = DEFAULT_POLICY.solvers_for(built.problem)
    assert tuple(a.solver for a in error.attempts) == tried


# -- THESIS_POLICY (MAR-98) --------------------------------------------------

GOLDEN_RESULTS = REPO_ROOT / "parity" / "golden" / "full_optimization_results.csv.gz"
THESIS_APPROACH = {
    "portfolio": "integrated_portfolio_optimization",
    "cluster": "cluster_optimization",
}
# MSE objective values (loss units) of main's DEFAULT_POLICY before MAR-98 on
# this fixture (macOS arm64, workspace lock). Compared to 1e-9 relative, not
# bit for bit: OSQP's iterates depend on the BLAS and on the solver versions
# of each CI job. The MAR-98 default lands 9.1e-5 (portfolio) and 4.7e-6
# (cluster) lower, far outside that tolerance.
PRE_MAR98_MSE = {"portfolio": 606424236718.7905, "cluster": 676157755876.9508}


def golden_payouts(approach: str, entity_ids: tuple[str, ...]) -> NDArray[np.float64]:
    """The thesis single-run MSE step levels of the given entities."""
    table = pd.read_csv(GOLDEN_RESULTS)
    selected = (
        (table["Source"] == "single_run")
        & (table["Approach"] == approach)
        & (table["Method"] == "pure_basis_risk_minimization")
    )
    payouts = dict(
        zip(
            table.loc[selected, "Asset_ID"], table.loc[selected, "Payouts"], strict=True
        )
    )
    return np.vstack(
        [np.array(str(payouts[e]).strip("[]").split(), float) for e in entity_ids]
    )


@needs_fixture
@pytest.mark.parametrize("scope", ["portfolio", "cluster"])
def test_thesis_policy_reproduces_the_thesis_mse_solves(
    thesis_data: EventSet, scope: str
) -> None:
    payout = StepPayout(attachment=ATTACHMENT, limit=LIMIT, n_bins=N_BINS)
    (built,) = build_problems(
        thesis_data,
        SCOPES[scope],
        payout,
        MSE(),
        PurePremium(),
        (Budget(KAPPA),),
        basis=BASIS,
    )
    result = solve(built, THESIS_POLICY)
    assert result.solver == "OSQP"
    assert result.objective_value == pytest.approx(PRE_MAR98_MSE[scope], rel=1e-9)
    # ... which is the objective of the thesis payouts themselves.
    problem = built.context.problem
    theta = golden_payouts(THESIS_APPROACH[scope], result.entity_ids)
    paid = payout.evaluate(problem.index, theta).sum(axis=1)
    p = thesis_data.rates / thesis_data.rates.sum()
    thesis_value = numpy_objective("mse", problem.loss, paid, p)
    assert result.objective_value == pytest.approx(thesis_value, rel=1e-9)
