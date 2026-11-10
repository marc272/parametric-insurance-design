"""K-12 (MAR-311), question 4: ``climada.util.yearsets`` as an outcome route.

Works on small synthetic ``Impact`` objects; nothing is downloaded. It records:

1. how ``sample_events`` treats non-uniform frequencies, with and without
   replacement, against a reference (an exact compound Poisson simulation);
2. what ``correction_fac`` does to the tail metrics;
3. whether a ``sampling_vect`` can be built without the global numpy seed;
4. how to split years so that no event appears on both sides.

The event set has 2,000 events and 2 events per year. The two cases are
"uniform" (every frequency 1/1000) and "non-uniform" (frequency inversely
proportional to severity, so rare events are large). Run it with CLIMADA's
environment::

    python packages/climada/scripts/k12_yearsets.py --out yearsets.json
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Final

import numpy as np
from climada.engine import Impact
from climada.util import yearsets
from numpy.typing import NDArray

N_EVENTS: Final[int] = 2_000
LAM: Final[float] = 2.0
SEED: Final[int] = 311
REFERENCE_YEARS: Final[int] = 400_000
TAIL_LEVELS: Final[tuple[float, ...]] = (0.95, 0.99)
TRAIN_SHARE: Final[float] = 0.7


def make_event_set(*, uniform: bool) -> tuple[Impact, NDArray[np.float64]]:
    """Return an ``Impact`` of ``N_EVENTS`` events and its frequencies.

    Severity is Pareto with shape 1.5. With ``uniform=False`` an event's
    frequency is inversely proportional to its severity, so frequencies span
    several orders of magnitude and rare events are large; frequencies sum to
    ``LAM`` in both cases.
    """
    rng = np.random.default_rng(SEED)
    severity = rng.pareto(1.5, size=N_EVENTS) + 1.0
    if uniform:
        frequency = np.full(N_EVENTS, LAM / N_EVENTS)
    else:
        frequency = LAM * (1.0 / severity) / np.sum(1.0 / severity)
    event_id = 1001 + np.arange(N_EVENTS) * 7
    impact = Impact(
        event_id=event_id,
        event_name=event_id.tolist(),
        date=np.ones(N_EVENTS, dtype=int),
        frequency=frequency,
        at_event=severity,
        aai_agg=float(frequency @ severity),
    )
    return impact, frequency


def reference_annual(
    impact: Impact, frequency: NDArray[np.float64], n_years: int
) -> NDArray[np.float64]:
    """Return annual losses of an exact compound Poisson simulation.

    Each event occurs Poisson(``frequency``) times per year, independently. The
    loop is over events; every occurrence lands in a uniformly drawn year.
    """
    rng = np.random.default_rng(SEED + 1)
    annual = np.zeros(n_years)
    counts = rng.poisson(frequency * n_years)
    years = rng.integers(0, n_years, size=int(counts.sum()))
    np.add.at(annual, years, np.repeat(np.asarray(impact.at_event), counts))
    return annual


def tail_metrics(annual: NDArray[np.float64]) -> dict[str, float]:
    """Return the mean, the VaR and the CVaR of annual losses."""
    out: dict[str, float] = {"mean": float(annual.mean())}
    ordered = np.sort(annual)
    for beta in TAIL_LEVELS:
        var = float(np.quantile(ordered, beta))
        tail = ordered[ordered >= var]
        out[f"var{int(beta * 100)}"] = var
        out[f"cvar{int(beta * 100)}"] = float(tail.mean())
    return out


class WarningCatcher(logging.Handler):
    """Collect the messages of the yearsets logger."""

    def __init__(self) -> None:
        """Start with no messages."""
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        """Keep one message."""
        self.messages.append(record.getMessage())


def annual_from_vect(impact: Impact, vect: list[Any]) -> NDArray[np.float64]:
    """Return the annual losses of a sampling vector, without a correction factor."""
    return np.asarray(yearsets.compute_imp_per_year(impact, vect), dtype=float)


def rate_ratio_by_frequency(
    vect: list[Any], frequency: NDArray[np.float64], n_years: int
) -> dict[str, float]:
    """Return realised over nominal occurrence rates, by frequency decile."""
    counts = np.bincount(
        np.concatenate([np.asarray(v, dtype=int) for v in vect]),
        minlength=frequency.size,
    )
    ratio = counts / (frequency * n_years)
    order = np.argsort(frequency)
    tenth = frequency.size // 10
    return {
        "lowest_frequency_decile": float(ratio[order[:tenth]].mean()),
        "highest_frequency_decile": float(ratio[order[-tenth:]].mean()),
    }


def sampling_experiment(*, uniform: bool) -> dict[str, Any]:
    """Compare ``sample_events`` with and without replacement to the reference."""
    impact, frequency = make_event_set(uniform=uniform)
    reference = reference_annual(impact, frequency, REFERENCE_YEARS)
    out: dict[str, Any] = {
        "case": "uniform" if uniform else "non-uniform",
        "frequency_max_over_min": float(frequency.max() / frequency.min()),
        "expected_annual": float(frequency @ np.asarray(impact.at_event)),
        "reference": tail_metrics(reference),
    }
    for n_years in (200, 2_000, 20_000):
        rng = np.random.default_rng(SEED + 2)
        per_year = rng.poisson(lam=LAM, size=n_years).astype(int)
        for replacement in (False, True):
            catcher = WarningCatcher()
            logger = logging.getLogger("climada.util.yearsets")
            logger.addHandler(catcher)
            try:
                vect = yearsets.sample_events(
                    per_year,
                    frequency,
                    with_replacement=replacement,
                    seed=np.random.default_rng(SEED + 3),
                )
            finally:
                logger.removeHandler(catcher)
            annual = annual_from_vect(impact, vect)
            label = f"years={n_years},replacement={replacement}"
            factor = float(yearsets.calculate_correction_fac(annual, impact))
            out[label] = {
                **tail_metrics(annual),
                "correction_factor": factor,
                "after_correction": tail_metrics(annual * factor),
                "warned": any("frequencies" in m for m in catcher.messages),
                "rate_ratio": rate_ratio_by_frequency(vect, frequency, n_years),
            }
    return out


def correction_experiment() -> dict[str, Any]:
    """Measure the effect of ``correction_fac`` on the tail metrics over replicates."""
    impact, frequency = make_event_set(uniform=False)
    reference = tail_metrics(reference_annual(impact, frequency, REFERENCE_YEARS))
    out: dict[str, Any] = {"reference": reference}
    for n_years in (200, 1_000, 10_000):
        rows: dict[str, list[list[float]]] = {"raw": [], "corrected": []}
        factors: list[float] = []
        for replicate in range(200):
            rng = np.random.default_rng([SEED, n_years, replicate])
            per_year = rng.poisson(lam=LAM, size=n_years).astype(int)
            vect = yearsets.sample_events(
                per_year, frequency, with_replacement=True, seed=rng
            )
            annual = annual_from_vect(impact, vect)
            factor = float(yearsets.calculate_correction_fac(annual, impact))
            factors.append(factor)
            names = sorted(reference)
            rows["raw"].append([tail_metrics(annual)[k] for k in names])
            rows["corrected"].append([tail_metrics(annual * factor)[k] for k in names])
        names = sorted(reference)
        truth = np.array([reference[k] for k in names])
        entry: dict[str, Any] = {
            "correction_factor_p05_p50_p95": np.quantile(
                factors, [0.05, 0.5, 0.95]
            ).tolist()
        }
        for key, values in rows.items():
            errors = np.array(values) / truth - 1.0
            entry[key] = {
                name: {
                    "mean_relative_error": float(errors[:, i].mean()),
                    "rmse_relative": float(np.sqrt((errors[:, i] ** 2).mean())),
                }
                for i, name in enumerate(names)
            }
        out[f"years={n_years}"] = entry
    return out


def seeding_experiment() -> dict[str, Any]:
    """Check which yearsets calls touch the global numpy random state."""
    impact, frequency = make_event_set(uniform=False)
    out: dict[str, Any] = {}

    def state() -> tuple[Any, ...]:
        kind, key, pos, has_gauss, cached = np.random.get_state()  # noqa: NPY002
        return (kind, np.asarray(key).tobytes(), pos, has_gauss, cached)

    np.random.seed(123456)  # noqa: NPY002 (only to detect changes to the global state)
    before = state()
    yearsets.sample_from_poisson(10, LAM, seed=7)
    out["sample_from_poisson_with_seed_changes_global_state"] = state() != before

    np.random.seed(123456)  # noqa: NPY002 (only to detect changes to the global state)
    before = state()
    yearsets.sample_from_poisson(10, LAM, seed=None)
    out["sample_from_poisson_without_seed_consumes_global_state"] = state() != before

    np.random.seed(123456)  # noqa: NPY002 (only to detect changes to the global state)
    before = state()
    rng = np.random.default_rng(SEED)
    per_year = rng.poisson(lam=LAM, size=200).astype(int)
    vect = yearsets.sample_events(per_year, frequency, with_replacement=True, seed=rng)
    yimp = yearsets.impact_yearset_from_sampling_vect(
        impact, list(range(2000, 2200)), vect, correction_fac=False
    )
    out["own_generator_route_leaves_global_state"] = state() == before
    out["consuming_sampling_vect_matches"] = bool(
        np.array_equal(np.asarray(yimp.at_event), annual_from_vect(impact, vect))
    )
    out["sampling_vect_holds_positions_not_event_ids"] = bool(
        int(np.concatenate(vect).max()) < N_EVENTS
        and int(np.asarray(impact.event_id).min()) > N_EVENTS / 2
    )
    rng_a = np.random.default_rng(SEED)
    rng_b = np.random.default_rng(SEED)
    per_a = rng_a.poisson(lam=LAM, size=200).astype(int)
    per_b = rng_b.poisson(lam=LAM, size=200).astype(int)
    a = yearsets.sample_events(per_a, frequency, with_replacement=True, seed=rng_a)
    b = yearsets.sample_events(per_b, frequency, with_replacement=True, seed=rng_b)
    out["own_generator_route_is_reproducible"] = all(
        np.array_equal(x, y) for x, y in zip(a, b, strict=True)
    )
    return out


def leaked(train: list[Any], test: list[Any]) -> float:
    """Return the share of the test draws whose event also appears in the training."""
    train_set = np.unique(np.concatenate([np.asarray(v, dtype=int) for v in train]))
    test_arr = np.concatenate([np.asarray(v, dtype=int) for v in test])
    return float(np.mean(np.isin(test_arr, train_set)))


def split_experiment() -> dict[str, Any]:
    """Compare three ways to split sampled years into training and test years.

    Parents are blocks of 10 consecutive events: the ensemble members of one
    parent. ``naive`` splits the sampled years; ``by_event`` draws the two
    sides from disjoint pools of events; ``by_parent`` from disjoint pools of
    parents. A pool's frequencies are scaled by the inverse of its share of
    the total frequency, so that a sampled year has the same expected number
    of events as the whole set.
    """
    impact, frequency = make_event_set(uniform=False)
    parent = np.arange(N_EVENTS) // 10
    n_years = 10_000
    n_train = int(TRAIN_SHARE * n_years)
    rng = np.random.default_rng(SEED + 4)
    out: dict[str, Any] = {"n_sampled_years": n_years, "train_share": TRAIN_SHARE}

    def draw(pool: NDArray[np.int64], years: int) -> list[Any]:
        scale = frequency[pool].sum()
        per_year = rng.poisson(lam=LAM, size=years).astype(int)
        draws = yearsets.sample_events(
            per_year, frequency[pool] / scale, with_replacement=True, seed=rng
        )
        return [pool[np.asarray(v, dtype=int)] for v in draws]

    everything = np.arange(N_EVENTS)
    full = draw(everything, n_years)
    train, test = full[:n_train], full[n_train:]
    out["naive"] = {
        "leak_event": leaked(train, test),
        "leak_parent": leaked(
            [parent[np.asarray(v, dtype=int)] for v in train],
            [parent[np.asarray(v, dtype=int)] for v in test],
        ),
    }

    order = rng.permutation(N_EVENTS)
    train_pool = np.sort(order[: int(TRAIN_SHARE * N_EVENTS)])
    test_pool = np.sort(order[int(TRAIN_SHARE * N_EVENTS) :])
    train, test = draw(train_pool, n_train), draw(test_pool, n_years - n_train)
    out["by_event"] = {
        "leak_event": leaked(train, test),
        "leak_parent": leaked(
            [parent[np.asarray(v, dtype=int)] for v in train],
            [parent[np.asarray(v, dtype=int)] for v in test],
        ),
        "share_of_frequency_in_test_pool": float(
            frequency[test_pool].sum() / frequency.sum()
        ),
    }

    parents = rng.permutation(N_EVENTS // 10)
    train_parents = parents[: int(TRAIN_SHARE * parents.size)]
    in_train = np.isin(parent, train_parents)
    train_pool, test_pool = np.flatnonzero(in_train), np.flatnonzero(~in_train)
    train, test = draw(train_pool, n_train), draw(test_pool, n_years - n_train)
    annual_train = annual_from_vect(impact, train)
    annual_test = annual_from_vect(impact, test)
    out["by_parent"] = {
        "leak_event": leaked(train, test),
        "leak_parent": leaked(
            [parent[np.asarray(v, dtype=int)] for v in train],
            [parent[np.asarray(v, dtype=int)] for v in test],
        ),
        "share_of_frequency_in_test_pool": float(
            frequency[test_pool].sum() / frequency.sum()
        ),
        "train_metrics": tail_metrics(annual_train),
        "test_metrics": tail_metrics(annual_test),
    }
    return out


def main() -> None:
    """Run the experiments and write the observations as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    facts = {
        "uniform": sampling_experiment(uniform=True),
        "non_uniform": sampling_experiment(uniform=False),
        "correction_fac": correction_experiment(),
        "seeding": seeding_experiment(),
        "split": split_experiment(),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(facts, indent=1) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
