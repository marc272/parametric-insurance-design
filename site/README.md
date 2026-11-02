# site/

The project website: interactive explorers of the payout design, and the posts. Today it has a home page with the two ideas and their combination, the method pages, an about page, the payout and exceedance explorer, the portfolio explorer (rendered, not in the navbar yet) and an empty post listing with an RSS feed.

- The stack is decided: Quarto with Observable JS (OJS), deployed to GitHub Pages ([ADR 0003](../docs/adr/0003-website-stack.md)). The site is https://marc272.github.io/parametric-insurance-design/.
- The site reads bundles exported from the result store and never runs an optimisation itself ([`docs/SPEC.md`](../docs/SPEC.md) §4). The explorer pages read the explorer and portfolio bundles, which the Site workflow solves and exports on every build (see "Bundles" below). The committed bundles under [`fixtures/`](fixtures/README.md) are test fixtures and are not part of the site.
- Everything published here follows the publication rule in [`AGENTS.md`](../AGENTS.md).
- Licence: BSD-3-Clause, under the repository's [LICENSE](../LICENSE). The bundle data are derived from the IRIS event set, so they are CC-BY-4.0 ([`fixtures/README.md`](fixtures/README.md), [`docs/data-sources.md`](../docs/data-sources.md)).

The repository's [README](../README.md) has the project's status.

## Layout

| Path | What it is |
|---|---|
| `_quarto.yml` | The Quarto project: website, navbar, light and dark themes (`flatly`, `darkly`), and the pinned Quarto version (`quarto-required`). It copies no bundle into the site |
| `index.qmd` | Home page: the tail-risk objective, portfolio (joint) calibration, their combination and the library, one section each, with a schematic from `figures/` |
| `method/*.qmd` | The method pages. Each one includes a concept doc from [`docs/concepts/`](../docs/concepts/README.md) with `{{< include >}}`, so the site never copies their text. `method/concepts.lua` (set for the folder in `method/_metadata.yml`) adapts the GitHub-flavoured files: the first heading becomes the title, links between the concept docs go to the site pages, links to other docs go to GitHub, figures are embedded from `docs/concepts/figures/`, and wide tables and figures scroll on phones. An unknown relative link fails the build |
| `about.qmd` | About: the project, the thesis (title and institution), how the numbers are reported, the licences |
| `figures/*.svg`, `filters/inline-svg.lua` | The home page's schematics (no data), drawn in `currentColor` and inlined by the filter, so they follow the light and the dark theme |
| `explorers/alpha-beta.qmd` | The payout and exceedance explorer on the explorer bundle: the objective, and α, β, the budget loading κ or the number of bins → the step payout of one site, the payout relative to the MSE design and the out-of-sample exceedance curves, with the setup of every number read from the bundle's manifest |
| `explorers/portfolio.qmd` | The portfolio explorer on the portfolio bundle, not in the navbar yet: for one owner of the nine sites, a joint design (portfolio scope; cluster scope) next to the sum of the individual designs (and the clusters each calibrated on their own), at the same total budget, per objective → the owner's totals (premium charged, expected loss, payout and shortfall, VaR and CVaR of the shortfall, with bootstrap intervals), the out-of-sample exceedance curves of the total payout against the total loss and of the owner's total shortfall, a map of the individual designs' per-site cover E[π]/E[L] sized by insured value, and the clusters (assignments, the weights of the cluster index). It shows no per-site number of a joint design (not identified; [payout allocation](../docs/methodology/payout-allocation.md)) and makes no comparative statement (the publication rule's joint-calibration rule) |
| `explorers/explorer.css` | The explorers' layout: the controls column, captions and setup notes |
| `explorers/portfolio.css` | The portfolio explorer's additions: the method note, scope legends and swatches, the totals table |
| `favicon.svg` | The site's icon (`website.favicon` in `_quarto.yml`), linked from every page |
| `blog/index.qmd` | The post listing and its RSS feed (`blog/index.xml`). Posts go under `blog/posts/` |
| `styles/site.scss` | Small additions to both themes: chart backgrounds, phone-width inputs, the setup table, the schematics, and scrolling tables and figures on the method pages |
| `fixtures/` | Committed test bundles of the site export (`thesis/`, `thesis-explorer/`) and the config of `thesis-explorer/`, checked by `packages/viz/tests/test_site_export.py`; not part of the site ([`fixtures/README.md`](fixtures/README.md)) |
| `configs/explorer.yaml` | The config of the explorer bundle that the Site workflow solves and exports on every build ("Bundles" below) |
| `configs/portfolio.yaml` | The config of the portfolio bundle, likewise |

