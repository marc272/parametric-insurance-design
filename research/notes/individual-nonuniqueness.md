# Individual designs are not unique either: the RQ2 baseline's portfolio KPIs over its optimal set

- Issue: MAR-198. Internal research note, 2026-11-01. **Observations only**; the interpretation is the owner's.
- Builds on checkpoint C1 (`research/checkpoints/C1.md`: section 6b, observation 32, T11) and the combination view (`research/notes/c1-combination.md`, MAR-182). Neither is edited here.
- **Publication rule** (C1.md, "Publication rule"): RQ2 statements are method-only in external outputs. Nothing here is for external use as a comparative claim.
- Scripts: `research/scripts/individual_nonuniqueness.py` (solves, bootstraps and comparisons; reads the C1 store and never writes to it) and `research/scripts/individual_nonuniqueness_tables.py` (committed CSVs and `tables.md`).
- Data: `research/data/individual-nonuniqueness/`. For each of the two methods (suffix `_free_bins`, `_near_optimal`): `ranges`, `asset_ranges`, `rq2_ends`, `contrasts_ends`, the change lists `rq2_changes` and `contrasts_changes` (CSV), and `summary_*.json`. `tables.md` holds T1–T6. Every row carries its config hash. Hashes here are the first 12 hex digits of the `sha256:` config hash.

## 1. The question

C1 and the design review treat non-uniqueness as a property of **joint** designs (C1.md observation 32 and T11; `docs/reviews/core-design-review.md` F8). An **individual** design is 9 separate problems, one per asset, and each problem can have several optimal payouts with the same objective value. The individual scope's **portfolio-level** KPIs (the owner's annual uncovered loss, summed over the 9 assets) depend on the 9 payouts, not only on their 9 objective values. So the 9 problems do not determine those KPIs.

Every RQ2 comparison in C1 section 6b, and every MAR-182 contrast with an individual term, uses one member of that set: the one the default solver policy returned.

MAR-165 found the effect (issue description). On the example config, the 9 per-asset E[U] optima are the same with and without the 20 m/s threshold filter, but the portfolio train E[U] is 5,330.25 USD with the filter and 5,282.66 USD without it. This note measures how wide that set is on the C1 main line, and what the C1 6b and MAR-182 intervals look like at its ends.

## 2. Setup of every number

Everything in C1.md section 2 (main line) and section 6b.1 applies. In brief, and what this note adds:

