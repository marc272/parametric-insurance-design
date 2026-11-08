# ADR 0005: Design of the `crc_sdk.parametric` module

- Status: **Accepted** (2026-11-06). The owner, Marc Prinzing, accepted all eleven recommendations of "Decisions for the owner" as written (D10, recorded on MAR-244).
- Date: 2026-11-05
- Decision issue: MAR-244 (R-12). It feeds MAR-245 (R-13, golden fixtures, which take their field names from §8), MAR-246 (R-14), MAR-43 (R-15), MAR-247 (R-17), MAR-248 (R-16), MAR-42 (R-18) and MAR-46 (R-19). Phase 2: MAR-45 (R-21), MAR-250 (R-22), MAR-44 (R-23). Questions for RiskThinking go to MAR-249 (R-20).
- Prepared by a worker agent from `main` at `56755a5`. The upstream repositories were cloned read-only and read at these commits. No upstream code was run against CRC data, and no CRC data was downloaded.
  - crc-sdk 0.11.1: [`9c56bb0`][sdk] (tag `v0.11.1`, 2026-11-04);
  - crc-framework 0.6.0: [`838c295`][fw] (tag `v0.6.0`; the later head changes only the release workflow);
  - crc-docs: [`7691f5f`][docs] (2026-11-04).
- Revised on 2026-11-05, before the owner's decision, to match the golden fixtures of MAR-245 (PR #183). The end of "Decisions for the owner" lists what changed.
- Amendments, at the end: 1 (2026-11-06, MAR-275), which records the owner's decision D11, curves first; 2 (2026-11-08, MAR-291), which records the owner's decisions D-25.1 to D-25.5, the per-year route; 3 (2026-11-08, MAR-292), which records the owner's decisions D-21.1 to D-21.6, the portfolio approach; and 4 (2026-11-08, MAR-329), which records the owner's decisions D-23.1 to D-23.6, scenario analysis.

The section "Decisions for the owner" lists what Marc decides. Every other choice below is the agent's recommendation, with the alternatives named where a choice is open.

## Context

### Requirements (owner, 2026-11-05)

Since 2026-11-05 the program's main goal is a generic parametric insurance module for Climate Risk Commons (CRC). With it, a user can:

- create a parametric cover for a hazard and an asset;
- analyse the cover's effectiveness on relevant metrics (overall coverage, tail coverage, basis risk, …) and under different scenarios;
- compare covers.

The module is generic: it makes no assumption about the assets, the impact functions, the scenarios, the optimisation goal, the payout function type or its parametrisation. Users assemble their own solutions from the parts.

