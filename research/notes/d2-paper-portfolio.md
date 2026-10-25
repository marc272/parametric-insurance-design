# D2: paper portfolio, decision note (for the owner's decision)

- Issue: [MAR-30](https://linear.app/marc-prinzing/issue/MAR-30/p-05-portfolio-spike-choose-the-paper-portfolio-d2) (Human / Decision). Prepared by a worker agent on 2026-10-25.
- Status: **open.** The owner, Marc Prinzing, decides D2. This note compares the candidates and proposes one; it does not record a decision. SPEC §11 D2 is unchanged.
- Location: next to the D7 note, in `research/notes/`.
- Scope: candidates (b) LitPop and (c) Overture are assessed. Candidate (a) VELO/CDT is **pending MAR-41** (the CRC/VELO stream is deferred), and no CRC/VELO data or credentials were used.
- No data was downloaded for this note. The only network reads were documentation pages and dataset metadata records (sources at the end). Counts marked "to measure" have not been computed.

## Question

Which realistic portfolio does the paper use (SPEC §6.6)? MAR-31 builds it as an EventSet, and the paper's experiments (C1, R1, figures) run on it. The thesis 9-asset Miami portfolio stays the illustrative and parity case either way.

Requirements (SPEC §6.6, MAR-30):

1. **R1. Single risk owner.** The positioning (`research/lit/positioning.md`) states the setting as "a corporate, municipal or sovereign body" holding several assets, with payouts calibrated against the owner's aggregate uncovered loss. Pools of several owners (CCRIF, Ciullo et al. 2023) are out of scope.
2. **R2. 25–200 assets inside the IRIS North Atlantic domain** (US Gulf/East coast, Caribbean, Central America).
3. **R3. Defensible values, or a documented value proxy.**

## Candidates against the requirements

| | (a) VELO/CDT asset database | (b) CLIMADA LitPop | (c) Overture places |
|---|---|---|---|
| R1 single owner | Yes, a real company (as described in SPEC §6.6) | **By construction**: a sovereign or sub-national government whose loss is the modelled asset loss in its territory. A documented framing, not an observed balance sheet | **Assumed**: Overture has no ownership field. A brand (one chain) or a public facility category (e.g. hospitals) stands in for an owner |
| R2 count and domain | Pending MAR-41 | **Yes, by choice of admin units**: Florida's 67 counties or Puerto Rico's 78 municipalities fall in 25–200 with no subsetting. Both lie in the IRIS NA basin | Probably yes after filtering, but the count depends on the category/brand and the confidence threshold. **To measure** |
| R3 values | Need a proxy (SPEC §6.6) | **Yes**: produced capital (World Bank, or GDP × wealth ratio) disaggregated by nightlights × population. Published method (Eberenz et al. 2020) | **No values.** Needs a proxy: uniform, building footprint × unit cost, or the LitPop value of the cell (hybrid) |
| Licence for publication | Owner's licence, never committed; publishing sensitive | **CC BY 4.0** (verified on the dataset records). Attribution only | Places: **CDLA-Permissive-2.0 / Apache-2.0 / CC0** by source (verified). Results are unrestricted. Footprints (Buildings) are **ODbL**, share-alike |
| Anonymisation | Probably needed (SPEC §6.6, §10) | Not needed | Needed or advisable for a named brand; not for public facilities |
| Reproducibility | Licensed access only | Pinned files with MD5 checksums on the CLIMADA data API | Monthly dated releases on public S3/Azure; no published checksums seen; quality varies by release |
| Fit with the CLIMADA tutorial (K-04, open data only) | Excluded (CRC/VELO-free stream) | Same data family as K-04 ("LitPop plus synthetic tracks", SPEC §8) | Open, but not a CLIMADA exposure type |

## (a) VELO/CDT asset database: pending MAR-41

Not assessed. MAR-41 (CRC R-01 inventory) was deferred by the owner on 2026-10-25 so that it doesn't block the CLIMADA-based work. When MAR-41 reports fields, values and terms, (a) can be added to this note. SPEC §6.6 and §10 already expect a value proxy and possible anonymisation.

## (b) CLIMADA LitPop

### Source and licence

- **What it is.** Gridded asset values: a national total (World Bank produced capital for 140 countries, otherwise 2014 GDP × Credit Suisse wealth-to-GDP ratio for 84 countries) disaggregated in proportion to Lit^m · Pop^n, with nightlights from NASA "Earth at Night" (Black Marble) and population from GPW v4.11. Reference: Eberenz, Stocker, Röösli & Bresch (2020), *ESSD* 12:817–833, doi:10.5194/essd-12-817-2020.
- **Licence: CC BY 4.0**, from two primary records:
  - CLIMADA data API, the per-file dataset records that `climada.util.api_client.Client` downloads: every one of the 684 active `litpop` records carries `"license": "Attribution 4.0 International (CC-BY-4.0)"`;
  - the archived dataset on the ETH Research Collection, doi:10.3929/ethz-b-000331316 (DataCite record registered by ETH Zurich): "Creative Commons Attribution 4.0 International", SPDX `cc-by-4.0`.
- **Upstream inputs.** GPW v4.11 population count: "openly shared, without restriction", per the NASA Earthdata catalogue page. The terms of the NASA Black Marble nightlights and of the World Bank wealth accounts were **not checked**. They are inputs to the CC BY dataset that ETH publishes, not data we use directly.

### Files that match the default LitPop (exponents (1, 1), produced capital, 150 arcsec)

Read from the CLIMADA data API on 2026-10-25. Version `v3`, created 2022-06-26 with CLIMADA v4.1.1 (originally v3.1.2), `reference_year` 2018, GPW v4.11.

| Dataset name | uuid | Size (bytes) | Checksum (from the API record) |
|---|---|---|---|
| `LitPop_150arcsec_USA` | `678e9551-32ca-40f3-9881-9bd38412c1cd` | 51,228,208 | `md5:9f019394e1736e67c6fd5572875a2fa1` |
| `LitPop_150arcsec_PRI` | `3a604fa2-1526-42ac-8214-1b493fa478df` | 1,097,656 | `md5:2fc9007e344362f3d03368ed003376fb` |
| `LitPop_150arcsec_DOM` | (in the API listing) | 1,249,224 | `md5:564038f6660d3aa3c59a684c35e223ee` |
| `LitPop_150arcsec_JAM` | (in the API listing) | 1,104,832 | `md5:69eedba92c5a19df9d1edb7eddb25103` |

All 27 countries and territories checked in and around the domain (US, Mexico, the seven Central American countries, the Greater and Lesser Antilles, the Bahamas, Cayman, Turks and Caicos, both Virgin Islands) have an active (1, 1) produced-capital file.

### How to build a single-owner portfolio of 25–200 assets

A LitPop grid cell is not an asset, and a country file has far more than 200 cells. The portfolio is therefore built by **aggregating cells to administrative units**, each unit being one "location" in the EventSet (`lat`/`lon` = value-weighted centroid, `value` = sum of its cells, the unit's code and cell count as metadata columns, SPEC §5). The owner is the government that holds a cover against modelled asset losses across its units.

| Option | Owner (framing) | Units | Count | Notes |
|---|---|---|---|---|
| **b1. Florida counties** | State of Florida | Counties | 67 | Contains the thesis Miami case (Miami-Dade). About 700 km north–south, Gulf and Atlantic coasts plus inland units, so storms hit subsets of the portfolio. All below 31° N (inside IRIS and STORM NA; no extratropical issue, D7 note). Needs the 51 MB USA file |
| **b2. Puerto Rico municipalities** | Government of Puerto Rico | Municipios | 78 | Small download. A compact island (about 180 × 65 km), so most storms hit most units: strong tail dependence and less room for cross-coverage. The owner reads as sovereign-like |
| b3. Top-N grid cells | A government, as above | The N highest-value 150-arcsec cells in a region | 25–200 by choice | No boundary file needed, but cells are arbitrary and the remainder of the region's value is dropped (must be recorded, not silent) |
| b4. Another Caribbean sovereign | That country's government | Provinces / parishes | Dominican Republic: 31 provinces plus the Distrito Nacional = 32. Jamaica: 14 parishes (below 25) | Fits CCRIF-style framing, but a single sovereign, not a pool |

The unit counts are standard administrative facts and are to be confirmed from the boundary file at build time.

**Value method.** The LitPop value of each unit is the sum of its cells. Unit and currency: the data-type description on the API says produced capital is "in constant 2014 USD", while the file records give `reference_year` 2018. **Which one applies is to verify** when the file is first read (MAR-31). Either way the value is a modelled proxy for the asset base, and the loss is CLIMADA's impact with the Emanuel impact function, as in the thesis.

**Index for an aggregated unit (needs a decision).** SPEC §6.3 defines the index at the asset. For a county or municipality, the options are:

- (i) wind at the value-weighted centroid, the analogue of thesis index (a);
- (ii) cat-in-a-circle around the centroid, SPEC index (b), as Steinmann et al. (2023) do around hospitals;
- (iii) value-weighted mean wind over the unit's cells. This is closer to a modelled-loss trigger, so basis risk would shrink, and it is not one of the SPEC index options.

(i) and (ii) fit the SPEC as written; (iii) would need a spec change.

**Asset count:** 67 (b1) or 78 (b2).

### Publication constraints

- **Licence of the results.** Data derived from a source keeps its terms (`docs/data-sources.md`). IRIS plus LitPop gives a **CC BY 4.0** EventSet, to be recorded in its `metadata.json`. CC BY allows publishing the EventSet, figures and tables with attribution.
- **Attribution.** Cite Eberenz et al. (2020) and the ETH dataset DOI (the API's `key_reference` asks for both), plus "CLIMADA data API, dataset `LitPop_150arcsec_<ISO3>` v3".
- **Anonymisation.** Not needed: no private data and no named company.
- **Framing.** The "owner" is a modelling construct (a government whose contingent liability is proxied by modelled asset losses), not a real policy. The paper should say so next to the setup of every number (publication rule, AGENTS.md).

### Reproducibility

- A download script in `packages/climada` (the pixi env) fetches the pinned dataset by name and version through the CLIMADA data API, checks the MD5 above, and never commits the file.
- The boundary file needs its own pinned download, checksum and `docs/data-sources.md` row. Candidates: US Census TIGER/Line counties (b1, and Puerto Rico's municipios, which TIGER treats as county equivalents) or geoBoundaries ADM2. **Neither licence was checked here.** Avoid Overture Divisions for this: they are ODbL, and the locations table would then arguably be a derivative database under share-alike.
- MAR-31 then runs IRIS, indices (a) and (b) and the vulnerability draws on the unit centroids (index) and on all cells (loss), and aggregates the loss per unit.

### Risks

- **Regeneration needs a login.** If the pinned API file is expired or replaced, regenerating it with `LitPop.from_countries` needs GPW v4.11 TIFFs, which per the CLIMADA tutorial require "a (free) login for the NASA SEDAC website". That is the owner's action (agents never use credentials). Mitigation: pin uuid and MD5 now; keep the owner's local copy.
- **Compute.** The loss is computed on every cell. Florida at 150 arcsec is roughly 8,000–10,000 land cells (a rough estimate from area, **to measure**), against 9 centroids in the thesis. Wind fields for the IRIS storms near Florida on that grid are heavy but routine for CLIMADA. A value threshold would cut it, but dropped cells must be recorded.
- **Skewed values.** A few counties (Miami-Dade, Broward, Palm Beach and others) probably hold most of Florida's value. The aggregate CVaR could then be driven by a handful of units. To measure in MAR-31's exposure summary.
- **Proxy quality.** LitPop is a top-down proxy. Nightlights saturate in dense cores, and produced capital is not insured value. Defensible with citation, but it is not an exposure database.
- **Puerto Rico's national total** may come from the GDP × wealth-ratio path rather than World Bank produced capital. Not checked.

## (c) Overture places

### Source and licence

- **What it is.** Points of interest from the Overture Maps Foundation, released monthly at dated paths (e.g. `release/2026-10-21.0/theme=places/type=place/`) on public S3 and Azure, with the latest release listed in the STAC catalogue. Fields include `taxonomy` (hierarchy, primary, alternates; `categories` was removed in the September 2026 release), `basic_category` (about 280 values), `brand`, `confidence` and `sources`.
- **Licence of Places** (Overture docs, places guide and attribution page): published "under the CDLA Permissive 2.0 and Apache 2.0 licenses, depending on the source". It contains no OpenStreetMap data and so carries no ODbL share-alike. By source: Meta, Microsoft, PinMeTo, Krick, RenderSEO, DAC, BrightQuery, Birdeye, Uberall and OpenTravel Alliance are CDLA-Permissive-2.0, Foursquare is Apache-2.0, AllThePlaces is CC0 1.0.
- **CDLA-Permissive-2.0** (the licence text): sharing the data requires making the licence text available with it (§2.1), and the licence "does not impose any restriction or obligations with respect to the use, modification, or sharing of Results" (§3.1). Payouts, figures and KPIs computed from place locations are Results.
- **Other themes.** Buildings, Divisions, Base and Transportation are **ODbL** ("© OpenStreetMap contributors"). Under ODbL a publicly used derivative database must stay ODbL (§4.4), and a publicly used produced work needs a notice (§4.3). Footprint-based values would make the locations table a likely derivative database.
- **Data quality** (places guide): places are "known to contain duplicates, a high junk rate, and low property completeness". `confidence` measures existence only and is not calibrated across providers.

### How to build a single-owner portfolio of 25–200 assets

| Option | Owner (assumed) | Selection | Count |
|---|---|---|---|
| c1. Public facilities of one government | A ministry of health or a county | One `taxonomy` category (e.g. hospitals) in one territory (e.g. Puerto Rico), `confidence` above a threshold, deduplicated | **To measure** with a bbox query |
| c2. One brand | A real company (one chain) | `brand` name in one state or region | **To measure**. Large chains likely exceed 200 in Florida and need a sub-region |

c1 is the Steinmann et al. (2023) setup (hospitals, cat-in-a-circle), moved to the North Atlantic. c2 names a real company's footprint from third-party data, which the company did not provide.

**Value method (needed in every case):**

1. uniform values (every site equal): simple, honest, but no value heterogeneity;
2. building footprint area × floors × a replacement cost per m²: footprints from Overture Buildings (ODbL, share-alike as above), floors are often missing, unit costs need a source (not checked);
3. hybrid with (b): the LitPop value of the site's cell, or a share of it. Each site then gets a CC BY value that reflects local asset density, not the site itself.

**Asset count:** to measure. **Ownership:** assumed, not observed.

### Publication constraints

- Attribution: "Overture Maps Foundation, overturemaps.org" with the access date, plus the per-source lines ("Data from Meta. Available under CDLA Permissive 2.0", etc.) and Foursquare's copyright line and NOTICE.txt (<https://opensource.foursquare.com/places-notice-txt/>).
- Sharing the locations table requires the CDLA text, and the Apache-2.0 notice for Foursquare-sourced rows. With footprint values (option 2), the table is likely ODbL.
- Anonymisation: c2 should be anonymised or avoided (a named company's assumed exposure). c1 does not need it.

### Reproducibility

Pin the release date and the query (bbox, category, confidence, dedup rule), store a checksum of the extracted points computed by the script itself, and never commit the extract. Overture publishes no per-file checksums on the pages read here, and the same query gives different rows across releases.

### Risks

- The single owner is an assumption; R1 is met only by construction of the story.
- Values are the weakest of the three candidates: either uninformative (uniform) or borrowed from LitPop or ODbL footprints.
- Duplicates and junk need a documented cleaning rule, and every dropped row must be reported (no silent drops).

## Recommendation (the agent's proposal, not a decision)

The agent proposes **(b) LitPop, option b1: Florida's 67 counties**, aggregated from the pinned `LitPop_150arcsec_USA` v3 file (CC BY 4.0), with the State of Florida as the single owner, as the D2 paper portfolio. The reasons:

- It meets all three requirements without subsetting or an invented value proxy: 67 units, all in the IRIS NA basin, with published LitPop values.
- It is fully open (CC BY 4.0, attribution only) and needs no anonymisation, so the paper, website and CLIMADA outputs can show the same numbers.
- Its spatial spread lets storms hit subsets of the portfolio, which is where joint calibration and cross-coverage (positioning claim A; website post 2) can show anything. Puerto Rico's compact island would make most units co-move.
- It contains the thesis Miami case, so results connect to the parity portfolio.
- It is the same data family as the K-04 tutorial.

**Fallback:** b2, Puerto Rico's 78 municipalities (same method and licence; a 1 MB file, which also suits a CLIMADA tutorial). If administrative boundaries prove a problem, b3 (top-N cells) needs none. If MAR-41 later shows VELO/CDT is viable and publishable, (a) could be added as a second, anonymised case, not a replacement.

**Not recommended as the main portfolio:** (c) Overture, because ownership is assumed and values must be borrowed. A c1 hospitals portfolio valued from LitPop could be a later robustness case.

This is a proposal. The owner framing (a government holding cover for modelled asset losses) and the choice of region are the owner's calls.

## Questions for Marc

1. **Candidate.** (b) LitPop as the paper portfolio, with (a) VELO/CDT revisited after MAR-41? Or wait for MAR-41, or use (c)?
2. **Region and owner.** Florida's 67 counties (State of Florida), Puerto Rico's 78 municipalities (Government of Puerto Rico), or another territory?
3. **Owner framing.** Do you accept a government whose loss is the modelled LitPop asset loss in its territory as the "single risk owner", stated as a documented proxy in the paper?
4. **Index for an aggregated unit.** Wind at the value-weighted centroid plus cat-in-a-circle around it (both in SPEC §6.3), or value-weighted mean wind over the unit (would need a spec change)?
5. **Publication constraints.** Confirm: CC BY 4.0 attribution on every output using the portfolio, no anonymisation, and the derived EventSet recorded as CC-BY-4.0.
6. **CLIMADA tutorial (K-04).** Reuse the paper portfolio, or use the smaller Puerto Rico file to keep the tutorial light?

## What MAR-31 would need under the recommendation

- A pinned download of `LitPop_150arcsec_USA` v3 through the CLIMADA data API, with the MD5 checked; never committed.
- A boundary source (TIGER/Line counties or geoBoundaries ADM2) with a verified licence, a pinned download and a `docs/data-sources.md` row.
- A mapping of cells to counties, with every cell outside a county (coast, water) reported, not dropped silently.
- Index (a) and (b) at the value-weighted centroid; loss computed on every cell and summed per county; vulnerability draws (SPEC §6.3).
- The value unit (2014 USD vs. reference year 2018) confirmed from the file, and `metadata.json` recording CC-BY-4.0, the dataset uuid and checksum.
- The exposure summary MAR-31 asks for: map, value distribution (to check the skew risk above), tail correlation matrix.

## Sources (all accessed 2026-10-25)

- CLIMADA data API, LitPop dataset records (licence, versions, files, MD5): <https://climada.ethz.ch/data-api/v2/dataset/?data_type=litpop&status=active> and the data-type record <https://climada.ethz.ch/data-api/v2/data_type/>.
- LitPop dataset on the ETH Research Collection, DataCite record: <https://api.datacite.org/dois/10.3929/ethz-b-000331316> (CC BY 4.0).
- CLIMADA LitPop tutorial (parameters, data sources, GPW login): <https://climada-python.readthedocs.io/en/stable/tutorial/climada_entity_LitPop.html>.
- GPW v4.11 population count, NASA Earthdata catalogue: <https://www.earthdata.nasa.gov/data/catalog/sedac-ciesin-sedac-gpwv4-popcount-r11-4.11>.
- Eberenz et al. (2020), *ESSD* 12:817–833, doi:10.5194/essd-12-817-2020 (cited from the records above; not read in full).
- Overture attribution page (licences per theme and source; page last updated 2026-05-15, docs v2.0.0): <https://docs.overturemaps.org/attribution/>.
- Overture places guide (licence statement, schema, quality, download): <https://docs.overturemaps.org/guides/places/>.
- CDLA-Permissive-2.0 text: <https://cdla.dev/permissive-2-0/>.
- ODbL 1.0 text: <https://opendatacommons.org/licenses/odbl/1-0/>.
- Thesis code (read-only): `parametric-insurance-framework/configs/experiment_config.yaml` (9 Miami assets, 156.5 M total value) and `src/CLIMADA/engine.py` (Emanuel USA impact function, IRIS NA files).

**Not reached or not verified:**

- The ETH Research Collection landing page itself was not opened; its licence comes from the DataCite record ETH registered, as for STORM in the D7 note.
- The terms of NASA Black Marble and of the World Bank wealth accounts (LitPop inputs) were not checked.
- The CLIMADA tutorial page states no licence; the licence comes from the dataset records.
- Overture's attribution page shows some source access dates later than its "last updated" date (2026-05-15). The licences were taken as stated.
- No boundary-file licence (TIGER/Line, geoBoundaries) was checked.
- No data was downloaded and no code was run, so cell counts, the per-county value distribution, the Overture counts and the LitPop value unit are all to measure.