| Item | Setting |
|---|---|
| Portfolio, basis, basis risk | Thesis portfolio (9 Miami assets, EventSet `sha256:404b0c3a…5294df`), annual basis, thesis noise layer (η 0.3, 13 copies, seed 42), threshold 20 m/s; step payout, 15 bins on [20, 70] m/s, `below_attachment = "first_bin"` (the C1 runs as they are) |
| Split | Holdout: train years 0–6,999 (in sample), test years 7,000–9,999 |
| Designs | The C1 main-line **individual** runs at κ 1: pricing pure and cost of capital r 0.06 (q 0.99); MSE, E[U], weighted CVaR (α 0.9) at design β 0.99 and 0.995. 8 designs, read from the C1 store |
| Joint designs compared | The C1 portfolio and cluster runs of the same (pricing, design), read from the C1 store, **as stored**. They are not ranged here: their own non-uniqueness is C1 T11 and observation 32 |
| KPIs | Portfolio level: E[U] and CVaR at 0.95, 0.99 and 0.995 of the annual uncovered loss, train and test |
| (a) Free bins: exact, tolerance 0 | Some bins have no train row for an asset (T3a). Their parameters change no train quantity: not the objective, not the premium, not the budget use. So every design that differs from the C1 design only there, within monotonicity and the cap, is **exactly optimal**, for every objective and pricing. The KPIs are non-increasing in every payout parameter, so the family's smallest KPI is at "every free parameter at its highest" and its largest at "every free parameter at its lowest". This family is a subset of the optimal set. For MSE it is the whole optimal set, because the Hessian restricted to the used bins is positive definite for every asset (T3a) |
| (b) Near-optimal set: C1 T11's tolerance | Asset *i*: the feasible set of its C1 problem with objective_i ≤ optimum_i + 10⁻⁵·\|optimum_i\|, the product over the 9 assets. A design counts as inside if a numpy recomputation (objective; premium against the budget; payout constraints) is within 10⁻⁶ of these bounds. **Smallest value:** one convex program per (design, split, KPI); CLARABEL, with a second attempt at 2,000 iterations; an iterate slightly outside a set is projected onto it (L∞) and rechecked. Most of these programs end `optimal_inaccurate` or are projected (status in `ranges_near_optimal.csv`), so the reported minimum is the smallest value found: an inner point. **Largest value:** successive linearisation from the C1 design and the alternative-solver design. Each step maximises the KPI's linearisation over the set (separable: 9 small programs); the KPI never decreases. It is an inner bound. **Outer bound on the largest:** the KPI at the coordinate-wise smallest parameters over each set (that point is usually not in the set). HiGHS is not used: on the joint programs it returned `optimal` for points whose value lay above the C1 design's |
| Alternative optimum | Each asset re-solved with `c1_rq2.ALT_POLICY` (HiGHS first for LPs, CLARABEL first for QPs), as C1's `_alt` designs |
| Intervals | Paired year-block bootstrap on the C1 resample of the test years (B 1000, seed 0, level 0.9), as in C1 6b and MAR-182. At a range end the individual design is the one with the smallest or largest **point value** of the KPI being compared, and the interval is that design's. `*`: the interval excludes zero |
| Checks | The re-solved objectives equal the stored C1 runs' (rtol 10⁻⁶). Every design's KPI from the search equals `evaluate.kpis` (rtol 10⁻⁸). With the C1 designs, the comparisons reproduce MAR-158's `scope_paired.csv` (128 rows) and MAR-182's `contrasts*.csv` (448 rows), values and bounds, under both methods (`summary_*.json`). Free bins: their designs pay exactly what the C1 design pays on every train row (checked) |
| Validation | The MAR-165 setting: the example config of `examples/portfolio_calibration.py` (no noise layer, `below_attachment = "zero"`, E[U], pure, κ 1), with and without the threshold filter |
| Compute | Free bins: about 6 min at `--jobs 3`. Near-optimal set: 1.0–2.0 h per design at `--jobs 5` on the shared machine (load average 15–60); pure MSE re-run on its own after a solver failure (`results/`, not committed) |
| Code | Branch `marcprinzing/mar-198-…` on `origin/main` 9051326, package `0.1.0.dev0` |

Config hashes of the individual designs (T1a, T1b):

| Pricing | MSE | E[U] | wCVaR β 0.99 | wCVaR β 0.995 |
|---|---|---|---|---|
| pure | `b6a790bd484c` | `9326e4840c25` | `f89028d0ef02` | `28ac9b153c21` |
| CoC r 0.06 | `af9fe556d6aa` | `3bee2dabbfe6` | `9c0222a65bad` | `587393142489` |

The joint designs are C1's: portfolio pure `4d63dddd3335` / `08a569620416` / `7d700f7bd02d` / `af7553a9ab56`, cluster pure `80bee12e4c89` / `b78a04a941dd` / `9a25ee86197d` / `4f21280640b7`, portfolio CoC `0ada0ff98fb2` / `e86fd26ac86f` / `a705dea1563a` / `f6aa2ce3adec`, cluster CoC `96457b8a9204` / `f5d42cdbabde` / `a56b270c97e4` / `163912a4237f` (same column order). MAR-165 check: `d4b6e94c5c4d` (filter), `2baf0e62dc04` (no filter).

## 3. Where the freedom is

