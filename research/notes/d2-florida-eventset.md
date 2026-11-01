# D2: the Florida-counties EventSets (measurements)

- Issues: MAR-114 (P-05b, part of MAR-31), first build; MAR-132 (F-12), rebuild with the basin filter of the `v_half` prior and the Monroe note; MAR-160 (F-12), rebuild with the prior recentred on the base function (first with the median recentred, then, as decided on 2026-11-01, in the excess form with the expected loss matched to the base). Written by worker agents on 2026-10-27, 2026-10-31 and 2026-11-01.
- Also MAR-145 (P-05): index (b) rebuilt at the chosen cat-in-a-circle radius, 75 km, with the recentred prior. Written by a worker agent on 2026-11-01.
- Decisions this implements: D2 (SPEC §6.6, MAR-30), on MAR-113's 67-county table (`research/notes/d2-florida-litpop-locations.md`); the owner's answers to MAR-118 Q1 (basin filter on the wind-only prior, default for C1 and the paper), Q2 (keep Monroe County and state its LitPop gap) and Q5 = b (recentre the prior on the base function, MAR-160; option 3 of the MAR-160 escalation, chosen by the orchestrator on 2026-11-01 under Marc's delegation: the excess form, with the expected loss matched to the no-draws build) and Q6 (the cat-in-a-circle radius for D2: 75 km, answered 2026-10-31 from MAR-133's sensitivity, `research/notes/cat-in-circle-radius-sensitivity.md`; MAR-145).
- Status: **observations**, not conclusions. Interpretation (which index, whether the prior's tail is acceptable) belongs to the owner and to MAR-31.
- Checksums, content hashes and config hashes:
  - the current pair (MAR-145): `research/data/d2-florida-eventset/checksums.json`, `summary.json`, `metadata/` and `exposure-summary/`, with their `README.md`. Index (a) is MAR-160's build (its config did not change), index (b) MAR-145's at 75 km;
  - MAR-160 rebuild: `research/data/f12-recentred-prior/checksums.json` and `summary.json`, with their `README.md`. Its index (b) build is the 50 km one, superseded by MAR-145. These files replace those of the first MAR-160 build (multiplicative median), whose hashes are kept below for reference only;
  - MAR-132 rebuild: hashes in the table below. Its `checksums.json`, `metadata/` and `exposure-summary/` were in `research/data/d2-florida-eventset/` until MAR-145 (see the git history).

  The MAR-114 values are kept below where they are compared.
- **MAR-160 in one line.** With the prior recentred to the base expected loss, the Florida EAL over the draws is **1.000000 times** the no-draws build's (target 1; the first build's median recentring gave 1.953) and the largest annual loss is **33.7 % of value** (no draws 15.1 %, MAR-132 20.5 %, first MAR-160 build 51.6 %). The matched factor is `s` = 0.690130, i.e. a median `v_half` of 86.293 m/s; it depends on the portfolio and the hazard (thesis portfolio: 84.849 m/s).
- **MAR-145 in one line.** Index (b) is now the cat-in-a-circle at **75 km** (content hash `sha256:70af1fed…e8328a60`). Its loss matrix is that of index (a) and of the 50 km build, so the matched factor and every loss and tail number above are unchanged (EAL / base 1.000000, largest annual loss 33.7 % of value). Only the index changes: the (row, county) pairs with category 0 now carry **17.1 %** of the loss (50 km: 37.5 %).

## What was built

Current EventSets (prior recentred to the base expected loss): index (a) from the MAR-160 rebuild, index (b) from the MAR-145 rebuild at 75 km:

| | Index (a) | Index (b) |
|---|---|---|
| Config | `packages/climada/configs/florida_counties.yaml` (SHA256 `67ab561757e1cfc5c0ae84de8fb39b49d68412b9b870640865ccf91de5f547da`) | `packages/climada/configs/florida_counties_cat_in_circle.yaml` (SHA256 `fd8ab002ad284b080cf9caf6c83675f0170be2e01121f6f3b936a9f87da7e4de`) |
| Index | wind at the county's value-weighted centroid (m/s) | cat-in-a-circle, 75 km around the centroid, Saffir-Simpson category 0–5 |
| EventSet content hash | `sha256:30b1723182e5bb3eef8abae0d0edcc605918aaf90e03b24bb09037a4c6416472` | `sha256:70af1fed283d9e800574c01181ff4e3ee40dee7ab227a890145d7744e8328a60` |
| Matched factor `s`, median `v_half` | 0.690130, 86.293 m/s | 0.690130, 86.293 m/s (the same loss) |
| Base of the match (`recentre.match.base_content_hash`) | `sha256:373e11a62ba098dfb513526edd589354fc488c10a9484d0e799e1adf672e690a` | `sha256:d62faf2ef7a9ba3575da005432be7d8122f3c728e12e34994a331f9b2b531e4c`, equal to the content hash of MAR-133's `research/configs/climada/florida_counties_cat_in_circle_75km_no_draws.yaml` build |
| MAR-160 build at 50 km (index (b) superseded by MAR-145) | the current build (above) | config SHA256 `a9c030c3fd4a7e7db045b1b44ea5fc18e5f4bf1d38bb707232306a8acca4ae01`, content hash `sha256:4d578aef7caed148181699ddfb6d9a9d877127b549d03031fbb18e4c5a26a70f`; base of the match `sha256:81a739db…1136a`, equal to MAR-133's 50 km no-draws build |
| First MAR-160 build (multiplicative median 74.7, superseded) | config SHA256 `6f3d39abb38d4835975104edf04ddf3697222025693844a73c3a3204bb143c10`, content hash `sha256:f95553d91f4dfe417838c5b4632ab86f9dde312e4b70f3b14632fc68a26c07d3` | config SHA256 `af666320e4d58614cdffee0f2c33fc4a5fe02505c388c90e1b88a3eb85c56075`, content hash `sha256:198573bbd5dfb4d958d379712e14559d50f26c28171fc9fc4e0bd2c8827396d8` |
| MAR-132 build (17-event prior, not recentred) | config SHA256 `09ae66710528a14af95e198e3a82ef91912c7cf59fc5f38481a0f2556c2ed379`, content hash `sha256:cad398875afb467f5d1475e6a47952116391be18f249cc484990436f46a6cbe6` | config SHA256 `4d6323d1613b92747357548c126947263cce3a06a4eed00a6391a093b0fbe1c0`, content hash `sha256:c7d6b76519d88bba4143d999bed81c78a0ff213777528aed3d7cea5ff2dfa67f` |
| MAR-114 build (19-event prior) | config SHA256 `eb8126a8…44a13a9`, content hash `sha256:d8698f7d2985409f5a5024101d7ba839d42a127a29d5456e5871ecaaa3385131` | config SHA256 `ed874270…9296a84`, content hash `sha256:81acd810655dc42edc3eb327f2ad6d4de3a666993c29fdfa80b48ee8b07a2d3e` |

Common settings: IRIS NA merged 10,000-year catalogue (SHA256 `7f7b224d…606bd`), 500 km proximity filter, H08 wind, Emanuel USA impact function (`v_thresh` 25.7, `v_half` 74.7, scale 1), 10 vulnerability draws per storm, seed 20261027, `licence: CC-BY-4.0`, `loss.unit` "USD (LitPop reference_year 2018)", and the value-unit caveat, the Monroe County note and the LitPop / TIGER/Line / IRIS attribution in the scenario text of `metadata.json`.

