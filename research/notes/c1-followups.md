# C1 follow-ups on the thesis portfolio (RQ1): CoC q ≠ KPI β, design β above 0.99 on draws, budget use, bootstrap coverage

- Issue: MAR-205 (split from MAR-152 items 1, 2, 3 and 5). An addendum to checkpoint C1 (`research/checkpoints/C1.md`, MAR-29).
- **Observations only.** No interpretation and no recommendation: that belongs to the owner. RQ1 statements here hold for the stated setup only (publication rule, AGENTS.md).
- Script: `research/scripts/c1_followups.py` (one `--family` per run family). Grid: `research/configs/c1-followups/followups.yaml`. Data: `research/data/c1-followups/`. Hashes in this note are the first 12 hex digits of the `sha256:` config hash; the `*_runs.csv` tables have the full config hash and run id of every run.
- Status: families 3 (budget use) and 1 (CoC q) below. Families 2 and 4 are added as they finish.
- Per run family, `research/data/c1-followups/` holds `<family>_runs.csv` (every run: config hash, run id, solver status, budget use, train E[π]), `<family>_kpis.csv` (portfolio KPIs: test with 90 % intervals, train point values, at every KPI β), `<family>_paired.csv` (paired differences on the test years), `<family>_summary.json` and `tables_<family>.md` (generated: every run's train and test CVaR, every paired difference with its interval and both hashes).

## Setup common to every family

Everything is C1's main line (`research/checkpoints/C1.md` section 2) unless a family says otherwise:

| Item | Setting |
|---|---|
| Portfolio | Thesis portfolio, 9 Miami assets (`A1`–`A9`); thesis EventSet, content hash `sha256:404b0c3a…5294df`, 10,000 years |
| Basis-risk model | Thesis noise layer: heteroscedastic, η = 0.3, 13 copies, seed 42; threshold 20 m/s on the index |
| Basis | `annual`: an outcome is a (year, copy) slot, U = Σ_e (L_e − π_e)⁺ per slot; CVaR over slots |
| Split | Holdout, `train_fraction` 0.7: train years 0–6,999, test years 7,000–9,999. Train values are in-sample |
| CIs | Year-block bootstrap of the test years, B = 1000, seed 0, level 0.9, percentile intervals; designs of one (variant, scope) share the resample, so differences are paired |
| Payout | Step, 15 bins on [20, 70] m/s |
| Scopes | individual (9 problems), cluster (3 clusters, thesis Ward, `beta_tail` 0.9), portfolio (1 problem) |
| Designs | MSE; E[U] (`expected_uncovered`); weighted CVaR, α = 0.9, design β as stated |
| Budget | premium ≤ κ·E[L] on the train years |
| KPIs | Portfolio level only (no per-asset KPIs of joint designs, MAR-98/MAR-100) |
| Solver | `solve.DEFAULT_POLICY` |
| Code | Package `0.1.0.dev0`, `origin/main` at 7f56a22 (MAR-228 merged) |

Train expected annual loss 215,536; test 231,626 (USD, the fixture's unit).

## Family 3: budget use next to the tail KPI in C1's κ sweep (MAR-152 item 3)

**Setup.** No new runs: C1's main-line κ sweep (κ 0.5, 1, 1.5; pure, cost of capital r 0.06 and r 0.10 with q 0.99; every scope), read from the committed C1 tables (`research/data/c1/runs.csv`, `kpis_main.csv`). `python research/scripts/c1_followups.py --family budget` writes `research/data/c1-followups/budget_use.csv` (every design, including β 0.95–0.98).

- **Budget use** = sum of the design problems' train premiums / (κ · train E[L]): the constraint each run satisfies. The portfolio premium KPI (premium of the aggregate payout, MAR-27) is in the CSV as `portfolio_premium_use`; it equals the budget use to 3 decimals except in ten individual-scope rows under the load (E[U] and weighted CVaR β ≤ 0.99 at κ 0.5 or 1.5), where it is 0.9976–0.9994.
- **Payout ratio** = train E[π] / train E[L].
- **Test CVaR₀.₉₉(U)**: the C1 value on the test years (intervals in `budget_use.csv` and C1 `tables.md`).

Each cell: budget use · payout ratio · test CVaR₀.₉₉(U) in thousands.

| Pricing | κ | Scope | MSE | E[U] | wCVaR β 0.99 | wCVaR β 0.995 | Hash MSE / E[U] / 0.99 / 0.995 |
|---|---|---|---|---|---|---|---|
| pure | 0.5 | individual | 1.000 · 0.500 · 6,594 | 1.000 · 0.500 · 7,934 | 1.000 · 0.500 · 6,825 | 1.000 · 0.500 · 6,562 | `bc3a13b25683` / `30fdb1cf223d` / `d3ecd9c5d16c` / `294b871e78f5` |
| pure | 0.5 | cluster | 1.000 · 0.500 · 6,764 | 1.000 · 0.500 · 6,684 | 1.000 · 0.500 · 6,858 | 1.000 · 0.500 · 6,811 | `0ca1dd536e99` / `d53102ad6a2f` / `c390d37f5a82` / `10f60e0e55c5` |
| pure | 0.5 | portfolio | 1.000 · 0.500 · 6,745 | 1.000 · 0.500 · 6,842 | 1.000 · 0.500 · 6,535 | 1.000 · 0.500 · 6,545 | `78fbb137bd90` / `9c1ce2bd2ff1` / `815a05eb1dde` / `744d86f88467` |
| pure | 1 | individual | 1.000 · 1.000 · 1,004 | 1.000 · 1.000 · 1,011 | 1.000 · 1.000 · 864 | 1.000 · 1.000 · 1,011 | `b6a790bd484c` / `9326e4840c25` / `f89028d0ef02` / `28ac9b153c21` |
| pure | 1 | cluster | 1.000 · 1.000 · 1,232 | 1.000 · 1.000 · 1,230 | 1.000 · 1.000 · 1,085 | 1.000 · 1.000 · 1,142 | `80bee12e4c89` / `b78a04a941dd` / `9a25ee86197d` / `4f21280640b7` |
| pure | 1 | portfolio | 1.000 · 1.000 · 995 | 1.000 · 1.000 · 1,001 | 1.000 · 1.000 · 856 | 1.000 · 1.000 · 915 | `4d63dddd3335` / `08a569620416` / `7d700f7bd02d` / `af7553a9ab56` |
| pure | 1.5 | individual | **0.669** · 1.004 · 990 | 1.000 · 1.500 · 0 | 1.000 · 1.500 · 0 | 1.000 · 1.500 · 0 | `b68089a79316` / `fba2bea3df54` / `d3e22ab13482` / `e7640c4973ac` |
| pure | 1.5 | cluster | **0.668** · 1.002 · 1,227 | 0.998 · 1.497 · 41 | 0.997 · 1.495 · 34 | 1.000 · 1.500 · 31 | `03b15309ae79` / `04dcddbeff14` / `6333fcf71853` / `b380b27e7ea1` |
| pure | 1.5 | portfolio | **0.667** · 1.001 · 994 | 0.967 · 1.450 · 76 | 0.957 · 1.436 · 78 | 0.994 · 1.490 · 76 | `9d926ca913e2` / `eb3e9fa69ed7` / `d626500713c2` / `72377b888b37` |
| CoC r 0.06 | 0.5 | individual | 1.000 · 0.072 · 16,196 | 1.000 · 0.166 · 16,827 | 1.000 · 0.072 · 16,256 | 1.000 · 0.072 · 16,195 | `4ee547b79314` / `e9ad51f8a251` / `6d21f3ccea09` / `79fced174adc` |
| CoC r 0.06 | 0.5 | cluster | 1.000 · 0.072 · 16,312 | 1.000 · 0.166 · 16,822 | 1.000 · 0.072 · 16,313 | 1.000 · 0.072 · 16,295 | `277656d3f68a` / `1ea68c9d74d7` / `379b85317f7c` / `06caefa7104e` |
| CoC r 0.06 | 0.5 | portfolio | 1.000 · 0.072 · 16,260 | 1.000 · 0.164 · 16,816 | 1.000 · 0.072 · 16,316 | 1.000 · 0.072 · 16,101 | `da6b151bfdfc` / `573ef72d95fe` / `cb6ac67a909f` / `8bba6e84995e` |
| CoC r 0.06 | 1 | individual | 1.000 · 0.144 · 14,464 | 1.000 · 0.292 · 15,522 | 1.000 · 0.144 · 14,488 | 1.000 · 0.144 · 14,421 | `af9fe556d6aa` / `3bee2dabbfe6` / `9c0222a65bad` / `587393142489` |
| CoC r 0.06 | 1 | cluster | 1.000 · 0.144 · 14,445 | 1.000 · 0.294 · 15,521 | 1.000 · 0.144 · 14,610 | 1.000 · 0.144 · 14,456 | `96457b8a9204` / `f5d42cdbabde` / `a56b270c97e4` / `163912a4237f` |
| CoC r 0.06 | 1 | portfolio | 1.000 · 0.144 · 14,402 | 1.000 · 0.288 · 15,500 | 1.000 · 0.144 · 14,583 | 1.000 · 0.144 · 14,268 | `0ada0ff98fb2` / `e86fd26ac86f` / `a705dea1563a` / `f6aa2ce3adec` |
| CoC r 0.06 | 1.5 | individual | 1.000 · 0.216 · 12,728 | 1.000 · 0.403 · 14,171 | 1.000 · 0.216 · 12,784 | 1.000 · 0.216 · 12,739 | `8c375d400b3f` / `ddea2a9464ff` / `471ef9e997d6` / `96e2e0102dec` |
| CoC r 0.06 | 1.5 | cluster | 1.000 · 0.216 · 12,493 | 1.000 · 0.401 · 14,143 | 1.000 · 0.216 · 12,861 | 1.000 · 0.216 · 12,512 | `e921d020a7fc` / `cd8900282791` / `caec9a0f486a` / `12bc6c29b80f` |
| CoC r 0.06 | 1.5 | portfolio | 1.000 · 0.216 · 12,254 | 1.000 · 0.395 · 14,128 | 1.000 · 0.216 · 12,825 | 1.000 · 0.216 · 12,234 | `e088dbf116d2` / `f38a4c855eb2` / `845b3223719b` / `755b2d6a7ee7` |
| CoC r 0.10 | 0.5 | individual | 1.000 · 0.046 · 16,776 | 1.000 · 0.123 · 17,202 | 1.000 · 0.046 · 16,878 | 1.000 · 0.046 · 16,833 | `2aec4fcaa8fb` / `01114757b891` / `a2e96d2a37ea` / `bdbf0f2f6519` |
| CoC r 0.10 | 0.5 | cluster | 1.000 · 0.046 · 16,966 | 1.000 · 0.125 · 17,201 | 1.000 · 0.046 · 16,919 | 1.000 · 0.046 · 16,888 | `0ad14d5a7746` / `ae034dd41b70` / `03eef00d91f8` / `32c35841af0d` |
| CoC r 0.10 | 0.5 | portfolio | 1.000 · 0.046 · 16,809 | 1.000 · 0.125 · 17,201 | 1.000 · 0.046 · 16,933 | 1.000 · 0.046 · 16,792 | `c1ca12401f5d` / `0a579feeede2` / `8e5d501f122f` / `97f320af6015` |
| CoC r 0.10 | 1 | individual | 1.000 · 0.092 · 15,655 | 1.000 · 0.223 · 16,364 | 1.000 · 0.092 · 15,777 | 1.000 · 0.092 · 15,707 | `9aed2418ab22` / `a8e3d193b7d2` / `102653e1f758` / `5c46a9cb2efe` |
| CoC r 0.10 | 1 | cluster | 1.000 · 0.092 · 15,726 | 1.000 · 0.225 · 16,367 | 1.000 · 0.092 · 15,848 | 1.000 · 0.092 · 15,815 | `f514d937ee8b` / `7bcffc295bd3` / `9e2e281aa4b6` / `f19e460aa906` |
| CoC r 0.10 | 1 | portfolio | 1.000 · 0.092 · 15,670 | 1.000 · 0.219 · 16,355 | 1.000 · 0.092 · 15,845 | 1.000 · 0.092 · 15,575 | `b4a513c6f1ab` / `94bbfeba79fe` / `120c06502b37` / `7588f543b8ef` |
| CoC r 0.10 | 1.5 | individual | 1.000 · 0.138 · 14,584 | 1.000 · 0.303 · 15,487 | 1.000 · 0.138 · 14,644 | 1.000 · 0.138 · 14,585 | `63f49b821db3` / `515875f6ab98` / `5ab6a5d24521` / `18781a336f62` |
| CoC r 0.10 | 1.5 | cluster | 1.000 · 0.138 · 14,737 | 1.000 · 0.306 · 15,487 | 1.000 · 0.138 · 14,766 | 1.000 · 0.138 · 14,645 | `4f9586566a40` / `f9b2ca1e0dc5` / `bd65fbdd05ec` / `c6efe35280a1` |
| CoC r 0.10 | 1.5 | portfolio | 1.000 · 0.138 · 14,558 | 1.000 · 0.297 · 15,467 | 1.000 · 0.138 · 14,741 | 1.000 · 0.138 · 14,416 | `fb4dcb53bb62` / `c4ccc0456c01` / `3f5ab04a5b59` / `b59f5f8b717d` |

Observations:

F3.1. **Pure pricing, κ 0.5 and 1:** every design uses its whole budget (1.000) and pays out κ · train E[L].

F3.2. **Pure pricing, κ 1.5:** the MSE design uses 0.667–0.669 of its budget in every scope and pays out 1.001–1.004 times the train E[L]. The E[U] and weighted-CVaR designs use 0.957–1.000 and pay out 1.436–1.500 times the train E[L]; their train E[U] and train CVaR₀.₉₉(U) are 0 (at most 0.1 USD), and their test CVaR₀.₉₉(U) is 0 (individual) and 31,000–78,000 (cluster, portfolio), against 990,000–1,227,000 for MSE. In the portfolio scope the E[U] and β 0.99 designs stop short of the budget (0.967, 0.957) with zero train shortfall.

F3.3. **Cost of capital (q 0.99), every κ:** every design uses its whole budget (1.000; portfolio premium 0.998–1.000). The MSE, weighted-CVaR β 0.99 and β 0.995 designs have the same payout ratio in every scope: 0.072, 0.144, 0.216 at r 0.06 (= κ / 6.94) and 0.046, 0.092, 0.138 at r 0.10 (= κ / 10.9). 6.94 and 10.9 are (1 − r) + r / 0.01, the premium per unit of E[π] when all payout falls in at most 1 % of slots (C1 observation 4). The E[U] design pays out 1.8–2.7 times as much (0.123–0.403) and has the higher test CVaR₀.₉₉(U) in every row (by 1.4–15.5 %).

F3.4. **Test premium against the train budget.** On the test years (E[L] 7.5 % above train) the designs' premium is 0.72 (pure κ 1.5 MSE) to 1.24 times the budget (`test_premium_to_budget` in the CSV).

## Family 1: cost of capital with q ≠ the KPI β (MAR-152 item 1)

**Question tested.** C1 observation 4: under cost of capital with q 0.99, the MSE and weighted-CVaR designs tie in sample at KPI β 0.99, because the binding budget fixes E[π] when all payout falls in at most 1 % of slots, and CVaR₀.₉₉(U) then follows from E[π]. Does the tie hold when q differs from the KPI β?

**Setup.** As above, κ 1, cost of capital r ∈ {0.06, 0.10} with **q ∈ {0.95, 0.995}** (premium = (1 − r)·E[π] + r·CVaR_q(π)); every scope; MSE, E[U], weighted CVaR β 0.99 and 0.995. 48 new runs, all `optimal` (CLARABEL, OSQP). Test CVaR(U) at KPI β 0.95, 0.99 and 0.995, bootstrapped as above; train values in-sample at the same β. C1's q 0.99 rows are in C1 section 3.2 and family 3. Wall time 1,360 s at `--jobs 2` (shared machine). Every run, interval and paired difference: `tables_coc_q.md`.

The premium per unit of E[π] when all payout falls in at most (1 − q) of slots is (1 − r) + r / (1 − q): 2.14 (r 0.06) and 2.9 (r 0.10) at q 0.95; 12.94 and 20.9 at q 0.995. At κ 1 the budget then fixes E[π] / E[L] at 0.467, 0.345, 0.077 and 0.048.

**Train (in sample):** payout ratio E[π] / E[L] and CVaR₀.₉₉(U) in thousands, for MSE / E[U] / wCVaR β 0.99 / wCVaR β 0.995.

| r | q | Scope | E[π] / E[L] | Train CVaR₀.₉₉(U) | Hash MSE / E[U] / 0.99 / 0.995 |
|---|---|---|---|---|---|
| 0.06 | 0.95 | individual | 0.467 / 0.467 / 0.467 / 0.467 | 7,335 / 9,170 / 7,336 / 7,324 | `d2d83d43a0cc` / `e8411b2ef99a` / `a94aca0ff3e0` / `06b57c7a8251` |
| 0.06 | 0.95 | cluster | 0.467 / 0.467 / 0.467 / 0.467 | 7,328 / 9,387 / 7,230 / 7,304 | `649858106720` / `98ddcaa00abc` / `04c272bbb89f` / `f941cd2fef03` |
| 0.06 | 0.95 | portfolio | 0.467 / 0.468 / 0.467 / 0.467 | 7,317 / 9,325 / 7,194 / 7,288 | `cba3ec36a713` / `a5352a7813db` / `86f102ba17ea` / `b6d2794197da` |
| 0.06 | 0.995 | individual | 0.082 / 0.283 / 0.178 / 0.077 | 15,324 / 14,547 / 14,189 / 15,377 | `fce71e2e206c` / `7c042c910de9` / `304973f2ab5c` / `7adbd3edeb7d` |
| 0.06 | 0.995 | cluster | 0.089 / 0.284 / 0.175 / 0.077 | 15,292 / 14,544 / 14,154 / 15,376 | `c7000e028b4e` / `666b3022ec6b` / `c82828f476d2` / `c1ee56723de1` |
| 0.06 | 0.995 | portfolio | 0.089 / 0.280 / 0.179 / 0.077 | 15,290 / 14,527 / 14,146 / 15,376 | `031eebc8a82b` / `9818d77f2d3a` / `8ca54dacb805` / `ff23cd7078d6` |
| 0.10 | 0.95 | individual | 0.345 / 0.345 / 0.345 / 0.345 | 9,684 / 11,650 / 9,690 / 9,652 | `e7fd53f802fc` / `51eb6a758f73` / `1fd5a8cb657d` / `e48c7e134b61` |
| 0.10 | 0.95 | cluster | 0.345 / 0.345 / 0.345 / 0.345 | 9,679 / 11,739 / 9,619 / 9,655 | `44c5528ad8fa` / `ae9f5dffda5f` / `d26372aab39b` / `b225c62dd30c` |
| 0.10 | 0.95 | portfolio | 0.345 / 0.345 / 0.345 / 0.345 | 9,684 / 11,762 / 9,611 / 9,651 | `c8de107cdbff` / `15f2c5de3064` / `52cea29e6abe` / `bc88f6450daa` |
| 0.10 | 0.995 | individual | 0.049 / 0.214 / 0.115 / 0.048 | 16,006 / 15,405 / 15,198 / 16,011 | `105e56def14b` / `2a5acadcfc85` / `fc1778b0a30b` / `e206b6fbf9e6` |
| 0.10 | 0.995 | cluster | 0.048 / 0.217 / 0.113 / 0.048 | 16,011 / 15,404 / 15,167 / 16,011 | `4f9ad2ecac4f` / `31086c7f2bb8` / `dc4755423aae` / `6eab1c15e9f6` |
| 0.10 | 0.995 | portfolio | 0.048 / 0.211 / 0.116 / 0.048 | 16,011 / 15,394 / 15,164 / 16,011 | `5cfe75c568cd` / `3d9141ca63dd` / `7e32d4caba35` / `c025526edcad` |

Every run uses its whole budget (budget use 1.000).

**Test (out of sample):** relative paired difference in test CVaR(U) at KPI β 0.95 / 0.99 / 0.995 (`*`: the 90 % interval excludes zero; intervals in `tables_coc_q.md`).

| r | q | Scope | wCVaR 0.99 − MSE | wCVaR 0.995 − MSE | wCVaR 0.99 − E[U] | wCVaR 0.995 − E[U] |
|---|---|---|---|---|---|---|
| 0.06 | 0.95 | individual | +1.0 % / +2.6 % / +11.5 % | +0.1 % / +0.2 % / +0.6 % | −2.9 % / −24.6 %* / −37.5 %* | −3.8 % / −26.4 %* / −43.6 %* |
| 0.06 | 0.95 | cluster | +0.8 % / +0.6 % / +4.7 % | −0.5 % / −0.7 % / −0.7 % | −2.2 % / −26.2 %* / −42.6 %* | −3.4 % / −27.2 %* / −45.6 %* |
| 0.06 | 0.95 | portfolio | −0.7 % / −1.7 % / +2.4 % | −1.0 % / −1.1 % / −0.9 % | −3.9 % / −28.2 %* / −41.9 %* | −4.1 % / −27.7 %* / −43.8 %* |
| 0.06 | 0.995 | individual | −7.8 % / −4.7 % / +4.5 % | +0.7 % / +0.6 % / +0.1 % | +14.1 %* / −2.5 %* / −1.9 %* | +24.7 %* / +2.9 % / −6.0 % |
| 0.06 | 0.995 | cluster | −7.9 % / −6.3 % / +1.6 % | +0.5 % / −0.7 % / −1.9 % | +15.1 %* / −2.4 %* / −1.9 %* | +25.6 %* / +3.5 % / −5.3 % |
| 0.06 | 0.995 | portfolio | −6.8 % / −5.5 % / +3.3 % | +0.7 % / −0.6 % / −1.8 % | +15.1 %* / −2.6 %* / −1.8 %* | +24.4 %* / +2.5 % / −6.7 % |
| 0.10 | 0.95 | individual | +0.5 % / +1.2 % / +10.2 % | −0.0 % / −0.1 % / +0.9 % | −3.5 % / −21.4 %* / −34.7 %* | −3.9 % / −22.4 %* / −40.2 %* |
| 0.10 | 0.95 | cluster | +0.7 % / +1.0 % / +4.2 % | −0.7 % / −1.0 % / −1.2 % | −2.2 % / −21.0 %* / −37.0 %* | −3.5 % / −22.6 % / −40.3 %* |
| 0.10 | 0.95 | portfolio | −1.3 % / −1.1 % / +2.7 % | −0.9 % / −1.2 % / −1.6 % | −4.4 % / −23.4 %* / −38.2 %* | −4.0 % / −23.5 %* / −40.7 %* |
| 0.10 | 0.995 | individual | −5.1 % / −3.1 % / +2.9 % | +0.3 % / +0.3 % / +0.4 % | +11.5 %* / −1.4 %* / −1.1 %* | +17.9 %* / +2.1 % / −3.4 % |
| 0.10 | 0.995 | cluster | −5.5 % / −4.0 % / +1.6 % | +0.1 % / +0.2 % / +0.3 % | +12.1 %* / −1.4 %* / −1.1 %* | +18.8 %* / +2.9 % / −2.4 % |
| 0.10 | 0.995 | portfolio | −4.9 % / −3.4 % / +2.6 % | −0.0 % / −0.0 % / −0.1 % | +12.1 %* / −1.5 %* / −1.1 %* | +17.8 %* / +2.0 % / −3.6 % |

Observations:

F1.1. **q 0.95: every design has the same E[π].** All four designs, in every scope and at both r, pay out the E[π] the budget fixes when all payout falls in at most 5 % of slots (0.467 and 0.345 of E[L]; E[U] portfolio r 0.06: 0.468). The E[U] design is no longer the one with the larger payout (it is under q 0.99, family 3).

F1.2. **q 0.95, KPI β 0.99 and 0.995.** In sample the MSE and weighted-CVaR designs are within 1.7 % of each other at KPI β 0.99 (wCVaR β 0.99 minus MSE: −1.7 to +0.1 %); the E[U] design's train CVaR₀.₉₉(U) is 20–28 % above MSE's. Out of sample, weighted CVaR (β 0.99 or 0.995) minus MSE is −1.7 to +2.6 % at KPI 0.99 and −1.6 to +11.5 % at KPI 0.995, every interval containing zero; weighted CVaR minus E[U] is −21.0 to −28.2 % at KPI 0.99 and −34.7 to −45.6 % at KPI 0.995, intervals excluding zero in 23 of these 24 cells (not cluster, r 0.10, β 0.995 design at KPI 0.99: upper bound +0.0 %). At KPI 0.95 the weighted-CVaR designs are within 4.4 % of MSE and of E[U], intervals containing zero.

F1.3. **q 0.995 read at KPI 0.99 (the case MAR-152 names).** The design with all payout in at most 0.5 % of slots is the weighted-CVaR β 0.995 design (ratio 0.077 / 0.048). The MSE design comes close (0.082–0.089 at r 0.06; 0.048–0.049 at r 0.10). The weighted-CVaR β 0.99 design pays out about twice as much (0.175–0.179; 0.113–0.116) and the E[U] design more again (0.280–0.284; 0.211–0.217).
- In sample at KPI 0.99, the β 0.99 design is 7.4–7.5 % (r 0.06) and 5.0–5.3 % (r 0.10) below MSE. The β 0.995 design and MSE are within 0.6 % at r 0.06 and equal to the reported precision in the cluster and portfolio scopes at r 0.10 (16,010.8 thousand both, every KPI β: `tables_coc_q.md`).
- Out of sample, weighted CVaR β 0.99 minus MSE is −3.1 to −6.3 % at KPI 0.99 and −4.9 to −7.9 % at KPI 0.95, every interval containing zero (upper bounds +2.2 to +4.5 % at KPI 0.95, +6.6 to +9.6 % at KPI 0.99); at KPI 0.995 it is +1.6 to +4.5 %, intervals containing zero. Weighted CVaR β 0.995 minus MSE is within ±1.9 % at every KPI β, intervals containing zero.
- Against E[U], the β 0.99 design is 1.4–2.6 % lower at KPI 0.99 and 1.1–1.9 % lower at KPI 0.995 (intervals excluding zero, narrow: e.g. −1.9 % [−1.9, −1.8] at r 0.06, portfolio), and 11.5–15.1 % higher at KPI 0.95 (intervals excluding zero). The β 0.995 design is 17.8–25.6 % above E[U] at KPI 0.95 (intervals excluding zero) and −6.7 to +3.5 % at KPI 0.99 and 0.995 (intervals containing zero).

F1.4. **Comparison with q 0.99 (C1).** At q 0.99 and KPI 0.99, C1 found weighted CVaR β 0.99 minus MSE at +0.2 to +1.3 % (r 0.06 and 0.10) and minus E[U] at −3.1 to −6.7 %, every interval containing zero (C1 section 3.2). In this family, the design that ties with MSE in sample is the one whose β equals q (β 0.995 at q 0.995; at q 0.95 every design but E[U] is within 1.7 %), not the one whose β equals the KPI β.
