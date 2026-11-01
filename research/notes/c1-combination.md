# C1 combination view: a tail objective calibrated jointly (RQ1 × RQ2)

- Issue: MAR-182. Internal research note, 2026-11-01. **Observations only**; the interpretation is the owner's.
- Builds on checkpoint C1 (`research/checkpoints/C1.md`, MAR-29, decided 2026-11-01): RQ1 in sections 3–6, RQ2 in section 6b, the owner's framing in section 8 ("RQ1, RQ2 and their combination … as three views, chosen by use case"). C1.md is not edited here.
- **Publication rule** (C1.md, "Publication rule"): any statement involving joint calibration is method-only in external outputs. The combination involves joint calibration, so nothing in this note is for external use as a comparative claim.
- Scripts: `research/scripts/c1_combination.py` (bootstraps and contrasts, from the C1 and MAR-158 stores; solves nothing) and `research/scripts/c1_combination_tables.py` (committed CSVs and `tables.md`).
- Data: `research/data/c1-combination/`. `runs.csv` maps every design to its full `config_hash` and `run_id`; `grid.csv`, `contrasts.csv`, `contrasts_train.csv`, `grid_f12.csv` and `contrasts_f12.csv` hold every number below; `tables.md` (T1–T10) holds every table of the grid, generated. Hashes in this note are the first 12 hex digits of the `sha256:` config hash.

## 1. The question

C1 answers RQ1 (the objective, within each scope) and RQ2 (the scope, within each objective) one at a time. The combination changes both at once: a weighted-CVaR objective calibrated jointly across one owner's 9 sites, against the alternatives the owner would otherwise use. And the interaction: does the tail gain depend on the scope, and does the joint gain depend on the objective?

## 2. Setup of every number

Everything in C1.md section 2 (main line) and section 6b.1 (cross-scope pairing) applies. In brief, and what this note adds:

| Item | Setting |
|---|---|
| Portfolio, basis, basis risk | Thesis portfolio (9 Miami assets, EventSet content hash `sha256:404b0c3a…5294df`), annual basis, thesis noise layer (η 0.3, 13 copies, seed 42), threshold 20 m/s; step payout, 15 bins on [20, 70] m/s, `below_attachment = "first_bin"` (the default; C1.md section 9, MAR-170) |
| Designs | The C1 main-line runs, read from the C1 store, **not re-solved**: scopes individual, cluster (3 clusters, thesis Ward, value-weighted mean index: **a different index**, C1.md 6b.6) and portfolio; objectives MSE, E[U], weighted CVaR (α 0.9) at design β 0.99 and 0.995; pricing pure and cost of capital r 0.06 / 0.10 (q 0.99); κ 0.5, 1, 1.5. 108 runs. F-12 (provisional): the 72 C1 F-12 runs (4 EventSets × pure, r 0.06 × κ 1 × MSE, E[U], wCVaR β 0.99 × 3 scopes) |
| Splits | **Train**: holdout calibration years 0–6,999, in sample, point values. **Test**: holdout years 7,000–9,999. **Pooled**: year-block 5-fold (MAR-151), every year evaluated by the design that did not see it; the 120 MAR-158 k-fold runs (κ 1, pure and r 0.06, the four designs, three scopes) |
| KPIs | Portfolio level (sum over the 9 assets): CVaR of the annual uncovered loss at KPI β 0.95, 0.99, 0.995; E[U]; expected payout; **budget use** = the design problems' premiums on the calibration years over κ·E[L]. No per-asset KPIs of joint designs (MAR-98, MAR-100) |
| Contrasts | J a joint scope (portfolio, or cluster), I individual, W a tail design (wCVaR β 0.99 or 0.995), O a baseline objective (MSE, or E[U]): **both** (J, W) − (I, O); **adds RQ2** (J, W) − (I, W); **adds RQ1** (J, W) − (J, O); **RQ1 alone** (I, W) − (I, O); **RQ2 alone** (J, O) − (I, O); **interaction** [(J, W) − (J, O)] − [(I, W) − (I, O)] |
| Interaction | The difference of differences. It equals [(J, W) − (I, W)] − [(J, O) − (I, O)], so "does the tail gain depend on the scope" and "does the joint gain depend on the objective" are the same number. Both = RQ1 alone + RQ2 alone + interaction, exactly (checked on all 2,016 decompositions) |
| Intervals | Paired year-block bootstrap, B 1000, seed 0, level 0.9, percentile intervals, on **one** resample per split shared by all 12 designs of a variant: the C1 resample of the test years; for pooled, the one resample of all 10,000 years (the two k-fold configs per pricing drew the same years: checked). `*` in the tables: the paired 90 % interval excludes zero |
| Pairing across scopes | MAR-179 is not merged, so MAR-158's method (C1.md 6b.1): `bootstrap.paired_difference` on copies of the portfolio-level rows with a common `problem_id` (`c1_rq2.portfolio_rows`), unchanged, with its same-resample check. The interaction is `paired_difference` of two difference bootstraps (`c1_combination.difference_bootstrap`: values and replicates subtracted row by row after the same check). Pooled: `kpi_replicates` of `kfold.pooled_designs`, checked against `kfold.pooled_difference` wherever both designs sit in one k-fold config (108 rows, equal to 1e-9) |
| Relative values | Relative to the subtracted design (b) for a difference; for the interaction, relative to the individual O design (the "neither" design). Intervals scaled by the same constant |
| Checks | The recomputed test KPIs equal C1's (`research/data/c1/kpis_*.csv`: 1,260 rows, both families); the two-term contrasts that C1 or MAR-158 reported equal theirs (1,380 holdout rows, 48 pooled rows; `research/data/c1/paired_*.csv`, `research/data/c1-rq2/scope_paired*.csv`); budget use equals C1's `runs.csv` (180 runs). Every check passed (`summary.json`) |
| New compute | **No new solves.** Bootstraps only: 5 min 44 s wall at `--jobs 3` on the shared machine |
| Code | `origin/main` at 973553c, package `0.1.0.dev0`. The C1 designs were solved at 5836676, the k-fold runs at MAR-158's head (C1.md 6b.1) |

