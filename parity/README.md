# parity/

Thesis golden data and the parity tests that check the new core reproduces the thesis results (`docs/SPEC.md` §4). The parity report goes in `parity/REPORT.md`.

- Owner: Linear project **Foundation: core rework**. The parity gate is MAR-18; no method change lands before it is signed off.
- The parity source is the thesis code, <https://github.com/marc272/parametric-insurance-framework>. Its `thesis-v1` tag is pending (MAR-7).
- Only small fixtures are committed. Anything larger is fetched by a script with checksums.
- The licence for the code under `parity/` is still open (MAR-79). The fixture data is CC0-1.0, following IRIS (`docs/data-sources.md`).

## Contents

| Path | What it is |
|---|---|
| `tests/data/thesis_eventset/` | The thesis event-loss table as an EventSet (schema v1, `docs/SPEC.md` §5): 6,057 storm rows × 9 Miami assets, `n_years` 10,000, rate 1/10,000 per row, `draw_id` 0. Index: max sustained wind at the asset (m/s). Loss: USD |
| `golden/full_optimization_results.csv.gz` | The thesis optimisation results, the parity targets. Gzipped copy, byte-identical to the thesis file after decompression (the raw CSV is 803 kB, over the repository's 500 kB limit) |
| `golden/benchmarking_kpis.csv.gz` | The thesis KPI table, the parity targets. Gzipped the same way |
| `golden/thesis_cluster_assignments.json` | Thesis cluster assignments (`n_clusters` 1 to 9) and clustering features of the 9 assets, on the thesis' prepared data (noise layer, 20 m/s filter) and without the noise layer. Derived from the thesis code by `scripts/derive_thesis_clusters.py` (MAR-12) |
| `manifest.json` | SHA256 and row/column counts of the thesis sources, the fixture files and the golden tables, plus the thesis commit |
| `scripts/convert_thesis_eventset.py` | Writes all of the above from a thesis checkout |
| `scripts/derive_thesis_clusters.py` | Runs the thesis clustering from a thesis checkout and writes `golden/thesis_cluster_assignments.json` |
| `golden/noise_digests.json` | SHA256 of the noisy loss matrix that the thesis noise layer (`add_noise_to_asset_losses`, seed 42, η = 0.3, 13 copies, heteroscedastic and homoscedastic) returns on the fixture, with the thesis module's checksum (MAR-10) |
| `scripts/thesis_noise_digests.py` | Writes `golden/noise_digests.json` from a thesis checkout. It loads the thesis `src/utils/data_processing.py` on its own (numpy and pandas only), so no thesis dependency is needed |
| `tests/` | Checks the committed files against the manifest and fixed checksums; with a thesis checkout, also recomputes the source checksums and regenerates the fixture |

## The event set

Source: `data/output/climada_transformed_loss_data.csv` in the thesis repository, written by its `src/CLIMADA/engine.py` from the IRIS North Atlantic 10,000-year catalogue.

- One row per IRIS storm whose track passes within 500 km of any asset, in CSV order (the thesis noise layer draws its random numbers in that order). 4,762 of the 6,057 rows have zero wind and zero loss at every asset; they are kept. Years with no such storm are implicit zero-loss years.
- `event_id` is the thesis `Event_ID` (`NA_<year>_<tc>`), `year` the IRIS simulation year (0 to 9,999).
- `index` is the thesis `A<k>_Wind`, `loss` the thesis `A<k>_Loss`, parsed exactly as the thesis notebook parses them (pandas defaults), so they are bit-identical.
- Locations, values (USD) and `impf_TC` come from the thesis `configs/experiment_config.yaml`; `n_years` from `configs/global_settings.yaml`.
- The CSV's `Portfolio_Total_Loss` and `Portfolio_Max_Wind` columns are not kept: they are the row sum and row max of the per-asset columns, and the thesis notebook recomputes them. The script checks both and records the result in `manifest.json` (0 rows differ).
- Source checksums (SHA256). All three are in `manifest.json`; the event-loss CSV (with the two thesis configs) is also in the EventSet's `metadata.json`, under `provenance.source_checksums`:
  - `data/output/climada_transformed_loss_data.csv`: `8513f5fefdcf6686207df575e6a89d576e5ed935f71b652b4045229caf23ff68` (6,057 rows × 22 columns)
  - `src/outputs/optimization_results/full_optimization_results.csv`: `98fe6556ae7b0cc9e5c48e1633ad24860cc8518047617ff2e0bbb18ae114fd31` (1,551 rows × 12 columns)
  - `src/outputs/benchmarking_results/benchmarking_kpis.csv`: `6e2b9d515a3812e35391233926afb4aa118ac797a19ad99d823bd40a3ac669d6` (1,776 rows × 17 columns)

## Regenerate and test

From the repository root:

```bash
# Rewrite the fixture, the golden tables and the manifest from a thesis checkout.
uv run python parity/scripts/convert_thesis_eventset.py \
    --thesis-repo ../parametric-insurance-framework \
    --created-at 2026-10-25T00:00:00+00:00 --overwrite

# Committed files only (no thesis checkout needed).
uv run pytest parity/tests

# Also recompute the source checksums and regenerate the fixture.
PARITY_THESIS_REPO=../parametric-insurance-framework uv run pytest parity/tests
```

To rewrite the noise digests (MAR-10):

```bash
uv run python parity/scripts/thesis_noise_digests.py \
    --thesis-repo ../parametric-insurance-framework --overwrite
```

Without `PARITY_THESIS_REPO`, the thesis-checkout tests are skipped and say why. If it is set but doesn't point at a thesis checkout, they fail.

### In CI

CI runs `uv run --locked pytest parity/tests -v` in its own step, "Test parity", of the `test (workspace, …)` jobs (Python 3.12 and 3.13). `PARITY_THESIS_REPO` is not set there, so:

- the tests on the committed files run; the thesis-checkout tests skip, each with its `PARITY_THESIS_REPO is not set` reason in the log's short test summary;
- the noise layer's exact SHA256 check (`test_noisy_losses_match_thesis_digest`) runs only on the platform that wrote `golden/noise_digests.json` (its `generated_with`: system, machine and numpy version). Elsewhere, such as on the Linux runners, it skips with a reason that names that platform, and only the summary check at rtol 1e-12 (`test_noisy_losses_match_thesis_summary`) runs. The log shows which of the two ran.

pyright (`include`) and ruff cover `parity/` like the packages.

### pandas below 4 for the thesis-checkout tests

With `PARITY_THESIS_REPO` set, the tests run the thesis' `src/utils/data_processing.py`, which calls `DataFrame.drop(..., inplace=True)` and `DataFrame.reset_index(..., inplace=True)`. pandas 3.1 warns about these (`Pandas4Warning`, PDEP-8), and pandas 4 removes the `inplace` keyword, so these tests need pandas below 4. The workspace lock pins pandas 3.1.0. Run them from the locked env (`uv run --locked`), and keep pandas below 4 in `uv.lock` for as long as these tests run the thesis code unchanged (it is read-only here).
