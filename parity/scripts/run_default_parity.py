r"""Run the thesis parity runs and write the parity report (MAR-68, MAR-69).

The thesis baseline (golden ``Source`` ``single_run``) is the thesis config's
default parameters for 3 scopes x 3 objectives: noise seed 42, eta = 0.3,
13 copies, alpha 0.9, beta 0.95, budget loading 1, 15 bins, 3 clusters
(``parity/configs/thesis.yaml``). The optimisation-parameter sweeps (golden
``Source`` ``<param>_sweep``, MAR-69) vary one of ``alpha``, ``beta``,
``budget_loading``, ``n_bins`` and ``n_clusters`` at a time
(:data:`OPTIMISATION_SWEEPS`). This script

1. runs the 9 single runs of that config into a result store
   (``runner.run_config``, cached by content hash) with
   :data:`PARITY_POLICY`, then the sweeps given (``sweeps.run_sweeps``, the
   same cache; a point equal to the baseline is a cache hit);
2. confirms that the noise draws of the runner's data preparation are
   bit-identical to the thesis noise layer (:func:`noise_check`, against
   ``golden/noise_digests.json``);
3. evaluates every golden thesis payout under **our** objective and
   constraints on the same prepared EventSet (:func:`thesis_payout_checks`),
   next to our stored solution: if its objective equals ours within solver
   tolerance and it is feasible, the two payouts are alternative optima, and
   so is every convex combination (checked at the midpoint); a larger gap is
   a potential porting bug. It also lists what we solved that has no golden
   counterpart (:func:`extra_runs`). The result is written to
   ``analysis/thesis_payouts.md``;
4. writes ``REPORT.md`` with ``report.py``: golden objectives from
   ``golden/golden_objectives.csv``, explanations from
   ``explanations.yaml``, the analysis as an appendix, and the run setup in
   the setup section. The adapter section ``analysis/adapter.md`` (MAR-20),
   written in the CLIMADA pixi env, follows as a second appendix.

Run from the repository root::

    uv run python parity/scripts/run_default_parity.py

``--sweep PARAM`` (repeatable) chooses the sweeps (default: the
optimisation sweeps) and ``--no-sweeps`` runs the baseline only; the report
compares the golden records of ``single_run`` and of the sweeps run.
``--check`` exits with status 1 if a finding has no explanation (as
``report.py --check``). The store defaults to the config's
``output.directory`` (``results/thesis``, not committed).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd
from numpy.typing import NDArray

PARITY_DIR: Final[Path] = Path(__file__).resolve().parents[1]
SCRIPTS_DIR: Final[Path] = PARITY_DIR / "scripts"
for _path in (PARITY_DIR, SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import harness  # noqa: E402
import report  # noqa: E402
import thesis_noise_digests as nd  # noqa: E402

from parametric_insurance_design.eventset import EventSet  # noqa: E402
from parametric_insurance_design.experiment.config import (  # noqa: E402
    ExperimentConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.runner import (  # noqa: E402
    RunInput,
    RunOutcome,
    load_input,
    package_versions,
    policy_fingerprint,
    prepare_eventset,
    run_config,
    run_single,
)
from parametric_insurance_design.experiment.store import ResultStore  # noqa: E402
from parametric_insurance_design.experiment.sweeps import (  # noqa: E402
    SWEEP_SOURCES,
    SweepResult,
    run_sweeps,
    sweep_points,
)
from parametric_insurance_design.interfaces import Sample  # noqa: E402
from parametric_insurance_design.problem import BuiltProblem, build_problems  # noqa: E402
from parametric_insurance_design.solve import (  # noqa: E402
    DEFAULT_POLICY,
    THESIS_POLICY,
    SolverPolicy,
)

PARITY_POLICY: SolverPolicy = THESIS_POLICY
"""Solver policy of the parity runs: ``solve.THESIS_POLICY``.

By owner decision (MAR-98, 2026-10-25) the parity gate compares with the
thesis under the policy that reproduces the thesis solves: Clarabel first for
the LPs, OSQP at cvxpy's default accuracy for the MSE QPs, as the thesis ran
them. The default policy runs OSQP at 1e-8 instead; its MSE results differ
from the thesis by the thesis's own solver error (``parity/BENCHMARK.md``)."""

CONFIG: Final[Path] = PARITY_DIR / "configs" / "thesis.yaml"
OBJECTIVES: Final[Path] = harness.GOLDEN_DIR / harness.OBJECTIVES_FILE
EXPLANATIONS: Final[Path] = PARITY_DIR / "explanations.yaml"
ANALYSIS: Final[Path] = PARITY_DIR / "analysis" / "thesis_payouts.md"
ADAPTER: Final[Path] = PARITY_DIR / "analysis" / "adapter.md"
"""The adapter section (MAR-20), written in the CLIMADA pixi env by
``packages/climada/scripts/thesis_adapter_parity.py`` and appended as is."""
REPORT: Final[Path] = PARITY_DIR / "REPORT.md"
SOURCE: Final[str] = "single_run"
OPTIMISATION_SWEEPS: Final[tuple[str, ...]] = (
    "alpha",
    "beta",
    "budget_loading",
    "n_bins",
    "n_clusters",
)
"""The optimisation-parameter sweeps (MAR-69), the default of ``--sweep``.

The simulation sweeps ``noise_level`` and ``n_assets`` are MAR-70: pass them
with ``--sweep``."""
DETAIL_RUNS: Final[frozenset[tuple[str, str]]] = frozenset(
    {("portfolio", "weighted_cvar")}
)
"""Runs whose analysis lists every entity (the ones with KPI findings)."""

SETUP_NOTE_POLICY: Final[str] = (
    "Solver policy: by owner decision (MAR-98), the parity gate runs with "
    "`solve.THESIS_POLICY` (`PARITY_POLICY` in "
    "`parity/scripts/run_default_parity.py`), which reproduces the thesis "
    "solves: OSQP at cvxpy's default accuracy for the MSE problems, as in the "
    "thesis. The default policy runs OSQP at 1e-8 instead."
)
SETUP_NOTE_MSE: Final[str] = (
    "Thesis MSE solver error: the thesis MSE solutions carry OSQP's default "
    "inaccuracy. Against accurate solves, their objective values are slightly "
    "too high and their payouts and KPIs off, most in the cluster and portfolio "
    "scopes (up to about 1.8 % in portfolio E[U]), and the individual-scope "
    "payouts of A2 to A4 exceed the budget by about 1e-4 relative (the appendix "
    "shows the same for ours under this policy). The MSE rows below therefore "
    "compare like with like, solver error included; `parity/BENCHMARK.md` "
    "(MAR-98) gives the measurements."
)


# --------------------------------------------------------------------------
# Runs
# --------------------------------------------------------------------------


def run_defaults(
    config: ExperimentConfig,
    store: ResultStore,
    data: RunInput,
    policy: SolverPolicy = PARITY_POLICY,
) -> tuple[RunOutcome, ...]:
    """Run the config's 9 single runs (cached) with the parity policy.

    Parameters
    ----------
    config : ExperimentConfig
        The thesis config.
    store : ResultStore
        Where the runs go.
    data : RunInput
        The EventSet as loaded.
    policy : SolverPolicy, default PARITY_POLICY
        Solver policy.

    Returns
    -------
    tuple of RunOutcome
        One per single run.
    """
    return run_config(config, store=store, data=data, source=SOURCE, policy=policy)


