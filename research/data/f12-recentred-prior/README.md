# F-12: the draws EventSets with the recentred `v_half` prior (MAR-160)

The Florida (D2) and thesis-portfolio draws EventSets rebuilt with `vulnerability.prior.recentre: {kind: excess, match: expected_loss}` (MAR-118 Q5 = b, in the form decided on 2026-11-01). The prior is the 17 wind-only North Atlantic NA2 values `v_half_i` of Eberenz et al. (2021), drawn as `v_thresh + s · (v_half_i − v_thresh)`. Each build solves the factor `s` so that the expected annual loss of the draws equals that of the same config built without draws: `s` = 0.6901 on Florida (median `v_half` 86.29 m/s) and 0.6737 on the thesis portfolio (84.85 m/s). Method: `docs/methodology/vulnerability.md`. Measurements and observations: `research/notes/d2-florida-eventset.md` (Florida) and the methodology page (thesis portfolio).

These files replace those of the first MAR-160 build (PR #100 at `ccb92ee`, the multiplicative median recentring), whose hashes are superseded.

**Licence: CC-BY-4.0.** Attribution on every output: asset values from the CLIMADA data API, dataset `LitPop_150arcsec_USA` v3 (CC BY 4.0, Eberenz et al. 2020, doi:10.5194/essd-12-817-2020; archive doi:10.3929/ethz-b-000331316); county boundaries: U.S. Census Bureau, 2025 TIGER/Line Shapefiles; hazard: IRIS (Sparks and Toumi 2024, doi:10.1038/s41597-024-03250-y; collection doi:10.6084/m9.figshare.c.6724251.v1); the `v_half` prior: Eberenz, Lüthi and Bresch (2021), doi:10.5194/nhess-21-393-2021, as shipped with CLIMADA 6.1.0.

The EventSets are **not committed**. Rebuild them into the git-ignored `data/eventsets/`:

```sh
cd packages/climada
pixi run --locked iris                 # once: IRIS catalogue (MAR-72)
pixi run --locked florida-locations    # once: locations.yaml, cells.parquet (MAR-113)
pixi run --locked build-eventset --config configs/florida_counties.yaml
pixi run --locked build-eventset --config configs/florida_counties_cat_in_circle.yaml
pixi run --locked build-eventset --config configs/thesis_vulnerability.yaml
pixi run --locked build-eventset --config configs/thesis_cat_in_circle_vulnerability.yaml
```

The Florida index (b) build here is at 50 km. Since MAR-145, `configs/florida_counties_cat_in_circle.yaml` is at 75 km and builds a different EventSet (`research/data/d2-florida-eventset/`). To rebuild the 50 km one, use the config as of `cecc667` (SHA256 `a9c030c3…8acca4ae01`, as in `checksums.json`), written next to the current one so that its relative paths resolve: `git show cecc667:packages/climada/configs/florida_counties_cat_in_circle.yaml > configs/florida_counties_cat_in_circle_cecc667.yaml`, then build that file, and delete it afterwards.

Each build first builds its base without draws, then the draws. A rebuild must reproduce the content hashes in `checksums.json`. The Parquet file hashes may differ with another pyarrow version. Run the `pixi run` commands one after the other, or start them a minute apart: two `pixi run` processes that start together can race while pixi checks the environment.

## Files here

| File | What it is |
|---|---|
| `checksums.json` | Input checksums; per build: content hash, config file SHA256, file sizes and SHA256s, row counts, EAL, the recentring record (factor, median, target EAL, matched EAL, tolerance, bracket, base content hash), the code commit, runtime (with the base pass and the match) and peak memory |
| `summary.json` | The loss and tail numbers of each portfolio against its no-draws base, the base hashes, the default-off hash check, and the offline evaluation of the other recentrings that preceded the decision |
| `metadata/*.metadata.json` | Each EventSet's `metadata.json` (provenance, build record, draws record with `prior.recentre`) |

## How `summary.json` was computed

- **Loss and tail numbers** come from the EventSets. They follow the MAR-132 conventions:
  - the EAL is `rates @ loss` summed over the locations, over all rows (each draw row carries `rate / 10`);
  - annual losses are per (year, `draw_id`) outcome, 10,000 years × 10 draws = 100,000 outcomes, zero years included;
  - quantiles are numpy's linear ones;
  - tail dependence is `P(A_i > q_i, A_j > q_j) / 0.01` on annual location losses, with q = 0.99.
- **The bases.**
  - Thesis: `configs/thesis.yaml` and `configs/thesis_cat_in_circle.yaml`, built on 2026-11-01. Their content hashes equal `recentre.match.base_content_hash` in the two draws builds.
  - Florida: the loss matrix and the years of `configs/florida_counties_no_draws.yaml` (MAR-32, `sha256:07eb5c9a…f1c379e5`), captured in a scratch run during the first MAR-160 build. Its EAL equals the match's target exactly. The match's base is `configs/florida_counties.yaml` without draws, which has the same loss matrix; its content hash differs because its scenario text carries the Monroe County note.
- **Other recentrings** (the `variants` objects) were evaluated offline before the decision, not built. The evaluation used:
  - the same storms and cells, with the cell winds captured from the scratch no-draws build;
  - the same generator stream (`rng.random((n_events, 10))` with the config's seed);
  - the same tabulated Emanuel function (0–120 m/s in 5 m/s steps, interpolated linearly).

  Its `EAL-matched` rows came from a root search to ±0.05 m/s. The implemented option is the excess form, EAL-matched; the builds now solve its factor to a relative tolerance of 1e-6, and their factors agree with the offline medians (Florida 86.29 m/s, thesis 84.85 m/s).
