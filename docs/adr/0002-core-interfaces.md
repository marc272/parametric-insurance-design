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
| `evaluate.py` | `var_cvar`, `kpis`, `exceedance_curves` |
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
solve.solve(built, policy=DEFAULT_POLICY) -> SolveResult      # or raises SolveError
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

**Year convention (proposed here):** `year ∈ [0, n_years)`, 0-based as in IRIS, the thesis and the merged MAR-9 parity fixture (years 0 to 9,999, matching the `NA_<year>_<tc>` event ids). SPEC §6 writes `y = 1..Y`; read that as notation, so "years 1–0.7Y" means the first 70 % of years. `Sample.full` enforces the range. Validating it when an EventSet is built is a proposed `eventset.py` amendment (follow-up).

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
| `runs` | run_id, problem_id | Config hash, source tag, component names, basis, calibration split/fold, parameters (canonical JSON of scalars), status, solver, objective value, premium, timings, error type/message, EventSet checksum (nullable until the hash follow-up), package version, created_at (UTC). Failed solves are rows too |
| `entities` | run_id, problem_id, entity_id, location_id | Entity membership (cluster assignments) |
| `payouts` | run_id, problem_id, entity_id, param_index | Bin edges `lower`/`upper` and fitted level `value`. No arrays stored as strings |
| `kpis` | run_id, problem_id, eval_split, fold, basis, level, subject_id, kpi, beta | `value`, plus `ci_low`, `ci_high`, `ci_level`, `n_bootstrap` for MAR-23. `level` ∈ location/entity/problem/portfolio. `problem_id = "*"` marks rows across all problems of a run |
| `exceedance` | as kpis up to subject_id, then quantity, curve, return_period | `value`; `curve` ∈ event/oep/aep |

KPI names are an enum (`KpiName`) mapped to the thesis columns. A new KPI needs an amendment.

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

**Amendment: transforms record, implemented by MAR-88.** `EventSetMetadata` gains an append-only `transforms: tuple[TransformRecord, ...]`, like `filters`. A `TransformRecord` holds `name`, `function` (fully qualified producer), `version` (the producer's distribution version), `n_filters_before` (its position among `filters`) and `parameters` (a JSON object, nested values allowed, e.g. an impact-function prior for MAR-25). `noise.add_noise` writes one record and leaves `scenario` unchanged. Seeds stay in the run config. In `metadata.json` the key is optional (missing reads as empty), and unknown keys stay errors. `content_hash()` includes the records and leaves out an empty `transforms`, so EventSets without transforms keep their MAR-82 hashes.

Open points left room for:

- **EventSet content hash:** `runs.eventset_checksum` is nullable until the `eventset.py` follow-up lands.
- **Rate convention for draw rows (proposed):** each of the `n` draws of an event gets `rate / n`, so the draws keep the event's total rate (thesis: `1/(Y·n_draws)` per row). `noise.add_noise` documents this. The annual basis (MAR-24) decides how draws map to outcomes, e.g. one outcome per (year, draw).
- **Year convention:** §5.

### 10. Ownership map

One owner issue per file. Other issues may import a module but never edit it. A change to anything marked *contract* goes through an amendment of this ADR: a PR that edits this file and the contract together, reviewed by the orchestrator. Where two issues need one file, they are **sequenced**: the second starts only after the first is merged.

| File (under `packages/core/`) | Owner | Notes |
|---|---|---|
| `src/.../interfaces.py` | MAR-61 | Contract; amendment only |
| `src/.../errors.py` | MAR-61 | Contract; new subclasses go in the owning module |
| `src/.../records.py` | MAR-61 | Contract; amendment only |
| `src/.../basis.py` | MAR-61 → **MAR-24** | MAR-61 built `event_conditional`; MAR-24 adds `event`, `annual` and grouped `aggregate_expression`. The public names are contract |
| `src/.../__init__.py` | MAR-61 | Re-exports only. Later changes via a "public API" follow-up, not by implementing issues |
| `src/.../eventset.py` | MAR-8 (Done) | Amendments via follow-ups (year range, error base, content hash) |
| `src/.../noise.py` | MAR-10 | |
| `src/.../payout.py` | MAR-11 | |
| `src/.../index.py` | MAR-12 | Cat-in-a-circle (MAR-26) is precomputed by the CLIMADA adapter and served by `PointIndex`. MAR-26 owns no core file |
| `src/.../scopes.py` | MAR-12 | |
| `src/.../clustering.py` | MAR-12 | |
| `src/.../objectives.py` | MAR-13 | Includes `rockafellar_uryasev`, which MAR-27 imports |
| `src/.../pricing.py` | MAR-13 → **MAR-27** | MAR-13 implements `PurePremium`; MAR-27 implements `CostOfCapitalLoad` after MAR-13 is merged. Both stubs exist now, so the signature is fixed |
| `src/.../constraints.py` | MAR-13 | |
| `src/.../problem.py` | MAR-14 | `BuiltProblem` fields and both function signatures are contract |
| `src/.../solve.py` | MAR-14 | `SolverPolicy` fields are contract; default values are MAR-14's choice |
| `src/.../evaluate.py` | MAR-16 | |
| `src/.../bootstrap.py` (new, not created yet) | MAR-23 | Block-bootstrap CIs, filling the `kpis.ci_*` columns |
| `src/.../splits.py` | MAR-22 | |
| `src/.../robust.py` | MAR-34 → **MAR-35** | R1 first; R2 only if D6 = yes at C1 |
| `src/.../experiment/__init__.py` | MAR-61 | Docstring only |
| `src/.../experiment/config.py` | MAR-63 | |
| `src/.../experiment/runner.py` | MAR-64 | |
| `src/.../experiment/store.py` | MAR-64 | |
| `src/.../experiment/sweeps.py` | MAR-65 | |
| `src/.../cli.py` | MAR-66 | |
| `tests/conftest.py`, `tests/test_interfaces.py`, `tests/test_basis.py`, `tests/test_records.py`, `tests/test_walking_skeleton.py` | MAR-61 | Others may use the fixtures; changes need an amendment |
| `tests/test_<module>.py` | The module's owner | E.g. `test_payout.py` belongs to MAR-11 |
| `tests/test_engine_properties.py` (new) | MAR-15 | Analytical and property tests (SPEC §6.7) through the public API |
| `pyproject.toml`, `uv.lock` (core and root) | Shared, append-only | An issue may add its own dependency or entry-point lines, with a one-line justification in its PR; never edit another issue's lines. On conflict: rebase on `main` and run `uv lock`. Examples: scipy (MAR-12/MAR-24), pydantic (MAR-63), the CLI entry point (MAR-66), hypothesis (MAR-15, root dev group) |
| `parity/BENCHMARK.md` | MAR-14 | Solve-time baseline |

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
- `cvxpy>=1.6` is a core dependency. cvxpy ≥ 1.8 needs numpy ≥ 2, so the CLIMADA env (numpy 1.26) resolves to cvxpy 1.7.x. Clarabel, OSQP and SCS come with cvxpy; HiGHS comes with cvxpy ≥ 1.8 (highspy), and with older versions through the `SCIPY` interface. MAR-14's solver policy must cope with HiGHS being missing.

## Follow-ups proposed

- `eventset.py`: validate `year ∈ [0, n_years)`; derive `EventSetError` from `ParametricInsuranceDesignError`; add an EventSet content hash for `runs.eventset_checksum`.
- SPEC §4.2: list the `experiment/` subpackage, `cli.py`, `interfaces.py`, `basis.py`, `errors.py`, `records.py` and `constraints.py`.
- MAR-23: create `bootstrap.py`.
