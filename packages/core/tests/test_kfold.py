"""Pooled k-fold out-of-sample KPIs (MAR-151): ``experiment/kfold.py``.

Every test reads a real k = 2 store written by the runner (a run per scope x
objective x fold), as the viz ``kfold`` fixture builds one. The pooled values
are checked against the stored per-fold KPIs: the pooled expectations are the
fold expectations weighted by each block's share of the measure, the pooled
VaR lies between the fold VaRs (a mixture's quantile) and the pooled CVaR is
at least the weighted mean of the fold CVaRs (CVaR is concave in the
distribution).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
import pytest

from parametric_insurance_design import splits
from parametric_insurance_design.basis import outcome_measure
from parametric_insurance_design.bootstrap import (
    BootstrapError,
    kpi_replicates,
    percentile_interval,
    premium_replicates,
    resample_years,
)
from parametric_insurance_design.evaluate import var_cvar
from parametric_insurance_design.eventset import (
    EventSet,
    EventSetMetadata,
    HazardSource,
    IndexDefinition,
    LossDefinition,
    Provenance,
)
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    parse_config,
)
from parametric_insurance_design.experiment.kfold import (
    POOLED_COLUMNS,
    POOLED_KPIS,
    POOLED_SPLIT,
    FoldDriftError,
    PooledKFoldError,
    PooledKpis,
    pooled_designs,
    pooled_difference,
    pooled_kpis,
)
from parametric_insurance_design.experiment.runner import (
    load_input,
    prepare_eventset,
    run_config,
    run_key,
)
from parametric_insurance_design.experiment.store import ResultStore
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.records import KpiName

N_EVENTS = 60
N_YEARS = 60
SEED = 11
N_BOOTSTRAP = 200


def make_eventset() -> EventSet:
    """60 events at three locations; loss grows with the index, plus noise."""
    rng = np.random.default_rng(20261028)
    base = rng.uniform(5.0, 75.0, size=N_EVENTS)
    index = np.clip(base[:, None] + rng.normal(0.0, 4.0, (N_EVENTS, 3)), 0.0, None)
    values = np.array([100.0, 60.0, 30.0])
    damage = np.clip((index - 20.0) / 50.0, 0.0, 1.0) ** 2
    loss = damage * values * rng.uniform(0.7, 1.3, (N_EVENTS, 3))
    events = pd.DataFrame(
        {
            "event_id": [f"ev{i}" for i in range(N_EVENTS)],
            "year": np.arange(N_EVENTS) % N_YEARS,
            "rate": np.full(N_EVENTS, 1 / N_YEARS),
            "draw_id": np.zeros(N_EVENTS, dtype=int),
            "scenario_id": ["toy"] * N_EVENTS,
        }
    )
    locations = pd.DataFrame(
        {
            "location_id": ["A1", "A2", "A3"],
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
            producer="core kfold tests",
            producer_version="0",
            created_at=datetime(2026, 10, 28, tzinfo=UTC),
        ),
        licence="CC0-1.0",
    )
    return EventSet(
        events=events, locations=locations, index=index, loss=loss, metadata=metadata
    )


def config_dict(directory: Path, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    data: dict[str, Any] = {
        "schema_version": 1,
        "name": "kfold-toy",
        "eventset": {"path": str(directory / "eventset")},
        "threshold": {"value": 20.0, "column": "index"},
        "basis": "event_conditional",
        "payout": {"attachment": 20.0, "limit": 70.0, "n_bins": 5},
        "scopes": [
            {"kind": "individual"},
            {
                "kind": "cluster",
                "n_clusters": 2,
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
            },
            {"kind": "portfolio"},
        ],
        "objectives": [
            {"kind": "mse"},
            {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.9},
        ],
        "constraints": [{"kind": "budget", "loading": 1.0}],
        "evaluation": {"beta": 0.9},
        "sample": {"kind": "kfold", "k": 2},
        "bootstrap": {"seed": SEED, "n_bootstrap": N_BOOTSTRAP},
        "output": {"directory": str(directory / "results")},
    }
    data.update(changes)
    return data


@dataclass(frozen=True)
class KFold:
    """A k-fold config, its store and what the figures command passes."""

    config: ExperimentConfig
    store: ResultStore
    eventset: EventSet  # prepared
    run_ids: tuple[str, ...]

    def pooled(self) -> PooledKpis:
        return pooled_kpis(self.config, self.store, self.eventset, self.run_ids)


def build(directory: Path, **changes: Any) -> KFold:  # noqa: ANN401
    directory.mkdir(parents=True, exist_ok=True)
    if not (directory / "eventset").exists():
        make_eventset().to_parquet(directory / "eventset")
    config = parse_config(config_dict(directory, **changes))
    run_config(config)
    data = load_input(config)
    run_ids = tuple(
        run_key(config_hash(s), data.checksum) for s in config.single_runs()
    )
    return KFold(
        config=config,
        store=ResultStore(config.output.directory),
        eventset=prepare_eventset(config, data.eventset),
        run_ids=run_ids,
    )


@pytest.fixture(scope="module")
def kfold(tmp_path_factory: pytest.TempPathFactory) -> KFold:
    """A real k = 2 store: 3 scopes x 2 objectives x 2 folds, bootstrapped."""
    return build(tmp_path_factory.mktemp("kfold"))


@pytest.fixture(scope="module")
def annual(tmp_path_factory: pytest.TempPathFactory) -> KFold:
    """The same on the annual basis (years without rows are outcomes)."""
    return build(
        tmp_path_factory.mktemp("annual"),
        basis="annual",
        scopes=[{"kind": "portfolio"}],
    )


@pytest.fixture(scope="module")
def loaded(tmp_path_factory: pytest.TempPathFactory) -> KFold:
    """A portfolio-scope k = 2 store priced with a cost-of-capital load."""
    return build(
        tmp_path_factory.mktemp("loaded"),
        scopes=[{"kind": "portfolio"}],
        pricing={"kind": "cost_of_capital", "rate": 0.3, "q": 0.95},
    )


def stored_test(v: KFold) -> pd.DataFrame:
    """The stored portfolio test rows of every fold run."""
    kpis = v.store.read("kpis", run_ids=v.run_ids)
    keep = (kpis["eval_split"] == "test") & (kpis["level"] == "portfolio")
    return where(kpis, keep).reset_index(drop=True)


def where(frame: pd.DataFrame, mask: object) -> pd.DataFrame:
    """The rows of ``frame`` where ``mask`` is true."""
    return cast(pd.DataFrame, frame.loc[np.asarray(mask, dtype=bool)])


def kpi_value(frame: pd.DataFrame, run_id: str, kpi: str) -> float:
    """The value of one KPI row of one run."""
    rows = where(frame, (frame["run_id"] == run_id) & (frame["kpi"] == kpi))
    return float(rows["value"].iloc[0])


def block_weights(v: KFold) -> np.ndarray:
    """Each test block's share of the pooled measure."""
    eventset = v.eventset
    samples = splits.year_block_kfold(eventset, k=2)
    full = Sample.full(eventset)
    measure = outcome_measure(eventset, v.config.basis, years=full.years)
    p = measure.probability / measure.probability.sum()
    weights = []
    for _, test in samples:
        if v.config.basis == "annual":
            weights.append(test.years.size / full.years.size)
        else:
            weights.append(float(p[measure.outcome_of_row[test.rows]].sum()))
    return np.asarray(weights)


