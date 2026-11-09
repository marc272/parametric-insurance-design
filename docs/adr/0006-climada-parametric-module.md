# ADR 0006: Design of the `climada_petals.engine.parametric` module

- Status: **Proposed**, for the owner's decision D12 (MAR-48). A worker agent prepared it under the issue's "Agent may prepare" part. Nothing here is decided until Marc Prinzing accepts it.
- Date: 2026-11-09
- Decision issue: MAR-48 (K-02). It feeds K-13 (MAR-312), K-15 to K-23 (MAR-314 to MAR-322), K-04 (MAR-50) and the questions of K-01 (MAR-47). It absorbs `docs/adr/climada-module.md`, the feedback skeleton on the branch of PR #39 (§15).
- Prepared from `main` at `98f184b`. The evidence is K-12 ([`docs/climada/k12-design-facts.md`](../climada/k12-design-facts.md), MAR-311), the prototype (`packages/climada/src/petals_parametric`, MAR-168) and the design review of 2026-11-09 (MAR-344, whose inputs Marc accepted). The sources of CLIMADA 6.2.0 and of `cat_bonds` in petals 6.2.0 were read at their tags, read-only.
- Boundary: this stream stays free of CRC code and data. [ADR 0005](0005-crc-parametric-module.md)'s text was read for its concepts and metric definitions only. No crc-sdk code or data was read, copied or ported: crc-sdk is AGPL and petals is GPL v3.

**How to read it.** The table below is the short version. "Decisions for the owner" gives the options and one recommendation for each of the 18 decisions: the 16 of MAR-48, and the two that K-12 says the list lacks. §1 to §15 say what the module looks like if the recommendations are accepted. Everything in those sections is the agent's recommendation.

This is a design record. It presents the method and the options. It makes no statement that a tail objective does better than another objective, and none about how joint calibration does against calibrating each unit alone.

## Decisions at a glance