Pooled 5-fold experiment config hashes (as in C1.md 6b.2): pure MSE, E[U], wCVaR β 0.99 `dcfc293da286`; pure wCVaR β 0.995 `0b9b994ccdda`; CoC r 0.06 MSE, E[U], wCVaR β 0.99 `e365ed1566e4`; CoC r 0.06 wCVaR β 0.995 `46bdbdf8095f`.

## 3. The grid (κ = 1, pure pricing)

The two scopes and four objectives that the combination compares, CVaR₀.₉₉(U) and E[U] in USD per year. Every scope (including cluster), pricing, κ and KPI β is in `tables.md` T1 (κ 1, with pooled values) and T2 (every κ, holdout).

| Scope | Objective | Train CVaR₀.₉₉ | Test CVaR₀.₉₉ [90 % CI] | Pooled CVaR₀.₉₉ [90 % CI] | Test E[U] | Pooled E[U] | Budget use | Hash |
|---|---|---|---|---|---|---|---|---|
| individual | MSE | 983,110 | 1,004,087 [650,025, 1,396,670] | 1,015,664 [806,439, 1,234,790] | 10,552 | 10,608 | 1.000 | `b6a790bd484c` |
| individual | E[U] | 977,257 | 1,011,027 [648,216, 1,405,215] | 1,006,240 [802,579, 1,213,226] | 10,500 | 10,442 | 1.000 | `9326e4840c25` |
| individual | wCVaR β 0.99 | 901,744 | 864,213 [679,984, 1,058,017] | 895,983 [797,826, 1,001,885] | 14,412 | 14,198 | 1.000 | `f89028d0ef02` |
| individual | wCVaR β 0.995 | 1,097,205 | 1,010,977 [898,171, 1,118,854] | 1,135,390 [1,067,567, 1,202,105] | 19,730 | 20,196 | 1.000 | `28ac9b153c21` |
| portfolio | MSE | 848,637 | 995,075 [676,459, 1,344,372] | 1,052,667 [818,493, 1,299,671] | 10,784 | 11,121 | 1.000 | `4d63dddd3335` |
| portfolio | E[U] | 841,320 | 1,001,281 [636,576, 1,417,756] | 1,017,483 [792,618, 1,262,535] | 10,621 | 10,586 | 1.000 | `08a569620416` |
| portfolio | wCVaR β 0.99 | 745,547 | 856,026 [635,489, 1,115,816] | 889,055 [749,128, 1,048,633] | 12,844 | 12,721 | 1.000 | `7d700f7bd02d` |
| portfolio | wCVaR β 0.995 | 832,345 | 915,161 [753,411, 1,099,869] | 969,184 [850,962, 1,112,507] | 17,023 | 15,992 | 1.000 | `af7553a9ab56` |

