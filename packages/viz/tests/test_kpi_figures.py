"""Tests of the KPI figures (MAR-111): their figure data on small fixture stores."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd
import pytest
import yaml

from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.runner import (
    load_input,
    run_config,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design_viz.command import (
    FIGURE_SETS,
    SkippedFigure,
    payout_figures,
    write_figures,
)
from parametric_insurance_design_viz.errors import (
    FigureDataError,
    IncompleteRunError,
    InconsistentRunsError,
)
from parametric_insurance_design_viz.figure_data import write_figure
from parametric_insurance_design_viz.kpi_figures import (
    CURVE_COLUMNS,
    KPI_COLUMNS,
    Baseline,
    exceedance_curves,
    kpi_figures,
    kpi_heatmap,
    kpi_label,
    kpi_table,
    performance_overview,
)
from parametric_insurance_design_viz.payout_functions import AxisLabels
from parametric_insurance_design_viz.reader import ResultReader, RunResult

if TYPE_CHECKING:
    from conftest import Fixture

SCOPES = ("individual", "cluster", "portfolio")
OBJECTIVES = ("mse", "expected_uncovered", "weighted_cvar")
KPI_NAMES = [
    "kpi_heatmap_cvar_uncovered",
    "kpi_heatmap_expected_uncovered",
    "performance_overview",
]


def grid(fixture: Fixture) -> dict[str, tuple[RunResult, ...]]:
    reader = ResultReader(fixture.store)
    n = len(fixture.config.objectives)
    ids = fixture.run_ids
    return {
        s.kind: reader.runs(ids[i * n : (i + 1) * n])
        for i, s in enumerate(fixture.config.scopes)
    }


def where(frame: pd.DataFrame, mask: Any) -> pd.DataFrame:  # noqa: ANN401
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


def store_kpi(run: RunResult, kpi: str, split: str = "full") -> float:
    k = run.kpis
    rows = where(
        k,
        (k["level"] == "portfolio") & (k["kpi"] == kpi) & (k["eval_split"] == split),
    )
    assert len(rows) == 1
    return float(rows["value"].iloc[0])


@pytest.fixture(scope="module")
def toy_grid(toy: Fixture) -> dict[str, tuple[RunResult, ...]]:
    return grid(toy)


# -- variants of the toy config, built in this file ------------------------------


@dataclass(frozen=True)
class Variant:
    config: ExperimentConfig
    store: ResultStore
    run_ids: tuple[str, ...]


def variant(toy: Fixture, directory: Path, **changes: Any) -> Variant:  # noqa: ANN401
    data = toy.config.model_dump(mode="json")
    data.update(
        scopes=[{"kind": "individual"}, {"kind": "portfolio"}],
        objectives=[
            {"kind": "mse"},
            {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.9},
        ],
        output={"directory": str(directory / "results")},
    )
    data.update(changes)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = load_config(path)
    run_config(config)
    checksum = load_input(config).checksum
    run_ids = tuple(run_key(config_hash(s), checksum) for s in config.single_runs())
    return Variant(config, ResultStore(config.output.directory), run_ids)


def variant_grid(v: Variant) -> dict[str, tuple[RunResult, ...]]:
    reader = ResultReader(v.store)
    n = len(v.config.objectives)
    return {
        s.kind: reader.runs(v.run_ids[i * n : (i + 1) * n])
        for i, s in enumerate(v.config.scopes)
    }


@pytest.fixture(scope="module")
def beta95(toy: Fixture, tmp_path_factory: pytest.TempPathFactory) -> Variant:
    """Evaluation beta 0.95: the VaR return period (20) is not a stored one."""
    return variant(toy, tmp_path_factory.mktemp("beta95"), evaluation={"beta": 0.95})


def as_holdout(run: RunResult) -> RunResult:
    """The run's rows relabelled as a train split, plus test rows (values x 2).

    The runner cannot write holdout runs yet (``splits.holdout`` is MAR-22),
    so the train and test rows are made from the full-sample rows.
    """

    def split(table: pd.DataFrame) -> pd.DataFrame:
        train = table.assign(eval_split="train")
        test = table.assign(eval_split="test", value=table["value"] * 2)
        return pd.concat([train, test], ignore_index=True)

    return dataclasses.replace(
        run, kpis=split(run.kpis), exceedance=split(run.exceedance)
    )


@pytest.fixture(scope="module")
def holdout(toy_grid: dict) -> dict[str, tuple[RunResult, ...]]:
    """Holdout-like runs: KPI and curve rows on the train and the test split."""
    return {
        k: tuple(as_holdout(r) for r in toy_grid[k])
        for k in ("individual", "portfolio")
    }


def as_annual(run: RunResult) -> RunResult:
    """The run's rows relabelled as annual: AEP and OEP (values / 2) curves.

    The runner cannot evaluate the annual basis yet (MAR-24), so the curves
    are made from the event curve.
    """
    curves = run.exceedance.assign(basis="annual")
    aep = curves.assign(curve="aep")
    oep = curves.assign(curve="oep", value=curves["value"] / 2)
    return dataclasses.replace(
        run,
        kpis=run.kpis.assign(basis="annual"),
        exceedance=pd.concat([aep, oep], ignore_index=True),
    )


@pytest.fixture(scope="module")
def annual(toy_grid: dict) -> dict[str, tuple[RunResult, ...]]:
    """Annual-basis runs: AEP and OEP curves instead of the event curve."""
    return {"portfolio": tuple(as_annual(r) for r in toy_grid["portfolio"])}


# -- kpi_table -------------------------------------------------------------------


def test_kpi_table_reads_the_portfolio_rows(toy_grid: dict) -> None:
    table = kpi_table(toy_grid, ["cvar_uncovered", "expected_uncovered"])
    assert list(table.columns) == list(KPI_COLUMNS)
    assert len(table) == 3 * 3 * 2
    assert list(table["scope_key"].unique()) == list(SCOPES)
    assert list(table["objective"].unique()) == list(OBJECTIVES)
    assert set(table["eval_split"]) == {"full"}
    assert set(table["subject_id"]) == {"portfolio"}
    # the individual scope's portfolio rows aggregate its design problems
    assert set(table.loc[table["scope"] == "individual", "problem_id"]) == {"*"}
    cvar = table[table["kpi"] == "cvar_uncovered"]
    assert set(cvar["beta"]) == {0.9}
    assert table.loc[table["kpi"] == "expected_uncovered", "beta"].isna().all()
    for row in cast(Any, table.itertuples(index=False)):
        run = next(r for r in toy_grid[row.scope_key] if r.run_id == row.run_id)
        assert run.objective == row.objective
        assert row.value == pytest.approx(store_kpi(run, row.kpi))


def test_kpi_table_errors(toy_grid: dict, failed: Fixture) -> None:
    with pytest.raises(InconsistentRunsError, match="unknown KPIs"):
        kpi_table(toy_grid, ["not_a_kpi"])
    with pytest.raises(InconsistentRunsError, match="unknown KPIs"):
        kpi_table(toy_grid, [])
    with pytest.raises(InconsistentRunsError, match="at least one scope"):
        kpi_table({}, ["cvar_uncovered"])
    with pytest.raises(InconsistentRunsError, match="has no runs"):
        kpi_table({"individual": ()}, ["cvar_uncovered"])
    mixed = {"individual": (toy_grid["individual"][0], toy_grid["portfolio"][1])}
    with pytest.raises(InconsistentRunsError, match="mixes runs"):
        kpi_table(mixed, ["cvar_uncovered"])
    twice = {"individual": (toy_grid["individual"][0],) * 2}
    with pytest.raises(InconsistentRunsError, match="repeats an objective"):
        kpi_table(twice, ["cvar_uncovered"])
    reordered = {
        "individual": toy_grid["individual"],
        "portfolio": tuple(reversed(toy_grid["portfolio"])),
    }
    with pytest.raises(InconsistentRunsError, match="in that order"):
        kpi_table(reordered, ["cvar_uncovered"])
    with pytest.raises(InconsistentRunsError, match="'test' split"):
        kpi_table(toy_grid, ["cvar_uncovered"], eval_split="test")
    with pytest.raises(InconsistentRunsError, match=r"at beta 0\.5"):
        kpi_table(toy_grid, ["cvar_uncovered"], beta=0.5)
    reader = ResultReader(failed.store)
    cluster = reader.run(failed.run_id("cluster", "mse"))
    with pytest.raises(IncompleteRunError):
        kpi_table({"cluster": (cluster,)}, ["cvar_uncovered"])


def test_kpi_table_prefers_the_test_split(holdout: dict) -> None:
    scopes = holdout
    table = kpi_table(scopes, ["expected_uncovered"])
    assert set(table["eval_split"]) == {"test"}
    run = scopes["portfolio"][0]
    value = table.loc[table["run_id"] == run.run_id, "value"].iloc[0]
    assert value == pytest.approx(store_kpi(run, "expected_uncovered", "test"))
    train = kpi_table(scopes, ["expected_uncovered"], eval_split="train")
    assert set(train["eval_split"]) == {"train"}
    assert not np.allclose(train["value"], table["value"])


def test_runs_must_share_a_split_and_beta(toy_grid: dict, holdout: dict) -> None:
    mixed = {
        "individual": toy_grid["individual"][:1],
        "portfolio": holdout["portfolio"][:1],
    }
    with pytest.raises(InconsistentRunsError, match="share no evaluation split"):
        kpi_table(mixed, ["expected_uncovered"])
    run = toy_grid["individual"][0]
    other = dataclasses.replace(
        toy_grid["portfolio"][0],
        runs=toy_grid["portfolio"][0].runs.assign(
            parameters=run.runs["parameters"]
            .iloc[0]
            .replace('"evaluation_beta":0.9', '"evaluation_beta":0.8')
        ),
    )
    assert other.parameters["evaluation_beta"] == 0.8
    with pytest.raises(InconsistentRunsError, match="differ in evaluation_beta"):
        kpi_table({"individual": (run,), "portfolio": (other,)}, ["cvar_uncovered"])


def test_duplicated_kpi_rows_are_an_error(toy_grid: dict) -> None:
    run = toy_grid["portfolio"][0]
    doubled = dataclasses.replace(run, kpis=pd.concat([run.kpis, run.kpis]))
    with pytest.raises(InconsistentRunsError, match="has 2 portfolio rows"):
        kpi_table({"portfolio": (doubled,)}, ["expected_uncovered"])


def test_kpi_label() -> None:
    assert kpi_label("cvar_uncovered", unit="USD") == (
        r"Tail basis risk $CVaR(UL^p)$ [USD]"
    )
    assert kpi_label("expected_uncovered") == r"Total basis risk $E(UL^p)$"
    assert kpi_label("correlation") == "correlation"


# -- heatmap ---------------------------------------------------------------------


def test_heatmap_data(toy_grid: dict, tmp_path: Path) -> None:
    output = kpi_heatmap(toy_grid, "cvar_uncovered")
    assert output.name == "kpi_heatmap_cvar_uncovered"
    written = write_figure(output, tmp_path)
    assert written.image.is_file()
    main = pd.read_csv(written.tables[""])
    assert list(main.columns) == [
        *KPI_COLUMNS,
        "baseline_value",
        "pct_vs_baseline",
        "is_baseline",
        "row",
        "col",
    ]
    assert len(main) == 9
    base = where(main, main["is_baseline"])
    assert list(zip(base["scope_key"], base["objective"], strict=True)) == [
        ("individual", "mse")
    ]
    ref = store_kpi(toy_grid["individual"][0], "cvar_uncovered")
    assert np.allclose(main["baseline_value"], ref)
    expected = (main["value"] - ref) / ref * 100
    assert np.allclose(main["pct_vs_baseline"], expected)
    assert base["pct_vs_baseline"].iloc[0] == 0
    assert list(main["row"]) == [0, 0, 0, 1, 1, 1, 2, 2, 2]
    assert list(main["col"]) == [0, 1, 2] * 3
    legend = pd.read_csv(written.tables["legend"])
    assert list(legend.columns) == ["class", "lower_pct", "upper_pct"]
    assert len(legend) == 7
    max_abs = float(np.abs(main["pct_vs_baseline"]).max())
    assert legend["lower_pct"].iloc[0] == pytest.approx(-max_abs)
    assert legend["upper_pct"].iloc[-1] == pytest.approx(max_abs)
    assert np.allclose(legend["lower_pct"].iloc[1:], legend["upper_pct"].iloc[:-1])


def test_heatmap_baseline_and_colours(toy_grid: dict) -> None:
    baseline = Baseline("portfolio", "weighted_cvar")
    output = kpi_heatmap(toy_grid, "expected_uncovered", baseline=baseline)
    main = output.data[""]
    assert main.loc[main["is_baseline"], "objective"].tolist() == ["weighted_cvar"]
    ref = store_kpi(toy_grid["portfolio"][2], "expected_uncovered")
    assert np.allclose(main["baseline_value"], ref)
    better = int(np.argmin(main["pct_vs_baseline"].to_numpy()))

    def colour(out: object, i: int) -> tuple[float, ...]:
        ax = out.figure.axes[0]  # type: ignore[attr-defined]
        return tuple(ax.patches[i].get_facecolor())

    lower = kpi_heatmap(toy_grid, "expected_uncovered", baseline=baseline)
    higher = kpi_heatmap(
        toy_grid, "expected_uncovered", baseline=baseline, lower_is_better=False
    )
    green, red = colour(lower, better), colour(higher, better)
    assert green[1] > green[0]  # lower is better: the lowest value is green
    assert red[0] > red[1]
    with pytest.raises(InconsistentRunsError, match="baseline"):
        kpi_heatmap(toy_grid, "cvar_uncovered", baseline=Baseline("x", "mse"))
    with pytest.raises(FigureDataError, match="n_legend_bins"):
        kpi_heatmap(toy_grid, "cvar_uncovered", n_legend_bins=0)


def test_baseline_default_without_the_benchmark(toy_grid: dict) -> None:
    scopes = {k: v[1:] for k, v in toy_grid.items()}
    assert Baseline.default(scopes) == Baseline("individual", "expected_uncovered")
    assert Baseline.default(toy_grid) == Baseline("individual", "mse")
    assert Baseline("individual", "mse").label(toy_grid) == (
        "individual scope & residual loss objective"
    )


def test_heatmap_with_a_zero_baseline_has_no_change(toy_grid: dict) -> None:
    run = toy_grid["individual"][0]
    kpis = run.kpis.copy()
    kpis.loc[kpis["kpi"] == "cvar_uncovered", "value"] = 0.0
    zero = dataclasses.replace(run, kpis=kpis)
    scopes = {**toy_grid, "individual": (zero, *toy_grid["individual"][1:])}
    main = kpi_heatmap(scopes, "cvar_uncovered").data[""]
    assert bool(main["pct_vs_baseline"].isna().all())


# -- performance overview --------------------------------------------------------


def test_performance_overview_data(toy_grid: dict, tmp_path: Path) -> None:
    output = performance_overview(toy_grid, labels=AxisLabels(payout_unit="USD"))
    written = write_figure(output, tmp_path)
    assert written.name == "performance_overview"
    main = pd.read_csv(written.tables[""])
    assert list(main.columns) == [
        *KPI_COLUMNS,
        "baseline_value",
        "pct_vs_baseline",
        "is_baseline",
        "bar_x",
    ]
    assert list(main["kpi"].unique()) == ["cvar_uncovered", "expected_uncovered"]
    assert len(main) == 18
    for kpi, rows in main.groupby("kpi"):
        ref = store_kpi(toy_grid["individual"][0], str(kpi))
        assert np.allclose(rows["baseline_value"], ref)
        assert int(rows["is_baseline"].to_numpy().sum()) == 1
        # bars: three groups of three, 0.1 apart within a group
        assert np.allclose(
            rows["bar_x"], [-0.1, 0.0, 0.1, 0.35, 0.45, 0.55, 0.8, 0.9, 1.0]
        )
    fig = output.figure
    assert fig.axes[0].get_ylabel() == r"Tail basis risk $CVaR(UL^p)$ [USD]"
    assert [len(ax.patches) for ax in fig.axes] == [9, 9]


def test_performance_overview_panels(toy_grid: dict) -> None:
    output = performance_overview(
        toy_grid, kpis=["rmse_residual"], figsize=None, name="overview_rmse"
    )
    assert output.name == "overview_rmse"
    assert list(output.data[""]["kpi"].unique()) == ["rmse_residual"]
    assert len(output.figure.axes) == 1


# -- exceedance curves -----------------------------------------------------------


def stored_curve(
    run: RunResult, curve: str = "event", split: str = "full"
) -> pd.DataFrame:
    e = run.exceedance
    mask = (
        (e["level"] == "portfolio")
        & (e["quantity"] == "uncovered")
        & (e["curve"] == curve)
        & (e["eval_split"] == split)
    )
    return where(e, mask).sort_values("return_period")


def test_exceedance_data(toy_grid: dict, tmp_path: Path) -> None:
    runs = toy_grid["portfolio"]
    output = exceedance_curves(runs)
    assert output.name == "exceedance_portfolio"
    written = write_figure(output, tmp_path)
    main = pd.read_csv(written.tables[""])
    assert list(main.columns) == list(CURVE_COLUMNS)
    # beta 0.9: the VaR return period 10 is a stored point, nothing is added
    assert set(main["source"]) == {"exceedance"}
    assert set(main["curve"]) == {"event"}
    for run in runs:
        rows = where(main, main["run_id"] == run.run_id)
        store = stored_curve(run)
        assert rows["objective"].iloc[0] == run.objective
        assert np.allclose(rows["return_period"], store["return_period"])
        assert np.allclose(rows["value"], store["value"])
    markers = pd.read_csv(written.tables["markers"])
    assert markers.to_dict("records") == [
        {
            "marker": "var_return_period",
            "beta": 0.9,
            "return_period": 10.0,
            "drawn": True,
        }
    ]


def test_exceedance_adds_the_var_point(beta95: Variant) -> None:
    runs = variant_grid(beta95)["individual"]
    main = exceedance_curves(runs, scope_key="individual").data[""]
    added = where(main, main["source"] == "kpis")
    assert list(added["return_period"]) == [20.0, 20.0]
    for run in runs:
        point = where(added, added["run_id"] == run.run_id)
        assert point["value"].iloc[0] == pytest.approx(store_kpi(run, "var_uncovered"))
        rows = where(main, main["run_id"] == run.run_id)
        assert rows["return_period"].is_monotonic_increasing
        assert len(rows) == len(stored_curve(run)) + 1
        # the VaR is the curve's lower quantile, so it sits between its neighbours
        values = rows["value"].to_numpy()
        assert np.all(np.diff(values) >= -1e-9)


def test_exceedance_curve_kinds(annual: dict, toy_grid: dict) -> None:
    runs = annual["portfolio"]
    main = exceedance_curves(runs).data[""]
    assert set(main["curve"]) == {"aep"}
    assert set(main["basis"]) == {"annual"}
    store = stored_curve(runs[0], "aep")
    rows = main[(main["run_id"] == runs[0].run_id) & (main["source"] == "exceedance")]
    assert np.allclose(rows["value"], store["value"])
    oep = exceedance_curves(runs, curve="oep").data[""]
    assert set(oep["curve"]) == {"oep"}
    assert set(oep["source"]) == {"exceedance"}  # VaR is an aggregate quantile
    loss = exceedance_curves(runs, quantity="loss").data[""]
    assert set(loss["quantity"]) == {"loss"}
    assert set(loss["source"]) == {"exceedance"}
    mixed = [toy_grid["portfolio"][0], runs[1]]
    with pytest.raises(InconsistentRunsError, match="mix curve kinds"):
        exceedance_curves(mixed)


def test_exceedance_without_a_drawn_var_line(toy_grid: dict) -> None:
    output = exceedance_curves(toy_grid["cluster"], beta=0.999, name="exc")
    assert output.name == "exc"
    markers = output.data["markers"]
    assert markers["return_period"].iloc[0] == pytest.approx(1000.0)
    assert not markers["drawn"].iloc[0]
    assert set(output.data[""]["source"]) == {"exceedance"}
    unbounded = exceedance_curves(toy_grid["cluster"], beta=1.0)
    assert np.isinf(unbounded.data["markers"]["return_period"].iloc[0])


def test_exceedance_errors(toy_grid: dict, holdout: dict) -> None:
    runs = toy_grid["portfolio"]
    with pytest.raises(InconsistentRunsError, match="at least one run"):
        exceedance_curves([])
    with pytest.raises(InconsistentRunsError, match="no portfolio exceedance rows"):
        exceedance_curves(runs, quantity="nothing")
    with pytest.raises(InconsistentRunsError, match="exactly one portfolio 'aep'"):
        exceedance_curves(runs, curve="aep")
    first = runs[0]
    shorter = dataclasses.replace(
        first, exceedance=first.exceedance[first.exceedance["return_period"] < 100]
    )
    with pytest.raises(InconsistentRunsError, match="different return periods"):
        exceedance_curves([shorter, *runs[1:]])
    other = holdout["portfolio"]
    with pytest.raises(InconsistentRunsError, match="share no evaluation split"):
        exceedance_curves([runs[0], other[1]])


# -- the figure set ---------------------------------------------------------------


def test_kpi_figures_are_registered() -> None:
    assert FIGURE_SETS[:2] == (payout_figures, kpi_figures)


def test_figures_command_writes_the_kpi_figures(toy: Fixture, tmp_path: Path) -> None:
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=tmp_path,
        eventset=toy.eventset,
        figure_sets=(kpi_figures,),
    )
    assert report.ok
    assert report.skipped == ()
    names = [*KPI_NAMES, *(f"exceedance_{s}" for s in SCOPES)]
    assert [w.name for w in report.written] == names
    for w in report.written:
        assert w.image.is_file()
        assert all(p.is_file() for p in w.tables.values())
    overview = pd.read_csv(tmp_path / "performance_overview.csv")
    assert set(overview["run_id"]) == set(toy.run_ids)
    assert toy.eventset.metadata.loss.unit == "USD"


def test_default_figure_set_includes_the_kpi_figures(
    toy: Fixture, tmp_path: Path
) -> None:
    report = write_figures(toy.config, toy.run_ids, store=toy.store, out_dir=tmp_path)
    names = [w.name for w in report.written]
    assert names[6:12] == [*KPI_NAMES, *(f"exceedance_{s}" for s in SCOPES)]


def test_failed_runs_skip_the_kpi_figures(failed: Fixture, tmp_path: Path) -> None:
    report = write_figures(
        failed.config,
        failed.run_ids,
        store=failed.store,
        out_dir=tmp_path,
        figure_sets=(kpi_figures,),
    )
    assert not report.ok
    assert [w.name for w in report.written] == ["exceedance_portfolio"]
    assert [(s.name, s.failed) for s in report.skipped] == [
        (name, True) for name in [*KPI_NAMES, "exceedance_cluster"]
    ]
    assert all("cluster x mse" in s.reason for s in report.skipped)
    assert isinstance(report.skipped[0], SkippedFigure)


def test_repeated_scope_kinds_keep_their_key(toy: Fixture, tmp_path: Path) -> None:
    scopes = toy.config.scopes
    config = toy.config.model_copy(update={"scopes": (scopes[2], scopes[2])})
    ids = [toy.run_id("portfolio", o) for o in OBJECTIVES] * 2
    report = write_figures(
        config, ids, store=toy.store, out_dir=tmp_path, figure_sets=(kpi_figures,)
    )
    names = [w.name for w in report.written]
    assert names[-2:] == ["exceedance_portfolio", "exceedance_portfolio_2"]
    heatmap = pd.read_csv(tmp_path / "kpi_heatmap_cvar_uncovered.csv")
    assert list(heatmap["scope_key"].unique()) == ["portfolio", "portfolio_2"]


def test_repeated_scope_labels() -> None:
    from parametric_insurance_design_viz.kpi_figures import _scope_text

    class Run:
        scope = "cluster"

    scopes: Any = {"cluster": [Run()], "cluster_2": [Run()]}
    assert _scope_text("cluster", scopes) == "Cluster scope"
    assert _scope_text("cluster_2", scopes) == "Cluster scope (cluster_2)"
