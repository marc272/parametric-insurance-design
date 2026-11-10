# C1 RQ2 sensitivities on the thesis portfolio: the noise layer, the cluster count, inaccurate range programs and non-unique joint designs

- Issue: MAR-206 (split from MAR-152 item 6). An addendum to checkpoint C1 (`research/checkpoints/C1.md`, MAR-29; section 6b, MAR-158), which is not edited here.
- **Observations only.** No interpretation and no recommendation: that belongs to the owner. **Publication rule** (C1.md): RQ2 statements are method-only in external outputs; nothing here is for external use as a comparative claim.
- Scripts: `research/scripts/c1_rq2_sensitivities.py` (one `--phase` per family; reads the C1 store and MAR-198's full results, never writes to them) and `research/scripts/c1_rq2_sensitivities_tables.py` (committed CSVs and `tables.md`). Configs: `research/configs/c1-rq2-sensitivities/`. Data: `research/data/c1-rq2-sensitivities/` (`tables.md` holds the tables cited below as A1, B1, …; every CSV row carries its config hash). Hashes here are the first 12 hex digits of the `sha256:` config hash.
- Status: complete, 2026-11-02. Families run in the order (a), (c), (d), (e), (b) (family (b) was restarted after a numerical check failed on zero-objective designs; see the script). 208 new runner runs (64 in (c), 144 in (d)), all `optimal`; no `DegenerateTailError`; every solver failure of the range programs is recorded with its status (A2, E1).
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

## Family (b): non-unique joint designs in C1's within-scope comparisons (sections 3–5), and C1 T6 under a named allocation rule

**Question.** C1 sections 3–5 compare the objectives *within* a scope (weighted CVaR − MSE, weighted CVaR − E[U]). In the cluster and portfolio scopes each design is one member of its optimal set (MAR-100). Do other members change those comparisons? And (binding comment from MAR-100) C1 6b.4 and T6 report the solver's per-asset split of the joint designs: re-derive them with a named allocation rule.

**Setup.** Every C1 joint design of sections 3–5: main line, cluster and portfolio scopes, pricing pure / CoC r 0.06 / CoC r 0.10, κ 0.5 / 1 / 1.5, MSE, E[U] and weighted CVaR at design β 0.95, 0.97, 0.98, 0.99, 0.995 (126 designs); and the event-conditional reference column (κ 1, MSE, E[U], weighted CVaR β 0.95; 18 designs). Read from the C1 store and re-solved (objective equal to the stored run's, rtol 10⁻⁶). Each design in four versions:

- `stored`: C1's design;
- `alt`: the same design problem solved with `c1_rq2.ALT_POLICY` (HiGHS first for LPs, CLARABEL first for QPs), a second optimum as in C1 observation 32;
- `free_lo`, `free_hi`: every bin without a train row of its entity's index at its lowest / highest value within monotonicity and the cap (exact optima: they pay the same on every train row; checked). Every KPI is non-increasing in every payout parameter, so the two combinations "weighted CVaR at `free_hi`, other design at `free_lo`" and the reverse give the smallest and the largest difference over the two free-bin families ("free low end", "free high end").

Each version's test KPIs are bootstrapped on the C1 resample (B 1000, seed 0) and every C1 within-scope difference (weighted CVaR minus MSE, minus E[U]; CVaR at each KPI β and E[U]) is recomputed for the combinations C1 / alt, alt / C1, alt / alt and the two free-bin ends. The C1/C1 differences reproduce `research/data/c1/paired_main.csv` and `paired_reference.csv` (1,896 rows: difference and interval bounds, rtol 10⁻⁵). Tables B1 (counts), B2 (the section 3 and 4 cells), B3 (every changed cell), B4 (the `alt` objectives), B5 (free bins); data `b_within_scope_<pricing>.csv` (hashes shortened to 12 digits; full hashes and run ids in `b_designs.csv`), `b_free_bins.csv`.

**T6 re-derived** (tables T6′, data `b_t6_allocation.csv`): `evaluate.kpis(..., allocation="value")` and `allocation="loss"` on the train (and test) years, κ 1, pure and CoC r 0.06, the four designs, both joint scopes, for the `stored` and `alt` designs. The rule splits each **design problem's** payout across its locations (here the whole portfolio, also in the cluster scope): `value` pro rata to insured value, `loss` pro rata to each location's loss in every row. The C1 T6 numbers are the solver's split (`level = "entity"`), labelled so in T6′.

Within-scope differences at κ 1, pure, CVaR₀.₉₉(U), weighted CVaR β 0.99 (C1 section 3.1; table B2 has every pricing and E[U]):

| Scope | Comparison | C1 | alt / alt | C1 / alt | alt / C1 | Free low end | Free high end | Hash wCVaR / other |
|---|---|---|---|---|---|---|---|---|
| cluster | − MSE | −11.9 %* [−24.3, −0.3] | −12.5 % [−27.3, +1.6] | −14.7 %* [−28.1, −2.6] | −9.8 % [−23.4, +4.0] | −11.9 %* | −11.9 %* | `9a25ee86197d` / `80bee12e4c89` |
| cluster | − E[U] | −11.8 %* [−23.2, −1.3] | −9.1 % [−21.1, +1.9] | −11.3 %* [−21.5, −1.7] | −9.7 % [−22.6, +2.4] | −11.8 %* | −11.8 %* | `9a25ee86197d` / `b78a04a941dd` |
| portfolio | − MSE | −14.0 %* [−26.2, −2.1] | −13.0 % [−29.9, +2.2] | −15.2 %* [−29.2, −2.2] | −11.8 % [−25.7, +1.9] | −19.9 %* [−37.6, −4.2] | −8.5 % [−21.4, +4.8] | `7d700f7bd02d` / `4d63dddd3335` |
| portfolio | − E[U] | −14.5 % [−33.5, +0.9] | −17.3 %* [−37.4, −0.9] | −19.5 %* [−42.7, −0.9] | −12.3 % [−31.7, +4.6] | −20.9 %* [−43.9, −1.6] | −9.4 % [−27.2, +6.9] | `7d700f7bd02d` / `08a569620416` |

Observations:

25. **The C1 section 3.1 verdicts depend on which optimum is read.** At κ 1, pure, CVaR₀.₉₉, the four intervals that exclude zero with the C1 designs (cluster and portfolio against MSE, cluster against E[U], C1 observation 1) contain zero when both joint designs are replaced by their `alt` optima (−9.1 to −13.0 %), and the one that contains zero (portfolio against E[U], −14.5 %) excludes it (−17.3 % [−37.4, −0.9]). The point differences stay between −8.5 and −20.9 % in every version (B2).
26. **The second optima have C1's objective.** The `alt` designs' train objective is within 10⁻⁶ (relative) of C1's for every main-line design under CoC, within 1.2·10⁻⁵ in the reference column, and within 6·10⁻⁵ under pure pricing at κ 0.5 and 1 (the largest are MSE designs, CLARABEL against C1's OSQP). At pure κ 1.5 the E[U] and weighted-CVaR optima are 0 (no train shortfall, C1 observation 12): C1's designs have objectives of order 10⁻⁹ and HiGHS's 0, so the relative numbers in B4 (−1 and 6·10²⁷⁸) are of a zero optimum. The pure κ 1.5 MSE portfolio `alt` design is 1.7·10⁻⁴ above C1's objective, outside a 10⁻⁵ set.
27. **Counts over the whole grid (B1).** Of the 720 main-line cells (126 joint designs, 5 design β × 2 comparisons × 2 scopes × 3 pricings × 3 κ × 4 KPIs), replacing both joint designs by their `alt` optima changes 131 interval verdicts (92 lose an exclusion of zero, 39 gain one) and the sign of 167 differences; replacing one of them changes 73–97. The free-bin ends change 16 (low end) and 22 (high end) verdicts. Over the five versions together (340 changed cells, B3), 228 are under pure pricing, 40 under r 0.06 and 72 under r 0.10; at κ 1, 58, 12 and 24.
28. **The event-conditional reference column (C1 section 4) keeps every verdict** under `alt` and the free-bin high end (36 cells each); at the free-bin low end one cell gains an exclusion of zero (CoC r 0.06). Its pure-pricing differences move by at most 5.8 points (−20.7 to −33.4 % over the versions, against C1's −23.0 to −28.0 %; B2).
29. **Under CoC at κ 1 the headline cells keep their verdicts.** Under r 0.06 and r 0.10, weighted CVaR β 0.99 − MSE stays within +0.2 to +4.6 % and − E[U] within −6.2 to −0.1 % at CVaR₀.₉₉ in every version, every interval containing zero (B2), as in C1 observation 3.
30. **The largest changes are at κ 0.5 under pure pricing.** The cluster E[U] design's `alt` optimum has the C1 train objective (relative difference −5·10⁻¹⁰) and a test CVaR₀.₉₉₅(U) of 18,160,197 against 8,349,653 (+117 %; CVaR₀.₉₉ +58 %, E[U] +8 %). With it, the cluster scope's weighted-CVaR − E[U] differences at KPI 0.995 change from −1.7 to +3.4 % to −114 to −120 % of the C1 E[U] value (B3, `b_designs.csv`). C1 observation 37 (the cluster index helping the E[U] design at κ 0.5) uses the C1 member of this design's optimal set.
31. **The design β grid (C1 section 5.1, pure, κ 1, against MSE at CVaR₀.₉₉).** With the `alt` optima the portfolio-scope cells move by up to 4.9 points (β 0.95: +0.5 % to +5.4 % alt / C1; β 0.98: −8.8 %* to −5.6 % alt / alt) and by up to 6.4 points at the free-bin ends; the cluster-scope cells move by up to 3.0 points. With C1's designs β 0.98 and 0.99 exclude zero in the portfolio scope; with `alt` / `alt` neither does; at the free-bin low end both do (−14.6 %, −19.0 %).
32. **Free bins in the joint designs (B5).** In the portfolio scope the same six assets as in the individual scope (MAR-198 T3a) have bins without a train row (A1, A2, A3, A4, A8 one bin; A6 two). In the cluster scope only cluster C1 (A1 A2) has one; C2 and C3 have none. The width of a free parameter reaches the whole cap where its lower neighbour pays 0 (CoC portfolio, A6).
33. **Under a named allocation rule every asset gets about its share of the loss.** Pure pricing, κ 1, train, portfolio scope: rule `value` gives E[π_i]/E[L_i] = 0.94–1.02 for every asset and design, rule `loss` 0.97–1.02, against the solver's split of 0.27–3.43 (C1 T6: A1 0.44–0.51, A7 2.66–3.43). The cluster scope gives the same per-asset values under each rule (0.94–1.02). Under CoC r 0.06 (portfolio scope) rule `value` gives 0.14–0.15 (MSE, weighted CVaR) and 0.27–0.29 (E[U]) and rule `loss` 0.10–0.15 and 0.28–0.36, against the solver's split of 0.00–2.11. Under pure pricing the `alt` optima give the same per-asset values under each rule to within 0.01, while their solver splits differ from C1's by up to 0.12 (A7 MSE 3.43 → 3.31, A6 MSE 0.89 → 1.00). On this portfolio the insured values are close to proportional to the train expected losses, so rule `value` is close to a pro-rata-to-expected-loss split.

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

## Family (d): the cluster count

**Setup.** The cluster scope of C1's main line (thesis Ward, `beta_tail` 0.9, value-weighted index) at n_clusters = 1, …, 9, each **both** jointly calibrated (`joint: true`, C1's cluster scope) and cluster by cluster (`joint: false`, MAR-180), so that the index part (`joint: false` − individual) and the joint part (`joint: true` − `joint: false`) separate at every n. κ 1; pricing pure and CoC r 0.06; MSE, E[U], weighted CVaR β 0.99 and 0.995. 144 runs through the runner, all `optimal`; no `DegenerateTailError`. The individual and portfolio designs are C1's runs, read from the C1 store; every scope of a (pricing, design) group is bootstrapped on the C1 resample. The configs derive from `research/configs/c1/c1_main.yaml` (C1's name and base), so n = 3 with `joint: true` has C1's config hashes and run ids (checked: all 8). Every run's hash: `d_nclusters_runs.csv`, table D3.

