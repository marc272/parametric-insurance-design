# R-01 data inventory: CRC Open and the VELO/CDT asset database

**Status: Draft — CRC Open part prepared by an agent from public sources; VELO/CDT part and licence terms pending owner (MAR-41)**

- Linear: [MAR-41](https://linear.app/marc-prinzing/issue/MAR-41/r-01-inventory-crc-open-and-the-velocdt-asset-database), labelled **Human**. Spec: `docs/SPEC.md` §6.6 (portfolio, D2) and §8 (CRC Showcase R-01).
- Feeds: the CRC adapter (MAR-42, MAR-43), the CRC showcase, and the paper portfolio decision D2 via spike P-05 (MAR-30).
- **Who wrote what.** Section 1 (CRC Open) was prepared by an agent from public, unauthenticated sources. Every fact names its source in [Sources and access log](#sources-and-access-log). Sections 2 and 3.2 are **placeholders for the owner**: agents have no VELO/CDT access and handle no credentials. Section 4 is the **agent's conditional recommendation**. The owner approves or replaces it.
- **No data is committed.** This file holds metadata only: catalogue fields, counts and URLs.

Contents:

1. [CRC Open (public releases)](#1-crc-open-public-releases)
2. [VELO/CDT asset database (owner)](#2-velocdt-asset-database-owner)
3. [Licence and publication constraints](#3-licence-and-publication-constraints)
4. [Recommendation for P-05 (agent, conditional)](#4-recommendation-for-p-05-agent-conditional)
5. [Unverified points and follow-ups](#5-unverified-points-and-follow-ups)
6. [Sources and access log](#sources-and-access-log)

---

## 1. CRC Open (public releases)

### 1.1 Release and access

| Item | Value | Source |
|---|---|---|
| Release ID | `ssp585-global-2026-10-20-v1` | [S1] |
| Catalogue | `https://data.riskthinking.ai/crc-open/ssp585-global-2026-10-20-v1/_CATALOG.json` (2,107,597 bytes, `Last-Modified: Wed, 21 Oct 2026 08:43:40 GMT`, served `immutable`) | [S1] |
| Catalogue SHA256 | `67cd35c76531838569bdaaae55702a208a80f1ebf06b0eaf2350e5583cce1863`. It matches the release's `_SUCCESS` marker | [S1], [S2] |
| Catalogue fields | `schema_version` `1.3`, `catalog_version` 1, `fixture: false`, `retrieved_at` `2026-10-20T21:22:32Z`, `pathways` `["ssp585"]`, `excluded_hazards` `{}` | [S1] |
| Size | 63 hazards, 5,243 Parquet partitions, 840,429,769 rows (each count summed from the catalogue) | [S1]; same totals in the executed notebook [S7] |
| Licence and attribution (machine-readable) | `licence: "CC-BY-NC-4.0"`, `attribution: "Riskthinking.AI bias-corrected climate distributions"` | [S1] |
| File format | Parquet. One file per hazard and H3 resolution-0 cell. The relative path is `{hazard}/h3_r0={cell}/part-00000.parquet`, and each partition lists `rows`, `size_bytes`, `sha256`, `horizons` and `curve_kinds` | [S1] |
| Access | Public HTTPS, no credentials. The `crc-sdk` package (≥ 0.8.1, AGPL-3.0-or-later) reads it with `HazardDataset.crc_open(release=..., source="https://data.riskthinking.ai/crc-open")`, pinned release, verified local cache. The partition URLs also work with DuckDB `read_parquet` (HTTP range requests, filter pushdown). | [S3], [S7], [S8] |
| Later releases | None found on 2026-10-25. The source root has no public index (`/crc-open/`, `/crc-open/index.json` return 404). Neither `crc-sdk` 0.8.1 (2026-10-21) nor 0.9.0a1 (2026-10-23) names another release. Completed release IDs are immutable. | [S3], [S4], [S6] |
| Earlier sampled release | `ssp585-fixture-2026-10-08-v2` (63 hazards, 47,013 rows; samples around 8 cities, none in the IRIS domain). It is used in the CRC docs for examples only. | [S5] |

### 1.2 What the data is (and is not)

- **Per-cell marginal distributions, not events.** Each row is one fitted curve for one key `(hazard_name, horizon, pathway, cell_index, source_id)`. The curve is one of five kinds: `fitted`, `hurdle` (a point mass plus a fitted positive part), `point_mass`, `tabulated` (probability/value lists) or `no_data` (with a reason code). There is no event set and no spatial dependence between cells. [S3]
- **Return values.** These are evaluated, not stored. For upper-tail hazards the SDK evaluates return period *T* at non-exceedance probability 1 − 1/*T*. Its evaluation outputs are columns `value_rp{T}`. [S3], [S7]
- **Spatial join.** Point assets go to the dataset's H3 resolution. Rows with source geometry (WKB) are refined with `ST_Covers`, and other rows keep cell-level precision (`spatial_match` = `exact_geometry` or `h3_cell`). Unmatched or ambiguous joins raise. `no_data` evaluates to null; it does not mean zero risk. [S3]
- **Consequence for this program.** Before CRC curves can be used as `EventSet` input, a dependence model is needed, which is R-04 (IRIS empirical copula). Without one they can only give per-location marginals (R-02) and return-level comparisons (R-03).

### 1.3 Hazards relevant to the program

All rows below: pathway `ssp585` only, `pooling: "pooled"`, `tail: "upper"`. No historical baseline is included. The sizes are the full global release. [S1]

| Hazard (`hazard_name`) | Unit | Statistic (`value_semantics`) | H3 res. | Horizons (labels) | `probability_semantics` | Catalogue note | Partitions / rows / size |
|---|---|---|---|---|---|---|---|
| `cyclone` | m/s | "pooled cyclone wind speed; time and scenario independent" | r5 | 2010, 2025–2100 every 5 y (17 labels) | **null** (not declared) | "Time- and scenario-independent pooled distribution broadcast upstream across labels; SSP585-labelled rows are not SSP585 projections" | 95 / 17,237,592 / 98.1 MiB |
| `rx1day` | mm/day | annual maximum one-day precipitation | r5 | 2025–2090 every 5 y (14) | `annual_value_distribution` | — | 83 / 12,758,200 / 240.4 MiB |
| `rx5day` | mm | annual maximum five-day precipitation | r5 | 2025–2090 (14) | `annual_value_distribution` | — | 83 / 12,761,938 / 243.0 MiB |
| `rflood` | m | river flood depth; depth capped at zero before fitting and on evaluation | r7 | 2025–2100 (16) | null | "Scenario-compatible SSP585-labelled curves; not independently fitted SSP585 projections." | 78 / 65,818,591 / 1,174.2 MiB |
| `cflood` | m | coastal flood depth; depth capped at zero | r7 | 2025–2100 (16) | null | same as `rflood` | 93 / 4,252,256 / 90.3 MiB |
| `inundation` | m | sea-level change and inundation depth; depth capped at zero | r7 | 2025–2100 (16) | null | "Source probability semantics are unspecified; retain source values without claiming annual exceedance probabilities." | 88 / 2,941,162 / 16.9 MiB |
| `wind_max_daily_max` | m/s | annual maximum daily maximum wind speed | r5 | 2025–2090 (14) | `annual_value_distribution` | — | 83 / 12,726,364 / 235.9 MiB |
| `wind_max_daily_mean` | m/s | annual maximum daily mean wind speed | r5 | 2025–2090 (14) | `annual_value_distribution` | — | 83 / 12,730,102 / 241.3 MiB |

Grid sizes (H3 averages): r5 has an edge of about 9.85 km and an area of about 253 km². r7 has an edge of about 1.41 km and an area of about 5.16 km². In the CRC docs' words, an H3 cell value "describe[s] a regional grid, not property-scale conditions". [S7]

The other 55 hazards are climate indices (temperature, heat, cold, fire weather, precipitation totals and counts, drought). All are r5, `annual_value_distribution`, 2025–2090. See [1.6](#16-full-hazard-list).

### 1.4 Cyclone layer: is it pooled and scenario-independent?

**Yes, as declared in the release catalogue** [S1]. The `cyclone` entry has `pooling: "pooled"` and `value_semantics` "time and scenario independent". Its note says the distribution is "broadcast upstream across labels" and "SSP585-labelled rows are not SSP585 projections". The CRC docs add that the 2010 label "is not a historical baseline" and that the cyclone ensemble scenario is unspecified [S5]. The `crc-sdk` README says cyclone labels "reuse a time/scenario-independent pooled distribution" [S3].

Gaps that matter for R-03 and the paper:

- **Probability semantics are not declared** (`probability_semantics: null`, unlike `rx1day`). Nothing in the public sources says whether a cyclone curve is an annual-maximum distribution. A return value from 1 − 1/*T* is therefore a convention, not a stated annual exceedance level. *Not verified*: it needs the provider's methodology or the owner's documentation.
- **Wind-speed definition** (averaging period, height, sustained or gust) is not stated in any public source found. *Not verified.*
- **Identical values across horizon labels** are stated by the catalogue, but this was not checked against the values themselves. That check needs partition data (see [5](#5-unverified-points-and-follow-ups)).
- **Curve kinds** in the IRIS-domain cyclone partitions: `fitted` 2,118,387, `hurdle` 58,582, `point_mass` 38,641, `no_data` 0 (from the catalogue's per-partition counts [S1]).

### 1.5 Coverage of the IRIS North Atlantic domain

**Method.** The catalogue lists partitions only at H3 resolution 0. The probe was a 0.5° lattice over 5–45° N, 100–55° W (the agent's approximation of SPEC §6.6's US Gulf/East coast, Caribbean and Central America), mapped to r0 parents. It gives 10 r0 cells. Partition presence comes from the catalogue [S1], and the H3 maths from the `h3` Python package. **An r0 partition being present does not mean every finer cell inside it has data** [S3]. Cell-level coverage at a given asset is not verified here.

| Hazard | r0 partitions present (of 10) | Missing r0 cells | Rows in present partitions | Whole-file download for the domain |
|---|---|---|---|---|
| `cyclone` | 10 | — | 2,215,610 | 11.7 MiB |
| `rx1day` | 9 | `803bfffffffffff` | 1,507,968 | 29.0 MiB |
| `rx5day` | 9 | `803bfffffffffff` | 1,507,968 | 29.2 MiB |
| `rflood` | 9 | `803bfffffffffff` | 6,220,598 | 108.7 MiB |
| `cflood` | 8 | `8027fffffffffff`, `803bfffffffffff` | 566,464 | 12.2 MiB |
| `inundation` | 8 | `8027fffffffffff`, `803bfffffffffff` | 136,524 | 1.5 MiB |
| `wind_max_daily_max` | 9 | `803bfffffffffff` | 1,507,926 | 28.7 MiB |

The 10 r0 cells are `801b…`, `8027…`, `802b…`, `803b…`, `8045…`, `8049…`, `804d…`, `805f…`, `8067…` and `806d…` (`…` = `fffffffffff`). The two cells with gaps were located from their H3 boundary vertices:

- `803b…` is centred at 30° N, 50° W (vertices 18.9–41.0° N, 62.0–37.2° W): the open central Atlantic, east of Bermuda and the Lesser Antilles.
- `8027…` is centred at 43.4° N, 97.4° W (vertices 31.6–55.2° N, 112.8–81.9° W): the North American interior, with no Gulf or Atlantic coastline. It lacks only `cflood` and `inundation`, which are coastal layers.

The agent's reading is that neither gap affects a hurricane-exposed coastal portfolio. This was not checked against a land mask.

**Candidate sites.** Each was mapped to its r5 cell and r0 parent. For all 27 probe sites, all 7 hazards above have a partition at the site's r0 parent:

| r0 cell | Probe sites mapped to it |
|---|---|
| `8045fffffffffff` | Miami, Tampa, Jacksonville, Pensacola (FL); New Orleans (LA); Houston (TX); Mobile (AL); Charleston (SC); Havana; Nassau; Cancún; Belize City |
| `8049fffffffffff` | Corpus Christi (TX) |
| `802bfffffffffff` | Wilmington (NC), Norfolk (VA), New York (NY), Hamilton (Bermuda) |
| `804dfffffffffff` | San Juan (PR), Santo Domingo |
| `8067fffffffffff` | Kingston, Port-au-Prince, Panama City |
| `805ffffffffffff` | Bridgetown, Port of Spain |
| `806dfffffffffff` | Veracruz, Tegucigalpa, Managua |

**Thesis Miami portfolio** (parity fixture `parity/tests/data/thesis_eventset/locations.parquet`, 9 assets): all assets fall in r0 `8045fffffffffff`. They map to **5 distinct r5 cells**, so assets in the same cell get identical CRC cyclone and rainfall marginals, and to 9 distinct r7 cells for the flood layers. This is an observation for R-03 and R-04, not a conclusion.

### 1.6 Full hazard list

All 63 hazards in `ssp585-global-2026-10-20-v1` [S1]. All are `pooled`, `upper`-tail and `ssp585`.

<details>
<summary>Show the 63 hazards</summary>

| Hazard | Unit | H3 | Horizons | Statistic |
|---|---|---|---|---|
| at | K | r5 | 2025–2090 | daily apparent temperature |
| bui | dimensionless | r5 | 2025–2090 | annual maximum Build Up Index |
| calm_days | (m/s) days | r5 | 2025–2090 | annual sum of positive wind-speed excess above threshold |
| cflood | m | r7 | 2025–2100 | coastal flood depth |
| cold_spell_days | days | r5 | 2025–2090 | annual total days in cold-spell events |
| cold_spell_frequency | events | r5 | 2025–2090 | annual count of cold-spell events |
| cooling_degree_days | K days | r5 | 2025–2090 | annual cooling degree-day accumulation |
| corn_heat_units | CHU | r5 | 2025–2090 | annual mean daily corn heat units |
| cyclone | m/s | r5 | 2010, 2025–2100 | pooled cyclone wind speed; time and scenario independent |
| daily_freezethaw_cycles | days | r5 | 2025–2090 | annual count of daily freeze-thaw cycles |
| dc | dimensionless | r5 | 2025–2090 | annual maximum Drought Code |
| dmc | dimensionless | r5 | 2025–2090 | annual maximum Duff Moisture Code |
| dry_days | days | r5 | 2025–2090 | annual count of dry days |
| dtr | K | r5 | 2025–2090 | annual mean diurnal temperature range |
| dtrmax | K | r5 | 2025–2090 | annual maximum diurnal temperature range |
| dtrvar | K | r5 | 2025–2090 | annual mean absolute day-to-day DTR variation |
| etr | K | r5 | 2025–2090 | annual extreme temperature range |
| ffmc | dimensionless | r5 | 2025–2090 | annual maximum Fine Fuel Moisture Code |
| frost_days | days | r5 | 2025–2090 | annual count of frost days |
| fwi | dimensionless | r5 | 2025–2090 | annual maximum Fire Weather Index |
| growing_degree_days | K days | r5 | 2025–2090 | annual growing degree-day accumulation |
| heat_index | degC | r5 | 2025–2090 | daily heat index |
| heat_wave_frequency | events | r5 | 2025–2090 | annual count of heat-wave events |
| heat_wave_index | days | r5 | 2025–2090 | annual total days in qualifying heat-wave-index events |
| heat_wave_max_length | days | r5 | 2025–2090 | annual maximum heat-wave event length |
| heat_wave_total_length | days | r5 | 2025–2090 | annual total days in heat-wave events |
| heating_degree_days | K days | r5 | 2025–2090 | annual heating degree-day accumulation |
| hot_days | days | r5 | 2025–2090 | annual count of hot days |
| hot_spell_frequency | events | r5 | 2025–2090 | annual count of hot-spell events |
| hot_spell_max_length | days | r5 | 2025–2090 | annual maximum hot-spell length |
| humidex | degC | r5 | 2025–2090 | daily humidex |
| ice_days | days | r5 | 2025–2090 | annual count of ice days |
| inundation | m | r7 | 2025–2100 | sea-level change and inundation depth |
| isi | dimensionless | r5 | 2025–2090 | annual maximum Initial Spread Index |
| liquidprcptot | mm | r5 | 2025–2090 | annual total liquid precipitation |
| max_consecutive_dry_days | days | r5 | 2025–2090 | annual maximum consecutive dry days |
| maximum_consecutive_frost_days | days | r5 | 2025–2090 | annual maximum consecutive frost days |
| maximum_consecutive_wet_days | days | r5 | 2025–2090 | annual maximum consecutive wet days |
| pet | mm/day | r5 | 2025–2090 | daily potential evapotranspiration |
| prcptot | mm | r5 | 2025–2090 | annual total precipitation |
| rflood | m | r7 | 2025–2100 | river flood depth |
| rx1day | mm/day | r5 | 2025–2090 | annual maximum one-day precipitation |
| rx5day | mm | r5 | 2025–2090 | annual maximum five-day precipitation |
| sdii | mm/day | r5 | 2025–2090 | annual mean precipitation on wet days |
| solidprcptot | mm | r5 | 2025–2090 | annual total solid precipitation |
| spei | dimensionless | r5 | 2025–2090 | standardized precipitation-evapotranspiration index |
| summer_days | days | r5 | 2025–2090 | annual count of summer days |
| tg_max | K | r5 | 2025–2090 | annual maximum daily mean temperature |
| tg_mean | K | r5 | 2025–2090 | annual mean daily mean temperature |
| tg_min | K | r5 | 2025–2090 | annual minimum daily mean temperature |
| tn_max | K | r5 | 2025–2090 | annual maximum daily minimum temperature |
| tn_mean | K | r5 | 2025–2090 | annual mean daily minimum temperature |
| tn_min | K | r5 | 2025–2090 | annual minimum daily minimum temperature |
| tropical_nights | days | r5 | 2025–2090 | annual count of tropical nights |
| tx_max | K | r5 | 2025–2090 | annual maximum daily maximum temperature |
| tx_mean | K | r5 | 2025–2090 | annual mean daily maximum temperature |
| tx_min | K | r5 | 2025–2090 | annual minimum daily maximum temperature |
| water_budget | kg m-2 s-1 | r5 | 2025–2090 | daily precipitation minus potential evapotranspiration flux |
| wbgt | K | r5 | 2025–2090 | daily wet-bulb globe temperature |
| wet_days | days | r5 | 2025–2090 | annual count of wet days |
| wind_max_daily_max | m/s | r5 | 2025–2090 | annual maximum daily maximum wind speed |
| wind_max_daily_mean | m/s | r5 | 2025–2090 | annual maximum daily mean wind speed |
| windchill | degC | r5 | 2025–2090 | annual mean wind chill |

</details>

### 1.7 Public versus the owner's licence

| Item | Public (CRC Open) | Needs the owner's full licence |
|---|---|---|
| Hazard curves above, SSP5-8.5 only | Yes, under CC BY-NC 4.0 [S1] | — |
| Other scenarios, a historical baseline, per-model ensemble spread, finer or asset-level hazard | Not in the public release [S1], [S5] | Per the CRC docs, VELO/CDT offers "broader/finer hazards", future scenarios and ownership data "depend[ing] on the connected service and entitlements" [S9]. **Owner to confirm what the licence covers.** |
| Commercial use of CRC Open data | Not under CC BY-NC; "commercial use needs a separate licence" [S5] | **Owner to confirm** whether the full licence covers it |
| Company/asset ownership, coordinates, types, values | No | VELO/CDT (Section 2) |

---

## 2. VELO/CDT asset database (owner)

> **Placeholder — owner input required.** Agents must not call the CDT Express MCP (`https://mcp.riskthinking.ai/mcp`), `velo-sdk` or any VELO/CDT API, and must not handle credentials. Everything in this section is either a question for Marc or a template for him to fill in. The tool names below come from the public CRC docs [S9], [S10]. They have **not** been checked against the live service.

### 2.1 Field table (to fill)

The CRC docs' property playbook lists the evidence fields it expects from VELO as "Asset ID, name, address, coordinates, type, value/materiality fields when authorized" [S10]. Confirm each against a real `get_company_assets` / `get_asset` response.

| Field | Present? | Name in response | Type / unit | Example (anonymised) | Coverage (% of assets non-null) | Notes |
|---|---|---|---|---|---|---|
| Asset ID | _owner_ | | | | | stable across calls? |
| Asset name | _owner_ | | | | | |
| Address | _owner_ | | | | | |
| Latitude / longitude | _owner_ | | | | | precision (geocoded vs. surveyed)? |
| Asset type | _owner_ | | | | | taxonomy / list of values |
| Country | _owner_ | | | | | ISO code? |
| Owner company ID / ownership share | _owner_ | | | | | single risk owner needed (SPEC §6.6) |
| Asset value / replacement cost | _owner_ | | | | | currency, basis, date |
| Materiality / weight / capacity / size | _owner_ | | | | | usable as a value proxy? |
| Footprint or area | _owner_ | | | | | |
| Climate score fields (e.g. `cvar_95`) | _owner_ | | | | | not needed for design; record for the CRC/VELO crosswalk |
| Other | _owner_ | | | | | |

### 2.2 Coverage in the IRIS North Atlantic domain (to fill)

| Question | Answer |
|---|---|
| How many assets in total lie in 5–45° N, 100–55° W (or the exact IRIS NA domain), by country? | _owner_ |
| Which asset types dominate there? | _owner_ |
| How many companies have 25–200 assets in hurricane-exposed regions of that domain? | _owner_ |

### 2.3 Candidate companies/portfolios (to fill)

Requirements from SPEC §6.6: one risk owner, 25–200 assets inside the IRIS NA domain, and defensible values or a documented proxy. The company name may be replaced by a code if the licence requires it.

| Code | Company (or anonymised label) | Assets in domain | Countries | Asset types | Value field or proxy available? | Publishable (asset-level / aggregated / not at all) | Notes |
|---|---|---|---|---|---|---|---|
| C1 | _owner_ | | | | | | |
| C2 | _owner_ | | | | | | |
| C3 | _owner_ | | | | | | |

### 2.4 Value-proxy options

These are listed by the agent for the owner to choose from; none has been checked against VELO data. Each would be documented in the portfolio's `metadata.json`.

| Option | Needs | Pros | Cons |
|---|---|---|---|
| V1. Value field from VELO/CDT (if present and licensed) | A VELO value or replacement-cost field | Real values | Publication limits likely |
| V2. Materiality/capacity field × unit cost by asset type | A VELO size/capacity field and a published unit-cost table | Traceable, type-aware | Unit-cost table to source and cite |
| V3. Building footprint area (e.g. Overture buildings at the asset coordinates) × construction cost per m² by type | Coordinates precise enough to match footprints; an open cost table | Open, reproducible | Footprint matching is noisy. Overture places don't prove ownership [S11] |
| V4. Allocate a published company total (e.g. PP&E from annual reports) across assets by type weights | Company financials | Ties to a real total | Allocation is arbitrary; mixes data sources |
| V5. Equal or type-weighted unit values | Asset type only | Simplest, transparent | Not a "defensible value" (SPEC §6.6); only useful as a sensitivity case |

### 2.5 Exact questions for Marc

1. **Access route.** Will you run the queries yourself and hand over exports, or connect the CDT Express MCP over OAuth in a session you control? Agents can't do either.
2. **Fields.** Paste or export one full `get_company_assets` response (and one `get_asset` response) for any company, anonymised if needed, so the field table in 2.1 can be filled. Which fields are present, and which are null for most assets?
3. **Values.** Is there any asset value, replacement cost, capacity, area or materiality field? With what unit and basis, and is it covered by your licence?
4. **Coverage.** How many assets does VELO/CDT hold in the IRIS NA domain (US Gulf/East coast, Caribbean, Central America), by country and asset type?
5. **Candidates.** Which companies have 25–200 assets in hurricane-exposed parts of that domain, under one risk owner? Please list the 3–5 best fits for 2.3.
6. **Ownership.** Are ownership shares or subsidiaries resolved, so that "one risk owner" is well defined?
7. **Coordinates.** How precise are the asset coordinates (geocoded address, site centroid, city centroid)?
8. **Licence: VELO/CDT.** What do your licence terms say about publishing (a) asset-level coordinates and types, (b) anonymised or jittered locations, (c) aggregate results (portfolio KPIs, payout curves), (d) the company name, in the paper, on the website and in this public repository?
9. **Licence: CRC Open.** Does your full licence change the CC BY-NC 4.0 terms of CRC Open for you (Section 3), e.g. commercial use or relicensing of derived figures?
10. **Hazards beyond CRC Open.** Does your licence give access to VELO/CDT hazard data (scenarios other than SSP5-8.5, a historical baseline, cyclone curves with stated probability semantics)? If yes, may results built on it be published?
11. **Cyclone methodology.** Can you obtain the definition of the CRC `cyclone` curve (source model, wind averaging period and height, whether it is an annual-maximum distribution)? See 1.4.

**Exports requested** (if you choose the export route; keep them out of the repository, which never holds VELO data):

- E1. For each candidate company: one row per asset with ID, latitude, longitude, asset type, country, and any value or materiality field. Parquet or CSV.
- E2. The response schema or field definitions (e.g. from `get_metrics_definition` or the API docs).
- E3. A count table of assets by country × asset type inside the IRIS NA domain bounds.
- E4. The licence text or the relevant clauses, or your written summary of them, for Section 3.2.

---

## 3. Licence and publication constraints

### 3.1 CRC Open (public terms, prepared by the agent)

- **Licence:** Creative Commons Attribution-NonCommercial 4.0 International (`CC-BY-NC-4.0`, <https://creativecommons.org/licenses/by-nc/4.0/>).
  - Machine-readable in the release catalogue [S1] and in the Parquet metadata [S5].
  - Stated in the provider's `crc-sdk` README [S3], [S8] and the CRC docs [S5], [S6].
  - No separate terms-of-use page for CRC Open was found on 2026-10-25. `https://data.riskthinking.ai/` returns 403 and `/crc-open/` returns 404.
- **Attribution string** (from the catalogue): "Riskthinking.AI bias-corrected climate distributions". The release ID and catalogue SHA256 should be cited alongside it.
- **Software is separate.** `crc-sdk` is AGPL-3.0-or-later. Its licence "covers the software" and "does not determine the data licence" [S3], [S5]. This matches ADR 0001: the CRC adapter is AGPL-3.0-or-later, and the data is under its own terms.
- **What CC BY-NC 4.0 implies here.** This is the agent's reading of the public licence text, not legal advice. The owner confirms it in 3.2.
  - Sharing and adapting are allowed for non-commercial purposes, with attribution, a licence link and an indication of changes.
  - Commercial use needs a separate licence [S5].
  - Derived data (e.g. per-location marginals, a CRC-based `EventSet`) keeps the NC terms (`docs/data-sources.md` rule).
  - **Paper.** Figures derived from CRC Open in a paper published under CC BY (common for open-access journals), or by a commercial publisher, may conflict with the NC clause. The owner should check this before CRC-derived figures go into the manuscript.
  - **Website and posts.** Showing CRC-derived results appears consistent with NC if the site is non-commercial and attributes the source. A LinkedIn post linked to professional activity is a grey area. Owner to decide.
  - **This repository.** It commits no CRC data (`showcase/crc/README.md`). Small CRC-derived fixtures would carry CC BY-NC and need a licence note. MAR-79 handles repository licensing.
- **Update needed elsewhere.** `docs/data-sources.md` still lists the CRC Open licence as "to verify: MAR-41". This PR doesn't edit that file (scope). See follow-up F1.

### 3.2 Owner's full licence (placeholder — owner input required)

| Question | Answer (owner) |
|---|---|
| Licence holder, date, and which products it covers (CRC Open, VELO/CDT assets, VELO/CDT hazards) | _owner_ |
| May CRC Open data be used beyond CC BY-NC (commercial use, relicensing derived figures)? | _owner_ |
| May VELO/CDT asset-level data (coordinates, types, values) appear in the paper / website / public repository? | _owner_ |
| May the company be named, or must it be anonymised? Is jittering or coarsening to H3 r5/r7 acceptable? | _owner_ |
| May aggregate results (portfolio KPIs, payout functions, exceedance curves) built on VELO/CDT data be published? | _owner_ |
| Required attribution text for VELO/CDT | _owner_ |
| Retention or deletion obligations for exports | _owner_ |

**Publication matrix** (owner to fill; ✓ allowed, ✗ not allowed, A = only anonymised/aggregated):

| Output | CRC Open-derived | VELO/CDT asset-derived |
|---|---|---|
| Paper figures and tables | _owner_ | _owner_ |
| Paper supplementary data / Zenodo release | _owner_ | _owner_ |
| Website explorers | _owner_ | _owner_ |
| Blog / LinkedIn posts | _owner_ | _owner_ |
| This public repository (fixtures, notebooks with outputs) | _owner_ | _owner_ (default: never) |
| CRC showcase report | _owner_ | _owner_ |

---

## 4. Recommendation for P-05 (agent, conditional)

> **This is the agent's recommendation, prepared before any VELO/CDT data was seen. It is conditional and needs the owner's approval.** It records options and the conditions that would choose between them. It makes no claim about method performance.

Observations that hold whatever VELO/CDT contains:

- O1. CRC Open gives per-cell **marginal** curves only (1.2). It cannot replace the IRIS event set as the paper's hazard catalogue without a dependence model (R-04).
- O2. The CRC `cyclone` layer is pooled and scenario-independent (1.4). It cannot provide climate scenarios for P-06; it is useful for R-03 as a cross-model check only. Its probability semantics are undeclared, so return levels compared in R-03 should be labelled with the 1 − 1/*T* convention.
- O3. CRC Open covers the IRIS NA domain at partition level for cyclone, rainfall and flood hazards (1.5). Cell-level coverage at the actual portfolio still needs checking (F3).
- O4. CRC Open is CC BY-NC (3.1). This matters for the paper only if CRC-derived numbers appear in it.

Conditional recommendation for D2:

1. **If** VELO/CDT has a company meeting SPEC §6.6 (one risk owner, 25–200 assets in the IRIS NA domain, coordinates and asset types), **and** it has a value field or a field supporting proxy V2, **and** your licence allows publishing at least anonymised or aggregated asset-level results in the paper, **then** choose candidate **(a) VELO/CDT**, anonymised as the licence requires, with the value proxy documented. Keep **(b) LitPop** as the open replication case (the CLIMADA tutorial needs it anyway, SPEC §6.6).
2. **If** such a company exists but there is no usable value field (only V3–V5 possible), **then** use (a) only if you judge the proxy defensible. Otherwise use (a) in the CRC showcase only and (b) LitPop for the paper.
3. **If** the licence forbids publishing asset-level or company-identifiable results, or no company has 25–200 assets in the domain, **then** choose **(b) LitPop** for the paper and keep VELO/CDT for the CRC showcase under the licence.
4. In every case the thesis 9-asset Miami portfolio stays the illustrative and parity case (SPEC §6.6).

---

## 5. Unverified points and follow-ups

### Not verified here

- **Cell-level coverage** of each hazard at specific coordinates. Only r0 partition presence was checked; no Parquet partition was downloaded.
- **Cyclone values identical across horizon labels**: declared in the catalogue, not checked against values.
- **Cyclone probability semantics and wind-speed definition**: not stated publicly (1.4, question 11).
- **The H3 r0 cells `803b…` and `8027…`** lying outside exposed coasts: located from boundary vertices only, not checked against a land mask.
- **The provider's own terms-of-use page** for CRC Open: none found; the licence is taken from the catalogue and the provider's READMEs.
- **The whole of Section 2 and Section 3.2.**

### Proposed follow-ups (for the orchestrator to file; not done here)

- **F1.** Update `docs/data-sources.md`: set the CRC Open row to CC BY-NC 4.0, with source `https://data.riskthinking.ai/crc-open/<release>/_CATALOG.json` (`licence` field) and check date 2026-10-25. Add a "CRC Open licence check (MAR-41)" subsection like the IRIS one. This is outside MAR-41's single owned file.
- **F2.** Add the release ID `ssp585-global-2026-10-20-v1` and catalogue SHA256 as the pinned default in the CRC adapter (MAR-42). The adapter should read `licence`/`attribution` from the catalogue into `EventSet` `metadata.json` rather than hard-coding them.
- **F3.** In MAR-42/MAR-43, run a cell-level coverage check (DuckDB range reads or `crc-sdk` `for_assets`) for the thesis Miami portfolio and the chosen P-05 portfolio. Report `no_data` and unmatched cells explicitly.
- **F4.** For R-03: record that CRC cyclone return levels use the 1 − 1/*T* convention on a curve with undeclared probability semantics, and that the 9 Miami assets share 5 r5 cells.
- **F5.** Ask the provider, through the owner, for the cyclone methodology (question 11). It may also be in the owner's licence documentation.

---

## Sources and access log

All accessed on **2026-10-25** without sign-in. The local reference repository `crc-docs/` (read-only) is at commit `f05a856998b4de4d3fa76e78a11f0ef18c646214` (2026-10-23).

| Ref | Source | What it gave |
|---|---|---|
| [S1] | <https://data.riskthinking.ai/crc-open/ssp585-global-2026-10-20-v1/_CATALOG.json> (HTTP 200, `application/json`, 2,107,597 bytes) | Release metadata, licence and attribution fields, per-hazard units, semantics, H3 resolution, horizons, notes, partitions, row counts, sizes, curve kinds |
| [S2] | <https://data.riskthinking.ai/crc-open/ssp585-global-2026-10-20-v1/_SUCCESS> | Catalogue SHA256 (matches [S1]) |
| [S3] | `crc-sdk` 0.8.1 README via <https://pypi.org/pypi/crc-sdk/json> (project page <https://pypi.org/project/crc-sdk/>) | Public source URL and default release, "no credentials", canonical Parquet contract, curve kinds, return-period convention, spatial matching, AGPL-3.0-or-later, data licence statement |
| [S4] | <https://pypi.org/pypi/crc-sdk/0.9.0a1/json> | Latest pre-release (2026-10-23) still names only `ssp585-global-2026-10-20-v1` |
| [S5] | `crc-docs/fixtures/crc_open/README.md` (local; public at <https://github.com/RiskThinking/crc-docs/blob/main/fixtures/crc_open/README.md>) | Interpretation of cyclone, flood and inundation labels; licence and commercial-use statement; fixture release |
| [S6] | <https://data.riskthinking.ai/crc-open/>, <https://data.riskthinking.ai/crc-open/index.json> (both 404); <https://data.riskthinking.ai/> (403) | No public release index or terms page at the data host |
| [S7] | `crc-docs/notebooks/crc_open_hazards.ipynb` and `crc-docs/pipelines/crc_open_pipeline.py` (local; public on GitHub `RiskThinking/crc-docs`) | Access pattern, release pinning, executed totals (63 hazards; 5,243 files; 840,429,769 rows), return-period evaluation, H3 interpretation |
| [S8] | <https://github.com/RiskThinking/crc-sdk> | Data licence CC BY-NC 4.0, separate from the AGPL software licence |
| [S9] | `crc-docs/ai-playbooks/docs/capability-matrix.md` (local) | VELO/CDT access route (OAuth MCP or `velo-sdk==0.0.20`), entitlement-dependent coverage |
| [S10] | `crc-docs/.agents/skills/velo-*/references/playbook.md` (local) | VELO tool names (`get_company_assets`, `get_all_company_assets`, `get_asset`, `search_assets`, `get_asset_climate_scores`, `get_metrics_definition`) and expected evidence fields. Not checked against the live service |
| [S11] | `crc-docs/README.md` (local) | "Overture places are candidate locations, not proof of ownership" |
| [S12] | <https://creativecommons.org/licenses/by-nc/4.0/> | Licence text linked from [S3] and [S5]. Not re-read for this draft; the summary in 3.1 is the agent's reading of the standard CC BY-NC 4.0 terms |

H3 cell maps and lattice probes were computed locally with the `h3` Python package (v4 API) on the catalogue metadata. No CRC Parquet data was downloaded, and no VELO/CDT service was contacted.
