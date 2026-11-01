"""Tests of the sweep figures (MAR-112): their figure data on a small sweep store.

The fixture store is the viz ``toy`` experiment (three locations, 60 events)
with small sweeps, computed at test time by the core runner and sweeps. The
sweep points are passed to the figures as the ``figures`` command passes
them (``cli._sweep_runs``). The tests check the figure-data CSVs against the
store's own tables.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import numpy as np
import pandas as pd
import pytest
from matplotlib.figure import Figure

from parametric_insurance_design import cli
from parametric_insurance_design.experiment.runner import load_input
from parametric_insurance_design.experiment.sweeps import run_sweeps
from parametric_insurance_design.solve import DEFAULT_POLICY
from parametric_insurance_design_viz import command, sweep_figures
from parametric_insurance_design_viz.command import (
    FigureReport,
    SkippedFigure,
    SweepRun,
    write_figures,
)
from parametric_insurance_design_viz.errors import (
    InconsistentRunsError,
    MissingRunError,
    VizError,
)
from parametric_insurance_design_viz.reader import ResultReader, RunResult
from parametric_insurance_design_viz.sweep_figures import (
    THESIS_TRANSACTION_COSTS,
    MissingKpiError,
    SweepSeries,
    kpi_value,
    parameter_label,
    parameter_symbol,
    premium_reallocation,
    sensitivity,
    tradeoff,
)

from .conftest import build_fixture

if TYPE_CHECKING:
    from conftest import Fixture

SWEEPS = [
    {"parameter": "alpha", "values": [0.5, 0.9]},
    {"parameter": "n_clusters", "values": [1, 2, 3]},
    {"parameter": "n_assets", "values": [1, 3]},
]

EXPECTED = [
    "premium_reallocation",
    "payout_sweep_individual_a1_alpha",
    "payout_sweep_cluster_c1_alpha",
    "payout_sweep_portfolio_a1_alpha",
    "sensitivity_alpha",
    "tradeoff_portfolio_alpha",
    "sensitivity_n_clusters",
    "net_advantage_cluster",
    "breakeven_cost_cluster",
    "sensitivity_n_assets",
]


@dataclass(frozen=True)
class SweepFixture:
    toy: Fixture
    sweeps: tuple[SweepRun, ...]
    out: Path
    report: FigureReport

    def csv(self, name: str) -> pd.DataFrame:
        return pd.read_csv(self.out / f"{name}.csv")

    def points(self, parameter: str) -> list[SweepRun]:
        return [p for p in self.sweeps if p.parameter == parameter]


def sweep_runs(toy: Fixture) -> tuple[SweepRun, ...]:
    """The sweep points as the ``figures`` command computes them."""
    data = load_input(toy.config)
    runs = cli._sweep_runs(command, toy.config, data, DEFAULT_POLICY)
    assert all(isinstance(r, SweepRun) for r in runs)
    return tuple(r for r in runs if isinstance(r, SweepRun))


@pytest.fixture(scope="module")
def swept(tmp_path_factory: pytest.TempPathFactory) -> SweepFixture:
    toy = build_fixture(tmp_path_factory.mktemp("swept"), sweeps=SWEEPS)
    outcome = run_sweeps(toy.config, store=toy.store, baseline=False)
    assert [s.parameter for s in outcome.sweeps] == ["alpha", "n_clusters", "n_assets"]
    sweeps = sweep_runs(toy)
    out = tmp_path_factory.mktemp("swept_figures")
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=out,
        eventset=toy.eventset,
        sweeps=sweeps,
        figure_sets=(sweep_figures.sweep_figures,),
    )
    return SweepFixture(toy=toy, sweeps=sweeps, out=out, report=report)


def where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    """Rows of a frame where a boolean mask holds (typed for pyright)."""
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


def all_na(column: object) -> bool:
    return bool(pd.isna(np.asarray(column, dtype=float)).all())


def baseline_kpi(fx: SweepFixture, scope: str, objective: str, kpi: str) -> float:
    run = ResultReader(fx.toy.store).run(fx.toy.run_id(scope, objective))
    return kpi_value(run, kpi)


# -- the figure set ------------------------------------------------------------


def test_sweep_runs_follow_the_config(swept: SweepFixture) -> None:
    singles = swept.toy.config.single_runs()
    alpha = swept.points("alpha")
    # alpha applies to weighted_cvar only: one run per scope and value
    assert [(p.value, p.single) for p in alpha] == [
        (0.5, 2),
        (0.5, 5),
        (0.5, 8),
        (0.9, 2),
        (0.9, 5),
        (0.9, 8),
    ]
    assert {singles[p.single].objectives[0].kind for p in alpha} == {"weighted_cvar"}
    # alpha = 0.9 is the baseline: the same run as the single run
    assert {p.run_id for p in alpha if p.value == 0.9} == {
        swept.toy.run_id(s, "weighted_cvar")
        for s in ("individual", "cluster", "portfolio")
    }
    n_assets = swept.points("n_assets")
    assert len(n_assets) == (3 + 1) * 9
    assert {p.location_ids for p in n_assets if p.value == 3} == {("A1", "A2", "A3")}
    assert {p.subset_index for p in n_assets if p.value == 1} == {0, 1, 2}


def test_writes_the_sweep_figures(swept: SweepFixture) -> None:
    assert [w.name for w in swept.report.written] == EXPECTED
    for written in swept.report.written:
        assert written.image.is_file()
        for path in written.tables.values():
            assert path.is_file()


def test_failed_points_are_reported_not_dropped(swept: SweepFixture) -> None:
    # one location cannot form two clusters: those n_assets points fail
    assert [(s.name, s.failed) for s in swept.report.skipped] == [
        ("sensitivity_n_assets", True)
    ]
    reason = swept.report.skipped[0].reason
    # 4 subsets x the 5 drawn lines; the excluded cluster lines are not counted
    assert "drawn without 3 of 20 sweep points" in reason
    assert not swept.report.ok
    points = swept.csv("sensitivity_n_assets.points")
    failed = where(points, ~points["ok"].astype(bool))
    assert len(failed) == 3
    assert set(failed["scope"]) == {"cluster"}
    assert set(failed["parameter_value"]) == {1}
    assert all_na(failed["kpi_value"])
    line = swept.csv("sensitivity_n_assets")
    cluster = where(line, (line["scope"] == "cluster") & (line["parameter_value"] == 1))
    assert cluster["n_runs"].tolist() == [3]
    assert cluster["n_failed"].tolist() == [3]
    assert all_na(cluster["kpi_value"])


def test_without_sweeps_only_the_reallocation(toy: Fixture, tmp_path: Path) -> None:
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=tmp_path,
        eventset=toy.eventset,
        figure_sets=(sweep_figures.sweep_figures,),
    )
    assert [w.name for w in report.written] == ["premium_reallocation"]
    assert report.ok


def test_reallocation_needs_both_scopes(failed: Fixture, tmp_path: Path) -> None:
    report = write_figures(
        failed.config,
        failed.run_ids,
        store=failed.store,
        out_dir=tmp_path,
        figure_sets=(sweep_figures.sweep_figures,),
    )
    assert report.written == ()
    (skipped,) = report.skipped
    assert (skipped.name, skipped.failed) == ("premium_reallocation", False)
    assert report.ok


def test_missing_sweep_points_are_an_error(swept: SweepFixture, tmp_path: Path) -> None:
    gone = SweepRun("alpha", 0.3, "sha256:" + "e" * 64, single=2)
    with pytest.raises(MissingRunError, match=r"1 of \d+ sweep points .*alpha 1/7"):
        write_figures(
            swept.toy.config,
            swept.toy.run_ids,
            store=swept.toy.store,
            out_dir=tmp_path,
            sweeps=(*swept.points("alpha"), gone),
        )
    bad = SweepRun("alpha", 0.5, swept.points("alpha")[0].run_id, single=99)
    with pytest.raises(InconsistentRunsError, match="single runs"):
        write_figures(
            swept.toy.config,
            swept.toy.run_ids,
            store=swept.toy.store,
            out_dir=tmp_path,
            sweeps=(bad,),
        )
    assert not list(tmp_path.iterdir())  # nothing drawn before the checks


# -- figure data ---------------------------------------------------------------


def test_premium_reallocation_data(swept: SweepFixture) -> None:
    data = swept.csv("premium_reallocation")
    # sorted by insured value: A1 100, A2 60, A3 30
    assert data["entity_id"].tolist() == ["A1", "A2", "A3"]
    assert data["location_value"].tolist() == [100.0, 60.0, 30.0]
    reader = ResultReader(swept.toy.store)
    ind = reader.run(swept.toy.run_id("individual", "weighted_cvar"))
    pf = reader.run(swept.toy.run_id("portfolio", "weighted_cvar"))
    assert set(data["individual_run_id"]) == {ind.run_id}
    assert set(data["portfolio_run_id"]) == {pf.run_id}
    for run, column in ((ind, "individual"), (pf, "portfolio")):
        premiums = [
            kpi_value(run, "expected_payout", level="entity", subject_id=e)
            for e in ("A1", "A2", "A3")
        ]
        np.testing.assert_allclose(data[f"{column}_premium"], premiums)
        np.testing.assert_allclose(
            data[f"{column}_share"], np.array(premiums) / sum(premiums)
        )
    np.testing.assert_allclose(data["individual_share"].sum(), 1.0)
    np.testing.assert_allclose(
        data["reallocation_pp"],
        (data["portfolio_share"] - data["individual_share"]) * 100,
    )


def test_payout_sweep_data(swept: SweepFixture) -> None:
    data = swept.csv("payout_sweep_individual_a1_alpha")
    assert set(data["entity_id"]) == {"A1"}
    baseline = where(data, data["role"] == "baseline")
    assert set(baseline["run_id"]) == {swept.toy.run_id("individual", "mse")}
    assert all_na(baseline["parameter_value"])
    sweep = where(data, data["role"] == "sweep")
    by_value = {
        p.value: p.run_id for p in swept.points("alpha") if p.single == 2
    }  # individual x weighted_cvar
    assert dict(sweep.groupby("parameter_value")["run_id"].first()) == by_value
    reader = ResultReader(swept.toy.store)
    for value, run_id in by_value.items():
        stored = reader.run(run_id).payouts
        stored = where(stored, stored["entity_id"] == "A1").sort_values("param_index")
        drawn = where(sweep, sweep["parameter_value"] == value)
        drawn = drawn.sort_values("param_index")
        np.testing.assert_allclose(drawn["value"], stored["value"])
        np.testing.assert_allclose(drawn["lower"], stored["lower"])
    events = swept.csv("payout_sweep_individual_a1_alpha.events")
    assert set(events["entity_id"]) == {"A1"}
    cluster = swept.csv("payout_sweep_cluster_c1_alpha")
    assert set(cluster["entity_id"]) == {"C1"}
    assert cluster["location_ids"].str.contains(";").all()


def test_sensitivity_data(swept: SweepFixture) -> None:
    data = swept.csv("sensitivity_alpha")
    lines = set(zip(data["scope"], data["objective"], strict=True))
    # the thesis cells leave out individual and cluster x mse / uncovered
    assert lines == {
        ("individual", "weighted_cvar"),
        ("cluster", "weighted_cvar"),
        ("portfolio", "mse"),
        ("portfolio", "expected_uncovered"),
        ("portfolio", "weighted_cvar"),
    }
    assert set(data["kpi"]) == {"cvar_uncovered"}
    assert set(data["beta"]) == {0.9}  # the evaluation beta of the toy config
    # alpha does not apply to mse: a flat line at the baseline value
    flat = data[(data["scope"] == "portfolio") & (data["objective"] == "mse")]
    assert set(flat["source"]) == {"baseline"}
    assert flat["parameter_value"].tolist() == [0.5, 0.9]
    np.testing.assert_allclose(
        flat["kpi_value"], baseline_kpi(swept, "portfolio", "mse", "cvar_uncovered")
    )
    # the sweep point alpha = 0.9 is the baseline run
    cvar = where(
        data, (data["scope"] == "portfolio") & (data["objective"] == "weighted_cvar")
    )
    assert set(cvar["source"]) == {"sweep"}
    at_default = where(cvar, cvar["parameter_value"] == 0.9)["kpi_value"].iloc[0]
    np.testing.assert_allclose(
        at_default,
        baseline_kpi(swept, "portfolio", "weighted_cvar", "cvar_uncovered"),
    )
    points = swept.csv("sensitivity_alpha.points")
    assert bool(points["ok"].all())
    assert set(points["source"]) == {"sweep", "baseline"}


def test_n_assets_sensitivity_averages_the_subsets(swept: SweepFixture) -> None:
    points = swept.csv("sensitivity_n_assets.points")
    line = swept.csv("sensitivity_n_assets")
    mine = where(
        points,
        (points["scope"] == "portfolio") & (points["objective"] == "weighted_cvar"),
    )
    ones = where(mine, mine["parameter_value"] == 1)
    assert sorted(ones["location_ids"]) == ["A1", "A2", "A3"]
    row = where(
        line,
        (line["scope"] == "portfolio")
        & (line["objective"] == "weighted_cvar")
        & (line["parameter_value"] == 1),
    )
    assert row["n_runs"].tolist() == [3]
    assert row["n_failed"].tolist() == [0]
    np.testing.assert_allclose(row["kpi_value"], ones["kpi_value"].mean())


def test_tradeoff_data(swept: SweepFixture) -> None:
    data = swept.csv("tradeoff_portfolio_alpha")
    assert data["parameter_value"].tolist() == [0.5, 0.9]
    reader = ResultReader(swept.toy.store)
    for row in data.to_dict("records"):
        run = reader.run(str(row["run_id"]))
        assert run.scope == "portfolio"
        assert run.objective == "weighted_cvar"
        for kpi in ("expected_uncovered", "cvar_uncovered"):
            np.testing.assert_allclose(row[kpi], kpi_value(run, kpi))


def test_cluster_data(swept: SweepFixture) -> None:
    penalty = swept.csv("net_advantage_cluster.penalty")
    port = baseline_kpi(swept, "portfolio", "weighted_cvar", "cvar_uncovered")
    assert penalty["n_clusters"].tolist() == [1, 2, 3]
    assert set(penalty["n_locations"]) == {3}
    assert set(penalty["portfolio_run_id"]) == {
        swept.toy.run_id("portfolio", "weighted_cvar")
    }
    np.testing.assert_allclose(penalty["cvar_portfolio"], port)
    np.testing.assert_allclose(
        penalty["penalty"], penalty["cvar_cluster"] - penalty["cvar_portfolio"]
    )
    net = swept.csv("net_advantage_cluster")
    assert sorted(set(net["transaction_cost"])) == list(THESIS_TRANSACTION_COSTS)
    merged = net.merge(penalty[["n_clusters", "penalty"]], on="n_clusters")
    np.testing.assert_allclose(
        merged["net_advantage"],
        (3 - merged["n_clusters"]) * merged["transaction_cost"] - merged["penalty_y"],
    )
    for _, group in net.groupby("transaction_cost"):
        best = group.loc[group["net_advantage"].idxmax(), "n_clusters"]
        assert set(group["optimal_n_clusters"]) == {best}
    breakeven = swept.csv("breakeven_cost_cluster")
    assert breakeven["n_clusters"].tolist() == [1, 2]  # C < K only
    np.testing.assert_allclose(
        breakeven["breakeven_cost"],
        breakeven["penalty"] / (3 - breakeven["n_clusters"]),
    )


# -- functions -----------------------------------------------------------------


def test_kpi_value_errors(toy: Fixture, failed: Fixture) -> None:
    reader = ResultReader(toy.store)
    run = reader.run(toy.run_id("portfolio", "mse"))
    with pytest.raises(MissingKpiError, match="0 'cvar_uncovered' rows"):
        kpi_value(run, "cvar_uncovered", level="entity", subject_id="nope")
    with pytest.raises(MissingKpiError, match="expected one"):
        kpi_value(run, "expected_payout", level="entity")  # one row per entity


def test_figure_inputs_are_checked(swept: SweepFixture) -> None:
    reader = ResultReader(swept.toy.store)
    ind = reader.run(swept.toy.run_id("individual", "weighted_cvar"))
    pf_mse = reader.run(swept.toy.run_id("portfolio", "mse"))
    with pytest.raises(InconsistentRunsError, match="one objective"):
        premium_reallocation(ind, pf_mse)
    with pytest.raises(InconsistentRunsError, match="no insured value"):
        premium_reallocation(
            ind,
            reader.run(swept.toy.run_id("portfolio", "weighted_cvar")),
            location_values={"A1": 1.0},
        )
    with pytest.raises(InconsistentRunsError, match="no lines"):
        sensitivity("alpha", [])
    series = SweepSeries("beta", "portfolio", pf_mse)
    with pytest.raises(InconsistentRunsError, match="got series of"):
        sensitivity("alpha", [series])
    with pytest.raises(InconsistentRunsError, match="no successful point"):
        tradeoff(series)


def test_reallocation_without_values_keeps_the_run_order(swept: SweepFixture) -> None:
    reader = ResultReader(swept.toy.store)
    out = premium_reallocation(
        reader.run(swept.toy.run_id("individual", "weighted_cvar")),
        reader.run(swept.toy.run_id("portfolio", "weighted_cvar")),
    )
    assert out.data[""]["entity_id"].tolist() == ["A1", "A2", "A3"]
    assert all_na(out.data[""]["location_value"])


def test_parameter_labels() -> None:
    assert parameter_symbol("alpha") == r"$\alpha$"
    assert parameter_label("budget_loading") == r"Budget loading $\kappa$"
    assert parameter_label("new_knob") == "New knob new knob"


def test_skipped_figure_is_the_command_type() -> None:
    assert sweep_figures.sweep_figures in command.FIGURE_SETS
    assert SkippedFigure.__module__ == command.__name__


def test_failed_baselines_skip_their_figures(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    cluster = {
        "kind": "cluster",
        "n_clusters": 4,  # more clusters than locations: the baseline fails
        "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
    }
    toy = build_fixture(
        tmp_path_factory.mktemp("broken"),
        scopes=[{"kind": "portfolio"}, cluster],
        objectives=[
            {"kind": "mse"},
            {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.9},
        ],
        sweeps=[
            {"parameter": "alpha", "values": [0.5]},
            {"parameter": "n_clusters", "values": [2, 4]},
        ],
    )
    run_sweeps(toy.config, store=toy.store, baseline=False)
    out = tmp_path_factory.mktemp("broken_figures")
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=out,
        eventset=toy.eventset,
        sweeps=sweep_runs(toy),
        figure_sets=(sweep_figures.sweep_figures,),
    )
    assert [w.name for w in report.written] == [
        "payout_sweep_portfolio_a1_alpha",
        "sensitivity_alpha",
        "tradeoff_portfolio_alpha",
        "sensitivity_n_clusters",
        "net_advantage_cluster",
        "breakeven_cost_cluster",
    ]
    skipped = [(s.name, s.failed) for s in report.skipped]
    assert skipped == [
        ("premium_reallocation", False),
        ("payout_sweep_cluster_alpha", True),
        ("sensitivity_alpha", True),
        ("sensitivity_n_clusters", True),
        ("net_advantage_cluster", True),
    ]
    assert "failed for *" in report.skipped[1].reason
    penalty = pd.read_csv(out / "net_advantage_cluster.penalty.csv")
    assert penalty["ok"].tolist() == [True, False]
    assert penalty["penalty"].isna().tolist() == [False, True]
    breakeven = pd.read_csv(out / "breakeven_cost_cluster.csv")
    assert breakeven["n_clusters"].tolist() == [2]


# -- unrun sweeps, bulk reads, transaction costs (MAR-120) ---------------------

GONE = "sha256:" + "e" * 64


def draw(swept: SweepFixture, out: Path, **options: Any) -> FigureReport:  # noqa: ANN401
    return write_figures(
        swept.toy.config,
        swept.toy.run_ids,
        store=swept.toy.store,
        out_dir=out,
        eventset=swept.toy.eventset,
        figure_sets=(sweep_figures.sweep_figures,),
        **options,
    )


def test_missing_sweep_points_skip_their_figures(
    swept: SweepFixture, tmp_path: Path
) -> None:
    # an alpha point of the portfolio x weighted CVaR run (single run 8) and
    # an n_clusters point at C = 4 > K = 3 of cluster x weighted CVaR (5)
    gone = (
        SweepRun("alpha", 0.3, GONE, single=8),
        SweepRun("n_clusters", 4, "sha256:" + "d" * 64, single=5),
    )
    report = draw(
        swept, tmp_path, sweeps=(*swept.sweeps, *gone), skip_missing_sweeps=True
    )
    assert report.missing_sweeps == gone
    assert not report.ok
    missing = [s.name for s in report.skipped if s.missing]
    assert missing == [
        "payout_sweep_portfolio_a1_alpha",
        "sensitivity_alpha",
        "tradeoff_portfolio_alpha",
        "sensitivity_n_clusters",
        "net_advantage_cluster",
    ]
    assert all(not s.failed for s in report.skipped if s.missing)
    reason = next(s.reason for s in report.skipped if s.name == "sensitivity_alpha")
    assert "1 of its 7 sweep points are not in the result store" in reason
    assert GONE in reason
    assert "sweep CONFIG --parameter alpha" in reason
    # figures whose points are all in the store are drawn as without the flag
    written = [w.name for w in report.written]
    assert written == [n for n in EXPECTED if n not in missing]
    assert "breakeven_cost_cluster" in written  # needs only C < K
    for name in ("payout_sweep_individual_a1_alpha", "breakeven_cost_cluster"):
        pd.testing.assert_frame_equal(
            pd.read_csv(tmp_path / f"{name}.csv"), swept.csv(name)
        )
    # the failed n_assets points are still reported as failed
    assert [s.name for s in report.skipped if s.failed] == ["sensitivity_n_assets"]


def test_skipping_with_nothing_missing_changes_nothing(
    swept: SweepFixture, tmp_path: Path
) -> None:
    report = draw(swept, tmp_path, sweeps=swept.sweeps, skip_missing_sweeps=True)
    assert report.missing_sweeps == ()
    assert [w.name for w in report.written] == EXPECTED
    assert report.skipped == swept.report.skipped


def test_every_sweep_point_missing(swept: SweepFixture, tmp_path: Path) -> None:
    gone = tuple(
        SweepRun(p.parameter, p.value, "sha256:" + f"{i:064x}", p.single)
        for i, p in enumerate(swept.sweeps)
    )
    report = draw(swept, tmp_path, sweeps=gone, skip_missing_sweeps=True)
    assert len(report.missing_sweeps) == len(gone)
    assert [w.name for w in report.written] == ["premium_reallocation"]
    assert [s.name for s in report.skipped] == EXPECTED[1:]
    assert all(s.missing and not s.failed for s in report.skipped)
    assert not report.ok


def test_sweep_runs_are_read_in_bulk(
    swept: SweepFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []
    bulk = ResultReader.runs

    def runs(self: ResultReader, run_ids: Iterable[str]) -> tuple[RunResult, ...]:
        ids = tuple(run_ids)
        calls.append(ids)
        return bulk(self, ids)

    def one(self: ResultReader, run_id: str) -> RunResult:
        raise AssertionError(f"read run {run_id} alone")

    monkeypatch.setattr(ResultReader, "runs", runs)
    monkeypatch.setattr(ResultReader, "run", one)
    report = draw(swept, tmp_path, sweeps=swept.sweeps)
    assert [w.name for w in report.written] == EXPECTED
    # the single runs, then one bulk read per sweep with all of its points
    assert calls[0] == swept.toy.run_ids
    assert [len(c) for c in calls[1:]] == [
        len({p.run_id for p in swept.points(x)})
        for x in ("alpha", "n_clusters", "n_assets")
    ]


def test_custom_transaction_costs_reach_the_figure_data(
    swept: SweepFixture, tmp_path: Path
) -> None:
    costs = (2.0, 0.5, 0.0)
    report = draw(swept, tmp_path, sweeps=swept.sweeps, transaction_costs=costs)
    assert [w.name for w in report.written] == EXPECTED
    net = pd.read_csv(tmp_path / "net_advantage_cluster.csv")
    assert sorted(set(net["transaction_cost"])) == sorted(costs)
    penalty = swept.csv("net_advantage_cluster.penalty")
    merged = net.merge(penalty[["n_clusters", "penalty"]], on="n_clusters")
    np.testing.assert_allclose(
        merged["net_advantage"],
        (3 - merged["n_clusters"]) * merged["transaction_cost"] - merged["penalty_y"],
    )
    zero = where(net, net["transaction_cost"] == 0.0)
    np.testing.assert_allclose(zero["net_advantage"], -zero["penalty"])
    # the break-even cost does not depend on the costs
    pd.testing.assert_frame_equal(
        pd.read_csv(tmp_path / "breakeven_cost_cluster.csv"),
        swept.csv("breakeven_cost_cluster"),
    )


@pytest.mark.parametrize(
    ("costs", "match"),
    [
        ((), "at least one"),
        ((1.0, -1.0), "finite and >= 0"),
        ((float("nan"),), "finite and >= 0"),
        ((1.0, 1.0), "repeat"),
    ],
)
def test_bad_transaction_costs_are_an_error(
    swept: SweepFixture, tmp_path: Path, costs: tuple[float, ...], match: str
) -> None:
    with pytest.raises(VizError, match=match):
        draw(swept, tmp_path, sweeps=swept.sweeps, transaction_costs=costs)
    assert not list(tmp_path.iterdir())  # checked before drawing


def test_money_tick_labels_are_distinct(
    swept: SweepFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # MAR-197: the thesis "%.0f" / "%.0fk" / "%.1fM" labels repeat on small
    # values (0.5 and 0 were both "0"); the toy losses are small
    saved: dict[str, list[tuple[str, list[str]]]] = {}
    savefig = Figure.savefig

    def spy(fig: Figure, fname: Any, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        fig.canvas.draw()
        saved[Path(str(fname)).name.split(".")[1]] = [
            (axis.get_label_text(), [t.get_text() for t in axis.get_ticklabels()])
            for ax in fig.axes
            for axis in (ax.xaxis, ax.yaxis)
            if axis.get_ticklabels()
        ]
        savefig(fig, fname, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", spy)
    draw(swept, tmp_path, sweeps=swept.sweeps, transaction_costs=(2.0, 0.5, 0.0))
    for name in ("net_advantage_cluster", "breakeven_cost_cluster"):
        axes = saved[name]
        for label, ticks in axes:
            assert len(set(ticks)) == len(ticks), (name, label, ticks)
    colorbar = [t for label, t in saved["net_advantage_cluster"] if "cost" in label]
    assert colorbar == [["0.0", "0.5", "2.0"]]  # was "0", "0", "2"
