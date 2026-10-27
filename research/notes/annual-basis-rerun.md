# MAR-24: the thesis config on the annual, event and event-conditional bases

- Issue: [MAR-24](https://linear.app/marc-prinzing/issue/MAR-24/f-10-annual-basis-cvar-over-years-and-annual-premium) (F-10, SPEC §6.2). Written by a worker agent on 2026-10-27.
- What the bases are: `docs/methodology/annual-basis.md`.
- Status: **observations only.** What they mean for the method belongs to checkpoint C1 (MAR-29). Every number is in-sample (sample `full`, as in the thesis config), because the out-of-sample split (MAR-22) isn't in yet.
- Files: `research/data/annual-basis-rerun/`: the three configs, `compare.py` (re-evaluation), `comparison.csv` (every number below, with full config hashes and run ids), `timing.py` and `timing.csv` (the draw-count re-timing).

## Setup

The three configs are `parity/configs/thesis.yaml` with `basis` set to `annual`, `event` or `event_conditional`, and only the β sweep kept. Everything else is the thesis setup:

- the same EventSet: `sha256:404b0c3a…294df`;
- heteroscedastic noise, η = 0.3, 13 copies, seed 42;
- the 20 m/s threshold filter;
- 15 bins on [20, 70];
- scopes: individual, cluster (3, thesis Ward) and portfolio;
- objectives: MSE, E[U], and weighted CVaR (α 0.9, β 0.95);
- pure premium, budget κ = 1, evaluation β 0.95.

The `event_conditional` configs have the same config hashes as the parity configs (checked: name, description, eventset path, output and sweeps are excluded from the hash). They were solved with the **default** solver policy, not the parity gate's thesis policy, so all three bases are compared under one policy.

Commands, from the repository root, at commit 9e948ff of this PR's branch with package version 0.0.0 of the workspace:

```bash
uv run parametric-insurance-design sweep research/data/annual-basis-rerun/thesis_annual.yaml -p beta --jobs 6
uv run parametric-insurance-design sweep research/data/annual-basis-rerun/thesis_event.yaml -p beta --jobs 6
uv run parametric-insurance-design sweep research/data/annual-basis-rerun/thesis_event_conditional.yaml -p beta --jobs 6
uv run python research/data/annual-basis-rerun/compare.py
```

Each sweep wrote 39 runs (9 baseline runs and 30 β-sweep points, 3 of which are baseline cache hits) with 0 failures. Wall time was 43 s for the annual sweep at `--jobs 6`, on a 10-core Mac shared with other jobs. `compare.py` rebuilds every stored design from its `payouts` and `entities` rows and evaluates it with `evaluate.kpis` on the **annual** basis, and on its own basis. That gives each design two readings: "annual" KPIs (comparable across the three calibrations) and "own" KPIs (what that run's store reports). All values are portfolio level, in USD.

## The prepared data on each basis

After the noise layer and the threshold filter: 13,897 rows (1,069 storms × 13 copies), `n_years` 10,000.

| Basis | Outcomes | Mass without rows |
|---|---|---|
| `event_conditional` | 13,897 (one per row) | none: probabilities rescaled |
| `event` | 13,898 (rows + "no event") | 0.8931 ("no event") |
| `annual` | 13,131 (13,130 occupied (year, copy) slots + one pooled) | 0.899 (empty slots) |

1,010 of the 10,000 years hold at least one storm above 20 m/s, and 56 hold two or three. Expected annual portfolio loss: 220,363 on `annual` and `event`. On `event_conditional`, the expected loss is 2,061,394 per event above the threshold, because 0.1069 × 2,061,394 = 220,363.

## Baseline: the nine thesis runs per basis, read on the annual basis

The "Hash" column is the first 12 hex digits of the run's config hash. `comparison.csv` has the full hashes. "Own" is the run's KPI on its own calibration basis.

| Scope | Objective | Calibrated on | Hash | Annual E[U] | Annual CVaR₀.₉₅ | Annual CVaR₀.₉₉ | Annual RMSE | Annual premium | Own E[U] | Own CVaR₀.₉₅ |
|---|---|---|---|---|---|---|---|---|---|---|
| cluster | expected_uncovered | `annual` | `ea1a85a748e7` | 10,915 | 218,299 | 1,034,890 | 270,839 | 220,363 | 10,915 | 218,299 |
| cluster | expected_uncovered | `event` | `2a1fa21d6f72` | 10,915 | 218,299 | 1,034,890 | 270,839 | 220,363 | 10,915 | 218,299 |
| cluster | expected_uncovered | `event_conditional` | `5ebf4bdfcedf` | 10,915 | 218,299 | 1,034,850 | 270,862 | 220,363 | 102,104 | 1,712,600 |
| cluster | mse | `annual` | `eeab1ad2dd5a` | 11,149 | 222,985 | 1,048,340 | 268,647 | 220,363 | 11,149 | 222,985 |
| cluster | mse | `event` | `1e2659372957` | 11,022 | 220,445 | 1,042,980 | 268,770 | 220,362 | 11,022 | 220,445 |
| cluster | mse | `event_conditional` | `9cedd23cf251` | 11,022 | 220,442 | 1,042,980 | 268,770 | 220,363 | 103,106 | 1,728,690 |
| cluster | weighted_cvar | `annual` | `ee90c0b2301f` | 10,915 | 218,299 | 1,034,560 | 271,029 | 220,363 | 10,915 | 218,299 |
| cluster | weighted_cvar | `event` | `4a7b77af5d8e` | 10,915 | 218,299 | 1,034,540 | 271,081 | 220,363 | 10,915 | 218,299 |
| cluster | weighted_cvar | `event_conditional` | `e85db2607bc6` | 15,608 | 311,832 | 971,566 | 314,183 | 220,363 | 146,009 | 1,296,480 |
| individual | expected_uncovered | `annual` | `31be2d0fb3c6` | 10,202 | 204,043 | 979,460 | 268,284 | 220,363 | 10,202 | 204,043 |
| individual | expected_uncovered | `event` | `db0d9c05ccb5` | 10,202 | 204,043 | 979,460 | 268,284 | 220,363 | 10,202 | 204,043 |
| individual | expected_uncovered | `event_conditional` | `8e3e9ca927bf` | 10,202 | 204,042 | 979,451 | 268,279 | 220,363 | 95,436 | 1,642,560 |
| individual | mse | `annual` | `e2cbcc3abdd5` | 10,300 | 206,003 | 987,182 | 266,651 | 220,257 | 10,300 | 206,003 |
| individual | mse | `event` | `a436e62f666d` | 10,155 | 203,105 | 983,104 | 266,686 | 220,363 | 10,155 | 203,105 |
| individual | mse | `event_conditional` | `3eec7ac6ed4d` | 10,155 | 203,105 | 983,104 | 266,686 | 220,363 | 94,997 | 1,659,690 |
| individual | weighted_cvar | `annual` | `a3dc154343eb` | 10,203 | 204,068 | 979,419 | 268,301 | 220,363 | 10,203 | 204,068 |
| individual | weighted_cvar | `event` | `36a72a36b57d` | 10,204 | 204,070 | 979,430 | 268,303 | 220,363 | 10,204 | 204,070 |
| individual | weighted_cvar | `event_conditional` | `3666438e3ea9` | 19,547 | 390,497 | 1,097,380 | 413,615 | 220,363 | 182,855 | 1,321,210 |
| portfolio | expected_uncovered | `annual` | `9cf92ce6c1e7` | 9,157 | 183,142 | 879,564 | 257,069 | 220,363 | 9,157 | 183,142 |
| portfolio | expected_uncovered | `event` | `bd8ad13852ce` | 9,157 | 183,142 | 879,564 | 257,069 | 220,363 | 9,157 | 183,142 |
| portfolio | expected_uncovered | `event_conditional` | `bbe10df69cbe` | 9,157 | 183,142 | 879,564 | 257,069 | 220,363 | 85,660 | 1,496,950 |
| portfolio | mse | `annual` | `6d7951e65dc7` | 9,378 | 187,569 | 881,505 | 254,571 | 220,363 | 9,378 | 187,569 |
| portfolio | mse | `event` | `8dd9586f6219` | 9,347 | 186,948 | 882,500 | 254,673 | 220,363 | 9,347 | 186,948 |
| portfolio | mse | `event_conditional` | `e134d0bea41f` | 9,347 | 186,948 | 882,500 | 254,673 | 220,363 | 87,440 | 1,486,160 |
| portfolio | weighted_cvar | `annual` | `fce1b208d097` | 9,157 | 183,142 | 879,564 | 257,069 | 220,363 | 9,157 | 183,142 |
| portfolio | weighted_cvar | `event` | `44d4d9158061` | 9,157 | 183,142 | 879,564 | 257,069 | 220,363 | 9,157 | 183,142 |
| portfolio | weighted_cvar | `event_conditional` | `71718bcbd1d5` | 14,158 | 282,747 | 807,051 | 312,695 | 220,363 | 132,444 | 1,065,600 |

Observations:

1. **E[U] designs are the same on all three bases.** The annual KPIs of the E[U] designs agree to the reported precision in every scope. This is expected: `E[U]` on `event` and `annual` equals `Σ_e w_e U_e`, which is `event_conditional`'s E[U] times the constant `Σ w = 0.1069`, and the annual budget is the event-conditional one times the same constant. The `own` columns differ by exactly that factor. The CVaR₀.₉₉ difference in the cluster scope (1,034,850 vs 1,034,890) is solver tolerance.
2. **MSE designs agree on `event` and `event_conditional`.** Their annual KPIs agree to the reported precision: both are per-row bases with proportional probabilities. The annual MSE designs differ slightly. That is the MAR-24 choice of squaring the summed yearly residual, which differs only in the 56 years with several storms. Annual E[U] is 1.4 % higher in the individual scope (10,300 vs 10,155) and RMSE about 0.01 % lower (266,651 vs 266,686). The annual individual MSE run spent 220,257 of the 220,363 budget; two of its nine problems were solved by CLARABEL after OSQP.
3. **Weighted CVaR (α 0.9, β 0.95) designs differ the most.** On `annual` and `event`, every scope's design gives the same annual KPIs as the E[U] design of that scope, to the reported precision. Calibrated on `event_conditional`, the annual E[U] is 1.5–1.9 times higher (portfolio 14,158 vs 9,157), and so is the annual CVaR₀.₉₅ (282,747 vs 183,142). The annual CVaR₀.₉₉ is lower in the cluster and portfolio scopes (portfolio 807,051 vs 879,564) and higher in the individual scope (1,097,380 vs 979,419).
4. **Why the annual β = 0.95 design equals the E[U] design: arithmetic, observed.** On the annual basis, the reported VaR₀.₉₅ of these designs' yearly uncovered loss is about 0, below 0.01 USD (`annual.var_uncovered@0.95` in `comparison.csv`). So at most 5 % of years have a positive uncovered loss, and then `CVaR₀.₉₅(U) = E[U] / 0.05` (portfolio: 9,157 / 0.05 = 183,140; reported 183,142). Weighted CVaR is then a constant multiple of E[U] and has the same minimisers. About 10 % of the (year, copy) slots hold any storm above the threshold, so at β ≤ 0.95 the annual tail is every year with a shortfall.
5. **The event basis is close to the annual basis on these data.** The largest annual-KPI difference between the `event` and `annual` calibrations in the baseline is 1.4 % (individual MSE E[U]). In the β sweep below it is 1.8 % (β 0.98, CVaR₀.₉₉: 812,117 vs 826,605).

## The β sweep of the portfolio weighted-CVaR design, read on the annual basis

| β | Calibrated on | Hash | Annual E[U] | Annual CVaR₀.₉₅ | Annual CVaR₀.₉₉ |
|---|---|---|---|---|---|
| 0.90 | `annual` | `11e5d64b73bf` | 9,157 | 183,142 | 879,563 |
| 0.90 | `event` | `e1e7e186cc92` | 9,157 | 183,142 | 879,563 |
| 0.90 | `event_conditional` | `32055dd479ed` | 11,126 | 222,324 | 765,969 |
| 0.91 | `annual` | `781004aee89b` | 9,157 | 183,142 | 879,564 |
| 0.91 | `event` | `1ae82d5774a6` | 9,157 | 183,142 | 879,563 |
| 0.91 | `event_conditional` | `9b7c4677efa3` | 11,605 | 231,857 | 764,906 |
| 0.92 | `annual` | `c7931b9c6728` | 9,157 | 183,142 | 879,564 |
| 0.92 | `event` | `16cf291993e3` | 9,157 | 183,142 | 879,563 |
| 0.92 | `event_conditional` | `33d74861e0c9` | 12,192 | 243,550 | 769,030 |
| 0.93 | `annual` | `45fa83c4f088` | 9,157 | 183,142 | 879,564 |
| 0.93 | `event` | `de03d7865a81` | 9,157 | 183,142 | 879,563 |
| 0.93 | `event_conditional` | `da32221dbc25` | 13,034 | 260,313 | 781,310 |
| 0.94 | `annual` | `9275043c506b` | 9,157 | 183,142 | 879,564 |
| 0.94 | `event` | `989bc3ec5a9e` | 9,157 | 183,142 | 879,564 |
| 0.94 | `event_conditional` | `5f1d341ed1af` | 13,512 | 269,861 | 791,053 |
| 0.95 | `annual` | `fce1b208d097` | 9,157 | 183,142 | 879,564 |
| 0.95 | `event` | `44d4d9158061` | 9,157 | 183,142 | 879,564 |
| 0.95 | `event_conditional` | `71718bcbd1d5` | 14,158 | 282,747 | 807,051 |
| 0.96 | `annual` | `6cdc86585a9c` | 9,157 | 183,142 | 879,563 |
| 0.96 | `event` | `1ecb9c641413` | 9,157 | 183,142 | 879,563 |
| 0.96 | `event_conditional` | `4d36d8abc401` | 15,117 | 301,896 | 837,550 |
| 0.97 | `annual` | `4b973e4cf17f` | 9,176 | 183,519 | 872,313 |
| 0.97 | `event` | `bbce21970d4b` | 9,180 | 183,602 | 871,185 |
| 0.97 | `event_conditional` | `7cdafaebf254` | 17,324 | 345,968 | 931,832 |
| 0.98 | `annual` | `ea832697a610` | 9,552 | 191,015 | 826,605 |
| 0.98 | `event` | `1dd0741239b3` | 9,732 | 194,607 | 812,117 |
| 0.98 | `event_conditional` | `90556a200fad` | 19,384 | 387,131 | 1,030,160 |
| 0.99 | `annual` | `77f815e403a2` | 11,458 | 228,921 | 763,922 |
| 0.99 | `event` | `d61885393ecf` | 11,448 | 228,714 | 764,791 |
| 0.99 | `event_conditional` | `62527053755d` | 22,234 | 444,106 | 1,181,520 |

Observations:

6. On `annual` and `event`, the design doesn't change from β = 0.90 to 0.96: the same annual KPIs as the E[U] design (observation 4). It moves from β = 0.97. At β = 0.99 the annual CVaR₀.₉₉ is 763,922, 13 % below the E[U] design's 879,564, at an annual E[U] 25 % higher (11,458 vs 9,157).
7. On `event_conditional`, the design moves at every β, and the annual CVaR₀.₉₉ is not monotone in β. Its lowest values, 764,906–769,030, are at β 0.90–0.92. At β 0.99 it is 1,181,520, above the E[U] design's 879,564.
8. Annual CVaR₀.₉₉ is the mean of the worst 1 % of (year, copy) slots, i.e. the 100-year level. Of the designs here, the annual β = 0.99 design and the event-conditional β = 0.90–0.92 designs are within 1 % of each other on it (763,922 to 769,030). Their annual E[U] differ: 11,458 vs 11,126–12,192.

## Re-timing with draws (MAR-25 note)

MAR-25 timed one design LP on the thesis portfolio with 1–50 vulnerability draws on the event-conditional basis (`docs/methodology/vulnerability.md`, "Number of draws and runtime"). At 50 draws CLARABEL didn't return an accepted result, and the policy fell back to HiGHS (96 s for asset A1, 144 s for the portfolio). `timing.py` repeats that setup on both bases:

- no threshold filter;
- weighted CVaR, α 0.5, β 0.99;
- 10 bins on [20, 70];
- pure premium, `Budget(1.0)`;
- default solver policy;
- asset A1 alone and the portfolio.

**One difference: the draws are the thesis noise layer, not vulnerability draws.** `noise.add_noise`, heteroscedastic, η 0.3, seed 42, with `n_copies` = draws, on the committed fixture (`sha256:404b0c3a…294df`). It gives the same rows, `draw_id`s and `rate / n` convention as the vulnerability draws. Only the loss values differ, so the LP sizes are the same and the solver behaviour may not be. Times are build + solve wall time, measured once each on the same shared 10-core Mac, load average about 5 at the start.

| Draws | Rows | Outcomes, event-cond. | Outcomes, annual | A1 event-cond., s | A1 annual, s | Portfolio event-cond., s | Portfolio annual, s |
|---|---|---|---|---|---|---|---|
| 1 | 6,057 | 6,057 | 4,576 | 0.30 | 0.30 | 0.66 | 0.71 |
| 10 | 60,570 | 60,570 | 45,751 | 6.67 | 4.33 | 10.44 | 9.30 |
| 20 | 121,140 | 121,140 | 91,501 | 19.19 | 11.99 | 27.01 | 18.11 |
| 50 | 302,850 | 302,850 | 228,751 | 66.32 | 63.87 | 102.97 | 81.91 |

Observations:

9. Without the threshold filter, 4,575 of the 10,000 years hold at least one storm. Per (year, draw) slot the annual basis has 24 % fewer outcomes, and so fewer Rockafellar–Uryasev auxiliaries, than the event-conditional basis (e.g. 45,751 against 60,570 at 10 draws).
10. The annual basis was faster at 10, 20 and 50 draws (single measurements: 4–37 % less time). At 1 draw the times were equal.
11. Every solve was accepted from CLARABEL on both bases, also at 50 draws. For asset A1 at 50 draws the status was `optimal_inaccurate` on both bases, which the policy accepts (thesis rule). No HiGHS fallback happened with these noise draws, unlike MAR-25's vulnerability draws. Whether CLARABEL holds at 50 vulnerability draws on the annual basis needs the MAR-25 EventSet (a CLIMADA build), which this issue didn't rebuild.
12. The event-conditional times at 1 and 10 draws are close to MAR-25's (0.3 / 6.7 / 10.4 s here, against 0.3 / 6.9 / 11.5 s).
