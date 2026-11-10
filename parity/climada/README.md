# parity/climada/: golden fixtures for `climada_petals.engine.parametric`

The CLIMADA module is built in a fork of `climada_petals`. Its tests never import this repository's core, `parametric_insurance_design`, and petals accepts only small test files. So the parity with the thesis-faithful core is this small set of fixtures, and closed-form cases where the core has no counterpart. K-18 and K-19 copy `samples/` and `cases/` into the fork's test data.

- 48 cases and 7 samples, all synthetic or hand-made. The whole folder, this page included, stays within **200 KB** (200,000 bytes); a test enforces it.
- The format is ADR 0006 §12, accepted on 2026-11-10 (MAR-312, K-13). Where it goes beyond §12, [Beyond ADR 0006 §12](#beyond-adr-0006-12) says how.
- The script is `parity/scripts/export_climada_fixtures.py`, the test `parity/tests/test_climada_fixtures.py`. The script uses `parametric_insurance_design` alone: nothing from crc-sdk, CRC data or CLIMADA.

These are test values on small synthetic samples. They show what the module must compute. They say nothing about how one objective or scope compares with another.

## Licence

- The script and the test are BSD-3-Clause (`parity/LICENSE`).
- The samples and the cases are **CC0-1.0**. Their author, Marc Prinzing, dedicates them to the public domain under CC0 1.0 Universal, by accepting ADR 0006 on 2026-11-10. To the extent possible under law, he waives all copyright and related or neighbouring rights to them. Legal code: <https://creativecommons.org/publicdomain/zero/1.0/legalcode>.
- They hold no third-party data: every sample comes from this script's seeded generator or was chosen by hand. CC0 is compatible with GPL v3, so the copies in the fork carry no attribution duty.
- Every sample records `"licence": "CC0-1.0"`. `parity/README.md` and `docs/data-sources.md` record the licence too.

## Regenerate and check

From the repository root:

```bash
uv run python parity/scripts/export_climada_fixtures.py            # rewrite samples/ and cases/
uv run python parity/scripts/export_climada_fixtures.py --check    # compare, write nothing
uv run python parity/scripts/export_climada_fixtures.py --summary  # rewrite, print the case table
uv run pytest parity/tests/test_climada_fixtures.py                # what CI runs
```

CI runs the test in the parity step (`pytest parity/tests`). It regenerates every sample and case in memory and judges the committed files against them:

- Everything but floats must be equal, except `generator.commit`. Floats agree within 1e-6 relative for the values a solve produces, and within 1e-12 elsewhere.
- In every design case from the core, the core evaluates `expected.parameters` again, and the objective, the premium and every metric must agree within 1e-12. The levels must meet every constraint, reach the regenerated optimum within 1e-6, and in LP cases lie within the regenerated ranges. Only a unique design also has its levels, premium and metrics compared with the regenerated ones: a solver on another platform can return another point of a non-unique optimum. The test repeats the check with perturbed solvers.

The test also reads every case the way the module's tests do, with plain numpy and the rules on this page only, and it solves every LP design again from ADR 0006 §5.1 and §6 with scipy's HiGHS. It checks the size limit, the case matrix, the shared samples and the licence records.

## A sample: `samples/<name>.json`

| Field | Meaning |
|---|---|
| `event_id` | One integer per event |
| `frequency` | The event's frequency per year |
| `year` | The event's catalogue year, from 0, or null if the sample has none |
| `parent` | Null in every sample here: no case splits a sample |
| `unit_id` | The insured units, in column order |
| `index`, `loss` | `n_events` rows with one value per unit |
| `index_unit`, `loss_unit` | Units of measure. The loss unit is the cover's `payout_unit` |
| `licence` | `CC0-1.0` |

## A case: `cases/<case_id>.json`

The id is `<payout>-<objective or "fixed">-<pricing>-<basis>-<scope>-<sample>`. The payout is `step`, `linear`, `piecewise-linear` or `binary`, with `-lower` for a lower tail.

| Field | Value | Meaning |
|---|---|---|
| `case_id` | string | The file name without `.json` |
| `kind` | `"design"` or `"evaluate"` | Calibrate the template, or evaluate a fixed cover |
| `source` | `"core"` or `"closed_form"` | Who computed `expected` |
| `sample` | `"samples/<name>.json"` | The shared sample |
| `basis` | `{"kind": "event"}` or `{"kind": "annual", "route": "catalogue", "n_years": N}` | ADR 0006 §5 |
| `scope` | `"individual"` or `"joint"` | §6.1; `"joint"` is the core's `Portfolio()` |
| `cover` | object | The cover: a template in design cases, resolved in evaluate cases |
| `objective` | object or null | `{"kind": "mse"}`, `{"kind": "expected_uncovered"}` or `{"kind": "weighted_cvar", "alpha": α, "beta": β}`; null when evaluating |
| `pricing` | object | `{"kind": "pure"}` or `{"kind": "cost_of_capital", "rate": r, "q": q}` |
| `budget` | object or null | `{"ratio": κ}`: premium at most κ·E[L]. Null when evaluating |
| `limit` | object or null | `{"rule": "largest_loss"}` in design cases: `Limit.largest_loss()`. Null when evaluating |
| `expected` | object | The values the module must reproduce |
| `compare_parameters` | `"exact"`, `"within_ranges"` or `"none"` | How a design's parameters compare |
| `tolerances` | object | `objective_value`, `premium`, `metrics`, `parameters`: 1e-6 each |
| `generator` | object | `script`, `core_version` and `commit` |

### `cover`

The field names are the constructor arguments of ADR 0006 §2, so a test can build the cover from them:

- `index`: `IndexDefinition(kind, unit, tail, index_stat, weight, source, parameters)`. Here `kind` is `"table"` and `source` `"synthetic"`, with the rest null, because a sample gives the index directly.
- `payout`: one document for every unit, or a mapping by unit id (case `step-fixed-coc-event-joint-h3`).
  - `{"kind": "step", "breakpoints": [...], "levels": [...], "tail": ..., "monotone": true}`
  - `{"kind": "linear", "attachment": a, "exhaustion": e, "limit": ℓ, "tail": ...}`
  - `{"kind": "piecewise_linear", "knots": [...], "levels": [...], "tail": ..., "monotone": true}`
  - `{"kind": "binary", "trigger": t, "amount": A, "tail": ...}`
- A free amount is `{"free": {"lower": 0.0, "upper": null, "grid": null}}`: `Free()`. Every threshold is a number.
- `unit_id`, `payout_unit`, `label` (null) and `limit`, the same as the case's `limit`.

The payouts are ADR 0006 §3's. Nothing is paid below the first threshold, and the core runs at `below_attachment="zero"` (`first_bin` is retired). A value equal to a threshold belongs to the more severe side. With `tail: "lower"`, the severity is minus the index, and the thresholds are written in index units in order of increasing severity (decreasing values).

### `expected`

| Field | Design cases | Evaluate cases |
|---|---|---|
| `objective_value` | The objective at `parameters` | null |
| `premium` | The premium at `parameters`, on the sample | The premium of the fixed cover |
| `parameters` | `{unit: {"levels[0]": …}}`, or `"limit"`, `"amount"` | null |
| `unidentified` | `{unit: [names]}`: amounts whose basis is zero at every event | null |
| `unique` | Whether every design problem's identified amounts are unique | null |
| `metrics` | Column → value (below) | Column → value |

**Scope.** `individual` has one design problem per unit, with its own objective, premium and budget. So `objective_value`, `premium` and `metrics` are mappings by unit id. `joint` has one design problem, on the total per event: those three are single values, the module's `"total"` row. `parameters` and `unidentified` are by unit in both.

**Unidentified amounts** follow `fill="lowest"` (ADR 0006 §6.5): the previous identified level, or 0 if there is none.

## What an outcome is

ADR 0006 §5.1, in terms of a sample:

- **Annual**, route `catalogue`: one outcome per year 0 … N − 1, weight 1/N, years without an event included. The frequencies are all 1/N.
- **Event**: one outcome per event, weight f_e. Where the frequencies sum to less than 1, the missing mass 1 − Σf is one more outcome with zero loss and payout. Where they sum to more than 1, the weights are the frequencies, with no rescaling, and 1 − β is a frequency per year.

Inside an outcome o: L_o = Σ L_e, π_o = Σ π_e, U_o = Σ (L_e − π_e)^+, R_o = L_o − π_o. A joint design works on each event's total over the units first. The objectives are §6.2's and the premium is §6.3's, on these outcomes, with weights p_o.

**Quantiles.** `VaR_β(X)` is the smallest x whose exceedance weight is at most 1 − β. The weights are exact here, so a level exactly on a step is known. A floating-point sum can land on either side of it, so such a value is written `{"either": [lower, upper]}`, and either passes. A rule with §7's tolerance gives the lower one. `CVaR_β(X) = VaR_β(X) + E[(X − VaR_β(X))^+] / (1 − β)`, always one value.

### Metrics

The definitions are ADR 0006 §7's, with `MetricOptions()` defaults at ℓ = 0 and ε = 0. To stay within the limit a case lists a subset of the columns: β in {0.9, 0.99} and T in {2, 10, 50}. A test compares the columns a case lists and may ignore the others.

- Every case has `expected_loss`, `expected_payout`, `premium`, `expected_uncovered`, `payout_to_loss_ratio`, `rmse`, `correlation`, `var_` and `cvar_` of `uncovered`, `loss` and `net_loss`, and `loss_rp<T>`, `payout_rp<T>`, `uncovered_rp<T>` and `net_loss_rp<T>`.
- The closed-form cases add what the core lacks: `coverage_ratio`, `tail_coverage_b<β>`, `cvar_uncovered_to_loss_b<β>`, `payout_frequency`, `false_negative_rate_l0` and `false_positive_rate_l0`.
- `net_loss` columns are null on the event basis, as §7 says.
- `coverage_ratio` is 1 − E[U]/E[L], and `tail_coverage` is `Σ w (L − U) / Σ w L`, so a year's several events count one by one.
- `correlation` is the Pearson correlation with the outcome weights; on the event basis the weights are the frequencies, and the missing mass counts where the frequencies sum to less than 1.
- `false_positive_rate_l0` on the event basis has only the file's events in its denominator (§7), so the missing mass isn't in it.

## How to compare

Call the scale of a case the largest total loss of one event: the maximum over the events of the sum over the units, at least 1.

**Evaluate cases.** Evaluate the fixed cover on the sample with `pricing`, and compare `premium` and every listed column.

**Design cases.** Calibrate the template on the sample with `objective`, `pricing`, `budget`, `limit` and `scope`. Then:

1. Compare `objective_value`, per design problem.
2. Compare the parameters as `compare_parameters` says, leaving out `unidentified`:
   - `"exact"`: every amount within `tolerances.parameters` times the scale;
   - `"within_ranges"`: the module ranges the optimal set (`ranges=True`), and every amount of `expected.parameters` lies within the module's range, widened by that tolerance;
   - `"none"`: not compared.
3. Compare `premium` and `metrics`: on the module's design where `unique` is true; otherwise on the template resolved with `expected.parameters`.
4. The module's `unique` must not be true where the case's is false.

### Tolerances, once

| Value | Passes if |
|---|---|
| `objective_value` | within 1e-6 relative; absolute floor 1e-9 × the scale (the scale squared for MSE) |
| `premium` | within 1e-6 relative; absolute floor 1e-9 × the scale |
| a metric | within 1e-6 relative; absolute floor 1e-9 × the scale, and 1e-9 for the unitless ones (`coverage_ratio`, `payout_to_loss_ratio`, `payout_frequency`, `correlation`, `tail_coverage_*`, `cvar_uncovered_to_loss_*`, `false_negative_rate_*`, `false_positive_rate_*`) |
| a parameter | within 1e-6 × the scale, absolute |

1e-6 is the tolerance of the prototype's parity test, `packages/climada/tests/test_petals_parametric_parity.py`. The floors matter near zero: a solver's levels are exact only to rounding, so an uncovered loss of 0 in exact arithmetic can be a few units in the last place.

## The cases

| Family | Cases | `kind`, `source` |
|---|---|---|
| Step designs | {MSE, E[U], weighted CVaR at β 0.9} × {annual on `s1`, event on `s2`} × {individual, joint} × {pure, cost of capital}: 24 | design, core |
| The example of ADR 0006 §12 | `step-wcvar-b0_99-pure-annual-joint-s1`; its tail is a single year: 1 | design, core |
| Fixed covers, Σf ≤ 1 | {linear, piecewise linear, binary} on `h1`, annual and pure, and event and cost of capital: 6 | evaluate, closed_form |
| Fixed covers, Σf above 1 | {step, linear, piecewise linear with cost of capital, binary} on `h2`: 4 | evaluate, closed_form |
| Fixed joint covers | linear on `s1`, annual; step with a payout per unit on `h3`, event, Σf above 1, cost of capital: 2 | evaluate, closed_form |
| Fixed covers, lower tail | {step, linear, piecewise linear, binary} on `h4`, annual: 4 | evaluate, closed_form |
| Designs with one free amount | binary and linear, on `h1` and on `h2` (Σf above 1), under MSE, E[U] and weighted CVaR at β 0.9: 6 | design, closed_form |
| A piecewise-linear design | MSE on `h5`, whose losses lie on the curve: 1 | design, closed_form |

Every design has `budget` 0.8 (1.2 in the piecewise-linear one), `limit` `largest_loss`, and weighted-CVaR weight α 0.9. The cost-of-capital pricing is rate 0.06 at q 0.99.

**One free amount.** The payout of event e is A·b_e, with b_e in [0, 1]. The premium is c·A, with c = E[b], or (1 − r)·E[b] + r·CVaR_q(b) under the load. With the limit and the budget, A lies in [0, A_max], A_max = min(largest loss, κ·E[L] / c).

- E[U] and weighted CVaR do not increase in A, so A_max is optimal. It is the only optimum when some event with b_e > 0 has L_e ≥ A_max·b_e.
- MSE is a quadratic in A, smallest at E[b·L] / E[b²] over the outcomes, clipped to [0, A_max], and unique.

In `binary-eu-pure-event-individual-h2` the limit binds, not the budget.

**The piecewise-linear design.** Every loss of `h5` equals the payout at its index, so the objective is 0 at the curve's levels, its minimum, and the budget does not bind.

## The samples

| Sample | Events × units | Frequencies | Holds |
|---|---|---|---|
| `s1` | 32 × 2, in 40 years | 1/40 each, Σf = 0.8 | Several events in some years, indices on breakpoints; `u2`'s index stays below the last breakpoint, so its last level is unidentified |
| `s2` | 30 × 2, no years | Non-uniform, Σf below 1 | The core's event basis with frequencies that differ; `u2`'s last level is unidentified |
| `h1` | 14 × 1, in 16 years | 1/16 each | Hand-made. Years 3 and 8 hold a large and a small event; thresholds on index values; a loss below the attachment, an index above it with no loss |
| `h2` | 12 × 1, no years | Non-uniform, Σf = 3.2 | Hand-made. Rows out of order of severity. From the top, the cumulative frequency passes through 0.02, 0.1 and 0.5, so quantiles lie on steps |
| `h3` | 8 × 2, no years | Non-uniform, Σf = 2.0 | Hand-made, for a joint cover with Σf above 1 |
| `h4` | 12 × 1, in 20 years | 1/20 each | Hand-made drought index, lower tail |
| `h5` | 10 × 1, in 20 years | 1/20 each | Hand-made. Every loss lies on the curve of the piecewise-linear design |

`s1` and `s2` come from `numpy.random.default_rng`, seeds 20261110 and 20261111. A storm has intensity 22 + Gamma(2, 7) m/s. The hazard at `u1` adds N(0, 3), and at `u2` it is 0.85 of the intensity plus N(0, 3). The loss is the unit's value (10 and 6 million USD) times the damage ratio v³ / (1 + v³), v = max(h − 25.7, 0) / 49. The index is the hazard plus another N(0, 3), floored at 0, so index and loss differ. Indices are rounded to 0.01 m/s and losses to whole USD. Step breakpoints are 25, 30, 36, 43 and 51 m/s.

### Core settings

- `StepPayout(attachment=25, limit=60, n_bins=5, breakpoints=(25, 30, 36, 43, 51, 60), below_attachment="zero")`. The core has one more edge than the module; values at or above it fall into the last bin, so it changes no payout and isn't written.
- `Individual()` and `Portfolio()`; `Basis.ANNUAL` and `Basis.EVENT`, the latter only where the frequencies sum to at most 1, because the core raises above that; `Budget(0.8)`; `WeightedCVaR(alpha=0.9, beta)`; `PurePremium()` and `CostOfCapitalLoad(rate=0.06, q=0.99)`. The core caps every amount at its unit's largest event loss, which is `Limit.largest_loss()`.
- Solvers, through the core's `solve.solve`: HiGHS for the LP vertices and the ranging LPs; Clarabel with tolerances at 1e-12 for the QPs and the non-unique LPs; OSQP at 1e-12 to check the QPs. Two accurate solvers must agree within 1e-9 relative.
- A unique LP is written as HiGHS's vertex; a non-unique one as Clarabel's interior point, with `compare_parameters` `"within_ranges"`. Uniqueness is decided as in ADR 0005 §5.4: ranging at two tolerances for LPs, and the rank of the outcome-level Hessian for QPs.
- Levels within 1e-9 of the scale of zero are written as 0. Computed values are rounded to 12 significant digits; inputs are written as stored.

The closed forms are computed in exact rational arithmetic. Where the weights are a distribution, their VaR and CVaR must agree with the core's risk measures within 1e-12.

## Beyond ADR 0006 §12

1. `licence` in a sample. §12 records the licence in `parity/README.md` and `docs/data-sources.md`; the field travels with the data.
2. In the individual scope, `objective_value`, `premium` and `metrics` are mappings by unit id, since each unit is its own design problem. §12's example is a joint case.
3. `unique` is one value per case: true when every design problem's amounts are unique. That is `CalibrationResult.unique` (§6.6).
4. The field names of the cover document are §2's constructor arguments, since §12 refers to the cover document of §3 and K-15 writes it. The script's `_Fields` holds each name once, so a rename is one edit there, followed by a regeneration.
5. Absolute floors on the tolerances, as in ADR 0005 §8.
6. A case lists a subset of §7's default columns, to stay within the size limit.
7. Where the frequencies sum to more than 1 and §7 doesn't say, `correlation` uses the frequencies as weights.
8. Not in the set: splits and out-of-sample rows, free shape parameters on a grid, `unidentified_share`, and the `"total"` row of individual covers. K-17, K-18 and K-19 test those in their own files.