Budget use on the main line: 1.000 for every design at κ 0.5 and 1 in every scope and pricing (holdout), and 0.9992–1.0000 on the k-fold calibrations. Below 0.999 only at pure κ 1.5: the MSE designs (0.667–0.669, every scope; C1.md observation 12) and the joint E[U] and weighted-CVaR designs (portfolio 0.957–0.994, cluster 0.997–0.998) (T2, `runs.csv`). On the F-12 EventSets the pure MSE designs use 0.929–0.953 of the budget on the cat-in-a-circle EventSets (C1.md observation 15) and 0.993–0.999 on the wind ones.

## 4. The combination against each baseline (κ = 1)

Portfolio scope with a weighted-CVaR objective, against the three alternatives of the issue. Relative to the baseline design's value; train in sample, test holdout, pooled 5-fold. Read at the KPI β that matches the design β (C1.md observation 9), plus the cost in E[U]. Every KPI β, both tail designs and the cluster scope: T3, T6.

| Pricing | Design (hash) | KPI | Comparison (baseline hash) | Train | Test [90 % CI] | Pooled [90 % CI] |
|---|---|---|---|---|---|---|
| pure | wCVaR β 0.99 (`7d700f7bd02d`) | CVaR₀.₉₉ | vs individual MSE (`b6a790bd484c`): both ideas against neither | −24.2 % | −14.7 % [−37.4, +4.0] | −12.5 %* [−22.9, −2.4] |
| pure | | | vs individual wCVaR β 0.99 (`f89028d0ef02`): adds RQ2 | −17.3 % | −0.9 % [−14.5, +13.7] | −0.8 % [−9.7, +9.2] |
| pure | | | vs portfolio MSE (`4d63dddd3335`): adds RQ1 | −12.1 % | −14.0 %* [−26.2, −2.1] | −15.5 %* [−24.8, −6.0] |
| pure | | E[U] | vs individual MSE | +6.2 % | +21.7 % [−1.3, +42.1] | +19.9 %* [+9.5, +30.6] |
| pure | | | vs individual wCVaR β 0.99 | −20.2 % | −10.9 % [−20.7, +0.2] | −10.4 %* [−17.2, −3.1] |
| pure | | | vs portfolio MSE | +21.5 % | +19.1 %* [+5.5, +31.7] | +14.4 %* [+5.1, +24.2] |
| pure | wCVaR β 0.995 (`af7553a9ab56`) | CVaR₀.₉₉₅ | vs individual MSE (`b6a790bd484c`) | −36.6 % | −30.1 %* [−61.5, −2.6] | −23.3 %* [−36.3, −10.5] |
| pure | | | vs individual wCVaR β 0.995 (`28ac9b153c21`) | −20.3 % | +0.8 % [−15.1, +19.9] | −1.0 % [−13.0, +13.9] |
| pure | | | vs portfolio MSE (`4d63dddd3335`) | −26.7 % | −27.8 %* [−51.7, −6.9] | −26.0 %* [−39.3, −12.7] |
| pure | | E[U] | vs individual MSE | +43.3 % | +61.3 %* [+27.8, +93.1] | +50.7 %* [+36.8, +66.1] |
| CoC r 0.06 | wCVaR β 0.99 (`a705dea1563a`) | CVaR₀.₉₉ | vs individual MSE (`af9fe556d6aa`) | −0.0 % | +0.8 % [−9.2, +13.7] | −0.5 % [−5.7, +4.7] |
| CoC r 0.06 | | | vs individual wCVaR β 0.99 (`9c0222a65bad`) | −0.0 % | +0.7 % [−0.9, +2.5] | −0.4 % [−1.1, +0.4] |
| CoC r 0.06 | | | vs portfolio MSE (`0ada0ff98fb2`) | −0.0 % | +1.3 % [−10.3, +16.0] | −0.5 % [−6.3, +5.4] |
| CoC r 0.06 | wCVaR β 0.995 (`f6aa2ce3adec`) | CVaR₀.₉₉₅ | vs individual MSE (`af9fe556d6aa`) | −0.6 % | −2.0 % [−5.9, +3.1] | −1.1 % [−4.3, +2.1] |
| CoC r 0.10 | wCVaR β 0.99 (`120c06502b37`) | CVaR₀.₉₉ | vs individual MSE (`9aed2418ab22`) | −0.0 % | +1.2 % [−7.5, +13.4] | not run |
| CoC r 0.10 | | | vs individual wCVaR β 0.99 (`102653e1f758`) | −0.0 % | +0.4 % [−0.6, +1.5] | not run |
| CoC r 0.10 | | | vs portfolio MSE (`b4a513c6f1ab`) | −0.0 % | +1.1 % [−8.6, +14.7] | not run |
| CoC r 0.10 | wCVaR β 0.995 (`7588f543b8ef`) | CVaR₀.₉₉₅ | vs individual MSE (`9aed2418ab22`) | −0.2 % | −0.8 % [−8.4, +10.2] | not run |

