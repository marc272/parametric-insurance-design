"""Parity of the optimisation-parameter sweeps (MAR-69).

Three groups:

- Fast checks (marker ``parity``, every pull request): the committed
  ``REPORT.md`` compares the baseline and the five optimisation sweeps,
  explains every finding, lists no potential porting bug and stays under the
  repository's file-size limit; the sweep points of the thesis config cover
  every golden sweep record; the verdict rules of the thesis-payout check and
  the evidence rule of the explanations, on hand-made checks.
- ``parity_full``: the baseline and every sweep point are solved into a
  fresh store, and the regenerated report must agree with the committed one
  (findings and overview counts), with every thesis payout optimal for our
  problem up to the solver's accuracy (about 10 minutes, the accurate MSE
  reference runs included).
"""

from __future__ import annotations

import importlib.util
import math
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import harness
import pytest
import report

from parametric_insurance_design.experiment.config import load_config

PARITY_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = PARITY_DIR / "scripts"
REPORT = PARITY_DIR / "REPORT.md"
ANALYSIS = PARITY_DIR / "analysis" / "thesis_payouts.md"
EXPLANATIONS = PARITY_DIR / "explanations.yaml"
MAX_FILE_BYTES = 500 * 1024  # pre-commit check-added-large-files --maxkb=500


def _load(name: str) -> ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


rdp = _load("run_default_parity")

SOURCES = (
    "single_run",
    "alpha_sweep",
    "beta_sweep",
    "budget_loading_sweep",
    "n_bins_sweep",
    "n_clusters_sweep",
)
OVERVIEW = (
    "| KPI values | 10656 | 10656 | 9944 | 712 | 0 |",
    "| Objective values | 759 | 759 | 751 | 8 | 0 |",
    "| Payout vectors | 1551 | 1551 | 1551 | 0 | 0 |",
    "| Cluster assignments | 93 | 93 | 93 | 0 | 0 |",
)
"""The overview counts of the committed report (errors left out)."""


# -- committed report --------------------------------------------------------


def test_committed_report_covers_the_optimisation_sweeps() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert "- Golden records compared: " + ", ".join(sorted(SOURCES)) + "." in text
    assert re.search(r"\n720 findings, 720 of them explained, 0 not yet\. ", text)
    for line in OVERVIEW:
        assert line in text
    assert report.PENDING not in text
    for parameter in rdp.OPTIMISATION_SWEEPS:
        assert f"- Sweep `{parameter}` (`{parameter}_sweep`, values " in text
    assert ", 0 with a failed design problem; sweep manifest `sha256:" in text
    assert "with a failed design problem" in text
    assert text.count(" with a failed design problem;") == 5
    assert all(
        " 0 with a failed design problem; sweep manifest" in line
        for line in text.splitlines()
        if line.startswith("- Sweep ")
    )
    assert "## Explanations" in text
    assert "### Extra runs, no golden" in text


def test_committed_report_has_no_potential_porting_bug() -> None:
    text = ANALYSIS.read_text(encoding="utf-8")
    assert "### Potential porting bugs\n\nNone:" in text
    match = re.search(
        r"\n(\d+) design problems checked: (\d+) alternative optimum, (\d+) OSQP "
        r"accuracy, 0 infeasible, 0 potential porting bug\.",
        text,
    )
    assert match is not None
    total, optimum, osqp = (int(g) for g in match.groups())
    assert total == 759 == optimum + osqp
    assert text in REPORT.read_text(encoding="utf-8")  # appended verbatim


def test_committed_files_stay_under_the_size_limit() -> None:
    for path in (REPORT, ANALYSIS, EXPLANATIONS):
        assert path.stat().st_size < MAX_FILE_BYTES, path


def test_explanations_claim_only_supported_verdicts() -> None:
    # Every explanation is either a claim the script checks against the
    # thesis-payout verdicts, or it names a single finding id.
    explanations = report.load_explanations(EXPLANATIONS)
    for key, text in explanations.items():
        assert key.startswith("P-") or any(
            text.startswith(prefix) for prefix in rdp.EVIDENCE
        ), key


