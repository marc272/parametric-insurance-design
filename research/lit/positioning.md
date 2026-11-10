# Positioning: what the paper claims, and why each claim is new

**Status: agreed with the owner, 2026-10-25 (MAR-28, MAR-84).** Prepared for MAR-28; Marc Prinzing's answers on MAR-28 and MAR-84 are applied here. Evidence is in [`claims-vs-prior-work.md`](claims-vs-prior-work.md), [`notes.md`](notes.md) and [`references.bib`](references.bib).

**Scope of the claims.** The claims below describe what the method *does*. They say nothing about whether tail optimisation performs better than MSE or expected-uncovered-loss designs. Checkpoint C1 (MAR-29) answers that question.

**Setting.** A single risk owner (a corporate, municipal or sovereign body) holds several assets exposed to tropical cyclones. Each asset or cluster gets a monotone, capped step payout driven by its own index. The payouts are calibrated on catastrophe-model event sets under one premium budget. The objective is α·CVaR_β(U) + (1−α)·E[U], where U = (L − π)⁺ is the uncovered loss. The Rockafellar–Uryasev reformulation makes the problem a linear program (SPEC §6).

## Claims

**A. Joint tail-risk calibration of asset-level payouts as one LP.** For one owner, we calibrate a separate payout for each asset jointly, against the owner's *aggregate* uncovered loss and under one shared budget, as one exact LP. The individual, cluster and portfolio scopes are special cases of the same LP. The claim rests on this joint multi-asset scope and on the exact LP.
- *Closest prior work:*
  - Maier & Scherer (2026a, b) design payments for one policyholder at a time, with a mean criterion rather than a tail measure. They name a joint view as future work.
  - Fan, Tan & Zhang (2023) already use CVaR and VaR as the design objective, for one regional contract, solved by random search.
  - Steinmann et al. (2023) choose one product, the same for every site, by an RMSE grid search.
  - Gao, Yang & Liu (2026) measure diversification across independent fixed contracts but do not optimise payouts.
  - The CLIMADA Petals `cat_bonds` module (2026; Bergmüller et al., 2026) gives each subarea of one sovereign issuer its own linear payout. It fits each payout separately by squared error (COBYLA), then sums and caps them. Countries are pooled by a genetic algorithm on an ES-based concentration ratio.
- *Why it is new:* none of these sources calibrates distinct per-asset payouts jointly against an owner's aggregate tail shortfall.
- *Why the claim does not rest on the taxonomy cell:* the thesis places its novelty in the "asymmetric measure × tail aggregator" cell of its taxonomy. That cell does not carry a claim on its own:
  - O1 (`notes.md`) shows that CVaR_β((L−π)⁺) = CVaR_β(L−π) whenever the β-quantile of L−π is non-negative.
  - With a binding budget, the tail term then equals, up to a constant, the hedged-loss CVaR the thesis attributes to Fan et al.
  - The one-sidedness only matters in the E[U] term and on the annual basis.

**B. Scenario-robust calibration across vulnerability and climate scenarios.** Scenario-robust (R1, min–max) calibration of tail-objective step payouts for one owner's assets, jointly over vulnerability and climate-scenario event sets, as one LP, with leave-one-scenario-out tests and the price of robustness. Hazard-model uncertainty is a stated limitation: there is no second hazard catalogue (D7 revisited 2026-10-31, MAR-62). A distributionally robust variant over year weights (R2) is included, conditionally (D6, decided 2026-11-01 at checkpoint C1): MAR-35 starts with a short relevance check, and if R2 doesn't add value or isn't tractable, the fallback is a short appendix or leaving it out.
- *Closest prior work:*
  - Steinmann et al. stress-test an already-chosen product under Knutson-scaled projections, but do not *design* against those scenarios.
  - Birghila & Pflug (2019) solve a distributionally robust AVaR design for *indemnity* contracts, with the premium set on the baseline distribution. Their setting has no index and no basis risk.
  - Zhu & Fukushima (2009) minimise worst-case CVaR over a set of candidate distributions as an LP, applied to investment portfolios.
- *What is new:* the contribution is the computational, multi-asset and empirical setting, not robust parametric design as such. The robust technique is standard. What is new is applying it as one LP over explicit vulnerability and climate-scenario event sets, for several assets of one owner, and evaluating it with leave-one-scenario-out tests and the price of robustness.

**C. How we evaluate.** A supporting contribution, not a claim.
- *What it covers:*
  - CVaR is taken over simulated years, so β has a return-period meaning.
  - Out-of-sample evaluation uses leakage-free year-block splits and bootstrap CIs.
  - The index is a cat-in-a-circle, kept separate from CLIMADA losses that include vulnerability draws.
  - A cost-of-capital load keeps pricing within the LP.
  - Everything ships as an open core library and a CLIMADA module.
- *Closest prior work:*
  - Steinmann et al.: an open CLIMADA framework with a cat-in-a-circle index and a historic check.
  - Maier & Scherer (2026b): cat-in-a-circle on STORM tracks, with premium loading.
  - Fan et al.: out-of-sample comparisons (per the thesis).
- *What it adds:* we found no source that combines these elements for tail-objective design, and none that uses an annual-basis CVaR. This is rigour more than novelty, so the paper presents it as how we evaluate A and B.

## Order and framing

- A is the core claim, B the extension and C the evaluation.
- State the single-owner assumption up front (SPEC M5). Sovereign pools such as CCRIF, and global pooling (Ciullo et al., 2023), involve *several* owners, so cross-coverage there would need a risk-sharing rule, which is out of scope.
