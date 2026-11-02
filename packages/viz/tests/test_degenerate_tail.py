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
