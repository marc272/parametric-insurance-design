"""Tests of the KPI figures (MAR-111): their figure data on small fixture stores.

Every store here is written by the core runner: the full-sample toy store
(``conftest``), an annual-basis store (MAR-24), a holdout store and a k-fold
store (MAR-137). No rows are relabelled.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
import yaml
from matplotlib.axes import Axes
from matplotlib.container import ErrorbarContainer
from numpy.typing import NDArray

from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.kfold import PooledKpis, pooled_kpis
from parametric_insurance_design.experiment.runner import (
    load_input,
    prepare_eventset,
    run_config,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design_viz import command
from parametric_insurance_design_viz.command import (
    FIGURE_SETS,
    FigureContext,
    SkippedFigure,
    payout_figures,
    write_figures,
)
from parametric_insurance_design_viz.errors import (
    FigureDataError,
    IncompleteRunError,
    InconsistentRunsError,
)
from parametric_insurance_design_viz.figure_data import FigureOutput, write_figure
from parametric_insurance_design_viz.kpi_figures import (
    CURVE_COLUMNS,
    KPI_COLUMNS,
    OVERVIEW_KPIS,
    POOLED_EXCEEDANCE_REASON,
    POOLED_KPI_COLUMNS,
    Baseline,
    KFoldRunsError,
    exceedance_curves,
    heatmap_figsize,
    interval_note,
    kpi_figures,
    kpi_heatmap,
    kpi_label,
    kpi_table,
    performance_overview,
    pooled_kpi_table,
    return_period_label,
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


def drawn(frame: pd.DataFrame) -> NDArray[np.bool_]:
    """The figure data's ``ci_drawn`` column as a numpy array."""
    return frame["ci_drawn"].to_numpy(dtype=bool)


def cell_text(value: float) -> str:
    """The thesis heatmap cell text, written out here as the test's oracle.

    Plain with two decimals for exponents -1 to 2, else e.g. ``1.66e6``.
    """
    if not np.isfinite(value):
        return ""
    if value == 0:
        return "0"
    exp = int(np.floor(np.log10(abs(value))))
    if -1 <= exp <= 2:
        return f"{value:.2f}"
    return f"{value / 10**exp:.2f}e{exp}"


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


@pytest.fixture(scope="module")
def holdout_store(toy: Fixture, tmp_path_factory: pytest.TempPathFactory) -> Variant:
    """A real holdout store (MAR-137): calibrated on years 0-41, tested on 42-59.

    The runner writes every KPI and curve row twice, on the ``train`` split
    (in sample) and on the ``test`` split (out of sample).
    """
    return variant(
        toy,
        tmp_path_factory.mktemp("holdout"),
        sample={"kind": "holdout", "train_fraction": 0.7},
    )


@pytest.fixture(scope="module")
def holdout(holdout_store: Variant) -> dict[str, tuple[RunResult, ...]]:
    """The holdout store's runs per scope (individual, portfolio)."""
    return variant_grid(holdout_store)


BOOTSTRAP = {"seed": 0, "n_bootstrap": 200, "level": 0.9}


@pytest.fixture(scope="module")
def holdout_ci_store(toy: Fixture, tmp_path_factory: pytest.TempPathFactory) -> Variant:
    """A real holdout store with block-bootstrap intervals (MAR-23, MAR-148).

    The runner fills ``ci_low``, ``ci_high``, ``ci_level`` and
    ``n_bootstrap`` of every KPI row, on both splits.
    """
    return variant(
        toy,
        tmp_path_factory.mktemp("holdout_ci"),
        sample={"kind": "holdout", "train_fraction": 0.7},
        bootstrap=BOOTSTRAP,
    )


@pytest.fixture(scope="module")
def holdout_ci(holdout_ci_store: Variant) -> dict[str, tuple[RunResult, ...]]:
    """The bootstrapped holdout store's runs per scope (individual, portfolio)."""
    return variant_grid(holdout_ci_store)


@pytest.fixture(scope="module")
def kfold(toy: Fixture, tmp_path_factory: pytest.TempPathFactory) -> Variant:
    """A real k-fold store (k = 2): a run per scope x objective x fold."""
    return variant(
        toy, tmp_path_factory.mktemp("kfold"), sample={"kind": "kfold", "k": 2}
    )


