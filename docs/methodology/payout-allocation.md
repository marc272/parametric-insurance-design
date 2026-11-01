# Allocating a joint payout to assets

Issues MAR-100 (F-04) and MAR-91. Code: `evaluate.kpis`, `evaluate.exceedance_curves` and `evaluate.evaluate_results`, argument `allocation`; the levels are in `records.KpiLevel`.

See also: [portfolio calibration](../concepts/portfolio-calibration.md), "Per-asset results of joint designs are not unique".

## Why

A joint design problem (the `Portfolio` or `Cluster` scope) has one objective and one budget, both on the sum over its payout entities. Its optimum is identified through that sum only:

- the MSE objective depends on the summed payout of each outcome alone, so any other split of the same sums across the entities is optimal too;
- E[U] and weighted CVaR have the same freedom wherever their linear program has several optimal solutions.

So the per-entity results of a joint design (the `entity` rows of `evaluate.kpis`, the per-entity θ, per-entity payout functions) show one member of the set of optimal designs, the one the solver returned. Two optimal designs can report different per-asset KPIs. A per-asset number of a joint design is meaningful only under a stated rule that doesn't depend on the solver's choice.

## The rules

An allocation rule splits each design problem's payout π_e, the sum over its entities in row e, across the problem's locations i:

$$\pi_{e,i} = s_{e,i}\,\pi_e, \qquad \sum_i s_{e,i} = 1 .$$

| `allocation` | Share $s_{e,i}$ | KPI `level` |
|---|---|---|
| `"none"` (default) | none: no per-location rows | — |
| `"value"` | $v_i / \sum_k v_k$, with $v$ the insured values (`locations.value`) of the problem's locations | `location_by_value` |
| `"loss"` | $L_{e,i} / \sum_k L_{e,k}$, the location's share of the problem's loss in that row; in a row where the problem has no loss, the value share | `location_by_loss` |

Each location's KPIs are then the usual eight KPIs (expected loss and payout, E[U], VaR and CVaR of U, RMSE of the residual, payout-to-loss ratio, correlation) of its own loss $L_{e,i}$ against $\pi_{e,i}$, on the run's basis and sample. `exceedance_curves` takes the same argument and adds each location's curves.

**The rule is in the level name.** A per-location row is always `location_by_value` or `location_by_loss`, so it can't be read as the solver's split. `evaluate` never writes the plain `location` level.

**Why the whole design problem, not each entity.** The thesis allocates a cluster's payout to its assets by value weight, within the cluster (eq. (3.23)). That fixes the split inside a cluster, but the split across clusters is not unique either. So the `"value"` rule applies the value weights over all the locations of the design problem. With one cluster, the two are the same.

## Properties

All tested in `packages/core/tests/test_evaluate_allocation.py`.

- **The rows depend only on the problem's payout.** Two designs that split the same row sums differently across their entities give identical per-location rows, and so do a portfolio-scope design and a cluster-scope design with the same problem payout. The `entity` rows of those designs differ.
- **Individual scope.** A problem with one location gives it its whole payout under every rule, so its location rows equal its entity rows.
- **Additivity.** The shares sum to 1 in every row, so the locations' expected loss and expected payout add up to their problem's.
  - Under `"loss"`, every location of a row has the same ratio of payout to loss, so they are short, or over-paid, together. Their E[U] also adds up to the problem's.
  - Under `"value"`, E[U] does not add up: an over-payment allocated to one asset doesn't offset another asset's shortfall in the per-asset rows, as it does on the problem's total.
  - VaR, CVaR, RMSE, the ratio and the correlation are not additive under any rule.
- **No premium per location.** Pricing is a component of the design problem, so `premium` is reported at the problem and portfolio levels only.

## Limits

- **A rule is an accounting choice, not the contract.** The location rows describe how the owner's total payout is attributed to assets. They are not the payouts that the per-entity payout functions would make.
- **The problem's payout itself need not be unique.**
  - On the `annual` basis, the MSE objective sees yearly sums only.
  - Out of sample, the per-entity payout functions are applied to new index values. Two designs with the same calibration-row sums can then give different problem payouts.

  An allocation removes the solver's choice of split, not these. The problem- and portfolio-level rows have the same limits.
- **Bootstrap.** `bootstrap.bootstrap_kpis` evaluates without an allocation rule, so it has no confidence bounds for per-location rows.
- **Insured values.** A joint problem whose locations all have value 0 has no value shares, so the `"value"` rule raises `EntityMismatchError`. So does the `"loss"` rule when the problem has a row without loss.

## Reporting

Outputs report per-asset KPIs of a joint design only from rows produced under a rule, and they name the rule. Which rule a given output uses is a reporting decision, recorded with that output.
