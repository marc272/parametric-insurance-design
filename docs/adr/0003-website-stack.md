# ADR 0003: Website stack and hosting

- Status: **Accepted**
- Date: 2026-10-25
- Decision issue: MAR-52 (D5)
- Decision: **Quarto + OJS, deployed to GitHub Pages by GitHub Actions** (D5). The owner, Marc Prinzing, accepted the recommendation below on 2026-10-25. Site bundles are JSON for small grids and uncompressed Arrow IPC for larger tables. MAR-53 starts with a time-boxed check that one explorer page works at 375 px in light and dark mode, and falls back to Observable Framework if it doesn't. SPEC §11 D5 records the outcome.

## Context

The Website & Blog project publishes a static, data-driven research site (SPEC §2, §8):

- **v1 (early release):** an α/β/κ/bins payout and exceedance explorer (MAR-54), a portfolio cross-coverage map (MAR-55), posts 1 and 2 (MAR-57, MAR-58), and the launch (MAR-60).
- **v2 (after the paper):** a robustness explorer (MAR-56), post 3 (MAR-59), and a relaunch with the preprint (MAR-74).

The site lives in `site/` and only reads bundles exported from the result store (SPEC §4). MAR-53 defines the export, `parametric-insurance-design export-site <config>`, which writes JSON/Parquet slices and a manifest. There is no live solver in v1 or v2 (SPEC §9).

The criteria come from MAR-52:

- precomputed bundles only;
- static hosting on GitHub Pages;
- works at phone width;
- dark and light mode;
- low maintenance.

This ADR also weighs:

- the licence (`site/` is BSD-3-Clause, ADR 0001);
- the fit with the paper workflow and with the explorers;
- the build tooling in CI;
- how each option reads the exported bundles.

The repository today is Python-only: a uv workspace, with CI in `.github/workflows/ci.yml`. It has no Node toolchain.

All facts below were checked on **2026-10-25** against each project's primary sources: its GitHub repository and releases, and its official docs. observablehq.com returned HTTP 429 on that day, so the Observable Framework docs were read from the `docs/` folder of its repository instead. That folder is the source of the published docs.

## Options

1. **Observable Framework:** a static site generator for data apps, with data loaders and built-in charts (Observable Plot).
2. **Vite + Plotly/D3:** a hand-built single-page site using a general-purpose bundler and chart libraries.
3. **Quarto:** a Markdown/notebook publishing system with native Observable JS (OJS) cells. It is the option closest to the paper workflow.

## Comparison

