"""Parity of the simulation sweeps: noise level and number of assets (MAR-70).

Three groups:

- The regenerated golden tables (``golden/simulation_sweeps/``): they load in
  the harness, pair up shard by shard, stay under the file-size limit, and
  their provenance records the figure check, the subsets and the thesis
  failures.
- The harness and script rules on hand-made cases: the optional key
  columns, the baseline parameters, the subset match, merged golden sets,
  the extra-run causes.
- The committed reports: ``reports/<sweep>.md`` explain every finding, list
  no potential porting bug, and ``REPORT.md`` indexes them.

The ``parity_full`` test, which solves every sweep point, is in
``test_sweeps.py``.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
import math
import re
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import harness
import pandas as pd
import pytest
import report
from harness import FindingKind, GoldenFormatError, RecordKey

from parametric_insurance_design.experiment.config import load_config
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.experiment.sweeps import n_assets_subsets

PARITY_DIR = Path(__file__).resolve().parents[1]
SCRIPTS = PARITY_DIR / "scripts"
SIMULATION = harness.SIMULATION_DIR
PROVENANCE = SIMULATION / "provenance.json"
REPORT = PARITY_DIR / "REPORT.md"
REPORTS = {
    "noise_value_sweep": PARITY_DIR / "reports" / "noise_value_sweep.md",
    "n_assets_sweep": PARITY_DIR / "reports" / "n_assets_sweep.md",
}
ANALYSES = {name: PARITY_DIR / "analysis" / f"{name}.md" for name in REPORTS}
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
dss = _load("derive_simulation_sweeps")


@pytest.fixture(scope="module")
def provenance() -> dict[str, Any]:
    return json.loads(PROVENANCE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def simulation_golden() -> harness.Golden:
    return harness.load_simulation_golden()


# -- the regenerated golden tables -------------------------------------------


def test_simulation_golden_loads_and_counts(
    simulation_golden: harness.Golden, provenance: dict[str, Any]
) -> None:
    keys = simulation_golden.keys()
    by_source: dict[str, int] = {}
    for key in keys:
        by_source[key.source] = by_source.get(key.source, 0) + 1
    # 11 noise levels x 9 scope x objective runs, none failed.
    assert by_source["noise_value_sweep"] == 99
    # 169 subsets x 9 runs, less the 102 cluster runs on 1 or 2 assets that
    # raise in the thesis (and fail in ours).
    assert by_source["n_assets_sweep"] == 169 * 9 - 102
    noise = provenance["sweeps"]["noise_value"]
    assets = provenance["sweeps"]["n_assets"]
    assert (
        len(simulation_golden.payouts) == noise["result_rows"] + assets["result_rows"]
    )
    assert len(simulation_golden.kpis) == noise["kpi_rows"] + assets["kpi_rows"]
    noise_keys = [k for k in keys if k.source == "noise_value_sweep"]
    assert all(dict(k.extras).keys() == {"noise_level"} for k in noise_keys)
    assert all(k.locations is None for k in noise_keys)
    asset_keys = [k for k in keys if k.source == "n_assets_sweep"]
    for key in asset_keys:
        assert key.locations is not None
        assert dict(key.extras) == {"n_assets": float(len(key.locations))}


def test_simulation_golden_files_stay_under_the_size_limit() -> None:
    files = sorted(SIMULATION.iterdir())
    assert files
    for path in files:
        assert path.stat().st_size < MAX_FILE_BYTES, path


def test_provenance_records_the_figure_check_and_the_subsets(
    provenance: dict[str, Any],
) -> None:
    config = load_config(PARITY_DIR / "configs" / "thesis.yaml")
    for name, entry in provenance["sweeps"].items():
        check = entry["figure_check"]
        assert check["ok"], name
        assert not check["missing"], name
        assert check["max_rel_deviation"] < 1e-5, name
        # Every scope x objective of the thesis figure, the excluded ones not.
        assert len(check["figure_combinations"]) == 5
    subsets = provenance["sweeps"]["n_assets"]["subsets"]
    assert subsets["n_subsets"] == 169
    assert subsets["equal_to_n_assets_subsets"]
    spec = next(s for s in config.sweeps if s.parameter == "n_assets")
    assert config.portfolio.location_ids is not None
    ours = [
        repr(list(s))
        for chosen in n_assets_subsets(
            config.portfolio.location_ids,
            [int(v) for v in spec.values],
            max_combinations=spec.max_combinations,
            seed=spec.seed,
        )
        for s in chosen
    ]
    assert subsets["subsets"] == ours
    for name, meta in provenance["outputs"].items():
        assert harness.file_sha256(SIMULATION / name) == meta["sha256"], name


def test_thesis_failures_are_the_small_cluster_subsets(
    provenance: dict[str, Any],
) -> None:
    failures = provenance["sweeps"]["n_assets"]["failures"]
    assert not provenance["sweeps"]["noise_value"]["failures"]
    assert len(failures) == 102
    assert {f["approach"] for f in failures} == {"cluster_optimization"}
    by_size = {
        n: {f["message"] for f in failures if len(f["location_ids"]) == n}
        for n in (1, 2)
    }
    assert sum(len(f["location_ids"]) == 1 for f in failures) == 9 * 3
    assert sum(len(f["location_ids"]) == 2 for f in failures) == 25 * 3
    # One asset: scipy's linkage has nothing to cluster. Two assets:
    # fcluster(maxclust=3) gives at most 2 clusters, so cluster 3 is empty
    # and np.column_stack of its (no) columns raises.
    assert by_size[1] == {
        "The number of observations cannot be determined on an empty distance matrix."
    }
    assert by_size[2] == {"need at least one array to concatenate"}


def test_shards_split_by_sweep_and_asset_count() -> None:
    frame = pd.DataFrame(
        {
            "Source": ["noise_value_sweep", "n_assets_sweep", "n_assets_sweep"],
            "N_Assets": [math.nan, 2.0, 1.0],
        }
    )
    parts = dss.shards(frame)
    assert list(parts) == ["noise_value", "n_assets_1", "n_assets_2"]
    assert [len(p) for p in parts.values()] == [1, 1, 1]
    with pytest.raises(ValueError, match="no shard"):
        dss.shards(pd.DataFrame({"Source": ["alpha_sweep"], "N_Assets": [9.0]}))


def test_objective_rows_follow_the_thesis_formulas() -> None:
    base = {
        "Source": "n_assets_sweep",
        "Alpha": 0.9,
        "Beta": 0.95,
        "Budget_Loading": 1.0,
        "N_Bins": 15,
        "N_Clusters": math.nan,
        "Noise_Value": math.nan,
        "N_Assets": 1.0,
        "Location_IDs": "['A1']",
        "Subset_Index": 0,
        "CVaR_Uncovered": 100.0,
        "E_Uncovered": 10.0,
        "E_Residual": 3.0,
    }
    kpis = pd.DataFrame(
        [
            {**base, "Approach": "individual_optimization",
             "Method": "weighted_cvar_minimization", "Asset": "A1"},
            {**base, "Approach": "individual_optimization",
             "Method": "weighted_cvar_minimization", "Asset": "Portfolio"},
            {**base, "Approach": "integrated_portfolio_optimization",
             "Method": "pure_basis_risk_minimization", "Asset": "Portfolio"},
            {**base, "Approach": "integrated_portfolio_optimization",
             "Method": "pure_basis_risk_minimization", "Asset": "A1"},
        ]
    )  # fmt: skip
    rows = dss.objective_rows(kpis, 0.95)
    assert list(rows["Problem"]) == ["A1", "portfolio"]
    assert rows["Objective_Value"].tolist() == pytest.approx([0.9 * 100 + 0.1 * 10, 9])


# -- harness rules -------------------------------------------------------------


def test_record_key_text_names_the_simulation_parameters() -> None:
    plain = RecordKey(
        "individual_optimization",
        "pure_basis_risk_minimization",
        "single_run",
        (("budget_loading", 1.0), ("n_bins", 15.0)),
    )
    assert plain.parameter_text() == "budget_loading=1, n_bins=15"
    noise = dataclasses.replace(
        plain, source="noise_value_sweep", extras=(("noise_level", 0.4),)
    )
    assert noise.parameter_text() == "budget_loading=1, n_bins=15, noise_level=0.4"
    subset = dataclasses.replace(
        plain,
        source="n_assets_sweep",
        extras=(("n_assets", 2.0),),
        locations=("A1", "A7"),
    )
    assert subset.parameter_text() == (
        "budget_loading=1, n_bins=15, n_assets=2, locations=A1+A7"
    )
    assert subset.sort_key() != plain.sort_key()


def test_from_row_reads_the_optional_columns() -> None:
    row = {
        "Approach": "cluster_optimization",
        "Method": "pure_uncovered_loss_minimization",
        "Source": "n_assets_sweep",
        **{c: math.nan for c in harness.PARAMETER_COLUMNS},
        "Budget_Loading": 1.0,
        "Noise_Value": math.nan,
        "N_Assets": 2.0,
        "Location_IDs": "['A2', 'A5']",
    }
    key = RecordKey.from_row(row)
    assert key.extras == (("n_assets", 2.0),)
    assert key.locations == ("A2", "A5")
    with pytest.raises(GoldenFormatError, match="at least one"):
        RecordKey.from_row({**row, "Location_IDs": "[]"})


def _set_locations(store: ResultStore, run_id: str, ids: list[str]) -> None:
    """Give a hand-made run the prepared locations a runner manifest has."""
    manifest = store.manifest(run_id)
    manifest["prepared_eventset"] = {"location_ids": ids}
    target = store._manifest_path(run_id)
    target.write_text(json.dumps(manifest), encoding="utf-8")


def test_baseline_parameters_resolve_simulation_runs(
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, cluster, dropped = mini_specs()
    noisier = dataclasses.replace(
        cluster,
        name="cluster-noise-0.5",
        parameters={**cluster.parameters, "noise_level": 0.5},
        source="noise_value_sweep",
    )
    store = make_store([individual, cluster, noisier, dropped])
    golden = harness.load_golden(
        mini_golden.results, mini_golden.kpis, mini_golden.objectives
    )
    ambiguous = harness.compare(golden, store)
    assert {f.kind for f in ambiguous.findings} == {FindingKind.AMBIGUOUS_RUN}
    result = harness.compare(
        golden, store, baseline_parameters={"noise_level": 0.3, "n_assets": 2}
    )
    assert result.ok
    assert result.baseline_parameters == {"noise_level": 0.3, "n_assets": 2}
    assert list(result.unmatched_runs["source"]) == ["noise_value_sweep"]
    restricted = harness.compare(golden, store, run_ids=[cluster.run_id])
    assert restricted.restricted
    assert restricted.n_store_runs == 1
    with pytest.raises(harness.HarnessError, match="optional key"):
        harness.compare(golden, store, baseline_parameters={"alpha": 0.5})


def test_simulation_records_match_on_noise_level_and_subset(
    tmp_path: Path,
    mini_golden: Any,  # noqa: ANN401
    make_store: Callable[..., ResultStore],
    mini_specs: Callable[..., list[Any]],
) -> None:
    individual, cluster, _ = mini_specs()
    noisier = dataclasses.replace(
        cluster,
        name="cluster-noise-0.5",
        parameters={**cluster.parameters, "noise_level": 0.5},
    )
    subset = dataclasses.replace(
        individual,
        name="individual-a2",
        parameters={**individual.parameters, "n_assets": 1},
        problems={"A2": individual.problems["A2"]},
        entities={"A2": individual.entities["A2"]},
        payouts={"A2": individual.payouts["A2"]},
        kpis={k: v for k, v in individual.kpis.items() if k[1] != "A1"},
    )
    store = make_store([individual, cluster, noisier, subset])
    for spec, ids in ((individual, ["A1", "A2"]), (cluster, ["A1", "A2"]),
                      (noisier, ["A1", "A2"]), (subset, ["A2"])):  # fmt: skip
        _set_locations(store, spec.run_id, ids)
    # A simulation golden set of two records, from the mini tables.
    results = pd.read_csv(mini_golden.results)
    kpis = pd.read_csv(mini_golden.kpis)
    cl_r = results[results["Approach"] == "cluster_optimization"].assign(
        Source="noise_value_sweep", Noise_Value=0.5
    )
    cl_k = kpis[(kpis["Approach"] == "cluster_optimization")].assign(
        Source="noise_value_sweep", Noise_Value=0.5
    )
    a2_r = results[(results["Asset_ID"] == "A2")].assign(
        Source="n_assets_sweep", N_Assets=1, Location_IDs="['A2']"
    )
    a2_k = kpis[(kpis["Source"] == "single_run")
                & (kpis["Approach"] == "individual_optimization")
                & (kpis["Asset"] == "A2")].assign(
        Source="n_assets_sweep", N_Assets=1, Location_IDs="['A2']"
    )  # fmt: skip
    cl_r = cl_r.drop_duplicates(subset=["Asset_ID"])
    cl_k = cl_k.drop_duplicates(subset=["Asset"])
    objectives = pd.DataFrame(columns=[*harness._OBJECTIVES_COLUMNS, "Noise_Value"])
    directory = tmp_path / "sim"
    directory.mkdir()
    for shard, (r, k) in {"noise_value": (cl_r, cl_k),
                          "n_assets_1": (a2_r, a2_k)}.items():  # fmt: skip
        r.to_csv(directory / f"simulation_results_{shard}.csv.gz", index=False)
        k.to_csv(directory / f"simulation_kpis_{shard}.csv.gz", index=False)
        objectives.to_csv(
            directory / f"simulation_objectives_{shard}.csv.gz", index=False
        )
    sim = harness.load_simulation_golden(directory)
    assert {k.source for k in sim.keys()} == {"noise_value_sweep", "n_assets_sweep"}
    result = harness.compare(
        sim, store, baseline_parameters={"noise_level": 0.3, "n_assets": 2}
    )
    assert result.ok, [f.path for f in result.findings]
    rows = result.matched_runs.to_dict("records")
    matched = {r["source"]: r["run_id"] for r in rows}
    assert matched == {
        "noise_value_sweep": noisier.run_id,
        "n_assets_sweep": subset.run_id,
    }
    # Merged with the mini thesis tables: the thesis records match the
    # baseline runs, the simulation records theirs.
    merged = harness.load_golden(
        mini_golden.results, mini_golden.kpis, mini_golden.objectives
    )
    both = harness.compare(
        merged.merge(sim),
        store,
        baseline_parameters={"noise_level": 0.3, "n_assets": 2},
        sources=["single_run", "noise_value_sweep", "n_assets_sweep"],
    )
    assert both.ok, [f.path for f in both.findings]
    with pytest.raises(GoldenFormatError, match="files named"):
        sim.merge(sim)
    # A shard without its KPI table is refused.
    (directory / "simulation_kpis_n_assets_1.csv.gz").unlink()
    with pytest.raises(GoldenFormatError, match="pair up"):
        harness.load_simulation_golden(directory)


# -- script rules ----------------------------------------------------------------


def test_parameter_text_of_simulation_runs() -> None:
    baseline = {"noise_level": 0.3, "n_assets": 9}
    params = {"budget_loading": 1.0, "n_bins": 15, "noise_level": 0.3, "n_assets": 2}
    assert rdp._parameter_text(params) == "budget_loading=1, n_bins=15"
    text = rdp._parameter_text(params, baseline=baseline, locations=["A1", "A3"])
    assert text == "budget_loading=1, n_bins=15, n_assets=2, locations=A1+A3"
    noisy = {**params, "noise_level": 0.6, "n_assets": 9}
    assert rdp._parameter_text(noisy, baseline=baseline) == (
        "budget_loading=1, n_bins=15, noise_level=0.6"
    )


def test_extra_run_sort_key_and_cause(provenance: dict[str, Any]) -> None:
    baseline = {"noise_level": 0.3, "n_assets": 9}
    failures = rdp.thesis_failures(provenance, baseline)
    assert len(failures) == 102

    def extra(parameters: str, statuses: tuple[str, ...], objective: str) -> Any:  # noqa: ANN401
        return rdp.ExtraRun(
            source="n_assets_sweep",
            scope="cluster",
            objective=objective,
            parameters=parameters,
            config_hash="sha256:" + "0" * 64,
            problems=("*",),
            statuses=statuses,
            whole_run=True,
        )

    failed = extra(
        "budget_loading=1, n_bins=15, n_clusters=3, n_assets=1, locations=A4",
        ("None failed",),
        "expected_uncovered",
    )
    assert rdp.extra_cause(failed, failures).startswith(
        "thesis rerun raised `ValueError: The number of observations"
    )
    clarabel = dataclasses.replace(
        failed, objective="mse", parameters="budget_loading=0.5, n_bins=15",
        statuses=("CLARABEL optimal",),
    )  # fmt: skip
    assert rdp.extra_cause(clarabel, failures) == rdp.CAUSE_CLARABEL
    assert rdp.extra_cause(dataclasses.replace(clarabel, statuses=("OSQP optimal",)),
                           failures) == "not recorded"  # fmt: skip
    ordered = sorted([failed, clarabel], key=rdp.ExtraRun.sort_key)
    assert ordered == [failed, clarabel]  # n_clusters sorts after n_bins=15


# -- committed reports -----------------------------------------------------------


@pytest.mark.parametrize("name", sorted(REPORTS))
def test_committed_simulation_reports_explain_every_finding(name: str) -> None:
    text = REPORTS[name].read_text(encoding="utf-8")
    match = re.search(r"\n(\d+) findings, (\d+) of them explained, 0 not yet\.", text)
    assert match is not None or "\nNo findings." in text
    assert f"- Golden records compared: {name}." in text
    assert report.PENDING not in text
    assert f"Golden `{name}`: regenerated with the thesis code" in text
    analysis = ANALYSES[name].read_text(encoding="utf-8")
    assert "### Potential porting bugs\n\nNone:" in analysis
    assert "0 potential porting bug." in analysis
    assert analysis in text  # appended verbatim
    assert "### MSE under the default policy (informational, not gated)" in analysis
    for path in (REPORTS[name], ANALYSES[name]):
        assert path.stat().st_size < MAX_FILE_BYTES, path


def test_n_assets_report_lists_the_runs_that_fail_on_both_sides() -> None:
    text = ANALYSES["n_assets_sweep"].read_text(encoding="utf-8")
    assert "### Extra runs, no golden: not compared" in text
    assert text.count("thesis rerun raised `ValueError") == 2  # the two labels
    assert "(27 runs): thesis rerun raised `ValueError: The number of" in text
    assert "(75 runs): thesis rerun raised `ValueError: need at least one" in text


def _findings(text: str) -> set[str]:
    return set(re.findall(r"^\| `(P-[0-9a-f]{10})` \|", text, flags=re.MULTILINE))


def _overview(text: str) -> list[str]:
    section = text.split("## Overview", 1)[1].split("\n## ", 1)[0]
    return [line for line in section.splitlines() if line.startswith("| ")]


@pytest.mark.parity_full
def test_simulation_sweeps_reproduce_the_committed_reports(tmp_path: Path) -> None:
    # About 25 minutes: 1,620 sweep points, the thesis-payout checks and the
    # accurate MSE runs.
    args = [
        "--store",
        str(tmp_path / "store"),
        "--out",
        str(tmp_path / "REPORT.md"),
        "--analysis",
        str(tmp_path / "thesis_payouts.md"),
        "--reports-dir",
        str(tmp_path / "reports"),
        "--analysis-dir",
        str(tmp_path / "analyses"),
        "--sweep",
        "noise_level",
        "--sweep",
        "n_assets",
        "--check",
    ]
    # Every finding explained and backed by its evidence; every failed run
    # one where the thesis rerun raised too.
    assert rdp.main(args) == 0
    for name, committed in REPORTS.items():
        ours = (tmp_path / "reports" / f"{name}.md").read_text()
        theirs = committed.read_text()
        assert _findings(ours) == _findings(theirs), name
        assert _overview(ours) == _overview(theirs), name
        assert "0 potential porting bug." in ours, name


def test_main_report_indexes_the_simulation_reports() -> None:
    text = REPORT.read_text(encoding="utf-8")
    assert "## Simulation sweeps (MAR-70)" in text
    for name in REPORTS:
        assert f"[`reports/{name}.md`](reports/{name}.md)" in text
    assert re.search(
        r"\nOver the simulation-sweep reports: (\d+) findings, \1 of them "
        r"explained, 0 not yet; 0 potential porting bugs\.\n",
        text,
    )
    assert f"| {report.GATED_KPIS} |" in text
    assert f"| {report.UNGATED_KPIS} |" in text
    assert "### MSE under the default policy (informational, not gated)" in text