@pytest.fixture(scope="module")
def annual(
    toy: Fixture, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, tuple[RunResult, ...]]:
    """Annual-basis runs (MAR-24): AEP and OEP curves instead of the event curve.

    The toy's 60 events are spread over 30 years (two per year, rate 1/30),
    so that the yearly sum (AEP) and the largest event of a year (OEP)
    differ; years whose rows the threshold filter drops are zero-loss years.
    """
    directory = tmp_path_factory.mktemp("annual")
    raw = EventSet.from_parquet(toy.path.parent / "eventset")
    n_years = 30
    events = raw.events.assign(year=np.arange(raw.n_rows) % n_years, rate=1.0 / n_years)
    EventSet(
        events=events,
        locations=raw.locations,
        index=raw.index,
        loss=raw.loss,
        metadata=dataclasses.replace(raw.metadata, n_years=n_years),
    ).to_parquet(directory / "eventset")
    v = variant(toy, directory, basis="annual", eventset={"path": "eventset"})
    return {"portfolio": variant_grid(v)["portfolio"]}


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


def test_the_holdout_store_is_real(holdout: dict) -> None:
    for runs in holdout.values():
        for run in runs:
            assert run.parameters["sample"] == "holdout"
            assert set(run.runs["calibration_split"]) == {"train"}
            assert set(run.kpis["eval_split"]) == {"train", "test"}
            assert set(run.exceedance["eval_split"]) == {"train", "test"}


def test_kpi_table_prefers_the_test_split(holdout: dict) -> None:
    scopes = holdout
    kpis = ["cvar_uncovered", "expected_uncovered"]
    table = kpi_table(scopes, kpis)
    assert set(table["eval_split"]) == {"test"}
    assert len(table) == 2 * 2 * 2
    for row in cast(Any, table.itertuples(index=False)):
        run = next(r for r in scopes[row.scope_key] if r.run_id == row.run_id)
        assert row.value == pytest.approx(store_kpi(run, row.kpi, "test"))
    train = kpi_table(scopes, kpis, eval_split="train")
    assert set(train["eval_split"]) == {"train"}
    for row in cast(Any, train.itertuples(index=False)):
        run = next(r for r in scopes[row.scope_key] if r.run_id == row.run_id)
        assert row.value == pytest.approx(store_kpi(run, row.kpi, "train"))
    # out of sample and in sample are different numbers
    assert not np.allclose(train["value"], table["value"])
    with pytest.raises(InconsistentRunsError, match="'full' split"):
        kpi_table(scopes, kpis, eval_split="full")


def test_holdout_heatmap_and_curves_read_the_test_split(holdout: dict) -> None:
    main = kpi_heatmap(holdout, "cvar_uncovered").data[""]
    assert set(main["eval_split"]) == {"test"}
    ref = store_kpi(holdout["individual"][0], "cvar_uncovered", "test")
    assert np.allclose(main["baseline_value"], ref)
    runs = holdout["portfolio"]
    curves = exceedance_curves(runs).data[""]
    assert set(curves["eval_split"]) == {"test"}
    for run in runs:
        rows = where(curves, curves["run_id"] == run.run_id)
        stored = stored_curve(run, split="test")
        assert np.allclose(rows["return_period"], stored["return_period"])
        assert np.allclose(rows["value"], stored["value"])


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
        "ci_drawn",
    ]
    assert len(main) == 9
    # no bootstrap in the toy config: no interval, no footnote
    intervals = main[["ci_low", "ci_high", "ci_level", "n_bootstrap"]]
    assert np.isnan(intervals.to_numpy(dtype=np.float64)).all()
    assert not drawn(main).any()
    assert not [t for t in output.figure.texts if "interval" in t.get_text()]
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