def run_parity_sweeps(
    config: ExperimentConfig,
    store: ResultStore,
    data: RunInput,
    parameters: Sequence[str],
    policy: SolverPolicy = PARITY_POLICY,
) -> tuple[SweepResult, ...]:
    """Run the given sweeps of the config (cached) with the parity policy.

    Run :func:`run_defaults` first, so that a sweep point equal to the
    baseline is a cache hit tagged ``single_run``.

    Parameters
    ----------
    config : ExperimentConfig
        The thesis config.
    store : ResultStore
        Where the runs and the sweep manifests go.
    data : RunInput
        The EventSet as loaded.
    parameters : sequence of str
        Sweep parameters, e.g. :data:`OPTIMISATION_SWEEPS`. Empty: none.
    policy : SolverPolicy, default PARITY_POLICY
        Solver policy.

    Returns
    -------
    tuple of SweepResult
        One per sweep, in config order.
    """
    if not parameters:
        return ()
    outcome = run_sweeps(
        config,
        store=store,
        data=data,
        parameters=parameters,
        baseline=False,
        policy=policy,
    )
    return outcome.sweeps


def sweep_sources(parameters: Sequence[str]) -> tuple[str, ...]:
    """Golden ``Source`` tags compared: ``single_run`` and the sweeps'."""
    return (SOURCE, *(SWEEP_SOURCES[p] for p in parameters))


# --------------------------------------------------------------------------
# Noise
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class NoiseCheck:
    """The runner's noise draws against the thesis digest (MAR-10)."""

    kind: str
    digest: str
    golden_digest: str
    same_platform: bool
    platform: str
    summary_deviation: float

    @property
    def bit_identical(self) -> bool | None:
        """True or False on the digest's platform; None elsewhere."""
        return self.digest == self.golden_digest if self.same_platform else None

    def text(self) -> str:
        """One setup line."""
        if self.bit_identical is None:
            verdict = (
                f"the SHA256 is only comparable on {self.platform}; the summary "
                f"(column sums and sampled entries) deviates by at most "
                f"{self.summary_deviation:.1e} relative"
            )
        elif self.bit_identical:
            verdict = (
                "bit-identical: the SHA256 of the noisy loss matrix equals the "
                f"thesis digest `{self.golden_digest[:16]}…` (platform "
                f"{self.platform})"
            )
        else:
            verdict = (
                f"NOT bit-identical: SHA256 `{self.digest[:16]}…`, thesis "
                f"`{self.golden_digest[:16]}…` (platform {self.platform})"
            )
        return (
            "Noise draws: the runner's data preparation (`prepare_eventset` "
            f"with the config's noise, {self.kind}, before the threshold filter) "
            f"against `golden/noise_digests.json` (MAR-10): {verdict}."
        )


def noise_check(config: ExperimentConfig, data: RunInput) -> NoiseCheck:
    """Compare the runner's noisy losses with the thesis noise digest.

    The threshold filter is switched off so that the matrix is the thesis
    noise layer's whole output (every expanded row), as the digest records.

    Parameters
    ----------
    config : ExperimentConfig
        The thesis config (with noise).
    data : RunInput
        The EventSet as loaded.

    Returns
    -------
    NoiseCheck
        Digests and the summary deviation.

    Raises
    ------
    ValueError
        If the config has no noise layer.
    """
    if config.noise is None:
        raise ValueError("the parity config has no noise layer")
    unfiltered = config.model_copy(update={"threshold": None})
    noisy = prepare_eventset(unfiltered, data.eventset)
    digests = json.loads(nd.DIGESTS.read_text(encoding="utf-8"))
    entry = digests["digests"][config.noise.kind]
    made = digests["generated_with"]
    return NoiseCheck(
        kind=config.noise.kind,
        digest=nd.matrix_digest(noisy.loss),
        golden_digest=entry["loss_sha256"],
        same_platform=nd.same_platform(digests),
        platform=f"{made['system']} {made['machine']}, numpy {made['numpy']}",
        summary_deviation=nd.summary_deviation(entry["summary"], noisy.loss),
    )


# --------------------------------------------------------------------------
# Thesis payouts under our problems
# --------------------------------------------------------------------------


def cvar(values: NDArray[np.float64], prob: NDArray[np.float64], beta: float) -> float:
    """Return ``CVaR_beta`` of a discrete distribution (Rockafellar-Uryasev).

    The same definition as the thesis ``calculate_var_cvar`` and the minimum
    of the Rockafellar-Uryasev LP.

    Parameters
    ----------
    values : numpy.ndarray
        Outcomes.
    prob : numpy.ndarray
        Their probabilities (summing to one).
    beta : float
        Level in ``(0, 1)``.

    Returns
    -------
    float
        The CVaR.
    """
    order = np.argsort(values, kind="stable")
    x, p = values[order], prob[order]
    k = min(int(np.searchsorted(np.cumsum(p), beta, side="left")), len(x) - 1)
    var = x[k]
    tail = x > var
    tail_prob = float(p[tail].sum())
    return float((p[tail] @ x[tail] + (1.0 - beta - tail_prob) * var) / (1.0 - beta))


@dataclass(frozen=True)
class Evaluation:
    """A payout evaluated under one design problem, in loss units."""

    objective: float
    negative: float
    monotonicity: float
    cap: float
    budget: float
    expected_payout: tuple[float, ...]

    @property
    def max_bound_violation(self) -> float:
        """Largest violation (USD) of theta >= 0, monotonicity and the cap."""
        return max(self.negative, self.monotonicity, self.cap)


class ProblemEvaluator:
    """Evaluate payout parameters under a built design problem with numpy.

    Independent of cvxpy and the solver: the objective is computed from the
    payout per row, with CVaR by :func:`cvar`.

    Parameters
    ----------
    built : BuiltProblem
        The design problem.
    objective : str
        ``runs.objective``: ``mse``, ``expected_uncovered`` or
        ``weighted_cvar``.
    alpha, beta : float
        Weighted CVaR parameters (ignored otherwise).
    loading : float
        Budget loading (pure premium).
    """

    def __init__(
        self,
        built: BuiltProblem,
        objective: str,
        alpha: float,
        beta: float,
        loading: float,
    ) -> None:
        """Store the problem data."""
        ctx = built.context
        problem = ctx.problem
        self.entity_ids = problem.spec.entity_ids
        self.prob = np.asarray(ctx.measure.probability, dtype=np.float64)
        self.loss = problem.loss
        self.entity_loss = problem.entity_loss
        self.basis = [
            np.asarray(ctx.payout_structure.basis_matrix(problem.index[:, j]))
            for j in range(problem.n_entities)
        ]
        self.objective = objective
        self.alpha, self.beta, self.loading = alpha, beta, loading

    def __call__(self, theta: NDArray[np.float64]) -> Evaluation:
        """Evaluate ``theta`` (loss units, shape (n_entities, n_params))."""
        payout = np.column_stack(
            [self.basis[j] @ theta[j] for j in range(len(self.entity_ids))]
        )
        total = payout.sum(axis=1)
        uncovered = np.maximum(self.loss - total, 0.0)
        expected = float(self.prob @ uncovered)
        if self.objective == "mse":
            value = float(self.prob @ (self.loss - total) ** 2)
        elif self.objective == "expected_uncovered":
            value = expected
        elif self.objective == "weighted_cvar":
            value = (
                self.alpha * cvar(uncovered, self.prob, self.beta)
                + (1.0 - self.alpha) * expected
            )
        else:
            raise ValueError(f"unknown objective {self.objective!r}")
        cap = self.entity_loss.max(axis=0)
        budget = self.loading * float(self.prob @ self.loss)
        diffs = np.diff(theta, axis=1)
        return Evaluation(
            objective=value,
            negative=float(max(0.0, -theta.min())),
            monotonicity=float(max(0.0, -diffs.min())) if diffs.size else 0.0,
            cap=float(max(0.0, (theta - cap[:, None]).max())),
            budget=(float(self.prob @ total) - budget) / budget,
            expected_payout=tuple(
                float(self.prob @ payout[:, j]) for j in range(payout.shape[1])
            ),
        )


GAP_TOL: Final[float] = 1e-7
"""Largest |gap| (relative objective difference) of an alternative optimum.

Clarabel's default accuracy and the golden payouts' 8-digit print each move
an LP objective by about 1e-9 to 1e-8 relative (MAR-68 appendix). A gap
above this is not explained by solver tolerance."""