# -- the table -----------------------------------------------------------------


def test_one_pooled_row_per_design_and_kpi(kfold: KFold) -> None:
    pooled = kfold.pooled()
    table = pooled.table
    assert list(table.columns) == list(POOLED_COLUMNS)
    assert pooled.k == 2
    assert pooled.failed == ()
    designs = list(
        dict.fromkeys(zip(table["scope_position"], table["objective"], strict=True))
    )
    assert designs == [(i, o) for i in range(3) for o in ("mse", "weighted_cvar")]
    assert len(table) == 6 * len(POOLED_KPIS)
    assert set(table["scope"]) == {"individual", "cluster", "portfolio"}
    assert set(table["eval_split"]) == {POOLED_SPLIT}
    assert set(table["level"]) == {"portfolio"}
    assert set(table["subject_id"]) == {"portfolio"}
    assert set(table["k"]) == {2}
    assert set(table["n_years"]) == {N_YEARS}
    assert set(table["basis"]) == {"event_conditional"}
    # individual: several design problems ("*"); joint scopes: "portfolio"
    problem = table.groupby("scope")["problem_id"].unique()
    assert problem["individual"].tolist() == ["*"]
    assert problem["cluster"].tolist() == ["portfolio"]
    # the run ids of each design are its two folds, in fold order
    singles = kfold.config.single_runs()
    for position, objective in designs:
        rows = where(
            table,
            (table["scope_position"] == position) & (table["objective"] == objective),
        )
        (ids,) = set(rows["run_ids"])
        folds = [
            (getattr(s.sample, "fold", None), run_id)
            for s, run_id in zip(singles, kfold.run_ids, strict=True)
            if s.scopes[0] == kfold.config.scopes[position]
            and s.objectives[0].kind == objective
        ]
        assert [f for f, _ in folds] == [0, 1]
        assert ids == ";".join(run_id for _, run_id in folds)
    beta_rows = table["kpi"].isin(["var_uncovered", "cvar_uncovered"])
    assert np.all(table.loc[beta_rows, "beta"] == 0.9)
    assert table.loc[~beta_rows, "beta"].isna().all()