Observations:

1. **Pure pricing, both ideas against neither.** The portfolio wCVaR β 0.99 design's CVaR₀.₉₉(U) is 24.2 % below the individual MSE design's in sample, 14.7 % below on the holdout test years (interval [−37.4, +4.0] contains zero) and 12.5 % below pooled over five folds (interval [−22.9, −2.4] excludes zero). With the β 0.995 design read at KPI 0.995: −36.6 % (train), −30.1 % (test) and −23.3 % (pooled), both intervals excluding zero.
2. **Against individual weighted CVaR (adds RQ2)** the combination is within −1.0 to +0.8 % on test and pooled at the matched KPI β, every interval containing zero, after −17.3 % and −20.3 % in sample. These are MAR-158's values (C1.md section 6b, observations 20 and 26; `research/data/c1-rq2/scope_paired.csv`), reproduced.
3. **Against portfolio MSE (adds RQ1)** it is 14.0 % (test) and 15.5 % (pooled) below at KPI 0.99, and 27.8 % and 26.0 % below at KPI 0.995 with the β 0.995 design; all four intervals exclude zero. The test values are C1's (`research/data/c1/paired_main.csv`), reproduced; the pooled ones are new (C1 ran no k-fold for RQ1).
4. **On test and pooled, the combination's tail difference to individual MSE is close to RQ1 alone.** Pure, β 0.99, KPI 0.99: −14.7 % (both) against −13.9 % (RQ1 alone, individual wCVaR − individual MSE) on test, −12.5 % against −11.8 % pooled (section 5).
5. **Its cost in E[U].** Pure: the combination's E[U] is 21.7 % (test, interval containing zero) and 19.9 % (pooled, excluding zero) above individual MSE's with β 0.99, and 61.3 % and 50.7 % above with β 0.995, both excluding zero. Against individual weighted CVaR it is 10.9 % (test) and 10.4 % (pooled) lower with β 0.99; the pooled interval excludes zero.
6. **Under the cost-of-capital load** the comparisons of the table (κ 1, matched KPI β) are within −2.0 to +1.3 % on test and pooled, every interval containing zero, and within −0.6 to 0.0 % in sample (the budget arithmetic of C1.md observations 4 and 24). Read at KPI 0.995, the β 0.99 combination is 2.4–6.3 % above its three baselines on test, intervals containing zero (T3).

## 5. Interaction: does the tail gain depend on the scope?

The combination split into its parts, pure pricing, κ 1, portfolio scope, baseline MSE: both = RQ1 alone + RQ2 alone + interaction, each with its paired 90 % interval in USD per year. "Interaction, relative" is the interaction over the individual MSE design's value. Hashes: (J, W) / (J, O) / (I, W) / (I, O) as in section 4 (`7d700f7bd02d` or `af7553a9ab56` / `4d63dddd3335` / `f89028d0ef02` or `28ac9b153c21` / `b6a790bd484c`); pooled: the k-fold experiment hashes of section 2. CoC, cluster and E[U] baselines: T4, T7, T8.

