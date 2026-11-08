"""K-12 (MAR-311), questions 2 and 3: the structure of CLIMADA's Data API hazards.

For one small country, reads hazards from CLIMADA's public Data API and records
the number of events, the frequencies, the dates, the event names, ``orig``, the
link between ensemble members and their parent, and the licence. It then tries
the three annual routes on each hazard: the prototype's catalogue years,
``climada.util.yearsets``, and neither. Nothing is committed: the observations
are written to ``--out``, which belongs under the git-ignored ``results/``.

Run it from a folder holding a ``climada.conf`` that points ``local_data.system``
at a git-ignored path, so that the Data API's cache stays out of the repository::

    python packages/climada/scripts/k12_data_api_facts.py --out facts.json

No credentials are needed. A dataset above ``--max-bytes`` is skipped and
recorded. The losses are a proxy with no economic meaning: the sum of the
hazard's intensity at the three centroids of largest mean intensity. They are
only there to compare the shape of the annual distribution between the routes.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import logging
import re
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import numpy as np
from climada.engine import Impact
from climada.entity import Exposures
from climada.util import yearsets
from climada.util.api_client import Client
from numpy.typing import NDArray

import petals_parametric as pm

MAX_BYTES: Final[int] = 2_000_000_000
"""Datasets above this size are not downloaded (the issue's limit, about 2 GB)."""

SAMPLED_YEARS: Final[int] = 20_000
"""Years drawn on the yearsets route."""

SEED: Final[int] = 311
"""Seed of the event draws (a seed of a local generator, never the global one)."""

MAX_EVENTS_NO_REPLACEMENT: Final[int] = 5_000
"""``sample_events`` without replacement is slow; only smaller sets run it."""

_STORM_NAME: Final[re.Pattern[str]] = re.compile(
    r".*_(?P<basin>[A-Z]{2})_1000_YEARS_(?P<file>\d+)(?:_IBTRACSDELTA)?\.txt"
    r"-(?P<year>\d+)-(?P<number>\d+)$"
)


@dataclass(frozen=True)
class Spec:
    """One dataset and the way its events are given simulation years."""

    label: str
    data_type: str
    name: str
    route: str


SPECS: Final[tuple[Spec, ...]] = (
    Spec(
        "tc_random_walk_present",
        "tropical_cyclone",
        "tropical_cyclone_10synth_tracks_150arcsec_JAM_1980_2020",
        "random_walk",
    ),
    Spec(
        "tc_random_walk_rcp45_2060",
        "tropical_cyclone",
        "tropical_cyclone_10synth_tracks_150arcsec_rcp45_JAM_2060",
        "random_walk",
    ),
    Spec(
        "tc_random_walk_rcp85_2060",
        "tropical_cyclone",
        "tropical_cyclone_10synth_tracks_150arcsec_rcp85_JAM_2060",
        "random_walk",
    ),
    Spec(
        "tc_observed",
        "tropical_cyclone",
        "tropical_cyclone_0synth_tracks_150arcsec_historical_JAM_1980_2020",
        "date",
    ),
    Spec("tc_storm_present", "tropical_cyclone", "TC_JAM_0300as_STORM", "storm"),
    Spec(
        "tc_storm_rcp85_cmcc",
        "tropical_cyclone",
        "TC_JAM_0300as_STORM_CMCC-CM2-VHR4",
        "storm",
    ),
    Spec(
        "river_flood_hist",
        "river_flood",
        "river_flood_150arcsec_hist_JAM_1980_2000",
        "flood",
    ),
    Spec(
        "river_flood_rcp60_2050",
        "river_flood",
        "river_flood_150arcsec_rcp60_JAM_2050_2070",
        "flood",
    ),
    Spec("earthquake", "earthquake", "earthquake_hist_above4_388", "date"),
    Spec(
        "wildfire",
        "wildfire",
        "wildfire_JAM_150arcsec_historical_2001_2020",
        "date",
    ),
    Spec("storm_europe", "storm_europe", "storm_europe_150arcsec_LUX", "wisc"),
)


def years_of(dates: NDArray[np.float64]) -> NDArray[np.int64]:
    """Return the calendar year of each ordinal date."""
    return np.array([dt.date.fromordinal(int(day)).year for day in dates], dtype=int)


def iso(day: float) -> str:
    """Return an ordinal date as an ISO date."""
    return dt.date.fromordinal(int(day)).isoformat()


def name_patterns(names: list[str]) -> list[tuple[str, int]]:
    """Return the most common event-name patterns, digits replaced by ``N``."""
    counts = collections.Counter(re.sub(r"\d+", "N", name) for name in names)
    return counts.most_common(6)


def frequencies(freq: NDArray[np.float64]) -> dict[str, Any]:
    """Summarise an array of event frequencies."""
    values, counts = np.unique(freq, return_counts=True)
    order = np.argsort(counts)[::-1][:6]
    return {
        "n_unique": int(values.size),
        "uniform": bool(values.size == 1),
        "min": float(freq.min()),
        "max": float(freq.max()),
        "sum_per_year": float(freq.sum()),
        "top": [
            {
                "frequency": float(values[i]),
                "one_over": float(1.0 / values[i]),
                "n_events": int(counts[i]),
            }
            for i in order
        ],
    }


def members_of(spec: Spec, names: list[str]) -> NDArray[np.int64] | None:
    """Return each event's ensemble member (0 = the parent), if the names say."""
    if spec.route == "random_walk":
        return np.array(
            [int(n.split("_gen")[1]) if "_gen" in n else 0 for n in names], dtype=int
        )
    if spec.route == "wisc":
        return np.array([int(n) % 100 for n in names], dtype=int)
    return None


def parents_of(spec: Spec, names: list[str]) -> list[str] | None:
    """Return each event's parent event, if the names say."""
    if spec.route == "random_walk":
        return [n.split("_gen")[0] for n in names]
    if spec.route == "wisc":
        return [str(int(n) // 100) for n in names]
    return None


def ensemble_facts(
    spec: Spec,
    names: list[str],
    hazard: Any,  # noqa: ANN401 (climada.hazard.Hazard)
) -> dict[str, Any] | None:
    """Return how the ensemble members relate to their parent, if the names say."""
    parents = parents_of(spec, names)
    members = members_of(spec, names)
    if parents is None or members is None:
        return None
    by_parent: dict[str, list[int]] = collections.defaultdict(list)
    for position, parent in enumerate(parents):
        by_parent[parent].append(position)
    sizes = collections.Counter(len(pos) for pos in by_parent.values())
    orig = np.asarray(hazard.orig, dtype=bool)
    groups = [np.array(pos) for pos in by_parent.values()]
    return {
        "n_parents": len(by_parent),
        "members_per_parent": dict(sizes),
        "member_index_min_max": [int(members.min()), int(members.max())],
        "orig_is_member_zero": bool(np.array_equal(orig, members == 0)),
        "share_parent_date": bool(
            all(np.unique(hazard.date[g]).size == 1 for g in groups)
        ),
        "parents_with_one_frequency": int(
            sum(np.unique(hazard.frequency[g]).size == 1 for g in groups)
        ),
        "adjacent_in_file": bool(all(g.max() - g.min() + 1 == g.size for g in groups)),
    }


def year_labels(
    spec: Spec,
    hazard: Any,  # noqa: ANN401 (climada.hazard.Hazard)
    names: list[str],
) -> tuple[NDArray[np.int64] | None, int | None, str]:
    """Return a simulation year per event, the number of years and how they arose."""
    if spec.route == "storm":
        found = [_STORM_NAME.match(name) for name in names]
        if any(m is None for m in found):
            return None, None, "a name does not fit the STORM pattern"
        labels = np.array(
            [int(m["file"]) * 1000 + int(m["year"]) for m in found if m is not None],
            dtype=int,
        )
        return labels, 10_000, "<file> * 1000 + <year> from the event name"
    calendar = years_of(np.asarray(hazard.date, dtype=float))
    if spec.route == "date":
        n_years = int(calendar.max() - calendar.min() + 1)
        return calendar - calendar.min(), n_years, "calendar year of the date"
    if spec.route == "flood":
        models = sorted({n.split("_", 1)[1] for n in names})
        member = np.array([models.index(n.split("_", 1)[1]) for n in names], dtype=int)
        span = int(calendar.max() - calendar.min() + 1)
        labels = (calendar - calendar.min()) + member * span
        return labels, span * len(models), "year + member * span, member from the name"
    members = members_of(spec, names)
    assert members is not None
    n_members = int(members.max()) + 1
    if spec.route == "random_walk":
        span = int(calendar.max() - calendar.min() + 1)
        labels = (calendar - calendar.min()) + members * span
        return labels, span * n_members, "year + member * span, member from _gen<m>"
    months = np.array([dt.date.fromordinal(int(d)).month for d in hazard.date])
    season = calendar - (months < 7).astype(int)
    implied = round(1.0 / float(np.median(hazard.frequency)) / n_members)
    span = int(season.max() - season.min() + 1)
    labels = (season - season.min()) + members * span
    how = (
        f"season (Jul-Jun) + member * span; the dates cover {span} seasons, "
        f"1 / frequency / members gives {implied}"
    )
    return labels, span * n_members, how


def proxy_centroids(
    hazard: Any,  # noqa: ANN401 (climada.hazard.Hazard)
) -> NDArray[np.int64]:
    """Return the three centroids with the largest mean intensity."""
    return np.argsort(np.asarray(hazard.intensity.mean(axis=0)).ravel())[::-1][:3]


def proxy_loss(
    hazard: Any,  # noqa: ANN401 (climada.hazard.Hazard)
    centroids: NDArray[np.int64],
) -> NDArray[np.float64]:
    """Return the sum of the intensity at the given centroids, per event."""
    return np.asarray(hazard.intensity[:, centroids].sum(axis=1)).ravel()


def try_index(
    hazard: Any,  # noqa: ANN401 (climada.hazard.Hazard)
    exposures: Any,  # noqa: ANN401 (climada.entity.Exposures)
    **kwargs: Any,  # noqa: ANN401
) -> dict[str, Any]:
    """Build the prototype's index and its annual measure; record what happened."""
    try:
        index = pm.ParametricIndex.from_hazard(hazard, exposures, **kwargs)
        measure = pm.outcome_measure(
            index.event_year,
            index.frequency,
            basis="annual",
            years=index.years,
            n_catalogue_years=index.years.size,
        )
    except pm.ParametricInputError as error:
        return {"ok": False, "error": str(error)[:400]}
    return {
        "ok": True,
        "n_years": int(index.years.size),
        "first_year": int(index.years[0]),
        "n_outcomes": int(measure.n_outcomes),
    }


def annual_summary(values: NDArray[np.float64]) -> dict[str, float]:
    """Return the mean, the zero share and two upper quantiles of annual values."""
    return {
        "mean": float(values.mean()),
        "share_zero": float(np.mean(values == 0.0)),
        "q90": float(np.quantile(values, 0.90)),
        "q99": float(np.quantile(values, 0.99)),
    }


def warned_on_unequal(call: Any) -> tuple[Any, bool]:  # noqa: ANN401
    """Run ``call``; return its result and whether yearsets warned about frequencies."""
    records: list[logging.LogRecord] = []

    class Catch(logging.Handler):
        """Keep the log records."""

        def emit(self, record: logging.LogRecord) -> None:
            """Store one record."""
            records.append(record)

    logger = logging.getLogger("climada.util.yearsets")
    handler = Catch()
    logger.addHandler(handler)
    try:
        result = call()
    finally:
        logger.removeHandler(handler)
    return result, any("frequencies" in r.getMessage() for r in records)


def yearset_route(
    hazard: Any,  # noqa: ANN401 (climada.hazard.Hazard)
    loss: NDArray[np.float64],
) -> dict[str, Any]:
    """Draw years with ``yearsets`` without the global numpy seed; summarise them."""
    freq = np.asarray(hazard.frequency, dtype=float)
    impact = Impact(
        at_event=loss,
        frequency=freq,
        event_id=np.arange(1, loss.size + 1),
        event_name=list(range(1, loss.size + 1)),
        date=np.ones(loss.size, dtype=int),
        aai_agg=float(freq @ loss),
    )
    rng = np.random.default_rng(SEED)
    per_year = rng.poisson(lam=float(freq.sum()), size=SAMPLED_YEARS).astype(int)
    out: dict[str, Any] = {"lam": float(freq.sum())}
    vect = yearsets.sample_events(per_year, freq, with_replacement=True, seed=SEED)
    out["with_replacement"] = annual_summary(
        yearsets.compute_imp_per_year(impact, vect)
    )
    if loss.size <= MAX_EVENTS_NO_REPLACEMENT:
        vect, warned = warned_on_unequal(
            lambda: yearsets.sample_events(
                per_year, freq, with_replacement=False, seed=SEED
            )
        )
        out["without_replacement"] = {
            **annual_summary(yearsets.compute_imp_per_year(impact, vect)),
            "warned": warned,
        }
    else:
        out["without_replacement"] = "not run: more events than the script's limit"
    return out


def facts_of(spec: Spec, client: Client, max_bytes: int) -> dict[str, Any]:
    """Return the facts of one dataset."""
    info = client.get_dataset_info(data_type=spec.data_type, name=spec.name)
    n_bytes = int(sum(f.file_size for f in info.files))
    base: dict[str, Any] = {
        "dataset": spec.name,
        "data_type": spec.data_type,
        "version": info.version,
        "licence": info.license,
        "bytes": n_bytes,
        "properties": dict(info.properties),
    }
    if n_bytes > max_bytes:
        return {**base, "skipped": f"{n_bytes} bytes is above the limit {max_bytes}"}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        hazard = client.to_hazard(info)
    names = [str(name) for name in hazard.event_name]
    freq = np.asarray(hazard.frequency, dtype=float)
    dates = np.asarray(hazard.date, dtype=float)
    calendar = years_of(dates)
    hit = np.asarray(hazard.intensity.getnnz(axis=1)) > 0
    base.update(
        {
            "haz_type": hazard.haz_type,
            "units": hazard.units,
            "n_events": int(hazard.size),
            "n_centroids": int(hazard.centroids.size),
            "n_events_with_intensity": int(hit.sum()),
            "frequency_unit": hazard.frequency_unit,
            "frequency": frequencies(freq),
            "frequency_of_events_with_intensity": frequencies(freq[hit]),
            "date_min": iso(dates.min()),
            "date_max": iso(dates.max()),
            "n_distinct_dates": int(np.unique(dates).size),
            "n_distinct_calendar_years": int(np.unique(calendar).size),
            "calendar_year_span": int(calendar.max() - calendar.min() + 1),
            "name_patterns": name_patterns(names),
            "first_names": names[:3],
            "n_orig_true": int(np.sum(hazard.orig)),
            "ensemble": ensemble_facts(spec, names, hazard),
        }
    )
    labels, n_years, how = year_labels(spec, hazard, names)
    centroids = proxy_centroids(hazard)
    exposures = Exposures(
        lat=hazard.centroids.lat[centroids],
        lon=hazard.centroids.lon[centroids],
        value=np.ones(centroids.size),
    )
    base["prototype_default"] = try_index(hazard, exposures)
    selected = hazard.select(event_id=hazard.event_id[hit].tolist())
    base["prototype_default_events_with_intensity"] = try_index(selected, exposures)
    base["labels"] = how
    loss = proxy_loss(hazard, centroids)
    routes: dict[str, Any] = {"expected_annual_proxy": float(freq @ loss)}
    if labels is not None and n_years is not None:
        base["n_years_from_labels"] = int(n_years)
        base["prototype_labelled"] = try_index(
            hazard, exposures, event_year=labels, n_years=n_years, first_year=0
        )
        base["prototype_labelled_events_with_intensity"] = try_index(
            selected, exposures, event_year=labels[hit], n_years=n_years, first_year=0
        )
        parents = parents_of(spec, names)
        if parents is not None:
            cut = int(0.7 * n_years)
            parent_arr = np.array(parents)
            seen = np.unique(parent_arr[hit & (labels < cut)])
            test = parent_arr[hit & (labels >= cut)]
            base["parent_leak_of_a_70_30_year_split"] = float(
                np.mean(np.isin(test, seen))
            )
        counts = np.bincount(labels[hit], minlength=n_years).astype(float)
        base["hit_events_per_year"] = {
            "mean": float(counts.mean()),
            "variance_over_mean": float(counts.var() / counts.mean()),
            "share_of_years_without": float(np.mean(counts == 0)),
            "max": int(counts.max()),
        }
        annual = np.zeros(n_years)
        np.add.at(annual, labels, loss)
        routes["catalogue_years"] = annual_summary(annual)
    routes["yearsets"] = yearset_route(hazard, loss)
    base["routes"] = routes
    return base


def main() -> None:
    """Read the datasets and write the facts as JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    args = parser.parse_args()
    client = Client()
    facts = {spec.label: facts_of(spec, client, args.max_bytes) for spec in SPECS}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(facts, indent=1, default=str) + "\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
