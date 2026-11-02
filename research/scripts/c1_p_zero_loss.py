r"""P(L_o = 0) of every C1 design problem on its calibration (train) years.

MAR-226, erratum to checkpoint C1 (``research/checkpoints/C1.md``). The C1
runs were solved before the run manifest recorded ``p_zero_loss``,
``tail_outcomes`` and ``degenerate_tail`` (MAR-173), so their stored
manifests lack them. This script measures them for every stored C1 run,
without solving anything:

1. read each manifest of the C1 result store and parse its ``config``;
2. check that the parsed config has the stored config hash, and that the
   input EventSet has the stored checksum;
3. prepare the EventSet as the runner does
   (:func:`~parametric_insurance_design.experiment.runner.prepare_eventset`)
   and check that its content hash is the stored ``prepared_eventset`` one;
4. take the calibration sample of the config (``holdout``: the train years)
   and build the run's design problems with
   :func:`~parametric_insurance_design.problem.build_problems`;
5. on each problem's outcome measure, compute the three manifest values the
   way the runner's MAR-173 code does (``runner._tail_record``, mirrored here
   from public names): ``p_zero_loss`` is the probability of the outcomes
   whose summed loss is zero; ``tail_outcomes`` is ``(1 - beta) / p_min``
   for weighted-CVaR runs; ``degenerate_tail`` is ``"expected_uncovered"``
   when ``beta <= p_zero_loss`` (within ``DEGENERATE_TAIL_ATOL``), else
   ``"single_outcome"`` when ``tail_outcomes <= 1``, else empty.

``p_zero_loss`` depends only on the prepared EventSet, the basis, the scope's
design problem and the calibration sample, not on the objective, the pricing
or the budget. The script reports it for every run anyway, so that every
value carries the config hash of a stored run.

Outputs (not committed; ``results/`` is gitignored):

* ``<out>/p_zero_loss.csv``: one row per (run, design problem);
* ``<out>/summary.csv``: one row per (family, EventSet, basis, scope, problem)
  with the distinct ``p_zero_loss`` values over its runs and one config hash.

Run from the repository root::

    uv run python research/scripts/c1_p_zero_loss.py \
        --store <C1 worktree>/results/c1/store --out results/c1-erratum
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Final

import numpy as np
import pandas as pd

from parametric_insurance_design import splits
from parametric_insurance_design.eventset import EventSet
from parametric_insurance_design.experiment.config import (
    ExperimentConfig,
    config_hash,
    parse_config,
)
from parametric_insurance_design.experiment.runner import (
    DEGENERATE_TAIL_ATOL,
    DEGENERATE_TAIL_EXPECTED_UNCOVERED,
    DEGENERATE_TAIL_SINGLE_OUTCOME,
    load_input,
    prepare_eventset,
)
from parametric_insurance_design.interfaces import Sample
from parametric_insurance_design.objectives import WeightedCVaR
from parametric_insurance_design.problem import build_problems

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
RUNS_CSV: Final[Path] = REPO_ROOT / "research" / "data" / "c1" / "runs.csv"


def calibration_sample(config: ExperimentConfig, prepared: EventSet) -> Sample:
    """Return the run's calibration sample (the runner's rule).

    Raises
    ------
    ValueError
        If the config's sample is neither ``full`` nor ``holdout`` (C1 has no
        k-fold runs).
    """
    sample = config.sample
    if sample.kind == "full":
        return Sample.full(prepared)
    if sample.kind == "holdout":
        train, _ = splits.holdout(prepared, train_fraction=sample.train_fraction)
        return train
    raise ValueError(f"unexpected sample kind {sample.kind!r} in a C1 run")


def tail_values(
    measure_probability: np.ndarray, outcome_loss: np.ndarray, beta: float | None
) -> dict[str, Any]:
    """Return ``p_zero_loss``, ``tail_outcomes``, ``degenerate_tail``.

    Mirrors the runner's MAR-173 record (module docstring of
    ``experiment.runner``, "Degenerate tail objectives").
    """
    p_zero = float(measure_probability[outcome_loss == 0.0].sum())
    out: dict[str, Any] = {
        "p_zero_loss": p_zero,
        "tail_outcomes": None,
        "degenerate_tail": None,
    }
    if beta is None:
        return out
    positive = measure_probability[measure_probability > 0.0]
    tail = (1.0 - beta) / float(positive.min())
    out["tail_outcomes"] = tail
    if beta <= p_zero + DEGENERATE_TAIL_ATOL:
        out["degenerate_tail"] = DEGENERATE_TAIL_EXPECTED_UNCOVERED
    elif tail <= 1.0 + DEGENERATE_TAIL_ATOL:
        out["degenerate_tail"] = DEGENERATE_TAIL_SINGLE_OUTCOME
    return out


def measure_run(
    manifest: dict[str, Any], prepared_cache: dict[str, EventSet]
) -> list[dict[str, Any]]:
    """Return one row per design problem of a stored run.

    Raises
    ------
    RuntimeError
        If the config hash, the input checksum or the prepared EventSet's
        content hash differs from the stored one.
    """
    config = parse_config(manifest["config"])
    stored_hash = manifest["cache_key"]["config_hash"]
    chash = config_hash(config)
    if chash != stored_hash:
        raise RuntimeError(
            f"run {manifest['run_id']}: config hash {chash} != stored {stored_hash}"
        )
    key = json.dumps(
        [
            str(config.eventset.path),
            manifest["config"].get("noise"),
            manifest["config"].get("threshold"),
            manifest["config"].get("portfolio"),
        ],
        sort_keys=True,
    )
    if key not in prepared_cache:
        data = load_input(config)  # checks config.eventset.checksum
        if data.checksum != manifest["input"]["content_hash"]:
            raise RuntimeError(
                f"run {manifest['run_id']}: input checksum {data.checksum} != "
                f"stored {manifest['input']['content_hash']}"
            )
        prepared_cache[key] = prepare_eventset(config, data.eventset)
    prepared = prepared_cache[key]
    prepared_hash = prepared.content_hash()
    if prepared_hash != manifest["prepared_eventset"]["content_hash"]:
        raise RuntimeError(
            f"run {manifest['run_id']}: prepared EventSet {prepared_hash} != stored "
            f"{manifest['prepared_eventset']['content_hash']}"
        )
    sample = calibration_sample(config, prepared)
    components = config.to_components()
    scope, objective = components.scopes[0], components.objectives[0]
    beta = objective.beta if isinstance(objective, WeightedCVaR) else None
    built = build_problems(
        prepared,
        scope,
        components.payout,
        objective,
        components.pricing,
        components.constraints,
        basis=components.basis,
        sample=sample,
    )
    rows: list[dict[str, Any]] = []
    for problem in built:
        measure = problem.context.measure
        outcome_loss = measure.aggregate(problem.context.problem.loss)
        values = tail_values(measure.probability, outcome_loss, beta)
        rows.append(
            {
                "run_id": manifest["run_id"],
                "config_hash": chash,
                "prepared_eventset": prepared_hash,
                "basis": components.basis.value,
                "calibration_sample": sample.name,
                "n_outcomes": measure.n_outcomes,
                "problem_id": problem.spec.problem_id,
                "objective_beta": beta,
                **values,
            }
        )
    return rows


def main(argv: list[str] | None = None) -> None:
    """Measure every stored run and write the tables."""
    parser = argparse.ArgumentParser(
        description="P(L_o = 0) of every C1 design problem on its train years."
    )
    parser.add_argument("--store", type=Path, required=True, help="C1 result store")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "results" / "c1-erratum"
    )
    args = parser.parse_args(argv)

    labels = pd.read_csv(RUNS_CSV)
    manifests = sorted((args.store / "manifests").glob("*.json"))
    if len(manifests) != len(labels):
        raise RuntimeError(
            f"{len(manifests)} manifests in the store, {len(labels)} runs in {RUNS_CSV}"
        )
    cache: dict[str, EventSet] = {}
    rows: list[dict[str, Any]] = []
    for i, path in enumerate(manifests, 1):
        manifest = json.loads(path.read_text())
        rows.extend(measure_run(manifest, cache))
        if i % 25 == 0:
            print(f"{i}/{len(manifests)} runs measured", flush=True)
    table = pd.DataFrame(rows)
    keep = ["run_id", "family", "eventset", "pricing", "kappa", "scope", "design"]
    table = labels[keep].merge(table, on="run_id", how="right", validate="1:m")
    if bool(table["family"].isna().any()):
        raise RuntimeError("a stored run is missing from runs.csv")

    args.out.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out / "p_zero_loss.csv", index=False)

    group = ["family", "eventset", "basis", "scope", "problem_id"]
    summary = (
        table.groupby(group, sort=False)
        .agg(
            p_zero_loss_min=("p_zero_loss", "min"),
            p_zero_loss_max=("p_zero_loss", "max"),
            n_outcomes=("n_outcomes", "first"),
            n_runs=("run_id", "nunique"),
            prepared_eventset=("prepared_eventset", "first"),
            config_hash=("config_hash", "first"),
        )
        .reset_index()
    )
    summary.to_csv(args.out / "summary.csv", index=False)
    flagged = table.dropna(subset=["degenerate_tail"])
    print(f"{len(table)} problem rows from {len(manifests)} runs")
    print(f"degenerate_tail set on {len(flagged)} rows:")
    print(flagged.groupby(["family", "eventset", "design", "degenerate_tail"]).size())


if __name__ == "__main__":
    main()
