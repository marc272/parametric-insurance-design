# Pricing: pure premium and cost-of-capital load

Issue MAR-27 (F-11), SPEC §6.4 (thesis issue M4). Code: `packages/core/src/parametric_insurance_design/pricing.py`; the portfolio premium in `evaluate.kpis`. Config section `pricing` (`kind: pure` or `kind: cost_of_capital` with `rate` and `q`).

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

The CVaR enters in the Rockafellar–Uryasev form `min_ζ ζ + E[(π − ζ)⁺]/(1 − q)` (`objectives.rockafellar_uryasev`, shared with the weighted-CVaR objective). The minimisation over `ζ` is wrapped in a cvxpy partial minimisation (`cvxpy.transforms.partial_optimize`). When cvxpy compiles the problem it inlines `ζ` and the epigraph variables `u_o ≥ π_o − ζ`, `u_o ≥ 0`, so the LP is exactly the Rockafellar–Uryasev one.

The wrapper is there for the value read back after the solve. With a bare Rockafellar–Uryasev expression, the premium's value at the solution would be the bound at whatever `ζ` the solver returned. That bound equals the CVaR only when the budget binds; with a slack budget, or no budget, it can be larger. The partial minimisation's value is computed by solving the small inner LP over `ζ` with `θ` fixed, so `SolveResult.premium` (and `runs.premium`) is the true loaded premium of the solution in every case. That inner solve uses cvxpy's default solver and agrees with the exact discrete CVaR (`evaluate.var_cvar`) to about 1e-9 relative in the tests.

## Portfolio premium (decision for MAR-27)

`evaluate.kpis` reports a `premium` KPI per design problem and one for the portfolio. Under the pure premium the portfolio premium is the sum of the problem premiums, since the expectation is additive. A cost-of-capital load is sub-additive: the CVaR of a sum is at most the sum of the CVaRs, and less when the tails of the parts fall in different outcomes. So "the portfolio premium" needs a definition.

**Definition:** the portfolio `premium` is the pricing applied to the aggregate payout of the run, the sum of every entity's payout. This is the price of the whole cover if one owner buys it from one writer, who holds capital against the aggregate tail. The rows at `level = "problem"` still price each design problem on its own, and their sum is the price of buying each cover separately.

Consequences:

- `kind: pure`: the portfolio premium is the sum of the problem premiums, as before (up to floating-point summation order).
- A run with one design problem (the portfolio scope): the portfolio premium is the problem premium.
- Individual and cluster scopes under a load: the portfolio premium is at most the sum of the problem premiums. Each design problem's budget constrains its own loaded premium, so the separately priced covers together cost the sum, and the portfolio row shows what the same payouts cost as one cover.

This does not change how designs are calibrated. Each design problem keeps its own budget on its own premium (ADR 0002).

## Not implemented

- A standard-deviation load (`Premium = E[π] + λ·σ(π)`, an SOCP). It would be another class in `pricing.py`.
