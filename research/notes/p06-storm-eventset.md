# P-06: the STORM hazard-model scenario (loader and reference; build pending)

- Issue: [MAR-32](https://linear.app/marc-prinzing/issue/MAR-32/p-06-second-hazard-catalogue-eventset) (P-06). Written by a worker agent on 2026-10-27.
- Decision this implements: D7 (SPEC §11, MAR-62): STORM, present climate, version 4, North Atlantic, as the second catalogue of uncertainty source (i) (SPEC §6.5). The portfolio is D2's (Florida's 67 counties, per-cell loss, MAR-114).
- Status: **partial.** The STORM loader, the track-source selection in the pipeline, the configs, the comparison script and the IRIS reference build are done. The STORM files could not be downloaded, so the STORM EventSet, its size estimate and the comparison figure are not built yet. Observations only.
- Files: `research/data/p06-storm-eventset/` (checksums of the IRIS reference build and its `metadata.json`).
- **Update 2026-11-01: the scenario is dropped.** D7 was revisited on 2026-10-31 (MAR-62): STORM is unavailable, so SPEC §6.5 (i) is "none", and the STORM half below will not be built. The loader, the `tracks:` selection, the equivalence test and the comparison script stay (MAR-62). The two STORM configs and the two tests that only loaded them were removed in MAR-185 (ADR 0004 Q5, option 5b); see "Configs" below for their SHA256s and the last commit that has them.

## Why the STORM build is missing

The dataset is served only by 4TU.ResearchData (`data.4tu.nl`, DOI 10.4121/12706085). On 2026-10-27, as on 2026-10-25 (MAR-62), every connection to `data.4tu.nl` (131.180.169.22, ports 443 and 80) timed out or was refused, from the shell and from the web fetcher, while `api.datacite.org`, `figshare.com` and `www.4tu.nl` answered. No mirror of version 4 was found: CLIMADA's data API has no STORM tracks, and the Internet Archive holds only small files and a version-2 zip (547 MB), which D7 does not cover (version 2 still had wrong categories and duplicate tracks). A download script needs the host's own file list and checksums, so it was not written against guessed values.

What is known about the files, from archived copies of the README and of the start of a zip (`docs/data-sources.md`, STORM licence check): one file per basin and 1,000 years, `STORM_DATA_IBTRACS_<basin>_1000_YEARS_<k>.txt`, `k` = 0 … 9, in a zip folder `VERSIE4/`; comma-separated, 13 columns, no header; the year restarts at 0 in every file. The first EP file is 48.5 MB uncompressed (11.1 MB deflated). The archived bytes agree with the layout the loader expects (decompressed: 13 numeric columns, years 0 to 89 in the first 4.5 MB).

## What is in place

**Loader (`storm.py`).** `read_storm_catalogue(directory, basin="NA", n_years=10000)`:

- year mapping: simulation year = `1000 * k + year in file`, with `k` from the file name. It raises if an index is missing or repeated (e.g. `_1.txt` and `_01.txt`), if a year in a file lies outside [0, 1000) (a year that is already global could not be told apart), or if `n_years` ≠ 1,000 × files. The build record keeps, per file, its SHA256, rows, storms, and year range before and after the mapping;
- wind: STORM's maximum wind is a 10-minute mean; it is divided by 0.88 (Bloemendaal et al. 2020; CLIMADA's `STORM_1MIN_WIND_FACTOR`) before it reaches CLIMADA and the Saffir-Simpson breakpoints;
- longitude: 0–360° E is mapped to (−180, 180];
- checks: 13 columns, finite values, integer codes, basin ID, month, TC number < 1,000 (track `id_no` = `1000 * year + tc`), positive pressure and radius, no repeated `(year, tc, timestep)` and consecutive time steps. CLIMADA's own reader drops duplicate rows silently; this one raises.

`storm_to_track` uses the IRIS path's time axis (3-hourly from a fixed anchor), unit conversions and environmental pressure (1,013 hPa), and sets no `radius_oci` (STORM has none; CLIMADA's wind models do not use it, and CLIMADA's STORM reader sets none either).

**Pipeline.** `tracks: {kind: storm}` in a config selects the loader; everything after reading the tracks is the IRIS path. A STORM config must give `hazard_release` and `licence`.

**Equivalence test.** `tests/test_storm.py` writes the five storms of the IRIS test catalogue as two STORM files (wind × 0.88, longitude + 360, years spread over both files). The STORM build gives the same index and loss as the IRIS build of the same tracks (`assert_allclose`, rtol 1e-9), for wind at the centroid and for cat-in-a-circle (exactly equal categories). Rates are `1 / 2000` with the two files, and the events carry the rebuilt years 3, 10 and 1008.

**IRIS unchanged.** IRIS builds write the same metadata as before:

- the thesis regeneration test (`test_adapter_regenerates_the_thesis_eventset`, `IRIS_CATALOGUE` set to the merged IRIS file) passes;
- a rebuild of MAR-114's `configs/florida_counties.yaml` on this branch gives content hash `sha256:d8698f7d2985409f5a5024101d7ba839d42a127a29d5456e5871ecaaa3385131`, the hash MAR-114 recorded (pipeline runtime 698.1 s, wall 715.7 s, peak RSS 2.02 GB, 139,020 rows × 67 counties).

