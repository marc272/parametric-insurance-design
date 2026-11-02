# D2 Florida-counties EventSets (MAR-114)

The paper's main EventSets (D2, SPEC §6.6): the CLIMADA adapter on Florida's 67 counties from MAR-113 (`../d2-florida-litpop/`), IRIS North Atlantic 10,000 years, 10 vulnerability draws per storm. The draws are Emanuel `v_half` values from Eberenz et al. (2021), NA2, the 17 wind-only North Atlantic events (MAR-103, MAR-132), recentred so that the expected annual loss equals that of the same config without draws (MAR-160, MAR-118 Q5). Index (b) is the cat-in-a-circle at **75 km** (MAR-145, MAR-118 Q6). A county's loss is the sum of the impacts on its LitPop cells. Method, measurements and observations: `research/notes/d2-florida-eventset.md`.

**Licence: CC-BY-4.0.** Attribution on every output: asset values from the CLIMADA data API, dataset `LitPop_150arcsec_USA` v3 (CC BY 4.0, Eberenz et al. 2020, doi:10.5194/essd-12-817-2020; archive doi:10.3929/ethz-b-000331316); county boundaries: U.S. Census Bureau, 2025 TIGER/Line Shapefiles; hazard: IRIS (Sparks and Toumi 2024, doi:10.1038/s41597-024-03250-y; collection doi:10.6084/m9.figshare.c.6724251.v1); the `v_half` prior: Eberenz, Lüthi and Bresch (2021), doi:10.5194/nhess-21-393-2021, as shipped with CLIMADA 6.1.0.

The EventSets themselves (10.8 MB and 8.9 MB) are **not committed**; they are rebuilt into the git-ignored `data/eventsets/`:

```sh
cd packages/climada
pixi run --locked iris                 # once: IRIS catalogue (MAR-72)
pixi run --locked florida-locations    # once: locations.yaml, cells.parquet (MAR-113)
pixi run --locked build-eventset --config configs/florida_counties.yaml
pixi run --locked build-eventset --config configs/florida_counties_cat_in_circle.yaml
```

Each build first builds its base without draws, then the draws. Run the two `pixi run` commands one after the other, or start them a minute apart: two `pixi run` processes that start together can race while pixi checks the environment.

| EventSet (`data/eventsets/…`) | Config | Index | Content hash | Built in |
|---|---|---|---|---|
| `florida-counties-iris-vulnerability` | `configs/florida_counties.yaml` (SHA256 `67ab5617…e5f547da`) | (a) wind at the value-weighted centroid, m/s | `sha256:30b1723182e5bb3eef8abae0d0edcc605918aaf90e03b24bb09037a4c6416472` | MAR-160 |
| `florida-counties-iris-cat-in-circle-75km-vulnerability` | `configs/florida_counties_cat_in_circle.yaml` (SHA256 `fd8ab002…7da7e4de`) | (b) cat-in-a-circle, 75 km, Saffir-Simpson category 0-5 | `sha256:70af1fed283d9e800574c01181ff4e3ee40dee7ab227a890145d7744e8328a60` | MAR-145 |

Both: 139,020 rows (13,902 storms × 10 draws) × 67 counties, 9,314,340 `values` rows. The loss matrices are identical (same rows, seed and per-cell draws; checked with `np.array_equal`), so both builds matched the same factor, `s` = 0.690130 (median `v_half` 86.293 m/s). The base of each match (`recentre.match.base_content_hash`) is the same config without draws, built in memory and not written: `sha256:373e11a6…672e690a` (a) and `sha256:d62faf2e…2b531e4c` (b). The latter equals the content hash of MAR-133's `research/configs/climada/florida_counties_cat_in_circle_75km_no_draws.yaml` build, so that config rebuilds the no-draws counterpart of (b) on disk.

