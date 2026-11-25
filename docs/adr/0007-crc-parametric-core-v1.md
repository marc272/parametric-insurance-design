# ADR 0007: The parametric core on crc-sdk 1.0, and the map of the addition stages

- Status: **Proposed.** Nothing is built until the owner, Marc Prinzing, approves it, as he approved ADR 0005.
- Date: 2026-11-25
- Decision issue: MAR-437 (R-27a). It starts MAR-345: "the stages (both the core parametric framework and the additions) are ready to be published as PRs based on the updated crc release". It records Marc's answers on MAR-435 (Q1 to Q7) and the review of MAR-433.
- Prepared by a worker agent from `main` at `985127d`. Read-only, at these commits; nothing was built or run against CRC data:
  - crc-sdk 1.0.1: `4b84782` (tag `v1.0.1`). Every crc-sdk citation below is `path:line` at this commit;
  - crc-framework 1.0.0: `33420fb` ("Release 1.0.0", 2026-11-24). Its citations are prefixed `fw:`;
  - RiskThinking's unmerged insurance drafts: crc-sdk `upstream/insurance-loss` at `6821eae` (`LossRun`), crc-framework `origin/insurance-loss` at `5466b84`;
  - the 0.11 module: the fork's `parametric` at `c830db5` (the branch is at `bda0cf5`; only `intervals.py` and the docs differ).
- Supersedes nothing. ADR 0005 stays the record of the 0.11 module (§11).

## Decisions at a glance

| # | Decision | Section |
|---|---|---|
| 1 | The core is a recipe inside crc-sdk, in the form of `LossRun`, contributed by PRs into RiskThinking's crc-sdk as PR #41 was (Q1 (a)). A package of our own is the fallback only | §2 |
| 2 | It is built on a new integration branch of the fork, `parametric-v1`, cut from `v1.0.1`; `parametric` (0.11) is frozen | §2 |
| 3 | 15 public names, flat, in 1.0's conventions | §3 |
| 4 | One asset, one hazard, a fitted curve per series; rows per scenario and period as the evaluation gives them | §4, §5 |
| 5 | Four payout families with free terms; MSE, E[U] and weighted CVaR under a budget and a limit; a held-out test from fresh draws | §5 |
| 6 | The core reuses crc-framework for draws, impacts and VaR/CVaR; payouts, basis risk, the other metrics and the design stay in the recipe; HiGHS (`highspy`) is an optional extra | §6 |
| 7 | 60 one-asset golden fixtures (MAR-245) carry over; tests check behaviour | §7 |
| 8 | About 3,500 source lines in three PRs into crc-sdk; no crc-framework PR in the core | §8 |
| 9 | Five addition stages in Q3's order, 5,300 lines in all; a short list dropped for good, as a proposal | §9 |
| 10 | Every module issue states its story and line budget (Q7) | §10 |
| 11 | ADR 0005 is frozen as the record of the 0.11 module | §11 |

## 1. Context

**Marc's decisions on MAR-435** (2026-11-25):

| Q | Decision |
|---|---|
| Q1 home | (a), a recipe inside crc-sdk, contributed like PR #41. Marc is in contact with RiskThinking |
| Q2 scope | (a) the core only: one asset, one hazard, fitted curves; covers with four payout families and free terms; a sample from the curve with the loss and a basis-risk model; evaluate and compare per scenario and period as 1.0's rows give them; design for MSE, E[U] and weighted CVaR under a budget and a limit, with a held-out test. About 3,500 source lines, tests at most that, one docs page of at most 300 lines, at most 15 public names, three PRs of at most about 1,500 lines |
| Q3 the rest | (a) parked on `parametric` (0.11), nothing deleted. A piece returns only through its own issue, naming its story and a line budget. Order: portfolio approach, several hazards, per-year route, a simple interval by year, design extras. Each stage ends ready to be published as PRs on crc-sdk 1.0 |
| Q4 entry | (a) a thin recipe on a 1.0 evaluation, as `LossRun`. `ParametricPlan`, `setup_text` and the metadata document are not ported |
| Q5 solver | (a) HiGHS (`highspy`) is the one backend, an optional extra in crc-sdk. RiskThinking say whether they want it there or in crc-framework |
| Q6 framework | (a) agents read `crc-framework-rs`; read for §6 |
| Q7 growth | (a) this record; then each module issue states its user story and line budget, a rare-path finding is a documented limit unless it breaks a story, and tests check behaviour, not message texts |

**The review (MAR-433)**, the CRC project's document "Review: `crc_sdk.parametric` against the goal, its size and crc-sdk 1.0 (MAR-433)", and its notes `A_source_inventory.md`, `B_tests_docs_history.md` and `C_v1_mapping.md`:

- The 0.11 module is 29 files and 43,101 lines, with 114 public names (A, "Headline numbers"); its tests are 66,027 lines (B, §1.1) and its docs page 4,863 (C, §1 "Sizes").
- By the review's tags, 10,827 lines are core to the three stories on one asset; 20,790 support them and 11,484 serve several assets or hazards (A).
- 14 of its 29 files import 0.x names that 1.0 removed, and 11 import pydantic, which 1.0 doesn't depend on (C, §3).
- crc-sdk 1.0.1 is 30,578 source lines (`cat crc_sdk/**/*.py | wc -l` at `4b84782`) and exports 109 names (`crc_sdk/contracts/api/public-api.json`, `exports`).

## 2. The home: a recipe inside crc-sdk (Q1 (a))

