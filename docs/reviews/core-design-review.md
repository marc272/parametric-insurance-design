# Core design review: tail and portfolio formulations

Issue MAR-161 (F-13a). Reviewed: `main` at `f74f123` (2026-10-31), `packages/core/src/parametric_insurance_design/`. Spec: SPEC §4.2, §5, §6; ADR 0002.

Parity (MAR-18) shows that the core reproduces the thesis code. This review asks something else: are the formulations well defined and well named, are the scopes compared fairly, and does the code read cleanly? It reports observations and proposes follow-ups. It changes no library code.

**How it was checked**

- I read the modules in scope. I compared them with SPEC §6, ADR 0002, the methodology notes, the thesis code (`parametric-insurance-framework`, `src/implementation.ipynb`) and the thesis PDF (§2.2–§3.6, text extracted with PDFKit).
- New property tests are in `packages/core/tests/test_design_properties.py`. All pass, so no property failed and nothing needed a stop-and-escalate.
- Numbers on thesis data come from direct library calls on the thesis fixture, prepared as in `parity/configs/thesis.yaml`: the noise layer (13 copies), then the 20 m/s filter. The prepared EventSet is `sha256:008057c84ba2541847f1c447c19a201c3d4951320610625e246a7a4bbd5eafdf`, with the config's components (15 bins on [20, 70], `Budget(1.0)`, pure premium) and only the basis changed. Where a stored run has the same setup, its config hash is given. My values match those runs, e.g. annual CVaR₀.₉₉ = 879,564 for `9cf92ce6c1e7`.

**Convention used throughout:** the weighted-CVaR objective is `α·CVaR_β(U) + (1 − α)·E[U]`, so **α weights the CVaR term**. This is the code (`objectives.py:226-304`), thesis eq. (2.4) and (3.9), and SPEC §6.7 ("with α = 0, weighted-CVaR equals E[U]"). See finding F3: two Linear issues write it the other way round.

## Verdicts by scope item

| # | Scope item | Verdict | Findings |
|---|---|---|---|
| 1a | Weighted-CVaR objective vs SPEC §6 and the thesis | **Sound** (code = thesis (2.4)/(3.9) = SPEC). Unclear wording: α is swapped in two issue texts; the thesis defines CVaR as E[L \| L ≥ VaR] | F3, F5 |
| 1b | Rockafellar–Uryasev epigraph; linearisation of U = (L − π)⁺ | **Sound** | — |
| 1c | Objective vs `riskmeasures.var_cvar` on each basis | **Sound**, tested on all three bases | — |
| 1d | α ∈ {0, 1}, β near 0 and 1 | **Sound**. No guard when 1 − β is below the smallest outcome probability | F15 |
| 1e | The "β ≤ 0.97" coincidence with E[U] on the annual basis | **Unclear.** It is a theorem only for β ≤ P(L_o = 0) (0.930 here); above that it is empirical, and "≤ 0.97" is off by one grid point | F4 |
| 1f | VaR at exact steps (MAR-155) | **Unclear.** On the annual basis a standard β always falls on a step; CVaR, designs and premiums are unaffected | F2 |
| 2a | How the scopes aggregate L and π | **Sound** | — |
| 2b | Budgets per scope; joint vs individual at the same total budget | **Sound** (proven: the joint problem relaxes the individual one). Unclear under a load | F6 |
| 2c | Cluster index (value-weighted mean) | **Sound** as implemented. Unclear as a comparison: it changes the index as well as the calibration. Clustering features ignore the basis | F7, F9 |
| 2d | MSE on the aggregate; per-asset KPIs of joint designs | MSE on the aggregate: **sound** (MAR-24 choice). Per-asset KPIs and payout functions of joint designs: **defect** (known, MAR-100, MAR-91) | F8 |
| 3 | Per-problem budget against the aggregate premium (MAR-27 option a) | **Sound**, now property-tested. Unclear presentation | F6 |
| — | Payout below the attachment, and the threshold filter (found in review) | **Defect** | F1 |
| 4a | Public API: `noise` and the `robust` stubs | **Unclear** | F10 |
| 4b | Names and stale docstrings | Cleanliness | F11, F12 |
| 4c | Duplicated logic, dead code, module boundaries vs ADR 0002 | Cleanliness. Boundaries **sound**; no STORM code in the core | F13, F14, F16 |
| 5 | Property tests | Added, all pass | "New property tests" below |

## Findings, ranked correctness → clarity → cleanliness

