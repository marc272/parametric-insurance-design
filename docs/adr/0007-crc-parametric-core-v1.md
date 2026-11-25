# ADR 0007: The parametric core on crc-sdk 1.0, and the map of the addition stages

- Status: **Proposed.** Nothing is built until the owner, Marc Prinzing, approves it, as he approved ADR 0005.
- Date: 2026-11-25
- Decision issue: MAR-437 (R-27a). It starts MAR-345: "the stages (both the core parametric framework and the additions) are ready to be published as PRs based on the updated crc release". It records Marc's answers on MAR-435 (Q1 to Q7) and the review of MAR-433. An independent review of this record (MAR-438) was addressed before Marc's approval.
- Prepared by a worker agent from `main` at `985127d`. Read-only, at these commits; nothing was built or run against CRC data:
  - crc-sdk 1.0.1: `4b84782` (tag `v1.0.1`). Every crc-sdk citation below is `path:line` at this commit;
  - crc-framework 1.0.0: `33420fb` ("Release 1.0.0", 2026-11-24). Its citations are prefixed `fw:`;
  - RiskThinking's unmerged insurance drafts: crc-sdk `upstream/insurance-loss` at `6821eae` (`LossRun`, cited as `loss:`), crc-framework `origin/insurance-loss` at `5466b84`;
  - the 0.11 module: the fork's `parametric` at `c830db5`. The branch is at `bda0cf5` now; `intervals.py`, `metadata.py`, two test files and the docs differ.
- Supersedes nothing. ADR 0005 stays the record of the 0.11 module (§11).

## Decisions at a glance

| # | Decision | Section |
|---|---|---|
| 1 | The core is a recipe inside crc-sdk, in the form of `LossRun`, contributed by PRs into RiskThinking's crc-sdk as PR #41 was (Q1 (a)). A package of our own is the fallback only | §2 |
| 2 | It is built on a new integration branch of the fork, `parametric-v1`, cut from `v1.0.1`; `parametric` (0.11) is frozen | §2 |
| 3 | 15 public names, flat, in 1.0's conventions | §3 |
| 4 | One asset, one hazard; the hazard curve per series is built from the evaluation's own quantile rows, adapting `LossRun`'s route, with a stated tail completion that caps the upper tail (M7); rows per scenario and period | §4, §5 |
| 5 | Four payout families with free terms, priced pure or with a cost-of-capital load; MSE, E[U] and weighted CVaR under a budget and a limit; a held-out test from fresh draws | §5 |
| 6 | The core reuses crc-framework for curves, draws, impacts and VaR/CVaR; payouts, basis risk, the other metrics and the design stay in the recipe, a stated departure from 1.0's rule; HiGHS (`highspy`) is an optional extra | §6 |
| 7 | 58 one-asset golden fixtures (MAR-245) carry over; tests check behaviour | §7 |
| 8 | Re-estimated at about 4,850 source lines in five PRs into crc-sdk, against Q2's 3,500: Marc's call (M5) | §8 |
| 9 | Five addition stages in Q3's order, about 6,450 lines; parked and drop lists, the latter a proposal | §9 |
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

**The form is `LossRun`'s** (`loss:crc_sdk/_loss.py:71-216`): private modules `crc_sdk/_parametric*.py`, flat names exported from `crc_sdk`, one recipe that takes an `Evaluation` and keyword-only typed declarations, the terminals `explain`, `validate`, `read`, `write` and `execute`, a result, a reopenable artifact, and 1.0's errors and failure rows. A public submodule is ruled out: `"root_imports_only": true` (`public-api.json:4986`) and the runtime check rejects any undeclared public attribute (`tools/api_contracts/check.py:754`).

**In-tree, it uses the private pieces `LossRun` uses**, which a contribution may:

| Piece | Where | `LossRun`'s use | Ours |
|---|---|---|---|
| `_Plan.assets`, `.query`, `._selected_responses()` | `crc_sdk/_evaluation.py:114-120, 183` | build-time checks of the query and the damage response (`loss:crc_sdk/_loss_inputs.py:147-190`) | the same checks |
| `_EvaluationNode` | `crc_sdk/_evaluation.py:459` | streams the evaluation's own rows (`loss:_loss_inputs.py:311-360, 428-453`) | the same |
| `ExecutionScope` | `crc_sdk/_graph.py:286` | one execution per run (`loss:_loss.py:226`) | the same (`AGENTS.md:52-53`) |
| `_publication_path` | `crc_sdk/_terminals.py:585` | atomic publication (`loss:_loss.py:38`) | the same (`AGENTS.md:54-55`) |

**Where it is built.** In the fork `marc272/crc-sdk`, on a new integration branch `parametric-v1` cut from `v1.0.1` (name: M3); issue branches are cut from it, as from `parametric` today. `parametric` stays at 0.11 as the parked source (Q3). Marc opens the PRs into RiskThinking's crc-sdk (MAR-249).

**The fallback (b)**, if RiskThinking decline: the same files become a package of our own on crc-sdk and crc-framework, with the same names. About 100 lines change: the build-time checks read `evaluation.inspect().metadata` (query and responses, `docs/evaluation.md:145-149`), the rows come from `evaluation.read()`, the recipe writes through its own temporary file and `os.replace`, and its execution holds the evaluation's `execute()` scope. Its `Explanation`, `Operation`, `ExecutionReport` and `ExecutionDiagnostic` would rest on constructors the contract doesn't declare (`public-api.json:2202-2232`, `:3281`).

**The files** (budgets in §8):

| File | Holds | Imports crc-sdk |
|---|---|---|
| `_parametric_cover.py` | the declarations of §3 but the recipe and its outputs | yes, for `SeriesReference` only |
| `_parametric_payouts.py` | the four families: payouts, the basis matrix, the amount constraints | no |
| `_parametric_sample.py` | the draws, the loss, the basis-risk model | no (crc-framework only) |
| `_parametric_metrics.py` | the premium and the metrics of §5 on arrays | no (crc-framework only) |
| `_parametric_design.py`, `_parametric_solver.py` | the grid, the LP and QP, the checks; HiGHS behind the extra | no |
| `_parametric_run.py` | `ParametricRun`, `ParametricExecution`: the checks, the rows, the series | yes |
| `_parametric_result.py` | `ParametricResult`, `ParametricMetadata`, `ParametricDesignRecord`, `ParametricArtifact` | yes |

