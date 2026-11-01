"""Per-entity payout panels of joint designs (MAR-218, design review F8).

A joint design (portfolio or cluster scope) is identified only through the
sum over its entities, so its per-entity payout functions are one of several
optimal designs. The payout figures caption them, or refuse them.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd
import pytest

from parametric_insurance_design_viz.command import payout_figures, write_figures
from parametric_insurance_design_viz.errors import FigureDataError, VizError
from parametric_insurance_design_viz.figure_data import FigureOutput, write_figure
from parametric_insurance_design_viz.payout_functions import (
    CAPTION_COLUMNS,
    JOINT_CAPTION,
    JOINT_ENTITIES_MODES,
    JointEntitiesError,
    is_joint_design,
    normalised_payout,
    payout_grid,
)
from parametric_insurance_design_viz.reader import ResultReader, RunResult

if TYPE_CHECKING:
    from conftest import Fixture

OBJECTIVES = ("mse", "expected_uncovered", "weighted_cvar")
JOINT = ("cluster", "portfolio")


def scope_runs(toy: Fixture, scope: str) -> tuple[RunResult, ...]:
    reader = ResultReader(toy.store)
    return reader.runs(toy.run_id(scope, o) for o in OBJECTIVES)


def suptitle(out: FigureOutput) -> str | None:
    """The figure's suptitle text, unwrapped, or None without one."""
    title = out.figure.get_suptitle()  # "" without one (matplotlib >= 3.8)
    return " ".join(title.split()) or None


@pytest.fixture(autouse=True)
def _close_figures() -> object:
    yield
    plt.close("all")


def test_joint_design_is_a_problem_with_several_entities(toy: Fixture) -> None:
    assert not any(is_joint_design(r) for r in scope_runs(toy, "individual"))
    for scope in JOINT:
        assert all(is_joint_design(r) for r in scope_runs(toy, scope))


def test_caption_names_no_tracker_and_reads_the_portfolio_level() -> None:
    # external outputs link no private tracker pages (publication rule)
    assert not re.search(r"MAR-\d+|linear\.app", JOINT_CAPTION)
    assert "one of several optimal designs" in JOINT_CAPTION
    assert "portfolio level" in JOINT_CAPTION
    assert JOINT_ENTITIES_MODES == ("caption", "refuse")


@pytest.mark.parametrize("scope", JOINT)
def test_joint_payout_grid_is_captioned_by_default(toy: Fixture, scope: str) -> None:
    runs = scope_runs(toy, scope)
    out = payout_grid(runs)
    assert suptitle(out) == JOINT_CAPTION
    caption = out.data["caption"]
    assert tuple(caption.columns) == CAPTION_COLUMNS
    assert caption.to_dict("records") == [
        {
            "scope": scope,
            "problem_id": "portfolio",
            "entity_ids": ";".join(runs[0].entity_order()),
            "caption": JOINT_CAPTION,
        }
    ]
    out.figure.canvas.draw()


def test_caption_lists_the_drawn_entities_only(toy: Fixture) -> None:
    out = payout_grid(scope_runs(toy, "portfolio"), entity_ids=["A3", "A1"])
    assert out.data["caption"]["entity_ids"].tolist() == ["A3;A1"]


@pytest.mark.parametrize(("scope", "entity"), [("cluster", "C1"), ("portfolio", "A2")])
def test_joint_normalised_payout_is_captioned_by_default(
    toy: Fixture, scope: str, entity: str
) -> None:
    out = normalised_payout(scope_runs(toy, scope), entity)
    assert suptitle(out) == JOINT_CAPTION
    caption = out.data["caption"]
    assert tuple(caption.columns) == CAPTION_COLUMNS
    assert caption["entity_ids"].tolist() == [entity]
    assert caption["caption"].tolist() == [JOINT_CAPTION]


def test_individual_figures_have_no_caption(toy: Fixture) -> None:
    runs = scope_runs(toy, "individual")
    for mode in JOINT_ENTITIES_MODES:
        for out in (
            payout_grid(runs, joint_entities=mode),
            normalised_payout(runs, "A1", joint_entities=mode),
        ):
            assert suptitle(out) is None
            assert "caption" not in out.data


@pytest.mark.parametrize("scope", JOINT)
def test_refuse_raises_a_typed_error_that_says_how_to_opt_in(
    toy: Fixture, scope: str
) -> None:
    runs = scope_runs(toy, scope)
    entity = runs[0].entity_order()[0]
    with pytest.raises(JointEntitiesError, match="joint_entities='caption'") as info:
        payout_grid(runs, joint_entities="refuse")
    assert isinstance(info.value, VizError)
    assert "one of several optimal designs" in str(info.value)
    with pytest.raises(JointEntitiesError, match=f"scope {scope!r}"):
        normalised_payout(runs, entity, joint_entities="refuse")
    assert not plt.get_fignums()  # refused before drawing


def test_unknown_mode_is_refused(toy: Fixture) -> None:
    runs = scope_runs(toy, "individual")
    with pytest.raises(FigureDataError, match="joint_entities"):
        payout_grid(runs, joint_entities="bare")  # pyright: ignore[reportArgumentType]
    with pytest.raises(FigureDataError, match="joint_entities"):
        normalised_payout(runs, "A1", joint_entities="")  # pyright: ignore[reportArgumentType]


def test_written_joint_figure_keeps_its_caption(toy: Fixture, tmp_path: Path) -> None:
    written = write_figure(payout_grid(scope_runs(toy, "cluster")), tmp_path)
    assert written.image.is_file()
    caption = pd.read_csv(written.tables["caption"])
    assert caption["caption"].tolist() == [JOINT_CAPTION]


def test_figures_command_captions_the_joint_scopes(
    toy: Fixture, tmp_path: Path
) -> None:
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=tmp_path,
        eventset=toy.eventset,
        figure_sets=(payout_figures,),
    )
    assert report.ok
    captioned = {w.name for w in report.written if "caption" in w.tables}
    assert captioned == {
        "payout_grid_cluster",
        "normalised_payout_cluster_c1",
        "payout_grid_portfolio",
        "normalised_payout_portfolio_a1",
    }
