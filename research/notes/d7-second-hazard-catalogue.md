# D7: second hazard catalogue, comparison note (for the owner's decision)

- Issue: MAR-62 (Human / Decision). Prepared by a worker agent on 2026-10-25.
- Status: **decided.** On 2026-10-25 the owner, Marc Prinzing, chose **STORM** (present climate, v4, North Atlantic, CC0) as the D7 second catalogue, following the recommendation below. Perturbed IBTrACS tracks stay for the K-04 CLIMADA tutorial and, at most, an optional check against history. SPEC §11 D7 records the outcome. The comparison below is kept as written, as the basis for the decision.
- Location: `research/notes/` is new. The only existing note folder, `research/lit/`, holds the literature review, so this note sits next to it rather than inside it.

## Question

Which second tropical-cyclone catalogue becomes the hazard-model scenario next to IRIS in source (i) of the robust design (SPEC §6.5): STORM, or CLIMADA synthetic tracks perturbed from IBTrACS? It feeds MAR-32 (the scenario EventSet) and then R1, which is min over scenarios of the max objective, judged by leave-one-scenario-out tests.

Assumed domain: D2 is still open (MAR-30). All three D2 candidates must lie in the IRIS North Atlantic domain (SPEC §6.6), and the thesis case is 9 Miami assets. So this note assumes a **North Atlantic, US Gulf / Florida** domain.

## Criteria at a glance

The β level is the one in SPEC §6.2. β = 0.99 on annual losses means CVaR is the mean of the worst 1 % of years. With the default 70/30 year split (§6.1), the test fold holds 30 % of the years.

| Criterion | IRIS (reference S_0, for context) | STORM (Bloemendaal et al.) | CLIMADA perturbed IBTrACS |
|---|---|---|---|
| Licence for publication | CC BY 4.0 (DataCite record of the figshare collection). The figshare item records of the downloaded files say CC0 1.0 (MAR-72). Both records listed; treated as CC BY 4.0 by owner decision (MAR-94, 2026-10-27; `docs/data-sources.md`) | **CC0 1.0**, all versions of the present-climate dataset (DataCite record by 4TU.ResearchData) | IBTrACS: "full and open access" under the WDC policy, WMO Resolution 40 as a guide for commercial use, citation requested (NCEI page). No named licence. Derived tracks come from CLIMADA (GPL-3.0) code |
| Domain coverage | 6 basins, including NA | 6 basins: EP, NA, NI, SI, SP, WP (no South Atlantic). NA is 5–60° N, from the American coastline to 360°. CLIMADA encodes this as `BasinBoundsStorm.NA` | Global, as IBTrACS. NA reaches back to the 19th century, but the satellite era starts around 1980 |
| Years for stable tails | 10,000 synthetic years (10 files × 1,000), independent years | **10,000 synthetic years** (10 files × 1,000 per basin), independent years | About 45 real seasons (1980 to now) × (1 + `nb_synth_tracks`) pseudo-copies. The default is 9 copies, giving 450 pseudo-years, but these are perturbations of the same 45 seasons (see below) |
| Test-fold years at β = 0.99 | 3,000 years, so CVaR averages 30 years | 3,000 years, so CVaR averages 30 years | 45 seasons if copies stay in one fold, as `splits.py` does for draws (SPEC §4.2): 13–14 test seasons, so the "worst 1 %" is less than one season. 450 pseudo-years if copies may cross folds: 135 test pseudo-years, so about 1.4 years, and train and test then share parent seasons |
| Effort to load | Custom loader in the thesis (`IRIS_transformer.py`, `engine.py`) | **Low.** Native `TCTracks.from_simulations_storm(path, years=None)` reads each `.txt` file and converts the 10-min wind to 1-min (÷ 0.88). The file layout is almost the same as IRIS | **Low to medium.** `TCTracks.from_ibtracs_netcdf` → `equal_timestep` → `calc_perturbed_trajectories`. Needs a pinned IBTrACS snapshot (it updates several times a week) and handling of a global seed |
| Independence from IRIS | — | **Partial.** Different model family, same observational base (see below) | **Low in kind.** A direct transformation of the observed record that IRIS is also fitted to |

## Option A: STORM