1. **6 of the 9 assets have bins without a train row** (T3a). The bins are 12 and 13, that is [60, 66.7) m/s: A1 (bin 12), A2, A4 and A8 (13), A3 (12), A6 (12 and 13). A5, A7 and A9 have none. Their used neighbour bins hold 13–104 train rows, that is one to eight events in 13 noise copies. In the test years, bins 12–13 hold 13 rows for A1 and A8 and 26 for A6, and none for A2, A3 and A4.
2. **How far those parameters can move**, relative to the asset's cap: up to 0.005–0.28 under pure pricing (every objective). Under CoC r 0.06 it is up to 0.09–0.23 for MSE, 0.03–0.04 (β 0.99) and 0.02–0.17 (β 0.995) for weighted CVaR, and 10⁻⁹ for E[U]: in the C1 CoC E[U] design the neighbours of every free bin have equal parameters (T3a).
3. **MSE is unique on the used bins.** The smallest-to-largest eigenvalue ratio of the MSE Hessian on the used bins is 0.003–0.010 for every asset. So the MSE optimal set is exactly the free-bin family, and the MSE train KPIs are fixed (T1a: range 0).
4. **The LP designs have more freedom than the free bins** (T1b, T3b). On the train years, where free bins change nothing, the near-optimal ranges are:
   - pure E[U]: −0.25 / +0.52 % (E[U]) and −0.29 / +0.65 % (CVaR₀.₉₉);
   - pure weighted CVaR β 0.99: −0.28 / +0.27 % and −0.08 / +0.09 %;
   - pure weighted CVaR β 0.995: −0.43 / +0.21 % and −0.44 / +0.26 %;
   - CoC: within ±0.03 %, except weighted CVaR β 0.99 at CVaR₀.₉₉₅ (−1.88 / +0.27 %).

   Under pure pricing every individual design pays every asset exactly its budget (T3b: E[π_i]/E[L_i] = 1.00 at both ends), so the freedom is in how an asset's payout is spread over its bins, not in how much it is paid.
5. **The MAR-165 values both lie in the range** (T2). The train E[U] range of the filtered problem is 5,252.0–5,421.6 USD; it contains 5,330.25 (filter) and 5,282.66 (no filter), and the unfiltered problem's range, 5,251.8–5,420.8, is the same within 0.02 %. On train the free-bin range is 0 there as well, so the MAR-165 difference comes from the LP's other degenerate directions, not from free bins. On test the same set spans 3,899–4,443 (E[U], −2.4 / +11.2 % of the default design) and 348,351–400,419 (CVaR₀.₉₉).

## 4. Range of the individual scope's portfolio KPIs

Test (holdout) values, relative to the C1 design. (a) is exact; (b) has inner-bound ends. Train ranges are in section 3, item 4; every row is in T1a and T1b.

| Pricing | Design | KPI | C1 design | (a) free bins | (b) near-optimal set | Alt. solver | Hash |
|---|---|---|---|---|---|---|---|
| pure | MSE | CVaR₀.₉₉ | 1,004,087 | −0.91 / +5.10 % | not resolved (see 6) | +1.87 % (outside the set) | `b6a790bd484c` |
| pure | MSE | E[U] | 10,552 | −0.86 / +4.98 % | −2.91 / +6.43 % | +2.14 % (outside the set) | `b6a790bd484c` |
| pure | E[U] | CVaR₀.₉₉ | 1,011,027 | −1.91 / +3.89 % | −3.17 / +5.20 % | +3.79 % | `9326e4840c25` |
| pure | E[U] | E[U] | 10,500 | −1.86 / +3.81 % | −3.06 / +4.96 % | +3.69 % | `9326e4840c25` |
| pure | wCVaR β 0.99 | CVaR₀.₉₉ | 864,213 | −0.76 / +1.79 % | −0.94 / +2.15 % | +1.79 % | `f89028d0ef02` |
| pure | wCVaR β 0.99 | E[U] | 14,412 | −0.56 / +1.24 % | −0.81 / +1.49 % | +1.24 % | `f89028d0ef02` |
| pure | wCVaR β 0.995 | CVaR₀.₉₉₅ | 1,259,243 | −0.23 / +1.10 % | −0.40 / +1.37 % | +1.10 % | `28ac9b153c21` |
| CoC r 0.06 | MSE | CVaR₀.₉₉ | 14,463,866 | −0.60 / +0.52 % | not resolved | 0.00 % | `af9fe556d6aa` |
| CoC r 0.06 | E[U] | CVaR₀.₉₉ | 15,522,105 | 0.00 / 0.00 % | −0.02 / +0.02 % | 0.00 % | `3bee2dabbfe6` |
| CoC r 0.06 | wCVaR β 0.99 | CVaR₀.₉₉ | 14,487,767 | −0.15 / +0.16 % | −2.95 / +3.64 % | +0.15 % | `9c0222a65bad` |
| CoC r 0.06 | wCVaR β 0.995 | CVaR₀.₉₉₅ | 19,546,354 | −0.43 / +0.50 % | −0.61 / +0.85 % | +0.46 % | `587393142489` |