def test_heatmap_height_follows_the_rows(toy_grid: dict) -> None:
    """Fewer than three scope rows: a lower figure, same cells (MAR-232)."""
    assert heatmap_figsize(3) == heatmap_figsize(5) == (8.0, 8.0)
    one, two = heatmap_figsize(1), heatmap_figsize(2)
    assert one[0] == two[0] == 8.0
    row = 8.0 - two[1]
    assert row == pytest.approx(0.62 * 8.0 / 3)
    assert one[1] == pytest.approx(8.0 - 2 * row)
    with pytest.raises(FigureDataError, match="at least one row"):
        heatmap_figsize(0)
    full = kpi_heatmap(toy_grid, "cvar_uncovered")
    single = kpi_heatmap({"individual": toy_grid["individual"]}, "cvar_uncovered")
    assert tuple(full.figure.get_size_inches()) == (8.0, 8.0)
    assert tuple(single.figure.get_size_inches()) == pytest.approx(one)
    # the cells keep their size: the axes are as high in inches
    heights = [
        out.figure.axes[0].get_position().height * out.figure.get_size_inches()[1]
        for out in (full, single)
    ]
    assert heights[1] == pytest.approx(heights[0] / 3)
    fixed = kpi_heatmap(toy_grid, "cvar_uncovered", figsize=(8.0, 8.0))
    assert tuple(fixed.figure.get_size_inches()) == (8.0, 8.0)


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
        "ci_drawn",
    ]
    assert not drawn(main).any()
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
    # without bounds: no interval bars and the legend has the baseline only
    assert [interval_bars(ax) for ax in fig.axes] == [[], []]
    assert legend_texts(fig)[-1] == [
        "Baseline (individual scope & residual loss objective)"
    ]


def test_performance_overview_panels(toy_grid: dict) -> None:
    output = performance_overview(
        toy_grid, kpis=["rmse_residual"], figsize=None, name="overview_rmse"
    )
    assert output.name == "overview_rmse"
    assert list(output.data[""]["kpi"].unique()) == ["rmse_residual"]
    assert len(output.figure.axes) == 1


# -- confidence intervals (MAR-148) ----------------------------------------------


def interval_bars(ax: Axes) -> list[tuple[float, float, float]]:
    """``(x, low, high)`` of every interval bar drawn on ``ax``, by x."""
    out: list[tuple[float, float, float]] = []
    for container in ax.containers:
        if isinstance(container, ErrorbarContainer):
            _, _, columns = container.lines
            for segment in columns[0].get_segments():
                (x0, y0), (x1, y1) = segment
                assert x0 == x1
                out.append((float(x0), float(min(y0, y1)), float(max(y0, y1))))
    return sorted(out)


def legend_texts(fig: Any) -> list[list[str]]:  # noqa: ANN401
    return [[t.get_text() for t in legend.get_texts()] for legend in fig.legends]


def store_row(run: RunResult, kpi: str, split: str) -> pd.Series:
    k = run.kpis
    rows = where(
        k,
        (k["level"] == "portfolio") & (k["kpi"] == kpi) & (k["eval_split"] == split),
    )
    assert len(rows) == 1
    return rows.iloc[0]


def test_the_bootstrapped_store_is_real(holdout_ci: dict) -> None:
    for runs in holdout_ci.values():
        for run in runs:
            assert run.parameters["sample"] == "holdout"
            assert run.manifest["bootstrap"]["n_bootstrap"] == 200
            kpis = run.kpis
            assert set(kpis["ci_level"]) == {0.9}
            assert set(kpis["n_bootstrap"]) == {200}
            portfolio = where(kpis, kpis["level"] == "portfolio")
            assert np.isfinite(portfolio["ci_low"].to_numpy(dtype=float)).any()


def test_kpi_table_reads_the_intervals(holdout_ci: dict) -> None:
    table = kpi_table(holdout_ci, ["cvar_uncovered", "expected_uncovered"])
    assert set(table["eval_split"]) == {"test"}
    assert set(table["ci_level"]) == {0.9}
    assert table["n_bootstrap"].tolist() == [200] * len(table)
    for row in cast(Any, table.itertuples(index=False)):
        run = next(r for r in holdout_ci[row.scope_key] if r.run_id == row.run_id)
        stored = store_row(run, row.kpi, "test")
        assert row.value == stored["value"]
        assert row.ci_low == stored["ci_low"]
        assert row.ci_high == stored["ci_high"]
        assert row.ci_low < row.ci_high
    assert interval_note(table) == ("90% block-bootstrap interval over years (B = 200)")


def test_overview_draws_the_stored_intervals(holdout_ci: dict, tmp_path: Path) -> None:
    output = performance_overview(holdout_ci)
    written = write_figure(output, tmp_path)
    main = pd.read_csv(written.tables[""])
    assert drawn(main).all()
    for ax, kpi in zip(output.figure.axes, OVERVIEW_KPIS, strict=True):
        rows = where(main, main["kpi"] == kpi).sort_values("bar_x")
        bars = interval_bars(ax)
        assert len(bars) == len(rows) == 4
        assert np.allclose([b[0] for b in bars], rows["bar_x"])
        assert np.allclose([b[1] for b in bars], rows["ci_low"])
        assert np.allclose([b[2] for b in bars], rows["ci_high"])
    assert legend_texts(output.figure)[-1] == [
        "Baseline (individual scope & residual loss objective)",
        "90% block-bootstrap interval over years (B = 200)",
    ]