**The `v_half` prior.** Eberenz et al. (2021), region NA2, event-wise fits (CLIMADA's `tc_impf_cal_v01_EDR.csv`, SHA256 `bde5670d…a3343e39`):

| Prior | Events | min | 5 % | 25 % | median | 75 % | 95 % | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MAR-160 (current): the MAR-132 values recentred, `25.7 + s · (v − 25.7)` with `s` = 0.6901 | 17 | 48.4 | 56.3 | 70.2 | 86.3 | 118.6 | 161.9 | 168.3 |
| First MAR-160 build (superseded): the MAR-132 values × 74.7 / 113.5 | 17 | 38.6 | 46.1 | 59.4 | 74.7 | 105.5 | 146.8 | 153.0 |
| MAR-132: wind-only, North Atlantic genesis basin (`wind_only: true`, `basins: [NA]`) | 17 | 58.6 | 70.0 | 90.2 | 113.5 | 160.3 | 223.0 | 232.4 |
| MAR-114: wind-only, all basins (`basins: null`) | 19 | 25.8 | 35.9 | 79.1 | 95.4 | 143.7 | 221.9 | 232.4 |

The basin filter removes two wind-only East Pacific storms that hit Hawaii: 1982324N10193 (Iwa, 25.8 m/s) and 2014212N11242 (Iselle, 37.0 m/s). The third East Pacific NA2 event, 1992249N12229 (Iniki, 25.8 m/s), was already out (Flood flag). The basin of each event is IBTrACS v04r01's genesis basin, from the pinned lookup `packages/climada/src/parametric_insurance_design_climada/eberenz2021_edr_basins.csv` (SHA256 `ffdd1674…2c4679a`; method and source in `docs/methodology/vulnerability.md`). MAR-118 expected the next-lowest wind-only value to be 37.0 m/s once Iwa is removed; 37.0 m/s is Iselle, an East Pacific storm too, so the minimum is 58.6 m/s (1999236N22292, Dennis 1999).

**Loss per cell.** A county's loss is the sum of the impacts on its 7,817 LitPop cells (`cells.parquet`, SHA256 `7a3ac587…3ca6`), each with the wind at its cell centre; the index stays at the centroid. This is the new `loss: {kind: cells}` path of the pipeline (ADR 0002 §10 amendment row, MAR-114). The 2,861 Alabama and Georgia cells in the file (0.184 × 10¹² USD) have no `location_id` and are left out, counted in the build record. The farthest cell from its county centroid is 110.5 km (in Monroe County), so `max_dist_eye_km` (300) plus 110.5 stays below `proximity_km` (500): no storm removed by the proximity filter can have wind at a cell.

**Draw semantics (MAR-25, kept).** One `v_half` per (storm, draw), shared by every cell of every county; storms and draws are independent. The generator is consumed exactly as with centroid losses (`rng.random((n_events, n_draws))` per batch), so (a) and (b) have identical loss matrices (checked: `np.array_equal`).

## Size, time and memory

Measured on the owner's Apple-silicon Mac (osx-arm64), CLIMADA 6.1.0, Python 3.12, `/usr/bin/time -l` around `pixi run`:

| Build | Pipeline runtime | Wall time | Peak RSS |
|---|---:|---:|---:|
| (a) `florida_counties.yaml`, batch 100 | 629 s | 643 s | 1.71 GB (1,714,077,696 B) |
| (b) `florida_counties_cat_in_circle.yaml`, batch 100 | 681 s | 694 s | 1.45 GB |
| Scratch, cells loss, no draws, batch 500 (not kept) | 591 s | – | – |
| Scratch, centroid loss, no draws, batch 500 (not kept) | 128 s | – | – |
| MAR-132 rebuild (a), batch 100 | 2,779 s | 2,808 s | 1.56 GB |
| MAR-132 rebuild (b), batch 100 | 2,812 s | 2,833 s | 1.38 GB |
| First MAR-160 build (a), batch 100 | 1,115 s | 1,131 s | 1.38 GB |
| First MAR-160 build (b), batch 100 | 1,092 s | 1,105 s | 1.50 GB |
| MAR-160 rebuild (a), batch 100, base pass and match included | 1,784 s (base pass and match 566 s) | 1,801 s | 1.51 GB |
| MAR-160 rebuild (b), batch 100, base pass and match included | 1,838 s (base pass and match 575 s) | 1,854 s | 1.37 GB |
| MAR-145 rebuild (b) at 75 km, batch 100, base pass and match included | 678 s (base pass and match 329 s) | 684 s | 1.93 GB (1,933,049,856 B) |

The MAR-132 rebuilds ran at the same time on a machine with a load average of about 40–50 from other jobs (10 cores), so their times are not comparable with MAR-114's. The first MAR-160 builds also ran at the same time, next to two thesis builds and a scratch no-draws run (load average about 10–12). The MAR-160 rebuilds ran at the same time, next to the two thesis builds and scratch thesis builds. With the match a build runs the pipeline twice: first without draws (the base, about 9.5 minutes here), then with the draws. The root-find between the two takes about 2 s (measured separately on the captured cell winds: 13,902 storms × 10 draws × 25 grid nodes); recording the grid loss during the base pass adds about 7 s. The MAR-145 build ran alone, with no other EventSet build on the machine (load average about 2–7); its match took 1 s after the last base batch.

- Rows: 13,902 storms × 10 draws = 139,020; × 67 counties = 9,314,340 `values` rows, equal to MAR-113's estimate. No storm skipped.
- On disk: 10.8 MB (a) and 8.9 MB (b at 75 km; 8.4 MB at 50 km), of which `values.parquet` is 10.6 MB for (a). Not committed (only `metadata.json`, checksums and the summary).
- The sparse long format (ADR 0002 option) was not needed: the dense grid fits.
- Most of the time is the wind field at the 7,817 cells (the centroid-only build takes about a fifth); the per-cell draws add little.

## Observations (not interpreted)

**Index (b) at 75 km, MAR-145 rebuild (current config).**

Setup:

- the EventSet `florida-counties-iris-cat-in-circle-75km-vulnerability`: content hash `sha256:70af1fed283d9e800574c01181ff4e3ee40dee7ab227a890145d7744e8328a60`, config SHA256 `fd8ab002ad284b080cf9caf6c83675f0170be2e01121f6f3b936a9f87da7e4de`, built on 2026-11-01 at commit `c9cfe05` (the code of `main` at `cecc667`; only the config changed);
- the base and the conventions are those of the MAR-160 section below. The numbers are in `research/data/d2-florida-eventset/summary.json`.

Cross-checks, all of which hold:

- the loss matrix equals that of index (a) (`sha256:30b17231…c6416472`) and of the 50 km build (`sha256:4d578aef…5a26a70f`), by `np.array_equal`;
- the match found the same factor as at 50 km, `s` = 0.6901304479036513 (median `v_half` 86.29345332594143 m/s, support 48.4–168.3 m/s). Target EAL 7,615,672,695.469273 USD, matched 7,615,672,695.4692745 USD (relative tolerance 1e-6);
- the base of the match, this config without draws, has content hash `sha256:d62faf2e…2b531e4c`: that of MAR-133's `research/configs/climada/florida_counties_cat_in_circle_75km_no_draws.yaml` build. That config differs from this one only in the vulnerability section, the batch size and the output path. The same holds at 50 km: MAR-160's base `sha256:81a739db…1136a` is MAR-133's 50 km build;
- the index of draw 0 (one row per storm) hashes to `sha256:89d5290c…07a7b`, MAR-133's 75 km no-draws index table (MAR-133's matrix hash), and every draw of a storm has the same index;
- the base loss matrix hashes to `sha256:a417c756…2a4873`, MAR-133's no-draws loss matrix.

