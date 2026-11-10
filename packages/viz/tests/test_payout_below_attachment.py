"""Payout figures of ``below_attachment = "zero"`` runs (MAR-178), Agg backend.

The ``zero`` fixture is the ``toy`` store of ``conftest.py`` with a payout that
pays nothing below the attachment (MAR-170). Since MAR-178 the runner records
the mode in ``runs.parameters``; the payout grid then draws 0 below the
attachment, with a step at ``b_0``, and its figure data have a zero row there.
Runs without the key (the ``toy`` store) are drawn and written as before.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd
import pytest
from matplotlib.lines import Line2D
from numpy.typing import NDArray

from parametric_insurance_design.payout import NO_BIN
from parametric_insurance_design_viz.command import payout_figures, write_figures
from parametric_insurance_design_viz.errors import (
    FigureDataError,
    InconsistentRunsError,
)
from parametric_insurance_design_viz.figure_data import write_figure
from parametric_insurance_design_viz.payout_functions import (
    STEP_COLUMNS,
    below_attachment_mode,
    normalised_payout,
    payout_grid,
    payout_steps,
    step_points,
)
from parametric_insurance_design_viz.reader import ResultReader, RunResult

from .conftest import build_fixture

if TYPE_CHECKING:
    from conftest import Fixture

OBJECTIVES = ("mse", "expected_uncovered", "weighted_cvar")
ATTACHMENT = 20.0
ZERO_PAYOUT = {
    "attachment": ATTACHMENT,
    "limit": 70.0,
    "n_bins": 5,
    "below_attachment": "zero",
}


@pytest.fixture(scope="module")
def zero(tmp_path_factory: pytest.TempPathFactory) -> Fixture:
    """The ``toy`` store with ``below_attachment: zero``."""
    return build_fixture(tmp_path_factory.mktemp("zero"), payout=ZERO_PAYOUT)


def scope_runs(fixture: Fixture, scope: str) -> tuple[RunResult, ...]:
    reader = ResultReader(fixture.store)
    return reader.runs(fixture.run_id(scope, o) for o in OBJECTIVES)


def where(frame: pd.DataFrame, **equal: Any) -> pd.DataFrame:  # noqa: ANN401
    """Rows of ``frame`` whose columns equal the given values."""
    mask = np.ones(len(frame), dtype=bool)
    for column, value in equal.items():
        mask &= frame[column].to_numpy() == value
    return cast(pd.DataFrame, frame.loc[mask])


def column(frame: pd.DataFrame, name: str) -> NDArray[Any]:
    """One column as a numpy array."""
    return frame[name].to_numpy()


def line_xy(line: Line2D) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """The points of a drawn line."""
    x = np.asarray(line.get_xdata(), dtype=np.float64)
    y = np.asarray(line.get_ydata(), dtype=np.float64)
    return x, y


def with_parameters(run: RunResult, **changes: Any) -> RunResult:  # noqa: ANN401
    """The run with ``runs.parameters`` changed (None removes a key)."""
    params = {**run.parameters, **changes}
    params = {k: v for k, v in params.items() if v is not None}
    text = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return dataclasses.replace(run, runs=run.runs.assign(parameters=text))


# -- the mode ------------------------------------------------------------------


def test_mode_is_read_from_the_run_parameters(toy: Fixture, zero: Fixture) -> None:
    reader = ResultReader(zero.store)
    for run in reader.runs(zero.run_ids):
        assert run.parameters["below_attachment"] == "zero"
        assert run.manifest["config"]["payout"]["below_attachment"] == "zero"
        assert below_attachment_mode(run) == "zero"
    for run in ResultReader(toy.store).runs(toy.run_ids):
        assert "below_attachment" not in run.parameters
        assert "below_attachment" not in run.manifest["config"]["payout"]
        assert below_attachment_mode(run) == "first_bin"


def test_a_zero_run_without_the_key_is_refused(zero: Fixture, toy: Fixture) -> None:
    # A "zero" run written before MAR-178: its config says "zero", but its
    # parameters have no key. Its run id is unchanged, so it is a cache hit.
    stale = with_parameters(scope_runs(zero, "individual")[0], below_attachment=None)
    with pytest.raises(InconsistentRunsError, match="written by an older runner"):
        below_attachment_mode(stale)
    with pytest.raises(InconsistentRunsError, match="written by an older runner"):
        payout_grid((stale,))
    # The other way round: parameters say "zero", the config does not.
    wrong = with_parameters(scope_runs(toy, "individual")[0], below_attachment="zero")
    with pytest.raises(InconsistentRunsError, match="'first_bin' below"):
        below_attachment_mode(wrong)
    # An explicit "first_bin" agrees with a config that leaves it out.
    explicit = with_parameters(
        scope_runs(toy, "individual")[0], below_attachment="first_bin"
    )
    assert below_attachment_mode(explicit) == "first_bin"


@pytest.mark.parametrize("bad", ["nothing", "ZERO", 0, ["zero"]])
def test_an_unknown_mode_is_refused(toy: Fixture, bad: object) -> None:
    run = with_parameters(scope_runs(toy, "individual")[0], below_attachment=bad)
    with pytest.raises(FigureDataError, match="not one of"):
        below_attachment_mode(run)


# -- drawing -------------------------------------------------------------------


def test_step_points_in_both_modes() -> None:
    bp = np.array([20.0, 30.0, 40.0])
    levels = np.array([2.0, 5.0])
    x, y = step_points(bp, levels, (10.0, 50.0), "first_bin")
    np.testing.assert_array_equal(x, [10.0, 20.0, 30.0, 40.0, 50.0])
    np.testing.assert_array_equal(y, [2.0, 2.0, 5.0, 5.0, 5.0])
    x, y = step_points(bp, levels, (10.0, 50.0), "zero")
    np.testing.assert_array_equal(x, [10.0, 20.0, 30.0, 40.0, 50.0])
    np.testing.assert_array_equal(y, [0.0, 2.0, 5.0, 5.0, 5.0])
    # An axis that starts above the attachment leaves no room below it.
    x, y = step_points(bp, levels, (25.0, 35.0), "zero")
    np.testing.assert_array_equal(x, [20.0, 20.0, 30.0, 40.0, 40.0])
    np.testing.assert_array_equal(y, [0.0, 2.0, 5.0, 5.0, 5.0])


@pytest.mark.parametrize("scope", ["individual", "cluster", "portfolio"])
def test_zero_run_is_drawn_with_nothing_below_the_attachment(
    zero: Fixture, scope: str
) -> None:
    runs = scope_runs(zero, scope)
    out = payout_grid(runs, shade_objective="mse")
    steps = payout_steps(runs)
    entities = runs[0].entity_order()
    for ax, entity_id in zip(out.figure.axes, entities, strict=True):
        lines = ax.get_lines()[: len(runs)]  # the steps, then the reference lines
        for line, run in zip(lines, runs, strict=True):
            x, y = line_xy(line)
            levels = column(
                where(steps, run_id=run.run_id, entity_id=entity_id), "value"
            )
            assert x[0] == 10.0  # the left edge of the axis
            assert x[1] == ATTACHMENT
            assert y[0] == 0.0
            np.testing.assert_allclose(y[1:-2], levels)
            assert y[-1] == y[-2] == levels[-1]
        # The shaded area is 0 below the attachment too.
        (shade,) = ax.collections
        vertices = np.concatenate([p.vertices for p in shade.get_paths()])
        below = vertices[vertices[:, 0] < ATTACHMENT]
        assert len(below) > 0
        assert np.all(below[:, 1] == 0.0)
    out.figure.canvas.draw()


def test_the_step_at_the_attachment_is_visible(zero: Fixture) -> None:
    # Individual MSE pays a positive first level in every entity of the
    # fixture, so the step at b_0 is a visible jump from 0.
    run = scope_runs(zero, "individual")[0]
    out = payout_grid((run,), shade_objective=None)
    for ax in out.figure.axes:
        _, y = line_xy(ax.get_lines()[0])
        assert y[0] == 0.0
        assert y[1] > 0.1


def test_runs_of_both_modes_in_one_figure(toy: Fixture, zero: Fixture) -> None:
    plain = scope_runs(toy, "individual")[0]  # mse
    zeroed = scope_runs(zero, "individual")[1]  # expected_uncovered
    out = payout_grid((plain, zeroed), shade_objective=None)
    first, second = out.figure.axes[0].get_lines()[:2]
    _, y_plain = line_xy(first)
    _, y_zero = line_xy(second)
    assert y_plain[0] == y_plain[1] > 0.0
    assert y_zero[0] == 0.0
    below = where(out.data[""], param_index=NO_BIN)
    assert set(column(below, "run_id")) == {zeroed.run_id}
    assert len(below) == len(zeroed.entity_order())


def test_normalised_payout_has_no_row_below_the_attachment(zero: Fixture) -> None:
    runs = scope_runs(zero, "individual")
    out = normalised_payout(runs, "A1")
    assert np.all(column(out.data[""], "param_index") >= 0)
    for line in out.figure.axes[0].get_lines()[: len(runs)]:
        x, _ = line_xy(line)
        assert x[0] == ATTACHMENT


# -- figure data ---------------------------------------------------------------


@pytest.mark.parametrize("scope", ["individual", "cluster", "portfolio"])
def test_zero_figure_data_csv_pays_nothing_below_the_attachment(
    zero: Fixture, scope: str, tmp_path: Path
) -> None:
    runs = scope_runs(zero, scope)
    written = write_figure(payout_grid(runs), tmp_path)
    data = pd.read_csv(written.tables[""])
    assert tuple(data.columns) == STEP_COLUMNS
    steps = payout_steps(runs)
    n_rows = len(runs) * len(runs[0].entity_order())
    assert len(data) == len(steps) + n_rows
    below = where(data, param_index=NO_BIN)
    assert len(below) == n_rows
    assert np.all(column(below, "lower") == -np.inf)
    assert np.all(column(below, "upper") == ATTACHMENT)
    assert np.all(column(below, "value") == 0.0)
    # Each zero row comes first in its entity's rows, and the bins follow as
    # payout_steps gives them.
    for _, rows in data.groupby(["run_id", "entity_id"], sort=False):
        assert column(rows, "param_index").tolist() == [NO_BIN, 0, 1, 2, 3, 4]
        assert column(rows, "upper")[0] == column(rows, "lower")[1]
    fitted = data.loc[column(data, "param_index") != NO_BIN].reset_index(drop=True)
    pd.testing.assert_frame_equal(fitted, steps, check_dtype=False)


def test_figures_command_writes_the_zero_rows(zero: Fixture, tmp_path: Path) -> None:
    report = write_figures(
        zero.config,
        zero.run_ids,
        store=zero.store,
        out_dir=tmp_path,
        eventset=zero.eventset,
        figure_sets=(payout_figures,),
    )
    assert report.ok
    for scope in ("individual", "cluster", "portfolio"):
        data = pd.read_csv(tmp_path / f"payout_grid_{scope}.csv")
        below = where(data, param_index=NO_BIN)
        assert len(below) == data.groupby(["run_id", "entity_id"]).ngroups
        assert np.all(column(below, "value") == 0.0)
        lower = column(data, "lower")
        assert np.all(column(data, "value")[lower < ATTACHMENT] == 0.0)


def test_default_figure_data_is_unchanged(toy: Fixture, tmp_path: Path) -> None:
    # Runs without the key: the main table is payout_steps, with no zero row,
    # and each step starts at the first level, as before MAR-178.
    for scope in ("individual", "cluster", "portfolio"):
        runs = scope_runs(toy, scope)
        out = payout_grid(runs, shade_objective=None)
        pd.testing.assert_frame_equal(out.data[""], payout_steps(runs))
        assert np.all(column(out.data[""], "param_index") >= 0)
        for ax in out.figure.axes:
            for line in ax.get_lines()[: len(runs)]:
                _, y = line_xy(line)
                assert y[0] == y[1]
        written = write_figure(out, tmp_path)
        data = pd.read_csv(written.tables[""])
        assert column(data, "lower").min() == ATTACHMENT
