# Confidence intervals: block bootstrap over years

Issue MAR-23 (F-09), SPEC §6.1 (thesis issue M1). Code: `packages/core/src/parametric_insurance_design/bootstrap.py`; the runner (`experiment/runner.py`); config section `bootstrap` (`experiment/config.py`).

## Why

A KPI from 3,000 test years is an estimate. The MAR-22 out-of-sample rerun showed gaps between in-sample and out-of-sample KPIs, and gaps between designs, that change sign across folds and bin counts. Without an uncertainty band nobody can tell a real difference from sampling noise. SPEC §6.1 asks for a block bootstrap over years, B = 1000 by default, with 90 % intervals on every reported KPI.

## Resampling unit: a year

A replicate draws |S| years with replacement from the |S| years S of the evaluation sample (`Sample.years`, years without rows included). Every row of a drawn year comes along: all its events and all their draws (the thesis noise copies, the vulnerability `draw_id`s). Events of one year can be dependent, and the draws of one event certainly are, so resampling rows would understate the uncertainty. The coverage test shows by how much: with strongly correlated events within a year, row resampling covers the true mean in 57 % of datasets instead of 90 %, and year blocks cover it in 89 %.

`resample_years(years, B, rng)` draws the year indices once, `rng.integers(0, |S|, size=(B, |S|))`. Every design evaluated on the same sample can reuse them.

## A replicate is a reweighted measure

Resampling never changes a row's loss or payout, only how much probability its outcome carries. With c_y the number of times year y was drawn, a replicate is the evaluation measure (`basis.outcome_measure`) with new outcome probabilities:

- An outcome with rows lies in one year y and gets p_o · c_y. The code checks this and raises `BootstrapError` if an outcome spans two years.
- `event_conditional`: the probabilities are conditional on an event, so they're divided by their sum. This is the thesis rescaling applied to the resampled rows.
- `event` and `annual`: the probabilities are absolute. On `event` a row has its annual rate; on `annual` each (year, draw) slot has 1 / (|S| · D). The outcomes with rows keep p_o · c_y, and the outcomes without rows take the rest, 1 − Σ p_o · c_y, shared in proportion to their probabilities. These are the `event` basis's "no event" outcome and the `annual` basis's single outcome that pools every empty (year, draw) slot (MAR-24). If no such outcome exists, the code adds a zero-valued one.
  - On `annual` this is exact. The empty slots of year y are drawn c_y times, so their total probability is the remainder. They all have value 0, so pooling them changes no KPI.
  - On `event` a replicate can need more than one event per year on average, which that basis can't represent. The code then raises `BootstrapError` and suggests the annual basis.

Duplicating an outcome c times and multiplying its probability by c give the same discrete distribution. So each replicate's KPIs (means, VaR, CVaR, correlation, premium) equal the KPIs of the concatenated resampled years. `tests/test_bootstrap.py` checks this replicate by replicate against a from-scratch concatenation, on all three bases, including the pooled empty slots and the "no event" outcome.

## Computation

