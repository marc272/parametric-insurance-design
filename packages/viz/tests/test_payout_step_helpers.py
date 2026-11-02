"""The public step helpers of ``payout_functions`` (MAR-193).

The payout grid and the payout sweep share one implementation of the step
points, the breakpoints, the zero rows below the attachment and the shared
attachment and limit. Since MAR-193 these helpers are public, and no viz
module imports a private name from another module.
"""

from __future__ import annotations

import ast
import dataclasses
import json
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

import parametric_insurance_design_viz
from parametric_insurance_design.payout import NO_BIN
from parametric_insurance_design_viz import payout_functions, sweep_figures
from parametric_insurance_design_viz.errors import (
    FigureDataError,
    InconsistentRunsError,
)
from parametric_insurance_design_viz.payout_functions import (
    bin_breakpoints,
    shared_attachment_limit,
    step_points,
    with_zero_rows,
)
from parametric_insurance_design_viz.reader import ResultReader, RunResult

if TYPE_CHECKING:
    from conftest import Fixture

SRC = Path(parametric_insurance_design_viz.__file__).parent
HELPERS = (
    "bin_breakpoints",
    "shared_attachment_limit",
    "step_points",
    "with_zero_rows",
)


def bins_table(run_id: str, entity_id: str, breakpoints: list[float]) -> pd.DataFrame:
    """Contiguous bins of one run's entity, levels 1, 2, ..."""
    n = len(breakpoints) - 1
    return pd.DataFrame(
        {
            "run_id": run_id,
            "entity_id": entity_id,
            "param_index": np.arange(n),
            "lower": breakpoints[:-1],
            "upper": breakpoints[1:],
            "value": np.arange(1.0, n + 1.0),
        }
    )


def with_parameters(run: RunResult, **changes: object) -> RunResult:
    """The run with ``runs.parameters`` changed."""
    params = {**run.parameters, **changes}
    text = json.dumps(params, sort_keys=True, separators=(",", ":"))
    return dataclasses.replace(run, runs=run.runs.assign(parameters=text))


# -- public API ----------------------------------------------------------------


@pytest.mark.parametrize("name", HELPERS)
def test_helpers_are_public_and_shared_with_the_sweep(name: str) -> None:
    assert name in payout_functions.__all__
    assert getattr(sweep_figures, name) is getattr(payout_functions, name)


def test_no_viz_module_imports_a_private_name() -> None:
    offenders: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if not node.module.startswith("parametric_insurance_design"):
                continue
            offenders += [
                f"{path.name}: {node.module}.{alias.name}"
                for alias in node.names
                if alias.name.startswith("_") and not alias.name.startswith("__")
            ]
        if "reportPrivateUsage" in path.read_text(encoding="utf-8"):
            offenders.append(f"{path.name}: a reportPrivateUsage ignore")
    assert offenders == []


# -- bin_breakpoints -----------------------------------------------------------


def test_breakpoints_are_the_lower_bounds_and_the_last_upper() -> None:
    bins = bins_table("r", "A1", [20.0, 30.0, 45.0, 70.0])
    np.testing.assert_array_equal(bin_breakpoints(bins), [20.0, 30.0, 45.0, 70.0])
    assert bin_breakpoints(bins).dtype == np.float64


def test_breakpoints_of_no_bins_are_refused() -> None:
    with pytest.raises(FigureDataError, match="at least one bin"):
        bin_breakpoints(bins_table("r", "A1", [20.0, 30.0]).iloc[:0])


# -- step_points ---------------------------------------------------------------


def test_step_points_extend_to_breakpoints_outside_the_axis() -> None:
    x, y = step_points(
        np.array([20.0, 30.0]), np.array([4.0]), (25.0, 28.0), "first_bin"
    )
    np.testing.assert_array_equal(x, [20.0, 20.0, 30.0, 30.0])
    np.testing.assert_array_equal(y, [4.0, 4.0, 4.0, 4.0])


@pytest.mark.parametrize(
    ("breakpoints", "levels"),
    [([20.0, 30.0], []), ([20.0, 30.0], [1.0, 2.0]), ([20.0], [1.0])],
)
def test_step_points_refuse_mismatched_lengths(
    breakpoints: list[float], levels: list[float]
) -> None:
    with pytest.raises(FigureDataError, match="do not bound"):
        step_points(np.array(breakpoints), np.array(levels), (0.0, 1.0), "zero")


# -- with_zero_rows ------------------------------------------------------------


def test_first_bin_steps_are_returned_unchanged() -> None:
    steps = bins_table("r", "A1", [20.0, 30.0, 40.0])
    assert with_zero_rows(steps, {"r": "first_bin"}) is steps


def test_zero_runs_get_one_zero_row_per_entity() -> None:
    steps = pd.concat(
        [
            bins_table("z", "A1", [20.0, 30.0, 40.0]),
            bins_table("z", "A2", [25.0, 35.0]),
            bins_table("f", "A1", [20.0, 30.0, 40.0]),
        ],
        ignore_index=True,
    )
    out = with_zero_rows(steps, {"z": "zero", "f": "first_bin"})
    assert len(out) == len(steps) + 2
    assert list(out.index) == list(range(len(out)))
    is_zero = out["param_index"].to_numpy() == NO_BIN
    # Each zero row comes right before its entity's bins; the rest keeps order.
    assert list(np.flatnonzero(is_zero)) == [0, 3]
    zero = out.iloc[np.flatnonzero(is_zero)]
    assert list(zero["run_id"]) == ["z", "z"]
    assert list(zero["entity_id"]) == ["A1", "A2"]
    assert np.all(np.isneginf(zero["lower"].to_numpy(dtype=np.float64)))
    np.testing.assert_array_equal(zero["upper"].to_numpy(), [20.0, 25.0])
    np.testing.assert_array_equal(zero["value"].to_numpy(), [0.0, 0.0])
    rest = out.iloc[np.flatnonzero(~is_zero)].reset_index(drop=True)
    pd.testing.assert_frame_equal(rest, steps, check_dtype=False)


def test_a_run_without_a_mode_is_refused() -> None:
    steps = bins_table("r", "A1", [20.0, 30.0, 40.0])
    with pytest.raises(FigureDataError, match=r"no below_attachment mode.*'r'"):
        with_zero_rows(steps, {"other": "zero"})


# -- shared_attachment_limit ---------------------------------------------------


def test_the_shared_attachment_and_limit(toy: Fixture) -> None:
    runs = ResultReader(toy.store).runs(toy.run_ids)
    attachment, limit = shared_attachment_limit(runs)
    assert (attachment, limit) == (
        float(runs[0].parameters["attachment"]),
        float(runs[0].parameters["limit"]),
    )


def test_runs_with_another_limit_or_no_runs_are_refused(toy: Fixture) -> None:
    runs = ResultReader(toy.store).runs(toy.run_ids[:2])
    other = with_parameters(runs[1], limit=float(runs[1].parameters["limit"]) + 1.0)
    with pytest.raises(InconsistentRunsError, match="share attachment and limit"):
        shared_attachment_limit((runs[0], other))
    with pytest.raises(InconsistentRunsError, match="share attachment and limit"):
        shared_attachment_limit(())
