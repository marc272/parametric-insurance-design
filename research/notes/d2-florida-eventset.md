# D2: the Florida-counties EventSets (measurements)

- Issues: [MAR-114](https://linear.app/marc-prinzing/issue/MAR-114/p-05b-build-the-florida-counties-eventset-and-exposure-summary) (P-05b, part of MAR-31), first build; [MAR-132](https://linear.app/marc-prinzing/issue/MAR-132/f-12-basin-filter-for-the-vulnerability-prior-drop-east-pacific-events) (F-12), rebuild with the basin filter of the `v_half` prior and the Monroe note. Written by worker agents on 2026-10-27.
- Decisions this implements: D2 (SPEC §6.6, MAR-30), on MAR-113's 67-county table (`research/notes/d2-florida-litpop-locations.md`); the owner's answers to MAR-118 Q1 (basin filter on the wind-only prior, default for C1 and the paper) and Q2 (keep Monroe County and state its LitPop gap).
- Status: **observations**, not conclusions. Interpretation (which index, whether the prior's tail is acceptable) belongs to the owner and to MAR-31.
- Checksums, content hashes and config hashes: `research/data/d2-florida-eventset/checksums.json` and its `README.md`. They are those of the MAR-132 rebuild; the MAR-114 values are kept below where they are compared.

## What was built

Current EventSets (MAR-132 rebuild):

| | Index (a) | Index (b) |
|---|---|---|
| Config | `packages/climada/configs/florida_counties.yaml` (SHA256 `09ae66710528a14af95e198e3a82ef91912c7cf59fc5f38481a0f2556c2ed379`) | `packages/climada/configs/florida_counties_cat_in_circle.yaml` (SHA256 `4d6323d1613b92747357548c126947263cce3a06a4eed00a6391a093b0fbe1c0`) |
| Index | wind at the county's value-weighted centroid (m/s) | cat-in-a-circle, 50 km around the centroid, Saffir-Simpson category 0–5 |
| EventSet content hash | `sha256:cad398875afb467f5d1475e6a47952116391be18f249cc484990436f46a6cbe6` | `sha256:c7d6b76519d88bba4143d999bed81c78a0ff213777528aed3d7cea5ff2dfa67f` |
| MAR-114 build (19-event prior) | config SHA256 `eb8126a8…44a13a9`, content hash `sha256:d8698f7d2985409f5a5024101d7ba839d42a127a29d5456e5871ecaaa3385131` | config SHA256 `ed874270…9296a84`, content hash `sha256:81acd810655dc42edc3eb327f2ad6d4de3a666993c29fdfa80b48ee8b07a2d3e` |

Common settings: IRIS NA merged 10,000-year catalogue (SHA256 `7f7b224d…606bd`), 500 km proximity filter, H08 wind, Emanuel USA impact function (`v_thresh` 25.7, `v_half` 74.7, scale 1), 10 vulnerability draws per storm, seed 20261027, `licence: CC-BY-4.0`, `loss.unit` "USD (LitPop reference_year 2018)", and the value-unit caveat, the Monroe County note and the LitPop / TIGER/Line / IRIS attribution in the scenario text of `metadata.json`.

**The `v_half` prior.** Eberenz et al. (2021), region NA2, event-wise fits (CLIMADA's `tc_impf_cal_v01_EDR.csv`, SHA256 `bde5670d…a3343e39`):

| Prior | Events | min | 5 % | 25 % | median | 75 % | 95 % | max |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MAR-132 (current): wind-only, North Atlantic genesis basin (`wind_only: true`, `basins: [NA]`) | 17 | 58.6 | 70.0 | 90.2 | 113.5 | 160.3 | 223.0 | 232.4 |
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

The MAR-132 rebuilds ran at the same time on a machine with a load average of about 40–50 from other jobs (10 cores), so their times are not comparable with MAR-114's.

- Rows: 13,902 storms × 10 draws = 139,020; × 67 counties = 9,314,340 `values` rows, equal to MAR-113's estimate. No storm skipped.
- On disk: 10.8 MB (a) and 8.4 MB (b), of which `values.parquet` is 10.6 MB for (a). Not committed (only `metadata.json`, checksums and the summary).
- The sparse long format (ADR 0002 option) was not needed: the dense grid fits.
- Most of the time is the wind field at the 7,817 cells (the centroid-only build takes about a fifth); the per-cell draws add little.

## Observations (not interpreted)

**Losses, MAR-132 rebuild (current prior, 17 events).** Setup: the current EventSets above (content hashes `sha256:cad39887…46a6cbe6` (a) and `sha256:c7d6b765…2dfa67f` (b)); rate-weighted over all rows (draws carry `rate / 10`). The base is `configs/florida_counties_no_draws.yaml` (MAR-32: no draws, `v_half` 74.7, the same 13,902 storms, content hash `sha256:07eb5c9a808af45f7d05932b5d78f0cc9b1142f37aef8c9749138dc8c1f379e5`, EAL 7,615,672,695 USD; `research/data/p06-storm-eventset/checksums.json`), not rebuilt here.

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

**Index (b), cat-in-a-circle at 50 km.** 3,057 of the 13,902 storms reach category ≥ 1 within 50 km of some centroid. With the MAR-132 prior, the (row, county) pairs with category 0 carry **36.0 %** of the total loss (rate-weighted sums; MAR-114: 50.2 %); for index (a), the pairs with zero wind carry 0.015 % (MAR-114: 0.03 %). A 50 km circle around one point of a county does not cover the county; the radius is a choice to revisit (≤ 250 km allowed; MAR-133).

**Tail dependence** (figure panel d): `λ_ij = P(A_i > q_i, A_j > q_j) / 0.01` on annual county losses per (year, draw), q = 0.99. Off-diagonal, MAR-132: min 0.000, median 0.084, max 0.889 (MAR-114: 0.007, 0.151, 0.919). Every county has a positive 99 % quantile (no ties at zero). Counties are ordered by value, not by geography.

**Monroe County (the Keys).** Valued at 0.765 × 10⁹ USD, rank 54 of 67; EAL 0.339 × 10⁶ USD, EAL / value 0.044 % (MAR-114: 1.70 × 10⁶ USD, 0.22 %).

- Its 138 cells: 29 on the Keys (lat < 25.2; 20 positive, 0.761 × 10⁹ USD) and 109 on the mainland Everglades part (43 positive, 3.6 × 10⁶ USD). The median positive cell is worth 152 USD; the state-wide mean positive cell is 0.67 × 10⁹ USD.
- **The LitPop file has no cell west of 81.604° W in the Keys.** Key West (about 24.56° N, 81.78° W) and the Lower Keys west of it have no LitPop cell at all, not even a zero-valued one: the file's land mask at 150 arcsec leaves them out (figure panel b). The cells that exist are LitPop's land mask; the TIGER/Line polygon includes water.
- Observation on plausibility (MAR-114): Monroe County's 2020 Census population is about 83,000 (general knowledge, not checked), roughly 0.4 % of Florida's; its LitPop value share is 0.016 %.
- **Owner decision (MAR-118 Q2, 2026-10-27): keep Monroe in the portfolio and state the gap.** The EventSets' scenario notes now carry it (configs `florida_counties.yaml` and `florida_counties_cat_in_circle.yaml`, `scenario_notes`). Text for the paper:

  > Monroe County (the Florida Keys) is kept in the portfolio with a known exposure gap. The LitPop grid (150 arcsec, Eberenz et al. 2020) has no cell centred west of 81.604° W in the Keys, so Key West and the Lower Keys carry no asset value; at this resolution LitPop's land mask leaves these small islands out. Monroe's value (0.765 × 10⁹ USD, 0.016 % of the portfolio's 4.893 × 10¹² USD) and its losses are therefore understated. We did not fill the gap from another source.

## Exposure summary figure

`research/data/d2-florida-eventset/exposure-summary/exposure_summary.png`, from `packages/climada/scripts/florida_exposure_summary.py` on EventSet (a) (content hash above), with its figure data (`counties.csv`, `monroe_cells.csv`, `tail_dependence.csv`, `summary.json`). Panels: (a) cells and centroids; (b) Monroe County cells against the county polygon; (c) county values with the 50 / 80 / 90 % ranks (5 / 15 / 22 counties); (d) tail dependence. The figure carries the LitPop, TIGER/Line and IRIS attribution.

```sh
cd packages/climada
pixi run --locked python scripts/florida_exposure_summary.py \
    --eventset ../../data/eventsets/florida-counties-iris-vulnerability \
    --cells ../../data/litpop-florida/locations/cells.parquet \
    --boundaries ../../data/litpop-florida/raw/tl_2025_us_county.zip \
    --out-dir ../../research/data/d2-florida-eventset/exposure-summary
```