6. **On test, exactly optimal individual designs differ by up to 6.0 % (pure MSE, CVaR₀.₉₉) and 5.8 % (pure E[U]).** Under pure pricing the free-bin width at CVaR₀.₉₉ is 6.0 % (MSE), 5.8 % (E[U]), 2.6 % (β 0.99) and 0.9 % (β 0.995). Under CoC r 0.06 it is 0.0–1.1 %. The near-optimal set widens the LP designs' test ranges to 8.4 % (pure E[U]) and 6.6 % (CoC β 0.99, CVaR₀.₉₉; 10.0 % at CVaR₀.₉₉₅).
7. **The alternative solver order lands inside the range.** For the LP designs the HiGHS-first optimum has the C1 objective (relative difference ≤ 6·10⁻⁷) and tests +3.79 % (pure E[U]) and +1.79 % (pure β 0.99) at CVaR₀.₉₉. Those values are at or near the upper end of the free-bin range. For pure MSE, the alternative (CLARABEL instead of OSQP) has an objective 4.7·10⁻⁵ above the optimum, outside the 10⁻⁵ set, and tests +1.87 %.
8. **Outer bounds.** The outer bound on the largest value is 2–10 % above the C1 design on test under pure pricing and up to 20.6 % (CoC β 0.99). So the true maximum over the near-optimal set may lie above the largest value found; T1b gives both.
9. **MSE under the near-optimal method is not resolved.** With the quadratic constraint at 10⁻⁵, CLARABEL ends most MSE range programs `optimal_inaccurate`. Their iterates often do not pass the numpy check even after projection (`n/a` in T1b), and the linearisation stops at its first step. Since the MSE optimum is unique on the used bins (item 3), (a) is the exact MSE range. The (b) MSE rows are near-optimal designs (within 10⁻⁵ of the objective), and some lie outside (a): for example pure MSE train E[U], −1.68 %.

## 5. Against the C1 section 6b differences (joint − individual)

Test, κ 1, CVaR₀.₉₉ unless stated, relative to the individual design used. "min": the individual design with the smallest KPI, which gives the largest joint − individual difference; "max": the largest. Every row and KPI is in T4a and T4b.