**Configs.**

| Config | Hazard | Index | Draws | Output (`data/eventsets/…`) |
|---|---|---|---|---|
| `florida_counties_no_draws.yaml` | IRIS (reference S_0) | (a) wind at the centroid | none | `florida-counties-iris` |
| `florida_counties_storm.yaml` | STORM (S_1) | (a) | none | `florida-counties-storm` |
| `florida_counties_storm_cat_in_circle.yaml` | STORM | (b) cat-in-a-circle, 50 km | none | `florida-counties-storm-cat-in-circle-50km` |

A test checks that the STORM config differs from the IRIS reference only in `catalogue`, `tracks`, `hazard_release`, `scenario_id`, `scenario_notes` and `output`, and that the no-draws reference differs from MAR-114's config only in `vulnerability` and `output`. No draws build: the vulnerability prior is open (MAR-118 Q1). `scenario_id` is `storm-present-climate`, after IRIS's `iris-present-climate`. Licence: `CC-BY-4.0`, the stricter of STORM's CC0 1.0 and LitPop's CC BY 4.0.

**Removed in MAR-185.** The two STORM configs and the tests that loaded them (`test_storm_configs_load`, `test_storm_config_differs_from_the_iris_reference_only_in_the_hazard`) were deleted; the no-draws test stays. The deleted files, as recorded in `research/data/p06-storm-eventset/checksums.json`:

| Config (`packages/climada/configs/…`, deleted) | SHA256 |
|---|---|
| `florida_counties_storm.yaml` | `2d24aa0970ad4df20dbde50154ee682311d2322901da1ee27aca42a784731884` |
| `florida_counties_storm_cat_in_circle.yaml` | `962516fee4a259660ba0fc3638a61c353314f753ec6610c7a7cb70fc34299cd3` |

They were added in `34bbb23` (this issue's PR #71) and are unchanged up to `603601c`, the last `main` commit that has them. Reviving STORM means writing one config: `florida_counties_no_draws.yaml` plus a `tracks: {kind: storm, basin: NA}` block, with `catalogue`, `hazard_release`, `scenario_id`, `scenario_notes` and `output` for STORM.

The same change rewrote the header comment of `florida_counties_no_draws.yaml`, which named the deleted STORM config. Its SHA256 went from `750480a23ddf035fc3f3f3a33711e0157c9d0d266de02d22000a5fd0e69f8e60` (recorded in `checksums.json`) to `049a6525e0c2eb689b0251c708da0d40429287d089c1f9eac53c3bc7fd3d1527`. Only comments changed; the parsed config is identical, so S_0 and its content hash below don't change.

**Comparison script.** `scripts/compare_hazard_return_levels.py` reads two EventSets with the same locations and writes `return_levels.csv` (per county and for the portfolio: 10-, 50-, 100- and 250-year annual loss and annual maximum index, reference, scenario, ratio), `summary.json` (both content hashes, counts of counties above, equal and below, median ratios) and a three-panel figure. The return level at `T` years is the empirical quantile at 1 − 1/T (numpy `method="higher"`): the 1,000th, 200th, 100th and 40th largest of 10,000 years. It raises unless every rate is `1 / (n_years × n_draws)`.

## IRIS reference S_0 (built)

`configs/florida_counties_no_draws.yaml` on IRIS: content hash `sha256:07eb5c9a808af45f7d05932b5d78f0cc9b1142f37aef8c9749138dc8c1f379e5`, 13,902 rows × 67 counties (8,977 rows with zero loss everywhere), expected annual loss 7.616 × 10⁹ USD (MAR-114 measured the same without draws). Pipeline runtime 487.9 s, wall 494.3 s, peak RSS 1.57 GB. Details in `research/data/p06-storm-eventset/`.

## What the STORM half needed (not pursued: D7 revisited)

Kept as the plan for the case STORM becomes reachable again. Step 4's configs no longer exist and would be written anew (see "Configs").

1. Reach `data.4tu.nl`; read the live landing page's licence; take the file list, sizes and MD5s from its API.
2. A download module and manifest in the pattern of `iris.py` / `iris_manifest.json` (archive and the ten NA members, size, MD5 and SHA256), a pixi task, and the `hazard.release` taken from the manifest when the files match it.
3. Estimate the dense grid first (storms within 500 km of a county), as MAR-113 did. IRIS gives 13,902 of 67,506 storms. Stop and report if STORM's count is far larger.
4. Build `florida_counties_storm.yaml` (and the cat-in-a-circle variant), record hashes, time and memory, run the comparison against `florida-counties-iris`, and commit the figure and its CSV.

## Open points (for the owner or the spec)

- **Environmental pressure.** The STORM path uses the IRIS path's 1,013 hPa (thesis value) so that only the tracks differ. CLIMADA's own STORM reader uses 1,010 hPa for the North Atlantic. The Holland (2008) wind profile depends on the pressure deficit, so this choice moves STORM's winds. Not measured.
- **Duplicate tracks.** Version 4's notes say the duplicates of older versions were removed; the loader raises if any remain, rather than dropping them as CLIMADA does.
- **Basin bound.** STORM's NA basin ends at 60° N and STORM's training drops extratropical stages (D7 note). This does not affect Florida.
