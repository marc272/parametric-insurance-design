"""Separately calibrated cluster runs get their own scope key and label (MAR-225).

A cluster scope with ``joint: false`` (MAR-180, one design problem per
cluster) has ``runs.scope = "cluster"``, like the joint cluster scope. The
figures and site bundles key it ``cluster_separate`` and label it "Cluster
scope, calibrated per cluster" (``style.config_scope_name``,
``style.run_scope_name``), so a figure or bundle holding both never shows
them under one key or label. The store here holds the individual, joint
cluster, separately calibrated cluster and portfolio scopes. Runs written
before MAR-225 lack the ``cluster_joint`` parameter; their problem ids
(``cluster:C<k>``) still tell them apart.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import pyarrow as pa
import pytest
from matplotlib.figure import Figure

from parametric_insurance_design.experiment import runner
from parametric_insurance_design.experiment.config import parse_config
from parametric_insurance_design.records import ALL_PROBLEMS
from parametric_insurance_design_viz import site_export, style
from parametric_insurance_design_viz.command import _scope_keys, write_figures
from parametric_insurance_design_viz.errors import (
    FigureDataError,
    InconsistentRunsError,
)
from parametric_insurance_design_viz.figure_data import MAIN_TABLE
from parametric_insurance_design_viz.kpi_figures import (
    exceedance_curves,
    kpi_figures,
    kpi_heatmap,
    performance_overview,
)
from parametric_insurance_design_viz.reader import ResultReader, RunResult
from parametric_insurance_design_viz.sweep_figures import SweepSeries, sensitivity

from .conftest import build_fixture, config_dict

if TYPE_CHECKING:
    from conftest import Fixture

CLUSTER = {
    "kind": "cluster",
    "n_clusters": 2,
    "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
}
SCOPES = [
    {"kind": "individual"},
    CLUSTER,
    {**CLUSTER, "joint": False},
    {"kind": "portfolio"},
]
OBJECTIVES = [{"kind": "mse"}, {"kind": "expected_uncovered"}]
KEYS = ["individual", "cluster", "cluster_separate", "portfolio"]
LABELS = [
    "Individual scope",
    "Cluster scope",
    "Cluster scope, calibrated per cluster",
    "Portfolio scope",
]


def four_scopes(directory: Path) -> Fixture:
    return build_fixture(directory, scopes=SCOPES, objectives=OBJECTIVES)


@pytest.fixture(scope="module")
def four(tmp_path_factory: pytest.TempPathFactory) -> Fixture:
    """Individual, joint cluster, separate cluster and portfolio scopes."""
    return four_scopes(tmp_path_factory.mktemp("four"))


def grid(fixture: Fixture) -> dict[str, tuple[RunResult, ...]]:
    """Runs per scope key, as the figures command passes them."""
    runs = ResultReader(fixture.store).runs(fixture.run_ids)
    per = len(fixture.config.objectives)
    keys = _scope_keys(fixture.config)
    return {k: tuple(runs[i * per : (i + 1) * per]) for i, k in enumerate(keys)}


def flat(text: str) -> str:
    """A tick label without the figures' line wrapping."""
    return " ".join(text.split())


def tick_labels(figure: Figure, axis: Callable[[Any], Any]) -> list[str]:
    return [flat(t.get_text()) for ax in figure.axes for t in axis(ax)]


# -- style -------------------------------------------------------------------------


def test_config_scope_name_names_the_separate_cluster_scope(tmp_path: Path) -> None:
    config = parse_config(config_dict(scopes=SCOPES, objectives=OBJECTIVES))
    names = [style.config_scope_name(s) for s in config.scopes]
    assert names == KEYS
    assert style.SEPARATE_CLUSTER_SCOPE == "cluster_separate"


def test_the_separate_cluster_scope_has_its_own_label_and_style() -> None:
    assert [style.scope_label(k) for k in KEYS] == LABELS
    styles = [style.SCOPE_STYLES[k] for k in KEYS]
    assert len(set(styles)) == len(KEYS)


# -- keys and names of a store with all four scopes ---------------------------------


def test_four_scopes_have_four_keys(four: Fixture) -> None:
    assert _scope_keys(four.config) == KEYS
    assert site_export._scope_keys(four.config) == KEYS
    runs = grid(four)
    for key, scope_runs in runs.items():
        assert {style.run_scope_name(r) for r in scope_runs} == {key}
        separate = key == style.SEPARATE_CLUSTER_SCOPE
        for run in scope_runs:
            params = run.parameters
            if separate:
                assert params[style.CLUSTER_JOINT_PARAMETER] is False
            else:
                assert style.CLUSTER_JOINT_PARAMETER not in params
    # runs.scope alone does not tell the two cluster settings apart
    assert {r.scope for r in runs["cluster"] + runs["cluster_separate"]} == {"cluster"}