| Pricing | Design | Comparison | C1 design (C1.md 6b) | (a) at min | (a) at max | (b) at min | (b) at max |
|---|---|---|---|---|---|---|---|
| pure | MSE | portfolio − individual | −0.9 % [−15.0, +11.1] | +0.0 % [−14.5, +12.2] | −5.7 % [−21.2, +7.2] | n/a | −0.9 % |
| pure | E[U] | portfolio − individual | −1.0 % [−15.1, +12.7] | +1.0 % [−14.3, +15.3] | −4.7 % [−19.2, +9.4] | +2.3 % [−13.1, +17.2] | −5.9 % [−21.2, +8.7] |
| pure | wCVaR β 0.99 | portfolio − individual | −0.9 % [−14.5, +13.7] | −0.2 % [−13.7, +14.6] | −2.7 % [−15.6, +11.1] | −0.0 % [−13.5, +14.8] | −3.0 % [−16.1, +10.7] |
| pure | wCVaR β 0.995 | portfolio − individual | −9.5 % [−20.8, +3.4] | −9.4 % [−20.7, +3.6] | −10.2 % [−21.4, +2.7] | −8.9 % [−20.3, +4.1] | −10.5 % [−21.7, +2.4] |
| pure | MSE | cluster − individual | +22.7 % [−3.7, +52.7] | +23.8 % [−2.8, +53.9] | +16.7 % [−10.1, +46.2] | +25.7 % [−1.2, +56.5] | +22.7 % |
| pure | E[U] | cluster − individual | +21.7 % [−2.2, +49.9] | +24.0 % [−0.3, +52.0] | +17.1 % [−6.4, +45.5] | +25.7 %* [+1.2, +54.5] | +15.7 % [−8.3, +44.1] |
| pure | wCVaR β 0.99 | portfolio − individual, E[U] | −10.9 % [−20.7, +0.2] | −10.4 % [−20.5, +1.0] | −12.0 %* [−21.6, −1.3] | −10.2 % [−20.2, +1.2] | −12.2 %* [−21.8, −1.5] |
| CoC r 0.06 | wCVaR β 0.99 | portfolio − individual, CVaR₀.₉₉₅ | +2.4 % [−0.0, +4.8] | +2.6 %* [+0.2, +5.1] | +2.2 % [−0.2, +4.5] | +8.9 % [−1.2, +21.1] | −1.6 % [−5.2, +3.3] |
| CoC r 0.06 | wCVaR β 0.99 | portfolio − individual | +0.7 % [−0.9, +2.5] | +0.8 % [−0.8, +2.7] | +0.5 % [−1.0, +2.2] | +3.7 % [−0.8, +9.6] | −2.9 % [−6.9, +1.6] |

10. **In sample, the RQ2 gap is far wider than the individual range.** Under pure pricing at κ 1, portfolio − individual on train is −13.7 % (MSE), −13.9 % (E[U]), −17.3 % (β 0.99) and −24.1 % (β 0.995) at CVaR₀.₉₉ (C1 observation 19). The individual train range is 0 under (a) and at most 0.94 % wide under (b) for the LP designs at that KPI (section 3, item 4).
11. **On test, the individual range is of the size of the RQ2 point differences.** At CVaR₀.₉₉, pure, the C1 portfolio − individual values of −0.9 to −1.0 % (MSE, E[U], β 0.99) become +0.0 to +1.0 % at the free-bin min end and −2.7 to −5.7 % at the max end, so their **sign changes** for MSE and E[U]. The near-optimal set gives +2.3 % and −5.9 % for E[U]. The β 0.995 difference (−9.5 %) stays within −8.9 to −10.5 %.
12. **Interval verdicts at the ends (C1 6b): 5 of 64 test rows change under (a), 10 of 64 under (b)** (T6a, T6b; `rq2_changes_*.csv`). Every one is a "contains zero" interval that excludes zero at one end:
    - pure β 0.99, portfolio − individual, E[U] and CVaR₀.₉₅ (both methods): −12.0 % [−21.6, −1.3] at the max end;
    - pure E[U] design, cluster − individual (CVaR₀.₉₅ and E[U] under (a); every KPI under (b), e.g. CVaR₀.₉₉ +25.7 % [+1.2, +54.5]): at the min end;
    - CoC β 0.99, portfolio − individual at CVaR₀.₉₉₅ (a): +2.6 % [+0.2, +5.1] at the min end;
    - under (b) also pure MSE cluster − individual (E[U]) and three CoC E[U]-design cluster cells of ≤ 0.3 %.

    No interval that excluded zero with the C1 design contains zero at an end, in either method. **Every portfolio − individual interval at CVaR₀.₉₉ and CVaR₀.₉₉₅ under pure pricing contains zero at both ends** of both ranges, as with the C1 designs (C1 observation 20).

## 6. Against the MAR-182 combination contrasts

Pure pricing, portfolio scope, test, relative to MAR-182's reference (the individual baseline design's C1 value). "Low" and "high": every individual term at the end that lowers or raises the contrast. The near-optimal sets of different individual designs are independent, so on the point values these are the contrast's range. Every contrast, KPI and the cluster scope are in T5a and T5b.