Explorer pages use Observable Plot pinned in the page (`@observablehq/plot@0.6.17`, from jsDelivr), because Quarto's built-in `Plot` follows the CDN's latest release. Quarto's OJS runtime reads the Arrow files with apache-arrow 9.

## Bundles

| Bundle | Where it comes from | Publishable? |
|---|---|---|
| `fixtures/thesis/`, `fixtures/thesis-explorer/` | Committed test fixtures, regenerated by hand ([`fixtures/README.md`](fixtures/README.md)). Not copied into the site: the Site workflow fails if `_site/fixtures/` exists, so no in-sample fixture number reaches a page | No: in sample, event-conditional basis |
| `bundles/explorer/` (in the built site only) | Solved and exported by the Site workflow on every build from [`configs/explorer.yaml`](configs/explorer.yaml) on the committed thesis parity event set ([ADR 0003](../docs/adr/0003-website-stack.md) "Where bundles come from in CI") | Its `eval_split = "test"` rows: out of sample, annual basis |
| `bundles/portfolio/` (in the built site only) | Likewise, from [`configs/portfolio.yaml`](configs/portfolio.yaml) | Its `eval_split = "test"` rows: out of sample, annual basis |

The explorer bundle is the one the payout explorer reads: the thesis portfolio, the individual scope, the MSE, E[U] and weighted-CVaR objectives, and the α, β, budget-loading (κ, 11 values from 0.5 to 1.5) and bin-count (5 bin counts, 5 to 25) sweeps, under pure pricing, on a holdout split (years 0–6,999 train, 7,000–9,999 test). It has block-bootstrap intervals (level 0.9). For CI it is reduced: one scope, and B = 200 bootstrap replicates (C1 has 1,000). The config lists every reduction, and the bundle's label (the config's description, `manifest.json` → `label`) repeats them. It is exported with `--split test`, so it holds the test rows only: out of sample, as the publication rule requires. About 3.4 MB in 18 data files plus the manifest; the largest, `sweep.budget_loading.exceedance.arrow`, is 1.0 MB of the 2 MB per-file budget.

The portfolio bundle is the one the portfolio explorer reads: the same setup (portfolio, noise layer, annual basis, holdout split, pure pricing, budget loading 1.0, 15 bins, the three objectives, bootstrap level 0.9 with B = 200) and four scopes: individual, portfolio, and the cluster scope (3 clusters, thesis Ward clustering, tail level 0.9) calibrated jointly and cluster by cluster (`joint: false`, scope key `cluster_separate`). Its budgets add up to the same total in every scope. 12 single runs and no sweeps; no allocation rule, so its per-site numbers (`baseline.map.arrow`) are those of the individual scope only. Exported with `--no-sweeps --split test`. About 0.3 MB in 6 data files plus the manifest.

- **Publication rule.** A holdout run stores its KPIs and exceedance curves on the train years (`eval_split = "train"`, in sample) and on the test years (`"test"`, out of sample). The bundle holds the `"test"` rows only, and a published page states the setup from `manifest.setup` and the filter from `manifest.split_filter`.
- **Checks.** Before the Pages artifact is uploaded, the build checks, for each bundle, every file against the manifest's SHA-256 and size, that the bundle directory holds no other file, that the manifest's config hash is that of its config, the setup (annual basis, out of sample, no run left out), and that every KPI, exceedance and map table holds `eval_split = "test"` rows only.
- **No cache.** The runs are solved on every build (the explorer's 67 runs, about 3 minutes on a GitHub runner with 4 worker processes: 177 s on 2026-11-01; the portfolio's 12 runs, one process, about 1 minute locally; the build job takes about 4 to 5). Run keys don't include the code version, so a cached store could serve results of older code.
- **Path filters.** The workflow also runs when a concept doc changes (`docs/concepts/`, included by the method pages at render time), and when the code, lock or event set the bundle comes from changes: `packages/core/src/`, `packages/viz/src/`, their `pyproject.toml`, the root `pyproject.toml`, `uv.lock` and `parity/tests/data/thesis_eventset/`.
- **Reading it from a page.** `export-site` writes the bundle into `_site/bundles/explorer/` after `quarto render`, because the render empties `_site/`. A page reads it at run time with a relative URL, e.g. `FileAttachment("../bundles/explorer/manifest.json")` from `explorers/`. Locally, run the three commands at the top of the config, then serve `_site/` (below).

