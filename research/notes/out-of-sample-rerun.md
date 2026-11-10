# F-09: the thesis configuration out of sample

- Issue: MAR-22 (F-09), SPEC §6.1, thesis issue M1. Written by a worker agent on 2026-10-27.
- Status: **observations only.** Interpretation belongs to checkpoint C1 (MAR-29). These are point values. Confidence intervals come with MAR-23. The publication rule applies: these numbers aren't for public use as a claim about the method.
- Method: `docs/methodology/out-of-sample.md`. Script: `research/scripts/out_of_sample_rerun.py`. Data: `research/data/out-of-sample-rerun/`, with every row's `config_hash` and `run_id`.

## Setup

- **Config.** `parity/configs/thesis.yaml`: 9 assets, heteroscedastic noise (η = 0.3, 13 copies, seed 42), threshold 20 m/s, event-conditional basis, pure pricing, budget loading 1, 15 bins, 3 clusters. Every KPI is evaluated at β = 0.95. Only the `sample` changes, and the only sweep run is `n_bins` (5, 10, 15, 20, 25).
- **Data.** EventSet `sha256:404b0c3a3aefa38965ad3ace2747d308685a67e3b218cb835d45a9ab375294df`. The prepared set has 13,897 rows over 10,000 years. Package `0.1.0.dev0`.
- **Solver.** `solve.DEFAULT_POLICY`: Clarabel, HiGHS and SCS for the LPs; OSQP at 1e-8 for the MSE QPs. This is not the parity policy, so the MSE numbers differ slightly from the parity store.
- **Samples.**
  - `full`: calibrate and evaluate on every year. This is the thesis, in sample.
  - `holdout`: calibrate on years 0–6,999 and evaluate on them (`train`) and on years 7,000–9,999 (`test`).
  - `kfold`: k = 5 blocks of 2,000 years, at 15 bins, with a run per fold.
- **Size.** 45 runs per sample, 135 in all. The first run took 357 s (`full`), 328 s (`holdout`) and 232 s (`kfold`) at `--jobs 4`, on a 10-core Mac shared with other jobs (load average about 20).
- **Not rerun.** The other thesis sweeps (α, β, budget loading, clusters, noise, asset count) weren't rerun out of sample.

Every number below is a **portfolio-level** KPI (`level = "portfolio"`): the sum over all nine locations and all payouts of a run. Money is in the fixture's loss unit.

- `cvar_uncovered` is CVaR at 0.95 of the uncovered loss (L − π)⁺ on the event-conditional basis: the tail of event rows given an event, as in the thesis, not a tail over years.
- **Gap** = test − train. A positive gap means the KPI is larger out of sample.

## 1. In sample vs. out of sample at the thesis defaults (15 bins)

`cvar_uncovered` (β = 0.95):

| Scope | Objective | Full (in sample) | Holdout train | Holdout test | Gap | Gap / train |
|---|---|---:|---:|---:|---:|---:|
| individual | MSE | 1,659,693 | 1,680,066 | 1,663,339 | −16,728 | −1.0 % |
| individual | E[U] | 1,642,564 | 1,676,387 | 1,657,701 | −18,686 | −1.1 % |
| individual | weighted CVaR | 1,321,207 | 1,349,245 | 1,175,425 | −173,819 | −12.9 % |
| cluster | MSE | 1,728,687 | 1,673,183 | 2,006,673 | +333,490 | +19.9 % |
| cluster | E[U] | 1,712,599 | 1,668,826 | 2,006,640 | +337,813 | +20.2 % |
| cluster | weighted CVaR | 1,296,483 | 1,295,060 | 1,544,663 | +249,603 | +19.3 % |
| portfolio | MSE | 1,486,165 | 1,468,978 | 1,638,140 | +169,162 | +11.5 % |
| portfolio | E[U] | 1,496,949 | 1,469,978 | 1,629,906 | +159,928 | +10.9 % |
| portfolio | weighted CVaR | 1,065,599 | 1,081,478 | 1,179,277 | +97,799 | +9.0 % |

`expected_uncovered`:

| Scope | Objective | Full | Train | Test | Gap / train |
|---|---|---:|---:|---:|---:|
| individual | MSE | 94,997 | 95,755 | 92,700 | −3.2 % |
| individual | E[U] | 95,436 | 96,789 | 92,958 | −4.0 % |
| individual | weighted CVaR | 182,855 | 172,656 | 169,705 | −1.7 % |
| cluster | MSE | 103,107 | 100,987 | 113,874 | +12.8 % |
| cluster | E[U] | 102,104 | 99,844 | 114,522 | +14.7 % |
| cluster | weighted CVaR | 146,009 | 144,139 | 162,103 | +12.5 % |
| portfolio | MSE | 87,440 | 85,415 | 96,980 | +13.5 % |
| portfolio | E[U] | 85,660 | 83,402 | 94,009 | +12.7 % |
| portfolio | weighted CVaR | 132,444 | 131,412 | 141,526 | +7.7 % |

