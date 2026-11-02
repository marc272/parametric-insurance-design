# Florida rerun: RQ1, RQ2 and the combination on the D2 portfolio

- Issue: MAR-202 (C1-F1, split from MAR-152 item 4). Internal research note, written by a worker agent on 2026-11-01. **Observations only**; the interpretation is the owner's. The owner revisits the RQ2 publication rule after this rerun (C1.md, "Publication rule").
- **Publication rule** (C1.md): every statement here involving joint calibration (RQ2 and the combination) is method-only in external outputs. Nothing in this note is for external use as a comparative claim.
- **MAR-118 Q5 is answered by MAR-160**: the vulnerability prior is recentred on the base impact function in the excess form, with the expected loss matched to the no-draws build (`s` = 0.690130, median `v_half` 86.293 m/s; `research/notes/d2-florida-eventset.md`). Both EventSets of this rerun carry that prior.
- Scripts: `research/scripts/florida_rerun.py` (runs, bootstraps, contrasts; reuses the workers of `c1_checkpoint.py`, `c1_rq2.py` and `c1_combination.py`, unchanged) and `research/scripts/florida_rerun_tables.py` (committed CSVs and `tables.md`). Configs and plan: `research/configs/florida/` (`florida_main.yaml`, `florida_cic75.yaml`, `plan.yaml`).
- Data: `research/data/florida-rerun/`. `runs.csv` maps every design to its full `config_hash` (or `derived:` id) and `run_id`; `grid.csv`, `contrasts.csv`, `contrasts_train.csv`, `cluster_parts.csv`, `entity_payouts.csv`, `clusters.csv`, `premiums.csv`, `premium_split.csv`, `kfold_folds.csv` and `guard.csv` hold every number below; `solver_check.csv` holds the solver check (T14); `tables.md` (T1–T15) holds every table, generated. Hashes in this note are the first 12 hex digits of the `sha256:` config hash.
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
| Splits | **Holdout**, train fraction 0.7: calibrate on years 0–6,999 (**train**, in sample), evaluate on years 7,000–9,999 (**test**). **Pooled 5-fold** (MAR-151): year blocks of 2,000; every year evaluated by the design that did not see it; κ 1 and **pure pricing only** (the CoC k-fold runs are deferred for compute, MAR-223) |
| Scopes | individual (67 design problems); cluster (3 clusters, thesis Ward on the train years, `beta_tail` 0.9, value-weighted mean index per cluster: a different index); portfolio (1 problem, 67 point indices). The cluster count is the C1 main line's, kept for the mirror; an `n_clusters` sweep is MAR-152 item 6 |
| Designs | MSE; E[U]; weighted CVaR α 0.9 at design β 0.99 and 0.995 |
| Pricing | `pure` (premium = E[π]); `cost_of_capital` r 0.06, q 0.99 (premium = (1 − r)·E[π] + r·CVaR₀.₉₉(π)) |
| Budget | premium ≤ κ·E[L] on the train years, κ ∈ {0.5, 1, 1.5}. Individual: each county budgets its stand-alone premium; joint: the aggregate premium (C1.md 6b.1) |
| KPIs | Portfolio level: the owner's annual uncovered loss summed over the 67 counties; CVaR at KPI β 0.95, 0.99, 0.995, E[U], E[π], budget use. Per county only payout and loss (no per-county KPI of a joint design: MAR-98, MAR-100) |
| Intervals | Year-block bootstrap, B 1000, seed 0, level 0.9, percentile intervals. Holdout: **one** resample of the test years per variant, shared by every design of that (index, pricing, κ), so all differences are paired. Pooled: one resample of all 10,000 years shared by every design of an (index, pricing) |
| Pairing across scopes | C1 section 6b.1's method (`c1_rq2.portfolio_rows`, then `bootstrap.paired_difference` unchanged), as in MAR-158 and MAR-182. MAR-179 merged while the runs were solving; the holdout phase computes every joint − individual pair also with `paired_difference(a.portfolio_rows(), b.portfolio_rows(), across_scopes=True)` and requires the same differences and intervals (rtol 1e-12) |
| Derived designs | `cluster_separate` (C1.md 6b.6; MAR-180 is not merged): the cluster scope's clusters and index, each cluster its own problem with budget κ·E[L_cluster]; solved by the script, `derived:` id. `portfolio_matched` (C1.md 6b.5): the portfolio problem with budget P(Σπ) ≤ A, A = the aggregate premium of the individual design's summed payout on the train years; a runner run (loading A / E[L]) with a config hash of its own |
| Solver | `solve.DEFAULT_POLICY` |
| Code | Branch of MAR-202 on `origin/main` 9051326, with `origin/main` 231d6cf (MAR-173, MAR-179) merged while the runs solved, and 15742bc (MAR-198) during the index (b) solves; package `0.1.0.dev0`. All 264 runs and every bootstrap were computed on that code. `origin/main` e9baf39 (MAR-217 among others) was merged afterwards: every run id is unchanged (the store is complete under the merged code) and the regenerated tables are byte-identical. MAR-173 does not change run ids (manifest only) |

