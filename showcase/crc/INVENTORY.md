# R-01 data inventory: CRC Open and the VELO/CDT asset database

**Status: Draft. Agents prepared the CRC Open part and the VELO/CDT survey from public sources (code and docs only, no data). Pending the owner (MAR-41): the VELO/CDT queries (2.9), their results (2.11) and the licence terms (3.2).**

- Linear: [MAR-41](https://linear.app/marc-prinzing/issue/MAR-41/r-01-inventory-crc-open-and-the-velocdt-asset-database), labelled **Human**. Spec: `docs/SPEC.md` §6.6 (portfolio, D2) and §8 (CRC Showcase R-01).
- Feeds: the CRC adapter (MAR-42, MAR-43), the CRC showcase, and the paper portfolio decision D2 via spike P-05 (MAR-30).
- **Who wrote what.** Every agent-written fact names its source in [Sources and access log](#sources-and-access-log).
  - Section 1 (CRC Open): an agent, from public, unauthenticated sources.
  - Sections 2.1–2.10 (VELO/CDT): an agent, from the **public SDK, MCP and notebook code and the public OpenAPI document only, not from data**. They include the agent's viability verdicts (2.10) and a query plan for the owner (2.9). Agents have no VELO/CDT access, called no VELO/CDT endpoint and handle no credentials.
  - Sections 2.11 and 3.2: **placeholders for the owner**.
  - Section 4: the **agent's conditional recommendation**. The owner approves or replaces it.
- **No data is committed.** This file holds metadata only: catalogue fields, counts and URLs.

Contents:

1. [CRC Open (public releases)](#1-crc-open-public-releases)
2. [VELO/CDT asset database](#2-velocdt-asset-database) (public-code survey, query plan, verdicts; owner results)
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
| Company/asset ownership, coordinates, types, values | No | VELO/CDT (Section 2). Public schemas declare these fields; no public data terms were found (2.8) |

---

## 2. VELO/CDT asset database

> **From public SDK code and docs, not from data.** It was prepared by an agent on 2026-10-25. The sources were the public RiskThinking repositories `velo-sdk`, `cdt-express-mcp`, `cdt-express-notebooks` and `crc-sdk`, plus the public OpenAPI document behind `api.docs.riskthinking.ai`. Commits and checksums are in [S13]–[S19]. No VELO/CDT/CRC API endpoint was called, not even unauthenticated. No MCP connector was used, nothing was signed in to, and no credentials were handled. What the code *declares* is not proof of what the service *returns* for the owner's entitlement. A field listed below is only *declared in a public schema*, unless a public example is cited for it. The owner's queries (2.9) confirm it. Sections 2.1–2.10 are the agent's; 2.11 and the licence (3.2) are **owner input**.

### 2.1 Access surfaces

| Surface | Version / commit | Licence (software only) | Auth | What it covers |
|---|---|---|---|---|
| `velo-sdk` (Python) | 0.0.20, `RiskThinking/velo-sdk@ae1aebec31cd7e831a8a53c594bfa4f426c2b3d6` (2026-02-26) | Apache-2.0 | API key: `APIClient(api_key=...)` or env `RISKTHINKING_API_KEY`, sent as `Bearer` | Typed wrappers for companies, assets and market indexes, under `https://api.riskthinking.ai`, prefixed `/v3`. `client.get(path, params=...)` reaches **any** endpoint, including ones without a wrapper ("Direct API Access" in the README) [S13] |
| CDT Express MCP | v0.6.0, `RiskThinking/cdt-express-mcp@3a0f904b8aada4b061b2245637705ad855fd91fa` (2026-08-19) | MIT | Remote `https://mcp.riskthinking.ai/mcp` with VELO OAuth sign-in. The API key is passed server-to-server ("never shown to the AI app"). Or a local MCPB extension with a pasted CDT Express key | 40 tools: 39 read-only GET wrappers for `/v3` assets, companies and markets and for `/v4` location climate metrics, plus a static glossary tool. Responses are the **raw API JSON** (or CSV for the `*_all_*` tools) [S14] |
| Public OpenAPI document | `https://api.docs.riskthinking.ai/openapi-public.yml` (the Redoc page's `spec-url`). OpenAPI 3.1.0, `version: v3`, 110,377 bytes, `Last-Modified: Wed, 21 Oct 2026 17:51:04 GMT`, SHA256 `01d042f0bdcda53c551bea2d89ae079683eb088face5efadf286907f9e3ea269` | not stated | `bearer` or `key` query parameter | Every `/v3` path with its parameters and response schemas. It describes the CDT as covering "physical asset data for over 12,000 companies" [S15] |
| CDT Express notebooks | `RiskThinking/cdt-express-notebooks@07de3194b0a7eeb1ad2bf1cfefad671e893bbe4c` (2025-06-18) | Apache-2.0 | API key | 9 example notebooks. Two (7 and 8) have **executed outputs that show real response rows** (Caterpillar, Procter & Gamble, Unilever), and the README has the credit rules [S16] |
| `crc-sdk` | `RiskThinking/crc-sdk@b08a51de50777c387aea550d0c7ff42b7904bef7` | AGPL-3.0-or-later | none | No VELO client. Its asset input contract (`asset_id`, `longitude`, `latitude`, optional extra columns) is what a VELO export must be mapped to for `for_assets` [S17]. `crc-framework-rs@5484de18` has no VELO/asset-database code. |

**Credits, not just rate limits.** The notebooks README says asset retrieval costs **one credit per asset**: "a company with 1,500 assets" costs 1 + 1,500 credits. An aggregation costs one credit per group returned, and a company search or get costs 1 [S16]. **No numeric rate limit is documented.** HTTP 429 is either a retryable rate limit (the SDK retries with exponential back-off, at most 5 tries) or a non-retryable "Insufficient API credits" error (`velo_sdk/api/base.py` L67–101, `errors.py`) [S13]. The credit cost of the endpoints the README doesn't list (locations, clusters, index screens) is **not documented**.

**Pagination.** Cursor-based. `limit` is 1–100. The response is `{"results": [...], "pagination": {"cursor", "count", "last_page"}}` (OpenAPI `components/parameters/limit`, `responses/Pagination` [S15]; `velo_sdk/api/pagination.py` [S13]). The MCP `*_all_*` tools merge pages into CSV but **stop after 30 pages** with a warning: `MAX_EXHAUSTIVE_FETCH_PAGES = 30`, i.e. ≤ 3,000 rows at `limit=100` (`src/utils.ts` L67–143) [S14].

### 2.2 Endpoints for companies and assets

"MCP" is the CDT Express MCP tool name. "—" means no wrapper: in the SDK, use `client.get("<path>", params={...})`. All paths are under `https://api.riskthinking.ai/v3`. Parameters are from the OpenAPI document [S15]; tool schemas are from `cdt-express-mcp/src/schema.ts` [S14].

| Purpose | Path | SDK method | MCP tool | Filters and parameters |
|---|---|---|---|---|
| Search companies | `GET /companies/search` | `companies.search_companies(name=...)` (returns one page only) | `search_companies` | `name`, `isin_code`, `stock_ticker`, `sector`, `method` (`strict` default, or `fuzzy`), `limit`. **No region, country or asset-count filter** |
| List companies | `GET /companies` | `companies.list_companies(scope=...)` | `list_companies`, `list_all_companies` | `scope` (`public`/`organization`), `sort_by` (`created_at`, `name`, `sector`), cursor/limit |
| Get a company | `GET /companies/{company_id}` | `companies.get_company` | `get_company` | — |
| Company assets (full rows) | `GET /companies/{company_id}/assets` | `companies.list_company_assets` | `get_company_assets`, `get_all_company_assets` (CSV) | `country` (ISO-3, comma list), `state` (names, comma list), `asset_type` (comma list), `sort_by` (`asset_type`, `country`, `state`, `address`, `city`, `latitude`, `longitude`), cursor/limit |
| Company asset **locations** | `GET /companies/{company_id}/assets/locations` | — | — | **`bbox`** (`min_lon,min_lat,max_lon,max_lat`), `country`, `state`, `asset_type`, `asset_function`, `asset_category`. Returns `asset_id`, `latitude`, `longitude`, `country`, `hex_id` only |
| Company asset **counts** | `GET /companies/{company_id}/assets/aggregation` | — | — | `by` = `country` / `state` / `asset_type`, plus `country` and `asset_type` filters. Returns `asset_count` per group |
| Company geo clusters | `GET /companies/{company_id}/geo/clusters` | — | `get_company_geo_clusters` | `zoom` (required), `bbox`, `country`, `asset_type`, `radius`. Returns `latitude`, `longitude`, `count` per cluster |
| Subsidiaries | `GET /companies/{company_id}/subsidiaries` | — | `get_company_subsidiaries` | "available only to authorized users" (OpenAPI). Returns `Company` objects |
| Get an asset | `GET /assets/{asset_id}` | `assets.get_asset` | `get_asset` | — |
| Asset owner | `GET /assets/{asset_id}/ownership` | `assets.get_asset_owner` (returns a `Company`) | — | — |
| List all assets | `GET /assets` | `assets.list_assets` | `list_assets`, `list_all_assets` (CSV) | `country`, `asset_type`, cursor/limit (MCP also passes `state` and `sector`). **No bbox.** One credit per asset, so a domain-wide pull is expensive |
| Search assets | `GET /assets/search` | `assets.search_assets(query, scope, company_id)` | `search_assets` | Free text over name/address, `scope` = `public`/`organization`/`company` |
| Index constituents | `GET /markets/indexes/{index_id}/companies` | `markets.get_index_companies` | `list_market_index_companies` | `sector`, `sort_by` (`company_name`, `sector`) |
| **Index company screen** | `GET /markets/indexes/{index_id}/companies/climate/scores` | — (only index-level totals are wrapped) | `get_market_index_companies_climate_scores`, `get_all_…` (CSV) | `country`, `state`, `asset_type`, `sector`, `pathway`, `horizon`, `metric`, `min_risk`/`max_risk`, **`sort_by=asset_count`**. Returns `company_id`, `sector`, **`asset_count`** and scores per company |
| Index asset counts | `GET /markets/indexes/{index_id}/assets/aggregation` | — | — | `by` = `country` / `asset_type` / `sector`, plus `country`, `asset_type` and `sector` filters |
| Index assets | `GET /markets/indexes/{index_id}/assets` | — | `list_market_index_assets`, `list_all_market_index_assets` | `country`, `state`, `asset_type`, `sector` |

### 2.3 Asset schema

The SDK model, quoted verbatim from `velo_sdk/api/types.py` L75–95 at `ae1aebec` [S13]. It is unchanged since the first public release (`445b40ee`, 2025-05-06).

```python
class Asset(BaseModel):
    """
    An asset represents aphysical asset that is subject to climate risk.
    """

    id: str
    name: str
    asset_type: str
    city: str
    state: str
    latitude: float
    longitude: float
    building_footprint: float
    asset_value: int
    address: str
    hex_id: int
    country: str
    ipcc_region: str
    materiality_score: float
    created_at: str
    updated_at: str
```

The OpenAPI `components/schemas/Asset` [S15] declares the same 16 properties. It gives `hex_id` as a string, `building_footprint` as an integer, and `asset_value` as `integer`, `format: int64`, **`default: 0`**. None of the three has a description, unit or currency. The paginated company-asset response adds `company_id` ("Company ID which owns this asset", `Asset-Pagination`). Notebook 7's executed output (Caterpillar, 2025) shows two more response columns, **`asset_function`** and **`asset_category`**. The SDK model doesn't declare them, so pydantic's default drops them. They do exist as filters on `/assets/locations` [S15], [S16].

| Field | Declared type (SDK / OpenAPI) | What public sources say | Public example evidence | Owner checks (2.9) |
|---|---|---|---|---|
| `id` | str (UUID) | Asset UUID (`ASSET_ID_SCHEMA`) | — | stable across calls? |
| `company_id` | — / str (pagination only) | Owning company | — | present on every row? |
| `name` | str | — | **Empty** in all 5 Caterpillar and 3 P&G rows shown [S16] | % non-empty |
| `asset_type` | str | "RiskThinking.ai's CDT physical asset type". The taxonomy isn't published | `Wholesale Trade`, `Professional Services`, `Machinery Manufacturing`, `Management of Companies`, `Manufacturing Plant`: industry-style labels, not construction or occupancy classes | full value list |
| `asset_function` | — (response only) | filter "Asset function" | `Storage and Distribution`, `Office`, `Manufacturing` | full value list |
| `asset_category` | — (response only) | filter "Asset category" | `Commercial Real Estate` | full value list |
| `address`, `city`, `state` | str | `state` filter takes names (example `California,Ontario`) | Full street addresses, e.g. `751 International Dr, Franklin, Indiana, 46131…` | — |
| `country` | str | ISO 3166-1 alpha-3 | `USA`, `JPN` | is Puerto Rico `PRI` or `USA`? |
| `ipcc_region` | str | — | `E.North-America`, `E.Asia`, `Western-Africa` | — |
| `latitude`, `longitude` | float | **Geocoding method and precision not documented** | 6–7 decimals, e.g. `39.517635, -86.067305`. The OpenAPI example is `31.2277022, 34.7594703` | precision per asset; site vs. address centroid |
| `hex_id` | int / str | H3 hexagon ID | `608661930621534207` = `0x872759346ffffff`, i.e. **H3 resolution 7** (all 3 decoded examples) | r7 everywhere? |
| `building_footprint` | float / integer | **Unit not documented** | `234.09`, `38392.89`, `27903.84`, and **0 in 2 of 5** rows. The provider's notebook 8 "impute[s] missing or zero building footprints" with type means and fills the rest with `700` [S16] | % > 0; unit (m²?) |
| `asset_value` | int / int64, default 0 | **No description, unit, currency or basis** | **0 in all 5** Caterpillar rows and in both OpenAPI examples | % > 0; currency, basis, date; licence |
| `materiality_score` | float | Not defined publicly | `5.0`, `6.0`, `18.0`, `100.0`. Notebook 6 bins it 0–100 and notebook 8 thresholds it at 50 | definition; relation to value |
| `created_at`, `updated_at` | str | — | 2025-02-14 / 2025-05-23 | data vintage |
| capacity, floor area, replacement cost, revenue per asset, ownership share | — | **Not in any public schema** | — | — |

Company fields (`Company`, `types.py` L49–72) are `id`, `name`, `slug`, `headquarters_address`, `headquarters_country`, `sector`, `market_cap`, `annual_revenue` (integers, currency undocumented), `isin_codes`, `figi_codes`, `cik_code`, `lei_code`, `stock_tickers`, `organization_id`, `is_grandparent`, `data_generated_at`, `data_generation_status`, `created_at` and `updated_at`. The search example also shows `asset_count`, which the model does not declare [S15].

**SDK caveats for exports** (from reading the code; not run):

- The pydantic models drop undeclared fields (`company_id`, `asset_function`, `asset_category`, `asset_count`). They also declare every asset field as required and non-null, so a null in the response would raise a validation error. Export the **raw JSON** via `client.get(...)` or the MCP, not `vars(Asset)`.
- The async handlers `await response.json()` on an httpx response, which looks broken (`base.py` L150). Use the sync methods.

### 2.4 Value fields and value-proxy options

**Observation.** The schema has a value field, `asset_value`, but the public sources give it no unit, currency or basis, and every public example shows `0`. The two fields that could carry a proxy are `building_footprint` (sometimes 0, unit unstated) and `materiality_score` (0–100, undefined). VELO's damage metrics are expressed "as a percentage of tangible capital asset value" (MCP glossary, `src/glossary.ts` [S14]). So VELO has an internal value notion, but no public schema exposes it as an amount. Whether the owner's entitlement populates `asset_value` is **unknown until query step 4**.

The options were listed by the agent; none has been checked against VELO data. Whichever is chosen is documented in the portfolio's `metadata.json`.

| Option | Needs | Pros | Cons |
|---|---|---|---|
| V1. `asset_value` from VELO/CDT | `asset_value > 0` for most candidate assets, a documented currency and basis, and a licence that permits use | Real values | All public examples are 0. Publication limits likely |
| V2. VELO `building_footprint` × construction cost per m² by `asset_type`/`asset_function` | Footprint > 0 for most candidate assets, its unit confirmed, and a published unit-cost table | Uses VELO's own geometry, traceable, type-aware. No footprint matching needed | Footprint isn't floor area (storeys unknown). Zeros need a documented imputation |
| V3. Overture building footprint at the asset coordinates × cost per m² | Coordinates precise enough to match a footprint; an open cost table | Open, reproducible | Matching is noisy. Overture places don't prove ownership [S11]. Only needed if V2 fails |
| V4. A published company total (e.g. PP&E) allocated across assets by footprint or type weights | Company financials | Ties to a real total | Allocation is arbitrary and mixes sources |
| V5. `materiality_score`, or equal/type-weighted unit values | Nothing extra | Simplest, transparent | `materiality_score` is undefined publicly. Not a "defensible value" (SPEC §6.6); useful only as a sensitivity case |

### 2.5 Exact questions for Marc

The "Public code shows" column is what the agent could establish without data. The "Query step" column points to the plan in 2.9.

| # | Question | Public code shows | Query step |
|---|---|---|---|
| 1 | **Access route.** Will you run the queries and hand over exports, or connect the CDT Express MCP in a session you control? | Both work. The SDK's `client.get` reaches every endpoint in 2.2. The MCP lacks the `locations`, company/index `aggregation` and `ownership` endpoints, and passes responses through the AI app. See the recommendation at the end of 2.9 | decision |
| 2 | **Fields.** Which fields does a real `get_company_assets` / `get_asset` response contain, and which are mostly null? | 16 declared fields, plus `company_id`, `asset_function` and `asset_category` (2.3) | 1, 4 |
| 3 | **Values.** Is there an asset value, replacement cost, capacity, area or materiality field, with unit and basis, covered by your licence? | `asset_value` (int, default 0, undocumented, 0 in every public example), `building_footprint` (unit undocumented), `materiality_score` (undefined). No capacity or replacement-cost field | 4 (value coverage), 0 (licence) |
| 4 | **Coverage.** How many VELO/CDT assets lie in the IRIS NA domain, by country and type? | No endpoint gives a global count cheaply (`/assets` has no bbox and costs a credit per asset). Index-level `assets/aggregation` gives counts per index constituent set | 2 |
| 5 | **Candidates.** Which 3–5 companies have 25–200 assets in hurricane-exposed parts of the domain, under one risk owner? | Index company screen sorted by `asset_count` with `country`/`state` filters. Then the company `aggregation` by state, and `locations` with a bbox | 2, 3 |
| 6 | **Ownership.** Are ownership shares or subsidiaries resolved, so that "one risk owner" is well defined? | Each asset has one owner (`company_id`, `/ownership`). **No ownership-share field.** Subsidiaries are "available only to authorized users". `is_grandparent` is undocumented | 5 |
| 7 | **Coordinates.** How precise are they (geocoded address, site centroid, city centroid)? | 6–7 decimals plus a full street address in the examples, which suggests address geocoding. The method isn't documented | 4 |
| 8 | **Licence: VELO/CDT.** What may be published (asset-level coordinates and types; anonymised or jittered locations; aggregates; the company name) in the paper, on the website and in this repository? | **No public data terms found** (2.8, 3.2). The software licences don't cover data | 0 |
| 9 | **Licence: CRC Open.** Does your full licence change CC BY-NC 4.0 for you? | Public terms only (3.1) | 0 |
| 10 | **Hazards beyond CRC Open.** Do you have VELO hazard data (other scenarios, historical, cyclone curves with stated semantics), and may results built on it be published? | The MCP exposes `/v4` location exposure/impact metrics and distributions for 63 risk factors. Pathways: `historic`, SSP1-1.9 … SSP5-8.5, `SV` and 4 warming bands. Horizons 2010–2100 (2.7) | 6 |
| 11 | **Cyclone methodology.** Can you obtain the definition of the CRC/VELO `cyclone` curve (source model, wind averaging and height, annual-max or not)? | Not in any public repo. No tool returns methodology; `get_metrics_definition` covers the damage metrics only | ask the provider |

**Exports requested** (save **outside the repository**; this repository never holds VELO data):

- E1. For each shortlisted company: one row per asset in the domain, with **all** response fields, as raw JSON or CSV converted to Parquet (step 4).
- E2. One raw JSON `get_asset` response and one raw `get_company` response, to confirm the schema (step 1).
- E3. Count tables: index screen output (company × `asset_count`) and per-candidate `aggregation` by state and by `asset_type` (steps 2–3). CSV.
- E4. The licence text or its relevant clauses, or your written summary, for 3.2 (step 0).

### 2.6 Finding candidates: what the filters allow

- **No direct filter.** Company search can't filter by region, country, bounding box or asset count (`/companies/search` takes `name`, `isin_code`, `stock_ticker`, `sector` only), and `/companies` sorts by `created_at`, `name` or `sector` only.
- **The efficient screen is per market index.** `/markets/indexes/{index_id}/companies/climate/scores` accepts `country` and `state` (comma lists) and `sort_by=asset_count`, and returns `asset_count` per company. One paged call per index lists companies by asset count. *Not documented:* whether `asset_count` counts only assets matching the `country`/`state` filter, or all the company's assets. Step 3 checks it on one company.
- **Per company, counts are cheap.** `/companies/{id}/assets/aggregation?by=state&country=USA` costs one credit per state returned [S16]. `/companies/{id}/assets/locations?bbox=-100,5,-55,45` returns coordinates only; its credit cost is undocumented. **A bbox filter exists only within a company** (`locations`, `geo/clusters`), not across all assets.
- **Coverage is limited to indexed companies.** Companies outside the indexes the owner can see need a name search first. "Over 12,000 companies" is the provider's own figure [S15].

### 2.7 Hazard and climate metrics per asset

| Level | Endpoint / tool | Content |
|---|---|---|
| Asset scores | `/assets/{id}/climate/scores` (`get_asset_climate_scores`); `/companies/{id}/assets/climate/scores` (`list_company_asset_climate_scores`) | `dcr_score`, `expected_impact`, `var_50/95/99`, `cvar_50/95/99`, per `pathway` and `horizon`. Glossary: `dcr_score` is "the probability that a physical asset will experience more negative impact during a future horizon than during the historical baseline (2010 horizon)". The others are damage "measured as a percentage of tangible capital asset value" [S14] |
| Asset impacts by factor | `/companies/{id}/assets/climate/impacts` (`list_company_asset_impact_scores`) | Per risk factor (`index_name`, e.g. `cyclone`, `frost_days`): `index_impact_*` and `index_attribution_*` at 50/95/99 and expected [S13], [S16] |
| Location exposure | `/v4/climate/metrics/exposure` (`get_climate_metrics_exposure`) | Raw hazard statistics at a latitude/longitude. Percentiles (default 50, 75, 90, 95, 99), statistics (`minimum`, `maximum`, `mean`, `stddev`, `cvar_95`) and return periods (default 2, 5, 10, 20, 100) [S14] |
| Location distribution | `/v4/climate/distribution/exposure`, `/impact` (`get_climate_distribution_*`) | "The full exposure distribution (quantile values) for a single risk factor", per pathway and horizon [S14] |
| Location impact | `/v4/climate/metrics/impact`, `/probability_adjusted_impact` | Damage estimates at a point [S14] |

- **Overlap with CRC Open.** The MCP's 63 `RISK_FACTORS` (`src/constants.ts` L3–67) are the same names as CRC Open's 63 hazards (1.6), with one spelling difference: VELO `maximum_consecutive_dry_days` vs. CRC `max_consecutive_dry_days`. Where CRC Open has SSP5-8.5 only, the VELO schemas list the pathways `historic`, `ssp119`, `ssp126`, `ssp245`, `ssp370`, `ssp434`, `ssp460`, `ssp585`, `SV` and `<2 degrees` … `>4 degrees`, with horizons 2010 and 2025–2100. Which of these the owner's entitlement serves is unknown. The notebooks also use pathway `RT3`, which no schema lists. *Unknown:* whether VELO's `cyclone` is the same pooled distribution as CRC Open's.
- **Relevance to the program.** Location distributions are per-point **marginals**, like CRC Open. There's no event set and no cross-site dependence, so R-04 is still needed before they can drive an `EventSet`. VELO's damage metrics (DCR, VaR/CVaR as % of value) are not hazard intensities. They are not comparable to CRC values or to the core's losses without a crosswalk [S10].

### 2.8 Licence and publication: what public sources say

- The **software** licences are Apache-2.0 (`velo-sdk`, notebooks) and MIT (`cdt-express-mcp`). They cover the code only.
- **No public VELO/CDT data terms were found** on 2026-10-25:
  - `docs.riskthinking.ai/docs/horizons` redirects (301) to `velo.riskthinking.ai/resources/docs/horizons`, a sign-in page that shows only "All rights reserved". It was not signed in to.
  - The OpenAPI document states no data licence.
  - A web search found nothing.
- `crc-sdk/docs/licence-policy.md` [S17]: proprietary products (the pooled bias-corrected CDFs, VELO/CDT) "are separate works … the open data does not make the proprietary data open".
- **Everything about publishing VELO-derived results needs the owner's licence text** (3.2): asset-level, anonymised, aggregate, company name.
- One more point for the licence check: through the remote MCP, responses (including asset coordinates) pass into the AI app's session. Whether the licence permits processing by a third-party AI service is an owner question.

### 2.9 Query plan for the owner

The steps run cheapest first. Each says which question (2.5) it answers, and when to stop. Credit figures come from the notebooks README [S16]; "unknown" means the README doesn't price that endpoint. All calls are read-only GETs.

The setup runs on the owner's machine, never in this repository. The key stays in the owner's environment.

```python
# pip install "velo-sdk==0.0.20" polars   (outside this repo)
import json, pathlib, polars as pl
from velo_sdk.api import APIClient

c = APIClient()  # reads RISKTHINKING_API_KEY
OUT = pathlib.Path.home() / "velo-exports" / "mar41"
OUT.mkdir(parents=True, exist_ok=True)


def save(name, obj):
    (OUT / f"{name}.json").write_text(json.dumps(obj, indent=2))


def all_rows(path, **params):  # raw cursor paging; keeps every response field
    rows, cur = [], None
    while True:
        page = c.get(
            path, params={**params, "limit": 100, **({"cursor": cur} if cur else {})}
        )
        rows += page["results"]
        cur = page["pagination"].get("cursor")
        if page["pagination"].get("last_page", True) or not cur:
            return rows


GULF_ATL = "Texas,Louisiana,Mississippi,Alabama,Florida,Georgia,South Carolina,North Carolina,Virginia,Puerto Rico"
CARIB_CA = "MEX,CUB,DOM,HTI,JAM,PRI,BHS,BLZ,GTM,HND,SLV,NIC,CRI,PAN,BRB,TTO,BMU,CYM,TCA"
BBOX = "-100,5,-55,45"  # min_lon,min_lat,max_lon,max_lat: the IRIS NA probe box in 1.5
```

| Step | Answers | SDK call (raw JSON) | MCP equivalent | Cost | Save as |
|---|---|---|---|---|---|
| **0** | Q8, Q9, Q10 (licence part) | Read the licence; fill 3.2 | `get_metrics_definition` (static text, no API call) | 0 | E4 |
| **1** | Q2 (schema) | `co = c.get("/companies/search", params={"name": "Caterpillar", "limit": 1}); save("company", co)`; `cid = co["results"][0]["id"]`; `save("asset_page", c.get(f"/companies/{cid}/assets", params={"limit": 1}))`. Then `save("asset", c.get(f"/assets/{aid}"))` for that page's asset `id` | `search_companies {name: "Caterpillar", limit: 1}`, then `get_company_assets {company_id, limit: 1}` | ≈ 2 | E2 |
| **2** | Q4, Q5 (screen) | `idx = c.get("/markets/indexes", params={"limit": 100})` (pick broad US indexes). Per index: `c.get(f"/markets/indexes/{iid}/companies/climate/scores", params={"state": GULF_ATL, "country": "USA", "sort_by": "asset_count", "sort_direction": "descending", "limit": 100, "metric": "dcr_score", "pathway": "ssp585", "horizon": 2050})`. Repeat with `country=CARIB_CA` and no `state`. Optional: `c.get(f"/markets/indexes/{iid}/assets/aggregation", params={"by": "country", "country": "USA," + CARIB_CA})` | `list_all_market_indexes {}`; `get_all_market_index_companies_climate_scores {index_id, country: "USA", state: GULF_ATL, sort_by: "asset_count", limit: 100, pathway: "ssp585", horizon: "2050", metric: ["dcr_score"]}` (no aggregation tool) | unknown, probably 1 per row returned; ≤ 100 per index page | E3 (CSV) |
| **3** | Q5 (verify), Q4 per company | For the top 10 companies with `asset_count` in about 15–300: `c.get(f"/companies/{cid}/assets/aggregation", params={"by": "state", "country": "USA"})` and `params={"by": "asset_type"}`; `c.get(f"/companies/{cid}/assets/locations", params={"bbox": BBOX})`. Count rows in the bbox and compare with step 2's `asset_count` (this settles the filter-semantics question in 2.6) | no tool for `aggregation`/`locations`; `get_company_geo_clusters {company_id, zoom: 3, bbox: BBOX}` gives counts | aggregation likely 1 per group (the README prices score aggregations so); `locations` unknown | E3 |
| **Stop A** | | If no company has ≥ 25 assets in the domain under one `company_id`, stop: for the paper, §4 item 3 applies (LitPop). | | | |
| **4** | Q2, Q3, Q7 (on the shortlist) | For 1–3 shortlisted companies: `rows = all_rows(f"/companies/{cid}/assets", country="USA", state=GULF_ATL) + all_rows(f"/companies/{cid}/assets", country=CARIB_CA)`; `save(f"{cid}_assets", rows)`; `pl.DataFrame(rows).write_parquet(OUT / f"{cid}.parquet")` | `get_all_company_assets {company_id, country: "USA", state: GULF_ATL, limit: 100}` (CSV, ≤ 3,000 rows) | 1 per asset (≤ 200 each) | E1 (Parquet) |
| | | Report per company: number of rows; % with `asset_value > 0`, `building_footprint > 0`, non-empty `name`; distinct `asset_type`/`asset_function`; decimals of latitude/longitude; distinct `hex_id` | | 0 (local) | 2.11 |
| **Stop B** | | If `asset_value` is 0 for most assets **and** `building_footprint` is 0 for most assets, only V3–V5 remain: §4 item 2 applies | | | |
| **5** | Q6 | `c.get(f"/companies/{cid}")` (`is_grandparent`); `c.get(f"/companies/{cid}/subsidiaries")` (may be refused); `c.get(f"/assets/{aid}/ownership")` for 3 sample assets | `get_company`, `get_company_subsidiaries` (no ownership tool) | ≈ 5 | E2 |
| **6** | Q10 (optional) | At one thesis Miami coordinate: `c.get("/v4/climate/distribution/exposure", params={"latitude": 25.77, "longitude": -80.19, "risk_factor": "cyclone", "pathway": "historic", "horizon": 2010})` and the same with `ssp585`/`2050`. Compare with the CRC Open `cyclone` marginal at that r5 cell | `get_climate_distribution_exposure {latitude, longitude, risk_factor: "cyclone", pathway: "ssp585", horizon: "2050"}` | unknown (2 calls) | JSON |
| **Don't** | | `list_all_assets` / `GET /assets` for the whole domain: one credit per asset, no bbox, and the MCP truncates at 30 pages | | | |

**Where exports go.** A folder outside every git checkout (e.g. `~/velo-exports/mar41/`). Add a `README.txt` there with the query date, endpoint, parameters, SDK or MCP version and credits used, plus a SHA256 of each file. Only counts and field-coverage percentages come back into this file (2.11). Asset rows, coordinates and company names don't, unless 3.2 allows it.

**Recommended access route (agent's view).** Route (a): **the owner runs steps 0–5 with the SDK's `client.get` and drops exports outside the repository.**

- It reaches the `aggregation` and `locations` endpoints that make steps 2–3 cheap, and the MCP doesn't expose them.
- It keeps raw responses with every field.
- It doesn't route proprietary rows through an AI service before the licence question (2.8) is answered.

Route (b), the owner connecting the CDT Express MCP as a connector in a session he controls, is a reasonable alternative for steps 1–2 only, if the licence permits AI-tool processing. The tool calls are visible and read-only. Expect the 30-page cap and no aggregation endpoints.

### 2.10 Viability verdicts (agent, from public code only)

| Use | Verdict | Reasons |
|---|---|---|
| **(a) CRC showcase** (real company assets × CRC Open hazards) | **Viable with a value proxy**, conditional on the licence allowing at least aggregated or anonymised publication | The schema carries what the showcase needs: coordinates (address-level in the examples), `asset_type`/`asset_function`, `country`/`state`, an owning `company_id`, an H3 r7 `hex_id`, and a footprint for proxy V2. VELO risk factors use CRC Open's hazard names, which makes a CRC-vs-VELO comparison straightforward to label. What's missing is a populated value (every public example has `asset_value = 0`). The showcase can state its proxy openly. Publication form is unknown until 3.2 is filled |
| **(b) Paper portfolio** (D2 candidate (a)) | **Unknown until a query is run** (steps 2–4); best case **viable with a value proxy** | Whether any company has 25–200 assets in the domain under one owner can't be read from code. `asset_value` is undocumented and 0 in every public example, so V1 is unlikely. V2 depends on footprint coverage (zeros seen, unit unstated). "One risk owner" is well defined per asset (`company_id`), but there are no ownership shares and subsidiary resolution is restricted. Publishing asset-level data in a paper needs licence terms nobody outside has seen. If Stop A or Stop B triggers, or the licence forbids even anonymised results, use LitPop (§4 item 3) |

### 2.11 Owner results (to fill)

**Field coverage** (from step 4, per shortlisted company):

| Company code | Rows in domain | `asset_value > 0` | `building_footprint > 0` (unit) | `name` non-empty | Coordinate decimals (median) | Distinct `hex_id` (r7) | Distinct `asset_type` |
|---|---|---|---|---|---|---|---|
| C1 | _owner_ | | | | | | |
| C2 | _owner_ | | | | | | |

**Coverage in the IRIS NA domain** (from steps 2–3):

| Question | Answer |
|---|---|
| Indexes screened, and companies with ≥ 25 assets in Gulf/Atlantic states or the Caribbean/Central America | _owner_ |
| Does the screen's `asset_count` honour the `country`/`state` filters? (step 3 check) | _owner_ |
| Which asset types dominate there? | _owner_ |

**Candidate companies/portfolios.** Requirements from SPEC §6.6: one risk owner, 25–200 assets inside the IRIS NA domain, and defensible values or a documented proxy. The company name may be replaced by a code if the licence requires it.

| Code | Company (or anonymised label) | Assets in domain | Countries / states | Asset types | Value field or proxy (V1–V5) | Publishable (asset-level / aggregated / not at all) | Notes |
|---|---|---|---|---|---|---|---|
| C1 | _owner_ | | | | | | |
| C2 | _owner_ | | | | | | |
| C3 | _owner_ | | | | | | |

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

No public VELO/CDT data terms exist to start from (2.8). The software licences of `velo-sdk` (Apache-2.0), `cdt-express-mcp` (MIT) and the notebooks (Apache-2.0) cover code only. One extra question applies if route (b) of 2.9 is used: may VELO/CDT responses be processed by a third-party AI service?

| Question | Answer (owner) |
|---|---|
| Licence holder, date, and which products it covers (CRC Open, VELO/CDT assets, VELO/CDT hazards) | _owner_ |
| May CRC Open data be used beyond CC BY-NC (commercial use, relicensing derived figures)? | _owner_ |
| May VELO/CDT asset-level data (coordinates, types, values) appear in the paper / website / public repository? | _owner_ |
| May the company be named, or must it be anonymised? Is jittering or coarsening to H3 r5/r7 acceptable? | _owner_ |
| May aggregate results (portfolio KPIs, payout functions, exceedance curves) built on VELO/CDT data be published? | _owner_ |
| Required attribution text for VELO/CDT | _owner_ |
| Retention or deletion obligations for exports | _owner_ |
| May VELO/CDT responses be processed in an AI chat session (MCP route)? | _owner_ |

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

> **This is the agent's recommendation, prepared before any VELO/CDT data was seen.** It uses the public VELO/CDT code only (Section 2). It is conditional and needs the owner's approval. It records options and the conditions that would choose between them. It makes no claim about method performance.

Observations that hold whatever VELO/CDT contains:

- O1. CRC Open gives per-cell **marginal** curves only (1.2). It cannot replace the IRIS event set as the paper's hazard catalogue without a dependence model (R-04).
- O2. The CRC `cyclone` layer is pooled and scenario-independent (1.4). It cannot provide climate scenarios for P-06; it is useful for R-03 as a cross-model check only. Its probability semantics are undeclared, so return levels compared in R-03 should be labelled with the 1 − 1/*T* convention.
- O3. CRC Open covers the IRIS NA domain at partition level for cyclone, rainfall and flood hazards (1.5). Cell-level coverage at the actual portfolio still needs checking (F3).
- O4. CRC Open is CC BY-NC (3.1). This matters for the paper only if CRC-derived numbers appear in it.
- O5. The public VELO/CDT asset schema has coordinates, asset type and function, country and state, one owning `company_id` and an H3 r7 cell (2.3). It has **no ownership-share field**.
- O6. The schema's only value field, `asset_value`, is undocumented and 0 in every public example. A value proxy (V2: VELO footprint × unit cost) is the likely path, and footprint coverage decides whether it works (2.4, query step 4).
- O7. Candidates can be screened per market index by `asset_count` with `country`/`state` filters, and counted per company by state or within a bounding box (2.6). There is no global bounding-box search.

Conditional recommendation for D2:

1. **If** VELO/CDT has a company meeting SPEC §6.6 (one risk owner, 25–200 assets in the IRIS NA domain, coordinates and asset types), **and** it has a value field or a field supporting proxy V2, **and** your licence allows publishing at least anonymised or aggregated asset-level results in the paper, **then** choose candidate **(a) VELO/CDT**, anonymised as the licence requires, with the value proxy documented. Keep **(b) LitPop** as the open replication case (the CLIMADA tutorial needs it anyway, SPEC §6.6).
2. **If** such a company exists but neither V1 nor V2 is usable (only V3–V5 possible: query plan "Stop B"), **then** use (a) only if you judge the proxy defensible. Otherwise use (a) in the CRC showcase only and (b) LitPop for the paper.
3. **If** the licence forbids publishing asset-level or company-identifiable results, or no company has 25–200 assets in the domain (query plan "Stop A"), **then** choose **(b) LitPop** for the paper and keep VELO/CDT for the CRC showcase under the licence.
4. In every case the thesis 9-asset Miami portfolio stays the illustrative and parity case (SPEC §6.6).

---

## 5. Unverified points and follow-ups

### Not verified here

- **Cell-level coverage** of each hazard at specific coordinates. Only r0 partition presence was checked; no Parquet partition was downloaded.
- **Cyclone values identical across horizon labels**: declared in the catalogue, not checked against values.
- **Cyclone probability semantics and wind-speed definition**: not stated publicly (1.4, question 11).
- **The H3 r0 cells `803b…` and `8027…`** lying outside exposed coasts: located from boundary vertices only, not checked against a land mask.
- **The provider's own terms-of-use page** for CRC Open: none found; the licence is taken from the catalogue and the provider's READMEs.
- **Section 2 against the live service.** Everything in 2.1–2.10 is read from public code and docs. Unverified in particular:
  - which fields the owner's entitlement returns, and how often `asset_value` and `building_footprint` are non-zero;
  - the unit of `building_footprint` and the definition of `materiality_score`;
  - whether the index screen's `asset_count` honours the `country`/`state` filters;
  - credit costs of `locations`, `geo/clusters` and the index screens;
  - whether VELO's `cyclone` is the same pooled distribution as CRC Open's;
  - the `RT3` pathway used in the notebooks.
- **The two SDK caveats in 2.3** (dropped undeclared fields, broken async handlers) were found by reading the code. Nothing was run.
- **Section 2.11 and Section 3.2** (owner).

### Proposed follow-ups (for the orchestrator to file; not done here)

- **F1.** Update `docs/data-sources.md`: set the CRC Open row to CC BY-NC 4.0, with source `https://data.riskthinking.ai/crc-open/<release>/_CATALOG.json` (`licence` field) and check date 2026-10-25. Add a "CRC Open licence check (MAR-41)" subsection like the IRIS one. This is outside MAR-41's single owned file.
- **F2.** Add the release ID `ssp585-global-2026-10-20-v1` and catalogue SHA256 as the pinned default in the CRC adapter (MAR-42). The adapter should read `licence`/`attribution` from the catalogue into `EventSet` `metadata.json` rather than hard-coding them.
- **F3.** In MAR-42/MAR-43, run a cell-level coverage check (DuckDB range reads or `crc-sdk` `for_assets`) for the thesis Miami portfolio and the chosen P-05 portfolio. Report `no_data` and unmatched cells explicitly.
- **F4.** For R-03: record that CRC cyclone return levels use the 1 − 1/*T* convention on a curve with undeclared probability semantics, and that the 9 Miami assets share 5 r5 cells.
- **F5.** Ask the provider, through the owner, for the cyclone methodology (question 11). It may also be in the owner's licence documentation.
- **F6.** A CRC adapter loader for VELO exports (MAR-42/MAR-43, if the owner picks VELO/CDT). It would read the raw JSON/Parquet export (2.9 step 4) into the core's asset table: `asset_id` ← `id`, coordinates, `asset_type`/`asset_function`, `hex_id`. It must record value-proxy provenance, raise on null coordinates, and keep zero values and footprints visible instead of dropping them. Map VELO `maximum_consecutive_dry_days` to CRC `max_consecutive_dry_days`.
- **F7.** Ask the provider, through the owner, for the definitions of `asset_value` (currency, basis), `building_footprint` (unit) and `materiality_score`, and the geocoding method. These are needed to document a value proxy in `metadata.json`.

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
| [S10] | `crc-docs/.agents/skills/velo-*/references/playbook.md` and `crc-docs/.agents/skills/compare-crc-velo-assessments/references/crosswalk.md` (local) | VELO tool names (`get_company_assets`, `get_all_company_assets`, `get_asset`, `search_assets`, `get_asset_climate_scores`, `get_metrics_definition`), expected evidence fields, and the CRC↔VELO crosswalk rule ("Never compare directly to DCR/VaR/CVaR"). Not checked against the live service |
| [S11] | `crc-docs/README.md` (local) | "Overture places are candidate locations, not proof of ownership" |
| [S12] | <https://creativecommons.org/licenses/by-nc/4.0/> | Licence text linked from [S3] and [S5]. Not re-read for this draft; the summary in 3.1 is the agent's reading of the standard CC BY-NC 4.0 terms |
| [S13] | <https://github.com/RiskThinking/velo-sdk> at `ae1aebec31cd7e831a8a53c594bfa4f426c2b3d6` (2026-02-26; `pyproject.toml` version 0.0.20, Apache-2.0). Files: `README.md`, `velo_sdk/api/types.py` (models), `assets.py`, `companies.py`, `markets.py`, `base.py` (base URL, `/v3` prefix, 429 handling), `pagination.py`, `errors.py`, `climate.py`. `types.py` history: the `Asset` model is unchanged since `445b40eeec` (2025-05-06) | SDK endpoints, `Asset`/`Company`/score models, pagination, retry/credit errors, direct `client.get` access |
| [S14] | <https://github.com/RiskThinking/cdt-express-mcp> at `3a0f904b8aada4b061b2245637705ad855fd91fa` (2026-08-19; v0.6.0, MIT). Files: `README.md`, `manifest.json`, `src/server.ts` (40 tools and their URLs), `src/schema.ts` (tool input schemas), `src/constants.ts` (risk factors, pathways, horizons, metrics), `src/glossary.ts`, `src/utils.ts` (raw JSON pass-through, 30-page cap) | MCP tools, parameters, filters, metric definitions, remote OAuth route |
| [S15] | <https://api.docs.riskthinking.ai/openapi-public.yml>: the spec file loaded by the public Redoc page <https://api.docs.riskthinking.ai/> (HTTP 200, `text/yaml`, 110,377 bytes, `Last-Modified: Wed, 21 Oct 2026 17:51:04 GMT`, served by GitHub Pages; SHA256 `01d042f0bdcda53c551bea2d89ae079683eb088face5efadf286907f9e3ea269`). A documentation file, not an API endpoint. `api.riskthinking.ai` itself was not contacted | Every `/v3` path and its parameters (`bbox`, `state`, `asset_function`, `asset_category`, `by`, `sort_by=asset_count`), the `Asset`/`Company`/pagination schemas, the "over 12,000 companies" statement |
| [S16] | <https://github.com/RiskThinking/cdt-express-notebooks> at `07de3194b0a7eeb1ad2bf1cfefad671e893bbe4c` (2025-06-18, Apache-2.0). `README.md`/`notebooks.json` (credit rules). Executed outputs of `7.company-asset-map.ipynb` cell 8 (5 Caterpillar asset rows), `8.company-competitor-comparison.ipynb` cells 12–19 (P&G/Unilever rows, footprint imputation), `6.company-asset-materiality-risk.ipynb` (materiality bins, pathway `RT3`) | Real response columns and example values (`asset_value` 0, footprint zeros, `hex_id` r7, coordinate decimals, `asset_function`/`asset_category`), credit costs |
| [S17] | <https://github.com/RiskThinking/crc-sdk> at `b08a51de50777c387aea550d0c7ff42b7904bef7` (`README.md` `for_assets` contract; `docs/licence-policy.md`). <https://github.com/RiskThinking/crc-framework-rs> at `5484de1840d7ffed9134517ff93da06ba229c175` (no VELO or asset-database code) | CRC asset input columns; proprietary-vs-open data statement |
| [S18] | <https://docs.riskthinking.ai/docs/horizons>: 301 to <https://velo.riskthinking.ai/resources/docs/horizons>, a sign-in page (no content beyond "All rights reserved"). Not signed in | No public VELO data-coverage or terms page |
| [S19] | Web search "Riskthinking.AI VELO terms of use data licence academic" (2026-10-25) | No public VELO/CDT data terms found |

H3 cell maps and lattice probes were computed locally with the `h3` Python package (v4 API) on the catalogue metadata. The three VELO `hex_id` examples were decoded locally with bit arithmetic (resolution = bits 52–55). No CRC Parquet data was downloaded. No VELO/CDT API or MCP endpoint (`api.riskthinking.ai`, `mcp.riskthinking.ai`) was contacted. Public repositories were cloned into a scratch directory outside the repository and read only.
