# Cat-in-a-circle radius sensitivity, Florida counties (MAR-133)

Index (b) of the D2 Florida-counties EventSet, the cat-in-a-circle Saffir-Simpson category around each county's value-weighted centroid (MAR-26), at radii 50, 75, 100 and 150 km, on the **base impact function without vulnerability draws** (Emanuel USA, `v_half` 74.7 m/s; the loss of `configs/florida_counties_no_draws.yaml`, MAR-32). Method and observations: `research/notes/cat-in-circle-radius-sensitivity.md`.

**Licence: CC-BY-4.0.** Attribution: asset values from the CLIMADA data API, dataset `LitPop_150arcsec_USA` v3 (CC BY 4.0, Eberenz et al. 2020, doi:10.5194/essd-12-817-2020); county boundaries: U.S. Census Bureau, 2025 TIGER/Line Shapefiles; hazard: IRIS (Sparks and Toumi 2024, doi:10.1038/s41597-024-03250-y).

The configs are in `research/configs/climada/` (moved byte-identical from `packages/climada/configs/` in MAR-185, so the SHA256s below still hold). The EventSets are **not committed**; they are rebuilt into the ignored `data/eventsets/` and the files here are regenerated from them:

```sh
cd packages/climada
for r in 50 75 100 150; do
  pixi run --locked build-eventset --config ../../research/configs/climada/florida_counties_cat_in_circle_${r}km_no_draws.yaml
done
pixi run --locked python scripts/cat_in_circle_radius_sensitivity.py \
    --eventset ../../data/eventsets/florida-counties-iris-cat-in-circle-50km \
    --eventset ../../data/eventsets/florida-counties-iris-cat-in-circle-75km \
    --eventset ../../data/eventsets/florida-counties-iris-cat-in-circle-100km \
    --eventset ../../data/eventsets/florida-counties-iris-cat-in-circle-150km \
    --config ../../research/configs/climada/florida_counties_cat_in_circle_50km_no_draws.yaml \
    --config ../../research/configs/climada/florida_counties_cat_in_circle_75km_no_draws.yaml \
    --config ../../research/configs/climada/florida_counties_cat_in_circle_100km_no_draws.yaml \
    --config ../../research/configs/climada/florida_counties_cat_in_circle_150km_no_draws.yaml \
    --provisional ../../data/eventsets/florida-counties-iris-cat-in-circle-50km-vulnerability \
    --out-dir ../../research/data/cat-in-circle-radius-sensitivity
```

The `--provisional` EventSet is the MAR-132 build of `configs/florida_counties_cat_in_circle.yaml` as it was then (50 km; the config is at 75 km since MAR-145; 10 draws from the 17-event basin-filtered prior, content hash `sha256:c7d6b765…2dfa67f`); it is in the CSVs with `provisional = True` and is not in the figure, because the prior's default is an open question (MAR-118).

| EventSet (`data/eventsets/…`) | Config (`research/configs/climada/…`, SHA256) | Content hash | Index-table hash |
|---|---|---|---|
| `florida-counties-iris-cat-in-circle-50km` | `florida_counties_cat_in_circle_50km_no_draws.yaml` (`374a0e3c78da774a2f67739d53751a43e7d1455765ef0a11fbe15b38ff6d25c1`) | `sha256:81a739dbc5aaa72833d7153f5f771f158059f79613ece437dc1ea2b75a41136a` | `sha256:06d8ef4e36b75e3ced4ff1cb149e09131c45d0968b321b9bf3984a0dcfa40af7` |
| `florida-counties-iris-cat-in-circle-75km` | `florida_counties_cat_in_circle_75km_no_draws.yaml` (`5b2b02a62f6f265bf8f820fa9537b5c8df4a2e10da6f6f4d20f24c684985ac26`) | `sha256:d62faf2ef7a9ba3575da005432be7d8122f3c728e12e34994a331f9b2b531e4c` | `sha256:89d5290cb6d4635b216221e738d9ca6e2c2445e2081a37986150ec0764307a7b` |
| `florida-counties-iris-cat-in-circle-100km` | `florida_counties_cat_in_circle_100km_no_draws.yaml` (`04583a0fffc790fa97b0f786256e67271fc5e21f483c14eadc3e6938ee2bb46b`) | `sha256:31bd914c9a86e680a6193dd4440a7e5e8be2449efab8192cbd8968536cf7fa57` | `sha256:b46334a6ab9a0208b0df1604894f150bacf32fa6be75941afb04d8e8befc1c24` |
| `florida-counties-iris-cat-in-circle-150km` | `florida_counties_cat_in_circle_150km_no_draws.yaml` (`33e55ca8c6a3b9f7bab8acc6a5984498da66918421272eb76fc6c89ef60be2d0`) | `sha256:45843d0e3ac788599f3677983cc0872aeff3e109767f649ab3a73a521afcd74b` | `sha256:5d07310a836895763eada78c9662016898aa99385f2ccafc26537869066e8200` |

All four: 13,902 rows (one per storm within 500 km, no draws) × 67 counties, and the same loss matrix (hash `sha256:a417c756df582e02456254bfd65de210f303a66e0d1e72cee0b6ac2fab2a4873`, EAL 7,615,672,695 USD, equal to the MAR-32 no-draws build's). The index-table hash is SHA-256 over `"<rows>x<cols>\n"` and the index matrix as C-order little-endian float64 bytes (`matrix_hash` in the script); it identifies the index independently of the loss and the metadata.

## Files here

| File | What it is |
|---|---|
| `summary.csv` | One row per EventSet: hashes, EAL, pair share and loss share by category 0-5, storms reaching category ≥ 1 at some county, basis risk (portfolio per event, per year, two-fold; county min / median / max / EAL-weighted), trigger frequency per county (min / median / max) |
| `counties.csv` | One row per EventSet and county: EAL, category-0 loss share, basis risk (in-sample and two-fold), events a year with category ≥ 1, and events a year in each category |
| `radius_sensitivity.png` | The figure: (a) loss share by category, (b) basis risk, (c) trigger frequency |
| `checksums.json` | Per EventSet: content, index-table and loss-matrix hashes and config SHA256; SHA256 of the three files above |

Build time (four builds in parallel, `/usr/bin/time -l`, load average about 15 on 10 cores): 1,236–1,249 s wall each, peak RSS 0.83–0.91 GB.