## 3. How to read the observations

All 264 runs of the plan are in the store (144 holdout: 2 indices × 2 pricings × 3 κ × 3 scopes × 4 designs; 120 k-fold: 2 indices × 3 scopes × 4 designs × 5 folds, pure, κ 1), with the 48 derived `cluster_separate` designs and the 24 `portfolio_matched` runs. T15 lists every config hash.

Every number below is: D2 portfolio (67 counties, the State as owner), annual basis, basis risk from the index against the cell-level loss with vulnerability draws (no noise layer), `below_attachment: zero`, the index stated ((a): wind at the county centroid, 15 bins on [20, 70] m/s, threshold 20 m/s; (b): cat-in-a-circle 75 km, one bin per category), the pricing and κ stated, and the split stated: **holdout** (train years 0–6,999, test 7,000–9,999) or **pooled** 5-fold (pure, κ 1). Differences are paired, with 90 % year-block intervals; `*` marks an interval that excludes zero. Config hashes are in `tables.md` next to every row (T1–T10, T14, T15) and in full in `runs.csv`.

Caveats that apply to every cross-scope (RQ2 and combination) difference below:

- **Individual-scope ranges.** Each compares a joint design with **one** individual design: individual-scope near-optimal ranges are not measured yet for Florida (MAR-203), and individual designs are not unique either (MAR-198).
- **Joint-scope optima.** The Florida cross-scope differences have not been checked for non-unique joint optima yet; on the thesis portfolio, second optima of the joint designs changed 131 of 720 C1 verdicts (MAR-206, `research/notes/c1-rq2-sensitivities.md`). The check (families (b) and (e) of `research/scripts/c1_rq2_sensitivities.py`) is a follow-up.
- **Cluster scope.** It confounds the cluster index (value-weighted mean index of 3 clusters) with the joint calibration: MAR-180 has not merged. T6 splits cluster − individual as C1 section 6b.6 does, with `cluster_separate`, which keeps the cluster index.
- **Solver check (T14).** Two stored designs are not optimal: the index (b) k-fold portfolio MSE designs of folds 0 and 4 (pure, κ 1), stored by OSQP with status `optimal`, a zero payout and an objective 66–67 % above a CLARABEL re-solve. Every number that uses them (the index (b) pooled portfolio MSE KPIs and the pooled contrasts with that design as a term) reads "not optimal (T14)" in the tables and is left out here. Nothing else is affected: the other 53 checked designs agree within 10⁻⁵, and no holdout design is affected.

## 4. RQ1: the tail design within each scope

**Index (a), holdout**

1. **Pure pricing, κ 1 (T2).** At the KPI β equal to the design β, weighted CVaR minus MSE and minus E[U] on test is −2.8 to −9.2 % in the individual scope, −8.0 to −16.4 % in the cluster scope and −15.9 to −19.2 % in the portfolio scope; all 12 intervals exclude zero. The train differences are −3.7 to −23.3 %. Test E[U] rises by +0.9 to +4.1 % (individual), +1.8 to +19.1 % (cluster) and +13.3 to +18.6 % (portfolio); 9 of those 12 intervals exclude zero.
2. **CoC r 0.06, κ 1 (T2).** Against MSE the test differences are −1.4 to +2.4 %; one interval excludes zero, individual β 0.99 at +2.4 % [+0.2, +4.5]. Against E[U] they are −3.5 to −5.5 % with intervals below zero in 5 of 6 cells; the exception is individual β 0.99, +0.0 % [−0.8, +0.8]. The tail design's test E[U] is higher than E[U]'s by +6.3 to +24.6 %.
3. **Across κ (T3).** Under pure pricing at κ 0.5 the tail design against MSE is within −3.4 to +1.7 % at the matched KPI β (individual β 0.99 at KPI 0.99: +1.7 % [+0.7, +2.8]). At κ 1.5 it is −31.5 to −41.8 %: the pure MSE designs use 0.67 of the budget at κ 1.5 (individual 0.666, portfolio 0.672, cluster 0.580) and 1.00 at κ 0.5 (`grid.csv`, `budget_use`), while the tail designs use all of it. Against E[U] at κ 1.5 the tail design is −1.3 to −20.3 %.
4. **At KPI 0.95 (T3),** below the design β, the tail design's test CVaR against E[U]'s is higher in 21 of the 24 (pricing, κ ≥ 1, scope, design) cells, 17 of them with an interval above zero, up to +18.8 % (pure, κ 1.5, portfolio, β 0.995).

