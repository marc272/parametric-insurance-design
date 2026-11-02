"""Tests of the degenerate-tail marks (MAR-207): figures and their data.

The ``flagged`` store is the viz toy EventSet (60 events, event-conditional
basis) with the individual and portfolio scopes and a weighted-CVaR objective
at beta 0.05, swept over beta 0.05, 0.9 and 0.99. On the calibration sample,
``P(L_o = 0)`` is about 0.039 (A1), 0.098 (A2) and 0.078 (A3) for the
individual problems and 0 for the portfolio problem, and the CVaR tail holds
``(1 - beta) * 51`` outcomes. So:

* beta 0.05: the individual run is flagged ``expected_uncovered`` at A2 and
  A3, not at A1; the portfolio run is not flagged;
* beta 0.9: nothing is flagged (5.1 tail outcomes);
* beta 0.99: every problem is flagged ``single_outcome`` (0.51 outcomes).

The session ``toy`` store (beta 0.9) has no flag: its figures carry no mark.

The ``clustered`` store (a joint cluster scope and the portfolio scope,
weighted CVaR at beta 0.9, an ``n_clusters`` sweep over 1, 2 and 3) has no
flag either. A joint cluster scope is one design problem over every location,
so its flag cannot change with the cluster count; the net-advantage and
break-even tests set a run's manifest record (:func:`flag_run`) to have a
flagged and an unflagged point in one figure.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

import numpy as np
import pandas as pd
import pyarrow as pa
import pytest
from matplotlib.figure import Figure
from matplotlib.text import Text

from parametric_insurance_design.experiment import runner
from parametric_insurance_design.experiment.store import (
    MANIFESTS_DIR,
    ResultStore,
    run_file_stem,
)
from parametric_insurance_design.experiment.sweeps import run_sweeps
from parametric_insurance_design_viz import degenerate_tail as dt
from parametric_insurance_design_viz import kpi_figures, sweep_figures
from parametric_insurance_design_viz.command import write_figures
from parametric_insurance_design_viz.errors import IncompleteRunError
from parametric_insurance_design_viz.reader import ResultReader, RunResult
from parametric_insurance_design_viz.site_export import export_site, read_bundle
from parametric_insurance_design_viz.sweep_figures import (
    SweepSeries,
    breakeven_cost,
    net_advantage,
    payout_sweep,
    premium_reallocation,
    sensitivity,
    tradeoff,
)

from .conftest import build_fixture, command_sweep_runs

if TYPE_CHECKING:
    from conftest import Fixture

    from parametric_insurance_design_viz.command import FigureReport

OBJECTIVES = [
    {"kind": "expected_uncovered"},
    {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.05},
]
SCOPES = [{"kind": "individual"}, {"kind": "portfolio"}]
BETAS = [0.05, 0.9, 0.99]


@dataclass(frozen=True)
class Flagged:
    toy: Fixture
    reader: ResultReader
    out: Path
    report: FigureReport

    def run(self, scope: str, objective: str) -> RunResult:
        return self.reader.run(self.toy.run_id(scope, objective))

    def series(self, scope: str) -> SweepSeries:
        """The beta sweep of a scope's weighted-CVaR run."""
        single = [
            (s.scopes[0].kind, s.objectives[0].kind)
            for s in self.toy.config.single_runs()
        ].index((scope, "weighted_cvar"))
        points = [
            p
            for p in command_sweep_runs(self.toy.config)
            if p.parameter == "beta" and p.single == single
        ]
        runs = self.reader.runs(p.run_id for p in points)
        return SweepSeries(
            "beta",
            scope,
            self.run(scope, "weighted_cvar"),
            tuple(zip(points, runs, strict=True)),
        )


