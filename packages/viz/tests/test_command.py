"""Tests of the figure set of the ``figures`` command (MAR-110)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
import pytest

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
    report = write_figures(toy.config, toy.run_ids, store=toy.store, out_dir=tmp_path)
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
    report = write_figures(config, run_ids, store=toy.store, out_dir=tmp_path)
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
    assert FIGURE_SETS == (payout_figures,)


def test_scope_keys_number_repeated_kinds(toy: Fixture) -> None:
    scopes = toy.config.scopes
    config = toy.config.model_copy(update={"scopes": (scopes[1], scopes[0], scopes[1])})
    assert _scope_keys(config) == ["cluster", "individual", "cluster_2"]
