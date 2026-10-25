"""Tests of the parity harness (MAR-67).

Acceptance: the harness runs on a hand-made mini golden file
(``data/mini_golden/``) against a small result store built in the test, and
flags an injected mismatch (:func:`test_injected_kpi_mismatch_is_flagged`).

The fixtures are in ``conftest.py``. ``parity_full`` tests run the thesis
experiment and are skipped unless selected (``parity/conftest.py``).
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

import harness
import numpy as np
import pytest
from harness import FindingKind, Golden, GoldenFormatError, ParityResult

from parametric_insurance_design.experiment.store import ResultStore

PARITY_DIR = Path(__file__).resolve().parents[1]


def _golden(paths: Any, *, objectives: bool = True) -> Golden:  # noqa: ANN401
    return harness.load_golden(
        paths.results, paths.kpis, paths.objectives if objectives else None
    )


def _kinds(result: ParityResult) -> list[str]:
    return [f.kind.value for f in result.findings]


# --------------------------------------------------------------------------
# Parsing the golden tables
# --------------------------------------------------------------------------


def test_parse_array_reads_numpy_prints() -> None:
    np.testing.assert_array_equal(
        harness.parse_array("[0.00000000e+00 2.77558997e+03\n 2.31563400e+04]"),
        [0.0, 2775.58997, 23156.34],
    )
    np.testing.assert_array_equal(
        harness.parse_array("[20.         23.33333333 70.        ]"),
        [20.0, 23.33333333, 70.0],
    )
    np.testing.assert_array_equal(harness.parse_array("[1.0, 2.5]"), [1.0, 2.5])
    assert harness.parse_array("[]").size == 0


@pytest.mark.parametrize("bad", ["1 2 3", "[1 two 3]", None, 3.0])
def test_parse_array_rejects_malformed_values(bad: object) -> None:
    with pytest.raises(GoldenFormatError):
        harness.parse_array(bad)


def test_parse_assets() -> None:
    assert harness.parse_assets("['A1', 'A2']") == ("A1", "A2")
    assert harness.parse_assets("[]") == ()
    assert harness.parse_assets(math.nan) is None
    assert harness.parse_assets(None) is None
    for bad in ("[1, 2]", "A1, A2", "['A1'", 3):
        with pytest.raises(GoldenFormatError):
            harness.parse_assets(bad)


def test_mini_golden_loads(mini_golden: Any) -> None:  # noqa: ANN401
    golden = _golden(mini_golden)
    assert len(golden.payouts) == 5
    assert len(golden.kpis) == 7
    assert golden.objectives is not None
    assert len(golden.objectives) == 2
    assert len(golden.keys()) == 4
    a2 = next(p for p in golden.payouts if p.entity_id == "A2")
    np.testing.assert_array_equal(a2.levels, [10.0, 200.0])  # wrapped line
    np.testing.assert_array_equal(a2.breakpoints, [20.0, 45.0, 70.0])
    c1 = next(p for p in golden.payouts if p.entity_id == "C1")
    assert c1.included == ("A1", "A2")
    assert dict(c1.key.parameters) == {
        "alpha": 0.5,
        "beta": 0.9,
        "budget_loading": 1.0,
        "n_bins": 2.0,
        "n_clusters": 1.0,
    }
    assert c1.key.scope == "cluster"
    assert c1.key.objective == "weighted_cvar"
    a2_kpis = next(k for k in golden.kpis if k.subject == "A2")
    assert math.isnan(a2_kpis.values["Correlation"])
    assert set(golden.files) == {
        "full_optimization_results.csv",
        "benchmarking_kpis.csv",
        "objectives.csv",
    }


def test_load_golden_rejects_bad_tables(tmp_path: Path, mini_golden: Any) -> None:  # noqa: ANN401
    results = mini_golden.results.read_text(encoding="utf-8")
    kpis = mini_golden.kpis.read_text(encoding="utf-8")
    cases = {
        "missing column": results.replace("Breakpoints", "Edges"),
        "unknown approach": results.replace("cluster_optimization", "clusters", 1),
        "repeated key": results + results.splitlines()[-1] + "\n",
    }
    for name, text in cases.items():
        bad = tmp_path / f"{name.replace(' ', '_')}.csv"
        bad.write_text(text, encoding="utf-8")
        with pytest.raises(GoldenFormatError):
            harness.load_golden(bad, mini_golden.kpis)
    bad_kpis = tmp_path / "kpis.csv"
    bad_kpis.write_text(kpis.replace(",0.8\n", ",high\n"), encoding="utf-8")
    with pytest.raises(GoldenFormatError, match="number"):
        harness.load_golden(mini_golden.results, bad_kpis)


def test_committed_thesis_golden_loads() -> None:
    golden = harness.load_golden()
    assert len(golden.payouts) == 1551
    assert len(golden.kpis) == 1776
    assert golden.objectives is None
    for p in golden.payouts:
        assert len(p.breakpoints) == len(p.levels) + 1
        assert len(p.levels) == dict(p.key.parameters)["n_bins"]
    sources = {k.source for k in golden.keys()}
    assert sources == {
        "single_run",
        "alpha_sweep",
        "beta_sweep",
        "budget_loading_sweep",
        "n_bins_sweep",
        "n_clusters_sweep",
    }
    clusters = [p for p in golden.payouts if p.key.approach == "cluster_optimization"]
    assert clusters
    assert all(p.included for p in clusters)


# --------------------------------------------------------------------------
# Comparisons on the mini golden
# --------------------------------------------------------------------------


def test_matching_store_has_no_findings(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = harness.compare(_golden(mini_golden), make_store())
    assert result.ok, [f.path for f in result.findings]
    assert result.n_store_runs == 3
    assert result.unmatched_runs.empty
    # 7 KPI subjects x 6 KPIs; A2's undefined correlation matches ours.
    assert len(result.kpis) == 42
    assert set(result.kpis["status"]) == {"match"}
    assert list(result.payouts["status"]) == ["compared"] * 5
    assert list(result.clusters["status"]) == ["match", "match"]
    assert list(result.objectives["status"]) == ["match", "match"]
    assert result.payouts["max_abs_diff"].to_numpy(dtype=float).max() == 0.0


def test_injected_kpi_mismatch_is_flagged(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    # Acceptance (MAR-67): ours is 0.1 % off on A1's expected uncovered loss.
    store = make_store(kpi_offsets={("ind", "A1", 2): 1e-3})
    result = harness.compare(_golden(mini_golden), store)
    assert not result.ok
    (finding,) = result.findings
    assert finding.kind is FindingKind.KPI
    assert finding.key.approach == "individual_optimization"
    assert finding.key.source == "single_run"
    assert (finding.subject, finding.item) == ("A1", "E_Uncovered")
    assert finding.golden == "20"
    assert finding.ours == "20.02"
    assert finding.rel_error == pytest.approx(1e-3)
    assert finding.id.startswith("P-")
    assert len(finding.id) == 12
    row = result.kpis[
        (result.kpis["subject"] == "A1") & (result.kpis["kpi"] == "E_Uncovered")
    ]
    assert list(row["status"]) == ["mismatch"]
    # Same injection, same id: explanations keyed by id survive a rerun.
    again = harness.compare(_golden(mini_golden), store)
    assert again.findings[0].id == finding.id


def test_difference_within_tolerance_is_not_flagged(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    store = make_store(kpi_offsets={("ind", "A1", 2): 5e-5, ("clu", "C1", 0): -9e-5})
    result = harness.compare(_golden(mini_golden), store)
    assert result.ok
    tight = harness.compare(
        _golden(mini_golden), store, tolerances=harness.Tolerances(kpi_rtol=1e-5)
    )
    # Sorted by source, approach, method: C1 twice (alpha_sweep, single_run).
    assert [(f.key.source, f.subject, f.item) for f in tight.findings] == [
        ("alpha_sweep", "C1", "CVaR_Uncovered"),
        ("single_run", "C1", "CVaR_Uncovered"),
        ("single_run", "A1", "E_Uncovered"),
    ]


def test_value_defined_on_one_side_is_flagged(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, cluster, dropped = mini_specs()
    kpis = dict(individual.kpis)
    kpis[("entity", "A1")] = (*kpis[("entity", "A1")][:5], math.nan)
    store = make_store([dataclasses.replace(individual, kpis=kpis), cluster, dropped])
    result = harness.compare(_golden(mini_golden), store)
    (finding,) = result.findings
    assert (finding.kind, finding.subject, finding.item) == (
        FindingKind.KPI,
        "A1",
        "Correlation",
    )
    assert finding.detail == "defined on one side only"


def test_objective_mismatch_is_flagged(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = harness.compare(
        _golden(mini_golden), make_store(objective_offsets={"A2": 2e-4})
    )
    (finding,) = result.findings
    assert (finding.kind, finding.subject) == (FindingKind.OBJECTIVE, "A2")


def test_without_objective_table_objectives_are_not_compared(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = harness.compare(
        _golden(mini_golden, objectives=False),
        make_store(objective_offsets={"A2": 0.5}),
    )
    assert result.ok
    assert not result.objectives_available
    assert result.objectives.empty


def test_payout_differences_are_reported_not_flagged(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = harness.compare(
        _golden(mini_golden), make_store(payout_offsets={"A2": 4.0})
    )
    assert result.ok
    a2 = result.payouts[result.payouts["entity_id"] == "A2"].iloc[0]
    assert a2["max_abs_diff"] == pytest.approx(4.0)
    assert a2["max_rel_diff"] == pytest.approx(4.0 / 200.0)
    assert a2["status"] == "compared"


def test_other_bin_edges_or_shape_are_flagged(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, cluster, dropped = mini_specs()
    shifted = dataclasses.replace(individual, edges=(20.0, 40.0, 70.0))
    result = harness.compare(
        _golden(mini_golden), make_store([shifted, cluster, dropped])
    )
    assert _kinds(result) == ["payout_shape", "payout_shape"]
    assert "bin edges differ by up to 5" in result.findings[0].detail

    three = dataclasses.replace(
        cluster, payouts={"C1": (5.0, 100.0, 300.0)}, edges=(20.0, 30.0, 45.0, 70.0)
    )
    result = harness.compare(
        _golden(mini_golden), make_store([individual, three, dropped])
    )
    assert _kinds(result) == ["payout_shape", "payout_shape"]
    assert result.findings[0].ours == "3 levels, 4 edges"


def test_cluster_assignment_is_compared_exactly(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, cluster, dropped = mini_specs()
    split = dataclasses.replace(
        cluster,
        entities={"C1": ("portfolio", ("A1",)), "C2": ("portfolio", ("A2",))},
    )
    result = harness.compare(
        _golden(mini_golden), make_store([individual, split, dropped])
    )
    assert _kinds(result) == ["cluster_assignment", "cluster_assignment"]
    finding = result.findings[0]
    assert finding.golden == "C1={A1, A2}"
    assert finding.ours == "C1={A1}; C2={A2}"
    assert finding.detail == "the clusters differ"
    assert list(result.clusters["status"]) == ["mismatch", "mismatch"]

    relabelled = dataclasses.replace(
        cluster,
        entities={"C2": ("portfolio", ("A1", "A2"))},
        payouts={"C2": (5.0, 300.0)},
        kpis={
            ("portfolio", "Portfolio"): cluster.kpis[("portfolio", "Portfolio")],
            ("entity", "C2"): cluster.kpis[("entity", "C1")],
        },
    )
    result = harness.compare(
        _golden(mini_golden), make_store([individual, relabelled, dropped])
    )
    labels = [f for f in result.findings if f.kind is FindingKind.CLUSTER_ASSIGNMENT]
    relabel = "same partition, different cluster labels"
    assert [f.detail for f in labels] == [relabel, relabel]
    # C1 itself is then missing: its payout and its KPI row.
    assert sorted(set(_kinds(result))) == [
        "cluster_assignment",
        "missing_entity",
        "missing_kpi",
    ]


def test_missing_run_is_flagged(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, _, dropped = mini_specs()
    result = harness.compare(_golden(mini_golden), make_store([individual, dropped]))
    assert _kinds(result) == ["missing_run", "missing_run"]  # both cluster records
    assert {f.key.source for f in result.findings} == {"single_run", "alpha_sweep"}
    cluster_kpis = result.kpis[result.kpis["approach"] == "cluster_optimization"]
    assert set(cluster_kpis["status"]) == {"missing"}
    assert list(result.clusters["status"]) == ["missing", "missing"]


def test_source_must_agree_only_when_strict(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    store = make_store()
    assert harness.compare(_golden(mini_golden), store).ok
    strict = harness.compare(_golden(mini_golden), store, strict_source=True)
    (finding,) = strict.findings
    assert finding.kind is FindingKind.MISSING_RUN
    assert finding.key.source == "alpha_sweep"  # the store run is tagged single_run


def test_ambiguous_runs_are_flagged_and_fixed_parameters_resolve_them(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, cluster, dropped = mini_specs()
    noisier = dataclasses.replace(
        cluster,
        name="cluster-noise-0.5",
        parameters={**cluster.parameters, "noise_level": 0.5},
        source="noise_level_sweep",
    )
    store = make_store([individual, cluster, noisier, dropped])
    result = harness.compare(_golden(mini_golden), store)
    assert _kinds(result) == ["ambiguous_run", "ambiguous_run"]
    assert "2 runs match" in result.findings[0].detail
    fixed = harness.compare(
        _golden(mini_golden), store, fixed_parameters={"noise_level": 0.3}
    )
    assert fixed.ok
    assert list(fixed.unmatched_runs["source"]) == ["noise_level_sweep"]


def test_failed_solves_are_flagged(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, cluster, dropped = mini_specs()
    failed = dataclasses.replace(
        individual,
        problems={"A1": individual.problems["A1"], "A2": ("infeasible", None)},
        payouts={"A1": individual.payouts["A1"]},
        kpis={},  # the runner writes no KPIs if a design problem failed
    )
    result = harness.compare(
        _golden(mini_golden), make_store([failed, cluster, dropped])
    )
    assert set(_kinds(result)) == {"solve_failed"}
    by_subject = {(f.subject, f.item) for f in result.findings}
    # Payout and objective of A2, KPIs of A1, A2 and the portfolio.
    assert ("A2", "") in by_subject
    assert ("Portfolio", "") in by_subject
    assert len(result.findings) == 5
    payout = next(
        f for f in result.findings if f.subject == "A2" and f.golden == "2 levels"
    )
    assert payout.detail == "problem A2: status infeasible (InfeasibleError)"


def test_missing_kpi_without_a_failure_is_flagged(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, cluster, dropped = mini_specs()
    kpis = {k: v for k, v in individual.kpis.items() if k[0] != "portfolio"}
    result = harness.compare(
        _golden(mini_golden),
        make_store([dataclasses.replace(individual, kpis=kpis), cluster, dropped]),
    )
    (finding,) = result.findings
    assert (finding.kind, finding.subject) == (FindingKind.MISSING_KPI, "Portfolio")


def test_kpis_at_another_beta_or_basis_are_not_used(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, cluster, dropped = mini_specs()
    store = make_store([dataclasses.replace(individual, beta=0.99), cluster, dropped])
    result = harness.compare(_golden(mini_golden), store)
    missing = {(f.subject, f.item) for f in result.findings}
    assert missing == {
        (s, "CVaR_Uncovered,VaR_Uncovered") for s in ("A1", "A2", "Portfolio")
    }
    # At beta 0.99 the individual run's KPIs are found, the cluster run's not.
    at_99 = harness.compare(_golden(mini_golden), store, evaluation_beta=0.99)
    assert {f.key.approach for f in at_99.findings} == {"cluster_optimization"}
    annual = harness.compare(_golden(mini_golden), make_store(), basis="annual")
    assert {f.kind for f in annual.findings} == {FindingKind.MISSING_KPI}


def test_sources_restrict_the_golden_records(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
) -> None:
    result = harness.compare(_golden(mini_golden), make_store(), sources=["single_run"])
    assert result.ok
    assert set(result.payouts["source"]) == {"single_run"}
    assert result.sources == ("single_run",)
    # The budget-loading run is not needed by these records.
    assert list(result.unmatched_runs["source"]) == ["budget_loading_sweep"]


# --------------------------------------------------------------------------
# The thesis experiment (slow; MAR-68 runs the full comparison)
# --------------------------------------------------------------------------


@pytest.mark.parity_full
def test_thesis_default_runs_match_their_golden_records(tmp_path: Path) -> None:
    import report

    from parametric_insurance_design.experiment.config import load_config
    from parametric_insurance_design.experiment.runner import run_config

    config = load_config(PARITY_DIR / "configs" / "thesis.yaml")
    store = ResultStore(tmp_path / "store")
    run_config(config, store=store)
    result = harness.compare(harness.load_golden(), store, sources=["single_run"])
    # Every single-run record finds its run, solved, with the thesis bins and
    # clusters. Value gaps are MAR-68's to explain; here they are only shown.
    structural = {
        FindingKind.MISSING_RUN,
        FindingKind.AMBIGUOUS_RUN,
        FindingKind.SOLVE_FAILED,
        FindingKind.MISSING_ENTITY,
        FindingKind.MISSING_KPI,
        FindingKind.PAYOUT_SHAPE,
        FindingKind.CLUSTER_ASSIGNMENT,
    }
    assert not [f.path for f in result.findings if f.kind in structural]
    assert result.unmatched_runs.empty
    out = report.write_report(result, tmp_path / "REPORT.md")
    print(out.read_text(encoding="utf-8")[:4000])