Loss and tail numbers, reported as in MAR-132. They equal MAR-160's below, because the loss matrix is the same:

| | MAR-145, index (b) at 75 km | No draws (base) |
|---|---:|---:|
| Portfolio EAL, USD | 7.616 × 10⁹ | 7.616 × 10⁹ |
| EAL / value | 0.156 % | 0.156 % |
| **EAL ratio to the base function** | **1.000000** (0.9999999999999997) | 1 |
| Annual portfolio loss, 90 % quantile | 6.19 × 10⁹ | 9.36 × 10⁹ |
| 99 % | 187 × 10⁹ | 181 × 10⁹ |
| 99.6 % | 375 × 10⁹ | 319 × 10⁹ |
| 99.9 % | 697 × 10⁹ | 460 × 10⁹ |
| **Largest annual loss** | **1.648 × 10¹² USD, 33.7 % of value** (year 1611, `draw_id` 9) | 15.1 % |

The index at 75 km, with draws. Shares of the 139,020 × 67 (row, county) pairs, and of the total loss on them (rate-weighted):

| Category | 0 | 1 | 2 | 3 | 4 | 5 |
|---|---:|---:|---:|---:|---:|---:|
| Pairs | 96.90 % | 1.15 % | 0.64 % | 0.59 % | 0.55 % | 0.19 % |
| **Loss, MAR-145 (10 draws)** | **17.1 %** | 5.4 % | 8.0 % | 17.4 % | 33.8 % | 18.3 % |
| Loss, MAR-133 (no draws) | 16.4 % | 4.7 % | 7.1 % | 17.1 % | 35.1 % | 19.7 % |

