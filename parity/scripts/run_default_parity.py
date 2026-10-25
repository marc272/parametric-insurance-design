r"""Run the thesis default runs and write the parity report (MAR-68).

The thesis baseline (golden ``Source`` ``single_run``) is the thesis config's
default parameters for 3 scopes x 3 objectives: noise seed 42, eta = 0.3,
13 copies, alpha 0.9, beta 0.95, budget loading 1, 15 bins, 3 clusters
(``parity/configs/thesis.yaml``). This script

1. runs the 9 single runs of that config into a result store
   (``runner.run_config``, cached by content hash) with
   :data:`PARITY_POLICY`;
2. confirms that the noise draws of the runner's data preparation are
   bit-identical to the thesis noise layer (:func:`noise_check`, against
   ``golden/noise_digests.json``);
3. evaluates every golden thesis payout under **our** objective and
   constraints on the same prepared EventSet (:func:`thesis_payout_checks`):
   if its objective equals ours within solver tolerance and it is feasible,
   the two payouts are alternative optima, and so is every convex
   combination (checked at the midpoint). The result is written to
   ``analysis/thesis_payouts.md``;
4. writes ``REPORT.md`` with ``report.py``: golden objectives from
   ``golden/golden_objectives.csv``, explanations from
   ``explanations.yaml``, the analysis as an appendix, and the run setup in
   the setup section.

Run from the repository root::

    uv run python parity/scripts/run_default_parity.py

``--check`` exits with status 1 if a finding has no explanation (as
``report.py --check``). The store defaults to the config's
``output.directory`` (``results/thesis``, not committed).
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import numpy as np
from numpy.typing import NDArray

PARITY_DIR: Final[Path] = Path(__file__).resolve().parents[1]
SCRIPTS_DIR: Final[Path] = PARITY_DIR / "scripts"
for _path in (PARITY_DIR, SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

import harness  # noqa: E402
import report  # noqa: E402
import thesis_noise_digests as nd  # noqa: E402

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
)
from parametric_insurance_design.experiment.store import ResultStore  # noqa: E402
from parametric_insurance_design.interfaces import Sample  # noqa: E402
from parametric_insurance_design.problem import BuiltProblem, build_problems  # noqa: E402
from parametric_insurance_design.solve import (  # noqa: E402
    THESIS_POLICY,
    SolverPolicy,
    solve,
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
REPORT: Final[Path] = PARITY_DIR / "REPORT.md"
SOURCE: Final[str] = "single_run"
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


@dataclass(frozen=True)
class PayoutCheck:
    """One design problem: our solution and the thesis payout under it."""

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

    @property
    def gap(self) -> float:
        """(thesis - ours) / ours, both evaluated with numpy."""
        return (self.thesis.objective - self.ours.objective) / abs(self.ours.objective)

    @property
    def midpoint_gap(self) -> float:
        """(midpoint - ours) / ours."""
        return (self.midpoint.objective - self.ours.objective) / abs(
            self.ours.objective
        )


_APPROACH = {v: k for k, v in harness.APPROACHES.items()}
_METHOD = {v: k for k, v in harness.METHODS.items()}


def thesis_payout_checks(
    config: ExperimentConfig,
    data: RunInput,
    golden: harness.Golden,
    policy: SolverPolicy = PARITY_POLICY,
) -> list[PayoutCheck]:
    """Evaluate each golden ``single_run`` payout under our problem.

    For each of the 9 single runs: build the design problems as the runner
    does, solve them with ``policy``, and evaluate (numpy) our solution, the
    golden thesis payout of the same entities and their midpoint under our
    objective and constraints.

    Parameters
    ----------
    config : ExperimentConfig
        The thesis config.
    data : RunInput
        The EventSet as loaded.
    golden : harness.Golden
        The golden tables.
    policy : SolverPolicy, default PARITY_POLICY
        Solver policy (the one of the runs).

    Returns
    -------
    list of PayoutCheck
        One per design problem, in run and problem order.

    Raises
    ------
    KeyError
        If a golden payout entity is missing.
    ValueError
        If the config uses loaded pricing (the check assumes a pure premium).
    """
    checks: list[PayoutCheck] = []
    for single in config.single_runs():
        if single.pricing.kind != "pure":
            raise ValueError("the payout check assumes pure pricing")
        components = single.to_components()
        scope, objective = components.scopes[0], components.objectives[0]
        prepared = prepare_eventset(single, data.eventset)
        built = build_problems(
            prepared,
            scope,
            components.payout,
            objective,
            components.pricing,
            components.constraints,
            basis=components.basis,
            sample=Sample.full(prepared),
        )
        loading = next(
            float(c.loading) for c in single.constraints if c.kind == "budget"
        )
        levels = {
            p.entity_id: p.levels
            for p in golden.payouts
            if p.key.source == SOURCE
            and p.key.approach == _APPROACH[scope.name]
            and p.key.method == _METHOD[objective.name]
        }
        for problem in built:
            result = solve(problem, policy)
            evaluate = ProblemEvaluator(
                problem,
                objective.name,
                float(getattr(objective, "alpha", 0.0)),
                float(getattr(objective, "beta", 0.95)),
                loading,
            )
            thesis_theta = np.vstack([levels[e] for e in evaluate.entity_ids])
            ours_theta = np.asarray(result.theta, dtype=np.float64)
            checks.append(
                PayoutCheck(
                    scope=scope.name,
                    objective=objective.name,
                    config_hash=config_hash(single),
                    problem_id=problem.spec.problem_id,
                    entity_ids=tuple(evaluate.entity_ids),
                    solver=result.solver,
                    status=result.status.value,
                    solver_objective=result.objective_value,
                    ours=evaluate(ours_theta),
                    thesis=evaluate(thesis_theta),
                    midpoint=evaluate(0.5 * (ours_theta + thesis_theta)),
                    expected_loss=tuple(
                        float(evaluate.prob @ evaluate.entity_loss[:, j])
                        for j in range(len(evaluate.entity_ids))
                    ),
                )
            )
    return checks


def _cell(text: object) -> str:
    return str(text).replace("|", "\\|")


def _row(*cells: object) -> str:
    return "| " + " | ".join(_cell(c) for c in cells) + " |"


def render_analysis(checks: Sequence[PayoutCheck]) -> str:
    """Render the thesis-payout check as a Markdown report appendix.

    Parameters
    ----------
    checks : sequence of PayoutCheck
        From :func:`thesis_payout_checks`.

    Returns
    -------
    str
        Markdown, starting with a level-2 heading.
    """
    lines = [
        "## Appendix: the thesis payouts under our design problems",
        "",
        "Generated by `parity/scripts/run_default_parity.py` (MAR-68). Each golden "
        "`single_run` thesis payout is evaluated under **our** objective and "
        "constraints on the same prepared EventSet, with numpy (not the solver): "
        "objective, bound violations in USD (theta >= 0, monotone levels, cap at "
        "the entity's largest loss) and the budget, as (E[payout] - loading E[L]) "
        "/ (loading E[L]). *Gap* is (thesis - ours) / ours. If the thesis payout "
        "is feasible and its objective equals ours within solver tolerance, both "
        "are optimal: they are alternative optima, and so is every convex "
        "combination (the problem is convex), checked at the midpoint. The "
        "bound and budget violations of the MSE solutions, ours and the "
        "thesis's alike, come from OSQP at cvxpy's default accuracy, which "
        "`THESIS_POLICY` keeps (MAR-98).",
        "",
        _row(
            "Scope",
            "Objective",
            "config_hash",
            "Problem",
            "Solver",
            "Ours (solver)",
            "Ours (numpy)",
            "Thesis payout",
            "Gap",
            "Midpoint gap",
            "Thesis bound viol. (USD)",
            "Thesis budget",
            "Our bound viol. (USD)",
            "Our budget",
        ),
        "|" + "---|" * 14,
    ]
    for c in checks:
        lines.append(
            _row(
                c.scope,
                c.objective,
                f"`{c.config_hash[:19]}…`",
                c.problem_id,
                f"{c.solver} ({c.status})",
                f"{c.solver_objective:.10g}",
                f"{c.ours.objective:.10g}",
                f"{c.thesis.objective:.10g}",
                f"{c.gap:.2e}",
                f"{c.midpoint_gap:.2e}",
                f"{c.thesis.max_bound_violation:.2g}",
                f"{c.thesis.budget:.2e}",
                f"{c.ours.max_bound_violation:.2g}",
                f"{c.ours.budget:.2e}",
            )
        )
    gaps = [abs(c.gap) for c in checks]
    lines += [
        "",
        f"Largest |gap| over the {len(checks)} design problems: {max(gaps):.2e}; "
        f"largest |midpoint gap|: {max(abs(c.midpoint_gap) for c in checks):.2e}.",
    ]
    for c in checks:
        if (c.scope, c.objective) not in DETAIL_RUNS:
            continue
        lines += [
            "",
            f"### {c.scope} / {c.objective}: expected payout per entity",
            "",
            "The objective depends on the payouts only through the portfolio's "
            "total payout per event; the two optima above split that total "
            "differently between assets. E[payout] / E[loss] per asset (the KPI "
            "`E_Payout_to_E_Loss_Ratio`):",
            "",
            _row("Entity", "Thesis payout", "Our payout", "Relative difference"),
            "|---|---|---|---|",
        ]
        for j, entity in enumerate(c.entity_ids):
            loss = c.expected_loss[j]
            theirs = c.thesis.expected_payout[j] / loss
            ours = c.ours.expected_payout[j] / loss
            rel = (ours - theirs) / theirs if theirs else 0.0
            lines.append(_row(entity, f"{theirs:.10g}", f"{ours:.10g}", f"{rel:.2e}"))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------


def setup_notes(
    config: ExperimentConfig,
    data: RunInput,
    noise: NoiseCheck,
    policy: SolverPolicy = PARITY_POLICY,
) -> list[str]:
    """Return setup lines for the report: policy, noise, inputs, versions."""
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
    ]


NOTES: Final[str] = (
    "This report covers the thesis baseline, the golden `single_run` records "
    "(MAR-68). It is written by `uv run python "
    "parity/scripts/run_default_parity.py`, which runs the 9 default runs, "
    "checks the noise draws and the thesis payouts (appendix), and calls "
    "`report.py` with the golden objective table "
    "(`golden/golden_objectives.csv`) and `explanations.yaml`."
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
        0, or 1 with ``--check`` if a finding has no explanation.
    """
    parser = argparse.ArgumentParser(
        description="Run the thesis default runs and write the parity report."
    )
    parser.add_argument("--config", default=str(CONFIG))
    parser.add_argument(
        "--store", help="result store (default: the config's output.directory)"
    )
    parser.add_argument("--out", default=str(REPORT))
    parser.add_argument("--analysis", default=str(ANALYSIS))
    parser.add_argument("--explanations", default=str(EXPLANATIONS))
    parser.add_argument("--objectives", default=str(OBJECTIVES))
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    config = load_config(Path(args.config))
    store = ResultStore(Path(args.store) if args.store else config.output.directory)
    data = load_input(config)
    outcomes = run_defaults(config, store, data)
    failed = [o for o in outcomes if not o.ok]
    if failed:
        print(f"{len(failed)} runs have a failed design problem", file=sys.stderr)
    noise = noise_check(config, data)
    golden = harness.load_golden(objectives=args.objectives)
    analysis = Path(args.analysis)
    analysis.parent.mkdir(parents=True, exist_ok=True)
    analysis.write_text(
        render_analysis(thesis_payout_checks(config, data, golden)), encoding="utf-8"
    )
    report_args = [
        "--store",
        _display(store.root),
        "--objectives",
        args.objectives,
        "--explanations",
        args.explanations,
        "--source",
        SOURCE,
        "--out",
        args.out,
        "--notes",
        NOTES,
        "--appendix",
        str(analysis),
    ]
    for note in setup_notes(config, data, noise):
        report_args += ["--setup-note", note]
    if args.check:
        report_args.append("--check")
    code = report.main(report_args)
    return 1 if failed else code


def _display(path: Path) -> str:
    """Return a path relative to the working directory when it is inside it."""
    try:
        return str(path.resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    sys.exit(main())
