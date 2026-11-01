# Combining the two ideas

The thesis this library comes from[^thesis] has two ideas. The [tail-risk objective](tail-risk-objective.md) sets what a design minimises: the uncovered loss on average **and** in the bad years. [Portfolio calibration](portfolio-calibration.md) sets whose loss counts and which budget applies: one owner's assets calibrated jointly, on their total. Those two pages explain each idea on its own. This page explains them together: the weighted-CVaR objective on the owner's total uncovered loss, in one design problem. It covers what changes against each idea alone, how the two interact, and which view answers which owner's question.

This page describes the method and the code (`objectives.py`, `scopes.py`, `problem.py`), as checked in the [core design review](../reviews/core-design-review.md). It makes no claim that the combination outperforms either idea alone, nor the reverse. In sample, the combined problem does at least as well on its own objective as the individual tail designs at the same total budget, which is a property of the optimisation ([below](#against-each-idea-alone)). Whether it lowers the owner's shortfall in the bad years on years it wasn't calibrated on is an open question of this project.

[^thesis]: M. Prinzing, *Tail-Risk-Optimized Payout Design in Parametric Insurance*, master's thesis, Technical University of Munich, 2026. Not public.

## Two choices, one grid

A design has an objective and a scope, and the code keeps them apart. `pid.problem.build_problems`, which `pid.design` calls:

1. splits the assets into design problems with the scope;
2. sums each design problem's losses and payouts over its entities;
3. builds the objective on those sums, and the constraints, such as the budget, once per design problem.

The objective sees only the summed loss and payout, and the scope never sees the objective. So any objective goes with any scope, and the views are the cells of one grid:

| | `Individual` | `Portfolio` or `Cluster` (joint) |
|---|---|---|
| `ExpectedUncovered` or `MSE` | neither idea | joint calibration alone |
| `WeightedCVaR` | the tail objective alone | **the combination** |

This project studies the two ideas as two research questions, the objective (RQ1) and the scope (RQ2), each on its own and in combination. A config lists scopes and objectives, and the runner runs every pair, so one config can hold all four cells. The thesis config, `parity/configs/thesis.yaml`, lists the three scopes and the three objectives.

## The combined design problem

In the portfolio scope, each asset i keeps its own [step payout](tail-risk-objective.md#setting) of its own index $x_{e,i}$, and the design problem is on the sums over assets:

$$L_e = \sum_i L_{e,i}, \qquad \pi_e = \sum_i \sum_k \theta_{i,k} \mathbf{1}[x_{e,i}\in B_k], \qquad U_o = \sum_{e\in o} (L_e - \pi_e)^+ .$$

U is the owner's total uncovered loss, after [cross-coverage](portfolio-calibration.md#cross-coverage): within an event, a payout at one asset offsets a shortfall at another. The combination minimises the [weighted-CVaR objective](tail-risk-objective.md#the-objective) of this U,

$$F_{\alpha,\beta}(\theta) = \alpha \mathrm{CVaR}_\beta(U) + (1-\alpha) \mathbb{E}[U],$$

under two constraints:

- **Payout shape**, for every asset: $0 \le \theta_{i,0} \le \dots \le \theta_{i,K-1} \le c_i$, with the cap $c_i$ the asset's largest loss in the calibration rows.
- **One budget**, on the total: $\mathrm{Premium}(\sum_i \pi_i) \le \kappa \mathbb{E}[\sum_i L_i]$.

It is one design problem (`problem_id = "portfolio"`) and one LP: the tail page's [linear program](tail-risk-objective.md#the-design-problem-is-a-linear-program), with the payouts summed over the assets. `pid.design` returns one `pid.SolveResult` for it, with one row of θ per asset.

The cluster scope is joint too, and the combination works on it the same way, with one payout function per cluster on the cluster's mean index. That also changes the trigger, so a cluster combination differs from a portfolio one by more than the calibration ([the cluster scope](portfolio-calibration.md#the-cluster-scope)). The rest of this page uses the portfolio scope.

## How the two interact

**The tail objective weights the worst outcomes of the total.** The code builds the objective in the Rockafellar–Uryasev form ([CVaR, as implemented](tail-risk-objective.md#cvar-as-implemented)):

$$\alpha \zeta + \sum_o p_o \Big(\frac{\alpha}{1-\beta} (U_o - \zeta)^+ + (1-\alpha) U_o\Big).$$

With ζ at the VaR of U, one more unit of uncovered loss in outcome o adds to it

- $p_o \big(\tfrac{\alpha}{1-\beta} + 1 - \alpha\big)$ if $U_o$ lies above the VaR;
- $p_o (1-\alpha)$ if it lies below.

At the VaR itself, the weight lies in between. With α = 0.9 and β = 0.95, the thesis config's values, that is 18.1 against 0.1 times the probability: a unit of shortfall in the worst 5 % of outcomes weighs 181 times as much as one elsewhere.

In the combined problem, U is the owner's total, so the outcomes that weigh most are the owner's worst ones (years, on the annual basis): those whose total uncovered loss is in its worst $1-\beta$, for example because several assets are hit at once. Call them the **joint tail years**. Cross-coverage lets the optimiser cover them through whichever asset's index triggers in them, up to that asset's cap, and so also beyond that asset's own loss. So the tail objective decides which years count most, and cross-coverage decides which triggers can pay in them: **cross-coverage is spent on the joint tail years**. Neither idea alone does this:

| | The objective weights | The budget can go to |
|---|---|---|
| Tail objective alone (`Individual`, `WeightedCVaR`) | each asset's own shortfall, with its own worst years weighted up | each asset's own trigger, for its own loss, from its own budget |
| Joint calibration alone (`Portfolio`, `ExpectedUncovered`) | the total shortfall, every outcome by its probability alone | any asset's trigger, for any asset's loss in the same event, from one budget |
| The combination (`Portfolio`, `WeightedCVaR`) | the total shortfall, with the owner's worst years weighted up | any asset's trigger, for any asset's loss in the same event, from one budget |

An asset's own worst years need not be the owner's. A year in which one asset is hit hard and the others are spared can be in that asset's tail but not in the owner's. A year in which every asset is hit moderately can be in the owner's tail but in no single asset's. With `MSE` in place of E[U], over-payments count too, and they net across assets in both directions.

## A worked toy example, not data

Two assets A and B, 20 equally likely years with one event each, two bins ([20, 45) and [45, 70] m/s), the pure premium and κ = 0.5. That is a budget of 0.6 a year in total; in the individual scope, 0.2 for A and 0.4 for B. The weighted-CVaR designs use α = 0.9 and β = 0.9, so the tail is the worst 2 of the 20 years.

| Years | Kind | Index at A | Index at B | Loss at A | Loss at B | Total loss |
|---|---|---|---|---|---|---|
| 2 | both hit | 60 | 30 | 2 | 4 | 6 |
| 1 | A alone | 60 | 30 | 4 | 0 | 4 |
| 1 | false alarm at A | 60 | 30 | 0 | 0 | 0 |
| 4 | B alone | 30 | 60 | 0 | 2 | 2 |
| 12 | quiet | 30 | 30 | 0 | 0 | 0 |

The owner's two worst years are the "both hit" years, and only A's index is high in them. A's high bin pays in 4 years (both hit, A alone, false alarm), B's high bin in the 4 "B alone" years, and B's low bin in the other 16. A's cap is 4, its loss in the "A alone" year.

| Design | θ at A (low, high) | θ at B (low, high) | Payout in a "both hit" year | E[U] of A + B | CVaR₀.₉ of the uncovered loss of A + B |
|---|---|---|---|---|---|
| Neither idea: individual, E[U] | (0, 1) | (0, 2) | 1 | 0.65 | 5 |
| Tail objective alone: individual, weighted CVaR | (0, 1) | (0.4, 0.4) | 1.4 | 0.91 | 4.6 |
| Joint calibration alone: portfolio, E[U] | (0, 1) | (0, 2) | 1 | 0.65 | 5 |
| The combination: portfolio, weighted CVaR | (0, 3) | (0, 0) | 3 | 0.75 | 3 |

- **E[U], in either scope.** B's high bin is the cheapest cover: every unit it pays covers a unit of loss. A unit on A's high bin is paid in 4 years but covers loss in only 3, since nothing is lost in the false-alarm year. So E[U] fills B's high bin up to B's loss of 2, at 0.4 a year, and spends the remaining 0.2 on A's high bin: θ = 1. The individual budgets allow the same split, so here joint calibration alone changes nothing.
- **The tail objective alone.** A's budget allows θ = 1 on its high bin whatever the objective, so A's design stays. B's own worst years are the "both hit" years, where B's index is low. B's design can reach them only through its low bin, which pays in 16 of the 20 years. So it spreads its budget over both bins, 0.4 each: it covers 0.4 of B's loss of 4 in a "both hit" year, and gives up most of its cover in the "B alone" years.
- **The combination.** Its tail is the owner's two "both hit" years, and the trigger that fires in them is A's high bin. In the joint problem, A's payout there can exceed A's own loss of 2 and cover B's loss: cross-coverage, up to A's cap of 4. The whole budget goes to A's high bin, θ = 3, and B's cover is dropped. The owner's shortfall in a "both hit" year falls to 3. The price: no cover in the "B alone" years, and a payout of 3 in the false-alarm year, so E[U] is 0.75.

The E[U] and CVaR columns are the owner's totals in sample, as `pid.evaluate.kpis` reports them at `level = "portfolio"`. In sample, of the four designs, the combined one must have the lowest weighted-CVaR objective on the owner's total, and the joint E[U] design the lowest E[U] ([below](#against-each-idea-alone)); the toy shows nothing more. All four optima are unique, and the library returns these numbers on all three bases, and with α = 1 too.

The combined design relies on A's index for B's losses in the "both hit" years. In a year in which both are hit but A's index stays low, it pays nothing; in a false alarm at A, it pays 3 with nothing lost. That is what the combination risks out of sample, as [cross-coverage](portfolio-calibration.md#cross-coverage) does on its own.

## Against each idea alone

**Against the tail objective alone, at the same total budget, the combined problem relaxes the individual one in sample.** This is the [relaxation of portfolio calibration](portfolio-calibration.md#joint-versus-individual-calibration-at-the-same-budget), with the weighted-CVaR objective. The individual tail designs, used together, are a design of the combined problem: the same payout structure and caps, and an aggregate premium at most the sum of their premiums, which meets the total budget. So, with $F_i$ asset i's own weighted-CVaR objective and $\theta^{\mathrm{ind}}$ the individual designs:

$$\min_\theta F_{\alpha,\beta}(\theta) \quad\le\quad F_{\alpha,\beta}(\theta^{\mathrm{ind}}) \quad\le\quad \sum_i F_i(\theta_i^{\mathrm{ind}}).$$

The first step is the relaxation. The second holds because $(\sum_i a_i)^+ \le \sum_i a_i^+$, and CVaR is monotone and sub-additive: the CVaR of the owner's total shortfall is at most the sum of the assets' own. `test_portfolio_optimum_is_at_most_the_individual_designs_on_the_aggregate` proves both steps with weighted CVaR among its objectives, on all three bases, under pure and loaded pricing.

**Against joint calibration alone, at the same scope and budget.** The combined design and the joint E[U] design are optima over the same set of designs: the objective adds no constraint on θ, so the payout shape and the budget are the same. So, in sample, the combined design has the lower weighted-CVaR objective and the E[U] design the lower E[U]. Neither says by how much.

**When the combination is a joint E[U] design.** The tail page's [theorem](tail-risk-objective.md#when-the-weighted-cvar-design-is-the-eu-design) holds per design problem: if β ≤ P(L_o = 0), the probability of the outcomes without loss, the weighted-CVaR designs are the E[U] designs. In the combined problem, $L_o$ is the owner's total, which is zero only when every asset's loss is zero, because losses are never negative. So its P(L_o = 0) is at most every asset's own, and the theorem covers a narrower range of β than in the individual problems. On the thesis data, the tail page lists 0.930 for the joint problem and 0.943 to 0.947 for the assets (annual basis, setup there): values of the data, not of any design.

**Out of sample, nothing follows.** All three statements are about optima on the calibration data. On other years neither design is optimal, so no ordering of their objectives is implied. The tail objective puts most of its weight on the worst $1-\beta$ of the calibration outcomes, a small share of them, and the joint scope adds the freedom to fit which assets are hit together there and whose index fires. The toy shows how far a design can rely on that. Whether the combination lowers the owner's shortfall in the bad years on other years is a question for the [out-of-sample evaluation](../methodology/out-of-sample.md).

## Which view fits which owner

Each view answers a different question. Which one fits depends on who holds the risk and what the cover is for; this table is not a ranking of the methods.

| Owner | Question | View | Design |
|---|---|---|---|
| One site | How to keep the site's shortfall small in the bad years, not only on average? | The tail objective (RQ1 view) | `pid.Individual()` with `pid.WeightedCVaR(alpha, beta)` |
| Many sites, one owner, an average-fit mandate | How to spend one budget across the sites so that the total shortfall is small on average, or the total payout tracks the total loss? | Joint calibration (RQ2 view) | `pid.Portfolio()` with `pid.ExpectedUncovered()` or `pid.MSE()` |
| Many sites, one owner, a tail mandate | How to spend one budget across the sites so that the total shortfall is small in the owner's bad years? | The combination | `pid.Portfolio()` with `pid.WeightedCVaR(alpha, beta)` |
| Many sites, separate owners | How to cover each owner? | One single-site case per owner: no cross-coverage | `pid.Individual()`, with either kind of objective |

- With one site, the individual and portfolio scopes are the same problem: one design problem with one entity. With one site and an average-fit mandate, neither idea is involved: `pid.Individual()` with `pid.ExpectedUncovered()` or `pid.MSE()`.
- The joint views need a single owner of all the losses and all the payouts ([the use case](portfolio-calibration.md#the-use-case-one-risk-owner)). A payout triggered at one asset helps another asset only if both belong to the same party.
- A tail mandate also sets a level. β sets the tail, the worst $1-\beta$ of the outcomes, and what an outcome is depends on the basis ([β per basis](tail-risk-objective.md#the-objective)); α sets how much of the objective is on the tail.

## Reading a combined design

- **Read the owner's KPIs.** `pid.evaluate.kpis` reports the owner's total at `level = "portfolio"`. For a joint scope, that is also the design problem's row at `level = "problem"`, `problem_id = "portfolio"`. When the KPI β equals the design β, the objective value is α·`cvar_uncovered` + (1 − α)·`expected_uncovered` of that row ([the objective](tail-risk-objective.md#the-objective)).
- **Per-asset results aren't unique** in general. A combined design is a joint design, so its per-asset θ and KPIs show one member of a set of optimal designs ([per-asset results](portfolio-calibration.md#per-asset-results-of-joint-designs-are-not-unique)). The toy's optimum is unique, which isn't true in general.
- **Under a cost-of-capital load**, a comparison with the individual tail designs mixes cross-coverage with a pricing-diversification credit ([two effects](portfolio-calibration.md#under-a-cost-of-capital-load-two-effects)). The load's CVaR is on the aggregate payout. If a combined design pays only in outcomes of total probability at most $1-q$, for example only in the owner's worst years, its premium is $\big(1 - r + \tfrac{r}{1-q}\big) \mathbb{E}[\pi]$, so for r > 0 the budget buys less expected payout than under the pure premium ([when the budget pins it](tail-risk-objective.md#when-the-budget-pins-it)).

## Code map

All modules are in `packages/core/src/parametric_insurance_design/`. After `import parametric_insurance_design as pid`, the components of both ideas are top-level names (`pid.WeightedCVaR`, `pid.Portfolio`, …), and everything else is reached through its module, as `pid.<module>`.

| Concept | Code |
|---|---|
| The combination in one call | `pid.design(eventset, pid.Portfolio(), payout, pid.WeightedCVaR(alpha, beta), *, basis, pricing, constraints, sample, policy)`: one `pid.SolveResult`, `problem_id = "portfolio"`, one row of θ per asset |
| The four views in one config | `scopes: [{kind: individual}, {kind: portfolio}]` and `objectives: [{kind: expected_uncovered}, {kind: weighted_cvar, alpha, beta}]`; the runner runs every scope × objective (`ExperimentConfig.single_runs` in `experiment/config.py`) |
| Sums over entities; one budget per design problem | `pid.problem.build_context` (the summed `loss` and `payout`), `pid.problem.build_problems`, then `pid.solve.solve` for each problem (the low-level path that `pid.design` composes) |
| Weighted CVaR in the RU form | `pid.WeightedCVaR(alpha, beta)`; `pid.objectives.rockafellar_uryasev(values, probability, beta)` |
| Scopes | `pid.Individual`, `pid.Portfolio`, `pid.Cluster(strategy, n_clusters)` with `pid.ThesisWardClustering(beta_tail)`; `pid.scopes.PORTFOLIO_PROBLEM_ID` (`"portfolio"`) |
| Budget and premiums | `pid.Budget(loading)`; `pid.PurePremium`, `pid.CostOfCapitalLoad(rate, q)` |
| The owner's KPIs | `pid.evaluate.kpis`: `level = "portfolio"`, with `expected_uncovered`, `var_uncovered` and `cvar_uncovered` at the KPI β |

## Proven properties

Tests in `packages/core/tests/`.

| Statement | Test |
|---|---|
| `pid.design` builds and solves every scope with every objective, as the low-level path does | `test_workflow.py::test_design_equals_build_problems_then_solve_on_the_fixture` (three scopes × three objectives, parity fixture) |
| At the same total budget, the individual designs fit the portfolio problem, so the combined optimum is at most their objective on the total, which is at most the sum of their own objectives | `test_design_properties.py::test_portfolio_optimum_is_at_most_the_individual_designs_on_the_aggregate` (weighted CVaR among three objectives; all three bases; pure and loaded pricing) |
| The objective value of a combined design equals its problem-level KPI | `test_design_properties.py::test_objective_value_equals_its_problem_level_kpi` (individual and portfolio scopes; all three bases) |
| β ≤ P(L_o = 0) of the joint problem: the combined design is a joint E[U] design | `test_design_properties.py::test_weighted_cvar_reproduces_expected_uncovered_below_the_zero_loss_mass` (individual and portfolio scopes; all three bases) |