| Contrast | Design, KPI | C1 designs (MAR-182) | (a) low | (a) high | (b) low | (b) high |
|---|---|---|---|---|---|---|
| both (P, W) − (I, MSE) | β 0.99, CVaR₀.₉₉ | −14.7 % [−37.4, +4.0] | −19.8 % [−46.1, +2.2] | −13.8 % [−36.3, +4.8] | −14.7 % | −12.3 % [−34.3, +6.2] |
| both | β 0.995, CVaR₀.₉₉₅ | −30.1 %* [−61.5, −2.6] | −35.4 %* [−69.1, −5.8] | −29.1 %* [−60.8, −1.8] | −36.4 %* [−70.6, −6.7] | n/a |
| RQ1 alone (I, W) − (I, MSE) | β 0.99, CVaR₀.₉₉ | −13.9 % [−36.9, +4.5] | −19.7 % [−45.8, +1.9] | −11.5 % [−33.5, +6.5] | −14.7 % | −9.6 % [−31.0, +7.8] |
| RQ1 alone | β 0.995, CVaR₀.₉₉₅ | −30.6 %* [−64.9, −1.0] | −36.1 %* [−71.3, −5.0] | −28.8 % [−61.9, +0.2] | −37.2 %* | n/a |
| RQ2 alone (P, MSE) − (I, MSE) | CVaR₀.₉₉ | −0.9 % [−15.0, +11.1] | −6.0 % [−22.2, +7.6] | +0.0 % [−14.3, +12.1] | −0.9 % | +1.5 % [−12.7, +13.6] |
| adds RQ2 (P, W) − (I, W) | β 0.99, CVaR₀.₉₉ | −0.9 % [−14.5, +13.7] | −2.7 % [−15.9, +11.3] | −0.2 % [−13.6, +14.5] | −3.1 % | −0.0 % |
| adds RQ2 | β 0.99, E[U] | −10.9 % [−20.7, +0.2] | −12.1 %* [−21.9, −1.3] | −10.3 % [−20.4, +1.0] | −12.4 %* [−22.2, −1.6] | −10.1 % [−20.0, +1.2] |
| interaction (base MSE) | β 0.99, CVaR₀.₉₉ | +0.1 % [−9.8, +14.0] | −2.4 % [−12.8, +10.9] | +5.8 % [−7.2, +22.4] | −4.2 % | +0.9 % |
| interaction (base MSE) | β 0.99, E[U] | −17.1 %* [−28.8, −2.7] | −19.6 %* [−31.8, −5.3] | −11.3 % [−24.9, +6.0] | −22.0 %* [−34.3, −7.8] | −9.5 % [−23.0, +7.7] |
| interaction (base E[U]) | β 0.99, CVaR₀.₉₉₅ | +6.4 %* [+0.2, +13.4] | +2.8 % [−5.1, +10.5] | +11.1 %* [+2.4, +21.0] | +1.1 % [−6.5, +8.3] | +12.8 %* [+3.6, +23.2] |
| interaction (base MSE) | β 0.995, E[U] | −27.9 %* [−44.0, −10.6] | −29.8 %* [−46.0, −11.7] | −22.7 %* [−40.6, −4.5] | −32.3 %* | −20.3 %* [−38.0, −2.1] |

(b) "MSE" ends: n/a where the MSE near-optimal search found no design (section 4, item 9). (b) cells without an interval are the C1 design's own (no wider design found in that direction).

13. **MAR-182 test contrasts whose interval verdict changes at an end: 19 of 224 under (a), 27 of 224 under (b)** (T6a, T6b; `contrasts_changes_*.csv`). The changes go both ways:
    - **Lose their exclusion of zero at one end** (a): the interaction in E[U] and CVaR₀.₉₅ with β 0.99 (portfolio scope with base MSE and E[U], cluster scope with base E[U]; e.g. −17.1 % becomes −11.3 % [−24.9, +6.0]); the interaction at CVaR₀.₉₅ with β 0.995 (cluster); the interaction with base E[U] at CVaR₀.₉₉₅ (+6.4 % becomes +2.8 % [−5.1, +10.5]; also under CoC); RQ1 alone with β 0.995 at CVaR₀.₉₉₅ (−30.6 % becomes −28.8 % [−61.9, +0.2], base MSE and E[U]).
    - **Gain an exclusion of zero at one end**: adds RQ2 with β 0.99 in E[U] and CVaR₀.₉₅ (−12.1 % [−21.9, −1.3]); RQ2 alone for the E[U] design, cluster scope, E[U] and CVaR₀.₉₅ (a), and every KPI under (b); interaction with base MSE in E[U], cluster scope, at the low end; under CoC, adds RQ2 with β 0.99 at CVaR₀.₉₉₅.