GAP_ATOL: Final[float] = 1e-8
"""Absolute floor of the gap tolerance of an LP, as a fraction of E[L].

Where our optimum is (near) zero, e.g. E[U] at budget loadings of 1.3 and
above, a relative gap is undefined or huge. Rounding the golden levels to 8
significant digits moves E[U] by up to about 5e-9 E[payout], so an LP
objective difference of at most ``GAP_TOL |ours| + GAP_ATOL E[L]`` (USD) is
within tolerance. Not used for MSE."""

LP_BOUND_TOL: Final[float] = 0.1
"""Largest bound violation (USD) of a feasible thesis payout in an LP.

The golden levels are printed to 8 significant digits, so a level at the cap
(at most about 2e7 USD here) can exceed it by rounding alone by up to about
0.1 USD."""

LP_BUDGET_TOL: Final[float] = 1e-8
"""Largest relative budget excess of a feasible thesis payout in an LP."""

MSE_REF_TOL: Final[float] = 1e-4
"""Tolerance (relative, SPEC F-06) of an MSE payout against an accurate optimum.

Under ``THESIS_POLICY`` the MSE problems are solved by OSQP at cvxpy's
default accuracy, as in the thesis (MAR-98); the thesis's solutions and ours
alike can overspend the budget and violate the payout bounds, so neither the
gap between them nor their feasibility is a sign of a porting bug. Instead
each such MSE payout is compared with the accurate optimum (``DEFAULT_POLICY``)
of our problem at the budget that payout actually spends
(:class:`MseReference`)."""

VERDICTS: Final[tuple[str, ...]] = (
    "alternative optimum",
    "OSQP accuracy",
    "infeasible",
    "potential porting bug",
)
"""Verdicts of :attr:`PayoutCheck.verdict`, in report order."""


@dataclass(frozen=True)
class MseReference:
    """Accurate optima of an MSE design problem (``DEFAULT_POLICY``).

    The thesis payout of an MSE problem solved at OSQP's default accuracy
    may spend more than the budget; its objective is then compared with the
    accurate optimum of our problem at the loading it spends,
    ``loading (1 + budget excess)``, and likewise ours.

    Parameters
    ----------
    loading : float
        The run's budget loading.
    at_loading : float
        Accurate optimum at ``loading``.
    thesis_loading, at_thesis : float
        The loading the thesis payout spends, and the optimum there.
    ours_loading, at_ours : float
        The loading our solution spends, and the optimum there.
    config_hashes : tuple of str
        ``config_hash`` of the three reference runs (in the reference store).
    """

    loading: float
    at_loading: float
    thesis_loading: float
    at_thesis: float
    ours_loading: float
    at_ours: float
    config_hashes: tuple[str, ...]


@dataclass(frozen=True)
class PayoutCheck:
    """One design problem: our solution and the thesis payout under it.

    ``source`` and ``parameters`` name the golden record (its ``Source`` and
    :meth:`harness.RecordKey.parameter_text`).
    """

    scope: str
    objective: str
    config_hash: str
    problem_id: str
    entity_ids: tuple[str, ...]
    solver: str
    status: str
    solver_objective: float
    ours: Evaluation
    thesis: Evaluation
    midpoint: Evaluation
    expected_loss: tuple[float, ...]
    source: str = SOURCE
    parameters: str = ""
    reference: MseReference | None = None

    @property
    def gap(self) -> float:
        """(thesis - ours) / |ours|, both evaluated with numpy (inf if ours is 0)."""
        return _relative(self.thesis.objective, self.ours.objective)

    @property
    def midpoint_gap(self) -> float:
        """(midpoint - ours) / |ours|."""
        return _relative(self.midpoint.objective, self.ours.objective)

    @property
    def scaled_gap(self) -> float:
        """|thesis - ours| / E[L], E[L] the expected loss of the problem."""
        return abs(self.thesis.objective - self.ours.objective) / sum(
            self.expected_loss
        )

    def _within(self, value: float) -> bool:
        """Whether an objective value equals ours within solver tolerance."""
        atol = 0.0 if self.objective == "mse" else GAP_ATOL * sum(self.expected_loss)
        return (
            abs(value - self.ours.objective)
            <= GAP_TOL * abs(self.ours.objective) + atol
        )

    @property
    def record(self) -> str:
        """``approach / method / source`` of the golden record."""
        return f"{_APPROACH[self.scope]} / {_METHOD[self.objective]} / {self.source}"

    @property
    def thesis_feasible(self) -> bool:
        """Whether the thesis payout meets our constraints.

        For the LPs within :data:`LP_BOUND_TOL` and :data:`LP_BUDGET_TOL`.
        For MSE, where OSQP at cvxpy's default accuracy leaves violations in
        the thesis's and our solutions alike (MAR-98), within the larger of
        those tolerances and our own solution's violation.
        """
        bound, budget = LP_BOUND_TOL, LP_BUDGET_TOL
        if self.objective == "mse":
            bound = max(bound, 1.01 * self.ours.max_bound_violation)
            budget = max(budget, 1.01 * self.ours.budget)
        return self.thesis.max_bound_violation <= bound and self.thesis.budget <= budget

    @property
    def strict(self) -> bool:
        """Feasible, and objective and midpoint equal to ours within tolerance.

        Within :data:`GAP_TOL` relative (plus :data:`GAP_ATOL` E[L] for the
        LPs).
        """
        return (
            self._within(self.thesis.objective)
            and self._within(self.midpoint.objective)
            and self.thesis_feasible
        )

    @property
    def thesis_reference_gap(self) -> float | None:
        """(thesis - accurate optimum at its spent loading) / that optimum."""
        ref = self.reference
        return None if ref is None else _relative(self.thesis.objective, ref.at_thesis)

    @property
    def ours_reference_gap(self) -> float | None:
        """(ours - accurate optimum at our spent loading) / that optimum."""
        ref = self.reference
        return None if ref is None else _relative(self.ours.objective, ref.at_ours)

    @property
    def verdict(self) -> str:
        """One of :data:`VERDICTS`.

        * ``alternative optimum``: :attr:`strict`.
        * ``OSQP accuracy`` (MSE, with a :class:`MseReference`): the thesis
          payout's objective is at least the accurate optimum of our problem
          at the loading it spends, less :data:`MSE_REF_TOL`, and at most
          that optimum plus :data:`MSE_REF_TOL` or plus our own solution's
          distance to its accurate optimum (and 1e-5), whichever is larger:
          it is as optimal for our problem as OSQP at that accuracy makes
          ours.
        * ``infeasible``: the objectives agree but the thesis payout breaks
          a constraint of ours (LPs).
        * ``potential porting bug``: otherwise. Either the thesis payout is
          worse under our problem (the problems differ) or better (our solve
          is not optimal, or our problem is tighter).
        """
        if self.strict:
            return "alternative optimum"
        thesis_gap, ours_gap = self.thesis_reference_gap, self.ours_reference_gap
        if self.objective == "mse" and thesis_gap is not None and ours_gap is not None:
            upper = max(MSE_REF_TOL, abs(ours_gap) + 1e-5)
            if -MSE_REF_TOL <= thesis_gap <= upper:
                return "OSQP accuracy"
            return "potential porting bug"
        if self._within(self.thesis.objective) and self._within(
            self.midpoint.objective
        ):
            return "infeasible"
        return "potential porting bug"


def _relative(value: float, reference: float) -> float:
    """(value - reference) / |reference|; 0 if both are equal, else inf if 0."""
    diff = value - reference
    if reference == 0.0:
        return 0.0 if diff == 0.0 else math.copysign(math.inf, diff)
    return diff / abs(reference)


_APPROACH = {v: k for k, v in harness.APPROACHES.items()}
_METHOD = {v: k for k, v in harness.METHODS.items()}


