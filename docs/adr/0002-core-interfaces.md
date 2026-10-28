# ADR 0002: Core interfaces, module skeleton and ownership map

- Status: Accepted
- Date: 2026-10-25
- Issue: MAR-61 (F-03). Spec: SPEC §3, §4.2, §5, §6.

## Context

The thesis code put nine near-duplicate solvers in a notebook (thesis issue C1), read globals (C2) and skipped failures silently (C3). The core rework replaces them with combinable blocks: scope × payout structure × objective × pricing × constraints, assembled by one builder.

Several workers build these blocks in parallel (MAR-10 to MAR-16). They need fixed contracts first, and each file needs exactly one owner, so that no two PRs edit the same file. The contracts must also leave room for the core v1 features and the paper (SPEC §6.1 to §6.5), so that those don't need interface breaks.

## Decision

### 1. Module layout

All modules are in `packages/core/src/parametric_insurance_design/`. Every module in SPEC §4.2 exists. ADR 0002 adds five modules and splits `experiment.py` into a subpackage.

| Module | Responsibility |
|---|---|
| `interfaces.py` (new) | Every type that more than one issue implements or consumes: `Sample`, `Entity`, `ProblemSpec`, `DesignProblem`, `ProblemContext`, `Term`, `ObjectiveTerm`, the ABCs `PayoutStructure`, `Scope`, `Objective`, `Pricing`, `Constraint`, and `SolveStatus`, `SolverAttempt`, `SolveResult` |
| `basis.py` (new) | `Basis` enum, `OutcomeMeasure`, `outcome_measure()` |
| `errors.py` (new) | Error hierarchy (§6 below) |
| `records.py` (new) | Result-store record schemas (§7 below) |
| `constraints.py` (new) | `Budget` (MAR-13 scope; SPEC §4.2 has no file for constraints) |
| `eventset.py` | Unchanged (MAR-8) |
| `index.py` | `EntityIndex`, `PointIndex`, `ValueWeightedIndex` |
| `payout.py` | `StepPayout`, `uniform_breakpoints` |
| `scopes.py` | `Individual`, `Portfolio`, `Cluster` |
| `clustering.py` | `ClusteringStrategy` protocol, `ThesisWardClustering` |
| `objectives.py` | `MSE`, `ExpectedUncovered`, `WeightedCVaR`, `rockafellar_uryasev` |
| `pricing.py` | `PurePremium`, `CostOfCapitalLoad` |
| `problem.py` | `BuiltProblem`, `build_context`, `build_problems` |
| `solve.py` | `SolverPolicy`, `DEFAULT_POLICY`, `solve`; re-exports the result types and `SolveError` |
| `evaluate.py` | `kpis`, `exceedance_curves`, `evaluate_results` (MAR-143); re-exports `var_cvar` |
| `riskmeasures.py` (new, MAR-143) | `var_cvar` and the lower quantile of a discrete distribution, shared by `pricing.py` and `evaluate.py` |
| `splits.py` | `holdout`, `year_block_kfold` |
| `robust.py` | `build_scenario_robust` (R1), `DistributionallyRobust` (R2) |
| `noise.py` | `add_noise`, `NoiseKind` |
| `experiment/` | Replaces SPEC §4.2 `experiment.py`: `config.py`, `runner.py`, `store.py`, `sweeps.py` (§8 below). `__init__.py` stays docstring-only |
| `cli.py` | The `parametric-insurance-design` command (MAR-66) |

Each stub raises `NotImplementedError`, with `# pragma: no cover` on the raise line only, so that coverage counts real code. The implementing issue removes the pragma with the stub.

`__init__.py` imports every module and re-exports the data contract and the shared types (`EventSet`, `EventSetMetadata`, `Basis`, `OutcomeMeasure`, `Sample`, `Entity`, `ProblemSpec`, `DesignProblem`, `SolveResult`, `SolveStatus`, `ParametricInsuranceDesignError`, `SolveError`). Components are reached through their modules (`pid.payout.StepPayout`), so `__init__.py` doesn't change when a module gains a class.

### 2. Contracts

Signatures are in the code; the docstrings are part of the contract. In short:

```
Scope.partition(eventset) -> tuple[ProblemSpec, ...]
Scope.materialise(eventset, spec) -> DesignProblem           # index xi and entity losses
PayoutStructure.n_params; .parameter_bounds() -> (lower, upper)
PayoutStructure.basis_matrix(index[n_rows]) -> M[n_rows, n_params]
PayoutStructure.constraints(theta[n_entities, n_params], cap[n_entities]) -> tuple[cp.Constraint, ...]
PayoutStructure.evaluate(index[n_rows, n_entities], theta) -> payout[n_rows, n_entities]
Objective.build(ctx) -> ObjectiveTerm
Pricing.premium(ctx) -> Term;  Pricing.premium_value(payout[n_rows], measure) -> float
Constraint.build(ctx, premium: Term) -> tuple[cp.Constraint, ...]
problem.build_context(problem, payout_structure, measure, *, scale=None, theta=None) -> ProblemContext
problem.build_problems(eventset, scope, payout_structure, objective, pricing, constraints=(),
                       *, basis, sample=None, specs=None) -> tuple[BuiltProblem, ...]
solve.solve(built, policy=DEFAULT_POLICY, *, pricing=None) -> SolveResult   # or raises SolveError; pricing: MAR-143
evaluate.kpis(eventset, scope, results, *, basis, beta, run_id, sample=None, pricing=None) -> DataFrame
```

