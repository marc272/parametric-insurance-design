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

## Family (c): the per-asset noise layer

**Question (MAR-206).** C1 7b read the in-sample joint gain (portfolio − individual, train CVaR₀.₉₉(U), −13.7 to −24.1 % under pure pricing) as the joint designs fitting the per-asset noise layer, which gives each asset's loss its own noise. Rerun the RQ2 comparison without the layer, or with noise common to all assets.

**Setup.** Two new variants of the thesis EventSet, everything else as C1's main line; κ 1; pricing pure and CoC r 0.06; MSE, E[U], weighted CVaR β 0.99 and 0.995; four scopes: individual, cluster (joint), cluster with `joint: false` (MAR-180; the same problems as C1's derived `cluster_separate`), portfolio. 64 runs through the runner, all `optimal` (CLARABEL; OSQP for most MSE runs); no `DegenerateTailError`. Configs `research/configs/c1-rq2-sensitivities/noise_none.yaml` and `noise_common.yaml`; every run's hash in `c_noise_runs.csv` and table C2.

- **none**: `noise: null`. One outcome slot per year (no copies): 7,000 train slots instead of 91,000, so train CVaR₀.₉₉ averages the worst 70 slots instead of 910. The index is the wind at the asset and the loss the base loss of the row: within a row, each asset's loss is a function of its own index.
- **common**: the thesis layer (heteroscedastic, η 0.3, 13 copies, bounds 20/70 m/s, seed 42), but one standard-normal draw per (event, copy) row shared by the 9 assets: factor_j = exp(−σ_j²/2 + σ_j z), σ_j ramping with asset j's index. Each asset's noise has the per-asset layer's marginal distribution; across assets it is comonotone instead of independent. Built by `add_common_noise` in the script (research only, not a library function), EventSet content hash `sha256:a5507206…3b401da` (not committed; the script rebuilds it and checks the hash).
- **per asset**: C1's runs and C1 6b's intervals (`research/data/c1-rq2/scope_paired.csv`), for reference.

Train expected annual loss: 217,083 (none), 214,397 (common), 215,536 (per asset); test 231,743, 231,279, 231,626. The thesis Ward clusters are C1's in both variants (C1 = A1 A2, C2 = A3–A6, C3 = A7–A9; table C4).

Portfolio − individual, CVaR₀.₉₉(U), pure, κ 1 (table C1 has every comparison and both pricings):

| Design | Per asset (C1): train | test [90 % CI] | Common: train | test [90 % CI] | None: train | test [90 % CI] | Hash individual / portfolio, common; none |
|---|---|---|---|---|---|---|---|
| MSE | −13.7 % | −0.9 % [−15.0, +11.1] | −6.0 % | +1.2 % [−8.7, +10.8] | −40.7 % | +25.6 % [−13.0, +65.7] | `563b7fb5a588` / `2c2028e93aca`; `8a536d14c293` / `b66718f9b627` |
| E[U] | −13.9 % | −1.0 % [−15.1, +12.7] | −6.6 % | +0.5 % [−10.0, +11.6] | −43.1 % | +24.2 % [−12.0, +68.8] | `069b27dd498b` / `dfd238a2c8a8`; `c35f4af210e5` / `dc9e808f3455` |
| wCVaR β 0.99 | −17.3 % | −0.9 % [−14.5, +13.7] | −7.4 % | −4.5 % [−18.4, +8.2] | −54.5 % | −5.3 % [−31.6, +26.1] | `959245906ede` / `5fa91b066c77`; `8bc3b5b68cf2` / `e19d234c7a82` |
| wCVaR β 0.995 | −24.1 % | −9.5 % [−20.8, +3.4] | −5.6 % | +5.6 % [−7.4, +18.5] | −53.7 % | −15.4 % [−35.0, +8.8] | `b502ff5322e7` / `cefaade5c69f`; `907e7c345d94` / `f5334b8c5942` |

Observations:

6. **Common noise: the in-sample joint gain is smaller.** Portfolio − individual on train is −5.6 to −7.4 % (four designs, pure), against −13.7 to −24.1 % with the per-asset layer. The joint part of the cluster scope (cluster − cluster `joint: false`) is −2.6 to −3.9 % on train, against −7.9 to −9.8 % (C1 observation 36).
7. **No noise: the in-sample joint gain is larger.** Portfolio − individual on train is −40.7 % (MSE), −43.1 % (E[U]), −54.5 % (β 0.99) and −53.7 % (β 0.995); the joint part of the cluster scope −23.0 to −28.9 %. The individual designs' train CVaR₀.₉₉(U) is 460,022–497,126 here, against 901,744–983,110 with the per-asset layer (C1 section 3.1) and 1,462,893–1,600,626 with common noise.
8. **Out of sample, every portfolio − individual interval contains zero in all three variants** (pure, CVaR₀.₉₉): common −4.5 to +5.6 %; none −15.4 to +25.6 %, with intervals 40–80 points wide.
9. **Train to test, the joint designs rise and the separately calibrated ones do not, in every variant** (pure, CVaR₀.₉₉, table C2):
   - none: individual −26.4 to +1.2 %, cluster `joint: false` −15.4 to +0.2 %, cluster +36.8 to +51.8 %, portfolio +60.5 to +93.1 %;
   - common: individual +10.6 to +24.1 %, cluster `joint: false` +11.3 to +22.7 %, cluster +24.0 to +34.3 %, portfolio +23.7 to +33.5 %;
   - per asset (C1 observation 21): individual −7.9 to +3.5 %, `cluster_separate` −6.8 to +5.9 %, cluster +15.3 to +24.0 %, portfolio +9.9 to +19.0 %.

   The test expected loss is 6.8 % above train with no noise, 7.9 % with common noise and 7.5 % per asset.
10. **Without noise the cluster scope is behind individual out of sample, with intervals excluding zero.** Cluster − individual on test: +82.9 % [+16.2, +156.1] (MSE), +115.9 % [+44.5, +199.8] (E[U]), +53.1 % [+6.2, +112.7] (β 0.99), +43.5 % [+6.5, +89.4] (β 0.995). Both of its parts are positive: the index part (`joint: false` − individual) +26.2 to +64.1 % (E[U] and β 0.99 excluding zero), the joint part +7.6 to +31.6 % (MSE and E[U] excluding zero). With common noise the joint part is +3.7 to +9.0 % (β 0.995: +8.5 % [+1.0, +17.5]) and cluster − individual +6.6 to +13.1 % (β 0.995 excluding zero).
11. **Under CoC r 0.06 the noise layer changes little.** In every variant the train differences between scopes are within ±0.2 % and the test differences within −2.2 to +2.1 %; the intervals excluding zero are E[U]-design cells of at most 0.1 % (table C1, CoC).
12. **The joint designs move payout from the large assets to the small ones in every variant.** The portfolio designs' solver split (pure, train E[π_i]/E[L_i]; one member of the optimal set, see family (b)): A1 0.42–0.54 (common) and 0.54–0.62 (none), A7 2.88–3.29 and 2.69–2.91, A3 2.06–3.14 and 1.53–2.24 (`c_noise_entities.csv`). With the per-asset layer: A1 0.44–0.51, A7 2.66–3.43, A3 2.24–3.09 (C1 T6).

Not run here: the pooled 5-fold comparison (C1 6b.3) for these variants, κ 0.5 and 1.5, r 0.10, other noise seeds, and a variant with the per-asset layer at another η.
