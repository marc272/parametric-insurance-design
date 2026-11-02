"""The payout sweep (Fig. 5.8) of ``below_attachment = "zero"`` runs (MAR-192).

Two small sweep stores of the viz ``toy`` experiment, computed at test time:
``zero_swept`` pays nothing below the attachment (MAR-170, recorded in
``runs.parameters`` since MAR-178), ``default_swept`` is the default
(``"first_bin"``). :func:`~parametric_insurance_design_viz.sweep_figures.payout_sweep`
draws each run in its own mode, as the payout grid does, and its figure data
have the grid's zero row for a ``"zero"`` run. A default sweep is drawn and
tabulated exactly as before MAR-192: :func:`reference_table` and
:func:`reference_xy` are that code (``f51e395``), frozen here.
"""

from __future__ import annotations

import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest
from matplotlib.lines import Line2D
from numpy.typing import NDArray

from parametric_insurance_design.experiment.sweeps import run_sweeps
from parametric_insurance_design.payout import NO_BIN
from parametric_insurance_design_viz import sweep_figures
from parametric_insurance_design_viz.command import (
    FigureReport,
    SweepRun,
    write_figures,
)
from parametric_insurance_design_viz.errors import (
    FigureDataError,
    InconsistentRunsError,
)
from parametric_insurance_design_viz.figure_data import FigureOutput, write_figure
from parametric_insurance_design_viz.payout_functions import (
    below_attachment_mode,
    payout_steps,
)
from parametric_insurance_design_viz.reader import ResultReader, RunResult
from parametric_insurance_design_viz.sweep_figures import (
    SWEEP_STEP_COLUMNS,
    SweepSeries,
    payout_sweep,
)

from .conftest import build_fixture, command_sweep_runs

if TYPE_CHECKING:
    from conftest import Fixture

ATTACHMENT = 20.0
LIMIT = 70.0
XLIM = (10.0, 80.0)  # 20 % of the payout range on either side
ZERO_PAYOUT = {
    "attachment": ATTACHMENT,
    "limit": LIMIT,
    "n_bins": 5,
    "below_attachment": "zero",
}
SWEEPS = [
    {"parameter": "alpha", "values": [0.5, 0.9]},
    {"parameter": "n_bins", "values": [3, 5]},
]
SCOPES = ("individual", "cluster", "portfolio")
PARAMETERS = ("alpha", "n_bins")
FIGURES = [
    f"payout_sweep_{scope}_{entity}_{parameter}"
    for parameter in PARAMETERS
    for scope, entity in zip(SCOPES, ("a1", "c1", "a1"), strict=True)
]


@dataclass(frozen=True)
class Swept:
    toy: Fixture
    sweeps: tuple[SweepRun, ...]
    out: Path
    report: FigureReport

    def csv(self, name: str) -> pd.DataFrame:
        return pd.read_csv(self.out / f"{name}.csv")

    def series(self, scope: str, parameter: str) -> tuple[SweepSeries, RunResult]:
        """The scope's weighted-CVaR series of a sweep, and its MSE baseline."""
        reader = ResultReader(self.toy.store)
        run_id = self.toy.run_id(scope, "weighted_cvar")
        single = self.toy.run_ids.index(run_id)
        points = tuple(
            p for p in self.sweeps if p.parameter == parameter and p.single == single
        )
        runs = reader.runs(p.run_id for p in points)
        series = SweepSeries(
            parameter=parameter,
            scope=scope,
            baseline=reader.run(run_id),
            points=tuple(zip(points, runs, strict=True)),
        )
        return series, reader.run(self.toy.run_id(scope, "mse"))


def build_swept(directory: Path, out: Path, **changes: Any) -> Swept:  # noqa: ANN401
    toy = build_fixture(directory, sweeps=SWEEPS, **changes)
    run_sweeps(toy.config, store=toy.store, baseline=False)
    sweeps = command_sweep_runs(toy.config)
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=out,
        eventset=toy.eventset,
        sweeps=sweeps,
        figure_sets=(sweep_figures.sweep_figures,),
    )
    return Swept(toy=toy, sweeps=sweeps, out=out, report=report)