| Criterion | Observable Framework | Vite + Plotly/D3 | Quarto (+ OJS) |
|---|---|---|---|
| Static hosting on GitHub Pages | Yes. The output is a static `dist/` folder. The docs give a GitHub Actions workflow for Pages [F2] | Yes. The output is `dist/`. A project site needs `base: '/<REPO>/'`. The docs give an Actions workflow [V2] | Yes. Three documented routes: a `docs/` folder, `quarto publish gh-pages`, or the official GitHub Action [Q2] |
| Precomputed bundles only | Native design goal. Data loaders "precompute static snapshots of data at build time" [F1]. No server at runtime | Whatever we write: `fetch()` JSON at runtime. No server | OJS reads files with `FileAttachment` at runtime. No server is needed unless Shiny is used [Q4] |
| Reads the exported bundles | `FileAttachment` supports JSON, CSV, `.arrow` and **`.parquet`** (to an Arrow table) [F4] | JSON is trivial. Parquet needs an extra library (e.g. parquet-wasm or DuckDB-WASM) that we choose and maintain | Documented `FileAttachment` formats: CSV, TSV, JSON, **Arrow (uncompressed)** and SQLite. **Parquet is not listed** [Q4]. So bundles would be JSON or uncompressed Arrow IPC, which pyarrow writes |
| Phone width | Responsive grid and layout classes. The sidebar collapses (built-in theme) | Entirely ours to build and test | Bootstrap-based responsive layout. OJS charts can size to the page width |
| Dark / light mode | Built in. With a light and a dark theme, it switches on `prefers-color-scheme` [F3]. **No reader toggle** documented | Ours to build: CSS variables plus re-theming each Plotly/D3 chart | Built in. Light and dark themes, a **reader toggle**, and `respect-user-color-scheme` [Q3]. Python plots can ship light/dark versions with the `renderings: [light, dark]` cell option [Q6] |
| Blog / posts (MAR-57, 58, 59) | Pages are Markdown, but there is **no blog listing, RSS or post index**. We would hand-build them | Ours to build, or a second tool | Built-in website + blog: listing pages, RSS, categories |
| Fit with the paper workflow (MAR-62 onward, MAR-74) | Separate from the paper tooling. Data loaders can call Python (incl. a uv env) [F5] | Separate from the paper tooling | Closest. Python/Jupyter cells, citations and cross-references. **Manuscript projects** output HTML plus PDF/Word and a MECA archive [Q5]. The same tool could host the preprint companion page |
| Fit with the explorers (MAR-54, 55, 56) | Best fit: reactive inputs, Observable Plot, linked views and maps, purpose-built for dashboards | Most flexible: any interaction, but all of it is our code | Good. OJS uses the same Observable runtime, `Inputs` and Plot as Framework, inside a document page. Layout control is less app-like than Framework's (unverified in a prototype; see below) |
| Build tooling in CI | Node ≥ 18 [F6], `npm ci`, and a `package.json` + lockfile in `site/` | Node 20.19+ / 22.12+ [V3], a `package.json` + lockfile, plus chart libraries | The Quarto CLI via `quarto-dev/quarto-actions/setup@v2` [Q2]. **No Node lockfile.** Python is needed only if a page executes code (avoidable here, or frozen with `freeze`) [Q2] |
| Maintenance burden for us | Low code, but npm dependency churn (Dependabot). **Upstream risk:** see below | **Highest.** We own the routing, layout, theming, blog, chart wrappers and npm churn. Plotly's full bundle is 1.49 MB gzipped; the "basic" partial bundle is 401 kB [V5] | Low. A single pinned CLI version, no npm tree. Pages are Markdown |
| Licence (site output is BSD-3-Clause) | ISC [F1] | Vite MIT [V1]; Plotly.js MIT [V4]; D3 ISC [V6] | MIT (Posit) [Q1]. The installer bundles third-party tools such as Pandoc under their own licences. They run at build time only and are not part of the published site |
| Maintenance status upstream | **Patch-only since v1.13.0 (2024-11-13).** Patch releases followed on 2025-01-22, 2025-01-23 and 2025-04-16. Latest is **v1.13.4 (2026-03-02)**, dependency upgrades only, released the day after issue #2045 asked whether Framework "is actually being maintained anymore". Last push 2026-05-15 [F1, F7]. Observable's active development has moved to Notebook Kit (v2.8.0, 2026-10-23) [F8]. No official statement on Framework's future was found [F9] | Vite **v8.3.5 (2026-10-21)**, very active [V1]. Plotly.js **v4.1.2 (2026-10-05)**, active [V4]. D3 v7.9.0 (2024-03-12), stable; the repository is still maintained [V6] | **v1.10.19 (2026-10-06)** stable, with a v1.11.6 pre-release on 2026-10-14. Roughly monthly releases. Backed by Posit [Q1] |

GitHub Pages limits apply to every option: a 1 GB published site, a soft 100 GB/month of bandwidth, a 10-minute deployment timeout, and a soft limit of 10 builds per hour. The build limit does not apply to custom Actions workflows [G1]. The bundle size budget in MAR-53 should stay well inside these limits.

## Option 1: Observable Framework

**Pros**
- Built for exactly this kind of site: precomputed data, reactive inputs, Plot charts, dashboards and grids.
- Native Parquet and Arrow reading, so MAR-53 can emit Parquet as SPEC §8 suggests.
- Automatic dark/light switching, and a documented GitHub Pages deploy.
- Data loaders can call Python in a uv environment, so `export-site` could run as a loader. This only works if the result store is reachable in CI (see "Open points common to all options").