def _loading(single: ExperimentConfig) -> float:
    """Budget loading of a single-run config (pure pricing only).

    Raises
    ------
    ValueError
        If the config uses loaded pricing (the checks assume a pure premium).
    """
    if single.pricing.kind != "pure":
        raise ValueError("the payout check assumes pure pricing")
    return next(float(c.loading) for c in single.constraints if c.kind == "budget")


class _Builder:
    """Build a run's design problems as the runner does, cached by config."""

    def __init__(self, data: RunInput) -> None:
        self.data = data
        self.prepared: dict[str, EventSet] = {}
        self.built: dict[str, tuple[BuiltProblem, ...]] = {}

    def __call__(
        self, chash: str, single: ExperimentConfig
    ) -> tuple[BuiltProblem, ...]:
        """Return the design problems of ``single`` (its hash ``chash``)."""
        if chash in self.built:
            return self.built[chash]
        components = single.to_components()
        data_key = json.dumps(
            single.model_dump(include={"noise", "threshold", "portfolio"}),
            sort_keys=True,
        )
        if data_key not in self.prepared:
            self.prepared[data_key] = prepare_eventset(single, self.data.eventset)
        prepared = self.prepared[data_key]
        self.built[chash] = tuple(
            build_problems(
                prepared,
                components.scopes[0],
                components.payout,
                components.objectives[0],
                components.pricing,
                components.constraints,
                basis=components.basis,
                sample=Sample.full(prepared),
            )
        )
        return self.built[chash]


def _store_theta(
    store: ResultStore, run_id: str
) -> tuple[dict[str, NDArray[np.float64]], dict[str, tuple[str, str, float]]]:
    """Our payout levels per entity and (solver, status, objective) per problem."""
    payouts = store.read("payouts", run_ids=[run_id])
    theta: dict[str, NDArray[np.float64]] = {}
    for entity, rows in payouts.groupby("entity_id", sort=False):
        ordered = rows.sort_values("param_index", kind="stable")
        theta[str(entity)] = ordered["value"].to_numpy(dtype=np.float64)
    runs = store.read("runs", run_ids=[run_id])
    solved = {
        str(r["problem_id"]): (
            str(r["solver"]),
            str(r["status"]),
            float(r["objective_value"]),
        )
        for r in runs.to_dict("records")
        if r["objective_value"] is not None and not pd.isna(r["objective_value"])
    }
    return theta, solved


def _spent_loading(loading: float, excess: float) -> float:
    """Return the loading a payout spends, rounded to 12 significant digits."""
    return float(f"{loading * (1.0 + excess):.12g}")


def mse_references(
    checks: Sequence[PayoutCheck],
    config: ExperimentConfig,
    data: RunInput,
    reference_store: ResultStore,
    *,
    sweeps: Sequence[str] = (),
    policy: SolverPolicy = DEFAULT_POLICY,
) -> list[PayoutCheck]:
    """Add an accurate reference to every MSE check that is not strict.

    The reference runs (the check's config at its loading, at the loading
    the thesis payout spends and at the loading ours spends) are solved with
    ``policy`` by :func:`runner.run_single` into ``reference_store``, a
    separate store (cached by content hash): in the parity store a run at
    the golden loading would be a second match of the golden record.

    Parameters
    ----------
    checks : sequence of PayoutCheck
        From :func:`thesis_payout_checks`.
    config : ExperimentConfig
        The thesis config.
    data : RunInput
        The EventSet as loaded.
    reference_store : ResultStore
        Where the reference runs go.
    sweeps : sequence of str, default ()
        As for :func:`thesis_payout_checks`.
    policy : SolverPolicy, default DEFAULT_POLICY
        The accurate policy (OSQP at 1e-8, MAR-98).

    Returns
    -------
    list of PayoutCheck
        ``checks``, with :attr:`PayoutCheck.reference` set where added.

    Raises
    ------
    RuntimeError
        If a reference run fails.
    """
    configs = point_configs(config, sweeps)
    out: list[PayoutCheck] = []
    for check in checks:
        if check.objective != "mse" or check.strict:
            out.append(check)
            continue
        single = configs[check.config_hash]
        loading = next(
            float(c.loading) for c in single.constraints if c.kind == "budget"
        )
        values: list[float] = []
        hashes: list[str] = []
        loadings = (
            loading,
            _spent_loading(loading, check.thesis.budget),
            _spent_loading(loading, check.ours.budget),
        )
        for value in loadings:
            point = single.with_parameter("budget_loading", value)
            outcome = run_single(
                point, data, reference_store, source="parity_reference", policy=policy
            )
            if not outcome.ok:
                raise RuntimeError(
                    f"reference run {outcome.run_id} failed: {outcome.failed}"
                )
            runs = reference_store.read("runs", run_ids=[outcome.run_id])
            row = runs[runs["problem_id"] == check.problem_id].iloc[0]
            values.append(float(row["objective_value"]))
            hashes.append(outcome.config_hash)
        out.append(
            replace(
                check,
                reference=MseReference(
                    loading=loading,
                    at_loading=values[0],
                    thesis_loading=loadings[1],
                    at_thesis=values[1],
                    ours_loading=loadings[2],
                    at_ours=values[2],
                    config_hashes=tuple(hashes),
                ),
            )
        )
    return out


def point_configs(
    config: ExperimentConfig, sweeps: Sequence[str] = ()
) -> dict[str, ExperimentConfig]:
    """Map ``config_hash`` to the single-run config of every parity run.

    Parameters
    ----------
    config : ExperimentConfig
        The thesis config.
    sweeps : sequence of str, default ()
        Sweep parameters whose points are included.

    Returns
    -------
    dict of str to ExperimentConfig
        The baseline single runs and every sweep point (a point equal to the
        baseline has the baseline's hash).
    """
    configs = {config_hash(s): s for s in config.single_runs()}
    for parameter in sweeps:
        for point in sweep_points(config, parameter):
            configs.setdefault(config_hash(point.config), point.config)
    return configs


