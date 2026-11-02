"""Joint designs in the sweep figures (MAR-222, design review F8).

The payout sweep (``payout_sweep_*``) of an entity of a joint design problem
(portfolio scope, joint cluster scope with more than one cluster) carries
the joint-design caption, as the payout grid does (MAR-218). A cluster
scope calibrated cluster by cluster (``joint: false``) has one entity per
problem, so its payout sweep has no caption, and its net-advantage and
break-even figures, which measure what the joint cluster calibration
gains, are skipped and listed as skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import matplotlib.pyplot as plt
import pandas as pd
import pytest
from matplotlib.figure import Figure

from parametric_insurance_design import cli
from parametric_insurance_design.experiment.runner import load_input
from parametric_insurance_design.experiment.sweeps import run_sweeps
from parametric_insurance_design.solve import DEFAULT_POLICY
from parametric_insurance_design_viz import command, style, sweep_figures
from parametric_insurance_design_viz.command import (
    FigureReport,
    SweepRun,
    write_figures,
)
from parametric_insurance_design_viz.errors import FigureDataError
from parametric_insurance_design_viz.figure_data import MAIN_TABLE
from parametric_insurance_design_viz.payout_functions import (
    CAPTION_COLUMNS,
    JOINT_CAPTION,
    JointEntitiesError,
)
from parametric_insurance_design_viz.reader import ResultReader
from parametric_insurance_design_viz.sweep_figures import (
    SEPARATE_CLUSTER_REASON,
    SweepSeries,
    payout_sweep,
)

from .conftest import build_fixture

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
KEYS = ("individual", "cluster", "cluster_separate", "portfolio")
OBJECTIVES = [{"kind": "mse"}, {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.9}]
SWEEPS = [
    {"parameter": "alpha", "values": [0.5, 0.9]},
    {"parameter": "n_clusters", "values": [1, 2]},
]
CAPTIONED = ("payout_sweep_cluster_c1_alpha", "payout_sweep_portfolio_a1_alpha")
UNCAPTIONED = (
    "payout_sweep_individual_a1_alpha",
    "payout_sweep_cluster_separate_c1_alpha",
)


@dataclass(frozen=True)
class Swept:
    toy: Fixture
    sweeps: tuple[SweepRun, ...]
    report: FigureReport


@pytest.fixture(scope="module")
def swept(tmp_path_factory: pytest.TempPathFactory) -> Swept:
    toy = build_fixture(
        tmp_path_factory.mktemp("joint-sweeps"),
        scopes=SCOPES,
        objectives=OBJECTIVES,
        sweeps=SWEEPS,
    )
    run_sweeps(toy.config, store=toy.store, baseline=False)
    data = load_input(toy.config)
    points = cli._sweep_runs(command, toy.config, data, DEFAULT_POLICY)
    sweeps = tuple(p for p in points if isinstance(p, SweepRun))
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=tmp_path_factory.mktemp("joint-sweep-figures"),
        eventset=toy.eventset,
        sweeps=sweeps,
        figure_sets=(sweep_figures.sweep_figures,),
    )
    return Swept(toy=toy, sweeps=sweeps, report=report)


@pytest.fixture(autouse=True)
def _close_figures() -> object:
    yield
    plt.close("all")


def captions(figure: Figure) -> list[str]:
    """Figure-level texts, unwrapped (the axes' own labels are not among them)."""
    return [" ".join(t.get_text().split()) for t in figure.texts]


def alpha_series(swept: Swept, key: str) -> SweepSeries:
    """The alpha sweep of one scope's weighted-CVaR run, as the builder reads it."""
    position = KEYS.index(key) * len(OBJECTIVES) + 1  # weighted_cvar
    reader = ResultReader(swept.toy.store)
    points = [
        (p, reader.run(p.run_id))
        for p in swept.sweeps
        if p.parameter == "alpha" and p.single == position
    ]
    baseline = reader.run(swept.toy.run_ids[position])
    return SweepSeries("alpha", key, baseline, tuple(points))


def test_joint_payout_sweeps_carry_the_caption_and_its_table(swept: Swept) -> None:
    written = {w.name: w for w in swept.report.written}
    for name in CAPTIONED:
        assert "caption" in written[name].tables, name
        table = pd.read_csv(written[name].tables["caption"])
        assert tuple(table.columns) == CAPTION_COLUMNS
        assert len(table) == 1
        row = table.iloc[0]
        assert row["caption"] == JOINT_CAPTION
        assert row["entity_ids"] == name.split("_")[-2].upper()
    for name in UNCAPTIONED:
        assert set(written[name].tables) == {MAIN_TABLE, "events"}, name


@pytest.mark.parametrize("key", ["cluster", "portfolio"])
def test_the_caption_is_drawn_above_the_title(swept: Swept, key: str) -> None:
    series = alpha_series(swept, key)
    entity = series.baseline.entity_order()[0]
    out = payout_sweep(series, entity)
    assert captions(out.figure) == [JOINT_CAPTION]
    (ax,) = [a for a in out.figure.axes if a.get_title()]
    out.figure.draw_without_rendering()
    (text,) = out.figure.texts
    caption_box = text.get_window_extent()
    title_box = ax.title.get_window_extent()
    assert caption_box.y0 > title_box.y1  # above the title, not over it
    assert out.data["caption"]["problem_id"].tolist() == [
        series.baseline.problem_specs()[0].problem_id
    ]


@pytest.mark.parametrize("key", ["cluster", "portfolio"])
def test_joint_payout_sweeps_can_be_refused(swept: Swept, key: str) -> None:
    series = alpha_series(swept, key)
    entity = series.baseline.entity_order()[0]
    with pytest.raises(JointEntitiesError, match="one of several optimal designs"):
        payout_sweep(series, entity, joint_entities="refuse")


@pytest.mark.parametrize("key", ["individual", "cluster_separate"])
def test_payout_sweeps_of_unique_designs_have_no_caption(
    swept: Swept, key: str
) -> None:
    series = alpha_series(swept, key)
    entity = series.baseline.entity_order()[0]
    plain = payout_sweep(series, entity)
    refused = payout_sweep(series, entity, joint_entities="refuse")
    for out in (plain, refused):
        assert captions(out.figure) == []
        assert "caption" not in out.data
    pd.testing.assert_frame_equal(plain.data[MAIN_TABLE], refused.data[MAIN_TABLE])


def test_an_unknown_mode_is_refused(swept: Swept) -> None:
    series = alpha_series(swept, "individual")
    with pytest.raises(FigureDataError, match="joint_entities must be one of"):
        payout_sweep(series, "A1", joint_entities="hide")  # pyright: ignore[reportArgumentType]


def test_cluster_figures_of_the_separate_cluster_scope_are_skipped(
    swept: Swept,
) -> None:
    written = [w.name for w in swept.report.written]
    assert "net_advantage_cluster" in written
    assert "breakeven_cost_cluster" in written
    names = ("net_advantage_cluster_separate", "breakeven_cost_cluster_separate")
    assert not set(names) & set(written)
    skipped = [s for s in swept.report.skipped if s.name in names]
    assert [s.name for s in skipped] == list(names)
    for s in skipped:
        assert s.reason == SEPARATE_CLUSTER_REASON
        assert not s.failed
        assert not s.missing
    assert swept.report.ok
    # the skip keys on the scope name, not on the kind
    separate = alpha_series(swept, "cluster_separate")
    assert separate.scope_name == style.SEPARATE_CLUSTER_SCOPE
    assert separate.scope_kind == "cluster"