**Cons**
- **Upstream maintenance risk.** There has been no feature release in almost two years, and the latest release came in response to a public "is it maintained?" issue. Observable's focus has moved to Notebook Kit. The site has a multi-year life (v1, then v2 after the paper), and a stalled generator is a real long-term cost: security warnings, Node version drift.
- No blog features. Posts 1 to 3 would need a hand-built index and feed, or a second tool.
- Adds a Node toolchain and an npm lockfile to a Python-only repository.
- No reader-facing dark/light toggle; it follows the OS setting only.
- Unrelated to the paper's tooling.

## Option 2: Vite + Plotly/D3

**Pros**
- Maximum control over interaction and layout. Vite and Plotly.js are very actively maintained.
- Plotly is familiar from Python, and D3 can handle any bespoke chart.
- No dependency on a niche generator.

**Cons**
- **Highest maintenance burden.** We would build and maintain routing, page layout, phone layouts, dark/light theming (each Plotly figure must be re-themed), the blog, and Parquet reading.
- A large npm dependency tree, with constant Dependabot churn.
- Plotly bundles are heavy for phones: 1.49 MB gzipped for the full bundle, and 401 kB for the basic one, which has no maps.
- Unrelated to the paper's tooling.
- Contrary to the "low maintenance" criterion. It also gives the agents writing MAR-54 and MAR-55 the most code surface to get wrong.

## Option 3: Quarto (with OJS for the explorers)

**Pros**
- Actively maintained, with roughly monthly releases and a company behind it. Permissive licence.
- One tool for the site, the blog (posts 1 to 3, with listing and RSS) and, if the owner wants it, the paper's companion pages or manuscript project (MAR-74). It is the closest fit to a Python/Jupyter research workflow.
- Dark/light mode with a reader toggle and a user-preference default. Responsive by default.
- OJS uses the same Observable runtime, `Inputs` and Plot as Framework. The explorers are written in the same style, and could move to Framework or Notebook Kit later if needed.
- CI needs only the Quarto CLI action. No npm lockfile in the repository, and no Python execution at site-build time if pages only read bundles.

**Cons**
- OJS inside a document gives less app-like layout control than Framework. A dense linked-view explorer (MAR-54) may need care at phone width. This is **unverified**: no prototype was built (see below).
- Parquet is not a documented `FileAttachment` format. MAR-53 would export JSON for small grids and uncompressed Arrow IPC for larger tables. pyarrow writes both, but Feather v2's default compression must be switched off. Parquet would otherwise need DuckDB-WASM (heavy on phones).
- Plotly figures from Python do not follow the theme automatically. Use Plot in OJS, or the `renderings: [light, dark]` cell option.
- The Quarto CLI is an external binary. Its version must be pinned in CI and noted in the runbook.

## Agent's recommendation (for the owner to accept or reject)

> **Recommendation by the agent preparing MAR-52, not a decision.**
>
> **Quarto, with OJS (Observable `Inputs` + Plot) for the explorers, deployed to GitHub Pages by a GitHub Actions workflow.** Bundles: JSON for small grids and manifests, uncompressed Arrow IPC for larger tables.
>
> Why:
> 1. It meets every MAR-52 criterion out of the box. It is the only option with a built-in reader toggle for dark/light mode, and it is the most actively maintained of the two generators.
> 2. It covers the blog posts and the paper companion with the same tool, so the program maintains one site tool rather than two.
> 3. It keeps the repository free of a Node toolchain.
> 4. Its explorer code (OJS + Plot) is portable to Observable Framework or Notebook Kit if the explorers outgrow Quarto.
>
> Observable Framework is the strongest alternative for the explorers alone. Its upstream maintenance status and missing blog support are the main reasons it ranks second. Vite + Plotly/D3 is the least suited to the "low maintenance" criterion.
>
> Suggested safeguard: make the first step of MAR-53 a time-boxed check that one α/β explorer page (sliders → step payout + exceedance curve, from one JSON bundle) works at 375 px width in both colour modes. If it does not, fall back to Observable Framework before MAR-54 starts.