def test_kpi_figures_label_the_four_scopes_distinctly(four: Fixture) -> None:
    runs = grid(four)
    heatmap = kpi_heatmap(runs, "cvar_uncovered")
    labels = tick_labels(heatmap.figure, lambda ax: ax.get_yticklabels())
    assert [lb for lb in labels if lb in LABELS] == list(reversed(LABELS))
    overview = performance_overview(runs)
    labels = tick_labels(overview.figure, lambda ax: ax.get_xticklabels())
    assert set(LABELS) <= set(labels)
    assert not [lb for lb in labels if "(" in lb]  # no "(cluster_2)"-style keys
    for figure in (heatmap, overview):
        assert sorted(set(figure.data[MAIN_TABLE]["scope_key"])) == sorted(KEYS)
    curves = exceedance_curves(runs["cluster_separate"])
    assert curves.name == "exceedance_cluster_separate"
    assert set(curves.data[MAIN_TABLE]["scope_key"]) == {"cluster_separate"}


def test_the_figures_command_writes_four_scope_keys(
    four: Fixture, tmp_path: Path
) -> None:
    report = write_figures(
        four.config,
        four.run_ids,
        store=four.store,
        out_dir=tmp_path,
        eventset=four.eventset,
        figure_sets=(kpi_figures,),
    )
    assert report.ok
    written = {w.name: w for w in report.written}
    assert {f"exceedance_{k}" for k in KEYS} <= set(written)
    table = pd.read_csv(written["kpi_heatmap_cvar_uncovered"].tables[MAIN_TABLE])
    assert sorted(set(table["scope_key"])) == sorted(KEYS)


def test_sweep_legends_label_the_four_scopes_distinctly(four: Fixture) -> None:
    series = [SweepSeries("alpha", key, runs[0]) for key, runs in grid(four).items()]
    assert [s.scope_name for s in series] == KEYS
    assert [s.scope_kind for s in series] == [
        "individual",
        "cluster",
        "cluster",
        "portfolio",
    ]
    figure = sensitivity("alpha", series, values=[0.5, 0.9])
    (legend,) = figure.figure.legends
    texts = [t.get_text() for t in legend.get_texts()]
    assert [t for t in texts if t in LABELS] == LABELS
    assert sorted(set(figure.data[MAIN_TABLE]["scope"])) == sorted(KEYS)


def test_export_site_writes_four_scope_keys(four: Fixture, tmp_path: Path) -> None:
    site_export.export_site(
        four.config,
        four.run_ids,
        store=four.store,
        out_dir=tmp_path,
        eventset=four.eventset,
    )
    entries = json.loads((tmp_path / "runs.json").read_text(encoding="utf-8"))["runs"]
    per = len(four.config.objectives)
    assert [e["scope_key"] for e in entries] == [k for k in KEYS for _ in range(per)]
    for entry in entries:
        separate = entry["scope_key"] == "cluster_separate"
        assert (style.CLUSTER_JOINT_PARAMETER in entry["parameters"]) is separate
    for name in ("kpis", "exceedance", "payouts", "map"):
        with pa.memory_map(str(tmp_path / f"baseline.{name}.arrow")) as source:
            table = pa.ipc.open_file(source).read_all().to_pandas()
        assert sorted(set(table["scope_key"])) == sorted(KEYS), name


# -- run_scope_name: its sources ---------------------------------------------------


def with_parameters(
    run: RunResult, change: Callable[[dict[str, Any]], None]
) -> RunResult:
    def edit(text: str) -> str:
        data = json.loads(text)
        change(data)
        return json.dumps(data)

    return replace(
        run, runs=run.runs.assign(parameters=run.runs["parameters"].map(edit))
    )


def without_configured_joint(run: RunResult) -> RunResult:
    """The manifest config's cluster scope without ``joint``: it reads True."""
    manifest = json.loads(json.dumps(run.manifest))
    manifest["config"]["scopes"][0].pop("joint", None)
    return replace(run, manifest=manifest)


def without_manifest_config(run: RunResult) -> RunResult:
    manifest = {k: v for k, v in run.manifest.items() if k != "config"}
    return replace(run, manifest=manifest)


def without_parameter(run: RunResult) -> RunResult:
    return with_parameters(run, lambda p: p.pop(style.CLUSTER_JOINT_PARAMETER))