The numerics are plain functions on numpy arrays, apart from the cover file's one import. So they can move to crc-framework (§6) or into a package of our own without change.

## 3. The public surface: 15 names

Signatures are outlines of the final surface; types from crc-framework are written `cf.`. Story 1 is "create a cover", 2 "analyse it", 3 "compare covers". "PR" is the PR that adds the name (§8).

| # | Name | Signature | Story | PR |
|---|---|---|---|---|
| 1 | `PayoutKind` | enum: `LINEAR`, `STEP`, `PIECEWISE_LINEAR`, `BINARY` | 1 | 1 |
| 2 | `ParametricCover` | `(kind: PayoutKind, *, thresholds: Sequence[float \| FreeTerm], amounts: Sequence[float \| FreeTerm], tail: cf.Tail, monotone: bool = True, label: str \| None = None)`; `id`, `payout(index) -> NDArray[float64]`, `resolve(terms: Mapping[str, float]) -> ParametricCover`, `to_json()`, `from_json(text)` | 1 | 1 |
| 3 | `BasisRisk` | `BasisRisk.none()`, `BasisRisk.impact_noise(*, sigma: float, upper: float \| None = None)` | 2 | 1 |
| 4 | `Pricing` | `Pricing.pure()`, `Pricing.cost_of_capital(*, rate: float, level: float)` | 1, 2 | 1 |
| 5 | `ParametricSampling` | `(*, draws: int, seed: int, basis_risk: BasisRisk, tail_completion: cf.TailCompletion \| None = None, test_draws: int \| None = None)` | 2 | 2 |
| 6 | `ParametricRun` | `(evaluation: Evaluation, *, damage_response: str, value: str \| float, loss_unit: str, covers: Sequence[ParametricCover], sampling: ParametricSampling, pricing: Pricing \| None = None, design: ParametricDesign \| None = None, levels: Sequence[float] \| None = None, return_periods: Sequence[float] \| None = None)`; `explain(*, runtime=None) -> Explanation`, `validate(*, runtime=None) -> ExecutionReport`, `read(*, runtime=None) -> ParametricResult`, `write(path, *, overwrite=False, runtime=None) -> ParametricArtifact`, `execute(*, runtime=None) -> ParametricExecution` | 1, 2, 3 | 2 |
| 7 | `ParametricResult` | `table: pa.Table`, `covers: tuple[ParametricCover, ...]`, `metadata: ParametricMetadata`, `report: ExecutionReport` | 2, 3 | 2 |
| 8 | `ParametricMetadata` | `schema_version`, `evaluation: EvaluationMetadata`, `covers`, `sampling`, `pricing`, `design`, `designs: tuple[ParametricDesignRecord, ...]`, `levels`, `return_periods`; `to_json()`, `from_json(text)` | 2, 3 | 2 |
| 9 | `FreeTerm` | `(*, lower: float = 0.0, upper: float \| None = None, grid: int \| Sequence[float] \| None = None)` | 1 | 3 |
| 10 | `Objective` | `Objective.mse()`, `Objective.expected_uncovered()`, `Objective.weighted_cvar(*, alpha: float, beta: float)` | 1 | 3 |
| 11 | `Budget` | `Budget.ratio(value: float)`, `Budget.amount(value: float)` | 1 | 3 |
| 12 | `ParametricDesign` | `(objective: Objective, *, budget: Budget \| None = None, limit: float \| None = None, series: SeriesReference \| None = None, max_grid_points: int = 10_000)` | 1 | 3 |
| 13 | `ParametricDesignRecord` | `cover_id`, `design_id`, `route`, `status`, `objective_value`, `premium`, `unidentified`, `unique`, `ties`, `degenerate_tail`, `solver` | 1 | 3 |
| 14 | `ParametricExecution` | context manager: `read()`, `validate()`, `write(path, *, overwrite=False)`, `report` | 2, 3 | 5 |
| 15 | `ParametricArtifact` | `open(path)`, `read()`, `validate()`, `path`, `metadata` | 2, 3 | 5 |