- **KPIs.** The eight `evaluate` KPIs are vectorised over replicates. Each subject's per-outcome sums are computed once. For VaR and CVaR the outcome values are sorted once, because the order doesn't depend on the weights, and only the cumulative weights differ per replicate. Replicates are processed in chunks of about 2 million (replicate, outcome) cells.
- **Premium.** The premium is `pricing.premium_value` on each replicate's measure. It's generic, so the cost-of-capital load (MAR-27) needs no change here. At the portfolio level it prices the portfolio payout.
- **Array level.** `kpi_replicates` (the eight KPIs of per-row loss and payout) and `premium_replicates` (the premium of a per-row payout, MAR-153) replicate without an EventSet, on the same code as `bootstrap_kpis`: on the same rows, measure and resample, `premium_replicates` gives `bootstrap_kpis`' premium replicates bit for bit. The pooled k-fold KPIs use both.
- **VaR on a step.** When β falls exactly on a step of the distribution, for example β = 0.8 with 40 equally likely years, the summed probabilities land a rounding error above or below β. Which side depends on the summation order, and that order differs between platforms (`numpy.argsort` of tied values). The bootstrap counts a shortfall of at most 1e-10 as reaching β (summation error over 10⁴–10⁵ outcomes is about 1e-12; single-outcome probabilities are far larger), which gives the exact-arithmetic VaR. The constant is `riskmeasures.CDF_ATOL`. `var_cvar` (in `riskmeasures.py` since MAR-143, re-exported by `evaluate`; it gives `evaluate`'s VaR/CVaR KPIs, the cost-of-capital premium and, through `lower_quantile`, the exceedance curves) does **not** use it: it compares strictly, as the thesis does. At β exactly on a step its result is either the exact-arithmetic atom or the next one up, depending on the summation order of tied rows, so it can differ between platforms. It stays strict so that the parity reports reproduce the thesis golden values byte for byte (MAR-143, option B: the tolerance moved 162 `VaR_Uncovered` values of the asset-count sweep to the lower atom). A platform-independent quantile is tracked as a follow-up.
- **Drift guard.** `bootstrap_kpis` also evaluates its formulas on the unresampled measure (every year drawn once). It raises `BootstrapError` if any value differs from `evaluate.kpis` by more than 1e-9 relative (for VaR on such a step, the two adjacent atoms are both accepted, and the point value stays `evaluate`'s), or if `evaluate` reports a KPI the bootstrap doesn't know.
- **Timing.** On the thesis fixture with B = 1000, the 3,000-year test sample (about 4,200 rows) takes 1.0 s for the cluster scope, 1.9 s for the portfolio scope and 3.6 s for the individual scope (9 problems, 19 subjects), on a shared 10-core Mac. Train and test together take about 3.5 times that.

## Intervals

- **Method.** Percentile intervals: the (1 − level)/2 and (1 + level)/2 quantiles of the replicate values (`numpy.quantile`, linear). The default level is 0.9.
- **Point estimates.** They never change. The `value` column is `evaluate.kpis`'s value.
- **Undefined replicates.** If a KPI is undefined in some replicate (a payout-to-loss ratio with zero expected loss, a correlation with zero variance), its bounds are null. `KpiBootstrap.n_undefined` counts the undefined replicates, and the run manifest records them. An interval over the defined replicates alone would be conditional on them.
- **Bootstrapped rows.** `ci_level` and `n_bootstrap` are set on every row of a bootstrapped table. A null bound next to them means "bootstrapped, undefined", not "not bootstrapped".

**Coverage observed.**

- The acceptance test is a synthetic case with a known answer: E[L] = 10, and a paired difference of −2. Over 300 datasets of 150 years, both 90 % intervals cover the true value in 89 % of datasets.
- Tail measures are harder for a percentile bootstrap. For CVaR of an exponential loss, the coverage was 85 % (300 years, β = 0.9), 92 % (3,000 years, β = 0.95) and 87 % (3,000 years, β = 0.99), over 200 datasets each. Read CVaR intervals as approximate.

## Paired differences between designs

`paired_difference(a, b)` gives, for every KPI, the interval of KPI(a) − KPI(b) from the replicate differences.

- **Pairing.** Both designs must have been bootstrapped with the same `YearResample`, so each replicate compares them on the same resampled years. The function refuses different resamples.
- **Width.** Two designs' KPIs move together across years, so the paired interval is much narrower than the two separate intervals suggest.
- **Subjects.** Rows are paired on the `kpis` key without `run_id`, so both designs must describe the same subjects (the same scope).
- **Storage.** Paired differences aren't stored in the result store. The `kpis` table has no place for them, and adding one is an ADR 0002 change. They're computed on demand from `KpiBootstrap` objects (see the research script below).

## Runs: the `bootstrap` config section

```yaml
bootstrap:
  seed: 0            # required
  n_bootstrap: 1000  # default
  level: 0.9         # default
```

- **Opt-in.** The section is off by default. Without it, KPI tables are as before, with null `ci_*` columns. The section is also left out of the config hash and of the YAML when it's absent, so every existing config, including the parity configs, keeps its hash and its cache entries.
- **Part of the hash when set.** The intervals are part of the run's stored `kpis` table. A config with other bootstrap settings, or none, must therefore be another cache entry, or a cache hit would serve intervals that weren't asked for, or none at all. The price is that turning the bootstrap on re-solves the run. The solve itself doesn't depend on the bootstrap.
- **Generators.** The runner gives each evaluation sample (train, test, full) a fresh generator `np.random.default_rng(seed)`. Two runs with the same seed and the same evaluation sample therefore draw the same years, so their stored intervals rest on the same resamples, and `paired_difference` can be recomputed exactly from the seed.
- **Manifest.** The manifest's `bootstrap` entry records the settings, the time per sample and the KPIs whose bounds are null.

## Figures

The KPI figures (`packages/viz/.../kpi_figures.py`, MAR-148) draw the stored intervals. They read `ci_low`, `ci_high`, `ci_level` and `n_bootstrap` from the `kpis` table and compute nothing.

- **Performance overview** (thesis Figure 5.5): an interval bar from `ci_low` to `ci_high` on each bar. The legend names the level and B, e.g. "90% block-bootstrap interval over years (B = 1000)".
- **KPI heatmaps:** the interval in brackets as a third line in each cell, with the same text as a footnote.
- **Rows without bounds** are drawn without an interval. These are the rows of a config without a `bootstrap` section, and KPIs undefined in some replicate. Without any bounds the figures are the same as before MAR-148. The figure data's `ci_drawn` column says which rows carry an interval.
- **One level per figure.** Runs whose intervals differ in level or B are refused (`InconsistentRunsError`), because one legend can't describe both.
- **The interval is drawn as stored.** A percentile interval doesn't have to contain the point estimate. The bar is drawn from `ci_low` to `ci_high` either way.
- **Not drawn:** exceedance curves (no interval columns), and paired differences between designs (not stored; see above). The heatmap's percentage against the baseline therefore has no interval.
- **k-fold configs:** the figures draw the pooled k-fold KPIs and their intervals; see "Pooled k-fold KPIs" in [`out-of-sample.md`](out-of-sample.md#pooled-k-fold-kpis).

## Not covered

- Exceedance curves have no interval columns (`records.EXCEEDANCE`).
- Better interval methods (BCa, studentised) for tail measures aren't covered. They are a possible follow-up if the C1 analysis needs tighter coverage.
