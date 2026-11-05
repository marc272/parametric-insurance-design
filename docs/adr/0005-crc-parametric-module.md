# ADR 0005: Design of the `crc_sdk.parametric` module

- Status: **Proposed**. The owner, Marc Prinzing, decides (D10). His decision is recorded on MAR-244; the orchestrator then sets the status to Accepted.
- Date: 2026-11-05
- Decision issue: MAR-244 (R-12). It feeds MAR-245 (R-13, golden fixtures, which take their field names from §8), MAR-246 (R-14), MAR-43 (R-15), MAR-247 (R-17), MAR-248 (R-16), MAR-42 (R-18) and MAR-46 (R-19). Phase 2: MAR-45 (R-21), MAR-250 (R-22), MAR-44 (R-23). Questions for RiskThinking go to MAR-249 (R-20).
- Prepared by a worker agent from `main` at `56755a5`. The upstream repositories were cloned read-only and read at these commits. No upstream code was run against CRC data, and no CRC data was downloaded.
  - crc-sdk 0.11.1: [`9c56bb0`][sdk] (tag `v0.11.1`, 2026-11-04);
  - crc-framework 0.6.0: [`838c295`][fw] (tag `v0.6.0`; the later head changes only the release workflow);
  - crc-docs: [`7691f5f`][docs] (2026-11-04).
- Revised on 2026-11-05, before the owner's decision, to match the golden fixtures of MAR-245 (PR #183). The end of "Decisions for the owner" lists what changed.

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

**Entry point.** `ParametricPlan.for_evaluation(request)` takes the `PortfolioEvaluation` the user already built with `HazardDataset.<source>(...).for_assets(assets).select(...).impact(...)`, and reuses its dataset, assets, selection and impact function. It changes nothing in `PortfolioEvaluation`. `ParametricPlan.for_annual_extremes(...)` is the second entry, for per-year sources (U5).

To sample from curves the plan needs each asset's curve, and the join that finds it is private (U3). **Recommendation:** R-18 adds one public execution point to crc-sdk, `PortfolioEvaluation.asset_curves() -> pyarrow.Table`, with one row per asset, hazard, horizon and pathway, the curve columns and `spatial_match`, built on the existing join. It is additive. RiskThinking confirms the name and the place (Q1). A chaining method on `PortfolioEvaluation` (for example `.parametric(...)`) is the alternative; it edits their class, so it is their choice (Q2).

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
Cover.to_json() -> str; Cover.from_json(text) -> Cover; Cover.definition_hash -> str
register_payout(cls) -> cls

# outcome samples (R-15)
OutcomeSample(...)                                     # §4.1
sample_curve(distribution, *, metadata, n_draws, rng, loss_model, basis_risk, asset_id,
             assume_semantics=None, outside_support="raise") -> OutcomeSample
    # metadata: the curve's HazardDatasetMetadata (semantics, tail, support, units, source)
AnnualSeries.from_table(table, *, year="year", value="value", where=None, unit) -> AnnualSeries
AnnualSeries.nearest_cell(table, *, longitude, latitude, unit, ...) -> AnnualSeries
sample_annual(hazard, *, loss_model, basis_risk, asset_id, index=None, rng=None, missing="raise") -> OutcomeSample
OutcomeSample.from_table(table, *, period, asset_id, index, loss, probability=None, semantics, index_unit, loss_unit) -> OutcomeSample
holdout(sample, train_fraction=0.7) -> tuple[OutcomeSample, OutcomeSample]
year_block_kfold(sample, k) -> tuple[tuple[OutcomeSample, OutcomeSample], ...]

# evaluation and comparison (R-17)
evaluate(cover, sample, *, split, fold=0, pricing=PurePremium(), premium=None, options=MetricOptions()) -> pyarrow.Table   # one row
compare(covers, sample, *, split, fold=0, pricing=PurePremium(), options=MetricOptions()) -> pyarrow.Table
write_comparison(table, path, *, metadata) -> None    # atomic