- The pair shares equal MAR-133's at 75 km: the index does not depend on the draws.
- At 50 km, with the same prior and loss matrix (MAR-160), category 0 carried 37.5 % of the loss.
- 3,411 of the 13,902 storms reach category ≥ 1 within 75 km of some centroid (50 km: 3,057). 34,110 of the 139,020 rows have a non-zero index at some county (50 km: 30,570).

MAR-133's numbers for the chosen radius (no draws; `research/notes/cat-in-circle-radius-sensitivity.md`). The basis-risk measure is MAR-133's: the share of the loss variance left unexplained by a least-squares step payout per county on the category.

- Category-0 loss share 16.4 % (50 km: 36.7 %).
- Portfolio basis risk 0.408 per event and 0.391 per year (two-fold 0.423), the lowest of the four radii (50 km: 0.454).
- County median 0.508 (0.381–0.604). 51 of the 67 counties have their lowest in-sample basis risk at 75 km (two-fold: 54).
- The median county sees category ≥ 1 in its circle 0.035 times a year (0.029–0.093).

These were not recomputed with the draws. MAR-133's provisional line at 50 km (MAR-132 prior) measured 0.741 per event with the draws, against 0.454 without.

**Losses, MAR-160 rebuild (the 17-event prior recentred to the base expected loss; index (a) current, index (b) at 50 km).**

Setup:

- the EventSets: content hashes `sha256:30b17231…c6416472` (a) and `sha256:4d578aef…5a26a70f` (b), factor `s` = 0.690130, median `v_half` 86.293 m/s, support 48.4–168.3 m/s;
- rate-weighted over all rows;
- the base is the no-draws build of the same config. The match's own base (`florida_counties.yaml` without draws, `sha256:373e11a6…672e690a`) is not written to disk; its loss matrix is that of `configs/florida_counties_no_draws.yaml` (`sha256:07eb5c9a…f1c379e5`, EAL 7,615,672,695 USD), whose loss and years were captured in a scratch run of the first MAR-160 build. Apart from the draws section and the output path, the two configs differ only in the Monroe County scenario note, which enters the content hash: hence the two hashes. The EAL of that capture equals the match's `target_expected_loss` to the last digit (7,615,672,695.469273 USD).

The numbers are in `research/data/f12-recentred-prior/summary.json`.

| | MAR-160 (excess, EAL-matched) | First MAR-160 build (median 74.7, superseded) | MAR-132 (17 events) | MAR-114 (19 events) | No draws (base) |
|---|---:|---:|---:|---:|---:|
| Portfolio EAL, USD | **7.616 × 10⁹** | 14.87 × 10⁹ | 3.041 × 10⁹ | 14.44 × 10⁹ | 7.616 × 10⁹ |
| EAL / value | 0.156 % | 0.304 % | 0.062 % | 0.295 % | 0.156 % |
| **EAL ratio to the base function** | **1.000000** | 1.953 | 0.399 | 1.90 | 1 |
| Annual portfolio loss, 90 % quantile | 6.19 × 10⁹ | 12.8 × 10⁹ | 2.13 × 10⁹ | 4.16 × 10⁹ | 9.36 × 10⁹ |
| 99 % | 187 × 10⁹ | 384 × 10⁹ | 70.8 × 10⁹ | 287 × 10⁹ | 181 × 10⁹ |
| 99.6 % | 375 × 10⁹ | 717 × 10⁹ | 153 × 10⁹ | 1,010 × 10⁹ | 319 × 10⁹ |
| 99.9 % | 697 × 10⁹ | 1,232 × 10⁹ | 319 × 10⁹ | 2,090 × 10⁹ | 460 × 10⁹ |
| **Largest annual loss** | **1.648 × 10¹² USD, 33.7 % of value** | 2.525 × 10¹², 51.6 % | 1.004 × 10¹², 20.5 % | 4.49 × 10¹², 91.7 % | 15.1 % |