**Index (b), holdout**

5. **Pure pricing, κ 1 (T2).** Against MSE the tail design is −11.0 to −14.1 % on test in every scope (all 6 intervals below zero; train −9.7 to −13.7 %). Against E[U]: −2.4 % and −4.0 % (individual), −0.6 % and −0.3 % (cluster, intervals contain zero), −10.4 % and −11.4 % (portfolio). The individual and cluster tail designs also have a lower test E[U] than MSE (−4.6 to −9.8 %; 3 of 4 intervals below zero); in the portfolio scope their E[U] is +3.8 % and +7.5 % above MSE's. Against E[U], test E[U] rises by +0.1 to +11.5 %.
6. **CoC r 0.06, κ 1 (T2).** Against MSE −0.8 to +1.3 % (one interval excludes zero: individual β 0.995, +0.3 % [+0.1, +0.5]). Against E[U]: +0.0 % and −1.4 % (individual, intervals contain zero), −1.8 % and −2.4 % (cluster), −3.9 % and −4.4 % (portfolio); the last four intervals lie below zero.
7. **Across κ (T3).** Pure, against MSE at the matched KPI β: −0.9 to −3.2 % at κ 0.5 (3 of 6 intervals below zero), −25.0 to −30.3 % at κ 1.5, where the pure MSE designs use 0.68 of the budget (0.680–0.683 in every scope) and the tail designs all of it. Under CoC, at the matched KPI β, every scope stays within −5.3 to +1.3 % at every κ.

**Pooled 5-fold (pure, κ 1)**

8. **Index (a) (T2).** Weighted CVaR against MSE and E[U] at the matched KPI β: −3.3 to −9.6 % (individual), −7.8 to −19.3 % (cluster), −12.5 to −17.7 % (portfolio); all 12 intervals below zero, each within 5 points of the holdout test value. Pooled E[U] rises by +0.8 to +23.4 %.
9. **Index (b) (T2).** Against MSE: −10.0 and −10.3 % (individual), −12.5 and −10.8 % (cluster); the portfolio cells use the two non-optimal fold designs (T14). Against E[U]: −1.8 and −3.4 % (individual), −0.6 and −0.3 % (cluster, intervals contain zero), −8.1 and −9.3 % (portfolio).

## 5. RQ2: joint against individual calibration within each design

Every difference in this section compares a joint design with one individual design (section 3: individual-scope ranges not measured yet, MAR-203; joint optima not checked, MAR-206 follow-up). Cluster rows confound the cluster index with the joint calibration (MAR-180 not merged).

**Index (a), holdout**

