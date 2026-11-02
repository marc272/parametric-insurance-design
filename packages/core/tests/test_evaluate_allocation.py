"""Tests for per-location KPI rows under an allocation rule (MAR-100, MAR-91).

A joint design is identified only through its design problem's payout: two
designs that split the same per-row sums differently across their entities
are equally optimal for MSE. These tests check that the per-location rows
depend on the problem's payout alone, that they record their rule in the
level name, and that the rules' additivity holds. Expected values are worked
out by hand on the toy EventSet of ``conftest.py`` (A: value 100, B: value
50; rows of probability 1/3 each on the event-conditional basis).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest
from numpy.typing import ArrayLike

from parametric_insurance_design import records
from parametric_insurance_design.basis import Basis
from parametric_insurance_design.errors import (
    ComponentConfigError,
    EntityMismatchError,
)
from parametric_insurance_design.evaluate import (
    ALLOCATION_LEVELS,
    Allocation,
    evaluate_results,
    exceedance_curves,
    kpis,
)
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.interfaces import (
    Entity,
    ProblemSpec,
    Sample,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.records import KpiLevel, KpiName
from parametric_insurance_design.scopes import Cluster, Individual, Portfolio

# Bins [20, 40), [40, 60]. On the toy, both A's (10, 30, 50) and B's
# (15, 35, 55) indices fall in bins 0, 0, 1, and so does the value-weighted
# cluster index (11.7, 31.7, 51.7).
PAYOUT = StepPayout(attachment=20.0, limit=60.0, n_bins=2)

# Two portfolio designs with the same per-row sum, payout 2, 2, 13: equally
# optimal for any objective on the problem's payout (MAR-100).
SPLIT_1 = {"A": [1.0, 8.0], "B": [1.0, 5.0]}
SPLIT_2 = {"A": [2.0, 13.0], "B": [0.0, 0.0]}

LOCATION_LEVELS = (KpiLevel.LOCATION_BY_VALUE.value, KpiLevel.LOCATION_BY_LOSS.value)
ADDITIVE = (KpiName.EXPECTED_LOSS, KpiName.EXPECTED_PAYOUT)


def _result(spec: ProblemSpec, theta: ArrayLike) -> SolveResult:
    return SolveResult(
        spec=spec,
        payout_structure=PAYOUT,
        theta=np.asarray(theta, dtype=np.float64),
        status=SolveStatus.OPTIMAL,
        objective_value=0.0,
        premium=0.0,
        scale=1.0,
        solver="test",
        attempts=(),
        build_seconds=0.0,
        solve_seconds=0.0,
    )


def portfolio(split: Mapping[str, list[float]]) -> tuple[SolveResult, ...]:
    spec = ProblemSpec("portfolio", (Entity("A", ("A",)), Entity("B", ("B",))))
    return (_result(spec, [split["A"], split["B"]]),)


def individual(split: Mapping[str, list[float]]) -> tuple[SolveResult, ...]:
    return tuple(
        _result(ProblemSpec(loc, (Entity(loc, (loc,)),)), [split[loc]])
        for loc in ("A", "B")
    )


@dataclass(frozen=True)
class OneCluster:
    """Every location in cluster 1 (a ``ClusteringStrategy`` test double)."""

    def assign(self, eventset: EventSet, n_clusters: int) -> Mapping[str, int]:
        return dict.fromkeys(eventset.location_ids, 1)


def one_cluster() -> tuple[SolveResult, ...]:
    spec = ProblemSpec("portfolio", (Entity("C1", ("A", "B")),))
    return (_result(spec, [[2.0, 13.0]]),)


def with_loss(
    toy: EventSet, loss: ArrayLike, value: ArrayLike | None = None
) -> EventSet:
    """The toy with another loss matrix (and optionally other values)."""
    locations = toy.locations.copy()
    if value is not None:
        locations["value"] = np.asarray(value, dtype=np.float64)
    return EventSet(
        events=toy.events,
        locations=locations,
        index=toy.index,
        loss=np.asarray(loss, dtype=np.float64),
        metadata=toy.metadata,
    )


def value(table: pd.DataFrame, level: str, subject: str, kpi: KpiName) -> float:
    row = table.loc[
        (table["level"] == level)
        & (table["subject_id"] == subject)
        & (table["kpi"] == kpi.value)
    ]
    assert len(row) == 1
    return float(row["value"].to_numpy()[0])


def rows(table: pd.DataFrame, levels: tuple[str, ...]) -> pd.DataFrame:
    out = table.loc[table["level"].isin(levels)]
    return out.sort_values(["level", "subject_id", "kpi"]).reset_index(drop=True)


def run_kpis(
    eventset: EventSet,
    scope: object,
    results: tuple[SolveResult, ...],
    allocation: Allocation | str,
    basis: Basis = Basis.EVENT_CONDITIONAL,
) -> pd.DataFrame:
    return kpis(
        eventset,
        scope,  # type: ignore[arg-type]
        results,
        basis=basis,
        beta=0.5,
        run_id="r1",
        allocation=allocation,
    )


# --------------------------------------------------------------------------
# The default and the rule names
# --------------------------------------------------------------------------


def test_default_writes_no_location_rows(toy_eventset: EventSet) -> None:
    default = kpis(
        toy_eventset,
        Portfolio(),
        portfolio(SPLIT_1),
        basis=Basis.EVENT_CONDITIONAL,
        beta=0.5,
        run_id="r1",
    )
    explicit = run_kpis(toy_eventset, Portfolio(), portfolio(SPLIT_1), "none")
    pd.testing.assert_frame_equal(default, explicit)
    assert set(default["level"]) == {"entity", "problem", "portfolio"}


@pytest.mark.parametrize(
    "allocation", ["value", "loss", Allocation.LOSS], ids=["value", "loss", "enum"]
)
def test_location_rows_record_their_rule_in_the_level(
    toy_eventset: EventSet, allocation: str
) -> None:
    table = run_kpis(toy_eventset, Portfolio(), portfolio(SPLIT_1), allocation)
    records.KPIS.validate(table)
    level = ALLOCATION_LEVELS[Allocation(allocation)].value
    assert level == f"location_by_{Allocation(allocation).value}"
    located = table.loc[table["level"] == level]
    # Two locations, the eight KPIs each, no premium; nothing at "location".
    assert sorted(set(located["subject_id"])) == ["A", "B"]
    assert len(located) == 2 * 8
    assert set(located["kpi"]) == set(KpiName) - {KpiName.PREMIUM}
    assert np.all(located["problem_id"] == "portfolio")
    assert KpiLevel.LOCATION.value not in set(table["level"])
    # The other rows are the default table's.
    default = run_kpis(toy_eventset, Portfolio(), portfolio(SPLIT_1), "none")
    pd.testing.assert_frame_equal(
        table.loc[table["level"] != level].reset_index(drop=True), default
    )


@pytest.mark.parametrize("allocation", ["entity", "Value", "", None, 1])
def test_unknown_allocation_raises(toy_eventset: EventSet, allocation: object) -> None:
    with pytest.raises(ComponentConfigError, match="allocation must be one of"):
        run_kpis(toy_eventset, Portfolio(), portfolio(SPLIT_1), allocation)  # type: ignore[arg-type]
    with pytest.raises(ComponentConfigError, match="allocation must be one of"):
        exceedance_curves(
            toy_eventset,
            Portfolio(),
            portfolio(SPLIT_1),
            basis=Basis.EVENT_CONDITIONAL,
            run_id="r1",
            allocation=allocation,  # type: ignore[arg-type]
        )


def test_premium_stays_at_the_problem_and_portfolio_levels(
    toy_eventset: EventSet,
) -> None:
    table = kpis(
        toy_eventset,
        Portfolio(),
        portfolio(SPLIT_1),
        basis=Basis.EVENT_CONDITIONAL,
        beta=0.5,
        run_id="r1",
        pricing=PurePremium(),
        allocation="value",
    )
    premium = table.loc[table["kpi"] == KpiName.PREMIUM.value]
    assert set(premium["level"]) == {"problem", "portfolio"}


# --------------------------------------------------------------------------
# The rules, by hand
# --------------------------------------------------------------------------


def test_value_rule_by_hand(toy_eventset: EventSet) -> None:
    # Problem payout 2, 2, 13; shares 2/3 (A, value 100) and 1/3 (B, 50).
    # A: payout 4/3, 4/3, 26/3 against loss 0, 4, 10; uncovered 0, 8/3, 4/3.
    # B: payout 2/3, 2/3, 13/3 against loss 1, 2, 6; uncovered 1/3, 4/3, 5/3.
    table = run_kpis(toy_eventset, Portfolio(), portfolio(SPLIT_1), "value")
    level = "location_by_value"
    assert value(table, level, "A", KpiName.EXPECTED_PAYOUT) == pytest.approx(34 / 9)
    assert value(table, level, "A", KpiName.EXPECTED_UNCOVERED) == pytest.approx(4 / 3)
    assert value(table, level, "A", KpiName.VAR_UNCOVERED) == pytest.approx(4 / 3)
    assert value(table, level, "B", KpiName.EXPECTED_PAYOUT) == pytest.approx(17 / 9)
    assert value(table, level, "B", KpiName.EXPECTED_UNCOVERED) == pytest.approx(10 / 9)
    assert value(table, level, "B", KpiName.EXPECTED_LOSS) == pytest.approx(3.0)


def test_loss_rule_by_hand_with_value_shares_where_nothing_is_lost(
    toy_eventset: EventSet,
) -> None:
    # Row ev1 has no loss: value shares 2/3, 1/3 of its payout 2.
    # Rows ev2, ev3: loss shares 4/6, 2/6 and 10/16, 6/16.
    # A: payout 4/3, 4/3, 65/8 against loss 0, 4, 10; uncovered 0, 8/3, 15/8.
    # B: payout 2/3, 2/3, 39/8 against loss 0, 2, 6; uncovered 0, 4/3, 9/8.
    data = with_loss(toy_eventset, [[0.0, 0.0], [4.0, 2.0], [10.0, 6.0]])
    table = run_kpis(data, Portfolio(), portfolio(SPLIT_1), "loss")
    level = "location_by_loss"
    assert value(table, level, "A", KpiName.EXPECTED_PAYOUT) == pytest.approx(
        (4 / 3 + 4 / 3 + 65 / 8) / 3
    )
    assert value(table, level, "A", KpiName.EXPECTED_UNCOVERED) == pytest.approx(
        (8 / 3 + 15 / 8) / 3
    )
    assert value(table, level, "B", KpiName.EXPECTED_PAYOUT) == pytest.approx(
        (2 / 3 + 2 / 3 + 39 / 8) / 3
    )
    assert value(table, level, "B", KpiName.EXPECTED_UNCOVERED) == pytest.approx(
        (4 / 3 + 9 / 8) / 3
    )


def test_loss_rule_gives_every_location_of_a_row_the_same_cover_ratio(
    toy_eventset: EventSet,
) -> None:
    ev = evaluate_results(
        toy_eventset,
        Portfolio(),
        portfolio(SPLIT_1),
        basis=Basis.EVENT_CONDITIONAL,
        allocation="loss",
    )
    located = [s for s in ev.subjects if s.level is KpiLevel.LOCATION_BY_LOSS]
    (problem,) = [s for s in ev.subjects if s.level is KpiLevel.PROBLEM]
    ratio = problem.payout / problem.loss
    for s in located:
        np.testing.assert_allclose(s.payout, ratio * s.loss, rtol=1e-15)


# --------------------------------------------------------------------------
# What the rows depend on
# --------------------------------------------------------------------------


@pytest.mark.parametrize("basis", list(Basis))
@pytest.mark.parametrize("allocation", ["value", "loss"])
def test_location_rows_do_not_depend_on_the_split_across_entities(
    toy_eventset: EventSet, basis: Basis, allocation: str
) -> None:
    # MAR-100: two equally optimal portfolio designs.
    one = run_kpis(toy_eventset, Portfolio(), portfolio(SPLIT_1), allocation, basis)
    two = run_kpis(toy_eventset, Portfolio(), portfolio(SPLIT_2), allocation, basis)
    # The entity rows (the solver's split) differ ...
    assert not np.allclose(
        rows(one, ("entity",))["value"].fillna(-1.0),
        rows(two, ("entity",))["value"].fillna(-1.0),
    )
    # ... the problem, portfolio and location rows don't.
    joint = ("problem", "portfolio", *LOCATION_LEVELS)
    pd.testing.assert_frame_equal(rows(one, joint), rows(two, joint))


@pytest.mark.parametrize("allocation", ["value", "loss"])
def test_location_rows_depend_on_the_problem_payout_only(
    toy_eventset: EventSet, allocation: str
) -> None:
    # One cluster of A and B paying 2, 2, 13: the same problem payout as the
    # portfolio designs, through another entity structure and index.
    cluster = run_kpis(
        toy_eventset, Cluster(OneCluster(), 1), one_cluster(), allocation
    )
    port = run_kpis(toy_eventset, Portfolio(), portfolio(SPLIT_1), allocation)
    pd.testing.assert_frame_equal(
        rows(cluster, LOCATION_LEVELS), rows(port, LOCATION_LEVELS)
    )


@pytest.mark.parametrize("basis", list(Basis))
@pytest.mark.parametrize("allocation", ["value", "loss"])
def test_individual_location_rows_equal_entity_rows(
    toy_eventset: EventSet, basis: Basis, allocation: str
) -> None:
    # One location per problem gets its problem's whole payout, also with
    # value 0 at a location (no value shares needed).
    data = with_loss(toy_eventset, [[0.0, 0.0], [4.0, 2.0], [10.0, 6.0]], [0.0, 0.0])
    table = run_kpis(data, Individual(), individual(SPLIT_1), allocation, basis)
    level = ALLOCATION_LEVELS[Allocation(allocation)].value
    located = rows(table, (level,)).drop(columns="level")
    entity = rows(table, ("entity",)).drop(columns="level")
    pd.testing.assert_frame_equal(located, entity)


@pytest.mark.parametrize("basis", list(Basis))
@pytest.mark.parametrize("allocation", ["value", "loss"])
def test_locations_add_up_to_their_problem(
    toy_eventset: EventSet, basis: Basis, allocation: str
) -> None:
    data = with_loss(toy_eventset, [[0.0, 0.0], [4.0, 2.0], [10.0, 6.0]])
    for scope, results in (
        (Portfolio(), portfolio(SPLIT_1)),
        (Cluster(OneCluster(), 1), one_cluster()),
    ):
        table = run_kpis(data, scope, results, allocation, basis)
        level = ALLOCATION_LEVELS[Allocation(allocation)].value
        additive = (
            (*ADDITIVE, KpiName.EXPECTED_UNCOVERED)
            if allocation == "loss"
            else ADDITIVE
        )
        for kpi in additive:
            located = table.loc[(table["level"] == level) & (table["kpi"] == kpi)]
            assert located["value"].sum() == pytest.approx(
                value(table, "problem", "portfolio", kpi), rel=1e-12
            )


def test_value_rule_uncovered_loss_is_not_additive(toy_eventset: EventSet) -> None:
    # Over-payment at A offsets B's shortfall in the problem, not per
    # location: E[U] of the locations (4/3 + 10/9) exceeds the problem's.
    table = run_kpis(toy_eventset, Portfolio(), portfolio(SPLIT_1), "value")
    located = table.loc[
        (table["level"] == "location_by_value")
        & (table["kpi"] == KpiName.EXPECTED_UNCOVERED.value)
    ]
    problem = value(table, "problem", "portfolio", KpiName.EXPECTED_UNCOVERED)
    assert located["value"].sum() == pytest.approx(4 / 3 + 10 / 9)
    assert located["value"].sum() > problem


def test_out_of_sample_allocates_on_the_sample_rows(toy_eventset: EventSet) -> None:
    # Rows ev2 and ev3 only: A's payout 4/3, 26/3, mean 5.
    test = Sample("test", rows=np.array([False, True, True]), years=np.array([1, 2]))
    table = kpis(
        toy_eventset,
        Portfolio(),
        portfolio(SPLIT_1),
        basis=Basis.EVENT_CONDITIONAL,
        beta=0.5,
        run_id="r1",
        sample=test,
        allocation="value",
    )
    level = "location_by_value"
    assert value(table, level, "A", KpiName.EXPECTED_PAYOUT) == pytest.approx(5.0)
    assert set(table["eval_split"]) == {"test"}


# --------------------------------------------------------------------------
# Failures
# --------------------------------------------------------------------------


@pytest.mark.parametrize("allocation", ["value", "loss"])
def test_joint_problem_without_values_raises(
    toy_eventset: EventSet, allocation: str
) -> None:
    data = with_loss(toy_eventset, [[0.0, 0.0], [4.0, 2.0], [10.0, 6.0]], [0.0, 0.0])
    with pytest.raises(EntityMismatchError, match="every location of the problem"):
        run_kpis(data, Portfolio(), portfolio(SPLIT_1), allocation)


def test_loss_rule_needs_no_values_where_every_row_has_a_loss(
    toy_eventset: EventSet,
) -> None:
    data = with_loss(toy_eventset, toy_eventset.loss, [0.0, 0.0])
    table = run_kpis(data, Portfolio(), portfolio(SPLIT_1), "loss")
    assert int(np.sum(np.asarray(table["level"]) == "location_by_loss")) == 2 * 8


# --------------------------------------------------------------------------
# Exceedance curves
# --------------------------------------------------------------------------


def test_exceedance_curves_of_the_value_rule(toy_eventset: EventSet) -> None:
    curves = exceedance_curves(
        toy_eventset,
        Portfolio(),
        portfolio(SPLIT_1),
        basis=Basis.EVENT_CONDITIONAL,
        run_id="r1",
        return_periods=(1.5, 3.0),
        allocation="value",
    )
    records.EXCEEDANCE.validate(curves)

    def payout(level: str, subject: str) -> np.ndarray:
        sel = curves.loc[
            (curves["level"] == level)
            & (curves["subject_id"] == subject)
            & (curves["quantity"] == "payout")
        ].sort_values("return_period")
        return sel["value"].to_numpy()

    # A fixed share scales every quantile.
    problem = payout("problem", "portfolio")
    np.testing.assert_allclose(payout("location_by_value", "A"), problem * 2 / 3)
    np.testing.assert_allclose(payout("location_by_value", "B"), problem / 3)
    default = exceedance_curves(
        toy_eventset,
        Portfolio(),
        portfolio(SPLIT_1),
        basis=Basis.EVENT_CONDITIONAL,
        run_id="r1",
        return_periods=(1.5, 3.0),
    )
    assert "location_by_value" not in set(default["level"])