def thesis_payout_checks(
    config: ExperimentConfig,
    data: RunInput,
    golden: harness.Golden,
    store: ResultStore,
    *,
    sources: Sequence[str] = (SOURCE,),
    sweeps: Sequence[str] = (),
) -> list[PayoutCheck]:
    """Evaluate each golden thesis payout under our problem.

    For every golden record of ``sources`` that the harness matches to one
    store run: rebuild that run's design problems as the runner does (same
    config, same prepared EventSet), and evaluate (numpy) our stored
    solution, the golden thesis payout of the same entities and their
    midpoint under our objective and constraints. A problem is evaluated
    when the golden table has a payout for each of its entities (the thesis
    dropped some after failed solves) and, in the cluster scope, the golden
    cluster has our members.

    Parameters
    ----------
    config : ExperimentConfig
        The thesis config.
    data : RunInput
        The EventSet as loaded.
    golden : harness.Golden
        The golden tables.
    store : ResultStore
        The parity runs.
    sources : sequence of str, default ("single_run",)
        Golden ``Source`` tags to check.
    sweeps : sequence of str, default ()
        Sweep parameters whose points may be in the store (to find the
        config of a matched run).

    Returns
    -------
    list of PayoutCheck
        One per design problem evaluated, in golden-record order.

    Raises
    ------
    KeyError
        If a matched run's config is not a parity run of ``config``.
    ValueError
        If a run uses loaded pricing (the check assumes a pure premium).
    """
    result = harness.compare(golden, store, sources=sources)
    configs = point_configs(config, sweeps)
    keys = {
        (k.source, k.approach, k.method, k.parameter_text()): k for k in golden.keys()
    }
    payouts: dict[harness.RecordKey, dict[str, harness.GoldenPayout]] = defaultdict(
        dict
    )
    for p in golden.payouts:
        payouts[p.key][p.entity_id] = p
    builder = _Builder(data)
    store_cache: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    matched = {
        keys[(r["source"], r["approach"], r["method"], r["parameters"])]: r
        for r in result.matched_runs.to_dict("records")
        if r["run_id"]
    }
    checks: list[PayoutCheck] = []
    for key in sorted(matched, key=harness.RecordKey.sort_key):
        row = matched[key]
        chash, run_id = str(row["config_hash"]), str(row["run_id"])
        single = configs.get(chash)
        if single is None:
            raise KeyError(f"run {run_id}: config {chash} is not a parity run")
        components = single.to_components()
        scope, objective = components.scopes[0], components.objectives[0]
        if run_id not in store_cache:
            store_cache[run_id] = _store_theta(store, run_id)
        ours_levels, solved = store_cache[run_id]
        loading = _loading(single)
        levels = payouts[key]
        for problem in builder(chash, single):
            spec = problem.spec
            if not all(e.entity_id in levels for e in spec.entities):
                continue  # the thesis has no payout for an entity
            if spec.problem_id not in solved:
                continue  # our solve failed: a harness finding already
            if scope.name == "cluster" and any(
                set(levels[e.entity_id].included or ()) != set(e.location_ids)
                for e in spec.entities
            ):
                continue  # other members: a cluster-assignment finding
            evaluate = ProblemEvaluator(
                problem,
                objective.name,
                float(getattr(objective, "alpha", 0.0)),
                float(getattr(objective, "beta", 0.95)),
                loading,
            )
            thesis_theta = np.vstack([levels[e].levels for e in evaluate.entity_ids])
            ours_theta = np.vstack([ours_levels[e] for e in evaluate.entity_ids])
            solver, status, value = solved[spec.problem_id]
            checks.append(
                PayoutCheck(
                    scope=scope.name,
                    objective=objective.name,
                    config_hash=chash,
                    problem_id=spec.problem_id,
                    entity_ids=tuple(evaluate.entity_ids),
                    solver=solver,
                    status=status,
                    solver_objective=value,
                    ours=evaluate(ours_theta),
                    thesis=evaluate(thesis_theta),
                    midpoint=evaluate(0.5 * (ours_theta + thesis_theta)),
                    expected_loss=tuple(
                        float(evaluate.prob @ evaluate.entity_loss[:, j])
                        for j in range(len(evaluate.entity_ids))
                    ),
                    source=key.source,
                    parameters=key.parameter_text(),
                )
            )
    return checks


@dataclass(frozen=True)
class ExtraRun:
    """Design problems we solved that have no golden counterpart.

    The thesis dropped the results of its failed solves without a trace
    (MAR-65): a whole run (no golden record) or some entities of one.
    """

    source: str
    scope: str
    objective: str
    parameters: str
    config_hash: str
    problems: tuple[str, ...]
    statuses: tuple[str, ...]
    whole_run: bool
    run_id: str = ""
    bound_violation: float | None = None
    budget: float | None = None

    def sort_key(self) -> tuple[object, ...]:
        """Source, scope, objective, then the parameter values as numbers."""
        values = tuple(
            float(item.split("=", 1)[1]) for item in self.parameters.split(", ")
        )
        return (self.source, self.scope, self.objective, values)


def _number_text(value: float) -> str:
    """As the golden parameter text: integers without a decimal point."""
    return str(int(value)) if value == int(value) else repr(value)


def _parameter_text(parameters: Mapping[str, Any]) -> str:
    """``name=value`` of the golden parameters a run has, in golden order."""
    names = harness.PARAMETER_COLUMNS.values()
    return ", ".join(
        f"{n}={_number_text(float(parameters[n]))}"
        for n in names
        if parameters.get(n) is not None
    )


def extra_runs(
    golden: harness.Golden, store: ResultStore, result: harness.ParityResult
) -> list[ExtraRun]:
    """List what we solved beyond the golden records of a comparison.

    Parameters
    ----------
    golden : harness.Golden
        The golden tables (with the objective table).
    store : ResultStore
        The parity runs.
    result : harness.ParityResult
        :func:`harness.compare` of the two.

    Returns
    -------
    list of ExtraRun
        Unmatched store runs, then matched runs with design problems that
        have neither a golden objective nor a golden payout, in report order.
    """
    runs = store.read("runs")
    by_run = {str(k): g for k, g in runs.groupby("run_id", sort=True)}

    def problems(run_id: str, wanted: set[str] | None) -> tuple[tuple[str, ...], ...]:
        frame = by_run[run_id]
        rows = [
            (str(r["problem_id"]), f"{r['solver']} {r['status']}")
            for r in frame.to_dict("records")
            if wanted is None or str(r["problem_id"]) in wanted
        ]
        return tuple(p for p, _ in rows), tuple(s for _, s in rows)

    extras: list[ExtraRun] = []
    for row in result.unmatched_runs.to_dict("records"):
        run_id = str(row["run_id"])
        first = by_run[run_id].iloc[0]
        ids, statuses = problems(run_id, None)
        extras.append(
            ExtraRun(
                source=str(row["source"]),
                scope=str(row["scope"]),
                objective=str(row["objective"]),
                parameters=_parameter_text(json.loads(str(row["parameters"]))),
                config_hash=str(first["config_hash"]),
                problems=ids,
                statuses=statuses,
                whole_run=True,
                run_id=run_id,
            )
        )
    covered: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for o in golden.objectives or ():
        covered[_key_tuple(o.key)].add(o.problem_id)
    for p in golden.payouts:
        covered[_key_tuple(p.key)].add(p.entity_id)
    for row in result.matched_runs.to_dict("records"):
        if not row["run_id"]:
            continue
        key = (row["source"], row["approach"], row["method"], row["parameters"])
        frame = by_run[str(row["run_id"])]
        missing = {str(p) for p in frame["problem_id"]} - covered[key]
        if not missing:
            continue
        ids, statuses = problems(str(row["run_id"]), missing)
        extras.append(
            ExtraRun(
                source=str(row["source"]),
                scope=harness.APPROACHES[str(row["approach"])],
                objective=harness.METHODS[str(row["method"])],
                parameters=str(row["parameters"]),
                config_hash=str(row["config_hash"]),
                problems=ids,
                statuses=statuses,
                whole_run=False,
                run_id=str(row["run_id"]),
            )
        )
    return sorted(extras, key=ExtraRun.sort_key)


def evaluate_extras(
    extras: Sequence[ExtraRun],
    config: ExperimentConfig,
    data: RunInput,
    store: ResultStore,
    *,
    sweeps: Sequence[str] = (),
) -> list[ExtraRun]:
    """Add our solutions' bound and budget violations to the extra runs.

    There is nothing to compare these solutions with, so this records how
    well they meet our own constraints, evaluated with numpy as in
    :class:`ProblemEvaluator`: the largest bound violation (USD) and the
    largest relative budget excess over the extra design problems.

    Parameters
    ----------
    extras : sequence of ExtraRun
        From :func:`extra_runs`.
    config : ExperimentConfig
        The thesis config.
    data : RunInput
        The EventSet as loaded.
    store : ResultStore
        The parity runs.
    sweeps : sequence of str, default ()
        As for :func:`thesis_payout_checks`.

    Returns
    -------
    list of ExtraRun
        ``extras`` with ``bound_violation`` and ``budget`` set where every
        extra problem has a solution.
    """
    configs = point_configs(config, sweeps)
    builder = _Builder(data)
    out = []
    for extra in extras:
        single = configs[extra.config_hash]
        objective = single.to_components().objectives[0]
        theta, solved = _store_theta(store, extra.run_id)
        evaluations = []
        for problem in builder(extra.config_hash, single):
            if problem.spec.problem_id not in extra.problems:
                continue
            if problem.spec.problem_id not in solved:
                evaluations = []
                break
            evaluate = ProblemEvaluator(
                problem,
                objective.name,
                float(getattr(objective, "alpha", 0.0)),
                float(getattr(objective, "beta", 0.95)),
                _loading(single),
            )
            evaluations.append(
                evaluate(np.vstack([theta[e] for e in evaluate.entity_ids]))
            )
        if evaluations:
            extra = replace(
                extra,
                bound_violation=max(e.max_bound_violation for e in evaluations),
                budget=max(e.budget for e in evaluations),
            )
        out.append(extra)
    return out