- Annual losses are per (year, draw) outcome: 10,000 years × 10 draws = 100,000 outcomes; the no-draws column has 10,000 outcomes.
- The largest annual loss is year 1611, `draw_id` 9: mostly storm `NA_1611_5`, at 30.6 % of value. The next four largest outcomes are 32.8 % (year 4001, `draw_id` 6, `NA_4001_4`), 31.9 % (year 4001, `draw_id` 9, `NA_4001_4`), 31.2 % (year 2444, `draw_id` 4, `NA_2444_3`) and 31.0 % (year 2444, `draw_id` 7, `NA_2444_3`).
- The EAL per `draw_id` ranges from 7.18 × 10⁹ to 8.78 × 10⁹ USD across the 10 draws.
- Per county:
  - the EAL ratio to the base runs from 0.976 (Flagler) to 1.053 (Liberty), median 1.017. The match is on the portfolio total, not per county;
  - EAL / value runs from 0.110 % (Nassau) to 0.487 % (Escambia);
  - Monroe's EAL is 0.87 × 10⁶ USD (ratio 1.02).
- For storms with a positive portfolio loss, the median coefficient of variation across the 10 draws is 0.99 (first MAR-160 build 1.12, MAR-132 1.01).
- 49,250 rows and 659,190 (row, county) pairs have a positive loss, as before: whether a loss is positive depends on the wind, not on `v_half`.
- The loss matrices of (a) and (b) are identical (`np.array_equal`), and both builds matched the same factor.
- Index (b) at 50 km: the (row, county) pairs with category 0 carry 37.5 % of the total loss (first MAR-160 build 40.0 %, MAR-132 36.0 %; at 75 km, MAR-145: 17.1 %).
- Tail dependence (q = 0.99, off-diagonal): min 0.000, median 0.084, max 0.888 (first MAR-160 build 0.001, 0.093, 0.895; MAR-132 0.000, 0.084, 0.889).

**Why the first build overshot, and what the match changes.** The first MAR-160 build made the median `v_half` 74.7 m/s, but the loss is not linear in `v_half`. At the winds that carry most of the loss the Emanuel damage is convex in `v_half` (near `v_thresh`, `mdd ≈ ((w − v_thresh)/(v_half − v_thresh))³`), so draws below the median add more loss than draws above it remove: the EAL was 1.95 times the base. The current builds instead solve the factor so that the EAL equals the base's. Its matched median, 86.293 m/s, lies above the base 74.7 m/s for the same reason: a prior spread around 74.7 m/s would carry more expected loss than the base function itself.

**The recentrings evaluated offline before the decision (MAR-160 escalation; built: the last-but-one row).** These use the same storms, cells and generator stream as the builds, and the same tabulated Emanuel function. The evaluator reproduced the MAR-132 and first MAR-160 builds' EAL to within 1e-12 (relative), and the 1-draw base loss to 5e-15. Florida, 100,000 annual outcomes:

| transform of the 17 values | smallest `v_half` | median | EAL / base | annual loss 99 % | 99.9 % | largest annual loss, share of value |
|---|---:|---:|---:|---:|---:|---:|
| none (MAR-132) | 58.6 | 113.5 | 0.399 | 70.8 × 10⁹ | 319 × 10⁹ | 20.5 % |
| multiplicative, median 74.7 (first MAR-160 build, superseded) | 38.6 | 74.7 | 1.953 | 384 × 10⁹ | 1,232 × 10⁹ | 51.6 % |
| additive shift `v_half_i − 38.8`, median 74.7 | 19.8 | 74.7 | not defined: Dennis 1999 (58.6 m/s) falls 5.9 m/s below `v_thresh` | – | – | – |
| `v_thresh + (v_half_i − v_thresh) × c`, median 74.7 | 44.1 | 74.7 | 1.602 | 310 × 10⁹ | 990 × 10⁹ | 42.3 % |
| multiplicative, median chosen so that EAL = base | 46.1 | 89.3 | 1.000 | 185 × 10⁹ | 736 × 10⁹ | 36.3 % |
| **`v_thresh + (v_half_i − v_thresh) × s`, EAL = base (implemented; the build: median 86.293, 33.7 %)** | 48.4 | 86.3 | 1.000 | 187 × 10⁹ | 697 × 10⁹ | 33.7 % |
| no draws (base function) | 74.7 | 74.7 | 1 | 181 × 10⁹ | 460 × 10⁹ | 15.1 % |

The offline EAL-matched medians came from a root search to ±0.05 m/s. They depend on the portfolio and the hazard; on the thesis portfolio they are 87.9 m/s (multiplicative) and 84.9 m/s (excess; the build: 84.849 m/s).

