# ADR 0005: Design of the `crc_sdk.parametric` module

- Status: **Accepted** (2026-11-06). The owner, Marc Prinzing, accepted all eleven recommendations of "Decisions for the owner" as written (D10, recorded on MAR-244).
- Date: 2026-11-05
- Decision issue: MAR-244 (R-12). It feeds MAR-245 (R-13, golden fixtures, which take their field names from §8), MAR-246 (R-14), MAR-43 (R-15), MAR-247 (R-17), MAR-248 (R-16), MAR-42 (R-18) and MAR-46 (R-19). Phase 2: MAR-45 (R-21), MAR-250 (R-22), MAR-44 (R-23). Questions for RiskThinking go to MAR-249 (R-20).
- Prepared by a worker agent from `main` at `56755a5`. The upstream repositories were cloned read-only and read at these commits. No upstream code was run against CRC data, and no CRC data was downloaded.
  - crc-sdk 0.11.1: [`9c56bb0`][sdk] (tag `v0.11.1`, 2026-11-04);
  - crc-framework 0.6.0: [`838c295`][fw] (tag `v0.6.0`; the later head changes only the release workflow);
  - crc-docs: [`7691f5f`][docs] (2026-11-04).
- Revised on 2026-11-05, before the owner's decision, to match the golden fixtures of MAR-245 (PR #183). The end of "Decisions for the owner" lists what changed.
- Amendments, at the end: 1 (2026-11-06, MAR-275), which records the owner's decision D11, curves first; 2 (2026-11-08, MAR-291), which records the owner's decisions D-25.1 to D-25.5, the per-year route; 3 (2026-11-08, MAR-292), which records the owner's decisions D-21.1 to D-21.6, the portfolio approach; 4 (2026-11-08, MAR-329; revised 2026-11-09 on the owner's decisions after the design review MAR-344: ERA5 leaves scenario sets, and a scenario may be a window of horizons), which records the owner's decisions D-23.1 to D-23.6, scenario analysis; 5 (2026-11-08, MAR-330), which records the owner's decisions D-22.1 to D-22.8, multi-hazard covers; and 6 (2026-11-09, MAR-346), which fixes the public API of the additions the owner accepted in the design review of 2026-11-09 (MAR-344).

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

Amendment 4 (scenario analysis) adds `ScenarioSet`, `compare_scenarios`, `to_drift`, `.scenarios(...)`, and `scenario=` and windows of horizons on `sample_curve`.

Amendment 5 (multi-hazard covers) adds to both outlines below: `CompositeIndex`, `IndexComponent`, `.component()`, `SumOf`, `MaxOf`, `StepGrid`, `CappedSum`, `CompoundDamage`, `sample_annual_hazards`, `sample_curve_hazards`, `GaussianCopula`, `CoverPackage`, `split_budget`, `payout_breakdown`, `.hazard`, `.combine` and `.package`.

Amendment 6 (the additions from the design review) adds to the Layer 1 outline below: `HazardNoise`, `HazardBasisRisk`, `compare_pooled`, `bootstrap_intervals` and `design_frontier`.

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

Amendment 5 (D-22.1, D-22.4, D-22.6, D-22.8) corrects the next paragraph: a maximum of payouts can't stay an LP or QP with free amounts, and `Limit` on a `SumOf` bounds the year's total.

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

Amendment 5 (D-22.1) adds `index_components` and `OutcomeSample.component()`: a sample may hold several named hazards at one asset.

- **One draw is one year.** A cover pays once per draw, on that draw's index, against that draw's loss. This is the core's annual basis with one row per year. Several events within a year are out of scope for Phase 1 (§9).
- **One asset per sample in Phase 1** (MAR-43). The asset axis exists, so arrays are (n, 1); a second asset raises `SampleError` until Phase 2. The plan handles several assets as one sample each. So Phase 1 imposes no dependence between assets: it computes no cross-asset sum.
- Arrays are read-only (`setflags(write=False)`). A sample written to Parquet uses the long table above and the metadata key `crc.parametric.sample`.

Amendment 2 (the per-year route) adds pooled samples, whose `period` is a draw number and whose rows record their (year, model, member), and two fields of `SampleProvenance`: `trend` and `pool`.

#### 4.2 Sources and the probability semantics each needs

Amendment 1 (D11) sets the order of release: Monte Carlo from a fitted curve first, per-year values as the second step. The rules below don't change.

Amendment 2 (the per-year route) adds a stated trend option, pooled model-years and a `scenario` label to the per-year source, and says what of the route goes in the Phase 1 upstream PR.

Amendment 4 (scenario analysis) adds `scenario=` and windows of horizons to `sample_curve`.

Amendment 5 adds `sample_annual_hazards`, `sample_curve_hazards` and a user table with several index columns.

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

Amendment 5 (D-22.3) adds a stated rule for the combined loss of several impacts.

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

Amendment 6 (F2) adds `HazardNoise(sigma)` to this table, a model in which the hazard at the asset is the index times a stated random factor, and says what `ImpactNoise` can't change.

- `basis_risk` is a required argument with no default: every sample states its model. `NoBasisRisk()` must be written out.
- An index at a reference point for Monte Carlo samples needs a joint distribution of two curves, which CRC doesn't provide (U11). It waits for Phase 2's dependence models (§9).
- Vulnerability draws from the uncertainty ranges of registry impacts become a model once RiskThinking says whether such ranges exist (Q7).
- **Seeding.** Layer-1 functions take `rng: numpy.random.Generator` as a required keyword wherever they draw. One generator per call. The draw order is fixed and documented: the hazard uniforms first, then the basis-risk model. The provenance records the bit generator's name and its `state` at entry, so a sample can be rebuilt exactly.

**Splits.** `holdout(sample, train_fraction=0.7)` and `year_block_kfold(sample, k)` split by contiguous blocks of `period`, as the core's `splits.py` does. For per-year samples the test block is the latest years. Monte Carlo draws are i.i.d., so a fresh sample with another seed (`fresh_draws`) is the plainer out-of-sample test; the plan offers both. Evaluating a design out of sample on a sample that shares a period with its design sample from the same source raises `LeakageError`.

