"""Tests of the result-store reader (MAR-110) on the fixture store."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.records import ALL_PROBLEMS, TABLES
from parametric_insurance_design_viz.errors import (
    EventSetMismatchError,
    IncompleteRunError,
    MissingRunError,
)
from parametric_insurance_design_viz.reader import (
    EVENT_COLUMNS,
    ResultReader,
    RunResult,
    check_eventset,
    entity_events,
)

if TYPE_CHECKING:
    from conftest import Fixture

UNKNOWN = "sha256:" + "0" * 64


def test_reads_one_run_with_every_table(toy: Fixture) -> None:
    reader = ResultReader(toy.config.output.directory)
    assert repr(reader).startswith("ResultReader(")
    assert set(toy.run_ids) <= set(reader.run_ids())
    run_id = toy.run_id("individual", "weighted_cvar")
    run = reader.run(run_id)
    assert run.run_id == run_id
    for table in (run.runs, run.entities, run.payouts, run.kpis, run.exceedance):
        assert set(table["run_id"]) == {run_id}
    assert (run.scope, run.objective) == ("individual", "weighted_cvar")
    assert run.parameters["n_bins"] == 5
    assert run.parameters["alpha"] == 0.9
    assert run.complete
    assert run.failed_problems == ()
    run.require_complete()
    assert run.manifest["run_id"] == run_id
    assert len(run.payouts) == 3 * 5  # three assets, five bins
    assert len(run.kpis) > 0


def test_reader_accepts_a_store_object(toy: Fixture) -> None:
    assert ResultReader(toy.store).store is toy.store


def test_problem_specs_rebuild_the_entities(toy: Fixture) -> None:
    reader = ResultReader(toy.store)
    individual = reader.run(toy.run_id("individual", "mse")).problem_specs()
    assert [s.problem_id for s in individual] == ["A1", "A2", "A3"]
    assert [s.entities[0].location_ids for s in individual] == [
        ("A1",),
        ("A2",),
        ("A3",),
    ]
    (cluster,) = reader.run(toy.run_id("cluster", "mse")).problem_specs()
    assert cluster.problem_id == "portfolio"
    members = [loc for e in cluster.entities for loc in e.location_ids]
    assert sorted(members) == ["A1", "A2", "A3"]
    assert [e.entity_id for e in cluster.entities] == ["C1", "C2"]
    run = reader.run(toy.run_id("portfolio", "mse"))
    assert run.entity_order() == ("A1", "A2", "A3")


def test_missing_runs_raise_with_a_hint(toy: Fixture) -> None:
    reader = ResultReader(toy.store)
    with pytest.raises(MissingRunError, match="never re-run an optimisation"):
        reader.run(UNKNOWN)
    with pytest.raises(MissingRunError, match=r"1 of 2 runs"):
        reader.runs([toy.run_ids[0], UNKNOWN])
    assert [r.run_id for r in reader.runs(toy.run_ids[:2])] == list(toy.run_ids[:2])


def test_failed_run_is_reported_not_skipped(failed: Fixture) -> None:
    run = ResultReader(failed.store).run(failed.run_id("cluster", "mse"))
    assert not run.complete
    assert run.failed_problems == (ALL_PROBLEMS,)
    assert run.payouts.empty
    with pytest.raises(IncompleteRunError, match=r"cluster x mse.*\*"):
        run.require_complete()


def test_check_eventset_against_the_manifest(toy: Fixture) -> None:
    run = ResultReader(toy.store).run(toy.run_id("portfolio", "mse"))
    check_eventset(run, toy.eventset)
    check_eventset(run, toy.eventset.content_hash())
    raw = toy.eventset.select_locations(["A1", "A2"])
    with pytest.raises(EventSetMismatchError, match="not the one"):
        check_eventset(run, raw)
    bare = RunResult(
        run_id=run.run_id,
        runs=run.runs,
        entities=run.entities,
        payouts=run.payouts,
        kpis=run.kpis,
        exceedance=run.exceedance,
        manifest={},
    )
    assert bare.prepared_eventset_hash is None
    with pytest.raises(EventSetMismatchError, match="records no prepared"):
        check_eventset(bare, toy.eventset)


def test_entity_events_are_what_the_scope_materialises(toy: Fixture) -> None:
    reader = ResultReader(toy.store)
    es = toy.eventset
    run = reader.run(toy.run_id("individual", "mse"))
    events = entity_events(es, toy.config.scopes[0].build(), run.problem_specs())
    assert tuple(events.columns) == EVENT_COLUMNS
    assert len(events) == 3 * es.n_rows
    a2 = events[events["entity_id"] == "A2"]
    j = es.location_ids.index("A2")
    np.testing.assert_array_equal(a2["index"], es.index[:, j])
    np.testing.assert_array_equal(a2["loss"], es.loss[:, j])
    np.testing.assert_array_equal(a2["rate"], es.rates)

    cluster = reader.run(toy.run_id("cluster", "mse"))
    (spec,) = cluster.problem_specs()
    events = entity_events(es, toy.config.scopes[1].build(), (spec,))
    for entity in spec.entities:
        cols = [es.location_ids.index(loc) for loc in entity.location_ids]
        rows = events[events["entity_id"] == entity.entity_id]
        np.testing.assert_allclose(rows["loss"], es.loss[:, cols].sum(axis=1))
        values = es.locations.set_index("location_id").loc[
            list(entity.location_ids), "value"
        ]
        weights = values.to_numpy() / values.sum()
        np.testing.assert_allclose(rows["index"], es.index[:, cols] @ weights)


def test_entity_events_without_specs_is_empty(toy: Fixture) -> None:
    events = entity_events(toy.eventset, toy.config.scopes[0].build(), ())
    assert events.empty
    assert tuple(events.columns) == EVENT_COLUMNS


# -- bulk reads (MAR-120) -------------------------------------------------------


def one_at_a_time(store: ResultStore, run_id: str) -> dict[str, pd.DataFrame]:
    """Each table of one run, read alone (the reader before MAR-120)."""
    return {name: store.read(name, run_ids=[run_id]) for name in TABLES}


@pytest.mark.parametrize("name", ["toy", "failed"])
def test_bulk_read_equals_the_per_run_reads(
    name: str, request: pytest.FixtureRequest
) -> None:
    fx: Fixture = request.getfixturevalue(name)
    reader = ResultReader(fx.store)
    ids = list(reversed(fx.run_ids))  # not the store's sorted order
    bulk = reader.runs(ids)
    assert [r.run_id for r in bulk] == ids
    for run in bulk:
        alone = one_at_a_time(fx.store, run.run_id)
        for table, frame in alone.items():
            pd.testing.assert_frame_equal(getattr(run, table), frame)
        assert dict(run.manifest) == fx.store.manifest(run.run_id)
    kpis = reader.kpis(ids)
    expected = pd.concat(
        [one_at_a_time(fx.store, r)["kpis"] for r in sorted(ids)], ignore_index=True
    )
    pd.testing.assert_frame_equal(kpis, expected)


def test_bulk_read_of_a_failed_run_has_empty_tables(failed: Fixture) -> None:
    run_id = failed.run_id("cluster", "mse")
    (run,) = ResultReader(failed.store).runs([run_id])
    assert run.payouts.empty
    assert list(run.payouts.columns) == list(TABLES["payouts"].column_names)
    pd.testing.assert_frame_equal(
        run.payouts, failed.store.read("payouts", run_ids=[run_id])
    )


def test_bulk_read_repeats_and_empty(toy: Fixture) -> None:
    reader = ResultReader(toy.store)
    first = toy.run_ids[0]
    a, b = reader.runs([first, first])
    assert a.run_id == b.run_id == first
    assert reader.runs([]) == ()
    assert reader.kpis([]).empty
    with pytest.raises(MissingRunError, match=r"1 of 2 runs"):
        reader.kpis([first, UNKNOWN])