14. **Rows that keep their verdict at both ends** (both methods): both ideas against neither with β 0.995 at CVaR₀.₉₉₅ (−29.1 to −36.4 %, every end excluding zero) and with β 0.99 at CVaR₀.₉₉ (−12.3 to −19.8 %, every end containing zero); the interaction with β 0.995 in E[U] (−20.3 to −32.3 %, excluding zero); in the portfolio scope, RQ2 alone and adds RQ2 at CVaR₀.₉₉ and CVaR₀.₉₉₅ (every end containing zero).
15. **Under CoC r 0.06** the contrast ends lie within 1.4 percentage points of the C1 designs' values under (a) (largest: β 0.995 at CVaR₀.₉₉₅) and within 6.2 points under (b) (largest: terms with the β 0.99 design at CVaR₀.₉₉₅, whose test range is wide; section 4).

## 7. Coverage gaps and limitations

- **Holdout only.** The pooled 5-fold results (C1 6b.3, MAR-182) use one individual design per fold; their ranges were not measured. So were κ 0.5 and 1.5, r 0.10 and the F-12 EventSets.
- **The joint designs are held at their C1 values.** Their own optimal sets (C1 T11, observation 32) were not ranged jointly with the individual ones. A difference's full range over both sets is wider than the ranges here.
- **Inner and outer bounds.** (a) is exact for its family, and the whole optimal set for MSE. (b)'s largest values are inner bounds (outer bounds in T1b); its smallest values are exact only where the program ended `optimal` without projection, which is rare (`ranges_near_optimal.csv`, `status_min`). The tolerance is C1 T11's 10⁻⁵; no other tolerance was run.
- **Interval at an end.** The end designs extremise the point value, not an interval bound, so an interval bound's own extreme over the set can lie further out.
- **MSE, method (b):** not resolved by CLARABEL at this tolerance (section 4, item 9).
- **One portfolio.** On the thesis portfolio the free bins come from 1–5 events per used neighbour bin at 60–70 m/s.

## 8. Proposed follow-ups (not done here)

1. **Florida rerun (MAR-152 item 4): measure the same way before reading any RQ2 difference.**
   - Run `individual_nonuniqueness.py --method free_bins` (cheap: minutes) on the paper portfolio's individual designs, with a plan for its runs, and report the C1 6b and MAR-182 differences at the ends.
   - Run the near-optimal method for the LP designs if the compute allows. It costs about 1–2 h per design here; 67 counties would cost more.
   - Report the free-bin count per county. Sparse upper bins are likely with 67 counties.
   - Do the same for each k-fold fold, if pooled results are read.
2. **Joint and individual ranges together:** range a joint − individual difference over both optimal sets: the joint min/max LP of C1 T11 with the KPI as objective, against the individual ends here.
3. **A tie-break rule is a method decision (owner).** Possible rules for an empty bin: interpolate, take a neighbour's value, take the lowest value, or report every design's KPI range. This is an owner question, not done here. Any rule changes the test KPIs of every scope, not only the individual one. The library leaves it to the solver.
4. **MSE near-optimal sets:** an exact parametrisation (the unique used-bin optimum plus the free bins, as in (a)) replaces the QP-constrained programs; no further solver work is needed for MSE.
5. **Library:** a helper that lists each design's free bins (bins without calibration rows) and, optionally, warns about them, would make this visible in every run. This would be an addition to `evaluate` or `payout`, not an interface change.