**A step payout on the category index (MAR-170; mode decided 2026-11-01).** Use integer category breakpoints with attachment 1 and `below_attachment: zero`, e.g. the experiment config's `payout: {kind: step, attachment: 1, limit: 6, n_bins: 5, below_attachment: zero}`: one bin per category 1 to 5, with category 5 in `[5, 6)`, and nothing paid on category 0. The owner decided `zero` for the D2 Florida configs and every new experiment config (MAR-170); the core's default stays `first_bin`, so the D2 run configs set it explicitly. Why: with attachment 0, bin 0 is the category-0 bin, and category-0 pairs carry 17.1 % of the loss at 75 km (`research/notes/d2-florida-eventset.md`; 37.5 % at 50 km), so the optimiser pays on category 0. Under `first_bin` (the thesis code), that level is paid on every storm that the adapter's 500 km `proximity_km` filter kept and on none of the others, so the design and its premium depend on the filter (design review MAR-161, finding F1). No attachment avoids this under `first_bin`: with attachment 1, category 0 is clipped into the category-1 bin. Under `zero`, the storms the filter dropped change nothing.

## Files here

| File | What it is |
|---|---|
| `checksums.json` | Input checksums; per build: content hash, config file SHA256, file sizes and SHA256s, row counts, EAL, the recentring record (factor, median, target EAL, matched EAL, tolerance, bracket, base content hash), the code commit, runtime (with the base pass and the match) and peak memory. Index (a)'s build record is MAR-160's, copied from `../f12-recentred-prior/checksums.json` |
| `summary.json` | The loss and tail numbers of the 75 km index (b) build against the no-draws base, its category shares, and the cross-checks: loss matrix equal to (a) and to the 50 km build; index of each draw equal to MAR-133's 75 km no-draws index table |
| `metadata/*.metadata.json` | Each EventSet's `metadata.json` (provenance, build record, draws record with `prior.recentre`, value unit, attribution) |
| `exposure-summary/exposure_summary.png` | The exposure summary figure (map, Monroe County cells, value distribution, tail dependence) |
| `exposure-summary/*.csv`, `summary.json` | Its figure data, from `packages/climada/scripts/florida_exposure_summary.py` on the index (a) EventSet (`sha256:30b17231…c6416472`); the loss matrix of (b) is the same, so the figure holds for both |

A rebuilt EventSet must reproduce the content hash; the Parquet file hashes may differ with another pyarrow version.

## History

- **MAR-132 rebuild (2026-10-27).** Both EventSets were rebuilt with the basin filter of the `v_half` prior (`basins: [NA]`, the default together with `wind_only: true`: 17 NA2 events instead of 19) and with Monroe County's LitPop gap stated in the scenario notes. Content hashes `sha256:cad39887…46a6cbe6` (a) and `sha256:c7d6b765…2dfa67f` (b, 50 km). The MAR-114 content hashes were `sha256:d8698f7d…a3385131` (a) and `sha256:81acd810…b07a2d3e` (b, 50 km).
- **MAR-160 rebuild (2026-11-01).** Both EventSets were rebuilt with the prior recentred (`recentre: {kind: excess, match: expected_loss}`): content hashes `sha256:30b17231…c6416472` (a, current) and `sha256:4d578aef…5a26a70f` (b, 50 km, superseded). Their records are in `../f12-recentred-prior/`. Since MAR-145 the 50 km build is rebuilt from the config as it was at commit `cecc667` (SHA256 `a9c030c3…cca4ae01`; `git show cecc667:packages/climada/configs/florida_counties_cat_in_circle.yaml`, saved next to the current configs, since its paths are relative to the file).
- **MAR-145 (2026-11-01).** Index (b) was rebuilt at 75 km, the owner's answer to MAR-118 Q6 from MAR-133's radius sensitivity (`../cat-in-circle-radius-sensitivity/`); its output directory changed with the radius. Index (a)'s config did not change, so its MAR-160 build stays current and was not rebuilt. `checksums.json`, `metadata/` and `exposure-summary/` now describe the current pair; until MAR-145 they were MAR-132's.

Measurements: `research/notes/d2-florida-eventset.md`.