**The form is `LossRun`'s** (crc-sdk `upstream/insurance-loss`, `crc_sdk/_loss.py:71-216`): private modules `crc_sdk/_parametric*.py`, flat names exported from `crc_sdk`, one recipe that takes an `Evaluation` and keyword-only typed declarations, the terminals `explain`, `validate`, `read`, `write` and `execute`, a result, a reopenable artifact, and 1.0's errors and failure rows. A public submodule is ruled out: `"root_imports_only": true` (`public-api.json:4986`) and the runtime check rejects any undeclared public attribute (`tools/api_contracts/check.py:754`).

**In-tree, it uses the private pieces `LossRun` uses**, which a contribution may:

| Piece | Where | Use |
|---|---|---|
| `_Plan.source` | `crc_sdk/_evaluation.py:115` | the evaluation's dataset, whose rows hold the curves (`LossRun` reads `evaluation._plan`, `_loss.py:51,261`) |
| `ExecutionScope` | `crc_sdk/_graph.py:286` | one execution resolves each source once (`AGENTS.md:52-53`) |
| `_publication_path` | `crc_sdk/_terminals.py:585` | atomic publication, no overwrite by default (`AGENTS.md:54-55`) |

**Where it is built.** In the fork `marc272/crc-sdk`, on a new integration branch `parametric-v1` cut from `v1.0.1`; issue branches are cut from it, as from `parametric` today. `parametric` stays at 0.11 as the parked source (Q3). Marc opens the PRs into RiskThinking's crc-sdk (MAR-249).

**The fallback (b)**, if RiskThinking decline: the same files become a package of our own on crc-sdk and crc-framework, with the same names. Three changes, about 100 lines: the recipe takes the curves' `Dataset` as a keyword, since `_Plan` is private; it writes through its own temporary file and `os.replace`; and its execution holds the evaluation's own `execute()` scope. Its `Explanation`, `Operation`, `ExecutionReport` and `ExecutionDiagnostic` would rest on constructors the contract doesn't declare (`public-api.json:2202-2232`, `:3281`).

**The files** (budgets in §8):

| File | Holds | Imports crc-sdk |
|---|---|---|
| `_parametric_cover.py` | the declarations of §3 but the recipe and its outputs | no |
| `_parametric_payouts.py` | the four families: payouts, the basis matrix, the amount constraints | no |
| `_parametric_sample.py` | draws from a curve, the loss, the basis-risk model | no (crc-framework only) |
| `_parametric_metrics.py` | the metrics of §5 on arrays | no (crc-framework only) |
| `_parametric_design.py`, `_parametric_solver.py` | the grid, the LP and QP, the checks; HiGHS behind the extra | no |
| `_parametric_run.py` | `ParametricRun`, `ParametricExecution`: the join, the series, the rows | yes |
| `_parametric_result.py` | `ParametricResult`, `ParametricMetadata`, `ParametricDesignRecord`, `ParametricArtifact` | yes |

The numerics are plain functions on numpy arrays, and only the last two files touch crc-sdk. So the numerics can move to crc-framework (§6) or into a package of our own without change.

## 3. The public surface: 15 names

Signatures are outlines; types from crc-framework are written `cf.`. Story 1 is "create a cover", 2 "analyse it", 3 "compare covers".

| # | Name | Signature | Story | PR |
|---|---|---|---|---|
| 1 | `PayoutKind` | enum: `LINEAR`, `STEP`, `PIECEWISE_LINEAR`, `BINARY` | 1 | 1 |
| 2 | `ParametricCover` | `(kind: PayoutKind, *, thresholds: Sequence[float \| FreeTerm], amounts: Sequence[float \| FreeTerm], tail: cf.Tail, monotone: bool = True, label: str \| None = None)`; `id`, `payout(index) -> NDArray[float64]`, `resolve(terms: Mapping[str, float]) -> ParametricCover`, `to_json()`, `from_json(text)` | 1 | 1 |
| 3 | `BasisRisk` | `BasisRisk.none()`, `BasisRisk.impact_noise(*, sigma: float, upper: float \| None = None)` | 2 | 1 |
| 4 | `ParametricSampling` | `(*, draws: int, seed: int, basis_risk: BasisRisk, test_draws: int \| None = None)` | 2 | 1 |
| 5 | `ParametricRun` | `(evaluation: Evaluation, *, damage_response: str, value: str \| float, loss_unit: str, covers: Sequence[ParametricCover], sampling: ParametricSampling, design: ParametricDesign \| None = None, levels: Sequence[float] = (0.9, 0.95, 0.99), return_periods: Sequence[float] = (2, 5, 10, 25, 50, 100, 250))`; `explain(*, runtime=None) -> Explanation`, `validate(*, runtime=None) -> ExecutionReport`, `read(*, runtime=None) -> ParametricResult`, `write(path, *, overwrite=False, runtime=None) -> ParametricArtifact`, `execute(*, runtime=None) -> ParametricExecution` | 1, 2, 3 | 1 |
| 6 | `ParametricResult` | `table: pa.Table`, `covers: tuple[ParametricCover, ...]`, `metadata: ParametricMetadata`, `report: ExecutionReport` | 2, 3 | 1 |
| 7 | `ParametricMetadata` | `schema_version`, `evaluation: EvaluationMetadata`, `covers`, `sampling`, `design`, `designs: tuple[ParametricDesignRecord, ...]`, `levels`, `return_periods`; `to_json()`, `from_json(text)` | 2, 3 | 1 |
| 8 | `FreeTerm` | `(*, lower: float = 0.0, upper: float \| None = None, grid: int \| Sequence[float] \| None = None)` | 1 | 2 |
| 9 | `Objective` | `Objective.mse()`, `Objective.expected_uncovered()`, `Objective.weighted_cvar(*, alpha: float, beta: float)` | 1 | 2 |
| 10 | `Pricing` | `Pricing.pure()`, `Pricing.cost_of_capital(*, rate: float, level: float)` | 1, 2 | 2 |
| 11 | `Budget` | `Budget.ratio(value: float)`, `Budget.amount(value: float)` | 1 | 2 |
| 12 | `ParametricDesign` | `(objective: Objective, *, budget: Budget \| None = None, limit: float \| None = None, pricing: Pricing \| None = None, series: SeriesReference \| None = None, max_grid_points: int = 10_000)` | 1 | 2 |
| 13 | `ParametricDesignRecord` | `cover_id`, `design_id`, `route`, `status`, `objective_value`, `premium`, `unidentified`, `unique`, `ties`, `degenerate_tail`, `solver` | 1 | 2 |
| 14 | `ParametricExecution` | context manager: `read()`, `validate()`, `write(path, *, overwrite=False)`, `report` | 2, 3 | 3 |
| 15 | `ParametricArtifact` | `open(path)`, `read()`, `validate()`, `path`, `metadata` | 2, 3 | 3 |