(Erratum 15, 2026-11-10, MAR-359: this note is new. MAR-354 (R-35) settled in marc272/crc-sdk#35 what "the same source" means in the sentence above. Each source a sample holds is compared by the lineage it has alone, whichever kind of sample holds it: a run of a pool (a plain per-year sample counts as one run), the hazard or index series of a per-year sample, a component of a sample of several hazards, per-year or from curves, or an asset of a joined or drawn sample. So a design on one series, read out of sample on a sample of several hazards or a join that holds the same years of that series, raises `LeakageError`, and the error names the shared sources and the years. The same holds for a one-asset table and a table of several assets with one stated source. Before MAR-354 the check compared whole lineages, so such a pair raised nothing. Disjoint years still pass. A per-year series or a table with no stated source is identified by its data, so two windows of that series, or a one-asset and a several-asset table, aren't linked. A table and an `AnnualSeries` have no comparable identity, and the same series at another asset id is another source. §7 has the record. No decision changes.)

#### 4.5 Dimensions reserved for Phase 2

Amendment 2 (D-25.5) lets a per-year sample state its `scenario` label.

Amendment 4 (scenario analysis) adds `scenario=` on curves and the `ScenarioSet` this section reserves.

Amendment 5 (D-22.1) fills the hazards item below: each component has a name, a unit and a tail.

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

Amendment 5 says what `Limit` means on a `SumOf`: a bound on the year's total.

- `PurePremium()`: `P = E[π]`.
- `CostOfCapitalLoad(rate, q)`: `P = (1 − r) · E[π] + r · CVaR_q(π)`, with r ∈ [0, 1] and q ∈ (0, 1). It is convex in the payout, so the problem stays an LP or QP.
- `Budget(ratio=κ)` means P ≤ κ·E[L]; `Budget(amount=B)` means P ≤ B, in payout units. Exactly one of the two. Premium and E[L] are taken on the design sample.
- `Limit(amount)`: the payout never exceeds `amount` (the family's `amount_constraints`).
- The family's constraints: amounts ≥ 0, monotone if set, and the bounds of `Free`.
- E[U] and weighted CVaR need a budget or bounded amounts; without either, any payout at least as large as the loss is optimal, and `design` raises `DesignError` before solving. MSE needs neither.

#### 5.3 Solver route

Amendment 5 (D-22.5, D-22.6) adds the routes of `SumOf`, `MaxOf` and `StepGrid`.

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

Amendment 6 (F4, F5) adds `unidentified_share`, the probability of an evaluation block that falls where the fill rule set a design's amounts, and says how non-uniqueness is reported along a budget frontier.

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

Amendment 5 adds the level `"package"`, the columns `components` and `design_budget`, and D-22.7's separate table, `payout_breakdown`.

Amendment 6 adds the metric columns `payout_frequency` and `unidentified_share`, the columns of the rank-block flag, the pooled rows of `compare_pooled` and the separate table of `bootstrap_intervals`.

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

Amendment 5 adds `hazard_dependence`, `combine` and `components` to a sample's provenance, and a package's entry to `covers`.

Amendment 6 adds the record of `HazardNoise`, the pooled entries of `setup.evaluations`, `setup.intervals` and `setup.frontier`.

**Hashes.**

- **Cover:** `definition_hash` (§3).
- **Sample:** `content_hash`, the SHA-256 of the canonical bytes of the long table (sorted by period and asset), with the units, the semantics and the scenario.
- **Design:** `design_id`, the SHA-256 of the canonical JSON of the template hash, the objective, the pricing, the budget, the limit, the design options and the design sample's hash. The solver's identity and the time go into the record, not into the id.

**Lineages** (erratum 15, 2026-11-10, MAR-359: this paragraph is new, and §4.4 has the rule). MAR-354 (R-35) added `SampleProvenance.source_lineages` in marc272/crc-sdk#35. On a sample whose rows read several series or streams of draws, it maps each source's name to the lineage that source has in a sample of its own: a component's name on a sample of several hazards, per-year or from curves, and `"hazard"` and `"index"` on a per-year sample with an index series. A component's view keeps the sources it reads. It is `None` on every other sample and left out of `to_document()` when `None`, so the document of a sample that reads one source doesn't change. The lineages have to be recorded: a series with no stated source is identified by a hash of its data, which no provenance document holds, so they can't be rebuilt at check time, and a component's view drops `components`. Tables need no such record, as an asset's lineage is rebuilt from the table's stated source. `content_hash` leaves the provenance out, and `sample.lineage` doesn't change. No decision changes.

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
- **Multi-hazard covers (R-22, MAR-250).** Amendment 5 (D-22.1 to D-22.8) settles this item. `CompositeIndex` (named `IndexDefinition`s), payouts with several `index_names`, `OutcomeSample.index_components`, and the combinator families of §3. Two hazards at one site need a joint distribution; for per-year samples it is the data's own.
- **Scenarios (R-23, MAR-44).** A `ScenarioSet` maps scenario labels to samples with the same assets. `compare` fills the `scenario` column. Robust design (min–max over scenarios, as SPEC §6.5 R1) becomes an objective wrapper, `Robust(objective)`, over a `ScenarioSet`.
  - Amendment 4 (D-23.1 to D-23.6) settles this item: a `ScenarioSet` holds one sample per scenario, `compare_scenarios` fills the `scenario` and `design_scenario` columns, and `Robust(objective)` stays for later.
- **Also reserved:** the semantics value `"event"` (several events per year); a local refinement after the grid; block-bootstrap intervals and pooled k-fold metrics; a second solver backend in `_solver.py`.
  - Amendment 6 (F3) settles the block-bootstrap intervals and the pooled k-fold metrics. The other items stay reserved.

### 10. The issue map

The split into R-14 to R-18 holds, with four adjustments (marked "adjusted"). Amendment 1 (D11) splits R-18 into MAR-42 and MAR-271, and adds R-25 (MAR-274).

Amendment 3 (the portfolio approach) adds the rows of R-21: MAR-298 and MAR-301 to MAR-305, with R-21g deferred.

Amendment 4 (scenario analysis) adds the rows of R-23: MAR-331 to MAR-335.

Amendment 5 (multi-hazard covers) adds the rows of R-22: MAR-336 to MAR-342.

Amendment 6 (the additions from the design review) adds the rows of R-28 to R-32: MAR-347 to MAR-351.

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

## Amendment 4 (2026-11-08, revised 2026-11-09, MAR-329): scenario analysis

On 2026-11-08 the owner, Marc Prinzing, decided D-23.1 to D-23.6 (in chat; recorded on MAR-44 and MAR-329). They fix the public API of scenario analysis (R-23, MAR-44), which the owner calls a core capability of CRC, so this amendment comes before any R-23 issue starts, and the owner approves it before it merges. It builds on Amendments 2 and 3 and on errata 11 and 12. Amendment 5 (multi-hazard, MAR-330) follows it.

**Revised on 2026-11-09, before it merged.** The owner's design review of that day (MAR-344) and his answer on MAR-329, "Accept all", changed this amendment, and he approves the revised text before it merges. ERA5 leaves scenario sets, which reverses his steer of 2026-11-08 ("ERA5 should be a first-class reference") and changes D-23.5 and D-23.6. A scenario may now be a window of horizons, which extends D-23.1 and D-23.4. Five smaller points that were open are settled.

| | Decided on 2026-11-09 | Section |
|---|---|---|
| E1 | ERA5 leaves scenario sets. The reference stays required and named, and the docs use each product's earliest period. A set holds all curves or all per-year series, and two products need `mixed_products=True`, the reference included | "Why ERA5 left the sets", "`ScenarioSet`", "What is refused" |
| F1 | Several (pathway, horizon) pairs under one label form one scenario, an equal-weight mixture of those horizons' draws on the same uniforms. The docs and the notebook lead with windows, and a single horizon stays allowed | "A window of horizons" |
| S2 | `design_on="each"` is the default | "The plan" |
| S3 | A given cover is priced once on the reference's design block | "The premium" |
| S4 | The `n_rows` column stays | "One table" |
| S5 | The check that every scenario in a set reads the same hazard stays | "What is refused" |
| S6 | The new leakage rule sits in the shared check, `_check_out_of_sample`, so a hand-built loop that reuses one generator state raises `LeakageError` | "What is shared" |

The rest of the ADR stands. §2, §4.2, §4.4, §4.5, §6, §7, §9 and §10 keep their text and each carries a one-sentence pointer here, and this amendment says what they now mean, as Amendment 1 did. Every addition has a default, so a call or a plan without scenarios gives the same rows and hashes, with the new columns beside them. The one exception is a Layer 1 call that reuses one generator state across curves out of sample, which now raises (below). The publication rule applies: this amendment presents the options and what each one records, nothing here says that a product, a pathway, a horizon or a design is better than another, and joint designs are described as a method only.

### The six decisions

All six are option (A) of the refinement on MAR-44, as the owner adjusted them. D-23.1, D-23.4, D-23.5 and D-23.6 read as he revised them on 2026-11-09.

| | Decision |
|---|---|
| D-23.1 | Scenarios are a dimension of the module: `ParametricPlan.scenarios(ScenarioSet(...))`, with no separate `ScenarioPlan`. `for_evaluation` accepts several horizons or pathways once scenarios are stated, so `select(horizons=…, pathways=…)` is the way in. Layer 1: `ScenarioSet`, `compare_scenarios`, `to_drift`; the plan equals them row for row. Both routes, pools, individual and joint designs (owner-total rows). A scenario may be a window of horizons of one pathway. Min-max robust design stays for later |
| D-23.2 | One table: every cover or design on every scenario's evaluation block, out of sample only, the reference included. `scenario` says where a row is evaluated and `design_scenario` where it was designed. Terms, loss model, values, basis-risk model, pricing and metric options stay fixed. Curves share one set of evaluation draws, separate from the design's. `to_drift(table, reference=)` adds differences and ratios, with no ranking column |
| D-23.3 | `premium` and the net-loss columns stay at the contract price: a design's premium, or a given cover's stated premium or its premium priced once on the reference (`premium_basis="reference"`). A new `premium_repriced` prices the same payouts on each scenario |
| D-23.4 | `scenario` stays a free label (D-25.5). New columns `pathway` (the source's spelling, checked with `strict=True`), `horizon` (the curve's year, or the centre of a window, of horizons or of a per-year series) and `product` come from the source record, never the label, and are null where it states none. Nothing interpolates between horizons: a window is a mixture, not an interpolation |
| D-23.5 | `ScenarioError` for scenarios that differ in anything but the hazard (assets, units, loss or basis-risk model, trend option, a pool's models); a stated pathway the source contradicts; two scenarios with one pathway, horizon and product; equal curves at several horizons (CRC Open's cyclone); a horizon outside the dataset's window; a cover bound to a location a scenario's index doesn't read; a set that holds both curves and per-year series; several pathways in one window; and two products in a set, the reference included, unless `mixed_products=True`. The setup text says the difference includes the products wherever a row's product differs from the reference's |
| D-23.6 | The reference is required and named, and the module chooses none. The docs and the notebook use the earliest window (or the earliest horizon, where a single horizon is used) on CRC Open and the same models' `historical` years on NEX. ERA5 is not a first-class reference |

### Why ERA5 left the sets (E1, 2026-11-09)

D-23.6 first read "The reference is required and named. ERA5 is a first-class reference on both routes. Otherwise the earliest horizon on CRC Open and the same models' `historical` years on NEX". D-23.5 first ended "and two products among the non-reference scenarios unless `mixed_products=True`. ERA5 as the reference beside model output needs no flag, and the setup text always says the difference includes the products".

The owner changed both after an internal check at one site, and not on a judgment of ERA5's quality. The ratio of expected payouts against ERA5 moved with the block of years used and always includes the products, while the ratio between two horizons of one product doesn't include them. A design on a short record left its upper amounts to the fill rule. The evidence and its setup are on MAR-329 and MAR-344. One site, one hazard and one cover can't say that any product, pathway or design is better, and this paragraph doesn't.

ERA5 keeps its other jobs: the back-test on real years, the per-year route (D-25.1), the dependence source for `EmpiricalCopula` (D-21.5, D-22.2), the index read elsewhere (`.index(...)`, D-25.4), and comparing indices on one loss. None of them needs a scenario set.

### `ScenarioSet` (D-23.1, D-23.6, §4.5, §9)

```text
# scenarios (R-23b); frozen; no I/O
ScenarioSet(entries=(), *, reference, labels=None, mixed_products=False)
    # entries: one OutcomeSample per scenario (Layer 1), or what a plan reads (Layer 2, below)
    # reference: required, the label of one scenario
    # labels: Layer 2 only, a mapping from a label to its (pathway, horizon) pairs
    .reference -> str
    .labels -> tuple[str, ...]           # Layer 1 only: the reference first, then as given
    .sample(label) -> OutcomeSample      # Layer 1 only
ScenarioError                            # a SampleError, so also a ValueError
```

- **Built or described.** A set holds built samples or a plan's descriptions, never both, and `compare_scenarios` and `.scenarios(...)` each refuse the other kind with a `TypeError`.
- **All curves or all years (D-23.5).** Every scenario of a set is read from curves, one horizon or a window of them, or every scenario is read from per-year rows: a series, a pool or a table. A sample's `provenance.source_kind` says which: `"monte_carlo"` is curves, and `"annual"` and `"table"` are per-year rows. Years beside draws raise `ScenarioError`.
- **At Layer 1** each entry is one scenario's evaluation block, a one-asset or multi-asset `OutcomeSample`. Its label is the sample's own `scenario` (D-25.5), so a sample keeps one name, which is in its hash. Two samples with one label raise, and the error names `scenario=`, which R-23a adds to `sample_curve`, `sample_curves` and `OutcomeSample.from_table`.
- **The reference** has no default and must be one of the labels (D-23.6). It prices a given cover (D-23.3), and it is the default reference of `to_drift`. The module doesn't choose one. `docs/parametric.md` and the notebook use the earliest window on CRC Open, which has no historical baseline, and the same models' `historical` years on NEX.
- **One scenario is allowed**, the reference alone. Then `compare_scenarios` gives `compare`'s rows on that block, except that a cover given as is takes D-23.3's premium.
- **The refusals** that need the samples run at construction on a Layer 1 set and at execution on a plan, through one function. Those that need only the labels run at construction on both.

### The plan (D-23.1, §2, Layer 2)

```text
ParametricPlan
    .for_annual_extremes(..., hazard_name=None)                   # the hazard its own source reads
    .scenarios(scenarios, *, design_on="each", premiums=None)     # R-23d
    .scenario_samples() -> Mapping[str, Mapping[str, OutcomeSample]]    # execution; label, then asset

# what a plan reads, beside its own source: AnnualScenario on a per-year plan, CurveScenario on a plan on curves
AnnualScenario(label, source, *, provenance, unit=None, location=None, year_column=None, hazard_column=None,
               years=None, missing=None, trend=None, pool=None, pathway=None, hazard_name=None)
CurveScenario(label, dataset, *, pathway=None, horizon=None)         # horizon: one year, or several for a window
```

- **The way in, on the curve route.** `for_evaluation(request)` keeps refusing several hazards, but no longer several horizons or pathways. `.scenarios(...)` comes after it, so that check moves: `explain()` and every execution point raise today's `ValueError` when several horizons or pathways are selected and no scenarios are stated.
  - With `.scenarios(...)`, the request's `select(...)` must state exactly one hazard in `hazard_names`, and `horizons` and `pathways`, so `explain()` can list the scenarios and their hazard without reading anything.
  - Without `labels=`, every selected (pathway, horizon) is one curve scenario, labelled `<pathway>_<horizon>`.
  - `labels=` maps a label to its pairs. `labels={"2050s": [("ssp585", 2045), ("ssp585", 2050), ("ssp585", 2055)]}` is a window ("A window of horizons", below), and `labels={"mid-century": [("ssp585", 2050)]}` a single horizon. When given it lists exactly the pairs used, because a dataset need not hold every pair of the product, and every pair it lists must be selected.
  - One `.monte_carlo(n_draws, seed=...)` serves every curve scenario.
  - With nothing else to read, `ScenarioSet(reference="2030s", labels=...)`, or `ScenarioSet(reference="ssp585_2030")` for single horizons, is the whole statement: `entries` stays empty on a plan whose scenarios all come from the selection. An empty set raises at Layer 1.
- **`AnnualScenario`** is a scenario read from per-year values on a per-year plan, such as another pathway's years. `source` takes what `for_annual_extremes` takes. On a plan on curves it raises `ValueError`.
  - The plan's own source is one scenario, under its `scenario=` label, and a field left `None` takes the plan's value. `impact`, `value_column`, `context`, `cell` and `seed` are the plan's, so they are not options.
  - `pool=None` takes the plan's `pool=`, `pool=False` states a series that is not pooled, and a `ModelPool` states one.
  - `pathway=` states a pathway. It fills the column where the source states none, and must agree with the source where it does (D-23.5).
  - `hazard_name=` states the hazard it reads, as "What is refused" sets out.
- **`CurveScenario`** is a scenario read from another local canonical dataset with the plan's assets. It reads the plan's selected hazard. `pathway` and `horizon` pick its curves and are required if it holds several, and several years in `horizon` make a window of that pathway. On a per-year plan it raises `ValueError`.
- **A second product (D-23.5).** It needs `mixed_products=True`, the reference included, and the docs don't lead with it. Two forms stay possible. On a plan on curves, a `CurveScenario` of another product's curve, such as ERA5's own fitted curve (`HazardDataset.era5(recipe)…canonicalize(...).materialize(path)`). On a per-year plan, an `AnnualScenario` with `pool=False`, such as ERA5's years beside NEX pools.
- **`design_on`.** `"each"`, the default, designs every template under every objective on every scenario's design block, which makes "drift" and "a design per scenario" slices of one table. `"reference"` designs on the reference's only.
- **`premiums=`** maps a `cover_label` to a stated premium, for covers given as is (D-23.3). A key that matches no such cover raises `EvaluationError`.
- **`.split(...)` is required**, because the rows are out of sample only (D-23.2): without it `explain()` and every execution point raise `ValueError`. One rule makes each scenario's design and evaluation blocks:

  | `.split(...)` | Curve scenarios | Per-year scenarios |
  |---|---|---|
  | `FreshDraws(n, seed=)` | Design on the plan's draws, evaluate on the fresh draws | `TypeError`, as today |
  | `Holdout(f)` | First share of the draws, then the rest | First share of the years, then the rest |
  | `KFold(k)` | One block per fold | One block per fold |
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
- `reference=None` takes the set's reference, from the metadata. Any label in the table may be stated instead, so differences can be taken from another scenario than the set's reference.
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

| Column | A curve | A window of curves | A per-year series | A pool | A table |
|---|---|---|---|---|---|
| `pathway` | The canonical row's `pathway` | The members' one `pathway` | As `setup_text` reads it (Amendment 2): the source's or the series' `pathway`, or the one-valued `scenario` column of a table with `model`, `member` and `scenario` | The runs' one pathway (D-25.3) | Its source's `pathway`, else null |
| `horizon` | The canonical row's `horizon` | `(first + last) // 2` of its members' horizons | `(first + last) // 2` of the series' whole window, `details.years`, as `TemporalWindow.horizon` | The same, on the pool's years | Null |
| `product` | `metadata.source.provider` | The same | The series' `source.provider` | The runs' provider | Its source's `provider`, else null |

- **`pathway`** keeps the source's spelling. A strict read (below) checks it with `crc_sdk.pathways.resolve_pathway(label, strict=True)`: an unknown label raises `ScenarioError`, and `register_pathway` adds a private one. Comparisons use `pathways_equivalent`, so `historic` and `historical` are one.
- **`horizon`** on a per-year sample is the window's centre, not the block's: `details.years` survives a split, so a scenario's blocks have one horizon. 1985–2014 reads 1999 and 2041–2070 reads 2055. Under `LinearTrend` the values are at the reference year's level, which the setup text states, and the column still gives the centre. On a window of curves it is the centre of the members, and the members are in the record ("A window of horizons").
- **`product`** is the record's `provider` as written, so a CRC Open row reads `crc_open`, an ERA5 row `era5`, and a native CMIP6 row `cmip6`. On the plan route a per-year source's provider is the caller's `SourceProvenance.provider`; the docs use `nex-gddp-cmip6` for NEX.
- **Nothing interpolates.** A scenario is a horizon the dataset holds, or several of them. Between two horizons there is no row. A window is a mixture, not an interpolation: every row is a draw from a curve the dataset holds, and no parameter, return level or value is computed between two curves. Its `horizon` column names the centre, and no row need be read there.
- **Several sources in one sample** (several assets; Amendment 5's components) must agree on `pathway`, `horizon` and `product` on a strict read, or `ScenarioError` says which. Amendment 5 may relax this for `product`.
- **A strict read** (erratum 17, 2026-11-10, MAR-359). MAR-331 (R-23a) settled which reads are strict, in marc272/crc-sdk#39. `compare`, `evaluate`, `payout_breakdown`, `compare_pooled` and `bootstrap_intervals` read a sample strictly when a caller gave it a `scenario=` label other than the default, `"baseline"`. `ScenarioSet` and `compare_scenarios` read every sample strictly, whatever its label. Any other read keeps what this amendment's opening says of a call without scenarios: the pathway stands as spelled, and a field the sources disagree on is null. A window is checked at its builder, whatever its label ("A window of horizons"). The `pathway` bullet first read "**`pathway`** keeps the source's spelling and is checked with `crc_sdk.pathways.resolve_pathway(label, strict=True)`. An unknown label raises `ScenarioError`, and `register_pathway` adds a private one." The bullet on several sources first read "must agree on `pathway`, `horizon` and `product`, or `ScenarioError` says which." No decision changes.

### What is refused (D-23.5)

Each `ScenarioError` names the two scenarios and the field.

| Refusal | What is compared | Between |
|---|---|---|
| Assets | `asset_ids`, in order | All |
| One kind of scenario | `source_kind`: curve draws, or per-year rows | All |
| Hazard (an addition to D-23.5, below) | The name of the hazard each scenario reads, exactly | All |
| No hazard named (the same addition) | A scenario whose record states none | Each scenario |
| Units | `index_unit`, `loss_unit`, exactly | All |
| Loss model | The `loss_model` document per asset (`parts` on a multi-asset sample) | All |
| Basis-risk model | The `basis_risk` document | All |
| Trend option | `trend`'s kind, with `n` or with `method` and `min_years`. A reference year or the fitted slopes may differ | Per-year scenarios |
| A pool's models | The (model, member) pairs | Pools; and a series that isn't a pool beside a pool, unless `mixed_products=True` |
| A contradicted pathway | A stated `pathway=` against the source's, by `pathways_equivalent` | Each scenario |
| One pathway, horizon and product | The three values, null equal to null; for a window of curves, its members instead of its centre | All |
| Equal curves | The curve documents of any one asset, each distinct (pathway, horizon) of the set once, a window's members included | Curve scenarios |
| A horizon outside the window | Each selected horizon, and each member of a window, against `temporal_window`, the test of `warn_if_outside_window(strict=True)`, a warning today | Each curve scenario |
| A pair the dataset doesn't hold | Every selected (pathway, horizon), and every member of a window, for every asset | Each curve scenario |
| A window's pathway | The members' `pathway`, by `pathways_equivalent` | Each window |
| A window's members | Hazard, cell and dataset must be one, and `horizon` must differ, member by member | Each window |
| A window's draws | `n_draws`, and `FreshDraws(n)`, a whole multiple of the number of members | Each window |
| A bound cover | The table below | Each cover and scenario |
| Two products | The `product` strings, a null beside a string counting as two, unless `mixed_products=True` | All, the reference included |
| Draws not shared | `period` and the generator records (below) | Curve scenarios |
| Dependence | The `dependence` document, without an `EmpiricalCopula`'s `k` | Curve scenarios |

A set of CRC Open windows has one product, and needs no flag. The reference is no exception: a second product beside it needs the flag too.

(Erratum 18, 2026-11-10, MAR-359: MAR-332 (R-23b) settled three readings of this table in marc272/crc-sdk#41. "Dependence" first read "The `dependence` document". An `EmpiricalCopula`'s `k` counts one member's draws per reference year, so a window beside a single horizon on the same draws records two values of it, and comparing the documents whole would refuse what "Overlaps and widths" allows. So `k` is left out, of `dependence` and of Amendment 5's `hazard_dependence`, and the rest is compared, so another reference still raises. "Two products" first read "The `product` strings, unless `mixed_products=True`". A null `product` beside a string counts as two products, so a scenario whose source states no provider needs `mixed_products=True` beside one that does. A per-year series beside a table is one kind of scenario, so "One kind of scenario" passes the pair, and "Loss model" refuses it, because a table states none. No decision changes.)

| A cover read at | Is evaluated on a scenario whose index is |
|---|---|
| `AtAsset()` | Any: each scenario reads its own index at the asset, and `product` says which |
| `AtPoint(p)` | A per-year series whose matched cell is centred at p, compared as `.index(...)` compares a bound location |
| `AtStation(id)` | A per-year series of that station |
| `AtCell(c)` | A curve at H3 cell c |

**Which hazard a scenario reads (an addition to D-23.5, which the owner kept on 2026-11-09, S5).** D-23.5's list would let a set put one source's `rx1day` beside another's `rx5day` when their units agree, because a per-year sample records no hazard name. So every scenario of a set names the hazard its loss reads, and two that differ raise `ScenarioError`, naming the two scenarios and `hazard_name`. Names are compared exactly: crc-sdk has no crosswalk of hazard names, as `crc_sdk.pathways` is of pathways, and this amendment adds none.

| A scenario that is | Its name comes from | `hazard_name=` | If nothing states one |
|---|---|---|---|
| One of the plan's selected curves | The canonical row's `hazard_name`, which `select(hazard_names=[name])` picks | None. `.scenarios(...)` requires exactly one selected hazard, so `explain()` names it without I/O | Can't happen: a canonical row holds one |
| A `CurveScenario` | The same column of its own dataset, read for the plan's selected hazard | None. It reads the plan's hazard, so it needs no argument | A dataset with no curve of that hazard raises `ScenarioError`, naming the hazards it holds |
| An `AnnualScenario`, or a per-year plan's own source | The source plan's `explain()`, its `recipe` (ERA5 and CMIP6 canonicalization plans, station plans) and otherwise its `hazard_name`; or a one-valued `recipe` column of the table (NEX-GDDP-CMIP6) | `AnnualScenario(hazard_name=)` and `for_annual_extremes(hazard_name=)`. Optional where the source states a name, and then the two must agree. Required where it doesn't: a plain table or file, NOAA water levels, or a `recipe` column with several values | `ScenarioError` at execution, naming the scenario and `hazard_name`. The plan's own hazard is not a default |
| A curve sample at Layer 1 | The canonical row passed as `curve` | `sample_curve(..., hazard_name=None)` and `sample_curves`. Required for a distribution or `CurveParameters`, which hold no row | `ScenarioSet` raises |
| A per-year, pool or table sample at Layer 1 | Its `source=` document's `recipe` or `hazard_name`, or the one-valued `recipe` column | `sample_annual`, `sample_annual_pool` and `OutcomeSample.from_table`, under the same rule | `ScenarioSet` raises |

- **A stated name never overrides the record.** A `hazard_name=` the source contradicts raises `ScenarioError` at the builder, naming the scenario and both names, as a stated pathway does. A name stated for a source that is silent is the caller's statement, and the setup text says so.
- **Spelling.** A product that spells one hazard differently is refused: a station plan's `recipe` is `temperature_max`, ERA5's `txx`. Its table, passed without the source plan, is silent, so it takes a stated name.
- **Only a set requires a name.** `hazard_name=None` is the default everywhere, so a sample without one stays valid, and a call or a plan without scenarios doesn't change.
- **When it is known.** A source plan states its name before anything is read, so `explain()` shows it and raises on a difference. A table's or a file's is known at execution.
- **The record.** `SampleProvenance` gains `hazard`, with a default: `{"name": name, "from": "curve_row" | "source_plan" | "table_column" | "stated"}`. It stays out of `content_hash`, `design_id` and the lineage, so §4.4's check sees through it. On a sample with a `scenario=` label other than the default, every asset and every run of a pool must agree, and two names raise `ScenarioError` at the builder. With the default label such a sample records none. (Erratum 17, 2026-11-10, MAR-359, in "What a row says it read": the last two sentences first read "Every asset of a sample and every run of a pool must agree.")
- **Which series.** The name is that of the series the loss reads, the source with role `"hazard"`. A separate index series may read another hazard on purpose (D-25.4), so it isn't compared, and the setup text names it.

### What is shared (D-23.2)

A scenario's *evaluation block* is the rows its out-of-sample metrics are taken on: fresh or held-out draws for a curve, held-out years for a per-year series or a pool.

| | Curves beside curves | Years beside years |
|---|---|---|
| Terms, loss model, values, basis-risk model, pricing, metric options | The same | The same |
| The rows of the blocks | The same uniforms, row by row | Each scenario's own held-out years |
| The number of rows | Equal | Each scenario's own |
| Noise factors of a model that draws | The same, row by row | From the asset's generator, the same start in every scenario |
| What the leakage check compares | (generator record, draw number) | (lineage, year); (run lineage, year) on a pool |
| `leakage_check` on a cross row | `"passed"` | `"passed"` if a lineage or run is in common, else `"different_sources"` |

**Curves share one set of evaluation draws.** Every Monte Carlo block of a set must hold the same `period` values and the same generator record for each `hazard` step of each asset (`provenance.rng`, or `parts` on a multi-asset sample). So each asset's row d holds one uniform in every curve scenario, and, since the basis-risk model draws after the uniforms (§4.4), one noise factor. The dependence models reorder by the ranks of the uniforms and a stated reference only, so the reordering is the same in every curve scenario of one width too ("A window of horizons"). Otherwise `ScenarioSet` raises `ScenarioError`, naming `rng` or `period`. A Layer 1 caller builds each block with a new generator from one seed sequence. Reusing one `Generator` object advances it, and the check refuses that. The plan rebuilds each asset's child generator per scenario, from the plan's seed for the design draws and from `FreshDraws.seed` for the evaluation draws.

**Separate from the design's.** §4.4's leakage check (`_check_out_of_sample`) gains a rule: two Monte Carlo samples share a draw when a `hazard` step of one has the generator record of a `hazard` step of the other and they have a period in common, whatever the curve. That raises `LeakageError`. Today such a pair passes, since another curve has another lineage, and the setup text says "on fresh Monte Carlo draws". The blocks of one `holdout` still pass: their periods are disjoint. It sits in the shared check, so it holds in `evaluate` and `compare` too, and a hand-built loop that reuses one generator state raises `LeakageError` (S6).

**The split method.** `setup.evaluations[*].method` gains `"other_scenario"`, used by `compare_scenarios` when the design sample's label differs from the block's. It takes precedence over the block's own split step, because today a held-out block of another source reads `"holdout"`. For a cover given as is the design sample is the reference's design block. `details` records the block's own split, under `block`. (Erratum 19, 2026-11-10, MAR-359, in "The metadata": the first sentence first read "`setup.evaluations[*].method` gains `"other_scenario"`, used when the design sample's label differs from the block's.")

**Cross rows.**

- **`design_scenario` and `scenario` name blocks.** They don't say that the two are comparable. The terms are the resolved design's, in index units. A threshold set on one scenario's values is read on another's as it stands, and nothing rescales it. A cross row says what the same terms would pay on that block.
- **`"different_sources"`** is recorded on a cross row between per-year sources with no lineage or run in common, such as `historical` and `ssp585` pools. It says that no row could be compared, not that the sources are independent. Two runs may share a history or a calibration, and the module can't see that.
- **Short blocks.** On a block of n rows, CVaR at β with (1 − β)·n ≤ 1 is the block's worst row, and a return period above n reads its largest value. On 14 held-out years that holds for β = 0.95 and 0.99 and for T = 25 and above of the default options. `n_rows` shows the count and the setup text names the columns concerned.

**What the setup text says.** `setup_text` states, next to the numbers:

1. Every scenario: its label, whether it is the reference, the hazard it reads and whether the caller stated that name, its product, pathway and horizon, its rows (years with their range, or draws), and how the block was made. For a curve scenario, whether it is a single horizon or a window. For a window, its members, that they are mixed with equal weight on one set of uniforms, that `horizon` is the centre, and each member's rows on the block.
2. What stays fixed, and that a cross row is a cover or design from one scenario on another's block, naming both.
3. For curve scenarios, that they share one set of evaluation draws, separate from the design's.
4. Where a row's product differs from the reference's, that the difference includes the products: resolution, method and pooling differ, so it can't be attributed to the scenario alone.
5. Where each scenario reads the index: the nearest cell or the station, or the asset's H3 cell.
6. The premium basis of every cover, and that `premium_repriced` prices the same payouts on each block.
7. Whether a design's budget moves with the scenario (`ratio`) or not (`amount`).
8. For `product` `cmip6`, crc-sdk's own caveat: results are change signals, not design values.
9. That β is the same on every scenario while the tail's loss level isn't, and the short-block columns above.
10. Where a set holds windows of different widths, or a window beside a single horizon, that the difference includes the width.

### A window of horizons (D-23.1, D-23.4; F1, 2026-11-09)

**Why.** A single horizon can be noisy. On the same internal check, adjacent 5-year horizons of one product could move a cover's expected payout by more than the trend between them, at one site, on one hazard and one cover. The evidence is on MAR-344. RiskThinking's `how_hard_will_it_rain` in crc-docs averages several horizons for the same reason: three on its CDT route, four or five on its CRC Open route. So several (pathway, horizon) pairs under one label form one scenario, a *window*. `docs/parametric.md` and the notebook lead with windows. A single horizon stays allowed, and the setup text says it is one.

**What it is.** A window is an equal-weight mixture of its horizons' curves: one simulated year of the window is a draw from one of its members, each member equally likely. It holds one pathway, and a second raises `ScenarioError`. Each row is a draw from a curve the dataset holds, so a window interpolates nothing.

```text
# a window of horizons (R-23a); no new public name
sample_curve(curve, *, ..., scenario="baseline", hazard_name=None)
    # curve: what §4.2 takes, or a sequence of two or more canonical rows, the members
sample_curves(curves, *, ...)
    # each asset's curve: the same, with the same horizons for every asset
```

- **The members** are one asset's curves of one hazard, cell, pathway and dataset, and differ in `horizon` alone. They are canonical rows, because a bare distribution states no pathway or horizon. They are sorted by horizon, so the order they are given in doesn't matter. The dataset is the call's one `metadata=`. A row's `source_id` isn't compared: it names a source pixel, and one cell may hold a different one at each horizon. At the builder, whatever the label, a member whose pathway `crc_sdk.pathways` doesn't know, members under two pathways, and assets or components whose windows differ raise `ScenarioError`. (Erratum 17, 2026-11-10, MAR-359, in "What a row says it read": the last three sentences are new.)
- **The rows.** The asset's generator draws `n_draws` uniforms once, as for one curve. With m members, row d reads member d mod m at its uniform u_d. So `period` is still the draw number, `n_draws` the number of rows and 1/n_draws the probability, and the sample has the one `hazard` generator record of a single curve. The basis-risk model draws after the uniforms, as in §4.4.
- **`n_draws`** must be a whole multiple of m, so every member holds exactly n_draws/m rows. Otherwise `ScenarioError` names the two nearest valid counts, as `EmpiricalCopula` does. The same holds for `FreshDraws(n)`, and on a plan `explain()` checks every window.
- **Blocks.** `holdout` and `year_block_kfold` cut contiguous periods, so the cycle leaves every member within one row of the others on every block, and each block is a mixture of all the horizons. Their probabilities are rescaled as for any block. With 30,000 draws, three members and `Holdout(0.7)`, the design block holds 7,000 rows of each and the held-out block 3,000 of each.
- **Common random numbers.** Row d holds the same uniform in every curve scenario, whatever its number of members, and two windows of equal width read the same position of their members. So "Draws not shared" reads the same fields as for single horizons and passes unchanged.
- **`horizon`** is the centre, `(first + last) // 2` of the members' horizons, the formula of a per-year window and of `TemporalWindow.horizon`. (2045, 2050, 2055) reads 2050 and (2045, 2050, 2055, 2060) reads 2052. The centre need not be a horizon the dataset holds.
- **The record.** `provenance.sources` holds one `hazard` entry per member, in horizon order, each with its row and curve document, and `details.window` holds the members as (pathway, horizon) pairs and `"assignment": "cycle"`. A row's member is its `period` modulo m, so a block needs no record of its own. The support, outside-support, atom and tabulated counts of `details` are kept per member. The lineage holds every member's source. `setup.scenarios` repeats the members, and `explain()` lists them without I/O.
- **Several assets or hazards.** A row is one simulated year at one horizon for every asset and every component, so a dependence model reorders within each member's rows. `Independent()`, which keeps draw order, already holds one horizon per row. Applied across the pooled rows, `Comonotonic()` would leave about 1/m of the rows reading one horizon for both assets. `EmpiricalCopula` then needs `n_draws` to be a multiple of m times the reference's years.
- **Overlaps and widths.** Two windows may share members, and a set may hold windows of different widths (numbers of members), or a window beside a single horizon. The setup text says the difference includes the width.
- **One pair under a label** is a single horizon, and a plain `sample_curve` of that curve: nothing about it changes.

| How `n_draws` divides | Rows | Weights | On a 70 % holdout | Assessment |
|---|---|---|---|---|
| **The cycle: one stream of `n_draws` uniforms, row d reads member d mod m** (chosen) | `n_draws` | Exact when m divides `n_draws` | Every block holds every member, within one row | No more random numbers, one generator record as for one curve |
| Every uniform at every member | `n_draws` · m | Exact | Every block holds every member | m times the rows, and the LP with them. On synthetic windows the standard error of E[π] fell by 4 % against the cycle at 3× the rows, and that of CVaR at β = 0.95 by 23 % |
| `n_draws`/m uniforms, each at every member | `n_draws` | Exact | Every block holds every member | The same rows from fewer uniforms. On synthetic windows the standard error of E[π] was 1.65× the cycle's, and that of CVaR at β = 0.95 1.31× |
| Consecutive blocks of `n_draws`/m rows | `n_draws` | Exact | The held-out block reads the last member only | A holdout no longer tests the window |
| A random member per row | `n_draws` | In expectation only | Within sampling error | A second stream, which the shared-draws check would have to compare |
| A quantile of the mixture at each uniform | `n_draws` | Exact on any block | Every block holds the mixture | Needs a numerical inverse of the mean CDF for every kind of curve, and a row is no longer a draw from a stated curve |

**A mixture, not an average of metrics.** The alternative is to run each horizon as its own scenario and average each metric across them.

| Form | What it gives | Assessment |
|---|---|---|
| **A mixture** (chosen) | One sample, one row per scenario, one design per scenario | Every metric, CVaR included, is that metric of one distribution |
| Averaging each metric across the horizons | m rows per window, and a mean of each column | Expected payout and a pure premium agree with the mixture, because expectations are linear. CVaR doesn't: an average of CVaRs is the CVaR of no distribution, and CVaR is concave in the distribution, so the average is at most the mixture's and leaves out the spread between horizons. A design would have no one sample to be made on |
| Averaging the curves' return levels into one curve, as `how_hard_will_it_rain` does for a return-level statement | One curve the dataset doesn't hold | The module would compute a curve between the horizons, so "nothing interpolates" would no longer hold, and it too leaves out the spread between horizons |

**The refusals, for a window.**

| Refusal | For a window |
|---|---|
| One pathway, horizon and product | Compares the members, not the centre. Two labels with the same members raise. Two windows with one centre and different members pass, and so does a single horizon at a window's centre |
| Equal curves | Each distinct (pathway, horizon) of the set counts once, for any one asset. So a window over a time-invariant layer raises, and two windows don't raise for the horizons they share |
| A horizon outside the window, a pair the dataset doesn't hold, a contradicted pathway | Every member. A window never shrinks to the members it finds |
| Hazard, units, loss model, basis-risk model | As for a single horizon: a window reads one hazard through one loss model |
| Two products | A window reads one dataset, so it has one product |
| Draws not shared, dependence | Unchanged: a window's `period` and generator record are those of a single curve |
| A bound cover | `AtCell(c)`: every member at cell c |

### With Amendments 2, 3 and 5

- **`scenario=` (D-25.5)** is the label. The lineage still leaves it out, so §4.4's check sees through a relabelling.
- **`trend=`.** One option for every per-year scenario, and each scenario's fit is on its own design years. `reference_year=None` is each series' last year, so two windows have two reference years, and the setup text states each.
- **Pools.** A pool holds one pathway (D-25.3), so `historical` and each SSP are separate scenarios with the same (model, member) pairs. Their blocks are years, and §4.4's check compares (run lineage, year). `FreshDraws` stays refused.
- **`.index(...)`** applies to every per-year scenario, on that scenario's hazard years, under `missing=`. A station index has no future years, so a future scenario beside it raises. Covers are bound as in D-25.4, and a bound cover follows the table in "What is refused".
- **Several assets.** A set's samples may hold several assets, and all must hold the same ones. Rows have Amendment 3's `level` and `scope`.
- **Joint designs.** Under `Joint()`, each scenario has one multi-asset sample per block, and a `JointDesignResult` gets one `"total"` row per scenario, and allocated rows under `.allocation(...)`. `design_on` applies as for `Individual()`.
- **Dependence.** `.dependence(...)` applies on a plan on curves, as in Amendment 3, and a window reorders within each member. A per-year plan keeps the data's own. An `EmpiricalCopula` set uses `FreshDraws`.
- **D-21.4.** The `scope` column keeps the scopes apart. `to_drift` pairs a row only with the same cover or design, so it never sets one scope against the other. The docs and the notebook run `Joint()` alone until the owner revisits the RQ2 rule (MAR-152 item 4).
- **Amendment 5.** Nothing above assumes one asset or one hazard. A set compares its samples' fields, the generator check covers every `hazard` step, and the three columns read every hazard source. `sample_curve_hazards` takes a window per component under the same rule: a row reads one member for every component, and every member must exist for every hazard. Amendment 5 adds a multi-hazard sample's component names, units and hazard names to the compared fields.

### The metadata (§7)

- `setup.scenarios` (new, null without scenarios): the reference, the labels, `mixed_products`, `design_on` and, per scenario, its source kind, `hazard`, `n_rows`, `pathway`, `horizon`, `product` and `members`: its (pathway, horizon) pairs in horizon order, one pair for a single horizon, null for a per-year scenario. It records which scenarios share draws and the generator record they share. `EvaluationMetadata.merge` requires one `setup.scenarios` across folds.
- Each entry of `setup.evaluations` gains `scenario` and `design_scenario`, so a block has one entry per design scenario. `method` gains `"other_scenario"` and `leakage_check` gains `"different_sources"`, which appears on `"other_scenario"` entries only, so plain comparisons read as before.
- Each entry of `setup.samples` gains `pathway`, `horizon`, `product` and, for a window, `members`. `columns` gains `premium_repriced`. A plan's `source_records` and `sources` hold one entry per dataset or per-year source, each with its scenario's label, and `licences` every input's terms.
- `to_drift`'s table keeps the metadata and adds `drift`, with the reference used. A document without these keys reads as before, and `schema_version` stays `"1.0"`.
- **Beyond this list** (erratum 19, 2026-11-10, MAR-359: this bullet is new, and no decision changes). MAR-333 (R-23c) settled four details in marc272/crc-sdk#42.
  - `compare_scenarios` writes keys this list doesn't name, which the setup text reads. Each of its entries of `setup.evaluations` has `premium_bases`, the `cover_hash`, `cover_label`, `level` and `premium_basis` of each row (statement 6). Each scenario of `setup.scenarios` has `index_read`, where it reads the index (statement 5), and `blocks`, one per fold, each with `fold`, `sample_hash`, `n_rows`, `made` (how the block was made), `member_rows` (a window's rows per member, null otherwise) and `short_block_columns` (statements 1 and 9).
  - A scenario's `n_rows` is the sum over its `blocks`. `merge` compares the rest of `setup.scenarios` and combines the `blocks` without repeats.
  - `setup.scenarios` and `setup.drift` are left out of a document when null, and read as null, so the document of a table without them stays byte for byte.
  - `compare` doesn't write `"other_scenario"`. Only `compare_scenarios` does, so a plain `compare` of a labelled pair keeps its method and plain comparisons read as before.

### What the other sections now mean

- **§2.** The outlines gain the entries above. The module layout gains `scenarios.py` (R-23b, R-23c: `ScenarioSet`, `AnnualScenario`, `CurveScenario`, `compare_scenarios`, `to_drift`). `errors.py` gains `ScenarioError`. `for_evaluation`'s refusal of several horizons or pathways moves as above.
- **§4.2.** `sample_curve` gains `scenario="baseline"` and takes a sequence of canonical rows for a window of horizons. Every sample builder gains `hazard_name=None`, and `SampleProvenance` gains `hazard`.
- **§4.4.** "Evaluating a design out of sample on a sample that shares a period with its design sample from the same source raises `LeakageError`" now also holds for two Monte Carlo samples that reuse one generator record, whatever the curve.
- **§4.5.** "Phase 2 adds a `ScenarioSet`" is this amendment.
- **§6.** "The premium used" gains the case above and the value `"reference"`. The table gains the columns above, and its key gains `design_scenario`.
- **§7.** `setup` gains the entries above.
- **§9, scenarios.** "`compare` fills the `scenario` column" now reads: `compare_scenarios` fills it, with `design_scenario`. `Robust(objective)` stays for later (D-23.1).

### The issue map (§10)

R-23 is split as below (each about one PR). The other rows stand.

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| MAR-331 (R-23a) | `scenario=` on `sample_curve`, `sample_curves` and `from_table`; a window of horizons on `sample_curve` (the cycle, `n_draws` as a multiple of the members, the record, a window's own refusals); `hazard_name=` on every sample builder and `SampleProvenance.hazard`; the columns `design_scenario`, `pathway`, `horizon`, `product` and `n_rows`, with the strict pathway check and a window's centre; `design_scenario` in the key; a table without them reads as null | `sources`, `sample`, `evaluate`, `metadata` | This amendment, MAR-295, MAR-303 |
| MAR-332 (R-23b) | `ScenarioSet`, `ScenarioError`, the refusals of D-23.5 as revised and the hazard check added to them, one test each and one for how each reads on a window; all curves or all years; two products need `mixed_products=True`, the reference included; the shared-draws check; `reference` required | `scenarios` (new), `errors`, `__init__` | R-23a, MAR-296 |
| MAR-333 (R-23c) | `compare_scenarios`, `to_drift`, `premium_repriced`; the premium basis `"reference"`; the split method `"other_scenario"`, and `"different_sources"` for years beside years; the generator-record rule of the leakage check, in `_check_out_of_sample`; the setup text, windows included | `scenarios`, `sample`, `evaluate`, `metrics`, `metadata` | R-23b |
| MAR-334 (R-23d) | `.scenarios`, `AnnualScenario` on per-year plans, `CurveScenario`, `for_annual_extremes(hazard_name=)`, `design_on`, `.scenario_samples`; windows through `labels=`; the moved `for_evaluation` check; results equal the function route; the scenario section of `docs/parametric.md`, the method only, leading with windows and saying that a single horizon is allowed and that β is the same in each scenario while the tail's loss level isn't | `plan`, `scenarios`; `docs/parametric.md` | R-23c, MAR-304 |
| MAR-335 (R-23e) | The notebook section in crc-docs: heavy rain in Toronto, in two sets, one per product. CRC Open `rx1day` in three-horizon windows around 2030, 2050 and 2080, the earliest window the reference, stating SSP5-8.5 only and no historical baseline. NEX pools of the same models for `historical` and two SSPs, `historical` the reference. No ERA5 as the reference. How one fixed cover ages by window. Every number out of sample next to `setup_text`, and each drift a measurement of that setup | crc-docs fork | R-23d, MAR-299 |

`scenario=` and a window on `sample_curves`, and the shared-draws check of a multi-asset curve set, land with the later of MAR-302 and the issue above that owns them.

### Beyond the six decisions

The six decisions don't determine these. The text above settles each as the agent recommends, and the owner's approval of this amendment covers them. On 2026-11-09 he settled S2 to S6 and accepted the others as recommended, except those that existed only because of ERA5 beside curves, which went. The PR lists the alternatives of each.

1. A cross row between per-year sources with no lineage or run in common records `leakage_check="different_sources"`, not `"passed"`.
2. A `ScenarioSet` takes built samples, whose own labels name them, or a plan's descriptions.
3. A selected curve is labelled `<pathway>_<horizon>` unless `labels=` names it, and `labels=` lists the pairs used.
4. `.scenarios(...)` needs `select(...)` to state both `horizons` and `pathways`.
5. `AnnualScenario`, on per-year plans, and `CurveScenario`, on plans on curves, are the plan's descriptions of other sources, and `pool=False` states a series beside pools.
6. `design_on="each"` is the default, so drift and a design per scenario are slices of one table (S2, settled by the owner).
7. A plan with scenarios must state a split.
8. A given cover's `design_scenario` is null, and the key of §6 gains `design_scenario`.
9. "Priced once on the reference" means on the reference's design block (S3, settled by the owner).
10. A stated premium is `premiums=`, keyed by `cover_label`.
11. The generator-record rule sits in `_check_out_of_sample`, so `evaluate` and `compare` get it too, and a hand-built loop that reuses one generator state raises `LeakageError` (S6, settled by the owner).
12. `to_drift` returns a long table, leaves the reference's own rows out, and takes any label as `reference=`.
13. `n_rows` is a column, not only metadata (S4, settled by the owner).
14. A per-year `horizon` is the centre of the series' whole window, not the block's.
15. `product` is the record's `provider`.
16. The dependence model joins the fields that must match among curve scenarios.
17. Equal curves are refused if any one asset's curves are equal, so a time-invariant layer can't read as a measured absence of drift.
18. A pool's models are compared as (model, member) pairs, and a series that isn't a pool beside pools needs `mixed_products=True`.
19. A selected (pathway, horizon) the dataset doesn't hold raises, where `asset_curves()` returns no row and no error.
20. `ScenarioError` is a `SampleError`.
21. `.samples()` holds the reference's samples, and `.scenario_samples()` all of them.
22. An addition to D-23.5: a set compares the hazard each scenario reads, by exact name, with no crosswalk (S5, settled by the owner).
23. A source that states no hazard name needs `hazard_name=`, and the plan's hazard is not a default.
24. A stated `hazard_name=` must agree with the source's, and never overrides it.
25. `CurveScenario` takes no `hazard_name=`: it reads the plan's selected hazard, and `.scenarios(...)` requires exactly one.
26. The name compared is that of the series the loss reads, not a separate index series or a cover's `index.hazard_name`.
27. A window divides `n_draws` by the cycle: one stream of uniforms, row d reads member d mod m. The table above has the options.
28. `n_draws` and `FreshDraws(n)` must be whole multiples of a window's members, while a block of a holdout may leave them one row apart.
29. At Layer 1 a window is a sequence of canonical rows passed as `curve`, with no new public name. A bare distribution can't be a member.
30. `labels=` maps a label to its (pathway, horizon) pairs.
31. A window's `horizon` is `(first + last) // 2` of its members.
32. A window's members are in `details.window` and `setup.scenarios`, not in a column.
33. A dependence model reorders within each member's rows, so a row is one horizon for every asset and component.
34. Windows may overlap and may differ in width, and the setup text says the difference includes the width.
35. `"One pathway, horizon and product"` compares a window's members, not its centre, and the equal-curves check counts each distinct (pathway, horizon) once.

### Not verified

- No R-23 code exists. A throwaway check (2026-11-08, not committed; script and output in the PR) ran the rules on synthetic numbers, the fork's `parametric` at `edcb8b0` and numpy, without any CRC, ERA5 or NEX data:
  - today, the same seed on another curve gives identical uniforms, lineages that differ, method `"fresh_draws"` and `leakage_check="passed"`; one cover on two `"baseline"` samples repeats a row key; two equal curves give equal rows;
  - a held-out block of another curve, or of another source, reads `"holdout"` today;
  - blocks of one `holdout` keep the generator record and have disjoint periods, the basis-risk step's record is equal when the hazard step's is, and `details.years` survives a split;
  - two windows of one series share a lineage, and disjoint windows pass;
  - the arithmetic above: the centres 1999 and 2055, and on 14 rows CVaR at β = 0.95 and 0.99 is the largest value and T ≥ 15 reads it.
- A second throwaway check (2026-11-09, not committed; script and output in the PR) ran the window rules on synthetic Gumbel curves, numpy and the fork's `sample_curve`, `holdout` and dependence models at `ed4c6ee` (a working branch on `parametric` `08975e7`), without any CRC, ERA5 or NEX data:
  - rows taken by the cycle from three members' samples on one generator state equal Q_j(u_d), and the members share their `hazard` and basis-risk generator records;
  - at 9,000 rows and 1,500 seeds, the standard error of E[π] was 1,161 for the cycle, 1,176 for a random member and 1,920 for 3,000 uniforms at each member, and 1,111 for every uniform at every member, at 27,000 rows; that of CVaR at β = 0.95 was 3,020, 3,070, 3,943 and 2,328;
  - under a 70 % holdout of 30,000 rows the cycle held out 3,000 rows of each member and consecutive blocks 9,000 of the last;
  - the mean of the members' CVaR was below the mixture's at β = 0.9, 0.95 and 0.99, and E[π] agreed;
  - `Comonotonic()` on the pooled rows of three members left 33.5 % of the rows at one horizon for both assets, and within each member 100 %.
- The grid route was run for `design_id` and `premium_basis`. No LP or QP design ran, because that environment has no `highspy`.
- The internal check that "Why ERA5 left the sets" and "A window of horizons" refer to is the orchestrator's, of 2026-11-09, on cached CRC Open and ERA5 data at one site. Its results and setup are on MAR-329 and MAR-344. This agent read them there and did not rerun them, and whether they hold at other sites or for other hazards is unknown.
- No CRC Open catalogue, NEX or CMIP6 table or ERA5 data was read for this amendment. So whether the cyclone files declare themselves time-invariant is unknown, hence the refusal on equal curves. How many NEX models share `historical` and each SSP at a site is unknown, and that decides how often the refusal on a pool's models fires. Whether every horizon of a window exists at every site is unknown, hence the refusal of a missing member.
- The sources of a hazard name were checked at `parametric` `68f551c`, by reading the code and running builders and `explain()` on synthetic tables, without reading data: ERA5's canonicalization plan states `recipe`, NEX-GDDP-CMIP6's table carries a `recipe` column and its plan has no `explain()`, NOAA water levels state neither, and a bare distribution holds no row. How many of CRC Open's 59 indices share their spelling with the ERA5, CMIP6 and NEX recipes was not checked; `rx1day` does in their docs.
- A name can only say what a source calls its hazard. A statement for a silent source is taken as given.
- The cost of `design_on="each"` on a large set was not measured.

## Amendment 5 (2026-11-08, MAR-330): multi-hazard covers

On 2026-11-08 the owner, Marc Prinzing, decided D-22.1 to D-22.8 (in chat; recorded on MAR-250 and MAR-330). They fix the public API of covers and samples over several hazards (R-22, MAR-250), so this amendment comes before any R-22 issue starts, and the owner approves it before it merges. It builds on Amendments 2 and 3 and on errata 11 and 12, and it follows Amendment 4 (scenario analysis, MAR-329), which is recorded separately. "With Amendments 2, 3 and 4" below says where they meet.

The rest of the ADR stands. §2, §3, §4.1, §4.2, §4.3, §4.5, §5.2, §5.3, §6, §7, §9 and §10 keep their text and each carries a one-sentence pointer here, and this amendment says what they now mean, as Amendment 1 did. Every addition has a default, so a one-index cover, a one-hazard sample, their documents, their tables and their hashes don't change, and a plan without `.hazard(...)` gives the same rows, with the new columns beside them. The publication rule applies: this amendment presents the options and what each one records, and nothing here says that a payout family, a dependence model or a cover form does better than another.

### The eight decisions

All eight are option (A) of the refinement on MAR-250. The owner took every recommendation and added the design principle below.

| | Decision |
|---|---|
| D-22.1 | Several hazards are another axis, as §4.5 reserves: named `index_components`, with a unit and a tail each, and one asset per multi-hazard sample for now |
| D-22.2 | On the curve route, Amendment 3's `Independent()`, `Comonotonic()` and `EmpiricalCopula(reference)`, applied across hazards by the same reorder, plus `GaussianCopula(correlation)`; always stated, never defaulted |
| D-22.3 | A required `combine=` whenever two or more impacts read the sample, with no default: `CappedSum(cap)`, `CompoundDamage()` or a user rule. A component with no impact needs no rule |
| D-22.4 | A 2-D step table of (m+1)×(q+1) cells, where only the cell below both first thresholds pays nothing |
| D-22.5 | Free thresholds on a grid: a stated grid per breakpoint and an LP or QP at each point of the product, under `max_grid_points` |
| D-22.6 | A maximum of payouts takes existing paths: one free common scale over fixed components stays LP or QP; otherwise the numpy grid over the free amounts |
| D-22.7 | A separate `payout_breakdown` table that adds up to E[π]: each component's payout for `SumOf`, an attribution for `MaxOf`, rows by region for a 2-D grid |
| D-22.8 | The user protocol is open for vectors: the built-ins pass the same gate |

The alternatives of the refinement:

| | Not chosen | Evidence |
|---|---|---|
| D-22.1 | (B) another axis, with several assets and a dependence model over both axes now. (C) the same axis, hazards as pseudo-assets | (C) reuses `join`, but its `"total"` rows would add hazards up. (B) needs a dependence model over two axes that no decision states |
| D-22.2 | (B) Amendment 3's three only. (C) those and a t copula | `EmpiricalCopula` needs per-year data for both hazards, so cyclone or flood would otherwise have only the two extremes |
| D-22.3 | (B) a default `CappedSum(1.0)`, with a warning. (C) user tables only | A default would be an unstated assumption |
| D-22.4 | (B) m×q levels, paying only when both indices are past their first thresholds | Under (A) a year can pay on one hazard alone, and sums and maxima of steps are special cases |
| D-22.5 | (B) fixed breakpoints only, as D-21.6. (C) one axis at a time | (C) finds a local optimum. (A) needs no new code; two free breakpoints per axis at 8 points are 4,096 candidates |
| D-22.6 | (B) a new integer route in HiGHS. (C) evaluation only | (B) is exact, but it grows with the draws and has none of §5.4's ranges. (A) fits two to four free amounts |
| D-22.7 | (B) a Shapley split for every payout. (C) `SumOf` only | (B) needs a stated no-event value per hazard |
| D-22.8 | (B) built-ins only for now | Under (A) the built-ins pass the same gate, so it adds a test and a paragraph of docs |

**What the code says** (the fork's `parametric` at `68f551c`, read and not changed). One index sits at a few gates: `Cover` requires `index_names == ("index",)` and one `tail`, `design` and `evaluate` read one column of `sample.index`, and `OutcomeSample` has one `index` and one `index_unit`. The solve and the metrics generalise: `design._programme` takes any basis, `_order_edges` any partial order, and `metric_values` reads only loss, payout and probability. `LossModel` holds one impact, and `for_evaluation` raises on several `hazard_names`. Per-year sources offer temperature, precipitation and water levels and no wind, so wind and rain need curves under a copula or a user's table. The core has no multi-hazard code, so no golden fixtures are possible: closed forms and reductions to existing parity cases are the test.

### The design principle

The owner's steer: the module is generic in principle, so that users can run their own analysis. **Every piece below is a public, composable building block, so a user can run an analysis the module doesn't name.** The plan composes the same functions, and its rows equal the function route's.

| Piece | Built in | What a user brings | What is recorded |
|---|---|---|---|
| A payout over several indices | `SumOf`, `MaxOf`, `StepGrid` | A class with several `index_names`, through `register_payout` (D-22.8) | Its document, in the cover's hash |
| The rule for a combined loss | `CappedSum`, `CompoundDamage` | A `CombineRule` (D-22.3) | Its document and sentence, as `combine` |
| The dependence between curve columns | `Independent`, `Comonotonic`, `EmpiricalCopula`, `GaussianCopula` | A `DependenceModel` | Its document and sentence, as `hazard_dependence` |
| A multi-hazard sample | `sample_annual_hazards`, `sample_curve_hazards` | A table with several index columns, through `OutcomeSample.from_table` | The table's source and content hash |
| One hazard's view of a sample | `sample.component(name)` | Nothing: it is a view | `selection` records the step |
| Separate contracts as one row | `CoverPackage`, `split_budget` | Their covers and shares | The covers' records and the sum of the budgets |
| What a design minimises, and basis risk | §5.1, §4.4 | `UserObjective`, `BasisRisk`, as today | As today |

A holistic cover against separate covers is the worked example ("Holistic and separate covers"). The same blocks give analyses this amendment doesn't name: a one-index cover designed on the combined loss, `design(template, sample)`; three hazards under one `SumOf`; or a package beside a one-contract `SumOf` of the same terms.

### Several hazards in one sample (D-22.1, §4.1, §4.5)

```text
# components (R-22a)
IndexComponent(values, *, unit, tail, hazard=None, own_loss=None)
OutcomeSample(..., scenario="baseline", index_components=None)
    .component(name, *, loss="own") -> OutcomeSample
OutcomeSample.from_table(table, *, period, asset_id, index, loss, probability=None, hazard=None, own_loss=None,
                         semantics, index_unit, loss_unit, tails=None, source=None) -> OutcomeSample
    # index: a column, or a mapping from component name to column (two or more)
    # with a mapping: index_unit is a mapping by name too, tails is required, and hazard and own_loss are mappings,
    # as is Amendment 4's hazard_name=
```

- **The field.** `index_components` maps each component's name to an `IndexComponent`, two or more, in order, read-only. It is `None` on every other sample. §4.5 reserved bare arrays. It holds objects instead, because D-22.1 gives each component a unit and a tail and `component()` needs each hazard's own loss. `values`, `hazard` and `own_loss` are (n, 1). `values` are finite. `tail` is `"upper"` or `"lower"`.
  - `hazard` is the value the loss model read, kept when it differs from the index, as on the sample (§4.1).
  - `own_loss` is the loss of this hazard alone, in the sample's loss unit. It is `None` for a component with no impact.
- **The primary.** The first component. `index`, `index_unit` and `hazard` hold its values, as §4.5 says, so code that reads one index reads it. `loss` is the combined loss (D-22.3). `OutcomeSample` raises `SampleError` if `index` differs from the first component's values.
- **One asset.** A sample with components holds exactly one asset, or `SampleError` says why. `join` refuses one and `asset()` returns it, as on any one-asset sample. Several assets with several hazards need a dependence model over both axes and come later.
- **Names.** Non-empty, with no surrounding whitespace and no `.`, `+`, `[` or `]`, because parameter names and table columns are built from them. A one-index cover finds its component by name (below), so a name is usually the hazard's.
- **Splits.** `select`, `holdout` and `year_block_kfold` act on every array and keep the lineage. `holdout` and `year_block_kfold` raise on an `EmpiricalCopula` sample as Amendment 3 says, whichever axis the model is on.
- **Hashes and tables.** A one-hazard sample's `content_hash` and `to_table` don't change. With components, the hash document adds `components` (each one's name, unit, tail, values, hazard and own loss), and `to_table` adds the columns `index[<name>]`, `hazard[<name>]` and `own_loss[<name>]`, with the units and tails in `crc.parametric.sample`. Both write `schema_version` `"1.1"`, so a reader that knows only `"1.0"` refuses the table, as `from_written_table` does today, and doesn't drop the components.
- **A user's table.** With a mapping as `index`, `from_table` builds a multi-hazard sample of one asset. Its `loss` column is the combined loss as the caller states it, and `combine` records `{"kind": "table"}`. `hazard_dependence` records `{"kind": "data"}`, as Amendment 3 records a multi-asset table: its rows are what the caller states.

**`component(name, *, loss="own")`** returns that hazard's one-hazard sample, with the same periods and probabilities. Its `index`, `index_unit` and `hazard` are the component's. On a one-hazard sample it raises `SampleError`.

- `loss="own"` holds `own_loss`, so a separate cover can be designed on its own hazard's loss. A component with no impact has none, so the default raises `SampleError`, naming `loss="combined"`.
- `loss="combined"` keeps the sample's combined loss, for a cover on this index designed against what the owner loses in total.
- The provenance is the component's own, from `components`, and `selection` records `{"kind": "component", "name": name, "loss": loss}`, so the setup text can say what a design read. The lineage is the sample's, so §4.4's leakage check still sees the source.
- Under `Independent()` a component holds `sample_curve`'s rows, with `sample_curve`'s `content_hash` for the same generator (R-22e tests it).

**What a cover reads.**

| Cover | On a sample with components | On a one-hazard sample |
|---|---|---|
| One `IndexDefinition` | The component named its `hazard_name`. If there is none, `SampleError` lists the names and names `component(name, loss="combined")` | `index`, as today |
| A `CompositeIndex` | The components of its names, in its order; every name must be in the sample, and each unit and tail must equal the component's | `SampleError` |

A sample may hold components a cover doesn't read. `design` takes the loss of the sample it is given and nothing else: `design(template, sample)` designs on the combined loss, and `design(template, sample.component(name))` on that hazard's own loss. `evaluate` and `compare` read `sample.loss` on a multi-hazard block, so every row of one comparison is on the combined loss.

### Covers over several components (D-22.1, D-22.8, §3)

```text
# covers (R-22a)
CompositeIndex(components)      # a mapping from component name to IndexDefinition, two or more, in order
Cover(index, payout, *, payout_unit, asset_id=None, label=None)     # index: an IndexDefinition or a CompositeIndex
Cover.payout_values(index_values)     # with a CompositeIndex: (n, k), columns in index_names order; returns (n,)
Cover.index_definition -> IndexDefinition | CompositeIndex     # what the cover pays on
Cover.index -> IndexDefinition                                 # a cover on one index; a CompositeIndex raises CoverDefinitionError
```

(Erratum 14, 2026-11-09, MAR-346: the `Cover.index_definition` and `Cover.index` lines of this outline are new, and this amendment first named neither. MAR-336 (R-22a) added them in marc272/crc-sdk#30. `Cover.index_definition` is a public property that returns what a cover pays on, an `IndexDefinition` or a `CompositeIndex`. `Cover.index` keeps its one-index meaning and raises `CoverDefinitionError` on a cover with a `CompositeIndex`, naming `index_definition`. No decision changes.)

- **The document.** A one-index cover's document, its `schema_version` `"1.0"` and its `definition_hash` don't change. A cover with a `CompositeIndex` writes the same six keys with `schema_version` `"1.1"`, so a reader that knows only `"1.0"` refuses it by name, and:

  ```text
  "index": {"components": [{"index": {<an IndexDefinition document>}, "name": "rx1day"},
                           {"index": {<an IndexDefinition document>}, "name": "txx"}],
            "kind": "composite"}
  ```

  It is a list, because canonical JSON sorts keys and the order of `index_names` is part of the terms. `semantics_version` stays `crc-parametric-cover/1`: one row still pays once.
- **The gate.** `Cover` takes a `CompositeIndex` when `payout.index_names` equals its names and `payout.tail` its tails, in order. It raises `CoverDefinitionError` otherwise. The check for a one-index cover is unchanged.
- **The protocol (D-22.8).** §3's `PayoutFunction` holds for vectors. `index_names` lists the components. On a payout with several `index_names`, `tail` is a tuple of one `Tail` per name, `evaluate(index)` takes (n, k) and returns (n,), and `basis(index)`, if it has one, returns (n, n_amounts). `register_payout` adds it to the registry as any other. Built-in and user families pass one gate, and a registered test family designs on the LP and QP routes (R-22a).

### Payouts over several indices (D-22.4, D-22.6, §3)

```text
# payouts (R-22b, R-22c)
SumOf(components)                   # a mapping from component name to a one-index payout, two or more
MaxOf(components, *, scale=1.0)     # the same mapping; scale is a float or Free
StepGrid(breakpoints, levels, *, tail=("upper", "upper"), monotone=True)
    # breakpoints: a mapping from exactly two component names to thresholds, in increasing severity
    # levels: an (m+1) x (q+1) table of floats and Free, rows along the first name; levels[0][0] is 0.0
```

| Family | Payout | Linear in |
|---|---|---|
| `SumOf` | Σ_k π_k(s_k) | Every amount, when every component is `LinearInAmounts` |
| `MaxOf` | A · max_k π_k(s_k) | A, when every component amount is fixed |
| `StepGrid` | θ_{i,j}, with i and j the bins of s_1 and s_2: bin 0 below the first threshold, bin k for b_{k−1} ≤ s < b_k, the last bin from the last threshold up. θ_{0,0} = 0 | Every level |

- **Registry keys:** `"sum_of"`, `"max_of"` and `"step_grid"`. Component payouts are read through the registry, so a user family can be a component.
- **Names.** A component's parameter is `<name>.<its name>`: `rx1day.levels[2]`, `txx.attachment`. `MaxOf`'s scale is `scale`. A grid's are `<name>.breakpoints[k]` and `levels[i,j]`, with no `levels[0,0]`.
- **The grid (D-22.4).** Only the cell below both first thresholds pays nothing, which carries §3's "nothing below the attachment" to two axes, and a year can pay on one hazard alone, in the cells (i, 0) and (0, j). `levels[0][0]` must be 0.0, and `Free` there raises `CoverDefinitionError`. An (m+1)×(q+1) table has (m+1)(q+1) − 1 amounts. `monotone=True`, the default, adds θ_{i,j} ≤ θ_{i+1,j} and θ_{i,j} ≤ θ_{i,j+1}, which is m(q+1) + q(m+1) − 2 rows. Each axis works on its own severity, so mixed tails need nothing more. `monotone=False` is allowed and recorded.
- **Special cases.** A resolved `SumOf` of two steps equals the grid with levels θ_i + φ_j, and a `MaxOf` the grid with max(θ_i, φ_j), with θ_0 = φ_0 = 0. A grid over three hazards comes later.
- **`MaxOf`'s scale.** Free over fixed components, it is the one amount of the LP or QP (below). Free beside a free component amount, it raises `CoverDefinitionError`: the scale would multiply amounts that are free already, so it is not identified.

**The correction to §3.** §3 says that `basis` keeps the shape (n, n_amounts), "so the LP and QP routes need no change". That holds for `SumOf` and `StepGrid`. It is wrong for `MaxOf` with free amounts. With one year of loss 1 and two unit payouts, the amounts (1, 0) and (0, 1) leave nothing uncovered and their midpoint leaves 0.5, so the objective isn't convex in the amounts and no LP represents it.

**`Limit` (§3, §5.2).** §3's "every amount ≤ ℓ" holds for a family whose `basis` rows sum to at most 1: the four built-ins and `StepGrid`. A `SumOf`'s rows can sum to its number of components, so on a `SumOf` **`Limit(ℓ)` bounds the year's total**.

- For every choice of one amount per component, the chosen amounts sum to at most ℓ. Each component pays at most its largest amount and any component can reach it, so that is the worst year. With every component monotone it is one row, the last amounts; otherwise it is Π_k n_k rows, in `a_ub`. The rows of each component's `basis` must not sum above 1 on a design sample, and `design` raises `DesignError` if they do, because the limit rows then don't bound the year.
- On a `MaxOf` with a free scale, with G the largest amount of any component, `Limit(ℓ)` is A ≤ ℓ / G.
- `Limit` stays a constraint on the amounts. It isn't a clip, so nothing caps a payout at evaluation, and no new term enters the cover's document.
- The numpy grid route checks a `LinearInAmounts` candidate against `constraints.upper` only. A total limit sits in `a_ub`, so R-22b makes that check read `a_ub`. Today such a candidate is not dropped, and the design ends in `DesignError`.

### Design (D-22.5, D-22.6, §5.3)

§5.3's table reads as before, and these rows join it:

| Payout | Free shape parameters | Objective | Pricing | Route |
|---|---|---|---|---|
| `SumOf` of `LinearInAmounts` components | none | any built-in | any | one LP or QP on the block basis [B_1 \| … \| B_K] |
| `StepGrid` | none | any built-in | any | one LP or QP, on the one-hot basis of the cells |
| `SumOf` or `StepGrid` | some | any built-in | any | §5.3's grid over the shape candidates, with the LP or QP above at each point, under `max_grid_points` (D-22.5) |
| `MaxOf` with `scale=Free(...)` and fixed component amounts | none, or on a grid | any built-in | any | one LP or QP in one amount, with basis max_k π_k(s_k), at each shape candidate |
| `MaxOf` with a fixed scale, a `SumOf` with a component that isn't `LinearInAmounts`, a user vector payout without `LinearInAmounts`, or a `UserObjective` | any | any | any | §5.3's numpy grid over every free parameter, under `max_grid_points` |

- **The gate.** §5.3's first rows now read "`LinearInAmounts` with at least one amount". `MaxOf` and `SumOf` answer `amount_names()` with `()` when their amounts aren't linear in the sense above, and `design` then takes the numpy grid. So each family keeps one public name, and a user family with no amounts takes the same route.
- **A free breakpoint** needs a grid (§3). Candidates are the product over every free threshold of every axis, restricted to ordered thresholds. Two free breakpoints per axis at 8 points are 4,096 points, of which 784 are ordered when each axis's two breakpoints share one grid.
- **The numpy grid** fits two to four free amounts: four at 10 points each is 10,000 candidates, the default cap, and at 11 points `design` raises.
- **§5.4 applies.** A grid cell that no design year reaches is `unidentified`, and `fill` runs on the two-axis order. A `SumOf`'s amounts may not be identified when two components' columns are linearly dependent, and `unique` says so.
- **`DesignResult`** names parameters as above. Nothing else changes. `design_joint` raises on a composite template, because D-22.1 keeps one asset per multi-hazard sample.

### The combined loss (D-22.3, §4.3)

```text
# the loss of several hazards (R-22d); frozen, numpy only
CappedSum(cap)      # min(sum of the impacts, cap); cap > 0, in the impacts' unit
CompoundDamage()    # 1 - product of (1 - impact); every impact in [0, 1]
class CombineRule(Protocol):
    def to_document(self) -> dict[str, Any]                       # plain JSON, with a "kind"
    def statement(self) -> str                                    # one sentence for the setup text
    def combine(self, impacts: Mapping[str, NDArray]) -> NDArray  # (n,), finite, >= 0
```

- **The order.** Each component's impact comes from its `LossModel`, on its hazard, after the basis-risk model (§4.4). `own_loss` is that impact times the value. The rule takes the impacts, and the combined loss is the rule's result times the value. So `CappedSum(1.0)` of 0.7 and 0.6 is 1.0, and `CompoundDamage()` is 1 − 0.3 · 0.4 = 0.88.
- **Required, with no default (D-22.3).** Two or more impacts without `combine=` raise `SampleError`, naming the rules. `combine=` with fewer than two impacts raises too, rather than being ignored. A component with no impact is left out of `loss_models` and needs no rule. A sample with no impact at all raises: it has no loss.
- **One value.** The loss models must have one value, one `value_unit` and one `value_column`, or `SampleError` says which.
- **A user rule** passes the same gate: the document is plain JSON with a `kind` other than a built-in's, `statement()` is a non-empty string, and the result has shape (n,), finite and non-negative. A bare callable raises `TypeError`, because every rule has a document.
- `CompoundDamage()` raises `SampleError` if an impact lies outside [0, 1]. `ImpactNoise` without `upper=1` can put one there.
- A rule that caps or compounds makes the combined loss smaller than the sum of the own losses. "Holistic and separate covers" says what that does to a budget.

### Samples across hazards (D-22.2, §4.2)

```text
# per-year (R-22d)
sample_annual_hazards(series, *, tails, loss_models, combine=None, basis_risk, asset_id, rng=None,
                      missing="raise", trend=AsRecorded(), scenario="baseline", hazard_names=None) -> OutcomeSample
    # series, tails, loss_models: mappings by component name; the order of series sets the components
    # hazard_names: Amendment 4's hazard_name=, a mapping by component name

# curves (R-22e)
sample_curve_hazards(curves, *, dependence, metadata, n_draws, rngs, loss_models, combine=None, basis_risk,
                     asset_id, assume_semantics=None, outside_support="raise", details=None,
                     scenario="baseline", hazard_names=None) -> OutcomeSample
    # curves, metadata, rngs, loss_models: mappings by component name; the order of curves sets the components
    # dependence: required, no default. Tails come from each dataset's return_period_tail
```

**Per-year values** carry the real dependence: `hazard_dependence` is `{"kind": "data"}`, written "the data's own". The series must hold the same years, or `SampleError` lists each one's years. Under `missing="drop_year"` a year missing from any series is dropped from all of them and listed. The setup text states that two annual maxima of one year may come from different events: the rows are the same years, not the same events. `trend=` is one option for every series, with one fit per series on the same fit years and the same reference year, as Amendment 2 says of an index series. One basis-risk model serves every component and draws in component order from `rng`, and `NoBasisRisk()` warns as for one hazard. `index=` is not offered here: a user's table can state an index that differs from the hazard.

**Fitted curves** carry no dependence. `sample_curve_hazards` mirrors `sample_curves`: each component is what `sample_curve` makes with that component's generator (uniforms first, then the basis-risk model), and the dependence model then puts each component's rows in another order. A row's hazard, index and own loss stay together and no value changes. The combined loss is computed after the reorder. `period` is the draw number. The lineage leaves the model out, as in `sample_curves`.

### Dependence across hazards (D-22.2)

```text
# dependence (R-22e); numpy and the standard library
GaussianCopula(correlation)     # a number in [-1, 1] for two columns, or a positive definite matrix in column order
class DependenceModel(Protocol):
    def to_document(self) -> dict[str, Any]                                      # plain JSON, with a "kind"
    def record(self, n_draws: int, columns: Sequence[str]) -> dict[str, Any]     # what the sample records
    def statement(self, n_draws: int, between: str) -> str                       # the sentence next to a number
    def reorder(self, uniforms: NDArray, columns: Sequence[str]) -> NDArray[int64]   # (n, d): each row's draw per column
```

- **The same reorder.** `Independent()`, `Comonotonic()` and `EmpiricalCopula(reference)` already name their columns, so they serve hazards by the same call, with the component names as `columns`. A model is stated on `sample_curve_hazards` and never defaulted.
- **`EmpiricalCopula(reference)`** takes a multi-hazard `OutcomeSample` of per-year rows holding exactly the sample's components, ranked on each component's `hazard`, or on its values when it has none. Amendment 3's rank blocks, n = k·m, and its ties apply unchanged. It needs per-year data for both hazards, which is why D-22.2 adds `GaussianCopula`.
- **`GaussianCopula(correlation)`** keeps Amendment 3's rule that every model only reorders. With z_j = Φ⁻¹(u_j), the normal scores of each column's own uniforms, and y = z Lᵀ with L the Cholesky factor of the correlation matrix, column j's draw of rank r goes to the row where y_j has rank r. For two columns, y_1 = z_1 and y_2 = ρ z_1 + √(1 − ρ²) z_2. Φ⁻¹ is the standard library's `statistics.NormalDist().inv_cdf`, on uniforms clipped to the open interval. It uses no random numbers beyond the draws. It is a function of the uniforms, so Amendment 4's shared uniforms give one reorder. ρ = 0 equals `Independent()` and ρ = 1 equals `Comonotonic()` row for row, which R-22e tests. `correlation` is the copula's parameter, and the rows' Spearman rank correlation is about 6/π · arcsin(ρ/2).

  | Where the normals come from | Random numbers | ρ = 0 | Assessment |
  |---|---|---|---|
  | **Normal scores of the columns' own uniforms** (recommended) | None | `Independent()`, row for row | Needs Φ⁻¹, which the standard library has. Keeps Amendment 3's rule |
  | A generator the model holds, `seed=` | One stated stream | A random reorder | Needs no Φ⁻¹, but a design and its fresh draws share one rank pattern unless each block has its own seed |
  | Each column's generator, after its draws | More draws from each | A random reorder | Moves the generators, which §4.4's draw order and Amendment 4's shared-draws check would need to take in |
  | A generator seeded from a hash of the uniforms | None moved | A random reorder | A function of the uniforms too, but it loses the exact reductions, which are the plainest test |

- **Mixed tails.** Every model reorders by the values of the draws, not their severity. With one `"upper"` and one `"lower"` component, `Comonotonic()` pairs the most severe of one with the least severe of the other, and the setup text says so.
- **The user protocol.** `DependenceModel` is what the built-ins already do. `sample_curves` and `sample_curve_hazards` take anything that passes one gate, run before the sample is returned, which raises `SampleError` unless:
  - `to_document()` is plain JSON and its `kind` isn't a built-in's, so nothing else can be recorded as `"independent"`;
  - `statement(...)` is a non-empty string, which for a user's model the module writes after its own opening, "The dependence between the hazards is an assumption:", so no model can leave that word out (the built-ins' sentences already open so);
  - `reorder` returns integers of shape (n, d), each column a permutation of 0 to n − 1, so no draw is dropped, repeated or changed;
  - two calls on the same uniforms agree: a model may hold its parameters, but no generator its document doesn't describe.

  A bare callable raises `TypeError`, as for a payout.
- **`GaussianCopula`** is Amendment 3's "comes later": one class, so `sample_curves` takes it too. The union `Dependence` stays exported and gains it.
- **The record.** The sample's `hazard_dependence` holds `model.record(n_draws, components)`, and the setup text prints the model's sentence, so the dependence is always called an assumption.

### Holistic and separate covers (the owner's steer)

**A holistic cover against separate covers is a supported analysis.** One comparison holds, on the same draws and the same combined loss: the 2-D cover designed on the combined loss, each single-hazard cover, and the package of the separate covers as one row.

```text
# separate contracts (R-22b)
CoverPackage(covers, *, label=None)
    # covers: a mapping from component name to a resolved one-index Cover or a design; all covers or all designs
    .covers -> Mapping[str, Cover]
    .payout -> SumOf            # the SumOf built from the covers as designed: every amount fixed
    .as_cover() -> Cover        # the same payout as one contract
    .package_hash -> str        # covers_hash of .covers
split_budget(budget, sample, *, shares) -> Mapping[str, Budget]
    # shares: "own_loss", or a mapping from component name to a share, the shares summing to 1

# the comparison, in full
train, test = holdout(sample)                         # or a second sample of fresh draws, under the same dependence
budgets = split_budget(Budget(amount=B), train, shares="own_loss")
holistic = design(grid, train, objective, pricing=pricing, budget=Budget(amount=B))
rain = design(rain_template, train.component("rx1day"), objective, pricing=pricing, budget=budgets["rx1day"])
heat = design(heat_template, train.component("txx"), objective, pricing=pricing, budget=budgets["txx"])
table = compare([holistic, CoverPackage({"rx1day": rain, "txx": heat}, label="separate")], test, split="out_of_sample")
```

| Row | `level` | `components` | Designed on | `premium` |
|---|---|---|---|---|
| The grid | `"asset"` | `rx1day+txx` | The combined loss | Its design premium |
| Rain's cover | `"asset"` | `rx1day` | Rain's own loss | Its design premium |
| Heat's cover | `"asset"` | `txx` | Heat's own loss | Its design premium |
| `separate` | `"package"` | `rx1day+txx` | Each cover on its own | The sum of the two |

Every row has one `sample_hash`, and its metrics are on the combined loss.

**What a package is.** A `CoverPackage` holds separately designed contracts. Its `.payout` is the owner's "`SumOf` built from covers already designed", with every amount fixed. `compare` and `evaluate` treat it as Amendment 3 treats a set of covers: one row per cover and one row for the sum.

| Option | What it is | Assessment |
|---|---|---|
| **`CoverPackage`** (recommended) | A small frozen type, with the covers or designs by component name | Priced as separate contracts, keeps each design's record, has a label and its own hash, and can't be read as one contract. One new public name |
| A `SumOf` cover built from the designs | One resolved `Cover` | One document and one premium: under a cost-of-capital load that is the load on the sum, not the sum of two loaded premiums, so it needs `premium=` by hand, and the designs' records are lost. It stays available, as `.as_cover()`, for what one contract with these terms would be |
| Amendment 3's mapping, keyed by component name | No new type | No label and no hash of its own, and one form would mean assets on one sample and hazards on another, which breaks once a sample holds both |
| A `contracts=` term on `SumOf` | A flag in the cover's document | Puts a pricing statement in the contract's terms and hash, and `compare` still needs each contract's premium |

- **The covers.** Two or more. Each key is the component the cover reads, so it needn't equal the cover's `hazard_name`. Each is one-index, and all share one `payout_unit` and one `asset_id` (or none). A mix of covers and designs raises `EvaluationError`, as in Amendment 3, and Amendment 3's mapping on a multi-hazard sample raises, naming `CoverPackage`. A package of composite covers is a later, additive option.
- **The rows.** One `"asset"` row per cover, with its own `cover_hash` and `design_id`, and one `"package"` row:

  | Column | The `"package"` row |
  |---|---|
  | `level` | `"package"`: the sum of one asset's separate contracts. `asset_id` stays the asset |
  | `scope` | `"individual"` |
  | `cover_hash` | `package_hash`, so it can't collide with the `definition_hash` of a one-contract `SumOf` of the same terms |
  | `cover_label` | `label`, or the first 12 hex digits of the hash |
  | `design_id`, `unique`, `ties`, `degenerate_tail` | Null, as on a `"total"` row of a set of covers: they describe single designs, which the cover rows carry |
  | `premium`, `premium_basis` | The sum of the cover rows' premiums, and their basis. `evaluate`'s `premium=` states the total instead (`"stated"`) |
  | `design_budget` | The sum of the covers' budget bounds; null if any has none |
  | The metrics | §6 on the combined L_d and π_d = Σ_k π_{d,k} |

  A package's covers listed again as entries of the same `compare` repeat a key, and `compare` raises.
- **The premium** is the sum of the two contracts', each on its own terms:

  | Pricing | The package's premium | The same payout as one contract |
  |---|---|---|
  | `PurePremium()` | Σ_k E[π_k] | The same |
  | `CostOfCapitalLoad(r, q)` | Σ_k ((1 − r) E[π_k] + r CVaR_q(π_k)) | (1 − r) E[π] + r CVaR_q(π), which is at most the sum |

  A loading isn't additive across contracts, because CVaR is subadditive, so the setup text says which contracts a premium prices. Each premium is the one §6 gives that contract: a design's, on its design sample; a cover's as given, priced on the block, or on the reference under Amendment 4.
- **Each cover keeps its own limit.** A `Limit` or `Free(upper=...)` stated at a cover's design is that contract's term, in its amounts. A package has no limit of its own: its largest year is at most the sum of its covers' limits. `Limit(ℓ)` on a `SumOf` template is a different thing, one contract's bound on the year's total, and on a `StepGrid` a bound on every cell. So limits of ℓ_1 and ℓ_2 on separate contracts match a holistic limit of ℓ_1 + ℓ_2 at the largest year only, and the setup text states each.
- **The budget.** A budget is a design's (§5.2), so each row has its own, and `design_budget` shows it. For a like-for-like statement the bounds of the separate contracts sum to the holistic one, under one pricing:

  | Holistic | Separate contracts | The sum of the budgets |
  |---|---|---|
  | `Budget(amount=B)` | `split_budget(Budget(amount=B), train, shares=...)` | B |
  | `Budget(ratio=κ)` | `split_budget(Budget(ratio=κ), train, shares=...)` | κ·E[L] on the combined loss |
  | `Budget(ratio=κ)` | `Budget(ratio=κ)` on each own loss | κ·Σ_k E[L_k], which exceeds κ·E[L] when the rule caps or compounds in some year |

  `split_budget` returns `Budget(amount=...)`, the bound on `sample` times each share. `shares` has no default, because how to split a budget between two hazards is an assumption. `"own_loss"` takes each component's share of the summed expected own losses and raises if a component has no own loss. A mapping states the shares. The third row is a legitimate statement of a different budget: `compare` neither refuses nor adjusts it, and the setup text gives the numbers. Under a cost-of-capital load, equal premiums don't mean equal expected payouts.
- **The same draws and the same combined loss.** There is one multi-hazard sample and one split. `component()` views a block, with the block's periods and lineage, so each separate cover is designed on the rows the holistic cover is designed on, with its own hazard's loss. `compare` evaluates every entry on the held-out block's `loss`, the combined loss. §4.4's check holds for each pair: as Amendment 3 does for a set, `compare` checks the design sample of each contract and of each one-index design against the same component view of the block, and compares a stated `design_sample=` with that view of it.

### `payout_breakdown` (D-22.7, §6)

```text
payout_breakdown(covers, sample, *, split, fold=0, options=MetricOptions(), design_sample=None) -> pyarrow.Table
    # covers: what compare takes; a one-asset sample
```

One row per entry and part, a separate table, with the identity columns of `compare` and `part`, `part_kind`, `expected_payout`, `share` (of E[π], null when E[π] = 0) and `payout_frequency`, P(the part pays more than `options.payout_threshold`).

| Entry | `part` | `part_kind` | What a row holds |
|---|---|---|---|
| A one-index cover | The component's name | `"component"` | The cover's payout |
| `SumOf`, `CoverPackage` | Each component | `"component"` | That component's payout |
| `MaxOf` | Each component | `"attribution"` | Each year's payout, to the component paying most; equal shares when several tie. It is labelled an attribution: one contract pays one amount |
| `StepGrid` | `only:<first>`, `only:<second>`, `both` | `"region"` | The payout of the years where one index is past its first threshold and the other isn't, and of those where both are. A grid has no payout per hazard |
| A user vector payout with `breakdown(index) -> Mapping[str, NDArray]` | Its keys | `"user"` | Its columns, which must add up to the payout |
| A user vector payout without one | `whole` | `"whole"` | The payout |

The rows of one entry add up to its E[π], within the metrics' tolerance, and `payout_breakdown` checks it. The table holds §7's metadata under the same key, and `write_comparison` writes it.

### The plan (§2, Layer 2)

```text
ParametricPlan
    .hazard(name, source=None, *, impact=None, unit=None, tail=None, provenance=None, location=None,
            year_column="year", hazard_column="value", hazard_name=None)       # R-22f
    .combine(rule)                                           # required when two or more impacts read the hazards
    .package(covers, *, label, shares=None)                  # covers: component name to a cover_label in .covers(...)
    .payout_breakdown() -> pyarrow.Table                     # execution
```

- **`.hazard(...)`** adds a component. On a plan on curves, `source` is a second `PortfolioEvaluation` for the same assets, selecting one hazard, horizon and pathway, and its `.impact(...)`, if stated, is that component's impact. The plan's own request is the first component, named by its selected hazard. On a per-year plan `source` takes what `for_annual_extremes` takes, and `.hazard(name, tail=...)` with no `source` names the plan's own hazard as a component and comes first. Amendment 4's `hazard_name=` stays what names a hazard in the record. `for_evaluation` keeps refusing several hazards in one request.
- **`.dependence(model)`** is required on a plan on curves with `.hazard(...)`, and states the dependence across the hazards. On a per-year plan it raises, as today.
- **Refusals** (`ValueError`, at `explain()` and every execution point): `Joint()`, `pool=` and `.index(...)` on a plan with `.hazard(...)`.
- **What is designed on what.** A composite template is designed on the combined loss. A one-index template is designed on its own hazard's loss, `component(name)`; on a component with no impact it raises, naming the function route.
- **`.package(...)`** names one-index templates or covers by label. With a budget on `.objective(...)`, `shares` is required: the budget is the holistic one, and each template named in a package takes `split_budget(budget, block, shares=shares)[name]` on each design block. A template named in no package takes the budget as stated. Without a budget, `shares` raises. With several objectives, each gives one package.
- **Generators.** An asset's child generator (§2) draws the first component, and each other component a generator spawned from that child, in component order. So the first component draws what the one-hazard plan draws.
- `explain()` lists the hazards, the rule, the dependence and the packages, without I/O. `.samples()` returns one multi-hazard sample per asset.

### With Amendments 2, 3 and 4

- **Amendment 2.** `trend=` and `scenario=` apply as above. `pool=` and `.index(...)` raise on a plan with `.hazard(...)`: a pool across hazards would need the same (year, model, member) rows for every hazard, which no decision states, and an index read elsewhere has no per-component form yet.
- **Amendment 3.** A multi-hazard sample has one asset, so `level` takes `"asset"` or `"package"`, `scope` is `"individual"`, and no `"total"` row appears on one. `join` and `design_joint` refuse one. `.dependence(...)` doesn't mean both axes: a plan with `.hazard(...)` can't hold `Joint()`.
- **Amendment 4: scenarios compose, and no concrete blocker was found.** A multi-hazard sample goes through `ScenarioSet` and `compare_scenarios` like any other, and a `CoverPackage` is an entry like any other. On top of Amendment 4's fields, `ScenarioSet` compares:

  | Field | What is compared | Between |
  |---|---|---|
  | The components | Their names, in order | All |
  | Units and tails | Each component's, exactly | All |
  | Hazard names | Each component's name in its `hazard` record, exactly (Amendment 4's check, per component) | All |
  | Loss models | Each component's `loss_model` document in `components` | All |
  | The rule | The `combine` document | All |
  | Hazard dependence | The `hazard_dependence` document | Curve scenarios |
  | Shared draws | `period`, and the generator record of every `hazard` step of every component | Curve scenarios |
  | Equal curves | The curve documents of any one component | Curve scenarios |
  | A bound cover | Each component's location, against Amendment 4's table | Each cover and scenario |

  - **Hazard names.** Amendment 4's check of the hazard a scenario reads applies per component. A component's record is in `components`, stated through `hazard_names=` under Amendment 4's rule where its source is silent, and `SampleProvenance.hazard` is null on a multi-hazard sample, which has several. A component's name isn't taken for a hazard name. A component with no impact reads no loss, so, like a separate index series, it needs no name.
  - **`pathway` and `horizon`** must agree across a sample's components, or `ScenarioError` says which. **`product`** is the one Amendment 4 left open, and it is relaxed: a multi-hazard sample may read several products, and the column holds the distinct providers, sorted, joined by `+`. The two-products check compares those strings.
  - **Premiums.** A package's `premium`, `premium_repriced` and basis are the sum of its cover rows', as for the `"total"` row of Amendment 4's table.
  - **Years beside draws** no longer arise: a set holds all curves or all per-year series. (Erratum 13, 2026-11-09, MAR-329: this bullet first read "Amendment 4's setup statement 11 also covers `hazard_dependence`: the data's own on one side and the stated model on the other." Amendment 4, as the owner revised it on 2026-11-09, removes years beside draws and that statement, so a set never holds both. No other decision changes.)
  - **The plan.** `AnnualScenario` and `CurveScenario` each describe one source, so on a plan with `.hazard(...)` their `source` or `dataset`, and the per-source keywords, take a mapping by component name. Every selected (pathway, horizon) must exist for every hazard. `design_on` applies per design block, and a package is built from the designs on that block.

### The publication rule

- **D-21.4 is read as not covering this comparison.** D-21.4 says no table or figure sets individual against joint until the owner revisits the RQ2 rule (MAR-152 item 4). It concerns joint calibration across one owner's assets. A holistic cover is one contract on one asset's hazards. So this amendment reads D-21.4 as not covering the comparison of a holistic cover with separate covers, and the owner's approval of this amendment confirms or corrects that reading.
- **The module's docs and the notebook** give that comparison as a measurement of a stated setup, out of sample, with no claim that either form is better. `compare` has no rank and no best flag. The same holds for payout families and dependence models.
- Tail statements stay conditional on a stated setup (the RQ1 rule).

### The metadata (§7)

- **`SampleProvenance`** gains `hazard_dependence`, `combine` and `components`, each with a default and null on a one-hazard sample. `hazard_dependence` says where the dependence between the hazards comes from, and a sample with components must state it, as a multi-asset sample must state `dependence`. `combine` holds the rule's document and sentence, or `{"kind": "table"}`. `components` holds each component's own provenance document, by name. The `rng` and `sources` entries name their component.
- **`setup.samples`.** Each entry gains `components` (names, units, tails, whether each has an own loss), `combine` and `hazard_dependence`.
- **`covers`** holds composite documents. A package's entry is `{"kind": "package", "covers": {<name>: <cover hash>}}` under `package_hash`, beside the covers' own entries.
- **`setup.evaluations`.** `level` may hold `"package"`.
- **The comparison table** gains `level="package"` and two columns beside the identity columns, which `to_long` keeps: `components` (string, nullable: what the row's cover reads, joined by `+`; null on a one-hazard sample) and `design_budget` (float64, nullable: the design's budget bound in payout units, the sum on a package; null for a cover given as is). The key of §6 doesn't change. A table without them reads as null, a document without these keys reads as before, and `schema_version` stays `"1.0"`.
- **`setup_text`** states, next to the numbers:

  1. Every component: its name, hazard, unit, tail, where it is read, and its source.
  2. The rule for the combined loss, or that a table states the loss.
  3. `hazard_dependence`: the data's own, with the sentence on annual maxima, or the model's sentence, calling it an assumption. With mixed tails, that dependence is between values, not severities.
  4. For every row: which components its cover reads, what loss it was designed on (the combined loss, or its own), its budget and its pricing.
  5. That every row's metrics are on the combined loss, so a single-hazard cover's row sets its own payout against both hazards' loss.
  6. For a package row: each contract's budget and premium, their sums, that each cover keeps its own limit, and that a loading isn't additive across contracts.
  7. For a `MaxOf` breakdown, that the rows are an attribution.

### What the other sections now mean

- **§2.** The outlines gain the entries above. The module layout gains `combine.py` (R-22d: `CappedSum`, `CompoundDamage`, `CombineRule`). `index.py` gains `CompositeIndex`, `sample.py` `IndexComponent`, `payouts.py` `SumOf`, `MaxOf` and `StepGrid`, `sources.py` `sample_annual_hazards` and `sample_curve_hazards`, `dependence.py` `GaussianCopula` and `DependenceModel`, and `evaluate.py` `CoverPackage`, `split_budget` and `payout_breakdown`.
- **§3.** `Cover` takes a `CompositeIndex` beside an `IndexDefinition`. The `index_names` comment of the protocol and "In Phase 1, `Cover` requires `index_names == ("index",)`" hold for a one-index cover. "So the LP and QP routes need no change" is replaced by "The correction to §3" and §5.3's rows above. "Every amount ≤ ℓ" holds as "`Limit`" above says.
- **§4.1.** `OutcomeSample` gains `index_components` and `component()`. `SampleProvenance` gains the three fields above.
- **§4.2.** The table gains `sample_annual_hazards`, `sample_curve_hazards` and a table with several index columns.
- **§4.3.** `LossModel` keeps one impact. Several go through `loss_models=` and `combine=`.
- **§4.4.** One basis-risk model serves every component. The index at a reference point for Monte Carlo samples stays out of this amendment.
- **§4.5.** "`index_components: Mapping[str, NDArray]`" now reads as `IndexComponent`s. "`index` stays the primary component" stands.
- **§5.2.** `Limit` on a `SumOf` bounds the year's total.
- **§5.3.** The table gains the rows above, and its first rows read "with at least one amount".
- **§6.** The table gains the level, the columns and the separate table above.
- **§7.** As "The metadata".
- **§9, multi-hazard.** This amendment settles the item. A trigger on one hazard scaled by another, which MAR-250 names, is not in this split. It can be an additive family later, and under D-22.8 a user can register it.
- **Amendment 3.** "`GaussianCopula(correlation)` comes later" is this amendment. "Every model only reorders" holds for it, and `sample_curves` takes it and any `DependenceModel`.
- **Amendment 4.** "Amendment 5 may relax this for `product`" is the relaxation above.
- **"Not verified" in the first part of this ADR.** "How fast a vectorised standard normal is without scipy": measured, below.

### The issue map (§10)

R-22 is split as below (each about one PR). The other rows stand.

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| MAR-336 (R-22a) | `IndexComponent`, `index_components`, `component()`, `CompositeIndex`, covers with several `index_names`; the documents and hashes of both kinds; a user table with several index columns; `design`, `evaluate` and `compare` read components; §5.3's gate; a registered test family on the LP and QP routes | `index`, `cover`, `payouts`, `sample`, `design`, `evaluate`, `metadata` | This amendment, MAR-298, MAR-303 |
| MAR-337 (R-22b) | `SumOf`, `MaxOf`, the limit rows and the grid route's check of `a_ub`; `CoverPackage` and `split_budget`; `level="package"`, `components` and `design_budget`; `payout_breakdown`. Tests: a `SumOf` whose second component never pays reproduces 1-D parity cases, one per objective, and `MaxOf` with one scale, MSE and no budget gives A* = Σ p L g / Σ p g² | `payouts`, `design`, `evaluate`, `metrics`, `metadata`, `__init__` | R-22a |
| MAR-338 (R-22c) | `StepGrid`; free breakpoints on the grid route; unreached cells in `unidentified`; the region rows of `payout_breakdown`. Tests: under MSE with no budget and `monotone=False`, each reached level is its cell's mean loss, and with every year below the second axis's first threshold it equals `StepPayout` on a 1-D parity case | `payouts`, `evaluate` | R-22b |
| MAR-339 (R-22d) | `CappedSum`, `CompoundDamage`, `CombineRule`; `sample_annual_hazards`; `own_loss`; `hazard_dependence` `{"kind": "data"}`; the setup text on the rule and on annual maxima | `combine` (new), `sources`, `sample`, `metadata` | R-22a, MAR-295 |
| MAR-340 (R-22e) | `sample_curve_hazards`; `GaussianCopula`; `DependenceModel` and its gate; `EmpiricalCopula` on components; the setup text on the assumption | `dependence`, `sources`, `sample`, `metadata` | R-22d, MAR-302 |
| MAR-341 (R-22f) | `.hazard`, `.combine`, `.package`, `.payout_breakdown`; results equal the function route; the refusals; the scenario fields above; the method section of `docs/parametric.md` | `plan`, `scenarios`; `docs/parametric.md` | R-22c, R-22e, MAR-304, MAR-334 |
| MAR-342 (R-22g) | The notebook section in crc-docs: heavy rain and heat at the primer's Toronto site. ERA5 `rx1day` and `txx` carry the real dependence; CRC Open curves of the same two use an `EmpiricalCopula` from those years, printed as an assumption; the `txx` impact is labelled illustrative. Every number out of sample next to `setup_text`, and the comparison of the holistic cover with the separate covers a measurement of that setup, with no claim that a cover, payout family or copula is better | crc-docs fork | R-22f, MAR-299, and the owner's permission to download CRC Open for this section |

Later, not in this split: several assets with several hazards, grids over three hazards, and a trigger on one hazard scaled by another.

### Beyond the eight decisions

The eight decisions don't determine these. The text above settles each as the agent recommends, and the owner's approval of this amendment covers them. The PR lists the alternatives of each.

1. `index_components` holds `IndexComponent`s, not §4.5's bare arrays.
2. The first component is the primary, and `loss` is the combined loss.
3. Component names exclude `.`, `+`, `[` and `]`.
4. A one-index cover finds its component by `hazard_name`, and a package by its key.
5. `component(name, *, loss="own")` has `loss="combined"`, and raises by default on a component with no impact.
6. `design` uses the loss of the sample it is given, with no multi-hazard rule of its own.
7. Composite cover documents and multi-hazard written samples write `schema_version` `"1.1"`.
8. A vector payout's `tail` is a tuple, in `index_names` order.
9. §5.3's gate is "`LinearInAmounts` with at least one amount", so `MaxOf` and `SumOf` keep one public name each.
10. A free scale beside a free component amount raises.
11. `Limit` on a `SumOf` is combination rows in `a_ub`. `basis` rows are checked per component, and the grid route learns to read `a_ub`.
12. `StepGrid` takes the whole table with `levels[0][0]` equal to 0.0, and its parameters are `levels[i,j]`.
13. `GaussianCopula` reads normal scores of the columns' own uniforms, through the standard library. The table above has the options.
14. `correlation` is a number for two columns and a positive definite matrix otherwise.
15. `DependenceModel` and its gate, and the opening sentence the module writes.
16. `sample_curves` takes `GaussianCopula` and any `DependenceModel`.
17. A rule acts on impacts, before the value, and needs one value.
18. `combine=` with fewer than two impacts raises, and a sample with no impact raises.
19. `sample_annual_hazards` and `sample_curve_hazards`, with one generator per component on curves.
20. `basis_risk` is one model per sample, and `index=` isn't offered on the multi-hazard sources.
21. `CoverPackage`, not a `SumOf` cover or a mapping. The table above has the options.
22. A package entry also gives one row per cover.
23. `level="package"`, with `asset_id` kept.
24. The columns `components` and `design_budget`.
25. `split_budget`, with no default for `shares`.
26. `payout_breakdown`'s columns, equal shares on a `MaxOf` tie, and an optional `breakdown` on a user payout.
27. `.hazard(name, source=None, ...)`, with `source=None` naming a per-year plan's own hazard.
28. On a plan a one-index template is designed on its own hazard's loss.
29. `.package(...)` splits the plan's budget by `shares`.
30. The first component draws the asset's own child stream, and the others spawn from it.
31. `product` joins a multi-hazard sample's providers with `+`.
32. A curve scenario's equal-curves refusal reads any one component.
33. Amendment 4's `hazard_name=` is a mapping by component on a multi-hazard sample, and a component's name isn't taken for a hazard name.

### Not verified

- No R-22 code exists, so every name is a proposal. Amendment 4's names are those of its open PR (MAR-329, at `f982d62`). A throwaway check (2026-11-08, not committed; script and output in the PR) ran the fork's `parametric` at `68f551c` and numpy on synthetic numbers, without any CRC, ERA5 or NEX data:
  - **The module's real LP and QP routes**, on stand-in families registered with one encoded index, because `Cover` still refuses several `index_names`. A 2-D table under MSE, no budget and `monotone=False` gave every reached level within 6e-11 of its cell's mean loss, with the unreached cell in `unidentified`. Under E[U] and weighted CVaR, with pure and cost-of-capital pricing, the levels were monotone on both axes, and `fill` ran on the two-axis order under both rules.
  - **A `SumOf` basis.** With a second axis that never pays, the objective equalled `StepPayout`'s under MSE, E[U] and weighted CVaR, to eight digits. A total limit bound at 8.0, also when its row touched an unidentified amount.
  - **`MaxOf`.** One scale under MSE gave the closed form A*. The numpy grid took 1.1 s on 549 rows and 2.9 s on 5,490 at 10,000 candidates, on one macOS arm64 machine. At 11 points each the design raises (14,641 points).
  - **The grid route with a total limit in `a_ub`** picks an over-limit candidate and raises at the end, the reason for that item of R-22b.
  - **The Gaussian reorder.** ρ = 0 and ρ = 1 equal the fork's `Independent()` and `Comonotonic()` row for row, the columns are permutations and no generator moved. Spearman was within 0.0024 of 6/π · arcsin(ρ/2) for ρ from −0.7 to 0.9 at 100,000 draws, and within 0.0043 on three columns. `statistics.NormalDist().inv_cdf` took 0.066 s per million draws.
  - **Premiums**, on the `"total"` row Amendment 3 already builds. The sum of two contracts was 23.12 under `CostOfCapitalLoad(0.1, 0.9)`, against 20.70 for one contract on the sum, and the two were equal, 15.50, under `PurePremium()`.
  - **Budgets.** `Budget(ratio=0.8)` on each own loss summed to 256,990, against 236,395 on the combined loss, under `CompoundDamage()`.
  - The arithmetic of the examples: 1.0 and 0.88 for the rules, the `MaxOf` counterexample, the grid's special cases and the region rows adding up.
- `_order_edges`, `_propagate` and `_fill` ran on a two-axis order, on those stand-ins, not on a real vector payout.
- How many cells of a grid a few decades of per-year rows reach is not known, so neither is how much of a 2-D table is `unidentified` on real records.
- The cost of Π_k n_k limit rows, of a large `StepGrid`, and of a grid search over free breakpoints on a large sample was not measured.
- Whether CRC Open holds `txx` at Toronto is unknown, because no catalogue was read. If it doesn't, R-22g's curve half needs another pair.
- No CRC Open, ERA5 or NEX data was read for this amendment.

## Amendment 6 (2026-11-09, MAR-346): additions from the design review

On 2026-11-09 the owner, Marc Prinzing, accepted the findings of that day's design review (in chat; recorded on MAR-344). E1 and F1 change Amendment 4 and are on MAR-329. This amendment fixes the public API of F2 to F6 and F8, so that the issues that build them (MAR-347 to MAR-351) have one text to follow, and the owner approves it before it merges. It builds on Amendments 2, 3 and 5, and on Amendment 4 as he revised it that day (MAR-329).

The rest of the ADR stands. §2, §4.4, §5.4, §6, §7, §9 and §10 keep their text and each carries a one-sentence pointer here, and this amendment says what they now mean, as Amendment 1 did. Every addition has a default or is a new name. A call written before this amendment gives the same rows, with the same `content_hash`, `definition_hash` and `design_id`, and its table gains the new columns of F4 and F6 beside them. The publication rule applies: this amendment presents each method and what it records, and nothing here says that a basis-risk model, a budget or a design is better than another.

### What the review accepted

| | Accepted on 2026-11-09 | Section |
|---|---|---|
| F2 | A built-in model of basis risk on the hazard side. `ImpactNoise` stays and says what it can't change, and the docs lead with the new model | "A basis-risk model on the hazard side" |
| F3 | Pooled k-fold metrics and block-bootstrap intervals, moved up from MAR-254 | "Pooled folds and intervals" |
| F4 | `payout_frequency` and `unidentified_share` in §6's comparison table | "Two columns" |
| F5 | A budget frontier: a Layer 1 function over a list of budgets, with no "best" point | "A budget frontier" |
| F6 | A resolution flag for rank blocks | "A resolution flag for rank blocks" |
| F7 | Phase 2's Layer 1 is built now, and new plan builders wait for RiskThinking's API guideline | No new plan builder appears here. The one change to `plan.py` is F2's seed rule |
| F8 | One sentence in the setup text on what fresh draws test | "The metadata" |

The evidence is on MAR-344. Its numbers are internal (one site, one hazard, one hypothetical cover, or synthetic), so this amendment argues in words, and the only numbers in it are synthetic ones of its own ("Not verified").

**What the code says** (the fork's `parametric` at `f3327e5`, read and not changed). `sample_curve` and `sample_annual` compute the impact and then call `BasisRisk.apply(index, hazard, impact, rng)`, so a built-in model can only change an impact the index has already fixed, and the primer had to write `LocalRainFactor`, which holds the damage function itself. §1 already separates "hazard" from "index", and `OutcomeSample.hazard` already holds the value the loss read when it differs from the index. `year_block_kfold` gives one pair of blocks per fold, and `metric_values` works on arrays, so pooling needs no new kernel. `DesignResult.unidentified` lists the amounts the fill rule set, and `to_record()` carries them. `EmpiricalCopula.record` already holds m and k.

### A basis-risk model on the hazard side (F2, §4.4)

```text
# basis-risk models (R-28); frozen; numpy only
HazardNoise(sigma)                                 # sigma finite and >= 0
class HazardBasisRisk(BasisRisk, Protocol):        # opt-in, as LinearInAmounts is for PayoutFunction
    def apply_hazard(self, index, hazard, rng) -> tuple[NDArray, NDArray]     # (index, hazard at the asset)
```

**The model.** In year d the hazard at the asset is the index times a mean-one lognormal factor, h_d = x_d · exp(σ Z_d − σ²/2), with one draw per year and asset. The index doesn't change, so the cover pays on x_d and the loss model reads h_d. For one cover, a year can then pay with no loss and a loss can occur with no payout, and §6's `false_negative_rate_l<ℓ>` and `false_positive_rate_l<ℓ>` respond to σ. §4.1's `hazard` holds h_d.

**How it reaches the impact.** The impact function stays on the `LossModel`, and the samplers call the model before they compute the impact:

| Step | What | Draws |
|---|---|---|
| 1 | The hazard: a curve's uniforms and quantiles, or a series' years with its trend | §4.4's first |
| 2 | `apply_hazard(index, hazard, rng)`, if the model has it, gives the index and the hazard at the asset | The model's |
| 3 | `loss_model.impact_values(hazard at the asset)` | None |
| 4 | `apply(index, hazard, impact, rng)` gives the index and the impact | The model's |
| 5 | loss = impact × value (§4.3) | None |

- **§4.4's draw order holds**: the hazard first, then the basis-risk model, and the impact draws nothing. One `basis_risk` generator record is taken at entry to step 2.
- **Existing models don't change.** A model without `apply_hazard` skips step 2, and step 3 draws nothing, so `NoBasisRisk()`, `ImpactNoise` and a user's `BasisRisk`, the primer's included, give today's rows.
- **`HazardNoise` is a `BasisRisk`.** Its `apply` returns its inputs, so everything that takes a model takes it, `.basis_risk(model)` included. A user's model may have both methods, and `apply_hazard` runs first.
- **The gate** on `apply_hazard` is the one on `apply`: a tuple of two arrays of the input's shape, finite, or `SampleError`.

| How the model reaches the impact | Assessment |
|---|---|
| **An opt-in `apply_hazard`, before the impact is computed** (recommended) | The model never holds the damage function, so it can't differ from the `LossModel`, and context columns and the plan's impact work unchanged. `BasisRisk` doesn't change. One new protocol, in the pattern of `LinearInAmounts` |
| The model holds the damage function (the primer's form) | The impact is stated twice and can differ. A plan takes its impact from the `PortfolioEvaluation`, so the caller has none to pass, and a registry impact's context would be stated twice too |
| `apply` gains an argument, a callable or the `LossModel` | Breaks every model written to today's signature, the primer's included. `BasisRisk` is in `__all__` |
| A factor on the `LossModel` | `basis_risk=` would read `NoBasisRisk()` on a sample with basis risk, against §4.4's rule that every sample states its model |

**The draws.** One call, `rng.normal(-σ²/2, σ, size=n)`, as in `ImpactNoise`. It draws n normals at every σ, σ = 0 included, so a sweep over σ from one generator state reads one set of Z_d.

**σ = 0** is allowed, unlike in `ImpactNoise`. The factor is exactly 1, so `index`, `loss` and `content_hash` equal `NoBasisRisk()`'s and `hazard` is `None`, and it warns with `ComonotoneIndexWarning` as `NoBasisRisk()` does.

**What it refuses**, with `SampleError`:

- A negative hazard, because a factor would move it the wrong way. A zero stays zero. The model suits a hazard on a ratio scale, where zero means none (rain, wind, depth), and the docs say so. The module can't tell that a temperature in °C isn't one.
- A separate index series (`index=` or `.index(...)`), where the index and the hazard already differ. The hazard at the asset is then data, so a factor on the index would contradict it, and a factor on the hazard would be another model. A refusal can be lifted later without breaking a call.
- A negative or non-finite σ, and, as for `ImpactNoise`, a missing generator. On a per-year plan without a seed, `.basis_risk(HazardNoise(...))` raises `ValueError` at every σ.

**The mean is on the hazard, not on the loss.** With a damage function that is convex or has a threshold, E[L] moves with σ, and that is part of what the model states. `details.basis_risk` records `hazard_mean_ratio` and `impact_mean_ratio`, the mean impact with the factor over the mean impact without it, and the setup text gives both. σ is an assumption the caller states, and the module doesn't estimate it. The σ of `HazardNoise` and the σ of `ImpactNoise` are not the same physical quantity, and the docs don't set them side by side as if they were.

**`ImpactNoise` stays**, with the same draws and rows. Its docstring gains: "The factor multiplies an impact the index has already fixed, and a year with zero impact keeps zero impact. So it can't change whether a year pays or whether a loss occurs, and `false_negative_rate_l0` and `false_positive_rate_l0` don't move with sigma. With a loss threshold above zero they can, because the factor can carry a loss across the threshold."

**The docs lead with the new model.** `docs/parametric.md` presents `HazardNoise` first, then `ImpactNoise`, `NoBasisRisk()` and a second series as the index, and says what each can and can't change. It doesn't say that any of them is more realistic for a given asset.

| Name | Assessment |
|---|---|
| **`HazardNoise`** (recommended) | Reads beside `ImpactNoise`, and says where the factor enters |
| `LocalHazardFactor`, the primer's name made general | "Local" claims a physical reading that the module doesn't estimate |
| `SpatialBasisRisk` | Claims that the spread is spatial, while a caller may state it for another reason |

### Pooled folds and intervals (F3, §6)

```text
# pooled k-fold metrics and block-bootstrap intervals (R-29); numpy only; no I/O
compare_pooled(entries, folds, *, pricing=PurePremium(), options=MetricOptions(),
               allocation=None, values=None) -> pyarrow.Table
bootstrap_intervals(entries, on, *, rng, n_bootstrap=1000, ci_level=0.9, split=None, fold=0, pricing=PurePremium(),
                    premiums=None, options=MetricOptions(), design_sample=None,
                    allocation=None, values=None) -> pyarrow.Table
    # on: one block, read as compare reads it, or folds, read as compare_pooled reads them
    # split= (required) and design_sample= are for one block; with folds they raise EvaluationError

# in full
folds = year_block_kfold(sample, 5)
designs = [design(template, train, objective, budget=budget) for train, _ in folds]
table = compare_pooled([designs], folds)
intervals = bootstrap_intervals([designs], folds, rng=numpy.random.default_rng(7))
```

**How folds are pooled.** The held-out blocks of a k-fold split partition the years, so every year is evaluated once, by the design made without it. A pooled row is §6's metrics on all those rows together, each row's payout from its own fold's design, with probability 1/N on each of the N rows. It is not the mean of the folds' numbers: a tail metric from 1/k of the years is noisier than one from all of them, and the mean of k CVaRs is the CVaR of no distribution. This is the rule of the core's `experiment/kfold.py`.

- **`folds`** is what `year_block_kfold` returns, in fold order. Under `LinearTrend` each fold's pair comes from that fold's own fit (Amendment 2), and a year's loss is the one its own fold states.
- **`entries`** holds, per entry, either a sequence of k of what `compare` takes (designs, `JointDesignResult`s, mappings or packages) in fold order, or one resolved `Cover` or mapping of covers, which applies on every fold. The rows have the levels `compare` gives them.
- **What it refuses**, with `EvaluationError`: pairs that aren't the k folds of one split in fold order (read from each block's `selection` step); held-out blocks that repeat or miss a year; a design whose design sample isn't its fold's design block; a block with unequal probabilities, which only a stated `probability` column can give; blocks of different `scenario` labels. A holdout and fresh draws have one block, so they have nothing to pool.

| Column | On a pooled row |
|---|---|
| `split` | `"out_of_sample"` |
| `fold` | Null. The column is nullable in a pooled table only, and null exactly on pooled rows, so it stays non-null in `compare`'s schema |
| `cover_hash` | The `sha256:` hash of the canonical JSON of the per-fold cover hashes, in fold order (the folds' hash). For one resolved cover, its own hash |
| `cover_label` | The covers' label if they share one, else the first 12 hex digits of the hash, as in Amendment 3 |
| `design_id` | The folds' hash of the design ids. Null for a cover given as is, and on a `"total"` row of a set of covers (Amendment 3) |
| `sample_hash` | The folds' hash of the held-out blocks' `content_hash` |
| `premium`, `premium_basis` | The probability-weighted mean of each row's premium, below. `"design"` for designs, `"evaluation"` for a resolved cover |
| The net-loss columns | N_d = L_d − π_d + P_d, with P_d the premium of row d's own fold |
| `unique` | True if every fold's is true, false if any fold's is false, otherwise null |
| `ties`, `degenerate_tail` | The sum of the folds'. The folds' flag if they all agree, else `"mixed"` |
| `unidentified_share` | Each row by its own fold's design |
| Amendment 4's and 5's columns | `n_rows` the sum, `design_budget` the mean over the rows of each fold's bound (null if any has none), and the others the blocks' one value |

**The premium of a pooled row.** Each year pays the contract in force for it, that fold's design premium. So §6's rule, that out-of-sample rows use the price agreed at design, holds year by year. `premium` is their mean. `metric_values` takes a per-draw `premium` for this. A resolved cover has one contract, priced once on the pooled rows.

| A pooled row's premium | Assessment |
|---|---|
| **Each year pays its own fold's design premium** (recommended) | Follows §6's rule, and the net loss of a year is what that year's contract costs |
| `pricing` once on the pooled payout, as the core does | A price no contract was sold at, set on the held-out years |
| The unweighted mean of the k design premiums | Stands for no year, and differs from the above when blocks differ in size |

**Intervals.** F3's questions, answered:

| | Decision |
|---|---|
| Resampling unit | A year, with every row of that year, as the splits define it: one row of a series or a curve sample, and every run's row of one calendar year in a pool. Rows of several assets or hazards in a year stay together. An `EmpiricalCopula` block is resampled by row: its reference is part of the stated model, so the reference's years are not resampled |
| Replicates | `n_bootstrap` draws of the block's Y years with replacement, by one call `rng.integers(0, Y, size=(n_bootstrap, Y))`. A replicate reweights the rows by how often their year was drawn, which gives the metrics of the concatenated years, as in the core's `bootstrap.py`. The designs are held fixed, and nothing is solved |
| The seed | `rng`, a required keyword, as everywhere in Layer 1 (§4.4), and never a global seed. Its state at entry goes into `rng` (§7), so the table can be rebuilt |
| Pairing | One set of replicates serves every entry and every metric of a call |
| Which metrics | Every metric column of the wide table. A design's premium is a fixed price, so on one block its interval is the value itself. A cover priced on the block is priced again on each replicate |
| Interval | The percentile interval: the (1 − `ci_level`)/2 and (1 + `ci_level`)/2 quantiles of the replicates (`numpy.quantile`, linear interpolation). `n_bootstrap=1000` and `ci_level=0.9`, the core's and SPEC's defaults |
| An undefined replicate | A metric undefined in some replicate (no expected loss, no variance) gets null bounds, counted in `n_undefined`. `ci_level` and `n_bootstrap` are on every row, so a null bound means "resampled, undefined" |

(Erratum 16, 2026-11-10, MAR-359: this note is new, and "The metadata" below has the rest of the erratum. This amendment left `premiums=` of `bootstrap_intervals` to Amendment 4's text. MAR-348 (R-29) settled it in marc272/crc-sdk#38, and `compare_scenarios` (marc272/crc-sdk#42) reads `premiums=` through the same code. It maps a `cover_label` to a stated premium, for covers given as is on one block. A set of covers or a package is stated whole or not at all, or `EvaluationError` says so, and its `"total"` or `"package"` row holds the sum, with `premium_basis` `"stated"`. A key that matches no cover given as is raises `EvaluationError`, and so does `premiums=` with folds, as `compare_pooled` has none. A stated premium is a fixed price, so its interval is the value itself. No decision changes.)

**The table.** One row per wide row and metric column, in a separate table with `to_long`'s columns and these. `value` is the wide table's number: resampling never changes a point estimate. It holds §7's metadata under the same key, and `write_comparison` writes it.

| Column | Type | Meaning |
|---|---|---|
| `ci_low`, `ci_high` | float64, nullable | The bounds. Null when the metric is undefined in a replicate, or null in the wide table |
| `ci_level` | float64 | As stated |
| `n_bootstrap` | int32 | As stated |
| `n_undefined` | int32 | The replicates in which the metric is undefined |
| `short_block` | bool, nullable | True when the column's level reaches the block's worst row: (1 − β)·n ≤ 1 for a β column, and T > n for a return-period column, with n the rows the metric reads. This is Amendment 4's "Short blocks". Null for a column with no level |

The bounds of a `short_block` row are computed like any other. They can't reach beyond the block's largest rows, so they understate how far the number could move, and the setup text names those columns.

| Where intervals go | Assessment |
|---|---|
| **A separate long table** (recommended) | The wide table and its schema don't change, and the form is `to_long`'s, which analysis already reads. A second table to keep beside the first |
| Two columns per metric in the wide table | Triples the width of a table of more than 60 metric columns, and changes every reader of a written table |
| A keyword on `compare` | A call would return one table or two, or wide columns again |

**The wording** (`docs/parametric.md` and `setup_text`, method only). `compare_pooled` evaluates every held-out year with the design made without it, and computes each metric once over all those years. `bootstrap_intervals` redraws the evaluated years with replacement and recomputes each metric with the designs held fixed. An interval is the middle `ci_level` of those values. It describes how much a number moves with the years drawn. It leaves out uncertainty in the hazard data, the impact function and the design, and on a curve block it is the Monte Carlo error of the draws and says nothing about the curve. Two rows' intervals are not a test of a difference between them.

**No plan builder (F7).** A plan's `KFold` keeps writing rows per fold. A builder for pooled rows and intervals comes after RiskThinking's guideline.

### Two columns (F4, §5.4, §6)

| Column | Definition | Null when |
|---|---|---|
| `payout_frequency` | `P(π > ε)`, with ε = `MetricOptions.payout_threshold`: the probability that the cover pays. `payout_breakdown` has the same definition per part | Never |
| `unidentified_share` | `Σ_d p_d · 1{B_j(x_d) ≠ 0 for some j in A}`, with B the basis of the resolved cover on this block's index and A the amounts the fill rule set (§5.4): the block's probability whose payout reads an amount that no design year reached | See the table below |

Both are metric columns, after `payout_to_loss_ratio`, with entries in `columns` in unit `"1"`, in every table with metric columns, and `to_long` and `to_drift` carry them.

| The row's design | A | `unidentified_share` |
|---|---|---|
| LP or QP route | `unidentified` | The formula; 0.0 when `unidentified` is empty |
| A grid over the shapes, with an LP or QP inside (§5.3) | `unidentified` at the chosen candidate | The formula |
| The numpy grid, which searches every free parameter (§5.3; `amounts` is `"grid"` in the record) | None, because no fill rule ran. An amount no year reaches is a tie there, in `ties` | Null |
| A cover given as is | No design | Null |
| A `JointDesignResult`: `"total"` and allocated rows | The union over the assets | A year counts if any asset's payout reads a filled amount |
| A set of designs | Each asset's own on its `"asset"` row; the union on the `"total"` row | The formula |
| A package (Amendment 5) | Each contract's own on its row; the union on the `"package"` row | The formula |

- **On the design block it is 0 by construction**, because an unidentified amount's column is zero in every design year. It is above 0 only out of sample, on a block that reaches where the design had no year.
- **What counts.** Any non-zero basis entry, in full, including a year on a piecewise segment that only partly reads a filled knot. A filled amount may equal its neighbour, and the year still counts: the column says where the amount came from, not what it is. Fixed amounts are never in A. Non-uniqueness among identified amounts is what `unique` reports, and it doesn't count here.
- **How it is read.** A comes from `to_record()`, so `DesignedCover` doesn't change, and a record without the key reads null. `metric_values` gains `unidentified=None`, a boolean per draw.
- **Existing tables.** A table written earlier reads as null, and no hash changes. **The golden fixtures don't change.** The fork's parity test asserts that a closed-form case holds exactly the metric columns, so MAR-349 makes that check leave these two columns out. The cases are byte-for-byte copies with about 2 kB of room left (Amendment 3), and hand-made tests cover the two columns.

### A budget frontier (F5)

```text
# a budget frontier (R-31); needs the solver extra, as design does
design_frontier(template, sample, objective, *, budgets, evaluate_on, split, fold=0, pricing=PurePremium(), limit=None,
                design_options=DesignOptions(), metric_options=MetricOptions()) -> pyarrow.Table
    # sample: the design sample. budgets: a sequence of Budget. evaluate_on: the block the rows are read on

# in full
train, test = holdout(sample)
frontier = design_frontier(template, train, objective, budgets=[Budget(ratio=r) for r in (0.5, 1.0, 1.5)],
                           evaluate_on=test, split="out_of_sample")
```

**One row per budget, in the order given.** Each row is exactly `design(template, sample, objective, pricing=pricing, budget=b, limit=limit, options=design_options)`, read by `compare([result], evaluate_on, split=split, fold=fold, pricing=pricing, options=metric_options)`. (Erratum 20, 2026-11-10, MAR-359, in "The metadata": the `compare` call first read `compare([result], evaluate_on, split=split, fold=fold, options=metric_options)`. The frontier's `pricing` also goes to `compare`, as a plan's does. It can't change a row, because a design keeps its design premium. It keeps the evaluation's `pricing` record and the `Pricing` line in step with the designs.) It has `compare`'s columns and these, beside the identity columns, which `to_long` keeps:

| Column | Type | Meaning |
|---|---|---|
| `budget_ratio`, `budget_amount` | float64, nullable | The budget as stated: exactly one is non-null |
| `design_budget` | float64 | Amendment 5's column: the bound in payout units on the design sample |
| `budget_use` | float64, nullable | The design premium's share of the bound |
| `objective_value` | float64 | The design's objective on the design sample, in payout units |

- **No best point.** There is no rank, no best flag, no knee, no marginal column and no ordering by a metric. A reader takes differences between rows for what another unit of premium buys, on a stated block.
- **The name is `design_frontier`,** F5's. It takes one template and one objective. Several go through several calls and `EvaluationMetadata.merge`.
- **`split` has no default,** as in `compare`. So a frontier states whether its rows are in or out of sample, and external numbers come from out-of-sample rows.
- **Failures.** An empty list raises `EvaluationError`, and so does a repeated budget, because two rows would repeat a key. A budget the template can't meet raises `design`'s error, naming that budget, so no row is dropped quietly. A multi-asset sample raises `SampleError`, as `design` does. A joint frontier over `design_joint` is a later, additive option.

**Non-uniqueness along the frontier** is reported row by row: each row carries `unique`, `ties`, `degenerate_tail` and `unidentified_share`, as every design's row does. `DesignOptions(ranges=True)` applies to every row, at four LPs per amount per budget, and without it `unique` is null on the LP route and the setup text says "not checked".

| How non-uniqueness is reported | Assessment |
|---|---|
| **Per row; each row solved on its own** (recommended) | A row equals `design` at that budget and doesn't depend on the list's order. Amounts may jump between neighbouring budgets where a row isn't unique, and `unique` says so |
| Warm-start each row from the previous one | The rows depend on the order of the list, and a row is no longer `design` at that budget |
| Choose, among optimal designs, the one closest to the previous row | Smooth amounts, at one more LP per budget, and the smoothness is the module's choice, not the problem's |
| Leave out non-unique rows | Drops rows quietly |

On the design sample the objective doesn't rise with the bound, because the feasible sets are nested, and R-31 tests that. Out of sample nothing guarantees it, and the docs say so. **A plan builder comes later:** F7 keeps new builders waiting for RiskThinking's guideline, and this amendment names none.

### A resolution flag for rank blocks (F6)

Inside one reference year's block, `EmpiricalCopula` treats the columns as independent. When (1 − β)·m ≤ 1, the tail at β holds at most one reference year's block, so a sum's tail metric lies inside that assumption. Each row records m and flags those β, as `degenerate_tail` flags a design's tail.

| Column | Type | Meaning |
|---|---|---|
| `copula_reference_years` | int32, nullable | m, the reference's rows (`dependence.m` in the record) |
| `copula_block_tail_b<β>` | bool, nullable | One per β of `MetricOptions.betas`: true when (1 − β)·m ≤ 1, with the tolerance of `degenerate_tail` (1e-9), else false |

Both sit beside the identity columns, which `to_long` keeps. They are not metrics.

| A row | The columns |
|---|---|
| `"total"`, `"asset_by_value"` or `"asset_by_loss"` on a multi-asset sample under `EmpiricalCopula` | Filled: the row reads a sum over the reordered columns |
| An `"asset"` row on such a sample | Null: one asset's draws are the same under every model |
| Any row on a multi-hazard sample under `EmpiricalCopula` | Filled: every row reads the combined loss (Amendment 5) |
| Other dependence models, per-year samples, and one-asset one-hazard samples | Null |

- `degenerate_tail` doesn't change, so no existing column changes value, and a table written earlier reads as null. A tolerance is needed, since (1 − 0.95)·20 is 1.0000000000000009 in floating point. A `component(name)` view has one hazard's provenance, so it reads null.
- The flag says where a number lies inside an assumption. It doesn't say the number is wrong, and the setup text says neither.

| How the flag is stored | Assessment |
|---|---|
| **One boolean column per β** (recommended) | Names follow §6's label rule, filters are direct, and null keeps apart "no rank blocks" and "resolved" |
| One string column listing the flagged β | A fixed schema, but readers must parse it |
| A third value of `degenerate_tail` | Changes an existing column's values, and it describes a design's one β, not the metric options' |
| Only the number (1 − β)·m, per β | Leaves the flag to every reader |

### With Amendments 2, 3, 4 and 5

- **Amendment 2.** Step 1 holds the trend, so under `LinearTrend` the factor multiplies the adjusted hazard. `sample_annual_pool` takes `HazardNoise`, one factor per row. A pool is resampled by calendar year.
- **Amendment 3.** `sample_curves` applies the model per asset, from that asset's generator, so the factors are independent between assets, and the setup text says so. A dependence model moves a row's index, hazard and loss together.
- **Amendment 4.** `HazardNoise` draws after the uniforms, so row d holds one factor in every curve scenario, and "What is shared" holds. Its document is one more `basis_risk` document to compare. `compare_pooled` takes one scenario's folds, and a design from one scenario read on another's block isn't pooled here. For a scenario's block, `bootstrap_intervals` takes one call per block, with `premiums=` as in `compare_scenarios` for a given cover's price, and `premium_repriced` isn't among its rows. Intervals on `to_drift`'s differences need one resampling across two blocks and come later.
- **Amendment 5.** One model serves every component (§4.4), with its own factors per component in Amendment 5's draw order. A component with no impact still draws its factors, so the others' draws don't depend on it. `own_loss` reads the component's hazard at the asset. `design_frontier` uses `design_budget`.

### The publication rule

- `compare_pooled`, `bootstrap_intervals` and `design_frontier` have no rank, no best flag and no ordering by a metric.
- `docs/parametric.md` presents each as a method. It makes no claim that a basis-risk model is more realistic for an asset, that a budget or a design is better, or that one interval shows a difference from another.
- Tail statements stay conditional on a stated setup (the RQ1 rule).
- D-21.4 holds. Joint rows can be pooled and given intervals, and the module's docs and notebook run `Joint()` alone until the owner revisits the RQ2 rule (MAR-152 item 4).
- The setup text states every σ, budget, split, k and number of resamples next to the numbers.

### The metadata (§7)

- **`SampleProvenance`.** `basis_risk` holds `{"kind": "hazard_noise", "sigma": σ}`, and `details.basis_risk` gains `hazard_mean_ratio` and `impact_mean_ratio` on a model with `apply_hazard`. `hazard` is part of `content_hash` as today, and the lineage doesn't change.
- **`setup.evaluations`.** A pooled entry has `fold` null, `method` `"kfold_pooled"`, and `details` with k and the held-out blocks' hashes in fold order. `setup.samples` holds each block and one entry for the pooled rows.
- **`setup.intervals`** (new, null otherwise): `{"method": "percentile", "unit": "year", "n_bootstrap": B, "ci_level": ℓ, "short_block_columns": [...]}`. `unit` is `"row"` on an `EmpiricalCopula` block, and `"year"` otherwise. `short_block_columns` names the columns with `short_block` true. `rng` gains a `bootstrap` step with the generator's state at entry. (Erratum 16, 2026-11-10, MAR-359: the record first read `{"method": "percentile", "unit": "year", "n_bootstrap": B, "ci_level": ℓ}`, and the two sentences after it are new. MAR-348 (R-29) settled both in marc272/crc-sdk#38. "Intervals" above says an `EmpiricalCopula` block is resampled by row, so `unit` records what was done. Item 3 of `setup_text` below names the columns with `short_block` true, and `setup_text(metadata)` has no table to read them from. Given a table, the text uses the rows it still holds. No decision changes.)
- **`setup.frontier`** (new, null otherwise): a list with one entry per call of `design_frontier`, each holding the template's hash, the objective, the list of budgets, `design_ids` (one per budget), `design_sample`, `sample_hash`, `split` and `fold`. It is left out of a document when null, and reads as null. (Erratum 20, 2026-11-10, MAR-359: this bullet first read "**`setup.frontier`** (new, null otherwise): the template's hash, the objective and the list of budgets." MAR-350 (R-31) settled the rest in marc272/crc-sdk#44. It is a list because several templates and objectives go through `merge`, so a merged table holds several entries. The setup text needs the new keys to name the blocks and to state only the budgets that filtered rows still hold. Left out when null, it leaves every other table's document as it was. No decision changes.)
- **`columns`** gains `payout_frequency` and `unidentified_share`.
- **`designs`** holds one record per fold's or budget's design. A pooled row's `design_id` has an entry that lists the designs. `covers` likewise, as a package's does in Amendment 5.
- A document without these keys reads as before, and `schema_version` stays `"1.0"`.
- **`setup_text`** states, next to the numbers:
  1. For `HazardNoise`: that the hazard at the asset is the index times a mean-one lognormal factor with that σ, one per year and asset, as an assumption the caller states, and the two mean ratios.
  2. For a pooled row: k, the rows, and that each year is evaluated by the design made without it.
  3. For intervals: the resamples, the level, the unit, and the wording above. The columns with `short_block` true.
  4. For a frontier: one design per budget on the stated design block, each row read on the stated block, and that the table names no best budget.
  5. For rank blocks: m, the β flagged among the metric options, and whether the weighted-CVaR β of a row's design is flagged too.
  6. **F8.** On a row whose design block and evaluation block are draws from one curve (`fresh_draws`, or a holdout or k-fold of draws): "Out of sample here means new draws from the same curve, so these rows test the design's sampling error, not the curve."

### What the other sections now mean

- **§1.** The basis-risk row gains `HazardNoise` and `HazardBasisRisk`.
- **§2.** The Layer 1 outline gains the entries above. The module layout gains `intervals.py` (R-29: `compare_pooled`, `bootstrap_intervals`) and `frontier.py` (R-31: `design_frontier`), and `basis_risk.py` gains `HazardNoise` and `HazardBasisRisk`. `plan.py` changes only in treating `HazardNoise` as it treats `ImpactNoise` for the seed rule.
- **§4.4.** The table gains `HazardNoise`. "The hazard uniforms first, then the basis-risk model" stands. The samplers' order is the table above.
- **§5.4.** `unidentified` also feeds `unidentified_share`.
- **§6.** "Pooled k-fold metrics are a follow-up" is "Pooled folds and intervals" above. The metric table and the comparison table gain the columns above.
- **§7.** As "The metadata".
- **§8.** The fixtures keep their columns. "Every column of §6" in `parity/crc/README.md` now reads "every column but `payout_frequency` and `unidentified_share`".
- **§9.** Block-bootstrap intervals and pooled k-fold metrics are this amendment. The local refinement after the grid and the second solver backend stay reserved (MAR-254).
- **D10's point 8.** `NoBasisRisk()` stays a stated choice, and `basis_risk` stays required.

### The issue map (§10)

Each row is about one PR. The other rows stand.

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| MAR-347 (R-28) | `HazardNoise`, `HazardBasisRisk`, the samplers' order, the refusals, the seed rule, `details.basis_risk`, the setup text, `ImpactNoise`'s docstring; `docs/parametric.md` leads with the model. Tests: both failures occur for one cover; at σ = 0 the rows and `content_hash` equal `NoBasisRisk()`'s; §4.4's draw order; a model without `apply_hazard` gives today's rows; a stand-in that holds the damage function gives the same rows | `basis_risk`, `sources`, `metadata`, `plan` (the seed rule), `__init__`; `docs/parametric.md` | This amendment |
| MAR-348 (R-29) | `compare_pooled`, `bootstrap_intervals`, a pooled row's columns, a per-draw premium in `metric_values`, the metadata and the setup text; the method in the docs. Tests: a pooled row equals `metric_values` on the concatenated rows; a closed form at k = 2; replicates against the core's `kpi_replicates` on the same year draws; one generator state gives one table; all-ones counts give the point estimate | `intervals` (new), `metrics`, `metadata`, `__init__`; `docs/parametric.md` | This amendment |
| MAR-349 (R-30) | `payout_frequency`, `unidentified_share`, their `columns` entries, and F8's sentence. Tests on hand-made samples: a design with unidentified amounts read on a block that reaches them, and 0.0 on its design block; null on the numpy grid and for a cover given as is; a table without them reads as null. The fork's parity test leaves the two columns out of its check | `metrics`, `evaluate`, `metadata`; the fork's parity test | This amendment |
| MAR-350 (R-31) | `design_frontier`, its columns, `setup.frontier` and the setup text; the method in the docs. Tests: each row equals `design` and `compare` by hand at that budget; the objective doesn't rise with the bound on the design sample; non-uniqueness and degenerate tails per row; no rank, best flag or ordering | `frontier` (new), `metadata`, `__init__`; `docs/parametric.md` | This amendment, MAR-337 (`design_budget`), MAR-349 |
| MAR-351 (R-32) | `copula_reference_years`, `copula_block_tail_b<β>`, `to_long` keeping them, and the setup text. Tests at (1 − β)·m = 1 and on either side of it; null on the other models and on per-year samples; existing tables and hashes don't change | `evaluate`, `metadata` | This amendment |

### Beyond the six items

The items don't determine these. The text above settles each as the agent recommends, and the owner's approval of this amendment covers them. The PR lists the alternatives of each.

1. `HazardBasisRisk` is opt-in and extends `BasisRisk`, and `HazardNoise.apply` returns its inputs.
2. A user's model may have both methods, and `apply_hazard` runs first.
3. `HazardNoise` allows σ = 0, unlike `ImpactNoise`, and warns then as `NoBasisRisk()` does.
4. It draws at every σ, so a sweep over σ shares its draws.
5. The factor is lognormal with mean one on the hazard, as `ImpactNoise`'s is on the impact.
6. A negative hazard raises.
7. A separate index series raises.
8. One σ serves every asset and component of a sample.
9. `details.basis_risk` holds the two mean ratios.
10. `compare_pooled` is a function of its own, and `fold` is null on its rows.
11. `compare_pooled` requires equal probabilities in each block.
12. A pooled row's hashes are hashes of the per-fold hashes, in fold order.
13. `unique`, `ties` and `degenerate_tail` aggregate over the folds, with the value `"mixed"`.
14. A resolved cover is priced once on the pooled rows.
15. `rng` is a required keyword, not a `seed=`.
16. `n_bootstrap=1000` and `ci_level=0.9`, and a percentile interval.
17. A pool is resampled by calendar year, and an `EmpiricalCopula` block by row.
18. Every metric column gets an interval, with no `metrics=` option.
19. A `short_block` row keeps its bounds and is flagged.
20. `bootstrap_intervals` takes `premiums=`, and `to_drift`'s differences get no interval yet.
21. The two new columns sit after `payout_to_loss_ratio`.
22. `unidentified_share` counts any non-zero basis entry in full.
23. On a `"total"` or `"package"` row it is the union over the contracts.
24. It is null on the numpy grid route.
25. The fixtures don't change, and the fork's parity test leaves out the two columns.
26. `design_frontier` takes `evaluate_on` and a required `split`.
27. One template and one objective per call.
28. The columns `budget_ratio`, `budget_amount`, `budget_use` and `objective_value`.
29. A joint frontier is later.
30. The columns `copula_reference_years` and `copula_block_tail_b<β>`.
31. They are filled only on rows that read a sum over the reordered columns.
32. They use `degenerate_tail`'s tolerance.
33. F8's sentence also holds for a holdout or k-fold of draws from one curve.

### Not verified

- No R-28 to R-32 code exists, so every name is a proposal. Amendment 4's names are those of its open PR (MAR-329, at `85f5010`), and Amendment 5's `design_budget` is MAR-337's, in progress. A throwaway check (2026-11-09, not committed; script and output in the PR) ran a private copy of the fork's `parametric` at `f3327e5` with `HazardNoise` and step 2 patched in, on synthetic numbers, without any CRC, ERA5 or NEX data:
  - **The two failures.** On 20,000 synthetic Gumbel years, with a ramp damage function from 80 to 200 and one fixed two-step cover at 90 and 120, `false_negative_rate_l0` and `false_positive_rate_l0` were 0.4543 and 0.0000 under `NoBasisRisk()`, and the same under `ImpactNoise(σ)` for σ = 0.1, 0.25, 0.5 and 1. Under `HazardNoise(σ)` they were (0.4969, 0.0053), (0.6347, 0.0349), (0.7422, 0.0698) and (0.8081, 0.1016), and E[L] moved from 30.21 to 33.92, 51.11, 91.55 and 131.25. The setup is arbitrary, and the numbers say nothing about which model suits an asset.
  - **σ = 0, on both routes.** Rows, `content_hash` and lineage equal `NoBasisRisk()`'s, `hazard` is `None`, and the generator's state after the call is the same at σ = 0 and σ = 0.5.
  - **The draw order, on curves.** At σ = 0.25 the index equals the one from the same uniforms under `NoBasisRisk()`, and the `hazard` generator record is the same.
  - **Existing models.** The fork's 362 tests of basis risk, sources, pools and dependence passed on the patched copy. A stand-in that holds the damage function, as the primer's does, gave the same rows as `HazardNoise`.
  - **The refusal** of a separate index series raises.
  - **Pooling and resampling.** A pooled row on 63 synthetic years and five folds was computed by `metric_values` on the concatenated rows. Reweighting by counts and duplicating rows agreed to 7e-15. 1,000 resamples took 0.2 s for one wide row at 63 rows, and about 9 s at 20,000 rows, in a plain loop on one macOS arm64 machine.
  - **`unidentified_share`.** A step design with two unreached levels read 0.0 on its design block, 0.0 on a held-out block that didn't reach them, and 0.368 on a block with larger index values, on synthetic numbers.
  - **A frontier by hand.** Seven budgets on 700 synthetic rows took 0.05 s. The objective fell at every step, and `budget_use` was 1.0 at each.
- Whether a percentile interval has its nominal coverage on a short block wasn't tested, which is why `short_block` exists. How large the bias of a tail metric inside a rank block is rests on MAR-344's synthetic check, which this agent read and didn't rerun.
- The cost of `bootstrap_intervals` on a table of many covers and of `ranges=True` along a frontier was not measured.
- How often a real design leaves amounts to the fill rule is not known here.
- The patched path and every other piece were not run against Amendment 4's or Amendment 5's unbuilt parts.
- No CRC Open, ERA5 or NEX data was read for this amendment.
