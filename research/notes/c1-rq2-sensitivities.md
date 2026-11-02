# C1 RQ2 sensitivities on the thesis portfolio: the noise layer, the cluster count, inaccurate range programs and non-unique joint designs

- Issue: MAR-206 (split from MAR-152 item 6). An addendum to checkpoint C1 (`research/checkpoints/C1.md`, MAR-29; section 6b, MAR-158), which is not edited here.
- **Observations only.** No interpretation and no recommendation: that belongs to the owner. **Publication rule** (C1.md): RQ2 statements are method-only in external outputs; nothing here is for external use as a comparative claim.
- Scripts: `research/scripts/c1_rq2_sensitivities.py` (one `--phase` per family; reads the C1 store and MAR-198's full results, never writes to them) and `research/scripts/c1_rq2_sensitivities_tables.py` (committed CSVs and `tables.md`). Configs: `research/configs/c1-rq2-sensitivities/`. Data: `research/data/c1-rq2-sensitivities/` (`tables.md` holds the tables cited below as A1, B1, …; every CSV row carries its config hash). Hashes here are the first 12 hex digits of the `sha256:` config hash.
- Stores: new runs in a fresh store (`results/c1-rq2-sensitivities/store`, not committed). C1's runs are read from the C1 store, MAR-198's individual end designs and replicates from its full results.

## Setup common to every family

Everything is C1's main line (C1.md section 2) and C1 6b's setup (section 6b.1) unless a family says otherwise:

| Item | Setting |
|---|---|
| Portfolio | Thesis portfolio, 9 Miami assets (`A1`–`A9`); thesis EventSet, content hash `sha256:404b0c3a…5294df`, 10,000 years |
| Basis-risk model | Thesis noise layer: heteroscedastic, η = 0.3, 13 copies, seed 42, independent across assets; threshold 20 m/s on the index (family (c) changes the layer) |
| Basis | `annual`: an outcome is a (year, copy) slot; U = Σ_e (L_e − π_e)⁺ per slot; CVaR over slots |
| Split | Holdout, `train_fraction` 0.7: train years 0–6,999 (in sample), test years 7,000–9,999 |
| CIs | Year-block bootstrap of the test years, B = 1000, seed 0, level 0.9, percentile intervals, on the C1 resample, so every difference is paired |
| Payout, budget | Step payout, 15 bins on [20, 70] m/s; premium ≤ κ·E[L] on the train years, κ = 1 |
| Scopes | individual (9 problems); cluster (thesis Ward, `beta_tail` 0.9, value-weighted index; joint by default, `joint: false` = one problem per cluster, MAR-180); portfolio (1 problem) |
| Designs | MSE; E[U]; weighted CVaR α 0.9 at design β 0.99 and 0.995 (family (b): every C1 design β 0.95–0.995) |
| Pricing | pure; cost of capital r 0.06, q 0.99 (family (b): also r 0.10) |
| KPIs | Portfolio level only: the owner's annual uncovered loss summed over the 9 assets. Per-asset payout of a joint design only under a named allocation rule (B, T6′) or as the solver's split, labelled as such |
| Solver | `solve.DEFAULT_POLICY`; second optima with `c1_rq2.ALT_POLICY` (HiGHS first for LPs, CLARABEL first for QPs) |
| Code | Package `0.1.0.dev0`, branch cut from `origin/main` at 2d55f15 |

Train expected annual loss 215,536; test 231,626 (USD, the fixture's unit), with the per-asset noise layer.

## Family (a): the six C1 T11 range programs that ended `optimal_inaccurate`

**Setup.** C1 T11 (C1.md observation 30) ranged each entity's train E[π_j]/E[L_j] over a joint design's near-optimal set: the design problem's feasible set with objective ≤ optimum·(1 + 10⁻⁵), κ 1, pricing pure and CoC r 0.06. Seven of those programs (six entities) ended `optimal_inaccurate` under CLARABEL and were reported `n/a` (`research/data/c1-rq2/payout_ranges.csv`): pure MSE, cluster C2 (min), portfolio A5 (min, max), A8 (max), A9 (min); CoC r 0.06 weighted CVaR β 0.99, cluster C3 (max), portfolio A6 (max). `--phase inaccurate` re-solves both ends of those six entities:

- **LPs** (weighted CVaR under CoC): CLARABEL (C1's attempt), HiGHS, and CLARABEL with 2,000 iterations.
- **MSE** (a quadratic constraint, the objective ≤ its bound): CLARABEL and SCS (ε 10⁻⁹, 200,000 iterations) on C1's form, with one squared residual per outcome (91,000 outcomes); and both solvers on an **exact compact form** of the same constraint: f(θ) − f* = dᵀHd + 2gᵀd with d = θ − θ*, H = AᵀPA, g = AᵀP(Aθ* − l) over the 135 payout parameters, divided by the allowed excess 10⁻⁵·f* so that its right-hand side is 1. On C1's form the allowed excess is about 10⁻¹⁰ in the problem's scaled units, below the solvers' absolute tolerances.
- **Check**: every solution is recomputed in numpy (objective, budget, payout structure) and counts as in the set if the objective is within 10⁻⁵ + 10⁻⁶ of the optimum, the budget within 10⁻⁶ and the structure within 10⁻⁶ of the cap (MAR-198's check). The joint designs are re-solved first; their objectives equal the stored C1 runs' (rtol 10⁻⁶).

Hashes: pure MSE cluster `80bee12e4c89`, portfolio `4d63dddd3335`; CoC r 0.06 weighted CVaR β 0.99 cluster `a56b270c97e4`, portfolio `a705dea1563a`. Tables A1 (ranges) and A2 (all 44 programs: status, value, check, seconds); data `a_inaccurate.csv`.

| Pricing | Design | Scope | Entity | Stored | C1 T11 range | Re-solved range | From |
|---|---|---|---|---|---|---|---|
| pure | MSE | cluster | C2 | 1.65 | [n/a, 1.71] | [1.60, 1.71] | compact (CLARABEL, SCS agree) / C1 form |
| pure | MSE | portfolio | A5 | 2.24 | [n/a, n/a] | [1.96, 2.56] | compact, CLARABEL |
| pure | MSE | portfolio | A8 | 1.54 | [1.41, n/a] | [1.41, 1.70] | C1 form / compact, CLARABEL |
| pure | MSE | portfolio | A9 | 0.71 | [n/a, 0.76] | [0.68, 0.76] | compact, CLARABEL / C1 form |
| CoC r 0.06 | wCVaR β 0.99 | cluster | C3 | 0.21 | [0.00, n/a] | [0.00, 0.54] | HiGHS |
| CoC r 0.06 | wCVaR β 0.99 | portfolio | A6 | 0.29 | [0.00, n/a] | [0.00, 1.11] | HiGHS |

Observations:

1. **SCS on C1's form does not resolve the MSE programs.** All 8 SCS runs on C1's form ended `optimal_inaccurate` after 220–308 s, with points outside the set (objective excess 0.002 to 5.0, i.e. 0.2 % to 500 %, against an allowed 10⁻⁵); reported ratios such as 0.00 or 26.9 are not members of the set. CLARABEL on C1's form ended `optimal_inaccurate` and outside the set on the same 5 MSE ends as in C1 (excess 1.7·10⁻⁵ to 2.8·10⁻⁴).
2. **The compact form resolves all of them.** CLARABEL on the compact form ended `optimal` and inside the set on all 12 MSE ends (0.1–0.3 s each), with the objective at the bound (excess 0.9999·10⁻⁵ to 1.0000·10⁻⁵). On the four ends that C1's form solved `optimal`, the two forms agree to 0.0005 (C2 max 1.7051 / 1.7046, A8 min 1.4066 / 1.4074, A9 max 0.7601 / 0.7600). SCS on the compact form agrees with CLARABEL on C2 (1.5962, 1.7046) and stays inside the set elsewhere, but ends `optimal_inaccurate` at points short of CLARABEL's ends (A5: 2.16 / 2.34 against 1.96 / 2.56; A8 max 1.55 against 1.70).
3. **The resolved MSE ranges.** Portfolio scope: A5 0.18 of its loss below and 0.32 above the stored 2.24 (range 1.96–2.56); A8 1.41–1.70; A9 0.68–0.76. Cluster scope: C2 1.60–1.71 around the stored 1.65. Every resolved range contains the stored value, and no near-optimal MSE design pays A5, A8 or A9 less than 0.68 of its loss.
4. **The two CoC LPs.** HiGHS ended `optimal`, inside the set: cluster C3 0.00–0.54 and portfolio A6 0.00–1.11. CLARABEL's `optimal_inaccurate` iterates at those ends were inside the set too (0.537 and 1.104), so its status, not its point, was the problem; 2,000 iterations did not change it. So, under CoC, the weighted-CVaR β 0.99 joint designs can pay C3 nothing or 0.54 of its loss, and A6 nothing or 1.11, at the same objective (C1 observation 31 reported their ranges as starting at 0.00 with the top `n/a`).
5. **Every T11 cell now has a value.** With these six rows, C1 T11 has no `n/a` left at κ 1 (pure and CoC r 0.06).