@pytest.mark.parametrize("variant", ["kfold", "annual"])
def test_pooled_expectations_weight_the_folds(
    variant: str, request: pytest.FixtureRequest
) -> None:
    v: KFold = request.getfixturevalue(variant)
    table = v.pooled().table
    stored = stored_test(v)
    weights = block_weights(v)
    assert weights.sum() == pytest.approx(1.0)
    for ids, rows in table.groupby("run_ids", sort=False):
        fold_ids = str(ids).split(";")
        for kpi in ("expected_loss", "expected_payout", "expected_uncovered"):
            fold_values = [kpi_value(stored, run_id, kpi) for run_id in fold_ids]
            pooled = float(where(rows, rows["kpi"] == kpi)["value"].iloc[0])
            assert pooled == pytest.approx(float(weights @ fold_values), rel=1e-9)


def test_pooled_tail_kpis_are_those_of_the_mixture(kfold: KFold) -> None:
    table = kfold.pooled().table
    stored = stored_test(kfold)
    weights = block_weights(kfold)
    for ids, rows in table.groupby("run_ids", sort=False):
        fold_ids = str(ids).split(";")

        def folds(kpi: str, fold_ids: list[str] = fold_ids) -> np.ndarray:
            return np.array([kpi_value(stored, r, kpi) for r in fold_ids])

        def pooled(kpi: str, rows: pd.DataFrame = rows) -> float:
            return float(where(rows, rows["kpi"] == kpi)["value"].iloc[0])

        var = folds("var_uncovered")
        assert var.min() - 1e-9 <= pooled("var_uncovered") <= var.max() + 1e-9
        # CVaR is concave in the distribution: the mean of the fold CVaRs
        # understates the pooled CVaR (the rejected rule).
        assert (
            pooled("cvar_uncovered") >= float(weights @ folds("cvar_uncovered")) - 1e-9
        )


def test_pooled_payout_is_each_folds_design_on_its_test_block(kfold: KFold) -> None:
    designs, failed = pooled_designs(
        kfold.config, kfold.store, kfold.eventset, kfold.run_ids
    )
    assert failed == ()
    assert len(designs) == 6
    samples = splits.year_block_kfold(kfold.eventset, k=2)
    for design in designs:
        assert np.all(np.isfinite(design.payout))
        assert design.payout.shape == (kfold.eventset.n_rows,)
        for f, (_, test) in enumerate(samples):
            assert np.all(design.fold[test.rows] == f)
        np.testing.assert_allclose(design.loss, kfold.eventset.loss.sum(axis=1))
    # the two objectives' designs differ (the payout is not shared by mistake)
    by_key = {(d.scope_position, d.objective): d for d in designs}
    assert not np.array_equal(
        by_key[(2, "mse")].payout, by_key[(2, "weighted_cvar")].payout
    )


