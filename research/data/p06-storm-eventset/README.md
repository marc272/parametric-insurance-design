# P-06 STORM hazard-model scenario (MAR-32)

The hazard-model scenario once planned for the robust design: the D2 portfolio (Florida's 67 counties, per-cell loss) on STORM next to IRIS. Method and measurements: `research/notes/p06-storm-eventset.md`.

**Status: dropped.** D7 was revisited on 2026-10-31 (MAR-62): STORM is unavailable, so SPEC §6.5 (i), the second hazard catalogue, is "none". The IRIS reference S_0 was built; the STORM EventSet never was, because the STORM host (`data.4tu.nl`) could not be reached. The STORM loader stays in `packages/climada`, tested on synthetic files (MAR-62); its two configs were removed in MAR-185 (ADR 0004 Q5, option 5b). The records below are kept as they were.

**Licence: CC-BY-4.0.** Attribution on every output: asset values from the CLIMADA data API, dataset `LitPop_150arcsec_USA` v3 (CC BY 4.0, Eberenz et al. 2020, doi:10.5194/essd-12-817-2020); county boundaries: U.S. Census Bureau, 2025 TIGER/Line Shapefiles; hazard: IRIS (Sparks and Toumi 2024, doi:10.1038/s41597-024-03250-y; collection doi:10.6084/m9.figshare.c.6724251.v1) and, for the dropped STORM scenario, STORM (Bloemendaal et al. 2020, doi:10.1038/s41597-020-0381-2; dataset doi:10.4121/12706085.v4, CC0 1.0).

The EventSets are **not committed**; they are rebuilt into the root `data/eventsets/`:

```sh
cd packages/climada
pixi run --locked iris                 # once (MAR-72)
pixi run --locked florida-locations    # once (MAR-113)
pixi run --locked build-eventset --config configs/florida_counties_no_draws.yaml
```

A STORM build would need the ten STORM NA files in `data/storm/raw/STORM_v4/` and a STORM config, written as `configs/florida_counties_no_draws.yaml` plus a `tracks: {kind: storm, basin: NA}` block (`packages/climada/README.md`, "STORM loader (parked)"). `scripts/compare_hazard_return_levels.py` would then compare it with `florida-counties-iris`.

| EventSet (`data/eventsets/…`) | Config (SHA256) | Content hash |
|---|---|---|
| `florida-counties-iris` (S_0, IRIS, index (a), no draws) | `configs/florida_counties_no_draws.yaml` (`750480a2…69f8e60`) | `sha256:07eb5c9a808af45f7d05932b5d78f0cc9b1142f37aef8c9749138dc8c1f379e5` |
| `florida-counties-storm` (S_1, STORM, index (a), no draws) | `florida_counties_storm.yaml`, removed (`2d24aa09…4731884`) | not built |
| `florida-counties-storm-cat-in-circle-50km` (S_1, index (b)) | `florida_counties_storm_cat_in_circle.yaml`, removed (`962516fe…4299cd3`) | not built |

**Config changes since the build (MAR-185).**

- The two STORM configs were deleted from `packages/climada/configs/`. Their SHA256s: `florida_counties_storm.yaml` `2d24aa0970ad4df20dbde50154ee682311d2322901da1ee27aca42a784731884`, `florida_counties_storm_cat_in_circle.yaml` `962516fee4a259660ba0fc3638a61c353314f753ec6610c7a7cb70fc34299cd3` (as in `checksums.json`). They were added in `34bbb23` (MAR-32) and are unchanged up to `603601c`, the last `main` commit that has them; `git show 603601c:packages/climada/configs/florida_counties_storm.yaml` restores one.
- The header comment of `configs/florida_counties_no_draws.yaml` was rewritten, because it named the deleted STORM config. Its SHA256 changed from `750480a23ddf035fc3f3f3a33711e0157c9d0d266de02d22000a5fd0e69f8e60` (the value in `checksums.json`) to `049a6525e0c2eb689b0251c708da0d40429287d089c1f9eac53c3bc7fd3d1527`. Only comments changed and the parsed config is the same, so the EventSet and its content hash `sha256:07eb5c9a…f1c379e5` don't change.

S_0: 13,902 rows (the storms within 500 km of a county, as in MAR-114) × 67 counties; 8,977 rows with zero loss at every county; expected annual loss 7.616 × 10⁹ USD (LitPop reference_year 2018), equal to MAR-114's no-draws scratch figure. Pipeline runtime 487.9 s, wall 494.3 s, peak RSS 1.57 GB.

## Files here

| File | What it is |
|---|---|
| `checksums.json` | Input checksums, config SHA256s, and per build: content hash, file sizes and SHA256s, rows, runtime and peak memory. Also the check that MAR-114's IRIS build reproduces its content hash on this branch |
| `metadata/florida-counties-iris.metadata.json` | The reference EventSet's `metadata.json` |

A rebuilt EventSet must reproduce the content hash; the Parquet file hashes may differ with another pyarrow version.