def test_heatmap_shows_the_stored_intervals(holdout_ci: dict) -> None:
    output = kpi_heatmap(holdout_ci, "cvar_uncovered")
    main = output.data[""]
    assert drawn(main).all()
    texts = [t.get_text() for t in output.figure.axes[0].texts]
    for row in cast(Any, main.itertuples(index=False)):
        assert f"[{cell_text(row.ci_low)}, {cell_text(row.ci_high)}]" in texts
    notes = [t.get_text() for t in output.figure.texts]
    assert "In brackets: 90% block-bootstrap interval over years (B = 200)" in notes


def test_rows_without_bounds_draw_without_an_interval(holdout_ci: dict) -> None:
    """A KPI undefined in some replicate has null bounds next to ci_level."""
    run = holdout_ci["portfolio"][1]
    kpis = run.kpis.copy()
    undefined = (kpis["kpi"] == "cvar_uncovered") & (kpis["eval_split"] == "test")
    kpis.loc[undefined, ["ci_low", "ci_high"]] = np.nan
    scopes = {
        **holdout_ci,
        "portfolio": (holdout_ci["portfolio"][0], dataclasses.replace(run, kpis=kpis)),
    }
    output = performance_overview(scopes)
    main = output.data[""]
    missing = (
        (main["kpi"] == "cvar_uncovered") & (main["run_id"] == run.run_id)
    ).to_numpy(dtype=bool)
    assert drawn(main)[missing].tolist() == [False]
    assert drawn(main)[~missing].all()
    cvar_ax, total_ax = output.figure.axes
    assert len(interval_bars(cvar_ax)) == 3
    assert len(interval_bars(total_ax)) == 4
    heatmap = kpi_heatmap(scopes, "cvar_uncovered").data[""]
    assert int(drawn(heatmap).sum()) == 3


def test_intervals_of_different_levels_are_refused(holdout_ci: dict) -> None:
    run = holdout_ci["portfolio"][1]
    other = dataclasses.replace(run, kpis=run.kpis.assign(ci_level=0.95))
    scopes = {**holdout_ci, "portfolio": (holdout_ci["portfolio"][0], other)}
    with pytest.raises(InconsistentRunsError, match="differ in level"):
        performance_overview(scopes)
    with pytest.raises(InconsistentRunsError, match="differ in level"):
        kpi_heatmap(scopes, "expected_uncovered")
    sized = dataclasses.replace(run, kpis=run.kpis.assign(n_bootstrap=100))
    scopes = {**holdout_ci, "portfolio": (holdout_ci["portfolio"][0], sized)}
    with pytest.raises(InconsistentRunsError, match="number of replicates"):
        performance_overview(scopes)
    unlabelled = dataclasses.replace(run, kpis=run.kpis.assign(ci_level=np.nan))
    scopes = {**holdout_ci, "portfolio": (holdout_ci["portfolio"][0], unlabelled)}
    with pytest.raises(InconsistentRunsError, match="differ in level"):
        performance_overview(scopes)


def test_interval_note_without_bounds(toy_grid: dict) -> None:
    assert interval_note(kpi_table(toy_grid, ["cvar_uncovered"])) is None


def test_figures_command_draws_intervals_on_a_holdout_store(
    holdout_ci_store: Variant, tmp_path: Path
) -> None:
    v = holdout_ci_store
    report = write_figures(
        v.config,
        v.run_ids,
        store=v.store,
        out_dir=tmp_path,
        figure_sets=(kpi_figures,),
    )
    assert report.ok
    for name in KPI_NAMES:
        main = pd.read_csv(tmp_path / f"{name}.csv")
        assert drawn(main).all(), name
        assert set(main["ci_level"]) == {0.9}, name
        assert set(main["n_bootstrap"]) == {200}, name


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
            "unit": "events",  # event_conditional basis (MAR-139)
            "drawn": True,
        }
    ]
    ax = output.figure.axes[0]
    assert ax.get_xlabel() == r"Return period $RP$ [events]"
    assert any("10$ events)" in t.get_text() for t in ax.texts)