- **Terms.** A cover's terms are its index-unit `thresholds` and its payout-unit `amounts`, read per family as ADR 0005 §3's table: `LINEAR` (attachment, exhaustion; limit), `STEP` (breakpoints; levels), `PIECEWISE_LINEAR` (knots; levels), `BINARY` (trigger; amount). Term names are `thresholds[i]` and `amounts[i]`. One class with a kind replaces ADR 0005's four classes, its protocol and its registry.
- **Closed choices are enums or named constructors**, as `Probability.annual(tail=...)` is (`crc_sdk/_declarations.py:353`). `BasisRisk`, `Objective`, `Pricing` and `Budget` have no public `__init__`.
- **The design series** is a 1.0 `SeriesReference` (`crc_sdk/_inspection.py:85`), as `inspect().series` lists them. It may be omitted only when the evaluation reads one series.
- **The value** is an asset column carried by `Assets(columns=[...])` (`crc_sdk/_assets.py:336`) into the evaluation's `asset` field, or one number. `loss_unit` is an exact identifier, recorded.
- **The table is long**, like 1.0's evaluation rows: `asset_id`, `variable_id`, `scenario_id`, `period_id`, `support_id`, `cover_id`, `cover_label`, `design_id`, `split` (`"design"` or `"test"`), `metric`, `level` (β or T, or null), `value`, `failure` (`code`, `message`, as in `crc_sdk/_evaluation_schema.py:867-874`). The column set is fixed whatever the levels, so no metric name depends on β or T.
- **Errors.** No new exception class. Constructor misuse raises `TypeError` or `ValueError`. A refused setup (several assets or variables, no response named `damage_response`, a design series that isn't read) is an `ExecutionDiagnostic` (`crc_sdk/_dataset_schema.py:274`): `validate()` returns it, and the other terminals raise `ValidationError(report=)` (`crc_sdk/_errors.py:13`; `docs/execution.md:184-187`). A per-series problem is a failure row and a warning diagnostic, and the run goes on: `no_covering_support` (passed through), `curve_unavailable`, `curve_not_fitted`, `probability_not_annual`, `tail_mismatch`, `damage_unavailable`, `value_unavailable`, `design_infeasible`, `design_unbounded`, `solver_limit`. A missing extra raises an `ImportError` naming it (`docs/development.md:56-57`), and `explain()` lists it as a `Requirement`, as `LossRun` lists missing columns (`_loss.py:49-60`).
- **Stages.** `explain()` adds `Operation`s to the evaluation's own explanation with 1.0's stages: `Stage.DECODING` (curves), `Stage.JOINING` (curves to rows), `Stage.EVALUATION` (draws, design, metrics), `Stage.WRITING` (`crc_sdk/_dataset_schema.py:261`). 1.0 has no design stage; `LossRun` uses `EVALUATION` too (`_loss.py:186-193`).

**How the names enter `public-api.json`, and what that means for a contribution.** Each name gets one entry with its constructor, methods, parameter kinds, annotations, defaults and properties; the list stays sorted (`check.py:268`); every annotation must resolve to a declared name (`check.py:97`), which is why the design record is a name; the framework types the signatures use (`cf.Tail`) go in `external_symbols` (`public-api.json:4918`), and no framework type is re-exported (`check.py:410`). `__all__` must equal the exports and no other public attribute or member may exist (`check.py:745, 754, 851`). So a PR into crc-sdk carries, beside the code: the contract entries; the `__init__.py` imports; a row in `docs/api-reference.md` and `docs/README.md`; a docs page whose Python examples run offline under `tools/check_examples.py`; and, with the artifact (PR 3), a format `parametric` in `release.json` with its JSON Schema and generator. The checker hard-codes the set of formats (`check.py:246-258`), so it changes too, as `LossRun`'s did (+20 lines, C §5). The base wheel must import and pass `check.py --runtime` without `highspy` (`.github/workflows/ci.yml:145-161`).

## 4. What the core reads from crc-sdk 1.0

| What | Symbol | At `v1.0.1` |
|---|---|---|
| The evaluation | `Evaluation`, `.probabilities`, `.impact`, `.explain`, `.execute`, `.write` | `crc_sdk/_evaluation.py:992, 1064, 1079, 1099, 1260, 1265` |
| Its dataset (in-tree) | `_Plan.source`, `_Plan.assets` | `crc_sdk/_evaluation.py:114-116` |
| Its rows | `evaluation_arrow_schema`: `asset_id`, `variable_id`, `scenario_id`, `period_id`, `support_id`, `response_id`, `resolution_id`, `query_value`, `value`, `failure` | `crc_sdk/_evaluation_schema.py:863-911` |
| Row failure codes | `no_covering_support`, `overlapping_supports`, `query_outside_support` | `crc_sdk/_evaluation_schema.py:68-70` |
| The asset, the series | `Dataset.evaluate`, `Assets(..., columns=)`, `SpatialMatch` | `crc_sdk/_recipes.py:2019`; `crc_sdk/_assets.py:315, 336`; `crc_sdk/_evaluation_spatial.py:58` |
| The curves | dataset rows keyed by `(variable_id, scenario_id, period_id, support_id, cell_id)`; `decode_curves(rows)` → `cf.Distribution \| cf.QuantileCurve \| None` | `docs/datasets.md:22`; `crc_sdk/_curves.py:11-22` |
| A fitted curve | `Dataset.fit(spec)` | `crc_sdk/_recipes.py:2055` |
| The impact | `EvaluationMetadata.resolutions` → `EvaluationResolution(response_id, impact: cf.Impact, asset_ids, context)` | `crc_sdk/_evaluation_schema.py:212, 470, 476` |
| Scenario and period | `Scenario`, `Period`, `SeriesReference` | `crc_sdk/_declarations.py:213, 269`; `crc_sdk/_inspection.py:85` |
| Units and semantics | `Variable(measurement=)`, `Probability.annual(tail=)`, `ProbabilityKind` | `crc_sdk/_declarations.py:179, 353, 47` |
| Execution | `Runtime`, `ExecutionScope`, `_publication_path` | `crc_sdk/_runtime.py:137`; `crc_sdk/_graph.py:286`; `crc_sdk/_terminals.py:585` |
| Reports and errors | `ExecutionReport`, `ExecutionDiagnostic`, `Stage`, `ValidationError`, `CapabilityError` | `crc_sdk/_dataset_schema.py:387, 274, 261`; `crc_sdk/_errors.py:13, 8` |
| Explanation | `Explanation`, `Operation`, `Requirement` | `crc_sdk/_inspection.py:216, 74, 61` |

**The join.** No terminal returns the fitted curve per asset (C, row 1). The recipe reads the evaluation's rows for the asset's `support_id` per series, reads `_Plan.source`'s rows for those series and supports, joins on the dataset key and calls `decode_curves`. Whether that join is intended is RiskThinking's question 4 (§13).

**The loss.** The user names a response added with `.impact(name, model, variable=, context=)`. The recipe takes that asset's resolved `cf.Impact` from the evaluation's metadata and applies it to the drawn hazard values. So 1.0 checks the measurement and the context and records them, and the core holds no impact logic. Only four built-in models bind in `.impact(...)` (`docs/migration-v1.md:389-393`); user `Impact.linear`, `tabulated`, `binned` and `sigmoid` models bind too.

**Checks the core makes on 1.0's facts:** the series declares `ProbabilityKind.ANNUAL` (replacing ADR 0005 §4.2's semantics rules); the cover's `tail` equals the series' probability tail (ADR 0005 §3); the decoded curve is a `cf.Distribution`. A `cf.QuantileCurve` is `curve_not_fitted`, because it has no values outside its knot interval (fw: `docs/python.md:64`). Its remedy is `Dataset.fit`, or `complete(TailCompletion)` before the dataset is built, which states the tails (fw: `python/crc_framework/_distribution.py:937`).

