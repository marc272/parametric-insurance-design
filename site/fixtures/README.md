# site/fixtures/

Small committed site bundles, so the site can be built and tested without a result store. **They hold thesis-fixture data: placeholders, not results to publish.**

| Bundle | What it is |
|---|---|
| `thesis/` | The 9 single runs (3 scopes × 3 objectives) of the thesis experiment, `parity/configs/thesis.yaml`, on the thesis parity event set (`parity/tests/data/thesis_eventset`), solved with the default solver policy. No sweeps. In-sample (`sample: full`), on the event-conditional basis, under pure pricing, with the thesis noise layer as the basis-risk model: it does **not** meet the publication rule's out-of-sample, annual-basis requirement (`AGENTS.md`), so no number from it goes on a published page. About 220 kB |

A bundle is what `parametric-insurance-design export-site` writes: a `manifest.json` (format version, config hash, run ids, the setup of every number, each file's size and SHA-256, and the bundle rules for infinities, NaN, types and the size budget) plus one JSON or uncompressed Arrow IPC file per slice. The format is documented in `packages/viz/src/parametric_insurance_design_viz/site_export.py`.

## Licence

The data are derived from the IRIS event set, so they are **CC-BY-4.0**, like the event set they come from (`parity/README.md`, `docs/data-sources.md`). The manifest records the licence under `eventset.licence`.

## Regenerate

From the repository root (about a minute: the runs are solved first):

```bash
uv run parametric-insurance-design run parity/configs/thesis.yaml
uv run parametric-insurance-design export-site parity/configs/thesis.yaml --no-sweeps \
    --out site/fixtures/thesis \
    --label "thesis-fixture data: the thesis experiment (parity/configs/thesis.yaml) on the thesis parity event set, in-sample, event-conditional basis. A placeholder for the site skeleton, not a result to publish."
```

The solver output differs in the last digits between platforms, so a regenerated bundle need not be byte-identical; the test `packages/viz/tests/test_site_export.py` checks the committed one against its manifest and against the config it came from.