| # | Decision | Recommendation | Against the issue's starting recommendation |
|---|---|---|---|
| [1](#d1-does-the-build-wait-for-the-maintainers) | Does the build wait for the maintainers? | No. K-01 gates only the upstream PR | Same |
| [2](#d2-location) | Location | `climada_petals.engine.parametric`, next to `cat_bonds` | Same |
| [3](#d3-api-shape) | API shape | Classes with `from_*` constructors and module functions. No plan object | Same |
| [4](#d4-cover-and-result-apart) | Cover and result apart | Yes: `ParametricCover` holds the terms, `CalibrationResult` the record | Same |
| [5](#d5-result-objects) | Result objects | Payouts and **uncovered losses** as `Impact`, metrics as pandas | **Changed:** a net loss can't be an `Impact` |
| [6](#d6-annual-basis) | Annual basis | The event basis on frequencies always works. The annual basis takes a stated route, `CatalogueYears` or `YearSets`, with no default | Same, and the event basis is now defined |
| [7](#d7-insured-units) | Units | A point, a group or the whole set. A group's payout maps back by value share | Same |
| [8](#d8-payout-families) | Payout families | Step, linear, piecewise linear, binary and a user protocol. Nothing paid below the attachment | Same, and `first_bin` is retired |
| [9](#d9-free-shape-parameters) | Free shape parameters | A stated grid with an exact solve at each point. Joint designs take fixed thresholds | Same, with a rule for joint designs |
| [10](#d10-solver-and-dependencies) | Solver and dependencies | scipy's public HiGHS for the LPs. For MSE, `SLSQP` on the amounts, with cutting planes under a loaded premium. No new package, and stated size limits | The MSE route is now chosen |
| [11](#d11-basis-risk) | Basis risk | Structural sources lead, measured and flagged. Impact-function draws come second. No required model | **Changed** (MAR-344) |
| [12](#d12-phase-1-scope) | Phase 1 scope | Several exposures, joint calibration and scenarios are all in Phase 1 | Same |
| [13](#d13-metric-definitions-and-names) | Metric definitions | ADR 0005's where the concepts coincide, plus `payout_frequency`, `unidentified_share` and a budget frontier | Extended (MAR-344) |
| [14](#d14-relation-to-cat_bonds) | Relation to `cat_bonds` | Complementary. `Subareas` is a unit source, and nothing inside it is edited | Same |
| [15](#d15-the-tutorials-case) | The tutorial's case | Jamaica for tropical cyclones, Luxembourg for the second hazard (windstorm). Florida stays with the paper | Same, and the second hazard is named |
| [16](#d16-the-issue-map) | The issue map | K-14 to K-23 confirmed, with the adjustments of §14 | New |
| [17](#d17-the-lp-method) | The LP method (from K-12) | Stated, with a rule as the default: `highs` for one unit, `highs-ipm` for several | New |
| [18](#d18-which-climada-the-module-targets) | Which CLIMADA (from K-12) | `develop` of both repositories, declaring `climada>=6.1` | New |

## Context

### Requirements (owner, 2026-11-08)

Marc started the CLIMADA lane on 2026-11-08: a generic parametric insurance module for CLIMADA, similar in principle to the CRC module but accounting for how CLIMADA works, and a detailed tutorial notebook. With it, users:

- create a parametric cover for a hazard and exposures;
- analyse its effectiveness on several metrics (overall coverage, tail coverage, basis risk, …) and under different scenarios;
- compare covers.

The module makes no assumption about the hazard, the exposures, the impact functions, the scenario, the optimisation goal, or the payout function's type and parametrisation.

The thesis's two ideas are features from Phase 1 (Marc, 2026-10-31): the weighted CVaR of the uncovered loss as an optimisation goal next to MSE and E[U], and calibration across one owner's exposures. **The calibration scope is a first-class design element next to the objectives** (§6.1). Cluster scope is in only if the maintainers want it (K-31).

Phase 2 is continuous: multi-hazard covers, cluster scope, robust design and trajectories, `unsequa`, cost-benefit and a bridge to cat bonds (§13).

### How CLIMADA differs from the CRC module's setting

| | CRC module | CLIMADA | Where this ADR handles it |
|---|---|---|---|
| Probability | Fitted curves or per-year series; a row is a year | An event set: each event has a frequency, and years exist only if the catalogue holds them | §5 |
| Dependence across sites | Lost in curves, so joint work needs a stated dependence model | Each event is one joint footprint | §6.1 |
| Loss | Impact × value, computed by the module | `ImpactCalc` gives an `Impact` with `imp_mat` | §4 |
| Insured unit | One asset | Exposure points, often thousands | §4 |
| Index | The value at the asset | Any statistic of a footprint, tracks, another hazard set or a user's table | §4 |
| Basis risk | A required, stated model | Comes from the data's structure; a centroid index with one impact function has almost none | §8 |
| Scenarios | Pathways and horizons in a dataset | Another `Hazard` or `Exposures`; `apply_climate_scenario_knu` changes frequencies only | §9 |
| Results and API | Arrow, Parquet, `explain()`, a lazy plan | `Impact`, pandas, `plot_*`, `from_*` constructors | §2, §7 |
| Dependencies | `highspy` as an optional extra | A new package needs the admins' permission; petals has no optional extras | §6.4 |
| Licence | AGPL-3.0-or-later | GPL v3 | The header above |

### What CLIMADA and petals give

| # | Fact | Where |
|---|---|---|
| C1 | A `Hazard` holds `event_id`, `event_name`, `date`, `frequency`, `frequency_unit` and a sparse `intensity` matrix, in which zero means no recorded intensity | CLIMADA; K-16's notes |
| C2 | `ImpactCalc(exposures, impfset, hazard).impact(save_mat=True)` gives an `Impact` whose `imp_mat` is events × exposure points. `calc_freq_curve`, `local_exceedance_impact`, `impact_per_year`, `write_hdf5` and the plots work on any `Impact` | CLIMADA 6.2.0 |
| C3 | No single year structure holds across the Data API's hazards. `random_walk` files have non-uniform frequencies on the whole file, and their future files differ between members of one parent. STORM's `date` holds no year. Flood and wildfire hold one event per year or member-year. Windstorm's dates cover 74 seasons and its frequency implies 73 | K-12 Q2, Q3 |
| C4 | Summed frequencies can be far above 1 per year: 1.95 for windstorm in Luxembourg, 365.9 for the earthquake file, 98.96 for the whole `random_walk` file | K-12 Q2 |
| C5 | `climada.util.yearsets` samples years from an event set. `with_replacement` defaults to False, which distorts non-uniform frequencies. `sample_from_poisson` touches numpy's global seed; `sample_events` takes a `Generator`. A `sampling_vect` holds positions, not event ids, although its docstring says ids. `impact_yearset_from_sampling_vect` returns annual totals with no `imp_mat` | CLIMADA 6.2.0; K-12 Q4 |
| C6 | `Impact.local_exceedance_impact` filters out values at or below `min_impact`, which is 0 by default. `calc_freq_curve(return_per=...)` is deprecated in 6.2.0 | CLIMADA 6.2.0 |
| C7 | `climada.util.calibrate` is impact-function calibration, a different meaning of the word | CLIMADA 6.2.0 |
| C8 | `Impact.calc_risk_transfer(attachment, cover)` is an indemnity layer on each event's total. It is CLIMADA's only insurance layer, and its source carries a note to rewrite it | K-34's notes |
| C9 | `cat_bonds` designs parametric sovereign cat bonds. A subarea's index is `index_stat`: `"mean"` or a percentile of the footprint. Its payout is `calc_payout(min_trig, max_trig, haz_int, max_pay)`. There, "basis risk" names the event-level squared error, and `attachment_point` and `exhaustion_point` are levels of loss | petals 6.2.0; K-12 Q8 |
| C10 | `Subareas` holds polygons with no point-to-subarea column. `from_resolution` raises on one exposure point. `from_geodataframe`'s coverage check never fires. COBYLA can return `min_trig > max_trig` | K-12 Q8 |
| C11 | Neither cvxpy nor highspy is a dependency of CLIMADA or petals. Petals has no optional extras. `pymoo`, the one solver package it requires, is a genetic-algorithm library | K-12 Q6 |
| C12 | CLIMADA's conventions: `from_*` constructors, `write_*`, `plot_*` returning axes, a module `LOGGER`, numpydoc, pylint with `max-args=7` and at most 1,000 lines per module, `unittest` classes, unit tests of at most 2 s, 100 % line coverage of new code | K-11, K-14, K-23 |
| C13 | conda-forge can't install climada 6.2.0 and petals together: petals 6.2.0 pins `climada 6.1.*`. Petals `develop` declares `climada>=6.1`. The prototype passes on 6.1, on 6.2.0 and on `develop` of both | K-12 Q1 |

### What the prototype gives, and what it taught

The prototype has one payout family (`StepPayout`), two objectives as LPs and MSE through cvxpy, `individual` and `portfolio` scopes, the annual and event bases, cat-in-a-circle, and metrics. Its 301 tests pass on every environment K-12 tried. Lessons that shape this design:

- **A calibration result is not a contract.** Its `ParametricCover` holds levels and how they were found, so it can't be written down or carried to another hazard set without its index and years (§3).
- **Years don't belong to the index.** `ParametricIndex` takes each event's year, the number of years and the first year. That ties every index to the catalogue route, and its default accepted hazards whose dates hold no usable year, with only a logged warning: STORM became 2 outcomes out of 10,000, flood 21 of 920, windstorm 66 of 2,190 (K-12 Q3). §5 moves years out and makes that an error.
- **The annual basis needs `frequency = 1/N`**, which fails on climate-scaled hazards. **The event basis needs frequencies that sum to at most 1**, which fails on C4.
- **One unit is one exposure point**, and the loss is densified. At 1,000 units × 50,000 events the dense arrays alone hold 763 MB (K-12 Q5).
- **Limits of the host.** `calibrate` has more arguments than `max-args=7`, and `index.py` has 985 lines against the limit of 1,000.
- **A hidden cap.** Levels are capped at each unit's largest calibration loss without the caller saying so. Here it is a stated term (§3).

### Rules that constrain the design

- The module never imports `parametric_insurance_design` or the CLIMADA adapter. Parity goes through K-13's fixtures (§12).
- No new package without the admins' permission (C11). Nothing paid below the attachment (owner, 2026-11-01). No silent failures: typed errors, or a failure recorded in the result.
- No data committed. Tests are offline, on small synthetic objects.
- The publication rule (`AGENTS.md`) binds the module's docs and the tutorial: every number with its setup, external numbers from out-of-sample runs on the annual basis, tail statements only conditional on a stated setup, joint calibration as a method only.

## The design, if the recommendations are accepted

### 1. Concepts and names

The two modules use the same word where the concept is the same. Where the concept differs, or CLIMADA already uses the word, the name differs and the table says why.

| Concept | Name here | CRC module (ADR 0005) | CLIMADA or `cat_bonds` term | Prototype |
|---|---|---|---|---|
| Cover: the contract terms | `ParametricCover` | `Cover` | none | `ParametricCover`, but there it is the calibration result |
| What the cover pays on | `IndexDefinition` | `IndexDefinition` | `index_stat` | fields of `ParametricIndex` |
| The index's values, per event and unit | `ParametricIndex` | a column of `OutcomeSample` | `_calc_parametric_index`'s table | `ParametricIndex` |
| Insured unit | `InsuredUnits`, `unit_id` | asset, `asset_id` | an exposure point, `region_id`, a subarea | unit, one exposure point |
| Payout function | `PayoutFunction` (protocol); `StepPayout`, `LinearPayout`, `PiecewiseLinearPayout`, `BinaryPayout` | the same | `calc_payout` | `StepPayout` |
| One parameter | a float, or `Free(lower, upper, grid=...)` | the same | none | `theta` |
| What an outcome is | `EventBasis`, `CatalogueYears`, `YearSets` | `semantics="annual"` | `frequency`, `date`, `climada.util.yearsets` | `basis=` and `event_year=` |
| What a cover is designed or evaluated on | `OutcomeSample` | `OutcomeSample` | an `Impact` and a basis | `index`, `impact`, `years` |
| Objective | `MSE`, `ExpectedUncovered`, `WeightedCVaR`, `UserObjective` | the same | "basis risk" is `cat_bonds`' squared-error objective | `MeanSquaredError`, `ExpectedUncovered`, `WeightedCVaR` |
| Scope | `scope="individual"` or `scope="joint"` | `Individual()`, `Joint()` | "pooling" is something else (below) | `"individual"`, `"portfolio"` |
| Pricing | `PurePremium`, `CostOfCapitalLoad` | the same | `premium_class.py` prices bonds | the same |
| Constraints | `Budget(ratio=κ)` or `Budget(amount=B)`; `Limit` | the same | `principal` caps a bond | `budget=κ`; an implicit cap |
| The verb | `calibrate`, `calibrate_frontier` | `design`, `design_frontier` | `climada.util.calibrate` means impact functions (C7) | `calibrate` |
| Its result | `CalibrationResult` | `DesignResult` | `SubareaCalculations` | `ParametricCover` with `CoverProblem` |
| Evaluation | `evaluate`, `compare`, `MetricOptions` | the same | `pay_vs_dam` | `basis_risk` |
| A set of scenarios | `ScenarioSet` | `ScenarioSet` | another `Hazard`; `climate_scenario`, `ref_year` | none |

Naming rules:

- **`scope="joint"`, not `"portfolio"`.** The prototype and K-19 say `"portfolio"`. Here "the whole portfolio" is also a *unit* (K-16's title): one payout for the whole exposure set. The two are different things, so the scope takes the CRC module's word. Tables use `level="unit"` and `level="total"`.
- **`calibrate`, not `design`.** It is the prototype's word and the thesis's, and `cat_bonds` calibrates its payout functions too. Docstrings say once that `climada.util.calibrate` calibrates impact functions and is unrelated.
- **"Attachment" is an index threshold here.** In `cat_bonds`, `attachment_point` and `exhaustion_point` are levels of *loss*, which set a bond's principal. `LinearPayout.from_triggers(min_trig, max_trig, max_pay)` takes `cat_bonds`' words for the same three numbers as `LinearPayout(attachment, exhaustion, limit)`.
- **"Basis risk" is a family of metrics here** (§7), not one objective. **"Pooling"** in `cat_bonds` groups countries into one bond; this module has no such concept and doesn't use the word.
- **`Impact` is CLIMADA's object. "Loss"** is `imp_mat` aggregated to units, in `Impact.unit`. **"Index"** is the value the cover pays on, whatever it is computed from.
- **"Budget"** is the premium budget, and **"load"** is only the cost-of-capital load. **"CVaR" never stands alone** in a metric name: `cvar_uncovered`, `cvar_net_loss`, `cvar_loss`.
- `index_stat`, `"mean"` or a percentile, keeps `cat_bonds`' parameter name and values (§4).

### 2. API shape, module layout and errors

**Shape.** Classes with `from_*` constructors and module functions, eager and in memory. There is no lazy plan: `ADR 0005` needs one because CRC's sources are remote and lazy, while a CLIMADA user already holds a `Hazard` and an `Impact`. Every function fits `max-args=7`.

A full run, in outline. The names are this ADR's, and nothing here is implemented yet.

```python
from climada.engine import ImpactCalc
from climada_petals.engine import parametric as pm

impact = ImpactCalc(exposures, impfset, hazard).impact(save_mat=True)

units = pm.InsuredUnits.from_column(exposures, "parish")
index = pm.ParametricIndex.from_hazard(hazard, units, index_stat="mean", weight="value")
basis = pm.YearSets.from_frequencies(
    impact, n_years=20_000, rng=np.random.default_rng(311)
)
sample = pm.OutcomeSample.from_impact(index, impact, units=units, basis=basis)
train, test = pm.holdout(sample, train_fraction=0.7, rng=np.random.default_rng(312))

template = pm.ParametricCover(
    index.definition,
    pm.StepPayout.uniform(attachment=33.0, exhaustion=80.0, n_steps=5),
    unit_id=units.unit_id,
    payout_unit=impact.unit,
    limit=pm.Limit.largest_loss(),
)
result = pm.calibrate(
    template,
    train,
    pm.WeightedCVaR(alpha=0.9, beta=0.99),
    scope="joint",
    budget=pm.Budget(ratio=1.0),
)
table = pm.evaluate(result, test, split="out_of_sample")
payouts = pm.payout_impact(result.cover, test)  # a climada Impact
```

**Signatures in outline** (types abbreviated; the owner issue in brackets):

```text
# covers (K-15)
Free(lower=0.0, upper=None, *, grid=None)
StepPayout(breakpoints, levels, *, tail="upper", monotone=True)
StepPayout.uniform(attachment, exhaustion, n_steps, *, levels=None, tail="upper", monotone=True)
LinearPayout(attachment, exhaustion, limit, *, tail="upper")
LinearPayout.from_triggers(min_trig, max_trig, max_pay, *, tail="upper")
PiecewiseLinearPayout(knots, levels, *, tail="upper", monotone=True)
BinaryPayout(trigger, amount, *, tail="upper")
register_payout(cls) -> cls
IndexDefinition(kind, *, unit, tail="upper", index_stat=None, weight=None, source=None, parameters=None)
Limit(amount)    # one float, or a mapping by unit id
Limit.largest_loss()
ParametricCover(index, payout, *, unit_id, payout_unit, limit=None, label=None)
    # payout: one family for every unit, or a mapping by unit id
    .free_parameters() -> tuple[str, ...]
    .with_values(values) -> ParametricCover
    .payout_matrix(index: ParametricIndex) -> NDArray      # (n_events, n_units); resolved covers only
    .to_dict() -> dict; .write_json(path) -> None; ParametricCover.from_json(path_or_text) -> ParametricCover
    .definition_hash -> str

# units and index (K-16)
InsuredUnits.points(exposures)
InsuredUnits.from_column(exposures, column)                # a column of Exposures.data, such as region_id
InsuredUnits.from_geometries(exposures, gdf, *, id_column)
InsuredUnits.whole(exposures, *, unit_id="total")
InsuredUnits.from_subareas(subareas, exposures)            # K-22
    .unit_id; .membership -> csr (n_points, n_units)
    .aggregate(imp_mat) -> csr (n_events, n_units)
    .to_points(payout) -> csr (n_events, n_points)         # by value share
ParametricIndex(values, event_id, unit_id, definition)     # (n_events, n_units); holds no years
ParametricIndex.from_hazard(hazard, units, *, index_stat="at_centroid", weight=None, absent_value=None)
ParametricIndex.from_cat_in_circle(tracks, units, *, hazard, radius_km)
ParametricIndex.from_table(table, units, *, definition, event_id="event_id", unit_id="unit_id", value="value")
    .matched_to(impact, *, on="event_id") -> ParametricIndex

# outcomes (K-17)
EventBasis()
CatalogueYears.from_dates(hazard, *, season_start_month=1, n_years=None)
CatalogueYears.from_event_names(hazard, pattern, *, n_years=None)       # named groups: year, optional block
CatalogueYears.from_labels(event_id, year, *, n_years, first_year=0, block=None)
YearSets.from_sampling_vect(event_id, sampling_vect, *, block=None)     # positions, as climada.util.yearsets returns them
YearSets.from_frequencies(impact_or_hazard, *, n_years, rng, block=None)
OutcomeSample.from_impact(index, impact, *, units, basis, scenario="baseline")
    .select(years_or_pool) -> OutcomeSample; .unit(unit_id) -> OutcomeSample
holdout(sample, *, train_fraction=0.7, rng=None) -> tuple[OutcomeSample, OutcomeSample]
year_block_kfold(sample, k, *, rng=None) -> tuple[tuple[OutcomeSample, OutcomeSample], ...]

# evaluation (K-18)
MetricOptions(betas=(0.9, 0.95, 0.99), return_periods=(2, 5, 10, 25, 50, 100, 250),
              loss_thresholds=(0.0,), payout_threshold=0.0, allocation=None)
evaluate(entry, sample, *, split, fold=0, pricing=PurePremium(), premium=None, options=MetricOptions()) -> DataFrame
compare(entries, sample, *, split, fold=0, pricing=PurePremium(), options=MetricOptions()) -> DataFrame
payout_impact(cover, sample) -> Impact
uncovered_impact(cover, sample) -> Impact
plot_payout(cover, unit_id=None, ax=None); plot_payout_vs_loss(cover, sample, ...); plot_exceedance(table_or_impact, ...)
setup_text(table) -> str

# calibration (K-19)
MSE(); ExpectedUncovered(); WeightedCVaR(alpha, beta); UserObjective(function, *, name, parameters=None)
PurePremium(); CostOfCapitalLoad(rate, q)
Budget(*, ratio=None, amount=None)
CalibrationOptions(fill="lowest", ranges=False, lp_method="auto", max_slsqp_amounts=1_000, max_cut_rounds=100,
                   max_grid_points=10_000, feasibility_tolerance=1e-7, time_limit=None)
calibrate(template, sample, objective, *, scope, pricing=PurePremium(), budget=None,
          options=CalibrationOptions()) -> CalibrationResult
calibrate_frontier(template, sample, objective, *, budgets, scope, pricing=PurePremium(),
                   options=CalibrationOptions()) -> DataFrame

# basis risk (K-20) and scenarios (K-21)
index_diagnostics(sample, *, threshold=0.99) -> DataFrame
impact_function_draws(impf_set, *, n_draws, scale, rng) -> tuple[ImpactFuncSet, ...]
OutcomeSample.from_impact_draws(index, impacts, *, units, basis, scenario="baseline")
ScenarioSet(members)      # label -> OutcomeSample, or a sequence of them (§9)
evaluate_scenarios(entry, scenarios, *, split, pricing=PurePremium(), options=MetricOptions()) -> DataFrame
calibrate_per_scenario(template, scenarios, objective, *, scope, pricing=PurePremium(), budget=None, options=...) -> dict
```

`scope` has no default. Every call says which it is, as `basis` does.

**Module layout** under `climada_petals/engine/parametric/`. One owner issue per file. Files with two owners are sequenced: the second starts after the first is merged.

| File | Content | Issue |
|---|---|---|
| `__init__.py` | The public names and `__all__` | K-14, then each issue adds its own names in sequence |
| `errors.py` | The hierarchy below | K-14; K-15 to K-19 add their subclasses in sequence |
| `_checks.py` | Argument checks | K-14 |
| `parameters.py` | `Free` | K-15 |
| `payout.py` | `PayoutFunction`, `LinearInAmounts`, the four families, `register_payout` | K-15 |
| `cover.py` | `ParametricCover`, `IndexDefinition`, `Limit` | K-15 |
| `units.py` | `InsuredUnits` | K-16; K-22 adds `from_subareas` |
| `index.py` | `ParametricIndex`, the footprint builders | K-16 (K-14 splits the file) |
| `index_tracks.py` | `from_cat_in_circle` and its track geometry | K-16 (K-14 splits it off) |
| `measure.py` | `OutcomeMeasure`, `EventBasis`, `CatalogueYears`, `YearSets` | K-17 |
| `sample.py` | `OutcomeSample`, `holdout`, `year_block_kfold` | K-17; K-20 adds `from_impact_draws` |
| `riskmeasures.py` | `var_cvar`, tail weights | K-18 |
| `pricing.py` | `PurePremium`, `CostOfCapitalLoad` | K-18 |
| `metrics.py` | `MetricOptions`, the metric kernels and column names | K-18 |
| `evaluate.py` | `evaluate`, `compare`, `payout_impact`, `uncovered_impact`, `setup_text` | K-18 |
| `plots.py` | `plot_*` | K-18 |
| `objectives.py` | The objectives | K-19 |
| `constraints.py` | `Budget` | K-19 |
| `solvers.py` | The LP and QP assembly and routes | K-19 |
| `calibrate.py` | `calibrate`, `calibrate_frontier`, `CalibrationOptions`, `CalibrationResult` | K-19 |
| `basis_risk.py` | `index_diagnostics`, `impact_function_draws` | K-20 |
| `scenarios.py` | `ScenarioSet`, `evaluate_scenarios`, `calibrate_per_scenario` | K-21 |
| `test/test_<module>.py` | One per module, with its owner | as the module |

Outside the package: `doc/climada_petals/climada_petals.engine.parametric.rst` and its toctree line (K-14, finished by K-23); `doc/tutorial/climada_engine_Parametric.ipynb` (K-04); `climada_petals/test/test_parametric.py`, the integration tests (K-23).

**Errors** (`errors.py`). `ParametricError` is the base.

| Error | Also a | Raised for |
|---|---|---|
| `ParametricInputError` | `ValueError` | The prototype's general class: an invalid argument |
| `CoverDefinitionError` | `ValueError` | An invalid payout, parameter or cover |
| `UnknownPayoutKindError` | `ValueError` | `from_json` on an unregistered `kind` |
| `UnresolvedParameterError` | `ValueError` | A template used where a resolved cover is needed |
| `UnitMappingError` | `ValueError` | An empty unit, a unit of zero value, a point in two units, a polygon set that doesn't cover the points it should |
| `EventAlignmentError` | `ValueError` | Index and `Impact` events that don't match on `event_id` |
| `ImpactInputError` | `ValueError` | No `imp_mat`, a `frequency_unit` other than `1/year`, exposures with `cover` or `deductible`, negative losses |
| `YearRouteError` | `ValueError` | An annual route that doesn't fit the events (§5.2) |
| `LeakageError` | `ValueError` | An evaluation sample that shares an event or a parent with its design sample |
| `CalibrationError` | `RuntimeError` | The base of the failures below; carries `problem_id`, `status` and the solver's message |
| `InfeasibleCalibrationError`, `UnboundedCalibrationError` | `RuntimeError` | The solver's own verdict |
| `CalibrationLimitError` | `RuntimeError` | A size limit or `time_limit` reached (§6.4) |
| `MissingDependencyError` | `ImportError` | An optional route whose package is missing |

There are no custom warning classes. Warnings go through the module's `LOGGER`, as `cat_bonds`' do. Every warning that changes how a number should be read is also a column in the table, so that it can't be lost in a log (§7, §8). A logged warning alone was how the date route failed in the prototype.

### 3. Covers and payout families

**A cover holds terms and nothing else.** It holds an index definition, one payout function per unit with its parameters, the payout's unit and the limit. It holds no events, years, frequencies or solver output. So one cover can be stored, compared and applied to another hazard set. A cover with a `Free` parameter is a template; `calibrate` returns a resolved cover, and `with_values` resolves one by hand. It round-trips through JSON (`to_dict`, `write_json`, `from_json`).

`definition_hash` is the SHA-256 of the canonical JSON, in the form `sha256:<hex>`. It identifies a cover in comparison tables. It doesn't change with `label`. It changes with the terms, the units or the limit. The module has no design id and no metadata layer, unlike ADR 0005 §7. CLIMADA has neither, and the setup columns (§7) carry what the publication rule needs.

**Families.** The definitions are ADR 0005 §3's, so a cover means the same thing in both modules. With s the severity (the index, or minus the index for `tail="lower"`):

| Family | Index-unit parameters | Amounts | Payout | Linear in |
|---|---|---|---|---|
| `LinearPayout` | attachment a, exhaustion e | limit ℓ | `ℓ · clip((s − a) / (e − a), 0, 1)` | ℓ |
| `StepPayout` | breakpoints b_0 < … < b_{n−1} | levels θ_0 … θ_{n−1} | θ_k for b_k ≤ s < b_{k+1}; θ_{n−1} for s ≥ b_{n−1}; 0 for s < b_0 | θ |
| `PiecewiseLinearPayout` | knots c_0 < … < c_{m−1} | levels y_0 … y_{m−1} | 0 for s < c_0; linear between the points; y_{m−1} for s ≥ c_{m−1} | y |
| `BinaryPayout` | trigger t | amount A | A for s ≥ t, else 0 | A |

- **Nothing is paid below the first threshold**, in every family. `below_attachment="first_bin"` is retired at K-15 (D8). So an event below the attachment at every unit adds nothing to any outcome.
- A value equal to a threshold belongs to the more severe side. Non-finite values raise. Index values are always converted to float first: `cat_bonds`' `calc_payout` truncates on an integer-typed index (K-12 Q8), and this one doesn't.
- `LinearPayout` equals `calc_payout` where the parameters coincide and the index is float (K-22 tests it).
- `StepPayout.uniform(attachment, exhaustion, n_steps)` is the prototype's construction, in which `limit` was the top step's right edge. It writes the breakpoints out and leaves the levels `Free` unless given. The word `limit` is kept for an amount (`Limit`, `LinearPayout`).

**The protocol.** `PayoutFunction` is vectorised over numpy arrays. `LinearInAmounts` is its opt-in extension for the exact routes: `amount_names()`, `basis(index) -> (n, n_amounts)`, and `amount_constraints(limit)`. A user family implements the first, and the second if it wants the LP and QP routes. `register_payout` lets `from_json` find it. A bare callable isn't a payout, because a cover needs a document.

**Parameters.** A float, or `Free(lower, upper, grid=...)`. Amounts have `lower ≥ 0` and may have `upper=None`. Shape parameters need finite bounds and a grid (§6.4).

**`Limit`.** The most one event pays at one unit, as a term of the cover. `Limit(amount)` states it, for all units or by unit. `Limit.largest_loss()` is the prototype's and the core's implicit rule, now stated: each unit's largest event loss on the design sample, written into the resolved cover as a number. With no `Limit`, the amounts are bounded by `upper` or by the budget alone. E[U] and weighted CVaR with neither a budget nor bounded amounts raise before solving, because any payout at least as large as the loss would be optimal.

### 4. Insured units and the index

**Units.** A unit is what gets one payout function: one exposure point, a group of points, or the whole set. An `InsuredUnits` holds the membership and the points' values.

- A point belongs to at most one unit. Points in no unit are counted and logged, and the loss doesn't include them. A unit with no point or with zero total value raises `UnitMappingError`.
- The loss per unit is `imp_mat` summed over the unit's points, sparse throughout.
- **A group's payout maps back to its points by value share**, `π_{e,i} = π_e · v_i / Σ_{k in unit} v_k`. So a payout `Impact` has the same exposure points as the loss `Impact`, and `eai_exp` and the plots work on it.
- `from_geometries` checks that every polygon holds points and reports the points left out, because `Subareas`' own check doesn't fire (C10). `MultiPolygon`s are accepted.

**The index.** A `ParametricIndex` is a dense array of one value per event and unit, with its `event_id`, `unit_id` and `IndexDefinition`. It holds no years and no frequencies.

| Builder | Index | Basis-risk source it brings (§8) |
|---|---|---|
| `from_hazard(hazard, units, index_stat="at_centroid")` | The intensity at the unit's assigned centroid. One-point units only | None, if the same hazard drives the loss |
| `from_hazard(..., index_stat="mean" or a percentile, weight=None or "value")` | The statistic over the unit's assigned centroids. `index_stat` follows `cat_bonds`: `"mean"`, or a number in `[0, 100]`; `"max"` is added. Only `"mean"` takes `weight` | The spread of the footprint over the group |
| `from_hazard(other_hazard, ...)` | Another source or resolution than the loss's hazard, matched with `matched_to(impact, on=...)` | The two hazards' difference |
| `from_cat_in_circle(tracks, units, hazard=, radius_km=)` | The category a track reaches within the radius, as in the prototype and Steinmann et al. 2023 | A coarse trigger with a spatial error |
| `from_table(table, units, definition=)` | A user's table keyed on `event_id` and unit: station readings, a satellite product, anything else | Whatever the table is |

**CLIMADA specifics**, each handled by a typed error or an explicit argument:

- **Alignment is on `event_id`**, never by position. A shuffled `Impact` works. `cat_bonds` aligns by position; this module doesn't.
- **Zero means no recorded intensity** (C1). For `tail="lower"`, `absent_value=` is required, so a drought index states what an absent reading means.
- **`frequency_unit`** must be `1/year`; otherwise `ImpactInputError`.
- **`Impact` without `imp_mat`** raises and names `save_mat=True`.
- **Exposures with `cover` or `deductible`:** their `Impact` is already net of an indemnity layer. The module raises `ImpactInputError`, and the caller drops the columns to go on.
- **Two exposure points at one location** break `Centroids.from_exposures` with `TropCyclone.from_tracks` (K-12 Q1): the matrix gets a column index of −1. `InsuredUnits` raises `UnitMappingError` if a point's assigned centroid is out of range, and the docs say to de-duplicate the centroids.

### 5. Outcomes: the event basis, the annual basis and splits

An `OutcomeSample` joins an index, a loss per event and unit, and a basis. The basis says what an outcome is. It is a required argument.

#### 5.1 The measure

`OutcomeMeasure` holds a sparse matrix `G` of shape (n_outcomes, n_events), with the count of event e in outcome o, and the outcome weights. It replaces the prototype's one outcome per event: on the `yearsets` route an event can occur twice in a year, and in several years. A per-event quantity x gives the outcome value `G @ x`. Everything downstream reads this one object.

Inside an outcome, the uncovered loss is the sum over its events, `U_o = Σ_e G_oe (L_e − π_e)^+`. Each event pays against its own loss, so an over-payment in one event doesn't offset a shortfall in another of the same year. The residual `R_o = L_o − π_o` is summed before it is squared, as in the core.

**`EventBasis()`.** One outcome per event, with weight f_e, the event's frequency per year. This basis always works, because nothing requires the frequencies to sum to at most 1 (C4).

- E[X] = Σ_e f_e X_e is an expected value per year. E[L] is `Impact.aai_agg` restricted to the units.
- **1 − β is read as a frequency per year.** `VaR_β(X)` is the smallest x with `Σ_{X_e > x} f_e ≤ 1 − β`, which is CLIMADA's event exceedance curve at the return period T = 1/(1 − β), up to that curve's interpolation. `CVaR_β(X)` is the mean of the worst 1 − β of frequency. If the frequencies sum to less than 1 − β, the missing mass counts as zero.
- In the Rockafellar–Uryasev form this is the same LP with f_e in place of p_e, and ζ ≥ 0.

Dividing by Σf instead would make β depend on which loss-free events a file holds, and the tropical-cyclone files hold every storm of the global set (K-12 Q2). With frequencies as weights, loss-free events below the attachment change nothing. Where the frequencies sum to at most 1, this is the same measure as the prototype's and the core's `event` basis. A spot check confirmed all three points (Not verified, at the end).

#### 5.2 The annual basis takes a stated route

One outcome per simulated year. The weight of a year is 1/N. There is no default route: no single route fits every hazard (K-12 Q3), and the route changes tail numbers. On Jamaica `random_walk`, K-12's proxy of the 99th annual percentile is 193 on catalogue years and 218 on `yearsets`. So the route is part of the setup of every number.

| | `CatalogueYears` | `YearSets` |
|---|---|---|
| A year is | A label on each event | A draw of Poisson(λ) events from the set |
| Constructors | `from_dates`, `from_event_names`, `from_labels` | `from_sampling_vect`, `from_frequencies` |
| Frequencies | Each kept event must have frequency 1/N | Any, so climate-scaled frequencies work |
| Empty years | As the catalogue has them | Sampled |
| Noise | None beyond the catalogue's | Sampling error, stated by `n_years` and the seed |

**`CatalogueYears`.** It raises `YearRouteError` when:

- the labels and the frequencies disagree: `frequency × N` differs from 1 by more than 1e-6 on an event the sample keeps. Windstorm raises here (74 seasons in the dates, 73 from the frequency, K-12 Q3), and any `apply_climate_scenario_knu` set does too;
- `from_dates` gets dates that don't carry the years: the span of the hazard's dates, in years, is not the N that the frequency implies. This is the prototype's silent collapse, now an error (STORM's span is 1 year, flood's 20, against N of 10,000 and 920). `n_years=` states N where a catalogue's span is known to differ, as with a season that crosses New Year;
- `from_event_names` meets a name that doesn't match its `pattern`.

"An event the sample keeps" is an event with a loss or a non-zero index at some unit, so the check runs when the sample is built. The `random_walk` files have other frequencies only on events that never reach the country (K-12 Q3), so a check on the whole file would refuse them for no reason. Events left out are counted and recorded, not dropped silently.

STORM's labels and ensembles use `from_labels`, or `from_event_names` with a pattern. The tutorial shows the recipes; they are not hazard-specific code in the module.

**`YearSets`.**

- `from_frequencies` always samples **with replacement**. CLIMADA's default is without, which draws the rarest decile 6 to 7 times too often from 2,000 sampled years on (K-12 Q4, synthetic, non-uniform frequencies).
- It draws the counts with the caller's `Generator` and passes it to `sample_events`, so numpy's global state is never touched (K-12 Q4).
- **`correction_fac` is not applied.** It forces the mean to the input's expected annual impact with one factor for every year, and doesn't repair the tail (K-12 Q4). The factor that would apply is recorded.
- `from_sampling_vect` takes positions, as the function returns them (C5).
- The module works from `sampling_vect` at event level, because `impact_yearset_from_sampling_vect` gives annual totals only. The same `sampling_vect` applies to a payout `Impact`.
- Events with no loss and no non-zero index can be left out before sampling. Sampling all events and then dropping those is the same as sampling the rest at its own λ (Poisson thinning), and it makes the sample much smaller on files that hold every storm of the globe.

**Which route for which hazard** is guidance in the docs, not code. It follows K-12's observations on one country per hazard:

| Hazard, as in K-12's files | Route the docs suggest | Why |
|---|---|---|
| STORM | Catalogue, labelled `k × 1000 + y` from the names | The 10,000 simulated years are the data; `date` holds no year |
| Flood, wildfire | Catalogue | One event per year or member-year; `yearsets` gives 36.9 % of years empty against none |
| Earthquake, observed tropical cyclones | Catalogue from `date` | Real calendar years; a short record (§5.4) |
| `random_walk` (present and future) | `YearSets` on the whole file; or catalogue on the events that reach the country, with the parent's year as `block` | Members aren't independent years; future files have frequencies that differ between members |
| Windstorm | `YearSets` | The catalogue doesn't run as labelled |
| A set scaled by `apply_climate_scenario_knu` | `YearSets` | Frequencies no longer equal 1/N |

#### 5.3 Splits with no leakage

`holdout` and `year_block_kfold` split by the unit that must stay together, and record what they did.

| Basis and route | What is split | Rule |
|---|---|---|
| `CatalogueYears`, no ensemble | Contiguous blocks of years | The first 70 % calibrate, as in the core |
| `CatalogueYears`, ensemble | The `block` label: the parent's calendar year | All members follow their parent |
| `YearSets` | Pools of parents, or of events with no parents given; years are sampled in each pool | Needs `rng`. A pool's frequencies are divided by its share, so both sides keep λ |
| `EventBasis` | Pools, as above | Needs `rng`. Frequencies rescaled as above |

K-12 Q3 and Q4 show why: with ensemble labels 85.7 % of the test events with wind have their parent in the training years for `random_walk` and 100 % for windstorm, and splitting sampled years leaves 99.3 % of test draws on events that also train. `evaluate` raises `LeakageError` when an out-of-sample split shares an event or a parent with the design sample.

**Draws.** `OutcomeSample` has a draws dimension, reserved for K-20: one row per event and draw, each with frequency f_e / n_draws (the core's rate convention), each draw of an event in the same `block`.

#### 5.4 Short records

A short record leaves the upper amounts unidentified: a step that no event reaches changes nothing on the sample, whatever its level. In CLIMADA this is ordinary: the observed Jamaica file has 13 events with wind in 41 years, and wildfire has 20 years (K-12 Q2). The design reports it (`unidentified`, §6.5), and an evaluation reports how much of a sample lands there (`unidentified_share`, §7). The tutorial shows it (§14, K-04).

### 6. Calibration

`calibrate(template, sample, objective, *, scope, pricing, budget, options)` chooses the free parameters of a template on a design sample.

#### 6.1 The calibration scope

The scope says which units share a design problem. It is a required argument, next to the objective.

- **`scope="individual"`.** One design problem per unit, with its own objective on its own loss and payout, and its own budget, `P_j ≤ κ·E[L_j]`.
- **`scope="joint"`.** One design problem for one risk owner. Each unit keeps its own index and its own payout function, and pays by its own terms. The objective is on the owner's total per event, L_e = Σ_j L_{e,j} and π_e = Σ_j π_{e,j}, under one budget on the total premium. Within an event, an over-payment at one unit can offset a shortfall at another.
- **The combination** is the weighted-CVaR objective with `scope="joint"`, a tail objective on the owner's total uncovered loss. It is first-class (Marc, 2026-11-01). Nothing in the API treats it as a special case.

These are methods. What each optimises is stated in the docs. Nothing in the module says which scope gives better cover. Event sets keep the dependence between units, so joint calibration needs no dependence model here, which is why it belongs in Phase 1 (D12).

The joint LP and QP are the individual ones with the block basis B = [B_1 | … | B_m]. Thresholds are fixed in a joint design (D9). A `Budget(ratio=κ)` means P ≤ κ·E[L] per problem, so at equal κ and under the pure premium both scopes spend the same total. In the individual scope, `Budget(amount=B)` takes a mapping by unit.

Cluster scope is K-31, and `scope` can take a richer value then without a break.

#### 6.2 Objectives

With outcome weights p_o, and U_o and R_o from §5.1:

- `MSE()`: `Σ_o p_o R_o²`.
- `ExpectedUncovered()`: `E[U] = Σ_o p_o U_o`.
- `WeightedCVaR(alpha, beta)`: `α · CVaR_β(U) + (1 − α) · E[U]`, in the Rockafellar–Uryasev form. Here α weights the CVaR term, β is the tail level, and this mixture is not a CVaR with weights on the outcomes. On the event basis, §5.1 says what β means.
- `UserObjective(function, *, name, parameters=None)`: `function(loss, payout, weight) -> float` on outcome arrays. It is evaluated, not compiled, so it takes the grid route.

#### 6.3 Pricing and constraints

- `PurePremium()`: `P = E[π]`. `CostOfCapitalLoad(rate, q)`: `P = (1 − r)·E[π] + r·CVaR_q(π)`.
- `Budget(ratio=κ)`: P ≤ κ·E[L]. `Budget(amount=B)`: P ≤ B. Exactly one of the two, on the design sample.
- The limit is a term of the cover (§3). A family's own constraints are amounts ≥ 0 and monotone levels if `monotone=True`.

#### 6.4 Solver routes

| Payout | Free shape parameters | Objective | Pricing | Route |
|---|---|---|---|---|
| `LinearInAmounts` | none | E[U], weighted CVaR | any | One LP: `scipy.optimize.linprog` |
| `LinearInAmounts` | none | MSE | pure | One QP on the amounts, solved with `SLSQP` |
| `LinearInAmounts` | none | MSE | cost of capital | The same, with the premium held by cutting planes |
| `LinearInAmounts` | some | any built-in | any | A grid over the shape candidates, with the LP or QP above at each point. Individual scope only |
| Any other payout, or a `UserObjective` | any | any | any | A grid over every free parameter, evaluated in numpy. Individual scope only. Labelled `route="grid"` |

**The LP method.** `CalibrationOptions(lp_method="auto")` uses `highs` for a problem with one unit and `highs-ipm` for a problem with several. `"highs"` and `"highs-ipm"` can be stated (D17). The method used is recorded. `time_limit` passes through to HiGHS, and reaching it raises `CalibrationLimitError`, so a stalled solve ends with a typed error.

**MSE without a new package.** The problem is `min Σ_o p_o (L_o − B_o θ)²` over the amounts, under bounds, monotonicity and the budget. It has as many variables as amounts, so `SLSQP` works on it directly, with analytic derivatives.

- `SLSQP` matches cvxpy to about 1e-11 on 5 and 335 amounts (K-12 Q6), and to 5e-10 on 1,000 (spot check, below). Its cost grows about with the cube of the amounts: about 1 s at 335 (K-12), 222 s at 1,000 (spot check), not done in 600 s at 5,000 (K-12). So `max_slsqp_amounts=1_000` is a stated limit. Above it, `CalibrationLimitError` names the option. Individual designs are far below it.
- Under a cost-of-capital load the premium is the largest of finitely many linear functions of the amounts. Each round solves the QP with the cuts so far and adds the linear piece at the solution, until the premium meets the budget within `feasibility_tolerance`. It needs no auxiliaries, so the QP stays small. `max_cut_rounds=100` is a stated limit, and reaching it raises `CalibrationLimitError`. In the spot check it matched cvxpy to about 1e-10 at 5 and at 70 amounts, in under a second. At 335 amounts it hadn't met the tolerance after 100 rounds and 449 s, so a loaded MSE on a large joint design raises.

If the maintainers accept one new package, `highspy` or cvxpy can go behind `solvers.py`, with no change in the API (D10, Q2).

**Grid.** Candidates are the Cartesian product of the shape parameters' grids, restricted to ordered thresholds, capped by `max_grid_points` (above it, `CalibrationLimitError`). The best candidate wins; ties within the tolerance go to the first in lexicographic order and are counted. The objective at every candidate is kept (`profile`).

**Size.** Losses are held sparse. Loss-free events get no shortfall variable, as in the prototype: an event without loss has no shortfall for any payout. Losses and payouts are divided by the largest event loss of the problem before solving, and results are in loss units.

**No silent failures.** After a solve, numpy recomputes the objective, the premium, the budget and every constraint from the returned parameters, with relative tolerance 1e-7. A violation, or a solver status other than optimal, raises. There is no fallback to other thresholds, as `cat_bonds` has after a failed fit (`_fallback_thresholds`).

#### 6.5 Non-uniqueness and degenerate tails

The module reports non-uniqueness, as ADR 0005 §5.4 defines it.

- **Unidentified amounts.** An amount that no calibration outcome reaches changes nothing on the sample. `CalibrationResult.unidentified` lists them, and a stated rule sets them: `fill="lowest"`, the default, or `fill="highest"`.
- **Ranges on the LP route** (`ranges=True`): four LPs per amount, the two-tolerance test of ADR 0005 §5.4, `unique` and `ranges`.
- **MSE route:** `unique` comes from the smallest eigenvalue of the Hessian restricted to the identified amounts.
- **Joint designs.** The joint objective sees only each event's total payout, so other splits across the units are often optimal too. A joint design holds the one split the solver returned, unless `unique` is true. Tables mark this (§7).
- **Degenerate tails.** `degenerate_tail = "expected_uncovered"` when the tail covers all the loss: β ≤ P(L = 0) on an annual route, 1 − β ≥ Σ_{L_e > 0} f_e on the event basis. `"single_outcome"` when (1 − β) is at most the smallest outcome weight. Recorded, not raised.

#### 6.6 The result, and the budget frontier

`CalibrationResult` holds: the resolved `cover`; the template's hash; the objective's document and value; `premium`, `expected_loss`, the budget's use; `scope`; one `CoverProblem` per design problem with its `route`, solver name, version, status, method and time; `unidentified`, `fill`, `unique`, `ties`, `ranges`, `degenerate_tail`, `profile`; the basis and route; and the design sample's size. `summary()` and `parameters_frame()` return it as tables. The prototype's `levels_frame()` becomes `parameters_frame()`, which also holds non-step parameters.

**`calibrate_frontier(template, sample, objective, *, budgets, scope, ...)`** runs one calibration per budget and returns one table, one design per budget. It is a measurement: "what does another unit of premium buy in tail protection?" The table has no "best" point. It carries the same columns as a `CalibrationResult.summary()`, and per budget the cover's parameters.

### 7. Evaluation and comparison

`evaluate` and `compare` take any cover, designed or given, on any sample. They return pandas tables: one row per entry, level and split, with the metrics as columns. They use ADR 0005 §6's definitions, with the event-level detail of §5.1.

**The premium used.** It is `premium=` if given; for a design, the design premium, which is the contract price; otherwise the premium on the evaluation sample. The row says which (`premium_basis`). `premium_repriced` sits beside it, the same pricing applied on the evaluation sample, so a row under another scenario shows both.

**VaR and CVaR.** `VaR_β(X)` is the smallest x with cumulative weight at least β, allowing 1e-10 for rounding, so a β on a step gives the lower atom on every platform. On the event basis, §5.1 gives the same in frequency terms.

| Column | Definition | On the event basis |
|---|---|---|
| `expected_loss`, `expected_payout`, `expected_uncovered`, `premium`, `premium_repriced` | E[L], E[π], E[U], P | Per year: `expected_loss` is `aai_agg` on the units |
| `coverage_ratio` | `E[min(π, L)] / E[L] = 1 − E[U] / E[L]` | The same |
| `payout_to_loss_ratio` | `E[π] / E[L]` | The same |
| `tail_coverage_b<β>` | `Σ w^β (L − U) / Σ w^β L`, on the worst 1 − β of the loss | Worst 1 − β of frequency |
| `cvar_uncovered_to_loss_b<β>` | `CVaR_β(U) / CVaR_β(L)` | §5.1 |
| `payout_frequency` | `P(π > ε)` | Paying events per year, Σ f_e 1[π_e > ε] |
| `unidentified_share` | The weight of outcomes where the design's amounts were set by the fill rule: on an annual route, the probability of a year with at least one event on a filled amount | Such events per year. Null for a cover given as is |
| `false_negative_rate_l<ℓ>` | `P(π ≤ ε, L > ℓ) / P(L > ℓ)` | Ratio of frequencies |
| `false_positive_rate_l<ℓ>` | `P(π > ε, L ≤ ℓ) / P(L ≤ ℓ)` | Ratio of frequencies. Its denominator holds the loss-free events the file keeps, so the docstring warns that it depends on them |
| `rmse` | `sqrt(E[R²])` | Per event |
| `correlation` | Weighted Pearson of L and π | The same |
| `var_uncovered_b<β>`, `cvar_uncovered_b<β>` | VaR_β(U), CVaR_β(U) | §5.1 |
| `var_net_loss_b<β>`, `cvar_net_loss_b<β>` | Of N = L − π + P, the owner's cost of the outcome | Null: the premium is annual, an event isn't |
| `var_loss_b<β>`, `cvar_loss_b<β>` | Of L | §5.1 |
| `loss_rp<T>`, `payout_rp<T>`, `uncovered_rp<T>`, `net_loss_rp<T>` | The value exceeded with probability 1/T | With frequency 1/T; `net_loss_rp` null |

Thresholds are always stated in `MetricOptions`. Labels follow ADR 0005: `cvar_uncovered_b0_99`, `loss_rp100`, `false_negative_rate_l0`.

**In and out of sample.** Every row says `split` and `fold`. External numbers come from out-of-sample rows on the annual basis (publication rule). In-sample rows exist for the overfitting gap.

**Rows and levels.**

| Column | Meaning |
|---|---|
| `cover_label`, `cover_hash` | The user's label, and §3's hash |
| `scope` | `"individual"` or `"joint"`, or null for a cover given as is |
| `level`, `unit_id` | `"unit"`, or `"total"` with null `unit_id`; `"unit_by_value"`, `"unit_by_loss"` (below) |
| `scenario` | `"baseline"` unless stated |
| `basis`, `route`, `n_years` | `"event"` or `"annual"`; `"frequency"`, `"catalogue"` or `"yearsets"`; the years, null on the event basis |
| `index_definition` | One line: source, statistic, unit |
| `pricing`, `premium_basis` | The pricing's name and parameters; `"stated"`, `"design"` or `"evaluation"` |
| `split`, `fold` | `"in_sample"` or `"out_of_sample"`; the fold |
| `unique`, `ties`, `degenerate_tail` | From the design; null for a cover given as is |
| `comonotone_index` | §8 |
| one column per metric | Null where the table above says |

Setup is in columns, not in `DataFrame.attrs`, so it survives a `concat` or a filter. `setup_text(table)` renders it as the sentence a notebook prints next to a number.

**Joint designs.** A joint design has one `"total"` row. It has per-unit rows only under a stated evaluation-time allocation, `MetricOptions(allocation="value")` or `"loss"`: `"unit_by_value"` or `"unit_by_loss"`, with no premium and no net-loss columns. The rule is in `level`, so no row can be read as the solver's split (the rule of ADR 0005, Amendment 3). A set of individual covers has one `"unit"` row per unit and one `"total"` row, whose premium is the sum of the contract premiums. The `scope` column keeps the two apart and makes no statement about them.

**CLIMADA objects.**

- `payout_impact(cover, sample)` returns the payouts as an `Impact`, on the exposure points of the loss `Impact` (§4), with its events, frequencies and dates.
- `uncovered_impact(cover, sample)` returns `(L_e − π_e)^+` per event and point, the same way. At group level, the shortfall of a unit maps back by value share.
- `calc_freq_curve`, `eai_exp`, `local_exceedance_impact` and `write_hdf5` work on both, unchanged. Both are non-negative, which is what those tools expect (C6).
- A signed net loss is not offered as an `Impact`: `local_exceedance_impact` would drop its negative part, and the premium is annual, so it has no place in an event. The net-loss metrics are in the table.
- On an annual route, the same `sampling_vect` gives a payout's annual totals through CLIMADA's own functions.

Plots follow `plot_*`, return axes and never call `plt.show()`.

### 8. Basis risk

With a centroid index, one exposure point and one impact function, CLIMADA's loss is an exact function of the index, and a design can replicate it. That would mislead a reader of the numbers. In K-12 Q7, on one synthetic site near Miami (one unit, individual scope, annual basis, the last 900 of 3,000 simulated years out of sample, pure premium, budget 1.0, objective E[U], step payout uniform on 25 to 85 m/s, K steps), `E[U] / E[L]` is:

| Setup | Spearman(index, loss) | K = 5 | K = 20 | K = 80 |
|---|---|---|---|---|
| One point, centroid wind, one impact function | 1.000 | 14.1 % | 5.0 % | 1.2 % |
| 25 points on a 0.1° grid, wind at the centre | 0.999 | 13.6 % | 4.3 % | 1.8 % |
| 25 points on a 0.5° grid, mean wind of the points | 0.956 | 6.0 % | 3.7 % | 3.3 % |
| One point, `v_half` drawn per event | 0.921 | 29.3 % | 25.6 % | 25.7 % |
| Cat-in-a-circle at 50 km, wind within it | 0.637 | 46.3 % | 46.3 % | 46.3 % |

A share that falls with K is what no basis risk looks like. Three things follow.

**Structural sources lead.** CLIMADA's natural basis risk is that the index and the loss are different things: an index from another hazard set or resolution, a statistic over a group, a track-based trigger, a user's station table. §4's builders are where that is stated, and `IndexDefinition` records it in every row of every table. The docs lead with these.

**The unit's size doesn't settle it.** A 0.1° group behaves like one point in the table above. So the module measures the relation between index and loss, and doesn't infer it from the setup.

`index_diagnostics(sample, threshold=0.99)` returns, per unit, the frequency-weighted Spearman correlation of index and loss over the events with a loss or a non-zero index, the flag `comonotone_index`, and the share of E[L] on events with a zero index (41 % for the cat-in-a-circle rows above). `calibrate` and `evaluate` run it. A flagged unit logs a warning and sets the `comonotone_index` column, so a reader of a table sees it. The threshold is a stated default from one synthetic site: 0.999 behaved like one point, 0.956 did not.

**Impact-function draws come second, with their limit stated.** Several `Impact`s, one per draw of the `ImpactFuncSet`, go in on the draws dimension of §5.3, in calibration and in evaluation. They widen the uncovered loss, as the `v_half` row shows. But noise on the impact can't change whether an event pays, and it can't change whether a loss occurs unless the draws move the impact function's threshold. So where the index equals the hazard, the false-negative and false-positive rates at ℓ = 0 don't move (the design review, MAR-344, measured this on the CRC module). The docs say so next to the helper. `unsequa` is Phase 2 (K-33).

**No required model.** ADR 0005 requires a stated basis-risk model because a CRC sample has no second source of information. Here the index builder is the statement. A required argument would add a word with no information in it, and the degenerate case is caught by measurement rather than by a promise.

A synthetic noise layer on the index is not in Phase 1. The CRC module needs one, because it reads one hexagon. A CLIMADA user can build the index from another hazard, resolution or unit, or bring a table. If the maintainers or Marc want it, it is a small addition to `basis_risk.py`.

### 9. Scenarios

In CLIMADA a scenario is another `Hazard` and possibly other `Exposures`. So a fixed cover is portable by construction (§3), and this belongs in Phase 1.

- **`ParametricIndex.from_definition(definition, hazard, units, tracks=None)`** rebuilds a cover's index on another hazard set. Nothing in a cover depends on event ids.
- **`ScenarioSet`** maps labels to samples. `evaluate_scenarios` evaluates a fixed cover on each, and fills the `scenario` column. `calibrate_per_scenario` runs K-19 on each.
- **The route must be the same across a comparison,** or it raises. `apply_climate_scenario_knu` changes frequencies only, so it needs the event basis or `YearSets` (§5.2). Other `Exposures` change the units' values, so a value-weighted index and the value shares follow the exposures given; `units` records them. Freezing the weights at inception, as a contract would, is an open point for K-21.

**One horizon of one product can be noisy** (the design review, MAR-344, found this on the CRC module's curves). On CLIMADA's objects:

- **Several samples under one label form one scenario**, an equal-weight mixture. `ScenarioSet({"rcp45, 2040 to 2080": [s_2040, s_2060, s_2080]})`. On the event basis each member's frequencies are divided by m; on an annual route each member's years get weight 1/(m·N_i). It adds no concept beyond a sequence in place of a sample. The members must have the same units.
- **The docs and the tutorial lead with windows or members**, not with one file. The Data API offers them: `random_walk` for Jamaica at `ref_year` 2040, 2060 and 2080 (rcp 2.6, 4.5, 6.0; 2040 and 2060 at rcp 8.5), and STORM rcp 8.5 per GCM, four of them (listing read on 2026-11-09).
- **A frequency-scaled set keeps the events,** so its difference from the baseline holds no sampling noise on the event basis.
- **The `yearsets` route adds its own noise.** In K-12 Q4 (synthetic, non-uniform frequencies, 200 replicates, with replacement) the error of the annual CVaR at 99 % has an RMSE of about 16 % at 1,000 sampled years and 6 % at 10,000. So the docs ask for at least 10,000 sampled years on that route, and every scenario row records `n_years`. Robust design and CLIMADA's `trajectory` module are Phase 2 (K-32).

### 10. Working with `cat_bonds`

The two are complementary (accepted 2026-10-31). `cat_bonds` designs bonds for a sovereign: one linear payout per subarea, squared error, COBYLA, pooling and bond pricing. This module designs covers for one risk owner, for any payout family and goal.

- **`InsuredUnits.from_subareas(subareas, exposures)`** (K-22) makes units from `Subareas`, through a spatial join, since `Subareas` holds no point-to-subarea column. Its own coverage check doesn't fire (C10), so the module checks coverage itself. `subarea_letter` is used as a label only, and stays unique past 26 subareas.
- **A check that the two agree:** `LinearPayout` equals `calc_payout` for the same triggers and maximum payout, on float input (K-12 Q8).
- **A check on design:** an MSE design with `LinearPayout` on a subarea, on a stated grid of triggers, reaches `cat_bonds`' COBYLA objective on the same data within a stated tolerance, or improves on it (K-22).
- **Terms.** A short section of the docs puts the two vocabularies side by side (§1).
- **Nothing inside `climada_petals/engine/cat_bonds/` is edited.** What we noticed there is a note for the maintainers (§15). The bridge to bond simulation is K-35.

### 11. Porting map from the prototype

K-14 moves the prototype with its behaviour unchanged. The table says what later issues then do to it.

| Prototype | In the module | Fate | Issue |
|---|---|---|---|
| `ParametricCover` (levels, problems, years) | `ParametricCover` (terms) and `CalibrationResult` (record) | **Split** | K-15, K-19 |
| `CoverProblem`, `summary()` | `CoverProblem`, `summary()`, with the route and the method added | Kept | K-19 |
| `levels_frame()` | `parameters_frame()` | Renamed, for any family | K-19 |
| `ParametricCover.payout_matrix` | The same | Kept | K-15 |
| `ParametricCover.payout_impact(index, impact)` | `payout_impact(cover, sample)` | A function now, in K-18's file | K-18 |
| `ParametricIndex` with `event_year`, `years`, `frequency`, `date` | `ParametricIndex` without any of them | **Years move out** to `CatalogueYears` | K-16, K-17 |
| `from_hazard(hazard, exposures, ...)` | `from_hazard(hazard, units, index_stat=..., weight=...)` | Generalised | K-16 |
| `from_cat_in_circle`, `SAFFIR_SIMPSON_KN`, the track geometry | The same, in `index_tracks.py` | Kept, moved | K-14, K-16 |
| `event_year="date"` as the default route | `CatalogueYears.from_dates`, which raises on a collapse | **Default retired** | K-17 |
| `split_years` | `holdout`, `year_block_kfold` | Renamed, generalised | K-17 |
| `OutcomeMeasure(outcome_of_event, probability, n_years)` | `OutcomeMeasure(G, weights)` | Generalised | K-17 |
| `basis="annual"` or `"event"` | `CatalogueYears`, `YearSets`, `EventBasis` | Replaced by objects | K-17 |
| The event basis's Σf ≤ 1 | Frequencies as weights | **Check retired** | K-17 |
| `StepPayout(attachment, limit, n_steps, breakpoints, below_attachment)` | `StepPayout(breakpoints, levels, ...)` and `StepPayout.uniform(...)` | Reshaped | K-15 |
| `below_attachment="first_bin"` | None | **Retired** at K-15 | K-15 |
| `MeanSquaredError` | `MSE` | Renamed | K-19 |
| `ExpectedUncovered`, `WeightedCVaR` | The same | Kept | K-19 |
| `PurePremium`, `CostOfCapitalLoad` | The same | Kept | K-18 |
| `budget=κ` | `Budget(ratio=κ)` or `Budget(amount=B)` | Reshaped | K-19 |
| The implicit cap at the largest loss | `Limit.largest_loss()`, stated | Made explicit | K-15, K-19 |
| `scope="portfolio"` | `scope="joint"` | **Renamed** (§1) | K-19 |
| `solve_design`, `_LinearProgram`, the LP assembly | The same, on `LinearInAmounts` | Generalised | K-19 |
| `_solve_qp` (cvxpy and Clarabel) | `SLSQP` and cuts | **Retired** | K-19 |
| `MissingDependencyError` | Kept for later optional routes | Kept | K-14 |
| `calibrate(index, impact, payout=, objective=, basis=, scope=, pricing=, budget=, years=)` | `calibrate(template, sample, objective, *, scope, pricing, budget, options)` | Reshaped to `max-args=7` | K-19 |
| `basis_risk(index, impact, cover, ...)` | `evaluate`, `compare` | Replaced | K-18 |
| `rmse_residual` | `rmse` | Renamed, as in ADR 0005 | K-18 |
| `var_cvar`, `_checks` | The same | Kept | K-14, K-18 |
| `errors.py` | The table of §2 | Extended | K-14 onward |
| `README.md` | The seed of the tutorial and the API page | Absorbed | K-04, K-23 |
| `ruff.toml` | None; it is this repository's isolation rule | Not moved | K-14 |
| `test/` | `unittest` classes, adapted | Kept | K-14 onward |

The prototype in this repository is frozen after K-14. Its isolation rule stays.

### 12. Test strategy and the parity contract

**Layers.**

| Layer | What it holds | Where | Issue |
|---|---|---|---|
| Unit | Every module; `unittest` classes, offline, at most 2 s each. Each statistic and error path by hand; shuffled events | `engine/parametric/test/` | K-14 to K-22 |
| Golden | K-13's cases against the thesis-faithful core | `engine/parametric/test/data/` (copied), tests in the owners' files | K-13, K-18, K-19 |
| Closed form | What the core lacks: linear, piecewise linear and binary payouts; the event basis with Σf above 1; `yearsets` against a hand-worked `sampling_vect` | The same | K-13, K-17, K-19 |
| Properties | Loss-free events below the attachment change nothing, on both bases. A uniform-frequency catalogue and the same set as a `sampling_vect` give identical outcomes. Numpy's global random state doesn't move. K-19's feasibility property of the solver: the individual designs, taken together, are a feasible point of the joint problem. It checks the solver and says nothing about cover quality | The same | K-17, K-19 |
| CLIMADA round trip | An `Impact` from a cover passes `calc_freq_curve` and a `write_hdf5` round trip | The same | K-18 |
| Cross-module | `LinearPayout` against `calc_payout`, on floats; an MSE design against COBYLA | The same | K-22 |
| Integration | `Hazard`, `Exposures`, `ImpactCalc`, `calibrate`, `evaluate`, `compare` end to end, for two hazard types, on small synthetic objects | `climada_petals/test/` | K-23 |
| Merge gate | black, isort, pylint under petals' `.pylintrc`, 100 % line coverage of new code | K-11's commands | every issue |

**The parity contract (K-13).** The fork's tests never import the core. The fixtures live in this repository under `parity/climada/`, and K-18 and K-19 copy them into the fork's test data.

```text
parity/climada/
  README.md                  # format, licence, how to compare
  samples/<name>.json        # event_id, frequency, year (or null), parent (or null), unit_id,
                             # index [n_events × n_units], loss [n_events × n_units], index_unit, loss_unit
  cases/<case_id>.json       # one case each; names a sample by file
```

A sample is shared between cases, which is how the set stays small. One case:

```text
{"case_id": "step-wcvar-b0_99-pure-annual-joint-s1",
 "kind": "design",                       # or "evaluate"
 "source": "core",                       # or "closed_form"
 "sample": "samples/s1.json",
 "basis": {"kind": "annual", "route": "catalogue", "n_years": 30},    # or {"kind": "event"}
 "scope": "joint",                       # or "individual"
 "cover": <the cover document of §3>,    # a template, or a resolved cover if "evaluate"
 "objective": {"kind": "weighted_cvar", "alpha": 0.9, "beta": 0.99},
 "pricing": {"kind": "pure"},            # or {"kind": "cost_of_capital", "rate": 0.06, "q": 0.99}
 "budget": {"ratio": 0.8},
 "limit": {"rule": "largest_loss"},
 "expected": {"objective_value": ..., "premium": ...,
              "parameters": {"u1": {"levels[0]": ..., ...}, ...},
              "unidentified": {"u1": [...], ...},
              "unique": true,
              "metrics": {"expected_uncovered": ..., "var_uncovered_b0_9": {"either": [lower, upper]}, ...}},
 "compare_parameters": "exact",          # or "within_ranges" or "none"
 "tolerances": {"objective_value": 1e-6, "premium": 1e-6, "metrics": 1e-6, "parameters": 1e-6},
 "generator": {"script": "parity/scripts/export_climada_fixtures.py", "core_version": "...", "commit": "..."}}
```

- **Cases.** From the core: a step payout × {MSE, E[U], weighted CVaR} × {event basis, annual basis} × {individual, joint} × {pure premium, cost-of-capital load}, at `below_attachment="zero"`. The core's event basis needs frequencies that sum to at most 1, so those cases' samples do. Closed form: the three other families, and the event basis with Σf above 1.
- **Size.** At most 200 KB for the whole set, enforced by a test. Petals accepts only small test files, and the CRC fixtures are about 1 MB.
- **Licence.** Synthetic samples only, CC0-1.0, so the copies in a GPL v3 repository carry no attribution duty. Recorded in `parity/README.md` and `docs/data-sources.md`.
- **Tolerances, once.** Objective values, premiums and metrics agree within `1e-6` relative. A quantile on a step is written `{"either": [lower, upper]}`, and CVaR is a single value. Parameters agree within `1e-6` of the scale, absolute.
- **How a design case compares.** As ADR 0005 §8: the objective value always; then the parameters as `compare_parameters` says, leaving out unidentified amounts; premium and metrics on the module's design where `unique` is true, otherwise on the template resolved with `expected.parameters`.
- **Prototype.** A one-off run of `packages/climada/tests/test_petals_parametric_parity.py` against the port at K-14, at unchanged tolerances, and a last parity run at K-23.

The generator uses `parametric_insurance_design` alone. It may reuse the MAR-245 generator, which is our own BSD code, and nothing from crc-sdk.

### 13. Phase 2 extension points

Phase 1 exports only what it implements. Adding a name isn't breaking.

| Issue | What it adds | Where it plugs in |
|---|---|---|
| K-30, multi-hazard | Composite indices and payouts over several indices (a sum or maximum of single-index payouts; a two-dimensional step grid) | `IndexDefinition` gains named components, and `PayoutFunction` has `index_names` from the start (Phase 1 requires one name). Two hazard sets share no events, so the alignment is a stated rule: a date window, the year level through `YearSets` on a concatenated event list, or one event set with several hazards. `OutcomeMeasure` already takes it |
| K-31, cluster scope | A joint problem per cluster, if the maintainers want it | A richer value of `scope`. A cluster is a given grouping of units. Same report as §6.5 |
| K-32, robust design and trajectories | A min–max over a `ScenarioSet`, as a wrapper over objectives; cover metrics along CLIMADA's `trajectory` | `Robust(objective)`; a metric step in `RiskTrajectory`, to be assessed |
| K-33, `unsequa` | Uncertainty and sensitivity of cover metrics, in the style of `CalcImpact` | `evaluate` as the output function. The API states whether a cover is fixed or redesigned per sample |
| K-34, cost-benefit | A cover as an adaptation option: the premium as a periodic cost and payouts reducing the net impact | Needs the maintainers (C8, Q6), since their measure design is changing |
| K-35, bridge to cat bonds | Bond simulation and pricing on a cover designed here | An export to `pay_vs_dam` (`pay`, `damage`, `year`, `month`), respecting `CatalogueYears` |

Also reserved, with no issue yet: an annual aggregate limit or reinstatements, which truncate a year's payout and so aren't linear in the amounts; block-bootstrap intervals and pooled k-fold metrics (the design review's finding on short blocks applies to short records here too); a synthetic noise layer on the index (§8); an export of a step cover to an `ImpactFuncSet`, Steinmann et al.'s form (D5); a local refinement after the grid; a second solver backend behind `solvers.py`.

### 14. The issue map

K-14 to K-23 hold, with these adjustments. Each is marked "adjusted"; the ADR wins over the issue texts, and the orchestrator updates them once Marc has decided.

| Issue | Covers | Files (§2) | Starts after |
|---|---|---|---|
| K-13 (MAR-312) | §12's fixtures. **Adjusted:** shared samples; synthetic data only; the event basis from the core only where Σf ≤ 1, plus closed forms; `below_attachment="zero"` only; `scope` is `"joint"` | `parity/climada/` in this repository | This ADR |
| K-14 (MAR-313) | The port, behaviour unchanged. Confirmed: `first_bin` and `"portfolio"` stay until K-15 and K-19 change them | all of the prototype's | K-10, K-11 |
| K-15 (MAR-314) | Covers and families. **Adjusted:** `first_bin` is retired instead of kept; `IndexDefinition` and `Limit` live in `cover.py`; `LinearPayout.from_triggers` | `parameters`, `payout`, `cover` | K-14, this ADR |
| K-16 (MAR-315) | Units and index. **Adjusted:** years leave the index; `index_stat` as in `cat_bonds`; `from_definition`; starts **after K-15**, not in parallel, because it imports `IndexDefinition` | `units`, `index`, `index_tracks` | K-15 |
| K-17 (MAR-316) | Outcomes. **Adjusted:** the event basis as a frequency measure (§5.1); `OutcomeSample` and `sample.py` are its files; `block` as the general split key | `measure`, `sample` | K-16 |
| K-18 (MAR-317) | Evaluation. **Adjusted:** `uncovered_impact` replaces a net-loss `Impact`; adds `payout_frequency`, `unidentified_share`, `premium_repriced` and `setup_text`; `allocation` per Amendment 3's rule | `riskmeasures`, `pricing`, `metrics`, `evaluate`, `plots` | K-15, K-17, K-13 |
| K-19 (MAR-318) | Calibration. **Adjusted:** `constraints.py`, the `lp_method` rule (D17), the `SLSQP` route with cuts (D10), fixed thresholds in joint designs (D9), the fill rule and ranges, `calibrate_frontier`; cvxpy leaves | `objectives`, `constraints`, `solvers`, `calibrate` | K-18, K-13 |
| K-20 (MAR-319) | Basis risk. **Adjusted:** structural sources and `index_diagnostics` lead, draws second, with their limit stated (D11). Its title changes to match | `basis_risk`; `from_impact_draws` in `sample` | K-19 |
| K-21 (MAR-320) | Scenarios. **Adjusted:** a label may hold several samples, an equal-weight mixture; the docs lead with windows or members | `scenarios` | K-19 |
| K-22 (MAR-321) | `cat_bonds`. Confirmed. `from_subareas` is a sequenced edit of `units.py` | `units`; tests | K-16, K-19 |
| K-23 (MAR-322) | Review readiness. Confirmed | docs, integration tests, `CHANGELOG.md`, `AUTHORS.md` | K-20, K-21, K-22 |
| K-04 (MAR-50) | The tutorial. **Adjusted:** the case of D15; a section on short records: calibrate on the 41 observed years of Jamaica and evaluate on STORM, which shares no event with them, showing `unidentified` and `unidentified_share`; the budget frontier; the scenario section on windows or members; scope sections each on their own rows ("Beyond the eighteen decisions", item 1) | `doc/tutorial/` | K-23 |

`CHANGELOG.md` has a Dependency Changes entry only if D10's answer changes.

### 15. Questions for the maintainers, and the feedback record

These feed K-01 (MAR-47). Posting stays on hold until Marc lifts it. Nothing has been posted or sent, and agents never contact the maintainers. Q1 to Q5 are the five questions of the K-01 draft, sharpened.

- **Q1. Location.** Is a new `climada_petals.engine.parametric`, next to `cat_bonds`, the right place?
- **Q2. Solver.** The LPs use scipy's HiGHS through `linprog`. For MSE we use `SLSQP` on the amounts, with no new package, up to a stated size. Would you accept one optional package for larger problems? `highspy` is the small one. Petals has no optional extras today, so how would you want that declared?
- **Q3. Representation.** Payouts and uncovered losses as `Impact`, the index in a table aligned on `event_id`, metrics as pandas. Or Steinmann et al.'s index as a `Hazard` and payout as an `ImpactFuncSet`?
- **Q4. Simulation years.** Is there a recommended way to get each event's simulation year on probabilistic sets? We state the route: catalogue years or `yearsets`. Is `yearsets` with replacement the route you would use for non-uniform frequencies?
- **Q5. Tutorial data.** Data API tropical cyclones and LitPop for Jamaica, and windstorm for Luxembourg?
- **Q6. Insurance in the measures.** How should a cover relate to `Impact.calc_risk_transfer` and the new `MeasureConfig`?
- **Q7. Review.** One PR for the module, the API docs and the tutorial, or several? What would make the review shorter?
- **Q8. `cat_bonds`.** Is a unit source from `Subareas` and a linear payout that matches `calc_payout` the right amount of overlap?
- **Q9. Versions.** Should the module target `develop` as it is? When do you expect conda-forge's petals to accept climada 6.2?
- **Q10. Test files.** What size of small test files is acceptable in the repository?

Notes for the maintainers, which are not requests. K-12 and K-22 noticed:

- `sample_events`'s default distorts non-uniform frequencies, and a `sampling_vect` holds positions, although its docstring says event ids. `sample_from_poisson` sets numpy's global seed.
- `TropCyclone.from_tracks` returns a column index of −1 if a `Centroids` holds the same coordinates twice.
- `Subareas.from_geodataframe`'s coverage check never fires, and `subarea_letter` stops being a letter after 26.
- `calc_payout` truncates an integer-typed index, and an unconstrained COBYLA can return `min_trig > max_trig`.
- conda-forge's climada 6.2.0 needs Python 3.11.

**Feedback record** (absorbs `docs/adr/climada-module.md` from PR #39's branch; K-01 fills it, Marc holds the conversation).

- Where posted (URL):
- Posted on (date):
- Posted by:
- Other channels (developers' call, email), with dates:

For each question, who answered, the date, a link to the comment and the answer in a sentence or two:

- Q1. Location:
- Q2. Solver dependency:
- Q3. Representation (index and payout objects):
- Q4. Simulation years for annual metrics:
- Q5. Tutorial data:
- Q6 to Q10:
- Other feedback:

A maintainer's answer that changes a decision becomes an amendment to this ADR.

## Decisions for the owner (D12)

Each decision lists the options, then one recommendation and why. Numbers cited are K-12's, with its setups; the two spot checks are under "Not verified".

#### D1. Does the build wait for the maintainers?

- (a) No. K-01 gates only the upstream PR (K-05), and their feedback becomes amendments.
- (b) Wait for an answer on location and shape before anything beyond the port (K-14).
- (c) Wait before any fork work.

**Recommendation: (a).** `cat_bonds`' Discussion got no written reply, and its PR review took about seven months, so waiting could cost months for feedback that may arrive only at review anyway. The hard questions here are about CLIMADA's objects, and K-12 answered those by measurement. The risk is rework if the maintainers want another location or shape. A move of location is mechanical, and the module's parts most exposed to taste (names, result objects) are small. CLIMADA's guide asks contributors to discuss a new module with the admins first, so the post should go out well before K-05, as soon as Marc lifts the hold.

#### D2. Location

- (a) `climada_petals.engine.parametric`, next to `cat_bonds` (accepted 2026-10-31).
- (b) Extend `engine.cat_bonds`.
- (c) `climada.engine`, in the core repository.
- (d) A separate package.

**Recommendation: (a).** It is decided and nothing has changed it. (b) mixes two products with different calibration methods. (c) needs a higher bar and core changes. (d) is the fallback if they decline.

#### D3. API shape

- (a) Classes with `from_*` constructors and module functions (`calibrate`, `evaluate`, `compare`), eager, with no plan object.
- (b) A calculator class like `ImpactCalc`: `ParametricCalc(index, impact, ...).calibrate(...)`.
- (c) Two layers and a lazy plan, as in ADR 0005.

**Recommendation: (a).** It is CLIMADA's idiom, and it fits `max-args=7` (§2). `ImpactCalc` has one job on three inputs; this module has several verbs on the same inputs, so a calculator would only hold arguments. ADR 0005 needs a plan because CRC's sources are lazy and remote. A CLIMADA user holds a `Hazard` and an `Impact` in memory.

#### D4. Cover and result apart

- (a) `ParametricCover` holds the terms; `CalibrationResult` holds the record.
- (b) One object, as in the prototype.

**Recommendation: (a).** A cover can then be written down, compared and applied to another hazard set. In (b) it carries the sample it was fitted on, which makes K-21 impossible.

#### D5. Result objects

- (a) Payouts and uncovered losses as `Impact`; metrics as pandas tables.
- (b) The index as a `Hazard` and the payout as an `ImpactFuncSet`, as in Steinmann et al.
- (c) The module's own result classes only.

The issue's starting recommendation said "net losses as `Impact`". That doesn't hold, for two reasons: ADR 0005's net loss includes the premium, which is annual and has no place in one event; and a signed event residual is negative wherever a payout exceeds the loss, while `local_exceedance_impact` drops values at or below zero (C6). The non-negative event quantity is the uncovered loss.

**Recommendation: (a), with uncovered losses in place of net losses.** CLIMADA's tools then work unchanged (§7). (b) is elegant for a step payout on one point, but an `ImpactFunc` interpolates between tabulated points, so a step needs doubled points; a group needs a pseudo-exposure; and neither scope nor premium has a place. An export of a step cover to that form is reserved (§13) and asked as Q3.

#### D6. Annual basis

- (a) The event basis always works. The annual basis takes a stated route, `CatalogueYears` or `YearSets`, with no default.
- (b) Catalogue years by default where the dates fit, as in the prototype.
- (c) `yearsets` by default.

**Recommendation: (a).** No route fits every hazard (K-12 Q3): catalogue years fail on windstorm as labelled, and `yearsets` gives flood and wildfire 36.9 % empty years against none. Tail numbers move with the route. A default is how the prototype collapsed STORM into 2 outcomes of 10,000. For the claim that the event basis always works, this ADR defines it: frequencies are the weights, and 1 − β is a frequency per year (§5.1). The prototype's form raises on Σf above 1, which is the case for windstorm and the earthquake file. Guidance per hazard goes in the docs (§5.2).

#### D7. Insured units

- (a) A point, a group or the whole set. A group's payout maps back to its points by value share.
- (b) The same, mapping back by loss share per event.
- (c) One exposure point per unit, as in the prototype.

**Recommendation: (a).** LitPop has thousands of points, so a unit per point is rarely the contract anyone wants. Value share is fixed and needs no event's loss, so it works on a payout under another hazard set. Loss share is an accounting statement that needs the loss; it stays available as an evaluation-time `allocation` for joint designs (§7).

#### D8. Payout families

- (a) Step, linear, piecewise linear, binary and a user protocol. Nothing paid below the attachment, with `first_bin` retired at K-15.
- (b) The same, with `first_bin` kept for comparisons, as K-15 says today.
- (c) Step only.

**Recommendation: (a).** The owner's rule of 2026-11-01 says new designs pay nothing below the attachment. A mode that pays on every event the hazard set holds depends on which events were kept, and K-13's cases don't need it. It stays through K-14, so that the port's one-off parity run passes unchanged.

#### D9. Free shape parameters

- (a) A stated grid with an exact solve at each point. In joint designs, thresholds are fixed, and users compare thresholds by running the design several times.
- (b) A derivative-free optimiser, like `cat_bonds`' COBYLA.
- (c) A grid followed by local refinement.

**Recommendation: (a).** On a finite event set the objective is piecewise constant in step and binary thresholds and piecewise smooth in linear ones, so gradients mislead. A grid is reproducible and shows how flat the optimum is. COBYLA is unconstrained, and K-12 Q8 found that a fit can land on `min_trig > max_trig`. The joint rule is ADR 0005's D-21.6: per-unit grids multiply across units, and the same word should mean the same restriction in both modules. K-19's "any scope" for free shapes narrows to the individual scope. (c) is reserved (§13).

#### D10. Solver and dependencies

For the LPs, scipy's HiGHS through the public `linprog` stands (decision 2 of 2026-10-31). The open question is the MSE route, which is a QP. K-12 Q6 and the spot checks give, on K-12's synthetic generator (5 steps, annual basis, one joint problem, pure premium unless stated):

| Route | New package | Public interface | Objective gap to cvxpy | 335 amounts | 1,000 amounts | 5,000 amounts | With a cost-of-capital load |
|---|---|---|---|---|---|---|---|
| `SLSQP` on the amounts | none | yes | 1e-11 to 5e-10 | 1 to 1.4 s | 222 s | not in 600 s | Cutting planes: 70 amounts in 0.8 s; 335 not within tolerance after 100 rounds |
| `trust-constr` | none | yes | 1e-5 to 1e-3 | 0.3 s | | 53 s | not tried |
| `lsq_linear`, with a search on the multiplier | none | yes | 7e-10 to 4e-9 | 51 to 157 s | | not in 600 s | no |
| scipy's private HiGHS bindings | none | **no** | 1e-11 | 0.04 s | | 42 s | not run |
| `highspy` | `highspy` | yes | 1e-11 | 0.05 s | | 38 s | 5 amounts in 0.15 s; 335 not in 600 s |
| cvxpy with Clarabel, the prototype's | cvxpy and its solvers | yes | the reference | 0.6 to 1.3 s | 5.8 s | 14 s | 335 in 1.9 s |

- (a) `SLSQP` on the amounts, with cutting planes under a load. No new package. Stated limits, and a typed error above them.
- (b) (a), plus cvxpy as a lazily imported route above the limits, as in the prototype. Not declared in petals' dependencies.
- (c) `highspy` as a new required package.
- (d) scipy's private bindings.
- (e) `trust-constr`.
- (f) Leave MSE out, or leave it to a user objective.

**Recommendation: (a).** It adds no package, uses only public interfaces, and passes the parity tolerance of `1e-6`, which (e) doesn't reliably. Individual designs and small joint designs are well inside its limits: a unit has a few amounts, and the tutorial's 14 parishes × 5 steps are 70. What it gives up is real: MSE on a joint design of more than 1,000 amounts raises, and MSE under a cost-of-capital load raises on joint designs of a few hundred amounts, which cvxpy solved in seconds. A smarter cutting-plane scheme may extend that, and K-19 can try one. (d) would break with any scipy release. (f) would drop the objective closest to what `cat_bonds` uses. Q2 asks the maintainers whether they'd accept a package. If they do, `highspy` or cvxpy goes behind `solvers.py` with no change to the API. So (b) can follow (a) on their answer, and it shouldn't come before it: an undeclared import is itself a dependency decision.

#### D11. Basis risk

- (a) Structural sources lead: the index's source, statistic and unit are stated in `IndexDefinition`, and the relation of index to loss is measured and flagged in every table. Impact-function draws come second, with their limit stated. No required model.
- (b) Impact-function draws and a warning, as K-20 says today.
- (c) A required basis-risk model, as in ADR 0005.

**Recommendation: (a).** This changes the starting recommendation, as the design review (MAR-344) asked. Impact-function draws widen the uncovered loss, but they can't change whether an event pays. CLIMADA's own basis risk is structural: an index that isn't the loss's hazard, a group, a track-based trigger. K-12 Q7 shows that a small group doesn't remove the effect, so the module measures the relation and doesn't infer it from the setup (§8). (c) adds a word with no information: the index builder already states the source. A required model suits CRC, where a sample has no second source.

#### D12. Phase 1 scope

- (a) Several exposures, joint calibration and evaluation under scenarios are all in Phase 1.
- (b) One unit per design in Phase 1, the rest in Phase 2, as the CRC module.
- (c) Joint in Phase 1, scenarios in Phase 2.

**Recommendation: (a).** Each event is one joint footprint, so joint calibration needs no dependence model. A scenario is another `Hazard`, and a cover is portable by construction. So these are cheap here, where they weren't in CRC. Scope is Marc's first-class element.

#### D13. Metric definitions and names

- (a) ADR 0005's definitions where the concepts coincide: coverage ratio `E[min(π, L)] / E[L]`, the design premium out of sample, the VaR tolerance. Adds `payout_frequency`, `unidentified_share` and `calibrate_frontier`. Names follow `cat_bonds`' vocabulary where it applies: `index_stat`, `from_triggers`.
- (b) The prototype's metrics only.
- (c) `cat_bonds`' definitions, with "basis risk" as the event-level squared error.

**Recommendation: (a),** so the two modules speak the same language (§1, §7). The three additions are the design review's (MAR-344). The frontier is a measurement, one design per budget in one table, with no "best" point.

#### D14. Relation to `cat_bonds`

- (a) Complementary (accepted 2026-10-31). `Subareas` is a unit source, and nothing inside it is edited.
- (b) A shared base, with a refactor of `cat_bonds`.
- (c) No connection.

**Recommendation: (a).** A shared base is the maintainers' call and is asked as Q8. What is worth changing there goes to them as a note (§15).

#### D15. The tutorial's case

- (a) A small country from the Data API, with sub-national units: Jamaica for tropical cyclones, and Luxembourg for the second hazard, European windstorm. Florida stays with the paper.
- (b) Florida's 67 counties (D2), as K-04 says today, on IRIS.
- (c) Florida from the Data API's USA files.

**Recommendation: (a).** `cat_bonds`' reviewers asked for Data API data and probabilistic sets, and the IRIS set behind the Florida portfolio isn't on the Data API. Jamaica has `random_walk` present, four future scenarios at several horizons, and STORM, all CC BY 4.0 and small (K-12 Q2); LitPop is on the Data API for it (1.1 MB, CC BY 4.0). Jamaica's flood file holds almost no depth (at most 1.2e-7 m), so the second hazard must be another. Windstorm in Luxembourg (`storm_europe_150arcsec_LUX`, 14.1 MB, CC BY 4.0, LitPop 1.08 MB) is a different hazard with an ensemble structure, on which the catalogue route doesn't run as labelled, so it shows `YearSets` with a reason. The short-record section uses Jamaica's observed set (§5.4).

#### D16. The issue map

- (a) K-14 to K-23 and K-04 as adjusted in §14.
- (b) As they stand.

**Recommendation: (a).** The adjustments follow from D5, D8, D9, D10, D11 and D13, and from one dependency: K-16 imports K-15's `IndexDefinition`, so they run one after the other.

#### D17. The LP method

K-12 says the list lacks this one. `highs` didn't solve 1,000 units × 10,000 events in 2,400 s, and `highs-ipm` took 59 s.

| Units × events | `highs` | `highs-ipm` | Source |
|---|---|---|---|
| 1 × 10,000 | 0.25 s | 1.1 s | Spot check |
| 1 × 50,000 | 5.8 s | 10.5 s | Spot check |
| 67 × 10,000 | 4.8 s | 1.6 s | Spot check |
| 67 × 50,000 | 127 s | 21 s (36 s in K-12) | K-12 Q5; spot check |
| 1,000 × 10,000 | not in 2,400 s | 59 s | K-12 Q5 |

The objective values agree to every printed digit wherever both ran.

- (a) A stated option with a rule as the default: `highs` for one unit, `highs-ipm` for several. The method used is recorded.
- (b) Always `highs`, as in the prototype.
- (c) Always `highs-ipm`.
- (d) No default.

**Recommendation: (a).** It follows the table, and it costs one line. The rule is an optimisation of time alone: both methods give the same objective, and which member of an optimal set they return is what §6.5 reports.

#### D18. Which CLIMADA the module targets

K-12 says the list lacks this one too: conda-forge can't install climada 6.2.0 and petals together today.

- (a) `develop` of both repositories, built from source over their `requirements/env_climada.yml`, declaring `climada>=6.1` as petals `develop` does. The upstream PR goes to `develop`.
- (b) The newest pair conda-forge can install: climada 6.1 with petals 6.2.0, and so scipy 1.15.2.
- (c) Wait for a conda-forge petals that accepts climada 6.2.

**Recommendation: (a).** The prototype passes on it (743 passed, 1 skipped, K-12 Q1), and it is what the PR lands on. Phase 1 uses nothing that is new in 6.2, so `>=6.1` holds, and K-23 checks it. (b) builds against an old scipy: of the versions K-12 tried, 1.15.2 alone spends minutes after HiGHS returns on large LPs (Q5). On 6.1 the module still works, and only those LPs are slower. K-11 fixes the recipe. `trajectory`, which is new in 6.2, is Phase 2.

### Beyond the eighteen decisions

The decisions don't determine these. The text above settles each as the agent recommends, and accepting this ADR covers them. Marc may want to look at the first.

1. **The tutorial doesn't set individual against joint.** K-04's step 8 and Marc's note of 2026-10-31 ask for individual and joint calibration "at the same total budget". D-21.4, decided later for the CRC module, says that no table or figure sets individual against joint until the RQ2 rule is revisited (MAR-152 item 4). The publication rule binds both. So the tutorial shows each scope with its own rows and explains what it optimises, and states the budget each uses, with no side-by-side table or figure. If Marc wants the comparison there, this is the line to change.
2. `scope="joint"` replaces `"portfolio"` (§1), and `scope` has no default.
3. `Limit` is a term of the cover, and the prototype's hidden cap becomes `Limit.largest_loss()`, stated (§3).
4. cvxpy leaves the module at K-19. The port keeps it until then.
5. The module has no design id and no metadata layer; the setup is in columns (§3, §7).
6. Warnings go through `LOGGER`, and those that change how a number reads are also columns (§2).
7. Exposure-dependent weights follow the exposures given; freezing them at inception is open for K-21 (§9).

## Consequences

- K-13 can start once this ADR is accepted, in this repository. K-14 needs K-10 and K-11; K-15 and everything after it need this ADR too.
- The module carries its own implementation of the formulas. A change in the core or the module needs a fixture update, or the parity tests fail.
- Petals gains no package, if D10 stands. In return, MSE has stated size limits, and they are lower under a cost-of-capital load.
- Every number can state its setup from the table's own columns, as the publication rule asks.
- Several prototype names change (§11), so the K-01 draft's API sketch (PR #39) needs a refresh before it is posted.
- The event basis here extends the core's: where frequencies sum to more than 1, the core raises and this module doesn't. Parity is checked where both are defined.
- Joint designs have fixed thresholds, as in the CRC module.
- The build goes ahead without the maintainers (D1), so an answer to §15 can change a section after it is built.

## Alternatives considered

Beyond the options under each decision:

- **Dividing event frequencies by their sum.** Rejected: β would depend on which loss-free events a file holds (§5.1).
- **Years on the index, as in the prototype.** Rejected: it ties every index to the catalogue route, and a cover to a year structure.
- **Reading the year structure from the hazard automatically.** Rejected: K-12 Q3 shows no reading that works for every hazard.
- **A subclass of `Impact` for payouts.** Rejected: a plain `Impact` is what CLIMADA's tools expect.
- **Reusing `climada.util.calibrate`.** Rejected: it fits impact functions through a generic optimiser, and these problems have an exact solve.
- **A year-level payout cap in Phase 1.** Rejected: truncating a year's total isn't linear in the amounts. Reserved in §13.
- **A second, independent solver for checking every solve in the module.** Rejected: numpy's recomputation of the objective and constraints (§6.4) and the golden cases already catch wrong answers.

## Not verified

- **No module code exists.** The signatures are an outline, and K-14 onward may correct them through errata.
- K-12's limits apply: `linux-64` was not tested; each hazard was read for one country; timings come from one shared machine; Q7 uses synthetic storms and one site, with one objective.
- **Spot checks by the agent on 2026-11-09**, on one shared Apple M4 machine, scipy 1.17.1. Not committed; the PR description has the output.
  - *The event basis* (§5.1). 400 synthetic events on one unit, a step payout with 5 steps, weighted CVaR at α = 0.9 and β = 0.99, budget 0.8, frequencies summing to 12 per year. The LP's objective equals the value computed directly from the payout, the mean of the worst 1 − β of frequency. Adding 2,000 loss-free events below the attachment left the objective unchanged and moved the levels by at most 5e-13. With frequencies summing to 0.5, the objective equals the prototype's `event` measure to 1e-16 relative.
  - *The LP method* (D17). K-12's generator and script, with `--method highs-ipm` and `highs` at the sizes in the table.
  - *The MSE routes* (§6.4, D10). K-12's generator, budget 0.8, 5 steps, annual basis, one joint problem. `SLSQP` at 200 units × 10,000 events (1,000 amounts): 222 s and 178 iterations, the objective 5e-10 below cvxpy's, which took 5.8 s. Cutting planes under a cost-of-capital load (rate 0.3, q 0.99): at 1 unit × 10,000, 13 rounds and 0.01 s; at 14 units × 10,000, 61 rounds and 0.8 s; both about 1e-10 from cvxpy, with the premium on the budget to about 1e-13. At 67 units × 10,000 it was stopped at 100 rounds after 449 s, with the premium still 3.5e-6 above the budget.
- That a Natural Earth admin-1 join gives Jamaica's 14 parishes and Luxembourg's cantons on LitPop points: K-04 checks. The Data API's LitPop listings were read as metadata on 2026-11-09, and no data was downloaded.
- CLIMADA's and petals' code was read, not run, for this ADR, apart from what K-12 ran. That `calc_freq_curve` and `write_hdf5` take a payout `Impact` unchanged is K-18's test.
- That pylint's `max-args=7` counts keyword-only arguments is assumed. The signatures in §2 stay within 7 if it does.
- The threshold of `comonotone_index`, 0.99, rests on one synthetic site.
- Whether the maintainers accept any of §15.

## Sources

- This repository: [`docs/climada/k12-design-facts.md`](../climada/k12-design-facts.md), the prototype under `packages/climada/src/petals_parametric`, `packages/climada/scripts/k12_*.py`, [ADR 0002](0002-core-interfaces.md), [ADR 0005](0005-crc-parametric-module.md) (read for concepts and metric definitions), `packages/core/src/parametric_insurance_design/basis.py`, and `docs/adr/climada-module.md` on PR #39's branch.
- Linear (private): MAR-48, MAR-47, MAR-50, MAR-311 to MAR-322, MAR-323 to MAR-328, MAR-344, the CLIMADA Contribution project.
- CLIMADA 6.2.0 (<https://github.com/CLIMADA-project/climada_python/tree/v6.2.0>): `climada/engine/impact.py`, `climada/util/yearsets.py`, `climada/util/interpolation.py`, `climada/util/calibrate/`.
- petals 6.2.0 (<https://github.com/CLIMADA-project/climada_petals/tree/v6.2.0>): `climada_petals/engine/cat_bonds/subarea_calculations.py` and K-12's reading of the rest.
- CLIMADA Data API (<https://climada.ethz.ch/data-api/>): the listings for LitPop, tropical cyclones and windstorm, read as metadata on 2026-11-09.
- Rockafellar and Uryasev (2000), for the CVaR's form. Steinmann et al. (2023), *Environment Systems and Decisions*, <https://doi.org/10.1007/s10669-023-09934-x>, for cat-in-a-circle and the index-as-`Hazard` form.
