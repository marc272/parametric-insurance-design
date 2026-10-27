# F-09: headline comparison with 90 % block-bootstrap intervals

- Issue: [MAR-23](https://linear.app/marc-prinzing/issue/MAR-23/f-09-block-bootstrap-confidence-intervals-for-all-kpis) (F-09), SPEC §6.1. Written by a worker agent on 2026-10-28.
- Status: **observations only.** Interpretation belongs to checkpoint C1 (MAR-29). The publication rule applies: these numbers aren't for public use as a claim about the method.
- Method: `docs/methodology/bootstrap.md`. Script: `research/scripts/bootstrap_headline.py`. Data: `research/data/bootstrap-headline/` (`kpis.csv`, `paired.csv`, `summary.json`), with every run's `config_hash` and `run_id`.
- This extends the MAR-22 rerun (`research/notes/out-of-sample-rerun.md`) with intervals. The point values are the same as there; only the intervals are new.

## Setup

- **Config.** `parity/configs/thesis.yaml`: 9 assets, heteroscedastic noise (η = 0.3, 13 copies, seed 42), threshold 20 m/s, **event-conditional basis** (the thesis basis, not the paper default `annual`), pure pricing, budget loading 1, 15 bins, 3 clusters. KPIs at β = 0.95.
- **Split.** Holdout: calibrate on years 0–6,999, evaluate on them (`train`) and on years 7,000–9,999 (`test`).
- **Bootstrap.** `bootstrap: {seed: 0, n_bootstrap: 1000, level: 0.9}`: year blocks, percentile intervals. All 9 runs on one sample share the same resampled years (same seed), so the comparisons between designs are paired.
- **Data.** EventSet `sha256:404b0c3a3aefa38965ad3ace2747d308685a67e3b218cb835d45a9ab375294df`. The prepared set has 13,897 rows over 10,000 years. Package `0.1.0.dev0`. Solver policy `solve.DEFAULT_POLICY`.
- **Check.** The script recomputes every run in-process and checks that the runner's stored intervals equal those computed from the in-process replicates. They do.
- **Level.** Every number is portfolio-level (`level = "portfolio"`), in the fixture's loss unit. `cvar_uncovered` is CVaR at 0.95 of (L − π)⁺ over event rows given an event (event-conditional), as in the thesis.

**How to read the intervals.**

- **Test intervals.** They show the sampling uncertainty of the out-of-sample KPI over 3,000 test years, with the design held fixed.
- **Train intervals.** They hold the design fixed too. They don't include the uncertainty of the calibration, which used those very years, so they're narrower than an honest in-sample band.
- **Tail intervals.** The coverage of percentile intervals for CVaR measured 85–92 % instead of 90 % in synthetic checks (`docs/methodology/bootstrap.md`).

## 1. Out-of-sample `cvar_uncovered` with 90 % intervals (test years)

| Scope | Objective | Test value | 90 % CI | Train value | 90 % CI |
|---|---|---:|---|---:|---|
| individual | MSE | 1,663,339 | [1,079,888, 2,320,021] | 1,680,066 | [1,282,410, 2,116,072] |
| individual | E[U] | 1,657,701 | [1,065,993, 2,328,689] | 1,676,387 | [1,280,879, 2,117,031] |
| individual | weighted CVaR | 1,175,425 | [1,023,162, 1,323,514] | 1,349,245 | [1,214,469, 1,499,862] |
| cluster | MSE | 2,006,673 | [1,325,076, 2,708,206] | 1,673,183 | [1,330,595, 2,052,697] |
| cluster | E[U] | 2,006,640 | [1,327,129, 2,686,388] | 1,668,826 | [1,316,818, 2,062,066] |
| cluster | weighted CVaR | 1,544,663 | [1,149,287, 1,952,764] | 1,295,060 | [1,124,981, 1,488,515] |
| portfolio | MSE | 1,638,140 | [1,093,279, 2,234,903] | 1,468,978 | [1,152,111, 1,858,938] |
| portfolio | E[U] | 1,629,906 | [1,028,248, 2,308,672] | 1,469,978 | [1,110,531, 1,897,684] |
| portfolio | weighted CVaR | 1,179,277 | [909,934, 1,478,902] | 1,081,478 | [927,825, 1,269,017] |

`expected_uncovered`, test:

| Scope | MSE | E[U] | weighted CVaR |
|---|---|---|---|
| individual | 92,700 [61,434, 127,967] | 92,958 [61,266, 127,927] | 169,705 [146,761, 194,793] |
| cluster | 113,874 [75,983, 156,369] | 114,522 [76,403, 156,604] | 162,103 [134,466, 191,511] |
| portfolio | 96,980 [66,540, 130,456] | 94,009 [61,881, 131,849] | 141,526 [120,037, 164,406] |

Observations:

- **Width.** The separate intervals are wide. The test-year `cvar_uncovered` interval of MSE spans 1.08–2.32 million in the individual scope, about ±37 % of the point value. The test-year expected loss alone has the interval [1,524,417, 2,636,110] around 2,049,786.
- **Overlap.** The separate test intervals of weighted CVaR and MSE overlap in every scope. For `cvar_uncovered`, weighted CVaR's upper bound lies above MSE's lower bound in all three scopes.
- **Weighted CVaR is narrower.** Weighted CVaR's `cvar_uncovered` and `var_uncovered` intervals are narrower than those of MSE and E[U] in every scope, on both train and test.
- **Train vs. test.** For 8 of the 9 runs, the train value of `cvar_uncovered` lies inside the run's test interval. The exception is individual × weighted CVaR: its train value of 1,349,245 lies above its test interval [1,023,162, 1,323,514].

## 2. Paired differences between designs (same resampled years)

`cvar_uncovered`, weighted CVaR minus the other design:

| Scope | Comparison | Train: difference [90 % CI] | Test: difference [90 % CI] |
|---|---|---|---|
| individual | − MSE | −330,822 [−659,483, −45,479] | −487,913 [−1,022,660, −15,911] |
| individual | − E[U] | −327,143 [−655,264, −40,614] | −482,276 [−1,022,426, −13,310] |
| cluster | − MSE | −378,123 [−586,381, −179,486] | −462,011 [−831,623, −116,770] |
| cluster | − E[U] | −373,767 [−594,443, −167,523] | −461,977 [−822,261, −126,836] |
| portfolio | − MSE | −387,500 [−591,767, −188,926] | −458,863 [−826,914, −122,980] |
| portfolio | − E[U] | −388,500 [−641,763, −166,193] | −450,629 [−901,711, −65,205] |

Other KPIs, test, weighted CVaR − MSE:

| Scope | `expected_uncovered` | `var_uncovered` | `rmse_residual` | `expected_payout` | `correlation` |
|---|---|---|---|---|---|
| individual | +77,005 [+43,323, +109,272] | +492,553 [+354,233, +601,725] | +317,165 [+140,575, +465,416] | −4,943 [−77,546, +77,393] | −0.00129 [−0.00223, −0.00070] |
| cluster | +48,228 [+25,203, +70,374] | +221,579 [−58,900, +365,060] | +196,878 [+21,219, +333,893] | −16,179 [−61,408, +37,897] | −0.00167 [−0.00246, −0.00046] |
| portfolio | +44,546 [+20,696, +66,380] | +242,044 [+66,753, +328,004] | +193,552 [+72,582, +291,016] | −661 [−49,782, +54,547] | −0.00079 [−0.00145, −0.00038] |

Observations:

- **Paired vs. separate.** Pairing narrows the intervals of the differences: the separate intervals overlap, but every paired `cvar_uncovered` interval excludes zero, in every scope, against MSE and against E[U], on both train and test.
- **Upper bounds near zero.** Some paired upper bounds are close to zero: individual, test, −15,911 against MSE and −13,310 against E[U]. The paired intervals are also wide relative to their point values: the test intervals are 0.70–1.01 million wide, against differences of 0.45–0.49 million.
- **The other side of the trade.** The paired intervals of `expected_uncovered` and `rmse_residual` (weighted CVaR higher) exclude zero in every scope on test. So does `var_uncovered`, except in the cluster scope, where the test intervals against MSE ([−58,900, +365,060]) and against E[U] contain zero.
- **Payout.** `expected_payout` differences have intervals that contain zero in every scope on test. On train they're 0 up to solver precision (the budget binds there), and their intervals come only from resampling the train years.
- **Correlation.** The correlation differences are small (−0.0005 to −0.0017), and their intervals exclude zero on test, except weighted CVaR − E[U] in the portfolio scope ([−0.00133, +0.00013]).

Config hashes and run ids of the 9 runs (holdout with bootstrap; they differ from the MAR-22 holdout hashes because the `bootstrap` section is hashed):

| Scope | Objective | `config_hash` | `run_id` |
|---|---|---|---|
| individual | MSE | `sha256:76fa6a211ef896701ebaaf0da19c78d2d6fe6ae99b2de0ed95607cd7db050251` | `sha256:3c5bbdee99f37dedf5d39007701ce8ecae70824dc118d42da6d6c01250d16e66` |
| individual | E[U] | `sha256:a9256cc9b34c8babf4fa637ca3e7f8407c4bcc6cdd32ea53db3b7ad9681cfd90` | `sha256:9dcb4391e6290ed72be0a1cecf6fcb10ff8677695e2004ce5b61e0c5f86c0d08` |
| individual | weighted CVaR | `sha256:f8725a9beee8d9bc84d0771c4bfd417ddb036a482ddb6284a74b614b60ea9457` | `sha256:37baafdf959dc3a3909ede530880ee09ad2decfa07064464df3afa72390efd41` |
| cluster | MSE | `sha256:d54442e350cc708e6345c9a06ad9869b243931ae0500b0eb5ca1fda039e97f84` | `sha256:04286c513502fae0bb89d55d78024a8318f9c910a813952f9d8b1971a2448649` |
| cluster | E[U] | `sha256:e7d6062c6f2ee172b13f9f1257b0c424dd4e439cfd28cad6aaf868105b9ce11e` | `sha256:c9fff502a018f1e7db4a4c9685eea53f3cb2ec144c3ff05b58ddc717f20012d5` |
| cluster | weighted CVaR | `sha256:691419c8ea6e1bf2e83b739e6d98f244ad821d47e2c2d3f5ed2d64030fe58b24` | `sha256:84554182b3e56e204d28c2f71ee594d659410b32b4c336b6caec551103d89e2b` |
| portfolio | MSE | `sha256:b3b396a3e8178a62877538e4c7d7ad12e0915d7b9474056bfdb050e7f6c39fd0` | `sha256:d5795786f8275970654699f67da418f65d2db036f28b238bd0833ad6a3b00ce0` |
| portfolio | E[U] | `sha256:1dff61a5f0978725f135daec8d4c956ff2e481e38bc54a4968a2578a49a84783` | `sha256:4b3232442b6a74cc9417cc1d02a0d026a1a3bf418a00551e8fa5c76122d450bf` |
| portfolio | weighted CVaR | `sha256:effe8566488c883da52dccbd21b42b0330095d5eacf979e49112f883794dc18c` | `sha256:1b346edf38fc2e0d8380d17f42842dc1dfceb33c35bc97ea1c74da90cf8718de` |

## 3. Timings

These are B = 1000 runs on a 10-core Mac shared with a parity run at `--jobs 4`, so they're slower than on an idle machine (`summary.json`). Bootstrap seconds per run, train (7,000 years) / test (3,000 years):

- individual: 4.6 / 2.5 (MSE), 8.0 / 4.3 (E[U]), 12.7 / 4.4 (weighted CVaR);
- cluster: 2.8 / 1.3, 3.7 / 1.7, 5.0 / 2.0;
- portfolio: 8.7 / 4.3, 5.9 / 2.4, 12.3 / 6.4.

On the idle machine the test sample took 3.6 s (individual), 1.0 s (cluster) and 1.9 s (portfolio). On most runs the bootstrap takes longer than the solve.

## Not covered

- **Basis and pricing.** Neither the annual basis (the paper default, MAR-24) nor loaded pricing (MAR-27) is covered. The C1 analysis needs both, with intervals.
- **k-fold.** k-fold intervals and a rule for combining folds aren't covered.
- **Train-to-test gaps.** No interval is computed for a gap, whose two sides come from different years and a calibration on one of them.
- **Other sweeps.** The `n_bins` and other sweeps weren't rerun with intervals.
