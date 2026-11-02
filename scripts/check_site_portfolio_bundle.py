r"""Check the portfolio bundle against the result store it was exported from.

The portfolio explorer (``site/explorers/portfolio.qmd``) reads the bundle
that ``parametric-insurance-design export-site site/configs/portfolio.yaml
--no-sweeps --split test`` writes. This script checks that every number the
page shows is the result store's, and that the bundle has what the page
needs:

* the manifest's config hash is the config's, and the bundle holds one run
  per scope key and objective of the config, each complete;
* the portfolio-level KPI rows (value and bootstrap interval) and the
  portfolio-level exceedance rows of every run equal the store's
  ``eval_split = "test"`` rows, and no other split is in the bundle;
* each design problem's premium in ``runs.json`` equals the store's
  ``runs.premium`` (the page adds them up as the premium charged);
* the per-site numbers of ``baseline.map.arrow`` for the individual scope
  equal the store's entity KPI rows on the test years, and the joint runs
  (cluster and portfolio scopes) have no per-site numbers;
* each site's cluster in ``baseline.map.arrow`` equals the store's
  ``entities`` table, and every cluster run has the same clusters.

Usage, from the repository root, after the solve and the export::

    uv run python scripts/check_site_portfolio_bundle.py \\
        site/configs/portfolio.yaml site/_site/bundles/portfolio

Exit 0 when every check passes, 1 with the failures listed otherwise.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pyarrow as pa

from parametric_insurance_design.experiment.config import config_hash, load_config
from parametric_insurance_design_viz.reader import ResultReader

SPLIT = "test"
"""The evaluation split the bundle holds (``--split test``)."""

INDIVIDUAL = "individual"
JOINT_SCOPE_KEYS = ("cluster", "portfolio")
CLUSTER_SCOPE_KEYS = ("cluster", "cluster_separate")
MAP_NUMBERS = ("expected_loss", "expected_payout", "expected_uncovered")


def _arrow(path: Path) -> pd.DataFrame:
    with pa.memory_map(str(path)) as source:
        table = pa.ipc.open_file(source).read_all()
    frame = table.to_pandas()
    for column in frame.columns:
        if isinstance(frame[column].dtype, pd.CategoricalDtype):
            frame[column] = frame[column].astype(str)
    return frame


def _same(a: float | None, b: float | None) -> bool:
    """Equal floats, or both undefined (null in the bundle, NaN in the store)."""
    a_missing = a is None or (isinstance(a, float) and math.isnan(a))
    b_missing = b is None or (isinstance(b, float) and math.isnan(b))
    if a_missing or b_missing:
        return a_missing and b_missing
    return math.isclose(float(a), float(b), rel_tol=1e-12, abs_tol=1e-9)  # type: ignore[arg-type]


def _compare(
    bundle: pd.DataFrame,
    store: pd.DataFrame,
    keys: Sequence[str],
    values: Sequence[str],
    what: str,
) -> list[str]:
    """Compare two tables row for row on ``keys``; return the failures."""
    failures: list[str] = []
    b = bundle.set_index(list(keys)).sort_index()
    s = store.set_index(list(keys)).sort_index()
    if b.index.has_duplicates or s.index.has_duplicates:
        return [f"{what}: duplicate keys"]
    if set(b.index) != set(s.index):
        missing = len(set(s.index) - set(b.index))
        extra = len(set(b.index) - set(s.index))
        return [
            f"{what}: {missing} store rows missing from the bundle, "
            f"{extra} bundle rows not in the store"
        ]
    for key, row in b.iterrows():
        for value in values:
            if not _same(row[value], s.loc[key, value]):
                failures.append(
                    f"{what} {key} {value}: bundle {row[value]!r}, "
                    f"store {s.loc[key, value]!r}"
                )
    return failures


def check(config_path: Path, bundle_dir: Path) -> tuple[list[str], dict[str, int]]:
    """Run every check; return the failures and the number of values compared."""
    failures: list[str] = []
    counts: dict[str, int] = {}
    config = load_config(config_path)
    manifest = json.loads((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    runs_index = json.loads((bundle_dir / "runs.json").read_text(encoding="utf-8"))[
        "runs"
    ]

    expected_hash = config_hash(config)
    if manifest["config"]["hash"] != expected_hash:
        failures.append(
            f"config hash: bundle {manifest['config']['hash']}, config {expected_hash}"
        )
    if manifest.get("split_filter", {}).get("eval_split") != SPLIT:
        failures.append(
            f"split filter: {manifest.get('split_filter')!r}, expected {SPLIT!r}"
        )
    if manifest["runs"].get("skipped"):
        failures.append(f"runs left out: {manifest['runs']['skipped']!r}")

    run_ids = list(manifest["runs"]["baseline"])
    by_id = {r["run_id"]: r for r in runs_index}
    pairs = [(by_id[i]["scope_key"], by_id[i]["objective"]) for i in run_ids]
    n_scopes, n_objectives = len(config.scopes), len(config.objectives)
    if len(set(pairs)) != len(pairs) or len(pairs) != n_scopes * n_objectives:
        failures.append(
            f"runs: {len(pairs)} (scope key, objective) pairs, "
            f"expected {n_scopes} x {n_objectives}, each once"
        )
    scope_of = {i: by_id[i]["scope_key"] for i in run_ids}

    reader = ResultReader(Path(config_path).parent / config.output.directory)
    results = {r.run_id: r for r in reader.runs(run_ids)}
    for run in results.values():
        if not run.complete:
            failures.append(
                f"run {run.run_id}: failed problems {run.failed_problems!r}"
            )

    # KPIs: every portfolio-level row of the test split.
    kpis = _arrow(bundle_dir / "baseline.kpis.arrow")
    exceedance = _arrow(bundle_dir / "baseline.exceedance.arrow")
    map_rows = _arrow(bundle_dir / "baseline.map.arrow")
    for name, table in (("kpis", kpis), ("exceedance", exceedance), ("map", map_rows)):
        splits = set(table["eval_split"])
        if splits != {SPLIT}:
            failures.append(
                f"{name}: eval_split {sorted(splits)}, expected only {SPLIT!r}"
            )

    store_kpis = pd.concat([r.kpis for r in results.values()], ignore_index=True)
    store_portfolio = store_kpis[
        (store_kpis["level"] == "portfolio") & (store_kpis["eval_split"] == SPLIT)
    ]
    bundle_portfolio = kpis[kpis["level"] == "portfolio"]
    kpi_values = ("value", "ci_low", "ci_high")
    failures += _compare(
        bundle_portfolio,
        store_portfolio,
        ("run_id", "kpi"),
        kpi_values,
        "portfolio KPI",
    )
    counts["portfolio KPI values"] = len(bundle_portfolio) * len(kpi_values)

    # Exceedance: every portfolio-level curve point of the test split.
    store_exc = pd.concat([r.exceedance for r in results.values()], ignore_index=True)
    store_exc = store_exc[
        (store_exc["level"] == "portfolio") & (store_exc["eval_split"] == SPLIT)
    ]
    bundle_exc = exceedance[exceedance["level"] == "portfolio"]
    exc_keys = ("run_id", "quantity", "curve", "return_period")
    failures += _compare(
        bundle_exc, store_exc, exc_keys, ("value",), "portfolio exceedance"
    )
    counts["portfolio exceedance values"] = len(bundle_exc)

    # Premiums: each design problem's, as the page adds them up.
    n_premiums = 0
    for run_id, run in results.items():
        store_premium = run.runs.set_index("problem_id")["premium"]
        bundle_problems = {
            p["problem_id"]: p["premium"] for p in by_id[run_id]["problems"]
        }
        if set(bundle_problems) != set(store_premium.index):
            failures.append(
                f"run {run_id}: problems {sorted(bundle_problems)} in runs.json, "
                f"{sorted(store_premium.index)} in the store"
            )
            continue
        for pid, premium in bundle_problems.items():
            n_premiums += 1
            if not _same(premium, float(store_premium[pid])):
                failures.append(
                    f"run {run_id} problem {pid} premium: bundle {premium!r}, "
                    f"store {store_premium[pid]!r}"
                )
    counts["problem premiums"] = n_premiums

    # Per-site cover: the individual runs' entity rows; joint runs have none.
    individual = [i for i in run_ids if scope_of[i] == INDIVIDUAL]
    store_entity = (
        store_kpis[
            (store_kpis["level"] == "entity")
            & (store_kpis["eval_split"] == SPLIT)
            & (store_kpis["run_id"].isin(individual))
            & (store_kpis["kpi"].isin(MAP_NUMBERS))
        ]
        .pivot_table(
            index=["run_id", "subject_id"], columns="kpi", values="value", observed=True
        )
        .reset_index()
    )
    store_entity = store_entity.rename(columns={"subject_id": "location_id"})
    bundle_individual = map_rows[map_rows["run_id"].isin(individual)]
    failures += _compare(
        bundle_individual,
        store_entity,
        ("run_id", "location_id"),
        MAP_NUMBERS,
        "per-site cover",
    )
    counts["per-site values (individual)"] = len(bundle_individual) * len(MAP_NUMBERS)
    joint = map_rows[map_rows["scope_key"].isin(JOINT_SCOPE_KEYS)]
    if bool(joint.loc[:, list(MAP_NUMBERS)].notna().to_numpy().any()):
        failures.append(
            "map: a joint run (cluster or portfolio scope) has per-site numbers"
        )

    # Clusters: each site's entity, from the store's entities table.
    assignments: dict[str, dict[str, str]] = {}
    for run_id in run_ids:
        if scope_of[run_id] not in CLUSTER_SCOPE_KEYS:
            continue
        store_assign = dict(
            zip(
                results[run_id].entities["location_id"],
                results[run_id].entities["entity_id"],
                strict=True,
            )
        )
        rows = map_rows[map_rows["run_id"] == run_id]
        bundle_assign = dict(zip(rows["location_id"], rows["entity_id"], strict=True))
        if bundle_assign != store_assign:
            failures.append(
                f"run {run_id}: clusters {bundle_assign!r} in the bundle, "
                f"{store_assign!r} in the store"
            )
        assignments[run_id] = store_assign
    if len({json.dumps(a, sort_keys=True) for a in assignments.values()}) > 1:
        failures.append("the cluster runs have different clusters")
    counts["cluster assignments"] = sum(len(a) for a in assignments.values())
    return failures, counts


def main(argv: Sequence[str] | None = None) -> int:
    """Run the checks on the command line's config and bundle; return the exit code."""
    parser = argparse.ArgumentParser(
        description="Check the portfolio bundle against its result store."
    )
    parser.add_argument("config", type=Path, help="site/configs/portfolio.yaml")
    parser.add_argument("bundle", type=Path, help="the exported bundle directory")
    args = parser.parse_args(argv)
    failures, counts = check(args.config, args.bundle)
    manifest = json.loads((args.bundle / "manifest.json").read_text(encoding="utf-8"))
    print(f"bundle {args.bundle} from {args.config}")
    print(f"config hash {manifest['config']['hash']}")
    for what, n in counts.items():
        print(f"  compared {n:5d} {what}")
    if failures:
        print(f"{len(failures)} failures:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    print("every number the portfolio explorer shows equals the result store's")
    return 0


if __name__ == "__main__":
    sys.exit(main())
