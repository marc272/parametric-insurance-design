"""Smoke and data tests of the payout figures (MAR-110), Agg backend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design_viz import style
from parametric_insurance_design_viz.errors import (
    FigureDataError,
    IncompleteRunError,
    InconsistentRunsError,
)
from parametric_insurance_design_viz.payout_functions import (
    BENCHMARK_ZERO_RTOL,
    MARKER_COLUMNS,
    STEP_COLUMNS,
    AxisLabels,
    _normalised_levels,
    _SciOffsetFormatter,
    normalised_payout,
    payout_grid,
    payout_steps,
    weighted_quantile,
)
from parametric_insurance_design_viz.reader import (
    ResultReader,
    RunResult,
    entity_events,
)

if TYPE_CHECKING:
    from conftest import Fixture


def where(frame: pd.DataFrame, **equal: Any) -> pd.DataFrame:  # noqa: ANN401
    """Rows of ``frame`` whose columns equal the given values."""
    mask = np.ones(len(frame), dtype=bool)
    for column, value in equal.items():
        mask &= frame[column].to_numpy() == value
    return cast(pd.DataFrame, frame.loc[mask])


OBJECTIVES = ("mse", "expected_uncovered", "weighted_cvar")
SCOPES = {"individual": 0, "cluster": 1, "portfolio": 2}


def scope_runs(toy: Fixture, scope: str) -> tuple[RunResult, ...]:
    reader = ResultReader(toy.store)
    return reader.runs(toy.run_id(scope, o) for o in OBJECTIVES)


def scope_events(toy: Fixture, scope: str) -> pd.DataFrame:
    runs = scope_runs(toy, scope)
    component = toy.config.scopes[SCOPES[scope]].build()
    return entity_events(toy.eventset, component, runs[0].problem_specs())


@pytest.fixture(autouse=True)
def _close_figures() -> object:
    yield
    plt.close("all")


def test_payout_steps_table(toy: Fixture) -> None:
    runs = scope_runs(toy, "cluster")
    steps = payout_steps(runs)
    assert tuple(steps.columns) == STEP_COLUMNS
    assert len(steps) == 3 * 2 * 5  # objectives x clusters x bins
    assert set(steps["objective"]) == set(OBJECTIVES)
    first = where(steps, run_id=runs[0].run_id, entity_id="C1")
    assert first["param_index"].tolist() == [0, 1, 2, 3, 4]
    assert first["lower"].iloc[0] == 20.0
    assert first["upper"].iloc[-1] == 70.0
    members = set(first["location_ids"].iloc[0].split(";"))
    assert members <= {"A1", "A2", "A3"}
    assert payout_steps(()).empty


@pytest.mark.parametrize("scope", sorted(SCOPES))
def test_payout_grid_smoke(toy: Fixture, scope: str) -> None:
    runs = scope_runs(toy, scope)
    events = scope_events(toy, scope)
    out = payout_grid(runs, events=events, labels=AxisLabels("m/s", "USD"))
    assert out.name == f"payout_grid_{scope}"
    n_entities = len(runs[0].entity_order())
    axes = [ax for ax in out.figure.axes if ax.get_visible() and ax.axison]
    assert len(axes) == n_entities
    assert set(out.data) == {"", "markers", "events"}
    pd.testing.assert_frame_equal(out.data[""], payout_steps(runs))
    assert tuple(out.data["markers"].columns) == MARKER_COLUMNS
    assert set(out.data["markers"]["marker"]) == {"attachment", "limit"}
    pd.testing.assert_frame_equal(out.data["events"], events)
    texts = [t.get_text() for t in out.figure.legends[0].get_texts()]
    assert texts[0].startswith("Underlying")
    assert texts[1:] == [style.objective_label(o) for o in OBJECTIVES]
    assert "[m/s]" in axes[0].get_xlabel()
    assert "[USD]" in axes[0].get_ylabel()
    out.figure.canvas.draw()


def test_payout_grid_cluster_titles_name_members(toy: Fixture) -> None:
    out = payout_grid(scope_runs(toy, "cluster"))
    titles = [ax.get_title() for ax in out.figure.axes]
    assert all(t.startswith(("C1  [", "C2  [")) for t in titles)
    assert "events" not in out.data  # no event data given


def test_payout_grid_subset_and_layout(toy: Fixture) -> None:
    out = payout_grid(
        scope_runs(toy, "individual"),
        entity_ids=["A3", "A1"],
        ncols=1,
        name="detail",
        xlim=(0.0, 90.0),
    )
    assert out.name == "detail"
    assert [ax.get_title() for ax in out.figure.axes] == ["A3", "A1"]
    assert out.figure.axes[0].get_xlim() == (0.0, 90.0)
    assert set(out.data[""]["entity_id"]) == {"A1", "A3"}


def test_step_curve_extends_to_the_axis_edges(toy: Fixture) -> None:
    runs = scope_runs(toy, "portfolio")
    out = payout_grid(runs[:1], entity_ids=["A1"], shade_objective=None)
    (line,) = out.figure.axes[0].get_lines()[:1]
    x = np.asarray(line.get_xdata(), dtype=float)
    y = np.asarray(line.get_ydata(), dtype=float)
    bins = where(payout_steps(runs[:1]), entity_id="A1")
    assert x[0] == 10.0
    assert x[-1] == 80.0
    np.testing.assert_allclose(y[1:-2], bins["value"])
    assert y[0] == y[1]
    assert y[-1] == y[-2] == bins["value"].iloc[-1]


def test_payout_grid_rejects_inconsistent_runs(toy: Fixture, failed: Fixture) -> None:
    individual = scope_runs(toy, "individual")
    cluster = scope_runs(toy, "cluster")
    with pytest.raises(InconsistentRunsError, match="one scope"):
        payout_grid((individual[0], cluster[0]))
    with pytest.raises(InconsistentRunsError, match="each objective once"):
        payout_grid((individual[0], individual[0]))
    with pytest.raises(InconsistentRunsError, match="at least one run"):
        payout_grid(())
    with pytest.raises(InconsistentRunsError, match="not entities"):
        payout_grid(individual, entity_ids=["Z9"])
    broken = ResultReader(failed.store).run(failed.run_id("cluster", "mse"))
    with pytest.raises(IncompleteRunError):
        payout_grid((broken,))


def test_runs_with_other_entities_are_refused(toy: Fixture) -> None:
    runs = scope_runs(toy, "portfolio")
    other = RunResult(
        run_id=runs[1].run_id,
        runs=runs[1].runs,
        entities=runs[1].entities.assign(entity_id="X"),
        payouts=runs[1].payouts,
        kpis=runs[1].kpis,
        exceedance=runs[1].exceedance,
        manifest=runs[1].manifest,
    )
    with pytest.raises(InconsistentRunsError, match="different entities"):
        payout_grid((runs[0], other))


@pytest.mark.parametrize(("scope", "entity"), [("individual", "A1"), ("cluster", "C1")])
def test_normalised_payout_smoke(toy: Fixture, scope: str, entity: str) -> None:
    runs = scope_runs(toy, scope)
    events = scope_events(toy, scope)
    out = normalised_payout(runs, entity, events=events)
    assert out.name == f"normalised_payout_{scope}_{entity.lower()}"
    main = out.data[""]
    assert set(main["objective"]) == set(OBJECTIVES)
    bench = where(main, objective="mse")
    finite = bench["relative_pct"].dropna()
    np.testing.assert_allclose(finite, 100.0)
    # NaN exactly where the benchmark level is zero to solver precision
    scale = bench["value"].abs().max()
    zero = (bench["value"].abs() <= BENCHMARK_ZERO_RTOL * scale).to_numpy()
    assert bench["relative_pct"].isna().tolist() == zero.tolist()
    other = where(main, objective="weighted_cvar")
    expected = other["value"].to_numpy() / bench["value"].to_numpy() * 100
    np.testing.assert_allclose(
        other["relative_pct"].to_numpy()[~zero],
        expected[~zero],
    )
    density = out.data["density"]
    assert len(density) == 500
    assert np.all(density["density"].to_numpy() >= 0)
    markers = out.data["markers"].set_index("marker")
    assert markers.loc["tail_quantile", "level"] == 0.9  # evaluation.beta
    rows = where(events, entity_id=entity)
    assert markers.loc["tail_quantile", "value"] == weighted_quantile(
        rows["index"].to_numpy(), rows["rate"].to_numpy(), 0.9
    )
    texts = [t.get_text() for t in out.figure.legends[0].get_texts()]
    assert texts == [*(style.objective_label(o) for o in OBJECTIVES), "Event density"]
    out.figure.canvas.draw()


def test_normalised_payout_without_events(toy: Fixture) -> None:
    out = normalised_payout(scope_runs(toy, "portfolio"), "A2", tail_level=0.5)
    assert out.data["density"].empty
    assert set(out.data["markers"]["marker"]) == {"attachment", "limit"}


def test_normalised_payout_needs_benchmark_and_entity(toy: Fixture) -> None:
    runs = scope_runs(toy, "individual")
    with pytest.raises(InconsistentRunsError, match="benchmark objective 'mse'"):
        normalised_payout(runs[1:], "A1")
    with pytest.raises(InconsistentRunsError, match="not an entity"):
        normalised_payout(runs, "C7")


def test_normalised_levels_masks_zero_benchmark() -> None:
    bp = np.array([0.0, 1.0, 2.0, 3.0])
    bench, rel = _normalised_levels(
        bp, np.array([1.0, 2.0, 6.0]), bp, np.array([1e-9, 4.0, 3.0])
    )
    np.testing.assert_array_equal(bench, [1e-9, 4.0, 3.0])
    assert np.isnan(rel[0])
    np.testing.assert_allclose(rel[1:], [50.0, 200.0])
    # coarser benchmark bins: looked up at each bin midpoint
    _, rel = _normalised_levels(
        bp, np.array([2.0, 2.0, 2.0]), np.array([0.0, 1.5, 3.0]), np.array([1.0, 4.0])
    )
    np.testing.assert_allclose(rel, [200.0, 50.0, 50.0])


def test_density_needs_two_distinct_values(toy: Fixture) -> None:
    runs = scope_runs(toy, "portfolio")
    events = scope_events(toy, "portfolio").assign(index=30.0)
    out = normalised_payout(runs, "A1", events=events)
    assert out.data["density"].empty
    assert out.data["markers"].set_index("marker").loc["tail_quantile", "value"] == 30.0


def test_weighted_quantile() -> None:
    v = np.array([3.0, 1.0, 2.0, 4.0])
    w = np.ones(4)
    assert weighted_quantile(v, w, 0.5) == 2.0
    assert weighted_quantile(v, w, 0.51) == 3.0
    assert weighted_quantile(v, w, 1.0) == 4.0
    assert weighted_quantile(v, w, 0.0) == 1.0
    assert weighted_quantile(v, np.array([0.0, 0.0, 0.0, 1.0]), 0.1) == 4.0
    with pytest.raises(FigureDataError):
        weighted_quantile(v, w, 1.5)
    with pytest.raises(FigureDataError):
        weighted_quantile(v, np.zeros(4), 0.5)
    with pytest.raises(FigureDataError):
        weighted_quantile(v[:0], w[:0], 0.5)


def test_scientific_offset_text_is_compact() -> None:
    fig, ax = plt.subplots()
    ax.plot([0.0, 3e7])
    formatter = _SciOffsetFormatter(useMathText=False)
    formatter.set_scientific(True)
    formatter.set_powerlimits((0, 0))
    ax.yaxis.set_major_formatter(formatter)
    fig.canvas.draw()
    assert ax.yaxis.get_offset_text().get_text() == "e+07"


def test_axis_labels() -> None:
    assert AxisLabels().index(aggregate=False) == r"Index $x$"
    assert AxisLabels("m/s").index(aggregate=True) == r"Aggregate index $x^{(c)}$ [m/s]"
    assert AxisLabels(payout_unit="USD").payout() == r"Payout $Y_{P}(x)$ [USD]"