**Losses, MAR-132 rebuild (17-event prior, not recentred).** Setup: the MAR-132 EventSets above (content hashes `sha256:cad39887…46a6cbe6` (a) and `sha256:c7d6b765…2dfa67f` (b)); rate-weighted over all rows (draws carry `rate / 10`). The base is `configs/florida_counties_no_draws.yaml` (MAR-32: no draws, `v_half` 74.7, the same 13,902 storms, content hash `sha256:07eb5c9a808af45f7d05932b5d78f0cc9b1142f37aef8c9749138dc8c1f379e5`, EAL 7,615,672,695 USD; `research/data/p06-storm-eventset/checksums.json`), not rebuilt here.

| | MAR-132 (17-event prior) | MAR-114 (19-event prior) | No draws (base) |
|---|---:|---:|---:|
| Portfolio EAL, USD | **3.041 × 10⁹** | 14.44 × 10⁹ | 7.616 × 10⁹ |
| EAL / value | 0.062 % | 0.295 % | 0.156 % |
| EAL ratio to the base function | **0.399** | 1.90 | 1 |
| Annual portfolio loss, 90 % quantile | 2.13 × 10⁹ | 4.16 × 10⁹ | – |
| 99 % | 70.8 × 10⁹ | 287 × 10⁹ | 181 × 10⁹ |
| 99.6 % | 153 × 10⁹ | 1,010 × 10⁹ | – |
| 99.9 % | 319 × 10⁹ | 2,090 × 10⁹ | – |
| Largest annual loss | **1.004 × 10¹² USD, 20.5 % of value** | 4.49 × 10¹², 91.7 % | 15.1 % |

- Annual losses are per (year, draw) outcome, 10,000 years × 10 draws = 100,000 outcomes; value 4.893 × 10¹² USD. The no-draws column is MAR-114's scratch build (same rows; its 90 %, 99.6 % and 99.9 % quantiles were not recorded).
- The largest annual loss is year 1611, `draw_id` 9: storm `NA_1611_5` (19.5 % of value) plus `NA_1611_1` (1.1 %). The next four largest outcomes are 19.4, 18.6, 18.3 and 18.1 % of value.
- The EAL per `draw_id` (each draw as one version of the 10,000 years) ranges from 2.82 × 10⁹ to 3.66 × 10⁹ USD across the 10 draws.
- Per county, EAL / value runs from 0.042 % (Nassau) to 0.198 % (Escambia); Monroe is second lowest at 0.044 %.
- For storms with a positive portfolio loss, the median coefficient of variation of the portfolio loss across the 10 draws is 1.01.
- Rows with a positive loss at some county: 49,250 of 139,020; positive (row, county) pairs: 659,190 (7.1 % of the grid). Both are as in MAR-114: whether a loss is positive depends on the wind exceeding `v_thresh`, not on `v_half`.
- Loss matrices of (a) and (b) are identical (checked: `np.array_equal`), so the loss numbers hold for both.
- The prior's smallest `v_half` is 58.6 m/s and 15 of its 17 values exceed the base 74.7 m/s; the mean Emanuel damage ratio over the prior is 0.3 % at 35 m/s and 7.1 % at 55 m/s, against 0.7 % and 17.6 % for the base function (`docs/methodology/vulnerability.md`).

**Losses, MAR-114 (19-event prior, kept for comparison).** Cells vs centroid without draws: cells 7.616 × 10⁹, centroid 7.614 × 10⁹ USD; per county the cells/centroid EAL ratio is 0.943 (Brevard) to 1.050 (Glades), median 1.0003; the MAR-113 smoke run gave 7.61 × 10⁹ for the centroid loss. With the 19-event prior the draws/no-draws EAL ratio was 1.67–2.55 per county, and the 91.7 % year came with the prior's smallest `v_half` at 25.8 m/s, 0.1 m/s above `v_thresh` (event 1982324N10193, an East Pacific storm; now removed by the basin filter).