10. **Portfolio − individual, κ 1 (T4).** Under pure pricing, test CVaR₀.₉₉: MSE −2.5 % [−4.4, −0.7], E[U] +1.3 % [−1.4, +3.9], weighted CVaR β 0.99 −13.7 % [−19.4, −8.1], β 0.995 −9.1 % [−14.3, −3.6]; train −0.7 to −15.1 %. Under CoC r 0.06: −4.3 to −9.6 %, all four intervals below zero; train −3.3 to −8.4 %.
11. **Across κ and KPI β (T5, T11).** In T11's count of RQ2 alone (portfolio − individual for the MSE and E[U] designs, both pricings, every κ and KPI β), 30 of 36 test intervals lie below zero and none above. In every row of T5 the portfolio − individual test difference is within 4.2 points of the train difference (largest gap: pure, κ 1.5, weighted CVaR β 0.99, train −19.6 %, test −15.4 %).
12. **Test E[U] of the portfolio designs (T4).** Pure: +12.5 % and +14.6 % for the two tail designs (intervals above zero), −0.5 % and +1.4 % for MSE and E[U]. CoC: −4.3 to −11.7 %, all below zero.
13. **Cluster − individual, κ 1 (T4; cluster index and joint calibration confounded).** Pure: +4.9 to +17.2 % on test (3 of 4 intervals above zero), +0.7 to +14.7 % on train. CoC: −0.9 to −5.1 % (2 of 4 below zero). T6 splits it (pure): the index part (`cluster_separate` − individual) is +10.2 to +23.3 %, every interval above zero; the joint part (cluster − `cluster_separate`) is −0.7 to −4.9 %, two intervals below zero.
14. **Payout per county (T7).** Every pure individual design pays each county its own expected loss (E[π_i]/E[L_i] 0.97–1.00). The portfolio designs do not: the pure weighted-CVaR designs pay less than 1 % of the expected loss to 26 (β 0.99) and 33 (β 0.995) of the 67 counties and more than twice it to 7; the 5 largest-loss counties hold 48.9 % of the train loss and receive 52.9 % and 58.8 % of the payout. Escambia (4.0 % of the loss) receives 0.02 and 0.00 of its expected loss there, against 0.92 under portfolio MSE. In the cluster scope the weighted-CVaR designs pay nothing to cluster C3 (33 counties, 8.3 % of the train loss). Each joint design's split across counties is one member of its optimal set (MAR-100, MAR-161 F8).
15. **The premium split under the load (T8, CoC r 0.06).** The pricing-diversification credit 1 − A/S is 10.8–33.8 % (largest for weighted CVaR β 0.99, 31.5–33.8 %). Of portfolio − individual on test, pricing diversification (portfolio − `portfolio_matched`) is −1.0 to −8.7 %, every interval below zero; cross-coverage (`portfolio_matched` − individual) is −0.0 to −5.2 %, 7 of 12 intervals below zero. On train, cross-coverage of the E[U] design is +0.3 to +0.8 %.

**Index (b), holdout**

16. **Portfolio − individual, κ 1 (T4).** Pure, test CVaR₀.₉₉: MSE −5.9 % [−8.2, −3.6], E[U] −0.1 % [−2.5, +2.4], weighted CVaR β 0.99 −8.2 % [−12.7, −3.8], β 0.995 −6.7 % [−11.9, −1.7]; train −2.1 to −10.4 %. CoC: −4.0 to −7.8 %, all four intervals below zero; train −4.3 to −7.8 %. Test E[U]: pure −7.4 % (MSE), −0.8 % (E[U]), +6.6 % and +9.1 % (tail designs); CoC −4.7 to −12.4 %, all below zero.
17. **Across κ and KPI β (T5, T11).** RQ2 alone (portfolio − individual, MSE and E[U] designs): 27 of 36 test intervals below zero, none above. In T5, portfolio − individual is below zero on test in every CoC row (−1.5 to −11.5 %); under pure pricing the E[U] design's difference is −0.4 to +0.9 % at every κ (intervals contain zero).
18. **Cluster − individual, κ 1 (T4; confounded).** Pure: −1.7 to +3.5 % on test (MSE +2.5 % [+0.8, +4.3] the one interval excluding zero). CoC: −5.7 to −7.4 %, all four below zero. T6: under pure pricing the index part is +7.0 % [+5.2, +8.6] for MSE and −0.4 to +1.2 % for the others, the joint part −4.2 % [−5.6, −2.8] for MSE and −1.3 to +2.2 % for the others; under CoC the index part is −4.3 to −5.6 % and the joint part −1.5 to −2.2 %, all eight intervals below zero.
19. **Payout per county (T7).** The pure portfolio weighted-CVaR designs pay less than 1 % of the expected loss to 43 (β 0.99) and 42 (β 0.995) of the 67 counties, and the 5 largest-loss counties receive 56.1 % and 54.7 % of the payout (48.9 % of the loss). Orange (9.8 % of the loss) receives 0.01 (MSE), 0.36 (E[U]) and 0.00 (both tail designs) of its expected loss; Hillsborough 0.60–2.24. Index (b)'s clusters differ from index (a)'s: 17, 19 and 31 counties with 67.3, 31.1 and 1.6 % of the train loss; the tail designs pay cluster C3 0.10 of its expected loss.
20. **The premium split (T8).** The credit 1 − A/S is 28.5–39.8 %. Pricing diversification on test is −1.8 to −9.2 %, every interval below zero; cross-coverage is −2.8 to +0.3 %, 7 of 12 intervals excluding zero (6 below, one above: E[U] at κ 0.5, +0.3 % [+0.1, +0.5]).