Checks: n = 9 puts each asset in its own cluster, whose value-weighted index is the asset's own index. Its `joint: true` designs have the portfolio scope's train objective and its `joint: false` designs the individual scope's, to 6 significant digits, for all 8 (pricing, design) pairs, and their test differences to those scopes are 0.0 % (tables D). At n = 1 the two settings are one problem (difference 0.0 %).

The clusters (table D2): n = 2 splits A1 A2 from the rest; n = 3 is C1's; n = 4 to 8 split off A8, then A7 and A9, then A3 A4 / A5 A6, then A5, A6, then A3, A4; A1 and A2 stay together up to n = 8.

Pure pricing, MSE, CVaR₀.₉₉(U), κ 1 (relative to the second scope; tables D for every design and CoC):

| n | joint − individual: train | test [90 % CI] | index part: test | joint part: train | joint part: test |
|---|---|---|---|---|---|
| 1 | +40.0 % | +47.6 %* [+19.5, +76.3] | +47.6 %* | 0.0 % | 0.0 % |
| 2 | +9.6 % | +11.4 % [−14.7, +38.1] | +15.7 % | −4.8 % | −3.7 % [−9.1, +1.7] |
| 3 (C1) | +2.4 % | +22.7 % [−3.7, +52.7] | +15.6 % | −8.2 % | +6.1 % [−4.3, +16.7] |
| 4 | −0.8 % | +36.7 %* [+10.4, +66.6] | +22.7 %* | −10.6 % | +11.4 %* [+0.4, +23.0] |
| 5 | −3.9 % | +36.4 %* [+12.6, +62.9] | +15.8 % | −13.4 % | +17.8 %* [+4.4, +32.9] |
| 6 | −7.6 % | +24.2 %* [+1.2, +47.7] | +11.9 % | −16.3 % | +10.9 % [−2.4, +25.1] |
| 7 | −9.4 % | +28.5 %* [+4.3, +53.6] | +11.5 % | −17.6 % | +15.2 %* [+2.0, +29.6] |
| 8 | −10.3 % | +22.7 %* [+1.0, +45.6] | +8.9 % | −18.5 % | +12.6 % [−0.2, +26.4] |
| 9 (= portfolio / individual) | −13.7 % | −0.9 % [−15.0, +11.1] | 0.0 % | −13.7 % | −0.9 % [−15.0, +11.1] |