- **What it is.** A fully statistical model. It resamples genesis, track and intensity from 38 years of IBTrACS (1980–2018), with an MPI constraint and a wind–pressure relationship, to 10,000 present-climate years. The output is 3-hourly, with the wind as a 10-min mean (U10) and the radius of maximum winds included.
- **Licence.** CC0 1.0 on the dataset DOI 10.4121/12706085 (v4, 2022) and on the v2 DOI cited in the paper and in CLIMADA's docstring. The article is CC BY 4.0. Publishing derived results raises no issue.
- **Fit to the paper.** It gives the same 10,000-year size as IRIS, so S_0 and S_1 have equally stable tails, and leave-one-scenario-out compares like with like. Close prior work (Maier & Scherer 2026b, in `research/lit/`) uses cat-in-a-circle on STORM tracks, so STORM also eases comparison.
- **Known caveats.**
  - The basin domain ends at 60° N, and the training data drop extratropical stages. This barely matters for Florida or the Gulf, but it does for New England or Atlantic Canada.
  - Meiler et al. (2022) found STORM gives too many high-intensity landfalls in the North Indian Ocean. That is outside our domain, but it is a reminder that model choice moves the costliest events.
  - CLIMADA sets every STORM track to year 1980 with frequency 1. The adapter must rebuild `year` (0–9,999 across the 10 files) and set `rate = 1/10,000`.
- **Also available.** A STORM climate-change set for 2015–2050 under SSP5-8.5 / RCP8.5 (DOI 10.4121/14237678, CC0, four GCMs). It is outside D7's scope, but it could later serve as a cross-check for source (iii).

## Option B: CLIMADA synthetic tracks from IBTrACS

- **What it is.** `calc_perturbed_trajectories` (CLIMADA v6.1.0 and `main`) runs a directed random walk on each historical track: it shifts the starting point and perturbs direction and translation speed. It applies landfall decay when `decay=True`. Its docstring says: "No other track parameter is perturbed." The defaults are "only roughly calibrated".
- **Licence.** IBTrACS is open, with citation requested (Knapp et al. 2010; the v04r01 dataset DOI 10.25921/82ty-9e16). No named licence, so record the WDC / WMO Res. 40 wording.
- **Fit to the paper.**
  - Intensity is not resampled, so no storm is stronger than its historical parent, apart from decay. Meiler et al. (2022) attribute a **low-intensity bias** in IBTrACS_p (99 copies per track) to exactly this.
  - Every pseudo-year inherits the count and sequence of storms in one real season. So the annual-loss tail at β = 0.99 is bounded by about 45 real seasons, whatever `nb_synth_tracks` is.
  - The fold rule faces a choice. If copies stay in one fold (as for draws), the test set is too small for CVaR_0.99. If copies may cross folds, information leaks from train into test.
- **Extra facts.**
  - The function seeds NumPy's **global** RNG (`np.random.seed(seed)`). That conflicts with the "no global seeds" standard, so the adapter would have to isolate it and record the seed.
  - It is what the K-04 tutorial ("LitPop plus synthetic tracks", SPEC §8) needs anyway. That holds whatever D7 says.

## Independence: are these two different "hazard-model scenarios"?

- **IRIS and STORM.** Both are statistical models trained on IBTrACS, with overlapping periods (1980–2021 and 1980–2018), so they share the sampling error of one observed record. Their structure differs:
  - STORM simulates the full lifecycle from genesis.
  - IRIS simulates only the decay from lifetime maximum intensity, constrained by ERA5 potential intensity.

  The pair therefore spans **model-structure uncertainty**, but not observational uncertainty.
- **IRIS and perturbed IBTrACS.** This pair compares an extrapolating model with a smoothed copy of history. A gap between them mixes model structure with "no extrapolation beyond the record". It is closer to a historical-anchor check than to a second hazard model.

## Recommendation (the agent's proposal, not a decision)

The agent proposes **STORM (present climate, v4, NA basin) as the D7 second catalogue** for source (i). The reasons:

- it is CC0;
- it has 10,000 independent years, like IRIS;
- CLIMADA can already read it;
- it differs from IRIS in model structure.

Perturbed IBTrACS tracks would stay what the CLIMADA tutorial (K-04) uses, and at most an optional historical-anchor sensitivity check, not a scenario S_k. This is a proposal. Whether R1's source (i) should represent model-structure uncertainty or anchoring to history is the owner's call.

