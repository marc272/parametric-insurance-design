"""Parity of the thesis default runs, 3 scopes x 3 objectives (MAR-68).

Three groups:

- Fast checks (marker ``parity``, every pull request): the golden objective
  table (``golden/golden_objectives.csv``) re-derives from the golden KPIs,
  covers every ``single_run`` design problem and loads in the harness; the
  golden content matches ``parity/manifest.json``; the runner's noise draws
  equal the thesis noise layer's; the committed ``REPORT.md`` has no
  unexplained finding; the parity runs use ``solve.THESIS_POLICY``.
- Against the thesis code (``PARITY_THESIS_REPO``): the whole golden
  objective table, including the rows recomputed with the thesis code, is
  rewritten byte-identically.
- ``parity_full``: the 9 runs are solved, the report is regenerated and must
  agree with the committed one (findings and overview), and every thesis
  payout is an alternative optimum of our design problem.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from types import ModuleType

import harness
import pandas as pd
import pytest
import report

from parametric_insurance_design.experiment.config import load_config
from parametric_insurance_design.experiment.runner import load_input

PARITY_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = PARITY_DIR / "scripts"
OBJECTIVES = PARITY_DIR / "golden" / "golden_objectives.csv"
PROVENANCE = PARITY_DIR / "golden" / "golden_objectives.json"
REPORT = PARITY_DIR / "REPORT.md"
EXPLANATIONS = PARITY_DIR / "explanations.yaml"


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


dgo = _load("derive_golden_objectives")
rdp = _load("run_default_parity")


@pytest.fixture(scope="module")
def committed() -> pd.DataFrame:
    return pd.read_csv(OBJECTIVES, keep_default_na=False, dtype=str)


@pytest.fixture(scope="module")
def config_and_input() -> tuple:
    config = load_config(rdp.CONFIG)
    return config, load_input(config)


# -- golden objective table --------------------------------------------------


def test_a_rows_rederive_from_the_golden_kpis(
    tmp_path: Path, committed: pd.DataFrame
) -> None:
    out_csv, out_json = tmp_path / "o.csv", tmp_path / "o.json"
    assert (
        dgo.main(["--a-only", "--out-csv", str(out_csv), "--out-json", str(out_json)])
        == 0
    )
    derived = pd.read_csv(out_csv, keep_default_na=False, dtype=str)
    a_rows = pd.DataFrame(committed[committed["Derivation"] == dgo.DERIVED_FROM_KPIS])
    pd.testing.assert_frame_equal(
        derived.reset_index(drop=True), a_rows.reset_index(drop=True)
    )
    # Every row not derivable from the KPIs is one the thesis code gave.
    b_rows = committed[committed["Derivation"] == dgo.RECOMPUTED]
    assert len(a_rows) + len(b_rows) == len(committed)
    not_compared = json.loads(out_json.read_text())["not_compared"]
    assert len(not_compared) == len(b_rows)


def test_provenance_describes_the_committed_files() -> None:
    record = json.loads(PROVENANCE.read_text())
    assert record["output"]["sha256"] == dgo.sha256_file(OBJECTIVES)
    for name, digest in record["inputs"].items():
        assert dgo.sha256_file(PARITY_DIR / "golden" / name) == digest
    assert record["not_compared"] == []
    assert record["thesis_check"]["max_rel_deviation_single_run"] < 1e-6
    assert record["output"]["by_derivation"] == {
        "a_golden_kpis": 657,
        "b_thesis_code": 102,
    }


def test_every_single_run_problem_has_a_golden_objective(
    committed: pd.DataFrame,
) -> None:
    single = committed[committed["Source"] == "single_run"]
    counts = single.groupby(["Approach", "Method"]).size().to_dict()
    for method in harness.METHODS:
        assert counts[("individual_optimization", method)] == 9
        assert counts[("cluster_optimization", method)] == 1
        assert counts[("integrated_portfolio_optimization", method)] == 1
    assert set(single["Derivation"]) == {dgo.DERIVED_FROM_KPIS}


def test_objective_formulas() -> None:
    kpis = {"E_Residual": 3.0, "E_Uncovered": 10.0, "CVaR_Uncovered": 50.0}
    assert dgo.objective_from_kpis(dgo.MSE, None, kpis) == 9.0
    assert dgo.objective_from_kpis(dgo.EXPECTED_UNCOVERED, None, kpis) == 10.0
    value = dgo.objective_from_kpis(dgo.WEIGHTED_CVAR, 0.9, kpis)
    assert value == pytest.approx(0.9 * 50.0 + 0.1 * 10.0)
    with pytest.raises(dgo.DerivationError):
        dgo.objective_from_kpis(dgo.WEIGHTED_CVAR, None, kpis)
    with pytest.raises(dgo.DerivationError):
        dgo.objective_from_kpis("other", None, kpis)
    np_text = "[0.00000000e+00 2.77558997e+03\n 2.31563400e+04]"
    assert dgo.parse_printed_array(np_text) == [0.0, 2775.58997, 23156.34]
    with pytest.raises(dgo.DerivationError):
        dgo.parse_printed_array("1 2")


def test_golden_objectives_load_in_the_harness() -> None:
    golden = harness.load_golden(objectives=OBJECTIVES)
    assert golden.objectives is not None
    assert len(golden.objectives) == 759
    derivations = {o.derivation for o in golden.objectives}
    assert derivations == {"a_golden_kpis", "b_thesis_code"}
    assert all(o.kpi_source for o in golden.objectives)


def test_golden_content_matches_the_manifest() -> None:
    golden = harness.load_golden()
    assert harness.check_manifest(golden.content_sha256) == {
        "full_optimization_results.csv": "matches",
        "benchmarking_kpis.csv": "matches",
    }


def test_check_manifest_flags_differences(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"golden": {"a.csv": {"sha256": "1" * 64}}}))
    out = harness.check_manifest({"a.csv": "2" * 64, "b.csv": "3" * 64}, manifest)
    assert out["a.csv"].startswith("differs")
    assert out["b.csv"] == "not in the manifest"
    assert harness.check_manifest({"a.csv": "1" * 64}, manifest) == {"a.csv": "matches"}
    assert harness.check_manifest({"a.csv": "x"}, tmp_path / "none.json") == {}


# -- noise, policy, committed report ----------------------------------------


def test_runner_noise_draws_equal_the_thesis_noise_layer(
    config_and_input: tuple,
) -> None:
    config, data = config_and_input
    check = rdp.noise_check(config, data)
    assert check.kind == "heteroscedastic"
    assert check.summary_deviation <= 1e-12
    if check.same_platform:
        assert check.bit_identical, check.text()
    assert "Noise draws" in check.text()


def test_parity_policy_is_the_thesis_policy() -> None:
    # Owner decision (MAR-98): the gate runs with the policy that reproduces
    # the thesis solves, OSQP at cvxpy's default accuracy, Clarabel first for
    # the LPs.
    from parametric_insurance_design.solve import THESIS_POLICY

    policy = rdp.PARITY_POLICY
    assert policy is THESIS_POLICY
    assert policy.lp_solvers[0] == "CLARABEL"
    assert policy.qp_solvers[0] == "OSQP"
    assert "OSQP" not in policy.solver_options
    assert policy.accept_inaccurate


def test_committed_report_explains_every_finding() -> None:
    text = REPORT.read_text(encoding="utf-8")
    match = re.search(r"\n(\d+) findings, (\d+) of them explained, 0 not yet\.\n", text)
    assert match is not None, "the committed report has unexplained findings"
    assert "- Golden records compared: single_run." in text
    assert "| Objective values | 33 | 33 | 33 | 0 | 0 |" in text
    assert "## Appendix: the thesis payouts under our design problems" in text
    assert "Solver policy: by owner decision (MAR-98)" in text
    assert "`solve.THESIS_POLICY`" in text
    assert "Thesis MSE solver error:" in text
    assert "Noise draws:" in text
    assert report.PENDING not in text
    assert report.load_explanations(EXPLANATIONS)


def test_cvar_matches_the_definition() -> None:
    import numpy as np

    values = np.array([0.0, 1.0, 2.0, 10.0])
    prob = np.full(4, 0.25)
    assert rdp.cvar(values, prob, 0.75) == pytest.approx(10.0)
    # beta 0.5: the worst half, mean of 2 and 10.
    assert rdp.cvar(values, prob, 0.5) == pytest.approx(6.0)
    # beta 0.6: VaR 2 carries 0.15 of the 0.4 tail.
    assert rdp.cvar(values, prob, 0.6) == pytest.approx((0.25 * 10 + 0.15 * 2) / 0.4)


# -- against the thesis code ------------------------------------------------


@pytest.fixture(scope="module")
def thesis_repo() -> Path:
    value = os.environ.get("PARITY_THESIS_REPO")
    if not value:
        pytest.skip(
            "PARITY_THESIS_REPO is not set; set it to a checkout of "
            "https://github.com/marc272/parametric-insurance-framework to "
            "recompute the golden objectives with the thesis code"
        )
    return Path(value)


def test_golden_objectives_rewrite_identically(
    tmp_path: Path, thesis_repo: Path
) -> None:
    out_csv, out_json = tmp_path / "o.csv", tmp_path / "o.json"
    args = ["--thesis-repo", str(thesis_repo), "--out-csv", str(out_csv)]
    assert dgo.main([*args, "--out-json", str(out_json)]) == 0
    assert out_csv.read_bytes() == OBJECTIVES.read_bytes()
    written = json.loads(out_json.read_text())
    committed = json.loads(PROVENANCE.read_text())
    written["output"].pop("file")
    committed["output"].pop("file")
    assert written == committed


# -- slow: the runs themselves ----------------------------------------------


def _findings(text: str) -> set[str]:
    return set(re.findall(r"^\| `(P-[0-9a-f]{10})` \|", text, flags=re.MULTILINE))


def _overview(text: str) -> list[str]:
    section = text.split("## Overview", 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("| ")]


@pytest.mark.parity_full
def test_default_runs_reproduce_the_committed_report(tmp_path: Path) -> None:
    out = tmp_path / "REPORT.md"
    args = [
        "--store",
        str(tmp_path / "store"),
        "--out",
        str(out),
        "--analysis",
        str(tmp_path / "analysis.md"),
        "--check",
    ]
    assert rdp.main(args) == 0  # every run solved, every finding explained
    ours, committed = out.read_text(), REPORT.read_text()
    assert _findings(ours) == _findings(committed)
    assert _overview(ours)[:4] == _overview(committed)[:4]  # counts, not errors
    assert "| KPI values | 432 | 432 | 422 | 10 | 0 |" in ours
    assert "| Objective values | 33 | 33 | 33 | 0 | 0 |" in ours


@pytest.mark.parity_full
def test_thesis_payouts_are_alternative_optima(config_and_input: tuple) -> None:
    config, data = config_and_input
    checks = rdp.thesis_payout_checks(config, data, harness.load_golden())
    assert len(checks) == 33
    for c in checks:
        label = f"{c.scope}/{c.objective}/{c.problem_id}"
        assert abs(c.gap) <= 1e-7, label
        assert abs(c.midpoint_gap) <= 1e-7, label
        if c.objective != "mse":  # OSQP's default accuracy: see the appendix
            assert c.thesis.max_bound_violation <= 1e-3, label
            assert c.thesis.budget <= 1e-8, label
