# P-06 STORM hazard-model scenario (MAR-32)

The hazard-model scenario of the robust design (SPEC §6.5 (i), D7): the D2 portfolio (Florida's 67 counties, per-cell loss) on STORM next to IRIS. Method, measurements and what is pending: `research/notes/p06-storm-eventset.md`.

**Status: the IRIS reference S_0 is built; the STORM EventSet is not**, because the STORM host (`data.4tu.nl`) could not be reached on 2026-10-27. The STORM rows, the return-level figure and its CSV come with the follow-up PR.

**Licence: CC-BY-4.0.** Attribution on every output: asset values from the CLIMADA data API, dataset `LitPop_150arcsec_USA` v3 (CC BY 4.0, Eberenz et al. 2020, doi:10.5194/essd-12-817-2020); county boundaries: U.S. Census Bureau, 2025 TIGER/Line Shapefiles; hazard: IRIS (Sparks and Toumi 2024, doi:10.1038/s41597-024-03250-y; collection doi:10.6084/m9.figshare.c.6724251.v1) and, for the STORM scenario, STORM (Bloemendaal et al. 2020, doi:10.1038/s41597-020-0381-2; dataset doi:10.4121/12706085.v4, CC0 1.0).

The EventSets are **not committed**; they are rebuilt into the root `data/eventsets/`:

```sh
cd packages/climada
pixi run --locked iris                 # once (MAR-72)
pixi run --locked florida-locations    # once (MAR-113)
pixi run --locked build-eventset --config configs/florida_counties_no_draws.yaml
# once the ten STORM NA files are in data/storm/raw/STORM_v4/:
pixi run --locked build-eventset --config configs/florida_counties_storm.yaml
pixi run --locked python scripts/compare_hazard_return_levels.py \
    --reference ../../data/eventsets/florida-counties-iris \
    --scenario ../../data/eventsets/florida-counties-storm \
    --out-dir ../../research/data/p06-storm-eventset/return-levels
```

| EventSet (`data/eventsets/…`) | Config (SHA256) | Content hash |
|---|---|---|
| `florida-counties-iris` (S_0, IRIS, index (a), no draws) | `configs/florida_counties_no_draws.yaml` (`750480a2…69f8e60`) | `sha256:07eb5c9a808af45f7d05932b5d78f0cc9b1142f37aef8c9749138dc8c1f379e5` |
| `florida-counties-storm` (S_1, STORM, index (a), no draws) | `configs/florida_counties_storm.yaml` (`2d24aa09…4731884`) | not built |
| `florida-counties-storm-cat-in-circle-50km` (S_1, index (b)) | `configs/florida_counties_storm_cat_in_circle.yaml` (`962516fe…4299cd3`) | not built |

S_0: 13,902 rows (the storms within 500 km of a county, as in MAR-114) × 67 counties; 8,977 rows with zero loss at every county; expected annual loss 7.616 × 10⁹ USD (LitPop reference_year 2018), equal to MAR-114's no-draws scratch figure. Pipeline runtime 487.9 s, wall 494.3 s, peak RSS 1.57 GB.

## Files here

| File | What it is |
|---|---|
| `checksums.json` | Input checksums, config SHA256s, and per build: content hash, file sizes and SHA256s, rows, runtime and peak memory. Also the check that MAR-114's IRIS build reproduces its content hash on this branch |
| `metadata/florida-counties-iris.metadata.json` | The reference EventSet's `metadata.json` |

A rebuilt EventSet must reproduce the content hash; the Parquet file hashes may differ with another pyarrow version.