## Consequences per option (MAR-53 onwards)

**If Quarto:**
- MAR-53:
  - `site/_quarto.yml` (website + blog), a deploy workflow (`quarto-dev/quarto-actions/setup@v2` plus `actions/upload-pages-artifact` / `actions/deploy-pages`), and a pinned Quarto version;
  - `export-site` writes JSON and uncompressed Arrow IPC with a manifest, not Parquet.
- MAR-54/55/56: OJS explorer pages using `Inputs`, Plot and `FileAttachment`. The map uses Plot's geo projections.
- MAR-57/58/59: posts are `.qmd` files under the blog listing, with RSS.
- MAR-60/74: the launch and the v2 relaunch are configuration changes. MAR-74 can link to, or embed, a Quarto manuscript build of the preprint if the paper uses Quarto (not required).
- The runbook gets one line for installing the Quarto CLI locally.

**If Observable Framework:**
- MAR-53:
  - `site/` gets `package.json`, `package-lock.json` and `observablehq.config.js`, plus the documented Pages workflow;
  - `export-site` can emit Parquet directly.
- MAR-54/55/56: Framework pages using Plot and `Inputs`, the closest fit for linked views.
- MAR-57/58/59: posts are Markdown pages with a hand-maintained index. RSS needs a custom step, or posts go elsewhere.
- Ongoing: Dependabot/npm upkeep. Watch upstream status; Notebook Kit is the likely migration path if Framework stalls.

**If Vite + Plotly/D3:**
- MAR-53: grows to include the app shell (routing, layout, theming, phone breakpoints), `package.json` plus lockfile, the `base` configuration for the project-site URL, and a Parquet or JSON loader.
- MAR-54/55/56: Plotly/D3 components with manual dark/light re-theming. Choose a partial Plotly bundle to stay inside the phone budget.
- MAR-57/58/59: need a blog solution, either hand-built or a second tool.
- Highest ongoing maintenance and review load.

## Open points common to all options (for MAR-53, not decided here)