## 5. The numerics

Plain functions on numpy arrays, in the files of §2.

| Part | The core | ADR 0005 carried over unchanged |
|---|---|---|
| Payout families | four families, half-open bins on the severe side, nothing below the first threshold, amounts ≥ 0, `monotone` | §3: "Severity", the families' table, "Nothing below the attachment", "Boundaries", "Constraints of the family"; the `Free` rules as `FreeTerm` |
| The sample | n design draws and m test draws per series. Uniforms u from `numpy.random.default_rng(seed)` (design) and an independent child stream (test); hazard = `curve.quantile(u)`; loss = `impact.evaluate(hazard)` × value; then the basis-risk model. Every series of the run reads the same uniforms, so scenarios and periods are compared on shared draws | §4.4's draw order (hazard uniforms first, then the basis-risk model) and `NoBasisRisk`; `ImpactNoise` |
| Metrics | `expected_loss`, `expected_payout`, `premium`, `expected_uncovered`, `coverage_ratio`, `payout_to_loss_ratio`, `tail_coverage`, `cvar_uncovered_to_loss`, `false_negative_rate`, `false_positive_rate` (ℓ = ε = 0, recorded), `rmse`, `correlation`, VaR and CVaR of uncovered loss, net loss and loss, and the four return levels | §6: notation, "The premium used", "VaR and CVaR", "Tail weights", the metrics' definitions and null rules; "In and out of sample" |
| Design | a grid over free thresholds; at each point the amounts by an LP (E[U], weighted CVaR) or a QP (MSE); MSE under a cost-of-capital budget by cutting planes; scaling; numpy verification of every constraint; `unidentified` with the fill rule; MSE uniqueness by eigenvalue; grid ties; degenerate tails | §5.1 (but `UserObjective`), §5.2 (but `ExpectedPayoutMultiple`), §5.3's table rows 1 to 4, "The grid", "Why a grid", "Scaling", "No silent failures"; §5.4's "Unidentified amounts", "MSE route", "Grid route", "Degenerate tails"; §5.5's QP route for at most 100 columns and its LP rule |
| Solver | HiGHS (`highspy`) for LPs and for the dense active-set QP's LPs, imported lazily, in the extra `crc-sdk[parametric] = ["highspy>=1.13,<2"]` (the floor of 0.11, `pyproject.toml:58-60` at `c830db5`) | §5.5's policy and choice of highspy |

