# D2: the Florida-counties EventSets (measurements)

- Issue: [MAR-114](https://linear.app/marc-prinzing/issue/MAR-114/p-05b-build-the-florida-counties-eventset-and-exposure-summary) (P-05b, part of MAR-31). Written by a worker agent on 2026-10-27.
- Decision this implements: D2 (SPEC §6.6, MAR-30), on MAR-113's 67-county table (`research/notes/d2-florida-litpop-locations.md`).
- Status: **observations**, not conclusions. Interpretation (which index, whether the prior's tail is acceptable, Monroe County) belongs to the owner and to MAR-31.
- Checksums, content hashes and config hashes: `research/data/d2-florida-eventset/checksums.json` and its `README.md`.

## What was built

| | Index (a) | Index (b) |
|---|---|---|
| Config | `packages/climada/configs/florida_counties.yaml` (SHA256 `eb8126a847cbfd8ece6a117be3dd3173bd1fbb3d8cadb5a3ac27eb64044a13a9`) | `packages/climada/configs/florida_counties_cat_in_circle.yaml` (SHA256 `ed8742705d7bd9315a8a191ee139e46fac94d213f3fd3789c82ce49ee9296a84`) |
| Index | wind at the county's value-weighted centroid (m/s) | cat-in-a-circle, 50 km around the centroid, Saffir-Simpson category 0–5 |
| EventSet content hash | `sha256:d8698f7d2985409f5a5024101d7ba839d42a127a29d5456e5871ecaaa3385131` | `sha256:81acd810655dc42edc3eb327f2ad6d4de3a666993c29fdfa80b48ee8b07a2d3e` |

Common settings: IRIS NA merged 10,000-year catalogue (SHA256 `7f7b224d…606bd`), 500 km proximity filter, H08 wind, Emanuel USA impact function (`v_thresh` 25.7, `v_half` 74.7, scale 1), 10 vulnerability draws per storm (`v_half` from Eberenz et al. 2021, NA2, the 19 wind-only events, MAR-103), seed 20261027, `licence: CC-BY-4.0`, `loss.unit` "USD (LitPop reference_year 2018)", and the value-unit caveat and the LitPop / TIGER/Line / IRIS attribution in the scenario text of `metadata.json`.

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

- Rows: 13,902 storms × 10 draws = 139,020; × 67 counties = 9,314,340 `values` rows, equal to MAR-113's estimate. No storm skipped.
- On disk: 10.8 MB (a) and 8.4 MB (b), of which `values.parquet` is 10.6 MB for (a). Not committed (only `metadata.json`, checksums and the summary).
- The sparse long format (ADR 0002 option) was not needed: the dense grid fits.
- Most of the time is the wind field at the 7,817 cells (the centroid-only build takes about a fifth); the per-cell draws add little.

## Observations (not interpreted)

**Losses.** Setup: as above; rate-weighted over all rows (draws carry `rate / 10`).

- Rows with a positive loss at some county: 49,250 of 139,020; positive (row, county) pairs: 659,190 (7.1 % of the grid).
- Portfolio expected annual loss: **14.44 × 10⁹ USD** with the draws (0.295 % of the 4.893 × 10¹² USD of value). Per county, EAL / value runs from 0.22 % (Monroe) to 0.82 % (Escambia).
- Without draws (base `v_half` 74.7, scratch builds, same rows): cells 7.616 × 10⁹, centroid 7.614 × 10⁹ USD. Per county the cells/centroid EAL ratio is 0.943 (Brevard) to 1.050 (Glades), median 1.0003. The MAR-113 smoke run gave 7.61 × 10⁹ for the centroid loss.
- Draws / no draws, EAL: 1.90 for the portfolio, 1.67–2.55 per county (thesis portfolio, MAR-25: 1.78).
- Annual portfolio loss per (year, draw), 100,000 outcomes, with draws: 90 % quantile 4.16 × 10⁹, 99 % 0.287 × 10¹², 99.6 % 1.01 × 10¹², 99.9 % 2.09 × 10¹² USD; maximum **4.49 × 10¹² USD, 91.7 % of the portfolio value**. Without draws the maximum year is 15.1 % of the value (cells) and the 99 % quantile 0.181 × 10¹². Not traced to the outcome's draws. The wind-only prior's smallest `v_half` is 25.8 m/s, 0.1 m/s above `v_thresh` (25.7), and its 5 % quantile 35.9 m/s (metadata, `vulnerability_draws` record); with `v_half` that close to `v_thresh`, the Emanuel damage ratio is near 1 for any wind a little above 25.7 m/s. Whether this tail is acceptable is for the owner (MAR-103 / MAR-31).

**Index (b), cat-in-a-circle at 50 km.** 3,057 of the 13,902 storms reach category ≥ 1 within 50 km of some centroid. The (row, county) pairs with category 0 carry **50.2 %** of the total loss (rate-weighted sums); for index (a), the pairs with zero wind carry 0.03 %. A 50 km circle around one point of a county does not cover the county; the radius is a choice to revisit (≤ 250 km allowed).

**Tail dependence** (figure panel d): `λ_ij = P(A_i > q_i, A_j > q_j) / 0.01` on annual county losses per (year, draw), q = 0.99. Off-diagonal: min 0.007, median 0.151, max 0.919. Every county has a positive 99 % quantile (no ties at zero). Counties are ordered by value, not by geography.

**Monroe County (the Keys).** Valued at 0.765 × 10⁹ USD, rank 54 of 67, EAL / value 0.22 % (the lowest).

- Its 138 cells: 29 on the Keys (lat < 25.2; 20 positive, 0.761 × 10⁹ USD) and 109 on the mainland Everglades part (43 positive, 3.6 × 10⁶ USD). The median positive cell is worth 152 USD; the state-wide mean positive cell is 0.67 × 10⁹ USD.
- **The LitPop file has no cell west of 81.604° W in the Keys.** Key West (about 24.56° N, 81.78° W) and the Lower Keys west of it have no LitPop cell at all, not even a zero-valued one: the file's land mask at 150 arcsec leaves them out (figure panel b). The cells that exist are LitPop's land mask; the TIGER/Line polygon includes water.
- Observation on plausibility: Monroe County's 2020 Census population is about 83,000 (general knowledge, not checked in this session), roughly 0.4 % of Florida's; its LitPop value share is 0.016 %. With Key West missing from the grid, the county's value looks **implausibly low**; not checked against any other value source. Options for the owner: accept and state it; add the missing island value from another source; or drop Monroe from the paper portfolio.

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