- **Where bundles come from in CI.** The result store is not committed (AGENTS.md: no data beyond small fixtures, and pre-commit blocks files over 500 kB). The deploy job must either run `export-site` against a reproducible run, download bundles from a release asset with a checksum, or use small committed bundles under the size limit.
  - **Resolved (MAR-208, 2026-11-01): the Site workflow solves and exports the bundle itself.** The build job of `.github/workflows/site.yml` runs `sweep` and then `export-site` on `site/configs/explorer.yaml` (the thesis portfolio on the committed thesis parity event set, out of sample, annual basis; its reductions for CI are stated in the config and on the bundle's label), on every pull request that touches the site or the code, lock or event set the bundle comes from, and on every push to `main`. The bundle goes to `bundles/explorer/` of the rendered site. Before the Pages artifact is uploaded, the job checks every file against the manifest's SHA-256 and size, that the directory holds nothing else, that the manifest's config hash is the config's, and the publication rule's setup (annual basis, out of sample, no run left out). There is no download and no cache: the run keys do not include the code version, so a cached store could serve results of older code. The committed fixtures under `site/fixtures/` stay for the skeleton's placeholder page and are checked against their manifests as before.
  - Why not a release asset: creating a GitHub release is the owner's (MAR-189), and a solve in CI keeps the bundle reproducible from the commit alone. The cost is solve time on every site build: about 2.5 minutes on a loaded 10-core Mac with 4 worker processes; see the PR of MAR-208 for the time on a GitHub runner. A larger bundle (all scopes, bootstrap intervals, the full sweep grids) would need the release-asset route, or a cache keyed on the code as well as the config.
- **GitHub Pages must be enabled** with "GitHub Actions" as the source in the repository settings. That is an owner action: agents do not change account or repository settings.
- **URL:** the default is the project site `https://marc272.github.io/parametric-insurance-design/`. A custom domain is optional and is the owner's choice.

## Prototype

None was built. The comparison relies on primary documentation. The one property that most needs hands-on confirmation is OJS explorer ergonomics at phone width. It is proposed as the first, time-boxed step of MAR-53 rather than done here, because it needs a real bundle from `export-site`.

## Sources (all accessed 2026-10-25)

- [F1] Observable Framework repository: licence ISC, releases, last push. https://github.com/observablehq/framework and https://github.com/observablehq/framework/releases
- [F2] Framework docs, "Deploying" (GitHub Pages via Actions). https://github.com/observablehq/framework/blob/main/docs/deploying.md (published at https://observablehq.com/framework/deploying)
- [F3] Framework docs, "Themes" (light, dark, auto via `prefers-color-scheme`). https://github.com/observablehq/framework/blob/main/docs/themes.md.ts
- [F4] Framework docs, "Files" (`FileAttachment` formats incl. `.parquet`, `.arrow`). https://github.com/observablehq/framework/blob/main/docs/files.md
- [F5] Framework docs, "Data loaders" (polyglot, Python, uv). https://github.com/observablehq/framework/blob/main/docs/data-loaders.md
- [F6] Framework docs, "Getting started" (Node.js 18 or later). https://github.com/observablehq/framework/blob/main/docs/getting-started.md
- [F7] Framework issue #2045, "is Observable Framework actually being maintained anymore?" (opened 2026-03-01, closed 2026-03-02); v1.13.4 release notes. https://github.com/observablehq/framework/issues/2045 and https://github.com/observablehq/framework/releases/tag/v1.13.4
- [F8] Observable Notebook Kit repository (ISC; v2.8.0, 2026-10-23). https://github.com/observablehq/notebook-kit
- [F9] Observable forum, "Where is Observable going?" (staff replies cover notebooks, not Framework). https://talk.observablehq.com/t/where-is-observable-going/10372
- [V1] Vite repository: licence MIT, v8.3.5 (2026-10-21). https://github.com/vitejs/vite
- [V2] Vite docs, "Deploying a Static Site" (GitHub Pages, `base`). https://vite.dev/guide/static-deploy
- [V3] Vite docs, "Getting Started" (Node.js 20.19+, 22.12+). https://vite.dev/guide/
- [V4] Plotly.js repository: licence MIT, v4.1.2 (2026-10-05). https://github.com/plotly/plotly.js
- [V5] Plotly.js bundle sizes. https://github.com/plotly/plotly.js/blob/master/dist/README.md
- [V6] D3 repository: licence ISC, v7.9.0 (2024-03-12). https://github.com/d3/d3
- [Q1] Quarto CLI repository: MIT licence (COPYRIGHT, Posit Software, PBC), v1.10.19 (2026-10-06), v1.11.6 pre-release (2026-10-14). https://github.com/quarto-dev/quarto-cli
- [Q2] Quarto docs, "GitHub Pages" (docs folder, `quarto publish`, GitHub Action, `freeze`). https://quarto.org/docs/publishing/github-pages.html
- [Q3] Quarto docs, "HTML Theming" (light/dark, toggle, `respect-user-color-scheme`). https://quarto.org/docs/output-formats/html-themes.html
- [Q4] Quarto docs, "Observable JS" (`FileAttachment` formats, `ojs_define`). https://quarto.org/docs/interactive/ojs/
- [Q5] Quarto docs, "Manuscripts". https://quarto.org/docs/manuscripts/
- [Q6] Quarto docs, "Execution Options" (`renderings` cell option). https://quarto.org/docs/computations/execution-options.html
- [G1] GitHub docs, "GitHub Pages limits". https://docs.github.com/en/pages/getting-started-with-github-pages/github-pages-limits
