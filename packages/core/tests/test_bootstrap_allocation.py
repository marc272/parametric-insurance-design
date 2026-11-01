"""Bootstrap intervals of per-location KPI rows (MAR-217).

``bootstrap.bootstrap_kpis`` takes ``evaluate``'s ``allocation`` rule. Under
``"value"`` or ``"loss"`` its table has the per-location rows of
``evaluate.kpis`` (MAR-100) with intervals; under ``"none"`` (the default)
the table and the replicates are exactly those of a call without the
keyword. ``paired_difference`` pairs location rows of two designs of one
scope and refuses unpaired ones; with ``across_scopes=True`` it refuses them
as every non-portfolio row (MAR-179). The runner passes the config's rule.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pytest
from numpy.typing import ArrayLike, NDArray

from parametric_insurance_design import splits
from parametric_insurance_design.basis import Basis
from parametric_insurance_design.bootstrap import (
    BootstrapError,
    KpiBootstrap,
    YearResample,
    bootstrap_kpis,
    kpi_replicates,
    paired_difference,
    resample_years,
)
from parametric_insurance_design.errors import ComponentConfigError
from parametric_insurance_design.evaluate import evaluate_results, kpis
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.experiment.config import parse_config
from parametric_insurance_design.experiment.runner import run_config
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import (
    Entity,
    ProblemSpec,
    Scope,
    SolveResult,
    SolveStatus,
)
from parametric_insurance_design.payout import StepPayout
from parametric_insurance_design.pricing import PurePremium
from parametric_insurance_design.records import KpiLevel, KpiName
from parametric_insurance_design.scopes import Individual, Portfolio

N_YEARS = 40
N_BOOTSTRAP = 120
BETA = 0.9
PAYOUT = StepPayout(attachment=20.0, limit=70.0, n_bins=3)
LOCATIONS = ("A1", "A2", "A3")
LOCATION_LEVELS = {
    "value": KpiLevel.LOCATION_BY_VALUE.value,
    "loss": KpiLevel.LOCATION_BY_LOSS.value,
}
CI_COLUMNS = ["ci_low", "ci_high", "ci_level", "n_bootstrap"]


def make_eventset() -> EventSet:
    """40 events in 40 years at three locations; loss grows with the index."""
    rng = np.random.default_rng(20261101)
    base = rng.uniform(5.0, 75.0, size=N_YEARS)
    index = np.clip(base[:, None] + rng.normal(0.0, 4.0, (N_YEARS, 3)), 0.0, None)
    values = np.array([100.0, 60.0, 30.0])
    damage = np.clip((index - 20.0) / 50.0, 0.0, 1.0) ** 2
    loss = damage * values * rng.uniform(0.7, 1.3, (N_YEARS, 3))
    events = pd.DataFrame(
        {
            "event_id": [f"ev{i}" for i in range(N_YEARS)],
            "year": np.arange(N_YEARS),
            "rate": np.full(N_YEARS, 1 / N_YEARS),
            "draw_id": np.zeros(N_YEARS, dtype=int),
            "scenario_id": ["toy"] * N_YEARS,
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": list(LOCATIONS),
            "lat": [25.0, 25.5, 26.0],
            "lon": [-80.0, -80.5, -81.0],
            "value": values,
            "name": ["Asset 1", "Asset 2", "Asset 3"],
        }
    )
    metadata = EventSetMetadata(
        hazard=HazardSource(name="toy", release="1"),
        index=IndexDefinition(definition="wind at the asset", unit="m/s"),
        loss=LossDefinition(unit="USD", currency="USD"),
        n_years=N_YEARS,
        scenario="toy",
        provenance=Provenance(
            producer="core bootstrap allocation tests",
            producer_version="0",
            created_at=datetime(2026, 11, 1, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events, locations=locations, index=index, loss=loss, metadata=metadata
    )


@pytest.fixture(scope="module")
def eventset() -> EventSet:
    return make_eventset()


@pytest.fixture(scope="module")
def resample() -> YearResample:
    return resample_years(np.arange(N_YEARS), N_BOOTSTRAP, np.random.default_rng(5))


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


def portfolio(theta: ArrayLike) -> tuple[SolveResult, ...]:
    spec = ProblemSpec("portfolio", tuple(Entity(loc, (loc,)) for loc in LOCATIONS))
    return (_result(spec, theta),)


def individual(theta: ArrayLike) -> tuple[SolveResult, ...]:
    rows = np.asarray(theta, dtype=np.float64)
    return tuple(
        _result(ProblemSpec(loc, (Entity(loc, (loc,)),)), rows[[i]])
        for i, loc in enumerate(LOCATIONS)
    )


THETA_1 = [[5.0, 20.0, 60.0], [2.0, 12.0, 35.0], [1.0, 6.0, 18.0]]
THETA_2 = [[3.0, 25.0, 70.0], [3.0, 10.0, 30.0], [0.0, 5.0, 20.0]]


def boot(
    eventset: EventSet,
    scope: Scope,
    results: tuple[SolveResult, ...],
    resample: YearResample,
    run_id: str = "run",
    allocation: str = "none",
) -> KpiBootstrap:
    return bootstrap_kpis(
        eventset,
        scope,
        results,
        basis=Basis.EVENT_CONDITIONAL,
        beta=BETA,
        run_id=run_id,
        resample=resample,
        pricing=PurePremium(),
        allocation=allocation,
    )


def _mask(table: pd.DataFrame, levels: set[str]) -> NDArray[np.bool_]:
    return np.isin(table["level"].astype(str).to_numpy(), sorted(levels))


def _equal(table: pd.DataFrame, column: str, value: str) -> NDArray[np.bool_]:
    return (table[column].astype(str) == value).to_numpy()


def _col(table: pd.DataFrame, column: str) -> NDArray[np.float64]:
    return table[column].to_numpy(dtype=np.float64)


def _defined(location: pd.DataFrame) -> pd.DataFrame:
    """Location rows except the correlation (undefined in some replicates)."""
    return _rows(location, ~_equal(location, "kpi", KpiName.CORRELATION.value))


def _rows(table: pd.DataFrame, mask: np.ndarray) -> pd.DataFrame:
    return cast(pd.DataFrame, table.loc[mask]).reset_index(drop=True)


# -- bootstrap_kpis ---------------------------------------------------------------


def test_none_is_the_default(eventset: EventSet, resample: YearResample) -> None:
    results = portfolio(THETA_1)
    default = boot(eventset, Portfolio(), results, resample)
    explicit = boot(eventset, Portfolio(), results, resample, allocation="none")
    pd.testing.assert_frame_equal(default.table, explicit.table)
    np.testing.assert_array_equal(default.replicates, explicit.replicates)
    assert not _mask(default.table, set(LOCATION_LEVELS.values())).any()


@pytest.mark.parametrize("rule", ["value", "loss"])
def test_location_rows_get_intervals(
    eventset: EventSet, resample: YearResample, rule: str
) -> None:
    level = LOCATION_LEVELS[rule]
    results = portfolio(THETA_1)
    plain = boot(eventset, Portfolio(), results, resample)
    ruled = boot(eventset, Portfolio(), results, resample, allocation=rule)

    # The point values are evaluate.kpis' under the rule.
    expected = kpis(
        eventset,
        Portfolio(),
        results,
        basis=Basis.EVENT_CONDITIONAL,
        beta=BETA,
        run_id="run",
        pricing=PurePremium(),
        allocation=rule,
    )
    pd.testing.assert_frame_equal(
        ruled.table.drop(columns=CI_COLUMNS), expected.drop(columns=CI_COLUMNS)
    )

    is_location = _mask(ruled.table, {level})
    location = _rows(ruled.table, is_location)
    assert set(location["subject_id"]) == set(LOCATIONS)
    assert KpiName.PREMIUM.value not in set(location["kpi"])
    # Every row is bootstrapped; the defined location KPIs have bounds.
    assert not np.isnan(_col(ruled.table, "ci_level")).any()
    assert np.all(_col(ruled.table, "n_bootstrap") == N_BOOTSTRAP)
    defined = _defined(location)
    low, high = _col(defined, "ci_low"), _col(defined, "ci_high")
    assert not np.isnan(low).any()
    assert not np.isnan(high).any()
    assert np.all(low <= high)

    # The other rows, and their replicates, are the "none" bootstrap's.
    pd.testing.assert_frame_equal(_rows(ruled.table, ~is_location), plain.table)
    np.testing.assert_array_equal(ruled.replicates[~is_location], plain.replicates)


@pytest.mark.parametrize("rule", ["value", "loss"])
def test_location_replicates_are_kpi_replicates_of_the_allocated_payout(
    eventset: EventSet, resample: YearResample, rule: str
) -> None:
    results = portfolio(THETA_1)
    ruled = boot(eventset, Portfolio(), results, resample, allocation=rule)
    ev = evaluate_results(
        eventset,
        Portfolio(),
        results,
        basis=Basis.EVENT_CONDITIONAL,
        allocation=rule,
    )
    row_years = eventset.events["year"].to_numpy(dtype=np.int64)
    table = ruled.table
    for subject in ev.subjects:
        if subject.level.value != LOCATION_LEVELS[rule]:
            continue
        reps = kpi_replicates(
            subject.loss,
            subject.payout,
            ev.measure,
            row_years,
            resample,
            beta=BETA,
        )
        for kpi, values in reps.items():
            (i,) = np.flatnonzero(
                (
                    (table["level"].astype(str) == subject.level.value)
                    & (table["subject_id"] == subject.subject_id)
                    & (table["kpi"] == kpi.value)
                ).to_numpy()
            )
            np.testing.assert_allclose(
                ruled.replicates[i], values, rtol=1e-12, atol=1e-12
            )


def test_expected_payout_adds_up_in_every_replicate(
    eventset: EventSet, resample: YearResample
) -> None:
    ruled = boot(eventset, Portfolio(), portfolio(THETA_1), resample, allocation="loss")
    table = ruled.table
    payout = (table["kpi"] == KpiName.EXPECTED_PAYOUT.value).to_numpy()
    location = payout & _mask(table, {LOCATION_LEVELS["loss"]})
    problem = payout & _mask(table, {KpiLevel.PROBLEM.value})
    assert location.sum() == len(LOCATIONS)
    np.testing.assert_allclose(
        ruled.replicates[location].sum(axis=0),
        ruled.replicates[problem][0],
        rtol=1e-10,
    )


def test_individual_location_rows_equal_entity_rows(
    eventset: EventSet, resample: YearResample
) -> None:
    ruled = boot(
        eventset, Individual(), individual(THETA_1), resample, allocation="value"
    )
    table = ruled.table
    location = _mask(table, {LOCATION_LEVELS["value"]})
    entity = _mask(table, {KpiLevel.ENTITY.value})
    keep = ["problem_id", "subject_id", "kpi", "beta", "value", *CI_COLUMNS]
    pd.testing.assert_frame_equal(
        _rows(table, location).loc[:, keep], _rows(table, entity).loc[:, keep]
    )
    np.testing.assert_array_equal(ruled.replicates[location], ruled.replicates[entity])


def test_an_unknown_rule_raises(eventset: EventSet, resample: YearResample) -> None:
    with pytest.raises(ComponentConfigError, match="allocation must be one of"):
        boot(eventset, Portfolio(), portfolio(THETA_1), resample, allocation="bogus")


def test_a_resample_of_other_years_still_raises(eventset: EventSet) -> None:
    other = resample_years(np.arange(N_YEARS - 1), 10, np.random.default_rng(0))
    with pytest.raises(BootstrapError, match="draw it from"):
        boot(eventset, Portfolio(), portfolio(THETA_1), other, allocation="value")


def test_a_test_sample_gets_location_rows(
    eventset: EventSet,
) -> None:
    _, sample = splits.holdout(eventset, train_fraction=0.75)
    resample = resample_years(sample.years, 50, np.random.default_rng(1))
    ruled = bootstrap_kpis(
        eventset,
        Portfolio(),
        portfolio(THETA_1),
        basis=Basis.EVENT_CONDITIONAL,
        beta=BETA,
        run_id="run",
        resample=resample,
        sample=sample,
        allocation="loss",
    )
    location = _rows(ruled.table, _mask(ruled.table, {LOCATION_LEVELS["loss"]}))
    assert set(location["eval_split"]) == {"test"}
    assert set(location["subject_id"]) == set(LOCATIONS)


# -- paired_difference ------------------------------------------------------------


def test_paired_difference_pairs_location_rows(
    eventset: EventSet, resample: YearResample
) -> None:
    a = boot(
        eventset, Portfolio(), portfolio(THETA_1), resample, "a", allocation="value"
    )
    b = boot(
        eventset, Portfolio(), portfolio(THETA_2), resample, "b", allocation="value"
    )
    diff = paired_difference(a, b)
    location = _rows(diff, _equal(diff, "level", LOCATION_LEVELS["value"]))
    assert set(location["subject_id"]) == set(LOCATIONS)
    assert len(diff) == len(a.table)
    np.testing.assert_allclose(
        _col(location, "difference"),
        _col(location, "value_a") - _col(location, "value_b"),
    )


def test_paired_difference_refuses_designs_under_different_rules(
    eventset: EventSet, resample: YearResample
) -> None:
    a = boot(
        eventset, Portfolio(), portfolio(THETA_1), resample, "a", allocation="value"
    )
    b = boot(eventset, Portfolio(), portfolio(THETA_2), resample, "b")
    with pytest.raises(BootstrapError, match="no partner"):
        paired_difference(a, b)
    c = boot(
        eventset, Portfolio(), portfolio(THETA_2), resample, "c", allocation="loss"
    )
    with pytest.raises(BootstrapError, match="no partner"):
        paired_difference(a, c)


def test_across_scopes_refuses_location_rows(
    eventset: EventSet, resample: YearResample
) -> None:
    joint = boot(
        eventset, Portfolio(), portfolio(THETA_1), resample, "j", allocation="value"
    )
    alone = boot(
        eventset, Individual(), individual(THETA_2), resample, "i", allocation="value"
    )
    with pytest.raises(BootstrapError, match="portfolio-level rows only"):
        paired_difference(joint, alone, across_scopes=True)
    # portfolio_rows() drops them, and the result is the "none" result.
    plain_joint = boot(eventset, Portfolio(), portfolio(THETA_1), resample, "j")
    plain_alone = boot(eventset, Individual(), individual(THETA_2), resample, "i")
    pd.testing.assert_frame_equal(
        paired_difference(
            joint.portfolio_rows(), alone.portfolio_rows(), across_scopes=True
        ),
        paired_difference(
            plain_joint.portfolio_rows(),
            plain_alone.portfolio_rows(),
            across_scopes=True,
        ),
    )


# -- runner -----------------------------------------------------------------------


def config_dict(directory: Path, rule: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "bootstrap-allocation",
        "eventset": {"path": str(directory / "eventset")},
        "basis": "event_conditional",
        "sample": {"kind": "holdout", "train_fraction": 0.75},
        "payout": {"attachment": 20.0, "limit": 70.0, "n_bins": 3},
        "scopes": [{"kind": "individual"}, {"kind": "portfolio"}],
        "objectives": [{"kind": "mse"}],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": BETA, "allocation": rule},
        "bootstrap": {"seed": 7, "n_bootstrap": 60},
        "output": {"directory": str(directory / f"results-{rule}")},
    }


def test_runner_bootstraps_location_rows(tmp_path: Path, eventset: EventSet) -> None:
    eventset.to_parquet(tmp_path / "eventset")
    tables: dict[str, pd.DataFrame] = {}
    outcomes = {}
    for rule in ("none", "value"):
        config = parse_config(config_dict(tmp_path, rule))
        store = ResultStore(config.output.directory)
        outcomes[rule] = run_config(config, store=store)
        assert all(o.ok for o in outcomes[rule])
        tables[rule] = store.read("kpis")
        for outcome in outcomes[rule]:
            entry = store.manifest(outcome.run_id)["bootstrap"]
            assert {s["sample"] for s in entry["samples"]} == {"train", "test"}

    ruled = tables["value"]
    location = _rows(ruled, _mask(ruled, {LOCATION_LEVELS["value"]}))
    assert set(location["eval_split"]) == {"train", "test"}
    assert set(location["subject_id"]) == set(LOCATIONS)
    assert not np.isnan(_col(location, "ci_level")).any()
    assert np.all(_col(location, "n_bootstrap") == 60)
    assert not np.isnan(_col(_defined(location), "ci_low")).any()

    # Every other row, intervals included, is the "none" run's.
    for plain_run, ruled_run in zip(outcomes["none"], outcomes["value"], strict=True):
        ours = _rows(ruled, _equal(ruled, "run_id", ruled_run.run_id))
        ours = _rows(ours, ~_mask(ours, {LOCATION_LEVELS["value"]}))
        theirs = _rows(
            tables["none"], _equal(tables["none"], "run_id", plain_run.run_id)
        )
        pd.testing.assert_frame_equal(
            ours.drop(columns=["run_id"]), theirs.drop(columns=["run_id"])
        )
