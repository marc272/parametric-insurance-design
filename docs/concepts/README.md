# Concepts

The two ideas this library is built on, explained as the code implements them:

- [The tail-risk objective](tail-risk-objective.md): the uncovered loss, the weighted-CVaR objective α·CVaR_β(U) + (1 − α)·E[U], why the design problem is a linear program, the premium budget, and when the objective reduces to E[U].
- [Portfolio calibration](portfolio-calibration.md): the individual, portfolio and cluster scopes, cross-coverage for a single risk owner, and what joint calibration does and doesn't guarantee.

How each feature is evaluated (the bases, out-of-sample splits, the bootstrap, loaded pricing) is in [`docs/methodology/`](../methodology/). These pages describe the method and the tool. They make no claim that either idea outperforms the alternatives.

## Glossary

Three words carry more than one meaning in the code (review finding F12). The names stay as they are, because configs and stored results depend on them.

**portfolio**
- The scope `scopes.Portfolio` (`kind: portfolio`): one payout function per asset, calibrated jointly.
- The `problem_id` of the single design problem of **both** joint scopes, `Portfolio` and `Cluster` (`scopes.PORTFOLIO_PROBLEM_ID`).
- A KPI level, `level = "portfolio"` in `evaluate.kpis`: every asset's loss and every entity's payout of a run, summed. Its `problem_id` is `"*"` when the run has several design problems, as in the individual scope.
- A KPI subject, `subject_id = "portfolio"` (`evaluate.PORTFOLIO_SUBJECT`).
- In prose: the set of assets of one owner, such as the thesis's 9 Miami assets or the paper's 67 Florida counties.

**loading**
- `Budget.loading` is κ, the budget loading (the thesis's `budget_loading`): Premium ≤ κ·E[L].
- It is not the **cost-of-capital load**, `CostOfCapitalLoad(rate=r, q=q)`, which is part of the premium: (1 − r)·E[π] + r·CVaR_q(π).
- The thesis text's risk loading λ (its eq. (3.15)) is not implemented. The thesis code didn't use it either (SPEC §3.1, C8).

**weighted CVaR**
- The objective α·CVaR_β(U) + (1 − α)·E[U] (`objectives.WeightedCVaR`, `kind: weighted_cvar`), with α the weight of the CVaR term.
- It is a mixture of the mean and the CVaR of the uncovered loss. It is not a CVaR computed with weights on the outcomes, nor an average of CVaRs at several levels.

Other terms used on these pages:

- **Uncovered loss** U: the loss left after the payout, summed over the events of an outcome, $U_o = \sum_{e\in o}(L_e - \pi_e)^+$.
- **Design problem**: one optimisation, with one objective and one budget. One per asset in the individual scope; one in each joint scope.
- **Payout entity**: whatever gets its own payout function: an asset, or a cluster of assets.
- **Basis**: what an outcome is (a year, an event, or an event given the threshold filter) and its probability; see [the evaluation basis](../methodology/annual-basis.md).
