# F-12: the draws EventSets with the recentred `v_half` prior (MAR-160)

The Florida (D2) and thesis-portfolio draws EventSets rebuilt with `vulnerability.prior.recentre: median` (MAR-118 Q5 = b): the 17 wind-only North Atlantic NA2 values of Eberenz et al. (2021) rescaled by 74.7 / 113.5, so that their median is the base function's `v_half` of 74.7 m/s. Method: `docs/methodology/vulnerability.md`. Measurements and observations: `research/notes/d2-florida-eventset.md` (Florida) and the methodology page (thesis portfolio).

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

A rebuild must reproduce the content hashes in `checksums.json`. The Parquet file hashes may differ with another pyarrow version.

## Files here

| File | What it is |
|---|---|
| `checksums.json` | Input checksums; per build: content hash, config file SHA256, file sizes and SHA256s, row counts, EAL, the recentring (factor, target, calibrated median), runtime and peak memory |
| `summary.json` | The loss and tail numbers of each portfolio against its no-draws base, and the offline evaluation of other recentrings (see below) |
| `metadata/*.metadata.json` | Each EventSet's `metadata.json` (provenance, build record, draws record with `prior.recentre`) |

## How `summary.json` was computed

- **Loss and tail numbers** come from the EventSets. They follow the MAR-132 conventions:
  - the EAL is rate-weighted over all rows (each draw row carries `rate / 10`);
  - annual losses are per (year, `draw_id`) outcome, 10,000 years × 10 draws = 100,000 outcomes, zero years included;
  - quantiles are numpy's linear ones;
  - tail dependence is `P(A_i > q_i, A_j > q_j) / 0.01` on annual location losses, with q = 0.99.

  The bases are the no-draws EventSets: `configs/florida_counties_no_draws.yaml` (MAR-32, `sha256:07eb5c9a…f1c379e5`, rebuilt in a scratch run with the same hash) and `configs/thesis.yaml` (`sha256:7b0cf281…8b0bb`).
- **Other recentrings** (the `variants` objects) were evaluated offline, not built. The evaluation used:
  - the same storms and cells, with the cell winds captured from the scratch no-draws build;
  - the same generator stream (`rng.random((n_events, 10))` with the config's seed);
  - the same tabulated Emanuel function (0–120 m/s in 5 m/s steps, interpolated linearly).

  For the implemented multiplicative recentring, it reproduces the builds' EAL to within 1e-12 (relative). The `EAL-matched` rows are the median that gives an EAL equal to the base, found by root search to ±0.05 m/s. They depend on the portfolio and the hazard.
