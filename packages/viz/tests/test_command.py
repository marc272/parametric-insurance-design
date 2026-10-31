"""Tests of the figure set of the ``figures`` command (MAR-110).

k-fold configs (MAR-151): the KPI figures draw the pooled out-of-sample KPIs
of a real k = 2 store; the other figures are skipped with their reasons.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import pandas as pd
import pytest
import yaml

from parametric_insurance_design import cli
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.kfold import (
    FoldDriftError,
    PooledKpis,
    pooled_kpis,
)
from parametric_insurance_design.experiment.runner import (
    load_input,
    prepare_eventset,
    run_config,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design_viz import command
from parametric_insurance_design_viz.command import (
    FIGURE_SETS,
    KFOLD_PAYOUT_REASON,
    KFOLD_SET_REASON,
    FigureContext,
    SkippedFigure,
    _scope_keys,
    payout_figures,
    write_figures,
)
from parametric_insurance_design_viz.errors import (
    EventSetMismatchError,
    InconsistentRunsError,
    MissingRunError,
)
from parametric_insurance_design_viz.kpi_figures import KFoldRunsError
from parametric_insurance_design_viz.reader import ResultReader

if TYPE_CHECKING:
    from conftest import Fixture

EXPECTED = [
    "payout_grid_individual",
    "normalised_payout_individual_a1",
    "payout_grid_cluster",
    "normalised_payout_cluster_c1",
    "payout_grid_portfolio",
    "normalised_payout_portfolio_a1",
]


def test_writes_the_payout_figure_set(toy: Fixture, tmp_path: Path) -> None:
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=tmp_path,
        eventset=toy.eventset,
        figure_sets=(payout_figures,),
    )
    assert report.ok
    assert report.skipped == ()
    assert report.out_dir == tmp_path
    assert [w.name for w in report.written] == EXPECTED
    for written in report.written:
        assert written.image.is_file()
        assert written.image.parent == tmp_path
        for path in written.tables.values():
            assert path.is_file()
    grid = pd.read_csv(tmp_path / "payout_grid_individual.csv")
    assert set(grid["run_id"]) == {
        toy.run_id("individual", o)
        for o in ("mse", "expected_uncovered", "weighted_cvar")
    }
    assert (tmp_path / "payout_grid_individual.events.csv").is_file()
    assert (tmp_path / "normalised_payout_cluster_c1.density.csv").is_file()


def test_without_eventset_there_are_no_overlays(toy: Fixture, tmp_path: Path) -> None:
    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=tmp_path,
        figure_sets=(payout_figures,),
    )
    assert [w.name for w in report.written] == EXPECTED
    assert not (tmp_path / "payout_grid_individual.events.csv").exists()
    assert pd.read_csv(tmp_path / "normalised_payout_individual_a1.density.csv").empty


def test_failed_scope_is_skipped_and_reported(failed: Fixture, tmp_path: Path) -> None:
    report = write_figures(
        failed.config,
        failed.run_ids,
        store=failed.store,
        out_dir=tmp_path,
        eventset=failed.eventset,
        figure_sets=(payout_figures,),
    )
    assert not report.ok
    assert [w.name for w in report.written] == [
        "payout_grid_portfolio",
        "normalised_payout_portfolio_a1",
    ]
    assert [(s.name, s.failed) for s in report.skipped] == [
        ("payout_grid_cluster", True),
        ("normalised_payout_cluster", True),
    ]
    assert "cluster x mse" in report.skipped[0].reason


def test_normalised_figure_needs_the_benchmark(toy: Fixture, tmp_path: Path) -> None:
    config = toy.config.model_copy(
        update={
            "objectives": toy.config.objectives[1:],
            "scopes": toy.config.scopes[2:],
        }
    )
    run_ids = [
        toy.run_id("portfolio", o) for o in ("expected_uncovered", "weighted_cvar")
    ]
    report = write_figures(
        config,
        run_ids,
        store=toy.store,
        out_dir=tmp_path,
        figure_sets=(payout_figures,),
    )
    assert report.ok
    assert [w.name for w in report.written] == ["payout_grid_portfolio"]
    assert report.skipped == (
        SkippedFigure(
            "normalised_payout_portfolio",
            "the config has no 'mse' objective to normalise by",
            failed=False,
        ),
    )


def test_input_errors(toy: Fixture, failed: Fixture, tmp_path: Path) -> None:
    with pytest.raises(InconsistentRunsError, match="9 single runs, got 8"):
        write_figures(toy.config, toy.run_ids[1:], store=toy.store, out_dir=tmp_path)
    missing = ("sha256:" + "f" * 64, *toy.run_ids[1:])
    with pytest.raises(MissingRunError):
        write_figures(toy.config, missing, store=toy.store, out_dir=tmp_path)
    with pytest.raises(EventSetMismatchError):
        write_figures(
            toy.config,
            toy.run_ids,
            store=toy.store,
            out_dir=tmp_path,
            eventset=failed.eventset.select_locations(["A1", "A2"]),
        )
    assert not list(tmp_path.iterdir())  # nothing drawn before the checks


def test_figure_sets_are_extensible(toy: Fixture, tmp_path: Path) -> None:
    seen: list[FigureContext] = []

    def custom(context: FigureContext) -> list[SkippedFigure]:
        seen.append(context)
        return [SkippedFigure("custom", "nothing to draw", failed=False)]

    report = write_figures(
        toy.config,
        toy.run_ids,
        store=toy.store,
        out_dir=tmp_path,
        figure_sets=(custom,),
    )
    assert report.written == ()
    assert [s.name for s in report.skipped] == ["custom"]
    (context,) = seen
    assert [s.key for s in context.scopes] == ["individual", "cluster", "portfolio"]
    assert [len(s.runs) for s in context.scopes] == [3, 3, 3]
    assert FIGURE_SETS[0] is payout_figures  # later sets append (ADR 0002)


def test_scope_keys_number_repeated_kinds(toy: Fixture) -> None:
    scopes = toy.config.scopes
    config = toy.config.model_copy(update={"scopes": (scopes[1], scopes[0], scopes[1])})
    assert _scope_keys(config) == ["cluster", "individual", "cluster_2"]


# -- k-fold configs: pooled KPIs (MAR-151); refused without them (MAR-142) --------


@dataclass(frozen=True)
class KFold:
    path: Path
    config: ExperimentConfig
    store: ResultStore
    run_ids: tuple[str, ...]


@pytest.fixture(scope="module")
def kfold(toy: Fixture, tmp_path_factory: pytest.TempPathFactory) -> KFold:
    """A real k-fold store (k = 2), written by the runner: 2 x 2 x 2 runs."""
    directory = tmp_path_factory.mktemp("kfold")
    data = toy.config.model_dump(mode="json")
    data.update(
        scopes=[{"kind": "individual"}, {"kind": "portfolio"}],
        objectives=[
            {"kind": "mse"},
            {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.9},
        ],
        sample={"kind": "kfold", "k": 2},
        bootstrap={"seed": 3, "n_bootstrap": 100},
        output={"directory": str(directory / "results")},
    )
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = load_config(path)
    run_config(config)
    checksum = load_input(config).checksum
    run_ids = tuple(run_key(config_hash(s), checksum) for s in config.single_runs())
    return KFold(path, config, ResultStore(config.output.directory), run_ids)


def pooled_of(kfold: KFold, store: ResultStore | None = None) -> PooledKpis:
    prepared = prepare_eventset(kfold.config, load_input(kfold.config).eventset)
    return pooled_kpis(kfold.config, store or kfold.store, prepared, kfold.run_ids)


def test_the_kfold_store_is_real(kfold: KFold) -> None:
    runs = ResultReader(kfold.store).runs(kfold.run_ids)
    assert len(runs) == 2 * 2 * 2
    assert {r.parameters["sample"] for r in runs} == {"kfold"}
    assert sorted((r.scope, r.objective, r.parameters["fold"]) for r in runs) == [
        (scope, objective, fold)
        for scope in ("individual", "portfolio")
        for objective in ("mse", "weighted_cvar")
        for fold in (0, 1)
    ]


def test_a_kfold_config_without_pooled_kpis_is_refused_before_any_figure_set(
    kfold: KFold, toy: Fixture, tmp_path: Path
) -> None:
    called: list[FigureContext] = []

    def spy(context: FigureContext) -> list[SkippedFigure]:
        called.append(context)
        return []

    out_dir = tmp_path / "figures"
    for figure_sets in (FIGURE_SETS, (spy,)):
        with pytest.raises(KFoldRunsError) as info:
            write_figures(
                kfold.config,
                kfold.run_ids,
                store=kfold.store,
                out_dir=out_dir,
                eventset=None,
                figure_sets=figure_sets,
            )
        message = str(info.value)
        assert "config 'viz-toy' has a k-fold sample (k=2)" in message
        assert "pooled out-of-sample KPIs (MAR-151)" in message
        assert "experiment.kfold.pooled_kpis" in message
    assert called == []  # no figure set ran
    assert not out_dir.exists()  # nothing written
    # not the misleading payout-figure error of a fold grouped as an objective
    assert "each objective once" not in message
    assert issubclass(KFoldRunsError, InconsistentRunsError)
    # the refusal is of the config: a store holding the runs is not read first
    with pytest.raises(KFoldRunsError):
        write_figures(kfold.config, (), store=toy.store, out_dir=out_dir)
    # a config that fixes one fold cannot be pooled
    one_fold = kfold.config.model_copy(
        update={"sample": kfold.config.sample.model_copy(update={"fold": 0})}
    )
    with pytest.raises(KFoldRunsError, match="fixes fold 0"):
        write_figures(
            one_fold,
            kfold.run_ids[:1],
            store=kfold.store,
            out_dir=out_dir,
            pooled_kpis=pooled_of(kfold).table,
        )
    assert not out_dir.exists()


def test_a_kfold_config_draws_the_pooled_kpi_figures(
    kfold: KFold, tmp_path: Path
) -> None:
    pooled = pooled_of(kfold)
    eventset = prepare_eventset(kfold.config, load_input(kfold.config).eventset)
    report = write_figures(
        kfold.config,
        kfold.run_ids,
        store=kfold.store,
        out_dir=tmp_path,
        eventset=eventset,
        pooled_kpis=pooled.table,
    )
    assert report.ok
    assert [w.name for w in report.written] == [
        "kpi_heatmap_cvar_uncovered",
        "kpi_heatmap_expected_uncovered",
        "performance_overview",
    ]
    assert [(s.name, s.failed) for s in report.skipped] == [
        ("payout_grid_individual", False),
        ("normalised_payout_individual", False),
        ("payout_grid_portfolio", False),
        ("normalised_payout_portfolio", False),
        ("exceedance_individual", False),
        ("exceedance_portfolio", False),
        ("sweep_figures", False),
    ]
    reasons = [s.reason for s in report.skipped]
    assert reasons[:4] == [KFOLD_PAYOUT_REASON] * 4
    assert reasons[-1] == KFOLD_SET_REASON
    heatmap = pd.read_csv(tmp_path / "kpi_heatmap_cvar_uncovered.csv")
    assert len(heatmap) == 4  # one pooled row per scope x objective
    assert set(heatmap["eval_split"]) == {"pooled"}
    assert bool(heatmap["ci_drawn"].all())  # paired intervals from one resample
    assert set(heatmap["n_bootstrap"]) == {100}


def test_kfold_scopes_hold_a_run_per_objective_and_fold(
    kfold: KFold, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[FigureContext] = []

    def spy(context: FigureContext) -> list[SkippedFigure]:
        seen.append(context)
        return []

    monkeypatch.setattr(command, "KFOLD_FIGURE_SETS", (spy,))
    pooled = pooled_of(kfold)
    report = write_figures(
        kfold.config,
        kfold.run_ids,
        store=kfold.store,
        out_dir=tmp_path,
        figure_sets=(spy, payout_figures),
        pooled_kpis=pooled.table,
    )
    # a figure set that does not handle k-fold is reported, not run
    assert [(s.name, s.reason) for s in report.skipped] == [
        ("payout_figures", KFOLD_SET_REASON)
    ]
    (context,) = seen
    pd.testing.assert_frame_equal(cast(pd.DataFrame, context.pooled_kpis), pooled.table)
    assert [len(s.runs) for s in context.scopes] == [4, 4]
    assert all(s.events is None for s in context.scopes)
    for single_index, single in enumerate(kfold.config.single_runs()):
        scope, run = context.scope_of(single_index)
        assert scope.key == single.scopes[0].kind
        assert run.run_id == kfold.run_ids[single_index]
        assert run.parameters["fold"] == getattr(single.sample, "fold", None)
    with pytest.raises(InconsistentRunsError, match="no single run 8"):
        context.scope_of(8)


def test_the_drift_guard_on_the_kfold_store(kfold: KFold) -> None:
    """The core's drift guard on this real k = 2 store (MAR-151)."""

    class Tampered(ResultStore):
        def read(self, table: str, *, run_ids: Any = None) -> pd.DataFrame:  # noqa: ANN401
            frame = super().read(table, run_ids=run_ids)
            if table == "payouts":
                frame = frame.copy()
                frame.loc[frame.index[-1], "value"] += 7.0
            return frame

    with pytest.raises(FoldDriftError, match="drift guard"):
        pooled_of(kfold, Tampered(kfold.store.root))


def test_the_figures_command_draws_a_kfold_config(
    kfold: KFold, capsys: pytest.CaptureFixture[str]
) -> None:
    out_dir = kfold.config.output.directory / "figures"
    code = cli.main(["figures", str(kfold.path)])
    stdout = capsys.readouterr().out
    assert code == cli.ExitCode.OK
    assert (
        "pooled k-fold KPIs (k = 2): 4 of 4 scope x objective pooled over every "
        "fold's test block; B = 100, level 0.9" in stdout
    )
    assert "wrote   kpi_heatmap_cvar_uncovered.png" in stdout
    assert "skipped exceedance_portfolio: k-fold config" in stdout
    assert (out_dir / "performance_overview.png").is_file()
    overview = pd.read_csv(out_dir / "performance_overview.csv")
    assert set(overview["eval_split"]) == {"pooled"}