def test_exceedance_adds_the_var_point(beta95: Variant) -> None:
    runs = variant_grid(beta95)["individual"]
    output = exceedance_curves(runs, scope_key="individual")
    # the individual scope's dotted line, in the curves and the legend
    legend = output.figure.legends[0].get_lines()
    assert [line.get_linestyle() for line in legend] == [":", ":"]
    main = output.data[""]
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
    output = exceedance_curves(runs)
    main = output.data[""]
    # the annual basis counts years (MAR-117, MAR-139)
    assert output.figure.axes[0].get_xlabel() == r"Return period $RP$ [years]"
    assert output.data["markers"]["unit"].tolist() == ["years"]
    assert set(main["curve"]) == {"aep"}
    assert set(main["basis"]) == {"annual"}
    store = stored_curve(runs[0], "aep")
    rows = main[(main["run_id"] == runs[0].run_id) & (main["source"] == "exceedance")]
    assert np.allclose(rows["value"], store["value"])
    oep = exceedance_curves(runs, curve="oep").data[""]
    assert set(oep["curve"]) == {"oep"}
    assert set(oep["source"]) == {"exceedance"}  # VaR is an aggregate quantile
    # Real annual curves: the yearly sum is at least the largest event of the
    # year, and above it at some return period (two events per year).
    e = runs[0].exceedance
    portfolio_loss = (e["level"] == "portfolio") & (e["quantity"] == "loss")
    by_period = {
        kind: where(e, portfolio_loss & (e["curve"] == kind))
        .sort_values("return_period")["value"]
        .to_numpy()
        for kind in ("aep", "oep")
    }
    assert np.all(by_period["aep"] >= by_period["oep"] - 1e-9)
    assert np.any(by_period["aep"] > by_period["oep"] + 1e-9)
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


def value_axis(output: FigureOutput) -> tuple[str, list[str], list[float]]:
    """Label, tick labels and tick values of a figure's value (y) axis."""
    output.figure.canvas.draw()
    ax = output.figure.axes[0]
    labels = [t.get_text() for t in ax.get_yticklabels()]
    axis = ax.get_ylabel(), labels, [float(v) for v in ax.get_yticks()]
    plt.close(output.figure)
    return axis


def scaled(runs: tuple[RunResult, ...], factor: float) -> list[RunResult]:
    """The runs with every exceedance value multiplied by ``factor``."""
    return [
        dataclasses.replace(
            r, exceedance=r.exceedance.assign(value=r.exceedance["value"] * factor)
        )
        for r in runs
    ]


def drawn_top(runs: tuple[RunResult, ...]) -> float:
    """Largest value an exceedance figure of the runs draws (portfolio U)."""
    return max(float(stored_curve(r)["value"].to_numpy().max()) for r in runs)


def test_exceedance_tick_labels_are_distinct(toy_grid: dict) -> None:
    # MAR-197: below one million the thesis "%.1fM" repeated labels
    usd = AxisLabels(payout_unit="USD")
    for scope, runs in toy_grid.items():
        top = drawn_top(runs)
        assert top < 1e6, scope  # the toy losses are below one million
        for factor in (1.0, 1e3 / top, 2.9e5 / top, 0.3 / top):
            label, ticks, _ = value_axis(exceedance_curves(scaled(runs, factor)))
            assert len(set(ticks)) == len(ticks), (scope, factor, ticks)
        label, ticks, values = value_axis(
            exceedance_curves(scaled(runs, 2.9e5 / top), labels=usd)
        )
        assert label == "Portfolio uncovered losses $UL^P$ [k USD]"
        assert all(t.endswith("k") for t in ticks)
        assert [float(t[:-1]) * 1e3 for t in ticks] == pytest.approx(values)
        label, ticks, values = value_axis(exceedance_curves(scaled(runs, 50 / top)))
        assert label == "Portfolio uncovered losses $UL^P$"  # no unit, no prefix
        assert [float(t) for t in ticks] == pytest.approx(values)


def test_exceedance_tick_labels_in_millions_are_the_thesis_labels(
    toy_grid: dict,
) -> None:
    runs = toy_grid["portfolio"]
    top = drawn_top(runs)
    output = exceedance_curves(
        scaled(runs, 6.3e6 / top), labels=AxisLabels(payout_unit="USD")
    )
    label, ticks, values = value_axis(output)
    assert label == "Portfolio uncovered losses $UL^P$ [M USD]"
    assert ticks == [f"{v * 1e-6:.1f}M" for v in values]  # thesis format_millions
    assert ticks[:3] == ["0.0M", "1.0M", "2.0M"]
    assert len(set(ticks)) == len(ticks)


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