**What the core changes against ADR 0005:**

- **A held-out test from fresh draws.** On a fitted curve the draws are i.i.d., so the test sample is m fresh draws on the second stream (ADR 0005 §4.4, "Splits"). Year-block holdout and k-fold return with the per-year route (stage 3). Rows say `split`; external numbers come from `"test"` rows (publication rule).
- **The premium used** on test rows is the design premium; a stated cover is priced on its own sample.
- **No QP above 100 columns.** A template with more than 100 free amounts is refused at construction, so HiGHS's QP solver, its limits and the fallback of §5.5 aren't ported.
- **The LP route doesn't range.** `unique` is null on LP designs, as with `ranges=False` in 0.11. Ranges, which the owner made the default on MAR-405, return with stage 5.
- **Not in the core:** the numpy grid over every free parameter (only `UserObjective` needed it), the local refinement (§5.3), `ExpectedPayoutMultiple`, `HazardNoise`, `payout_frequency`, `unidentified_share`, the short-block flags, metric thresholds other than 0, and the leakage, pairing and lineage checks. Draws from one seed per run can't leak between design and test.
- **Determinism** comes from an integer `seed` recorded in the metadata, as crc-framework's `Distribution.sample(size, *, seed)` takes one (fw: `_distribution.py:437-449`). No global seed.

## 6. Integration with crc-framework

**What it is** (fw: `AGENTS.md`, `README.md`). The numerical core of CRC: one Rust crate, `crates/core`, with PyO3 bindings (`src/`, `crc_framework._core`), a typed Python API (`python/crc_framework`, 88 exports in its `public-api.json`), and WASM/JS. It holds about 581,000 lines of Rust, of which 559,250 are reference data under `crates/core/src/reference/`, and 5,212 lines of Python (`git ls-files` and `wc -l` at `33420fb`). Its Python package depends on `numpy` and `jsonschema` only (fw: `pyproject.toml`), and `Cargo.lock` has no LP or QP solver; its one optimiser is the likelihood search of its curve fits (fw: `crates/core/src/distribution.rs:1336`).

**What it already does that the core needs:**

| Need | crc-framework 1.0.0 | Fit for the core |
|---|---|---|
| Draw hazard values from a curve | `Distribution.quantile(probabilities)` takes arrays and keeps their shape (fw: `_distribution.py:374`; `docs/python.md:22-24`). `Distribution.sample(size, *, seed)` is `quantile(numpy.random.default_rng(seed).random(size))` (fw: `_distribution.py:437-449`) | Reused. The recipe draws its own uniforms with the same generator, so that series share draws and the basis-risk draws follow, then calls `quantile` |
| Supplied quantiles | `QuantileCurve`: no sampling; a query outside `probability_interval` raises `ValueError`; `complete(TailCompletion)` and `condition(q_min, q_max)` make a complete law (fw: `_distribution.py:819-960`; `docs/python.md:64-77`) | Refused as `curve_not_fitted` (§4); completion is the user's stated choice |
| An impact on arrays | `Impact.evaluate(values)` on arrays (fw: `_impacts.py:351`); `ImpactReference.resolve(context)` (fw: `_impacts.py:1036`) | Reused, through the evaluation's resolutions (§4) |
| Exact laws of a response | `Impact.expectation`, `Impact.pushforward` (fw: `_impacts.py:544, 564`) | Not in the core: the design needs the joint draws of index and loss. A later route for E[π] of a stated cover |
| VaR and CVaR of weighted draws | `Distribution.discrete(values, probabilities)` (fw: `_distribution.py:307`); its `quantile` is the lowest value whose rounded cumulative probability reaches q (fw: `crates/core/src/numerical.rs:926-932`); `statistics(metrics=[Statistic.CVAR], level=, tail=)` integrates the tail exactly, a partial atom included (fw: `_distribution.py:451`; `numerical.rs:617-654`) | Reused for VaR, CVaR and the return levels. The CVaR equals ADR 0005 §6's. The VaR lacks §6's 1e-10 slack; the fixtures write a quantile on a step as `{"either": [...]}` (ADR 0005 §8), so both pass. The tail weights, coverage and rates stay in numpy |
| Payout-like functions | `Impact.linear(..., minimum=, maximum=)` (fw: `_impacts.py:254`); `Impact.binned` with bins `[e_i, e_{i+1})` (fw: `crates/core/src/impact/kernel.rs:68-70`) and `Impact.tabulated`, both refusing values outside their finite domain (fw: `_impacts.py:295-337`; `kernel.rs:26-49`) | Not reused: `LINEAR` is `Impact.linear` clamped to [0, ℓ], but step, binary and piecewise-linear payouts must pay 0 below and stay flat above any value, and the design needs the basis matrix in the amounts. Question F2 (§13) |
| Units of money | an open `Measurement(quantity=, unit=)` needs no registration (fw: `_measurement.py:556-579`) | A later typed `loss_unit`; the core records a string |
| Random numbers | Python: numpy `default_rng(seed)` (PCG64) (fw: `_distribution.py:448`). Rust: `rand` 0.9 behind the default feature `sampling` (fw: `crates/core/Cargo.toml:11-22`). The unmerged insurance branch: ChaCha12 streams keyed by SHA-256 of a versioned algorithm name, primary and secondary (fw: `origin/insurance-loss:crates/core/src/insurance/sampling.rs:1-60`) | The core follows the Python convention and records `numpy.random.PCG64`. Pairing with `LossRun`'s trials would need its primary ranks (RiskThinking's question 3) |