# -- sweep points ------------------------------------------------------------


def _point_parameters(single: Any) -> tuple[object, ...]:  # noqa: ANN401
    """(scope, objective, alpha, beta, budget_loading, n_bins, n_clusters)."""
    objective = single.objectives[0]
    scope = single.scopes[0]
    return (
        scope.kind,
        objective.kind,
        getattr(objective, "alpha", None),
        getattr(objective, "beta", None),
        rdp._loading(single),
        float(single.payout.n_bins),
        getattr(scope, "n_clusters", None),
    )


def _same(a: tuple[object, ...], b: tuple[object, ...]) -> bool:
    return all(
        x == y
        if not (isinstance(x, float | int) and isinstance(y, float | int))
        else math.isclose(float(x), float(y), rel_tol=1e-9)
        for x, y in zip(a, b, strict=True)
    )


def test_sweep_points_cover_every_golden_sweep_record() -> None:
    config = load_config(rdp.CONFIG)
    configs = rdp.point_configs(config, rdp.OPTIMISATION_SWEEPS)
    # 9 baseline runs and 231 sweep points, 27 of which equal a baseline run.
    assert len(configs) == 9 + 231 - 27
    points = [_point_parameters(c) for c in configs.values()]
    keys = [k for k in harness.load_golden().keys() if k.source in SOURCES]
    for key in keys:
        want = (key.scope, key.objective, *(v for _, v in key.parameters))
        assert any(_same(want, point) for point in points), key.label()


def test_sweep_sources() -> None:
    assert rdp.sweep_sources(()) == ("single_run",)
    assert rdp.sweep_sources(rdp.OPTIMISATION_SWEEPS) == SOURCES
    assert rdp.sweep_sources(("noise_level",)) == ("single_run", "noise_value_sweep")


def test_cli_rejects_bad_sweep_arguments() -> None:
    with pytest.raises(SystemExit):
        rdp.main(["--sweep", "alpha", "--no-sweeps"])
    with pytest.raises(SystemExit):
        rdp.main(["--sweep", "gamma"])


@pytest.mark.parametrize("jobs", ["0", "-2", "two"])
def test_cli_rejects_bad_jobs(jobs: str) -> None:
    with pytest.raises(SystemExit):
        rdp.main(["--jobs", jobs])


class _Stop(Exception):
    """Raised by a stub to end :func:`rdp.main` once the call is seen."""


def test_cli_passes_jobs_to_the_sweeps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def run_parity_sweeps(*args: object, **kwargs: object) -> None:
        seen.update(parameters=args[3], jobs=kwargs["jobs"])
        raise _Stop

    monkeypatch.setattr(rdp, "load_input", lambda config: None)
    monkeypatch.setattr(rdp, "run_defaults", lambda config, store, data: ())
    monkeypatch.setattr(rdp, "run_parity_sweeps", run_parity_sweeps)
    store = ["--store", str(tmp_path / "store")]
    with pytest.raises(_Stop):
        rdp.main([*store, "--sweep", "alpha", "--jobs", "8"])
    assert seen == {"parameters": ("alpha",), "jobs": 8}
    with pytest.raises(_Stop):
        rdp.main(store)
    assert seen == {"parameters": rdp.ALL_SWEEPS, "jobs": 1}  # serial default


def test_run_parity_sweeps_passes_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    class Outcome:
        sweeps = ("result",)

    def run_sweeps(config: object, **kwargs: object) -> Outcome:
        seen.update(kwargs)
        return Outcome()

    monkeypatch.setattr(rdp, "run_sweeps", run_sweeps)
    store: Any = None
    data: Any = None
    config = load_config(rdp.CONFIG)
    assert rdp.run_parity_sweeps(config, store, data, ("alpha",), jobs=3) == ("result",)
    assert seen["jobs"] == 3
    assert seen["baseline"] is False
    assert seen["parameters"] == ("alpha",)
    assert rdp.run_parity_sweeps(config, store, data, (), jobs=3) == ()


