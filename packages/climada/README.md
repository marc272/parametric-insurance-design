# parametric-insurance-design-climada

Adapter from CLIMADA to the EventSet of [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design): tracks → CLIMADA hazard and impact → EventSet.

```python
from parametric_insurance_design_climada.config import load_config
from parametric_insurance_design_climada.pipeline import build_eventset

result = build_eventset(load_config("configs/thesis.yaml"))
result.eventset.to_parquet("data/eventsets/thesis-iris")
```

Status: the IRIS download (MAR-72) and the track → wind → impact pipeline (MAR-73) are in. Parity with the thesis event-loss table is verified under MAR-20. The cat-in-a-circle index (MAR-26) and the vulnerability draws (MAR-25) are in.

## Environment

This package is **not a member of the uv workspace**. CLIMADA comes from conda-forge, and its pins would clash with the CRC adapter's pandas ≥ 3 requirement, so this package has its own **pixi** environment (`docs/SPEC.md` §4.1):

- `pixi.toml` and the committed `pixi.lock` in this folder define it: CLIMADA 6.1.0 on Python 3.12 from conda-forge, the core installed editable from `../core`, and this package installed editable from `.`.
- The core's dependencies come from conda-forge too, so no PyPI wheel shadows the conda numpy/scipy stack.
- Locked platforms: `linux-64` (CI) and `osx-arm64`. Add one with `pixi workspace platform add <platform>`.

From this folder:

```sh
pixi run test             # this package's tests
pixi run test-core        # the core's tests, in this env
pixi run typecheck        # pyright (basic) on src/ and tests/, in this env
pixi run iris             # download and merge the IRIS North Atlantic catalogue (below)
pixi run build-eventset --config configs/thesis.yaml   # build an EventSet (below)
pixi lock                 # after changing pixi.toml, pyproject.toml or the core's dependencies; commit pixi.lock
```

CI runs the test tasks and `typecheck` in the workflow `.github/workflows/climada.yml` with `pixi install --locked`, so it fails when `pixi.lock` is out of date, including after a change to the core's dependencies. The root pyright (`ci.yml`) skips this package, because CLIMADA is only in this env; `pyrightconfig.json` here configures the in-env run. ruff (lint and format) runs from the root, as for every package.

## IRIS data

`pixi run iris` (module `parametric_insurance_design_climada.iris`, MAR-72) gets the IRIS event set (Sparks and Toumi, 2024) from figshare and builds the 10,000-year North Atlantic catalogue the thesis used:

1. downloads `IRIS_event_set.zip` (about 260 MB) and its README, checking size, MD5 and SHA256;
2. extracts the ten files `IRIS_NA_1000Y_n0.txt` … `n9.txt`, checking each SHA256;
3. merges them into `IRIS_NA_10000Y_merged.txt` (SHA256 `7f7b224d…606bd`, byte-identical to the thesis file).

Everything is written to the **git-ignored `data/iris/` at the repository root** (`raw/` for the download and the extracted files, `transformed/` for the merged catalogue). Re-running skips files that are already present and verified; a file that does not match is never overwritten. If you already have the zip, pass it instead of downloading:

```sh
pixi run iris --archive /path/to/IRIS_event_set.zip
```

The pinned URLs, DOIs, version, citation and checksums are in `src/parametric_insurance_design_climada/iris_manifest.json`; the pipeline reads the release and the merged checksum from it. The IRIS licence record conflicts (CC0 on the figshare items, CC BY 4.0 on the collection record); the owner decides under MAR-94, and the EventSet's `licence` is written as the parity fixture does (`CC0-1.0`) until then. See `docs/data-sources.md`.

**No Parquet copy of the catalogue.** pandas parses the 103 MB merged text file in about half a second, and the build itself takes about 30 s, so a typed Parquet copy would add a second artefact to keep in sync for no measurable gain. The reader checks the layout and types instead (`tracks.read_iris_catalogue`).

## Florida county locations (LitPop, D2)