@pytest.fixture(scope="module")
def flagged(tmp_path_factory: pytest.TempPathFactory) -> Flagged:
    toy = build_fixture(
        tmp_path_factory.mktemp("flagged"),
        scopes=SCOPES,
        objectives=OBJECTIVES,
        sweeps=[{"parameter": "beta", "values": BETAS}],
    )
    run_sweeps(toy.config, store=toy.store, baseline=False)
    out = tmp_path_factory.mktemp("flagged-figures")
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=out,
        eventset=toy.eventset,
        sweeps=command_sweep_runs(toy.config),
        figure_sets=(kpi_figures.kpi_figures, sweep_figures.sweep_figures),
    )
    return Flagged(toy=toy, reader=ResultReader(toy.store), out=out, report=report)


def rings(fig: Figure) -> list[tuple[str, list[float]]]:
    """(marker, x values) of the degenerate-tail rings of a figure."""
    found = []
    for ax in fig.axes:
        for line in ax.get_lines():
            if line.get_markerfacecolor() == "none" and line.get_linestyle() == "None":
                xs = [float(x) for x in line.get_xdata()]  # pyright: ignore[reportGeneralTypeIssues]
                found.append((str(line.get_marker()), xs))
    return found


def texts(fig: Figure) -> str:
    """Every text of a figure, legends included."""
    return "\n".join(str(t.get_text()) for t in fig.findobj(Text))


def where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    """Rows of a frame where a boolean mask holds (typed for pyright)."""
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


# -- the record ---------------------------------------------------------------


def test_the_flags_are_the_runners() -> None:
    assert dt.DEGENERATE_TAILS == runner.DEGENERATE_TAILS
    assert dt.EXPECTED_UNCOVERED == runner.DEGENERATE_TAIL_EXPECTED_UNCOVERED
    assert dt.SINGLE_OUTCOME == runner.DEGENERATE_TAIL_SINGLE_OUTCOME


def test_problem_tails_read_the_manifest(flagged: Flagged) -> None:
    run = flagged.run("individual", "weighted_cvar")
    tails = {t.problem_id: t for t in dt.problem_tails(run) or ()}
    assert tails.keys() == {"A1", "A2", "A3"}
    assert tails["A1"].degenerate_tail is None
    assert tails["A2"].degenerate_tail == dt.EXPECTED_UNCOVERED
    assert tails["A3"].degenerate_tail == dt.EXPECTED_UNCOVERED
    for tail in tails.values():
        assert tail.p_zero_loss is not None
        # beta 0.05 against P(L_o = 0): flagged exactly where beta is not above.
        assert (tail.degenerate_tail is not None) == (0.05 <= tail.p_zero_loss)
    assert dt.run_degenerate_tail(run) == dt.EXPECTED_UNCOVERED
    portfolio = flagged.run("portfolio", "weighted_cvar")
    assert dt.run_degenerate_tail(portfolio) is None
    # Another objective is never flagged; it records P(L_o = 0) all the same.
    eu = flagged.run("individual", "expected_uncovered")
    assert dt.run_degenerate_tail(eu) is None
    assert all(t.p_zero_loss is not None for t in dt.problem_tails(eu) or ())


def test_a_run_without_the_record_has_no_flag(flagged: Flagged) -> None:
    run = flagged.run("individual", "weighted_cvar")
    problems = [
        {k: v for k, v in p.items() if k not in dt.TAIL_KEYS}
        for p in run.manifest["problems"]
    ]
    old = dataclasses.replace(run, manifest={**run.manifest, "problems": problems})
    assert dt.problem_tails(old) is None
    assert dt.run_degenerate_tail(old) is None
    assert dt.degenerate_tail_table([old]).empty


def test_an_unknown_flag_is_refused(flagged: Flagged) -> None:
    run = flagged.run("individual", "weighted_cvar")
    problems = [{**p, "degenerate_tail": "other"} for p in run.manifest["problems"]]
    bad = dataclasses.replace(run, manifest={**run.manifest, "problems": problems})
    with pytest.raises(IncompleteRunError, match="unknown degenerate_tail"):
        dt.problem_tails(bad)


