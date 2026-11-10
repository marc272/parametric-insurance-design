# The evaluation basis: annual, event and event-conditional

Issue MAR-24 (F-10), SPEC §6.2 (thesis issue M3). Code: `packages/core/src/parametric_insurance_design/basis.py`; config field `basis`. Tests: `packages/core/tests/test_basis_annual.py`, `packages/core/tests/test_engine_properties_bases.py`. The rerun of the thesis config on the three bases is in `research/notes/annual-basis-rerun.md`.

See also: [the tail-risk objective](../concepts/tail-risk-objective.md) (what β means on each basis, and when the weighted-CVaR design is the E[U] design).

## Why

The thesis rescales the event probabilities to sum to one after the threshold filter. Its distribution is conditional on "an event above the threshold", so:

- β has no return-period meaning;
- the budget κ·E[L] is per event above the threshold, not per year;
- the dropped events and the years without events vanish from the measure.

The `annual` basis fixes this: outcomes are simulated years, so the expected uncovered loss, the premium and the budget are annual, and CVaR_β is over years.

## The three bases

Every objective, premium, constraint and KPI is computed on one `OutcomeMeasure` (ADR 0002 §4): each EventSet row belongs to one outcome, per-row quantities are summed into outcomes, and outcomes carry probabilities that sum to one. Only the measure depends on the basis.

Notation: `w_e` the rate of row `e`, `Y` the EventSet's `n_years`, `S` the years the rows represent (the sample's years, all `Y` by default), `D` the number of draws per event (1 without draws).

| Basis | Outcome | Probability | Zero-loss mass |
|---|---|---|---|
| `event_conditional` (thesis parity only) | one per row | `w_e / Σ w` over the rows given | none: dropped rows and empty years vanish |
| `event` | one per row, plus "no event" | `w_e · Y / \|S\|` (the unrescaled annual rate) | the "no event" outcome, `1 − Σ` |
| `annual` (paper default) | one per simulated year and draw | `1 / (\|S\| · D)` per (year, draw) slot | every slot without rows |

**Annual.** The uncovered loss of a year is `U_y = Σ_{e∈y} (L_e − π_e)^+`: per-event shortfalls add up, and an over-payment in one event doesn't offset a shortfall in another. With draws (noise copies or vulnerability draws), each draw is one simulated version of its year (SPEC §5), so outcomes are per (year, draw). The premium is the annual expected payout, `E[π_y] = Σ_e w_e π_e`. The budget `Premium ≤ κ·E[L]` compares it with the expected annual loss.

- The draw count comes from the rates. The draw-row convention gives every row `w_e = 1 / (Y · D)` (SPEC §5). On the annual basis a row whose rate doesn't fit one integer `D`, or a `draw_id` outside `[0, D)`, raises `InputMismatchError`. A rate that disagrees with the year structure would make `E[·]` over years differ from `Σ_e w_e (·)`.
- Years without rows are kept. All slots without rows are pooled into one last outcome, with probability `(number of empty slots) / (|S| · D)`. Every per-row quantity is 0 there, and a discrete distribution doesn't change when atoms at the same value merge. So pooling changes no expectation, quantile, CVaR, correlation or exceedance curve. It keeps the number of outcomes, and so of Rockafellar–Uryasev auxiliaries, at most `n_rows + 1`. Without pooling it would be `|S| · D`, which is 130,000 on the thesis data (10,000 years × 13 noise copies), against 13,131 outcomes with pooling.
- On a sample (e.g. the training years), probabilities count the sample's years, not the EventSet's `n_years`.

**Event.** One outcome per row with its own annual rate, so the expected values equal the annual basis's: `E[U] = Σ_e w_e U_e` on both. Only the tail differs. On the event basis, CVaR_β is the mean over the worst `1 − β` of annual event probability. This is close to an occurrence (OEP-type) tail when years rarely hold more than one event. The remaining mass `1 − Σ` is a "no event" outcome without rows. The rows' rates must therefore sum to at most one event per year (`Σ_e w_e · Y/|S| ≤ 1`), otherwise building the measure raises. On the thesis data the sum is 0.107 after the 20 m/s filter (1,069 storms in 10,000 years). On a sample the rates are re-expressed over the sample's years (factor `Y / |S|`, 1 on the full sample): an event seen once in `|S|` years has annual rate `1/|S|`.

**Event-conditional.** Unchanged: `rate / Σ rate` over the rows given. The parity runs stay bit-identical (MAR-24 PR, `run_default_parity.py --check`).