**Question for Marc:** should the second hazard scenario represent *a different hazard model* (then STORM), or *closeness to the observed record* (then perturbed IBTrACS, accepting a test fold of about 45 independent seasons)?

## What MAR-32 would need under each option

- **If STORM:**
  - a download script for the 10 NA `.txt` files from 4TU (DOI 10.4121/12706085, v4), with checksums;
  - a row in `docs/data-sources.md` (CC0, verified on the 4TU page);
  - a reader that wraps `TCTracks.from_simulations_storm`, rebuilds `year` across files and sets `rate = 1/10,000`;
  - the same wind field, centroids and impact functions as the IRIS path, so the scenarios differ only in hazard;
  - metadata recording the 10-min → 1-min wind conversion;
  - the EP files too, if D2 adds Pacific-coast Central America.
- **If perturbed IBTrACS:**
  - a pinned IBTrACS v04r01 snapshot (NA, a fixed season range) with a checksum;
  - the `equal_timestep` + `calc_perturbed_trajectories` parameters and seed recorded in the EventSet metadata;
  - a documented mapping from copies to `year`/`draw_id`;
  - a decision, routed through the spec owner, on whether perturbed copies are "copies of an event" for `splits.py`;
  - code that isolates the global-seed call.

**How the answer would change with D2.**

- **VELO/CDT or LitPop assets in the Gulf, Florida or East Coast below about 40° N:** no change.
- **Caribbean islands:** sparse historical hits make the 45-season limit of perturbed IBTrACS worse, which favours STORM.
- **Pacific-coast Central America or Mexico:** add the STORM EP basin (same reader).
- **Assets north of about 40° N:** both STORM and IRIS drop the extratropical stages, so neither option differs much there. Note it as a limitation.

## Outside the listed options (brief, not assessed)

CLIMADA also reads CHAZ (`from_simulations_chaz`), FAST (`from_FAST`) and MIT/Emanuel (`from_simulations_emanuel`) tracks. Meiler et al. (2022) compare MIT and CHAZ with STORM. Their licences and NA availability were not checked. CHAZ and MIT are statistical-dynamical, so they would differ from IRIS more than STORM does.

## Sources (all accessed 2026-10-25)

- STORM present-climate dataset, DataCite metadata registered by 4TU.ResearchData: <https://api.datacite.org/dois/10.4121/12706085> (v4, 2022, CC0 1.0) and <https://api.datacite.org/dois/10.4121/uuid:82c1dc0d-5485-43d8-901a-ce7f26cda35d> (v2, 2020, CC0 1.0).
- STORM climate-change dataset, DataCite: <https://api.datacite.org/dois/10.4121/14237678> (v2, 2023, CC0 1.0).
- Bloemendaal et al. (2020), *Sci. Data* 7:40, doi:10.1038/s41597-020-0381-2. Full text via Europe PMC PMC7005259. Source for basins, input period, file layout and the 0.88 factor.
- Sparks & Toumi (2024), IRIS, *Sci. Data*, doi:10.1038/s41597-024-03250-y (PMC11043368). The IRIS figshare collection on DataCite: <https://api.datacite.org/dois/10.6084/m9.figshare.c.6724251.v1> (CC BY 4.0; the item records say CC0 1.0, and IRIS-derived data is treated as CC BY 4.0 by owner decision, MAR-94).
- CLIMADA source: `climada/hazard/tc_tracks.py` (`from_simulations_storm`, `BasinBoundsStorm`) and `climada/hazard/tc_tracks_synth.py` (`calc_perturbed_trajectories`), read at tag v6.1.0 (the latest release, 2025-09-30) and on `main`. <https://github.com/CLIMADA-project/climada_python>. The STORM reader is also present at v3.0.0.
- IBTrACS product page, NOAA NCEI: <https://www.ncei.noaa.gov/products/international-best-track-archive>. Source for the terms of use, v04r01 and the citation.
- Meiler et al. (2022), *Nat. Commun.* 13:6156, doi:10.1038/s41467-022-33918-1 (PMC9579140).

**Not reached or not verified:**

- The 4TU landing page (`data.4tu.nl`) refused connections, so the CC0 licence comes from the repository's DataCite record, not from the page itself. File sizes are unknown.
- nature.com redirected to a login, so the open-access copy on Europe PMC was used instead.
- The exact first NA season in IBTrACS was not checked.
- No code was run.
