# Pricing: pure premium and cost-of-capital load

Issue MAR-27 (F-11), SPEC §6.4 (thesis issue M4). Code: `packages/core/src/parametric_insurance_design/pricing.py`; the portfolio premium in `evaluate.kpis`. Config section `pricing` (`kind: pure` or `kind: cost_of_capital` with `rate` and `q`).

See also: [the tail-risk objective](../concepts/tail-risk-objective.md) (the budget in the design problem) and [portfolio calibration](../concepts/portfolio-calibration.md) (which premium each scope's budget constrains).

## Why

The thesis budget is on the pure premium, `E[π] ≤ κ·E[L]`. A writer of a tail-heavy cover has to hold more risk capital than one of a cover that pays often and little, and charges for that capital. A pure-premium budget therefore makes tail cover look cheaper than it is. The cost-of-capital load prices the payout tail.

## The premium principles

For one design problem, with `π_o` its payout in outcome `o` (the sum over the rows of the outcome; one row per outcome on the `event_conditional` basis) and `p_o` the outcome probabilities:

- **`PurePremium`**: `Premium = E[π] = Σ_o p_o π_o`.
- **`CostOfCapitalLoad(rate=r, q=q)`**: `Premium = (1 − r)·E[π] + r·CVaR_q(π)`, with `CVaR_q(π)` the mean of the worst `1 − q` probability mass of `π`. Equivalently `E[π] + r·(CVaR_q(π) − E[π])`: the expected payout plus a charge `r` on the capital held between the mean and the tail.

The budget is `Premium ≤ κ·E[L]` in both cases (`constraints.Budget`).

Properties of the loaded premium, all tested (`tests/test_pricing.py`, `tests/test_engine_properties_loaded.py`):

- `r = 0` is the pure premium. The component then returns `PurePremium`'s own term, so the problem, the solution and the recorded premium are bit-identical to `kind: pure` (only the config hash differs).
- `E[π] ≤ Premium ≤ CVaR_q(π)`, and the premium is non-decreasing in `r`. So, for the same `κ`, a loaded budget is tighter than a pure one and the optimum is never better.
- Convex in the payout for `r ∈ [0, 1]` and positively homogeneous of degree 1. The design problem stays an LP (a QP with the MSE objective), and loss scaling carries through.
- `rate ∈ [0, 1]` and `q ∈ (0, 1)` are checked by the component itself (`ComponentConfigError`), not only by the config schema.

Paper defaults: `r = 0.06–0.10`, `q = 0.99`, both swept.

## In the optimisation problem

The CVaR enters in the Rockafellar–Uryasev form `min_ζ ζ + E[(π − ζ)⁺]/(1 − q)` (`objectives.rockafellar_uryasev`, shared with the weighted-CVaR objective). The premium term is the function being minimised, with `ζ` a variable of the design problem; when cvxpy compiles the problem it adds the epigraph variables `u_o ≥ π_o − ζ`, `u_o ≥ 0`, so the LP is exactly the Rockafellar–Uryasev one. Its minimum over `ζ` is the CVaR, so the budget admits exactly the payouts whose loaded premium meets it.

The term's value at a solution is the bound at whatever `ζ` the solver returned. That bound equals the CVaR only when the budget binds; with a slack budget, or no budget, it can be larger. So the recorded premium is not read from the term: since MAR-143, `solve.solve(built, policy, pricing=...)` records `SolveResult.premium` (and so `runs.premium`) as `premium_value` of the solution's realised payout, the exact discrete CVaR load computed in numpy (`riskmeasures.var_cvar`, which compares the cumulative probability with `q` strictly, as the thesis; at a `q` exactly on a step of the payout distribution see `docs/methodology/bootstrap.md`, "VaR on a step"), budget binding or not. No solver runs to read a premium, and the recorded premium equals the in-sample `premium` KPI of the design problem bit for bit. The runner always passes the run's pricing. Until MAR-143 the term wrapped the minimisation over `ζ` in `cvxpy.transforms.partial_optimize`, whose value solved an inner LP with cvxpy's default solver (not pinned) on every read, and agreed with the exact value to about 1e-9 relative.

## Portfolio premium (decision for MAR-27)

`evaluate.kpis` reports a `premium` KPI per design problem and one for the portfolio. Under the pure premium the portfolio premium is the sum of the problem premiums, since the expectation is additive. A cost-of-capital load is sub-additive: the CVaR of a sum is at most the sum of the CVaRs, and less when the tails of the parts fall in different outcomes. So "the portfolio premium" needs a definition.

**Definition:** the portfolio `premium` is the pricing applied to the aggregate payout of the run, the sum of every entity's payout. This is the price of the whole cover if one owner buys it from one writer, who holds capital against the aggregate tail. The rows at `level = "problem"` still price each design problem on its own, and their sum is the price of buying each cover separately.

Consequences:

- `kind: pure`: the portfolio premium is the sum of the problem premiums, as before (up to floating-point summation order).
- A run with one design problem (the portfolio scope): the portfolio premium is the problem premium.
- The individual scope under a load: the portfolio premium is at most the sum of the problem premiums. Each design problem's budget constrains its own loaded premium, so the separately priced covers together cost the sum, and the portfolio row shows what the same payouts cost as one cover. The cluster scope, like the portfolio scope, is one design problem (`problem_id = "portfolio"`, one entity per cluster) with its budget on the aggregate payout, so its portfolio premium is the problem premium.

This does not change how designs are calibrated. Each design problem keeps its own budget on its own premium (ADR 0002).

## Not implemented

- A standard-deviation load (`Premium = E[π] + λ·σ(π)`, an SOCP). It would be another class in `pricing.py`.
