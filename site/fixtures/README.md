# site/fixtures/

Small committed site bundles: **test fixtures** of the site bundle export, so it can be tested on thesis data without a result store. No page reads them and they are not copied into the built site: the Site workflow fails if `_site/fixtures/` exists. The pages read the explorer bundle that the Site workflow solves and exports on every build ([`../README.md`](../README.md), "Bundles"). **They hold thesis-fixture data, in sample: not results to publish.**

| Bundle | What it is |
|---|---|
| `thesis-explorer/` | The one committed bundle with sweeps (it was the bundle of the former placeholder explorer page): a reduced thesis experiment, `site/fixtures/thesis_explorer.yaml` (config hash `sha256:19d35dcb12b0fb20cb17d0ddca87a9a98981019990966cdb7304f0994a802a38`). One location of the thesis portfolio (A1, Brickell_HighRise), the individual scope, the weighted-CVaR objective (α = 0.9, β = 0.95) and its α sweep (0.1 to 1.0) and β sweep (0.90 to 0.99), one factor at a time; 21 runs, 19 distinct sweep points plus the baseline. Same event set, noise layer, threshold, payout grid (15 bins, 20 to 70 m/s), pure pricing and budget (loading 1.0) as the thesis experiment, solved with the default solver policy. In-sample (`sample: full`), on the event-conditional basis: like `thesis/`, it does **not** meet the publication rule, so no number from it goes on a published page. 13 files, about 220 kB (184 kB of data files plus the manifest) |
| `thesis/` | The 9 single runs (3 scopes × 3 objectives) of the thesis experiment, `parity/configs/thesis.yaml`, on the thesis parity event set (`parity/tests/data/thesis_eventset`), solved with the default solver policy. No sweeps. In-sample (`sample: full`), on the event-conditional basis, under pure pricing, with the thesis noise layer as the basis-risk model: it does **not** meet the publication rule's out-of-sample, annual-basis requirement (`AGENTS.md`), so no number from it goes on a published page. Its map (`baseline.map.arrow`) has per-location numbers for the individual scope only: the thesis runs have no allocation-rule rows, so the cluster and portfolio rows are null, never the solver's split of a joint design. 7 files, about 225 kB |

A bundle is what `parametric-insurance-design export-site` writes: a `manifest.json` (format version, config hash, run ids, the setup of every number, each file's size and SHA-256, and the bundle rules for infinities, NaN, types and the size budget) plus one JSON or uncompressed Arrow IPC file per slice. The format is documented in `packages/viz/src/parametric_insurance_design_viz/site_export.py`.

## Licence

The data are derived from the IRIS event set, so they are **CC-BY-4.0**, like the event set they come from (`parity/README.md`, `docs/data-sources.md`). The manifest records the licence under `eventset.licence`.

## Regenerate

From the repository root (about a minute: the runs are solved first):

```bash
uv run parametric-insurance-design run parity/configs/thesis.yaml
uv run parametric-insurance-design export-site parity/configs/thesis.yaml --no-sweeps \
    --out site/fixtures/thesis \
    --label "thesis-fixture data: the thesis experiment (parity/configs/thesis.yaml) on the thesis parity event set, in-sample, event-conditional basis. A test fixture of the site bundle export, not a result to publish."
```

For `thesis-explorer/` (about a minute; `sweep` runs the baseline and both sweeps):

```bash
uv run parametric-insurance-design sweep site/fixtures/thesis_explorer.yaml
uv run parametric-insurance-design export-site site/fixtures/thesis_explorer.yaml -p alpha -p beta \
    --out site/fixtures/thesis-explorer \
    --label "thesis-fixture data: a reduced thesis experiment (site/fixtures/thesis_explorer.yaml: location A1 only, individual scope, weighted CVaR, alpha and beta sweeps) on the thesis parity event set, in-sample, event-conditional basis. A test fixture of the site bundle export with sweeps, not a result to publish."
```

The config writes its result store to the ignored `results/site-fixtures/thesis-explorer/`.

The solver output differs in the last digits between platforms, so a regenerated bundle need not be byte-identical; the tests in `packages/viz/tests/test_site_export.py` check each committed bundle against its manifest (every file's size and SHA-256, no other file) and against the config it came from (config hash; for `thesis-explorer/`, every sweep point in every sweep table). They run in the CI workflow, not in the Site workflow.
