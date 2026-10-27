# D2: Florida county locations from LitPop (measurements)

- Issue: [MAR-113](https://linear.app/marc-prinzing/issue/MAR-113/p-05a-florida-county-locations-from-litpop-locations-table-with) (P-05a, part of MAR-31). Written by a worker agent on 2026-10-27.
- Decision this implements: D2 (SPEC §6.6, MAR-30), with the method proposed in `research/notes/d2-paper-portfolio.md`.
- Status: **observations**, not conclusions. Interpretation (skew, framing, which index) belongs to the owner and to MAR-114/MAR-31.

## How the table was built

```sh
cd packages/climada
pixi run --locked florida-locations          # writes ../../data/litpop-florida/
```

- **Inputs** (pinned in `packages/climada/src/parametric_insurance_design_climada/litpop_florida_manifest.json`; both downloaded through the script and checked):

| File | Source | Size (bytes) | MD5 | SHA256 |
|---|---|---|---|---|
| `LitPop_150arcsec_USA.hdf5` | CLIMADA data API, `LitPop_150arcsec_USA` v3, uuid `678e9551-32ca-40f3-9881-9bd38412c1cd` (record `active` on 2026-10-27) | 51,228,208 | `9f019394e1736e67c6fd5572875a2fa1` (= the API record and the D2 note) | `16eee0b8ffbe200e86881a4f759b7cd0d8924e91ec60d27907c5a2f9a4242c49` |
| `tl_2025_us_county.zip` | U.S. Census Bureau, TIGER/Line 2025, County and Equivalent Entities (national file) | 83,989,800 | `026de3fea9492009a0ab9d2b526ea9c5` | `9c6e9d9076abce2670d1de255de3710c35ecca00a7005d88e012dec52d95f763` |

- **Method** (`portfolio_litpop.aggregate_cells`): every LitPop cell centre inside the region (the 67 counties' bounding box widened by 0.5°: lon −88.135 to −79.474, lat 23.896 to 31.501) is assigned to the TIGER/Line county polygon it intersects (polygons reprojected NAD83 → WGS 84). A county's `value` is the sum of its cells; its `lat`/`lon` is the value-weighted mean of its cells' coordinates.
- **Outputs** (git-ignored `data/litpop-florida/locations/`; the first and third are also committed in `research/data/d2-florida-litpop/`, CC BY 4.0):

| File | Size (bytes) | SHA256 |
|---|---|---|
| `locations.yaml` (the 67-county table) | 12,744 | `d0aed5d286a2db2472bd046a1a01a0d894ee72fbb8d4ef20b5e943b154a1cdb2` |
| `cells.parquet` (10,678 region cells with their county) | 174,365 | `7a3ac58782aa4a160d4ff804d8171abb505872a89a97a75e05a6af28c5d73ca6` |
| `provenance.json` | 4,293 | holds `created_at`, so its hash changes per run; the committed copy is `7ac7d238b570b1d2d92b5b2641addb0689f0ceb39aae4055fa9ff6b4b45d378e` |

  Rebuilding with `--overwrite` gave the same `locations.yaml` and `cells.parquet` bytes (checked twice on 2026-10-27, osx-arm64, CLIMADA 6.1.0, geopandas 1.1.4, shapely 2.2.0).

## Where the cells went

| Group | Cells | Value (USD) |
|---|---:|---:|
| All cells in the USA file | 643,099 | 65.385 × 10¹² |
| Outside the region (rest of the US) | 632,421 | 60.307 × 10¹² |
| In a Florida county | **7,817** | **4.893 × 10¹²** (7.48 % of the US file) |
| In another county inside the region (Alabama 1,094; Georgia 1,767) | 2,861 | 0.184 × 10¹² |
| In the region but in no county | **0** | 0 |
| On a shared county edge (tie-broken) | 0 | – |

- No cell was outside every county, so nothing was left unassigned. The LitPop USA file has no cells over open water near Florida, and TIGER/Line county polygons include coastal water areas.
- No county is empty, and none is zero-valued. 536 of the 7,817 Florida cells (6.9 %) have value 0 and carry no weight in the centroids.
- Every value-weighted centroid lies inside its own county polygon (`centroid_in_unit` is true for all 67).

## Cell counts per county

- Mean 116.7, median 101, min 33 (Union), max 296 (Palm Beach). Quartiles 79 and 143.
- Fewest cells: Union 33, Pinellas 38, Bradford 43, Seminole 46, Gilchrist 48. Most: Palm Beach 296, Collier 274, Miami-Dade 260, Polk 259, Marion 236.
- Per county, cells and positive cells are in the table below.

## Value skew across counties

| Measure | Value |
|---|---|
| Total | 4.893 × 10¹² USD |
| Largest county (Miami-Dade) | 14.7 % |
| Top 5 | 51.8 % (Miami-Dade, Broward, Orange, Hillsborough, Palm Beach) |
| Top 10 | 69.9 % |
| Counties holding 50 / 80 / 90 % of the value | 5 / 15 / 22 |
| Median county | 19.8 × 10⁹ USD |
| Largest / median | 36.4 |
| Largest / smallest (Miami-Dade / Lafayette) | 5,854 |
| Herfindahl index | 0.0684, i.e. an effective number of 14.6 equal counties |

Observations, not interpreted:

- The skew the D2 note expected is there: five south-east and central counties hold half of the value, and 45 counties each hold under 1 %.
- Monroe County (the Keys) is valued at 0.76 × 10⁹ USD, rank 54 of 67, with 63 of its 138 cells positive. This was not checked against any other source; at 150 arcsec (about 4.6 km) many Keys cells may be water-dominated in the LitPop inputs.
- LitPop (1, 1) disaggregates by Lit × Pop, which concentrates value in bright, dense cells more than population alone would. Whether this matters for the paper is for MAR-31.

## The LitPop value unit

- The file itself records `value_unit = "USD"`, `ref_year = 2018` and the description "LitPop Exposure for ['USA'] at 150 as, year: 2018, financial mode: pc, exp: (1, 1), admin1_calc: False" (read with `climada.entity.Exposures.from_hdf5`).
- The API's data-type record describes `fin_mode = pc` as World Bank produced capital "in constant 2014 USD".
- CLIMADA's code that computes the national total (`climada.util.finance.world_bank_wealth_account`, read in the CLIMADA 6.1.0 install; the file was made with CLIMADA v4.1.1 / v3.1.2, whose code was **not** read) takes the latest World Bank wealth-accounts year (2014, constant 2014 USD) and, for a later reference year, scales it by the ratio of World Bank GDP (`NY.GDP.MKTP.CD`, current USD) in the reference year to GDP in 2014. It then divides by 1.24 to remove built-up land.
- **Observation.** If that code path produced this file, the 2018 values are 2014 constant-USD produced capital scaled by nominal US GDP growth 2014 → 2018, which is neither constant 2014 USD nor a 2018 wealth estimate. The table records the unit as "USD (LitPop reference_year 2018)". The EventSet `metadata.json` (MAR-114) should state it the same way, with this caveat. Not verified against the World Bank series themselves.

## Dense events × locations grid for IRIS over these 67 locations

`packages/climada/scripts/estimate_florida_grid.py` counts, without running CLIMADA, the IRIS storms that the pipeline would keep (`tracks.storms_near_locations`, the same filter as `build_eventset`), on the pinned merged catalogue (`IRIS_NA_10000Y_merged.txt`, SHA256 `7f7b224d…606bd`, 67,506 storms, 1,687,818 track points):

```sh
pixi run --locked python scripts/estimate_florida_grid.py \
    --catalogue ../../data/iris/transformed/IRIS_NA_10000Y_merged.txt \
    --locations ../../data/litpop-florida/locations/locations.yaml \
    --cells ../../data/litpop-florida/locations/cells.parquet \
    --compare-eventset ../../parity/tests/data/thesis_eventset
```

| | Thesis (9 Miami assets) | Florida (67 centroids) | Florida (7,817 cells) |
|---|---:|---:|---:|
| Storms within 500 km (pipeline rows, no draws) | 6,057 | **13,902** | 14,569 |
| Storms within 300 km (`max_dist_eye_km`: an upper bound on rows with any non-zero wind) | 3,397 | 9,572 | 10,123 |
| Storms with a single track point among them | 0 | 0 | – |
| Dense grid, no draws (rows × locations) | 54,513 | **931,434** | 113.9 × 10⁶ |
| Dense grid, 10 vulnerability draws | 545,130 | **9,314,340** | – |
| Dense float64 index + loss in memory, 10 draws | 8.3 MiB | **142 MiB** | – |

- The thesis count (6,057) equals the parity fixture's row count, so the filter matches the pipeline.
- With 67 centroids the grid is about 17 times the thesis grid; with 10 draws it is about 9.3 million (row, location) cells in the `values` long table.
- If losses were computed per cell (the D2 note's "loss on every cell, summed per county"), the hazard grid would be 14,569 storms × 7,817 cells, about 1.1 × 10⁸ entries (0.85 GiB as dense float64). CLIMADA stores wind as a sparse matrix, so its actual size depends on the footprint; not measured.

**Smoke run (not the MAR-114 EventSet).** To check that the table is consumable, `pixi run build-eventset` was run once on `locations.yaml` with the `configs/thesis.yaml` settings (500 km, H08, Emanuel USA `v_half` 74.7, no draws, `licence: CC-BY-4.0`), writing to a scratch directory that was not kept. Observed:

- it ran to the end in about 2 minutes wall time (osx-arm64, from file timestamps; peak memory not measured);
- 13,902 rows × 67 locations, equal to the estimate above; no storm skipped;
- 5,890 rows with non-zero wind at some centroid, 4,349 rows with a non-zero loss at some county, and 49,167 non-zero (row, location) loss cells, 5.3 % of the dense grid;
- the free columns (`n_cells`, `n_cells_positive`, `centroid_in_unit`) went through to the EventSet's `locations` table;
- portfolio expected annual loss `rates @ loss.sum(1)` = 7.61 × 10⁹ USD for 4.893 × 10¹² USD of value (setup: IRIS NA 10,000 years, centroid wind, Emanuel USA, no vulnerability draws, no noise). Recorded only as a sanity figure for MAR-114; not a result.
- EventSet content hash `sha256:d8bd94f1c2818154d8cd8fcd1d5b68e1c01381124d178b07037257836c708d79`. The config was `configs/thesis.yaml` with `locations: {yaml: <locations.yaml>}`, `licence: CC-BY-4.0` and absolute paths (config file SHA256 `0d5e8c07…b1a1b0`, machine-specific because of the paths).

## Per-county table

Sorted by value. `location_id` is the county GEOID (state FIPS 12 + county FIPS). Values in 10⁹ USD.

| Rank | location_id | County | lat | lon | Value | Share % | Cum. % | Cells | Positive cells |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 12086 | Miami-Dade | 25.7716 | -80.3166 | 721.43 | 14.74 | 14.7 | 260 | 185 |
| 2 | 12011 | Broward | 26.1295 | -80.2267 | 583.36 | 11.92 | 26.7 | 166 | 83 |
| 3 | 12095 | Orange | 28.5245 | -81.3850 | 450.62 | 9.21 | 35.9 | 151 | 146 |
| 4 | 12057 | Hillsborough | 27.9860 | -82.4078 | 394.57 | 8.06 | 43.9 | 145 | 145 |
| 5 | 12099 | Palm Beach | 26.6049 | -80.1383 | 386.72 | 7.90 | 51.8 | 296 | 195 |
| 6 | 12031 | Duval | 30.3005 | -81.6214 | 244.66 | 5.00 | 56.8 | 122 | 122 |
| 7 | 12103 | Pinellas | 27.9050 | -82.7239 | 212.24 | 4.34 | 61.2 | 38 | 38 |
| 8 | 12071 | Lee | 26.5753 | -81.8538 | 157.34 | 3.22 | 64.4 | 98 | 98 |
| 9 | 12105 | Polk | 28.0338 | -81.8372 | 144.12 | 2.95 | 67.3 | 259 | 258 |
| 10 | 12117 | Seminole | 28.6970 | -81.3273 | 126.69 | 2.59 | 69.9 | 46 | 46 |
| 11 | 12101 | Pasco | 28.2509 | -82.5377 | 126.04 | 2.58 | 72.5 | 102 | 102 |
| 12 | 12127 | Volusia | 29.0776 | -81.1243 | 101.70 | 2.08 | 74.6 | 172 | 171 |
| 13 | 12009 | Brevard | 28.2058 | -80.6928 | 94.71 | 1.94 | 76.5 | 150 | 138 |
| 14 | 12081 | Manatee | 27.4689 | -82.5303 | 87.50 | 1.79 | 78.3 | 114 | 114 |
| 15 | 12021 | Collier | 26.2084 | -81.7231 | 85.50 | 1.75 | 80.1 | 274 | 267 |
| 16 | 12115 | Sarasota | 27.2225 | -82.4341 | 84.71 | 1.73 | 81.8 | 79 | 78 |
| 17 | 12097 | Osceola | 28.2670 | -81.4057 | 83.32 | 1.70 | 83.5 | 204 | 198 |
| 18 | 12111 | St. Lucie | 27.3279 | -80.3555 | 79.63 | 1.63 | 85.1 | 76 | 75 |
| 19 | 12069 | Lake | 28.7277 | -81.7707 | 68.05 | 1.39 | 86.5 | 157 | 157 |
| 20 | 12073 | Leon | 30.4597 | -84.2784 | 65.72 | 1.34 | 87.8 | 94 | 93 |
| 21 | 12083 | Marion | 29.1260 | -82.1182 | 65.05 | 1.33 | 89.2 | 236 | 230 |
| 22 | 12033 | Escambia | 30.4788 | -87.2676 | 61.35 | 1.25 | 90.4 | 95 | 95 |
| 23 | 12001 | Alachua | 29.6586 | -82.3755 | 52.21 | 1.07 | 91.5 | 133 | 133 |
| 24 | 12019 | Clay | 30.1267 | -81.7799 | 48.08 | 0.98 | 92.5 | 90 | 90 |
| 25 | 12053 | Hernando | 28.4917 | -82.5231 | 44.64 | 0.91 | 93.4 | 77 | 77 |
| 26 | 12109 | St. Johns | 29.9876 | -81.4230 | 40.53 | 0.83 | 94.2 | 95 | 95 |
| 27 | 12015 | Charlotte | 26.9662 | -82.1201 | 29.57 | 0.60 | 94.8 | 102 | 101 |
| 28 | 12119 | Sumter | 28.8821 | -82.0077 | 26.72 | 0.55 | 95.4 | 75 | 74 |
| 29 | 12035 | Flagler | 29.5342 | -81.2249 | 26.43 | 0.54 | 95.9 | 71 | 71 |
| 30 | 12061 | Indian River | 27.6535 | -80.4356 | 26.17 | 0.53 | 96.4 | 79 | 79 |
| 31 | 12085 | Martin | 27.1412 | -80.2347 | 25.34 | 0.52 | 97.0 | 91 | 83 |
| 32 | 12005 | Bay | 30.1925 | -85.6468 | 22.12 | 0.45 | 97.4 | 118 | 115 |
| 33 | 12113 | Santa Rosa | 30.5901 | -87.0649 | 20.38 | 0.42 | 97.8 | 139 | 136 |
| 34 | 12017 | Citrus | 28.8654 | -82.4631 | 19.84 | 0.41 | 98.2 | 82 | 80 |
| 35 | 12091 | Okaloosa | 30.5612 | -86.5753 | 18.92 | 0.39 | 98.6 | 140 | 116 |
| 36 | 12055 | Highlands | 27.4865 | -81.4612 | 12.83 | 0.26 | 98.9 | 159 | 157 |
| 37 | 12023 | Columbia | 30.1705 | -82.6523 | 7.02 | 0.14 | 99.0 | 109 | 95 |
| 38 | 12089 | Nassau | 30.6204 | -81.5782 | 6.40 | 0.13 | 99.2 | 88 | 88 |
| 39 | 12107 | Putnam | 29.6301 | -81.6906 | 5.63 | 0.11 | 99.3 | 111 | 111 |
| 40 | 12051 | Hendry | 26.7100 | -81.2355 | 3.73 | 0.08 | 99.4 | 166 | 162 |
| 41 | 12131 | Walton | 30.5849 | -86.2076 | 3.70 | 0.08 | 99.4 | 143 | 131 |
| 42 | 12093 | Okeechobee | 27.2411 | -80.8271 | 3.69 | 0.08 | 99.5 | 118 | 112 |
| 43 | 12027 | DeSoto | 27.2031 | -81.8615 | 2.54 | 0.05 | 99.6 | 77 | 77 |
| 44 | 12039 | Gadsden | 30.5859 | -84.5633 | 2.40 | 0.05 | 99.6 | 77 | 77 |
| 45 | 12063 | Jackson | 30.7899 | -85.2277 | 2.23 | 0.05 | 99.6 | 127 | 127 |
| 46 | 12007 | Bradford | 29.9402 | -82.1128 | 1.92 | 0.04 | 99.7 | 43 | 43 |
| 47 | 12003 | Baker | 30.2781 | -82.1416 | 1.89 | 0.04 | 99.7 | 89 | 83 |
| 48 | 12049 | Hardee | 27.5580 | -81.8158 | 1.87 | 0.04 | 99.8 | 88 | 88 |
| 49 | 12121 | Suwannee | 30.2781 | -82.9880 | 1.54 | 0.03 | 99.8 | 97 | 97 |
| 50 | 12123 | Taylor | 30.0980 | -83.5842 | 1.30 | 0.03 | 99.8 | 143 | 127 |
| 51 | 12129 | Wakulla | 30.1896 | -84.3408 | 1.21 | 0.02 | 99.8 | 86 | 81 |
| 52 | 12133 | Washington | 30.7191 | -85.5737 | 0.98 | 0.02 | 99.9 | 85 | 85 |
| 53 | 12075 | Levy | 29.4177 | -82.6380 | 0.89 | 0.02 | 99.9 | 156 | 156 |
| 54 | 12087 | Monroe | 24.9333 | -80.7198 | 0.76 | 0.02 | 99.9 | 138 | 63 |
| 55 | 12043 | Glades | 26.8364 | -81.2426 | 0.67 | 0.01 | 99.9 | 144 | 134 |
| 56 | 12059 | Holmes | 30.8136 | -85.6789 | 0.62 | 0.01 | 99.9 | 71 | 71 |
| 57 | 12079 | Madison | 30.4611 | -83.4174 | 0.60 | 0.01 | 99.9 | 103 | 101 |
| 58 | 12047 | Hamilton | 30.5157 | -82.9732 | 0.49 | 0.01 | 99.9 | 74 | 72 |
| 59 | 12125 | Union | 30.0051 | -82.3596 | 0.48 | 0.01 | 100.0 | 33 | 33 |
| 60 | 12013 | Calhoun | 30.4449 | -85.0636 | 0.41 | 0.01 | 100.0 | 82 | 81 |
| 61 | 12029 | Dixie | 29.6329 | -83.1062 | 0.38 | 0.01 | 100.0 | 101 | 98 |
| 62 | 12045 | Gulf | 30.0115 | -85.2374 | 0.31 | 0.01 | 100.0 | 76 | 73 |
| 63 | 12065 | Jefferson | 30.5234 | -83.8772 | 0.29 | 0.01 | 100.0 | 89 | 87 |
| 64 | 12041 | Gilchrist | 29.6405 | -82.8401 | 0.20 | 0.00 | 100.0 | 48 | 48 |
| 65 | 12077 | Liberty | 30.4282 | -84.9375 | 0.14 | 0.00 | 100.0 | 121 | 107 |
| 66 | 12037 | Franklin | 29.8034 | -84.8317 | 0.14 | 0.00 | 100.0 | 75 | 64 |
| 67 | 12067 | Lafayette | 30.0702 | -83.1901 | 0.12 | 0.00 | 100.0 | 74 | 68 |

## Open points for MAR-114 and MAR-31

- **Index location.** The pipeline gives each location one centroid, so `build_eventset` on `locations.yaml` computes wind and loss at the value-weighted centroid (index (a), SPEC §6.6). The D2 note proposed computing the loss on every cell and summing per county; `cells.parquet` makes that possible, but `build_eventset` has no per-cell loss path today. Which loss truth MAR-114 uses is a method choice, not made here.
- **Value unit** caveat above, for the EventSet `metadata.json`.
- **Attribution.** Every output from this table cites LitPop (CC BY 4.0, Eberenz et al. 2020, the ETH DOI, and "CLIMADA data API, dataset `LitPop_150arcsec_USA` v3") and acknowledges "U.S. Census Bureau, 2025 TIGER/Line Shapefiles" (`docs/data-sources.md`).