# -- verdicts ----------------------------------------------------------------


def _evaluation(objective: float, *, bound: float = 0.0, budget: float = 0.0) -> Any:  # noqa: ANN401
    return rdp.Evaluation(
        objective=objective,
        negative=bound,
        monotonicity=0.0,
        cap=0.0,
        budget=budget,
        expected_payout=(1.0,),
    )


def _check(
    ours: float,
    thesis: float,
    *,
    objective: str = "weighted_cvar",
    thesis_bound: float = 0.0,
    thesis_budget: float = 0.0,
    reference: object | None = None,
) -> Any:  # noqa: ANN401
    return rdp.PayoutCheck(
        scope="portfolio",
        objective=objective,
        config_hash="sha256:" + "0" * 64,
        problem_id="portfolio",
        entity_ids=("A1",),
        solver="CLARABEL",
        status="optimal",
        solver_objective=ours,
        ours=_evaluation(ours),
        thesis=_evaluation(thesis, bound=thesis_bound, budget=thesis_budget),
        midpoint=_evaluation(0.5 * (ours + thesis)),
        expected_loss=(1000.0,),
        source="alpha_sweep",
        parameters="alpha=0.5, beta=0.95, budget_loading=1, n_bins=15",
        reference=reference,
    )


def test_lp_verdicts() -> None:
    assert _check(100.0, 100.0 + 5e-6).verdict == "alternative optimum"
    assert _check(100.0, 100.0 + 1e-3).verdict == "potential porting bug"
    assert _check(100.0, 100.0 - 1e-3).verdict == "potential porting bug"
    # A zero optimum: the absolute floor GAP_ATOL E[L] applies.
    assert _check(0.0, 5e-6).gap == math.inf
    assert _check(0.0, 5e-6).verdict == "alternative optimum"
    assert _check(0.0, 1e-3).verdict == "potential porting bug"
    infeasible = _check(100.0, 100.0, thesis_budget=1e-6)
    assert infeasible.verdict == "infeasible"
    assert _check(100.0, 100.0, thesis_bound=1.0).verdict == "infeasible"
    assert _check(100.0, 100.0, thesis_bound=0.05).verdict == "alternative optimum"


def _reference(at_thesis: float, at_ours: float) -> Any:  # noqa: ANN401
    return rdp.MseReference(
        loading=1.0,
        at_loading=at_ours,
        thesis_loading=1.01,
        at_thesis=at_thesis,
        ours_loading=1.0,
        at_ours=at_ours,
        config_hashes=("a", "b", "c"),
    )


def test_mse_verdicts_against_an_accurate_reference() -> None:
    # Strictly equal: no reference needed.
    assert _check(100.0, 100.0, objective="mse").verdict == "alternative optimum"
    gap = 0.1  # 1e-3 relative, far above GAP_TOL
    plain = _check(100.0, 100.0 - gap, objective="mse", thesis_budget=0.01)
    assert plain.verdict == "potential porting bug"  # no reference yet
    # The thesis payout overspends the budget; at the loading it spends it
    # is within MSE_REF_TOL of the accurate optimum.
    ok = _check(
        100.0,
        100.0 - gap,
        objective="mse",
        thesis_budget=0.01,
        reference=_reference(at_thesis=(100.0 - gap) / (1 + 5e-5), at_ours=100.0),
    )
    assert ok.thesis_reference_gap == pytest.approx(5e-5)
    assert ok.verdict == "OSQP accuracy"
    # Far above the accurate optimum: the thesis payout is not optimal for us.
    worse = _check(
        100.0,
        100.0 - gap,
        objective="mse",
        reference=_reference(at_thesis=90.0, at_ours=100.0),
    )
    assert worse.verdict == "potential porting bug"
    # Below the accurate optimum by more than MSE_REF_TOL: our problem is
    # tighter than the one the thesis solved.
    better = _check(
        100.0,
        100.0 - gap,
        objective="mse",
        reference=_reference(at_thesis=100.0, at_ours=100.0),
    )
    assert better.verdict == "potential porting bug"
    # As far from its optimum as our own solution from ours: OSQP accuracy.
    same = _check(
        100.0,
        100.0 - gap,
        objective="mse",
        reference=_reference(at_thesis=(100.0 - gap) / (1 + 3e-4), at_ours=99.97),
    )
    assert same.ours_reference_gap == pytest.approx(3.0009e-4, rel=1e-3)
    assert same.verdict == "OSQP accuracy"