**Does 1.0 change the golden fixtures?** No. Every case of MAR-245 carries its index and loss arrays, design and evaluation blocks alike (ADR 0005 §8); none holds a curve, so 1.0's curve changes (fw: `docs/migration-v1.md:36-50`) don't touch them. They change the 0.11 module's tests on curves, which aren't ported.

**Which numerics belong where.** 1.0's rule puts numerical algorithms in crc-framework (`docs/development.md:60-61`; `AGENTS.md:44-45`). Recommendations:

| Numeric | Recommendation | Reason |
|---|---|---|
| Draws, impacts, VaR, CVaR | crc-framework, as it is | Reuse; no new code there |
| Payout families | the recipe now; crc-framework later, as an `Impact` kind or a payout type, if RiskThinking want it | Each family is 10 to 30 lines of numpy plus its basis matrix. In crc-framework one would be Rust in `crates/core`, a PyO3 binding with `py.detach`, a typed wrapper, a `_core.pyi` stub, a contract entry, a numerical-document schema for JS, and Rust and Python tests: several times the lines, and a framework release before the SDK PR |
| Basis risk (`ImpactNoise`) | the recipe | Three lines of numpy on the recipe's generator. The nearest framework concept, the insurance branch's secondary damage draws, isn't on `main` |
| Tail coverage, coverage ratio, rates, correlation, RMSE | the recipe | Short numpy expressions over the design's draws; no framework counterpart |
| Design LP/QP | the recipe, with `highspy` as an optional extra (Q5) | crc-framework has no solver. A Rust HiGHS binding builds HiGHS's C++ and would not serve the WASM target; whether a solver may enter the Rust core is RiskThinking's question 5 |

**How crc-framework takes contributions** (fw: `AGENTS.md`; `docs/development.md`; `docs/releases.md`):

| Topic | Convention |
|---|---|
| Language and layout | Algorithms in Rust (edition 2024, Rust ≥ 1.87) in `crates/core`, "edit here first"; PyO3 0.29 bindings in `src/`, long calls releasing the GIL (`py.detach`); a typed Python wrapper in `python/crc_framework/_*.py`; `_core.pyi` matching `src/`; WASM in `crates/wasm` and `js/` |
| Interface | `public-api.json` and `release.json` as in crc-sdk; one name per concept; enums for closed choices; `tools/api_contracts/check.py`, with `--runtime` on the wheel |
| Tests | `cargo fmt`, `cargo clippy -D warnings`, `cargo test`; `pytest` and `mypy` after `maturin develop`; shared accepted and rejected fixtures; explicit numerical tolerances |
| Release | one version in the root `Cargo.toml`, matching `release.json`; the framework is released before an SDK that needs it (crc-sdk `docs/development.md:89-91`) |
| Licence | AGPL-3.0-or-later, as crc-sdk |
| Precedent | RiskThinking's own insurance numerics on `origin/insurance-loss`: 1,988 lines of Rust in `crates/core/src/insurance/`, a 300-line binding, a 682-line Python wrapper, +449 contract lines and 774 lines of Python tests (`git diff --numstat` against `main`) |

**What that does to the budget and the PRs.** With the recommendations, the core needs no crc-framework PR, and reusing its VaR and CVaR saves about 50 lines (§8). If RiskThinking want the payouts or metrics in crc-framework, that is a PR series into crc-framework first: on the precedent above, about 1,500 to 2,000 lines of Rust, bindings, contract and tests for the four families. It needs a fork of crc-framework among the program's repositories, which is Marc's call (question M1, §13). The crc-sdk PRs then shrink by their numpy files and wait for a framework release.

## 7. Tests and parity

- **Offline and synthetic**, in crc-sdk's `tests/`, under `pytest`, `mypy` (strict) and `ruff`. Test lines at most the source's, per PR.
- **Behaviour, not message texts** (Q7): a test asserts the type of an error, a failure code or a value, never the words of a message.
- **The golden fixtures** (MAR-245, `parity/crc/`): the core keeps the 60 one-asset cases of the 100. By `scope`, `kind`, `split` and `pricing` (counted from the case files): 23 core designs on the whole sample, 1 closed-form design, 4 core and 16 closed-form evaluations of fixed covers, and 16 designs with an evaluation block (8 holdout, 6 k-fold, 2 fresh draws); 37 under pure pricing and 23 under a cost-of-capital load; `compare_parameters` is `"exact"` in 40 and `"none"` in 20, so none needs ranges. Every case gives its evaluation block, so the k-fold and holdout cases test the design and the metrics without the splits. The 40 joint and cluster cases return with stage 1.
- **Their size.** The 60 cases are 21,052 lines and 635,592 bytes as written, 473,161 bytes minified (measured). They are copied minified, one case per line, into one JSON Lines file with a README that keeps each case's licence (CC0-1.0, and CC-BY-4.0 with the attribution for the 14 `thesis` cases; `parity/crc/README.md`). The data counts toward no line budget. RiskThinking may want less data (question 7): the 46 CC0 cases alone are 425,030 bytes as written.
- **The recipe's tests** build an evaluation in memory with `Dataset.from_quantiles` and `Dataset.fit`, as 1.0's guides do (`docs/evaluation.md`), and check rows, failure codes, shared draws across series, the design and test splits, explain without I/O, and the artifact's round trip.

## 8. The budget and the PR split