# -- intervals: one resample, paired -------------------------------------------


def test_intervals_come_from_one_shared_resample(kfold: KFold) -> None:
    pooled = kfold.pooled()
    assert pooled.resample is not None
    assert pooled.replicates is not None
    assert pooled.level == 0.9
    expected = resample_years(
        np.arange(N_YEARS), N_BOOTSTRAP, np.random.default_rng(SEED)
    )
    assert pooled.resample.same_as(expected)
    assert pooled.replicates.shape == (len(pooled.table), N_BOOTSTRAP)
    designs, _ = pooled_designs(
        kfold.config, kfold.store, kfold.eventset, kfold.run_ids
    )
    full = Sample.full(kfold.eventset)
    measure = outcome_measure(kfold.eventset, kfold.config.basis, years=full.years)
    years = kfold.eventset.events["year"].to_numpy()
    pricing = kfold.config.to_components().pricing
    table = pooled.table
    for design in designs:
        reps = kpi_replicates(
            design.loss, design.payout, measure, years, expected, beta=0.9
        )
        reps[KpiName.PREMIUM] = premium_replicates(
            design.payout, measure, years, expected, pricing
        )
        mask = (
            (table["scope_position"] == design.scope_position)
            & (table["objective"] == design.objective)
        ).to_numpy()
        for position in np.flatnonzero(mask):
            row: dict[str, Any] = table.iloc[int(position)].to_dict()
            kpi = KpiName(row["kpi"])
            np.testing.assert_array_equal(pooled.replicates[position], reps[kpi])
            low, high = percentile_interval(reps[kpi], 0.9)
            if np.isnan(low):
                assert np.isnan(row["ci_low"])
            else:
                assert (row["ci_low"], row["ci_high"]) == (low, high)
            assert row["ci_level"] == 0.9
            assert row["n_bootstrap"] == N_BOOTSTRAP
    # the pooled tail intervals are proper intervals
    cvar = where(table, table["kpi"] == "cvar_uncovered")
    assert np.all(cvar["ci_low"] <= cvar["ci_high"])
    # every row is bootstrapped, the premium included (MAR-153)
    assert bool(table["ci_level"].notna().all())
    assert bool(table["n_bootstrap"].notna().all())
    assert pooled.n_undefined.columns.tolist() == [
        "scope_position",
        "scope",
        "objective",
        "kpi",
        "n_undefined",
    ]


def premium_and_payout_rows(pooled: PooledKpis) -> list[tuple[int, int, int, str]]:
    """Per design: positions of its premium and expected payout rows, its key."""
    table = pooled.table
    position = table["scope_position"].to_numpy()
    objective = table["objective"].to_numpy()
    kpi = table["kpi"].to_numpy()
    designs = dict.fromkeys(zip(position.tolist(), objective.tolist(), strict=True))
    out: list[tuple[int, int, int, str]] = []
    for p, o in designs:
        mine = (position == p) & (objective == o)
        (premium,) = np.flatnonzero(mine & (kpi == "premium"))
        (payout,) = np.flatnonzero(mine & (kpi == "expected_payout"))
        out.append((int(premium), int(payout), int(p), str(o)))
    return out