- **Terms.** A cover's terms are its index-unit `thresholds` and its payout-unit `amounts`, read per family as ADR 0005 §3's table: `LINEAR` (attachment, exhaustion; limit), `STEP` (breakpoints; levels), `PIECEWISE_LINEAR` (knots; levels), `BINARY` (trigger; amount). Term names are `thresholds[i]` and `amounts[i]`. One class with a kind replaces ADR 0005's four classes, its protocols and its registry.
- **Closed choices are enums or named constructors**, as `Probability.annual(tail=...)` is (`crc_sdk/_declarations.py:353`). `BasisRisk`, `Pricing`, `Objective` and `Budget` have no public `__init__`. The record's `route`, `status` and `degenerate_tail` are nested enums, which add no names; the table's `split` is a data column, like 1.0's `failure.kind`.
- **Pricing belongs to the run**: it prices stated covers on their sample and the design's budget alike, as 0.11's `evaluate` and `compare` took a pricing.
- **The design series** is a 1.0 `SeriesReference` (`crc_sdk/_inspection.py:85`), as `inspect().series` lists them. It may be omitted only when the evaluation reads one series.
- **The value** is an asset column carried by `Assets(columns=[...])` (`crc_sdk/_assets.py:336`) into the evaluation's `asset` field, or one number. `loss_unit` is an exact identifier, recorded.
- **Defaults.** `levels=None` means (0.9, 0.95, 0.99) and `return_periods=None` means (2, 5, 10, 25, 50, 100, 250), both recorded: 1.0's checker accepts only an empty tuple as a tuple default (`tools/api_contracts/check.py:193-197`). `LossRun`'s branch relaxes that rule (`git diff v1.0.1 upstream/insurance-loss -- tools/api_contracts/check.py`: +17/−3); the core doesn't need it.
- **Signatures grow by PR.** The checker resolves every annotation to a declared name (`check.py:97-111`), so each PR declares the signatures its names allow: PR 2's `ParametricRun` has no `design` and `ParametricCover` takes floats only until PR 3; `write` and `execute` arrive with PR 5. 1.0 replaces unshipped definitions in place (`AGENTS.md:59-60`).
- **The table is long**, like 1.0's evaluation rows, with columns passed through from the evaluation, `asset_id`, `member_id` (null in the core), `variable_id`, `scenario_id`, `period_id`, `support_id`, `distance_metres`, then `cover_id`, `cover_label`, `design_id`, `split` (`"design"` or `"test"`), `metric`, `level` (β or T, or null), `value`, and `failure` with 1.0's four fields `code`, `message`, `record`, `kind` (`crc_sdk/_evaluation_schema.py:867-874`). The column set is fixed whatever the levels, so no metric name depends on β or T.
- **Errors.** No new exception class.
  - At construction, as `LossRun`: `TypeError` or `ValueError` for misuse; a `damage_response` absent from the evaluation's selection is a `ValueError` (`loss:_loss_inputs.py:150-154`); `CapabilityError` (`crc_sdk/_errors.py:8`) when the response's output isn't `Ratio(unit=RatioUnit.FRACTION)` or the query isn't `.probabilities([...])` (`loss:_loss_inputs.py:155-172`), and `ValueError` when the knots don't run from 0 to 1 and no `tail_completion` is given (`:187-192`).
  - At execution: a refused setup (several assets or variables, a design series that isn't read) is an `ExecutionDiagnostic` (`crc_sdk/_dataset_schema.py:274`); `validate()` returns it and the other terminals raise `ValidationError(report=)` (`crc_sdk/_errors.py:13`; `docs/execution.md:184-187`).
  - Per series, a failure row and a warning diagnostic, and the run goes on: the evaluation's own codes passed through (`no_covering_support`, `overlapping_supports`, `outside_max_distance`, `query_outside_support`, `crc_sdk/_evaluation_schema.py:68-70`; `source_unavailable` as `failure.kind`), and the core's `incomplete_grid`, `tail_completion_outside_knots`, `probability_not_annual`, `tail_mismatch`, `value_unavailable`, `design_infeasible`, `design_unbounded`, `solver_limit`.
  - A missing extra raises an `ImportError` naming it (`docs/development.md:56-57`), and `explain()` lists it as a `Requirement`, as `LossRun` lists missing columns (`loss:_loss.py:49-60`).
- **Stages.** `explain()` adds `Operation`s to the evaluation's explanation with 1.0's stages: `Stage.VALIDATION` (checks), `Stage.EVALUATION` (draws, design, metrics), `Stage.WRITING` (`crc_sdk/_dataset_schema.py:261`). 1.0 has no design stage; `LossRun` uses the same two (`loss:_loss.py:186-193`).
- **`ParametricMetadata` takes `LossRunMetadata`'s form**, typed metadata under one footer key. It is not 0.11's metadata document.

**How the names enter `public-api.json`, and what that means for a contribution.** Each name gets one entry with its constructor, methods, parameter kinds, annotations, defaults and properties; the list stays sorted (`check.py:268`); the framework types the signatures use (`cf.Tail`, `cf.TailCompletion`) go in `external_symbols` (`public-api.json:4918`), and no framework type is re-exported (`check.py:410`). `__all__` must equal the exports, and no other public attribute or member may exist (`check.py:745, 754, 851`). So a PR into crc-sdk carries, beside the code: the contract entries; the `__init__.py` imports; a row in `docs/api-reference.md` and `docs/README.md`; the docs page, whose Python examples run offline under `tools/check_examples.py`; and, with the artifact (PR 5), a format `parametric` in `release.json` with its JSON Schema and generator. The checker hard-codes the set of formats (`check.py:246-258`), so it changes too, as `LossRun`'s did. The base wheel must import and pass `check.py --runtime` without `highspy` (`.github/workflows/ci.yml:145-161`).

## 4. What the core reads from crc-sdk 1.0

| What | Symbol | At `v1.0.1` |
|---|---|---|
| The evaluation | `Evaluation`, `.probabilities`, `.impact`, `.explain`, `.execute`, `.write` | `crc_sdk/_evaluation.py:992, 1064, 1079, 1099, 1260, 1265` |
| Its plan (in-tree) | `_Plan.assets`, `.query`, `._selected_responses()`; `_EvaluationNode` | `crc_sdk/_evaluation.py:114-120, 183, 459` |
| The query | `QueryKind.PROBABILITY`, `EvaluationQuery` | `crc_sdk/_evaluation_schema.py:74, 82` |
| Its rows | `evaluation_arrow_schema`: `asset_id`, `member_id`, `resource_id`, `variable_id`, `scenario_id`, `period_id`, `support_id`, `distance_metres`, `response_id`, `resolution_id`, `query_value`, `value`, `failure`; `exposure` on named-only selections; `asset` when columns are bound | `crc_sdk/_evaluation_schema.py:863-927` |
| Row failure codes | `no_covering_support`, `overlapping_supports`, `outside_max_distance`, `query_outside_support` | `crc_sdk/_evaluation_schema.py:68-70` |
| The asset, the series | `Dataset.evaluate`, `Assets(..., columns=)`, `SpatialMatch` | `crc_sdk/_recipes.py:2019`; `crc_sdk/_assets.py:315, 336`; `crc_sdk/_evaluation_spatial.py:58` |
| The impact | `EvaluationMetadata.resolutions` → `EvaluationResolution(response_id, impact: cf.Impact, asset_ids, context)` | `crc_sdk/_evaluation_schema.py:212, 470, 476` |
| Scenario and period | `Scenario`, `Period`, `SeriesReference` | `crc_sdk/_declarations.py:213, 269`; `crc_sdk/_inspection.py:85` |
| Units and semantics | `Variable(measurement=)`, `Probability.annual(tail=)`, `ProbabilityKind` | `crc_sdk/_declarations.py:179, 353, 47` |
| Execution | `Runtime`, `ExecutionScope`, `_publication_path` | `crc_sdk/_runtime.py:137`; `crc_sdk/_graph.py:286`; `crc_sdk/_terminals.py:585` |
| Reports and errors | `ExecutionReport`, `ExecutionDiagnostic`, `Stage`, `ValidationError`, `CapabilityError` | `crc_sdk/_dataset_schema.py:387, 274, 261`; `crc_sdk/_errors.py:13, 8` |
| Explanation | `Explanation`, `Operation`, `Requirement` | `crc_sdk/_inspection.py:216, 74, 61` |

**The curve route: `LossRun`'s, adapted.** The user queries the evaluation with `.probabilities([...])` in non-exceedance ranks and names a damage response. Per asset and series, the recipe takes the exposure values at the knots, builds `cf.QuantileCurve(probabilities, values)`, and completes it with the sampling's `tail_completion` unless the knots run from 0 to 1. `LossRun` builds its curve the same way, but from the damage response's `value`, for one series per run, and raises `loss_row_identity` otherwise (`loss:_loss_inputs.py:167-190, 338-350, 363-420`). The core builds from `exposure.value` and groups the rows by series. Two routes were weighed:

- (i) the evaluation's own quantile rows (chosen). It uses only the evaluation, as `LossRun` does, and works whatever the dataset holds, including CRC Open's `QuantileCurve`s (`crc_sdk/_climate_io.py:192`; `crc_sdk/_climate_sources.py:941`), which have no values outside their knots (fw: `docs/python.md:64-65`). Its costs:
  - Between knots the hazard is interpolated linearly in probability, so the grid is a stated modelling choice, recorded in the metadata.
  - **It caps the hazard's upper tail.** A `QuantileCurve` takes only finite values (fw: `_distribution.py:134-138`), so above the last knot q_max a fitted, unbounded tail is replaced by a straight line up to the finite `TailCompletion.upper` (fw: `_distribution.py:86-98, 937-951`). About (1 − q_max) of the draws fall there. Those draws drive CVaR, tail coverage and the weighted-CVaR objective, one of the program's two ideas. The run reports that share as a row (`metric` `completed_tail_share`), and the docs page tells users to query up to a q_max well above their highest β. Marc decides under M7.
  - One `tail_completion` serves every series and asset of a run. `complete()` raises when its endpoints don't contain a series' knots (fw: `_distribution.py:941-942`); that series gets the failure `tail_completion_outside_knots`.
- (ii) joining the evaluation's `support_id` to the dataset's rows (`_Plan.source`, `crc_sdk/_evaluation.py:115`) and calling `decode_curves` (`crc_sdk/_curves.py:11-22`). A fitted `Distribution` from `Dataset.fit` has full support and needs no completion, which exists only on `QuantileCurve` (fw: `_distribution.py:937`), so there is no cap. But it rests on a private join with no precedent; RiskThinking's question 4 asks whether it is intended.

**The loss.** The recipe takes the asset's resolved `cf.Impact` from the evaluation's resolutions and applies it to the drawn hazard values, rather than interpolating the response's knots as `LossRun` does. So the basis-risk model acts on the impact at each draw, and 1.0 still checks and records the measurement and the context. Only four built-in models bind in `.impact(...)` (`docs/migration-v1.md:389-393`); user `Impact.linear`, `tabulated`, `binned` and `sigmoid` models bind too.

**Checks on 1.0's facts:** the series declares `ProbabilityKind.ANNUAL` (replacing ADR 0005 §4.2's semantics rules); the cover's `tail` equals the series' probability tail (ADR 0005 §3); every knot has an exposure value, else `incomplete_grid`, as `LossRun`'s `loss_incomplete_grid` (`loss:_loss_inputs.py:375`).

