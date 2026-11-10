# K-01: CLIMADA module proposal (draft for the owner)

- Issue: MAR-47 (Human). Design: [ADR 0006](../adr/0006-climada-parametric-module.md), accepted 2026-11-10. Where this draft and the ADR differ, the ADR wins.
- Prepared by an agent under the issue's "Agent may prepare" part: first on 2026-10-25, rewritten on 2026-11-10 for ADR 0006.
- **Nothing has been posted or sent. Posting is on hold until Marc lifts it.** Marc reviews, edits, posts and holds the conversation. No agent contacts the maintainers.
- Feedback goes in the feedback record of ADR 0006 §15.

## 1. Proposal text

For petals Discussions, category "Ideas" (see P2 below). The body is about 930 words without the collapsible sketch, of which the ten questions are 250. Copy from the raw file, between the markers. The text between the markers carries no issue IDs.

<!-- BEGIN PASTE: title -->
Proposal: a module for parametric insurance covers (`climada_petals.engine.parametric`)
<!-- END PASTE: title -->

<!-- BEGIN PASTE: body -->
Hi CLIMADA team,

I'd like to contribute a module for designing and evaluating parametric (index-based) insurance covers. Your guide asks contributors to discuss a new module with the admins first, so this comes before any PR.

**Nothing is built upstream yet.** A prototype with one payout family lives in my own repository ([marc272/parametric-insurance-design](https://github.com/marc272/parametric-insurance-design)). The design below goes beyond it and has no code yet. Its [design record](https://github.com/marc272/parametric-insurance-design/blob/main/docs/adr/0006-climada-parametric-module.md) is the long version.

**Motivation**

CLIMADA already holds what a parametric design needs: an event set, exposures, and an `Impact` with each event's loss per point. The closest pieces I found are `Impact.calc_risk_transfer`, an indemnity layer on each event's total, and `engine.cat_bonds`, which designs parametric sovereign cat bonds (one linear payout per subarea, fitted by squared error; countries pooled into one bond).

This module would serve one risk owner: create a cover for any hazard and exposures, analyse its effectiveness on several metrics and under scenarios, and compare covers. It grew out of my master's thesis (TUM, 2026), and its cat-in-a-circle index follows Steinmann et al. (2023, [doi:10.1007/s10669-023-09934-x](https://doi.org/10.1007/s10669-023-09934-x)).

**What Phase 1 would contain**

- **Covers.** `ParametricCover` holds terms only, so it can be stored, compared and applied to another hazard set. `CalibrationResult` holds how it was found.
- **Units.** A point, a group of points or the whole set, each with one payout function. A group's payout maps back to its points by value share.
- **Index.** A footprint statistic (`index_stat`, as in `cat_bonds`), cat-in-a-circle from tracks, another hazard set, or a user's table keyed on `event_id`.
- **Payouts.** Step, linear, piecewise linear, binary, or a user's own. Nothing is paid below the attachment.
- **Calibration.** `MSE`, `ExpectedUncovered`, `WeightedCVaR` (α·CVaR_β(U) + (1 − α)·E[U], with U the uncovered loss) or a user's objective, under a pure premium or a cost-of-capital load. `scope` is required: `"individual"` solves one problem per unit, and `"joint"` solves one problem on one owner's total per event, under one premium budget.
- **Outcomes.** `EventBasis` uses the frequencies as weights and always applies. An annual basis takes a stated route: `CatalogueYears` (year labels on events) or `YearSets` (`climada.util.yearsets`, with replacement). In the Data API files I read, no single year structure holds across hazards, so there is no default.
- **Evaluation.** `evaluate` and `compare` return pandas tables of coverage, tail and basis-risk metrics (a family here, not `cat_bonds`' event-level squared error), with each row's setup in columns. On one point with one impact function, a centroid index determines the loss exactly, so the module measures how index and loss relate and flags that case.
- **Scenarios.** Another `Hazard` or other `Exposures`. A fixed cover's index is rebuilt there and evaluated.
- **Results.** Payouts and uncovered losses come back as `Impact`, so that `calc_freq_curve` and the plots apply. A signed net loss stays in the tables, since `local_exceedance_impact` drops values at or below zero.
- **Docs.** API pages and a tutorial on Data API data.

**Location**

A new `climada_petals.engine.parametric`, next to `cat_bonds`, under petals' GPL v3, declaring `climada>=6.1` as petals `develop` does. Nothing inside `engine/cat_bonds` would change. `Subareas` can supply units, and `LinearPayout.from_triggers` takes `calc_payout`'s three numbers.

**Solver, and its limits**

No new package, since a new one needs your permission. `ExpectedUncovered` and `WeightedCVaR` are linear programs for SciPy's HiGHS, through the public `linprog`. `MSE` is a quadratic program and petals has no optional extras, so it uses `SLSQP` on the payout amounts, with cutting planes on the premium under a cost-of-capital load. That costs size: `MSE` raises a typed error above `max_slsqp_amounts=1_000`, and under a load on joint designs of a few hundred amounts (`max_cut_rounds=100`). Individual designs are far below the limits. Every solve is rechecked in numpy, with no silent fallback.

**Phase 2, continuous and open to your priorities**

Multi-hazard covers, cluster scope if you want it, robust design and `trajectory`, `unsequa`, cost-benefit, and a bridge to `cat_bonds`' bond simulation.

**Questions**

1. **Location.** Is a new `climada_petals.engine.parametric`, next to `cat_bonds`, the right place?
2. **Solver.** The LPs use SciPy's HiGHS through `linprog`. For MSE I'd use `SLSQP` on the amounts, with no new package, up to a stated size. Would you accept one optional package for larger problems? `highspy` is the small one. Petals has no optional extras today, so how would you want that declared?
3. **Representation.** Payouts and uncovered losses as `Impact`, the index in a table aligned on `event_id`, metrics as pandas. Or Steinmann et al.'s index as a `Hazard` and payout as an `ImpactFuncSet`?
4. **Simulation years.** Is there a recommended way to get each event's simulation year on probabilistic sets, for each kind of hazard? The module has the caller state the route: catalogue years or `yearsets`. Is `yearsets` with replacement the route you would use for non-uniform frequencies?
5. **Tutorial data.** Data API tropical cyclones and LitPop for Jamaica, and windstorm for Luxembourg?
6. **Insurance in the measures.** How should a cover relate to `Impact.calc_risk_transfer` and the new `MeasureConfig`?
7. **Review.** One PR for the module, the API docs and the tutorial, or several? What would make the review shorter?
8. **`cat_bonds`.** Is a unit source from `Subareas` and a linear payout that matches `calc_payout` the right amount of overlap?
9. **Versions.** Should the module target `develop` as it is? When do you expect conda-forge's petals to accept climada 6.2?
10. **Test files.** What size of small test files is acceptable in the repository?

<details>
<summary>API sketch (a proposal: nothing here is implemented, and every name is open)</summary>

```python
import numpy as np
from climada.engine import ImpactCalc
from climada_petals.engine import parametric as pm

impact = ImpactCalc(exposures, impfset, hazard).impact(save_mat=True)

# A unit gets one payout function: a point, a group of points or the whole set.
units = pm.InsuredUnits.from_column(exposures, "parish")
index = pm.ParametricIndex.from_hazard(hazard, units, index_stat="mean", weight="value")

# What an outcome is, always stated: EventBasis, CatalogueYears or YearSets.
basis = pm.YearSets.from_frequencies(
    impact, n_years=20_000, rng=np.random.default_rng(311)
)
sample = pm.OutcomeSample.from_impact(index, impact, units=units, basis=basis)
train, test = pm.holdout(sample, train_fraction=0.7, rng=np.random.default_rng(312))

# Terms only. The step levels are free, so this is a template.
template = pm.ParametricCover(
    index.definition,
    pm.StepPayout.uniform(attachment=33.0, exhaustion=80.0, n_steps=5),
    unit_id=units.unit_id,
    payout_unit=impact.unit,
    limit=pm.Limit.largest_loss(),
)

# Also pm.ExpectedUncovered() or pm.WeightedCVaR(alpha=0.9, beta=0.99).
# scope is "individual" or "joint", with no default.
result = pm.calibrate(
    template, train, pm.MSE(), scope="joint", budget=pm.Budget(ratio=1.0)
)  # a CalibrationResult: the record of how the cover was found
cover = result.cover  # a resolved ParametricCover: the terms, ready to store

table = pm.evaluate(result, test, split="out_of_sample")  # a pandas DataFrame
payouts = pm.payout_impact(cover, test)  # a climada Impact
uncovered = pm.uncovered_impact(cover, test)  # also a climada Impact

# One cover under scenarios. Each s_* is an OutcomeSample on another Hazard,
# its index rebuilt with pm.ParametricIndex.from_definition.
scenarios = pm.ScenarioSet({"rcp45, 2040 to 2080": [s_2040, s_2060, s_2080]})
pm.evaluate_scenarios(cover, scenarios, split="out_of_sample")
```

</details>

I plan to build this in my own fork while we talk, and to change it where your answers call for that. A PR to `develop` would come only after this discussion. I'd also be glad to talk it through on a call.

Thanks for reading.

Marc
<!-- END PASTE: body -->

## 2. Decisions for Marc before posting

Already settled, so not asked again: the location, scipy's HiGHS for the LPs, GPL v3 as no blocker, and `cat_bonds` as complementary (Marc, 2026-10-31; ADR 0006 D2, D10, D14). The thesis is not public, so the post cites it without a link (Marc, 2026-10-31).

| # | Decision | Recommendation | Why |
|---|---|---|---|
| P1 | When to post | Yours. The hold stands until you lift it | The post should go out well before the upstream PR, K-05 (ADR 0006 D1) |
| P2 | Where to post | petals Discussions, "Ideas". With no reply after a few weeks, cross-link it in `climada_python` Discussions | The module goes to petals, and `cat_bonds` was proposed in a petals Discussion |
| P3 | Contact the ETH group | Post first, then ask to present at a developers' call. Whether to @-mention the `cat_bonds` reviewers is yours (2026-10-31); the draft doesn't | `cat_bonds`' Discussion got no written reply (D1), so a post alone may bring no feedback. The post offers "a call" without naming one |
| P4 | Mention the paper | No, only the thesis | The post shows no results, and a paper invites questions about them |
| P5 | Link the design record (ADR 0006) | Keep the link | A maintainer who wants the detail needs it, and it is a page of the public repository you decided to link. But it carries issue IDs and your decisions, and it sets names beside another module's, which isn't part of this proposal. To drop it, delete the sentence "Its design record is the long version." |
| P6 | The notes on their code (ADR 0006 §15) | Leave them out of the first post, and offer them later as separate issues | Yours (K-12's comment on MAR-47). The post asks for their time, and a list of defects is a different conversation |
| P7 | Say where the code stands | Keep "I plan to build this in my own fork" only if it is still true when you post | ADR 0006 D1 has the build go ahead without waiting. The fork itself doesn't exist yet (MAR-309), so the post states a plan |

Left out on purpose: the first draft's sentence that Steinmann et al.'s code is archived in `climada_papers`. It is in neither ADR 0006's facts nor K-12. The first draft read it from that repository on 2026-10-25, so you can put it back if you want it in the motivation.

## 3. Publication-rule check

The text between the markers:

- presents the method and the tool only, and makes no novelty claim;
- shows no result numbers. The numbers in it are example arguments in the sketch (`n_years`, `attachment`, `alpha`, `beta`, the budget) and the solver's stated limits, which are terms of the design;
- makes no claim that a tail objective does better. `WeightedCVaR` is listed as one objective among several;
- says what joint calibration is and what it optimises, with no comparison against calibrating each unit alone. `scope="individual"` and `scope="joint"` are named side by side with no ranking;
- says that nothing is built upstream and that the prototype is ours;
- carries no issue IDs and no Linear links, and says nothing about the CRC module.

If you edit the text, keep these limits.

## 4. Where each statement comes from

Facts C1 to C13, the decisions (D) and the sections (§) are ADR 0006's. Q is a question of K-12 ([design facts](k12-design-facts.md)). What the table doesn't list is the module's own design, from ADR 0006 §1 to §9.

| Statement in the post | Source |
|---|---|
| The guide asks to discuss a new module with the admins first | D1 |
| `imp_mat` is events × points; `calc_freq_curve` and the plots work on any `Impact` | C2 |
| `calc_risk_transfer` is an indemnity layer on each event's total | C8 |
| What `cat_bonds` does, and its terms "basis risk" and pooling | C9, §1, §10 |
| `index_stat` follows `cat_bonds` | C9, §4 |
| Cat-in-a-circle after Steinmann et al.; their index as a `Hazard` and payout as an `ImpactFuncSet` | §4, D5, Sources |
| No single year structure across the Data API's hazards | C3; Q2, Q3 (one country per hazard, hence "the files I read") |
| `YearSets` samples with replacement | C5, §5.2; Q4 |
| The event basis always applies | §5.1, C4 |
| The loss is an exact function of a centroid index | §8; Q7 |
| `local_exceedance_impact` drops values at or below zero | C6 |
| GPL v3; `climada>=6.1` as petals `develop` declares; a PR to `develop` | ADR header, C13, D18 |
| `Subareas` as a unit source; `LinearPayout` against `calc_payout`; nothing in `cat_bonds` edited | §3, §10; Q8 |
| A new package needs the admins' permission; petals has no optional extras | Context table, C11; Q6 |
| The MSE route, its options and limits; the recheck after a solve | §6.4, D10 |
| The prototype has one payout family; no module code exists | "What the prototype gives", "Not verified" |
| Phase 2 | Context, §13 |
| The ten questions | §15, with "for each kind of hazard" added to the fourth (K-12's comment on MAR-47) |

**Not verified:**

- The sketch has not been run. It follows ADR 0006 §2, whose signatures are an outline.
- `MeasureConfig` appears only by name, in §15's Q6. The post says nothing about it beyond asking.
- That `calc_freq_curve` takes a payout `Impact` unchanged is K-18's test (ADR 0006, "Not verified").
- Question 9 depends on conda-forge's state on 2026-11-08 (C13). Check it again before posting.
- P2 and P3 rest on the first draft's reading of petals' Discussions and the contribution guide on 2026-10-25, which ADR 0006 does not restate beyond D1.