### F1. A payout below the attachment is θ_{j,0}, but the event and annual bases count dropped rows and empty years as paying nothing (defect)

**Where.**
- `payout.py:18-19` and `payout.py:261`: index values below `b_0` are clipped into bin 0, so "a zero index (no hazard) pays `theta[j, 0]`".
- `basis.py:28-30, 43-51`: the "no event" outcome and the pooled empty (year, draw) slots have zero payout.
- SPEC §5: "A threshold filter may drop rows only for speed … dropped rows count as zero-loss mass."
- `eventset.py:1325-1327`: the filter "keeps every row that can trigger a payout".

**The contradiction.** Every kept row whose index is below the attachment pays θ_{j,0}. The same index on a dropped row, or in a year without rows, pays nothing in the measure. So the payout is not a function of the index alone: it depends on which rows the EventSet holds. Nothing forces θ_{j,0} = 0, and the optimiser sets it positive whenever bin 0 carries loss. A design calibrated on filtered data then has two problems:

- it changes when the filter changes, which contradicts SPEC §5;
- priced on all events, its premium is higher than the one recorded and budgeted.

The thesis text agrees with the intended semantics: §3.3 (3) calls the attachment "an attachment point below which no payout is triggered". Its §3.3.1 and its code clip into B₁ instead.

**Minimal reproduction** (one location, 10 years, `StepPayout(20, 70, 2)`). Events: index 30 with loss 4; index 60 with loss 10; index 5 with loss 0. `filter_threshold(20)` drops the last event, which has zero loss. Same numbers on `event` and `annual`:

| Objective, budget | Calibrated on | θ | Recorded premium | Premium on all events | Budget |
|---|---|---|---|---|---|
| MSE, `Budget(5)` | all events | (2, 10) | 1.4 | 1.4 | 7 |
| MSE, `Budget(5)` | filtered | (4, 10) | 1.4 | **1.8** | 7 |
| E[U], `Budget(0.5)` | all events | (0, 7) | 0.7 | 0.7 | 0.7 |
| E[U], `Budget(0.5)` | filtered | (1.86, 5.14) | 0.7 | **0.89** | 0.7 (**broken**) |

"Premium on all events" is the portfolio `premium` of `evaluate.kpis(full, Individual(), [result], basis=…, pricing=PurePremium())`, i.e. the design evaluated on the unfiltered EventSet. "Budget" is κ·E[L], which is the same on both EventSets because the dropped event has zero loss. On the filtered data, the E[U] optimum isn't unique: every θ with θ₀ + θ₁ = 7 and θ₀ ≤ 4 is optimal. Every one of them with θ₀ > 0 breaks the budget on all events; the solver returned (1.86, 5.14).

**Impact.**
- **Thesis data: small, one design over budget.** The Emanuel function gives zero loss below 25.7 m/s, so bin 0 [20, 23.3) carries no loss, and the 20 m/s filter drops no loss (`expected_loss_dropped` = 0). Only the MSE designs pay noticeably in bin 0. On the annual basis, MSE pays on zero-loss events to fit multi-event years. I priced the filtered designs on the unfiltered noisy EventSet: 78,741 rows instead of 13,897.
  - Annual individual MSE design (`e2cbcc3abdd5`, θ_{j,0} up to 2,507): premium 221,568 instead of the recorded 220,257, which is **0.5 % over its budget** of 220,363.
  - Portfolio MSE designs on `annual` and `event`: +0.0035 %.
  - E[U] and weighted-CVaR designs: unchanged.
  - Parity (`event_conditional`, conditional on the kept rows by construction) is unaffected.
