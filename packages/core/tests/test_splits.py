"""Tests of the year-block splits and the KPI gap (MAR-22, SPEC §6.1)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design.errors import InputMismatchError, RecordSchemaError
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.noise import add_noise
from parametric_insurance_design.records import KPIS
from parametric_insurance_design.splits import (
    GAP_KEY,
    LeakageError,
    SplitError,
    holdout,
    kpi_gap,
    year_block_kfold,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PARITY_EVENTSET = REPO_ROOT / "parity" / "tests" / "data" / "thesis_eventset"

needs_fixture = pytest.mark.skipif(
    not PARITY_EVENTSET.is_dir(),
    reason="the parity fixture is only in a repository checkout",
)


def make_eventset(
    years: Sequence[int],
    *,
    n_years: int,
    draws: int = 1,
    event_ids: Sequence[str] | None = None,
) -> EventSet:
    """One event per entry of ``years`` (``draws`` rows each), one location."""
    ids = [f"ev{i}" for i in range(len(years))] if event_ids is None else event_ids
    rows = [
        (event_id, year, draw)
        for event_id, year in zip(ids, years, strict=True)
        for draw in range(draws)
    ]
    return from_rows(rows, n_years=n_years, draws=draws)


def from_rows(
    rows: Sequence[tuple[str, int, int]], *, n_years: int, draws: int = 1
) -> EventSet:
    """An EventSet of ``(event_id, year, draw_id)`` rows at one location."""
    n = len(rows)
    events = pd.DataFrame(
        {
            "event_id": [r[0] for r in rows],
            "year": [r[1] for r in rows],
            "rate": [1 / (n_years * draws)] * n,
            "draw_id": [r[2] for r in rows],
            "scenario_id": ["toy"] * n,
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": ["A"],
            "lat": [25.0],
            "lon": [-80.0],
            "value": [100.0],
            "name": ["Asset A"],
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name="toy", release="1"),
        index=IndexDefinition(definition="wind at the asset", unit="m/s"),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=n_years,
        scenario="toy",
        provenance=Provenance(
            producer="tests",
            producer_version="0",
            created_at=datetime(2026, 10, 27, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    values = np.linspace(20.0, 60.0, n).reshape(n, 1) if n else np.zeros((0, 1))
    return EventSet(
        events=events,
        locations=locations,
        index=values,
        loss=values / 10,
        metadata=metadata,
    )


def event_ids(eventset: EventSet, sample: Sample) -> set[str]:
    return set(eventset.events["event_id"].to_numpy()[sample.rows])


def assert_no_leakage(eventset: EventSet, samples: Sequence[Sample]) -> None:
    """No event_id in two samples; every sample selects cleanly."""
    seen: dict[str, int] = {}
    for i, sample in enumerate(samples):
        sample.select(eventset)  # refuses rows outside the sample's years
        for event_id in event_ids(eventset, sample):
            assert event_id not in seen, f"{event_id} in samples {seen[event_id]}, {i}"
            seen[event_id] = i


# -- holdout -----------------------------------------------------------------


def test_holdout_on_the_toy_eventset(toy_eventset: EventSet) -> None:
    train, test = holdout(toy_eventset)  # 0.7 * 3 years -> 2 training years
    assert (train.name, train.fold, test.name, test.fold) == ("train", 0, "test", 0)
    assert train.years.tolist() == [0, 1]
    assert test.years.tolist() == [2]
    assert train.rows.tolist() == [True, True, False]
    assert test.rows.tolist() == [False, False, True]


def test_holdout_partitions_years_and_rows_with_draws() -> None:
    # Years 2, 5 and 8 have no events; every event has four draws.
    es = make_eventset([0, 1, 1, 3, 4, 6, 7, 9], n_years=10, draws=4)
    train, test = holdout(es, train_fraction=0.7)
    assert train.years.tolist() == list(range(7))
    assert test.years.tolist() == [7, 8, 9]
    assert not (train.rows & test.rows).any()
    assert (train.rows | test.rows).all()
    assert event_ids(es, train) == {f"ev{i}" for i in range(6)}
    assert event_ids(es, test) == {"ev6", "ev7"}
    assert_no_leakage(es, [train, test])


def test_holdout_matches_the_thesis_year_range() -> None:
    # SPEC §6.1: the first 70 % of 10,000 years, stored 0 .. 6,999, train.
    es = make_eventset([0, 6_999, 7_000, 9_999], n_years=10_000, draws=13)
    train, test = holdout(es)
    assert (train.years[0], train.years[-1], train.years.size) == (0, 6_999, 7_000)
    assert (test.years[0], test.years[-1], test.years.size) == (7_000, 9_999, 3_000)
    assert event_ids(es, train) == {"ev0", "ev1"}
    assert event_ids(es, test) == {"ev2", "ev3"}


def test_holdout_floors_with_a_float_tolerance() -> None:
    es = make_eventset(list(range(100)), n_years=100)
    # 0.29 * 100 == 28.999999999999996 in floating point
    assert holdout(es, train_fraction=0.29)[0].years.size == 29
    assert holdout(es, train_fraction=0.295)[0].years.size == 29


@pytest.mark.parametrize("fraction", [0, 1, 0.0, 1.0, -0.1, 1.5, float("nan"), True])
def test_holdout_refuses_invalid_fractions(
    toy_eventset: EventSet, fraction: float
) -> None:
    with pytest.raises(SplitError, match="train_fraction"):
        holdout(toy_eventset, train_fraction=fraction)


def test_holdout_refuses_a_non_number(toy_eventset: EventSet) -> None:
    with pytest.raises(SplitError, match="train_fraction"):
        holdout(toy_eventset, train_fraction="0.5")  # type: ignore[arg-type]


@pytest.mark.parametrize("fraction", [0.1, 1 - 1e-12])
def test_holdout_needs_a_year_in_each_block(
    toy_eventset: EventSet, fraction: float
) -> None:
    with pytest.raises(SplitError, match="at least one year"):
        holdout(toy_eventset, train_fraction=fraction)


def test_holdout_refuses_an_empty_sample() -> None:
    es = make_eventset([0, 1, 2], n_years=10)  # no events in the test years
    with pytest.raises(SplitError, match=r"test sample of fold 0 .* holds no rows"):
        holdout(es)


def test_split_errors_are_input_mismatch_errors() -> None:
    assert issubclass(SplitError, InputMismatchError)
    assert issubclass(LeakageError, SplitError)


# -- leakage -----------------------------------------------------------------


def test_an_event_spanning_two_years_is_refused() -> None:
    # ev0's draws 0 and 1 lie in different years.
    es = from_rows([("ev0", 0, 0), ("ev1", 3, 0), ("ev0", 8, 1)], n_years=10)
    with pytest.raises(LeakageError, match="1 events have rows in more than one"):
        holdout(es)
    with pytest.raises(LeakageError, match="'ev0'"):
        year_block_kfold(es, k=2)


def test_no_event_id_appears_in_two_folds_with_noise_draws(
    toy_eventset: EventSet,
) -> None:
    # Acceptance (MAR-22): the leakage test, with noise copies as draw_id.
    base = make_eventset(list(range(20)) * 3, n_years=20)
    es = add_noise(
        base,
        level=0.3,
        kind="heteroscedastic",
        n_copies=7,
        rng=np.random.default_rng(1),
    )
    assert es.n_rows == 60 * 7
    folds = year_block_kfold(es, k=5)
    assert_no_leakage(es, [test for _, test in folds])
    for train, test in folds:
        assert_no_leakage(es, [train, test])
    assert_no_leakage(es, holdout(es))


@needs_fixture
def test_no_leakage_on_the_thesis_fixture() -> None:
    es = add_noise(
        EventSet.from_parquet(PARITY_EVENTSET),
        level=0.3,
        kind="heteroscedastic",
        n_copies=13,
        rng=np.random.default_rng(42),
    )
    folds = year_block_kfold(es, k=5)
    tests = [test for _, test in folds]
    assert_no_leakage(es, tests)
    assert sum(t.n_selected for t in tests) == es.n_rows
    train, test = holdout(es)
    assert_no_leakage(es, [train, test])
    assert train.n_selected + test.n_selected == es.n_rows


# -- k-fold ------------------------------------------------------------------


def test_kfold_uses_contiguous_year_blocks() -> None:
    es = make_eventset(list(range(12)), n_years=12, draws=2)
    folds = year_block_kfold(es, k=5)
    assert len(folds) == 5
    blocks = [test.years.tolist() for _, test in folds]
    assert blocks == [[0, 1, 2], [3, 4, 5], [6, 7], [8, 9], [10, 11]]
    for fold, (train, test) in enumerate(folds):
        assert (train.name, test.name) == ("train", "test")
        assert train.fold == test.fold == fold
        assert sorted([*train.years.tolist(), *test.years.tolist()]) == list(range(12))
        assert not (train.rows & test.rows).any()
        assert (train.rows | test.rows).all()
    rows = np.sum([test.rows for _, test in folds], axis=0)
    assert rows.tolist() == [1] * es.n_rows  # every row tested exactly once


def test_kfold_default_is_five_folds() -> None:
    es = make_eventset(list(range(10)), n_years=10)
    assert len(year_block_kfold(es)) == 5


@pytest.mark.parametrize("k", [1, 0, 11, True, 2.0])
def test_kfold_refuses_invalid_k(k: int) -> None:
    es = make_eventset(list(range(10)), n_years=10)
    with pytest.raises(SplitError, match="k must be an int"):
        year_block_kfold(es, k=k)


def test_kfold_refuses_a_fold_without_rows() -> None:
    es = make_eventset([0, 1, 2, 3], n_years=10)
    with pytest.raises(SplitError, match=r"test sample of fold 2 .* holds no rows"):
        year_block_kfold(es, k=5)


def test_kfold_with_k_equal_to_n_years(toy_eventset: EventSet) -> None:
    folds = year_block_kfold(toy_eventset, k=3)
    assert [test.years.tolist() for _, test in folds] == [[0], [1], [2]]
    assert [train.years.tolist() for train, _ in folds] == [[1, 2], [0, 2], [0, 1]]


# -- kpi_gap -----------------------------------------------------------------


def kpi_rows(split: str, values: Sequence[float], fold: int = 0) -> list[dict]:
    return [
        {
            "run_id": "sha256:run",
            "problem_id": "portfolio",
            "eval_split": split,
            "fold": fold,
            "basis": "event_conditional",
            "level": "portfolio",
            "subject_id": "portfolio",
            "kpi": kpi,
            "beta": 0.95,
            "value": value,
            "ci_low": None,
            "ci_high": None,
            "ci_level": None,
            "n_bootstrap": None,
        }
        for kpi, value in zip(
            ("cvar_uncovered", "expected_uncovered"), values, strict=True
        )
    ]


def test_kpi_gap_pairs_train_and_test() -> None:
    frame = KPIS.from_rows(
        kpi_rows("train", [1.0, 2.0])
        + kpi_rows("test", [1.5, 1.0])
        + kpi_rows("train", [3.0, 4.0], fold=1)
        + kpi_rows("test", [5.0, 4.0], fold=1)
        + kpi_rows("full", [9.0, 9.0])
    )
    gap = kpi_gap(frame)
    assert list(gap.columns) == [*GAP_KEY, "train", "test", "gap"]
    assert len(gap) == 4
    assert gap["fold"].tolist() == [0, 0, 1, 1]
    assert gap["train"].tolist() == [1.0, 2.0, 3.0, 4.0]
    assert gap["test"].tolist() == [1.5, 1.0, 5.0, 4.0]
    assert gap["gap"].tolist() == [0.5, -1.0, 2.0, 0.0]


def test_kpi_gap_refuses_unpaired_rows() -> None:
    frame = KPIS.from_rows(
        kpi_rows("train", [1.0, 2.0]) + kpi_rows("test", [1.5, 1.0])[:1]
    )
    with pytest.raises(InputMismatchError, match=r"1 KPI rows .* a train row"):
        kpi_gap(frame)
    frame = KPIS.from_rows(kpi_rows("test", [1.5, 1.0]))
    with pytest.raises(InputMismatchError, match=r"2 KPI rows .* a test row"):
        kpi_gap(frame)


def test_kpi_gap_validates_the_table() -> None:
    with pytest.raises(RecordSchemaError):
        kpi_gap(pd.DataFrame({"run_id": ["x"]}))


def test_kpi_gap_of_no_rows_is_empty() -> None:
    gap = kpi_gap(KPIS.empty())
    assert gap.empty
    assert list(gap.columns) == [*GAP_KEY, "train", "test", "gap"]