## 5. The numerics

Plain functions on numpy arrays, in the files of §2.

| Part | The core | ADR 0005 carried over unchanged |
|---|---|---|
| Payout families | four families, half-open bins on the severe side, nothing below the first threshold, amounts ≥ 0, `monotone` | §3: "Severity", the families' table, "Nothing below the attachment", "Boundaries", "Constraints of the family"; the `Free` rules as `FreeTerm` |
| The sample | n design draws and m test draws per series. Uniforms u from `numpy.random.default_rng(seed)` (design) and an independent child stream (test); hazard = the completed curve's `quantile(u)`; loss = `impact.evaluate(hazard)` × value; then the basis-risk model. Every series of the run reads the same uniforms, so scenarios and periods are compared on shared draws | §4.4's draw order (hazard uniforms first, then the basis-risk model) and `NoBasisRisk`; `ImpactNoise` |
| Premium | `PurePremium` and `CostOfCapitalLoad` | §5.2's first two bullets; §6's "The premium used" |
| Metrics | `expected_loss`, `expected_payout`, `premium`, `expected_uncovered`, `coverage_ratio`, `payout_to_loss_ratio`, `tail_coverage`, `cvar_uncovered_to_loss`, `false_negative_rate`, `false_positive_rate` (ℓ = ε = 0, recorded), `rmse`, `correlation`, VaR and CVaR of uncovered loss, net loss and loss, and the four return levels | §6: notation, "VaR and CVaR", "Tail weights", the metrics' definitions and null rules; "In and out of sample" |
| Design | a grid over free thresholds; at each point the amounts by an LP (E[U], weighted CVaR) or a QP (MSE); MSE under a cost-of-capital budget by cutting planes; scaling; numpy verification of every constraint; `unidentified` with the fill rule; MSE uniqueness by eigenvalue; grid ties; degenerate tails | §5.1 (but `UserObjective`), §5.2 (but `ExpectedPayoutMultiple`), §5.3's table rows 1 to 4, "The grid", "Why a grid", "Scaling", "No silent failures"; §5.4's "Unidentified amounts", "MSE route", "Grid route", "Degenerate tails"; §5.5's QP route for at most 100 columns and its LP rule |
| Solver | HiGHS (`highspy`) for LPs and for the dense active-set QP's LPs, imported lazily, in the extra `crc-sdk[parametric] = ["highspy>=1.13,<2"]` (0.11's floor, `pyproject.toml:58-60` at `c830db5`) | §5.5's policy and choice of highspy |

**What the core changes against ADR 0005:**