**Pooled 5-fold (pure, κ 1)**

21. **Index (a) (T4, T12).** Portfolio − individual, pooled CVaR₀.₉₉: MSE −1.0 % [−2.1, −0.0], E[U] +0.1 % [−1.2, +1.2], weighted CVaR −9.5 % and −6.3 % (intervals below zero). Cluster − individual: +3.5 to +15.7 % (3 of 4 above zero). Per fold (T12), portfolio − individual is −15.0 to −0.3 % on the training blocks and −13.0 to +0.8 % on the held-out blocks.
22. **Index (b) (T4, T12).** Portfolio − individual: E[U] +0.1 % [−1.2, +1.4], weighted CVaR −6.3 % and −4.6 % (below zero); MSE uses the two non-optimal fold designs (T14). Cluster − individual: −3.4 to +0.6 % (E[U] −3.4 % [−5.3, −1.8] the one interval excluding zero at KPI 0.99). Per fold, the E[U] and tail designs are −10.5 to −1.7 % on training blocks and −9.5 to +2.5 % on held-out blocks.

## 6. The combination

Every difference in this section involves joint calibration and so carries the caveats of section 3 (individual-scope ranges not measured yet, MAR-203; joint optima not checked, MAR-206 follow-up).

**Index (a), holdout**

23. **Portfolio weighted CVaR against the three alternatives, κ 1 (T9).** Pure: against individual MSE −18.1 % (β 0.99) and −20.1 % (β 0.995) on test, against individual weighted CVaR −13.7 % and −12.0 %, against portfolio MSE −15.9 % and −17.7 %; all six intervals below zero. The E[U] cost against individual MSE is +13.6 % and +18.1 %. CoC r 0.06: against individual MSE −7.4 % and −4.5 %, against individual weighted CVaR −9.6 % and −4.8 % (all below zero), against portfolio MSE −1.4 % [−2.6, +0.1] and +0.3 % [−2.6, +2.7].
24. **Interaction (T10, base MSE).** Pure: −18.1 % = −5.0 % (RQ1 alone) + −2.5 % (RQ2 alone) + interaction −10.5 % [−15.3, −5.5] (β 0.99), and −20.1 % = −9.2 % + −2.9 % + −8.0 % [−12.4, −3.4] (β 0.995). For E[U] the interaction is +13.1 % and +15.6 % (above zero). CoC r 0.06: interaction −3.7 % [−5.6, −1.7] (β 0.99) and +0.1 % [−2.6, +2.2] (β 0.995); for E[U] +5.3 % and +5.0 %.
25. **Across the grid (T11).** Interaction cells with an interval below zero: 35 of 72 in the portfolio scope (12 above), 28 of 72 in the cluster scope (18 above).

**Index (b), holdout**

26. **Against the three alternatives, κ 1 (T9).** Pure: against individual MSE −19.0 % and −17.6 %, against individual weighted CVaR −8.2 % and −7.4 %, against portfolio MSE −14.0 % and −14.1 %; all six intervals below zero. Against individual MSE the test E[U] is −3.9 % and −0.4 % (intervals contain zero). CoC: −6.6 % and −5.7 % against individual MSE, −7.8 % and −6.0 % against individual weighted CVaR (all below zero), −0.2 % and −0.8 % against portfolio MSE (intervals contain zero).
27. **Interaction (T10).** Pure: −19.0 % = −11.8 % + −5.9 % + interaction −1.4 % [−3.9, +1.4] (β 0.99), and −17.6 % = −11.0 % + −4.1 % + −2.5 % [−6.0, +1.3] (β 0.995). For E[U] the interaction is +13.3 % and +15.7 % (above zero). CoC: −1.5 % [−2.5, −0.4] and −1.1 % [−2.0, +0.0]; for E[U] +1.5 % and +3.6 % (above zero).
28. **Across the grid (T11).** Interaction cells below zero: 33 of 72 (portfolio, 10 above) and 17 of 72 (cluster, 7 above). "Both" (joint tail design against individual base design): 64 of 72 below zero and none above (portfolio).

