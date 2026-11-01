# site/

The project website: interactive explorers of the payout design, and the posts. It is a **skeleton** (MAR-201): a home page, an empty post listing with an RSS feed, and one placeholder explorer page on thesis-fixture data.

- The stack is decided: Quarto with Observable JS (OJS), deployed to GitHub Pages ([ADR 0003](../docs/adr/0003-website-stack.md)). The site is https://marc272.github.io/parametric-insurance-design/.
- The site reads bundles exported from the result store and never runs an optimisation itself ([`docs/SPEC.md`](../docs/SPEC.md) §4). For now the bundles are the committed fixtures under [`fixtures/`](fixtures/README.md).
- Everything published here follows the publication rule in [`AGENTS.md`](../AGENTS.md).
- Licence: BSD-3-Clause, under the repository's [LICENSE](../LICENSE). The fixture data are CC-BY-4.0 ([`fixtures/README.md`](fixtures/README.md)).

The repository's [README](../README.md) has the project's status.

## Layout

| Path | What it is |
|---|---|
| `_quarto.yml` | The Quarto project: website, navbar, light and dark themes (`flatly`, `darkly`), the pinned Quarto version (`quarto-required`) and the bundles copied into the site (`resources`) |
| `index.qmd` | Home page |
| `explorers/alpha-beta.qmd` | The α/β payout explorer, a placeholder on the `fixtures/thesis-explorer/` bundle: α or β of the weighted-CVaR objective → the step payout and the exceedance curves, with the setup of every number read from the bundle's manifest |
| `blog/index.qmd` | The post listing and its RSS feed (`blog/index.xml`). Posts go under `blog/posts/` |
| `styles/site.scss` | Small additions to both themes: chart backgrounds, phone-width inputs, the setup table |
| `fixtures/` | The committed bundles and the config of the explorer bundle ([`fixtures/README.md`](fixtures/README.md)) |

Explorer pages use Observable Plot pinned in the page (`@observablehq/plot@0.6.17`, from jsDelivr), because Quarto's built-in `Plot` follows the CDN's latest release. Quarto's OJS runtime reads the Arrow files with apache-arrow 9.

## Build

The workflow [`.github/workflows/site.yml`](../.github/workflows/site.yml) builds the site on every pull request that touches `site/` or the workflow, and builds and deploys it to GitHub Pages on `main`. It first checks the fixture bundles against the SHA-256 in their manifests.

Locally, with the pinned Quarto CLI (1.10.19; `QUARTO_VERSION` in the workflow and `quarto-required` in `_quarto.yml`, change both together) and no system install, from the repository root on macOS:

```bash
V=1.10.19
mkdir -p results/quarto-dl
gh release download v$V -R quarto-dev/quarto-cli -D results/quarto-dl \
    -p "quarto-$V-macos.tar.gz" -p "quarto-$V-checksums.txt"
(cd results/quarto-dl && shasum -a 256 -c --ignore-missing quarto-$V-checksums.txt)
mkdir -p results/quarto-$V && tar -xzf results/quarto-dl/quarto-$V-macos.tar.gz -C results/quarto-$V
results/quarto-$V/bin/quarto render site
python3 -m http.server 8765 --bind 127.0.0.1 -d site/_site   # then open http://127.0.0.1:8765/
```

The output goes to `site/_site/`, ignored with Quarto's cache `site/.quarto/` (`site/.gitignore`). The pages load the bundles with `fetch`, so open them through a local server, not as `file://` URLs.
