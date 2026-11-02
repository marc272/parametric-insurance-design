"""The figures of a holdout store (MAR-229): every figure reads one split and says so.

A holdout run stores its KPI rows on the train years (``eval_split =
"train"``, in sample) and on the test years (``"test"``, out of sample), and
no ``full`` rows. Before MAR-229 the sweep figures read ``full``, so the
``figures`` command exited 3 with ``MissingKpiError`` on a holdout config,
the publication rule's default (``site/configs/explorer.yaml``).

The fixture is the viz ``toy`` experiment (three locations, 60 events, every
scope and objective) on a holdout sample, with an ``alpha`` and an
``n_clusters`` sweep, so every figure of the set is drawn. It is computed at
test time by the core runner, as in ``test_sweep_figures``.
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure
from matplotlib.text import Text

from parametric_insurance_design import cli
from parametric_insurance_design.experiment.runner import load_input
from parametric_insurance_design.experiment.sweeps import run_sweeps
from parametric_insurance_design.solve import DEFAULT_POLICY
from parametric_insurance_design_viz import command
from parametric_insurance_design_viz.command import SweepRun
from parametric_insurance_design_viz.figure_data import (
    FigureOutput,
    WrittenFigure,
    write_figure,
)
from parametric_insurance_design_viz.kpi_figures import SPLIT_NOTES, split_note
from parametric_insurance_design_viz.reader import ResultReader, RunResult
from parametric_insurance_design_viz.sweep_figures import (
    SPLIT_COLUMNS,
    SPLIT_TABLE,
    MissingKpiError,
    SweepSeries,
    figure_split,
    kpi_value,
    parameter_label,
    premium_reallocation,
    sensitivity,
    tradeoff,
)

from .conftest import build_fixture

if TYPE_CHECKING:
    from conftest import Fixture

HOLDOUT = {"kind": "holdout", "train_fraction": 0.7}
SWEEPS = [
    {"parameter": "alpha", "values": [0.5, 0.9]},
    {"parameter": "n_clusters", "values": [1, 2, 3]},
]
OUT_OF_SAMPLE = "Out of sample (test years)"
IN_SAMPLE = "In sample (train years)"

PAYOUT_FIGURES = ("payout_grid_", "normalised_payout_", "payout_sweep_")
"""Figures of designs, which read no KPI and have no evaluation split."""

KPI_TABLE_FIGURES = ("kpi_heatmap_", "performance_overview", "exceedance_")
"""KPI figures whose main table has an ``eval_split`` column (MAR-111)."""

SPLIT_TABLE_FIGURES = (
    "premium_reallocation",
    "sensitivity_",
    "tradeoff_",
    "net_advantage_",
    "breakeven_cost_",
)
"""Sweep figures that read KPIs and record the split in a ``split`` table."""

EXPECTED = (
    "payout_grid_individual",
    "normalised_payout_individual_a1",
    "payout_grid_cluster",
    "normalised_payout_cluster_c1",
    "payout_grid_portfolio",
    "normalised_payout_portfolio_a1",
    "kpi_heatmap_cvar_uncovered",
    "kpi_heatmap_expected_uncovered",
    "performance_overview",
    "exceedance_individual",
    "exceedance_cluster",
    "exceedance_portfolio",
    "premium_reallocation",
    "payout_sweep_individual_a1_alpha",
    "payout_sweep_cluster_c1_alpha",
    "payout_sweep_portfolio_a1_alpha",
    "sensitivity_alpha",
    "tradeoff_portfolio_alpha",
    "sensitivity_n_clusters",
    "net_advantage_cluster",
    "breakeven_cost_cluster",
)


@dataclass(frozen=True)
class Drawn:
    """The holdout store, what ``figures`` returned and wrote, and the titles."""

    toy: Fixture
    sweeps: tuple[SweepRun, ...]
    code: int
    stdout: str
    out: Path
    texts: dict[str, list[str]]

    def csv(self, name: str, table: str = "") -> pd.DataFrame:
        suffix = f".{table}.csv" if table else ".csv"
        return pd.read_csv(self.out / f"{name}{suffix}")

    def run(self, run_id: str) -> RunResult:
        return ResultReader(self.toy.store).run(run_id)


def figure_texts(figure: Figure) -> list[str]:
    """Every non-empty text of a figure: figure texts, axes titles and texts."""
    texts: list[Text] = list(figure.texts)
    titles: list[str] = []
    for ax in figure.axes:
        titles.extend(ax.get_title(loc) for loc in ("left", "center", "right"))
        texts.extend(ax.texts)
    return [t for t in [*titles, *(x.get_text() for x in texts)] if t]


def sweep_runs(toy: Fixture) -> tuple[SweepRun, ...]:
    """The sweep points as the ``figures`` command computes them."""
    runs = cli._sweep_runs(command, toy.config, load_input(toy.config), DEFAULT_POLICY)
    return tuple(r for r in runs if isinstance(r, SweepRun))


@pytest.fixture(scope="module")
def drawn(
    tmp_path_factory: pytest.TempPathFactory,
) -> Drawn:
    toy = build_fixture(
        tmp_path_factory.mktemp("holdout"), sample=HOLDOUT, sweeps=SWEEPS
    )
    run_sweeps(toy.config, store=toy.store, baseline=False)
    out = tmp_path_factory.mktemp("holdout_figures")
    texts: dict[str, list[str]] = {}
    original = write_figure

    def recording(output: FigureOutput, *args: Any, **kwargs: Any) -> WrittenFigure:  # noqa: ANN401
        texts[output.name] = figure_texts(output.figure)
        return original(output, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(command, "write_figure", recording)
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = cli.main(["figures", str(toy.path), "--out", str(out)])
    return Drawn(
        toy=toy,
        sweeps=sweep_runs(toy),
        code=int(code),
        stdout=stdout.getvalue(),
        out=out,
        texts=texts,
    )


def kind_of(name: str) -> str:
    for kind, prefixes in (
        ("payout", PAYOUT_FIGURES),
        ("kpi", KPI_TABLE_FIGURES),
        ("split", SPLIT_TABLE_FIGURES),
    ):
        if name.startswith(prefixes):
            return kind
    raise AssertionError(f"figure {name} is of no known kind")


def series_of(fx: Drawn, parameter: str, scope: str, objective: str) -> SweepSeries:
    reader = ResultReader(fx.toy.store)
    baseline = reader.run(fx.toy.run_id(scope, objective))
    singles = list(fx.toy.run_ids).index(baseline.run_id)
    points = [p for p in fx.sweeps if p.parameter == parameter and p.single == singles]
    runs = reader.runs(tuple(p.run_id for p in points))
    return SweepSeries(
        parameter=parameter,
        scope=scope,
        baseline=baseline,
        points=tuple(zip(points, runs, strict=True)),
    )


def where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    """Rows of a frame where a boolean mask holds (typed for pyright)."""
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


def store_kpi(run: RunResult, kpi: str, split: str) -> float:
    """The portfolio row of a KPI on a split, read from the store directly."""
    k = run.kpis
    rows = where(
        k, (k["kpi"] == kpi) & (k["level"] == "portfolio") & (k["eval_split"] == split)
    )
    if bool(rows["beta"].notna().any()):
        beta = float(run.parameters["evaluation_beta"])
        rows = where(rows, np.isclose(rows["beta"].to_numpy(dtype=float), beta))
    assert len(rows) == 1
    return float(rows["value"].iloc[0])


# -- the figures command --------------------------------------------------------


def test_the_store_is_a_holdout_store(drawn: Drawn) -> None:
    for run_id in drawn.toy.run_ids:
        splits = set(drawn.run(run_id).kpis["eval_split"])
        assert splits == {"train", "test"}


def test_figures_exits_0_on_a_holdout_store(drawn: Drawn) -> None:
    assert drawn.code == cli.ExitCode.OK, drawn.stdout
    assert list(drawn.texts) == list(EXPECTED)
    assert f"{len(EXPECTED)} figures written, 0 skipped" in drawn.stdout


def test_every_figure_states_its_split(drawn: Drawn) -> None:
    """Every KPI figure reads ``test`` and says "out of sample" in its image."""
    for name, texts in drawn.texts.items():
        kind = kind_of(name)
        tables = sorted(p.name for p in drawn.out.glob(f"{name}.*csv"))
        if kind == "payout":
            # designs: no KPI, no split, no note
            assert not any(OUT_OF_SAMPLE.lower() in t.lower() for t in texts), name
            assert f"{name}.{SPLIT_TABLE}.csv" not in tables, name
            continue
        assert any(OUT_OF_SAMPLE.lower() in t.lower() for t in texts), (name, texts)
        if kind == "kpi":
            assert set(drawn.csv(name)["eval_split"]) == {"test"}, name
            assert f"{name}.{SPLIT_TABLE}.csv" not in tables, name
        else:
            split = drawn.csv(name, SPLIT_TABLE)
            assert list(split.columns) == list(SPLIT_COLUMNS)
            assert split.to_dict("records") == [
                {"eval_split": "test", "note": SPLIT_NOTES["test"]}
            ]


def test_sweep_figures_show_the_test_rows(drawn: Drawn) -> None:
    points = drawn.csv("sensitivity_alpha", "points")
    assert len(points) > 0
    for row in points.to_dict("records"):
        run = drawn.run(str(row["run_id"]))
        test = store_kpi(run, "cvar_uncovered", "test")
        assert row["kpi_value"] == pytest.approx(test, rel=1e-12)
    trade = drawn.csv("tradeoff_portfolio_alpha")
    for row in trade.to_dict("records"):
        run = drawn.run(str(row["run_id"]))
        assert row["expected_uncovered"] == pytest.approx(
            store_kpi(run, "expected_uncovered", "test"), rel=1e-12
        )
    penalty = drawn.csv("net_advantage_cluster", "penalty")
    benchmark = drawn.run(drawn.toy.run_id("portfolio", "weighted_cvar"))
    port = store_kpi(benchmark, "cvar_uncovered", "test")
    assert len(penalty) == 3
    assert penalty["cvar_portfolio"].to_numpy(dtype=float) == pytest.approx(
        [port] * 3, rel=1e-12
    )


def test_the_sensitivity_title_keeps_the_parameter(drawn: Drawn) -> None:
    title = f"{parameter_label('alpha')}\n{OUT_OF_SAMPLE}"
    assert title in drawn.texts["sensitivity_alpha"]


# -- the functions ----------------------------------------------------------------


def test_kpi_value_reads_the_run_split(drawn: Drawn, toy: Fixture) -> None:
    holdout = drawn.run(drawn.toy.run_id("portfolio", "weighted_cvar"))
    assert kpi_value(holdout, "cvar_uncovered") == store_kpi(
        holdout, "cvar_uncovered", "test"
    )
    assert kpi_value(holdout, "cvar_uncovered", eval_split="train") == store_kpi(
        holdout, "cvar_uncovered", "train"
    )
    full = ResultReader(toy.store).run(toy.run_id("portfolio", "weighted_cvar"))
    assert kpi_value(full, "cvar_uncovered") == kpi_value(
        full, "cvar_uncovered", eval_split="full"
    )


def test_a_split_the_runs_lack_is_refused(drawn: Drawn, toy: Fixture) -> None:
    holdout = drawn.run(drawn.toy.run_id("portfolio", "weighted_cvar"))
    with pytest.raises(MissingKpiError, match="split 'full'"):
        kpi_value(holdout, "cvar_uncovered", eval_split="full")
    with pytest.raises(MissingKpiError, match=r"no KPI rows on the 'full' split"):
        figure_split([holdout], "full")
    full = ResultReader(toy.store).run(toy.run_id("portfolio", "weighted_cvar"))
    # one figure never mixes splits: a full and a holdout run share none
    with pytest.raises(MissingKpiError, match="share no evaluation split"):
        figure_split([full, holdout])


def test_figure_split_prefers_test(drawn: Drawn, toy: Fixture) -> None:
    holdout = drawn.run(drawn.toy.run_id("portfolio", "weighted_cvar"))
    full = ResultReader(toy.store).run(toy.run_id("portfolio", "weighted_cvar"))
    assert figure_split([holdout]) == "test"
    assert figure_split([full]) == "full"
    assert figure_split([holdout], "train") == "train"
    assert figure_split([]) == "full"


def test_an_in_sample_figure_says_so(drawn: Drawn) -> None:
    series = series_of(drawn, "alpha", "portfolio", "weighted_cvar")
    output = tradeoff(series, eval_split="train")
    try:
        texts = figure_texts(output.figure)
    finally:
        plt.close(output.figure)
    assert f"{parameter_label('alpha')}\n{IN_SAMPLE}" in texts
    assert output.data[SPLIT_TABLE].to_dict("records") == [
        {"eval_split": "train", "note": SPLIT_NOTES["train"]}
    ]
    run = series.points[0][1]
    first = output.data[""].iloc[0]
    assert first["cvar_uncovered"] == store_kpi(run, "cvar_uncovered", "train")


def test_sensitivity_reads_one_split(drawn: Drawn) -> None:
    series = [
        series_of(drawn, "alpha", "portfolio", "weighted_cvar"),
        series_of(drawn, "alpha", "portfolio", "mse"),  # flat: its baseline
    ]
    output = sensitivity("alpha", series, eval_split="train")
    try:
        points = output.data["points"]
    finally:
        plt.close(output.figure)
    for row in points.to_dict("records"):
        run = drawn.run(str(row["run_id"]))
        assert row["kpi_value"] == store_kpi(run, "cvar_uncovered", "train")


def test_full_sample_figures_carry_no_note(toy: Fixture) -> None:
    """A full-sample figure is unchanged: no split note, no split table."""
    reader = ResultReader(toy.store)
    individual = reader.run(toy.run_id("individual", "weighted_cvar"))
    portfolio = reader.run(toy.run_id("portfolio", "weighted_cvar"))
    output = premium_reallocation(individual, portfolio)
    try:
        assert not output.figure.axes[0].get_title()
        assert SPLIT_TABLE not in output.data
    finally:
        plt.close(output.figure)
    assert split_note("full") is None
    assert split_note("test") == "out of sample (test years)"
    assert split_note("train") == "in sample (train years)"


def test_holdout_premium_reallocation_states_the_split(drawn: Drawn) -> None:
    texts = drawn.texts["premium_reallocation"]
    assert OUT_OF_SAMPLE in texts
    table = drawn.csv("premium_reallocation")
    run = drawn.run(str(table["portfolio_run_id"].iloc[0]))
    k = run.kpis
    test = k[
        (k["kpi"] == "expected_payout")
        & (k["level"] == "entity")
        & (k["eval_split"] == "test")
    ].set_index("subject_id")["value"]
    for row in table.to_dict("records"):
        assert row["portfolio_premium"] == pytest.approx(
            float(cast(float, test[row["entity_id"]])), rel=1e-12
        )