- **A held-out test from fresh draws.** The draws are i.i.d., so the test sample is m fresh draws on the second stream (ADR 0005 §4.4, "Splits"). Year-block splits return with stage 3. Rows say `split`; external numbers come from `"test"` rows (publication rule).
- **The premium used** on test rows is the design premium; a stated cover is priced on its own sample with the run's pricing.
- **No QP above 100 columns.** A template with more than 100 free amounts is refused at construction, so HiGHS's QP solver, its limits and the fallback of §5.5 aren't ported.
- **The LP route doesn't range.** `unique` is null on LP designs, as with `ranges=False` in 0.11. Ranges, which the owner made the default on MAR-405, return with stage 5.
- **Determinism** comes from an integer `seed` recorded in the metadata, as crc-framework's `Distribution.sample(size, *, seed)` takes one (fw: `_distribution.py:437-449`). No global seed.
- **Elsewhere:** §9 gives every 0.11 capability the core leaves out a stage, the parked list or the drop list.

## 6. Integration with crc-framework

**What it is** (fw: `AGENTS.md`, `README.md`). The numerical core of CRC: one Rust crate, `crates/core`, with PyO3 bindings (`src/`, `crc_framework._core`), a typed Python API (`python/crc_framework`, 88 exports in its `public-api.json`), and WASM/JS. It holds about 581,000 lines of Rust, of which 559,250 are under `crates/core/src/reference/`, mostly reference data but also `curve_fitting.rs` (3,604 lines of code), and 5,212 lines of Python (`git ls-files` and `wc -l` at `33420fb`). Its Python package depends on `numpy` and `jsonschema` only (fw: `pyproject.toml`), and `Cargo.lock` has no LP or QP solver; its one optimiser is the likelihood search of its curve fits (fw: `crates/core/src/distribution.rs:1336`).

**What it already does that the core needs:**

| Need | crc-framework 1.0.0 | Fit for the core |
|---|---|---|
| A complete hazard law from knots | `QuantileCurve(probabilities, values)`; a query outside `probability_interval` raises `ValueError`; `complete(TailCompletion(lower=, upper=))` adds linear tails to 0 and 1 and returns a `Distribution` (fw: `_distribution.py:819-960`; `docs/python.md:64-77`) | Reused, as `LossRun` does |
| Draws | `Distribution.quantile(probabilities)` takes arrays and keeps their shape (fw: `_distribution.py:374`; `docs/python.md:22-24`); `Distribution.sample(size, *, seed)` is `quantile(numpy.random.default_rng(seed).random(size))` (fw: `_distribution.py:437-449`) | Reused. The recipe draws its own uniforms with the same generator, so that series share draws and the basis-risk draws follow, then calls `quantile` |
| An impact on arrays | `Impact.evaluate(values)` (fw: `_impacts.py:351`); `ImpactReference.resolve(context)` (fw: `_impacts.py:1036`) | Reused, through the evaluation's resolutions (§4) |
| Exact laws of a response | `Impact.expectation`, `Impact.pushforward` (fw: `_impacts.py:544, 564`) | Not in the core: the design needs the joint draws of index and loss |
| VaR and CVaR of draws | `Distribution.empirical(samples)` keeps exact `K/N` ranks (fw: `_distribution.py:292-304`), better for equal-weight draws than `discrete`, which groups atoms in a Python loop (`:306-325`); `quantile` takes the lowest value whose rounded rank reaches q (fw: `crates/core/src/numerical.rs:926-932`); `statistics(metrics=[Statistic.CVAR], level=, tail=)` integrates the tail exactly, a partial atom included (fw: `_distribution.py:451`; `numerical.rs:617-654`) | Reused for VaR, CVaR and the return levels. The CVaR equals ADR 0005 §6's. The VaR lacks §6's 1e-10 slack; the fixtures write a quantile on a step as `{"either": [...]}` (ADR 0005 §8), so both pass. The tail weights, coverage and rates stay in numpy |
| Payout-like functions | `Impact.linear(..., minimum=, maximum=)` (fw: `_impacts.py:254`); `Impact.binned`, bins `[e_i, e_{i+1})` (fw: `crates/core/src/impact/kernel.rs:68-70`), and `Impact.tabulated`. The kernel either refuses or clamps values outside the domain (fw: `kernel.rs:26-49`), and the impact document defaults to `"clamp"` (fw: `crates/core/src/impact/definition.rs:1033-1043`), but the Python constructors fix `"error"` (fw: `_impacts.py:307, 333`) | Not reused: the design needs each family's basis matrix in its amounts, and step, binary and piecewise payouts must pay nothing below the first threshold whatever the index. With clamp exposed in Python, the payouts of stated covers could be framework `Impact`s (question F2) |
| Units of money | an open `Measurement(quantity=, unit=)` needs no registration (fw: `_measurement.py:556-579`) | A later typed `loss_unit`; the core records a string |
| Random numbers | Python: numpy `default_rng(seed)` (PCG64) (fw: `_distribution.py:448`). Rust: `rand` 0.9 behind the default feature `sampling` (fw: `crates/core/Cargo.toml:11-22`). The unmerged insurance branch: ChaCha12 streams keyed by SHA-256 of a versioned algorithm name (fw: `origin/insurance-loss:crates/core/src/insurance/sampling.rs:1-60`) | The core follows the Python convention and records `numpy.random.PCG64`. Pairing with `LossRun`'s trials would need its primary ranks (RiskThinking's question 3) |

**Does 1.0 change the golden fixtures?** No. Every case of MAR-245 carries its index and loss arrays, design and evaluation blocks alike (ADR 0005 §8); none holds a curve, so 1.0's curve changes (fw: `docs/migration-v1.md:36-50`) don't touch them.

**Which numerics belong where.** 1.0's rule puts numerical algorithms in crc-framework (`docs/development.md:60-61`; fw: `AGENTS.md`, "`crates/core` | All algorithms"), and RiskThinking's own insurance branch put its sampling and its annual-loss metrics there (`crates/core/src/insurance/sampling.rs`, `metrics.rs` with `summarize_annual_losses`). **The core departs from that rule**: about 2,650 lines of numerics (§8: payouts, sample, metrics, design, solver) go into crc-sdk. This is a stated risk, which Marc may put to RiskThinking (question 10):