@pytest.mark.parametrize("variant", ["kfold", "loaded"])
def test_pooled_premium_has_an_interval_from_the_shared_resample(
    variant: str, request: pytest.FixtureRequest
) -> None:
    # MAR-153: the pooled premium is bootstrapped like the other KPIs, with
    # bootstrap.premium_replicates of the pooled payout on the one resample.
    v: KFold = request.getfixturevalue(variant)
    pooled = v.pooled()
    assert pooled.replicates is not None
    assert pooled.resample is not None
    table = pooled.table
    assert pooled.resample.same_as(
        resample_years(np.arange(N_YEARS), N_BOOTSTRAP, np.random.default_rng(SEED))
    )
    designs, _ = pooled_designs(v.config, v.store, v.eventset, v.run_ids)
    by_key = {(d.scope_position, d.objective): d for d in designs}
    full = Sample.full(v.eventset)
    measure = outcome_measure(v.eventset, v.config.basis, years=full.years)
    years = v.eventset.events["year"].to_numpy()
    pricing = v.config.to_components().pricing
    assert pooled.failed == ()
    assert len(designs) == (6 if variant == "kfold" else 2)
    rows = premium_and_payout_rows(pooled)
    assert len(rows) == len(designs)
    for premium, payout, position, objective in rows:
        row = table.iloc[premium]
        reps = pooled.replicates[premium]
        assert row["kpi"] == "premium"
        assert row["ci_level"] == 0.9
        assert row["n_bootstrap"] == N_BOOTSTRAP
        assert np.all(np.isfinite(reps))
        assert (row["ci_low"], row["ci_high"]) == percentile_interval(reps, 0.9)
        assert row["ci_low"] <= row["ci_high"]
        design = by_key[(position, objective)]
        np.testing.assert_array_equal(
            reps,
            premium_replicates(design.payout, measure, years, pooled.resample, pricing),
        )
        # the point value is the premium on the unresampled measure
        assert row["value"] == pytest.approx(
            pricing.premium_value(design.payout, measure), rel=1e-12
        )
        expected_payout = pooled.replicates[payout]
        if v.config.pricing.kind == "pure":
            # a pure premium is the expected payout, replicate by replicate
            np.testing.assert_allclose(reps, expected_payout, rtol=1e-12)
        else:
            # a loaded premium exceeds it in every replicate
            assert np.all(reps >= expected_payout - 1e-9)
            assert np.any(reps > expected_payout + 1e-9)
            # each replicate prices the payout of the concatenated years
            counts = pooled.resample.counts(0, 3)
            for b in range(3):
                weight = counts[b][np.searchsorted(pooled.resample.years, years)]
                p = measure.probability[measure.outcome_of_row] * weight
                p = p / p.sum()
                concatenated = 0.7 * float(p @ design.payout) + 0.3 * float(
                    var_cvar(design.payout, p, 0.95)[1]
                )
                assert reps[b] == pytest.approx(concatenated, rel=1e-9)


def test_pooled_kpis_are_deterministic(kfold: KFold) -> None:
    a, b = kfold.pooled(), kfold.pooled()
    pd.testing.assert_frame_equal(a.table, b.table)
    assert a.replicates is not None
    assert b.replicates is not None
    np.testing.assert_array_equal(a.replicates, b.replicates)


def test_paired_difference_uses_the_shared_replicates(kfold: KFold) -> None:
    pooled = kfold.pooled()
    assert pooled.replicates is not None
    diff = pooled_difference(pooled, (2, "weighted_cvar"), (2, "mse"))
    assert diff["kpi"].tolist() == [k.value for k in POOLED_KPIS]
    table = pooled.table
    for row in diff.to_dict("records"):

        def position(objective: str, kpi: str = str(row["kpi"])) -> int:
            mask = (
                (table["scope_position"] == 2)
                & (table["objective"] == objective)
                & (table["kpi"] == kpi)
            ).to_numpy()
            return int(np.flatnonzero(mask)[0])

        ia, ib = position("weighted_cvar"), position("mse")
        assert row["value_a"] == table["value"].iloc[ia]
        assert row["value_b"] == table["value"].iloc[ib]
        assert row["difference"] == pytest.approx(row["value_a"] - row["value_b"])
        low, high = percentile_interval(
            pooled.replicates[ia] - pooled.replicates[ib], 0.9
        )
        if np.isnan(low):
            assert np.isnan(row["ci_low"])
        else:
            assert (row["ci_low"], row["ci_high"]) == (low, high)
        assert row["n_bootstrap"] == N_BOOTSTRAP
    wider = pooled_difference(pooled, (2, "weighted_cvar"), (2, "mse"), level=0.99)
    cvar = where(wider, wider["kpi"] == "cvar_uncovered").iloc[0]
    narrow = where(diff, diff["kpi"] == "cvar_uncovered").iloc[0]
    assert cvar["ci_low"] <= narrow["ci_low"]
    assert cvar["ci_high"] >= narrow["ci_high"]
    with pytest.raises(PooledKFoldError, match="is not pooled"):
        pooled_difference(pooled, (5, "mse"), (2, "mse"))
    with pytest.raises(BootstrapError):
        pooled_difference(pooled, (2, "mse"), (1, "mse"), level=1.5)