Conventions:

- **Rows** are EventSet rows (events × draws). An **entity** gets its own payout function (an asset, or a cluster). A **design problem** is one optimisation: one per asset in the individual scope, one (`problem_id = "portfolio"`) in the portfolio and cluster scopes.
- **Objective level = sum over entities:** `L_e = Σ_j L_{e,j}` and `π_e = Σ_j π_{e,j}`. `DesignProblem.loss` is that sum. This covers all three thesis scopes.
- `theta` has shape `(n_entities, n_params)`, and entity `j` pays `basis_matrix(ξ[:, j]) @ theta[j]`. One payout structure is shared by all entities of a design problem, as in the thesis. Per-entity structures would need an amendment.
- Every component is a frozen dataclass with explicit parameters and a `name` class attribute used in records. There is no global state (thesis issue C2).
- cvxpy annotates `cp.sum` as returning `int | Sum`. Implementers wrap it in `typing.cast(cp.Expression, ...)` where pyright needs it.

### 3. Assembly (what `problem.py` implements)

1. `data = sample.select(eventset)`, where the sample defaults to `Sample.full(eventset)`.
2. `measure = outcome_measure(data, basis, years=sample.years)`.
3. `specs = scope.partition(data)`, unless `specs` is passed in.
4. For each spec: `problem = scope.materialise(data, spec)` and `ctx = build_context(problem, payout_structure, measure)`.
5. `term = objective.build(ctx)` and `premium = pricing.premium(ctx)`. The constraints are `payout_structure.constraints(ctx.theta, ctx.cap)`, then `term.constraints`, then `premium.constraints`, then `c.build(ctx, premium)` for each extra constraint.
6. Build `cp.Problem(cp.Minimize(term.expression), constraints)`, wrap it in a `BuiltProblem`, and hand it to `solve.solve`.

`tests/test_walking_skeleton.py` runs this recipe with trivial components on a 3-event toy EventSet. It checks a hand-computed optimum, that the cvxpy and numpy paths agree, calibration on a train sample with evaluation on a test sample, and the record tables including a Parquet round trip.

**Loss scaling and caps.** `build_context` divides every loss and payout quantity by `scale`: by default the thesis rule, i.e. the maximum objective-level loss, or 1 if that is ≤ 1e-6. It also sets the cap per entity, by default the entity's maximum loss (thesis). Components work in scaled units and never see the scale. MAR-13 asked for scaling "inside, invisible to callers"; it lives in the builder instead, which is invisible to callers too. `SolveResult` reports loss units: `theta × scale` and `objective_value × scale**homogeneity`, where `ObjectiveTerm.homogeneity` is 1 for E[U] and CVaR and 2 for MSE.

**Basis is a problem-level input.** The objective, the premium and the budget always share one `OutcomeMeasure`, so they can't disagree on the basis. Objectives read `ctx.basis`. One that can't handle a basis raises `UnsupportedBasisError`. This is how MAR-13's "basis parameter on the objectives" is realised.

### 4. Basis and outcome measure (SPEC §6.2)

`OutcomeMeasure(basis, outcome_of_row[n_rows], probability[n_outcomes])`. Per-row quantities are transformed row by row (e.g. `(L_e − π_e)^+`), summed into outcomes (`aggregate` in numpy, `aggregate_expression` in cvxpy), then weighted by `probability`. The probabilities sum to 1. An outcome may have no rows, which is how zero-loss years enter.

- `event_conditional` (parity): one outcome per row, probability `rate / Σ rate` over the rows given. This reproduces the thesis rescaling after the threshold filter. Implemented in MAR-61, because it defines the parity contract and MAR-13 and MAR-16 both need it.
- `event` and `annual`: MAR-24, together with the general (non-per-row) case of `aggregate_expression`. That case needs a sparse matrix: MAR-24 adds `scipy`, which SPEC §4 already lists as a core dependency, as a declared dependency.

Objectives, pricing and evaluation are basis-agnostic. The annual basis changes `basis.py` only, not `objectives.py`, `pricing.py` or `evaluate.py`.

### 5. Samples and years (SPEC §6.1)

`Sample(name, rows[bool], years[int], fold=0)` holds a row mask and the simulation years the sample represents, including years without rows. `Sample.select` refuses rows from years outside its year set, which guards against leakage. `Scope.partition` runs on calibration data only, and `Scope.materialise` reuses that spec on any EventSet. Out-of-sample evaluation and the robust wrappers both rely on this.