def test_spent_loading() -> None:
    assert rdp._spent_loading(0.7, 0.0378) == 0.72646
    assert rdp._spent_loading(1.0, 0.0) == 1.0


def test_unsupported_explanations() -> None:
    key = harness.RecordKey(
        "integrated_portfolio_optimization",
        "weighted_cvar_minimization",
        "alpha_sweep",
        (
            ("alpha", 0.5),
            ("beta", 0.95),
            ("budget_loading", 1.0),
            ("n_bins", 15.0),
            ("n_clusters", None),
        ),
    )
    finding = harness.Finding(harness.FindingKind.KPI, key, "A1", "E_Residual")
    glob = {"kpi/*": "Alternative optimum (LP degeneracy)."}
    good = _check(100.0, 100.0)
    bad = _check(100.0, 101.0)
    assert rdp.unsupported_explanations([finding], [good], glob) == []
    (line,) = rdp.unsupported_explanations([finding], [good, bad], glob)
    assert finding.id in line
    assert "potential porting bug" in line
    # No check for the record: no evidence either.
    assert rdp.unsupported_explanations([finding], [], glob)
    # OSQP accuracy allows both verdicts; a text without a known prefix
    # claims nothing.
    osqp = {"kpi/*": "OSQP accuracy (MSE)."}
    assert rdp.unsupported_explanations([finding], [good], osqp) == []
    assert rdp.unsupported_explanations([finding], [bad], {"kpi/*": "Other."}) == []


def test_extra_run_sort_key() -> None:
    def extra(parameters: str) -> Any:  # noqa: ANN401
        return rdp.ExtraRun(
            "budget_loading_sweep",
            "individual",
            "mse",
            parameters,
            "sha256:0",
            ("A1",),
            ("CLARABEL optimal",),
            True,
        )

    runs = [
        extra("budget_loading=0.9, n_bins=15"),
        extra("budget_loading=0.5, n_bins=5"),
    ]
    ordered = sorted(runs, key=rdp.ExtraRun.sort_key)
    assert [r.parameters for r in ordered] == [
        "budget_loading=0.5, n_bins=5",
        "budget_loading=0.9, n_bins=15",
    ]


# -- slow: the sweeps themselves --------------------------------------------


def _findings(text: str) -> set[str]:
    return set(re.findall(r"^\| `(P-[0-9a-f]{10})` \|", text, flags=re.MULTILINE))


def _overview(text: str) -> list[str]:
    section = text.split("## Overview", 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("| ")]


@pytest.mark.parity_full
def test_sweeps_reproduce_the_committed_report(tmp_path: Path) -> None:
    out = tmp_path / "REPORT.md"
    analysis = tmp_path / "analysis.md"
    args = [
        "--store",
        str(tmp_path / "store"),
        "--out",
        str(out),
        "--analysis",
        str(analysis),
        "--reports-dir",
        str(tmp_path / "reports"),
        "--analysis-dir",
        str(tmp_path / "analyses"),
        *(arg for p in rdp.OPTIMISATION_SWEEPS for arg in ("--sweep", p)),
        "--check",
    ]
    # Every run solved, every finding explained, every explanation backed by
    # the thesis-payout verdicts of its record.
    assert rdp.main(args) == 0
    ours, committed = out.read_text(), REPORT.read_text()
    assert _findings(ours) == _findings(committed)
    assert len(_findings(ours)) == 720
    assert _overview(ours)[:5] == _overview(committed)[:5]  # header and counts
    for line in OVERVIEW:
        assert line in ours
    text = analysis.read_text()
    assert "### Potential porting bugs\n\nNone:" in text
    assert "0 potential porting bug." in text