| Design, KPI | Split | Both (J, W) − (I, O) | RQ1 alone | RQ2 alone | Interaction | Interaction, relative |
|---|---|---|---|---|---|---|
| β 0.99, CVaR₀.₉₉ | train | −237,563 | −81,366 | −134,473 | −21,724 | −2.2 % |
| | test | −148,061 [−375,996, 40,599] | −139,875 [−370,782, 44,789] | −9,013 [−150,462, 111,447] | 826 [−98,647, 140,712] | +0.1 % [−9.8, +14.0] |
| | pooled | −126,609* [−232,488, −24,608] | −119,681* [−239,575, −5,524] | 37,003 [−46,044, 118,616] | −43,931 [−86,374, 5,116] | −4.3 % [−8.5, +0.5] |
| β 0.99, CVaR₀.₉₉₅ | train | −553,720 | −400,088 | −234,660 | 81,029 | +4.6 % |
| | test | −463,517* [−880,554, −116,766] | −548,952* [−970,324, −203,524] | −57,356 [−326,789, 158,011] | 142,792 [−48,889, 409,800] | +7.9 % [−2.7, +22.6] |
| | pooled | −387,866* [−574,125, −201,204] | −491,010* [−700,180, −289,233] | 64,725 [−92,689, 210,591] | 38,420 [−45,333, 129,447] | +2.1 % [−2.5, +7.2] |
| β 0.99, E[U] | train | 636 | 3,381 | −1,282 | −1,462 | −14.3 % |
| | test | 2,292 [−138, 4,444] | 3,860* [1,488, 6,015] | 232 [−1,267, 1,551] | −1,800* [−3,037, −282] | −17.1 %* [−28.8, −2.7] |
| | pooled | 2,113* [1,005, 3,251] | 3,589* [2,265, 4,911] | 513 [−356, 1,367] | −1,989* [−2,567, −1,405] | −18.8 %* [−24.2, −13.2] |
| β 0.995, CVaR₀.₉₉₅ | train | −640,523 | −357,094 | −234,660 | −48,769 | −2.8 % |
| | test | −545,247* [−1,115,621, −47,347] | −554,766* [−1,176,670, −18,387] | −57,356 [−326,789, 158,011] | 66,875 [−154,263, 328,345] | +3.7 % [−8.5, +18.1] |
| | pooled | −421,677* [−657,443, −189,099] | −407,709* [−742,012, −97,843] | 64,725 [−92,689, 210,591] | −78,692 [−202,029, 65,615] | −4.4 % [−11.2, +3.6] |
| β 0.995, CVaR₀.₉₉ | train | −150,765 | 114,095 | −134,473 | −130,387 | −13.3 % |
| | test | −88,926 [−394,409, 177,340] | 6,890 [−334,516, 293,566] | −9,013 [−150,462, 111,447] | −86,804 [−201,304, 55,672] | −8.6 % [−20.0, +5.5] |
| | pooled | −46,480 [−176,502, 84,276] | 119,726 [−57,986, 286,225] | 37,003 [−46,044, 118,616] | −203,209* [−270,889, −125,854] | −20.0 %* [−26.7, −12.4] |
| β 0.995, E[U] | test | 6,471* [2,936, 9,825] | 9,178* [5,225, 13,111] | 232 [−1,267, 1,551] | −2,939* [−4,639, −1,114] | −27.9 %* [−44.0, −10.6] |
| | pooled | 5,384* [3,909, 7,008] | 9,587* [7,425, 11,939] | 513 [−356, 1,367] | −4,716* [−5,839, −3,563] | −44.5 %* [−55.0, −33.6] |

Observations:

7. **At the matched tail level the interaction contains zero.** Pure, κ 1: +0.1 % (test) and −4.3 % (pooled) for β 0.99 at KPI 0.99; +3.7 % and −4.4 % for β 0.995 at KPI 0.995; all four intervals contain zero (widths 9–27 percentage points). In sample it is −2.2 % and −2.8 %.
8. **In sample the parts add differently from out of sample.** On the train years RQ2 alone is −134,473 (−13.7 %) and RQ1 alone −81,366 (−8.3 %) at KPI 0.99; on test and pooled, RQ2 alone is −9,013 and +37,003 (intervals containing zero) and RQ1 alone −139,875 and −119,681. Of the in-sample combination gain (−237,563, −24.2 %) more than half is RQ2 alone; of the out-of-sample one, 94 % (test) and 95 % (pooled) is RQ1 alone.
9. **In E[U] the interaction is negative and its interval excludes zero.** Pure, κ 1: the weighted-CVaR objective's extra E[U] over MSE is smaller in the portfolio scope than in the individual scope: −17.1 % (test) and −18.8 % (pooled) of the individual MSE design's E[U] for β 0.99, −27.9 % and −44.5 % for β 0.995. Equivalently, joint calibration lowers the weighted-CVaR design's E[U] (−10.9 % test, −10.4 % pooled against individual wCVaR, section 4) and not the MSE design's (+2.2 %, +4.8 %). With E[U] as the baseline objective the same holds (−16.1 % and −15.5 %, both excluding zero; T8). CVaR₀.₉₅ moves with E[U] (CVaR₀.₉₅ ≈ E[U]/0.05 when at most 5 % of years have a shortfall; C1.md observation 8) and shows the same sign (T4).
10. **The β 0.995 design read at KPI 0.99** has a pooled interaction of −20.0 % [−26.7, −12.4] (test −8.6 %, interval containing zero). This is the off-matched reading of C1.md observation 26, where the portfolio β 0.995 design was 14.6 % below the individual one pooled at KPI 0.99.
11. **Under the load** the interaction at κ 1 is within −1.4 to +3.0 % of the individual MSE design on test and within −0.4 to 0.0 % pooled, every interval containing zero (T4).