**Source budget: about 3,500 lines**, docstrings included (1.0's style is short: `AGENTS.md` asks for no narration, and its docs keep compact examples):

| File | Lines | Against 0.11 |
|---|--:|---|
| `_parametric_cover.py` | 550 | `cover.py`, `parameters.py`, `objectives.py`, `pricing.py`, `constraints.py`, `basis_risk.py` CORE-tagged: 1,321 (A) |
| `_parametric_payouts.py` | 350 | `payouts.py` CORE: 888 |
| `_parametric_sample.py` | 250 | sampling on curves and the basis-risk models, concern d: 1,235 |
| `_parametric_metrics.py` | 250 | `metrics.py` and `_risk.py` CORE: 693 |
| `_parametric_design.py` | 650 | `design.py` CORE: 1,934 |
| `_parametric_solver.py` | 450 | `_solver.py` CORE: 1,079 |
| `_parametric_run.py` | 600 | the plan's core builders and execution, concern m: 7,268 for both routes |
| `_parametric_result.py` | 400 | `evaluate.py` CORE: 1,353 |
| **Total** | **3,500** | |

The design and the solver are the tightest, at 1,100 lines against 3,013 CORE-tagged lines in 0.11. They fit because the core drops the HiGHS QP path and its fallback, the ranges, the refinement and the numpy grid (§5). If a PR overruns its file's budget by more than 10 %, the issue stops and reports to Marc with the number (§10).

**One docs page**, `docs/parametric.md`, at most 300 lines, whose examples run under `tools/check_examples.py`.

**Three PRs into crc-sdk**, each at most about 1,500 lines of source, with its tests (at most its source) and its share of the contract and docs on top:

| PR | Content | Names | Source | Story it completes |
|---|---|---|--:|---|
| 1 | Stated covers on a fitted curve: `PayoutKind`, `ParametricCover`, `BasisRisk`, `ParametricSampling`; payouts, the sample, the metrics; `ParametricRun` with `explain`, `validate` and `read`; `ParametricResult`, `ParametricMetadata`; the 20 evaluation fixtures | 7 | 1,500 | 2 and 3 for stated covers: metrics per cover, scenario and period, covers side by side |
| 2 | Design: `FreeTerm`, `Objective`, `Pricing`, `Budget`, `ParametricDesign`, `ParametricDesignRecord`; the grid, LP, QP, cutting planes and checks; the extra; test draws and the `split` column; the 40 design fixtures | 6 | 1,350 | 1: a cover designed for a goal under a budget and a limit, with held-out numbers |
| 3 | Persistence and the guide: `ParametricExecution`, `ParametricArtifact`; `write` and `open`; the format `parametric` 1.0 with its schema and generator; the docs page | 2 | 650 | 1 to 3 as a 1.0 user runs them, saved and reopened |

- **"About 1,500 lines" is read as source lines.** With tests up to the source and the contract entries, a PR's diff is up to about 3,200 lines; PR 3 adds a generated schema (`LossRun`'s was 808 lines, C §5). If Marc meant the whole diff, the core needs five or six PRs, or tests at about half the source. The budget is Marc's to change.
- **The names fill the cap of 15.** A sixteenth needs Marc.

## 9. The addition stages, in Q3's order

Each stage is an issue series, each issue with its story and budget (§10), and ends as PRs on crc-sdk 1.0 of at most about 1,500 source lines each. The 0.11 lines are the review's subject totals (A, "Lines by subject").

| Stage | User story | Adds to the surface | Budget | 0.11 |
|---|---|---|--:|--:|
| 1. Portfolio approach | One risk owner with several sites designs covers on the owner's total loss and payout; joint calibration as a method (publication rule) | several assets in one run; `CalibrationScope` (`individual()`, `joint()`, `clustered(clusters)`); `Dependence` (`independent()`, `comonotonic()`, `gaussian(correlation)`) for draws across assets; `PayoutAllocation` (`VALUE`, `LOSS`); rows at the total and per asset; the 40 joint and cluster fixtures | 1,500 | 5,968 (dependence and scopes) |
| 2. Several hazards | A cover that pays on two hazards at one site | an evaluation of a `DatasetCollection` (`crc_sdk/_collection.py:847`); `PayoutCombination` (`SUM`, `MAX`); `LossCombination` (a capped sum of damages); dependence across hazards from stage 1 | 1,200 | 5,516 |
| 3. Per-year route | A cover on observed or modelled years (`Samples`: ERA5, CMIP6, GHCNh) | `ParametricRun.from_samples(samples, assets, *, ...)`; the asset matched to its support by the recipe, since `Samples` can't be evaluated (`crc_sdk/_terminals.py:203-225`); `YearSplit` (holdout, k-fold by year blocks); a second series as the index | 1,000 | 3,504 |
| 4. A simple interval by year | A metric reported with an interval from resampled years or draws | `ParametricInterval(*, level, resamples, seed)`; `lower` and `upper` on the rows. Whole years are resampled, all assets and hazards of a year together; no re-dealing of rank blocks | 400 | 1,829 |
| 5. Design extras | Finer control of a designed cover | `unique` and ranges on the LP route (ADR 0005 §5.4); the local refinement (§5.3); `Pricing.expected_payout_multiple`; `BasisRisk.hazard_noise` (Amendment 6, F2); a budget frontier; metric thresholds ℓ and ε; `payout_frequency`, `unidentified_share` | 1,200 | 2,913 |
| **Total** | | 7 names | **5,300** | |

With the core: about 8,800 source lines and 22 names, against 43,101 lines and 114 names in 0.11.

