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

## Not covered here

Block-bootstrap confidence intervals over years (SPEC §6.1, `ci_low`/`ci_high` in `kpis`) are MAR-23.