def test_run_scope_name_reads_the_problem_ids_without_the_parameter(
    four: Fixture,
) -> None:
    legacy = without_parameter(grid(four)["cluster_separate"][0])
    assert style.run_scope_name(legacy) == "cluster_separate"
    # the problem ids alone decide
    alone = without_manifest_config(legacy)
    assert style.run_scope_name(alone) == "cluster_separate"
    joint = without_manifest_config(grid(four)["cluster"][0])
    assert style.run_scope_name(joint) == "cluster"


def test_run_scope_name_of_a_failed_build(four: Fixture) -> None:
    """A failed build has only the problem id "*": the other sources decide."""
    run = grid(four)["cluster_separate"][0]
    failed = replace(run, runs=run.runs.iloc[[0]].assign(problem_id=ALL_PROBLEMS))
    assert style.run_scope_name(failed) == "cluster_separate"
    assert style.run_scope_name(without_manifest_config(failed)) == "cluster_separate"
    assert style.run_scope_name(without_parameter(failed)) == "cluster_separate"
    # no evidence at all: the joint cluster scope, runs.scope
    bare = without_manifest_config(without_parameter(failed))
    assert style.run_scope_name(bare) == "cluster"


def test_run_scope_name_refuses_disagreeing_sources(four: Fixture) -> None:
    joint = grid(four)["cluster"][0]
    claimed = with_parameters(
        joint, lambda p: p.update({style.CLUSTER_JOINT_PARAMETER: False})
    )
    with pytest.raises(InconsistentRunsError, match="disagree"):
        style.run_scope_name(claimed)
    separate = grid(four)["cluster_separate"][0]
    with pytest.raises(InconsistentRunsError, match="disagree"):
        style.run_scope_name(without_configured_joint(separate))
    mixed = replace(
        separate,
        runs=separate.runs.assign(
            problem_id=["portfolio", *list(separate.runs["problem_id"])[1:]]
        ),
    )
    with pytest.raises(InconsistentRunsError, match="mix"):
        style.run_scope_name(mixed)


@pytest.mark.parametrize("value", [True, "false", 0])
def test_run_scope_name_refuses_a_recorded_value_other_than_false(
    four: Fixture, value: object
) -> None:
    run = grid(four)["cluster_separate"][0]
    odd = with_parameters(
        run, lambda p: p.update({style.CLUSTER_JOINT_PARAMETER: value})
    )
    with pytest.raises(FigureDataError, match="only as false"):
        style.run_scope_name(odd)


def test_run_scope_name_refuses_a_configured_joint_that_is_not_a_bool(
    four: Fixture,
) -> None:
    run = grid(four)["cluster"][0]
    manifest = json.loads(json.dumps(run.manifest))
    manifest["config"]["scopes"][0]["joint"] = "no"
    with pytest.raises(FigureDataError, match="not a bool"):
        style.run_scope_name(replace(run, manifest=manifest))


def test_other_scopes_keep_their_runs_scope(four: Fixture) -> None:
    runs = grid(four)
    for key in ("individual", "portfolio"):
        assert style.run_scope_name(runs[key][0]) == key


# -- a store written before MAR-225 ------------------------------------------------


def test_a_store_written_before_mar_225_is_keyed_and_labelled_alike(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without ``cluster_joint`` in the runs' parameters (MAR-180 runs)."""
    recorded = runner.run_parameters

    def before_mar_225(*args: Any, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
        params = recorded(*args, **kwargs)
        params.pop(style.CLUSTER_JOINT_PARAMETER, None)
        return params

    monkeypatch.setattr(runner, "run_parameters", before_mar_225)
    legacy = four_scopes(tmp_path / "store")
    monkeypatch.undo()
    runs = grid(legacy)
    assert not any(
        style.CLUSTER_JOINT_PARAMETER in r.parameters
        for rs in runs.values()
        for r in rs
    )
    assert [style.run_scope_name(rs[0]) for rs in runs.values()] == KEYS
    heatmap = kpi_heatmap(runs, "cvar_uncovered")
    labels = tick_labels(heatmap.figure, lambda ax: ax.get_yticklabels())
    assert [lb for lb in labels if lb in LABELS] == list(reversed(LABELS))
    out = tmp_path / "bundle"
    site_export.export_site(
        legacy.config,
        legacy.run_ids,
        store=legacy.store,
        out_dir=out,
        eventset=legacy.eventset,
    )
    entries = json.loads((out / "runs.json").read_text(encoding="utf-8"))["runs"]
    assert sorted({e["scope_key"] for e in entries}) == sorted(KEYS)