**Year convention (owner-confirmed 2026-10-25, MAR-89):** `year ∈ [0, n_years)`, 0-based as in IRIS, the thesis and the merged MAR-9 parity fixture (years 0 to 9,999, matching the `NA_<year>_<tc>` event ids). SPEC §6 writes `y = 1..Y`; read that as notation, so "years 1–0.7Y" means the first 70 % of years. `Sample.full` enforces the range, and since MAR-82 (PR #18) the `EventSet` constructor does too.

### 6. Errors

`errors.py` defines the base `ParametricInsuranceDesignError` and, under it:

- `ComponentConfigError` (a `ValueError`), with the subclass `UnsupportedBasisError`;
- `ConfigError` (a `ValueError`);
- `InputMismatchError` (a `ValueError`), with the subclass `EntityMismatchError`;
- `SolveError` (a `RuntimeError`), carrying `problem_id`, `status` and `attempts`, with the subclasses `InfeasibleError` and `UnboundedError`;
- `RecordSchemaError` (a `ValueError`).

Implementing modules may add subclasses in their own files. A `SolveResult` exists only for an accepted status (`optimal`, or `optimal_inaccurate` if the policy allows it). Every failure raises.

### 7. Result-store records (`records.py`)

These are typed tables (`TableSchema`: columns, kinds, nullability, allowed values, key) with `validate`, `from_rows`, `empty` and `arrow_schema`. Evaluate, the runner, the store and viz all use them.

| Table | Key | Content |
|---|---|---|
| `runs` | run_id, problem_id | Config hash, source tag, component names, basis, calibration split/fold, parameters (canonical JSON of scalars), status, solver, objective value, premium, timings, error type/message, EventSet checksum (nullable in the schema; the runner fills it on every row since MAR-64, see §9 open points), package version, created_at (UTC). Failed solves are rows too |
| `entities` | run_id, problem_id, entity_id, location_id | Entity membership (cluster assignments) |
| `payouts` | run_id, problem_id, entity_id, param_index | Bin edges `lower`/`upper` and fitted level `value`. No arrays stored as strings |
| `kpis` | run_id, problem_id, eval_split, fold, basis, level, subject_id, kpi, beta | `value`, plus `ci_low`, `ci_high`, `ci_level`, `n_bootstrap` for MAR-23. `level` ∈ location/entity/problem/portfolio. `problem_id = "*"` marks rows across all problems of a run |
| `exceedance` | as kpis up to subject_id, then quantity, curve, return_period | `value`; `curve` ∈ event/oep/aep |

KPI names are an enum (`KpiName`) mapped to the thesis columns. A new KPI needs an amendment.

*Amendment (MAR-138, recording MAR-22, PR #78): k-fold is one run per fold.* A k-fold experiment calibrates once per fold, and each fold is a run of its own. `ExperimentConfig.single_runs()` expands a `kfold` sample without a `fold` into one config per fold, with `KFoldSampleConfig.fold` set, so the fold is part of the config hash and of the `run_id`. The runner refuses a k-fold config whose `fold` is unset. The `runs` key stays `(run_id, problem_id)`: no table gains a key column, and no schema changes. The fold number is in `runs.fold` (with `runs.calibration_split = "train"`), in the `fold` key column of `kpis` and `exceedance`, and in `runs.parameters` (`k` and `fold`). Sweeps expand the same way, one point per value and fold, and since MAR-138 each k-fold point's entry in the sweep manifest has a `fold` key (absent for other samples). Details: `docs/methodology/out-of-sample.md`.

### 8. `experiment/` subpackage

SPEC §4.2's `experiment.py` would be edited by four issues, so it becomes `experiment/config.py` (MAR-63), `experiment/runner.py` and `experiment/store.py` (MAR-64), and `experiment/sweeps.py` (MAR-65). MAR-66's CLI is the top-level `cli.py`, because later commands (`figures`, `export-site`) aren't experiment logic. These names match what the Linear issues already say. SPEC §4.2 should be updated to match (follow-up; SPEC edits aren't part of this issue).

### 9. EventSet choices ratified (MAR-8)

| # | Choice | Ruling |
|---|---|---|
| 1 | The event key is `(event_id, draw_id)`, unique across scenarios; `values` has no `scenario_id` | **Accepted.** Robust design takes one EventSet per scenario (`robust.build_scenario_robust(scenarios, ...)`), so `scenario_id` is descriptive |
| 2 | `location_id` is `str` | **Accepted.** Entity and problem ids are `str` too |
| 3 | `events` and `values` reject unknown columns; `locations` allows free metadata | **Accepted** |
| 4 | `values` is a complete grid; missing pairs are errors | **Accepted.** Dense matrices are the contract |
| 5 | Ranges: lon ∈ [−180, 180], lat ∈ [−90, 90], value ≥ 0, draw_id ≥ 0; index may be negative; year unchecked | **Accepted**, with an **amendment proposal**: validate year ∈ [0, n_years) (§5). **Amendment implemented by MAR-82, PR #18:** the EventSet constructor raises `OutOfRangeError` |
| 6 | The threshold filter keeps rows where any location ≥ threshold; default column `index` | **Accepted.** For the thesis filter on the portfolio max wind, this is the same thing. Dropped rows leave the `event_conditional` measure (thesis rescaling) and enter the annual measure as zero-loss mass, because the annual measure is built from years, not rows |
| 7 | Re-export `EventSet` from `__init__.py` | **Yes.** `EventSet` and `EventSetMetadata` are re-exported (§1) |
| 8 | EventSet errors live in `eventset.py` | **Accepted**, with an **amendment proposal**: `class EventSetError(ParametricInsuranceDesignError, ValueError)`. This is non-breaking, and lets callers catch the whole library with one class. **Amendment implemented by MAR-82, PR #18** |

With the row 5 amendment, MAR-82 adjusted two tests: in `tests/test_interfaces.py::test_full_sample_enforces_year_convention` the EventSet constructor now rejects one-based years, and the test reaches `Sample.full`'s own guard by bypassing validation; in `tests/test_clustering.py` the `make_eventset` helper wraps its years into `[0, n_years)` (clustering reads neither).

**Amendment: transforms record, implemented by MAR-88 (PR #23).** `EventSetMetadata` gains an append-only `transforms: tuple[TransformRecord, ...]`, like `filters`. A `TransformRecord` holds `name`, `function` (fully qualified producer), `version` (the producer's distribution version), `n_filters_before` (its position among `filters`) and `parameters` (a JSON object, nested values allowed, e.g. an impact-function prior for MAR-25). `noise.add_noise` writes one record and leaves `scenario` unchanged. Seeds stay in the run config. In `metadata.json` the key is optional (missing reads as empty), and unknown keys stay errors. `content_hash()` includes the records and leaves out an empty `transforms`, so EventSets without transforms keep their MAR-82 hashes. A producer may record its generating step as the first `TransformRecord` (`n_filters_before=0`), as the CLIMADA adapter does with `climada_tc_impact` (MAR-73, PR #34); this is a wording clarification within the existing contract (orchestrator, 2026-10-25), not a new field. An adapter build that draws randomly records its seed in its `TransformRecord`, because the adapter's build config is not stored with the EventSet: the CLIMADA adapter's `vulnerability_draws` record holds `vulnerability.seed` (MAR-25, PR #41; `seed: null` when the caller passes its own generator), so the EventSet can be reproduced from its metadata. Core runs keep their seeds in the run config (orchestrator, 2026-10-25).

**Amendment: location subset, implemented by MAR-92 (PR #27).** `EventSet.select_locations(location_ids) -> EventSet` keeps the given locations in the given order: matrix columns and `locations` rows (with their free columns). It keeps every event row, the metadata, the filters and the earlier transforms. It is the runner's step for `portfolio.location_ids` and each `n_assets` sweep point (MAR-63, MAR-64), before the noise layer, as in the thesis. Ids must be non-empty, unique, strings and known; otherwise it raises `SchemaError` (empty, a bare string, a non-string id), `DuplicateKeyError` or `InconsistentKeysError`, all with `table="locations"`. An empty selection is an error, not an empty EventSet, because the constructor refuses an EventSet without locations. Every call appends one `TransformRecord` with the existing MAR-88 structure, so no new field: `name="select_locations"` (exported as `SELECT_LOCATIONS_TRANSFORM`), `function` the method's qualified name, and `parameters={"location_ids": [...], "n_locations_before": n}`. It records even an identity selection, as `filter_threshold` records a filter that drops nothing, so `content_hash()` always tells a subset from its parent.

Open points left room for:

- **EventSet content hash:** implemented by MAR-82 (`EventSet.content_hash()`, PR #18). Since MAR-64 (PR #31) the runner fills `runs.eventset_checksum` on every row it writes, failed solves included, with the `content_hash()` of the EventSet as loaded (`experiment/runner.py`). The schema (`records.py`) still declares the column nullable; making it non-nullable would be a contract amendment, which has not been made.
- **Rate convention for draw rows (adopted in SPEC §5, MAR-83):** each of the `n` draws of an event gets `rate / n`, so the draws keep the event's total rate (thesis: `1/(Y·n_draws)` per row). `noise.add_noise` documents this. The annual basis (MAR-24) decides how draws map to outcomes, e.g. one outcome per (year, draw).
- **Year convention:** §5.

### 10. Ownership map

One owner issue per file. Other issues may import a module but never edit it. A change to anything marked *contract* goes through an amendment of this ADR: a PR that edits this file and the contract together, reviewed by the orchestrator. Where two issues need one file, they are **sequenced**: the second starts only after the first is merged.

| File (under `packages/core/`) | Owner | Notes |
|---|---|---|
| `src/.../interfaces.py` | MAR-61 | Contract; amendment only |
| `src/.../errors.py` | MAR-61 | Contract; new subclasses go in the owning module |
| `src/.../records.py` | MAR-61 → **MAR-130** | Contract; amendment only. *Amendment (MAR-130):* faster `validate`, same accepted and rejected frames, same errors and the same canonical output. A column's value types are decided from its dtype (pandas `string`, Arrow `string`/`large_string`, numpy bool/int/float, the nullable `boolean`/`Int*`/`Float*`) or, for an object column, from one `pandas.api.types.infer_dtype` pass; those shortcuts only accept. Anything they can't prove valid is checked value by value with the old `isinstance` rule (`_is_kind`), so every rejection is the old one. The allowed-values check looks at the column's distinct values. Schemas, the public interface and the Parquet files are unchanged; no store-specific fast path. Tests in `tests/test_records_validation.py` (MAR-130), which check every rejection on object, Parquet, nullable and Arrow-backed frames and the column check against the value-by-value rule (hypothesis) |
| `src/.../basis.py` | MAR-61 → **MAR-24** | MAR-61 built `event_conditional`; MAR-24 adds `event`, `annual` and grouped `aggregate_expression`. The public names are contract |
| `src/.../__init__.py` | MAR-61 | Re-exports only. Later changes via a "public API" follow-up, not by implementing issues |
| `src/.../eventset.py` | MAR-8 (Done) | Amendments via follow-ups (§9): year range, `EventSetError` base and content hash (MAR-82, PR #18), transforms record (MAR-88, PR #23), location subset (MAR-92, PR #27) |
| `src/.../noise.py` | MAR-10 | |
| `src/.../payout.py` | MAR-11 | |
| `src/.../index.py` | MAR-12 | Cat-in-a-circle (MAR-26) is precomputed by the CLIMADA adapter and served by `PointIndex`. MAR-26 owns no core file |
| `src/.../scopes.py` | MAR-12 | |
| `src/.../clustering.py` | MAR-12 | |
| `src/.../objectives.py` | MAR-13 | Includes `rockafellar_uryasev`, which MAR-27 imports |
| `src/.../pricing.py` | MAR-13 → MAR-27 → **MAR-143** | MAR-13 implements `PurePremium`; MAR-27 implements `CostOfCapitalLoad` after MAR-13 is merged. Both stubs exist now, so the signature is fixed. *Amendment (MAR-143):* `pricing.py` imports `var_cvar` from `riskmeasures.py`, not from `evaluate.py` (a problem component no longer imports the evaluation). `CostOfCapitalLoad.premium` is the plain Rockafellar–Uryasev term again, without the `cvxpy.transforms.partial_optimize` wrapper (the compiled LP has the same variables and constraints, `zeta` now a variable of the design problem). Its value at a solution is an upper bound on the loaded premium, exact where the budget binds; the exact premium is `premium_value`, which `solve` records (solve row). Signatures unchanged |
| `src/.../constraints.py` | MAR-13 | |
| `src/.../problem.py` | MAR-14 | `BuiltProblem` fields and both function signatures are contract |
| `src/.../solve.py` | MAR-14 | `SolverPolicy` fields are contract; default values are MAR-14's choice. MAR-98 (PR #38) tightened the default OSQP tolerance to `1e-8`; `THESIS_POLICY` (the pre-MAR-98 default, OSQP at cvxpy's defaults) exists for the parity gate only, by owner decision (MAR-98 option A). *Amendment (MAR-124):* `SolverPolicy` can be pickled (`__reduce__`: its class and fields, the options as plain dicts; unpickling calls the class, so the options are read-only again). Fields, equality and `policy_fingerprint` are unchanged, so run ids are too; `test_solve.py` pins the fingerprints and run ids of `DEFAULT_POLICY` and `THESIS_POLICY`. *Amendment (MAR-143): the premium of a solution.* `solve(built, policy=DEFAULT_POLICY, *, pricing=None)`: an optional keyword, so every existing call works unchanged. Given the pricing the problem was built with, `SolveResult.premium` is `pricing.premium_value` of the realised objective-level payout (`payout_structure.evaluate(index, theta)` in loss units, summed over the entities as `evaluate` sums them) under the problem's measure: exact, computed in numpy with no solver call, and equal to the in-sample `premium` KPI bit for bit. Without it, the premium term's value at the solution, as before (for a loaded premium the Rockafellar–Uryasev bound, exact only where the budget binds). A `pricing` that is not a `Pricing` raises `ComponentConfigError`. `SolveResult` (`interfaces.py`) and `BuiltProblem` (`problem.py`) are unchanged. Tests in `tests/test_solve_premium.py` |
| `src/.../evaluate.py` | MAR-16 → **MAR-143** | *Amendment (MAR-143):* `var_cvar` and the quantile helpers move to `riskmeasures.py`; `evaluate` re-exports `var_cvar` (same object, in `__all__`), so `from parametric_insurance_design.evaluate import var_cvar` keeps working. The per-row evaluation that `bootstrap.py` reused privately is public: `evaluate_results(eventset, scope, results, *, basis, sample=None) -> Evaluation` (fields `sample`, `measure`, `subjects`, `problem_payouts`), with `KpiSubject` (fields `level`, `problem_id`, `subject_id`, `loss`, `payout`); `kpis` and `exceedance_curves` use it, with unchanged signatures and tables |
| `src/.../riskmeasures.py` (new) | MAR-143 | `var_cvar`, `lower_quantile`, `sorted_cdf`, `discrete_distribution`, `check_beta` and `CDF_ATOL`: pure numpy, imports only `basis` and `errors`, so `pricing.py` and `evaluate.py` share one definition. A cumulative probability within `CDF_ATOL` (1e-10) below the level counts as reaching it, so a VaR or exceedance level on a step of the distribution is the exact-arithmetic quantile whatever order `argsort` gives tied values (Linux and macOS differ); the thesis compared exactly. Tests in `tests/test_riskmeasures.py` |
| `src/.../bootstrap.py` | MAR-23 → **MAR-143** | Block-bootstrap CIs, filling the `kpis.ci_*` columns. *Amendment (MAR-143):* imports the public `evaluate.evaluate_results` and `KpiSubject` instead of the private `_evaluate` and `_Subject`, and the CDF tolerance from `riskmeasures.CDF_ATOL` (same value, 1e-10). Public names and signatures unchanged |
| `src/.../splits.py` | MAR-22 | |
| `src/.../robust.py` | MAR-34 → **MAR-35** | R1 first; R2 only if D6 = yes at C1 |
| `src/.../experiment/__init__.py` | MAR-61 | Docstring only |
| `src/.../experiment/config.py` | MAR-63 | |
| `src/.../experiment/runner.py` | MAR-64 | *MAR-143:* `solve` is called with the run's pricing, so `runs.premium` and the manifest's problem `premium` are `pricing.premium_value` of the realised payout (solve row) |
| `src/.../experiment/store.py` | MAR-64 → **MAR-128** | *Amendment (MAR-128):* faster reads, same results and errors. `read(table, run_ids=...)` checks only the requested runs' manifest files (one `stat` each) instead of listing `manifests/`; the store caches nothing between calls, so a read sees runs that another process committed after an earlier read. Table files are read with `pq.ParquetFile(...).read()`. The public interface is unchanged: a bulk `read_manifests` was measured and gave no gain, so it was not added. Tests in `tests/test_store.py` |
| `src/.../experiment/sweeps.py` | MAR-65 → **MAR-105** | *MAR-105:* parallel execution, `run_sweep`/`run_sweeps(..., jobs=N)` (default 1, the serial path), with the typed error `SweepWorkerError` (a dead worker process). Workers only call `runner.execute`; the parent keeps the cache lookups and writes every run in point order, so the store keeps a single writer and `runner.py` and `store.py` are unchanged. Tests in `tests/test_sweeps_parallel.py`. *Amendment (MAR-124):* the `_PolicyFields` workaround is gone; the parent sends the `SolverPolicy` itself, after checking that a pickle round trip keeps its fingerprint (`SweepWorkerError` otherwise). *Amendment (MAR-131): cluster count of `n_assets` subsets.* The cluster scope config (`experiment/config.py`, its cluster-scope section) gains `cap_n_clusters: bool`, default `false`, the thesis behaviour: an `n_assets` subset with fewer locations than `n_clusters` keeps `n_clusters` and fails to build (`InputMismatchError`, a recorded failed run). With `true`, `sweep_points` gives such a point the effective count `min(n_clusters, len(subset))` (`ClusterScopeConfig.effective_n_clusters`) through `with_parameter("n_clusters", ...)`, so the run's config, its manifest (`config`, `parameters`), `runs.parameters` and its config hash carry the count it used; the `Cluster` scope never caps, so nothing is capped at run time. The cap is recorded, never silent: `SweepPoint` gains the defaulted fields `n_clusters_requested` and `n_clusters_effective` (and the property `n_clusters_capped`), and the sweep manifest point entries of a capped scope's cluster points gain the keys `n_clusters_requested` and `n_clusters_effective`; other entries, `sweep_membership` and `sweep_id` are unchanged. Other sweeps never cap. `cap_n_clusters` is left out of `to_dict`, `dump_config` and `canonical_json` while it is `false`, so every existing config, the parity config among them, dumps and hashes as before (no `CONFIG_HASH_DOMAIN` change). Tests in `tests/test_n_clusters_cap.py` |
| `src/.../cli.py` | MAR-66 | *MAR-105:* the `sweep` subcommand's `--jobs N` option only |
| `tests/conftest.py`, `tests/_doubles.py`, `tests/test_interfaces.py`, `tests/test_basis.py`, `tests/test_records.py`, `tests/test_walking_skeleton.py` | MAR-61 | Others may use the fixtures and doubles; changes need an amendment. MAR-87 (amendment) added `_doubles.py`: the payout, grouped-measure and context-builder doubles shared by `test_objectives.py`, `test_pricing.py` and `test_constraints.py`, imported with `from ._doubles import ...` (a relative import works under `--import-mode=importlib`). Its context builder calls the real `build_context`. MAR-24 may replace `GroupedMeasure` with the real grouped measure |
| `tests/test_<module>.py` | The module's owner | E.g. `test_payout.py` belongs to MAR-11 |
| `tests/test_engine_properties.py` (new) | MAR-15 | Analytical and property tests (SPEC §6.7) through the public API |
| `tests/test_import_boundaries.py` | MAR-122, **MAR-123** | AST check that no core module imports an adapter dynamically (`importlib.import_module`, `importlib.__import__`, `__import__`), the gap ruff's `TID251` (MAR-76) leaves. Its allow-list holds one call site, the `figures` lazy import of viz in `cli._import_viz`; a new dynamic import with a non-literal argument needs an entry there. **Amendment (MAR-123): runtime check.** A fresh interpreter (`python -I`, via `subprocess`) imports the core and every submodule `pkgutil.walk_packages` finds, and the test asserts that no `parametric_insurance_design_crc`, `parametric_insurance_design_climada` or `parametric_insurance_design_viz` module is then in `sys.modules`. It catches indirect loads (e.g. through a dependency) that the static checks can't see; viz counts because the core loads it only when `figures` runs. A submodule that fails to import or writes to stdout/stderr while importing fails the test, and the walked set must equal the module files the AST check parses |
| `pyproject.toml`, `uv.lock` (core and root) | Shared, append-only | An issue may add its own dependency or entry-point lines, with a one-line justification in its PR; never edit another issue's lines. On conflict: rebase on `main` and run `uv lock`. A change to the core's dependencies (`packages/core/pyproject.toml`) must also run `pixi lock` in `packages/climada` and commit `packages/climada/pixi.lock`, because the climada CI job installs with `--locked` and fails on a stale lock (MAR-71, PR #28). Examples: scipy (MAR-12/MAR-24), pydantic (MAR-63), the CLI entry point (MAR-66), hypothesis (MAR-15, root dev group) |
| `parity/BENCHMARK.md` | MAR-14 | Solve-time baseline |
| `packages/climada/src/.../portfolio_litpop.py`, `litpop_florida_manifest.json`, `tests/test_portfolio_litpop.py`, `scripts/estimate_florida_grid.py`; `research/data/d2-florida-litpop/` | MAR-113 | Not under `packages/core/`. LitPop cells to county locations (D2): pinned LitPop and TIGER/Line downloads, `aggregate_cells`, the 67-county `locations` table and its provenance. MAR-114 imports it; changes to the table's columns or the manifest go through a follow-up |
| `packages/climada/src/.../pipeline.py` and `config.py`, the per-cell loss path only; `configs/florida_counties*.yaml`, `scripts/florida_exposure_summary.py`, `tests/test_cell_loss.py`, `tests/test_florida_exposure_summary.py`; `research/data/d2-florida-eventset/` | MAR-114 | Not under `packages/core/`; the EventSet contract (SPEC §5) is unchanged. **Amendment (MAR-114): per-cell loss path.** A config section `loss` selects where the loss is computed: `{kind: centroid}` (default, the thesis: the impact at the location's `lat`/`lon`) or `{kind: cells, cells: <parquet>}` (D2: a location's loss is the sum of the impacts on its cells, e.g. MAR-113's `cells.parquet`). The index is unchanged (location level). The vulnerability hook runs on a cell-level `HazardBatch` (cells as its locations), so one `v_half` per (event, draw) is shared by every cell (MAR-25 semantics) and the generator stream is unchanged; `hooks.py` and `vulnerability.py` are not edited. `pipeline.read_cells` checks the cells (known `location_id`s, every location has a cell, cell values sum to the location value) and `build_eventset` checks that `max_dist_eye_km` plus the farthest cell from its location does not exceed `proximity_km`. The build record gains a `loss` object and `source_checksums` the cells file **only** in cells mode, so centroid builds (the thesis parity build) keep their content hashes. Two optional, default-neutral fields: `loss.unit` (written to `loss.unit` in `metadata.json`, default `"USD"`) and `scenario_notes` (sentences appended to the scenario description: value-unit caveat, attribution) |
| `packages/climada/src/.../storm.py`, `tests/test_storm.py`; `pipeline.py` and `config.py`, the track-source selection only; `configs/florida_counties_storm*.yaml`, `configs/florida_counties_no_draws.yaml`, `scripts/compare_hazard_return_levels.py`, `tests/test_compare_hazard_return_levels.py` | MAR-32 | Not under `packages/core/`; the EventSet contract (SPEC §5) is unchanged. **Amendment (MAR-32): track source.** A config section `tracks` selects the catalogue: `{kind: iris}` (default; `catalogue` is an IRIS text file) or `{kind: storm, basin: NA}` (D7; `catalogue` is the directory of the STORM files `STORM_DATA_IBTRACS_<basin>_1000_YEARS_<k>.txt`). `storm.read_storm_catalogue` rebuilds the simulation year as `1000 * k + year in file`, divides the 10-minute wind by 0.88, maps longitudes to (−180, 180] and raises on anything that would make the year mapping ambiguous (missing or repeated `k`, a year outside [0, 1000), `n_years` ≠ 1000 × files). `storm.storm_to_track` uses the IRIS path's time axis, units and environmental pressure (1,013 hPa), so the two catalogues differ only in the tracks. A STORM config must give `hazard_release` and `licence`. For STORM the build record's `catalogue` holds the per-file year mapping and SHA256s, `track_conversion` holds `storm.TRACK_CONVERSION`, `hazard.name` is `STORM`, and `source_checksums` lists every file; IRIS builds write exactly what they wrote before, so their content hashes are unchanged. The STORM download module and its manifest are not in this row yet (the 4TU host was unreachable) |

The viz package (`packages/viz/`, MAR-21 / F-08) follows the same rule. Viz modules read the result store and never import the solver, the problem builder, the runner, the sweeps or an adapter (SPEC §3.1 C6, ADR 0001; checked by `tests/test_imports.py`).

| File | Owner | Notes |
|---|---|---|
| `packages/viz/src/.../__init__.py`, `errors.py`, `style.py`, `reader.py`, `figure_data.py` | MAR-110 | Foundation: shared style (thesis `global_settings`), result-store reader, figure-data CSV writer, typed errors. Later sub-issues import them; a change goes through a follow-up. *Amendment (MAR-120):* `ResultReader.runs` reads in bulk (one `ResultStore.read` per table for all its runs, split by `run_id`; equal to `run` one at a time) and `ResultReader.kpis(run_ids)` reads the `kpis` table of many runs; `store.py` is unchanged |
| `packages/viz/src/.../payout_functions.py` | MAR-110 | Payout-function grid and normalised payout figure |
| `packages/viz/src/.../command.py` | MAR-110 → **MAR-111**, **MAR-112** | The `figures` figure set. MAR-111 and MAR-112 only append their builder to `FIGURE_SETS` (append-only); on conflict, rebase on `main`. *Amendment (MAR-112):* `SweepRun` (one sweep point: parameter, value, `run_id`, baseline single run, subset), `FigureContext.sweeps` and `FigureContext.eventset` (both defaulted, so existing builders are unaffected), `FigureContext.scope_of`, `write_figures(..., sweeps=)`, which checks that every sweep point is in the store before drawing (`MissingRunError`), and `FigureSet` returning any iterable, so a builder can be a generator that draws one figure at a time. *Amendment (MAR-120):* `write_figures(..., skip_missing_sweeps=, transaction_costs=)`; with `skip_missing_sweeps` missing sweep points are not an error but `FigureContext.missing_sweeps`, figure sets skip the figures that need them as `SkippedFigure(missing=True)`, and `FigureReport.missing_sweeps` lists them (`FigureReport.ok` is False if a figure was skipped as missing); `FigureContext.transaction_costs` (default the thesis' `THESIS_TRANSACTION_COSTS`). All new fields are defaulted |
| `packages/viz/src/.../kpi_figures.py` | MAR-111 | KPI heatmaps (`kpi_heatmap`), performance overview (`performance_overview`, thesis Fig 5.5) and exceedance curves (`exceedance_curves`, Fig 5.6), plus `kpi_table` and the `kpi_figures` builder in `FIGURE_SETS`. Reads only the `kpis` and `exceedance` tables; never re-evaluates payouts |
| `packages/viz/src/.../sweep_figures.py` | MAR-112 | Sweep plots, premium reallocation, tail-vs-total trade-off, cluster net advantage and break-even (thesis Figs 5.7 to 5.14, A.3), and the `sweep_figures` builder in `FIGURE_SETS`. Reads `FigureContext.sweeps`; never imports the sweeps module. *Amendment (MAR-120):* reads each sweep's runs in one bulk `ResultReader.runs` call, skips the figures whose points are in `FigureContext.missing_sweeps` (`SweepSeries.missing`), and passes `FigureContext.transaction_costs` to the net-advantage figure |
| `packages/viz/tests/conftest.py`, `tests/test_<module>.py` | The module's owner (MAR-110 for `conftest.py` and the foundation) | Others may use the `toy` and `failed` fixture stores but add their own fixtures in their test files |
| `packages/viz/pyproject.toml` | Shared, append-only | As the core's: MAR-110 added matplotlib, numpy, pandas, scipy |
| `packages/core/src/.../cli.py`, the `figures` subcommand only | MAR-110 → **MAR-112** | Imports `parametric_insurance_design_viz.command` lazily (`VizNotInstalledError` without it); the core never depends on viz. The rest of `cli.py` stays MAR-66's. *Amendment (MAR-112):* `_figures` also computes every sweep point's `run_id` (`sweep_points` + `run_key`, as the dry run of `sweep` does, so no sweep manifest is read) in the helper `_sweep_runs` and passes them as `sweeps=`. *Amendment (MAR-120):* `--skip-missing-sweeps` (missing sweep points skip their figures, listed as `MISSING`, exit 1; without it exit 3 as before) and `--transaction-costs TAU,...` (default the thesis values), passed to `write_figures`; adds `import math` and the parser helper `_costs` |
| `packages/core/tests/test_cli_figures.py` | MAR-110 → MAR-112, MAR-120 (additions) | |

**Parallel dispatch.** MAR-10, MAR-11, MAR-12, MAR-13, MAR-14 and MAR-16 own disjoint files and can be built at the same time. Each one tests against the contracts with small test doubles, as the walking skeleton does. The acceptance tests that need several real components (MAR-14: all nine combinations solve on the fixture; MAR-16: KPIs match the thesis on the fixture) also need MAR-11, MAR-12 and MAR-13 merged, plus the MAR-9 fixture.

### 11. How the contracts fit the planned work

| Need | Where the contract leaves room |
|---|---|
| C1 one builder | `problem.build_problems` composes the five component kinds |
| C2 no globals | Components are frozen dataclasses with explicit parameters; `np.random.Generator` is passed in (`noise.add_noise`) |
| C3 no silent failures | `SolveResult` only on success; `SolveError` carries every attempt; `runs` rows for failures; `EntityMismatchError` instead of dropping |
| C5, C6 data and layers | `records` schemas; viz reads only the store |
| §6.1 out of sample | `Sample` (rows + years), `partition`/`materialise` split, `eval_split`/`fold` columns, `ci_*` columns |
| §6.2 annual basis | `OutcomeMeasure`; basis-agnostic objectives, pricing and evaluation |
| §6.3 vulnerability draws, cat-in-a-circle | Draws are rows (`draw_id`), kept in one fold by year-based samples; precomputed indices go through `PointIndex` |
| §6.4 loaded pricing | `Pricing.premium` returns a `Term` with its own constraints (Rockafellar–Uryasev auxiliaries); shared `rockafellar_uryasev` |
| §6.5 R1 | `build_context(..., scale=, theta=)` shares θ across scenario contexts; `specs=` reuses the reference partition |
| §6.5 R2 | `ObjectiveTerm` decomposition `probability @ per_outcome + offset` lets a wrapper re-weight outcomes |
| Piecewise-linear payouts (parked) | Any `PayoutStructure` linear in θ: a basis matrix of hat functions |

## Consequences

- Workers can build the core blocks in parallel against stable contracts. The walking skeleton fails if a contract change breaks composition.
- Contract changes cost an ADR amendment. That's deliberate, and cheap for small additions (a new KPI name, a new error subclass).
- `cvxpy>=1.6` is a core dependency. Clarabel, OSQP and SCS come with cvxpy; HiGHS comes with cvxpy ≥ 1.8 (highspy), which needs numpy ≥ 2, and with older versions through the `SCIPY` interface. The CLIMADA env (`packages/climada/pixi.lock`, MAR-71) is CLIMADA 6.1.0 on Python 3.12 and resolves numpy 2.3.5, scipy 1.15.2 and cvxpy 1.9.3, so HiGHS is available there (highspy 1.15.1). MAR-14's solver policy still copes with HiGHS missing, as on any install with cvxpy < 1.8 (e.g. the core's lowest-direct CI job, numpy 1.26). *Correction (MAR-97):* this ADR first said the CLIMADA env had numpy 1.26 and cvxpy 1.7.x without HiGHS. That came from the thesis env (`climada_env.yml` of `parametric-insurance-framework`: CLIMADA 6.0.1, Python 3.11, numpy 1.26.4), not from this program's pixi env.

## Follow-ups proposed

- Done: `eventset.py` year range, `EventSetError` base and content hash (MAR-82, PR #18), transforms record (MAR-88, PR #23) and location subset (MAR-92, PR #27); SPEC §4.2 module list (MAR-83, PR #17).
- MAR-23: create `bootstrap.py`.