| Numeric | Recommendation | Reason |
|---|---|---|
| Curves, draws, impacts, VaR, CVaR | crc-framework, as it is | Reuse; no new code there |
| Payout families | the recipe; crc-framework later, as `Impact`s with clamp (F2) | Each family is 10 to 30 lines of numpy plus its basis matrix. In crc-framework it is Rust, a binding, a typed wrapper, a stub, a contract entry, a schema for JS, and Rust and Python tests, and a framework release before the SDK PR |
| Basis risk (`ImpactNoise`) | the recipe | Three lines of numpy on the recipe's generator; no framework counterpart on `main` |
| Cost-of-capital premium | the recipe | Inside the design it is the LP rows of the payout's CVaR, so it lives where the LP is built; for a stated cover it is one framework CVaR call |
| Tail weights, coverage, rates, correlation, RMSE | the recipe | Short numpy expressions over the design's draws. The insurance branch's `summarize_annual_losses` shows RiskThinking may want such metrics in Rust |
| Grid, LP/QP, cutting planes | the recipe, with `highspy` as an optional extra (Q5) | The grid and the cutting planes orchestrate solver calls, so they go where the solver is. crc-framework has no solver; a Rust HiGHS binding builds HiGHS's C++ and would not serve the WASM target |

**How crc-framework takes contributions** (fw: `AGENTS.md`; `docs/development.md`; `docs/releases.md`):

| Topic | Convention |
|---|---|
| Language and layout | Algorithms in Rust (edition 2024, Rust ≥ 1.87) in `crates/core`, "edit here first"; PyO3 0.29 bindings in `src/`, long calls releasing the GIL (`py.detach`); a typed Python wrapper in `python/crc_framework/_*.py`; `_core.pyi` matching `src/`; WASM in `crates/wasm` and `js/` |
| Interface | `public-api.json` and `release.json` as in crc-sdk; one name per concept; enums for closed choices; `tools/api_contracts/check.py`, with `--runtime` on the wheel |
| Tests | `cargo fmt`, `cargo clippy -D warnings`, `cargo test`; `pytest` and `mypy` after `maturin develop`; shared accepted and rejected fixtures; explicit numerical tolerances |
| Release | one version in the root `Cargo.toml`, matching `release.json`; the framework is released before an SDK that needs it (crc-sdk `docs/development.md:89-91`) |
| Licence | AGPL-3.0-or-later, as crc-sdk |
| Precedent | RiskThinking's insurance numerics on `origin/insurance-loss`: 1,988 lines of Rust in `crates/core/src/insurance/`, a 300-line binding, a 682-line Python wrapper, +449 contract lines and 774 lines of Python tests (`git diff --numstat` against `main`) |

**What that does to the budget and the PRs.** As recommended, the core needs no crc-framework PR. If RiskThinking want the payouts or metrics in crc-framework, a PR series into crc-framework comes first: on the precedent, about 1,500 to 2,000 lines of Rust, bindings, contract and tests for the four families. It needs a fork of crc-framework among the program's repositories (M1). The crc-sdk PRs then shrink by those files and wait for a framework release.

## 7. Tests and parity

- **Offline and synthetic**, in crc-sdk's `tests/`, under `pytest`, `mypy` (strict) and `ruff`. Test lines at most the source's, per PR.
- **Behaviour, not message texts** (Q7): a test asserts the type of an error, a failure code or a value, never the words of a message.
- **The golden fixtures** (MAR-245, `parity/crc/`), counted from the case files:
  - PR 1 takes 18 of the 20 one-asset evaluation cases, 6 of them under a cost-of-capital load. The 2 `-options` cases state ℓ and ε above 0 (`loss_thresholds` [150, 262.5] with `payout_threshold` 50; [0, 1e5, 1e6] with 1e4), so they go to stage 5.
  - PRs 3 and 4 take the 40 one-asset design cases: the 17 MSE cases in PR 4, the rest in PR 3. 16 of them carry an evaluation block (8 holdout, 6 k-fold, 2 fresh draws), so the splits are tested without being built. `compare_parameters` is `"exact"` or `"none"` in all 40. The 23 LP designs that assert `unique: true` go unchecked on that field, since the core leaves it null; stage 5 checks it.
  - Stage 1 takes the 40 joint and cluster cases. 14 of them compare `within_ranges` (9 joint, 5 cluster): stage 1 checks their objective and metrics, and stage 5 their ranges (`parity/crc/README.md:245`).
- **Their size.** The 60 one-asset cases are 21,052 lines and 635,592 bytes as written, 473,161 bytes minified (measured). They are copied minified, one case per line, into one JSON Lines file with a README that keeps each case's licence (CC0-1.0, and CC-BY-4.0 with the attribution for the 14 `thesis` cases; `parity/crc/README.md`). The data counts toward no line budget. RiskThinking may want less data (question 7): the 46 CC0 cases alone are 425,030 bytes as written.
- **The recipe's tests** build an evaluation in memory with `Dataset.from_quantiles` and `.probabilities([...])` (`docs/evaluation.md`), and check rows, failure codes, shared draws across series, the design and test splits, `explain` without I/O, and the artifact's round trip.

## 8. The budget and the PR split

**Re-estimated: about 4,850 source lines**, against Q2's 3,500, docstrings included at 1.0's density:

| File | Lines | Measured against |
|---|--:|---|
| `_parametric_cover.py` | 600 | 0.11's `cover.py`, `parameters.py`, `objectives.py`, `pricing.py`, `constraints.py`, `basis_risk.py`, CORE-tagged: 1,321 (A) |
| `_parametric_payouts.py` | 350 | `payouts.py` CORE: 888 |
| `_parametric_sample.py` | 250 | sampling on curves and the basis-risk models, concern d: 1,235 |
| `_parametric_metrics.py` | 250 | `metrics.py` and `_risk.py` CORE: 693 |
| `_parametric_design.py` | 1,100 | `design.py` and `_solver.py` CORE: 3,013, of which `solve_qp` (about 40) is dropped (A, §3; `a_classified.json`) |
| `_parametric_solver.py` | 700 | |
| `_parametric_run.py` | 800 | `LossRun`'s `_loss.py` and `_loss_inputs.py`: 1,051 (C, §5) |
| `_parametric_result.py` | 800 | `LossRun`'s `_loss_artifact.py`: 998 |
| **Total** | **4,850** | |