Observations:

- **Expected loss.** The two blocks have nearly the same expected loss: 2,066,785 on train and 2,049,786 on test (−0.8 %); the full sample has 2,061,394.
- **Sign of the gap.** In the portfolio and cluster scopes, `cvar_uncovered` and `expected_uncovered` are higher out of sample for every objective. In the individual scope they're lower out of sample for every objective.
- **Size of the gap.** At 15 bins the relative CVaR gap is +9.0 % to +11.5 % in the portfolio scope and +19.3 % to +20.2 % in the cluster scope.
- **Ranking within a scope.** At 15 bins, weighted CVaR has the lowest `cvar_uncovered` both in sample and out of sample, in each scope. Its `expected_uncovered` is the highest, in and out of sample.
- **Other KPIs.** Correlation stays between 0.987 and 0.993 on both blocks. The test payout-to-loss ratio is between 0.9946 and 1.0057 against 1.0 on train: the budget binds on train and is evaluated as is on test. `rmse_residual` is higher on test in the portfolio scope (+7.3 % to +8.5 %) and the cluster scope (+15.4 % to +17.7 %), and within ±1.1 % in the individual scope.

Config hashes of the 15-bin runs (holdout, then full; full equals the thesis baseline's single-run hash because only labels and the output directory differ):

| Scope | Objective | Holdout `config_hash` | Full `config_hash` |
|---|---|---|---|
| individual | MSE | `sha256:244a395f10c42942c884f335559c4194ad16f639ad674becaf55923314ef5d15` | `sha256:3eec7ac6ed4dac0540d409a87893d4e000f5e52c006833efd2f3e2db6e85d24c` |
| individual | E[U] | `sha256:a659efe1ab3e53df3a2b15f0c52c59fa7eb66cee3a9549ededd6616d178e342b` | `sha256:8e3e9ca927bfacf4ed5170f7498c7b8d3fbb12d9b55a2aa1ef6ace7fc20a86bd` |
| individual | weighted CVaR | `sha256:3be385a4d75da46c0eefe4e487e9e723ba8202f8c369af09297c90eda81f0d53` | `sha256:3666438e3ea961bf33412f3c1c6901baf1c80327f49ce186da0218620812dba5` |
| cluster | MSE | `sha256:bce19bf3cffa91569d8d55697225b0532d24c4be36fd535f9608c30184d956b3` | `sha256:9cedd23cf2511120da05d19a683dd783c25b34a90ad93484a946ca1837401d81` |
| cluster | E[U] | `sha256:b23ca4e70c665a99c01850a3abca26eac07f3b9aac097d8fb055bbb36f48fb63` | `sha256:5ebf4bdfcedf9a1b65338e0866cfb2d813b53d5c5102d321ed0a35703686fda9` |
| cluster | weighted CVaR | `sha256:169f6f111fa0e807d363ec766add5c72448c3739f89ac98d9778b5073092bbd1` | `sha256:e85db2607bc6c8f8530baa4cfbf55ece989c8e25d210693bd215fd59222254f2` |
| portfolio | MSE | `sha256:647eb3262f47cedc7fb5317a9c537de35db7da4586dda484102b701785084bb5` | `sha256:e134d0bea41f0bbf99b12a8817b161a2d3acb92a7bd38f9a8ea756322ac2178c` |
| portfolio | E[U] | `sha256:b1f21efe789c9bf64dd0295e58ab92df2746ab588ed50f344f80c925815f3c37` | `sha256:bbe10df69cbe6dc84bc6b8fca70e57eda14a20389e4ef954416232908c27236b` |
| portfolio | weighted CVaR | `sha256:54fd16fa96fecf92f58b51085be8b58d9db0a1f538a36632f1bf184baa25baa3` | `sha256:71718bcbd1d5384f70fba6472d89e3f846a62160f728ee6663e08a2522d27a6b` |

The hashes of the other bin counts and of the k-fold runs are in the CSV files.

## 2. Gap as a function of `n_bins` and scope (holdout)

`cvar_uncovered` gap (test − train), in thousands:

| Scope | Objective | 5 | 10 | 15 | 20 | 25 |
|---|---|---:|---:|---:|---:|---:|
| individual | MSE | +436 | +82 | −17 | +100 | −84 |
| individual | E[U] | +378 | +158 | −19 | +121 | +26 |
| individual | weighted CVaR | +132 | −93 | −174 | −62 | −121 |
| cluster | MSE | −257 | −6 | +333 | +59 | +247 |
| cluster | E[U] | −214 | +53 | +338 | +104 | +174 |
| cluster | weighted CVaR | −61 | +48 | +250 | +161 | +257 |
| portfolio | MSE | +772 | +536 | +169 | +114 | +332 |
| portfolio | E[U] | +863 | +528 | +160 | +276 | +309 |
| portfolio | weighted CVaR | +791 | +277 | +98 | +249 | +149 |

`cvar_uncovered` on train and test, portfolio scope, in thousands:

| Objective | | 5 | 10 | 15 | 20 | 25 |
|---|---|---:|---:|---:|---:|---:|
| MSE | train | 2,679 | 1,713 | 1,469 | 1,400 | 1,392 |
| MSE | test | 3,451 | 2,249 | 1,638 | 1,513 | 1,725 |
| E[U] | train | 2,611 | 1,699 | 1,470 | 1,414 | 1,398 |
| E[U] | test | 3,474 | 2,228 | 1,630 | 1,690 | 1,707 |
| weighted CVaR | train | 2,340 | 1,315 | 1,081 | 998 | 982 |
| weighted CVaR | test | 3,131 | 1,591 | 1,179 | 1,247 | 1,131 |

Observations:

- **Train CVaR.** In-sample `cvar_uncovered` falls as `n_bins` grows, from 5 to 25, in every scope and for every objective, with one exception: individual × weighted CVaR rises slightly from 20 to 25 bins (1,186,868 → 1,195,978).
- **Test CVaR.** Out-of-sample `cvar_uncovered` falls from 5 to 15 bins in every scope and for every objective. Beyond 15 bins it is not monotone. In the portfolio scope it rises again for at least one step after 15 bins for every objective, while train keeps falling.
- **Gap and `n_bins`.** The gap is not monotone in `n_bins` in any scope. It is largest at 5 bins in the portfolio scope (every objective) and for individual × MSE and individual × E[U], and negative at 5 bins in the cluster scope (every objective).
- **`expected_uncovered`.** Its gap is positive at every bin count in the portfolio and cluster scopes, except cluster × MSE at 10 bins (−689). In the individual scope it is positive at 5 and 10 bins and within ±6 thousand from 15 bins on (`holdout_gap.csv`).

## 3. Five-fold year blocks (15 bins)

Expected loss of each 2,000-year test block (the same for every run):

| Fold | Years | E[L] test | E[L] test − train |
|---:|---|---:|---:|
| 0 | 0–1,999 | 2,150,416 | +112,089 |
| 1 | 2,000–3,999 | 2,032,064 | −35,874 |
| 2 | 4,000–5,999 | 1,922,699 | −168,484 |
| 3 | 6,000–7,999 | 2,377,403 | +406,026 |
| 4 | 8,000–9,999 | 1,787,070 | −348,695 |

`cvar_uncovered` gap (test − train) per fold, portfolio scope, in thousands:

| Objective | 0 | 1 | 2 | 3 | 4 |
|---|---:|---:|---:|---:|---:|
| MSE | +689 | +812 | −215 | +542 | −419 |
| E[U] | +690 | +676 | −329 | +516 | −452 |
| weighted CVaR | +440 | +769 | −93 | +465 | −190 |

Observations:

- **Block-to-block spread.** The test blocks' expected loss ranges from 1.79 to 2.38 million, against 2.06 million on all years.
- **Sign across folds.** The per-fold CVaR gap changes sign across folds in all three scopes. In the portfolio scope it is negative in folds 2 and 4 for every objective; those are the folds whose test block has the lowest expected loss. Fold 1's gap is positive although its test block's expected loss is slightly below train.
- **Weighted CVaR.** In the portfolio scope, weighted CVaR has the smallest absolute CVaR gap of the three objectives in folds 0, 2, 3 and 4, and the lowest test `cvar_uncovered` in every fold. The same holds in the individual and cluster scopes for test `cvar_uncovered` in every fold (`kfold_gap.csv`).
- **Magnitude.** Across scopes and objectives the per-fold CVaR gaps range from −505,215 (individual × MSE, fold 4) to +894,183 (cluster × E[U], fold 0), wider than the holdout gaps of section 1 (−173,819 to +337,813). Telling calibration error (overfitting) apart from block-to-block variation of the loss sample needs the bootstrap CIs of MAR-23.

## Caveats

- **Basis.** `cvar_uncovered` is the thesis's event-conditional tail, recomputed per sample. Its probabilities are rescaled within each sample's rows, so train and test CVaRs condition on different event sets. The annual basis (MAR-24) will give tails over years instead.
- **Noise layer.** Noise is drawn once on the full set, before the split. Each event's 13 copies stay in one block.
- **Point values.** One holdout split and one 5-fold partition are reported, with no CIs. Section 3 shows that the choice of test block moves these numbers by amounts comparable to the gaps themselves.