## Build

The workflow [`.github/workflows/site.yml`](../.github/workflows/site.yml) builds the site on every pull request that touches `site/`, the workflow, or the code and data of the bundles (above), and builds and deploys it to GitHub Pages on `main`. It checks that the two Quarto pins agree (below), solves the explorer and portfolio runs, draws the explorer config's figures from the same store as a check only (they are not published; any non-zero `figures` exit fails the build, so a figure regression fails CI), exports both bundles, checks that no fixture bundle is in the site, and checks both bundles.

**The Quarto pin.** The Quarto CLI is pinned twice: `QUARTO_VERSION` in the workflow (what `quarto-dev/quarto-actions/setup` installs) and `quarto-required` in `_quarto.yml` (what the render requires). Change both together: the workflow's step "Check the Quarto pin" fails the build, before the solve, when they differ. That step catches drift between the two pins, not a pin that has fallen behind Quarto's releases.

Dependabot can't track the pin, so it is checked by hand. Dependabot's `github-actions` ecosystem updates the `uses:` reference of an action: it bumps `quarto-dev/quarto-actions/setup` itself (SHA and version comment), but never a `with:` input or an `env:` value such as `QUARTO_VERSION`. No ecosystem reads `quarto-required` in `_quarto.yml`, and Dependabot has no custom or pattern-based ecosystem for a version string in a file. The manual check, before a site release and whenever Dependabot's weekly Actions PR bumps `quarto-dev/quarto-actions`:

1. Find the latest stable release: `gh release view -R quarto-dev/quarto-cli --json tagName,publishedAt` (the release marked "Latest"; the pre-releases of the next minor version are not), or https://quarto.org/docs/download/.
2. If it is newer than the pin and at least a week old (the cooldown of `.github/dependabot.yml`), read its release notes, then set the version, without the leading `v`, in both `QUARTO_VERSION` (`.github/workflows/site.yml`) and `quarto-required` (`_quarto.yml`), in one PR.
3. The Site workflow builds the site with the new version on that PR, and its pin check fails if only one of the two changed. Look at the rendered pages (the local build below) before merging.

Locally, with the pinned Quarto CLI and no system install, from the repository root on macOS (`V` is read from `_quarto.yml`):

```bash
V=$(sed -nE 's/^quarto-required: "([^"]+)"$/\1/p' site/_quarto.yml)
mkdir -p results/quarto-dl
gh release download v$V -R quarto-dev/quarto-cli -D results/quarto-dl \
    -p "quarto-$V-macos.tar.gz" -p "quarto-$V-checksums.txt"
(cd results/quarto-dl && shasum -a 256 -c --ignore-missing quarto-$V-checksums.txt)
mkdir -p results/quarto-$V && tar -xzf results/quarto-dl/quarto-$V-macos.tar.gz -C results/quarto-$V
results/quarto-$V/bin/quarto render site
python3 -m http.server 8765 --bind 127.0.0.1 -d site/_site   # then open http://127.0.0.1:8765/
```

The output goes to `site/_site/`, ignored with Quarto's cache `site/.quarto/` (`site/.gitignore`). For the explorers' data, solve and export their bundles after the render (the commands at the top of [`configs/explorer.yaml`](configs/explorer.yaml) and [`configs/portfolio.yaml`](configs/portfolio.yaml)). The pages load the bundles with `fetch`, so open them through a local server, not as `file://` URLs.