@pytest.fixture(scope="module")
def zero_swept(tmp_path_factory: pytest.TempPathFactory) -> Swept:
    """Sweeps of the ``toy`` experiment with ``below_attachment: zero``."""
    return build_swept(
        tmp_path_factory.mktemp("zero_swept"),
        tmp_path_factory.mktemp("zero_swept_figures"),
        payout=ZERO_PAYOUT,
    )


@pytest.fixture(scope="module")
def default_swept(tmp_path_factory: pytest.TempPathFactory) -> Swept:
    """The same sweeps with the default payout (``"first_bin"``)."""
    return build_swept(
        tmp_path_factory.mktemp("default_swept"),
        tmp_path_factory.mktemp("default_swept_figures"),
    )


@pytest.fixture(autouse=True)
def _close_figures() -> object:
    yield
    plt.close("all")


# -- helpers -------------------------------------------------------------------


def where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    """Rows of a frame where a boolean mask holds (typed for pyright)."""
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


def column(frame: pd.DataFrame, name: str) -> NDArray[Any]:
    """One column as a numpy array."""
    return frame[name].to_numpy()


def with_parameters(run: RunResult, **changes: Any) -> RunResult:  # noqa: ANN401
    """The run with ``runs.parameters`` changed (None removes a key)."""
    params = {**run.parameters, **changes}
    params = {k: v for k, v in params.items() if v is not None}
    text = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return dataclasses.replace(run, runs=run.runs.assign(parameters=text))


def step_lines(out: FigureOutput, n: int) -> list[Line2D]:
    """The ``n`` drawn steps: the baseline, then the points by value.

    The attachment and limit lines are drawn after them.
    """
    return out.figure.axes[0].get_lines()[:n]


def line_xy(line: Line2D) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    x = np.asarray(line.get_xdata(), dtype=np.float64)
    y = np.asarray(line.get_ydata(), dtype=np.float64)
    return x, y


def drawn_runs(series: SweepSeries, benchmark: RunResult) -> list[RunResult]:
    """The runs of the figure in drawing order: the baseline, then the points."""
    return [benchmark] + [r for _, r in series.sorted_points() if r.complete]


def reference_table(
    series: SweepSeries, entity_id: str, benchmark: RunResult
) -> pd.DataFrame:
    """The main table as ``payout_sweep`` built it before MAR-192 (``f51e395``)."""
    ok = [(p, r) for p, r in series.sorted_points() if r.complete]
    drawn = [r for _, r in ok] + [benchmark]
    steps = payout_steps(drawn)
    steps = where(steps, steps["entity_id"] == entity_id).reset_index(drop=True)
    value_of = {r.run_id: p.value for p, r in ok}
    return steps.assign(
        role=[
            "baseline" if rid == benchmark.run_id else "sweep"
            for rid in steps["run_id"]
        ],
        parameter=series.parameter,
        parameter_value=[value_of.get(rid) for rid in steps["run_id"]],
    ).loc[:, list(SWEEP_STEP_COLUMNS)]