- **D2 cat-in-a-circle: material, not measured here** (the EventSet isn't on this machine).
  - `research/data/d2-florida-eventset/README.md:22` recommends "attachment 0" on the category index, which makes bin 0 the category-0 bin.
  - Category-0 (event, county) pairs are 98 % of the pairs and carry 36 % of the loss (`research/notes/d2-florida-eventset.md`).
  - So the MSE design sets θ_{j,0} > 0: with a slack budget its per-row optimum is the bin-wise conditional mean, which is positive in bin 0. E[U] and CVaR designs probably do too.
  - θ_{j,0} then pays on every storm that the adapter's `proximity_km` kept, and on none of the others. The adapter's proximity filter becomes part of the contract.

**Follow-up (new issue).** *[F-13] Step payout: pay nothing below the attachment, and make the threshold filter exact on the event and annual bases.*
- Owns `payout.py`, the payout section of `experiment/config.py`, `tests/test_payout.py`, a new `tests/test_filter_invariance.py`, an ADR 0002 amendment (`basis_matrix`'s "every row has exactly one 1" becomes per-mode), and the D2 README's attachment advice.
- Suggested shape: `StepPayout(below_attachment="zero" | "first_bin")`, with `first_bin` for the thesis and parity configs. The default for new configs is the owner's call.
- Acceptance: with `below_attachment="zero"`, dropping rows whose index is below the attachment at every location and whose loss is 0 changes neither θ nor the premium on the `event` and `annual` bases (a property test). Parity stays byte-identical with `first_bin`.

### F2. On the annual basis, a VaR at a standard β is always on a step (unclear; raises MAR-155's priority)

**Where.**
- `riskmeasures.py:188` (strict `searchsorted`) and `riskmeasures.py:197-198`: "VaR is the lower β-quantile: the smallest v with P(X ≤ v) ≥ β".
- `bootstrap.py:428` uses `CDF_ATOL` instead.

**Observation.** Every (year, draw) slot has probability 1/(|S|·D). When |S|·D is a multiple of 1,000, as for 10,000, 7,000 or 3,000 years, β·|S|·D is an integer for every β with three decimals, so the β-quantile lies exactly on a step. The strict comparison then returns whichever atom the rounding of the cumulative sum lands on.

- With 10,000 × 13 equally likely slots, it is the upper atom at every β in {0.9, 0.95, 0.99, 0.995, 0.999}.
- Annual portfolio E[U] design on thesis data (`9cf92ce6c1e7`), strict vs exact-arithmetic VaR:

  | β | Strict VaR | Exact-arithmetic VaR |
  |---|---|---|
  | 0.97 | 483.5 | 479.4 |
  | 0.99 | 91,937 | 91,750 |
  | 0.999 | 1,934,410 | 1,896,710 |

  These are the `var_uncovered` KPI and, at T = 1/(1 − β), the AEP exceedance value.
- The bootstrap's VaR uses the tolerance, so a VaR point estimate and its interval refer to adjacent atoms.
- CVaR doesn't depend on which atom is chosen. The new test `test_cvar_on_an_exact_step_does_not_depend_on_the_order_of_ties` proves it, including a pooled zero atom. So no design, CVaR or premium is affected.

MAR-155 treats the step as an edge case on unequal-probability bases. On the annual basis it is the normal case.

**Follow-up.** No new issue: add this evidence to MAR-155 and schedule it before C1 numbers are published. Acceptance is MAR-155's, plus one line: "the annual VaR KPI, the AEP curve and the bootstrap use one atom convention".

### F3. The α convention is swapped in two issue texts (clarity, high: feeds public pages)

**Where.** MAR-163's description writes "the weighted objective α·E[U] + (1 − α)·CVaR_β(U), written exactly as implemented". MAR-161's scope item 5 asks that "wCVaR with α = 1 reproduces the E[U] design".

**Observation.** The code, thesis (2.4) and SPEC §6.7 weight the CVaR with α. In the code's convention, MAR-161's property is SPEC §6.7's α = 0 property. That one is already tested on all three bases:
- `test_engine_properties.py::test_weighted_cvar_with_alpha_zero_equals_expected_uncovered`;
- `test_engine_properties_bases.py::test_weighted_cvar_with_alpha_zero_equals_expected_uncovered`.

Read literally (α = 1 is the pure CVaR), it is false in general. It holds exactly when β ≤ P(L_o = 0), which `test_weighted_cvar_reproduces_expected_uncovered_below_the_zero_loss_mass` proves, and F4 explains. MAR-163's text, copied into a concept page, would publish the objective with the weights swapped.

**Follow-up.** No new issue: the orchestrator corrects MAR-163's description to `α·CVaR_β(U) + (1 − α)·E[U]` before MAR-163 is dispatched.

### F4. "Weighted CVaR coincides with E[U] for β ≤ 0.97 on the annual basis" is partly a theorem and partly an observation (clarity)

**Where.**
- `research/notes/annual-basis-rerun.md`, observations 4 and 6;
- `research/notes/loaded-pricing.md`, A4;
- MAR-163 ("β ≤ 0.97").

**The theorem.**
1. 0 ≤ U_o ≤ L_o, so P(U_o = 0) ≥ P(L_o = 0) for every payout.
2. If β ≤ P(L_o = 0), then VaR_β(U) = 0 and CVaR_β(U) = E[U]/(1 − β) for every design.
3. The weighted-CVaR objective is then (α/(1 − β) + 1 − α)·E[U], with the same minimisers as E[U].

`test_weighted_cvar_reproduces_expected_uncovered_below_the_zero_loss_mass` proves it on all three bases, both scopes and α ∈ {0.5, 0.9, 1}. On the prepared thesis EventSet (annual, full sample), P(L_o = 0) is 0.930 for the portfolio and cluster problems and 0.943 to 0.947 for the nine individual problems.

**Beyond it.** Observation 6 found the same design for β = 0.90 to 0.96, and a different one from β = 0.97. So for 0.93 < β ≤ 0.96 the coincidence is a property of these data, not a theorem. That range includes the thesis default β = 0.95 (loaded-pricing A4). "β ≤ 0.97" is off by one grid point.

Observation 4 reasons that VaR₀.₉₅ is about 0 at the design, so CVaR = E[U]/0.05 there, so weighted CVaR has the same minimisers. The last step doesn't follow. `test_var_zero_at_the_expected_uncovered_design_is_not_enough` is a counterexample (β = 0.9, P(L_o = 0) = 0.41):

| | E[U] design | Weighted-CVaR design (α = 1 or 0.9) |
|---|---|---|
| θ | (1, 3), unique | (0, 8) |
| VaR₀.₉(U) | 0 | 1 |
| CVaR₀.₉(U) | 6.3 | 1.9 |
| E[U] | 0.63 | 0.68 |

So the E[U] design has VaR₀.₉ = 0, and the weighted-CVaR design is still a different one.

**Follow-ups.**
1. *[Research] Correct the E[U] coincidence wording in two research notes.*
   - Owns `research/notes/annual-basis-rerun.md` (observation 4) and `research/notes/loaded-pricing.md` (A4).
   - Acceptance: both state the theorem with its condition β ≤ P(L_o = 0), give the measured P(L_o = 0) with its config hash, and call the range above it an observation.
2. *[F-13] Record P(L_o = 0) and flag degenerate tail objectives.*
   - Owns `experiment/runner.py` (the manifest).
   - Acceptance: every run manifest carries P(L_o = 0) per design problem on the calibration measure, and a weighted-CVaR run with β ≤ that value is flagged `degenerate_tail: true` in its manifest (tested).

### F5. The thesis text and the thesis code (the parity source) disagree in four places (clarity, for the paper and the concept pages)

1. **Probabilities.** Thesis eq. (3.3) sets p_i = 1/T, "so that Σ p_i = N/T corresponds to the expected annual event frequency rather than to unity". That is the `event` basis. The thesis code rescales to sum to one (`probability_values / p_sum`), which is `event_conditional`, the parity basis.
   - E[U], MSE and the budget scale by the constant N/T, so their designs agree.
   - The weighted-CVaR designs don't: in the thesis results, β is a share of the events above the threshold, not the annual level the text gives it (§3.1).
2. **CVaR.** Thesis eq. (2.3) defines CVaR_β(L) = E[L | L ≥ VaR_β(L)], but solves the Rockafellar–Uryasev form (3.8). The two differ when there is an atom at the VaR. For U with an atom at 0, E[U | U ≥ 0] = E[U], while the RU value is E[U]/(1 − β). The code computes the RU value everywhere (`objectives.rockafellar_uryasev`, `riskmeasures.var_cvar`, with the atom split). That is the coherent CVaR and the right choice.
3. **Budget.** Thesis (3.15) is an equality with a risk loading, (1 + λ)·Σ p·y = κ·Σ p·s. The code uses `≤` without λ (SPEC §3.1 C8, SPEC §6.4). The difference matters only where the budget is slack, e.g. MSE with κ ≥ 1.
4. **Attachment.** §3.3 (3) says nothing is paid below the attachment; §3.3.1 and the code clip into the first bin (F1).

**Follow-up.** No new issue: MAR-163 and the manuscript state the implemented definitions (RU CVaR; `≤` budget; the basis). Add one paragraph to `parity/REPORT.md` noting that parity reproduces the thesis code, whose probabilities differ from thesis eq. (3.3) (owner: the parity gate's maintainer, MAR-18 follow-up).

### F6. Joint vs individual at the same total budget is fair, but under a load the joint scope also gets a pricing credit (clarity)

**Where.** `constraints.py:90` (one budget per design problem on its own E[L]), `evaluate.py:536` (the portfolio premium prices the aggregate payout), `docs/methodology/pricing.md`.

**Proven.** `test_portfolio_optimum_is_at_most_the_individual_designs_on_the_aggregate` covers all three bases, three objectives, pure and loaded pricing, and five budgets, and shows:
- the individual designs fit the portfolio problem: the same caps, and an aggregate premium ≤ the sum of their premiums ≤ κ·E[Σ_i L_i];
- so the portfolio optimum is at most the individual designs' objective on the aggregate;
- for E[U] and weighted CVaR, that aggregate objective is in turn at most the sum of the individual objectives, because shortfalls net across assets within an event.

This matches thesis (2.9)–(2.11): the same total budget in every scope.

**Unclear.** Under a cost-of-capital load:
- each individual cover is constrained on its stand-alone loaded premium, the joint cover on the aggregate one;
- the joint scope therefore also gains the load's diversification credit, on top of cross-coverage;
- the `premium` KPI at `level = "portfolio"` of an individual or cluster run is not the quantity its budgets constrained. It is up to 0.22 % below the budget on the thesis data (`research/notes/loaded-pricing.md`, A7).
- The in-sample relaxation also doesn't carry over out of sample (MAR-163 already lists this).

**Follow-up.** No new issue: MAR-163's portfolio page separates the two effects (cross-coverage; pricing diversification) and says which premium is budgeted in each scope.

**Erratum (2026-11-02, MAR-174).** "Of an individual or cluster run" should read "of an individual run". The cluster scope (joint, the default) is one design problem (`problem_id` "portfolio"), with one entity per cluster, budgeted on the aggregate premium, so its portfolio `premium` KPI is the quantity its budget constrains. The C1 and loaded-pricing CSVs have one problem per cluster run.

### F7. The cluster scope changes the index, not only the granularity (clarity)

**Where.** `index.py:118-155` (`ValueWeightedIndex`), `scopes.py:182-281`; thesis §2.3.3 ("What changes is only the granularity at which coverage is allocated") and (3.22).

**Observation.**
- `test_one_cluster_per_location_is_the_portfolio_scope`: with one location per cluster, the cluster problem is the portfolio problem (the same index, caps and optimum).
- `test_one_cluster_can_beat_the_portfolio_scope_in_sample`: one cluster on the mean index has MSE 0 where the portfolio scope's best fit has MSE 8.33. The loss occurs only when both winds are high; the mean separates that event, and no sum of per-asset monotone steps can.

So the cluster scope is neither a restriction nor a relaxation of the portfolio scope. A cluster-vs-portfolio difference mixes a change of trigger (the thesis's "zonal basis risk", which can go either way) with the change of calibration.

**Follow-up.** No new issue: MAR-163 states it, and C1 and paper comparisons label cluster results as "different index".

### F8. Per-asset KPIs and payout functions of joint designs are not identified (defect, known: MAR-100, MAR-91)

**Where.**
- `evaluate.py:358-372` writes `level = "entity"` rows for every entity of a joint design (assets in the portfolio scope, clusters in the cluster scope).
- The `payouts` table stores per-entity θ.
- `packages/viz/.../payout_functions.py` draws one panel per entity.

**Observation.**
- The MSE objective of a joint scope depends only on the summed payout per row, so the split across entities is free (MAR-100: up to 0.86 relative between optimal solutions).
- E[U] and CVaR have the same freedom wherever the LP is degenerate (MAR-67, MAR-68).
- The thesis allocates cluster payouts to assets by value weight, eq. (3.23). The core doesn't (MAR-91).
- The KPI figures use the portfolio level only (`kpi_figures.py`), but the payout-function figures and the stored entity rows show one arbitrary member of the optimal set.

**Follow-up.** No new issue: move MAR-100 and MAR-91 out of Backlog before any external output shows per-asset KPIs or per-asset payout functions of a joint design. Interim: MAR-163 and the website say these are not unique.

*Follow-up note (2026-11-01).* Per-asset KPIs: MAR-100 (PR #129, `8e221ca`, covering MAR-91) reports per-location KPI rows only under an explicit allocation rule (`allocation="value"` or `"loss"`; levels `location_by_value`, `location_by_loss`), see [allocating a joint payout to assets](../methodology/payout-allocation.md). The `entity` rows and the stored per-entity θ are unchanged. Payout functions: MAR-218 makes `payout_grid` and `normalised_payout` caption every per-entity panel of a joint design as one of several optimal designs, or refuse it (`joint_entities="refuse"`).

*Follow-up note (2026-11-02).* MAR-222 (PR #149, `738eeda`) covers the rest of the payout outputs: `sweep_figures.payout_sweep` captions a joint design's per-entity payout sweep the same way, or refuses it (`joint_entities="refuse"`), and every `payouts` table of a site bundle carries a `joint` column, with a manifest `joint` section (the rule, the caption to show, the joint runs).

### F9. Clustering features ignore the basis, and their tail can silently be the whole sample (clarity)

**Where.** `clustering.py:164-175`.

**Observation.**
- `ThesisWardClustering.features` always weights rows by `rate / Σ rate`, the event-conditional measure, whatever the run's basis (documented in the module docstring, a thesis port).
- The tail set is `L_port ≥ VaR_β_tail(L_port)`. When at least β_tail of the row probability has zero portfolio loss, the VaR is 0 and the "tail" is every row. The tail features then become whole-sample features without notice.
- On the prepared thesis EventSet 32 % of rows have zero portfolio loss, so the tail is fine there. The unfiltered fixture has 88 %, and D2-like EventSets with many zero-loss storms can cross 90 %.
- The filter didn't change the thesis assignment (checked unfiltered, at 10 m/s and at 20 m/s).

**Follow-up (new issue).** *[F-13] Clustering: refuse or record a degenerate tail.*
- Owns `clustering.py`, `tests/test_clustering.py`.
- Acceptance: when VaR_β_tail(L_port) = 0, `features` raises a typed error (or records the fact, if the owner prefers), and the docstring states that the features use row probabilities on every basis.

### F10. The public API exports two `NotImplementedError` stubs (cleanliness; matters for the public-ready milestone)

**Where.** `__init__.py:20-41` imports `noise` and `robust`. `robust.py:82` (`build_scenario_robust`) and `robust.py:107` (`DistributionallyRobust.build`) raise `NotImplementedError`. `DistributionallyRobust` validates neither `radius` nor `ball`.

**Observation.**
- `pid.robust` advertises R1 and R2, which don't exist yet.
- `pid.noise` is not thesis-only: SPEC §6.3 keeps the noise layer as the baseline next to vulnerability draws, and the runner uses it. It should stay, labelled as that baseline.

**Follow-up (new issue, the "public API" follow-up that ADR 0002 §10 names for `__init__.py`).** *[F-13] Public API surface for v1.*
- Owns `__init__.py`, `tests/test_package_exports.py`, and `robust.py`'s module docstring.
- Acceptance: `pid.robust` is not importable as public API until MAR-34 lands (e.g. renamed `_robust`, or left out of `__init__` and `__all__`); `pid.noise`'s docstring calls it the thesis baseline (SPEC §6.3); the exports test pins the list.

### F11. Docstrings carry process history, and some no longer match the code (cleanliness)

**Where.** 67 lines of the core's top-level modules cite Linear issues ("MAR-143, orchestrator decision: option B", "Until MAR-143 the term wrapped …", "The MAR-14 issue text names a single `build_problem` …"). Stale or wrong statements:

- `interfaces.py:507`: example keys `{"cvar": ..., "eu": ...}`; the code uses `"expected_uncovered"`.
- `noise.py:10-12`: "ADR 0002 records this as the proposed draw-row rate convention". It was adopted in SPEC §5 (MAR-83).
- `eventset.py:1325-1327`: the filter "keeps every row that can trigger a payout". False while bin 0 pays below the attachment (F1).
- `riskmeasures.py:197-198`: "the smallest value v with P(X ≤ v) ≥ β". Not on a step (F2); the caveat is a sentence later.
- `evaluate.py:101-103`: describes `bootstrap.py` as future ("ADR 0002 places them in a new module").
- `pricing.py:169-173` and `problem.py:26-29`: history, not behaviour.

**Follow-up (new issue).** *[F-13] Public-readiness pass on the core docstrings.*
- Owns the docstrings only (no code) of the core's top-level modules, which needs an orchestrator waiver across owners.
- Acceptance: no Linear IDs or decision history in the core's docstrings, except pointers to ADRs and `docs/methodology/`; the stale statements above are fixed; ruff and pyright are clean.

### F12. "portfolio", "loading" and "weighted CVaR" each mean more than one thing (cleanliness)

**Where.**
- `"portfolio"` names a scope (`Portfolio.name`), the `problem_id` of both joint scopes including `Cluster` (`scopes.py:57`), a KPI level, and a KPI `subject_id` (`evaluate.py`, `PORTFOLIO_SUBJECT`).
- `Budget.loading` is κ (thesis `budget_loading`), while "load" is also the cost-of-capital load (`CostOfCapitalLoad.rate`).
- "Weighted CVaR" is a mean–CVaR mixture, not a CVaR with weights.

**Follow-up.** No rename before v1: config compatibility and the parity hashes depend on these names. MAR-163 adds a glossary with the three meanings.

### F13. Duplicated validation and quantile logic (cleanliness)

**Where.**
- `objectives._check_level` (`objectives.py:57`) duplicates `riskmeasures.check_beta` (`riskmeasures.py:66`).
- The "finite real in a range" check is written again in `pricing._real` (`pricing.py:251`), `Budget.__post_init__` (`constraints.py:51-62`), `WeightedCVaR.__post_init__` (`objectives.py:256-265`), `payout._check_range` (`payout.py:56`), `ThesisWardClustering.__post_init__` (`clustering.py:129-141`) and `problem._check_scale` (`problem.py:107`).
- The cluster-count check exists twice: `Cluster.__post_init__` (`scopes.py:215-217`) and `clustering._check_n_clusters` (`clustering.py:262`).
- `clustering._weighted_quantile` (`clustering.py:321`) is a second lower quantile beside `riskmeasures.lower_quantile`, with its own normalisation and without the end clamp.
- Four property-test files repeat the same EventSet maker, numpy measure and tolerances (`test_engine_properties*.py`, and now `test_design_properties.py`, which could not import another owner's helpers).

**Follow-up (new issue).** *[F-13] Shared validators and one lower quantile.*
- Owns a new private `_validation.py`, the call sites above, and a shared `tests/_properties.py` (an ADR 0002 amendment for test-helper ownership).
- Acceptance: one implementation per check with unchanged error types; `clustering` uses `riskmeasures.lower_quantile` if the parity tests stay byte-identical, otherwise the reason is recorded in its docstring; the property tests import one helper module.

### F14. Dead code and STORM (sound for the core; documentation sync pending)

**Observation.**
- The core has no STORM path. The STORM loader lives in the CLIMADA adapter (`packages/climada/.../storm.py`) and is kept unused by owner decision (MAR-62 comment, 2026-10-31).
- SPEC §6.5 (i) and §11 D7 still name STORM; MAR-159 carries that sync.
- The only unimplemented core code is `robust.py` (F10).
- A full dead-code scan was not done.

**Follow-up.** None beyond MAR-159 and F10.

### F15. No guard for a β whose tail is a single outcome (cleanliness, low)

**Where.** `objectives.py:57-70` and `rockafellar_uryasev`.

**Observation.**
- β ∈ (0, 1) is the only check.
- When 1 − β is below the smallest outcome probability, CVaR_β is the single worst outcome. The objective is then a minimax over outcomes, with coefficients of order p/(1 − β).
- α = 0 is special-cased and exact. α = 1, and β → 0, are covered by existing tests.

**Follow-up.** Fold into F4's manifest flag: also record `tail_outcomes = (1 − β) × n_outcomes` and flag values below 1.

### F16. `solve` takes the pricing again, unchecked (cleanliness)

**Where.** `solve.py:439-463`, `solve.py:377-392`.

**Observation.**
- The pricing is used to build the problem and must be passed to `solve` a second time; `solve`'s docstring says "Not checked against the problem: pass the same pricing".
- Pass another pricing and the recorded premium is silently wrong.
- Pass none and a loaded premium is the Rockafellar–Uryasev upper bound.
- The runner does it right; library users can get it wrong.

**Follow-up (new issue).** *[F-13] `BuiltProblem` carries its pricing.*
- Owns `problem.py`, `solve.py`, their tests, and an ADR 0002 amendment (the `BuiltProblem` fields are contract).
- Acceptance: `solve(built)` records `pricing.premium_value` without a `pricing` argument; a `pricing` argument that differs from the built one raises `ComponentConfigError`.

### Module boundaries (ADR 0002): sound

The import graph matches the ownership map. `pricing → objectives.rockafellar_uryasev` is sanctioned (ADR 0002 §10, `objectives.py` row). SPEC §4.2's module table lacks `bootstrap.py`, `riskmeasures.py` and `experiment/kfold.py` (add to MAR-159).

## Sound, with the evidence

- **Uncovered loss and its LP form.** `U_o = Σ_{e∈o} (L_e − π_e)⁺` (`objectives.py:141-144`) is SPEC §6.2 and thesis (2.7) and (3.6). `cvxpy.pos` adds the epigraph u ≥ L − π, u ≥ 0 of thesis (3.6). It is exact because every objective uses U through non-decreasing terms: E[U] has weights ≥ 0, and the CVaR excess `pos(U − ζ)` is non-decreasing in U. DCP enforces this; a component that rewarded U would be refused at build time (`problem.py:259-265`).
- **Rockafellar–Uryasev.** `rockafellar_uryasev` (`objectives.py:73-138`) is thesis (3.8)–(3.9): ζ + p·(U − ζ)⁺/(1 − β), with v added by cvxpy.
  - In the objective, ζ is minimised, so the value is the CVaR at the optimum.
  - In the budget (`pricing.py:210-218`), ζ is free in an upper bound, so the feasible set is exactly {θ : CVaR_q(π) ≤ budget} (ADR 0002 §10, MAR-143).
  - The R2 decomposition (offset α·ζ, per-outcome α·excess + (1 − α)·U) re-weights correctly.
- **Objective = KPI.** `test_objective_value_equals_its_problem_level_kpi` (new) shows that `objective_value` equals `α·cvar_uncovered + (1 − α)·expected_uncovered`, `expected_uncovered`, or `rmse_residual²` from `evaluate.kpis` at `level = "problem"`, on all three bases. The existing engine property tests compare the objective with a numpy objective built on `var_cvar`.
- **Aggregation.** `DesignProblem.loss` is the sum over entities (`interfaces.py:365-368`). The objective-level payout is the sum of the entity payouts (`problem.py:192-197`). The evaluation's portfolio subject sums every location's loss and every entity's payout (`evaluate.py:358-389`). Caps: each entity's in-sample maximum loss (`problem.py:208`), i.e. the asset's in the individual and portfolio scopes and the cluster's aggregate in the cluster scope, as thesis (3.19).
- **Edge cases.**
  - α = 0 builds E[U]'s term exactly (`objectives.py:285-291`; tested on three bases).
  - α = 1 is the pure CVaR (the feasibility properties and the F4 counterexample).
  - β → 0 converges to E[U] (`test_weighted_cvar_converges_to_expected_uncovered_as_beta_goes_to_zero`).
  - β ≤ P(L_o = 0) is degenerate by the F4 theorem.

## New property tests

`packages/core/tests/test_design_properties.py` (12 tests, about 30 s; deterministic hypothesis profile as in MAR-15). Bases: `event_conditional`, `event`, `annual`.

| Test | Proves | Finding |
|---|---|---|
| `test_portfolio_optimum_is_at_most_the_individual_designs_on_the_aggregate` | At an equal total budget, the individual designs fit the portfolio problem (caps; aggregate premium ≤ Σ premiums ≤ κ·E[L], pure and loaded), so the portfolio optimum is ≤ their aggregate objective; for E[U] and weighted CVaR the aggregate objective is ≤ the sum of the parts | F6 |
| `test_one_cluster_per_location_is_the_portfolio_scope` | Singleton clusters reproduce the portfolio problem | F7 |
| `test_one_cluster_can_beat_the_portfolio_scope_in_sample` (×3 bases) | The cluster scope is not a restriction of the portfolio scope | F7 |
| `test_objective_value_equals_its_problem_level_kpi` | The objective a design minimises is the KPI reported for it | Sound |
| `test_weighted_cvar_reproduces_expected_uncovered_below_the_zero_loss_mass` | β ≤ P(L_o = 0): the weighted-CVaR design is an E[U] design, with objective (α/(1 − β) + 1 − α)·min E[U] | F3, F4 |
| `test_var_zero_at_the_expected_uncovered_design_is_not_enough` (×2 bases × 2 α) | VaR_β = 0 at the E[U] design does not make it the CVaR design | F4 |
| `test_cvar_on_an_exact_step_does_not_depend_on_the_order_of_ties` | At β on a step, VaR is one of two adjacent atoms, CVaR is the exact tail mean for every order of ties | F2 |

**Not added:** a filter-invariance property. It fails today (F1, reproduction above), and the property belongs to F1's fix.

## Not verified

- The D2 Florida EventSets aren't on this machine, so F1's impact on the cat-in-a-circle designs is inferred from the published shares (`research/notes/d2-florida-eventset.md`), not measured.
- The thesis PDF was read as extracted text (PDFKit), so the equations were read from a flattened layout. Equation numbers and wording were checked; typography was not.
- No full dead-code scan (F14).
