# Out-of-sample evaluation: year-block splits

Issue MAR-22 (F-09), SPEC §6.1 (thesis issue M1). Code: `packages/core/src/parametric_insurance_design/splits.py`; the runner (`experiment/runner.py`); config section `sample` (`experiment/config.py`).

## Why

The thesis calibrated each payout and computed its KPIs on the same events, so every KPI was in-sample. A split by rows wouldn't fix that: the noise copies (and vulnerability draws) of one storm are separate rows, and they would land on both sides. Splits here are by **contiguous blocks of simulation years**, and every row of an event stays in one block.

## Splits

Years are 0-based, `year ∈ [0, n_years)` (ADR 0002 §5). The `EventSet` constructor enforces that range, so splits need no calendar-year mapping.

- **Holdout** (`splits.holdout`, default `train_fraction = 0.7`): the first `floor(train_fraction · n_years)` years train, the rest test. On the thesis EventSet (10,000 years) that's years 0–6,999 and 7,000–9,999: SPEC §6.1's "years 1 … 0.7Y" in 0-based storage. A tolerance of 1e-9 keeps floating-point products such as `0.29 · 100 = 28.999…` from losing a year.
- **k-fold** (`splits.year_block_kfold`, default `k = 5`): `numpy.array_split` of the years into `k` contiguous blocks. The first `n_years mod k` blocks get one year more. Fold `i` tests on block `i` and trains on the other blocks.

Both return `Sample` objects (`train`, `test`) whose `years` include the years without rows, which the annual basis needs as zero-loss years.

**No leakage, no silent failures.**

- An event whose rows carry more than one year would end up in two folds. The EventSet contract allows that, because its key is `(event_id, draw_id)`, so both splits check for it and raise `LeakageError`.
- `Sample.select` refuses rows from years outside the sample's year set.
- A block with no years, or a sample with no rows, raises `SplitError`. Both errors are `InputMismatchError`s.
- The leakage test (`tests/test_splits.py`) checks that no `event_id` appears in two folds: on a toy set with noise copies, and on the thesis fixture with its 13 noise copies.

## Runs

`sample` in an experiment config chooses the split: `full` (in-sample, the thesis and parity default), `holdout` or `kfold`.

- **holdout:** the runner calibrates on `train`, including the cluster scope's partition. It evaluates the result on `train` (in-sample) and on `test` (out-of-sample). Both sets of rows go into `kpis` and `exceedance`, with `eval_split` set to `train` or `test`. `runs.calibration_split` is `train`.
- **k-fold: a run per fold.** The `runs` key `(run_id, problem_id)` has no fold, so each fold is a run of its own. `ExperimentConfig.single_runs()` expands a k-fold config into one config per fold, with `sample.fold` set. The fold is therefore part of the config hash and of the `run_id`, and no record table changes. `runs.fold`, `kpis.fold` and `exceedance.fold` carry the fold number, and `runs.parameters` holds `k` and `fold`. Sweeps expand the same way, one point per value and fold. The runner refuses a k-fold config without `fold`.
- The `full` path is unchanged, so the parity configs keep their hashes and results.

## Overfitting diagnostic

`splits.kpi_gap(kpis)` pairs each KPI's `train` and `test` values of one run and fold, with `gap = test − train`. Joined with `runs` (scope, `parameters.n_bins`), it gives the gap as a function of `n_bins` and scope. `research/scripts/out_of_sample_rerun.py` does this for the thesis configuration. Its observations are in `research/notes/out-of-sample-rerun.md`.

## Pooled k-fold KPIs

Issue MAR-151. Code: `packages/core/src/parametric_insurance_design/experiment/kfold.py` (`pooled_kpis`, `pooled_designs`, `pooled_difference`).