def test_without_bootstrap_there_are_point_values_only(
    tmp_path_factory: pytest.TempPathFactory, kfold: KFold
) -> None:
    v = build(
        tmp_path_factory.mktemp("plain"),
        bootstrap=None,
        scopes=[{"kind": "portfolio"}],
    )
    pooled = v.pooled()
    assert pooled.replicates is None
    assert pooled.resample is None
    assert pooled.level is None
    table = pooled.table
    for column in ("ci_low", "ci_high", "ci_level", "n_bootstrap"):
        assert bool(table[column].isna().all()), column
    assert pooled.n_undefined.empty
    # the point values do not depend on the bootstrap
    with_boot = kfold.pooled().table
    with_boot = where(with_boot, with_boot["scope"] == "portfolio")
    np.testing.assert_allclose(table["value"], with_boot["value"], rtol=1e-12)
    with pytest.raises(PooledKFoldError, match="no replicates"):
        pooled_difference(pooled, (0, "weighted_cvar"), (0, "mse"))


# -- drift guard ---------------------------------------------------------------


class Tampered(ResultStore):
    """A store whose reads of one table are changed by a function."""

    def __init__(self, root: Path, table: str, change: Any) -> None:  # noqa: ANN401
        super().__init__(root)
        self._table = table
        self._change = change

    def read(self, table: str, *, run_ids: Any = None) -> pd.DataFrame:  # noqa: ANN401
        frame = super().read(table, run_ids=run_ids)
        return self._change(frame) if table == self._table else frame


