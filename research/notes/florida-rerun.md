# Florida rerun: RQ1, RQ2 and the combination on the D2 portfolio

- Issue: [MAR-202](https://linear.app/marc-prinzing/issue/MAR-202/c1-f1-florida-rerun-rq1-rq2-and-the-combination-on-the-d2-portfolio) (C1-F1, split from MAR-152 item 4). Internal research note, written by a worker agent on 2026-11-01. **Observations only**; the interpretation is the owner's. The owner revisits the RQ2 publication rule after this rerun (C1.md, "Publication rule").
- **Publication rule** (C1.md): every statement here involving joint calibration (RQ2 and the combination) is method-only in external outputs. Nothing in this note is for external use as a comparative claim.
- **MAR-118 Q5 is answered by MAR-160**: the vulnerability prior is recentred on the base impact function in the excess form, with the expected loss matched to the no-draws build (`s` = 0.690130, median `v_half` 86.293 m/s; `research/notes/d2-florida-eventset.md`). Both EventSets of this rerun carry that prior.
- Scripts: `research/scripts/florida_rerun.py` (runs, bootstraps, contrasts; reuses the workers of `c1_checkpoint.py`, `c1_rq2.py` and `c1_combination.py`, unchanged) and `research/scripts/florida_rerun_tables.py` (committed CSVs and `tables.md`). Configs and plan: `research/configs/florida/` (`florida_main.yaml`, `florida_cic75.yaml`, `plan.yaml`).
- Data: `research/data/florida-rerun/`. `runs.csv` maps every design to its full `config_hash` (or `derived:` id) and `run_id`; `grid.csv`, `contrasts.csv`, `contrasts_train.csv`, `cluster_parts.csv`, `entity_payouts.csv`, `clusters.csv`, `premiums.csv`, `premium_split.csv`, `kfold_folds.csv` and `guard.csv` hold every number below; `tables.md` (T1–T13) holds every table, generated. Hashes in this note are the first 12 hex digits of the `sha256:` config hash.
- Result store (not committed; kept for MAR-203 and MAR-204): `results/florida/store` in this worktree, with the EventSets in `results/florida/eventsets/` and the full tables in `results/florida/full/`.

## 1. The question

C1 (`research/checkpoints/C1.md`) answered RQ1 and RQ2 on the 9-asset thesis portfolio, and MAR-182 (`research/notes/c1-combination.md`) the combination; both said the thesis portfolio is a weak test of joint calibration (C1.md 7b, item 5; observation 33). This note reruns the three views on the paper portfolio D2, Florida's 67 counties with the State of Florida as the single owner, for both indices:

- **RQ1 (tail):** within each scope, does the weighted-CVaR design lower the owner's tail shortfall against the MSE and E[U] designs, out of sample?
- **RQ2 (joint calibration):** within each objective, does calibrating the 67 counties jointly (portfolio scope, or cluster scope with a cluster index) lower the owner's total shortfall against calibrating each county on its own, at the same budget? With the cluster index separated from the joint calibration and, under the load, the portfolio premium split into cross-coverage and pricing diversification.
- **Combination:** a portfolio-scope weighted-CVaR design against individual MSE, individual weighted CVaR and portfolio MSE, and the interaction (does the tail gain depend on the scope, and the joint gain on the objective?).

## 2. Setup of every number

| Item | Setting |
|---|---|
| Portfolio | D2 (SPEC §6.6): Florida's 67 counties, values from LitPop `LitPop_150arcsec_USA` v3 (total 4.893 × 10¹² USD, reference year 2018), the State of Florida as the single owner (a documented proxy; `research/notes/d2-paper-portfolio.md`). Monroe County kept with its exposure gap (MAR-118 Q2) |
| Hazard and loss | IRIS NA 10,000 years, 13,902 storms; loss on the 7,817 LitPop cells, summed per county; Emanuel USA impact function with 10 `v_half` draws per storm from the recentred prior (MAR-160: `s` = 0.690130, median 86.293 m/s; EAL 7.616 × 10⁹ USD per year, equal to the no-draws build's). 139,020 rows (storm × draw); an annual outcome is a (year, draw) slot, 100,000 slots |
| Index (a) | Wind at the county's value-weighted centroid (m/s). EventSet `florida-counties-iris-vulnerability`, content hash `sha256:30b1723182e5bb3eef8abae0d0edcc605918aaf90e03b24bb09037a4c6416472`. Config `research/configs/florida/florida_main.yaml`: threshold 20 m/s on the index (keeps 53,240 rows; it drops 3,305 USD per year of expected loss, 4.3 × 10⁻⁷ of the EAL, recorded in the EventSet's filter record; the largest dropped row loss is 75.5 × 10⁶ USD, at a county whose centroid wind was below 20 m/s while some of its cells had loss); step payout, 15 bins on [20, 70] m/s |
| Index (b) | Cat-in-a-circle, 75 km around the centroid, Saffir-Simpson category 0–5 (MAR-145, radius from MAR-118 Q6). EventSet `florida-counties-iris-cat-in-circle-75km-vulnerability`, content hash `sha256:70af1fed283d9e800574c01181ff4e3ee40dee7ab227a890145d7744e8328a60`; the same loss matrix as (a). Config `research/configs/florida/florida_cic75.yaml`: no threshold; step payout with one bin per category (breakpoints 0, 1, …, 6), as C1's cat-in-a-circle F-12 runs |
| Basis-risk model | No thesis noise layer: the basis risk is the index (a point wind, or a category in a circle) against the cell-level loss with vulnerability draws |
| Payout | `below_attachment: zero` (Marc, 2026-11-01; MAR-170, MAR-178): an index below the attachment pays nothing. Every run is in a store created after `f51e395` (MAR-178), so no cache hit carries older parameters. For index (b) the attachment is category 0, so no index lies below it |
| Basis | `annual` (SPEC §6.2): U_y = Σ_{e∈y}(L_e − π_e)⁺ per (year, draw) slot; CVaR over slots |
| Splits | **Holdout**, train fraction 0.7: calibrate on years 0–6,999 (**train**, in sample), evaluate on years 7,000–9,999 (**test**). **Pooled 5-fold** (MAR-151): year blocks of 2,000; every year evaluated by the design that did not see it, κ 1 only |
| Scopes | individual (67 design problems); cluster (3 clusters, thesis Ward on the train years, `beta_tail` 0.9, value-weighted mean index per cluster: a different index); portfolio (1 problem, 67 point indices). The cluster count is the C1 main line's, kept for the mirror; an `n_clusters` sweep is MAR-152 item 6 |
| Designs | MSE; E[U]; weighted CVaR α 0.9 at design β 0.99 and 0.995 |
| Pricing | `pure` (premium = E[π]); `cost_of_capital` r 0.06, q 0.99 (premium = (1 − r)·E[π] + r·CVaR₀.₉₉(π)) |
| Budget | premium ≤ κ·E[L] on the train years, κ ∈ {0.5, 1, 1.5}. Individual: each county budgets its stand-alone premium; joint: the aggregate premium (C1.md 6b.1) |
| KPIs | Portfolio level: the owner's annual uncovered loss summed over the 67 counties; CVaR at KPI β 0.95, 0.99, 0.995, E[U], E[π], budget use. Per county only payout and loss (no per-county KPI of a joint design: MAR-98, MAR-100) |
| Intervals | Year-block bootstrap, B 1000, seed 0, level 0.9, percentile intervals. Holdout: **one** resample of the test years per variant, shared by every design of that (index, pricing, κ), so all differences are paired. Pooled: one resample of all 10,000 years shared by every design of an (index, pricing) |
| Pairing across scopes | C1 section 6b.1's method (`c1_rq2.portfolio_rows`, then `bootstrap.paired_difference` unchanged), as in MAR-158 and MAR-182. MAR-179 merged while the runs were solving; the holdout phase computes every joint − individual pair also with `paired_difference(a.portfolio_rows(), b.portfolio_rows(), across_scopes=True)` and requires the same differences and intervals (rtol 1e-12) |
| Derived designs | `cluster_separate` (C1.md 6b.6; MAR-180 is not merged): the cluster scope's clusters and index, each cluster its own problem with budget κ·E[L_cluster]; solved by the script, `derived:` id. `portfolio_matched` (C1.md 6b.5): the portfolio problem with budget P(Σπ) ≤ A, A = the aggregate premium of the individual design's summed payout on the train years; a runner run (loading A / E[L]) with a config hash of its own |
| Solver | `solve.DEFAULT_POLICY` |
| Code | Branch of MAR-202 on `origin/main` 9051326, with `origin/main` 231d6cf (MAR-173, MAR-179) merged while the runs solved; package `0.1.0.dev0`. MAR-173 does not change run ids (manifest only) |

OBSERVATIONS
