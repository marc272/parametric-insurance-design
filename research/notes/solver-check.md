# Solver check: OSQP's false `optimal`, wasted OSQP attempts, and the slow index (b) solves

- Issue: MAR-224 (F-03), from MAR-202 (PR #119, T14). Internal research note, written by a worker agent on 2026-11-02. **Observations and a recommendation with its trade-offs.** The decision on the solve policy is the owner's; `solve.py` is not changed here (a follow-up issue implements what is decided).
- Script: `research/scripts/solver_check.py`, one `--phases` entry per section below. It reads result stores and never writes to one. Data: `research/data/solver-check/` (`attempts.csv`, `florida_osqp.csv`, `thesis_mse.csv`, `stores.csv`, `profile.csv`, `inaccurate.csv`, and one `summary_<phase>.json` per phase). Hashes are the first 12 hex digits of the `sha256:` config hash; every CSV row carries its hash.
- Code and stack: package `0.1.0.dev0`, branch cut from `origin/main` 3e32338 (before MAR-188's 0.1.0 bump); cvxpy 1.9.3, OSQP 1.1.3 (the Python wrapper; its C library prints v1.0.0), Clarabel 0.11.1, HiGHS (highspy) 1.15.1, numpy 2.5.4, scipy 1.18.1; macOS arm64, Python 3.12. The Florida store of MAR-202 was computed on the same package version and stack (its manifests record both), and every re-solve of a stored problem below reproduces the stored objective exactly.
- Seconds are wall-clock seconds on a machine shared with two other workers; compare them within a table, not across notes.

## 1. Summary

1. **Cause of the two false `optimal` designs (T14).** OSQP converged on both problems (its own objective equals the CLARABEL optimum), then its *polishing* step failed to factorise the reduced KKT matrix (`status_polish = −2`, `OSQP_POLISH_LINSYS_ERROR`). On that path OSQP 1.x's `osqp_solve` jumps to its exit label before `store_solution`, so the returned primal vector is the solver's initial one, all zeros, while `info.status` stays `solved`. The OSQP Python wrapper ignores `osqp_solve`'s non-zero return code, and cvxpy maps `solved` to `optimal`. Not the tolerance, the scaling, the stopping rule or the iteration limit: with polishing off, the same 16,600 and 34,250 iterations return the optimum.
2. **The thesis portfolio is not affected.** All 702 MSE QP designs of the committed parity, C1 and site configs, re-solved with the default policy, the thesis policy and a tight CLARABEL reference: no polish linear-system error in 1,551 (default) and 1,569 (thesis policy) OSQP-solved problems, no zero payout, and every default-policy design within 4.0 × 10⁻⁵ of the reference objective. A scan of the stored C1, C1-RQ2 and C1-RQ2-sensitivities designs (640 runs, all with hashes in `research/data/`) finds no OSQP-solved problem with an all-zero payout; the same scan finds exactly the two T14 designs in the Florida store.
3. **OSQP-first wastes half of the Florida solve time.** Half of the Florida store's solver time (84,044 of 176,489 s) went to OSQP attempts that ended `infeasible`, `infeasible_inaccurate` or `user_limit` on MSE problems that are feasible (θ = 0 always is), before CLARABEL solved them. Under cost of capital OSQP never succeeded (420 attempts, 81,307 s); CLARABEL then needed 1,847 s. The same happens on the thesis portfolio, at a smaller scale.
4. **Slow index (b) LPs and `optimal_inaccurate`.** The index (b) problems are 2.3–2.7 times larger (no threshold: every storm in the circle has a category, so every row pays) and need 2.2–2.6 times as many CLARABEL iterations; the `optimal_inaccurate` endings are CLARABEL stopping at its default limit of 200 iterations. With `max_iter` 1000 every re-solved problem ends `optimal` after 204–243 iterations, and HiGHS reaches the same optimum 3–7 times faster. Rescaling the losses does not help. On the 10 re-solved problems the stored inaccurate designs are up to 0.30 % above the optimum in objective.
5. **Recommendation (section 8):** (a) a guard in `solve.py` that treats OSQP's `status_polish = −2` as a failed attempt, needed whatever else is chosen; (b) CLARABEL first for QPs, at tight tolerances, OSQP second; (c) CLARABEL `max_iter` 1000 for all problems. Thesis parity is unaffected by all three as long as `THESIS_POLICY` keeps its solver order and options.

## 2. Setup

| Item | Setting |
|---|---|
| Florida designs | MAR-202's store (`research/notes/florida-rerun.md`, section 2): D2 portfolio (67 counties), annual basis, index (a) wind at the centroid (15 bins on [20, 70] m/s, threshold 20 m/s) and index (b) cat-in-a-circle 75 km (one bin per category 0–5, no threshold), `below_attachment: zero`, pure and cost-of-capital (r 0.06, q 0.99) pricing, κ 0.5/1/1.5, holdout (train years 0–6,999) and pooled 5-fold (pure, κ 1) |
| Thesis-portfolio designs | Every MSE single run of `parity/configs/thesis.yaml` and its sweeps (587), `site/configs/explorer.yaml` and its sweeps (15), C1 main and reference (36, `c1_checkpoint.plan`), C1 F-12 (18 on the EventSets found, below), C1 RQ2 k-fold (30, `c1_rq2.kfold_configs`), C1 RQ2 sensitivities (50, `c1_rq2_sensitivities.plan_nclusters`, `plan_noise`): 736 designs, de-duplicated by config hash. `site/fixtures/thesis_explorer.yaml` has no MSE objective |
| Policies compared | `solve.DEFAULT_POLICY` (QP: OSQP at `eps_abs = eps_rel = 1e-8`, `max_iter` 100,000, polishing on, then CLARABEL; LP: CLARABEL, HiGHS, SCS; `optimal_inaccurate` accepted); `solve.THESIS_POLICY` (the same with OSQP at cvxpy's defaults, `1e-5`, 10,000; parity gate only); **reference**: CLARABEL alone at `tol_gap_abs = tol_gap_rel = tol_feas = 1e-10`, `max_iter` 500 |
| Fresh problems | Every solve is on a newly built cvxpy problem, so nothing is warm-started from an earlier solve |
| Gap | `(objective − reference) / reference`, objective in loss units squared (MSE) or loss units (LPs); a design counts as not optimal above 10⁻³, as in T14 |

## 3. The false `optimal` designs of T14

`--phases florida`; `florida_osqp.csv` (the `clarabel_tight` rows from a second call, `--florida-variants clarabel_tight`). The two designs: index (b), k-fold, pure, κ 1, portfolio scope, MSE, fold 0 (`5318734bca7e`, run `0e496b2db9c8`) and fold 4 (`8dd6c28a7ed9`, run `4973fcdf6e3a`). One problem each: 402 payout parameters (67 counties × 6 categories); OSQP's form has 60,673 variables, 61,411 constraints and 4.33 × 10⁶ non-zeros.

| Fold | Variant | Status | OSQP iterations | `status_polish` | θ all zero | Objective | vs CLARABEL | Seconds |
|---|---|---|---|---|---|---|---|---|
| 0 | OSQP, default policy | optimal | 16,600 | −2 (linsys error) | yes | 2.279697 × 10²¹ | +66.06 % | 261 |
| 0 | OSQP, polishing off | optimal | 16,600 | 0 (not performed) | no | 1.372786 × 10²¹ | −4.3 × 10⁻⁶ | 261 |
| 0 | OSQP, thesis policy (1e-5) | optimal | 225 | −1 (failed, benign) | no | 1.372802 × 10²¹ | +7.3 × 10⁻⁶ | 20 |
| 0 | CLARABEL, default | optimal | 17 (IPM) | – | no | 1.372792 × 10²¹ | 0 | 33 |
| 0 | CLARABEL, tight (reference) | optimal | 20 (IPM) | – | no | 1.372787 × 10²¹ | −4.2 × 10⁻⁶ | 38 |
| 4 | OSQP, default policy | optimal | 34,250 | −2 (linsys error) | yes | 2.480333 × 10²¹ | +66.88 % | 455 |
| 4 | OSQP, polishing off | optimal | 34,250 | 0 | no | 1.486256 × 10²¹ | −3.1 × 10⁻⁶ | 455 |
| 4 | OSQP, thesis policy (1e-5) | optimal | 150 | −1 | no | 1.486282 × 10²¹ | +1.5 × 10⁻⁵ | 21 |
| 4 | CLARABEL, default | optimal | 17 | – | no | 1.486260 × 10²¹ | 0 | 29 |
| 4 | CLARABEL, tight | optimal | 21 | – | no | 1.486256 × 10²¹ | −3.0 × 10⁻⁶ | 40 |

Observations:

1. The default-policy solves reproduce the stored objectives (2.279697 and 2.480333 × 10²¹) and the stored zero payout exactly.
2. OSQP's own record shows it converged: primal residual 1.9 × 10⁻⁸ and dual residual 8.9 × 10⁻¹³ at iteration 16,600 (fold 0, verbose log), and `info.obj_val` 5.3264 × 10⁻⁴ in scaled units, which is CLARABEL's optimum (1.372792 × 10²¹ / scale², scale 1.6054 × 10¹²). The objective of the returned point is that of θ = 0, the expected squared loss (8.845 × 10⁻⁴ scaled).
3. The verbose log then reads "Error in KKT matrix LDL factorization … The problem seems to be non-convex" and "Failed polishing". OSQP's polishing guesses the active constraints and solves a reduced KKT system regularised by `delta` (1e-6); QDLDL failed to factorise that system here. In OSQP 1.x (`src/osqp_api.c`, `osqp_solve`, unchanged on the project's master branch as read on 2026-11-02), a polish error (`polish()` returns > 0, `status_polish = OSQP_POLISH_LINSYS_ERROR`) executes `goto exit`, which skips `store_solution`. The solution vector therefore keeps its value from `osqp_setup`, all zeros, and `info.status` keeps `solved`. `osqp_solve` returns the error code, but the Python wrapper (`osqp/interface.py`, `solve(raise_error=False)`, as cvxpy calls it) does not check it, and cvxpy (`osqp_qpif.py`) maps `solved` to `optimal` and reads `x`.
4. So the cause is a solver-interface defect triggered by a polishing failure, not the tolerance, the scaling, the stopping rule or the iteration limit: polishing off returns the optimum after the same iterations. A *benign* polish failure (`status_polish = −1`: the polished point is not better, so OSQP keeps the ADMM point) is common and harmless: 806 of 1,551 OSQP-solved thesis-portfolio problems (section 4), and both T14 problems under the thesis policy.
5. Why these two problems: the index (b) portfolio MSE problems are the largest OSQP problems of the rerun (index (b) has a paying row for every storm, section 6). The other three index (b) k-fold folds of the same design returned their optimum (T14; fold 2 after 100,000 iterations, `optimal_inaccurate`). Which reduced KKT system QDLDL fails on cannot be predicted cheaply; it can only be detected after the solve.
6. A warm-started OSQP (cvxpy's solver cache, which the core does not use) would return the *previous* solution instead of zeros on this path: still wrong, and harder to spot.

## 4. Can it happen elsewhere? The thesis portfolio

`--phases thesis` (`thesis_mse.csv`) and `--phases stores` (`stores.csv`).

**Re-solves.** 736 MSE designs; 34 are `n_assets` sweep points of the parity config's cluster scope with one or two locations, which fail to build (`n_clusters=3 exceeds the 1 locations`; the parity config has no `cap_n_clusters`, so the runner records these runs as failed too). The other 702 are QPs: the cost-of-capital MSE designs are QPs as well (the premium's CVaR is a linear program), so the default policy tries OSQP on them first.

| | Default policy | Thesis policy | Reference |
|---|---|---|---|
| OSQP-solved problems | 1,551 | 1,569 | 0 |
| `status_polish`: success / failed (benign) / not performed / **linsys error** | 743 / 806 / 2 / **0** | 741 / 824 / 4 / **0** | – |
| Problems with an all-zero returned vector | 0 | 0 | 0 |
| Designs with a fallback to CLARABEL (OSQP attempts `infeasible` / `infeasible_inaccurate` / `user_limit`) | 109 (314 / 47 / 34) | 109 | – |
| Gap to the reference, range | −2.2 × 10⁻⁵ to +4.0 × 10⁻⁵ | −13.1 % to +0.49 % | 0 |
| Designs with gap > 10⁻³ | 0 | 1 (and 10 below −10⁻³) | – |
| Largest constraint violation (scaled) | 2.9 × 10⁻⁷ | 1.4 × 10⁻⁴ | – |
| Solve seconds, all 702 designs | 9,198 | 1,891 | 316 |

By source, the largest |gap| of the default policy is 2.7 × 10⁻⁵ (C1 main), 1.4 × 10⁻⁶ (C1 reference), 2.2 × 10⁻⁵ (C1 F-12), 3.2 × 10⁻⁵ (C1 RQ2 k-fold), 4.0 × 10⁻⁵ (C1 RQ2 sensitivities, `2bcee4d47e3f`, n 8, `joint: false`), 2.1 × 10⁻⁵ (parity), 3.6 × 10⁻⁵ (site). The positive gaps above 3.4 × 10⁻⁷ are designs with problems that OSQP failed (a false infeasibility certificate or the iteration limit, section 5) and CLARABEL at its default tolerances solved (the parity benchmark records the same 5–8 × 10⁻⁶ relative for CLARABEL's default tolerance, `parity/BENCHMARK.md`); designs OSQP solved alone are within −2.2 × 10⁻⁵ to +3.4 × 10⁻⁷ of the reference (median −6 × 10⁻⁸). Base parity designs: individual `e2921efb6439`, cluster `2100f064618d`, portfolio `3d3e150f1b37`, all within 6.1 × 10⁻⁸ under the default policy.

122 of the re-solved designs have their config hash in a committed `research/data/` table: every C1 main, reference, k-fold and sensitivity design, and the 6 F-12 designs on the `cic50` EventSet. The F-12 EventSets with vulnerability draws (`vuln`, `cic50_vuln`) found on this machine are not the ones C1 used (other hashes), and `vuln_basins_null` was not found, so those designs were re-solved on near-identical data only. The parity and site sweeps are not in `research/data/` (the parity gate and the Site workflow record them elsewhere), and were rebuilt from their committed configs.

**Store scan.** The failure has a signature in a store: a problem stored by OSQP whose payout parameters are all exactly zero (a zero payout can be optimal, so a hit is a candidate; no hit rules the failure out). Scanned read-only:

| Store | Runs | Hashes in `research/data/` | OSQP-solved problems | All-zero OSQP payouts |
|---|---|---|---|---|
| C1 (`results/c1/store` of an earlier C1 worktree) | 312 | 312 | 71 | 0 |
| C1 RQ2 k-fold | 120 | 120 | 48 | 0 |
| C1 RQ2 sensitivities | 208 | 208 | 70 | 0 |
| Florida (MAR-202) | 288 | 288 | 754 | **2**: `5318734bca7e`, `8dd6c28a7ed9` |

The C1 store holds all 312 runs of `research/data/c1/runs.csv`, including the F-12 designs on all four EventSets, so the stored C1 designs that the re-solves could not reproduce are covered by the scan. On the Florida store the scan finds exactly T14's two designs, which validates it. MAR-202's T14 already re-solved every other Florida run with an OSQP-solved problem (53 within 9.8 × 10⁻⁶).

**Observation on `THESIS_POLICY` (parity gate only).** At κ < 1, cvxpy's default OSQP accuracy lets MSE designs exceed the budget: parity κ sweep, portfolio scope, κ 0.7 (`7af80da742ab`) premium 1,446,812 against 1,442,976 at the reference (+0.27 %), constraint violation 1.4 × 10⁻⁴ scaled, OSQP `optimal_inaccurate` at its 10,000-iteration limit, objective 13.1 % below the reference; κ 0.8 (`fda7f23b036c`) −9.8 %; C1 main κ 0.5 cluster (`0ca1dd536e99`) −4.7 % and portfolio (`78fbb137bd90`) −2.5 %. One design is 0.49 % above the reference (C1 RQ2 sensitivities, no noise layer, portfolio, `b66718f9b627`). `THESIS_POLICY` reproduces the thesis's MSE solves at κ 1 (MAR-98), so the thesis's own κ < 1 MSE designs may carry the same violations; that was not checked against the thesis outputs. C1 and every research run use the default policy, which stays within 2.9 × 10⁻⁷ scaled of the constraints.

## 5. The cost of trying OSQP first

`--phases attempts` (`attempts.csv`, one row per Florida run, from the manifests' attempt logs).

| Florida, MSE problems | Pure | Cost of capital |
|---|---|---|
| OSQP attempts | 1,104 | 420 |
| … `optimal` / `optimal_inaccurate` | 753 / 1 | 0 / 0 |
| … `infeasible` / `infeasible_inaccurate` / `user_limit` | 349 / 0 / 1 | 318 / 84 / 18 |
| OSQP seconds | 7,268 | 81,307 |
| CLARABEL seconds (after OSQP failed) | 233 | 1,847 |

Every MSE problem is feasible (θ = 0 meets every constraint), so each `infeasible` is a false certificate: OSQP's infeasibility test runs at `eps_prim_inf = 1e-4`, much looser than the `1e-8` optimality tolerance. The policy then falls through to CLARABEL, so no design is wrong, but the time is lost: 84,044 s of the store's 176,489 s of solver time were failed OSQP attempts. Two examples: index (b), CoC, κ 0.5, individual MSE (`6bc55f225203`) took 13,932 s, of which CLARABEL 155 s; index (b), pure, κ 0.5, portfolio MSE (`9827c2e64e5e`) took 2,531 s, of which CLARABEL 51 s. If OSQP were the last solver of a list (as in `c1_rq2.ALT_POLICY`, CLARABEL then OSQP), a false certificate would raise `InfeasibleError`: loud, not silent.

The thesis portfolio shows the same pattern at a smaller scale (section 4): 395 failed OSQP attempts in 109 designs, 71 of the 73 cost-of-capital designs among them. C1 main under cost of capital: 45–104 s per design under the default policy against 0.3–2.7 s for the reference CLARABEL solve (e.g. κ 1 portfolio `0ada0ff98fb2`: 86.4 s against 0.74 s).

## 6. Why index (b) is slow

`--phases profile` (`profile.csv`): six counties of the individual scope, CoC r 0.06, κ 0.5, each problem solved by CLARABEL at its defaults; E[U] (`3bec11b738dd` (a), `7a89caa222d1` (b)) and MSE (`dfa1f449c947` (a), `6bc55f225203` (b)). Counties 12003, 12081 and 12107 ended `optimal_inaccurate` in the store under index (b); 12001, 12015 and 12099 ended `optimal`.

| Per county problem | Index (a) | Index (b) |
|---|---|---|
| Train rows (storm × draw) | 37,270 | 97,710 |
| Annual outcomes | 29,041 | 52,391 |
| Outcomes with a paying row | 5,330–7,210 | 52,390 |
| E[U] LP: variables / constraints / non-zeros (CLARABEL form) | 66,327 / 132,667 / 2.0–2.1 × 10⁵ | 150,108 / 300,220 / 5.6 × 10⁵ |
| E[U]: CLARABEL iterations, status | 76–90, all `optimal` | 187–200; the three stored-inaccurate counties reach the limit of 200 and end `optimal_inaccurate` |
| E[U]: seconds | 2.6–3.4 | 16.2–18.1 |
| MSE QP: CLARABEL iterations, seconds | 17–20, 0.5–0.7 | 20–22, 1.3–1.7 |
| Distinct index values per paying bin | up to 176 | 1 (a category per bin, by construction) |
| Distinct annual payout patterns (rows of the annual basis matrix) | 26–35 | 36–41 |
| Loss scale and range | identical (the same loss matrix) | identical |

Observations:

1. **Size.** Index (b) has no threshold and every storm within 75 km has a category ≥ 0, so every row lands in a paying bin and all but one of the 52,391 outcomes have a paying row. Index (a)'s threshold of 20 m/s keeps 38 % of the rows. The LP is 2.3–2.7 times larger.
2. **Iterations.** CLARABEL needs 2.2–2.6 times as many interior-point iterations on the index (b) LPs, close to its default limit of 200. Size times iterations gives the 5–6 times longer solves per county; the 5–10 times of the issue are these factors on the LPs, plus, on the MSE problems, the failed OSQP attempts of section 5 (index (b) CoC MSE runs: 13,932–15,858 s, against 2,281–4,968 s for index (a)).
3. **Not the loss scale.** Both indices have the same losses, scale and range (the smallest positive scaled annual loss is as small as 4 × 10⁻²⁷ in both); rescaling the losses does not help (section 7). The number of distinct annual payout patterns is similar (26–41) in both.
4. The MSE QPs themselves are easy for CLARABEL on both indices (17–22 iterations, under 2 s).

## 7. The `optimal_inaccurate` endings

`--phases inaccurate` (`inaccurate.csv`): 10 stored `optimal_inaccurate` problems of individual-scope holdout designs (up to two per design): index (b) CoC E[U] at κ 0.5 (`7a89caa222d1`), 1 (`9e36ee96f4c3`), 1.5 (`040a79743218`); weighted CVaR β 0.995 at κ 0.5 (`7bde56da18d3`) and 1 (`d046ebc331cc`); and index (a) CoC E[U] κ 1.5 (`49722193ffa3`). All LPs. Each re-solved four ways.

| Variant | Status | Iterations | Objective against the stored one | Seconds |
|---|---|---|---|---|
| CLARABEL, default (the stored solve) | `optimal_inaccurate` (10 of 10) | 200 | equal (all 10) | 6.9–34.8 |
| CLARABEL, `max_iter` 1000 | `optimal` (10 of 10) | 204–243 | −2.9 × 10⁻⁷ to −3.0 × 10⁻³ | 7.4–36.1 |
| HiGHS | `optimal` (10 of 10) | 2,179–10,272 (simplex/IPM) | the same as CLARABEL at 1000 to ≤ 7.3 × 10⁻⁷ relative | 1.2–6.7 |
| CLARABEL on losses scaled by 1/10 of the default scale | `optimal_inaccurate` 8, `user_limit` 1, `optimal` 1 | 192–200 | −4.3 × 10⁻⁴ to +1.4 × 10⁻³ | 7.6–29.1 |

Observations:

1. The endings are CLARABEL's iteration limit: at 200 iterations its reduced tolerances are met (`AlmostSolved`, which cvxpy maps to `optimal_inaccurate`); a few more iterations reach full accuracy. On the CoC E[U] runs at κ 1 and 1.5 most problems stop at 200 *without* reduced accuracy (`user_limit`, 108 problems in the store) and HiGHS, the next solver, solves them (`attempts.csv`).
2. The stored inaccurate designs are 0.11 %, 0.27 % and 0.30 % above the optimum on three of the ten problems (E[U], κ 1: 12013, 12029; κ 1.5: 12005) and within 3 × 10⁻⁵ on the others; their largest payout parameter differs from the optimum's by up to 2.5 % (12029).
3. Rescaling the losses does not remove the endings; neither scale is the issue.
4. HiGHS's design for the index (a) problem (12103) has the same objective but a very different payout vector (largest parameter 1.7 × 10¹¹ against 8.0 × 10⁹): an LP with a non-unique optimum (bins without a train row, MAR-100, MAR-198). A solver change for LPs changes designs on non-unique problems even when the objective agrees.

## 8. Recommendation and trade-offs

The owner decides; implementing any of this in `solve.py` is a separate issue. In order of priority:

**(a) Guard against OSQP's polish linear-system error (recommended in every case).** In `solve._try`, after an OSQP solve with an accepted status, read `problem.solver_stats.extra_stats.info.status_polish`; if it is −2 (`OSQP_POLISH_LINSYS_ERROR`), record the attempt as `solver_error` ("OSQP polishing failed to factorise; solution not stored, OSQP 1.x") and try the next solver. A more general variant compares OSQP's `info.obj_val` with the objective at the returned point.

- Exact: it catches the defect itself, and only it. On both T14 problems CLARABEL is next and returns the optimum.
- Changes no design that does not hit it: none of the 3,120 OSQP-solved thesis-portfolio problems (both policies) hit it, so parity, C1 and the site are unchanged. The Florida designs of T14 become correct.
- Small: no new dependency, no change to the policy's fields, so no change to policy fingerprints or run ids.
- Depends on solver internals: it reads the OSQP result object that cvxpy keeps in `solver_stats.extra_stats` (cvxpy 1.9.3 here) and OSQP 1.x's polish codes. OSQP < 1 (older environments, e.g. the core's lowest-direct CI job may resolve one) was not checked here; the guard should do nothing when `extra_stats`, `info` or the code is missing.
- Alternatives: `polishing: False` in `OSQP_OPTIONS` also avoids the defect (section 3) but changes the 743 thesis-portfolio problems where polishing succeeds (slightly) and the policy fingerprint, so every default-policy run id. A zero-payout check is weaker (zero can be optimal, and a warm-started OSQP would return a stale non-zero point) and is not recommended alone.

**(b) CLARABEL first for QPs, at tight tolerances, then OSQP.** `qp_solvers = ("CLARABEL", "OSQP")` with `CLARABEL: tol_gap_abs = tol_gap_rel = tol_feas = 1e-10` (the reference of section 4; `max_iter` as in (c)).

- Evidence: all 702 thesis-portfolio QP designs `optimal` (316 s against 9,198 s under the default policy); the default-policy designs lie within 4.0 × 10⁻⁵ of it. On the T14 problems 20–21 iterations, 38–40 s, against 261–455 s for OSQP. On Florida, it removes the 84,044 s of failed OSQP attempts (half the rerun's solver time) and the false certificates.
- Accuracy: at these tolerances CLARABEL matches OSQP at 1e-8: designs OSQP solved alone are a median 6 × 10⁻⁸ below the reference, with constraint violations up to 2.9 × 10⁻⁷ scaled (median 6 × 10⁻¹²); the reference's largest violation is 7 × 10⁻¹⁵. At CLARABEL's *default* tolerances the gap would be up to 4 × 10⁻⁵ (section 4), larger than MAR-98's 1e-8 target; hence the tight tolerances.
- Cost: every default-policy MSE design changes slightly (objective within ≤ 4 × 10⁻⁵, payouts more, since the objective is flat at its optimum: MAR-98 measured KPI shifts up to 2 % at OSQP's 1e-5) and the policy fingerprint changes, so every run id of a default-policy run changes and stores are recomputed. C1's and the Florida rerun's committed numbers stay as they are (they cite their run ids) until rerun. OSQP stays in the list as the fallback, so (a) is still needed.
- Thesis parity: unaffected if `THESIS_POLICY` keeps OSQP first at cvxpy's defaults (it is a separate policy).

**(c) CLARABEL `max_iter` 1000 (from cvxpy's default 200) for LPs and QPs.**

- Evidence: all 10 re-solved `optimal_inaccurate` problems end `optimal` at 204–243 iterations, removing objective errors of up to 0.30 % (section 7); problems that already converge are unaffected.
- Cost: changes the policy's options, so run ids change (as in (b)); a problem that would have ended `user_limit` at 200 now runs longer before HiGHS takes over.
- Alternatives considered: `accept_inaccurate = False` would hand the 69 inaccurate Florida LPs to HiGHS (on the 10 re-solved, HiGHS reaches the optimum) but departs from the thesis rule and raises `SolveError` when every solver is inaccurate. HiGHS first for LPs is 3–7 times faster on these problems but changes designs where the LP optimum is not unique (observation 7.4), which bears on MAR-100 and MAR-198. Rescaling: no effect (section 7).

**Release (MAR-189).** The thesis portfolio, C1 and the site are not affected by the defect. Without (a), core 0.1.0 can return a zero-payout MSE design with status `optimal` on large problems where OSQP's polishing fails to factorise (observed on 2 of 754 OSQP-solved Florida problems); the result would be detectable only by a re-solve or the store scan above.

## 9. Not done, and limits

- `solve.py` is unchanged (issue scope). Recommendations (a)–(c) need the owner's decision and a follow-up issue; (a) is independent of (b) and (c).
- MAR-140 (re-timing the annual basis at 50 vulnerability draws, CLARABEL against the HiGHS fallback) has no note yet; sections 6 and 7 bear on it (CLARABEL's iteration limit is what sends problems to HiGHS here).
- The F-12 `vuln`, `cic50_vuln` and `vuln_basins_null` C1 designs were not re-solved on C1's own EventSets (section 4); their stored designs are covered by the store scan only.
- The THESIS_POLICY budget violations at κ < 1 (section 4) are recorded, not traced into the parity report's κ-sweep rows.
- Timings are on a shared machine; the ratios within a table are the comparable numbers.