Hashes of the n = 3 `joint: true` runs are C1's (`80bee12e4c89`, `b78a04a941dd`, `9a25ee86197d`, `4f21280640b7` for MSE, E[U], β 0.99, β 0.995 under pure pricing).

Observations:

13. **In sample, the joint part grows with n.** Under pure pricing the joint part (`joint: true` − `joint: false`, train CVaR₀.₉₉) is −4.6 to −6.2 % at n = 2 and −18.5 to −23.0 % at n = 8, for the four designs (−13.7 to −24.1 % at n = 9, the portfolio scope). The index part on train is +21.8 to +43.6 % at n = 1 and +0.1 to +15.5 % at n = 2 to 8.
14. **Out of sample, the joint part is positive at every n from 3 to 8.** On test it is +5.3 to +19.9 % (pure, four designs, n = 3 to 8), with intervals excluding zero in 8 of these 24 cells (MSE n = 4, 5, 7; E[U] n = 5; β 0.99 n = 4, 5, 7, 8; none for β 0.995). At n = 2 it is −3.4 to −3.8 %, intervals containing zero. At n = 9 (portfolio against individual) it is C1's −0.9 to −9.5 %, intervals containing zero.
15. **Joint − individual on test is above zero from n = 4 to 8 for MSE and β 0.99** (+22.7 to +42.2 %, every interval excluding zero), and for E[U] at n = 4 and 5 (+30.3 %, +26.9 %); β 0.995 has +9.7 to +22.8 % with intervals containing zero. The same comparison at n = 9 is −0.9 to −9.5 %. n = 8 differs from n = 9 only in the cluster {A1, A2} with its value-weighted index; for MSE that cluster moves joint − individual on test from −0.9 % to +22.7 % [+1.0, +45.6].
16. **One cluster (n = 1) is behind individual on test for every design under pure pricing**: +30.1 to +53.2 %, every interval excluding zero; and behind the portfolio scope by +43.8 to +54.7 %.
17. **Under CoC r 0.06 the count changes little.** Every train difference is within ±0.3 %; on test every cell is within −2.1 to +2.5 %, and the cells with an interval excluding zero are E[U] cells of at most 0.1 %, the index part at n = 2 for MSE (−2.1 % [−4.3, −0.2]) and joint − portfolio for β 0.995 at n = 1 and 5 (+2.5 %, +1.5 %).

