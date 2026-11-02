# C1 follow-ups on the thesis portfolio (RQ1): CoC q ≠ KPI β, design β above 0.99 on draws, budget use, bootstrap coverage

- Issue: MAR-205 (split from MAR-152 items 1, 2, 3 and 5). An addendum to checkpoint C1 (`research/checkpoints/C1.md`, MAR-29).
- **Observations only.** No interpretation and no recommendation: that belongs to the owner. RQ1 statements here hold for the stated setup only (publication rule, AGENTS.md).
- Script: `research/scripts/c1_followups.py` (one `--family` per run family). Grid: `research/configs/c1-followups/followups.yaml`. Data: `research/data/c1-followups/`. Hashes in this note are the first 12 hex digits of the `sha256:` config hash; the `*_runs.csv` tables have the full config hash and run id of every run.
- Status: family 3 (budget use) below. Families 1, 2 and 4 are added as they finish.

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