- **Phase 1:** the basic functionality in crc-sdk, plus an example notebook in crc-docs.
- **Phase 2 (continuous):** multi-hazard (multi-dimensional) covers; the portfolio approach (a goal over one owner's assets, as in the thesis); analysis under scenarios.

**Where it lives (D9).** The module `crc_sdk.parametric` is built in the fork `marc272/crc-sdk` (integration branch `parametric`) and offered upstream to `RiskThinking/crc-sdk`, under AGPL-3.0-or-later. The notebook goes into a fork of crc-docs. This ADR, the golden fixtures (MAR-245) and the reference implementation (our core) stay in this repository under BSD-3-Clause.

**Rules that constrain the design:**

- The module never imports `parametric_insurance_design`. Parity is checked with golden fixtures (§8).
- Nothing new in crc-sdk's base install. A solver is an optional extra.
- crc-sdk's own rules ([`AGENTS.md`][sdk-agents]): mypy strict, ruff, offline tests, no I/O in builders or `explain()`, atomic writes, licence and provenance for every source, no breaking change to anything in `__all__`.
- No CRC Open data is committed (CC BY-NC 4.0).
- New designs pay nothing below the attachment (owner, 2026-11-01).
- The publication rule (`AGENTS.md`): tail statements only conditional on a stated setup; joint calibration only as a method; every number's setup stated; numbers from out-of-sample runs.

### Owner input, 2026-11-05

1. RiskThinking welcomes the module. Its place, `crc_sdk.parametric` in crc-sdk, is confirmed, so it is not an open question here.
2. scipy is acceptable as an optional extra, but the solver must be the best option for this module within the existing framework. §5.5 compares the options against what crc-sdk and crc-framework already ship, and recommends one.
3. The licence terms of crc-docs are out of scope for now: the owner provides the showcase on his own terms. They are not an open question here.

### What crc-sdk and crc-framework give

| # | Fact | Where |
|---|---|---|
| U1 | Every source is a lazy, immutable plan. Builders and `explain()` do no I/O; `explain(format="text")` returns JSON text and `format="json"` a dict. Work happens only at execution points: `prefetch`, `materialize`, `write_parquet` | [`docs/concepts.md`][sdk-concepts]; `explain` in [`workflows/crc_open.py`][sdk-crc-open] |
| U2 | `HazardDataset.<source>(...).for_assets(assets)` returns a `PortfolioEvaluation` with `.select(...)`, `.return_periods(...)`, `.impact(...)` and `.write_parquet(...)`. The output has one value column per return period (`value_rp100`) and its metadata under the Parquet key `crc.hazard.evaluation`. It has no `explain()` | [`workflows/portfolio.py`][sdk-portfolio-py], [`docs/portfolio.md`][sdk-portfolio] |
| U3 | The join of assets to curves (H3 cell, refined by exact geometry; several curves for one asset raise; a missing match raises) is private. It reads the curve columns, but the output keeps none, so no public call returns an asset's curve | `evaluate_hazard_portfolio` in [`workflows/_portfolio.py`][sdk-portfolio-join] |
| U4 | A curve is a quantile function over the non-exceedance probability. `return_period_tail` says which side is severe. `probability_semantics` is `annual_exceedance`, `annual_value_distribution`, `within_period_percentile`, `projection_uncertainty`, `estimate_confidence`, or absent (unspecified). The return-period check warns on `within_period_percentile` and `projection_uncertainty`; the docs also name `estimate_confidence` | [`types/dataset.py`][sdk-dataset], [`docs/design-decisions.md`][sdk-dd], `check_return_period_semantics` in [`workflows/distributions.py`][sdk-distributions] |
| U5 | Per-year values exist as `annual_extremes()` on several plans, each with its own columns: ERA5 and CMIP6 canonicalization plans (`year`, `latitude`, `longitude`, `value` per grid cell, years without a valid value left out); station plans (`station`, `year`, …, `value`, `complete`, incomplete years with null values); NEX-GDDP-CMIP6 (Arrow batches); NOAA water levels (detrended annual maxima). All are execution points | [`workflows/_plans.py`][sdk-plans], [`workflows/stations.py`][sdk-stations], [`workflows/nex.py`][sdk-nex] |
| U6 | `ImpactExpression` is a persisted, hashable impact definition: `to_json`, `from_json`, `definition_hash` (SHA-256 of canonical JSON, written `sha256:<hex>`), equality by hash, pickling through JSON. `.impact(...)` also takes framework `ImpactFunction`s and vectorised callables, evaluated event-aligned | [`impacts/expression.py`][sdk-expression], [`docs/portfolio.md`][sdk-portfolio] |
| U7 | Base dependencies: crc-framework, pydantic, duckdb, pyarrow, psutil, fsspec, s3fs, gcsfs. Optional extras are imported lazily and raise an `ImportError` that names the extra. No extra installs an LP, QP or general optimiser: the locked environment has no scipy | [`pyproject.toml`][sdk-pyproject], `uv.lock`, [`docs/runtime.md`][sdk-runtime] |
| U8 | "Numerical algorithms belong in crc-framework"; crc-sdk handles data access, orchestration and contracts. CI runs lint and mypy on 3.12, tests on 3.11–3.14 (3.14 non-blocking), a minimum-crc-framework job and a Windows job | [`docs/development.md`][sdk-dev] |
| U9 | crc-framework's `Distribution` protocol has `ppf`, `quantiles` and `sample(size, rng=...)`; with a `Generator`, `sample` is `quantiles(rng.random(size))`. Its only Python dependency is numpy. Its curve fitting uses its own Nelder–Mead in Rust; it ships no LP or QP solver | [`distributions/base.py`][fw-base], [`distributions/fitted.py`][fw-fitted], [`curve_fitting.rs`][fw-fitting], [`crates/core/Cargo.toml`][fw-cargo], [`pyproject.toml`][fw-pyproject] |
| U10 | crc-framework's `compute_risk` gives VaR and CVaR over the 2ⁿ branches of independent binary outcomes | [`docs/python.md`][fw-python] |
| U11 | None of the three repositories has payouts or basis risk: a search for `payout`, `basis risk`, `basis_risk`, `parametric insurance` and `trigger` at the commits above found no relevant code. The collaboration scan (`showcase/crc/COLLABORATION-SCAN.md` §2.5 and §3, 2026-11-01) also found no events, simulated years or dependence between sites | the three clones |

### What our core gives, and what it taught

The core, `parametric_insurance_design`, is the reference: `payout.StepPayout`, `objectives` (MSE, `ExpectedUncovered`, `WeightedCVaR` in the Rockafellar–Uryasev form), `pricing` (`PurePremium`, `CostOfCapitalLoad`), `constraints.Budget`, `basis` (the annual basis), `evaluate.kpis`, `riskmeasures`, `splits`, `scopes`, and the runner's degenerate-tail flags. `docs/concepts/` explains the method. Lessons that shape this design:

- **Below the attachment.** The core's default `below_attachment="first_bin"` pays the first level in years without hazard (design review F1). New designs pay nothing there (owner, 2026-11-01), so the module has no such mode.
- **VaR on a step.** With equally likely years, a standard β often falls exactly on a step of the distribution, and the core's strict comparison then picks either neighbouring atom, depending on the platform (review F2).
- **Degenerate tails.** When β ≤ P(L = 0), the weighted-CVaR objective is a multiple of E[U]; when (1 − β)·n ≤ 1, it is a minimax over outcomes (review F4, F15; `experiment/runner.py`).
- **Optima are often not unique.** Joint designs are not identified per asset (review F8). Individual designs are not unique either: bins that no calibration year reaches, and degenerate LP faces, leave the out-of-sample metrics open (MAR-198, MAR-203). A solver then returns one member of the optimal set, and which one depends on the solver.
- **Overloaded words.** "portfolio", "loading" and "weighted CVaR" each carry several meanings in the core (review F12).

## Decision

The eleven points of MAR-244, in order.

### 1. Concepts and names

| Concept | Name in `crc_sdk.parametric` | What it is | crc-sdk / crc-framework term | Core counterpart |
|---|---|---|---|---|
| Cover | `Cover` | The contract terms: an index definition, a payout function with its parameters, the payout unit, and the asset it is written for. Hashable, JSON round trip | Persisted like `ImpactExpression` (U6) | `StepPayout` plus one entity's `theta` in a `SolveResult` |
| Index | `IndexDefinition` | What the cover pays on: hazard name, unit, severe tail, location, aggregation | `hazard_name`, `value_unit`, `return_period_tail` of a canonical dataset | `index.PointIndex` |
| Payout function | `PayoutFunction` (protocol); `LinearPayout`, `StepPayout`, `PiecewiseLinearPayout`, `BinaryPayout` | Maps index values to a payout per year | None (new) | `PayoutStructure`, `StepPayout` |
| Parameter | a float (fixed) or `Free(lower, upper, grid=...)` | One named payout parameter | None | breakpoints (fixed), `theta` (free) |
| Outcome sample | `OutcomeSample` | Years (or simulated years) with a probability each, and an index value and a loss per year for the asset | Built from curves (U9), `annual_extremes()` tables (U5) or a user table | `EventSet` + `Sample` + the annual `OutcomeMeasure`, one row per year |
| Loss model | `LossModel` | loss = impact(hazard at the asset) × asset value | The impact function types of `.impact(...)` (U6) | The CLIMADA impact (adapter) |
| Basis-risk model | `BasisRisk` (protocol); `NoBasisRisk`, `ImpactNoise`; a second annual series as the index | How the index and the loss differ | None (U11) | `noise.add_noise`; vulnerability draws; cat-in-a-circle |
| Objective | `MSE`, `ExpectedUncovered`, `WeightedCVaR`, `UserObjective` | What the design minimises | None | `objectives.*` |
| Constraint | `Budget`, `Limit`, plus the payout family's own constraints | What a design must satisfy | None | `constraints.Budget`, the cap |
| Pricing | `PurePremium`, `CostOfCapitalLoad` | The premium of a payout | None | `pricing.*` |
| Design result | `DesignResult` | The designed cover and its record | None | `SolveResult` |
| Metric | the column names of §6 | One number about a cover on a sample | crc-framework's `var`/`cvar` are a different quantity (§6) | `records.KpiName` |
| Comparison | `compare(...)`, a `pyarrow.Table` | Covers as rows, metrics as columns | Wide value columns and a metadata key, like `PortfolioEvaluation` output (U2) | the `kpis` table |
| Plan | `ParametricPlan` | The lazy workflow from assets, hazard and impact to a written comparison | `*Plan`, `PortfolioEvaluation` (U1, U2) | `workflow.design` |

Naming rules:

- **"Portfolio" keeps crc-sdk's meaning**, a set of assets (`AssetPortfolio`, `PortfolioEvaluation`). Phase 2's joint scope is called `Joint`, not `Portfolio` (review F12).
- **"Impact"** is crc-sdk's impact value, usually a damage ratio. **"Loss"** is impact × value, in the payout's unit. **"Hazard"** is the value the loss model reads at the asset. **"Index"** is the value the cover pays on. Without a basis-risk model, index and hazard are the same value.
- **"Budget"** is the premium budget, `Budget(ratio=κ)` or `Budget(amount=B)`. "Load" is only the cost-of-capital load. The core's `Budget.loading` is `ratio` here.
- **"CVaR" never stands alone** in a metric name: `cvar_uncovered`, `cvar_net_loss`, `cvar_loss` (§6).

### 2. API shape and entry point

**Decision: two layers.**

- **Layer 1: functions and frozen value objects over numpy and Arrow.** They do no I/O. All numerical work is here, so tests and the notebook can use it without a plan, and a user can bring their own table.
- **Layer 2: a plan, `ParametricPlan` (R-18).** Immutable builders, `explain()` without I/O, and execution points that read through crc-sdk's existing plans and write Parquet atomically (temporary file, then `os.replace`) under the metadata key `crc.parametric.evaluation`.

**Entry point.** `ParametricPlan.for_evaluation(request)` takes the `PortfolioEvaluation` the user already built with `HazardDataset.<source>(...).for_assets(assets).select(...).impact(...)`, and reuses its dataset, assets, selection and impact function. It changes nothing in `PortfolioEvaluation`. `ParametricPlan.for_annual_extremes(...)` is the second entry, for per-year sources (U5). (Amendment 1, D11: the first release leads with `for_evaluation` and the curves; the per-year entry is the second step.)

To sample from curves the plan needs each asset's curve, and the join that finds it is private (U3). **Recommendation:** R-18 adds one public execution point to crc-sdk, `PortfolioEvaluation.asset_curves() -> pyarrow.Table`, with one row per asset, hazard, horizon and pathway, the curve columns and `spatial_match`, built on the existing join. It is additive. RiskThinking confirms the name and the place (Q1). A chaining method on `PortfolioEvaluation` (for example `.parametric(...)`) is the alternative; it edits their class, so it is their choice (Q2). (Amendment 1, D11: `asset_curves()` is built in the fork now, by MAR-271, and proposed to RiskThinking in the upstream PR. Q2 stays open.)

Amendment 2 (the per-year route) adds to both outlines below: `trend=`, `scenario=`, `pool=`, `cell=`, `.index(...)` and `sample_annual_pool`.

Amendment 4 (scenario analysis) adds `ScenarioSet`, `compare_scenarios`, `to_drift`, `.scenarios(...)` and `scenario=` on `sample_curve`.

**Layer 1 in outline** (names and signatures for R-14 to R-17; types abbreviated):

```text
# covers (R-14)
IndexDefinition(hazard_name, unit, *, tail="upper", location=AtAsset(), aggregation, source=None)
AtAsset() | AtPoint(longitude, latitude, name=None) | AtStation(station_id) | AtCell(cell_index)
Free(lower=0.0, upper=None, *, grid=None)
LinearPayout(attachment, exhaustion, limit, *, tail="upper")
StepPayout(breakpoints, levels, *, tail="upper", monotone=True)
PiecewiseLinearPayout(knots, levels, *, tail="upper", monotone=True)
BinaryPayout(trigger, amount, *, tail="upper")
Cover(index, payout, *, payout_unit, asset_id=None, label=None)
Cover.payout_values(index_values) -> NDArray          # resolved covers only
Cover.with_values(values: Mapping[str, float]) -> Cover
Cover.free_parameters() -> tuple[str, ...]
Cover.to_json() -> str; Cover.from_json(text, *, label=None) -> Cover; Cover.definition_hash -> str
register_payout(cls) -> cls

# outcome samples (R-15)
OutcomeSample(...)                                     # §4.1
sample_curve(curve, *, metadata, n_draws, rng, loss_model, basis_risk, asset_id,
             assume_semantics=None, outside_support="raise", details=None) -> OutcomeSample
    # curve: a crc-framework distribution, CurveParameters or a canonical row mapping
    # metadata: the curve's HazardDatasetMetadata (semantics, tail, support, units, source)
    # details: caller information for the provenance, for example the file's SHA-256
AnnualSeries.from_table(table, *, year="year", value="value", where=None, unit,
                        years=None, source=None) -> AnnualSeries
AnnualSeries.nearest_cell(table, *, longitude, latitude, unit, ...) -> AnnualSeries
sample_annual(hazard, *, loss_model, basis_risk, asset_id, index=None, rng=None, missing="raise") -> OutcomeSample
OutcomeSample.from_table(table, *, period, asset_id, index, loss, probability=None, hazard=None,
                         semantics, index_unit, loss_unit, source=None) -> OutcomeSample
holdout(sample, train_fraction=0.7) -> tuple[OutcomeSample, OutcomeSample]
year_block_kfold(sample, k) -> tuple[tuple[OutcomeSample, OutcomeSample], ...]

# evaluation and comparison (R-17)
evaluate(cover, sample, *, split, fold=0, pricing=PurePremium(), premium=None, options=MetricOptions(),
         design_sample=None) -> pyarrow.Table   # one row
compare(covers, sample, *, split, fold=0, pricing=PurePremium(), options=MetricOptions(),
        design_sample=None) -> pyarrow.Table
    # design_sample: the sample a cover given as is was chosen on; a design brings its own
write_comparison(table, path, *, metadata=None) -> None    # atomic; metadata defaults to the table's own

# design (R-16)
design(template, sample, objective, *, pricing=PurePremium(), budget=None, limit=None, options=DesignOptions()) -> DesignResult
```

(Erratum 10, 2026-11-06, MAR-286: seven entries of this outline first differed from the code that MAR-246 (R-14), MAR-43 (R-15) and MAR-247 (R-17) merged in marc272/crc-sdk#1, #2 and #3, and now read as it does. The `Cover.from_json` entry first read `Cover.from_json(text) -> Cover`: it takes the optional keyword `label=None`, the display name, which the JSON does not hold. The `sample_curve` entry first read `sample_curve(distribution, *, metadata, n_draws, rng, loss_model, basis_risk, asset_id, assume_semantics=None, outside_support="raise") -> OutcomeSample`: the first argument is `curve`, which is a crc-framework distribution, `CurveParameters` or a canonical row mapping, and the optional keyword `details=None` adds caller information to the provenance. The `AnnualSeries.from_table` entry first read `AnnualSeries.from_table(table, *, year="year", value="value", where=None, unit) -> AnnualSeries`, with no `...`: it also takes `years=None` and `source=None`. The `OutcomeSample.from_table` entry first read `OutcomeSample.from_table(table, *, period, asset_id, index, loss, probability=None, semantics, index_unit, loss_unit) -> OutcomeSample`: it also takes `hazard=None`, after `probability`, and `source=None`. The `evaluate` and `compare` entries first ended in `options=MetricOptions()) -> pyarrow.Table`: both also take `design_sample=None`. The `write_comparison` entry first read `write_comparison(table, path, *, metadata) -> None`: `metadata` is optional, `None` by default, and then the table's own metadata is written. The other entries already matched. Each signature is as the PR that added its module merged it (#1, #2 and #3, and #5 for `design`), and no later PR changed it, up to marc272/crc-sdk#14 (d54ec9b), by a comparison of the signatures, read with Python's `ast`, at every merge into `parametric`. The paragraph on seeding below the Layer 2 outline first read: "The plan holds an integer `seed`, which `explain()` can show. At execution it builds `numpy.random.SeedSequence(seed)` and spawns one child generator per asset, in asset order. Layer 1 takes a `numpy.random.Generator` instead, with no default and no global seed." It fitted the curve route only: on the per-year route `for_annual_extremes(..., seed=None)` allows no seed, as MAR-42 (R-18) merged it in marc272/crc-sdk#8, and only a basis-risk model that draws needs one; and `sample_annual` takes `rng=None`, as MAR-43 merged it in marc272/crc-sdk#2. No decision changes.)

**Layer 2 in outline (R-18):**

```text
ParametricPlan.for_evaluation(request, *, value_column=None, value_unit="1")
ParametricPlan.for_annual_extremes(source, assets, *, impact, unit, provenance,
                                   value_column=None, value_unit="1", context=None,
                                   location=NearestCell(), year_column="year",
                                   hazard_column="value", years=None, missing="raise", seed=None)
    # source: a plan with an annual_extremes() execution point, an Arrow table or a local Parquet file
    .monte_carlo(n_draws, *, seed, assume_semantics=None, outside_support="raise")   # curve sources only
    .basis_risk(model)
    .covers(*covers)                     # resolved covers and templates; Free parameters allowed
    .objective(*objectives, pricing=None, budget=None, limit=None, options=DesignOptions())   # optional: design the templates
    .pricing(pricing)                    # optional: PurePremium() | CostOfCapitalLoad(rate, q); one pricing per plan
    .split(rule)                         # Holdout(train_fraction=0.7) | KFold(k) | FreshDraws(n_draws, *, seed)
    .metrics(options)                    # MetricOptions(...)
    .explain(*, format="text") -> str | dict     # no I/O
    .samples() -> Mapping[str, OutcomeSample]    # execution, one per asset
    .designs() -> tuple[DesignResult, ...]       # execution
    .write_parquet(path) -> ParametricResult     # execution; atomic
```

(Erratum 8, 2026-11-06, MAR-276: the `.monte_carlo` line first read `.monte_carlo(n_draws, *, seed, assume_semantics=None)`. MAR-271 (R-18b) added `outside_support` in marc272/crc-sdk#9, with `sample_curve`'s values and default (§4.2): `"raise"`, `"extrapolate"` or `"clamp"`; `explain()` shows the choice. The `plan.py` row of the module layout below first named only `ParametricPlan` and `ParametricResult`. `plan.py` defines five more public names, and `crc_sdk.parametric` exports them: the split rules `Holdout` and `KFold` and the locators `NearestCell` and `StationColumn`, which MAR-42 (R-18) added in marc272/crc-sdk#8, and the split rule `FreshDraws(n_draws, *, seed)`, which MAR-271 added in marc272/crc-sdk#9. No decision changes.)

(Erratum 9, 2026-11-06, MAR-285: six lines of this outline first differed from the plan that MAR-42 (R-18) merged in marc272/crc-sdk#8, and now read as its code does. The `for_annual_extremes` line first read `ParametricPlan.for_annual_extremes(source_plan, assets, *, impact, value_column=None, value_unit="1", ...)`: the first argument is `source`, which is a plan with an `annual_extremes()` execution point, an Arrow table or a local Parquet file, and the `...` hid the required keywords `unit` and `provenance` as well as the optional ones. The `.covers` line first read `.covers(*templates)`, with the comment "Cover templates; Free parameters allowed": it takes `*covers`, both resolved covers and templates. The `.objective` line first read `.objective(objective, *, pricing=..., budget=..., limit=..., options=...)`: it takes `*objectives` and designs each template under each, and its defaults are those of `design`. The `.split` and `.metrics` lines first read `.split(Holdout(0.7) | KFold(5) | FreshDraws(n_draws, seed=...))` and `.metrics(MetricOptions(...))`, which named no parameter: they take `rule` and `options`, and the comments now give the types. The `.explain` line first read `.explain(format="text") -> str | dict`: `format` is keyword-only, and `format="json"` returns the dict. The other lines already matched. Of the later PRs, only marc272/crc-sdk#9 (MAR-271) changed `plan.py`: it added `for_evaluation`, `.monte_carlo` (erratum 8) and `FreshDraws` as they read here; marc272/crc-sdk#10 to #13 did not touch it. No decision changes.)

(Erratum 11, 2026-11-08, MAR-288: six passages of this ADR first differed from the merged code, and now read as it does. MAR-278 (R-18d) changed four of them in marc272/crc-sdk#16. The `.objective` line of this outline first read `.objective(*objectives, pricing=PurePremium(), budget=None, limit=None, options=DesignOptions())`: `pricing` now defaults to `None`, so erratum 9's "its defaults are those of `design`" no longer holds for it. The `.pricing(pricing)` line is new. One pricing prices every premium of a plan: the designs' on their design block and the resolved covers' on each evaluation block. `.pricing(...)` states it for a plan of resolved covers, which needs no `.objective(...)`, and `.objective(..., pricing=...)` states it too. Both may be given if they agree, two different pricings raise `ValueError`, and without either the premiums are pure (`PurePremium()`). §7 gains `source_records` and the hazard sources' checksums `canonical_file_sha256` and `annual_table_sha256`, and §4.2 says that `NearestCell` also locates assets by their H3 cells (`CellColumn`). The other two passages were incomplete from the start: MAR-43 (R-15) merged `LossModel(..., name=None)` (§4.3) and `sample_curve`'s `CurveParameters` and canonical row mapping (§4.2's source table) in marc272/crc-sdk#2. Each of the four passages outside this outline says what it first read, or that it is new. No decision changes.)

The plan holds a `seed`, which `explain()` shows (erratum 10 gives this paragraph's first text). On the curve route it is an integer, which `.monte_carlo(n_draws, *, seed, ...)` requires. On the per-year route `for_annual_extremes(..., seed=None)` allows none: only the basis-risk model draws there, so only a model that draws needs a seed, and `.basis_risk(ImpactNoise(...))` raises `ValueError` on a per-year plan without one. A plan with a seed builds `numpy.random.SeedSequence(seed)` at execution and spawns one child generator per asset, in asset order; `FreshDraws` seeds its draws from its own seed in the same way. Layer 1 takes a `numpy.random.Generator` instead, and never a global seed: `sample_curve` requires `rng`, and `sample_annual` takes `rng=None`, which only a basis-risk model that draws needs (§4.4).

**Module layout** under `crc_sdk/parametric/`. One owner issue per file; `__init__.py` is extended by each issue in sequence.

| File | Content | Issue |
|---|---|---|
| `__init__.py` | The public names and `__all__` (§9 says what is reserved) | R-14, then R-15, R-17, R-16, R-18 |
| `errors.py` | `ParametricError` and its subclasses, the warnings | R-14 |
| `_canonical.py` | Canonical JSON and `sha256:` hashes | R-14 |
| `index.py` | `IndexDefinition`, `AtAsset`, `AtPoint`, `AtStation`, `AtCell` | R-14 |
| `parameters.py` | `Free` | R-14 |
| `payouts.py` | `PayoutFunction`, `LinearInAmounts`, `LinearConstraints`, the four families, `register_payout` | R-14 |
| `cover.py` | `Cover` | R-14 |
| `sample.py` | `OutcomeSample`, `SampleProvenance`, `holdout`, `year_block_kfold` | R-15 |
| `sources.py` | `sample_curve`, `AnnualSeries`, `sample_annual` | R-15 |
| `loss.py` | `LossModel` | R-15 |
| `basis_risk.py` | `BasisRisk`, `NoBasisRisk`, `ImpactNoise` | R-15 |
| `_risk.py` | VaR, CVaR, tail weights, lower quantiles (numpy) | R-17 |
| `pricing.py` | `PurePremium`, `CostOfCapitalLoad` (premium values in numpy) | R-17 |
| `metrics.py` | `MetricOptions`, the metric kernels and column names | R-17 |
| `evaluate.py` | `evaluate`, `compare`, `write_comparison`, `to_long` | R-17 |
| `metadata.py` | `EvaluationMetadata` and `setup_text` (§7; erratum 7, 2026-11-06, MAR-272: this row first named only `EvaluationMetadata`) | R-17 |
| `objectives.py` | `MSE`, `ExpectedUncovered`, `WeightedCVaR`, `UserObjective` | R-16 |
| `constraints.py` | `Budget`, `Limit` | R-16 |
| `design.py` | `design`, `DesignOptions`, `DesignResult`; the LP and QP assembly | R-16 |
| `_solver.py` | The private solver interface and the HiGHS backend (§5.5) | R-16 |
| `plan.py` | `ParametricPlan`, `ParametricResult`; the split rules `Holdout`, `KFold` and `FreshDraws`; the locators `NearestCell` and `StationColumn` (erratum 8, 2026-11-06, MAR-276: this row first named only `ParametricPlan` and `ParametricResult`) | R-18 |

Outside the package: `docs/parametric.md` with its line in `docs/README.md` (stub R-14, finished R-18); tests `tests/test_parametric_<module>.py`, mirroring the modules as crc-sdk does; the extra in `pyproject.toml` (R-16); `PortfolioEvaluation.asset_curves()` in `workflows/portfolio.py` and `workflows/_portfolio.py` (R-18, if RiskThinking agrees, Q1).

**Errors** (`errors.py`): `ParametricError` is the base. `CoverDefinitionError` and `UnknownPayoutKindError` (also `ValueError`) cover invalid covers, payouts and parameters. `UnresolvedParameterError` is raised when a template is evaluated. `SampleError`, with `ProbabilitySemanticsError` and `LeakageError`, covers samples and splits (also `ValueError`). `DesignError`, with `InfeasibleDesignError` and `UnboundedDesignError` (also `RuntimeError`), carries the asset id, the solver status and its message. `SolverUnavailableError` (also `ImportError`) names the extra. `EvaluationError` (also `ValueError`) covers invalid evaluation arguments, metric options and comparison metadata, in `evaluate`, `compare`, `write_comparison`, `to_long`, `MetricOptions`, `EvaluationMetadata` and `setup_text`. Warnings: `ComonotoneIndexWarning`, and crc-sdk's own `ReturnPeriodExtrapolationWarning` for draws outside a curve's fitted support. (Erratum 7, 2026-11-06, MAR-272: this list first left out `EvaluationError`. MAR-266 (R-17b) added it in marc272/crc-sdk#7, together with `setup_text`, and `crc_sdk.parametric` exports both. No decision changes.)

### 3. Payout families and the extension protocol

**Severity.** `tail="upper"`: larger index values are more severe (rainfall, wind). `tail="lower"`: smaller values are more severe (a drought index). Every family pays more as the index moves to the severe side. Thresholds are given in index units, in order of increasing severity: increasing for `"upper"`, decreasing for `"lower"`. Internally a family works on the severity s = x (upper) or s = −x (lower), with its thresholds mapped the same way. `Cover` checks that the payout's `tail` equals the index's.

**Families.** π ≥ 0 is the payout of a year with severity s.

| Family | Index-unit parameters | Payout-unit parameters | Payout | Linear in |
|---|---|---|---|---|
| `LinearPayout` | attachment a, exhaustion e (a < e in severity) | limit ℓ | `ℓ · clip((s − a) / (e − a), 0, 1)` | ℓ |
| `StepPayout` | breakpoints b_0 < … < b_{n−1} | levels θ_0 … θ_{n−1} | θ_k for b_k ≤ s < b_{k+1}; θ_{n−1} for s ≥ b_{n−1}; 0 for s < b_0 | θ |
| `PiecewiseLinearPayout` | knots c_0 < … < c_{m−1}, m ≥ 2 | levels y_0 … y_{m−1} | 0 for s < c_0; linear interpolation of the points (c_k, y_k) on [c_0, c_{m−1}]; y_{m−1} for s ≥ c_{m−1} | y |
| `BinaryPayout` | trigger t | amount A | A for s ≥ t, else 0 | A |

- **Registry keys** (erratum 2, 2026-11-06, MAR-262): the four families register as `"linear"`, `"step"`, `"piecewise_linear"` and `"binary"`, as in the merged `crc_sdk.parametric` code (marc272/crc-sdk#1) and the fixtures. The table does not name the two new keys; no decision changes.
- **Nothing below the attachment.** Every family pays 0 below its first threshold (a, b_0, c_0 or t). There is no first-bin mode.
- **Boundaries.** A severity equal to a threshold belongs to the more severe side (half-open bins, as in the core). Non-finite index values raise `SampleError`.
- **Constraints of the family.** Amounts are ≥ 0. `monotone=True`, the default, adds θ_k ≤ θ_{k+1} and y_k ≤ y_{k+1}; `monotone=False` is allowed and recorded. `StepPayout` with the core's breakpoints `b_0 … b_n` is `StepPayout(breakpoints=b[:-1], levels=theta)` here: in the core, values at or above `b_n` fall into the last bin too, so `b_n` changes no payout.

**Parameters.** Each parameter is a float (fixed) or `Free(lower, upper, grid=...)`.

- Names are flat strings: `attachment`, `exhaustion`, `limit`, `breakpoints[0]`, `levels[2]`, `knots[1]`, `trigger`, `amount`.
- Amount parameters (payout units): `lower` ≥ 0, default 0; `upper` may be `None`, and then `Limit` or the budget bounds it.
- Shape parameters (index units): finite bounds and a grid, an integer (that many uniform points) or explicit values. Phase 1 designs free shape parameters on that grid (§5.3).
- A `Cover` with any `Free` parameter is a template. `payout_values` raises `UnresolvedParameterError` on a template. `design` returns a resolved cover; `Cover.with_values` resolves one by hand.
- Validation at construction raises `CoverDefinitionError`: lengths, orders, finiteness, bounds, and `lower ≤ upper`.

**The protocol** (outline):

```text
class PayoutFunction(Protocol):
    kind: ClassVar[str]                          # registry key: "linear", "step", ...
    tail: Literal["upper", "lower"]
    index_names: tuple[str, ...]                 # ("index",) in Phase 1
    def parameters(self) -> Mapping[str, float | Free]          # ordered, flat names
    def with_values(self, values: Mapping[str, float]) -> Self
    def evaluate(self, index: NDArray[float64]) -> NDArray[float64]   # resolved only; same shape; >= 0
    def to_document(self) -> dict[str, Any]
    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> Self

class LinearInAmounts(PayoutFunction, Protocol):     # opt-in: enables the LP and QP routes
    def amount_names(self) -> tuple[str, ...]
    def basis(self, index: NDArray[float64]) -> NDArray[float64]   # (n, n_amounts); shape parameters fixed
    def amount_constraints(self, limit: float | None) -> LinearConstraints   # monotone, bounds, limit

LinearConstraints(a_ub, b_ub, lower, upper)          # over the amount vector; dense and small
```

- The four built-in families implement both protocols. Their `basis` rows are non-negative and sum to at most 1, so `Limit(ℓ)` is "every amount ≤ ℓ".
- Built-in families and `IndexDefinition` are frozen pydantic models, following crc-sdk's `StrictFrozenModel` pattern (unknown fields rejected). A user family can be any class that meets the protocol.
- **User-defined payouts** implement `PayoutFunction`, and `LinearInAmounts` too if they want the LP and QP routes. `register_payout` adds the class to the registry under its `kind`. `Cover.from_json` resolves `kind` through the registry and raises `UnknownPayoutKindError` for an unknown kind. A bare callable is not a payout: every cover has a document and a hash.

**Multi-dimensional index (Phase 2).** A payout with several `index_names` takes `evaluate(index)` of shape (n, k), with columns in `index_names` order. The sample supplies the components (§4.5). `basis` keeps the shape (n, n_amounts), so the LP and QP routes need no change. Phase 2 adds combinators (`MaxOf`, `SumOf`) and a two-dimensional step grid as new families. In Phase 1, `Cover` requires `index_names == ("index",)`.

**The cover document and its hash.**

```text
{"asset_id": "warehouse-a",
 "index": {"aggregation": "annual_maximum", "hazard_name": "rx1day", "location": {"kind": "asset"},
           "source": null, "tail": "upper", "unit": "mm/day"},
 "payout": {"breakpoints": [60.0, 80.0, 100.0], "kind": "step",
            "levels": [{"free": {"grid": null, "lower": 0.0, "upper": null}}, ...],
            "monotone": true, "tail": "upper"},
 "payout_unit": "EUR",
 "schema_version": "1.0",
 "semantics_version": "crc-parametric-cover/1"}
```

- Canonical JSON follows crc-framework's impact contracts (`canonical_json` and `content_hash` in its [`crates/core/src/impact/json.rs`][fw-json]): keys sorted by their UTF-8 bytes, no whitespace, strings as unescaped UTF-8, zero (and −0.0) written `0.0`, every other number as its shortest round-trip digits, in positional notation with at least one digit after the point for a decimal exponent from −5 to 15 (`0.00001`, `1000000000000000.0`), and in exponent notation, signed and unpadded, outside that range (`1e-6`, `1e+16`, `1.5e-7`; Python's `json` writes `1e-06`). This is the profile `crc-canonical-json/1` (erratum 1, 2026-11-06, MAR-262: this bullet first said "Rust `serde_json`'s shortest round-trip spelling (`1e-7`, where Python's `json` writes `1e-07`)", which is not what crc-framework writes; crc-framework's contract fixture `canonical-json.json`, its `impact_definition` fixtures and a live `ImpactExpression` hash agree, and `crc_sdk/parametric/_canonical.py`, merged in marc272/crc-sdk#1, follows them. The decision, to hash covers in crc-framework's canonical profile, is unchanged). NaN and infinity are rejected. Every number in the document is a float, so a grid given as a count is stored as its explicit values. R-14 tests the spelling of small and large exponents against crc-framework's own hashes, so a cover hashes the same in Python and Rust (Q9).
- `definition_hash = "sha256:" + SHA-256(canonical bytes)`, the format of `ImpactExpression` (U6). `label` is not in the document, so two covers with the same terms have the same hash. `asset_id` is in it: the same terms on another asset are another contract.
- `Cover` compares and hashes by `definition_hash` and pickles through its JSON, as `ImpactExpression` does.

### 4. Outcome samples

#### 4.1 The object

```text
@dataclass(frozen=True)
class OutcomeSample:
    asset_ids: tuple[str, ...]           # Phase 1: exactly one
    period: NDArray[int64]               # (n,) year label, or draw number; strictly increasing
    probability: NDArray[float64]        # (n,) > 0, sums to 1 within 1e-12
    index: NDArray[float64]              # (n, n_assets), finite
    loss: NDArray[float64]               # (n, n_assets), finite, >= 0
    hazard: NDArray[float64] | None      # (n, n_assets) when it differs from the index
    index_unit: str
    loss_unit: str
    semantics: Literal["annual"]         # one draw is one year
    provenance: SampleProvenance         # §7
    scenario: str = "baseline"
    def select(self, periods) -> OutcomeSample
    def to_table(self) -> pyarrow.Table  # long: scenario, period, asset_id, probability, index, loss, hazard
    @property
    def content_hash(self) -> str
```

Amendment 3 (the portfolio approach) lifts the one-asset rule of this section: a sample holds one asset or more, and `OutcomeSample.asset()` and `OutcomeSample.join()` are added.

- **One draw is one year.** A cover pays once per draw, on that draw's index, against that draw's loss. This is the core's annual basis with one row per year. Several events within a year are out of scope for Phase 1 (§9).
- **One asset per sample in Phase 1** (MAR-43). The asset axis exists, so arrays are (n, 1); a second asset raises `SampleError` until Phase 2. The plan handles several assets as one sample each. So Phase 1 imposes no dependence between assets: it computes no cross-asset sum.
- Arrays are read-only (`setflags(write=False)`). A sample written to Parquet uses the long table above and the metadata key `crc.parametric.sample`.

Amendment 2 (the per-year route) adds pooled samples, whose `period` is a draw number and whose rows record their (year, model, member), and two fields of `SampleProvenance`: `trend` and `pool`.

#### 4.2 Sources and the probability semantics each needs

Amendment 1 (D11) sets the order of release: Monte Carlo from a fitted curve first, per-year values as the second step. The rules below don't change.

Amendment 2 (the per-year route) adds a stated trend option, pooled model-years and a `scenario` label to the per-year source, and says what of the route goes in the Phase 1 upstream PR.

Amendment 4 (scenario analysis) adds `scenario=` to `sample_curve`.

| Source | Function | One draw is | Probability | Semantics required |
|---|---|---|---|---|
| Monte Carlo from a fitted curve | `sample_curve` (a crc-framework distribution, `CurveParameters` or a canonical row mapping; erratum 11, 2026-11-08, MAR-288: this first read "a crc-framework `Distribution`"); the plan's `.monte_carlo(...)` | a simulated year | 1/n | `annual_exceedance` (the curve of an annual maximum) or `annual_value_distribution` (an annual value). Any other declared value raises `ProbabilitySemanticsError`. Unspecified raises too, unless the caller passes `assume_semantics=` one of the two; a stated value that contradicts the declared one raises |
| Per-year values | `sample_annual` on `AnnualSeries`; the plan's `.for_annual_extremes(...)` | an observed (ERA5, stations) or modelled (CMIP6, NEX) year | 1/n | None to assume: the years are the data. The series records its source and window. A trend is not removed |
| A user table | `OutcomeSample.from_table` | what the caller states | the `probability` column, or 1/n | `semantics="annual"` is a required argument |

**Monte Carlo from a curve.**

- Draw u from `rng.random(n_draws)`, then index = `distribution.quantiles(u)`. This is the inverse-CDF route of crc-framework's own `sample(size, rng=...)` (U9). A hurdle curve keeps its atom: a dry-year draw gets the atom's value.
- `no_data` rows raise; they never become zero. A non-finite quantile raises.
- **Support.** A curve is fitted on a range of return periods (`return_period_support`, `source_probability_support`); a draw outside it is extrapolation. The draws outside are counted on each side and recorded:
  - above the range (rarer than the longest fitted return period): `ReturnPeriodExtrapolationWarning`;
  - below it (more frequent than the shortest one; with a 2-year lower end, about half of all years): recorded and named in the setup text. They matter when the attachment or the impact's threshold lies there.
- A fitted family can be evaluated everywhere. A tabulated curve raises outside its declared range (crc-framework's default), so by default its sample raises. The caller may pass `outside_support="extrapolate"` (crc-framework's own extrapolation) or `"clamp"` (the nearest knot); the choice is recorded. Nothing is clamped silently.
- `ensemble.pooling = "pooled"`: a draw mixes model spread with year-to-year variability (crc-sdk's design decisions). It is allowed, recorded, and named in the setup text (Q6).
- The semantics come from the dataset's metadata (`semantics_source = "dataset"`) or from the caller (`"caller"`). Both are recorded.

**Per-year values.**

- `AnnualSeries(years, values, unit, provenance)` is one hazard at one location. `AnnualSeries.from_table` reads any of the tables of U5 with stated column names and a row filter (for example a station id). `AnnualSeries.nearest_cell` picks the grid cell whose centre is nearest to the asset, and accepts it only within half the grid spacing in latitude and longitude; otherwise it raises. The cell centre and the grid step are recorded, not the asset's point (erratum 12 below this list gives this sentence's first text). On the plan, `NearestCell` does this for an asset located by a point (`PointColumns`). For an asset located by an H3 cell (`CellColumn`), it takes the grid cell nearest the H3 cell's centre and accepts it only if the whole H3 cell lies inside that grid cell, every vertex within half a grid step of its centre; otherwise it raises `SampleError`, and the asset needs a point. This case needs the `geometry` extra, and the series records `"asset_location": "h3_cell"` (erratum 11, 2026-11-08, MAR-288: these sentences on the plan's `NearestCell` are new; this bullet first named only `AnnualSeries.nearest_cell`). RiskThinking may prefer to give `annual_extremes()` an asset join of its own (Q3).
- A missing or null year raises, unless `missing="drop_year"`; then the year is dropped and listed in the provenance.
- The `index=` argument takes a second series: another cell, a station or another hazard than the loss reads. The years of both series must match. This is the per-year basis-risk model of MAR-43: the dependence between index and loss is the data's own, not an assumption.

(Erratum 12, 2026-11-08, MAR-288: a nearest-cell series no longer records `distance_km`, the distance from the asset's point to the cell centre. It records the cell centre and the grid step (`cell` and `spacing_degrees`). The first bullet above first read "The cell centre and the distance are recorded." Three sentences of Amendment 2, which the owner approved with that text, said the same and now read as the code does: one in "Pooled model-years" and two in "The per-year source records", each with its first text. Unlike errata 1 to 11, this one records a choice. On MAR-308 the owner, Marc Prinzing, delegated the choice to the orchestrator (in chat, 2026-11-08). It chose to drop the field, and marc272/crc-sdk#20 (`48cb39c`) removed it. With the centre, the distance narrowed the asset's point to a ring around that centre, and two distances on different grids, as Amendment 2's `.index(... NearestCell(...))` would have recorded, to at most two candidate points. The grid step already bounds the distance, and nothing in the module read the field. Lineages don't change: the field was already out of them. The field stays on `feat/parametric-insurance`, the fork's branch for the upstream PR, until the owner decides on MAR-249 whether the removal goes there. No other decision changes.)

**A user table.** Required columns: period, asset id, index, loss. Optional: probability, hazard. Every (period, asset) pair appears exactly once; missing or duplicate pairs raise.

#### 4.3 Loss model

`LossModel(impact, *, value_column=None, value=None, value_unit="1", context=None, name=None)` (erratum 11, 2026-11-08, MAR-288: this line first ended `context=None)`):

- loss = `impact.evaluate(hazard)` × value. `impact` takes the types `.impact(...)` takes (U6): an `ImpactExpression`, a framework `ImpactFunction`, or a vectorised callable. Context columns for registry impacts work as in crc-sdk (`ImpactContextColumns`).
- The value comes from an asset column, in one stated currency, or is 1, which gives the loss in damage-ratio units (`value_unit="1"`).
- A negative or non-finite loss raises. `design` and `evaluate` check that the loss unit equals the cover's `payout_unit`.
- The plan takes the impact from the `PortfolioEvaluation`'s impact spec.
- `name` labels the impact in the provenance. By default it is the expression's model kind, the registry factor (the type's name for another `ImpactFunction`) or the callable's name.

#### 4.4 Basis-risk models and seeding

Amendment 2 (D-25.4) brings the `index=` series of this table into the plan, as `.index(...)`.

Amendment 4 extends the leakage check below to Monte Carlo samples that reuse one generator record, whatever the curve.

| Model | What it does | Sources |
|---|---|---|
| `NoBasisRisk()` | index = hazard at the asset, loss = impact(hazard) × value. It warns with `ComonotoneIndexWarning`: index and loss move together, so a cover can track the loss almost exactly | all |
| `ImpactNoise(sigma, *, upper=None)` | multiplies each year's impact by a mean-one lognormal factor exp(σZ − σ²/2), then caps it at `upper` if given (1 for a damage ratio). This is the core's thesis noise layer (homoscedastic), with one draw per year. The cap lowers the mean a little; that is recorded | all |
| a second `AnnualSeries` as `index=` | the index is another cell, station or hazard than the loss reads (§4.2) | per-year |
| user model | the `BasisRisk` protocol: `name`, `to_document()` and `apply(index, hazard, impact, rng) -> (index, impact)` | all |

- `basis_risk` is a required argument with no default: every sample states its model. `NoBasisRisk()` must be written out.
- An index at a reference point for Monte Carlo samples needs a joint distribution of two curves, which CRC doesn't provide (U11). It waits for Phase 2's dependence models (§9).
- Vulnerability draws from the uncertainty ranges of registry impacts become a model once RiskThinking says whether such ranges exist (Q7).
- **Seeding.** Layer-1 functions take `rng: numpy.random.Generator` as a required keyword wherever they draw. One generator per call. The draw order is fixed and documented: the hazard uniforms first, then the basis-risk model. The provenance records the bit generator's name and its `state` at entry, so a sample can be rebuilt exactly.

**Splits.** `holdout(sample, train_fraction=0.7)` and `year_block_kfold(sample, k)` split by contiguous blocks of `period`, as the core's `splits.py` does. For per-year samples the test block is the latest years. Monte Carlo draws are i.i.d., so a fresh sample with another seed (`fresh_draws`) is the plainer out-of-sample test; the plan offers both. Evaluating a design out of sample on a sample that shares a period with its design sample from the same source raises `LeakageError`.

#### 4.5 Dimensions reserved for Phase 2

Amendment 2 (D-25.5) lets a per-year sample state its `scenario` label.

Amendment 4 (scenario analysis) adds `scenario=` on curves and the `ScenarioSet` this section reserves.

- **Assets.** The asset axis exists (`asset_ids`, axis 1 of `index` and `loss`). Phase 2 lifts the one-asset rule and adds dependence models for Monte Carlo samples (§9).
- **Hazards.** Phase 2 adds a field `index_components: Mapping[str, NDArray] | None = None` (named (n, n_assets) arrays) and a `CompositeIndex` definition. `index` stays the primary component. A new field with a default doesn't break callers.
- **Scenarios.** Every sample has a `scenario` label (`"baseline"`), and the comparison table has a `scenario` column from Phase 1 on. Phase 2 adds a `ScenarioSet`.
- **Events within a year.** `semantics` reserves the value `"event"`; Phase 1 accepts only `"annual"`.

### 5. Design

Phase 1 designs one cover on one asset's sample: `design(template, sample, objective, ...)`.

#### 5.1 Objectives

On the design sample, with draw probabilities p_d, loss L_d, payout π_d and uncovered loss U_d = (L_d − π_d)^+:

- `MSE()`: `Σ p_d (L_d − π_d)²`.
- `ExpectedUncovered()`: `E[U] = Σ p_d U_d`.
- `WeightedCVaR(alpha, beta)`: `α · CVaR_β(U) + (1 − α) · E[U]`, with α ∈ [0, 1] the weight of the CVaR term and β ∈ (0, 1). In the Rockafellar–Uryasev form, `CVaR_β(U) = min_ζ ζ + Σ p_d (U_d − ζ)^+ / (1 − β)`.
- `UserObjective(function, *, name, parameters=None)`: `function(loss, payout, probability) -> float`. It is evaluated, not compiled, so it takes the grid route (§5.3). Its `name` and `parameters` go into the record.

#### 5.2 Pricing and constraints

- `PurePremium()`: `P = E[π]`.
- `CostOfCapitalLoad(rate, q)`: `P = (1 − r) · E[π] + r · CVaR_q(π)`, with r ∈ [0, 1] and q ∈ (0, 1). It is convex in the payout, so the problem stays an LP or QP.
- `Budget(ratio=κ)` means P ≤ κ·E[L]; `Budget(amount=B)` means P ≤ B, in payout units. Exactly one of the two. Premium and E[L] are taken on the design sample.
- `Limit(amount)`: the payout never exceeds `amount` (the family's `amount_constraints`).
- The family's constraints: amounts ≥ 0, monotone if set, and the bounds of `Free`.
- E[U] and weighted CVaR need a budget or bounded amounts; without either, any payout at least as large as the loss is optimal, and `design` raises `DesignError` before solving. MSE needs neither.

#### 5.3 Solver route

| Payout | Free shape parameters | Objective | Pricing | Route |
|---|---|---|---|---|
| `LinearInAmounts` | none | E[U], weighted CVaR | pure, cost of capital | one LP |
| `LinearInAmounts` | none | MSE | pure | one QP in the amounts only: `θᵀHθ − 2gᵀθ`, H = Bᵀ diag(p) B, g = Bᵀ diag(p) L |
| `LinearInAmounts` | none | MSE | cost of capital | one QP with the Rockafellar–Uryasev auxiliaries of the premium |
| `LinearInAmounts` | some | any built-in | any | a grid over the shape candidates, with the LP or QP above at each grid point |
| any other payout, or a `UserObjective` | any | any | any | a grid over every free parameter, evaluated in numpy; candidates that break the budget or the limit are dropped |

- **The grid.** A free shape parameter must have a grid (§3). The candidates are the Cartesian product of the grids, restricted to ordered breakpoints and knots. `DesignOptions(max_grid_points=10_000)` caps the product; above the cap `design` raises. The best candidate wins. Ties within the tolerance go to the first candidate in lexicographic order and are counted (`DesignResult.ties`). (Erratum 6, 2026-11-06, MAR-268: "the tolerance" is `DesignOptions.feasibility_tolerance` (1e-7). `ties` counts the *other* candidates whose objective lies within 1e-7 · max(1, |best|) of the best, in scaled units, so a unique best gives 0. A `UserObjective` has no known scale, so its candidates are compared in its own units. §5.4 has the rest; no decision changes.) The objective at every candidate is kept (`DesignResult.profile`, a `pyarrow.Table`).
- **Why a grid.** On a finite sample the objective is piecewise constant (step, binary) or piecewise smooth (linear, piecewise linear) in the shape parameters, so gradients mislead. A stated grid is reproducible and shows how flat the optimum is. A local refinement after the grid is a later option (§9).
- **Scaling.** Losses and payouts are divided by the scale before solving: the largest loss of a draw (in a joint design, of the draw's loss summed over the assets), or 1 if that is at most 1e-6, as the core's `build_context` does. Results are in payout units.
- **No silent failures.** After the solve, numpy recomputes the objective, the premium, the budget and every constraint from the returned parameters, with relative tolerance `DesignOptions.feasibility_tolerance = 1e-7`. A violation, or any solver status other than optimal, raises `DesignError` (or `InfeasibleDesignError`, `UnboundedDesignError`) with the asset id and the solver's message. Amounts below 1e-9 of the scale are set to 0 and counted, so a 1e-12 level doesn't count as a payout in §6's rates.

**`DesignResult`** holds: the resolved `cover`; `template_hash`; `design_id` (§7); the objective's document and `objective_value`; `premium`, `expected_loss` and the budget's use; `route` (`"lp"`, `"qp"` or `"grid"`); the solver's name, version, status, iterations and time; the non-uniqueness report of §5.4; the degenerate-tail flags; and the design sample's `content_hash`.

#### 5.4 Non-unique optima

The module reports non-uniqueness. It does not hide it behind one solver-dependent answer.

- **Unidentified amounts.** An amount whose basis column is zero in every design year (a step bin or a piecewise segment that no year reaches) changes nothing in the sample: not the objective, the premium or the budget, under every objective and pricing. `DesignResult.unidentified` lists them. A stated rule sets them: `DesignOptions(fill="lowest")`, the default, takes the smallest value the constraints allow (the previous identified level under `monotone`, else 0); `fill="highest"` takes the largest (the next identified level, or the limit or upper bound above the last one; with no bound above, `design` raises). Both keep the design exactly optimal. The rule is recorded.
- **Ranges and uniqueness on the LP route** (`DesignOptions(ranges=True)`). Each identified amount is ranged twice: its smallest and largest value over the near-optimal set {feasible θ : objective(θ) ≤ optimum + ε · max(1, |optimum|)}, in scaled units, for a wide ε₁ = 1e-9 and a narrow ε₂ = 1e-11. That is four LPs per amount, solved with HiGHS at primal and dual feasibility tolerances of 1e-10 (its defaults are 1e-7).
  - An amount is **pinned** when its narrow range is at most half its wide one, or narrower than 1e-7 of the scale. `unique` is true when every identified amount is pinned. `DesignResult.ranges` maps each amount to its wide range (low, high). Without `ranges=True`, `unique` is `None` on the LP route.
  - Why two tolerances: in an LP the width of a near-optimal range is, for small ε, w(ε) = w₀ + c·ε. Here w₀ is the width of the optimal set along that amount, and c is the inverse of the objective's slope there. At a unique vertex w₀ = 0, so the width falls a hundredfold from ε₁ to ε₂. On a set of optimal designs it keeps w₀. A single tolerance can't tell the two apart: the width at a unique vertex is ε/slope, which can be any size. In the MAR-245 fixtures it was 6e-6 to 5e-3 of the scale at a near-optimal tolerance of 1e-6, so a fixed width threshold would have called all 15 unique LP optima non-unique. With the two tolerances, the pinned ranges shrank to 4 % or less, and the others kept at least 99.8 % of their width and are at least 2e-3 of the scale wide (erratum 3, 2026-11-06, MAR-262: this sentence first said "1 % or less"; the ratio of the two tolerances is 1 %, and the solvers' own tolerance adds the rest where a range is near 1e-9 of the scale; the measured figure is in `parity/crc/README.md`).
  - The test detects an optimal set only if it is wider than about c·ε₁. A narrower one is reported as unique.
- **MSE route.** The minimiser over the identified amounts is unique exactly when H restricted to them is positive definite. `unique` comes from its smallest eigenvalue (relative tolerance 1e-10).
- **Grid route.** `ties` counts the candidates within the tolerance of the best (erratum 6, 2026-11-06, MAR-268: this bullet first said "`ties` counts the candidates within the tolerance of the best", which left the tolerance open and did not say whether the best counts itself). The tolerance is `DesignOptions.feasibility_tolerance` (1e-7). `ties` counts the *other* candidates whose objective lies within 1e-7 · max(1, |best|) of the best, in scaled units, so a unique best gives 0; for a `UserObjective`, which has no known scale, the comparison is in its own units. The first of the tied candidates in lexicographic order wins. On the LP and QP routes there is one candidate, so `ties` is 0. On the grid route `unique` is false when `ties` is above 0, else it is the inner solve's report. This is what the merged R-16 code does (`crc_sdk/parametric/design.py`, marc272/crc-sdk#5); no decision changes.
- **Degenerate tails** (weighted CVaR), as the core's runner defines them: `p_zero_loss = P(L = 0)`; `tail_outcomes = (1 − β) / p_min`, with p_min the smallest draw probability; `degenerate_tail = "expected_uncovered"` when β ≤ `p_zero_loss` (the objective is then a multiple of E[U]), `"single_outcome"` when `tail_outcomes ≤ 1`, otherwise `None`. They are recorded, not raised.
- Every comparison row of a designed cover carries `unique`, `ties` and `degenerate_tail` (§6), so no reader takes one member of an optimal set for the design.

#### 5.5 Solver and dependency policy

**Policy.** The base install gets nothing new. Sampling, payouts, metrics and the comparison use only numpy, pyarrow and crc-framework, which the base install already has. Only `design` needs a solver. It comes from the optional extra `crc-sdk[parametric]`, imported lazily inside `design`; without it, `design` raises `SolverUnavailableError` (an `ImportError`) that names the extra, following crc-sdk's rule (U7). The solver sits behind a private interface, `_solver.py`: `solve_lp(...)` and `solve_qp(...)` take matrices in compressed sparse column form as plain numpy arrays (pointers, indices, values; no scipy) and return the values, the status and the solver's identity. So the backend can change without an API change.

**The options**, checked against what crc-sdk and crc-framework ship (U7, U9) and against the three routes:

| | highspy (HiGHS) | scipy | clarabel (Python) | a solver inside crc-framework (Rust) | cvxpy |
|---|---|---|---|---|---|
| LP (E[U], weighted CVaR, cost of capital) | yes: simplex or interior point; vertex solutions | yes: the same HiGHS, through `linprog` | yes: interior point | yes (the Clarabel or HiGHS libraries) | through a solver |
| QP (MSE) | yes: convex QP | no QP interface; only `minimize` (SLSQP, trust-constr) on the small condensed QP | yes | yes | yes |
| MSE with a cost-of-capital budget (a sparse QP) | yes | no direct route | yes | yes | yes |
| Free shape parameters | the grid | the grid, or `minimize` and `differential_evolution` | the grid | the grid (crc-framework's Nelder–Mead is internal) | the grid |
| New Python dependencies | highspy; it needs only numpy | scipy | clarabel, scipy and cffi | none | cvxpy, clarabel, osqp, scs, scipy |
| Installed size (macOS arm64, CPython 3.12) | 9.6 MB | 70 MB | 2.3 MB plus scipy | adds to the crc-framework wheel | about 80 MB with its dependencies |
| Licence (all compatible with AGPL-3.0-or-later) | MIT | BSD-3-Clause | Apache-2.0 | Apache-2.0 (Clarabel) or MIT (HiGHS) | Apache-2.0 |
| Wheels for Python 3.11–3.13 | yes: 1.15.1 ships CPython 3.9–3.14 wheels for Linux, macOS and Windows | yes, but scipy 1.18 needs Python ≥ 3.12, so 3.11 resolves to 1.17 | yes: abi3 | through crc-framework's own wheels | yes |
| Types for mypy strict | ships `py.typed` and stubs | partial | not checked | through crc-framework's stubs | partial |
| Fit with crc-sdk | an optional extra, imported lazily | the same | the same, but it pulls in scipy | the best fit with U8, but it needs a crc-framework change and release, which is RiskThinking's call | far too heavy for an extra |

A smoke check by the agent on 2026-11-05 (synthetic step payouts, one machine, macOS arm64; script and output in the PR, not committed):

- **LP.** highspy and scipy's `linprog` gave the identical E[U] optimum: they run the same HiGHS.
- **QP.** highspy's QP and scipy's trust-constr on the condensed QP agreed on MSE to 1e-8 in the objective, and to about 1e-5 in the parameters. highspy solved MSE under a cost-of-capital budget, with the budget binding to machine precision. clarabel agreed with highspy to about 1e-6 in the parameters.
- **Time.** At 10,000 years and 15 bins: highspy 0.1 s for the weighted-CVaR LP and 0.4 s for the MSE + cost-of-capital QP. At 50,000 years: 4.8 s and 7.4 s; clarabel 2.6 s and 0.5 s. At 130,000 years: highspy 46 s for the LP, clarabel 10 s.

**Recommendation: highspy**, as `crc-sdk[parametric] = ["highspy>=<floor>,<2"]`; R-16 sets the floor and tests it in CI (the smoke check used 1.15.1). It is the only option that covers the LP, the QP and the cost-of-capital QP with one small, numpy-only, typed dependency. Its simplex returns vertex solutions of the LPs, it takes its matrices as plain numpy arrays, and its wheels cover crc-sdk's whole test matrix. The free-shape route is a grid with every backend, so scipy's optimisers buy nothing in Phase 1.

- **scipy is the acceptable alternative** (owner input 2). It ties on the LP, since it runs the same HiGHS. It has no QP interface, so MSE under a cost-of-capital budget would need a cutting-plane loop of our own. It is about seven times larger.
- **clarabel** was the fastest at large samples, but its Python package requires scipy, so as an extra it is larger than scipy alone.
- **A solver inside crc-framework** is the end state that best fits U8: no extra at all, and the same numerics in Python and JavaScript. It needs RiskThinking to accept a solver dependency in their Rust core (Q5). `_solver.py` keeps that move free of API changes.
- **cvxpy**, which the core uses, is rejected: it is a modelling layer that brings four solvers and scipy.

### 6. Metrics

**Notation.** On an evaluation sample, for one cover: p_d the draw probabilities; L_d the loss; π_d the payout; U_d = (L_d − π_d)^+ the uncovered loss; R_d = L_d − π_d the residual; P the premium used; N_d = L_d − π_d + P the net loss, the owner's cost of the year with the cover.

**The premium used.** It is the `premium=` argument if given. Otherwise, for a designed cover, it is the design premium: the contract price, priced on the design sample. Otherwise it is priced on the evaluation sample with the stated pricing. The row records which (`premium_basis`: `"stated"`, `"design"` or `"evaluation"`). Out-of-sample rows of a design therefore use the price agreed at design.

**VaR and CVaR.** `VaR_β(X)` is the smallest x with `Σ_{X_d ≤ x} p_d ≥ β`, where the comparison allows 1e-10 for the rounding of the summed probabilities. So a β exactly on a step gives the lower atom on every platform (review F2). `CVaR_β(X) = VaR_β(X) + Σ p_d (X_d − VaR_β(X))^+ / (1 − β)`, the mean of the worst 1 − β of the probability, with the atom at the VaR split as needed. The CVaR doesn't depend on which atom the VaR picks.

**Tail weights.** w_d^β are the CVaR_β weights of the loss: p_d where L_d > VaR_β(L); a share of the remaining mass 1 − β − P(L > VaR_β(L)), pro rata to p_d, where L_d = VaR_β(L); 0 elsewhere. They sum to 1 − β.

| Column | Definition | Null when |
|---|---|---|
| `expected_loss` | E[L] | — |
| `expected_payout` | E[π] | — |
| `premium` | P, as above | — |
| `expected_uncovered` | E[U] | — |
| `coverage_ratio` | E[min(π, L)] / E[L] = 1 − E[U] / E[L]: the share of the expected loss that payouts cover; payouts above the loss don't count | E[L] = 0 |
| `payout_to_loss_ratio` | E[π] / E[L]: payouts above the loss count too (the core's KPI of that name) | E[L] = 0 |
| `tail_coverage_b<β>` | `Σ w_d^β min(π_d, L_d) / Σ w_d^β L_d`: the share of the loss covered in the worst 1 − β of loss years | `Σ w_d^β L_d = 0` |
| `cvar_uncovered_to_loss_b<β>` | `CVaR_β(U) / CVaR_β(L)`: the tail of the uncovered loss against the tail of the uninsured loss | CVaR_β(L) = 0 |
| `false_negative_rate_l<ℓ>` | `P(π ≤ ε, L > ℓ) / P(L > ℓ)`: years with a loss above ℓ and no payout | P(L > ℓ) = 0 |
| `false_positive_rate_l<ℓ>` | `P(π > ε, L ≤ ℓ) / P(L ≤ ℓ)`: years with a payout and a loss of at most ℓ | P(L ≤ ℓ) = 0 |
| `rmse` | `sqrt(E[R²])` (the core's `rmse_residual`) | — |
| `correlation` | the p-weighted Pearson correlation of L and π | either has zero variance |
| `var_uncovered_b<β>`, `cvar_uncovered_b<β>` | VaR_β(U), CVaR_β(U) | — |
| `var_net_loss_b<β>`, `cvar_net_loss_b<β>` | VaR_β(N), CVaR_β(N) | — |
| `var_loss_b<β>`, `cvar_loss_b<β>` | VaR_β(L), CVaR_β(L), the same for every cover on a sample | — |
| `loss_rp<T>`, `payout_rp<T>`, `uncovered_rp<T>`, `net_loss_rp<T>` | the value exceeded with probability 1/T: the lower (1 − 1/T)-quantile, by the VaR rule above. T is in years, because a draw is a year | — |

- `MetricOptions(betas=(0.9, 0.95, 0.99), return_periods=(2, 5, 10, 25, 50, 100, 250), loss_thresholds=(0.0,), payout_threshold=0.0)` sets β, T, ℓ and ε. The thresholds are always stated: there is no hidden threshold (crc-docs' quality gate). ℓ is in loss units; ε is the payout below which a year counts as "no payout".
- Labels `<β>`, `<T>`, `<ℓ>` follow crc-sdk's return-period column rule (`value_rp2_5`): the decimal text with the point as an underscore, so β = 0.99 gives `cvar_uncovered_b0_99` and T = 100 gives `loss_rp100`. The default loss threshold 0.0 gives `l0`, as in `false_negative_rate_l0`. Colliding names raise. The metadata maps every column to its metric, parameter, unit and definition (§7).
- **crc-framework's CVaR is a different quantity.** Its `compute_risk` gives VaR and CVaR over the 2ⁿ branches of independent binary factor outcomes, each with a downside probability and impact (U10). This module's VaR and CVaR are over the years of an outcome sample, for one continuous quantity of one cover (uncovered loss, net loss or loss). The random variable, the outcomes and the dependence assumptions all differ. The two never share a column and are never compared. Docstrings and `docs/parametric.md` say so in these words.

**In and out of sample.**

- In sample means the design sample. Out of sample means held-out year blocks (holdout, k-fold) or fresh Monte Carlo draws. Every row says which: `split` and `fold`.
- k-fold gives one design per fold and rows per fold. Pooled k-fold metrics are a follow-up.
- External numbers come from out-of-sample rows (publication rule). In-sample rows exist for the overfitting gap.

**The comparison table** (`compare`): one row per cover and split, metrics as columns (MAR-247), the layout of crc-sdk's portfolio output (U2).

Amendment 3 (D-21.3) changes this table: it adds the `scope` column and the levels `"total"`, `"asset_by_value"` and `"asset_by_loss"`, and makes `asset_id` and `premium_basis` nullable.

Amendment 4 (D-23.2 to D-23.4) adds the columns `design_scenario`, `pathway`, `horizon`, `product`, `n_rows` and `premium_repriced`, and the premium basis `"reference"`.

| Column | Type | Meaning |
|---|---|---|
| `cover_label` | string | The user's label, or the first 12 hex digits of the hash |
| `cover_hash` | string | `Cover.definition_hash` |
| `design_id` | string, nullable | §7; null for a cover given as is |
| `asset_id` | string | The asset |
| `level` | string | `"asset"` in Phase 1 (§9 reserves more) |
| `scenario` | string | `"baseline"` in Phase 1 |
| `split` | string | `"in_sample"` or `"out_of_sample"` |
| `fold` | int32 | 0 for holdout and fresh draws; the fold for k-fold |
| `sample_hash` | string | The evaluation sample's `content_hash` |
| `premium_basis` | string | `"stated"`, `"design"` or `"evaluation"` |
| `unique`, `ties`, `degenerate_tail` | bool, int32, string; nullable | From the design (§5.4); null for a cover given as is |
| one column per metric | float64, nullable | As defined above; null where the table says |

- The key (`cover_hash`, `design_id`, `asset_id`, `level`, `scenario`, `split`, `fold`) is unique, and `compare` checks it.
- `to_long(table)` gives the tidy form (one row per metric and parameter) for analysis.
- `write_comparison` writes one Parquet file atomically, with the metadata of §7 under `crc.parametric.evaluation`.

### 7. Provenance

Amendment 2 (the per-year route) describes the per-year source records as merged, and adds the records of the trend, the pool and the index series.

Amendment 4 (scenario analysis) adds `setup.scenarios`, the split method `"other_scenario"` and the leakage result `"different_sources"`.

**Hashes.**

- **Cover:** `definition_hash` (§3).
- **Sample:** `content_hash`, the SHA-256 of the canonical bytes of the long table (sorted by period and asset), with the units, the semantics and the scenario.
- **Design:** `design_id`, the SHA-256 of the canonical JSON of the template hash, the objective, the pricing, the budget, the limit, the design options and the design sample's hash. The solver's identity and the time go into the record, not into the id.

**The Parquet metadata** under `crc.parametric.evaluation` is one JSON document, validated by a pydantic model (`EvaluationMetadata`) and written with sorted keys:

- `schema_version` (`"1.0"`), `producer` (`"crc_sdk.parametric"`), `creation_version` (the crc-sdk version), `crc_framework_version`, the solver's name and version (when a design ran), the numpy version, `platform`, `created_at` (UTC).
- `setup`, which the publication rule asks for next to every number:
  - `basis`: `"annual"`, one draw is one year;
  - per sample: the source kind; the number of draws, or the years and their range; the semantics and `semantics_source`; the basis-risk model and its parameters; the loss model (the impact's type, name, `definition_hash` if any, units, value column);
  - the pricing, budget and limit;
  - the split: holdout fraction, k and fold, or the seed of the fresh draws;
  - the metric options.
- `columns`: for every metric column, its metric, parameter, unit and one-line definition.
- `covers`: for every cover, its label, hash and full JSON document.
- `designs`: for every design, its `design_id`, template hash, objective, route, solver status, objective value, premium, unidentified amounts and fill rule, `unique`, `ties`, ranges (if computed), `p_zero_loss`, `tail_outcomes` and `degenerate_tail`.
- `sources`: for every hazard dataset, the source block of its `crc.hazard.metadata` (provider, dataset, URI, version, licence, attribution, retrieval time, checksum), its `probability_semantics`, `return_period_tail`, `temporal_window` and `ensemble`, the horizon and pathway, and the file's SHA-256. For per-year values: the source plan's `explain()` output and the matched cell or station. For a user table: the name the caller gives and the table's content hash.
- `source_records`: what a plan read, once for all its samples; empty for a comparison that `compare` or `evaluate` builds. On fitted curves it holds `{"canonical_file": {...}}`: the dataset's path, its SHA-256 and the number of matched curves. On per-year values it holds `{"annual_table": {...}}`: the table's rows, columns and SHA-256, the source plan's `explain()` and, for a file, its path and SHA-256. Each hazard entry of `sources` names its record by that checksum, `canonical_file_sha256` (the file's) or `annual_table_sha256` (the table's), and doesn't repeat the record. (Erratum 11, 2026-11-08, MAR-288: this bullet is new. `EvaluationMetadata.source_records` and the two checksums came with marc272/crc-sdk#16; before it, a plan repeated the record in every hazard entry of `sources`.)
- `assets`: the number of assets, the id column, and the SHA-256 of the (asset id, value) pairs. The values themselves are not written; they may be private.
- `licences`: every input licence and attribution, for example CRC Open's CC BY-NC 4.0 and its attribution text. The module claims no licence of its own for the output: it is derived data under its inputs' terms.
- `rng`: for every random step, the bit generator's name and its state at entry.

`ParametricPlan.explain()` returns the same `setup` block, as far as it is known before execution (no checksums). `setup_text(metadata)` renders it as the plain sentence a notebook prints next to a number.

### 8. Porting map and parity contract

**From our core** (concepts, formulas and test cases; the module's code is written new):

| Core | Module | What carries over |
|---|---|---|
| `payout.StepPayout` with `below_attachment="zero"` | `StepPayout` | The bin rule (half-open bins; at or above the last breakpoint, the last level) and the validation cases |
| `objectives.MSE`, `ExpectedUncovered`, `WeightedCVaR`, `rockafellar_uryasev` | `objectives.py`, `design.py` | The formulas and the Rockafellar–Uryasev form; solved with HiGHS instead of cvxpy |
| `pricing.PurePremium`, `CostOfCapitalLoad`; `constraints.Budget` | `pricing.py`, `constraints.py` | The formulas. `Budget(loading=κ)` becomes `Budget(ratio=κ)` |
| `basis.outcome_measure` on the annual basis | `OutcomeSample.probability` | One draw per year. No event or event-conditional basis |
| `evaluate.kpis` | `metrics.py` | `expected_loss`, `expected_payout`, `expected_uncovered`, `var_uncovered`, `cvar_uncovered`, `rmse` (the core's `rmse_residual`), `payout_to_loss_ratio`, `correlation`, `premium`: the same formulas |
| `riskmeasures.var_cvar`, `lower_quantile` | `_risk.py` | The CVaR as is; the VaR with the tolerance of §6 |
| `splits.holdout`, `year_block_kfold` | `sample.py` | Year blocks on `period` |
| The runner's degenerate-tail flags | `DesignResult` | The same definitions |
| `docs/concepts/` | `docs/parametric.md` | The method, without result claims |

**New in the module:** `LinearPayout`, `PiecewiseLinearPayout`, `BinaryPayout`; free shape parameters and the grid route; the cover document and hash; Monte Carlo from crc-framework curves with the semantics rules; `AnnualSeries` and the per-year basis-risk model; `LossModel` on crc-sdk impacts; `ImpactNoise`; `coverage_ratio`, `tail_coverage`, `cvar_uncovered_to_loss`, the false-negative and false-positive rates, the net-loss metrics and the return-period columns; the fill rule and the optimal-face ranges; the plan, `explain()` and the metadata.

**Not ported:** cvxpy; the `EventSet`; the experiment runner and store; the event and event-conditional bases; `below_attachment="first_bin"`; the thesis's noise copies (13 copies of each event); clustering and the joint scopes (Phase 2); the bootstrap (a follow-up).

**Parity contract with R-13 (MAR-245).** The module's tests read fixture files and never import the core. The fixtures live in this repository under `parity/crc/`, and its README describes the format. One case is one JSON document:

```text
{"case_id": "step-wcvar-b0_99-pure-individual-synthetic",
 "kind": "design",                         # or "evaluate" for a fixed cover
 "source": "core",                         # or "closed_form"
 "sample": {"asset_ids": ["A1"], "period": [0, 1, ...], "probability": [...],
            "index": [[x_0], [x_1], ...],  # n rows (draws), one value per asset: shape (n, n_assets)
            "loss": [[l_0], [l_1], ...],   # the same shape
            "index_unit": "m/s", "loss_unit": "USD"},
 "cover": <the cover document of §3>,      # joint cases: a list, one per asset, in asset_ids order
 "objective": {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.99},
                                           # or {"kind": "mse"}, {"kind": "expected_uncovered"}; null if evaluate
 "pricing": {"kind": "pure"},              # or {"kind": "cost_of_capital", "rate": 0.06, "q": 0.99}
 "budget": {"ratio": 0.8},                 # or {"amount": ...}; null if evaluate
 "limit": null,                            # always null: the cap is the Free upper bound
 "scope": "individual",                    # or "joint" (Phase 2, R-21)
 "expected": {"objective_value": ..., "premium": ...,
              "parameters": {"levels[0]": ..., ...},   # joint: {"A1": {...}, "A2": {...}, ...}
              "unidentified": ["levels[6]"],           # joint: {"A1": [...], ...}
              "unique": true,
              "metrics": {"expected_uncovered": ..., "var_uncovered_b0_9": {"either": [lower, upper]}, ...}},
 "compare_parameters": "exact",            # or "within_ranges" or "none"
 "tolerances": {"objective_value": 1e-6, "premium": 1e-6, "metrics": 1e-6, "parameters": 1e-6},
 "generator": {"script": "parity/scripts/export_crc_fixtures.py", "core_version": "...", "commit": "..."}}
```

**What a case holds.**

- **Out-of-sample fields** (erratum 4, 2026-11-06, MAR-262): the merged fixtures add `split` (null, or `{"kind": "holdout", "train_fraction": 0.7}`), `evaluation_sample` (the held-out block, in the form of `sample`, which stays the design block) and `expected.out_of_sample` (`{"fold": 0, "premium_basis": "design", "metrics": {…}}`). The holdout's design block is the first ⌊train_fraction · n + 1e-9⌋ draws in period order. `parity/crc/README.md` ("Out-of-sample cases") has the details. The metrics bullet below says "all in sample" for the in-sample cases. No decision changes.
- **More fixture fields** (erratum 5, 2026-11-06, MAR-268, from the fixtures of MAR-264, marc272/parametric-insurance-design#193): `split` also takes `{"kind": "kfold", "k": 5, "fold": i}`, one case per fold, with `sample` = the design blocks and `evaluation_sample` = the held-out block (the core's `array_split` blocks), and `{"kind": "fresh_draws", "n_draws": n, "seed": s}`, with `evaluation_sample` = an independent sample of the same process, whose periods may overlap the design's (leakage goes by lineage, §4.4). `metric_options` is null for the defaults, else the `MetricOptions` of the case. `expected.profile`, on the grid route, is the objective at every candidate. `parity/crc/README.md` has the format. No decision changes.
- **Orientation.** `index` and `loss` are (n, n_assets): one row per draw, one value per asset in `asset_ids` order, as in §4.1. `numpy.asarray(sample["index"])` has that shape.
- **Joint cases** (`scope = "joint"`, for Phase 2's `design_joint`):
  - `cover` is a list of cover documents, one per asset, in `asset_ids` order;
  - `expected.parameters` and `expected.unidentified` are keyed by asset id;
  - the objective, the premium, the budget and the metrics are taken on the sums over the assets of each draw's loss and payout.
- **The core's cap.** The core caps every level at the asset's largest loss on the sample. A case writes that cap as the bound of each amount, `Free(lower=0, upper=cap)`, and `limit` is always null.
  - For the built-in families, `Limit(amount=cap)` would give the same problem (§3: every amount ≤ ℓ). The cases use one form only, so each case has one reading.
  - `Limit` stays the contract's limit, a term the user states.
- **Cases** (39, as MAR-245 built them):
  - 32 design cases from the core: a step payout × {MSE, E[U], weighted CVaR at β 0.9 and 0.99} × {pure premium, cost-of-capital load} × {individual, joint} × {a seeded synthetic set, a subsample of the committed thesis fixture};
  - 4 evaluation cases of fixed step covers, from the core;
  - 3 evaluation cases of fixed linear covers (upper and lower tail), from closed forms.
- **Metrics.** All in sample.
  - Core cases carry only the metrics the core computes: `expected_loss`, `expected_payout`, `expected_uncovered`, `payout_to_loss_ratio`, `correlation`, `rmse`, `premium`, the VaR and CVaR columns, and the return-period columns.
  - The new metrics of §6 appear only in the closed-form cases, for now: `coverage_ratio`, `tail_coverage_b<β>`, `cvar_uncovered_to_loss_b<β>`, and the false-negative and false-positive rates.
- **Core settings.** `below_attachment="zero"`, the annual basis, and **at most one event row per year**.
  - The module has one draw per year, while the core's annual basis sums the events of a year. So a fixture year with several events would not match.
  - A year without an event row becomes a draw with index 0 and loss 0, below every cover's first threshold.
- **`generator.commit`** is the last commit on `main` that changed the core's source (`packages/core/src`) when the cases were generated, suffixed `+dirty` if that source had local edits. A case can't name its own commit, and a squash merge drops the branch's commits. Tests ignore the field, and so does the regeneration check.

**The scale** of a case is the largest summed loss of a draw, `max(sum(row) for row in sample["loss"])`. It is the scale of §5.3.

**Tolerances.**

| Value | Passes if |
|---|---|
| `objective_value` | within 1e-6 relative, with an absolute floor of 1e-9 × scale (1e-9 × scale² for MSE) |
| `premium` | within 1e-6 relative, with an absolute floor of 1e-9 × scale |
| a metric | within 1e-6 relative. The absolute floor is 1e-9 × scale for metrics in loss units, and 1e-9 for the unitless ones (`coverage_ratio`, `payout_to_loss_ratio`, `correlation`, `tail_coverage_*`, `cvar_uncovered_to_loss_*`, `false_negative_rate_*`, `false_positive_rate_*`) |
| a quantile on a step | written `{"either": [lower, upper]}`; either atom passes. This applies to the VaR and return-period columns; §6's rule gives the lower atom. CVaR is always a single value |
| a parameter | within 1e-6 × scale, absolute |

**How a design case is compared.**

1. `objective_value`, always.
2. The parameters, as `compare_parameters` says:
   - `"exact"`: every identified amount (one not in `unidentified`) agrees within the parameter tolerance. Unidentified amounts are left out, for every objective, MSE included: they change nothing on the sample, so any value the constraints allow is optimal (§5.4).
   - `"within_ranges"`: every identified amount of `expected.parameters` lies within the module's wide range (§5.4), widened by 1e-6 × scale.
   - `"none"`: the parameters are not compared.
3. The premium and the metrics:
   - when `unique` is true, those of the module's designed cover;
   - otherwise, those of the template resolved with `expected.parameters` (`Cover.with_values`) and evaluated on the sample. On a non-unique optimum only the objective value is the same for every optimal design. The premium and the metrics depend on which member of the optimal set a solver returns.
4. The module's `unique` must not be true where the case's is false.

**How the cases set `unique` and `compare_parameters`.**

- **LP cases.** The core solves with HiGHS, a vertex, and applies §5.4's two-tolerance test.
  - A unique optimum is written as that vertex, checked against Clarabel at tight tolerances (agreement within 1e-6 × scale). It gets `"exact"`.
  - A non-unique optimum is written as Clarabel's interior point at tight tolerances, one member of the optimal set, checked to lie within the ranges. It gets `"within_ranges"`.
- **MSE cases.** §5.4's eigenvalue rule decides. Unique on the identified amounts gives `"exact"`. A singular H gives `"none"`, because the MSE route computes no ranges; this happens in joint cases where the assets' bin-indicator columns are linearly dependent (for example, when two assets' bins hold the same draws).

### 9. Phase 2 extension points

Phase 1 exports only what it implements. Each name below is added to `__all__` when it is built; adding is not breaking, and nothing exported in Phase 1 has to change.

- **The portfolio approach (R-21, MAR-45).**
  - Amendment 3 (D-21.1 to D-21.6) changes this item: `allocation` moves from `design_joint` to evaluation time, `level` takes the values `"total"`, `"asset_by_value"` and `"asset_by_loss"` in place of those below, the dependence models are `Independent()`, `Comonotonic()` and `EmpiricalCopula(reference)`, and `Clustered(...)` comes later.
  - A new function `design_joint(templates, sample, objective, *, scope=Joint(), allocation="value")`. Its objective is on the owner's total loss and total payout over the assets; each asset keeps its own cover. `Clustered(...)` follows the core's cluster scope. `design` stays the per-asset function.
  - The LP and QP routes carry over: B becomes the block matrix over the assets' amounts.
  - A joint payout needs a stated allocation rule (`"value"` or `"loss"`, as in the core's `docs/methodology/payout-allocation.md`) for per-asset rows. The table's `level` column gains `"joint"` and `"cluster"`.
  - Multi-asset Monte Carlo samples need a dependence model: `Comonotonic()`, `Independent()` or `GaussianCopula(correlation)`, always stated and never defaulted. Per-year samples carry their own. Better dependence data is Q4.
  - External text presents joint calibration as a method only (publication rule).
- **Multi-hazard covers (R-22, MAR-250).** `CompositeIndex` (named `IndexDefinition`s), payouts with several `index_names`, `OutcomeSample.index_components`, and the combinator families of §3. Two hazards at one site need a joint distribution; for per-year samples it is the data's own.
- **Scenarios (R-23, MAR-44).** A `ScenarioSet` maps scenario labels to samples with the same assets. `compare` fills the `scenario` column. Robust design (min–max over scenarios, as SPEC §6.5 R1) becomes an objective wrapper, `Robust(objective)`, over a `ScenarioSet`.
  - Amendment 4 (D-23.1 to D-23.6) settles this item: a `ScenarioSet` holds one sample per scenario, `compare_scenarios` fills the `scenario` and `design_scenario` columns, and `Robust(objective)` stays for later.
- **Also reserved:** the semantics value `"event"` (several events per year); a local refinement after the grid; block-bootstrap intervals and pooled k-fold metrics; a second solver backend in `_solver.py`.

### 10. The issue map

The split into R-14 to R-18 holds, with four adjustments (marked "adjusted"). Amendment 1 (D11) splits R-18 into MAR-42 and MAR-271, and adds R-25 (MAR-274).

Amendment 3 (the portfolio approach) adds the rows of R-21: MAR-298 and MAR-301 to MAR-305, with R-21g deferred.

Amendment 4 (scenario analysis) adds the rows of R-23: MAR-331 to MAR-335.

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| MAR-246 (R-14) | The package skeleton, errors, canonical JSON, `IndexDefinition`, `Free`, the payout protocols and the four families, `Cover`, the registry; the `docs/parametric.md` stub | `__init__`, `errors`, `_canonical`, `index`, `parameters`, `payouts`, `cover` | This ADR is accepted. **Adjusted:** the optional extra moves to R-16, because R-14 needs no solver |
| MAR-43 (R-15) | `OutcomeSample`, the three sources and their semantics rules, `AnnualSeries`, `LossModel`, `NoBasisRisk` and `ImpactNoise`, seeding, the splits. One asset per sample | `sample`, `sources`, `loss`, `basis_risk` | R-14. **Adjusted:** the index from another cell or hazard is the per-year `index=` series; for Monte Carlo it waits for Phase 2 |
| MAR-247 (R-17) | `_risk`, `pricing` (premium values), the metrics, `evaluate`, `compare`, `write_comparison`, `EvaluationMetadata`; parity of the metrics with R-13 | `_risk`, `pricing`, `metrics`, `evaluate`, `metadata` | R-15, R-13. **Adjusted:** "coverage ratio" is E[min(π, L)] / E[L]; the issue's E[π] / E[L] is kept as `payout_to_loss_ratio` (owner decision 6) |
| MAR-248 (R-16) | Objectives, constraints, `design`, the solver interface and the HiGHS backend, the `parametric` extra, the non-uniqueness report; parity of the designs with R-13 | `objectives`, `constraints`, `design`, `_solver`; `pyproject.toml` | R-17, R-13. **Adjusted:** HiGHS through `highspy`, not through scipy (owner decision 2) |
| MAR-42 (R-18) | `ParametricPlan`, `explain()`, both entry points, `PortfolioEvaluation.asset_curves()` if RiskThinking agrees, the finished `docs/parametric.md`, the README line, the end-to-end offline test | `plan`; `workflows/portfolio.py` and `workflows/_portfolio.py` (one additive method) | R-16, Q1 |
| MAR-46 (R-19) | The notebook in the crc-docs fork, following crc-docs' conventions: a row in the README's "Choose a problem" table, a `REQUIREMENTS` set-up cell and static chart previews as [`tests/test_notebooks.py`][docs-tests] checks them. A skill and a pipeline are optional follow-ups | crc-docs fork | R-18 |
| MAR-245 (R-13) | The golden fixtures in this repository, with the fields of §8 | this repository | This ADR is accepted |

Amendment 2 (the per-year route) adds the rows of R-25: MAR-293 to MAR-297, MAR-300 and MAR-307.

### 11. Open questions for RiskThinking (for R-20, MAR-249)

- **Q1. Asset curves.** May R-18 add the public execution point `PortfolioEvaluation.asset_curves()` (the matched canonical rows, through the existing join)? Or would you rather add one yourselves, under another name or in another place? (Amendment 1, D11: the fork builds it now, and the upstream PR offers it as a proposal that RiskThinking can rename, move or replace.)
- **Q2. Chaining.** Do you want a method on `PortfolioEvaluation` (for example `.parametric(...)`), or the stand-alone `ParametricPlan.for_evaluation(...)`?
- **Q3. Annual extremes and assets.** Do you plan an asset join for `annual_extremes()`? Is "the nearest cell centre, within half a grid step" right for the ERA5, CMIP6 and NEX grids?
- **Q4. Dependence.** Do you have, or plan, event sets, spatially co-simulated fields, or the per-year and per-member samples behind the pooled curves? Phase 2's joint and multi-hazard designs need one of them, or an assumed copula.
- **Q5. The solver's home.** Is `highspy` acceptable as the optional extra `crc-sdk[parametric]`? In the long run, would you want the LP and QP solve in crc-framework (Rust, with Clarabel or HiGHS), so that crc-sdk needs no extra?
- **Q6. Probability semantics.** `cyclone` and the flood layers declare none: what should a caller state for them? Is sampling years from a `pooled` curve acceptable for a cover's annual outcomes? How should years more frequent than a curve's shortest fitted return period be treated (§4.2)? And should the return-period check also warn on `estimate_confidence`, as the docs say (U4)?
- **Q7. Damage-function uncertainty.** Are there uncertainty ranges for the registry impacts that could serve as vulnerability draws?
- **Q8. Names and keys.** Are the module name `crc_sdk.parametric`, the metadata keys `crc.parametric.evaluation` and `crc.parametric.sample`, the page `docs/parametric.md` and the extra name `parametric` fine?
- **Q9. Hashing.** crc-framework's canonical JSON is reachable from Python only as a method of its impact objects. Would you expose a general `canonical_json` and `content_hash`, so the cover's hash reuses yours instead of re-implementing the same spelling (§3)?
- **Q10. Review.** One upstream PR for Phase 1, or one per part?

## Decisions for the owner (D10)

Each with the agent's recommendation first.

1. **API shape:** both layers, functions first and the plan in R-18 (§2). Alternatives: the plan only, or functions only.
2. **Solver:** `highspy` as the optional extra (§5.5). Alternatives: scipy (acceptable, but no QP interface), clarabel (pulls in scipy), or a solver inside crc-framework later (Q5).
3. **Free shape parameters:** a stated grid in Phase 1 (§5.3). Alternative: a derivative-free optimiser now.
4. **Unidentified amounts:** report them and fill them by a stated rule, default `"lowest"` (§5.4). Alternatives: `"highest"` as the default, or raise.
5. **VaR on a step:** the tolerance rule, the lower atom on every platform (§6). Alternative: the core's strict comparison.
6. **"Coverage ratio":** E[min(π, L)] / E[L], with E[π] / E[L] kept as `payout_to_loss_ratio` (§6). Alternative: MAR-247's E[π] / E[L].
7. **Phase 1 scope:** one asset per sample and one draw per year; the plan handles several assets as one sample each, with no cross-asset sums (§4.1). Alternative: several assets per sample with a stated dependence model in Phase 1.
8. **Basis-risk model:** a required argument; `NoBasisRisk()` must be explicit and warns (§4.4). Alternative: `NoBasisRisk()` as a warned default.
9. **The premium out of sample:** the design premium, the contract price (§6). Alternative: priced again on each evaluation sample, as the core's `kpis` does.
10. **Entry point:** `ParametricPlan.for_evaluation(request)`, plus asking RiskThinking for `PortfolioEvaluation.asset_curves()` (§2, Q1).
11. **The issue map** with its four adjustments (§10).

**Revision after the MAR-245 fixtures (2026-11-05, before the decision).** The fixtures (PR #183) found nine points where the first draft was ambiguous or unworkable, and §5.4, §6 and §8 now settle them.

- **Two of the nine change a rule:**
  - point 4: the premium and the metrics of a non-unique design are compared at `expected.parameters`, not against the module's own design;
  - point 5: the LP uniqueness test uses two near-optimal tolerances (1e-9 and 1e-11) instead of one range width, which could not detect a unique optimum.
- **The other seven are clarifications:**
  - point 1: arrays are (n, n_assets);
  - point 2: the form of a joint case;
  - point 3: the core's cap is written as `Free(upper=cap)`, with `limit` null;
  - point 6: the absolute floors are in units of the scale;
  - point 7: `"exact"` leaves unidentified amounts out for every objective;
  - point 8: the `l0` label;
  - point 9: `generator.commit` is the last core-source commit on `main`, and tests ignore it.

  The note that core cases carry only the core's metrics is a clarification too.

## Consequences

- MAR-246 can start once this ADR is accepted. MAR-245 takes its field names from §3 and §8 now, and renames them if the accepted ADR differs.
- The module carries its own implementation of the formulas. A formula change in either the core or the module needs a fixture update, or the parity tests fail.
- crc-sdk gains one optional dependency and, if RiskThinking agrees, one additive public method. Nothing in its base install or its existing `__all__` changes.
- Phase 1 results are per asset. Statements about several assets together wait for Phase 2 and its stated dependence model.
- Every designed cover comes with its non-uniqueness report, so external text can't present one member of an optimal set as "the" design.
- The grid route costs one LP or QP per candidate; large grids on large samples take minutes (§5.5). `max_grid_points` keeps that visible.

## Alternatives considered

- **Port the core as it is (cvxpy and the `EventSet`).** Rejected: cvxpy is far too heavy for an extra (§5.5), CRC has no events (U11), and the module must not depend on our code.
- **The payout as an array of levels (the core's `theta`), not named parameters.** Rejected: named parameters make the JSON document readable, let any parameter be fixed or free, and fit families other than steps.
- **A first-bin mode for parity with the thesis.** Rejected by the owner's rule (2026-11-01). The parity cases use the core's `below_attachment="zero"`.
- **Gradient-based search over attachment, exhaustion and breakpoints.** Rejected for Phase 1: the objective is piecewise constant or piecewise smooth in them on a finite sample.
- **A long (tidy) comparison table as the stored form.** Rejected: MAR-247 asks for covers as rows, and crc-sdk's portfolio output uses wide value columns. `to_long` gives the tidy form.
- **The label inside the hash.** Rejected: the hash identifies the contract terms; a label is a display name.
- **A default dependence model (comonotonic) for multi-asset samples.** Rejected: it would be an unstated assumption, and Phase 1 doesn't need one.

## Not verified

- highspy's oldest version with the API `_solver.py` needs, and its behaviour on Windows and Linux: R-16's CI checks both. The smoke check ran on one macOS arm64 machine.
- How fast a vectorised standard normal is without scipy (for Phase 2's copulas). Phase 1 doesn't need it.
- That the existing join can serve `asset_curves()` without a change in behaviour. The join code was read, not run.
- The geometry of the CMIP6 and NEX grids for `nearest_cell`: regular latitude–longitude grids are assumed.
- clarabel's typing for mypy strict was not checked.
- crc-framework's spelling of numbers in canonical JSON was read in its Rust code, not tested from Python.
- The `return_period_support` of the CRC Open curves was not read (no CRC data was opened), so the share of draws below or above it is not known here.
- No crc-sdk or crc-framework test was run, and no CRC data was read.

## Sources

Upstream files at the commits read (2026-11-05):

- crc-sdk: [`AGENTS.md`][sdk-agents], [`docs/concepts.md`][sdk-concepts], [`docs/portfolio.md`][sdk-portfolio], [`docs/design-decisions.md`][sdk-dd], [`docs/runtime.md`][sdk-runtime], [`docs/development.md`][sdk-dev], [`pyproject.toml`][sdk-pyproject], [`workflows/_plans.py`][sdk-plans], [`workflows/portfolio.py`][sdk-portfolio-py], [`workflows/_portfolio.py`][sdk-portfolio-join], [`workflows/distributions.py`][sdk-distributions], [`workflows/crc_open.py`][sdk-crc-open], [`workflows/stations.py`][sdk-stations], [`workflows/nex.py`][sdk-nex], [`types/dataset.py`][sdk-dataset], [`impacts/expression.py`][sdk-expression].
- crc-framework: [`docs/python.md`][fw-python], [`python/crc_framework/distributions/base.py`][fw-base], [`fitted.py`][fw-fitted], [`crates/core/src/reference/curve_fitting.rs`][fw-fitting], [`crates/core/src/impact/json.rs`][fw-json], [`crates/core/Cargo.toml`][fw-cargo], [`pyproject.toml`][fw-pyproject].
- crc-docs: [`README.md`][docs-readme], [`tests/test_notebooks.py`][docs-tests].
- Solver packages (PyPI metadata, read 2026-11-05): highspy 1.15.1 (MIT), scipy 1.17 and 1.18 (BSD-3-Clause), clarabel 0.11.1 (Apache-2.0). Installed sizes measured in this repository's environment.
- This repository: `docs/adr/0001` to `0004`, `docs/SPEC.md` §5–§6, `docs/concepts/`, `docs/reviews/core-design-review.md`, `showcase/crc/COLLABORATION-SCAN.md`, `showcase/crc/MEETING-BRIEF.md`, `research/notes/individual-nonuniqueness.md`, and the core modules named above.

[sdk]: https://github.com/RiskThinking/crc-sdk/tree/9c56bb0e576f84a481bd5537d6db478dc89cf72e
[sdk-agents]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/AGENTS.md
[sdk-concepts]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/docs/concepts.md
[sdk-portfolio]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/docs/portfolio.md
[sdk-dd]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/docs/design-decisions.md
[sdk-runtime]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/docs/runtime.md
[sdk-dev]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/docs/development.md
[sdk-pyproject]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/pyproject.toml
[sdk-plans]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/crc_sdk/workflows/_plans.py
[sdk-portfolio-py]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/crc_sdk/workflows/portfolio.py
[sdk-portfolio-join]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/crc_sdk/workflows/_portfolio.py
[sdk-distributions]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/crc_sdk/workflows/distributions.py
[sdk-crc-open]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/crc_sdk/workflows/crc_open.py
[sdk-stations]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/crc_sdk/workflows/stations.py
[sdk-nex]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/crc_sdk/workflows/nex.py
[sdk-dataset]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/crc_sdk/types/dataset.py
[sdk-expression]: https://github.com/RiskThinking/crc-sdk/blob/9c56bb0e576f84a481bd5537d6db478dc89cf72e/crc_sdk/impacts/expression.py
[fw]: https://github.com/RiskThinking/crc-framework-rs/tree/838c295e4d078f98870819d8eb1004bb4f0611ec
[fw-python]: https://github.com/RiskThinking/crc-framework-rs/blob/838c295e4d078f98870819d8eb1004bb4f0611ec/docs/python.md
[fw-base]: https://github.com/RiskThinking/crc-framework-rs/blob/838c295e4d078f98870819d8eb1004bb4f0611ec/python/crc_framework/distributions/base.py
[fw-fitted]: https://github.com/RiskThinking/crc-framework-rs/blob/838c295e4d078f98870819d8eb1004bb4f0611ec/python/crc_framework/distributions/fitted.py
[fw-fitting]: https://github.com/RiskThinking/crc-framework-rs/blob/838c295e4d078f98870819d8eb1004bb4f0611ec/crates/core/src/reference/curve_fitting.rs
[fw-cargo]: https://github.com/RiskThinking/crc-framework-rs/blob/838c295e4d078f98870819d8eb1004bb4f0611ec/crates/core/Cargo.toml
[fw-json]: https://github.com/RiskThinking/crc-framework-rs/blob/838c295e4d078f98870819d8eb1004bb4f0611ec/crates/core/src/impact/json.rs
[fw-pyproject]: https://github.com/RiskThinking/crc-framework-rs/blob/838c295e4d078f98870819d8eb1004bb4f0611ec/pyproject.toml
[docs]: https://github.com/RiskThinking/crc-docs/tree/7691f5f1631941ebcb34a6a2278101a07739097a
[docs-readme]: https://github.com/RiskThinking/crc-docs/blob/7691f5f1631941ebcb34a6a2278101a07739097a/README.md
[docs-tests]: https://github.com/RiskThinking/crc-docs/blob/7691f5f1631941ebcb34a6a2278101a07739097a/tests/test_notebooks.py

## Amendment 1 (2026-11-06, MAR-275): D11, curves first

On 2026-11-06 the owner, Marc Prinzing, decided D11 (in chat; recorded on the Program hub, on MAR-249 and on MAR-271). It sets the order in which the module is released, and it builds `PortfolioEvaluation.asset_curves()` in the fork without waiting for RiskThinking's answer to Q1. Unlike errata 1 to 7, which correct the text, this amendment records a decision. The rest of the ADR stands: the two layers, the names, the payout families, the semantics rules, the design, the metrics, the provenance and the parity contract are unchanged.

- **Curves first (§2, §4.2).** The first release leads with CRC's fitted hazard curves: Monte Carlo of simulated years from each asset's curve (`sample_curve`), through the entry point `ParametricPlan.for_evaluation(request)` and the plan's `.monte_carlo(...)`.
  - Per-year series (ERA5, CMIP6 and NEX-GDDP-CMIP6, stations), through `ParametricPlan.for_annual_extremes(...)` and `sample_annual`, are the second step, in a later release (R-25, MAR-274). Their code is already on the fork's `parametric` branch (MAR-43, MAR-42). Whether the Phase 1 upstream PR holds them back or carries them as a secondary route is decided at upstream time (MAR-249).
  - The reasons, as the orchestrator gave them to the owner. Curves are CRC's core product and cover every hazard CRC publishes, including those it publishes only as curves, such as cyclone and flood. Per-year series give the real dependence between index and loss (spatial basis risk, the `index=` series of §4.2), but they cover fewer hazards, and their records are short in the tail.
  - The rules of §4.2 apply unchanged. A curve whose `probability_semantics` is unspecified is refused unless the caller states `assume_semantics=`. The cyclone and flood layers declare none, so Q6 matters more under curves first.
  - Both entry points and all three sources of §4.2 stay in the design. Only the order of release changes.
- **`asset_curves()` is built in the fork now (§2, §11 Q1).** The one additive public method that §2 recommended, `PortfolioEvaluation.asset_curves() -> pyarrow.Table`, is built in the fork by MAR-271 (R-18b), as §2 describes it: in crc-sdk's `workflows/portfolio.py` and `workflows/_portfolio.py`, on the existing join. Nothing else in `workflows/` changes, and no existing behaviour changes.
  - RiskThinking's answer to Q1 is no longer awaited. The upstream PR flags the method to them as a proposal, which they can rename, move or replace. §11 keeps Q1, now as that proposal.
  - Q2, a chaining method on `PortfolioEvaluation`, stays open.
  - So "if RiskThinking agrees" in §2's module layout, in §10's row for R-18 and in "Consequences", and "asking RiskThinking for" in D10's point 10, now read: built in the fork, and proposed upstream.
  - "Not verified" lists that the existing join can serve `asset_curves()` without a change in behaviour. MAR-271's tests check it.
- **The issue map (§10).** R-18 is split in two, and R-25 is added. The other rows stand, except that the notebook (MAR-46, R-19) now starts after MAR-271, because it shows the curve route.

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| MAR-42 (R-18) | `ParametricPlan`, `explain()`, `write_parquet`, the entry point `for_annual_extremes(...)`, `docs/parametric.md`, the README line and the end-to-end offline test. Done (marc272/crc-sdk#8) | `plan` | R-16 |
| MAR-271 (R-18b) | `PortfolioEvaluation.asset_curves()`, the entry point `for_evaluation(request)`, `.monte_carlo(...)` and `FreshDraws(...)` in the plan; `docs/parametric.md` leads with the curve route | `plan`; `workflows/portfolio.py` and `workflows/_portfolio.py` (one additive method) | MAR-42. No longer Q1 |
| MAR-274 (R-25) | The per-year route as the second step (ERA5, CMIP6 and NEX-GDDP-CMIP6, stations): its upstream packaging, a stated option for climate trends, pooled model-years, and its docs and notebook section. Scope and acceptance are set when it is refined | Set when it is refined | MAR-271 |

## Amendment 2 (2026-11-08, MAR-291): the per-year route

On 2026-11-08 the owner, Marc Prinzing, decided D-25.1 to D-25.5 (in chat; recorded on MAR-274 and MAR-291). They fix the public API of the per-year route (R-25, MAR-274), so this amendment comes before the issues that build on it (MAR-295, MAR-296 and MAR-297), and the owner approves it before it merges. Amendment 3 (MAR-292) is recorded separately; "With Amendment 3" below says where the two meet.

The rest of the ADR stands. §2, §4.1, §4.2, §4.4, §4.5, §7 and §10 keep their text and each carries a one-sentence pointer here, and this amendment says what they now mean, as Amendment 1 did. Every addition has a default, so a call or a plan written before this amendment gives the same rows. The publication rule applies: this amendment presents the options and what each one records, and nothing here says that a trend option, pooled model-years or an index read elsewhere changes how a cover does.

### The five decisions

All five are option (A) of the refinement on MAR-274.

| | Decision |
|---|---|
| D-25.1 | The per-year route goes in the Phase 1 upstream PR as the secondary, documented route |
| D-25.2 | Default `AsRecorded()`, always named in the setup text, with options `RecentYears(n)` and `LinearTrend(reference_year=None)`, an additive OLS fit on the year. Under a split, the trend is fitted on the design years only |
| D-25.3 | Pool model-years per asset, rows in (year, model, member) order, `period` as a draw number, each row's identity recorded. Holdout and k-fold hold out the latest years of every model. One pathway per pool |
| D-25.4 | A plan builder `.index(source, *, location=StationColumn(...) \| NearestCell(...), unit, provenance)`, binding each asset's covers to the resolved `AtStation` or `AtPoint` |
| D-25.5 | `scenario=` on `sample_annual` and `for_annual_extremes`, default `"baseline"` |

### The route in the upstream PR (D-25.1)

Amendment 1 left open whether the Phase 1 upstream PR holds the per-year route back or carries it as a secondary route. D-25.1 settles it: the PR carries the route as it stood when that PR was opened (`sample_annual`, `for_annual_extremes`, `NearestCell` and `StationColumn`), as the secondary, documented route, so "in a later release" in Amendment 1 no longer describes that route. This amendment's additions (`trend=`, `pool=`, `.index(...)`, `scenario=` and `cell=`) are not in that PR: they land on the fork's `parametric` afterwards, and reach upstream as MAR-249 decides later. The curves still lead `docs/parametric.md`, its quick start and the notebook, and §11 keeps Q3.

### Climate trends (D-25.2, §4.2)

```text
# trend (R-25b); numpy only; frozen, each with to_document()
AsRecorded()
RecentYears(n)
LinearTrend(reference_year=None, *, min_years=10, fit_years=None)
```

`trend=` takes one of the three, on `sample_annual`, `sample_annual_pool` and `for_annual_extremes`. The default is `AsRecorded()`.

- **`AsRecorded()`** uses the years as they are. This is what the route does today.
- **`RecentYears(n)`** keeps the last n years of the series: the last n entries of its years, after `years=` and before `missing=`. A gap before the window doesn't matter, and a gap inside it is a missing year. An n above the series' length raises `SampleError`. No value changes.
- **`LinearTrend`** removes an additive linear trend in the mean. On the fit years it fits x_t = a + b·(t − t₀) + e_t by ordinary least squares, with t the calendar year and t₀ the reference year, and replaces every year's value by x_t − b·(t − t₀). So a, the recorded intercept, is the fitted value at the reference year, and the adjusted fit years have mean a. The spread around the line isn't touched, so a change in the variance or the tail stays in the data.
  - **The reference year.** `reference_year=None` means the last year of the series: the last entry of its years, whether or not it has a value and whichever block it falls in, so it is the same in every fold. A stated year may lie outside the record.

    | Option | Assessment |
    |---|---|
    | **The last year of the series** (recommended) | Every fold's rows are at one level, the climate a threshold stated today is read against. Only the calendar of the held-out years enters, never their values. The design years' line is extrapolated over the held-out years, which the setup text shows through the fit years and the reference year |
    | The last design year | Stays inside the fit, but the level changes from fold to fold and differs from the plan without a split, so a fixed threshold is read against another climate in each fold |
    | The mean of the fit years | The level is that of the middle of the record, not the climate a threshold stated today refers to |

  - **One fit per series.** Each asset's hazard series has its own fit. A separate index series has its own, on the same years with the same reference year, and so does each run of a pool.
  - **Too few years.** Fewer than `min_years` fit years raise `SampleError`, naming the fold and the count; no fold is dropped. The default of 10 is a floor against a slope that is nearly all noise, not a statement that ten years are enough. `min_years` below 3, which would leave no residual, raises at construction.
  - **No clipping.** A non-finite value, or a value that was non-negative as recorded and is negative after the adjustment, raises `SampleError`. A value that is negative as recorded (a temperature) may stay negative.
- **The order.** `years=`; the window of `RecentYears`; `missing=`; the fit and the adjustment of the hazard and of the index; the impact on the adjusted hazard; the basis-risk model. A trend draws no random numbers, so §4.4's draw order stands. The sample's `index` and `hazard` hold the adjusted values, and `source_kind` stays `"annual"`.

**Under a split (D-25.2).**

- **The fit sees the design years only.** The held-out years are adjusted with the design years' slope. A changed held-out value changes neither the fit nor any row of the design block.
- **The plan builds one sample per fold.** With `LinearTrend` and `Holdout` or `KFold`, the plan builds each asset's sample once per fold, with that fold's design years as the fit years, and takes the fold's two blocks from it. The fit years are the years `holdout` or `year_block_kfold` puts in the design block, so the two can't disagree. A model that draws (`ImpactNoise`) starts every fold from the asset's same generator state, so a year's factor doesn't depend on the fold.
- **`.samples()` and `ParametricResult.samples`** hold all the years before any split, so their fit uses all the years, and their record says so. The comparison's rows come from the per-fold samples.
- **Layer 1.** `LinearTrend(fit_years=years)` states the fit years; by default they are every kept year. A year the series doesn't hold raises `SampleError`. A year dropped as missing is left out, so the record lists the years actually used. On the plan, `fit_years` raises `ValueError`, because the plan sets it per fold.
- **Leakage.** An out-of-sample `evaluate` or `compare` raises `LeakageError` when the trend of the design sample or of the evaluation sample was fitted on a year the evaluation sample holds from the same source. So `holdout(sample_annual(..., trend=LinearTrend()))` is refused at evaluation, and the error names `fit_years`. The lineage (§4.4) leaves the trend out: a design on adjusted years, evaluated on the same years as recorded, still shares their rows.
- **`RecentYears(n)`.** The window comes first and the split divides it, so the held-out block is the latest years inside the window. Nothing is fitted, so nothing is rebuilt per fold.

**The record.** `SampleProvenance` gains `trend`, with a default; it is `None` on Monte Carlo and table samples.

```text
{"kind": "as_recorded"}
{"kind": "recent_years", "n": n, "years": [first, last]}
{"kind": "linear_trend", "method": "ols_additive", "reference_year": t0, "min_years": 10,
 "fit_years": [...], "fits": [{"role": "hazard", "slope": b, "intercept": a}, ...]}     # one entry per series
```

`setup_text` writes one sentence for it on every per-year sample, the default included: which option, and for `LinearTrend` the fit years, the slope with its unit, the intercept and the reference year. Which option suits a hazard is the user's choice, and the module says nothing about it.

### Pooled model-years (D-25.3, §4.1, §4.2)

```text
# pooled model-years (R-25c)
ModelRun(series, *, model, member, pathway)      # one run's AnnualSeries at one location
sample_annual_pool(runs, *, loss_model, basis_risk, asset_id, rng=None, missing="raise",
                   trend=AsRecorded(), scenario="baseline") -> OutcomeSample
ModelPool(model="model", member="member", pathway="scenario")     # the plan's pool=, naming the table's columns
```

- **The rows.** One sample per asset. Every model-year is one row, in (year, model, member) order, with models and members in UTF-8 byte order. `period` is the draw number, 0 to N − 1, and each row has probability 1/N, so 3 models × n years give 3n rows at 1/(3n) each. `source_kind` stays `"annual"`, and §4.1's rule that `period` strictly increases holds.
- **Each row's identity.** `SampleProvenance` gains `pool`, with a default; it is `None` on every other sample. `runs` has one document per run (model, member, pathway, the run's lineage and its series' provenance), and `year` and `run` have one entry per row. `select`, `holdout` and `year_block_kfold` carry the identity of the rows they keep.
- **Refusals** (`SampleError`): runs under different pathways (`historical` is one, so a pool can't span NEX-GDDP-CMIP6's historical and SSP experiments); different units; different recipes, where the runs state one; the same model twice, whatever the member, so every model has the same weight; fewer than two runs; and runs that don't cover the same years. `AnnualSeries` keeps its rule of one row per year, so a table with several models at one location still raises unless the plan states `pool=`.
- **The same years.** After `years=`, the window and `missing=`, every run must hold the same years. With `missing="drop_year"`, a year without a value in any run is dropped from every run and listed with the run that lacked it.

  | Option, when models cover different years | What it does | Assessment |
  |---|---|---|
  | **The same years for every run** (recommended) | Otherwise `SampleError` lists each run's years | "The latest years" is one calendar block for every model, every run weighs the same at 1/N per row, and a stated `years=` resolves it. A short run narrows the window for all |
  | Each run's own latest share | Each run holds out the latest share of its own years | Every model has a held-out block, but the blocks are different calendar years, so one run's design block can reach past another's held-out block. A longer run weighs more |
  | One calendar cut | The latest share of the pool's distinct years is held out | One block for all, but a run that ends early has nothing held out, so it isn't "every model". A longer run weighs more |

- **Splits.** `holdout` and `year_block_kfold` work on a pool's distinct years, not on its rows. `holdout` puts the first ⌊train_fraction · n + 1e-9⌋ of the n years in the design block, and `year_block_kfold` splits the n years with `array_split`, so k is at most n. Cutting rows could cut through a year: of 3 models × 30 years from 2015, a fraction of 0.75 gives 67 rows, which puts 2037 in the design block for one model and in the held-out block for the others. Every run has the same held-out years: the latest ones under `Holdout`, and one block per fold under `KFold`, the last fold holding out the latest.
- **Leakage.** On a pool, §4.4's leakage check compares (run lineage, year) pairs instead of periods, and a plain per-year sample counts as one run. So a model-year can't be on both sides, between pools of different runs or between a pool and one of its runs.
- **`FreshDraws`** raises `TypeError`, as on every per-year plan: a pool's rows are model-years, not draws from a curve.
- **Trend.** Each run has its own fit, on the same design years with the same reference year, the last of the pool's years. `RecentYears(n)` takes the last n years of each run.
- **Basis risk.** `NoBasisRisk()` warns with `ComonotoneIndexWarning`, as for one series: pooling puts no difference between index and loss. `ImpactNoise` draws one factor per row, in row order, from the asset's generator.
- **What the setup text says.** The runs, the pathway, the years, the number of rows and that every run has the same weight, and two statements. A draw mixes model spread with year-to-year variability, as §4.2 says of a pooled curve. And the rows are not independent years: rows of one run share that model's climate and rows of one year the pathway's forcing, so the number of rows is not an effective sample size.
- **The plan.** `for_annual_extremes(..., pool=ModelPool())` pools. `source` is then one table, file or plan whose rows carry the three columns `ModelPool` names, as NEX-GDDP-CMIP6's batches do, or a sequence of sources, one per run, as CMIP6's plans are (one model each).
  - A run's identity comes from those columns or, where a source has none, from its plan's `explain(format="json")` (`model`, `member`, `pathway`). A source that states neither raises `SampleError`.
  - Each run is located on its own grid, so the matched cell and the grid step are recorded per run (erratum 12, 2026-11-08, MAR-288, in §4.2: this first read "so the matched cell and the distance are recorded per run"). `provenance` states the archive's licence and attribution once; each run's own columns are recorded with it.
  - `years=`, `missing=` and `trend=` apply to every run. `.samples()` returns one pooled sample per asset.

### An index read elsewhere (D-25.4, §2, §4.4)

```text
    .index(source, *, location, unit, provenance, point=None, year_column="year", index_column="value")     # R-25d
```

- **What it does.** The cover pays on a series read from `source` at `location`; the loss still reads the hazard of `for_annual_extremes`. `source` takes the kinds `for_annual_extremes` takes. `location` is required: `StationColumn(name)`, or `NearestCell(...)`, which reads the index source's grid. Each asset's sample equals `sample_annual(hazard, index=series, ...)` built by hand. `unit` is the index series' unit; it isn't checked against the impact, because the loss doesn't read it (§4.2).
- **Where `NearestCell` reads.** At the asset's own location by default, which suits an index from another product or grid. `point=PointColumns(longitude, latitude)` names asset columns holding another point, for a reference site or a neighbouring cell. Only the matched cell is recorded, as for the hazard. With `StationColumn`, `point=` raises `ValueError`.
- **Refusals** (`ValueError`, at the builder): on a plan on curves, because §4.4's index at a reference point needs a joint distribution of two curves; and with `pool=`. An observed station and a free-running model share no weather: year t of a model is not year t of the station, so pairing them by year would invent a dependence. An index from the same run at another cell has a meaning, and is a later, additive option.
- **The years.** The index is read on exactly the hazard's years. A hazard year the index lacks or holds as null (a station's incomplete year) is a missing year, under the plan's one `missing=`, as in `sample_annual`: `"raise"` raises and lists it, and `"drop_year"` drops the year from the sample and lists it in `dropped_years`. An index year the hazard doesn't have is not used, and the record lists it. So gaps in a station need no second argument.
- **Binding the covers.** A cover stated with `AtAsset()` is bound at execution to each asset's resolved location, as the plan already binds it to the asset:
  - `StationColumn` gives `AtStation(<the asset's station id>)`;
  - `NearestCell` gives `AtPoint(<the cell centre>)`, its longitude wrapped to [−180, 180], because `AtPoint` takes that range and some grids run from 0 to 360. The asset's own point stays out of the document.
  - The location is in the cover's document, so it is in `definition_hash`, `cover_hash` and `design_id`. A cover that already names a location must name that one, or the plan raises `SampleError`.
- **Without `.index(...)`** the refusal of `.covers` for a location other than `AtAsset()` stays.
- **Units and order.** `.covers` checks a cover's index unit against `.index`'s `unit`, not the hazard's, so `.index(...)` comes first when the two differ or a cover already names a location. `.index(...)` after `.covers(...)` checks the covers again and raises on a mismatch.
- **Basis risk.** `.basis_risk(model)` stays required (§4.4). `NoBasisRisk()` with a separate index series doesn't warn, as in `sample_annual`, and `ImpactNoise` may be added on top.
- **`explain()`** shows the covers as stated and the location rule; the bound documents are in the written metadata.

### The scenario label (D-25.5, §4.5)

`scenario="baseline"` on `sample_annual`, `sample_annual_pool` and `for_annual_extremes` sets `OutcomeSample.scenario`, so it reaches `to_table`, `content_hash` and the comparison's `scenario` column. It is the user's name for the rows and is not derived from the source. The `scenario` column of a CMIP6 table is the pathway, another thing, and the setup text states both. So a pool under `ssp245` with no label stated is labelled `"baseline"`, and its setup text names the pathway; `docs/parametric.md` and the notebook state a label whenever they use a pathway. The lineage leaves the label out, so §4.4's leakage check sees through a relabelling.

### A per-asset H3 cell (§2, R-25e)

`cell=` on `for_annual_extremes`, as MAR-294 merged it (marc272/crc-sdk#18), puts an H3 cell for each asset in the impact's context, on top of `context`: `cell="<column>"` names an asset column of unsigned 64-bit H3 cells, and `cell=H3Cell(resolution=r)` takes the cell of the asset's point, computed at execution with `crc_sdk.geometry.h3.point_to_cell`. `H3Cell` needs the `geometry` extra, and without it execution raises an `ImportError` naming `crc-sdk[geometry]`. It needs a point too, so for assets located by `CellColumn` it raises `SampleError`. `r` runs from 0 to 15 and has no default: which resolution the registry impacts expect is open point 7 on the upstream PR. `cell=` for an impact that takes no context raises `SampleError`, and `cell=` where the impact's context already holds a cell raises `ValueError`. Each sample's provenance and the setup text record the cell, not the point, and `explain()` states under `assets` what `cell=` says. It changes only the impact's context: the series is still located by `location`. Without `cell=`, the refusal of `for_annual_extremes` for a registry impact that needs a cell stays.

### The outlines (§2)

One outline for the route, as R-25b to R-25e build it. Other builders stand.

```text
# Layer 1, per-year samples
AsRecorded() | RecentYears(n) | LinearTrend(reference_year=None, *, min_years=10, fit_years=None)
sample_annual(hazard, *, loss_model, basis_risk, asset_id, index=None, rng=None, missing="raise",
              trend=AsRecorded(), scenario="baseline") -> OutcomeSample
ModelRun(series, *, model, member, pathway)
sample_annual_pool(runs, *, loss_model, basis_risk, asset_id, rng=None, missing="raise",
                   trend=AsRecorded(), scenario="baseline") -> OutcomeSample

# Layer 2, the per-year entry
ParametricPlan.for_annual_extremes(source, assets, *, impact, unit, provenance,
                                   value_column=None, value_unit="1", context=None,
                                   location=NearestCell(), year_column="year",
                                   hazard_column="value", years=None, missing="raise", seed=None,
                                   trend=AsRecorded(), scenario="baseline", pool=None, cell=None)
    # source: as in §2; with pool=, also a sequence of them, one per run
    # pool: None or ModelPool(model="model", member="member", pathway="scenario")
    # cell: None, the name of an asset column holding an H3 cell, or H3Cell(resolution=r)
    .index(source, *, location, unit, provenance, point=None, year_column="year", index_column="value")
    # location: StationColumn(name) or NearestCell(...); per-year plans only; not with pool=
```

| Together | Rule |
|---|---|
| `trend=` and `.index(...)` | Both series are adjusted, each with its own fit, on the same years with the same reference year |
| `trend=` and `pool=` | One fit per run |
| `years=` and `RecentYears(n)` | `years=` first; the window takes the last n of them |
| `pool=` and `.index(...)` | `ValueError` |
| `pool=` and `StationColumn` | `ValueError`: models have no stations |
| `cell=` and `pool=` | Allowed: the cell belongs to the asset, not to a run |
| `FreshDraws` on a per-year plan | `TypeError`, as today |

### The per-year source records (§7)

§7 says of per-year values: "the source plan's `explain()` output and the matched cell or station". As MAR-293 merged it (marc272/crc-sdk#17):

- **A series' `provenance`** holds its `source`, its `columns`, the `where` filter or the matched `cell` with `spacing_degrees`, and `table_columns`: for each of the table's provenance columns (such as `model`, `member`, `scenario`, `recipe`, `source_url`, `archive_licence` and `attribution`), its distinct values, at most 20, and their count. (Erratum 12, 2026-11-08, MAR-288, in §4.2: "the matched `cell` with `spacing_degrees`" first read "the matched `cell` with `distance_km` and `spacing_degrees`", as MAR-293 merged it.)
- **`source=`** on `AnnualSeries.from_table` and `nearest_cell` takes a name, a `SourceProvenance`, a mapping or the source plan itself. Of a plan only `explain(format="json")` is called, so no data is fetched.
- **Provider and dataset.** ERA5 and CMIP6 documents state what was asked for, not who holds it, so they get derived names: for ERA5, provider `era5` and dataset `<store> <recipe>`; for CMIP6, provider `cmip6` and dataset `<model> <member> <recipe>`. The document's own names win.
- **Pathway.** `setup_text` reads a series' pathway from its source's `pathway` key, or from a one-valued `scenario` column when the table also has `model` and `member` columns. A `scenario` column alone states no pathway.
- **On the plan**, a series' `source` is the caller's `SourceProvenance`, with the source plan's type or the file's SHA-256. `source_records` holds `{"annual_table": ...}`: the rows, the columns, the table's SHA-256, the source plan's `explain()` and, for a file, its path and SHA-256. Each hazard entry of `sources` names it by `annual_table_sha256`.

MAR-307 (marc272/crc-sdk#19) then changed two records. On the plan route, a pathway the source plan states is recorded on the series, beside the caller's `SourceProvenance`, and `setup_text` reads it there. A source plan's cache state and run details are left out of a series' lineage, as are a table's `retrieved_at` column and how the series found its rows, so one source links across fetches and windows; a `source` of the caller's own is kept whole.

This amendment adds:

- **`setup.samples`.** Each entry gains `trend` and `pool`. `pool` holds the runs and their years, without the row arrays: the rows follow from them, by the order of D-25.3, and the full arrays are in the sample's own metadata (`crc.parametric.sample`). A document without these keys reads as before: as recorded on a per-year sample, no pool, and `schema_version` stays `"1.0"`. `explain()` gives the trend option, the pool's columns and the scenario before anything is read.
- **The index series.** `sources` has an entry with role `"index"`, `source_records` an `{"index_table": ...}` record of the same form, named by `index_table_sha256`, and `licences` the index source's licence and attribution.
- **A pool.** `sources` has one hazard entry per run, and a sequence of sources has one `annual_table` record each.
- **`covers`** holds the bound documents.

MAR-307 settled the lineage's independence of cache state, ERA5's licence and attribution (crc-sdk's `ERA5_LICENCE` and `ERA5_ATTRIBUTION`, where the document states none), CMIP6's pathway on the plan route, NOAA's `explain()` (called without `format` where a plan takes none) and the docs line. MAR-308 then removed `distance_km` from a nearest-cell series, in marc272/crc-sdk#20; it was already out of the lineage. (Erratum 12, 2026-11-08, MAR-288, in §4.2: the sentence before this note first read "`distance_km` stays recorded, out of the lineage; whether to drop it is a question for the owner on MAR-308.")

### With Amendment 3

Amendment 3 lifts the one-asset rule and adds `join`, `scope`, `.dependence` and more `level` values. The two fit as follows.

- **`join`.** A multi-asset per-year sample is `OutcomeSample.join` of one-asset samples built as above, under its checks. It gains two:
  - the parts must share the trend's kind, its reference year and its fit years, so the total sums years on one basis. The slopes differ per asset, and `parts` holds them;
  - pools must hold the same (year, model, member) rows. Draw numbers alone would not line them up, the reason Amendment 3 gives for refusing Monte Carlo samples. `dependence` stays `{"kind": "data"}`: the rows are the same model-years.
- **Different windows** (`missing="drop_year"`, stations with different records) raise through `join`'s check of identical periods. One stated `years=` resolves it.
- **`Joint()`.** It works with `trend=`, `pool=` and `.index(...)`. With `LinearTrend` and a split the plan joins per fold, and `.joint_sample()` is all-years, like `.samples()`. Each asset keeps its own cover on its own bound index, as Amendment 3 has it.
- **`.dependence(...)`** still raises on every per-year plan, pooled or not, with or without `.index(...)`. The dependence stays the data's own, after the stated adjustment, and the setup text states both.
- **`level` and `scope`.** This amendment adds no value to either. A pool is one asset's sample, so it gets `"asset"` rows and, under `Joint()`, a `"total"` row.
- **`OutcomeSample.asset()`** returns the part's own `trend` and `pool`. `holdout` and `year_block_kfold` split a multi-asset pool by its years.
- **`EmpiricalCopula(reference)`.** A reference may be adjusted or pooled: only its ranks are used, `source_kind` stays `"annual"`, and m is its number of rows. Its record's first and last year come from `pool`.
- **The setup text.** The trend and pooling sentences come next to Amendment 3's levels, allocation and dependence, and `setup.samples` holds `trend`, `pool` and `dependence` side by side.

### What the other sections now mean

- **§2.** The outlines gain the entries above. The module layout gains `trend.py` (R-25b: `AsRecorded`, `RecentYears`, `LinearTrend`). `sources.py` gains `ModelRun` and `sample_annual_pool`, and `plan.py` `ModelPool` and `H3Cell`.
- **§4.1.** `period` is a draw number on a pool too. `SampleProvenance` gains `trend` and `pool`.
- **§4.2.** "A trend is not removed" now reads: by default; `trend=` states otherwise. "The years of both series must match" stays for `sample_annual`; the plan reads the index on the hazard's years.
- **§4.4.** The row "a second `AnnualSeries` as `index=`" reaches the plan through `.index(...)`. The row for `NoBasisRisk()` holds for a pool.
- **§4.5.** A per-year sample may name its label. §9's `ScenarioSet` doesn't change.
- **§7.** `setup`'s per-sample list gains the trend and the pool, and `sources` the records above.
- **Amendment 1.** As in "The route in the upstream PR".

### The issue map (§10)

R-25 is split as below (each about one PR). The other rows stand. In the owner's order, R-25a and R-25e run alongside the portfolio work, R-25b, R-25d and R-25c follow this amendment, and R-25f comes last. Each issue updates the per-year section of `docs/parametric.md` for what it adds.

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| MAR-293 (R-25a) | Per-year sources name their provider, dataset and pathway. Done (marc272/crc-sdk#17) | `sources`, `metadata` | No blocker |
| MAR-295 (R-25b) | `AsRecorded`, `RecentYears`, `LinearTrend`; `trend=`, fitted per fold; the leakage check; `SampleProvenance.trend`; the trend sentence. Also `scenario=` (D-25.5), which has no issue of its own and touches the same two signatures | `trend` (new), `sources`, `sample`, `plan`, `metadata` | This amendment, R-25a |
| MAR-297 (R-25d) | `.index(...)`: the index series, the binding of the covers, the years and `missing=`, its records | `plan`, `metadata` | This amendment |
| MAR-296 (R-25c) | `ModelRun`, `sample_annual_pool`, `ModelPool`, `pool=`; splits and leakage on a pool; `SampleProvenance.pool` | `sources`, `sample`, `plan`, `metadata` | This amendment, R-25a; in the owner's order after R-25b and R-25d, whose `trend=` and `.index(...)` it extends |
| MAR-294 (R-25e) | `cell=`, `H3Cell`; the cell in the loss model's document; the existing refusal without a cell. Done (marc272/crc-sdk#18) | `plan` | R-25a |
| MAR-300 (R-25f) | Notebook material in crc-docs: ERA5 annual extremes at the illustrative site, with the trend option and an out-of-sample split, every number out of sample next to `setup_text`, and no claim that a trend option, a station index or pooling changes how covers do | crc-docs fork | R-25b, R-25d, the primer notebook (MAR-299) |
| MAR-307 (R-25g) | Source-plan follow-ups: a lineage independent of cache state, ERA5's licence and attribution, CMIP6's pathway on the plan route, NOAA's `explain()`, the docs line. Done (marc272/crc-sdk#19) | `sources`, `plan`, `metadata` | R-25e |

`join` comes with Amendment 3 (MAR-298, R-21a). Its check of the trend lands with the later of MAR-298 and MAR-295, and its check of a pool's rows with the later of MAR-298 and MAR-296.

### Beyond the five decisions

The five decisions don't determine these. The text above settles each as the agent recommends, and the owner's approval of this amendment covers them.

1. `LinearTrend`'s default reference year is the last year of the series, the same in every fold. The table above has the options.
2. A fold with too few fit years raises `SampleError`, under a new keyword `min_years=10`, which may not go below 3.
3. One fit per series: per asset, per run, and for the hazard and the index separately.
4. `fit_years` is a field of `LinearTrend`, so a Layer 1 caller can fit on design years with one argument, and `LeakageError` guards the fit at evaluation.
5. `.samples()` under `LinearTrend` and a split gives the all-years fit; the rows come from per-fold samples, and every fold starts from the same generator state.
6. `RecentYears(n)` is the last n calendar years of the series, before `missing=`, and the window comes before the split.
7. A pool requires the same years for every run, and `drop_year` drops a year from all of them. The table above has the options.
8. A model appears once in a pool, whatever its member, as MAR-296 asks. Several members of one model would be a later, additive option with a stated weighting.
9. A pool's splits cut years, not rows, and its leakage check compares (run lineage, year).
10. The names: `ModelRun`, `sample_annual_pool`, `ModelPool`, `pool=` and a sequence of sources.
11. `.index(...)` and `index=` are refused on a pool.
12. `.index(...)` reads the index on the hazard's years, with the plan's one `missing=`.
13. `point=` on `.index(...)` lets `NearestCell` read at a point other than the asset, which MAR-274's "another cell as the trigger" needs. `year_column` and `index_column` name the index table's columns.
14. Covers are bound to the cell centre as `AtPoint`, its longitude wrapped; a cover already bound must match; and `.index(...)` comes before `.covers(...)` when the units differ.
15. `ComonotoneIndexWarning` follows `NoBasisRisk()` on a pool as on one series, and the setup text states the two things a pool's rows are not.
16. `join` also compares the trend's kind, reference year and fit years, and a pool's rows.
17. `H3Cell` has no default resolution.
18. `scenario=` (D-25.5) goes with MAR-295 in §10.

### Not verified

- No code for R-25b, R-25c or R-25d exists. A throwaway check (2026-11-08, not committed; script and output in the PR) ran the arithmetic of the rules on synthetic numbers with numpy only, without the fork or any CRC data:
  - x_t = 50 + 0.5(t − 1981) gives an adjusted range of 0.0, on all years and on a 70 % design block;
  - adding 500 to every held-out value changes the slope, the intercept and every design row by 0.0;
  - the adjusted fit years have mean a, within 1.5e-14;
  - 3 models × 30 years give 90 rows at 1/90; a fraction of 0.75 gives 22 design years and 66 rows with no year on both sides, while a cut of rows puts 2037 on both sides; every run has the same years held out in each of 4 folds.
- No CMIP6 or NEX-GDDP-CMIP6 table was read, only their code. How often models differ in their years at one location, which decides how often the same-years rule raises, is not known here. Nor are the longitude ranges of the CMIP6 grids.
- The cost of per-fold sample building, and of the row identity on a large pool, was not measured.
- No ERA5, station or CRC Open data was read for this amendment.

## Amendment 3 (2026-11-08, MAR-292): the portfolio approach

On 2026-11-08 the owner, Marc Prinzing, decided D-21.1 to D-21.6 (in chat; recorded on MAR-45 and MAR-292). They shape the public API of the portfolio approach (R-21, MAR-45), Phase 2's first extension, so this amendment comes before any R-21 issue starts, and the owner approves it before it merges. Amendment 2 (MAR-291) is recorded separately.

The rest of the ADR stands. §4.1, §6, §9 and §10 keep their text and each carries a one-sentence pointer here, and this amendment says what they now mean, as Amendment 1 did. The publication rule applies: joint calibration is described as a method only, and nothing here says how a joint design does against designs made asset by asset, in either direction.

### The six decisions

All six are option (A) of the refinement on MAR-45.

| | Decision |
|---|---|
| D-21.1 | Dependence between the assets of a curve sample: `Independent()`, `Comonotonic()` and `EmpiricalCopula(reference)`, always stated and never defaulted. `EmpiricalCopula` reorders the curve draws to the ranks of a stated per-year reference. Numpy only. `GaussianCopula` comes later |
| D-21.2 | Individual and joint scopes now, clusters as a later issue |
| D-21.3 | Every multi-asset evaluation gets an owner-total row (`level="total"`, plus a `scope` column). Per-asset rows of joint designs exist only under a stated evaluation-time `allocation`, `"value"` or `"loss"` (default none), in `asset_by_value` and `asset_by_loss` rows with no premium or net-loss columns. So `allocation` moves off `design_joint`, a change to §9 |
| D-21.4 | Show the joint design with its own rows and explain what it optimises. No table or figure sets individual against joint until the owner revisits the RQ2 rule (MAR-152 item 4) |
| D-21.5 | The illustrative book: a synthetic book of 5–10 stated sites in one region, with stated values (CC0), on ERA5 annual extremes. Optionally the same sites on CRC Open curves with an `EmpiricalCopula` from those ERA5 years |
| D-21.6 | Fixed thresholds only in joint designs; free shapes raise `DesignError`. Users compare threshold choices by running the design several times. All 16 joint parity cases use fixed thresholds |

### Several assets in one sample (§4.1)

The one-asset rule of §4.1 is lifted. "`asset_ids`: Phase 1: exactly one" and the bullet "One asset per sample in Phase 1" now read: a sample holds one asset or more, with distinct ids. The arrays stay (n, n_assets). `to_table`, `content_hash`, `select`, `holdout` and `year_block_kfold` work on every asset at once, `from_table` reads several assets, and a one-asset sample and its hash don't change.

- **Provenance.** `SampleProvenance` gains `dependence` and `parts`, both with defaults and both null on a one-asset sample. `parts` holds each asset's own provenance document, by asset id. `dependence` says where the dependence between the assets comes from: `{"kind": "data"}`, written "the data's own", or the document of a model of `sample_curves` (below).
- **`OutcomeSample.asset(asset_id) -> OutcomeSample`** returns that asset's one-asset sample, with the same periods and probabilities and the asset's own provenance from `parts`. It keeps the lineage (of a joined sample, the part's), so §4.4's leakage check still sees the source, and `selection` records the step.
- **`OutcomeSample.join(samples) -> OutcomeSample`** puts one-asset samples side by side.
  - It requires distinct asset ids and identical periods, probabilities, units, semantics and scenario, and raises `SampleError` otherwise. A part without a separate `hazard` contributes its index when another part has one.
  - It records `{"kind": "data"}`: the rows are the same years of the data. A multi-asset `from_table` records the same, because a table's rows are what the caller states (§4.2).
  - **It refuses Monte Carlo samples** (`source_kind` `"monte_carlo"`). Independently drawn curve samples line up by draw number only, so joining them would impose independence without stating it. The `SampleError` names `sample_curves`.
  - Its lineage is new, built from the parts' lineages.
- **`design` stays per asset.** On a multi-asset sample it raises `SampleError`, naming `asset()` and `design_joint`. `evaluate` and `compare` raise the same way until MAR-303 extends them (below).

The plan's default, one sample per asset under `Individual()`, doesn't change: it computes no cross-asset sum and imposes no dependence.

### Dependence between the assets of a curve sample (D-21.1, §9)

```text
# dependence (R-21d); numpy only
Independent() | Comonotonic() | EmpiricalCopula(reference)     # frozen, with to_document()
sample_curves(curves, *, dependence, metadata, n_draws, rngs, loss_models, basis_risk,
              assume_semantics=None, outside_support="raise", details=None) -> OutcomeSample
    # curves, metadata, rngs, loss_models: mappings by asset id; the order of curves sets asset_ids
    # dependence: required, no default. basis_risk: one model for every asset
```

- **Every model only reorders.** For each asset, `sample_curves` makes exactly what `sample_curve` makes with that asset's generator: the uniforms first, then the basis-risk model (§4.4). The dependence model then puts that asset's rows in another order. A row's hazard, index and loss stay together, and no value changes. So each column holds the rows of `sample_curve` with the same uniforms, and an asset's sample has the same values under all three models. `period` is the draw number, 0 to n − 1.
- **`Independent()`** keeps every asset's rows in draw order. The assets are independent because each has its own generator.
- **`Comonotonic()`** keeps the first asset's rows in draw order and moves every other asset's draw of rank r to the row of the first asset's draw of rank r. Ranks are those of the uniforms, so a hurdle curve's atom adds no ties, and the rank correlation of the uniforms is 1.
- **`EmpiricalCopula(reference)`.** `reference` is a multi-asset `OutcomeSample` of m observed or modelled years (`source_kind` `"annual"` or `"table"`) with equal probabilities, holding exactly the curves' assets. A Monte Carlo sample raises `SampleError`: it has no dependence of its own to lend.
  - Ranks are read from the reference's `hazard`, or from its `index` when it has no separate hazard. Only the ranks are used, so the reference's unit may differ from the curve's. A larger reference value takes a larger draw; a reference that moves the other way must be negated by the caller.
  - **More draws than reference years.** This is the point D-21.1 left open, and the owner decides it by approving this amendment. The recommendation is rank blocks.
    - The rule: `n_draws` must be a whole multiple of the reference's years, `n_draws = k·m` with k ≥ 1. Any other count, fewer draws than years included, raises `SampleError` naming the two nearest valid counts. For each asset, the n draws are sorted by their uniforms and cut into m consecutive blocks of k. A reference year of rank r at that asset takes block r. Inside a block the draws keep the order in which they were drawn. The rows are in reference-year order: the first k rows are the first reference year, and so on.
    - What it means: the reference fixes, for each year, which block of its own draws each asset falls in. With k = 1 the sample's ranks are the reference's ranks exactly; with k > 1 the block of every row's draw equals the reference's rank of that row's year. Inside a block the reference says nothing, so the model assumes independence between the assets there: a block's draw order is random, and each asset's comes from its own generator. This is the checkerboard form of the empirical copula. The reordering uses no random numbers beyond `sample_curve`'s.
    - The limit, which the setup text states: dependence finer than one year in m is assumed, not observed.

    | Option | What it assumes | Assessment |
    |---|---|---|
    | **Rank blocks** (recommended) | Independence between assets inside one reference year's block | Keeps each asset's draws, adds no random numbers, holds the reference's ranks exactly at block level, and its assumption is one sentence in the setup text |
    | Refuse unless `n_draws` is m | Nothing beyond the data | A reference of m years caps the sample at m draws, so the curve's tail beyond the record, the reason to simulate, isn't sampled |
    | Resample the reference years at random | As rank blocks, plus random year counts | Needs more random numbers, gives some years more weight by chance, and holds the ranks only approximately |
    | Keep a block's draws sorted | Perfect dependence inside a block | Deterministic too, but asserts the strongest dependence where the reference has no information, which is what the top blocks hold |
    | A smoothed copula (empirical beta copula) | A stated smoothing around each year's ranks | Not a reordering of the draws, as D-21.1 asks, holds the ranks only approximately, and is harder to state |

  - **Ties.** Years with equal reference values at one asset (dry years, rounded values) share the blocks of their ranks. The blocks are pooled and dealt to the tied years' rows in draw order, k each, in year order, so a tie adds no dependence between assets.
  - **Record.** `dependence` holds the kind, the reference's `content_hash`, its sources, its first and last year, m and k. The setup text names the model and calls the dependence an assumption.
  - **Splits.** Fresh draws (`FreshDraws`) use the same reference with new uniforms, and their `n_draws` must be a multiple of m too. Because the rows come in reference-year blocks, `holdout` and `year_block_kfold` raise `SampleError` on an `EmpiricalCopula` sample, naming `FreshDraws`. The reference is part of the stated model, so the design and the fresh draws share it, and the setup text says so.
- **`GaussianCopula(correlation)`** comes later: it needs a vectorised normal CDF without scipy ("Not verified").
- This amendment is about dependence between assets. §4.4's index at a reference point for Monte Carlo samples, a joint distribution of two curves for one asset, stays out of it. Q4 stays open.

### Scopes and `design_joint` (D-21.2, D-21.6, §5, §9)

```text
# scopes and joint designs (R-21b)
Individual()      # one design per asset; the plan's default
Joint()           # one objective and one budget on the asset owner's total, one cover per asset
design_joint(templates, sample, objective, *, pricing=PurePremium(), budget=None, limit=None,
             options=DesignOptions(), scope=Joint()) -> JointDesignResult
    # templates: one Cover per asset, in sample.asset_ids order
```

- **What it optimises.** On each draw d of a multi-asset sample, L_d = Σ_j L_{d,j} is the asset owner's total loss and π_d = Σ_j π_{d,j} the total payout. The objective of §5.1 and the premium of §5.2 are taken on L_d and π_d. `Budget(ratio=κ)` means P ≤ κ·E[L] on the total, and `Budget(amount=B)` means P ≤ B on the total. Each asset keeps its own cover, on its own index, and each cover pays by its own terms. The name stays `Joint` (§1).
- **How it is solved.** §5.3's LP and QP with the block basis B = [B_1 | … | B_m], the amounts in asset order, the `LinearConstraints` stacked block by block, and the summed loss. The scale is §5.3's, the largest summed loss of a draw. The route is `"lp"` or `"qp"`.
- **`templates`.** Each is written for its position's asset, or for none, and then the resolved cover names that asset. Families may differ between assets, and each must implement `LinearInAmounts`. Every `payout_unit` and index unit must match the sample's.
- **Fixed thresholds (D-21.6).** A `Free` parameter that isn't an amount raises `DesignError` before solving, naming the parameter. Users compare threshold choices by running `design_joint` once per choice. So joint designs have no grid route: `ties` is 0, `profile` and `grid` are `None`, and a `UserObjective` or a payout without `LinearInAmounts`, which §5.3 sends to the grid, raises `DesignError` too.
- A sample with one asset raises `DesignError`, naming `design`. `limit=` is each cover's own limit (§3), because `Limit` is a term of one contract; a limit on the total isn't offered. `scope` is `Joint()` for now.
- **`JointDesignResult`** holds `DesignResult`'s record (§5.3, §5.4), with these differences:
  - `covers` (asset id to resolved `Cover`, in `asset_ids` order) replaces `cover`, and `template_hashes` replaces `template_hash`;
  - `parameters`, `unidentified`, `zeroed` and `ranges` are keyed by asset id, then by §3's flat names, the shape of the fixtures' `expected` (§8);
  - `objective_value`, `premium`, `expected_loss`, `budget_bound`, `budget_use`, `p_zero_loss`, `tail_outcomes` and `degenerate_tail` are on the total;
  - `covers_hash` is the `sha256:` hash of the canonical JSON of the asset ids and cover hashes, sorted by asset id. `design_id` is §7's, with the template hashes in asset order and the scope's document.
- **Non-uniqueness.** §5.4 applies on the block basis: `fill` per asset, `DesignOptions(ranges=True)` for every identified amount of every asset. A joint design is often not identified per asset (review F8), so its per-asset amounts are one member of an optimal set unless `unique` is true.
- **`Clustered(assignment, *, joint=True)` is deferred** (R-21g, no issue yet). It waits for new cluster fixtures. The core's cluster scope pays one cover per cluster on a value-weighted mean index, so it changes the trigger; the module takes a stated assignment because the core's Ward clustering needs scipy.

### The comparison table (D-21.3, D-21.4, §6, §7)

An evaluation is multi-asset when its sample holds several assets. `evaluate` and `compare` gain `allocation=None` and `values=None`, and each entry on a multi-asset sample is one of:

- a `JointDesignResult`;
- a mapping from every asset id of the sample to that asset's resolved `Cover` or `DesignResult`, a set of covers that each stand on their own. They are all covers or all designs; a mix raises `EvaluationError`.

| Column | What changes |
|---|---|
| `scope` (new, string, after `level`) | `"individual"` or `"joint"`. Phase 1's rows are `"individual"` |
| `level` | `"asset"`: an asset's own cover. `"total"`: the sum over the assets of one owner. `"asset_by_value"`, `"asset_by_loss"`: an asset's share of a joint design's total payout, under the rule in the name. These replace §9's `"joint"` and `"cluster"`: joint is a `scope`, and cluster rows wait for `Clustered` |
| `asset_id` | Becomes nullable: null exactly on `"total"` rows |
| `cover_hash`, `cover_label` | On `"total"` and allocated rows, `covers_hash` (for a set of individual covers, built the same way). The label is the covers' label if they all share one, else the first 12 hex digits |
| `premium_basis` | Becomes nullable: null exactly on allocated rows |

The key of §6 doesn't change; `cover_hash` and `design_id` already differ between scopes.

| Entry | Rows |
|---|---|
| A set of individual covers | One `"asset"` row per asset, as in Phase 1, and one `"total"` row, all `scope="individual"` |
| A `JointDesignResult` | One `"total"` row, `scope="joint"`, and one allocated row per asset when `allocation` is set. No `"asset"` row, because the solver's split isn't identified per asset (review F8) |

- **`"total"` rows** hold every metric of §6 on L_d and π_d, the sums the fixtures' `expected.metrics` are taken on (§8).
  - A joint design's premium is its design premium, the price of one contract on the total, or `premium=`.
  - A set of individual covers pays one premium per contract, so its total row's premium is the sum of the asset rows' premiums, with their `premium_basis`. `evaluate`'s `premium=` states the total instead (`premium_basis` `"stated"`), as a test of a non-unique joint fixture needs (§8). The row's `design_id`, `unique`, `ties` and `degenerate_tail` are null: they describe single designs, which the asset rows carry.
- **Allocated rows.** `"value"`: π_{d,i} = π_d · v_i / Σ_k v_k. `"loss"`: π_{d,i} = π_d · L_{d,i} / L_d, and the value shares in a draw with L_d = 0. These are the core's rules (`docs/methodology/payout-allocation.md`), over all the assets of the design.
  - `values=` maps every asset id to its value, in the loss unit, and is required when `allocation` is set: a sample holds no asset values (§7 keeps them private). Missing, negative or non-finite values, or all zero, raise `EvaluationError`. The hash of the (asset id, value) pairs goes into `assets` (§7).
  - `premium` and the net-loss columns (`var_net_loss_b<β>`, `cvar_net_loss_b<β>`, `net_loss_rp<T>`) are null: a pricing prices the total payout, not a part of it.
  - `expected_loss` and `expected_payout` add up to the total row's under both rules, and `expected_uncovered` under `"loss"` only. The other metrics don't add up.
  - A rule is an accounting statement about the total payout, not the payout of an asset's cover. The rule is in `level`, so no row can be read as the solver's split.
  - `allocation` applies to joint entries only; with no joint entry it raises `EvaluationError` rather than being ignored.
- **The metadata (§7).** Each entry of `setup.evaluations` gains `level` (the levels of its rows, a list), `scope` (a list) and `allocation` (`"value"`, `"loss"` or null). Each entry of `setup.samples` gains `dependence`. A document or table without these reads as Phase 1's: `level` `["asset"]`, `scope` `["individual"]`, no allocation, no dependence; `schema_version` stays `"1.0"`. `setup_text` states the levels, which assets a total sums, the allocation rule and the dependence.
- **What the module shows (D-21.4).** `docs/parametric.md`, the docstrings and the notebook show a joint design with its own rows and explain what it optimises. No table or figure there sets individual against joint until the owner revisits the RQ2 rule (MAR-152 item 4). The `scope` column keeps the rows of each scope apart, and it makes no statement about them.

### The plan (§2, Layer 2)

```text
    .scopes(*scopes)              # Individual() and/or Joint(); default Individual()
    .dependence(model)            # curve sources only; required for Joint() on curves
    .allocation(rule)             # "value" or "loss"; per-asset rows of a joint design; default none
    .joint_sample() -> OutcomeSample   # execution; Joint() only
```

- The default is `Individual()`, so a plan that names no scope behaves as before: one sample per asset, and no `"total"` row. A multi-asset sample, and so a `"total"` row, exists only when the plan holds `Joint()`.
- `Joint()` needs at least two assets. On curves it needs `.dependence(...)`, and without it `explain()` and every execution point raise `ValueError`. `.dependence(...)` on a per-year plan raises: its dependence is the data's own.
- `.scopes` takes both scopes, because the `scope` column keeps them apart. Under D-21.4 the module's docs and notebook run `Joint()` alone.
- The plan applies each template to every asset, as it does today; different terms per asset go through `design_joint`. `.designs()` returns `JointDesignResult` under `Joint()`, and `.samples()` returns each asset's view. `.allocation` reads the values the plan's loss model read. `explain()` states the scopes, the dependence and the allocation.

### The joint fixtures (§8)

- **The contract** of `design_joint` is the 16 `*-joint-*` cases of `parity/crc/cases/`: step payouts on 3 assets, in sample, with 5 `exact`, 9 `within_ranges` and 2 `none`. Eight are `synthetic` (CC0-1.0) and eight `thesis` (CC-BY-4.0); a copy keeps its case's licence and attribution (`parity/crc/README.md`, "Licence"). All use fixed breakpoints, so D-21.6 excludes nothing they test.
- MAR-301 copies them byte for byte into the fork and passes the objective, the parameters, `unique` and the premium by `parity/crc/README.md`'s "How to compare". MAR-303 adds the metrics, through the `"total"` row. `cover` is the list of templates in `asset_ids` order, and `expected.parameters` and `expected.unidentified` are keyed by asset id as `JointDesignResult`'s fields are. The `"within_ranges"` cases need `DesignOptions(ranges=True)`.
- `expected.premium` is the premium on the total, and `expected.metrics` are the columns of a `"total"` row. For a non-unique case the comparison is on the templates resolved with `expected.parameters`: one `Cover.with_values` per asset, evaluated as a set of covers with `premium=expected.premium`, because only a stated premium reproduces a price on the total under a cost-of-capital load.
- No case covers dependence models, allocation or a joint design out of sample; the issues that build them test their properties. Clusters wait for new fixtures.
- **Size.** On 2026-11-08 the cases hold 997,747 bytes of the 1,000,000 that `test_total_size_is_under_1_mb` allows, and a joint case takes 19 to 26 kB. So a new joint case stays small (`synthetic52` or smaller), and the PR that adds it raises the limit, with a reason. The perturbed-solver test moves the solver's point in 9 cases, all non-unique joint designs.

### The illustrative book (D-21.5)

MAR-305 builds the book of D-21.5 in the crc-docs fork, labelled illustrative, with its sites and values stated (CC0). On ERA5 annual extremes the dependence is the data's own. The optional second part puts the same sites on CRC Open curves with an `EmpiricalCopula` from those ERA5 years; no CRC Open data is committed. The notebook prints the dependence as an assumption, states the setup of every number, uses out-of-sample numbers only, and follows D-21.4.

### What the other sections now mean

- **§2.** The Layer 1 and Layer 2 outlines gain the entries above. The module layout gains `dependence.py` (R-21d) and `joint.py` (R-21b: `Individual`, `Joint`, `design_joint`, `JointDesignResult`).
- **§5.** "Phase 1 designs one cover on one asset's sample" stays true of `design`. `design_joint` is the second design function.
- **§8.** "Not ported" now lists clustering, and no longer the joint scope.
- **§9, the portfolio approach.** `design_joint(templates, sample, objective, *, scope=Joint(), allocation="value")` now reads as the outline above, without `allocation`. "`Clustered(...)` follows" now means later, as R-21g. The allocation rule is the evaluation-time one above. "The table's `level` column gains `"joint"` and `"cluster"`" now reads as the table above. `Comonotonic()`, `Independent()` or `GaussianCopula(correlation)` now reads `Independent()`, `Comonotonic()` or `EmpiricalCopula(reference)`, with `GaussianCopula` later.
- **D10's point 7 and "Consequences"** describe Phase 1. For one-asset samples they still hold.

### The issue map (§10)

R-21 is split as below (each about one PR). The other rows stand.

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| MAR-298 (R-21a) | Multi-asset `OutcomeSample`; `asset()`, `join()` and their refusals; `dependence` and `parts`; `design`, `evaluate` and `compare` raise on a multi-asset sample | `sample`; the checks in `design` and `evaluate` | This amendment |
| MAR-301 (R-21b) | `Individual`, `Joint`, `design_joint`, `JointDesignResult`; the 16 joint cases; the budget and the premium on the total | `joint` (new); `tests/fixtures/parametric/` | R-21a |
| MAR-302 (R-21d) | `Independent`, `Comonotonic`, `EmpiricalCopula`, `sample_curves` | `dependence` (new), `sources` | R-21a; in parallel with R-21b |
| MAR-303 (R-21c) | `compare` and `evaluate` take `JointDesignResult` and sets of covers, with `allocation=` and `values=`; the `scope` column, `level`, the metadata and `setup_text`; the 16 joint cases' metrics | `evaluate`, `metadata`, `metrics` | R-21b |
| MAR-304 (R-21e) | `.scopes`, `.dependence`, `.allocation`, `.joint_sample`; results equal the function route; the method-only section of `docs/parametric.md` | `plan`; `docs/parametric.md` | R-21c, R-21d |
| MAR-305 (R-21f) | The illustrative book in the notebook (D-21.5) | crc-docs fork | R-21e |
| R-21g (later, no issue yet) | `Clustered(assignment, *, joint=True)` and its fixtures, an R-13 extension | Set when it is refined | New cluster fixtures |

### Beyond the six decisions

The six decisions don't determine these. The text above settles each as the agent recommends, and the owner's approval of this amendment covers them.

1. How `EmpiricalCopula` handles more draws than reference years: rank blocks, `n_draws = k·m`. D-21.1 asks the amendment to say; the table above has the options.
2. Ties in a reference: tied years pool their blocks.
3. An `EmpiricalCopula` sample takes `FreshDraws`; `holdout` and `year_block_kfold` raise on it.
4. The reference is a multi-asset `OutcomeSample`, ranked on its hazard.
5. `sample_curves` takes one generator per asset, so it reproduces `sample_curve` column by column and the plan's child generators.
6. A joint evaluation names its asset values with `values=`, because a sample holds none, and `"loss"` needs them for draws without loss.
7. The `"total"` row of a set of individual covers has the sum of the contract premiums.
8. On `"total"` rows `asset_id` is null and `cover_hash` is `covers_hash`, so no sentinel asset id is reserved.
9. `design_joint` raises for a `UserObjective`, a payout without `LinearInAmounts` and a one-asset sample; `limit=` is per cover.
10. `.scopes` takes both scopes, and a plan writes a `"total"` row only when it holds `Joint()`.

### Not verified

- No R-21 code exists, and the module's own routes were not run on a block basis. A throwaway check (2026-11-08, not committed; script and output in the PR) solved §5.1 and §5.2 on B = [B_1 | … | B_m] with the summed loss in cvxpy and Clarabel, without the core or the fork: all 16 joint cases gave their `expected.objective_value`, within 7e-9 relative.
- The rank-block reordering was checked the same way on synthetic numbers (numpy, not committed): the columns are permutations of the draws, the blocks equal the reference's ranks for k = 1, 3 and 100, ties pool, and no generator state moved.
- How long §5.4's ranges take on a large block basis: four LPs per amount.
- No ERA5 or CRC Open data was read for this amendment.

## Amendment 4 (2026-11-08, MAR-329): scenario analysis

On 2026-11-08 the owner, Marc Prinzing, decided D-23.1 to D-23.6 (in chat; recorded on MAR-44 and MAR-329). They fix the public API of scenario analysis (R-23, MAR-44), which the owner calls a core capability of CRC, so this amendment comes before any R-23 issue starts, and the owner approves it before it merges. It builds on Amendments 2 and 3 and on errata 11 and 12. Amendment 5 (multi-hazard, MAR-330) follows it.

The rest of the ADR stands. §2, §4.2, §4.4, §4.5, §6, §7, §9 and §10 keep their text and each carries a one-sentence pointer here, and this amendment says what they now mean, as Amendment 1 did. Every addition has a default, so a call or a plan without scenarios gives the same rows and hashes, with the new columns beside them. The one exception is a Layer 1 call that reuses one generator state across curves out of sample, which now raises (below). The publication rule applies: this amendment presents the options and what each one records, nothing here says that a pathway, a horizon or a design is better than another, and joint designs are described as a method only.

### The six decisions

All six are option (A) of the refinement on MAR-44, as the owner adjusted them.

| | Decision |
|---|---|
| D-23.1 | Scenarios are a dimension of the module: `ParametricPlan.scenarios(ScenarioSet(...))`, with no separate `ScenarioPlan`. `for_evaluation` accepts several horizons or pathways once scenarios are stated, so `select(horizons=…, pathways=…)` is the way in. Layer 1: `ScenarioSet`, `compare_scenarios`, `to_drift`; the plan equals them row for row. Both routes, pools, individual and joint designs (owner-total rows). Min-max robust design stays for later |
| D-23.2 | One table: every cover or design on every scenario's evaluation block, out of sample only, the reference included. `scenario` says where a row is evaluated and `design_scenario` where it was designed. Terms, loss model, values, basis-risk model, pricing and metric options stay fixed. Curves share one set of evaluation draws, separate from the design's. `to_drift(table, reference=)` adds differences and ratios, with no ranking column |
| D-23.3 | `premium` and the net-loss columns stay at the contract price: a design's premium, or a given cover's stated premium or its premium priced once on the reference (`premium_basis="reference"`). A new `premium_repriced` prices the same payouts on each scenario |
| D-23.4 | `scenario` stays a free label (D-25.5). New columns `pathway` (the source's spelling, checked with `strict=True`), `horizon` (the curve's year, or a per-year window's centre) and `product` come from the source record, never the label, and are null where it states none. Nothing interpolates between horizons |
| D-23.5 | `ScenarioError` for scenarios that differ in anything but the hazard (assets, units, loss or basis-risk model, trend option, a pool's models); a stated pathway the source contradicts; two scenarios with one pathway, horizon and product; equal curves at several horizons (CRC Open's cyclone); a horizon outside the dataset's window; a cover bound to a location a scenario's index doesn't read; and two products among the non-reference scenarios unless `mixed_products=True`. ERA5 as the reference beside model output needs no flag, and the setup text always says the difference includes the products |
| D-23.6 | The reference is required and named. ERA5 is a first-class reference on both routes. Otherwise the earliest horizon on CRC Open and the same models' `historical` years on NEX |

### `ScenarioSet` (D-23.1, D-23.6, §4.5, §9)

```text
# scenarios (R-23b); frozen; no I/O
ScenarioSet(entries=(), *, reference, labels=None, mixed_products=False)
    # entries: one OutcomeSample per scenario (Layer 1), or what a plan reads (Layer 2, below)
    # reference: required, the label of one scenario
    # labels: Layer 2 only, a mapping from (pathway, horizon) to a label
    .reference -> str
    .labels -> tuple[str, ...]           # Layer 1 only: the reference first, then as given
    .sample(label) -> OutcomeSample      # Layer 1 only
ScenarioError                            # a SampleError, so also a ValueError
```

- **One kind of entry.** A set holds built samples or a plan's descriptions, never both, and `compare_scenarios` and `.scenarios(...)` each refuse the other kind with a `TypeError`.
- **At Layer 1** each entry is one scenario's evaluation block, a one-asset or multi-asset `OutcomeSample`. Its label is the sample's own `scenario` (D-25.5), so a sample keeps one name, which is in its hash. Two samples with one label raise, and the error names `scenario=`, which R-23a adds to `sample_curve`, `sample_curves` and `OutcomeSample.from_table`.
- **The reference** has no default and must be one of the labels (D-23.6). It prices a given cover (D-23.3), and it is the default reference of `to_drift`. The module doesn't choose one. `docs/parametric.md` and the notebook use ERA5, shown next to the earliest horizon, because CRC Open has no historical baseline. Otherwise they use the earliest horizon on CRC Open and the same models' `historical` years on NEX.
- **One scenario is allowed**, the reference alone. Then `compare_scenarios` gives `compare`'s rows on that block, except that a cover given as is takes D-23.3's premium.
- **The refusals** that need the samples run at construction on a Layer 1 set and at execution on a plan, through one function. Those that need only the labels run at construction on both.

### The plan (D-23.1, §2, Layer 2)

```text
ParametricPlan
    .scenarios(scenarios, *, design_on="each", premiums=None)     # R-23d
    .split(rule, *, per_year=None)                                # per_year: Holdout(f), beside FreshDraws
    .scenario_samples() -> Mapping[str, Mapping[str, OutcomeSample]]    # execution; label, then asset

# what a plan reads, beside its own source
AnnualScenario(label, source, *, provenance, unit=None, location=None, year_column=None, hazard_column=None,
               years=None, missing=None, trend=None, pool=None, pathway=None)
CurveScenario(label, dataset, *, pathway=None, horizon=None)
```

- **The way in, on the curve route.** `for_evaluation(request)` keeps refusing several hazards, but no longer several horizons or pathways. `.scenarios(...)` comes after it, so that check moves: `explain()` and every execution point raise today's `ValueError` when several horizons or pathways are selected and no scenarios are stated.
  - With `.scenarios(...)`, the request's `select(...)` must state `horizons` and `pathways`, so `explain()` can list the scenarios without reading anything.
  - Every selected (pathway, horizon) is one curve scenario, labelled `<pathway>_<horizon>`. `labels={("ssp585", 2050): "mid-century"}` names them, and when given it lists exactly the pairs used, because a dataset need not hold every pair of the product.
  - One `.monte_carlo(n_draws, seed=...)` serves every curve scenario.
  - With nothing else to read, `ScenarioSet(reference="ssp585_2030")` is the whole statement: `entries` stays empty on a plan whose scenarios all come from the selection. An empty set raises at Layer 1.
- **`AnnualScenario`** is a scenario read from per-year values, such as ERA5's years on the curve route, or another pathway's years on the per-year route. `source` takes what `for_annual_extremes` takes.
  - On a per-year plan the plan's own source is one scenario, under its `scenario=` label, and a field left `None` takes the plan's value. `impact`, `value_column`, `context`, `cell` and `seed` are the plan's, so they are not options.
  - On a plan on curves, `unit` is required, the location defaults to `NearestCell()`, the columns to `"year"` and `"value"`, `missing` to `"raise"` and `trend` to `AsRecorded()`. The impact's H3 cell is the one the asset's curve row matched, so the loss model stays the same.
  - `pool=None` takes the plan's `pool=`, `pool=False` states a series that is not pooled, such as ERA5 beside NEX pools, and a `ModelPool` states one.
  - `pathway=` states a pathway. It fills the column where the source states none, and must agree with the source where it does (D-23.5).
- **`CurveScenario`** is a scenario read from another local canonical dataset with the plan's assets, such as ERA5's own fitted curve (`HazardDataset.era5(recipe)…canonicalize(...).materialize(path)`). `pathway` and `horizon` pick one of its curves and are required if it holds several. On a per-year plan it raises `ValueError`.
- **ERA5 on both routes (D-23.6).** On the curve route it is `AnnualScenario("era5", era5_plan, unit=..., provenance=...)`, its years beside the curves, or a `CurveScenario` of its fitted curve. On the per-year route it is the plan's own source, or an `AnnualScenario` with `pool=False` beside NEX pools. Either way it needs no flag. "What is shared" below says what its rows mean beside draws.
- **`design_on`.** `"each"`, the default, designs every template under every objective on every scenario's design block, which makes "drift" and "a design per scenario" slices of one table. `"reference"` designs on the reference's only.
- **`premiums=`** maps a `cover_label` to a stated premium, for covers given as is (D-23.3). A key that matches no such cover raises `EvaluationError`.
- **`.split(...)` is required**, because the rows are out of sample only (D-23.2): without it `explain()` and every execution point raise `ValueError`. One rule makes each scenario's design and evaluation blocks:

  | `.split(...)` | Curve scenarios only | Per-year scenarios only | Both |
  |---|---|---|---|
  | `FreshDraws(n, seed=)` | Design on the plan's draws, evaluate on the fresh draws | `TypeError`, as today | Needs `per_year=Holdout(f)` for the per-year scenarios |
  | `Holdout(f)` | First share of the draws, then the rest | First share of the years, then the rest | Applies to both |
  | `KFold(k)` | One block per fold | One block per fold | Applies to both, fold by fold |

  `per_year=` is allowed only beside `FreshDraws` on a set of both kinds, and otherwise raises `ValueError`. It exists because a set with `EmpiricalCopula` can't use `Holdout` on its curve scenarios (Amendment 3).
- **Execution.** For each asset (or, under `Joint()`, once) and each fold, the plan builds every scenario's blocks, designs on them, and calls `compare_scenarios` with the reference's design block, so the rows equal the function route's. `.designs()` is in scenario, asset, fold, cover, objective order. `.samples()` and `ParametricResult.samples` hold the reference's samples, and `.scenario_samples()` and `ParametricResult.scenario_samples` every scenario's; `ParametricResult.scenario_fresh_samples` holds the curve scenarios' fresh draws. One Parquet file is written, atomically. `explain()` lists the scenarios, their sources, the reference and `design_on`, without I/O.

### One table (D-23.2, §6)

```text
# comparison across scenarios (R-23c)
compare_scenarios(covers, scenarios, *, fold=0, pricing=PurePremium(), premiums=None, options=MetricOptions(),
                  design_sample=None, allocation=None, values=None) -> pyarrow.Table
to_drift(table, *, reference=None) -> pyarrow.Table
```

- **`covers`** takes what `compare` takes on the set's samples: resolved covers and designs, and on multi-asset samples a `JointDesignResult` or a mapping (Amendment 3). Every entry is evaluated on every scenario's block, one row per entry and scenario, reference first. Every row has `split="out_of_sample"`, so the function has no `split=`.
- **`design_sample`** is the reference's design block, and is required when an entry is a cover given as is. Its label must be the reference. A design brings its own, and the label of that sample must be one of the set's, or `ScenarioError` says so. That label is the row's `design_scenario`. The designs of one mapping must share a label, which is their `"total"` row's.
- **`fold`.** Layer 1 takes one fold at a time. Folds are concatenated with `EvaluationMetadata.merge`, as for `compare`.

| Column | Type | Meaning |
|---|---|---|
| `scenario` | string | Where the row is evaluated, as in §6 |
| `design_scenario` (new, after `scenario`) | string, nullable | The label of the design's own design sample. Null for a cover given as is, which wasn't designed on any scenario |
| `pathway`, `horizon`, `product` (new, after it) | string, int32, string; nullable | D-23.4, below |
| `n_rows` (new, after `sample_hash`) | int32 | The number of rows of the evaluation block |
| `premium_repriced` (new metric, after `premium`) | float64, nullable | D-23.3, below. Only in tables `compare_scenarios` writes |

`compare` and `evaluate` fill `design_scenario`, `pathway`, `horizon`, `product` and `n_rows` too, and a table without them reads as null. The key of §6 gains `design_scenario`. A design's `design_id` already holds its design sample's hash, and with it the label. But the `"total"` row of a set of individual designs has a null `design_id` (Amendment 3), and two such sets, designed on two scenarios, can resolve to the same covers.

**`to_drift(table, reference=None)`** returns a long table, one row per metric. It has `to_long`'s columns and `reference_scenario`, `reference_product`, `reference_n_rows`, `reference_value`, `difference` (`value − reference_value`) and `ratio` (`value / reference_value`, in unit `"1"`). Both are null where either value is null, and `ratio` too where `reference_value` is 0.

- A row is paired with the row of the same (`cover_hash`, `design_id`, `design_scenario`, `asset_id`, `level`, `split`, `fold`) on the reference. A key without a reference row raises `EvaluationError`. So `to_drift` compares one cover or design with itself across scenarios, never two covers, two designs or two scopes.
- Rows on the reference itself are left out: their differences are 0.
- `reference=None` takes the set's reference, from the metadata. Any label in the table may be stated instead, so differences can be taken from the earliest horizon while ERA5 stays the set's reference.
- It has no rank, no best flag and no ordering by a metric.

### The premium (D-23.3, §6)

| Entry | `premium` and the net-loss columns | `premium_basis` | `premium_repriced` |
|---|---|---|---|
| A design | Its design premium | `"design"` | `pricing` on this block's payouts |
| A cover given as is, with `premiums=` | The stated premium | `"stated"` | The same |
| Another cover given as is | `pricing` once, on the reference's design block | `"reference"` | The same |
| The `"total"` row of a set of individual covers | The sum of the asset rows' | Theirs, as in Amendment 3 | The sum of the asset rows' |
| The `"total"` row of a joint design | Its design premium, on the total | `"design"` | `pricing` on this block's total payout |
| An allocated row | Null | Null | Null |

- `premium` is what a contract in force costs, and `premium_repriced` what a renewal on this block would cost. Under `PurePremium`, `premium_repriced` equals `expected_payout`.
- **Priced on the reference's design block,** not its evaluation block: that is where a design is priced, so a given cover and a design on the reference stand on one footing, no held-out row enters the price, and a short per-year block doesn't set it.
- `premium_basis` gains the value `"reference"`.
- A budget is the design's. `Budget(ratio=κ)` is a share of each design block's expected loss, so it moves with the scenario. `Budget(amount=B)` doesn't. The setup text says which.

### What a row says it read (D-23.4)

`pathway`, `horizon` and `product` come from a sample's source records, never from its label.

| Column | A curve | A per-year series | A pool | A table |
|---|---|---|---|---|
| `pathway` | The canonical row's `pathway` | As `setup_text` reads it (Amendment 2): the source's or the series' `pathway`, or the one-valued `scenario` column of a table with `model`, `member` and `scenario` | The runs' one pathway (D-25.3) | Its source's `pathway`, else null |
| `horizon` | The canonical row's `horizon` | `(first + last) // 2` of the series' whole window, `details.years`, as `TemporalWindow.horizon` | The same, on the pool's years | Null |
| `product` | `metadata.source.provider` | The series' `source.provider` | The runs' provider | Its source's `provider`, else null |

- **`pathway`** keeps the source's spelling and is checked with `crc_sdk.pathways.resolve_pathway(label, strict=True)`. An unknown label raises `ScenarioError`, and `register_pathway` adds a private one. Comparisons use `pathways_equivalent`, so `historic` and `historical` are one.
- **`horizon`** on a per-year sample is the window's centre, not the block's: `details.years` survives a split, so a scenario's blocks have one horizon. 1979–2023 reads 2001 and 2041–2070 reads 2055. Under `LinearTrend` the values are at the reference year's level, which the setup text states, and the column still gives the centre.
- **`product`** is the record's `provider` as written, so a CRC Open row reads `crc_open`, an ERA5 row `era5`, and a native CMIP6 row `cmip6`. On the plan route a per-year source's provider is the caller's `SourceProvenance.provider`; the docs use `nex-gddp-cmip6` for NEX.
- **Nothing interpolates.** A scenario is a horizon the dataset holds. Between two horizons there is no row.
- **Several sources in one sample** (several assets; Amendment 5's components) must agree on `pathway`, `horizon` and `product`, or `ScenarioError` says which. Amendment 5 may relax this for `product`.

### What is refused (D-23.5)

Each `ScenarioError` names the two scenarios and the field.

| Refusal | What is compared | Between |
|---|---|---|
| Assets | `asset_ids`, in order | All |
| Units | `index_unit`, `loss_unit`, exactly | All |
| Loss model | The `loss_model` document per asset (`parts` on a multi-asset sample) | All |
| Basis-risk model | The `basis_risk` document | All |
| Trend option | `trend`'s kind, with `n` or with `method` and `min_years`. A reference year or the fitted slopes may differ | Per-year scenarios |
| A pool's models | The (model, member) pairs | Pools; and a scenario that isn't a pool beside a pool, unless it is the reference |
| A contradicted pathway | A stated `pathway=` against the source's, by `pathways_equivalent` | Each scenario |
| One pathway, horizon and product | The three values, null equal to null | All |
| Equal curves | The curve documents of any one asset | Curve scenarios |
| A horizon outside the window | Each selected horizon against `temporal_window`, the test of `warn_if_outside_window(strict=True)`, a warning today | Each curve scenario |
| A pair the dataset doesn't hold | Every selected (pathway, horizon), for every asset | Each curve scenario |
| A bound cover | The table below | Each cover and scenario |
| Two products | The `product` strings, unless `mixed_products=True` | Non-reference scenarios only |
| Draws not shared | `period` and the generator records (below) | Curve scenarios |
| Dependence | The `dependence` document | Curve scenarios |

The reference may be any product, so ERA5 needs no flag, and neither does any other reference. A set of CRC Open horizons has one product, and needs none either.

| A cover read at | Is evaluated on a scenario whose index is |
|---|---|
| `AtAsset()` | Any: each scenario reads its own index at the asset, and `product` says which |
| `AtPoint(p)` | A per-year series whose matched cell is centred at p, compared as `.index(...)` compares a bound location |
| `AtStation(id)` | A per-year series of that station |
| `AtCell(c)` | A curve at H3 cell c |

### What is shared, and ERA5 beside curves (D-23.2, D-23.6)

A scenario's *evaluation block* is the rows its out-of-sample metrics are taken on: fresh or held-out draws for a curve, held-out years for a per-year series or a pool.

| | Curves beside curves | Years beside years | Years beside draws |
|---|---|---|---|
| Terms, loss model, values, basis-risk model, pricing, metric options | The same | The same | The same |
| The rows of the blocks | The same uniforms, row by row | Each scenario's own held-out years | Nothing row by row |
| The number of rows | Equal | Each scenario's own | Each its own, often far apart |
| Noise factors of a model that draws | The same, row by row | From the asset's generator, the same start in every scenario | Unrelated |
| What the leakage check compares | (generator record, draw number) | (lineage, year); (run lineage, year) on a pool | Nothing: a draw is not a year |
| `leakage_check` on a cross row | `"passed"` | `"passed"` if a lineage or run is in common, else `"different_sources"` | `"different_sources"` |

**Curves share one set of evaluation draws.** Every Monte Carlo block of a set must hold the same `period` values and the same generator record for each `hazard` step of each asset (`provenance.rng`, or `parts` on a multi-asset sample). So each asset's row d holds one uniform in every curve scenario, and, since the basis-risk model draws after the uniforms (§4.4), one noise factor. The dependence models reorder by the ranks of the uniforms and a stated reference only, so the reordering is the same in every curve scenario too. Otherwise `ScenarioSet` raises `ScenarioError`, naming `rng` or `period`. A Layer 1 caller builds each block with a new generator from one seed sequence. Reusing one `Generator` object advances it, and the check refuses that. The plan rebuilds each asset's child generator per scenario, from the plan's seed for the design draws and from `FreshDraws.seed` for the evaluation draws.

**Separate from the design's.** §4.4's leakage check (`_check_out_of_sample`) gains a rule: two Monte Carlo samples share a draw when a `hazard` step of one has the generator record of a `hazard` step of the other and they have a period in common, whatever the curve. That raises `LeakageError`. Today such a pair passes, since another curve has another lineage, and the setup text says "on fresh Monte Carlo draws". The blocks of one `holdout` still pass: their periods are disjoint. The rule holds in `evaluate` and `compare` too, so it also closes the trap of a loop by hand.

**The split method.** `setup.evaluations[*].method` gains `"other_scenario"`, used when the design sample's label differs from the block's. It takes precedence over the block's own split step, because today a held-out block of another source reads `"holdout"`. For a cover given as is the design sample is the reference's design block. `details` records the block's own split, under `block`.

**Years beside draws.** ERA5's rows are years of a reanalysis at a grid cell. CRC Open's rows are simulated years from a fitted curve at an H3 cell. No uniform lies behind a year, so "shared draws" can't hold between the two. What D-23.2 keeps fixed still holds: the terms, the loss model, the values, the basis-risk model, the pricing and the metric options. A worked example, with ERA5 for 1979–2023 (45 years), CRC Open `ssp585` at 2030, 2050 and 2080, `.monte_carlo(21_000, seed=1)`, `.split(FreshDraws(9_000, seed=2), per_year=Holdout(0.7))` and `reference="era5"`:

| | A design on ERA5's years, on `era5` | The same design, on `ssp585_2050` | A design on the 2050 draws, on `era5` |
|---|---|---|---|
| `design_scenario` | `era5` | `era5` | `ssp585_2050` |
| `scenario` | `era5` | `ssp585_2050` | `era5` |
| Designed on | 1979–2009, 31 years (⌊0.7 · 45 + 1e-9⌋) | The same | 21,000 draws |
| `n_rows` | 14, the years 2010–2023 | 9,000 draws | 14 |
| `pathway`, `horizon`, `product` | null, 2001, `era5` | `ssp585`, 2050, `crc_open` | null, 2001, `era5` |
| `method` | `"holdout"` | `"other_scenario"` | `"other_scenario"` |
| `leakage_check` | `"passed"`: disjoint years of one lineage | `"different_sources"` | `"different_sources"` |
| The cover pays on | ERA5's value at the nearest cell | The curve's draw | ERA5's value at the nearest cell |
| `premium`, with its `premium_basis` | Priced on 1979–2009, `"design"` | The same | Priced on the 21,000 draws, `"design"` |
| `premium_repriced` | On 2010–2023 | On the 9,000 draws | On 2010–2023 |

- **`design_scenario` and `scenario` name blocks.** They don't say that the two are comparable. The terms are the resolved design's, in index units. A threshold set on ERA5's values is read on the curve as it stands, and nothing rescales it. A row on a curve says what the same terms would pay on that product's reading of the index, which is not what a contract written on ERA5 would pay.
- **`"different_sources"`** says that no row could be compared, not that the sources are independent. A bias-corrected curve may have been calibrated on a reanalysis, and the module can't see that.
- **Short blocks.** On a block of n rows, CVaR at β with (1 − β)·n ≤ 1 is the block's worst row, and a return period above n reads its largest value. On 14 years that holds for β = 0.95 and 0.99 and for T = 25 and above of the default options. On 9,000 draws (1 − 0.99)·9,000 = 90 rows. `n_rows` shows the difference and the setup text names the columns concerned.

| Option for ERA5 on the curve route | What is shared | Assessment |
|---|---|---|
| **Years stay years** (`AnnualScenario`, recommended as what the docs lead with) | The terms and models; no rows | No fit is added, and a design can be made on the observed years. A block holds few rows, and the row counts of the two sides differ |
| ERA5's own fitted curve (`CurveScenario`), also available | Everything, the uniforms included | Blocks have equal rows and the comparison is curve beside curve. A fit is added (by default a GEV on the annual extremes), so the tail is the fit's, not the record's |
| Evaluate each curve at the held-out years' plotting positions | Ranks | Reduces each curve to the record's few rows, and pairs a year's rank with a draw, which invents a dependence between two sources |
| Resample ERA5's years with the shared uniforms | The uniforms in name | Rows are repeats of a few years, so the row count misstates the information, and it adds no draw from the distribution |
| Refuse years beside draws | Nothing | Contradicts D-23.6 |

**What the setup text says.** `setup_text` states, next to the numbers:

1. Every scenario: its label, whether it is the reference, its product, pathway and horizon, its rows (years with their range, or draws), and how the block was made.
2. What stays fixed, and that a cross row is a cover or design from one scenario on another's block, naming both.
3. For curve scenarios, that they share one set of evaluation draws, separate from the design's.
4. Where a row's product differs from the reference's, that the difference includes the products: resolution, method and pooling differ, so it can't be attributed to the scenario alone. For years beside draws, also that no row of one corresponds to a row of the other and that the blocks hold different numbers of rows.
5. Where each scenario reads the index: the nearest cell or the station, or the asset's H3 cell.
6. The premium basis of every cover, and that `premium_repriced` prices the same payouts on each block.
7. Whether a design's budget moves with the scenario (`ratio`) or not (`amount`).
8. For a `"different_sources"` row, that no row could be compared and that different sources need not be independent.
9. For `product` `cmip6`, crc-sdk's own caveat: results are change signals, not design values.
10. That β is the same on every scenario while the tail's loss level isn't, and the short-block columns above.
11. On `"total"` rows of years beside draws, that the dependence between the assets differs: the data's own on one side and the stated model on the other.

### With Amendments 2, 3 and 5

- **`scenario=` (D-25.5)** is the label. The lineage still leaves it out, so §4.4's check sees through a relabelling.
- **`trend=`.** One option for every per-year scenario, and each scenario's fit is on its own design years. `reference_year=None` is each series' last year, so two windows have two reference years, and the setup text states each.
- **Pools.** A pool holds one pathway (D-25.3), so `historical` and each SSP are separate scenarios with the same (model, member) pairs. Their blocks are years, and §4.4's check compares (run lineage, year). ERA5 as the reference is not a pool (`pool=False`). `FreshDraws` stays refused.
- **`.index(...)`** applies to every per-year scenario, on that scenario's hazard years, under `missing=`. A station index has no future years, so a future scenario beside it raises. Covers are bound as in D-25.4, and a bound cover follows the table in "What is refused".
- **Several assets.** A set's samples may hold several assets, and all must hold the same ones. Rows have Amendment 3's `level` and `scope`.
- **Joint designs.** Under `Joint()`, each scenario has one multi-asset sample per block, and a `JointDesignResult` gets one `"total"` row per scenario, and allocated rows under `.allocation(...)`. `design_on` applies as for `Individual()`.
- **Dependence.** `.dependence(...)` applies to the curve scenarios and the per-year scenarios keep the data's own. An `EmpiricalCopula` set uses `FreshDraws`, with `per_year=` where it also holds years.
- **D-21.4.** The `scope` column keeps the scopes apart. `to_drift` pairs a row only with the same cover or design, so it never sets one scope against the other. The docs and the notebook run `Joint()` alone until the owner revisits the RQ2 rule (MAR-152 item 4).
- **Amendment 5.** Nothing above assumes one asset or one hazard. A set compares its samples' fields, the generator check covers every `hazard` step, and the three columns read every hazard source. Amendment 5 adds a multi-hazard sample's component names and units to the compared fields.

### The metadata (§7)

- `setup.scenarios` (new, null without scenarios): the reference, the labels, `mixed_products`, `design_on` and, per scenario, its source kind, `n_rows`, `pathway`, `horizon` and `product`. It records which scenarios share draws and the generator record they share. `EvaluationMetadata.merge` requires one `setup.scenarios` across folds.
- Each entry of `setup.evaluations` gains `scenario` and `design_scenario`, so a block has one entry per design scenario. `method` gains `"other_scenario"` and `leakage_check` gains `"different_sources"`, which appears on `"other_scenario"` entries only, so plain comparisons read as before.
- Each entry of `setup.samples` gains `pathway`, `horizon` and `product`. `columns` gains `premium_repriced`. A plan's `source_records` and `sources` hold one entry per dataset or per-year source, each with its scenario's label, and `licences` every input's terms.
- `to_drift`'s table keeps the metadata and adds `drift`, with the reference used. A document without these keys reads as before, and `schema_version` stays `"1.0"`.

### What the other sections now mean

- **§2.** The outlines gain the entries above. The module layout gains `scenarios.py` (R-23b, R-23c: `ScenarioSet`, `AnnualScenario`, `CurveScenario`, `compare_scenarios`, `to_drift`). `errors.py` gains `ScenarioError`. `for_evaluation`'s refusal of several horizons or pathways moves as above.
- **§4.2.** `sample_curve` gains `scenario="baseline"`.
- **§4.4.** "Evaluating a design out of sample on a sample that shares a period with its design sample from the same source raises `LeakageError`" now also holds for two Monte Carlo samples that reuse one generator record, whatever the curve.
- **§4.5.** "Phase 2 adds a `ScenarioSet`" is this amendment.
- **§6.** "The premium used" gains the case above and the value `"reference"`. The table gains the columns above, and its key gains `design_scenario`.
- **§7.** `setup` gains the entries above.
- **§9, scenarios.** "`compare` fills the `scenario` column" now reads: `compare_scenarios` fills it, with `design_scenario`. `Robust(objective)` stays for later (D-23.1).

### The issue map (§10)

R-23 is split as below (each about one PR). The other rows stand.

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| MAR-331 (R-23a) | `scenario=` on `sample_curve`, `sample_curves` and `from_table`; the columns `design_scenario`, `pathway`, `horizon`, `product` and `n_rows`, with the strict pathway check; `design_scenario` in the key; a table without them reads as null | `sources`, `sample`, `evaluate`, `metadata` | This amendment, MAR-295, MAR-303 |
| MAR-332 (R-23b) | `ScenarioSet`, `ScenarioError`, the refusals of D-23.5, one test each, the shared-draws check; `reference` required | `scenarios` (new), `errors`, `__init__` | R-23a, MAR-296 |
| MAR-333 (R-23c) | `compare_scenarios`, `to_drift`, `premium_repriced`; the premium basis `"reference"`; the split method `"other_scenario"` and `"different_sources"`; the generator-record rule of the leakage check; years beside draws; the setup text | `scenarios`, `sample`, `evaluate`, `metrics`, `metadata` | R-23b |
| MAR-334 (R-23d) | `.scenarios`, `AnnualScenario`, `CurveScenario`, `design_on`, `.split(per_year=)`, `.scenario_samples`; the moved `for_evaluation` check; results equal the function route; the scenario section of `docs/parametric.md`, the method only, saying that β is the same in each scenario while the tail's loss level isn't | `plan`, `scenarios`; `docs/parametric.md` | R-23c, MAR-304 |
| MAR-335 (R-23e) | The notebook section in crc-docs: heavy rain in Toronto against ERA5, CRC Open `rx1day` at 2030, 2050 and 2080 (stating SSP5-8.5 only and no historical baseline), NEX pools of the same models for `historical` and two SSPs. Every number out of sample next to `setup_text`, and each drift a measurement of that setup | crc-docs fork | R-23d, MAR-299 |

`scenario=` on `sample_curves`, and the shared-draws check of a multi-asset curve set, land with the later of MAR-302 and the issue above that owns them.

### Beyond the six decisions

The six decisions don't determine these. The text above settles each as the agent recommends, and the owner's approval of this amendment covers them.

1. Years stay years beside curve draws: nothing is shared row by row. ERA5's fitted curve is available as an ordinary curve scenario. The table above has the options.
2. A cross row against a per-year or curve block of another source records `leakage_check="different_sources"`, not `"passed"`.
3. A `ScenarioSet` takes built samples, whose own labels name them, or a plan's descriptions.
4. A selected curve is labelled `<pathway>_<horizon>` unless `labels=` names it, and `labels=` lists the pairs used.
5. `.scenarios(...)` needs `select(...)` to state both `horizons` and `pathways`.
6. `AnnualScenario` and `CurveScenario` are the plan's descriptions of other sources, and `pool=False` states a series beside pools.
7. `design_on="each"` is the default, so drift and a design per scenario are slices of one table.
8. `.split(rule, *, per_year=Holdout(f))` serves sets of both kinds. `Holdout` and `KFold` apply to both kinds without it. A plan with scenarios must state a split.
9. A given cover's `design_scenario` is null, and the key of §6 gains `design_scenario`.
10. "Priced once on the reference" means on the reference's design block.
11. A stated premium is `premiums=`, keyed by `cover_label`.
12. The generator-record rule sits in `_check_out_of_sample`, so `evaluate` and `compare` get it too.
13. `to_drift` returns a long table, leaves the reference's own rows out, and takes any label as `reference=`.
14. `n_rows` is a column, not only metadata.
15. A per-year `horizon` is the centre of the series' whole window, not the block's.
16. `product` is the record's `provider`.
17. The dependence model joins the fields that must match among curve scenarios.
18. Equal curves are refused if any one asset's curves are equal, so a time-invariant layer can't read as a measured absence of drift.
19. A pool's models are compared as (model, member) pairs, and a reference that isn't a pool is exempt.
20. The two-products check leaves out the reference, of any product.
21. A selected (pathway, horizon) the dataset doesn't hold raises, where `asset_curves()` returns no row and no error.
22. `ScenarioError` is a `SampleError`.
23. `.samples()` holds the reference's samples, and `.scenario_samples()` all of them.

### Not verified

- No R-23 code exists. A throwaway check (2026-11-08, not committed; script and output in the PR) ran the rules on synthetic numbers, the fork's `parametric` at `edcb8b0` and numpy, without any CRC, ERA5 or NEX data:
  - today, the same seed on another curve gives identical uniforms, lineages that differ, method `"fresh_draws"` and `leakage_check="passed"`; one cover on two `"baseline"` samples repeats a row key; two equal curves give equal rows;
  - a held-out block of another curve, or of another source, reads `"holdout"` today;
  - blocks of one `holdout` keep the generator record and have disjoint periods, the basis-risk step's record is equal when the hazard step's is, and `details.years` survives a split;
  - two windows of one series share a lineage, and disjoint windows pass;
  - the arithmetic above: 45 years give 31 and 14 at 0.7, the centres 2001 and 2055, and on 14 rows CVaR at β = 0.95 and 0.99 is the largest value and T ≥ 15 reads it.
- The grid route was run for `design_id` and `premium_basis`. No LP or QP design ran, because that environment has no `highspy`.
- No CRC Open catalogue, NEX or CMIP6 table or ERA5 data was read. So whether the cyclone files declare themselves time-invariant is unknown, hence the refusal on equal curves. How many NEX models share `historical` and each SSP at a site is unknown, and that decides how often the refusal on a pool's models fires.
- What pathway ERA5's canonical rows hold was not read; its code records `scenario="historical"`. So whether a set can hold both ERA5 forms depends on the rule against one pathway, horizon and product.
- A curve's calibration data was not checked, so whether CRC Open's bias correction used ERA5 is unknown.
- The module can't check that a per-year source measures the same thing as a curve beyond its unit: a per-year sample records no hazard name to compare.
- The cost of `design_on="each"` on a large set was not measured.
