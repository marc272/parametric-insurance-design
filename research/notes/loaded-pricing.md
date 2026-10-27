# F-11: the thesis baseline under pure and cost-of-capital pricing

- Issue: [MAR-27](https://linear.app/marc-prinzing/issue/MAR-27/f-11-cost-of-capital-loaded-pricing) (F-11, SPEC §6.4, thesis issue M4). Written by a worker agent on 2026-10-28.
- Status: **observations only.** No interpretation. That belongs to checkpoint C1 (MAR-29).
- Method: `docs/methodology/pricing.md`. Script: `research/scripts/loaded_pricing_sweep.py`. Tables: `research/data/mar27-loaded-pricing/headline.csv` (portfolio-level KPIs, one row per run, with config hash and run id) and `problem_premiums.csv` (premium and budget use per design problem).

## Setup

- Config: `parity/configs/thesis.yaml`, its baseline only (every scope × objective, no sweeps). The only change is the `pricing` block. Everything else is the thesis setup:
  - EventSet `parity/tests/data/thesis_eventset` (checksum `sha256:404b0c3a…294df`): 9 Miami assets, heteroscedastic noise 0.3 with 13 copies, threshold 20 m/s, 13,897 rows after preparation;
  - basis `event_conditional`: the annual basis (MAR-24) isn't merged yet;
  - sample `full`: calibration and KPIs on the same rows (**in sample**);
  - step payout with 15 bins on [20, 70] m/s;
  - weighted CVaR with α = 0.9 and β = 0.95;
  - budget κ = 1, so Premium ≤ E[L];
  - KPI β = 0.95.
- Pricings: `pure`, and `cost_of_capital` with r ∈ {0, 0.06, 0.10} × q ∈ {0.99, 0.995}. That is 7 configs × 9 runs = 63 runs.
- Code: branch `marcprinzing/mar-27-f-11-cost-of-capital-loaded-pricing` with `origin/main` at 9031143 (MAR-22) merged in, default solver policy. The tables were solved twice, once before and once after the merge, from an empty store each time; both runs gave byte-identical CSVs. The loaded runs take about 35–45 s per 9 runs, against 22–29 s for pure ones.
- Portfolio E[L] = 2.0614 M. Without cover, the portfolio loss has CVaR_0.95(L) = 24.37 M (VaR 12.33 M), CVaR_0.99(L) = 45.89 M and CVaR_0.995(L) = 55.09 M.

The `premium` column is the portfolio premium under the run's own pricing: the pricing applied to the aggregate payout (`docs/methodology/pricing.md`, "Portfolio premium"). "Σ problem premiums" is the sum of the per-problem premiums, each of which its own budget constrains.

## Headline table (portfolio level)

E[π]/E[L] is the expected payout over the expected loss. Money columns are in millions, in the loss units of the EventSet. The hash column gives the first 12 hex digits of the `sha256:` config hash; the full hashes are in `headline.csv`. The r = 0 rows are left out because they equal the `pure` rows (observation 1); their hashes are in the CSV.

| pricing | scope | objective | E[π]/E[L] | premium | Σ problem premiums | E[U] | CVaR_0.95(U) | RMSE | config hash |
|---|---|---|---|---|---|---|---|---|---|
| pure | individual | mse | 1.000 | 2.0614 | 2.0614 | 0.0950 | 1.660 | 0.816 | `3eec7ac6ed4d` |
| pure | individual | expected_uncovered | 1.000 | 2.0614 | 2.0614 | 0.0954 | 1.643 | 0.821 | `8e3e9ca927bf` |
| pure | individual | weighted_cvar | 1.000 | 2.0614 | 2.0614 | 0.1829 | 1.321 | 1.265 | `3666438e3ea9` |
| pure | cluster | mse | 1.000 | 2.0614 | 2.0614 | 0.1031 | 1.729 | 0.822 | `9cedd23cf251` |
| pure | cluster | expected_uncovered | 1.000 | 2.0614 | 2.0614 | 0.1021 | 1.713 | 0.829 | `5ebf4bdfcedf` |
| pure | cluster | weighted_cvar | 1.000 | 2.0614 | 2.0614 | 0.1460 | 1.296 | 0.960 | `e85db2607bc6` |
| pure | portfolio | mse | 1.000 | 2.0614 | 2.0614 | 0.0874 | 1.486 | 0.779 | `e134d0bea41f` |
| pure | portfolio | expected_uncovered | 1.000 | 2.0614 | 2.0614 | 0.0857 | 1.497 | 0.786 | `bbe10df69cbe` |
| pure | portfolio | weighted_cvar | 1.000 | 2.0614 | 2.0614 | 0.1324 | 1.066 | 0.957 | `71718bcbd1d5` |
| coc r=0.06 q=0.99 | individual | mse | 0.443 | 2.0542 | 2.0614 | 1.1485 | 11.175 | 3.437 | `60db9806f9b3` |
| coc r=0.06 q=0.99 | individual | expected_uncovered | 0.695 | 2.0614 | 2.0614 | 0.6785 | 12.863 | 4.063 | `fe6502bbd003` |
| coc r=0.06 q=0.99 | individual | weighted_cvar | 0.536 | 2.0612 | 2.0614 | 0.9560 | 10.419 | 3.545 | `5dba191dd996` |
| coc r=0.06 q=0.99 | cluster | mse | 0.451 | 2.0614 | 2.0614 | 1.1327 | 11.077 | 3.407 | `75da66ce760f` |
| coc r=0.06 q=0.99 | cluster | expected_uncovered | 0.697 | 2.0614 | 2.0614 | 0.6772 | 12.779 | 4.061 | `b20b147ce5fa` |
| coc r=0.06 q=0.99 | cluster | weighted_cvar | 0.521 | 2.0614 | 2.0614 | 0.9892 | 10.319 | 3.513 | `56de33b3c95c` |
| coc r=0.06 q=0.99 | portfolio | mse | 0.448 | 2.0614 | 2.0614 | 1.1371 | 10.962 | 3.400 | `e558646e58cc` |
| coc r=0.06 q=0.99 | portfolio | expected_uncovered | 0.696 | 2.0614 | 2.0614 | 0.6686 | 12.802 | 4.061 | `f743b244697c` |
| coc r=0.06 q=0.99 | portfolio | weighted_cvar | 0.518 | 2.0614 | 2.0614 | 0.9942 | 10.237 | 3.509 | `e5456b706725` |
| coc r=0.06 q=0.995 | individual | mse | 0.469 | 2.0608 | 2.0614 | 1.0950 | 10.619 | 3.512 | `4082273919d0` |
| coc r=0.06 q=0.995 | individual | expected_uncovered | 0.695 | 2.0614 | 2.0614 | 0.6785 | 12.863 | 4.063 | `8199e1523ec4` |
| coc r=0.06 q=0.995 | individual | weighted_cvar | 0.536 | 2.0614 | 2.0614 | 0.9560 | 10.419 | 3.545 | `baf02f522203` |
| coc r=0.06 q=0.995 | cluster | mse | 0.480 | 2.0614 | 2.0614 | 1.0716 | 10.470 | 3.491 | `75b18dfacc6c` |
| coc r=0.06 q=0.995 | cluster | expected_uncovered | 0.697 | 2.0614 | 2.0614 | 0.6772 | 12.779 | 4.061 | `dfc60a459de9` |
| coc r=0.06 q=0.995 | cluster | weighted_cvar | 0.521 | 2.0614 | 2.0614 | 0.9892 | 10.319 | 3.513 | `6f4c4bc0f3dd` |
| coc r=0.06 q=0.995 | portfolio | mse | 0.477 | 2.0614 | 2.0614 | 1.0773 | 10.389 | 3.485 | `b67dc111baaa` |
| coc r=0.06 q=0.995 | portfolio | expected_uncovered | 0.696 | 2.0614 | 2.0614 | 0.6686 | 12.802 | 4.061 | `8ea412840559` |
| coc r=0.06 q=0.995 | portfolio | weighted_cvar | 0.518 | 2.0614 | 2.0614 | 0.9942 | 10.237 | 3.509 | `600dab565666` |
| coc r=0.1 q=0.99 | individual | mse | 0.399 | 2.0602 | 2.0614 | 1.2394 | 13.528 | 4.169 | `15cf007f07f5` |
| coc r=0.1 q=0.99 | individual | expected_uncovered | 0.627 | 2.0614 | 2.0614 | 0.8294 | 15.491 | 4.537 | `4cb55ec4f334` |
| coc r=0.1 q=0.99 | individual | weighted_cvar | 0.452 | 2.0613 | 2.0614 | 1.1291 | 13.189 | 4.174 | `4f481aa2d51f` |
| coc r=0.1 q=0.99 | cluster | mse | 0.411 | 2.0614 | 2.0614 | 1.2146 | 13.427 | 4.144 | `f40618c6eea3` |
| coc r=0.1 q=0.99 | cluster | expected_uncovered | 0.624 | 2.0614 | 2.0614 | 0.8279 | 15.376 | 4.521 | `a0a2750f2624` |
| coc r=0.1 q=0.99 | cluster | weighted_cvar | 0.439 | 2.0614 | 2.0614 | 1.1570 | 13.059 | 4.155 | `90e586a4d0d2` |
| coc r=0.1 q=0.99 | portfolio | mse | 0.409 | 2.0614 | 2.0614 | 1.2188 | 13.372 | 4.143 | `0d1fed9fd5d8` |
| coc r=0.1 q=0.99 | portfolio | expected_uncovered | 0.621 | 2.0614 | 2.0614 | 0.8231 | 15.386 | 4.516 | `475d89ce072c` |
| coc r=0.1 q=0.99 | portfolio | weighted_cvar | 0.437 | 2.0614 | 2.0614 | 1.1612 | 13.041 | 4.160 | `0a2fb904b26c` |
| coc r=0.1 q=0.995 | individual | mse | 0.407 | 2.0614 | 2.0614 | 1.2216 | 13.303 | 4.173 | `32466c9c8aca` |
| coc r=0.1 q=0.995 | individual | expected_uncovered | 0.627 | 2.0614 | 2.0614 | 0.8294 | 15.491 | 4.537 | `f91f8e9fb072` |
| coc r=0.1 q=0.995 | individual | weighted_cvar | 0.452 | 2.0614 | 2.0614 | 1.1291 | 13.189 | 4.174 | `d93dfdca68d3` |
| coc r=0.1 q=0.995 | cluster | mse | 0.423 | 2.0614 | 2.0614 | 1.1902 | 13.099 | 4.151 | `685207b156f8` |
| coc r=0.1 q=0.995 | cluster | expected_uncovered | 0.624 | 2.0614 | 2.0614 | 0.8279 | 15.376 | 4.521 | `216d3564ab62` |
| coc r=0.1 q=0.995 | cluster | weighted_cvar | 0.439 | 2.0614 | 2.0614 | 1.1570 | 13.059 | 4.155 | `815b22c1862a` |
| coc r=0.1 q=0.995 | portfolio | mse | 0.421 | 2.0614 | 2.0614 | 1.1938 | 13.118 | 4.152 | `311c3b8238cf` |
| coc r=0.1 q=0.995 | portfolio | expected_uncovered | 0.621 | 2.0614 | 2.0614 | 0.8231 | 15.386 | 4.516 | `555a92ac8036` |
| coc r=0.1 q=0.995 | portfolio | weighted_cvar | 0.437 | 2.0614 | 2.0614 | 1.1612 | 13.041 | 4.160 | `2fa976bb1994` |

## Weighted CVaR against the other objectives, on CVaR_0.95(U)

This is the relative difference of the portfolio CVaR_0.95(U) of the weighted-CVaR design against the MSE and E[U] designs of the same scope. Negative means the weighted-CVaR design has the lower tail KPI. These are in-sample numbers.

| pricing | individual: vs MSE / vs E[U] | cluster | portfolio |
|---|---|---|---|
| pure | −20.4 % / −19.6 % | −25.0 % / −24.3 % | −28.3 % / −28.8 % |
| coc r=0.06 q=0.99 | −6.8 % / −19.0 % | −6.8 % / −19.3 % | −6.6 % / −20.0 % |
| coc r=0.06 q=0.995 | −1.9 % / −19.0 % | −1.4 % / −19.3 % | −1.5 % / −20.0 % |
| coc r=0.10 q=0.99 | −2.5 % / −14.9 % | −2.7 % / −15.1 % | −2.5 % / −15.2 % |
| coc r=0.10 q=0.995 | −0.9 % / −14.9 % | −0.3 % / −15.1 % | −0.6 % / −15.2 % |

## Observations

1. **r = 0 equals pure.** For both q, every run's `payouts` table is identical to the pure run's (`DataFrame.equals`). `runs.premium` and `runs.objective_value` are equal bit for bit, and so are the KPI rows. Only the config hash differs.
2. **The budget binds everywhere.** In all 63 runs every design problem uses its whole budget: the problem premium over κ·E[L] lies in [0.9999953, 1.0000000] (`problem_premiums.csv`). Under the loads, the expected payout is 0.44–0.70 of E[L] at r = 0.06 and 0.40–0.63 at r = 0.10, against 1.00 under pure pricing.
3. **Tail KPIs grow by an order of magnitude.** CVaR_0.95(U) goes from 1.07–1.73 M (pure) to 10.2–12.9 M (r = 0.06) and 13.0–15.5 M (r = 0.10). The uncovered CVaR without cover is 24.37 M. E[U] goes from 0.09–0.18 M to 0.67–1.24 M.
4. **Order of the objectives on CVaR_0.95(U).** In every scope and pricing, the weighted-CVaR design has the lowest CVaR_0.95(U) of the three objectives. Under the loads, MSE comes second and E[U] third. The margin over MSE falls from 20–28 % (pure) to 0.3–6.8 % (loaded); the margin over E[U] falls to 15–20 % (second table).
5. **Order of the objectives on E[U].** Under pure pricing, the E[U] and MSE designs are within 2 % of each other, and the weighted-CVaR design is higher (0.13–0.18 M). Under every load, the order is E[U] < weighted CVaR < MSE in each scope.
6. **q = 0.99 against q = 0.995.** For the E[U] and weighted-CVaR designs, the KPIs are the same at both q, to the precision shown, for each r. The implied payout CVaR, (premium − (1 − r)·E[π]) / r, is the same at both levels. So, for these designs, the payout is flat over its worst 1 % of probability mass. The MSE designs differ between the two levels. At q = 0.995 they pay more on average and have a lower CVaR_0.95(U).
7. **Portfolio premium against the sum of problem premiums.** The load priced on the aggregate payout is lower than the sum of the problem premiums only in the individual scope, by up to 0.35 % (r = 0.06, q = 0.99, MSE: 2.0542 M against 2.0614 M). In the cluster scope (3 problems) the two agree to the precision shown. Under pure pricing they agree up to floating-point rounding, as the expectation is additive.

## Caveats

- In sample, on the `event_conditional` basis. Its outcomes are events, not years, so q = 0.99 is the worst 1 % of *events*. On the annual basis (MAR-24) the payout tail, and so the load, will differ.
- One budget, κ = 1. Under loading, how the results depend on κ (e.g. a κ sweep against the effective pure-premium budget) was not run.
- No confidence intervals (MAR-23). No out-of-sample split: the thesis config uses the full sample. The MAR-22 splits are on `main` now but this baseline doesn't use them.
