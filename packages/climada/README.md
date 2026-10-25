# parametric-insurance-design-climada

Adapter from CLIMADA to the EventSet of [parametric-insurance-design](https://github.com/marc272/parametric-insurance-design): tracks → CLIMADA hazard and impact → EventSet.

```python
from parametric_insurance_design_climada.config import load_config
from parametric_insurance_design_climada.pipeline import build_eventset

result = build_eventset(load_config("configs/thesis.yaml"))
result.eventset.to_parquet("data/eventsets/thesis-iris")
```

Status: the IRIS download (MAR-72) and the track → wind → impact pipeline (MAR-73) are in. Parity with the thesis event-loss table is verified under MAR-20; vulnerability draws (MAR-25) and cat-in-a-circle (MAR-26) plug into the pipeline's extension points.

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

- `IndexBuilder`: turns a `HazardBatch` (tracks, hazard, locations, exposures, wind) into the index matrix. Default `CentroidWindIndex` (the thesis index). Cat-in-a-circle (MAR-26) is a second builder.
- `VulnerabilityDraws`: turns a batch and its base losses into `n_draws` loss matrices. Default `NoDraws`. With draws (MAR-25), the pipeline repeats each event's row per draw (event-major), gives each draw `rate / n_draws` (SPEC §5) and appends the hook's `TransformRecord`.

## Rules

- It never imports `parametric_insurance_design_crc`, and the env does not contain it: the CLIMADA stream is CRC-free. A smoke test checks this.
- Licence: GPL-3.0-or-later, because it imports GPLv3 CLIMADA (ADR 0001). See `LICENSE` in this folder.
- No data in git: IRIS and every built EventSet live under the git-ignored `data/`. CI builds a tiny synthetic catalogue in the tests and never downloads.
