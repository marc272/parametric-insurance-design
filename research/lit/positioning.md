# Positioning: what the paper claims, and why each claim is new

**Status: draft for owner review.** Prepared for [MAR-28](https://linear.app/marc-prinzing/issue/MAR-28/p-09-literature-review-and-positioning) on 2026-10-25. Marc Prinzing makes every call marked *judgement call*. Evidence is in [`claims-vs-prior-work.md`](claims-vs-prior-work.md), [`notes.md`](notes.md) and [`references.bib`](references.bib).

**Scope of the claims.** The claims below describe what the method *does*. They say nothing about whether tail optimisation performs better than MSE or expected-uncovered-loss designs. Checkpoint C1 ([MAR-29](https://linear.app/marc-prinzing/issue/MAR-29)) answers that question.

**Setting.** A single risk owner (a corporate, municipal or sovereign body) holds several assets exposed to tropical cyclones. Each asset or cluster gets a monotone, capped step payout driven by its own index. The payouts are calibrated on catastrophe-model event sets under one premium budget. The objective is α·CVaR_β(U) + (1−α)·E[U], where U = (L − π)⁺ is the uncovered loss. The Rockafellar–Uryasev reformulation makes the problem a linear program (SPEC §6).

## Candidate claims

**A. Joint tail-risk calibration of asset-level payouts as one LP.** For one owner, we calibrate a separate payout for each asset jointly, against the owner's *aggregate* uncovered loss and under one shared budget. The individual, cluster and portfolio scopes are special cases of the same LP.
- *Closest prior work:*
  - Maier & Scherer (2026a, b) design payments for one policyholder at a time, with a mean criterion rather than a tail measure. They name a joint view as future work.
  - Fan, Tan & Zhang (2023) already use CVaR and VaR as the design objective, for one regional contract, solved by random search.
  - Steinmann et al. (2023) choose one product, the same for every site, by an RMSE grid search.
  - Gao, Yang & Liu (2026) measure diversification across independent fixed contracts but do not optimise payouts.
- *Why it would be new:* none of these sources calibrates distinct per-asset payouts jointly against an owner's aggregate tail shortfall.
- *Judgement call:* the thesis places its novelty in the "asymmetric measure × tail aggregator" cell of its taxonomy.
  - O1 (`notes.md`) shows that CVaR_β((L−π)⁺) = CVaR_β(L−π) whenever the β-quantile of L−π is non-negative.
  - With a binding budget, the tail term then equals, up to a constant, the hedged-loss CVaR the thesis attributes to Fan et al.
  - The one-sidedness only matters in the E[U] term and on the annual basis.
  - **Proposal:** rest claim A on the joint multi-asset scope and the exact LP.

**B. Robust payout design across hazard, vulnerability and climate scenarios.** The payouts minimise the worst case over scenario event sets (R1, an LP). An optional distributionally robust variant (R2) uses a total-variation or χ² ball over year weights. Leave-one-scenario-out tests report the price of robustness.
- *Closest prior work:*
  - Steinmann et al. stress-test an already-chosen product under Knutson-scaled projections, but do not *design* against those scenarios.
  - Birghila & Pflug (2019) solve a distributionally robust AVaR design for *indemnity* contracts, with the premium set on the baseline distribution. Their setting has no index and no basis risk.
  - Zhu & Fukushima (2009) minimise worst-case CVaR over a set of candidate distributions as an LP, applied to investment portfolios.
- *Why it would be new:* the sources we checked contain no robust or distributionally robust design of index-based payouts. The technique is standard; the application and the evaluation would be new.
- *Judgement calls:*
  1. Claiming "first" needs a fuller search before submission.
  2. Jiang & Guan (2018) show that the worst-case mean over a total-variation (L1) ball is a mix of CVaR and the maximum. R2-TV on E[U] therefore stays close to the nominal objective, which bears on D6 (whether to include R2).

**C. Evaluation protocol and open tooling.**
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
- *Why it would be new:* we found no source that combines these elements for tail-objective design, and none that uses an annual-basis CVaR.
- *Judgement call:* this is rigour more than novelty. It could be presented as "how we evaluate", or promoted to the second claim if B leaves the paper.

## Proposed order and framing (owner decides)

- A is the core claim, B the extension and C the supporting contribution.
- State the single-owner assumption up front (SPEC M5). Sovereign pools such as CCRIF, and global pooling (Ciullo et al., 2023), involve *several* owners, so cross-coverage there would need a risk-sharing rule, which is out of scope.
- Maier & Scherer work at the chair that supervised the thesis. How to position against, or coordinate with, their work is the owner's call.