- **Design and solver, 1,800 against about 2,900.** The refinement, the ranges and the local searches are already outside the 3,013 (supporting lines). Their core lines hold 2,057 lines of code alone, so **1,800 is tight**. It rests on two simplifications, estimated, not measured: one cover class, so no dispatch over the `PayoutFunction`, `LinearInAmounts` and `LinearConstraints` protocols; and docstrings at 1.0's density (0.11's are 18.3 % of its lines, A). §10's stop rule covers an overrun: PR 3 or PR 4 more than 10 % over goes to Marc with the number.
- **Run and result, 1,600 against `LossRun`'s 2,049**, whose numerics are all in Rust. Ours read rows and write an artifact as `LossRun`'s do, with a smaller metadata.
- **One docs page**, `docs/parametric.md`, at most 300 lines, grown PR by PR; its examples run under `tools/check_examples.py`.

**Five PRs into crc-sdk**, each at most about 1,500 source lines, with its tests (at most its source) and its share of contract and docs on top:

| PR | Content | Names | Source | Story it completes |
|---|---|---|--:|---|
| 1 | Stated covers on arrays: `PayoutKind`, `ParametricCover` (fixed terms), `BasisRisk`, `Pricing`; payouts, the sample, the premium and the metrics; 18 evaluation fixtures | 4 | 1,100 | none alone: the numerics of stories 2 and 3 |
| 2 | The recipe for stated covers: `ParametricSampling`, `ParametricRun` (`explain`, `validate`, `read`), `ParametricResult`, `ParametricMetadata`; the checks, the curve route, rows and failures | 4 | 1,050 | 2 and 3 for stated covers: metrics per cover, scenario and period, covers side by side |
| 3 | Design on the LP route: `FreeTerm`, `Objective`, `Budget`, `ParametricDesign`, `ParametricDesignRecord`; the grid, the LPs, the checks, the extra; test draws; 23 design fixtures | 5 | 1,400 | 1 for E[U] and weighted CVaR, with held-out numbers |
| 4 | MSE: the dense active-set QP, the cutting planes, uniqueness by eigenvalue; 17 MSE fixtures | 0 | 700 | 1 for MSE |
| 5 | Persistence and the guide: `ParametricExecution`, `ParametricArtifact`; `write`, `open`; the format `parametric` 1.0 with its schema and generator | 2 | 600 | 1 to 3 as a 1.0 user runs them, saved and reopened |

- **This exceeds Q2** in lines (4,850 against 3,500) and PRs (five against three). The alternative that keeps close to Q2: move persistence (PR 5) and MSE under a cost-of-capital load to stage 5, with that route's 5 one-asset fixtures, about 3,800 lines in four PRs, with results that can't be saved. Marc decides (M5).
- **"About 1,500 lines" is read as source lines.** With tests up to the source and the contract entries, a PR's diff is up to about 3,200 lines; PR 5 adds a generated schema (`LossRun`'s was 808 lines, C §5). If Marc meant the whole diff, the PRs halve again (M2).
- **The names fill the cap of 15.** A sixteenth needs Marc.

## 9. The addition stages, in Q3's order

Each stage is an issue series, each issue with its story and budget (§10), and ends as PRs on crc-sdk 1.0 of at most about 1,500 source lines each. The 0.11 lines are the review's subject totals (A, "Lines by subject"). A stage's budget changes when what it holds changes, and the issue says so.

| Stage | User story | Adds | Budget | 0.11 |
|---|---|---|--:|--:|
| 1. Portfolio approach | One risk owner with several sites designs covers on the owner's total loss and payout; joint calibration as a method (publication rule) | several assets in one run; `CalibrationScope` (`individual()`, `joint()`, `clustered(clusters)`); `Dependence` (`independent()`, `comonotonic()`, `gaussian(correlation)`) across assets; `PayoutAllocation` (`VALUE`, `LOSS`); rows at the total and per asset; the 40 joint and cluster fixtures | 1,500 | 5,968 |
| 2. Several hazards | A cover that pays on two hazards at one site, alone or as a package of separate contracts | an evaluation of a `DatasetCollection` (`crc_sdk/_collection.py:847`); `PayoutCombination` (`SUM`, `MAX`); `LossCombination` (`CAPPED_SUM`, `COMPOUND`, 0.11's `CompoundDamage`); `ParametricPackage`, separate contracts under one budget with its split (0.11's `CoverPackage`, `split_budget`) and a payout breakdown per contract (`payout_breakdown`); dependence across hazards from stage 1 | 1,700 | 5,516 |
| 3. Per-year route | A cover on observed or modelled years, or on the user's own table of years | `ParametricRun.from_samples(samples, assets, *, ...)` for 1.0 `Samples` (ERA5, CMIP6, GHCNh), matched to the asset's support by the recipe, since `Samples` can't be evaluated (`crc_sdk/_terminals.py:203-225`); `ParametricRun.from_table(table, *, ...)` for the user's own index and loss per year (0.11's `OutcomeSample.from_table`); `YearSplit` (holdout, k-fold by year blocks) with pooled k-fold rows (`compare_pooled`); several hazards' years (`sample_annual_hazards`); a second series as the index; the short-block flags (ADR 0005 §6, erratum 30) | 1,650 | 3,504 |
| 4. A simple interval by year | A metric reported with an interval from resampled years or draws | `ParametricInterval(*, level, resamples, seed)`; `lower` and `upper` on the rows. Whole years are resampled, all assets and hazards of a year together; no re-dealing of rank blocks | 400 | 1,829 |
| 5. Design extras | Finer control of a designed cover | `unique` and ranges on the LP route (ADR 0005 §5.4), with the 14 `within_ranges` and 23 `unique` checks; the local refinement (§5.3); `Pricing.expected_payout_multiple`; `BasisRisk.hazard_noise` (Amendment 6, F2); a budget frontier; metric thresholds ℓ and ε, with the 2 `-options` fixtures; `payout_frequency`, `unidentified_share` | 1,200 | 2,913 |
| **Total** | | 8 names | **6,450** | |

With the core: about 11,300 source lines and 23 names, against 43,101 lines and 114 names in 0.11.

**Parked, not staged.** Each returns only through its own issue (Q3): scenario sets with their refusals, `allocate_scenarios`, `payout_breakdown_scenarios`, and windows of horizons as mixtures (ADR 0005 Amendment 4); trend treatments (Amendment 2); pools of model runs; `StepGrid`; `EmpiricalCopula`, which rests on reference years; re-dealt rank blocks in intervals; the leakage checks between samples.

**Proposed to drop for good** (M4):

- `ParametricPlan`, `setup_text` and the metadata document (Q4 decided it), with `SampleProvenance`, which `ParametricMetadata` replaces, and the cover's terms in words (`terms_text`);
- `register_payout`, a process-global registry, which 1.0 says it doesn't have (`docs/scientific-data.md:79`);
- the user protocols `PayoutFunction`, `LinearInAmounts`, `LinearConstraints`, `HazardBasisRisk`, `DependenceModel` and `CombineRule`, which `PayoutKind` and the named constructors replace; and `UserObjective` with the numpy grid route, which take an arbitrary callable, as 1.0 removed for impacts (`docs/migration-v1.md:326`);
- HiGHS's QP solver above 100 columns and its fallback (§5);
- the pairing and lineage checks: one seed per run can't leak between design and test;
- `OutcomeSample.to_table` and the written-sample round trip, which the artifact replaces;
- the 14 exception classes and the warning of 0.11, against 1.0's two exceptions and failure rows (`docs/migration-v1.md:629`);
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

- The core is small enough to review: about 4,850 lines and 15 names, against 43,101 and 114.
- The loss side, the curves, units, scenarios, periods, failures and execution are 1.0's, so the core holds no impact, unit or provenance logic.
- Between the evaluation's knots the hazard is interpolated, so results depend on the stated probability grid and tail completion, both recorded.
- Under route (i) the hazard's upper tail is capped at `TailCompletion.upper`, above the last knot; tail metrics and the weighted-CVaR design on curves depend on that cap until route (ii) is open (M7).
- The core loses, until a stage returns them: per-year samples and user tables, several assets or hazards, intervals, LP ranges and the refinement.
- Hashes and `design_id`s differ from 0.11's; the golden fixtures hold none (ADR 0005 §5.4).

## 13. Open questions

**RiskThinking's** (MAR-435's list; Marc asks them):