## Family (e): joint − individual over both optimal sets

**Question (MAR-198 follow-up 2, binding comment on MAR-206).** MAR-198 ranged the individual designs only, with the joint designs held at their C1 values. Range the joint − individual differences of C1 6b over both optimal sets together, using C1 T11's joint programs with the KPI as the objective, and separate the empty-bin (free-bin) directions on the joint scopes.

**Setup.** The 16 C1 joint designs at κ 1 (cluster and portfolio; pure and CoC r 0.06; MSE, E[U], weighted CVaR β 0.99 and 0.995), read from the C1 store and re-solved (objectives equal the stored runs', rtol 10⁻⁶). For each, on the test years (E[U], CVaR at 0.95, 0.99, 0.995) and on the train years (CVaR₀.₉₉):

- **Near-optimal set** (C1 T11's, tolerance 10⁻⁵; the MSE constraint in the compact form of family (a)): the smallest portfolio KPI (one convex program, the KPI in its Rockafellar–Uryasev form) and the largest KPI found by successive linearisation from the C1 and the `alt` designs (MAR-198's method, here one LP per step over the joint set; an inner bound). CLARABEL with a second attempt at 2,000 iterations; an iterate outside the set is projected onto it (L∞) and rechecked; every end design is checked in numpy against the set (objective within 10⁻⁵ + 10⁻⁶; all 160 ends pass). The numpy KPIs of the stored designs equal `evaluate.kpis` (rtol 10⁻⁸).
- **Free bins** (exact, tolerance 0): the joint design with every bin that holds no train row of its entity's index at its highest and at its lowest value (family (b)).
- **Individual ends**: MAR-198's, read from its full results (near-optimal method (b) and free-bin method (a); the same C1 resample, so its replicates pair with these). MAR-198's near-optimal MSE ends are not resolved (its section 4, item 9); for MSE the free-bin method is the exact optimal set of the individual design.
- **Differences**: low end = the joint design with the smallest KPI minus the individual design with the largest; high end = the reverse; with paired 90 % intervals of those end designs. The individual design at its C1 value is also reported, to separate the joint designs' share. The C1-design rows reproduce C1 6b (e.g. pure MSE, CVaR₀.₉₉, −0.9 % [−15.0, +11.1]).

Tables E1 (joint ranges, every design, split and KPI, with statuses and hashes) and E2 (differences); data `e_joint_ranges.csv`, `e_rq2_ends.csv`.

Portfolio − individual, test CVaR₀.₉₉(U), relative to the individual C1 design:

| Pricing | Design | C1 designs | Near-optimal: low / high end | Joint near-optimal only (individual C1) | Free bins: low / high end | Hash individual / portfolio |
|---|---|---|---|---|---|---|
| pure | MSE | −0.9 % [−15.0, +11.1] | −7.0 % / +11.1 % (individual: MAR-198 n/a) | −7.0 % / +8.6 % | −8.4 % [−27.2, +6.5] / +4.6 % [−11.6, +19.9] | `b6a790bd484c` / `4d63dddd3335` |
| pure | E[U] | −1.0 % [−15.1, +12.7] | −13.4 % [−33.1, +3.1] / +11.8 % [−5.8, +32.0] | −8.2 % / +8.7 % | −6.9 % / +6.0 % | `9326e4840c25` / `08a569620416` |
| pure | wCVaR β 0.99 | −0.9 % [−14.5, +13.7] | −8.6 % [−21.5, +4.1] / +6.6 % [−9.7, +24.4] | −6.4 % / +5.7 % | −4.3 % / +3.4 % | `f89028d0ef02` / `7d700f7bd02d` |
| pure | wCVaR β 0.995 | −9.5 % [−20.8, +3.4] | −14.3 %* [−23.7, −3.6] / −4.7 % [−17.1, +9.6] | −13.2 %* / −5.3 % | −10.6 % / −8.4 % | `28ac9b153c21` / `af7553a9ab56` |
| CoC r 0.06 | MSE | −0.4 % [−2.9, +2.0] | −2.4 % / n/a | −2.4 % / +1.0 % | −1.4 % / +0.8 % | `af9fe556d6aa` / `0ada0ff98fb2` |
| CoC r 0.06 | E[U] | −0.1 %* [−0.2, −0.0] | −0.2 %* / −0.1 % | −0.2 %* / −0.1 %* | −0.1 %* / −0.1 %* | `3bee2dabbfe6` / `e86fd26ac86f` |
| CoC r 0.06 | wCVaR β 0.99 | +0.7 % [−0.9, +2.5] | −17.3 %* [−28.9, −7.2] / +13.2 %* [+6.0, +20.7] | −13.6 %* / +10.2 %* | +0.2 % / +1.1 % | `9c0222a65bad` / `a705dea1563a` |
| CoC r 0.06 | wCVaR β 0.995 | −1.1 % [−4.8, +1.5] | −9.2 %* [−19.0, −1.1] / +8.1 %* [+3.6, +13.1] | −8.6 %* / +7.6 %* | −1.8 % / −0.2 % | `587393142489` / `f6aa2ce3adec` |

Observations:

18. **In sample the joint designs' tail is fixed by their optimal sets; out of sample it is not.** Over each joint design's near-optimal set the train CVaR₀.₉₉(U) moves by at most −0.6 / +0.4 % (pure) and 0.00 % (CoC, MSE and weighted CVaR; ±0.03 % for E[U]). The test CVaR₀.₉₉(U) moves by −4.1 / +4.6 % (β 0.995) to −7.3 / +9.7 % (E[U]) in the portfolio scope and −0.4 / +1.3 % (β 0.995) to −1.4 / +6.4 % (MSE) in the cluster scope under pure pricing, and by up to −14.2 / +9.5 % (weighted CVaR β 0.99, portfolio) under CoC (E1).
19. **The free-bin family is a small part of that.** The joint designs' free bins (exact optima) move the portfolio scope's test CVaR₀.₉₉ by −0.4 / +1.0 % (β 0.995) to −2.1 / +5.1 % (E[U]) under pure pricing and by at most ±0.6 % under CoC. The cluster designs have no free bins in any of these 16 designs (their cluster index fills every bin), so their free-bin range is 0. The `alt` designs lie inside the near-optimal ranges in every case.
20. **Over both sets, every pure-pricing portfolio − individual interval at CVaR₀.₉₉ contains zero at both ends for MSE, E[U] and β 0.99** (near-optimal ends −13.4 to +11.8 %, free-bin ends −8.4 to +6.0 %). For β 0.995 the near-optimal low end excludes zero (−14.3 % [−23.7, −3.6]), the high end does not (−4.7 % [−17.1, +9.6]); C1's value is −9.5 % [−20.8, +3.4].
21. **The width comes from both sides.** At CVaR₀.₉₉ under pure pricing, the joint near-optimal set alone (individual at C1) spans −8.2 to +8.7 % (E[U]), −6.4 to +5.7 % (β 0.99) and −13.2 to −5.3 % (β 0.995); with the individual set too it spans −13.4 to +11.8 %, −8.6 to +6.6 % and −14.3 to −4.7 % (MAR-198 section 5 found −4.7 to +1.0 % for E[U] from the individual side alone, free bins).
22. **Under CoC the weighted-CVaR joint designs are not identified out of sample.** Portfolio − individual at CVaR₀.₉₉ spans −17.3 % [−28.9, −7.2] to +13.2 % [+6.0, +20.7] (β 0.99) and −9.2 % to +8.1 % (β 0.995), both ends excluding zero in opposite directions, against C1's +0.7 % and −1.1 % (intervals containing zero). Most of it is the joint side: −13.6 % to +10.2 % with the individual design at its C1 value. The free-bin family moves the same differences by at most 0.9 points. Under CoC the train CVaR₀.₉₉ of these designs is fixed by the budget (C1 observation 4), so the near-optimal set leaves the in-sample tail unchanged while the test tail moves.
23. **Cluster − individual (E2).** Pure pricing, CVaR₀.₉₉: the near-optimal high end excludes zero for MSE (+32.9 % [+8.7, +61.9]), E[U] (+28.5 % [+5.1, +57.0]) and β 0.99 (+31.3 % [+0.2, +68.0]); the low ends (+14.1 to +20.9 %) and every free-bin end contain zero, as do C1's values (+21.7 to +25.5 %). For β 0.995 every end at CVaR₀.₉₉ contains zero (+11.4 to +15.1 %) and every end at CVaR₀.₉₉₅ excludes it (+31.3 to +36.0 %).
24. **E[U] as the KPI, β 0.99 design, portfolio − individual (C1 observation 25: −10.9 % [−20.7, +0.2]).** The near-optimal low end is −16.2 % [−25.9, −6.0] and the high end −5.9 % [−17.3, +7.0]; the free-bin low end −13.1 % [−23.1, −2.3] (MAR-198 found −12.0 % [−21.6, −1.3] from the individual side alone).

## Coverage gaps and limitations

- **Holdout only** for the new families: no pooled 5-fold results for (c), (d) and (e); κ 1 only for (a), (c), (d), (e) (family (b) covers κ 0.5–1.5).
- **(c) One realisation per variant.** One seed (42) for the common noise, one η (0.3). The no-noise variant also has 13 times fewer outcome slots, so its tail KPIs average fewer slots.
- **(e) Inner bounds.** The largest values over a near-optimal set are found by successive linearisation (inner bounds). MAR-198's near-optimal MSE ends of the individual designs are not resolved (its section 4, item 9), so the MSE rows of E2 under `near` combine resolved joint ends with MAR-198's unresolved or `n/a` individual ends; the free-bin rows are exact on both sides. An interval at an end is that end design's interval; an interval bound's own extreme over the set can lie further out.
- **(b) Two members, not the set.** `alt` is one other optimum and the free-bin ends are exact optima; the within-scope differences were not ranged over the whole near-optimal sets (E1 has the joint ranges at κ 1, not combined into within-scope ranges here).
- **Allocation rules** split each design problem's payout; they do not make the problem's payout unique (`evaluate` docstring).
- **One portfolio**: the 9 thesis assets.

## Proposed follow-ups (not done here)

1. **Within-scope ranges over the near-optimal sets** (κ 1): combine E1's joint end designs into weighted CVaR − MSE / − E[U] ranges, as family (e) does across scopes. The end designs and replicates are in the full results; this needs a table, not new solves.
2. **The compact MSE form for near-optimal programs**: C1 T11-style programs on the MSE objective resolve in 0.1–0.3 s with the compact quadratic constraint and fail on the per-outcome form. Future range or tie-break tooling (MAR-100 option c) could build on it.
3. **Florida rerun (MAR-152 item 4)**: run families (b) and (e) on the paper portfolio before reading within-scope or cross-scope differences there.
4. **k-fold for (c) and (d)**: pooled 5-fold versions of the no-noise, common-noise and n_clusters rows, as C1 6b.3 did for the main line.
5. **Noise seeds and η** for (c), to see how much of its rows is one realisation.