# design (R-16)
design(template, sample, objective, *, pricing=PurePremium(), budget=None, limit=None, options=DesignOptions()) -> DesignResult
```

**Layer 2 in outline (R-18):**

```text
ParametricPlan.for_evaluation(request, *, value_column=None, value_unit="1")
ParametricPlan.for_annual_extremes(source_plan, assets, *, impact, value_column=None, value_unit="1", ...)
    .monte_carlo(n_draws, *, seed, assume_semantics=None)       # curve sources only
    .basis_risk(model)
    .covers(*templates)                  # Cover templates; Free parameters allowed
    .objective(objective, *, pricing=..., budget=..., limit=..., options=...)   # optional: design the templates
    .split(Holdout(0.7) | KFold(5) | FreshDraws(n_draws, seed=...))
    .metrics(MetricOptions(...))
    .explain(format="text") -> str | dict        # no I/O
    .samples() -> Mapping[str, OutcomeSample]    # execution, one per asset
    .designs() -> tuple[DesignResult, ...]       # execution
    .write_parquet(path) -> ParametricResult     # execution; atomic
```

The plan holds an integer `seed`, which `explain()` can show. At execution it builds `numpy.random.SeedSequence(seed)` and spawns one child generator per asset, in asset order. Layer 1 takes a `numpy.random.Generator` instead, with no default and no global seed.

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
| `metadata.py` | `EvaluationMetadata` (§7) | R-17 |
| `objectives.py` | `MSE`, `ExpectedUncovered`, `WeightedCVaR`, `UserObjective` | R-16 |
| `constraints.py` | `Budget`, `Limit` | R-16 |
| `design.py` | `design`, `DesignOptions`, `DesignResult`; the LP and QP assembly | R-16 |
| `_solver.py` | The private solver interface and the HiGHS backend (§5.5) | R-16 |
| `plan.py` | `ParametricPlan`, `ParametricResult` | R-18 |

Outside the package: `docs/parametric.md` with its line in `docs/README.md` (stub R-14, finished R-18); tests `tests/test_parametric_<module>.py`, mirroring the modules as crc-sdk does; the extra in `pyproject.toml` (R-16); `PortfolioEvaluation.asset_curves()` in `workflows/portfolio.py` and `workflows/_portfolio.py` (R-18, if RiskThinking agrees, Q1).

**Errors** (`errors.py`): `ParametricError` is the base. `CoverDefinitionError` and `UnknownPayoutKindError` (also `ValueError`) cover invalid covers, payouts and parameters. `UnresolvedParameterError` is raised when a template is evaluated. `SampleError`, with `ProbabilitySemanticsError` and `LeakageError`, covers samples and splits (also `ValueError`). `DesignError`, with `InfeasibleDesignError` and `UnboundedDesignError` (also `RuntimeError`), carries the asset id, the solver status and its message. `SolverUnavailableError` (also `ImportError`) names the extra. Warnings: `ComonotoneIndexWarning`, and crc-sdk's own `ReturnPeriodExtrapolationWarning` for draws outside a curve's fitted support.

### 3. Payout families and the extension protocol

**Severity.** `tail="upper"`: larger index values are more severe (rainfall, wind). `tail="lower"`: smaller values are more severe (a drought index). Every family pays more as the index moves to the severe side. Thresholds are given in index units, in order of increasing severity: increasing for `"upper"`, decreasing for `"lower"`. Internally a family works on the severity s = x (upper) or s = −x (lower), with its thresholds mapped the same way. `Cover` checks that the payout's `tail` equals the index's.

**Families.** π ≥ 0 is the payout of a year with severity s.

| Family | Index-unit parameters | Payout-unit parameters | Payout | Linear in |
|---|---|---|---|---|
| `LinearPayout` | attachment a, exhaustion e (a < e in severity) | limit ℓ | `ℓ · clip((s − a) / (e − a), 0, 1)` | ℓ |
| `StepPayout` | breakpoints b_0 < … < b_{n−1} | levels θ_0 … θ_{n−1} | θ_k for b_k ≤ s < b_{k+1}; θ_{n−1} for s ≥ b_{n−1}; 0 for s < b_0 | θ |
| `PiecewiseLinearPayout` | knots c_0 < … < c_{m−1}, m ≥ 2 | levels y_0 … y_{m−1} | 0 for s < c_0; linear interpolation of the points (c_k, y_k) on [c_0, c_{m−1}]; y_{m−1} for s ≥ c_{m−1} | y |
| `BinaryPayout` | trigger t | amount A | A for s ≥ t, else 0 | A |

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

- Canonical JSON follows crc-framework's impact contracts (`canonical_json` and `content_hash` in its [`crates/core/src/impact/json.rs`][fw-json]): keys sorted by their UTF-8 bytes, no whitespace, strings as unescaped UTF-8, zero (and −0.0) written `0.0`, every other number in Rust `serde_json`'s shortest round-trip spelling (`1e-7`, where Python's `json` writes `1e-07`). NaN and infinity are rejected. Every number in the document is a float, so a grid given as a count is stored as its explicit values. R-14 tests the spelling of small and large exponents against crc-framework's own hashes, so a cover hashes the same in Python and Rust (Q9).
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

- **One draw is one year.** A cover pays once per draw, on that draw's index, against that draw's loss. This is the core's annual basis with one row per year. Several events within a year are out of scope for Phase 1 (§9).
- **One asset per sample in Phase 1** (MAR-43). The asset axis exists, so arrays are (n, 1); a second asset raises `SampleError` until Phase 2. The plan handles several assets as one sample each. So Phase 1 imposes no dependence between assets: it computes no cross-asset sum.
- Arrays are read-only (`setflags(write=False)`). A sample written to Parquet uses the long table above and the metadata key `crc.parametric.sample`.

#### 4.2 Sources and the probability semantics each needs

| Source | Function | One draw is | Probability | Semantics required |
|---|---|---|---|---|
| Monte Carlo from a fitted curve | `sample_curve` (a crc-framework `Distribution`); the plan's `.monte_carlo(...)` | a simulated year | 1/n | `annual_exceedance` (the curve of an annual maximum) or `annual_value_distribution` (an annual value). Any other declared value raises `ProbabilitySemanticsError`. Unspecified raises too, unless the caller passes `assume_semantics=` one of the two; a stated value that contradicts the declared one raises |
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

- `AnnualSeries(years, values, unit, provenance)` is one hazard at one location. `AnnualSeries.from_table` reads any of the tables of U5 with stated column names and a row filter (for example a station id). `AnnualSeries.nearest_cell` picks the grid cell whose centre is nearest to the asset, and accepts it only within half the grid spacing in latitude and longitude; otherwise it raises. The cell centre and the distance are recorded. RiskThinking may prefer to give `annual_extremes()` an asset join of its own (Q3).
- A missing or null year raises, unless `missing="drop_year"`; then the year is dropped and listed in the provenance.
- The `index=` argument takes a second series: another cell, a station or another hazard than the loss reads. The years of both series must match. This is the per-year basis-risk model of MAR-43: the dependence between index and loss is the data's own, not an assumption.

**A user table.** Required columns: period, asset id, index, loss. Optional: probability, hazard. Every (period, asset) pair appears exactly once; missing or duplicate pairs raise.

#### 4.3 Loss model

`LossModel(impact, *, value_column=None, value=None, value_unit="1", context=None)`:

- loss = `impact.evaluate(hazard)` × value. `impact` takes the types `.impact(...)` takes (U6): an `ImpactExpression`, a framework `ImpactFunction`, or a vectorised callable. Context columns for registry impacts work as in crc-sdk (`ImpactContextColumns`).
- The value comes from an asset column, in one stated currency, or is 1, which gives the loss in damage-ratio units (`value_unit="1"`).
- A negative or non-finite loss raises. `design` and `evaluate` check that the loss unit equals the cover's `payout_unit`.
- The plan takes the impact from the `PortfolioEvaluation`'s impact spec.

#### 4.4 Basis-risk models and seeding

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

- **The grid.** A free shape parameter must have a grid (§3). The candidates are the Cartesian product of the grids, restricted to ordered breakpoints and knots. `DesignOptions(max_grid_points=10_000)` caps the product; above the cap `design` raises. The best candidate wins. Ties within the tolerance go to the first candidate in lexicographic order and are counted (`DesignResult.ties`). The objective at every candidate is kept (`DesignResult.profile`, a `pyarrow.Table`).
- **Why a grid.** On a finite sample the objective is piecewise constant (step, binary) or piecewise smooth (linear, piecewise linear) in the shape parameters, so gradients mislead. A stated grid is reproducible and shows how flat the optimum is. A local refinement after the grid is a later option (§9).
- **Scaling.** Losses and payouts are divided by the scale before solving: the largest loss of a draw (in a joint design, of the draw's loss summed over the assets), or 1 if that is at most 1e-6, as the core's `build_context` does. Results are in payout units.
- **No silent failures.** After the solve, numpy recomputes the objective, the premium, the budget and every constraint from the returned parameters, with relative tolerance `DesignOptions.feasibility_tolerance = 1e-7`. A violation, or any solver status other than optimal, raises `DesignError` (or `InfeasibleDesignError`, `UnboundedDesignError`) with the asset id and the solver's message. Amounts below 1e-9 of the scale are set to 0 and counted, so a 1e-12 level doesn't count as a payout in §6's rates.

**`DesignResult`** holds: the resolved `cover`; `template_hash`; `design_id` (§7); the objective's document and `objective_value`; `premium`, `expected_loss` and the budget's use; `route` (`"lp"`, `"qp"` or `"grid"`); the solver's name, version, status, iterations and time; the non-uniqueness report of §5.4; the degenerate-tail flags; and the design sample's `content_hash`.

#### 5.4 Non-unique optima

The module reports non-uniqueness. It does not hide it behind one solver-dependent answer.

- **Unidentified amounts.** An amount whose basis column is zero in every design year (a step bin or a piecewise segment that no year reaches) changes nothing in the sample: not the objective, the premium or the budget, under every objective and pricing. `DesignResult.unidentified` lists them. A stated rule sets them: `DesignOptions(fill="lowest")`, the default, takes the smallest value the constraints allow (the previous identified level under `monotone`, else 0); `fill="highest"` takes the largest (the next identified level, or the limit or upper bound above the last one; with no bound above, `design` raises). Both keep the design exactly optimal. The rule is recorded.
- **Ranges and uniqueness on the LP route** (`DesignOptions(ranges=True)`). Each identified amount is ranged twice: its smallest and largest value over the near-optimal set {feasible θ : objective(θ) ≤ optimum + ε · max(1, |optimum|)}, in scaled units, for a wide ε₁ = 1e-9 and a narrow ε₂ = 1e-11. That is four LPs per amount, solved with HiGHS at primal and dual feasibility tolerances of 1e-10 (its defaults are 1e-7).
  - An amount is **pinned** when its narrow range is at most half its wide one, or narrower than 1e-7 of the scale. `unique` is true when every identified amount is pinned. `DesignResult.ranges` maps each amount to its wide range (low, high). Without `ranges=True`, `unique` is `None` on the LP route.
  - Why two tolerances: in an LP the width of a near-optimal range is, for small ε, w(ε) = w₀ + c·ε. Here w₀ is the width of the optimal set along that amount, and c is the inverse of the objective's slope there. At a unique vertex w₀ = 0, so the width falls a hundredfold from ε₁ to ε₂. On a set of optimal designs it keeps w₀. A single tolerance can't tell the two apart: the width at a unique vertex is ε/slope, which can be any size. In the MAR-245 fixtures it was 6e-6 to 5e-3 of the scale at a near-optimal tolerance of 1e-6, so a fixed width threshold would have called all 15 unique LP optima non-unique. With the two tolerances, the pinned ranges shrank to 1 % or less, and the others kept at least 2e-3 of the scale.
  - The test detects an optimal set only if it is wider than about c·ε₁. A narrower one is reported as unique.
- **MSE route.** The minimiser over the identified amounts is unique exactly when H restricted to them is positive definite. `unique` comes from its smallest eigenvalue (relative tolerance 1e-10).
- **Grid route.** `ties` counts the candidates within the tolerance of the best.
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
- **MSE cases.** §5.4's eigenvalue rule decides. Unique on the identified amounts gives `"exact"`. A singular H gives `"none"`, because the MSE route computes no ranges; this happens in joint cases where two assets' bins hold the same draws.

### 9. Phase 2 extension points

Phase 1 exports only what it implements. Each name below is added to `__all__` when it is built; adding is not breaking, and nothing exported in Phase 1 has to change.

- **The portfolio approach (R-21, MAR-45).**
  - A new function `design_joint(templates, sample, objective, *, scope=Joint(), allocation="value")`. Its objective is on the owner's total loss and total payout over the assets; each asset keeps its own cover. `Clustered(...)` follows the core's cluster scope. `design` stays the per-asset function.
  - The LP and QP routes carry over: B becomes the block matrix over the assets' amounts.
  - A joint payout needs a stated allocation rule (`"value"` or `"loss"`, as in the core's `docs/methodology/payout-allocation.md`) for per-asset rows. The table's `level` column gains `"joint"` and `"cluster"`.
  - Multi-asset Monte Carlo samples need a dependence model: `Comonotonic()`, `Independent()` or `GaussianCopula(correlation)`, always stated and never defaulted. Per-year samples carry their own. Better dependence data is Q4.
  - External text presents joint calibration as a method only (publication rule).
- **Multi-hazard covers (R-22, MAR-250).** `CompositeIndex` (named `IndexDefinition`s), payouts with several `index_names`, `OutcomeSample.index_components`, and the combinator families of §3. Two hazards at one site need a joint distribution; for per-year samples it is the data's own.
- **Scenarios (R-23, MAR-44).** A `ScenarioSet` maps scenario labels to samples with the same assets. `compare` fills the `scenario` column. Robust design (min–max over scenarios, as SPEC §6.5 R1) becomes an objective wrapper, `Robust(objective)`, over a `ScenarioSet`.
- **Also reserved:** the semantics value `"event"` (several events per year); a local refinement after the grid; block-bootstrap intervals and pooled k-fold metrics; a second solver backend in `_solver.py`.

### 10. The issue map

The split into R-14 to R-18 holds, with four adjustments (marked "adjusted").

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| MAR-246 (R-14) | The package skeleton, errors, canonical JSON, `IndexDefinition`, `Free`, the payout protocols and the four families, `Cover`, the registry; the `docs/parametric.md` stub | `__init__`, `errors`, `_canonical`, `index`, `parameters`, `payouts`, `cover` | This ADR is accepted. **Adjusted:** the optional extra moves to R-16, because R-14 needs no solver |
| MAR-43 (R-15) | `OutcomeSample`, the three sources and their semantics rules, `AnnualSeries`, `LossModel`, `NoBasisRisk` and `ImpactNoise`, seeding, the splits. One asset per sample | `sample`, `sources`, `loss`, `basis_risk` | R-14. **Adjusted:** the index from another cell or hazard is the per-year `index=` series; for Monte Carlo it waits for Phase 2 |
| MAR-247 (R-17) | `_risk`, `pricing` (premium values), the metrics, `evaluate`, `compare`, `write_comparison`, `EvaluationMetadata`; parity of the metrics with R-13 | `_risk`, `pricing`, `metrics`, `evaluate`, `metadata` | R-15, R-13. **Adjusted:** "coverage ratio" is E[min(π, L)] / E[L]; the issue's E[π] / E[L] is kept as `payout_to_loss_ratio` (owner decision 6) |
| MAR-248 (R-16) | Objectives, constraints, `design`, the solver interface and the HiGHS backend, the `parametric` extra, the non-uniqueness report; parity of the designs with R-13 | `objectives`, `constraints`, `design`, `_solver`; `pyproject.toml` | R-17, R-13. **Adjusted:** HiGHS through `highspy`, not through scipy (owner decision 2) |
| MAR-42 (R-18) | `ParametricPlan`, `explain()`, both entry points, `PortfolioEvaluation.asset_curves()` if RiskThinking agrees, the finished `docs/parametric.md`, the README line, the end-to-end offline test | `plan`; `workflows/portfolio.py` and `workflows/_portfolio.py` (one additive method) | R-16, Q1 |
| MAR-46 (R-19) | The notebook in the crc-docs fork, following crc-docs' conventions: a row in the README's "Choose a problem" table, a `REQUIREMENTS` set-up cell and static chart previews as [`tests/test_notebooks.py`][docs-tests] checks them. A skill and a pipeline are optional follow-ups | crc-docs fork | R-18 |
| MAR-245 (R-13) | The golden fixtures in this repository, with the fields of §8 | this repository | This ADR is accepted |

### 11. Open questions for RiskThinking (for R-20, MAR-249)

- **Q1. Asset curves.** May R-18 add the public execution point `PortfolioEvaluation.asset_curves()` (the matched canonical rows, through the existing join)? Or would you rather add one yourselves, under another name or in another place?
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