def test_notes_say_when_only_some_problems_are_flagged(flagged: Flagged) -> None:
    individual = flagged.run("individual", "weighted_cvar")
    notes = dt.degenerate_tail_notes([[individual]])
    assert notes == {
        dt.EXPECTED_UNCOVERED: dt.DEGENERATE_TAIL_NOTES[dt.EXPECTED_UNCOVERED]
        + dt.PARTIAL_NOTE
    }
    assert dt.degenerate_tail_notes([[flagged.run("portfolio", "weighted_cvar")]]) == {}


# -- sweep figures ------------------------------------------------------------


def test_sensitivity_rings_the_flagged_points(flagged: Flagged) -> None:
    out = sensitivity(
        "beta", [flagged.series("individual"), flagged.series("portfolio")]
    )
    # expected_uncovered at beta 0.05 (individual); single_outcome at 0.99.
    assert sorted(rings(out.figure)) == [
        ("D", [0.99]),
        ("D", [0.99]),
        ("o", [0.05]),
    ]
    table = out.data[dt.DEGENERATE_TAIL_TABLE]
    assert list(table.columns) == list(dt.DEGENERATE_TAIL_COLUMNS)
    flags = {
        (row["scope"], row["beta"], row["problem_id"]): row["degenerate_tail"]
        for row in table.to_dict("records")
    }
    assert flags == {
        ("individual", 0.05, "A2"): dt.EXPECTED_UNCOVERED,
        ("individual", 0.05, "A3"): dt.EXPECTED_UNCOVERED,
        **{("individual", 0.99, p): dt.SINGLE_OUTCOME for p in ("A1", "A2", "A3")},
        ("portfolio", 0.99, "portfolio"): dt.SINGLE_OUTCOME,
    }
    # The unflagged point (beta 0.9) is neither ringed nor listed.
    assert 0.9 not in set(table["beta"])
    drawn = texts(out.figure)
    assert dt.DEGENERATE_TAIL_NOTES[dt.EXPECTED_UNCOVERED] + dt.PARTIAL_NOTE in drawn
    assert dt.DEGENERATE_TAIL_NOTES[dt.SINGLE_OUTCOME] in drawn
    assert dt.DEGENERATE_TAIL_NOTES[dt.SINGLE_OUTCOME] + dt.PARTIAL_NOTE not in drawn


def test_tradeoff_rings_the_flagged_points(flagged: Flagged) -> None:
    out = tradeoff(flagged.series("portfolio"))
    [(marker, xs)] = rings(out.figure)
    assert marker == "D"
    main = out.data[""]
    flagged_x = float(
        main.loc[main["parameter_value"] == 0.99, "expected_uncovered"].iloc[0]
    )
    assert xs == [flagged_x]
    table = out.data[dt.DEGENERATE_TAIL_TABLE]
    assert list(table["beta"]) == [0.99]