**Pooled 5-fold (pure, κ 1)**

29. **Index (a) (T9, T10).** Against individual MSE −15.4 % and −18.8 %, against individual weighted CVaR −9.5 % and −10.1 %, against portfolio MSE −14.5 % and −17.7 %; all below zero. Interaction −7.8 % [−10.1, −5.4] and −7.8 % [−10.2, −5.3]; for E[U] +14.5 % and +17.4 %.
30. **Index (b) (T9).** Against individual MSE −15.6 % and −16.2 %, against individual weighted CVaR −6.3 % and −6.6 %; all below zero. The comparison with portfolio MSE and the interaction use the two non-optimal fold designs (T14).

## 7. Checks on every run

31. **Degenerate-tail guard (MAR-172, T13).** The zero-loss share of every calibration sample is 8.0–9.8 % for index (a) (after the 20 m/s threshold) and 63.0–66.1 % for index (b) (no threshold; 64.57 % unfiltered, both EventSets). The guard (at `beta_tail` 0.9) fires on none of the 24 samples.
32. **Tail records (MAR-173).** Recomputed for every weighted-CVaR design problem of every scope on every calibration sample (1,656 problem records): none is flagged degenerate; the 2,350 problem records carried by the manifests of runs solved after MAR-173 equal the recomputed ones (`summary.json`, guard phase).
33. **Pairing across scopes (MAR-179).** Every holdout joint − individual pair computed with `paired_difference(..., across_scopes=True)` equals the C1 6b.1 pairing (differences and intervals, rtol 10⁻¹²). The decomposition both = RQ1 alone + RQ2 alone + interaction holds on all 1,728 holdout and 144 pooled rows; the premium split adds up on all 216 rows; 108 pooled contrasts equal `kfold.pooled_difference`.
34. **Solver check (T14).** 55 designs re-solved with CLARABEL first: the 43 holdout and k-fold runs with an OSQP-solved problem (all MSE) and the 12 MSE `cluster_separate` designs. 53 agree within 9.8 × 10⁻⁶ (relative objective). Two do not: index (b), k-fold, pure, κ 1, portfolio MSE, folds 0 (`5318734bca7e`) and 4 (`8dd6c28a7ed9`). OSQP stored them with status `optimal`, budget use 0.000 (no payout) and objectives 2.28 × 10²¹ and 2.48 × 10²¹, against 1.37 × 10²¹ and 1.49 × 10²¹ re-solved (+66.1 % and +66.9 %). The LP designs (E[U], weighted CVaR) were solved by CLARABEL or HiGHS and are not part of this check.
35. **`optimal_inaccurate` statuses (MAR-224).** 16 designs have at least one problem with status `optimal_inaccurate` (`runs.csv`): 13 holdout or derived designs: 12 of index (b) (11 under CoC, mostly E[U], and the pure `cluster_separate` E[U] design at κ 0.5; budget use 0.994–1.002) and one of index (a) (CoC, individual E[U], κ 1.5); and 3 index (b) pure k-fold runs (cluster E[U] fold 4, individual weighted CVaR β 0.995 fold 1, portfolio MSE fold 2, which passes the solver check). Their numbers are shown as they are.

## 8. Coverage gaps

- CoC pooled k-fold: not run (deferred for compute, MAR-223); every CoC number is holdout only.
- Individual-scope near-optimal ranges (MAR-203) and joint-scope non-uniqueness (MAR-206 families (b), (e)) for Florida: not measured.
- MAR-180 (cluster index separated from the joint calibration in the library): not merged.
- The two non-optimal index (b) k-fold portfolio MSE designs are reported, not replaced; the pooled numbers that use them are missing until those runs are re-solved.
- The radius sweep and the near-optimal ranges are out of scope (MAR-152 sub-issues).

## Appendix: config hashes

Every run's config hash: `tables.md` T15 (first 12 hex digits; holdout per index, pricing, κ, scope and design, with the derived `cluster_separate` ids and the `portfolio_matched` runs; k-fold per fold) and `runs.csv` (full hashes and run ids). The k-fold experiment configs: index (a) `2ace43bd99c8` (MSE, E[U], weighted CVaR β 0.99) and `e030e975389d` (β 0.995); index (b) `a2e2c3b6875f` and `0e7dc2834399`. Base configs: `research/configs/florida/florida_main.yaml` (index (a)) and `florida_cic75.yaml` (index (b)).