## 6. Across κ and KPI β (holdout test)

T5 has every κ, pricing and tail design against individual MSE; T10 counts the intervals over the whole holdout grid (9 variants × 2 tail designs × 2 baselines × 4 KPIs = 144 cells per contrast and joint scope).

12. **Scarce budget (κ 0.5, pure).** The combination is within −0.9 to +3.0 % of individual MSE at KPI 0.99 and 0.995 (intervals containing zero), while the interaction against MSE is −6.7 % [−12.9, −1.5] (KPI 0.99) and −12.6 % [−21.3, −4.9] (KPI 0.995) for β 0.99, both excluding zero. Against E[U] as the baseline the interaction at κ 0.5 is positive: +22.1 % [+6.5, +35.9] (β 0.99) and +29.1 % [+8.7, +50.3] (β 0.995) at KPI 0.995. At κ 0.5 the joint E[U] design was the one ahead of individual out of sample (C1.md observation 23).
13. **Ample budget (κ 1.5, pure).** The combination is 91–93 % below individual MSE at every KPI; this is the MSE designs leaving a third of the budget unused (C1.md observation 12), not a tail effect. The individual weighted-CVaR designs have no test shortfall, so "adds RQ2" has no relative value there (joint designs: 77,593 USD at CVaR₀.₉₉, 155,187 at CVaR₀.₉₉₅ for β 0.99). The interaction is +2.6 to +11.0 %, intervals containing zero.
14. **Under the loads** the combination against individual MSE is within −5.0 to +6.7 % at every κ; three intervals exclude zero, all at r 0.06, κ 1.5, β 0.995 (−3.9 %, −5.0 % and −2.6 % in E[U]). The interaction against MSE excludes zero in one loaded cell: r 0.06, κ 1.5, β 0.99, KPI 0.995, +6.7 % [+1.0, +12.4] (T5).
15. **Counts (T10).** Portfolio interaction: 10 of 144 intervals below zero (8 at pure κ 1 for KPI 0.95 or E[U], 2 at pure κ 0.5 with the MSE baseline) and 6 above (pure κ 1 and 0.5 with the E[U] baseline at KPI 0.995, and three loaded cells of +2.1 to +6.7 %); 128 contain zero. Both ideas against neither: 31 below, 33 above, 80 containing zero. With 90 % intervals about 10 % of cells would exclude zero if every true difference were zero; the cells share resamples and designs, so they are not independent.

## 7. The cluster scope (a different index)

The cluster scope changes the index as well as the calibration (C1.md 6b.6); T6 and T7 have its rows.

16. Pure, κ 1, β 0.99, KPI 0.99: the cluster wCVaR design (`9a25ee86197d`) is 8.4 % below individual MSE in sample, and +8.0 % [−16.2, +33.8] (test) and +3.7 % [−9.2, +15.9] (pooled) out of sample. Against individual weighted CVaR it is +25.5 % [−2.4, +58.5] and +17.6 % [+6.1, +30.4] (C1.md observation 27); against cluster MSE (`80bee12e4c89`) −11.9 % [−24.3, −0.3] and −8.5 % [−15.6, −1.7]. Its E[U] is 37.2 % and 35.4 % above individual MSE's, both excluding zero.
17. The cluster interaction at KPI 0.99 is −0.7 % (test) and +2.1 % (pooled) for β 0.99, intervals containing zero, and −19.8 % [−29.3, −9.3] pooled for β 0.995; in E[U] it is −23.2 % (test, interval containing zero) and −13.5 % (pooled, excluding zero) for β 0.99 (T7).

