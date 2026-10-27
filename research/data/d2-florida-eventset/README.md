# D2 Florida-counties EventSets (MAR-114)

The paper's main EventSets (D2, SPEC §6.6): the CLIMADA adapter on Florida's 67 counties from MAR-113 (`../d2-florida-litpop/`), IRIS North Atlantic 10,000 years, 10 vulnerability draws per storm (Emanuel `v_half` from Eberenz et al. 2021, NA2, wind-only events). A county's loss is the sum of the impacts on its LitPop cells. Method, measurements and observations: `research/notes/d2-florida-eventset.md`.

**Licence: CC-BY-4.0.** Attribution on every output: asset values from the CLIMADA data API, dataset `LitPop_150arcsec_USA` v3 (CC BY 4.0, Eberenz et al. 2020, doi:10.5194/essd-12-817-2020; archive doi:10.3929/ethz-b-000331316); county boundaries: U.S. Census Bureau, 2025 TIGER/Line Shapefiles; hazard: IRIS (Sparks and Toumi 2024, doi:10.1038/s41597-024-03250-y; collection doi:10.6084/m9.figshare.c.6724251.v1).

The EventSets themselves (10.8 MB and 8.4 MB) are **not committed**; they are rebuilt into the git-ignored `data/eventsets/`:

```sh
cd packages/climada
pixi run --locked iris                 # once: IRIS catalogue (MAR-72)
pixi run --locked florida-locations    # once: locations.yaml, cells.parquet (MAR-113)
pixi run --locked build-eventset --config configs/florida_counties.yaml
pixi run --locked build-eventset --config configs/florida_counties_cat_in_circle.yaml
```

| EventSet (`data/eventsets/…`) | Config | Index | Content hash |
|---|---|---|---|
| `florida-counties-iris-vulnerability` | `configs/florida_counties.yaml` (SHA256 `eb8126a8…44a13a9`) | (a) wind at the value-weighted centroid, m/s | `sha256:d8698f7d2985409f5a5024101d7ba839d42a127a29d5456e5871ecaaa3385131` |
| `florida-counties-iris-cat-in-circle-50km-vulnerability` | `configs/florida_counties_cat_in_circle.yaml` (SHA256 `ed874270…9296a84`) | (b) cat-in-a-circle, 50 km, Saffir-Simpson category 0-5 | `sha256:81acd810655dc42edc3eb327f2ad6d4de3a666993c29fdfa80b48ee8b07a2d3e` |

Both: 139,020 rows (13,902 storms × 10 draws) × 67 counties, 9,314,340 `values` rows; the loss matrices are identical (same rows, seed and per-cell draws). With a step payout on the category index, use attachment 0 and integer category breakpoints.

## Files here

| File | What it is |
|---|---|
| `checksums.json` | Input checksums; per build: content hash, config file SHA256, file sizes and SHA256s, row counts, runtime and peak memory |
| `metadata/*.metadata.json` | Each EventSet's `metadata.json` (provenance, build record, draws record, value unit, attribution) |
| `exposure-summary/exposure_summary.png` | The exposure summary figure (map, Monroe County cells, value distribution, tail dependence) |
| `exposure-summary/*.csv`, `summary.json` | Its figure data, from `packages/climada/scripts/florida_exposure_summary.py` on the index (a) EventSet |

A rebuilt EventSet must reproduce the content hash; the Parquet file hashes may differ with another pyarrow version.