def reference_xy(
    bins: pd.DataFrame,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The step points ``payout_sweep`` drew before MAR-192 (``f51e395``)."""
    lower = bins["lower"].to_numpy(dtype=np.float64)
    bp = np.append(lower, float(bins["upper"].iloc[-1]))
    levels = bins["value"].to_numpy(dtype=np.float64)
    x = np.concatenate([[min(XLIM[0], bp[0])], bp, [max(XLIM[1], bp[-1])]])
    y = np.concatenate([[levels[0]], levels, [levels[-1], levels[-1]]])
    return x, y


# -- the figure set ------------------------------------------------------------


def test_the_stores_record_their_modes(zero_swept: Swept, default_swept: Swept) -> None:
    for swept, mode in ((zero_swept, "zero"), (default_swept, "first_bin")):
        reader = ResultReader(swept.toy.store)
        run_ids = dict.fromkeys([*swept.toy.run_ids, *(p.run_id for p in swept.sweeps)])
        for run in reader.runs(run_ids):
            assert below_attachment_mode(run) == mode
        written = [w.name for w in swept.report.written]
        assert [n for n in written if n.startswith("payout_sweep")] == FIGURES
        assert swept.report.ok


# -- "zero": nothing below the attachment ---------------------------------------


@pytest.mark.parametrize("name", FIGURES)
def test_zero_sweep_figure_data_pays_nothing_below_the_attachment(
    zero_swept: Swept, name: str
) -> None:
    # The CSV the figures command wrote: one zero row before the bins of
    # every drawn run (the MSE baseline and each sweep point).
    data = zero_swept.csv(name)
    assert tuple(data.columns) == SWEEP_STEP_COLUMNS
    n_runs = len(set(column(data, "run_id")))
    assert n_runs == 3  # the baseline and two points
    below = where(data, data["param_index"] == NO_BIN)
    assert len(below) == n_runs
    assert np.all(column(below, "lower") == -np.inf)
    assert np.all(column(below, "upper") == ATTACHMENT)
    assert np.all(column(below, "value") == 0.0)
    # Only the zero rows reach below the attachment.
    assert np.all(column(data, "value")[column(data, "lower") < ATTACHMENT] == 0.0)
    labels = ["role", "parameter", "parameter_value", *SWEEP_STEP_COLUMNS[3:9]]
    for _, rows in data.groupby("run_id", sort=False):
        n_bins = len(rows) - 1
        assert column(rows, "param_index").tolist() == [NO_BIN, *range(n_bins)]
        assert column(rows, "upper")[0] == column(rows, "lower")[1] == ATTACHMENT
        # The zero row carries its run's labels.
        first = rows.iloc[[0]].loc[:, labels].reset_index(drop=True)
        second = rows.iloc[[1]].loc[:, labels].reset_index(drop=True)
        pd.testing.assert_frame_equal(first, second)
    roles = where(below, below["role"] == "baseline")
    assert len(roles) == 1
    assert bool(pd.isna(roles["parameter_value"]).all())


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("parameter", PARAMETERS)
def test_zero_sweep_is_drawn_with_nothing_below_the_attachment(
    zero_swept: Swept, scope: str, parameter: str
) -> None:
    series, benchmark = zero_swept.series(scope, parameter)
    entity_id = series.baseline.entity_order()[0]
    out = payout_sweep(series, entity_id, benchmark=benchmark)
    table = out.data[""]
    # The bins are tabulated as before; the zero rows come on top.
    fitted = where(table, table["param_index"] != NO_BIN).reset_index(drop=True)
    pd.testing.assert_frame_equal(fitted, reference_table(series, entity_id, benchmark))
    runs = drawn_runs(series, benchmark)
    jumps = []
    for line, run in zip(step_lines(out, len(runs)), runs, strict=True):
        mine = (table["run_id"] == run.run_id) & (table["param_index"] >= 0)
        bins = where(table, mine)
        x, y = line_xy(line)
        x_before, y_before = reference_xy(bins)
        np.testing.assert_array_equal(x, x_before)
        assert x[0] == XLIM[0]
        assert x[1] == ATTACHMENT
        assert y[0] == 0.0  # 0 from the edge of the axis to b_0
        np.testing.assert_array_equal(y[1:], y_before[1:])
        jumps.append(y[1] - y[0])
    # The step at b_0 is a visible jump for the MSE baseline at least.
    assert jumps[0] > 0.1
    out.figure.canvas.draw()


def test_runs_of_both_modes_in_one_sweep(
    zero_swept: Swept, default_swept: Swept
) -> None:
    # Each run is drawn in its own mode: a default baseline under zero points.
    series, _ = zero_swept.series("individual", "alpha")
    _, benchmark = default_swept.series("individual", "alpha")
    out = payout_sweep(series, "A1", benchmark=benchmark)
    first, *points = step_lines(out, 3)
    _, y = line_xy(first)
    assert y[0] == y[1] > 0.0
    for line in points:
        _, y = line_xy(line)
        assert y[0] == 0.0
    table = out.data[""]
    below = where(table, table["param_index"] == NO_BIN)
    assert set(column(below, "run_id")) == {r.run_id for _, r in series.points}
    assert set(column(below, "role")) == {"sweep"}


# -- stale and unknown modes are refused ---------------------------------------


def test_a_stale_zero_run_is_refused(zero_swept: Swept) -> None:
    # A "zero" run written before MAR-178: its config says "zero", but its
    # parameters have no key (below_attachment_mode refuses it).
    series, benchmark = zero_swept.series("individual", "alpha")
    (point, run), *rest = series.points
    stale = with_parameters(run, below_attachment=None)
    with pytest.raises(InconsistentRunsError, match="before MAR-178"):
        below_attachment_mode(stale)
    stale_series = dataclasses.replace(series, points=((point, stale), *rest))
    with pytest.raises(InconsistentRunsError, match="before MAR-178"):
        payout_sweep(stale_series, "A1", benchmark=benchmark)
    # A stale baseline is refused too.
    stale_benchmark = with_parameters(benchmark, below_attachment=None)
    with pytest.raises(InconsistentRunsError, match="before MAR-178"):
        payout_sweep(series, "A1", benchmark=stale_benchmark)


def test_a_failed_stale_point_is_not_read(zero_swept: Swept) -> None:
    # Failed points are not drawn, so their mode is not read either.
    series, benchmark = zero_swept.series("individual", "alpha")
    (point, run), *rest = series.points
    stale = with_parameters(run, below_attachment=None)
    failed = dataclasses.replace(stale, runs=stale.runs.assign(error_type="Failed"))
    assert not failed.complete
    out = payout_sweep(
        dataclasses.replace(series, points=((point, failed), *rest)),
        "A1",
        benchmark=benchmark,
    )
    assert run.run_id not in set(out.data[""]["run_id"])


@pytest.mark.parametrize("bad", ["nothing", "ZERO", 0])
def test_an_unknown_mode_is_refused(default_swept: Swept, bad: object) -> None:
    series, benchmark = default_swept.series("individual", "alpha")
    (point, run), *rest = series.points
    unknown = with_parameters(run, below_attachment=bad)
    with pytest.raises(FigureDataError, match="not one of"):
        payout_sweep(
            dataclasses.replace(series, points=((point, unknown), *rest)),
            "A1",
            benchmark=benchmark,
        )


# -- "first_bin": unchanged ------------------------------------------------------


@pytest.mark.parametrize("scope", SCOPES)
@pytest.mark.parametrize("parameter", PARAMETERS)
def test_default_sweep_is_unchanged(
    default_swept: Swept, scope: str, parameter: str, tmp_path: Path
) -> None:
    # Runs without the key: the table and the drawn steps are exactly those
    # of the code before MAR-192, with no zero row.
    series, benchmark = default_swept.series(scope, parameter)
    entity_id = series.baseline.entity_order()[0]
    out = payout_sweep(series, entity_id, benchmark=benchmark)
    table = out.data[""]
    pd.testing.assert_frame_equal(table, reference_table(series, entity_id, benchmark))
    assert np.all(column(table, "param_index") >= 0)
    runs = drawn_runs(series, benchmark)
    for line, run in zip(step_lines(out, len(runs)), runs, strict=True):
        x, y = line_xy(line)
        x_before, y_before = reference_xy(where(table, table["run_id"] == run.run_id))
        np.testing.assert_array_equal(x, x_before)
        np.testing.assert_array_equal(y, y_before)
        assert y[0] == y[1]  # the first level reaches the edge of the axis
    written = write_figure(out, tmp_path)
    data = pd.read_csv(written.tables[""])
    assert column(data, "lower").min() == ATTACHMENT


def test_default_figures_command_has_no_zero_row(default_swept: Swept) -> None:
    for name in FIGURES:
        data = default_swept.csv(name)
        assert tuple(data.columns) == SWEEP_STEP_COLUMNS
        assert column(data, "param_index").min() == 0
        assert column(data, "lower").min() == ATTACHMENT