## 8. Realistic basis risk (F-12, provisional)

Provisional for the reasons in C1.md section 6 (MAR-118 Q5 prior, Q6 radius). κ 1, β 0.99 only, no k-fold runs. Portfolio wCVaR against individual MSE, holdout test, KPI CVaR₀.₉₉ (T9 has CVaR₀.₉₉₅, E[U] and every part with its hashes).

| EventSet | Pricing | Both [90 % CI] | RQ1 alone | RQ2 alone | Interaction | Hashes (J, W) / (I, O) |
|---|---|---|---|---|---|---|
| `cic50` | pure | −21.8 %* [−35.7, −9.4] | −22.9 %* | −5.5 %* | +6.6 %* [+3.4, +9.3] | `37482b754d70` / `cd924bdc540a` |
| `vuln` | pure | −4.5 % [−10.9, +1.1] | −4.3 % | +3.3 % | −3.4 % [−7.0, +0.1] | `071a05cfea70` / `39c960edac57` |
| `cic50_vuln` | pure | −13.7 %* [−19.6, −8.2] | −13.3 %* | −5.3 %* | +4.9 %* [+2.9, +7.1] | `c5f813d92aa7` / `6b3a82f1fa82` |
| `vuln_basins_null` | pure | −2.0 % [−5.8, +1.0] | −2.8 % | +0.2 % | +0.6 % [−0.2, +1.7] | `6b2cf262d897` / `ce56625c7f36` |
| `cic50` | CoC r 0.06 | −2.4 %* [−3.8, −1.2] | −0.2 %* | −2.4 %* | +0.2 %* [+0.0, +0.5] | `7248df3df4b6` / `0bef181cc134` |
| `vuln` | CoC r 0.06 | −2.4 % [−6.9, +3.2] | −0.9 % | +0.0 % | −1.6 %* [−3.2, −0.2] | `019baa827f09` / `a3d507bc365c` |
| `cic50_vuln` | CoC r 0.06 | −0.3 % [−2.3, +1.6] | +0.2 % | −2.0 %* | +1.4 %* [+0.2, +2.5] | `02dd5fedba16` / `b4736037fd2c` |
| `vuln_basins_null` | CoC r 0.06 | −0.9 %* [−1.7, −0.2] | −0.1 % | +0.1 % | −0.9 %* [−1.9, −0.1] | `63d697ef93e8` / `89a256a82683` |

18. **Cat-in-a-circle, pure: the two gains overlap.** On `cic50` and `cic50_vuln` both RQ1 alone and RQ2 alone are below zero with intervals excluding zero, and the interaction is positive with an interval excluding zero (+6.6 %, +4.9 %): the combination (−21.8 %, −13.7 %) is about RQ1 alone (−22.9 %, −13.3 %). Joint calibration lowers the MSE design's CVaR₀.₉₉ (RQ2 alone −5.5 %, −5.3 %) and not the weighted-CVaR design's (+1.4 %, −0.4 %; T9 "Adds RQ2").
19. **Wind index with draws** (`vuln`, `vuln_basins_null`): the combination is −4.5 % and −2.0 % under pure pricing, intervals containing zero; the interaction is −3.4 % and +0.6 %, intervals containing zero.
20. **Under the load** the combination is within −2.4 to −0.3 % and the interaction within −1.6 to +1.4 %; six of the eight intervals of these two columns exclude zero, for differences of at most 2.4 %.

## 9. Use cases: which view answers which owner question

Observations, not recommendations. "One site" is read from the individual scope, whose portfolio KPI is the sum over 9 separately calibrated sites; a single site's own KPIs were not tabulated (section 10). Values: thesis portfolio, annual basis, κ 1, out of sample, test / pooled, relative to the stated baseline.