def _key_tuple(key: harness.RecordKey) -> tuple[str, ...]:
    return (key.source, key.approach, key.method, key.parameter_text())


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|")


def _row(*cells: object) -> str:
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


_DETAIL_HEADER: Final[tuple[str, ...]] = (
    "Source",
    "Scope",
    "Objective",
    "Parameters",
    "config_hash",
    "Problem",
    "Solver",
    "Ours (solver)",
    "Ours (numpy)",
    "Thesis payout",
    "Gap",
    "Midpoint gap",
    "Gap / E[L]",
    "Thesis bound viol. (USD)",
    "Thesis budget",
    "Our bound viol. (USD)",
    "Our budget",
    "Verdict",
)


def _detail_row(c: PayoutCheck) -> str:
    return _row(
        c.source,
        c.scope,
        c.objective,
        c.parameters,
        f"`{c.config_hash[:19]}…`",
        c.problem_id,
        f"{c.solver} ({c.status})",
        f"{c.solver_objective:.10g}",
        f"{c.ours.objective:.10g}",
        f"{c.thesis.objective:.10g}",
        f"{c.gap:.2e}",
        f"{c.midpoint_gap:.2e}",
        f"{c.scaled_gap:.2e}",
        f"{c.thesis.max_bound_violation:.2g}",
        f"{c.thesis.budget:.2e}",
        f"{c.ours.max_bound_violation:.2g}",
        f"{c.ours.budget:.2e}",
        c.verdict,
    )


def _ratio_diffs(c: PayoutCheck) -> list[tuple[str, float, float, float]]:
    """Per entity: E[payout]/E[loss] of the thesis payout, of ours, rel. diff."""
    out = []
    for j, entity in enumerate(c.entity_ids):
        loss = c.expected_loss[j]
        theirs = c.thesis.expected_payout[j] / loss
        ours = c.ours.expected_payout[j] / loss
        rel = (ours - theirs) / theirs if theirs else 0.0
        out.append((entity, theirs, ours, rel))
    return out