def test_drift_guard_raises_on_a_changed_payout_level(kfold: KFold) -> None:
    def bump(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        last = (frame["run_id"] == kfold.run_ids[-1]) & (frame["param_index"] == 4)
        frame.loc[last, "value"] = frame.loc[last, "value"] + 5.0
        return frame

    store = Tampered(kfold.store.root, "payouts", bump)
    with pytest.raises(FoldDriftError, match=r"fold 1 .*\(drift guard\)"):
        pooled_kpis(kfold.config, store, kfold.eventset, kfold.run_ids)


def test_drift_guard_raises_on_a_changed_stored_kpi(kfold: KFold) -> None:
    def bump(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        row = (
            (frame["run_id"] == kfold.run_ids[0])
            & (frame["eval_split"] == "test")
            & (frame["level"] == "portfolio")
            & (frame["kpi"] == "cvar_uncovered")
        )
        frame.loc[row, "value"] = frame.loc[row, "value"] * (1 + 1e-6)
        return frame

    store = Tampered(kfold.store.root, "kpis", bump)
    with pytest.raises(FoldDriftError, match="'cvar_uncovered'"):
        pooled_kpis(kfold.config, store, kfold.eventset, kfold.run_ids)


def test_drift_guard_raises_on_changed_bin_edges(kfold: KFold) -> None:
    """Stored bin edges that the config's payout structure no longer gives."""

    def shift(frame: pd.DataFrame) -> pd.DataFrame:
        frame = frame.copy()
        frame["upper"] = frame["upper"] + 1.0
        return frame

    store = Tampered(kfold.store.root, "payouts", shift)
    with pytest.raises(FoldDriftError, match=r"bin edges \(upper\)"):
        pooled_kpis(kfold.config, store, kfold.eventset, kfold.run_ids)
    # a changed payout config is another run (its config hash differs)
    config = kfold.config.model_copy(
        update={"payout": kfold.config.payout.model_copy(update={"limit": 80.0})}
    )
    with pytest.raises(PooledKFoldError, match="config hash"):
        pooled_kpis(config, kfold.store, kfold.eventset, kfold.run_ids)


def test_drift_guard_needs_the_prepared_eventset(kfold: KFold) -> None:
    raw = load_input(kfold.config).eventset  # without the threshold filter
    with pytest.raises(FoldDriftError, match="prepared EventSet"):
        pooled_kpis(kfold.config, kfold.store, raw, kfold.run_ids)


# -- failures and refusals -----------------------------------------------------


def test_a_failed_fold_is_listed_not_pooled(
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    v = build(
        tmp_path_factory.mktemp("failed"),
        scopes=[
            {"kind": "portfolio"},
            {
                "kind": "cluster",
                "n_clusters": 4,
                "strategy": {"kind": "thesis_ward", "beta_tail": 0.9},
            },
        ],
        objectives=[{"kind": "mse"}],
    )
    pooled = v.pooled()
    assert set(pooled.table["scope"]) == {"portfolio"}
    (failure,) = pooled.failed
    assert (failure.scope_position, failure.scope, failure.objective) == (
        1,
        "cluster",
        "mse",
    )
    assert failure.run_ids == v.run_ids[2:]
    assert "fold 0" in failure.reason
    assert "fold 1" in failure.reason
    assert "failed for *" in failure.reason


def test_refuses_configs_that_are_not_kfold_over_every_fold(kfold: KFold) -> None:
    holdout = kfold.config.model_copy(
        update={
            "sample": parse_config(
                config_dict(Path("."), sample={"kind": "holdout"})
            ).sample
        }
    )
    with pytest.raises(PooledKFoldError, match="'holdout' sample"):
        pooled_kpis(holdout, kfold.store, kfold.eventset, kfold.run_ids)
    one_fold = kfold.config.model_copy(
        update={"sample": kfold.config.sample.model_copy(update={"fold": 1})}
    )
    with pytest.raises(PooledKFoldError, match="fixes fold 1"):
        pooled_kpis(one_fold, kfold.store, kfold.eventset, kfold.run_ids)


def test_refuses_run_ids_that_are_not_the_folds(kfold: KFold, tmp_path: Path) -> None:
    with pytest.raises(PooledKFoldError, match=r"12 single runs .* got 11 run ids"):
        pooled_kpis(kfold.config, kfold.store, kfold.eventset, kfold.run_ids[1:])
    swapped = (kfold.run_ids[1], kfold.run_ids[0], *kfold.run_ids[2:])
    with pytest.raises(PooledKFoldError, match="is not fold 0 of k=2"):
        pooled_kpis(kfold.config, kfold.store, kfold.eventset, swapped)
    objectives = (*kfold.run_ids[2:4], *kfold.run_ids[0:2], *kfold.run_ids[4:])
    with pytest.raises(PooledKFoldError, match="individual x mse"):
        pooled_kpis(kfold.config, kfold.store, kfold.eventset, objectives)
    # runs of the same scope kind and objective, but of another config
    scopes = list(kfold.config.scopes)
    scopes[1] = scopes[1].model_copy(update={"n_clusters": 3})
    other = kfold.config.model_copy(update={"scopes": tuple(scopes)})
    with pytest.raises(PooledKFoldError, match="config hash"):
        pooled_kpis(other, kfold.store, kfold.eventset, kfold.run_ids)
    missing = ("sha256:" + "0" * 64, *kfold.run_ids[1:])
    with pytest.raises(PooledKFoldError, match="1 of 12 fold runs are not in"):
        pooled_kpis(kfold.config, kfold.store, kfold.eventset, missing)


def test_the_stored_parameters_name_the_fold(kfold: KFold) -> None:
    runs = kfold.store.read("runs", run_ids=kfold.run_ids)
    for run_id, single in zip(kfold.run_ids, kfold.config.single_runs(), strict=True):
        params = json.loads(runs.loc[runs["run_id"] == run_id, "parameters"].iloc[0])
        assert params["fold"] == getattr(single.sample, "fold", None)