| Owner question | View | Contrast | Pure pricing: CVaR₀.₉₉ | Pure pricing: E[U] | CoC r 0.06: CVaR₀.₉₉ | Hashes |
|---|---|---|---|---|---|---|
| A single site: does a tail objective lower its tail? | RQ1 only | (I, wCVaR β 0.99) − (I, MSE) | −13.9 % [−36.9, +4.5] / −11.8 %* [−23.6, −0.5] | +36.6 %* / +33.8 %* | +0.2 % / −0.1 % | `f89028d0ef02` / `b6a790bd484c` |
| Many sites, average-fit mandate: does calibrating them together help? | RQ2 only | (P, MSE) − (I, MSE) | −0.9 % [−15.0, +11.1] / +3.6 % [−4.5, +11.7] | +2.2 % / +4.8 % | −0.4 % / −0.0 % | `4d63dddd3335` / `b6a790bd484c` |
| (the same, E[U] objective) | RQ2 only | (P, E[U]) − (I, E[U]) | −1.0 % / +1.1 % | +1.1 % / +1.4 % | −0.1 %* / −0.2 %* | `08a569620416` / `9326e4840c25` |
| Many sites, tail mandate: a tail objective calibrated jointly, against what the owner would otherwise use | combination | (P, wCVaR β 0.99) − (I, MSE) | −14.7 % [−37.4, +4.0] / −12.5 %* [−22.9, −2.4] | +21.7 % / +19.9 %* | +0.8 % / −0.5 % | `7d700f7bd02d` / `b6a790bd484c` |
| (the same, against a tail objective per site) | combination vs RQ1 | (P, wCVaR β 0.99) − (I, wCVaR β 0.99) | −0.9 % / −0.8 % | −10.9 % / −10.4 %* | +0.7 % / −0.4 % | `7d700f7bd02d` / `f89028d0ef02` |
| (the same, against joint MSE) | combination vs RQ2 | (P, wCVaR β 0.99) − (P, MSE) | −14.0 %* / −15.5 %* | +19.1 %* / +14.4 %* | +1.3 % / −0.5 % | `7d700f7bd02d` / `4d63dddd3335` |

In sample (train), the same rows are −8.3 %, −13.7 %, −13.9 %, −24.2 %, −17.3 % and −12.1 % in CVaR₀.₉₉ under pure pricing, and within −0.2 to +0.0 % under the load.

## 10. Coverage gaps and limitations

- **Not run (no new solves were made):** pooled k-fold at r 0.10 and at κ 0.5 and 1.5 (MAR-158 scope; the κ 0.5 interaction of observation 12 is holdout only); F-12 at design β 0.995, at κ ≠ 1, at r 0.10, and on k-fold (C1.md section 10); q ≠ 0.99 under the load (C1.md section 9). These cells read "not run" in `tables.md`.
- **One portfolio.** Thesis portfolio only (9 correlated assets in one city; C1.md section 9). The Florida rerun (MAR-152 item 4) must include this view.
- **Joint designs are not unique** (C1.md observation 32): a second solver order gave portfolio designs with the same train objective and test CVaR₀.₉₉ up to 5 % apart. The `_alt` designs were not carried into these contrasts, so every (J, ·) term carries that solver dependence.
- **Interval coverage.** Percentile intervals for CVaR measured 85–92 % coverage in synthetic checks (`docs/methodology/bootstrap.md`); the coverage of an interval for a difference of differences was not measured.
- **Relative interaction.** Normalised by the individual baseline design's value, a choice; the absolute values are in `contrasts*.csv`.
- **Single site.** The "one site" use case is read from the 9-site sum of individual designs; per-site KPIs of the individual designs exist in the C1 store but were not tabulated.
- **Payout below the attachment** pays the first bin (`first_bin`; MAR-170, C1.md section 9); every number here uses the C1 runs as they are.
- **Solver status.** 297 of the 300 designs used are `optimal`; 3 are `optimal_inaccurate` (CLARABEL; the E[U] designs of `cic50_vuln` under r 0.06, accepted by the default policy).
- **Train values** are in sample and carry no calibration uncertainty.

## 11. Proposed follow-ups (not done here)

1. **Florida rerun (MAR-152 item 4):** run `c1_combination.py`'s contrasts on the paper portfolio; the script reads the C1 plan (`c1_checkpoint.plan`) and the MAR-158 k-fold configs, so it needs a plan for the Florida runs.
2. **k-fold at κ 0.5** (pure and r 0.06, 120 runs, about 20 min at `--jobs 4`), where the holdout interaction excludes zero (observation 12), and at r 0.10.
3. **Library support for contrasts:** when MAR-179 (cross-scope pairing) merges, replace the `problem_id` relabelling; a contrast of more than two designs (`difference_bootstrap`) could live next to `paired_difference` in `bootstrap.py` (an addition, not an interface change).
4. **Per-site KPIs of the individual designs**, for the single-site use case.
5. **Carry the `_alt` designs into the contrasts**, to see how much of the joint terms depends on the solver's choice among optimal designs.