**One event per year.** With exactly one event in every year and no draws, the event and annual bases give the same outcomes and probabilities, in a different order on a sample. Every objective, premium and KPI then agrees (`test_one_event_per_year_designs_agree`).

## β and the return period

On the `annual` basis, `VaR_β` of the yearly uncovered loss is the level exceeded with probability `1 − β` per year, i.e. the `T = 1/(1 − β)`-year level, and `CVaR_β` is the mean of the worst `1 − β` of years. `evaluate.exceedance_curves` uses the same quantile (its `aep` curve).

| β | Worst share of years | Return period T = 1/(1 − β) | CVaR_β on the annual basis |
|---|---|---|---|
| 0.5 | 50 % | 2 years | mean of the worst half of years |
| 0.8 | 20 % | 5 years | mean of years at or beyond the 5-year level |
| 0.9 | 10 % | 10 years | … the 10-year level |
| 0.95 | 5 % | 20 years | … the 20-year level |
| 0.96 | 4 % | 25 years | … the 25-year level |
| 0.98 | 2 % | 50 years | … the 50-year level |
| 0.99 | 1 % | 100 years | mean of the worst 1 % of years |
| 0.995 | 0.5 % | 200 years | … the 200-year level |
| 0.996 | 0.4 % | 250 years | … the 250-year level |
| 0.999 | 0.1 % | 1,000 years | … the 1,000-year level |

"At or beyond the T-year level" is exact when `1 − β` is a whole number of years' probability. Otherwise CVaR takes the fractional part of the year at the VaR, as the Rockafellar–Uryasev form does.

Notes:

- On the `event` basis the same β reads as an annual occurrence probability: `T ≈ 1/(1 − β)` years between events at least that bad. The approximation holds when years rarely hold several bad events. In the thesis data, 56 of the 1,010 years with an event above 20 m/s have two or three such events.
- On `event_conditional`, `1 − β` is a share of the events above the threshold, not of years. The return period it corresponds to depends on the threshold and the catalogue. In the thesis data, the worst 5 % of the 1,069 storms above 20 m/s (13,897 rows with the 13 noise copies) weigh as much as about 53 storms in 10,000 years, a return period of about 190 years. That's why the thesis β (0.95) can't be read as a 20-year level.
- With several draws per year (D > 1, e.g. noise copies), the return periods on the `annual` basis are still in years, for any D: each (year, draw) slot has probability `1 / (|S| · D)`, so a share `1 − β` of the slots is a probability `1 − β` per year. The curve is a mixture over the draws: the `|S| · D` slots share the hazard of `|S|` years, so they are not `|S| · D` independent years of record. On the thesis data (D = 13) the 130,000 slots carry the information of 10,000 years, and a 1,000-year level rests on the worst 130 slots, which can come from as few as 10 distinct years (MAR-139).
- In the thesis data, 89.9 % of the (year, draw) slots have no event above the threshold. On the annual basis the uncovered loss of those years is 0, so VaR_β is 0 for every β ≤ 0.899 and CVaR_β only sees the worst `1 − β` of years.

## Decision: MSE on a grouped basis (MAR-24)

`MSE` squares each outcome's summed residual:

```
MSE = Σ_y p_y (L_y − π_y)²,   L_y − π_y = Σ_{e∈y} (L_e − π_e)
```

and not `Σ_y p_y Σ_{e∈y} (L_e − π_e)²`. The two agree on per-row bases (`event_conditional`, `event`, and `annual` with one event per year). Reasons:

1. **The annual basis measures the year.** The risk owner's net position in a year is `L_y − π_y`, and the premium and the budget are annual too. Squaring each event's residual would score the design per event while everything else is per year.
2. **The objective equals its KPI.** `evaluate.kpis` reports `rmse_residual = sqrt(E[R_y²])` with `R_y = Σ_{e∈y} (L_e − π_e)`, so on every basis the MSE design minimises exactly the `rmse_residual` reported for it.
3. **The alternative is degenerate.** `E[Σ_{e∈y} (L_e − π_e)²] = Σ_e w_e (L_e − π_e)²`, the event-basis MSE. The annual MSE design would then be the event design for any year structure, and the annual basis would change nothing for MSE.

The cost: within a year, an over-payment offsets a shortfall in the MSE (signed residuals add up), while `U_y` doesn't let them offset. This is the intended difference between the two measures: MSE is a two-sided fit of the annual total, and E[U] and CVaR count one-sided shortfalls per event. `test_mse_squares_the_summed_yearly_residual` and the grouped-measure cases in `test_objectives.py` pin the choice. This is a method choice within SPEC §6.2. It changes no SPEC §11 decision.