**Index (b), cat-in-a-circle at 50 km.** 3,057 of the 13,902 storms reach category ≥ 1 within 50 km of some centroid. With the MAR-132 prior, the (row, county) pairs with category 0 carry **36.0 %** of the total loss (rate-weighted sums; MAR-114: 50.2 %); for index (a), the pairs with zero wind carry 0.015 % (MAR-114: 0.03 %). A 50 km circle around one point of a county does not cover the county; the radius is a choice to revisit (≤ 250 km allowed; MAR-133). MAR-133 then measured 50, 75, 100 and 150 km, and the owner chose 75 km (MAR-118 Q6): see the MAR-145 section above.

**Tail dependence** (figure panel d): `λ_ij = P(A_i > q_i, A_j > q_j) / 0.01` on annual county losses per (year, draw), q = 0.99. Off-diagonal, MAR-132: min 0.000, median 0.084, max 0.889 (MAR-114: 0.007, 0.151, 0.919; first MAR-160 build: 0.001, 0.093, 0.895; MAR-160: 0.000, 0.084, 0.888). Since MAR-145 the figure shows MAR-160's (index (a), `sha256:30b17231…c6416472`; the same for index (b) at 75 km, whose loss matrix is identical). Every county has a positive 99 % quantile (no ties at zero). Counties are ordered by value, not by geography.

**Monroe County (the Keys).** Valued at 0.765 × 10⁹ USD, rank 54 of 67; EAL 0.339 × 10⁶ USD, EAL / value 0.044 % with the MAR-132 prior (MAR-114: 1.70 × 10⁶ USD, 0.22 %; first MAR-160 build: 1.74 × 10⁶ USD, 0.227 %; MAR-160: 0.87 × 10⁶ USD, 0.114 %).

- Its 138 cells: 29 on the Keys (lat < 25.2; 20 positive, 0.761 × 10⁹ USD) and 109 on the mainland Everglades part (43 positive, 3.6 × 10⁶ USD). The median positive cell is worth 152 USD; the state-wide mean positive cell is 0.67 × 10⁹ USD.
- **The LitPop file has no cell west of 81.604° W in the Keys.** Key West (about 24.56° N, 81.78° W) and the Lower Keys west of it have no LitPop cell at all, not even a zero-valued one: the file's land mask at 150 arcsec leaves them out (figure panel b). The cells that exist are LitPop's land mask; the TIGER/Line polygon includes water.
- Observation on plausibility (MAR-114): Monroe County's 2020 Census population is about 83,000 (general knowledge, not checked), roughly 0.4 % of Florida's; its LitPop value share is 0.016 %.
- **Owner decision (MAR-118 Q2, 2026-10-27): keep Monroe in the portfolio and state the gap.** The EventSets' scenario notes now carry it (configs `florida_counties.yaml` and `florida_counties_cat_in_circle.yaml`, `scenario_notes`). Text for the paper:

  > Monroe County (the Florida Keys) is kept in the portfolio with a known exposure gap. The LitPop grid (150 arcsec, Eberenz et al. 2020) has no cell centred west of 81.604° W in the Keys, so Key West and the Lower Keys carry no asset value; at this resolution LitPop's land mask leaves these small islands out. Monroe's value (0.765 × 10⁹ USD, 0.016 % of the portfolio's 4.893 × 10¹² USD) and its losses are therefore understated. We did not fill the gap from another source.

## Exposure summary figure

`research/data/d2-florida-eventset/exposure-summary/exposure_summary.png`, from `packages/climada/scripts/florida_exposure_summary.py` on the MAR-160 EventSet (a) (`sha256:30b17231…c6416472`; refreshed in MAR-145, before which it was drawn from the MAR-132 EventSet (a), `sha256:cad39887…46a6cbe6`), with its figure data (`counties.csv`, `monroe_cells.csv`, `tail_dependence.csv`, `summary.json`). Panels: (a) cells and centroids; (b) Monroe County cells against the county polygon; (c) county values with the 50 / 80 / 90 % ranks (5 / 15 / 22 counties); (d) tail dependence. The figure carries the LitPop, TIGER/Line and IRIS attribution.

```sh
cd packages/climada
pixi run --locked python scripts/florida_exposure_summary.py \
    --eventset ../../data/eventsets/florida-counties-iris-vulnerability \
    --cells ../../data/litpop-florida/locations/cells.parquet \
    --boundaries ../../data/litpop-florida/raw/tl_2025_us_county.zip \
    --out-dir ../../research/data/d2-florida-eventset/exposure-summary
```