def render_analysis(
    checks: Sequence[PayoutCheck],
    *,
    findings: Sequence[harness.Finding] = (),
    extras: Sequence[ExtraRun] = (),
) -> str:
    """Render the thesis-payout check as a Markdown report appendix.

    Parameters
    ----------
    checks : sequence of PayoutCheck
        From :func:`thesis_payout_checks`.
    findings : sequence of harness.Finding, default ()
        The report's findings: the problems of a record with a finding are
        listed in full, and records with asset-level KPI findings in a joint
        scope get the expected payout per entity.
    extras : sequence of ExtraRun, default ()
        From :func:`extra_runs`.

    Returns
    -------
    str
        Markdown, starting with a level-2 heading.
    """
    with_findings = {_key_tuple(f.key) for f in findings}
    entity_kpi = {
        _key_tuple(f.key)
        for f in findings
        if f.kind is harness.FindingKind.KPI and f.subject != harness.PORTFOLIO_SUBJECT
    }

    def key_of(c: PayoutCheck) -> tuple[str, ...]:
        return (c.source, _APPROACH[c.scope], _METHOD[c.objective], c.parameters)

    sources = sorted({c.source for c in checks})
    lines = [
        "## Appendix: the thesis payouts under our design problems",
        "",
        "Generated by `parity/scripts/run_default_parity.py` (MAR-68, MAR-69). "
        "Each golden thesis payout of the records compared "
        f"({', '.join(sources)}) is evaluated under **our** objective and "
        "constraints on the same prepared EventSet, with numpy (not the "
        "solver), next to our stored solution of the matched run: objective, "
        "bound violations in USD (theta >= 0, monotone levels, cap at the "
        "entity's largest loss) and the budget, as (E[payout] - loading E[L]) "
        "/ (loading E[L]). *Gap* is (thesis - ours) / ours. If the thesis "
        "payout is feasible and its objective equals ours within solver "
        "tolerance, both are optimal: they are alternative optima, and so is "
        "every convex combination (the problem is convex), checked at the "
        "midpoint. The bound and budget violations of the MSE solutions, ours "
        "and the thesis's alike, come from OSQP at cvxpy's default accuracy, "
        "which `THESIS_POLICY` keeps (MAR-98).",
        "",
        "*Verdict*: **alternative optimum** if the thesis payout's objective "
        "and the midpoint's differ from ours by at most "
        f"{GAP_TOL:g} |ours| (plus {GAP_ATOL:g} E[L] for the LPs, where ours "
        "can be zero: *Gap / E[L]* is the difference over the problem's "
        "expected loss) and the thesis payout is feasible (LPs: bound "
        f"violation at most {LP_BOUND_TOL:g} USD, the rounding of its 8-digit "
        f"print, and budget excess at most {LP_BUDGET_TOL:g}; MSE: no larger "
        "than our own solution's, x1.01). **OSQP accuracy** (MSE only, see "
        "*MSE against accurate optima* below): not so, but the thesis "
        "payout's objective lies within "
        f"{MSE_REF_TOL:g} of the accurate optimum of our problem at the "
        "budget it spends (or no further from it than our own solution from "
        "its own, plus 1e-5). **Infeasible**: the objectives agree but the "
        "thesis payout breaks one of our constraints (LPs). **Potential "
        "porting bug**: otherwise. A design problem is checked when the "
        "golden table has a payout for each of its entities and, in the "
        "cluster scope, the golden cluster has our members.",
        "",
        "### Summary",
        "",
        _row(
            "Source",
            "Scope",
            "Objective",
            "Records",
            "Problems",
            "Max \\|gap\\|",
            "Max \\|midpoint gap\\|",
            "Max gap / E[L]",
            "Max thesis bound viol. (USD)",
            "Max thesis budget",
            "Alternative optima",
            "OSQP accuracy",
            "Infeasible",
            "Potential porting bugs",
        ),
        "|" + "---|" * 14,
    ]
    groups: dict[tuple[str, str, str], list[PayoutCheck]] = defaultdict(list)
    for c in checks:
        groups[(c.source, c.scope, c.objective)].append(c)
    for (source, scope, objective), items in groups.items():
        lines.append(
            _row(
                source,
                scope,
                objective,
                len({c.parameters for c in items}),
                len(items),
                f"{max(abs(c.gap) for c in items):.2e}",
                f"{max(abs(c.midpoint_gap) for c in items):.2e}",
                f"{max(c.scaled_gap for c in items):.2e}",
                f"{max(c.thesis.max_bound_violation for c in items):.2g}",
                f"{max(c.thesis.budget for c in items):.2e}",
                *(sum(c.verdict == v for c in items) for v in VERDICTS),
            )
        )
    counts = ", ".join(f"{sum(c.verdict == v for c in checks)} {v}" for v in VERDICTS)
    lp = [c for c in checks if c.objective != "mse"]
    lines += [
        "",
        f"{len(checks)} design problems checked: {counts}. Over the "
        f"{len(lp)} LP problems (E[U] and weighted CVaR), the largest |gap| is "
        f"{max((abs(c.gap) for c in lp if math.isfinite(c.gap)), default=0.0):.2e} "
        "where ours is not zero, the largest gap / E[L] "
        f"{max((c.scaled_gap for c in lp), default=0.0):.2e}.",
        "",
        "### Potential porting bugs",
        "",
    ]
    bugs = [c for c in checks if c.verdict == "potential porting bug"]
    if bugs:
        lines += [
            "The thesis payout is not optimal under our problem, or ours is not "
            "optimal under it, beyond solver tolerance. Not explained:",
            "",
            _row(*_DETAIL_HEADER),
            "|" + "---|" * len(_DETAIL_HEADER),
            *(_detail_row(c) for c in bugs),
        ]
    else:
        lines.append(
            "None: every thesis payout checked is optimal for our problem within "
            "solver tolerance (verdicts above)."
        )
    referenced = [c for c in checks if c.reference is not None]
    if referenced:
        lines += [
            "",
            "### MSE against accurate optima",
            "",
            "MSE design problems whose thesis payout is not an alternative "
            "optimum by the strict test. Under `THESIS_POLICY` both the thesis "
            "and we solve them with OSQP at cvxpy's default accuracy (MAR-98), "
            "whose solutions can overspend the budget and break the payout "
            "bounds, so their gap says little. Each payout is compared instead "
            "with the accurate optimum of **our** problem (`DEFAULT_POLICY`, "
            "OSQP at 1e-8; reference runs in a separate store) at the loading "
            "the payout spends, loading x (1 + budget excess). *vs. optimum*: "
            "(payout - that optimum) / that optimum. A payout can beat it "
            "only by breaking the payout bounds (columns *bound viol.*).",
            "",
            _row(
                "Source",
                "Scope",
                "Parameters",
                "Problem",
                "Our status",
                "Accurate optimum at the loading",
                "Thesis: loading spent",
                "Thesis: vs. optimum",
                "Thesis bound viol. (USD)",
                "Ours: loading spent",
                "Ours: vs. optimum",
                "Our bound viol. (USD)",
                "Gap (thesis vs. ours)",
                "Verdict",
            ),
            "|" + "---|" * 14,
        ]
        for c in referenced:
            ref = c.reference
            assert ref is not None
            lines.append(
                _row(
                    c.source,
                    c.scope,
                    c.parameters,
                    c.problem_id,
                    f"{c.solver} ({c.status})",
                    f"{ref.at_loading:.10g}",
                    f"{ref.thesis_loading:.6g}",
                    f"{c.thesis_reference_gap:.2e}",
                    f"{c.thesis.max_bound_violation:.2g}",
                    f"{ref.ours_loading:.6g}",
                    f"{c.ours_reference_gap:.2e}",
                    f"{c.ours.max_bound_violation:.2g}",
                    f"{c.gap:.2e}",
                    c.verdict,
                )
            )
    infeasible = [c for c in checks if c.verdict == "infeasible"]
    if infeasible:
        lines += [
            "",
            "### Infeasible thesis payouts",
            "",
            _row(*_DETAIL_HEADER),
            "|" + "---|" * len(_DETAIL_HEADER),
            *(_detail_row(c) for c in infeasible),
        ]
    detail = [c for c in checks if c.source == SOURCE or key_of(c) in with_findings]
    lines += [
        "",
        "### Design problems of the baseline and of every record with a finding",
        "",
        _row(*_DETAIL_HEADER),
        "|" + "---|" * len(_DETAIL_HEADER),
        *(_detail_row(c) for c in detail),
    ]
    joint = [c for c in checks if c.scope != "individual" and key_of(c) in entity_kpi]
    if joint:
        lines += [
            "",
            "### Joint scopes with asset-level KPI findings: expected payout per "
            "entity",
            "",
            "In the cluster and portfolio scopes the objective depends on the "
            "payouts only through the portfolio's total payout per event; two "
            "optima can split that total differently between entities. Per "
            "record: E[payout] / E[loss] (the KPI `E_Payout_to_E_Loss_Ratio`) of "
            "the entity whose ratio differs most between the thesis payout and "
            "ours, and the number of entities whose ratio differs by more than "
            "1e-4 relative.",
            "",
            _row(
                "Source",
                "Scope",
                "Objective",
                "Parameters",
                "Entity",
                "Thesis payout",
                "Our payout",
                "Relative difference",
                "Entities > 1e-4",
            ),
            "|" + "---|" * 9,
        ]
        for c in joint:
            ratios = _ratio_diffs(c)
            entity, theirs, ours, rel = max(ratios, key=lambda r: abs(r[3]))
            lines.append(
                _row(
                    c.source,
                    c.scope,
                    c.objective,
                    c.parameters,
                    entity,
                    f"{theirs:.10g}",
                    f"{ours:.10g}",
                    f"{rel:.2e}",
                    sum(abs(r[3]) > 1e-4 for r in ratios),
                )
            )
    for c in checks:
        if c.source != SOURCE or (c.scope, c.objective) not in DETAIL_RUNS:
            continue
        lines += [
            "",
            f"### {c.scope} / {c.objective} ({c.source}): expected payout per entity",
            "",
            _row("Entity", "Thesis payout", "Our payout", "Relative difference"),
            "|---|---|---|---|",
        ]
        for entity, theirs, ours, rel in _ratio_diffs(c):
            lines.append(_row(entity, f"{theirs:.10g}", f"{ours:.10g}", f"{rel:.2e}"))
    lines += ["", "### Extra runs, no golden", ""]
    if not extras:
        lines.append("None.")
    else:
        lines += [
            "Design problems we solved for which the golden tables hold neither "
            "a payout nor an objective: the thesis solves failed there and the "
            "thesis dropped them without a record (MAR-65). They are not "
            "compared, so they are not findings. *Whole run*: no golden record "
            "at these parameters (the run is also listed under *Store runs "
            "without a golden record*); otherwise the golden record lacks these "
            "problems. *Our status*: solver and status, with the number of "
            "problems. With nothing to compare, the last two columns say how "
            "well our solutions meet our own constraints (numpy, as above; the "
            "largest over the problems listed). Observation: these are exactly "
            "the MSE problems where OSQP at cvxpy's default accuracy returns no "
            "accepted solution and `THESIS_POLICY` falls back to Clarabel. The "
            "thesis's fallback, `solve(solver=CLARABEL, max_iters=20000)`, "
            "raises with the workspace's cvxpy 1.9.3 (`TypeError: Clarabel: "
            "unrecognized "
            "solver setting 'max_iters'`), and its `_solve` swallows that.",
            "",
            _row(
                "Source",
                "Scope",
                "Objective",
                "Parameters",
                "config_hash",
                "Whole run",
                "Problems",
                "Our status",
                "Our bound viol. (USD)",
                "Our budget",
            ),
            "|" + "---|" * 10,
        ]
        for e in extras:
            statuses = sorted(set(e.statuses))
            lines.append(
                _row(
                    e.source,
                    e.scope,
                    e.objective,
                    e.parameters,
                    f"`{e.config_hash[:19]}…`",
                    "yes" if e.whole_run else "no",
                    ", ".join(e.problems),
                    ", ".join(f"{s} ({e.statuses.count(s)})" for s in statuses),
                    "" if e.bound_violation is None else f"{e.bound_violation:.2g}",
                    "" if e.budget is None else f"{e.budget:.2e}",
                )
            )
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def setup_notes(
    config: ExperimentConfig,
    data: RunInput,
    noise: NoiseCheck,
    policy: SolverPolicy = PARITY_POLICY,
    sweeps: Sequence[SweepResult] = (),
) -> list[str]:
    """Return setup lines for the report: policy, noise, runs, sweeps."""
    versions = ", ".join(
        f"{name} {v}" for name, v in package_versions().items() if v is not None
    )
    policy_text = json.dumps(policy_fingerprint(policy), sort_keys=True)
    return [
        SETUP_NOTE_POLICY + f" Fingerprint: `{policy_text}`.",
        SETUP_NOTE_MSE,
        noise.text(),
        f"Runs: the {len(config.single_runs())} single runs of "
        "`parity/configs/thesis.yaml` (3 scopes x 3 objectives; noise seed "
        f"{config.noise.seed if config.noise else '-'}, level "
        f"{config.noise.level if config.noise else '-'}, "
        f"{config.noise.n_copies if config.noise else '-'} copies), EventSet "
        f"checksum `{data.checksum}`. Versions: {versions}.",
        *(_sweep_note(config, s) for s in sweeps),
    ]