**Parked, not staged.** Scenario sets with their refusals and windows of horizons as mixtures (ADR 0005 Amendment 4), trend treatments (Amendment 2), pools of model runs, `StepGrid`, re-dealt rank blocks in intervals, and the leakage checks. Each returns only through its own issue (Q3).

**Proposed to drop for good** (Marc decides):

- `ParametricPlan`, `setup_text` and the metadata document (Q4 decided it);
- `register_payout`, a process-global registry, which 1.0 says it doesn't have (`docs/scientific-data.md:79`);
- `UserObjective` and the numpy grid route, which take an arbitrary callable, as 1.0 removed for impacts (`docs/migration-v1.md:326`);
- the 15 error classes and the warning of 0.11, against 1.0's two exceptions and failure rows (`docs/migration-v1.md:629`);
- `write_comparison` and `to_long`: the table is long, and writing is the `write` terminal;
- 0.11's patches to 0.x (`asset_curves()`), gone with 0.x.

## 10. The rule against growing again (Q7)

- **Every module issue** states its user story (one of the three, or a stage's) and a line budget for source and tests. The PR body reports both against the actuals.
- **A rare-path finding is a documented limit** in the docs page, unless it breaks a story. Breaking a story means a wrong number in a row, a run that doesn't return, or a refused setup that a story needs.
- **Tests check behaviour:** types, failure codes and values, never message texts.
- **Overruns stop the issue.** A PR more than 10 % over its budget, or a sixteenth name in the core, goes to Marc with the number and the reason.
- **No narration** in code or docs (crc-sdk `AGENTS.md:63-64`). Issue IDs stay in the PR's title, body and trailers.

## 11. What ADR 0005 becomes

ADR 0005 is the frozen record of the 0.11 module on `parametric`. It is at 511,983 bytes against the repository's cap of 512,000 (`wc -c`), and gets no more errata. This record cites its sections where a decision carries over (§5); it never amends it. A later finding about the 0.11 module goes to that module's issue, not to ADR 0005.

## 12. Consequences

- The core is small enough to review: about 3,500 lines and 15 names, against 43,101 and 114.
- The loss side, the curves, units, scenarios, periods, failures and execution are 1.0's, so the core holds no impact, unit or provenance logic.
- The core loses, until a stage returns them: per-year samples, several assets or hazards, intervals, LP ranges and the refinement.
- Hashes and `design_id`s differ from 0.11's; the golden fixtures hold none (ADR 0005 §5.4).

## 13. Open questions

**RiskThinking's** (MAR-435's list; Marc asks them):

| # | Question | What the answer changes here |
|---|---|---|
| 1 | The home | Decided (a) on our side. A no moves the core to the fallback of §2 |
| 2 | Does `LossRun` go into 1.0, and should a parametric recipe take the same inputs? | §3: `ParametricRun` would take `LossRun`'s inputs, or a `LossResult`, beside its own |
| 3 | Per-trial hazard values or ranks for pairing | §6: a cover could be read on `LossRun`'s trials; today the core draws its own |
| 4 | A public seeded way to draw years from a curve per asset; is joining evaluation rows to dataset rows on `support_id`, then `decode_curves`, intended? | §4: the join (about 100 lines) would become one call |
| 5 | The solver dependency: crc-sdk extra or crc-framework | §5, §6: the extra moves, or the design moves to crc-framework (M1) |
| 6 | Does crc-framework take outside contributions, and in which language? | §6: whether the payouts or metrics can move |
| 7 | The PR size they can review; are `docs/api-reference.md` and `docs/development.md` the API guideline of 2026-11-09? | §7, §8: the split and the fixtures' size |
| 8 | Should open PR #41 be closed and replaced? | §2: the first PR's framing |
| 9 | When do rainfall, wind and heat bind in `.impact()`? | §4: until then a cover on those hazards needs a user model |

**For crc-framework** (to RiskThinking, with question 6):

| # | Question | What it changes |
|---|---|---|
| F1 | Should `Distribution` offer a public inverse survival for draws near q = 1, as crc-sdk uses privately (`crc_sdk/_evaluation.py:893`; fw: `_distribution.py:624`)? | §5: draws in the far upper tail |
| F2 | Would they take a payout as an `Impact` kind with a flat value outside its domain? | §6: payouts and exact expected payouts move to crc-framework |
| F3 | Would they declare constructors for `Explanation`, `Operation`, `ExecutionReport` and `ExecutionDiagnostic`? | §2: the fallback rests on them |

**For Marc:**

| # | Question | What it changes |
|---|---|---|
| M1 | A fork of `crc-framework-rs` among the program's repositories, if any numerics move there | §6, §8: a PR series into crc-framework before crc-sdk's |
| M2 | "About 1,500 lines" per PR: source only, or the whole diff? | §8: three PRs, or five or six |
| M3 | The integration branch's name, `parametric-v1` | §2 |
| M4 | The drop list of §9 | §9 |

## Not verified

- Nothing here was built or run. The budgets are estimates against the review's counts; the sizes measured for this record are the fixtures' (§7), crc-sdk's source lines and exports (§1), crc-framework's line counts and the insurance branch's (§6), and ADR 0005's bytes (§11).
- Whether `Distribution.quantile` on 10,000 or more draws is fast enough per series, and whether `Distribution.discrete(...).statistics` on such draws is fast enough per metric, was not timed.
- Whether CRC Open's curves decode to `cf.Distribution` or to `cf.QuantileCurve` was not checked; if the latter, the core needs `Dataset.fit` before every run.
- The fallback's reliance on undeclared constructors (§2) was read in the contract, not tried.