def test_figures_command_on_a_holdout_store(
    holdout_store: Variant, tmp_path: Path
) -> None:
    v = holdout_store
    report = write_figures(
        v.config,
        v.run_ids,
        store=v.store,
        out_dir=tmp_path,
        figure_sets=(kpi_figures,),
    )
    assert report.ok
    assert [w.name for w in report.written] == [
        *KPI_NAMES,
        "exceedance_individual",
        "exceedance_portfolio",
    ]
    for w in report.written:
        main = pd.read_csv(w.tables[""])
        assert set(main["eval_split"]) == {"test"}, w.name
    overview = pd.read_csv(tmp_path / "performance_overview.csv")
    assert set(overview["run_id"]) == set(v.run_ids)


# -- k-fold stores: refused (MAR-137) ---------------------------------------------


def kfold_runs(v: Variant) -> dict[tuple[str, str, int], RunResult]:
    """The k-fold store's runs by (scope, objective, fold)."""
    runs = ResultReader(v.store).runs(v.run_ids)
    out: dict[tuple[str, str, int], RunResult] = {}
    for single, run in zip(v.config.single_runs(), runs, strict=True):
        assert single.sample.kind == "kfold"
        assert single.sample.fold is not None
        out[single.scopes[0].kind, single.objectives[0].kind, single.sample.fold] = run
    return out


def test_the_kfold_store_is_real(kfold: Variant) -> None:
    runs = kfold_runs(kfold)
    assert len(runs) == 2 * 2 * 2
    for (scope, objective, fold), run in runs.items():
        assert (run.scope, run.objective) == (scope, objective)
        assert run.parameters["sample"] == "kfold"
        assert (run.parameters["k"], run.parameters["fold"]) == (2, fold)
        assert set(run.kpis["fold"]) == {fold}
        assert "test" in set(run.kpis["eval_split"])
    # the two folds' out-of-sample values differ: one scope x objective has k
    values = {
        f: store_kpi(runs["portfolio", "mse", f], "cvar_uncovered", "test")
        for f in (0, 1)
    }
    assert values[0] != pytest.approx(values[1])


def test_kfold_runs_are_refused(kfold: Variant, holdout: dict) -> None:
    runs = kfold_runs(kfold)
    objectives = ("mse", "weighted_cvar")
    # one fold per objective, which would pass for a holdout grid
    fold0 = {
        s: tuple(runs[s, o, 0] for o in objectives) for s in ("individual", "portfolio")
    }
    # every fold of one objective
    folds = {"portfolio": (runs["portfolio", "mse", 0], runs["portfolio", "mse", 1])}
    for scopes in (fold0, folds):
        with pytest.raises(KFoldRunsError, match=r"refuse k-fold runs \(MAR-137\)"):
            kpi_table(scopes, ["cvar_uncovered"])
    with pytest.raises(KFoldRunsError, match=r"fold 1 of k=2"):
        kpi_table(folds, ["cvar_uncovered"], eval_split="test")
    with pytest.raises(KFoldRunsError):
        kpi_heatmap(fold0, "cvar_uncovered")
    with pytest.raises(KFoldRunsError):
        performance_overview(fold0)
    with pytest.raises(KFoldRunsError):
        exceedance_curves(fold0["portfolio"])
    # one k-fold run among holdout runs is refused as well
    mixed = {
        **holdout,
        "portfolio": (holdout["portfolio"][0], runs["portfolio", "weighted_cvar", 0]),
    }
    with pytest.raises(KFoldRunsError, match="portfolio x weighted_cvar, fold 0"):
        kpi_table(mixed, ["cvar_uncovered"])
    assert issubclass(KFoldRunsError, InconsistentRunsError)


def test_a_kfold_store_without_pooled_kpis_is_refused(
    kfold: Variant, tmp_path: Path
) -> None:
    with pytest.raises(KFoldRunsError, match=r"k-fold sample \(k=2\)") as info:
        write_figures(
            kfold.config,
            kfold.run_ids,
            store=kfold.store,
            out_dir=tmp_path,
            figure_sets=(kpi_figures,),
        )
    assert "pooled out-of-sample KPIs (MAR-151)" in str(info.value)
    assert not list(tmp_path.iterdir())  # nothing is drawn