def _sweep_note(config: ExperimentConfig, sweep: SweepResult) -> str:
    """One setup line per sweep: values, points, failures, manifest id."""
    spec = next(s for s in config.sweeps if s.parameter == sweep.parameter)
    values = ", ".join(str(v) for v in spec.values)
    return (
        f"Sweep `{sweep.parameter}` (`{sweep.source}`, values {values}): "
        f"{len(sweep.points)} points, {len(sweep.failed)} with a failed design "
        f"problem; sweep manifest `{sweep.sweep_id}` (MAR-65)."
    )


NOTES: Final[str] = (
    "This report covers the thesis baseline, the golden `single_run` records "
    "(MAR-68). It is written by `uv run python "
    "parity/scripts/run_default_parity.py`, which runs the 9 default runs, "
    "checks the noise draws and the thesis payouts (appendix), and calls "
    "`report.py` with the golden objective table "
    "(`golden/golden_objectives.csv`) and `explanations.yaml`. The last "
    "section checks that the CLIMADA adapter regenerates the thesis event-loss "
    "table (MAR-20)."
)

NOTES_SWEEPS: Final[str] = (
    "This report covers the thesis baseline, the golden `single_run` records "
    "(MAR-68), and the optimisation-parameter sweeps over alpha, beta, "
    "budget loading, n_bins and n_clusters (MAR-69). It is written by `uv run "
    "python parity/scripts/run_default_parity.py`, which runs the 9 default "
    "runs and every sweep point, checks the noise draws and the thesis "
    "payouts (appendix), and calls `report.py` with the golden objective "
    "table (`golden/golden_objectives.csv`) and `explanations.yaml`. A sweep "
    "point equal to the baseline is the baseline run (a cache hit), so its "
    "*Run source* is `single_run`. The last section checks that the CLIMADA "
    "adapter regenerates the thesis event-loss table (MAR-20)."
)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the default parity runs and write the report.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments (default: ``sys.argv[1:]``).

    Returns
    -------
    int
        0, or 1 if a run has a failed design problem, or with ``--check`` if
        a finding has no explanation or an explanation lacks its evidence
        (:func:`unsupported_explanations`).
    """
    parser = argparse.ArgumentParser(
        description="Run the thesis parity runs (baseline and sweeps) and write "
        "the parity report."
    )
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument(
        "--store", help="result store (default: the config's output.directory)"
    )
    parser.add_argument("--out", default=str(REPORT))
    parser.add_argument("--analysis", default=str(ANALYSIS))
    parser.add_argument(
        "--adapter",
        default=str(ADAPTER),
        help="adapter section appended after the analysis (MAR-20); '' to omit",
    )
    parser.add_argument("--explanations", default=str(EXPLANATIONS))
    parser.add_argument("--objectives", default=str(OBJECTIVES))
    parser.add_argument(
        "--reference-store",
        help="store of the accurate MSE reference runs (default: the store's "
        "directory name with -reference appended)",
    )
    parser.add_argument(
        "--sweep",
        action="append",
        dest="sweeps",
        metavar="PARAM",
        help="sweep to run and compare (repeatable; default: "
        f"{', '.join(OPTIMISATION_SWEEPS)})",
    )
    parser.add_argument(
        "--no-sweeps", action="store_true", help="run and compare the baseline only"
    )
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.no_sweeps and args.sweeps:
        parser.error("--sweep and --no-sweeps exclude each other")
    parameters: tuple[str, ...] = (
        () if args.no_sweeps else tuple(args.sweeps or OPTIMISATION_SWEEPS)
    )
    unknown = sorted(set(parameters) - set(SWEEP_SOURCES))
    if unknown:
        parser.error(f"unknown sweep parameters {unknown}")

    config = load_config(Path(args.config))
    store = ResultStore(Path(args.store) if args.store else config.output.directory)
    data = load_input(config)
    outcomes = run_defaults(config, store, data)
    failed = [o for o in outcomes if not o.ok]
    sweeps = run_parity_sweeps(config, store, data, parameters)
    failed += [p.outcome for s in sweeps for p in s.failed]
    if failed:
        print(f"{len(failed)} runs have a failed design problem", file=sys.stderr)
    noise = noise_check(config, data)
    golden = harness.load_golden(objectives=args.objectives)
    sources = sweep_sources(parameters)
    result = harness.compare(golden, store, sources=sources)
    checks = thesis_payout_checks(
        config, data, golden, store, sources=sources, sweeps=parameters
    )
    reference_store = ResultStore(
        Path(args.reference_store)
        if args.reference_store
        else store.root.with_name(store.root.name + "-reference")
    )
    checks = mse_references(checks, config, data, reference_store, sweeps=parameters)
    bugs = [c for c in checks if c.verdict == "potential porting bug"]
    if bugs:
        print(f"{len(bugs)} potential porting bugs (see the appendix)", file=sys.stderr)
    unsupported = unsupported_explanations(
        result.findings, checks, report.load_explanations(args.explanations)
    )
    for line in unsupported:
        print(f"explanation without evidence: {line}", file=sys.stderr)
    analysis = Path(args.analysis)
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text(
        render_analysis(
            checks,
            findings=result.findings,
            extras=evaluate_extras(
                extra_runs(golden, store, result),
                config,
                data,
                store,
                sweeps=parameters,
            ),
        ),
        encoding="utf-8",
    )
    report_args = [
        "--store",
        _display(store.root),
        "--objectives",
        args.objectives,
        "--explanations",
        args.explanations,
        *(arg for source in sources for arg in ("--source", source)),
        "--out",
        args.out,
        "--notes",
        NOTES_SWEEPS if parameters else NOTES,
        "--appendix",
        str(analysis),
        "--compact",
    ]
    if args.adapter:
        report_args += ["--appendix", args.adapter]
    for note in setup_notes(config, data, noise, sweeps=sweeps):
        report_args += ["--setup-note", note]
    if args.check:
        report_args.append("--check")
    code = report.main(report_args)
    if args.check and unsupported:
        code = 1
    return 1 if failed else code


EVIDENCE: Final[Mapping[str, frozenset[str]]] = {
    "Alternative optimum": frozenset({"alternative optimum"}),
    "OSQP accuracy": frozenset({"alternative optimum", "OSQP accuracy"}),
}
"""Explanation prefix to the payout-check verdicts that support it.

An explanation (``explanations.yaml``) that starts with one of these claims
that every design problem of the finding's record passed the thesis-payout
check with one of these verdicts; :func:`unsupported_explanations` holds it
to that."""


def unsupported_explanations(
    findings: Sequence[harness.Finding],
    checks: Sequence[PayoutCheck],
    explanations: Mapping[str, str],
) -> list[str]:
    """Return findings whose explanation claims evidence the checks lack.

    Parameters
    ----------
    findings : sequence of harness.Finding
        The report's findings.
    checks : sequence of PayoutCheck
        The thesis-payout checks (with MSE references).
    explanations : mapping of str to str
        From ``explanations.yaml``.

    Returns
    -------
    list of str
        One line per finding whose explanation starts with a key of
        :data:`EVIDENCE` while its record has no checked design problem, or
        one with another verdict. Empty if every claim is supported.
    """
    verdicts: dict[tuple[str, ...], list[str]] = defaultdict(list)
    for c in checks:
        verdicts[
            (c.source, _APPROACH[c.scope], _METHOD[c.objective], c.parameters)
        ].append(c.verdict)
    out = []
    for finding in findings:
        text = report.explanation_for(finding, explanations)
        if text is None:
            continue
        for prefix, allowed in EVIDENCE.items():
            if not text.startswith(prefix):
                continue
            found = verdicts.get(_key_tuple(finding.key), [])
            if not found or any(v not in allowed for v in found):
                out.append(
                    f"{finding.id} ({finding.path}) is explained as {prefix!r}, "
                    f"but its record's verdicts are {sorted(set(found)) or 'none'}"
                )
    return out


def _display(path: Path) -> str:
    """Return a path relative to the working directory when it is inside it."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