`pixi run florida-locations` (module `parametric_insurance_design_climada.portfolio_litpop`, MAR-113) builds the paper portfolio's `locations` table (D2, SPEC §6.6): Florida's 67 counties, each valued by the sum of its cells in the pinned CLIMADA data-API file `LitPop_150arcsec_USA` v3 and placed at the cells' value-weighted centroid.

1. downloads the LitPop file (51 MB) and the U.S. Census Bureau TIGER/Line 2025 county boundaries (84 MB), checking size, MD5 and SHA256 against `src/parametric_insurance_design_climada/litpop_florida_manifest.json`;
2. assigns every LitPop cell in the region (Florida's bounding box plus 0.5°) to the county polygon it intersects, using the national county file, so that cells across the state line count as "in another county";
3. writes `locations.yaml` (the layout `locations: {yaml: ...}` reads), `cells.parquet` (every region cell with its county, for a per-cell loss) and `provenance.json` (sources, checksums, method, counts) to the git-ignored `data/litpop-florida/locations/`. `--overwrite` rebuilds; `--download-only` only fetches and verifies.

No cell is dropped silently: the report counts cells in a Florida county, in another county, in no county and outside the region, with their values. A county without cells raises `EmptyUnitError`; one whose cells are all zero-valued raises `ZeroValueUnitError`. A copy of the 67-county table (13 KB, CC BY 4.0) and its provenance is committed in `research/data/d2-florida-litpop/`; the measured numbers are in `research/notes/d2-florida-litpop-locations.md`. If the LitPop file is ever withdrawn upstream, do not regenerate it: that needs a NASA login, which only the owner may use.

`scripts/estimate_florida_grid.py` counts the IRIS storms within the pipeline's radius of a set of locations, to size the dense events × locations grid before a build.

## Building an EventSet

`pixi run build-eventset --config <file>` (module `parametric_insurance_design_climada.cli`) runs the port of the thesis `src/CLIMADA/engine.py` (`pipeline.build_eventset`):

1. reads the locations (an EventSet's `locations` table or a YAML list) and the IRIS catalogue;
2. keeps the storms whose track passes within `proximity_km` (500) of any location, ordered by event ID as strings, as in the thesis;
3. in batches of `batch_size` storms, converts each storm to a CLIMADA track (m/s → knots, km → nautical miles, `r18` as `radius_oci`, 3 h steps, 1013 hPa environment), runs `TropCyclone.from_tracks` at one centroid per location and `ImpactCalc` with the impact function (Emanuel 2011 USA by default);
4. writes the EventSet (schema v1): `index` = wind at the asset (m/s), `loss` = impact (USD), `rate` = 1 / `n_years`, `year` from IRIS, `draw_id` 0.

`configs/thesis.yaml` is the thesis portfolio (the nine Miami assets, from the parity fixture's `locations`). Paths in a config are relative to the config file; `--catalogue` and `--output` override them, `--overwrite` replaces an existing EventSet. The output goes to the git-ignored `data/eventsets/`.

Provenance in the EventSet's `metadata.json`: `hazard.release` and the catalogue's SHA256 come from the IRIS manifest; the first `transforms` record (`climada_tc_impact`) holds the CLIMADA version, the catalogue checksum and counts, the radius, any storm skipped for having fewer than two track points (the thesis skipped them silently), the unit conversions, the wind parameters and the impact function with its intensity–damage table. `batch_size` is not recorded: it does not change the data.

Deliberate differences from the thesis script: storms that cannot be modelled are listed rather than dropped silently; locations keep their given order (the thesis sorted by asset ID, the same order for `A1`–`A9`); each location gets its own centroid explicitly; and the distance-to-coast cut-off is off by default (`wind.max_dist_inland_km: null`), because CLIMADA's default would download a 300 MB raster outside the checksummed downloads. For coastal assets such as the thesis portfolio both settings give the same wind.

**Extension points** (`hooks.py`): `build_eventset(config, index_builder=..., vulnerability=..., rng=...)`.

- `IndexBuilder`: turns a `HazardBatch` (tracks, hazard, locations, exposures, wind) into the index matrix. Default `CentroidWindIndex` (the thesis index). `CatInCircleIndex` is the cat-in-a-circle builder (see "Index builders" below). The config's `index` section selects the builder; a builder passed to `build_eventset` replaces it.
- `VulnerabilityDraws`: turns a batch and its base losses into `n_draws` loss matrices. Default `NoDraws`. `vulnerability.EmanuelVHalfDraws` (MAR-25) is the impact-function draws hook (see "Vulnerability draws" below). The config's `vulnerability` section selects it; a hook passed to `build_eventset` replaces the config's. With draws, the pipeline repeats each event's row per draw (event-major), gives each draw `rate / n_draws` (SPEC §5) and appends the hook's `TransformRecord`.

## Index builders

The config's `index` section chooses what goes into the EventSet's `index` column (SPEC §6.3). The loss column doesn't depend on it.

| `kind` | Builder | Index | Unit |
|---|---|---|---|
| `centroid_wind` (default) | `hooks.CentroidWindIndex` | (a) The thesis index: CLIMADA's modelled maximum 1-minute sustained wind at the asset | m/s |
| `cat_in_circle` | `cat_in_circle.CatInCircleIndex` (MAR-26) | (b) Cat-in-a-circle: the highest Saffir–Simpson category the storm's **track** reaches within `radius_km` of the asset | Saffir-Simpson category (0–5), or m/s with `metric: max_wind` |

Without an `index` section the build is unchanged from MAR-73. On the thesis portfolio its `index` and `loss` are bit-identical to the parity fixture.

```yaml
index:
  kind: cat_in_circle
  radius_km: 50                          # required; at most proximity_km / 2
  metric: category                       # or max_wind (m/s)
  breakpoints_kn: [64, 83, 96, 113, 137] # default: NHC Saffir-Simpson, categories 1-5
  track_step_hours: 0.5                  # default; null uses the raw 3-hourly points
```

`configs/thesis_cat_in_circle.yaml` is the thesis build with this index at 50 km.

How cat-in-a-circle is computed, for each storm and asset:

1. Take the storm's track points: centre position and maximum sustained wind.
2. Interpolate the track linearly in time to `track_step_hours`; the original points are kept. IRIS points are 3 hours apart, and a fast storm moves 50 km or more in that time, so without interpolation a small circle can miss a storm that crosses it.
3. Keep the points within `radius_km` of the asset, by the haversine distance of the proximity filter (sphere of 6,371 km, inclusive).
4. Take the highest wind among those points, or 0 if there are none.
5. With `metric: category`, report the number of breakpoints that wind reaches. Category 0 covers tropical storms, depressions and storms that never enter the circle. With `metric: max_wind`, report the wind itself, in m/s.

The index doesn't use CLIMADA's wind field, so it is decoupled from the loss driver (thesis issue M2).

**Wind and breakpoints.** IRIS `vmax` is a 1-minute sustained wind in m/s: IRIS is calibrated on the US agencies' IBTrACS data, which report 1-minute averages (Sparks and Toumi 2024, doi:10.1038/s41597-024-03250-y). The Saffir–Simpson scale is defined on the same 1-minute wind, in knots, so no averaging-period conversion is applied. The defaults are the NHC lower bounds of categories 1–5 (<https://www.nhc.noaa.gov/aboutsshws.php>), equal to CLIMADA's `SAFFIR_SIM_CAT[1:6]`. The tracks carry the wind in knots (m/s × 1.9438…), and the breakpoints are compared in knots.

**Radius limit.** The proximity filter only tests raw track points, so the config requires `radius_km <= proximity_km / 2`. This guarantees that no storm the filter removed could have a non-zero index after interpolation. The argument is in `config.check_circle_radius`.

**Provenance.** `metadata.index.definition` starts with `cat_in_circle(r=<radius> km, metric=<metric>)` and then states the breakpoints, the wind, the distance and the interpolation. The build record's `parameters.index` holds the same settings as data: radius, metric, breakpoints and their source, track step, distance and wind.

**Reference configuration.** Steinmann et al. (2023) build cat-in-a-circle products in CLIMADA, with radii of 10–50 km and step payouts on Saffir–Simpson categories. The index is industry practice, not a novelty claim (`research/lit/notes.md`, O3). The core needs no change for it: a step payout runs on the precomputed index through `PointIndex` (ADR 0002). With `metric: category`, `StepPayout(attachment=0, limit=6, n_bins=6, breakpoints=(0, 1, 2, 3, 4, 5, 6))` puts each category in its own bin. Category 0 then gets its own bin, so the optimiser can leave it unpaid. The core's step payout clips index values below the attachment into the first bin.

Index (c) of SPEC §6.3 (wind at the nearest grid node or at a reference point at distance d) is not implemented.

## Vulnerability draws

The config's `vulnerability` section makes the loss uncertain (SPEC §6.3, MAR-25). Each storm gets `n_draws` rows (`draw_id` 0 … n − 1), each with its loss recomputed using an Emanuel `v_half` drawn from a prior. The index is the same on every draw. The method, the prior's sources, the runtime and observations on the thesis portfolio are in [`docs/methodology/vulnerability.md`](../../docs/methodology/vulnerability.md).

Without a `vulnerability` section, or with `kind: none`, the build is unchanged: one row per storm, `draw_id` 0, the same content hash as before.

```yaml
vulnerability:
  kind: emanuel_v_half
  n_draws: 10              # default 10
  seed: 20261025           # required: numpy.random.default_rng(seed)
  prior:
    kind: eberenz2021_edr  # default: event-wise calibrated v_half, Eberenz et al. (2021)
    region: NA2            # default: USA and Canada (43 events)
    wind_only: false       # true drops events with surge/rain/flood/slide/other damage
  # or: prior: {kind: uniform, low: 60, high: 110, source: "..."}
```

The hook works as follows:

- **One `v_half` per storm and draw**, shared by all locations of the storm. Storms and draws are independent.
- **`v_thresh` and `scale` stay fixed**, at the values in `impact_function`. The Eberenz prior requires 25.7 m/s and 1, the values its calibration held fixed.
- **The default prior is CLIMADA's own data:** a draw at `u ~ U(0, 1)` equals `ImpfSetTropCyclone.calibrated_regional_vhalf("EDR", q=u)["NA2"]`, read from `climada/data/system/tc_impf_cal_v01_EDR.csv`. That file's SHA256 is pinned.
- **The loss is computed as `ImpactCalc` does:** on the base function's intensity grid with linear interpolation, `value · paa · mdd`. With the base `v_half` it reproduces the pipeline's loss.
- **The draws don't depend on `batch_size`.** The generator is consumed event-major.
- **A second transform record, `vulnerability_draws`, describes the draws:** the prior (source, DOI, data file and checksum, every value), `n_draws`, the sampling rule and the seed. The seed is `null` when the caller passes its own `rng` to `build_eventset`.

Example configs:

- `configs/thesis_vulnerability.yaml`: the thesis index (wind at the asset) with 10 draws;
- `configs/thesis_cat_in_circle_vulnerability.yaml`: cat-in-a-circle at 50 km with 10 draws, i.e. SPEC §6.3's index (b) plus vulnerability uncertainty.

`scripts/plot_vulnerability_spread.py` draws the loss spread per asset from the centroid-wind build: `docs/methodology/figures/vulnerability_loss_spread.png`.

## Rules

- It never imports `parametric_insurance_design_crc`, and the env does not contain it: the CLIMADA stream is CRC-free. A smoke test checks this.
- Licence: GPL-3.0-or-later, because it imports GPLv3 CLIMADA (ADR 0001). See `LICENSE` in this folder.
- No data in git: IRIS and every built EventSet live under the git-ignored `data/`. CI builds a tiny synthetic catalogue in the tests and never downloads.