# -- k-fold stores: pooled KPIs (MAR-151) -----------------------------------------


@pytest.fixture(scope="module")
def kfold_ci(toy: Fixture, tmp_path_factory: pytest.TempPathFactory) -> Variant:
    """A real k-fold store (k = 2) with a bootstrap section (MAR-151)."""
    return variant(
        toy,
        tmp_path_factory.mktemp("kfold_ci"),
        sample={"kind": "kfold", "k": 2},
        bootstrap=BOOTSTRAP,
    )


def pooled_of(v: Variant) -> PooledKpis:
    """The core's pooled KPIs of a k-fold store, as the figures command computes."""
    prepared = prepare_eventset(v.config, load_input(v.config).eventset)
    return pooled_kpis(v.config, v.store, prepared, v.run_ids)


def capture_kpi_figures(
    monkeypatch: pytest.MonkeyPatch,
) -> list[FigureOutput | SkippedFigure]:
    """Keep the outputs of ``kpi_figures`` when ``write_figures`` runs it."""
    outputs: list[FigureOutput | SkippedFigure] = []

    def capture(context: FigureContext) -> list[FigureOutput | SkippedFigure]:
        out = kpi_figures(context)
        outputs.extend(out)
        return out

    monkeypatch.setattr(command, "KFOLD_FIGURE_SETS", (capture,))
    return outputs


