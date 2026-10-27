"""Tests of the figure set of the ``figures`` command (MAR-110)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import pytest
import yaml

from parametric_insurance_design import cli
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    load_config,
)
from parametric_insurance_design.experiment.runner import (
    load_input,
    run_config,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design_viz.command import (
    FIGURE_SETS,
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


# -- k-fold configs: refused up front (MAR-142) -----------------------------------


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
        output={"directory": str(directory / "results")},
    )
    path = directory / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    config = load_config(path)
    run_config(config)
    checksum = load_input(config).checksum
    run_ids = tuple(run_key(config_hash(s), checksum) for s in config.single_runs())
    return KFold(path, config, ResultStore(config.output.directory), run_ids)


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


def test_a_kfold_config_is_refused_before_any_figure_set(
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
        assert "refuses k-fold configs (MAR-142)" in message
        assert "(MAR-23)" in message
        assert "holdout config" in message
    assert called == []  # no figure set ran
    assert not out_dir.exists()  # nothing written
    # not the misleading payout-figure error of a fold grouped as an objective
    assert "each objective once" not in message
    assert issubclass(KFoldRunsError, InconsistentRunsError)
    # the refusal is of the config: a store holding the runs is not read first
    with pytest.raises(KFoldRunsError):
        write_figures(kfold.config, (), store=toy.store, out_dir=out_dir)
    assert not out_dir.exists()


def test_the_figures_command_refuses_a_kfold_config(
    kfold: KFold, caplog: pytest.LogCaptureFixture
) -> None:
    out_dir = kfold.config.output.directory / "figures"
    with caplog.at_level(logging.ERROR, logger="parametric_insurance_design"):
        code = cli.main(["figures", str(kfold.path)])
    assert code == cli.ExitCode.INPUT_ERROR
    assert "KFoldRunsError: config 'viz-toy' has a k-fold sample (k=2)" in caplog.text
    assert "(MAR-23)" in caplog.text
    assert not out_dir.exists()