def test_an_unflagged_sweep_has_no_marks(toy: Fixture, tmp_path: Path) -> None:
    fixture = build_fixture(
        tmp_path / "plain",
        scopes=[{"kind": "portfolio"}],
        objectives=[{"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.9}],
        sweeps=[{"parameter": "beta", "values": [0.8, 0.9]}],
    )
    run_sweeps(fixture.config, store=fixture.store, baseline=False)
    reader = ResultReader(fixture.store)
    points = [p for p in command_sweep_runs(fixture.config) if p.parameter == "beta"]
    series = SweepSeries(
        "beta",
        "portfolio",
        reader.run(fixture.run_ids[0]),
        tuple(zip(points, reader.runs(p.run_id for p in points), strict=True)),
    )
    for out in (sensitivity("beta", [series]), tradeoff(series)):
        assert rings(out.figure) == []
        assert dt.DEGENERATE_TAIL_TABLE not in out.data
        assert "Weighted CVaR" not in texts(out.figure)


def test_the_payout_sweep_rings_the_flagged_values(flagged: Flagged) -> None:
    series = flagged.series("individual")
    # A2's own design problem: expected_uncovered at 0.05, single_outcome at
    # 0.99, unflagged at 0.9. The rings are on the colour bar (second axes).
    out = payout_sweep(series, "A2")
    assert len(out.figure.axes) == 2
    assert sorted(rings(out.figure)) == [("D", [0.99]), ("o", [0.05])]
    bar = out.figure.axes[1]
    assert all(line.axes is bar for line in bar.get_lines())
    drawn = texts(out.figure)
    assert dt.DEGENERATE_TAIL_NOTES[dt.EXPECTED_UNCOVERED] in drawn
    assert dt.DEGENERATE_TAIL_NOTES[dt.SINGLE_OUTCOME] in drawn
    assert dt.PARTIAL_NOTE not in drawn  # each ring is one design problem
    table = out.data[dt.DEGENERATE_TAIL_TABLE]
    assert set(table["beta"]) == {0.05, 0.99}
    # A1's design problem is not flagged at 0.05 (its P(L_o = 0) is below
    # beta), so its figure rings 0.99 only, though the run is flagged at A2.
    a1 = payout_sweep(series, "A1")
    assert rings(a1.figure) == [("D", [0.99])]
    assert dt.DEGENERATE_TAIL_NOTES[dt.EXPECTED_UNCOVERED] not in texts(a1.figure)


def test_a_payout_sweep_of_one_value_marks_its_label(flagged: Flagged) -> None:
    series = flagged.series("individual")
    at = {float(p.value): (p, r) for p, r in series.points}
    out = payout_sweep(dataclasses.replace(series, points=(at[0.05],)), "A2")
    assert rings(out.figure) == []  # no colour bar: the label carries the mark
    symbol = dt.DEGENERATE_TAIL_SYMBOLS[dt.EXPECTED_UNCOVERED]
    labels = [str(t.get_text()) for t in out.figure.legends[0].get_texts()]
    assert any(label.endswith(f"= 0.05 {symbol}") for label in labels)
    note = f"{symbol} {dt.DEGENERATE_TAIL_NOTES[dt.EXPECTED_UNCOVERED]}"
    assert note in texts(out.figure)
    plain = payout_sweep(dataclasses.replace(series, points=(at[0.9],)), "A2")
    assert symbol not in texts(plain.figure)
    assert "Weighted CVaR" not in texts(plain.figure)
    assert dt.DEGENERATE_TAIL_TABLE not in plain.data


def test_the_premium_reallocation_rings_the_flagged_locations(
    flagged: Flagged,
) -> None:
    individual = flagged.run("individual", "weighted_cvar")
    portfolio = flagged.run("portfolio", "weighted_cvar")
    assert dt.entity_flags(individual) == {
        "A1": None,
        "A2": dt.EXPECTED_UNCOVERED,
        "A3": dt.EXPECTED_UNCOVERED,
    }
    assert set(dt.entity_flags(portfolio).values()) == {None}
    out = premium_reallocation(individual, portfolio)
    main = out.data[""]
    # Entities in run order (no insured values): A1, A2, A3 at x 0, 1, 2.
    assert main["entity_id"].tolist() == ["A1", "A2", "A3"]
    assert rings(out.figure) == [("o", [1.0, 2.0])]
    [ring] = [
        line
        for line in out.figure.axes[0].get_lines()
        if line.get_markerfacecolor() == "none"
    ]
    ys = [float(y) for y in ring.get_ydata()]  # pyright: ignore[reportGeneralTypeIssues]
    assert ys == pytest.approx(main["individual_share"].iloc[1:].tolist())
    drawn = texts(out.figure)
    assert dt.DEGENERATE_TAIL_NOTES[dt.EXPECTED_UNCOVERED] in drawn
    assert dt.PARTIAL_NOTE not in drawn
    table = out.data[dt.DEGENERATE_TAIL_TABLE]
    assert sorted(table["problem_id"]) == ["A2", "A3"]


def test_an_unflagged_premium_reallocation_has_no_marks(toy: Fixture) -> None:
    reader = ResultReader(toy.store)
    out = premium_reallocation(
        reader.run(toy.run_id("individual", "weighted_cvar")),
        reader.run(toy.run_id("portfolio", "weighted_cvar")),
    )
    assert rings(out.figure) == []
    assert dt.DEGENERATE_TAIL_TABLE not in out.data
    assert "Weighted CVaR" not in texts(out.figure)


@dataclass(frozen=True)
class Clustered:
    series: SweepSeries  # the n_clusters sweep of the cluster scope
    benchmark: RunResult  # the portfolio scope's weighted-CVaR run


@pytest.fixture(scope="module")
def clustered(tmp_path_factory: pytest.TempPathFactory) -> Clustered:
    toy = build_fixture(
        tmp_path_factory.mktemp("clustered"),
        scopes=[
            {
                "kind": "cluster",
                "n_clusters": 2,
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
            },
            {"kind": "portfolio"},
        ],
        objectives=[{"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.9}],
        sweeps=[{"parameter": "n_clusters", "values": [1, 2, 3]}],
    )
    run_sweeps(toy.config, store=toy.store, baseline=False)
    reader = ResultReader(toy.store)
    points = [p for p in command_sweep_runs(toy.config) if p.single == 0]
    series = SweepSeries(
        "n_clusters",
        "cluster",
        reader.run(toy.run_id("cluster", "weighted_cvar")),
        tuple(zip(points, reader.runs(p.run_id for p in points), strict=True)),
    )
    return Clustered(series, reader.run(toy.run_id("portfolio", "weighted_cvar")))


def flag_run(run: RunResult, flag: str) -> RunResult:
    """The run with every design problem's record set to ``flag``."""
    problems = [{**p, "degenerate_tail": flag} for p in run.manifest["problems"]]
    return dataclasses.replace(run, manifest={**run.manifest, "problems": problems})


def test_the_cluster_figures_ring_the_flagged_count(clustered: Clustered) -> None:
    assert [p.value for p, _ in clustered.series.points] == [1, 2, 3]
    assert {dt.run_degenerate_tail(r) for _, r in clustered.series.points} == {None}
    points = tuple(
        (p, flag_run(r, dt.SINGLE_OUTCOME) if p.value == 2 else r)
        for p, r in clustered.series.points
    )
    series = dataclasses.replace(clustered.series, points=points)
    [flagged_id] = [r.run_id for p, r in points if p.value == 2]
    net = net_advantage(series, clustered.benchmark)
    costs = len(sweep_figures.THESIS_TRANSACTION_COSTS)
    # C = 2 on every cost curve; C = 1 and C = 3 are not ringed.
    assert rings(net.figure) == [("D", [2.0])] * costs
    breakeven = breakeven_cost(series, clustered.benchmark)
    assert rings(breakeven.figure) == [("D", [2.0])]
    for out in (net, breakeven):
        assert set(out.data[dt.DEGENERATE_TAIL_TABLE]["run_id"]) == {flagged_id}
        # The penalty also reads the unflagged benchmark: the note says so.
        note = dt.DEGENERATE_TAIL_NOTES[dt.SINGLE_OUTCOME] + dt.PARTIAL_NOTE
        assert note in texts(out.figure)


def test_a_flagged_benchmark_rings_every_count(clustered: Clustered) -> None:
    benchmark = flag_run(clustered.benchmark, dt.EXPECTED_UNCOVERED)
    net = net_advantage(clustered.series, benchmark)
    costs = len(sweep_figures.THESIS_TRANSACTION_COSTS)
    assert rings(net.figure) == [("o", [1.0, 2.0, 3.0])] * costs
    breakeven = breakeven_cost(clustered.series, benchmark)
    assert rings(breakeven.figure) == [("o", [1.0, 2.0])]  # C < K only
    table = breakeven.data[dt.DEGENERATE_TAIL_TABLE]
    assert list(table["run_id"]) == [benchmark.run_id]


def test_unflagged_cluster_figures_have_no_marks(clustered: Clustered) -> None:
    for out in (
        net_advantage(clustered.series, clustered.benchmark),
        breakeven_cost(clustered.series, clustered.benchmark),
    ):
        assert rings(out.figure) == []
        assert dt.DEGENERATE_TAIL_TABLE not in out.data
        assert "Weighted CVaR" not in texts(out.figure)


# -- KPI figures --------------------------------------------------------------


def grid(fx: Flagged) -> dict[str, list[RunResult]]:
    return {
        scope["kind"]: [fx.run(scope["kind"], o["kind"]) for o in OBJECTIVES]
        for scope in SCOPES
    }


def test_the_heatmap_marks_the_flagged_cell(flagged: Flagged) -> None:
    out = kpi_figures.kpi_heatmap(grid(flagged), "cvar_uncovered")
    main = out.data[""]
    marked = main.loc[main["degenerate_tail"].notna(), ["scope_key", "objective"]]
    assert marked.values.tolist() == [["individual", "weighted_cvar"]]
    drawn = texts(out.figure)
    assert dt.DEGENERATE_TAIL_SYMBOLS[dt.EXPECTED_UNCOVERED] in drawn
    assert dt.DEGENERATE_TAIL_SYMBOLS[dt.SINGLE_OUTCOME] not in drawn
    assert dt.DEGENERATE_TAIL_NOTES[dt.EXPECTED_UNCOVERED] + dt.PARTIAL_NOTE in drawn
    table = out.data[dt.DEGENERATE_TAIL_TABLE]
    assert sorted(table["problem_id"]) == ["A2", "A3"]


def test_the_overview_and_exceedance_mark_the_flagged_run(flagged: Flagged) -> None:
    overview = kpi_figures.performance_overview(grid(flagged))
    main = overview.data[""]
    flags = {
        (row["scope_key"], row["objective"], row["kpi"]): row["degenerate_tail"]
        for row in main.to_dict("records")
    }
    assert {k: v for k, v in flags.items() if isinstance(v, str)} == {
        ("individual", "weighted_cvar", kpi): dt.EXPECTED_UNCOVERED
        for kpi in kpi_figures.OVERVIEW_KPIS
    }
    symbol = dt.DEGENERATE_TAIL_SYMBOLS[dt.EXPECTED_UNCOVERED]
    annotations = [t for t in overview.figure.axes[0].texts if t.get_text() == symbol]
    assert len(annotations) == 1
    assert dt.DEGENERATE_TAIL_TABLE in overview.data

    flagged_curves = kpi_figures.exceedance_curves(grid(flagged)["individual"])
    assert symbol in texts(flagged_curves.figure)
    assert dt.DEGENERATE_TAIL_TABLE in flagged_curves.data
    plain_curves = kpi_figures.exceedance_curves(grid(flagged)["portfolio"])
    assert symbol not in texts(plain_curves.figure)
    assert dt.DEGENERATE_TAIL_TABLE not in plain_curves.data


def test_unflagged_kpi_figures_are_unchanged(toy: Fixture) -> None:
    reader = ResultReader(toy.store)
    scopes = {"individual", "cluster", "portfolio"}
    runs = {
        s: [
            reader.run(toy.run_id(s, o))
            for o in ("mse", "expected_uncovered", "weighted_cvar")
        ]
        for s in sorted(scopes)
    }
    for out in (
        kpi_figures.kpi_heatmap(runs, "cvar_uncovered"),
        kpi_figures.performance_overview(runs),
        kpi_figures.exceedance_curves(runs["portfolio"]),
    ):
        assert dt.DEGENERATE_TAIL_TABLE not in out.data
        assert "degenerate_tail" not in out.data[""].columns
        assert "Weighted CVaR" not in texts(out.figure)


# -- the figures command ------------------------------------------------------


def test_the_figures_command_writes_the_tables(flagged: Flagged) -> None:
    assert flagged.report.ok
    written = {f.name: f for f in flagged.report.written}
    with_table = {
        name for name, f in written.items() if dt.DEGENERATE_TAIL_TABLE in f.tables
    }
    assert {
        "kpi_heatmap_cvar_uncovered",
        "performance_overview",
        "exceedance_individual",
        "sensitivity_beta",
        "tradeoff_portfolio_beta",
        "payout_sweep_individual_a1_beta",
        "premium_reallocation",
    } <= with_table
    assert "exceedance_portfolio" not in with_table
    csv = pd.read_csv(written["sensitivity_beta"].tables[dt.DEGENERATE_TAIL_TABLE])
    assert list(csv.columns) == list(dt.DEGENERATE_TAIL_COLUMNS)
    assert set(csv["degenerate_tail"]) == {dt.EXPECTED_UNCOVERED, dt.SINGLE_OUTCOME}


# -- the site bundle ------------------------------------------------------------


def arrow(path: Path) -> pd.DataFrame:
    with pa.memory_map(str(path)) as source:
        return pa.ipc.open_file(source).read_all().to_pandas()


def flags_of(kpis: pd.DataFrame, problem_id: str, **where: object) -> set[object]:
    """The ``degenerate_tail`` values of a problem's rows (None for null)."""
    mask = kpis["problem_id"] == problem_id
    for column, value in where.items():
        mask &= kpis[column] == value
    return {None if pd.isna(v) else v for v in kpis.loc[mask, "degenerate_tail"]}


@pytest.fixture(scope="module")
def bundle(flagged: Flagged, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("flagged-bundle") / "bundle"
    export_site(
        flagged.toy.config,
        flagged.toy.run_ids,
        store=flagged.toy.store,
        out_dir=out,
        eventset=flagged.toy.eventset,
        sweeps=command_sweep_runs(flagged.toy.config),
    )
    return out


def test_the_bundle_kpis_carry_the_flags(flagged: Flagged, bundle: Path) -> None:
    kpis = arrow(bundle / "sweep.beta.kpis.arrow")
    ind = where(kpis, kpis["scope"] == "individual")
    # beta 0.05: A2 and A3 flagged, A1 not; the run's "*" rows carry the flag.
    assert flags_of(ind, "A2", sweep_value=0.05) == {dt.EXPECTED_UNCOVERED}
    assert flags_of(ind, "A3", sweep_value=0.05) == {dt.EXPECTED_UNCOVERED}
    assert flags_of(ind, "A1", sweep_value=0.05) == {None}
    assert flags_of(ind, "*", sweep_value=0.05) == {dt.EXPECTED_UNCOVERED}
    # beta 0.9: nothing flagged.
    assert flags_of(ind, "*", sweep_value=0.9) == {None}
    assert bool(where(ind, ind["sweep_value"] == 0.9)["degenerate_tail"].isna().all())
    assert flags_of(ind, "*", sweep_value=0.99) == {dt.SINGLE_OUTCOME}
    pf = where(kpis, kpis["scope"] == "portfolio")
    assert flags_of(pf, "portfolio", sweep_value=0.05) == {None}
    assert flags_of(pf, "portfolio", sweep_value=0.99) == {dt.SINGLE_OUTCOME}
    # P(L_o = 0) of each problem row is its manifest value; null on "*" rows.
    run = flagged.run("individual", "weighted_cvar")
    expected = {t.problem_id: t.p_zero_loss for t in dt.problem_tails(run) or ()}
    rows = where(ind, (ind["run_id"] == run.run_id) & (ind["problem_id"] != "*"))
    recorded: dict[str, set[float]] = {}
    for row in rows.to_dict("records"):
        recorded.setdefault(str(row["problem_id"]), set()).add(row["p_zero_loss"])
    assert recorded == {p: {v} for p, v in expected.items()}
    assert bool(where(ind, ind["problem_id"] == "*")["p_zero_loss"].isna().all())
    assert set(pf["p_zero_loss"]) == {0.0}
    # The baseline table has the columns too.
    baseline = arrow(bundle / "baseline.kpis.arrow")
    assert flags_of(baseline, "*", run_id=run.run_id) == {dt.EXPECTED_UNCOVERED}


def test_the_bundle_manifest_and_runs_state_the_flags(
    flagged: Flagged, bundle: Path
) -> None:
    manifest = read_bundle(bundle)
    section = manifest["degenerate_tail"]
    assert section["notes"] == dict(dt.DEGENERATE_TAIL_TEXT)
    assert section["not_recorded"] == []
    individual = flagged.run("individual", "weighted_cvar")
    portfolio = flagged.run("portfolio", "weighted_cvar")
    listed = {r["run_id"]: r for r in section["runs"]}
    assert listed[individual.run_id] == {
        "run_id": individual.run_id,
        "scope_key": "individual",
        "objective": "weighted_cvar",
        "problems": {"A2": dt.EXPECTED_UNCOVERED, "A3": dt.EXPECTED_UNCOVERED},
    }
    assert portfolio.run_id not in listed  # unflagged
    assert {tuple(sorted(set(r["problems"].values()))) for r in listed.values()} == {
        (dt.EXPECTED_UNCOVERED,),
        (dt.SINGLE_OUTCOME,),
    }
    columns = {
        c["name"]: c
        for f in manifest["files"]
        if f["path"] == "sweep.beta.kpis.arrow"
        for c in f["columns"]
    }
    assert columns["p_zero_loss"]["null_means"].startswith("not recorded")
    assert columns["degenerate_tail"]["null_means"].startswith("no flag")
    runs = json.loads((bundle / "runs.json").read_text(encoding="utf-8"))["runs"]
    entry = next(r for r in runs if r["run_id"] == individual.run_id)
    problems = {p["problem_id"]: p for p in entry["problems"]}
    assert problems["A2"]["degenerate_tail"] == dt.EXPECTED_UNCOVERED
    assert problems["A1"]["degenerate_tail"] is None
    assert problems["A1"]["p_zero_loss"] == pytest.approx(0.039, abs=1e-3)
    assert problems["A1"]["tail_outcomes"] == pytest.approx(0.95 * 51)


def test_a_bundle_run_without_the_record_is_listed(
    flagged: Flagged, tmp_path: Path
) -> None:
    store_dir = tmp_path / "store"
    shutil.copytree(flagged.toy.store.root, store_dir)
    run_id = flagged.toy.run_id("individual", "weighted_cvar")
    path = store_dir / MANIFESTS_DIR / f"{run_file_stem(run_id)}.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for problem in manifest["problems"]:
        for key in dt.TAIL_KEYS:
            del problem[key]
    path.write_text(json.dumps(manifest), encoding="utf-8")
    out = tmp_path / "bundle"
    export_site(
        flagged.toy.config,
        flagged.toy.run_ids,
        store=ResultStore(store_dir),
        out_dir=out,
        eventset=flagged.toy.eventset,
        parameters=[],
    )
    section = read_bundle(out)["degenerate_tail"]
    assert section["not_recorded"] == [run_id]
    assert run_id not in {r["run_id"] for r in section["runs"]}
    kpis = arrow(out / "baseline.kpis.arrow")
    rows = where(kpis, kpis["run_id"] == run_id)
    assert bool(rows["p_zero_loss"].isna().all())
    assert bool(rows["degenerate_tail"].isna().all())
    runs = json.loads((out / "runs.json").read_text(encoding="utf-8"))["runs"]
    entry = next(r for r in runs if r["run_id"] == run_id)
    assert {p["degenerate_tail"] for p in entry["problems"]} == {None}
    assert {p["p_zero_loss"] for p in entry["problems"]} == {None}