def test_kfold_figures_draw_one_pooled_row_per_design(
    kfold_ci: Variant, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pooled = pooled_of(kfold_ci)
    outputs = capture_kpi_figures(monkeypatch)
    report = write_figures(
        kfold_ci.config,
        kfold_ci.run_ids,
        store=kfold_ci.store,
        out_dir=tmp_path,
        figure_sets=(command.KFOLD_FIGURE_SETS[0],),
        pooled_kpis=pooled.table,
    )
    assert report.ok
    assert [w.name for w in report.written] == KPI_NAMES
    assert [(s.name, s.failed, s.reason) for s in report.skipped] == [
        (f"exceedance_{s}", False, POOLED_EXCEEDANCE_REASON)
        for s in ("individual", "portfolio")
    ]
    table = pooled.table
    designs = [
        (s, o) for s in ("individual", "portfolio") for o in ("mse", "weighted_cvar")
    ]
    for kpi in ("cvar_uncovered", "expected_uncovered"):
        heatmap = pd.read_csv(tmp_path / f"kpi_heatmap_{kpi}.csv")
        assert list(heatmap.columns[: len(POOLED_KPI_COLUMNS)]) == list(
            POOLED_KPI_COLUMNS
        )
        # one pooled row per scope x objective, not one per fold
        assert list(zip(heatmap["scope_key"], heatmap["objective"], strict=True)) == (
            designs
        )
        assert set(heatmap["eval_split"]) == {"pooled"}
        assert bool(heatmap["fold"].isna().all())
        assert set(heatmap["k"]) == {2}
        assert drawn(heatmap).all()
        for row in heatmap.to_dict("records"):
            ids = str(row["run_id"]).split(";")
            assert len(ids) == 2
            assert set(ids) <= set(kfold_ci.run_ids)
            core = where(
                table,
                (table["scope"] == row["scope"])
                & (table["objective"] == row["objective"])
                & (table["kpi"] == kpi),
            ).iloc[0]
            for column in ("value", "ci_low", "ci_high", "ci_level"):
                assert row[column] == pytest.approx(core[column], rel=1e-12)
            assert row["n_bootstrap"] == BOOTSTRAP["n_bootstrap"]
    overview = pd.read_csv(tmp_path / "performance_overview.csv")
    assert len(overview) == len(designs) * len(OVERVIEW_KPIS)
    assert drawn(overview).all()
    # the setup of every number is stated (publication rule)
    texts = {
        o.name: [t.get_text() for t in o.figure.texts]
        for o in outputs
        if isinstance(o, FigureOutput)
    }
    for name in KPI_NAMES:
        assert any("pooled out of sample over k = 2 folds" in t for t in texts[name])
    assert any("(B = 200)" in t for t in texts["kpi_heatmap_cvar_uncovered"])


def test_kfold_figures_without_bootstrap_have_no_intervals(
    kfold: Variant, tmp_path: Path
) -> None:
    pooled = pooled_of(kfold)
    assert pooled.resample is None
    report = write_figures(
        kfold.config,
        kfold.run_ids,
        store=kfold.store,
        out_dir=tmp_path,
        figure_sets=(kpi_figures,),
        pooled_kpis=pooled.table,
    )
    assert [w.name for w in report.written] == KPI_NAMES
    heatmap = pd.read_csv(tmp_path / "kpi_heatmap_cvar_uncovered.csv")
    assert not drawn(heatmap).any()
    assert set(heatmap["eval_split"]) == {"pooled"}


def test_pooled_kpi_table_checks_its_input(kfold_ci: Variant) -> None:
    table = pooled_of(kfold_ci).table
    keys = ["individual", "portfolio"]
    out = pooled_kpi_table(table, keys, ["cvar_uncovered"])
    assert len(out) == 4
    assert out["n_bootstrap"].dtype == "Int64"
    with pytest.raises(InconsistentRunsError, match="unknown KPIs"):
        pooled_kpi_table(table, keys, ["nope"])
    with pytest.raises(InconsistentRunsError, match="lacks the columns"):
        pooled_kpi_table(table.drop(columns=["run_ids"]), keys, ["cvar_uncovered"])
    with pytest.raises(InconsistentRunsError, match="has no rows"):
        pooled_kpi_table(table.iloc[:0], keys, ["cvar_uncovered"])
    with pytest.raises(InconsistentRunsError, match="'pooled' portfolio rows"):
        pooled_kpi_table(table.assign(eval_split="test"), keys, ["cvar_uncovered"])
    with pytest.raises(InconsistentRunsError, match="the config has 1 scopes"):
        pooled_kpi_table(table, keys[:1], ["cvar_uncovered"])
    no_cvar = where(table, table["kpi"] != "cvar_uncovered")
    with pytest.raises(InconsistentRunsError, match="0 rows of KPI 'cvar_uncovered'"):
        pooled_kpi_table(no_cvar, keys, ["cvar_uncovered"])


def test_pooled_kpis_must_fit_the_config(
    kfold_ci: Variant, kfold: Variant, tmp_path: Path
) -> None:
    table = pooled_of(kfold_ci).table
    one_objective = where(table, table["objective"] == "mse")
    with pytest.raises(InconsistentRunsError, match="cover the objectives"):
        write_figures(
            kfold.config,
            kfold.run_ids,
            store=kfold.store,
            out_dir=tmp_path,
            figure_sets=(kpi_figures,),
            pooled_kpis=one_objective,
        )
    with pytest.raises(InconsistentRunsError, match="the config has k = 2"):
        write_figures(
            kfold.config,
            kfold.run_ids,
            store=kfold.store,
            out_dir=tmp_path,
            figure_sets=(kpi_figures,),
            pooled_kpis=table.assign(k=3),
        )
    with pytest.raises(InconsistentRunsError, match="cover the scopes"):
        write_figures(
            kfold.config,
            kfold.run_ids,
            store=kfold.store,
            out_dir=tmp_path,
            figure_sets=(kpi_figures,),
            pooled_kpis=where(table, table["scope_position"] == 0),
        )
    with pytest.raises(InconsistentRunsError, match="not a complete"):
        write_figures(
            kfold.config,
            kfold.run_ids,
            store=kfold.store,
            out_dir=tmp_path,
            figure_sets=(kpi_figures,),
            pooled_kpis=where(
                table,
                ~((table["scope_position"] == 1) & (table["objective"] == "mse")),
            ),
        )


def test_return_period_label_per_basis() -> None:
    assert return_period_label("event_conditional") == r"Return period $RP$ [events]"
    assert return_period_label("annual") == r"Return period $RP$ [years]"
    assert return_period_label("event") == r"Return period $RP$ [years]"


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
        # a joint cluster run, as style.run_scope_name reads it (MAR-225)
        scope = "cluster"
        parameters: dict[str, Any] = {}  # noqa: RUF012
        runs = pd.DataFrame({"problem_id": ["portfolio"]})
        manifest: dict[str, Any] = {}  # noqa: RUF012

    scopes: Any = {"cluster": [Run()], "cluster_2": [Run()]}
    assert _scope_text("cluster", scopes) == "Cluster scope"
    assert _scope_text("cluster_2", scopes) == "Cluster scope (cluster_2)"