| # | Question | What the answer changes here |
|---|---|---|
| 1 | The home | Decided (a) on our side. A no moves the core to the fallback of §2 |
| 2 | Does `LossRun` go into 1.0, and should a parametric recipe take the same inputs? | §3, §4: `ParametricRun` already takes `LossRun`'s inputs; it could also read a `LossResult` |
| 3 | Per-trial hazard values or ranks for pairing | §6: a cover could be read on `LossRun`'s trials; today the core draws its own |
| 4 | A public seeded way to draw years from a curve per asset; is joining evaluation rows to dataset rows on `support_id`, then `decode_curves`, intended? | §4: route (ii) could replace route (i) for fitted curves, without the interpolation between knots and without the cap on the upper tail (M7) |
| 5 | The solver dependency: crc-sdk extra or crc-framework | §5, §6: the extra moves, or the design moves to crc-framework (M1) |
| 6 | Does crc-framework take outside contributions, and in which language? | §6: whether the payouts or metrics can move |
| 7 | The PR size they can review; are `docs/api-reference.md` and `docs/development.md` the API guideline of 2026-11-09? | §7, §8: the split and the fixtures' size |
| 8 | Should open PR #41 be closed and replaced? | §2: the first PR's framing |
| 9 | When do rainfall, wind and heat bind in `.impact()`? | §4: until then a cover on those hazards needs a user model |
| 10 | (proposed, for Marc to add) Where do they want a parametric recipe's numerics: payouts, metrics, the design? | §6, §8: the departure from 1.0's rule stands, or a crc-framework series comes first |

**For crc-framework** (to RiskThinking, with question 6):

| # | Question | What it changes |
|---|---|---|
| F1 | Should `Distribution` offer a public inverse survival for draws near q = 1, as crc-sdk uses privately (`crc_sdk/_evaluation.py:893`; fw: `_distribution.py:624`)? | §5: draws in the far upper tail |
| F2 | Would they expose `"clamp"` outside the domain in `Impact.binned` and `Impact.tabulated`, which the kernel and the document already support? | §6: stated covers' payouts as framework `Impact`s, with exact expected payouts |
| F3 | Would they declare constructors for `Explanation`, `Operation`, `ExecutionReport` and `ExecutionDiagnostic`? | §2: the fallback rests on them |

**For Marc:**

| # | Question | What it changes |
|---|---|---|
| M1 | A fork of `crc-framework-rs` among the program's repositories, if any numerics move there | §6, §8: a PR series into crc-framework before crc-sdk's |
| M2 | "About 1,500 lines" per PR: source only, or the whole diff? | §8: five PRs, or about ten |
| M3 | The integration branch's name, `parametric-v1` | §2 |
| M4 | The drop list of §9 | §9 |
| M5 | The core's budget: about 4,850 lines in five PRs, or about 3,800 in four with persistence and MSE under a cost-of-capital load moved to stage 5 | §8, §9 |
| M6 | Whether to ask RiskThinking question 10 now, or build against the stated departure from 1.0's rule and ask with the first PR | §6 |
| M7 | Accept route (i), with its cap on the upper tail, until RiskThinking answer question 4; or build route (ii) now, as a private join of about 100 lines. Recommended: (i), with no default `TailCompletion`, the `completed_tail_share` row, and a docs rule to query beyond the highest β. A default derived from the curve's upper knots would invent a tail, which 1.0 avoids (fw: `docs/python.md:64-66`). The cap moves only runs on curves; the weighted-CVaR fixtures hold arrays and don't change | §4, §12 |

## Not verified

- Nothing here was built or run. The budgets are estimates against the review's counts and `LossRun`'s; the sizes measured for this record are the fixtures' (§7), crc-sdk's source lines and exports (§1), crc-framework's line counts and the insurance branch's (§6), and ADR 0005's bytes (§11).
- The speed of `Distribution.quantile` and of `Distribution.empirical(...).statistics` on 10,000 or more draws per series was not timed.
- How fine a probability grid route (i) needs, against a fitted curve's exact quantiles, was not measured. Nor was how much the cap on the upper tail moves CVaR, tail coverage and the weighted-CVaR design for a given q_max and `TailCompletion.upper`.
- The fallback's reliance on undeclared constructors (§2) was read in the contract, not tried.