A k-fold experiment has one run per fold (see "Runs" above; the fold is in `runs.fold`, in `runs.parameters`, in the `fold` key of `kpis` and `exceedance` and, for sweeps, in each point's `fold` key of the sweep manifest; ADR 0002 §7, amendment MAR-138). Each scope × objective therefore has k out-of-sample KPI values, each over 1/k of the years. The pooled rule combines them into one out-of-sample value per scope × objective.

**The rule.**

- The k test blocks partition the years, so every year, and every row, is evaluated by exactly one design: the one calibrated on the other k − 1 blocks.
- The pooled payout of a row is that design's portfolio payout. With the row's portfolio loss, it forms one out-of-sample sample over **all** years. The pooled KPIs are the `evaluate` KPIs of that sample, on the evaluation measure of all years (`Sample.full`): the eight portfolio KPIs and the premium.
- Only the **portfolio level** is pooled. Entities and design problems aren't comparable across folds: the cluster scope's partition differs per fold, so cluster C1 of fold 0 isn't cluster C1 of fold 1.
- **Paired intervals.** One `bootstrap.resample_years(all_years, B, default_rng(seed))` is drawn and shared by every design, with B, seed and level from the config's `bootstrap` section. The replicates come from `bootstrap.kpi_replicates` of each design's pooled loss and payout and, for the premium, from `bootstrap.premium_replicates` of its pooled payout (MAR-153). The intervals come from `bootstrap.percentile_interval`. Because the resample is shared, a difference between two designs is paired: `pooled_difference(pooled, a, b)` gives its interval from the replicate differences. Without a `bootstrap` section, the pooled KPIs have point values only.
- **Rejected: the mean of the per-fold KPIs.** A tail KPI (VaR, CVaR) from 1/k of the years is noisier than one from all years, and the mean of k CVaRs isn't the CVaR of any distribution. CVaR is concave in the distribution, so the weighted mean of the fold CVaRs understates the pooled CVaR (`tests/test_kfold.py` checks this on a real k = 2 store).

**Without re-solving.** Each fold's design is read from the store. `entities` gives its `ProblemSpec`s and `payouts` gives its levels θ. The payout structure, scope, basis and pricing come from the config. A row's test payout is `payout.evaluate(scope.materialise(test_data, spec).index, θ)`, on the prepared EventSet split with `splits.year_block_kfold`.

**No silent failures.**

- **Drift guard.** Each fold's portfolio KPIs on its test block are recomputed from those payouts and compared with the stored `kpis` rows (`eval_split = "test"`). A mismatch raises `FoldDriftError`. The guard also raises when the stored bin edges differ from the config's payout structure, or when the EventSet isn't the runs' prepared EventSet (content hash in the manifests).
- A run missing from the store, or a run that isn't the expected fold of the expected scope × objective, raises `PooledKFoldError`. So do a config that isn't k-fold and one that fixes `sample.fold`.
- A scope × objective with a failed fold isn't pooled. It is listed in `PooledKpis.failed` with the reason.
- A KPI that is undefined in some replicate gets null bounds, with `ci_level` and `n_bootstrap` set (as in the `kpis` table), and `PooledKpis.n_undefined` counts its undefined replicates.

**Storage: computed on demand** (orchestrator decision, MAR-151 option A; ADR 0002 §7 amendment MAR-151). Nothing is written to the store, and no record table changes. The rejected options were a pseudo-run with `fold = -1` in the store (B) and a new `pooled_kpis` table (C). Both would change the store contract, so revisit them only if the website export needs pooled rows in the store.

## Figures

The KPI figures draw `full` and `holdout` runs, with their bootstrap intervals where the config has them (MAR-148, [`bootstrap.md`](bootstrap.md#figures)).

For a k-fold config (MAR-151), the `figures` command computes the pooled KPIs with `pooled_kpis` and passes them to `write_figures(..., pooled_kpis=...)`. The viz never re-evaluates payouts.

- The KPI heatmaps and the performance overview draw one pooled row per scope × objective, with the pooled intervals. Their figure data have `eval_split = "pooled"`, the k fold runs in `run_id` (joined by `;`) and `k`. The subtitle says "pooled out of sample over k = … folds".
- The exceedance figures are skipped, with the reason stated. The pooled rule covers the portfolio KPIs, while the `exceedance` table holds one curve per fold, over 1/k of the years.
- The payout figures are skipped, because each scope × objective has a design per fold. The sweep figures are skipped too, because they show one run per scope × objective.
- Without pooled KPIs, `write_figures` refuses a k-fold config (`KFoldRunsError`, MAR-142). The figure functions that take runs (`kpi_table`, `kpi_heatmap`, `performance_overview`, `exceedance_curves`) still refuse k-fold runs (MAR-137).

The exceedance x-axis is labelled per basis (MAR-117, MAR-139): "Return period RP [events]" on `event_conditional`, where 1/T is a share of the given events, and "[years]" on `annual` and `event`.

## Not covered here

Block-bootstrap confidence intervals over years (SPEC §6.1, `ci_low`/`ci_high` in `kpis`) are MAR-23: see [`bootstrap.md`](bootstrap.md).
